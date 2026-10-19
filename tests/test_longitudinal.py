"""Landmark task on a tiny fake cBioPortal-style study (made-up ids, no real data)."""

import numpy as np
import pandas as pd

from muffle.longitudinal import DAYS_PER_MONTH, evaluate, landmark, load

M = DAYS_PER_MONTH


def write(root, name, rows, columns, header=False):
    df = pd.DataFrame(rows, columns=columns)
    with open(root / name, "w") as f:
        if header:  # clinical files start with '#' description lines
            f.write("#Patient\n#desc\n#STRING\n#1\n")
        df.to_csv(f, sep="\t", index=False)


def make_study(root, n=40, seed=0):
    rng = np.random.default_rng(seed)
    ids = [f"P-{i:04d}" for i in range(n)]
    write(root, "data_clinical_sample.txt",
          [[f"{p}-T01", p, "Breast Cancer"] for p in ids] + [["X-T01", "X", "Lung Cancer"]],
          ["SAMPLE_ID", "PATIENT_ID", "CANCER_TYPE"], header=True)
    os_m = rng.uniform(3, 60, n)
    died = rng.random(n) < 0.5
    write(root, "data_clinical_patient.txt",
          [[p, f"{m:.1f}", "1:DECEASED" if d else "0:LIVING", "Yes", "No"]
           for p, m, d in zip(ids, os_m, died, strict=True)],
          ["PATIENT_ID", "OS_MONTHS", "OS_STATUS", "HR", "HER2"], header=True)
    tl = ["PATIENT_ID", "START_DATE", "STOP_DATE"]
    write(root, "data_timeline_diagnosis.txt", [[p, -300, "", "2B"] for p in ids],
          tl + ["CLINICAL_GROUP"])
    write(root, "data_timeline_treatment.txt",
          [[p, int(rng.integers(-100, 400)), "", "Chemo", "PACLITAXEL"] for p in ids],
          tl + ["SUBTYPE", "AGENT"])
    # patient 0 progresses at 3 months; patient 1 at 30 months (outside the 0-12 window)
    prog = [[ids[0], int(3 * M), "", "Y", "#fae9e9"], [ids[1], int(30 * M), "", "Y", "#fae9e9"]]
    write(root, "data_timeline_progression.txt", prog, tl + ["PROGRESSION", "STYLE_COLOR"])
    write(root, "data_timeline_tumor_sites.txt", [[ids[2], 10, "", "Bone"]], tl + ["TUMOR_SITE"])
    labs = [[p, d, "", str(rng.uniform(5, 80))] for p in ids for d in (-90, 0, 200)]
    write(root, "data_timeline_ca_15-3_labs.txt", labs, tl + ["RESULT"])
    write(root, "data_timeline_cea_labs.txt", labs, tl + ["RESULT"])
    write(root, "data_timeline_performance_status.txt",
          [[p, -5, "", "#eea8a8", "1"] for p in ids], tl + ["STYLE_COLOR", "ECOG"])
    write(root, "data_mutations.txt", [["PIK3CA", f"{ids[3]}-T01"]],
          ["Hugo_Symbol", "Tumor_Sample_Barcode"])
    return ids, os_m, died


def test_landmark_labels_use_only_the_window_and_features_only_the_past(tmp_path):
    ids, os_m, died = make_study(tmp_path)
    data = load(tmp_path)
    assert len(data["patients"]) == len(ids)  # the lung-cancer patient is dropped
    x, y = landmark(data, 0, horizon=12)
    assert x.loc[ids[0], "ecog_last"] == 1  # '#' inside a value doesn't cut the line
    assert y[ids[0]] == 1  # progressed at 3 months
    if ids[1] in y.index:  # progression at 30 months is outside (0, 12]
        assert y[ids[1]] == float(died[1] and os_m[1] <= 12)
    for p in y.index:
        expect = p == ids[0] or (died[ids.index(p)] and os_m[ids.index(p)] <= 12)
        assert y[p] == float(expect)
        assert os_m[ids.index(p)] > 12 or expect  # censored inside the window are dropped
    assert x.loc[ids[3], "mut_PIK3CA"] == 1 and x["progressions_so_far"].sum() == 0
    # the lab at day 200 is in the future at landmark 0, so the last value is the day-0 one
    x6, _ = landmark(data, 12, horizon=12)
    assert (x["ca153_tests"].dropna() == 2).all()
    assert (x6["ca153_tests"].dropna() == 3).all()


def test_evaluate_reports_both_models_per_landmark(tmp_path):
    make_study(tmp_path, n=120, seed=1)
    res = evaluate(load(tmp_path), seeds=(0, 1), landmarks=(0,))
    r = res["0"]
    assert r["n"] > 0 and 0 <= r["event_rate"] <= 1
    assert len(r["baseline_auroc"]) == 2 and len(r["runs"]) == 2
