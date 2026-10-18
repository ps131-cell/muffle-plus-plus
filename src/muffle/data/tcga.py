"""Open-tier TCGA (UCSC Xena GDC hub) -> one pooled cohort in the synthetic-cohort format.

Xena GDC hub matrices are feature x sample, with 16-char sample barcodes as columns
(TCGA-XX-XXXX-01A). Everything here is keyed on the 12-char patient barcode and keeps only the
primary-tumour vial A sample (01A) of each patient.

Feature selection is unsupervised (variance only, survival is never looked at) and pooled over
the whole cohort. In a real federation each site would rank on its own data and the sites would
agree on the feature list with ``preprocess.harmonize_features``.
"""

from __future__ import annotations

import gzip
import hashlib
import pickle
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from muffle.config import MODALITIES
from muffle.data.preprocess import beta_to_m, drop_sparse, log_zscore, top_variance, zscore

XENA_GDC_HUB = "https://gdc-hub.s3.us-east-1.amazonaws.com/download"
DAYS_PER_MONTH = 365.25 / 12

# Xena GDC hub file names; "{project}" is e.g. TCGA-BRCA.
SOURCES = {
    "survival": "{project}.survival.tsv.gz",
    "clinical": "{project}.clinical.tsv.gz",
    "genes": "gencode.v36.annotation.gtf.gene.probemap",
    "genomic": "{project}.gene-level_ascat3.tsv.gz",
    "rna": "{project}.star_tpm.tsv.gz",
    "methylation": "{project}.methylation450.tsv.gz",
    "protein": "{project}.protein.tsv.gz",
}
STREAMED = {"methylation"}  # ~3 GB for BRCA: read straight from the hub, never stored

CLINICAL_FEATURES = [
    "age", "stage", "pathologic_t", "pathologic_n", "metastasis", "ductal", "lobular",
    "stage_unknown",
]
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}


# --- barcodes -----------------------------------------------------------------------------

def tissue_source_site(barcode: str) -> str:
    """TCGA-XX-...: chars 6-7 (1-based) code the hospital that collected the sample."""
    return barcode[5:7]


def is_primary_a(sample: str) -> bool:
    """Sample type 01 (primary solid tumour), vial A."""
    return len(sample) >= 16 and sample[13:16] == "01A"


def primary_samples(samples: Iterable[str]) -> dict[str, str]:
    """{sample barcode: patient barcode} for 01A samples, first one per patient."""
    out: dict[str, str] = {}
    seen: set[str] = set()
    for s in samples:
        if is_primary_a(s) and s[:12] not in seen:
            out[s] = s[:12]
            seen.add(s[:12])
    return out


def per_patient(table: pd.DataFrame, sample_col: str = "sample") -> pd.DataFrame:
    """One-row-per-sample table -> one row per patient, preferring the 01A row."""
    table = table.assign(patient=table[sample_col].str[:12],
                         _primary=table[sample_col].map(is_primary_a))
    table = table.sort_values("_primary", ascending=False, kind="stable")
    return table.drop_duplicates("patient").set_index("patient").drop(columns="_primary")


# --- reading Xena matrices ----------------------------------------------------------------

@contextmanager
def open_source(source: str | Path):
    """Binary stream for a local path or an http(s) URL, gunzipped on the fly."""
    s = str(source)
    remote = s.startswith(("http://", "https://"))
    with urllib.request.urlopen(s, timeout=120) if remote else open(s, "rb") as raw:
        yield gzip.GzipFile(fileobj=raw) if s.endswith(".gz") else raw


def read_header(source: str | Path) -> list[str]:
    with open_source(source) as f:
        return f.readline().decode().rstrip("\r\n").split("\t")


def read_matrix(
    source: str | Path, samples: dict[str, str], chunksize: int = 20_000
) -> Iterator[pd.DataFrame]:
    """Yield patient x feature blocks of a feature x sample Xena matrix.

    Only the columns in ``samples`` (sample barcode -> patient) are parsed; they are renamed to
    patients. Blocks split the feature axis, so a 3 GB file never has to fit in memory.
    """
    index_col = read_header(source)[0]
    keep = {index_col, *samples}
    with open_source(source) as f:
        reader = pd.read_csv(
            f, sep="\t", index_col=0, usecols=lambda c: c in keep,
            dtype={s: np.float32 for s in samples}, chunksize=chunksize,
        )
        for chunk in reader:
            yield chunk.T.rename(index=samples)


# --- per-modality transforms --------------------------------------------------------------

def select_top(
    blocks: Iterable[pd.DataFrame],
    k: int,
    rank: Callable[[pd.DataFrame], pd.DataFrame] | None = None,
    max_missing: float = 0.2,
) -> pd.DataFrame:
    """drop_sparse -> top_variance(rank(x), k) over patient x feature blocks; returns raw values.

    Both steps are per feature, so keeping the best k after every block selects the same
    features as running on the whole matrix, with only k + one block in memory.
    """
    rank = rank or (lambda x: x)
    best = None
    for block in blocks:
        block = drop_sparse(block, max_missing)
        if best is not None:
            block = pd.concat([best, block], axis=1)
        best = block[top_variance(rank(block), k)]
    if best is None or best.shape[1] < k:
        n = 0 if best is None else best.shape[1]
        raise ValueError(f"only {n} features with <= {max_missing:.0%} missing, need {k}")
    return best


