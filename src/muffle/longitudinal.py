"""Risk updates along real patient timelines: MSK-CHORD breast cancer (milestone 1, part two).

python -m muffle.longitudinal              # after scripts/prepare_msk_chord.py; ~1 min

MSK-CHORD (Jee et al., Nature 2024; cBioPortal msk_chord_2024) is CC BY-NC-ND 4.0: it is used
locally only, and only code and aggregate results leave this machine. Nothing here prints,
saves outside data/ or sends anywhere any individual patient's record.

Time 0 is each patient's first tumor sequencing (MSK-IMPACT); diagnosis is earlier and overall
survival is counted from time 0. At each landmark L (months after time 0), every patient still
alive at L is scored for the **risk of progression (radiology-confirmed, NLP-derived) or death in
the next 12 months**, using only what was recorded up to L. Patients followed for less than
L + 12 months without an event are left out of that landmark.

Two versions of the same learner (gradient boosting, which handles missing values) are compared on
the same patients: a **baseline** that only knows the diagnosis (stage, HR, HER2) and a **record
so far** model that also sees the timeline up to L (treatments by type, prior progressions,
metastatic sites, the latest CA 15-3 / CEA and their trend, ECOG, sequenced drivers). Splits are
by patient (seeds 0-4); no hyper-parameters were tuned (library defaults, fixed depth).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss, roc_auc_score

ROOT = Path("data/raw/msk_chord/extract/msk_chord_2024")
DAYS_PER_MONTH = 30.4375
LANDMARKS = (0, 6, 12, 24)
HORIZON = 12  # months
TREATMENT_TYPES = ("Chemo", "Hormone", "Targeted", "Biologic", "Bone Treatment")
DRIVERS = ("ESR1", "PIK3CA", "TP53", "ERBB2", "AKT1", "CDH1", "GATA3", "PTEN")
BASELINE = ["stage", "hr", "her2"]


def _read(root: Path, name: str) -> pd.DataFrame:
    """cBioPortal tables; only the clinical files have '#' header lines (timeline files use '#'
    inside values, e.g. STYLE_COLOR '#fae9e9', so no comment parsing there)."""
    comment = "#" if name.startswith("data_clinical") else None
    return pd.read_csv(root / name, sep="\t", comment=comment, dtype=str, low_memory=False)


def _days(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(day=pd.to_numeric(df["START_DATE"], errors="coerce")).dropna(subset=["day"])


def load(root: Path = ROOT, cancer: str = "Breast Cancer") -> dict[str, pd.DataFrame]:
    """The tables the task needs, restricted to ``cancer`` patients (aggregate use only)."""
    samples = _read(root, "data_clinical_sample.txt")
    keep = set(samples.loc[samples["CANCER_TYPE"] == cancer, "PATIENT_ID"])
    pat = _read(root, "data_clinical_patient.txt").set_index("PATIENT_ID").loc[sorted(keep)]
    dx = _days(_read(root, "data_timeline_diagnosis.txt"))
    dx = dx[dx["PATIENT_ID"].isin(keep)].sort_values("day").drop_duplicates("PATIENT_ID")
    group = dx.set_index("PATIENT_ID")["CLINICAL_GROUP"].astype(str).str[0]
    patients = pd.DataFrame({
        "os_days": pd.to_numeric(pat["OS_MONTHS"], errors="coerce") * DAYS_PER_MONTH,
        "died": pat["OS_STATUS"].astype(str).str.startswith("1").astype(float),
        "hr": (pat["HR"] == "Yes").astype(float), "her2": (pat["HER2"] == "Yes").astype(float),
        "stage": pd.to_numeric(group.reindex(pat.index), errors="coerce").where(lambda s: s <= 4),
    })

    def events(name: str) -> pd.DataFrame:
        t = _days(_read(root, name))
        return t[t["PATIENT_ID"].isin(keep)]

    muts = _read(root, "data_mutations.txt")
    muts = muts.assign(PATIENT_ID=muts["Tumor_Sample_Barcode"].map(
        samples.set_index("SAMPLE_ID")["PATIENT_ID"]))
    return {
        "patients": patients,
        "treatment": events("data_timeline_treatment.txt"),
        "progression": events("data_timeline_progression.txt").query("PROGRESSION == 'Y'"),
        "sites": events("data_timeline_tumor_sites.txt"),
        "ca153": events("data_timeline_ca_15-3_labs.txt"),
        "cea": events("data_timeline_cea_labs.txt"),
        "ecog": events("data_timeline_performance_status.txt"),
        "drivers": muts[muts["PATIENT_ID"].isin(keep) & muts["Hugo_Symbol"].isin(DRIVERS)],
    }


def _lab_features(labs: pd.DataFrame, cut: float, name: str) -> pd.DataFrame:
    """Latest log value and its change over the 6 months before ``cut``."""
    t = labs[labs["day"] <= cut].assign(v=lambda d: np.log1p(
        pd.to_numeric(d["RESULT"], errors="coerce").clip(lower=0))).dropna(subset=["v"])
    t = t.sort_values("day")
    last = t.groupby("PATIENT_ID")["v"].last()
    early = t[t["day"] >= cut - 6 * DAYS_PER_MONTH].groupby("PATIENT_ID")["v"].first()
    return pd.DataFrame({f"{name}_last": last, f"{name}_change_6m": last - early,
                         f"{name}_tests": t.groupby("PATIENT_ID").size()})


def landmark(data: dict[str, pd.DataFrame], months: float,
             horizon: float = HORIZON) -> tuple[pd.DataFrame, pd.Series]:
    """(features, label) at ``months`` after time 0, from events up to then only.

    Label 1 = progression or death in (L, L + horizon]; 0 = followed past L + horizon without
    either; patients dead before L or censored inside the window are dropped."""
    cut, end = months * DAYS_PER_MONTH, (months + horizon) * DAYS_PER_MONTH
    p = data["patients"]
    alive = p[p["os_days"] > cut]
    prog = data["progression"]
    future = prog[(prog["day"] > cut) & (prog["day"] <= end)]["PATIENT_ID"].unique()
    event = alive.index.isin(future) | ((alive["died"] == 1) & (alive["os_days"] <= end))
    known = event | (alive["os_days"] > end)
    ids = alive.index[known]
    return features(data, ids, cut), pd.Series(event[known].astype(float), index=ids,
                                               name="event")


def features(data: dict[str, pd.DataFrame], ids, cut: float) -> pd.DataFrame:
    """The record-so-far features of patients ``ids`` from events on or before day ``cut``."""
    x = data["patients"].loc[ids, BASELINE].copy()
    tr = data["treatment"]
    tr = tr[tr["day"] <= cut]
    for kind in TREATMENT_TYPES:
        x[f"rx_{kind.lower().replace(' ', '_')}"] = (
            tr[tr["SUBTYPE"] == kind].groupby("PATIENT_ID").size().reindex(ids).fillna(0))
    x["rx_agents"] = tr.groupby("PATIENT_ID")["AGENT"].nunique().reindex(ids).fillna(0)
    prog = data["progression"]
    past = prog[prog["day"] <= cut]
    x["progressions_so_far"] = past.groupby("PATIENT_ID").size().reindex(ids).fillna(0)
    x["months_since_progression"] = ((cut - past.groupby("PATIENT_ID")["day"].max())
                                     / DAYS_PER_MONTH).reindex(ids)
    sites = data["sites"]
    x["metastatic_sites"] = (sites[sites["day"] <= cut].groupby("PATIENT_ID")["TUMOR_SITE"]
                             .nunique().reindex(ids).fillna(0))
    for name in ("ca153", "cea"):
        x = x.join(_lab_features(data[name], cut, name), how="left")
    ecog = data["ecog"][data["ecog"]["day"] <= cut].sort_values("day")
    x["ecog_last"] = pd.to_numeric(ecog.groupby("PATIENT_ID")["ECOG"].last(),
                                   errors="coerce").reindex(ids)
    drv = data["drivers"]  # sequenced at time 0, so known at every landmark
    for g in DRIVERS:
        x[f"mut_{g}"] = x.index.isin(drv.loc[drv["Hugo_Symbol"] == g, "PATIENT_ID"]).astype(float)
    return x


def _test_ids(data: dict[str, pd.DataFrame], seed: int, test_fraction: float) -> set:
    everyone = np.array(sorted(data["patients"].index))
    return set(np.random.default_rng(seed).permutation(everyone)
               [: int(len(everyone) * test_fraction)])


def _fit(x: pd.DataFrame, y: pd.Series, train, cols: list[str], seed: int):
    """(classifier, columns it uses) on the ``train`` rows."""
    # a feature nobody in the training split has yet (e.g. no progression before time 0)
    # carries no information, and an all-missing column breaks the binning
    cols = [c for c in cols if x.loc[train, c].notna().any()]
    clf = HistGradientBoostingClassifier(max_depth=3, random_state=seed)
    return clf.fit(x.loc[train, cols], y[train]), cols


def evaluate(data: dict[str, pd.DataFrame], seeds=(0, 1, 2, 3, 4), landmarks=LANDMARKS,
             test_fraction: float = 0.2, keep_models: bool = False) -> dict:
    """AUROC and Brier per landmark for the baseline and the record-so-far model.

    With ``keep_models``, each run also keeps its two fitted (classifier, columns) pairs under
    "models" (not JSON-serializable; used to score the demo's synthetic patient)."""
    out = {}
    for L in landmarks:
        x, y = landmark(data, L)
        rows = {"n": int(len(y)), "event_rate": float(y.mean()), "runs": []}
        for seed in seeds:
            test = x.index.isin(_test_ids(data, seed, test_fraction))
            run, models = {}, {}
            for name, cols in (("baseline", BASELINE), ("record_so_far", list(x.columns))):
                clf, used = _fit(x, y, ~test, cols, seed)
                prob = clf.predict_proba(x.loc[test, used])[:, 1]
                run[name] = {"auroc": float(roc_auc_score(y[test], prob)),
                             "brier": float(brier_score_loss(y[test], prob))}
                models[name] = (clf, used)
            if keep_models:
                run["models"] = models
            rows["runs"].append(run)
        for name in ("baseline", "record_so_far"):
            for m in ("auroc", "brier"):
                v = np.array([r[name][m] for r in rows["runs"]])
                rows[f"{name}_{m}"] = [float(v.mean()), float(v.std(ddof=1))]
        out[str(L)] = rows
    return out


def markdown(res: dict) -> str:
    lines = ["| landmark (months after sequencing) | patients | event rate | baseline AUROC | "
             "record-so-far AUROC | baseline Brier | record-so-far Brier |",
             "|---|---|---|---|---|---|---|"]
    def ms(v: list[float]) -> str:
        return f"{v[0]:.3f} ± {v[1]:.3f}"

    for L, r in res.items():
        lines.append(f"| {L} | {r['n']} | {r['event_rate']:.2f} | {ms(r['baseline_auroc'])} | "
                     f"{ms(r['record_so_far_auroc'])} | {ms(r['baseline_brier'])} | "
                     f"{ms(r['record_so_far_brier'])} |")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2, 3, 4])
    p.add_argument("--out", type=Path, default=Path("outputs/msk_chord"))
    args = p.parse_args(argv)
    res = evaluate(load(args.root), seeds=tuple(args.seeds))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "risk_updates.json").write_text(json.dumps(res, indent=1))
    table = markdown(res)
    (args.out / "risk_updates.md").write_text(table + "\n")
    print(table)  # aggregates only
    return res


if __name__ == "__main__":
    main()
