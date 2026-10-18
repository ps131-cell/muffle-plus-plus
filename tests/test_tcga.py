"""TCGA loader logic on a tiny synthetic Xena-style fixture (no real data, no network)."""

import numpy as np
import pandas as pd
import pytest

from muffle.config import MODALITIES
from muffle.data.dataset import MultiOmicDataset
from muffle.data.tcga import (
    CLINICAL_FEATURES,
    DAYS_PER_MONTH,
    SOURCES,
    build_cohort,
    clinical_features,
    copy_number_calls,
    primary_samples,
    select_top,
)

PROJECT = "FAKE-TEST"
DIMS = {"genomic": 5, "rna": 6, "methylation": 7, "protein": 4,
        "clinical": len(CLINICAL_FEATURES)}
SITES = ["AA", "AA", "AA", "BB", "BB", "BB", "CC", "CC", "CC", "CC"]
PATIENTS = [f"FAKE-{s}-{i:04d}" for i, s in enumerate(SITES)]  # TCGA barcode layout, made up


def write(df: pd.DataFrame, raw, role: str, index: bool = True):
    df.to_csv(raw / SOURCES[role].format(project=PROJECT), sep="\t", index=index,
              compression="gzip" if role != "genes" else None)


def xena(values: np.ndarray, features: list[str], samples: list[str], name: str) -> pd.DataFrame:
    """Feature x sample matrix, the hub's orientation."""
    return pd.DataFrame(values, index=pd.Index(features, name=name), columns=samples)


@pytest.fixture
def raw(tmp_path):
    """Patients 0-7 qualify; 8 has only an 01B tumour, 9 has no survival time."""
    rng = np.random.default_rng(0)
    days = rng.integers(30, 3000, len(PATIENTS)).astype(float)
    days[9] = np.nan
    event = np.arange(len(PATIENTS)) % 3 == 0
    surv = pd.DataFrame({"sample": [p + "-01A" for p in PATIENTS], "OS.time": days,
                         "OS": event.astype(int), "_PATIENT": PATIENTS})
    normal = surv.iloc[[0]].assign(sample=PATIENTS[0] + "-11A")
    write(pd.concat([surv, normal]), tmp_path, "survival", index=False)

    clin = pd.DataFrame({
        "sample": [p + "-01A" for p in PATIENTS],
        "age_at_index.demographic": [50, 61, np.nan, 45, 70, 38, 66, 59, 52, 48],
        "days_to_birth.demographic": -365.25 * np.array([50, 61, 72, 45, 70, 38, 66, 59, 52, 48]),
        "ajcc_pathologic_stage.diagnoses": ["Stage IIA", "Stage IIIC", "Stage I", "Stage IV",
                                            "Stage X", "Stage IB", None, "Stage IIB",
                                            "Stage II", "Stage III"],
        "ajcc_pathologic_t.diagnoses": ["T2", "T4b", "T1c", "T3", "TX", "T1", "T2", "T2", "T2",
                                        "T3"],
        "ajcc_pathologic_n.diagnoses": ["N0 (i-)", "N3a", "N1mi", "N2", "NX", "N0", "N1a", "N0",
                                        "N1", "N2"],
        "ajcc_pathologic_m.diagnoses": ["M0", "M0", "MX", "M1", "cM0 (i+)", "M0", "M0", "M0",
                                        "M0", "M0"],
        "primary_diagnosis.diagnoses": ["Infiltrating duct carcinoma, NOS",
                                        "Lobular carcinoma, NOS",
                                        "Infiltrating duct and lobular carcinoma",
                                        "Mucinous adenocarcinoma"] + ["Infiltrating duct "
                                                                     "carcinoma, NOS"] * 6,
    })
    write(clin, tmp_path, "clinical", index=False)

    genes = [f"ENSG{i:011d}.1" for i in range(40)]
    write(pd.DataFrame({"id": genes, "gene": [f"GENE{i}" for i in range(40)],
                        "chrom": "chr1", "chromStart": 1, "chromEnd": 2, "strand": "+"}),
          tmp_path, "genes", index=False)

    tumours = [p + "-01A" for p in PATIENTS]
    rna = rng.gamma(1.0, 2.0, (30, 10)) * rng.uniform(0.2, 3, (30, 1))
    rna_samples = tumours[:8] + [PATIENTS[0] + "-11A", PATIENTS[8] + "-01B"]
    write(xena(rna, genes[:30], rna_samples, "Ensembl_ID"), tmp_path, "rna")

    cn = rng.choice([0, 1, 2, 2, 2, 3, 4, 6], (40, 7)).astype(float)
    cn[0] = np.nan  # gene without coverage
    write(xena(cn, genes, tumours[:7], "Ensembl_ID"), tmp_path, "genomic")

    beta = rng.beta(0.5, 0.5, (50, 5))
    beta[3] = np.nan  # sparse probe
    beta[4, 0] = np.nan  # one missing value, imputed
    probes = [f"cg{i:08d}" for i in range(50)]
    write(xena(beta, probes, tumours[:5], "Composite Element REF"), tmp_path, "methylation")

    rppa = rng.normal(0, 0.5, (20, 6))
    write(xena(rppa, [f"PROT{i}" for i in range(20)], tumours[2:8], "peptide_target"),
          tmp_path, "protein")
    return tmp_path