def copy_number_calls(cn: pd.DataFrame) -> pd.DataFrame:
    """Absolute gene copy number (patients x genes) -> GISTIC-style calls relative to ploidy.

    Ploidy = the tumour's median gene copy number (rounded). -2 deep deletion (0 copies),
    -1 loss, 0 neutral, +1 gain, +2 amplification (>= 2x ploidy).
    """
    v = cn.to_numpy(np.float32)
    p = np.clip(np.round(np.nanmedian(v, axis=1, keepdims=True)), 1, None)
    calls = np.select([v == 0, v < p, v == p, v < 2 * p, v >= 2 * p], [-2, -1, 0, 1, 2], np.nan)
    return pd.DataFrame(calls.astype(np.float32), index=cn.index, columns=cn.columns)


def genomic_block(blocks: Iterable[pd.DataFrame], k: int, max_missing: float = 0.2):
    cn = drop_sparse(pd.concat(list(blocks), axis=1), max_missing)  # ploidy needs every gene
    return select_top([copy_number_calls(cn)], k, max_missing=max_missing).fillna(0.0)


def rna_block(blocks: Iterable[pd.DataFrame], k: int, max_missing: float = 0.2):
    """Hub values are log2(TPM + 1). Rank on the log scale, z-score afterwards: z-scored
    features all have variance 1, so top_variance must come before the z-score."""
    tpm = select_top((np.exp2(b) - 1 for b in blocks), k, np.log1p, max_missing)
    return log_zscore(tpm).fillna(0.0)


def methylation_block(blocks: Iterable[pd.DataFrame], k: int, max_missing: float = 0.2):
    m = beta_to_m(select_top(blocks, k, beta_to_m, max_missing))
    return m.fillna(m.mean())


def protein_block(blocks: Iterable[pd.DataFrame], k: int, max_missing: float = 0.2):
    """RPPA values are already log2 and median-centred, so only z-score."""
    return zscore(select_top(blocks, k, max_missing=max_missing)).fillna(0.0)


BUILDERS = {
    "genomic": genomic_block,
    "rna": rna_block,
    "methylation": methylation_block,
    "protein": protein_block,
}


# --- clinical + survival ------------------------------------------------------------------

def survival_table(survival: pd.DataFrame) -> pd.DataFrame:
    """Xena survival table (one row per sample) -> per patient OS time (months) and event."""
    s = survival.dropna(subset=["OS", "OS.time"])
    s = per_patient(s[s["OS.time"] > 0])
    return pd.DataFrame({"time": s["OS.time"] / DAYS_PER_MONTH, "event": s["OS"].astype(float)})


def _extract(values: pd.Series, pattern: str, codes: dict[str, int] | None = None) -> pd.Series:
    """First regex group as a float (via ``codes`` if given); NaN where it does not match."""
    found = values.astype("string").str.extract(pattern, expand=False).astype(object)
    return pd.to_numeric(found.map(codes) if codes else found, errors="coerce").astype(float)


def clinical_features(clinical: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """GDC clinical fields (one row per patient) -> (CLINICAL_FEATURES, stage 1-4).

    Continuous / ordinal features are median-imputed and z-scored; flags are 0/1.
    """
    stage = _extract(clinical["ajcc_pathologic_stage.diagnoses"],
                     r"^Stage (IV|III|II|I)[A-C]?$", ROMAN)
    age = clinical["age_at_index.demographic"].astype(float)
    if "days_to_birth.demographic" in clinical:
        age = age.fillna(-clinical["days_to_birth.demographic"] / 365.25)
    histology = clinical["primary_diagnosis.diagnoses"].astype("string").str.lower()
    feats = pd.DataFrame({
        "age": age,
        "stage": stage,
        "pathologic_t": _extract(clinical["ajcc_pathologic_t.diagnoses"], r"^T(\d)"),
        "pathologic_n": _extract(clinical["ajcc_pathologic_n.diagnoses"], r"^N(\d)"),
        "metastasis": clinical["ajcc_pathologic_m.diagnoses"].astype("string")
        .str.contains("M1", na=False).astype(float),
        "ductal": histology.str.contains("duct", na=False).astype(float),
        "lobular": histology.str.contains("lobular", na=False).astype(float),
        "stage_unknown": stage.isna().astype(float),
    }, index=clinical.index)[CLINICAL_FEATURES]
    cont = ["age", "stage", "pathologic_t", "pathologic_n"]
    feats[cont] = zscore(feats[cont].fillna(feats[cont].median()))
    return feats, stage.fillna(stage.median()).round()


# --- assembly -----------------------------------------------------------------------------

def assemble_cohort(
    survival: pd.DataFrame,
    clinical: pd.DataFrame,
    blocks: dict[str, pd.DataFrame],
    dims: dict[str, int],
) -> dict[str, np.ndarray]:
    """Merge per-patient survival, clinical fields and transformed omic blocks.

    survival: ``survival_table`` output; clinical: one row of GDC fields per patient;
    blocks: {modality: patients x features}. A patient needs survival, clinical data and at
    least one omic block. Unmeasured modalities are zeros with mask 0.
    """
    omic = set().union(*(b.index for b in blocks.values()))
    patients = sorted(set(survival.index) & set(clinical.index) & omic)
    if not patients:
        raise ValueError("no patient has survival, clinical and omic data")
    clin, stage = clinical_features(clinical.loc[patients])
    n = len(patients)
    out: dict[str, np.ndarray] = {}
    mask = np.zeros((n, len(MODALITIES)), np.float32)
    for j, m in enumerate(MODALITIES):
        if m == "clinical":
            block, names = clin, CLINICAL_FEATURES
        elif m in blocks:
            block, names = blocks[m], list(blocks[m].columns)
        else:
            out[f"x_{m}"] = np.zeros((n, dims[m]), np.float32)
            continue
        mask[:, j] = pd.Index(patients).isin(block.index)
        x = block.reindex(patients).to_numpy(np.float32)
        if x.shape[1] != dims[m]:
            raise ValueError(f"{m}: {x.shape[1]} features, config says {dims[m]}")
        out[f"x_{m}"] = np.nan_to_num(x, nan=0.0)
        out[f"names_{m}"] = np.array(names, dtype=str)
    surv = survival.loc[patients]
    out["time"] = surv["time"].to_numpy(np.float32)
    out["event"] = surv["event"].to_numpy(np.float32)
    out["mask"] = mask
    out["stage"] = stage.to_numpy(np.float32)
    out["tss"] = np.array([tissue_source_site(p) for p in patients])
    out["patient"] = np.array(patients)
    return out


def describe(cohort: dict[str, np.ndarray]) -> str:
    """Cohort size, events, modality coverage and sites (no patient-level values)."""
    t, e, mask = cohort["time"], cohort["event"], cohort["mask"]
    lines = [
        f"{len(t)} patients, {int(e.sum())} deaths (event rate {e.mean():.3f}), "
        f"median follow-up {np.median(t):.1f} months",
        "coverage: " + ", ".join(f"{m} {mask[:, j].mean():.0%}" for j, m in enumerate(MODALITIES)),
        f"all {len(MODALITIES)} modalities: {int((mask.min(1) == 1).sum())} patients",
    ]
    if "tss" in cohort:
        sites = pd.Series(cohort["tss"]).value_counts()
        lines.append(f"{len(sites)} tissue source sites; largest: "
                     + ", ".join(f"{s} {c}" for s, c in sites.head(6).items()))
    return "\n".join(lines)


# --- end to end ---------------------------------------------------------------------------

def locate(role: str, project: str, raw_dir: Path) -> str:
    """Local path of a hub file, downloading it first; streamed roles return the URL instead."""
    name = SOURCES[role].format(project=project)
    path = raw_dir / name
    if path.exists():
        return str(path)
    url = f"{XENA_GDC_HUB}/{name}"
    if role in STREAMED:
        return url
    part = path.with_name(path.name + ".part")
    urllib.request.urlretrieve(url, part)
    part.rename(path)
    return str(path)


def build_cohort(
    project: str,
    raw_dir: Path,
    dims: dict[str, int],
    skip: Iterable[str] = (),
    max_missing: float = 0.2,
    log: Callable[[str], None] = print,
) -> dict[str, np.ndarray]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    survival = survival_table(pd.read_csv(locate("survival", project, raw_dir), sep="\t"))
    clinical = per_patient(pd.read_csv(locate("clinical", project, raw_dir), sep="\t",
                                       low_memory=False))
    candidates = set(survival.index) & set(clinical.index)
    genes = pd.read_csv(locate("genes", project, raw_dir), sep="\t", usecols=["id", "gene"])
    symbol = dict(zip(genes["id"], genes["gene"], strict=True))
    blocks = {}
    for m, build in BUILDERS.items():
        if m in skip:
            log(f"{m}: skipped (mask 0)")
            continue
        source = locate(m, project, raw_dir)
        samples = {s: p for s, p in primary_samples(read_header(source)[1:]).items()
                   if p in candidates}
        cache = None
        if m in STREAMED and source.startswith("http"):
            key = hashlib.sha1("\n".join([source, str(dims[m]), str(max_missing), *sorted(samples)])
                               .encode()).hexdigest()[:10]
            cache = raw_dir / f"{project}.{m}.top{dims[m]}.{key}.pkl"
        if cache is not None and cache.exists():
            block = pd.read_pickle(cache)
            log(f"{m}: cached selection {cache.name}")
        else:
            log(f"{m}: reading {len(samples)} primary tumours from {source}")
            block = build(read_matrix(source, samples), dims[m], max_missing)
            if cache is not None:
                block.to_pickle(cache, protocol=pickle.HIGHEST_PROTOCOL)
        if m in ("genomic", "rna"):
            block.columns = [symbol.get(c, c) for c in block.columns]
        blocks[m] = block
        log(f"{m}: {block.shape[0]} patients x {block.shape[1]} features")
    return assemble_cohort(survival, clinical, blocks, dims)