def test_primary_samples_keeps_01a_only():
    cols = ["FAKE-AA-0001-01A", "FAKE-AA-0001-11A", "FAKE-AA-0002-01B", "FAKE-AA-0003-06A",
            "FAKE-AA-0004-01A", "Ensembl_ID"]
    assert primary_samples(cols) == {"FAKE-AA-0001-01A": "FAKE-AA-0001",
                                     "FAKE-AA-0004-01A": "FAKE-AA-0004"}


def test_select_top_blockwise_matches_whole_matrix():
    rng = np.random.default_rng(1)
    x = pd.DataFrame(rng.normal(size=(20, 60)) * rng.uniform(0.1, 5, 60),
                     columns=[f"f{i}" for i in range(60)])
    loudest = x.var().idxmax()
    x.loc[:11, loudest] = np.nan  # 60% missing -> dropped despite the largest variance
    whole = select_top([x], 10)
    blocks = select_top([x.iloc[:, :17], x.iloc[:, 17:41], x.iloc[:, 41:]], 10)
    assert loudest not in whole.columns
    assert list(blocks.columns) == list(whole.columns)
    with pytest.raises(ValueError):
        select_top([x], 60)


def test_copy_number_calls_relative_to_ploidy():
    cn = pd.DataFrame([[0, 1, 2, 2, 2, 3, 4, 5],    # diploid
                       [3, 3, 3, 2, 6, 0, 4, 3]])   # triploid
    assert copy_number_calls(cn).to_numpy().tolist() == [[-2, -1, 0, 0, 0, 1, 2, 2],
                                                         [0, 0, 0, -1, 2, -2, 1, 0]]


def test_clinical_features_parse_gdc_fields():
    clin = pd.DataFrame({
        "age_at_index.demographic": [40.0, 60.0, np.nan],
        "days_to_birth.demographic": [-14610.0, -21915.0, -18262.5],
        "ajcc_pathologic_stage.diagnoses": ["Stage IIIA", "Stage I", "Stage X"],
        "ajcc_pathologic_t.diagnoses": ["T4b", "T1c", "TX"],
        "ajcc_pathologic_n.diagnoses": ["N2a", "N0 (i-)", "NX"],
        "ajcc_pathologic_m.diagnoses": ["M1", "cM0 (i+)", "MX"],
        "primary_diagnosis.diagnoses": ["Lobular carcinoma, NOS",
                                        "Infiltrating duct and lobular carcinoma", None],
    })
    feats, stage = clinical_features(clin)
    assert list(feats.columns) == CLINICAL_FEATURES
    assert stage.tolist() == [3, 1, 2]  # unknown stage -> median
    assert feats["stage_unknown"].tolist() == [0, 0, 1]
    assert feats["metastasis"].tolist() == [1, 0, 0]
    assert feats["ductal"].tolist() == [0, 1, 0] and feats["lobular"].tolist() == [1, 1, 0]
    assert feats["age"].iloc[2] == pytest.approx(0)  # 50 from days_to_birth, mean of 40/60/50
    assert feats["pathologic_t"].iloc[0] > feats["pathologic_t"].iloc[1]
    assert np.isfinite(feats.to_numpy()).all()


def test_build_cohort_end_to_end(raw, tmp_path):
    cohort = build_cohort(PROJECT, raw, DIMS, log=lambda _: None)
    assert cohort["patient"].tolist() == PATIENTS[:8]
    assert cohort["tss"].tolist() == SITES[:8]

    measured = {"genomic": range(7), "rna": range(8), "methylation": range(5),
                "protein": range(2, 8), "clinical": range(8)}
    for j, m in enumerate(MODALITIES):
        x = cohort[f"x_{m}"]
        assert x.shape == (8, DIMS[m]) and x.dtype == np.float32
        expected = np.isin(np.arange(8), list(measured[m]))
        assert cohort["mask"][:, j].tolist() == expected.astype(float).tolist()
        assert np.all(x[~expected] == 0)
        assert np.isfinite(x).all()
    assert "cg00000003" not in cohort["names_methylation"]  # sparse probe dropped
    assert all(n.startswith("GENE") for n in cohort["names_rna"])
    rna = cohort["x_rna"]
    assert np.allclose(rna.mean(0), 0, atol=1e-5) and np.allclose(rna.std(0), 1, atol=1e-4)
    assert set(np.unique(cohort["x_genomic"])) <= {-2, -1, 0, 1, 2}

    surv = pd.read_csv(raw / SOURCES["survival"].format(project=PROJECT), sep="\t")
    days = surv.drop_duplicates("_PATIENT").set_index("_PATIENT")["OS.time"]
    assert np.allclose(cohort["time"], days[PATIENTS[:8]] / DAYS_PER_MONTH)
    assert cohort["event"].tolist() == [float(i % 3 == 0) for i in range(8)]
    assert set(cohort["stage"]) <= {1, 2, 3, 4}

    np.savez_compressed(tmp_path / "cohort.npz", **cohort)
    ds = MultiOmicDataset(tmp_path / "cohort.npz", DIMS)
    assert len(ds) == 8 and ds.mask.shape == (8, len(DIMS))
