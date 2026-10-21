"""Radiology workbench: the report reads of the synthetic record, the lesion table, lead and lag,
kinetics, measurements on hand-made masks, the seed rule on a hand-made volume, and the page."""

import json
from pathlib import Path

import numpy as np
import pytest

from muffle.timeline import EVENTS
from muffle.workbench.radiology import (
    CANNOT_SEE,
    CUTOFFS,
    NO_MEASUREMENTS,
    PLACEHOLDERS,
    PROGRESSION,
    REPORT_CANNOT_SEE,
    STABLE,
    breast_region,
    candidates,
    cleft_row,
    dense_fraction,
    file_events,
    imaging_reads,
    kinetics,
    lead_lag,
    lesion_table,
    load_index,
    load_study,
    longest_diameter_mm,
    search,
    slice_box,
    volume_ml,
    volume_range_ml,
)
from muffle.workspace import IMPLEMENTED, finding_key, synthetic_file

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "app" / "workbenches" / "radiology_results"


def test_reads_of_the_synthetic_record_keep_the_reports_words():
    reads = imaging_reads(EVENTS)
    assert [r["month"] for r in reads] == [-1, 7, 12, 19, 24]
    assert [r["read"] for r in reads] == [PROGRESSION, STABLE, PROGRESSION, STABLE, STABLE]
    assert [r["new_sites"] for r in reads] == [["Bone"], [], ["Liver"], [], []]
    assert reads[0]["words"] == "read as progression" and all(r["agrees"] for r in reads)
    assert reads[-1]["source"].startswith("clinic visit note")  # "Imaging stable" at month 24
    assert {r["measurements"] for r in reads} == {NO_MEASUREMENTS}
    assert {r["evidence"] for r in reads} == {"observed"}


def test_lesion_table_tracks_named_sites_and_never_calls_an_unnamed_site_stable():
    table = {row["site"]: row for row in lesion_table(imaging_reads(EVENTS))}
    assert list(table) == ["Bone", "Liver"]
    bone, liver = table["Bone"]["cells"], table["Liver"]["cells"]
    assert bone[-1] == "new" and bone[7] == "not named; overall read: stable"
    assert bone[12] == "not named; overall read: progression"
    assert liver[-1] == liver[7] == "not yet named" and liver[12] == "new"
    assert table["Liver"]["first_named"] == 12 and table["Bone"]["named_in"] == [-1]
    assert all("stable" != cell for row in table.values() for cell in row["cells"].values())
    assert table["Bone"]["measurements"] == NO_MEASUREMENTS


def test_lead_and_lag_against_ca153_is_an_observed_order_of_events():
    lag = {x["imaging_month"]: x for x in lead_lag(EVENTS)}
    assert lag[12]["marker_month"] == 11 and lag[12]["lead_months"] == 1
    assert "rising" in lag[12]["flag"] and lag[12]["what"].endswith("concordant")
    assert lag[-1]["marker_month"] == -2 and lag[-1]["progression"]
    assert lag[24]["lead_months"] == 0  # the clinic visit holds both the marker and the read
    assert {x["evidence"] for x in lag.values()} == {"observed"}
    assert "not a validated lead time" in lag[12]["caveat"]


def test_kinetics_in_the_lexicons_terms():
    fast_washout = kinetics([100, 260, 240, 200], [0, 60, 120, 360])
    assert fast_washout["initial"] == "fast" and fast_washout["peak_phase"] == 1
    assert fast_washout["delayed"] == "washout" and fast_washout["curve_type"] == "III"
    slow = kinetics([100, 120, 140, 180], [0, 60, 120, 360])
    assert slow["initial"] == "slow" and slow["peak_phase"] == 2  # the stronger early phase
    assert slow["delayed"] == "persistent" and slow["curve_type"] == "I"
    plateau = kinetics([100, 180, 182, 185, 178])  # no times: the first post phase is initial
    assert plateau["initial"] == "medium" and plateau["peak_phase"] == 1
    assert plateau["delayed"] == "plateau" and plateau["evidence"] == "model inference"
    assert "note" in kinetics([100, 150])
    assert CUTOFFS["delayed_band_pct"][1].startswith("literature")  # placeholder until calibrated


def test_longest_diameter_and_volume_on_hand_made_masks():
    rect = np.zeros((40, 40), bool)
    rect[5:15, 10:30] = True  # 10 x 20 pixels
    d, (a, b) = longest_diameter_mm(rect, (1.0, 1.0))
    assert d == pytest.approx(np.hypot(9, 19)) and {a[0], b[0]} == {5, 14}
    assert longest_diameter_mm(rect, (0.5, 0.5))[0] == pytest.approx(d / 2)
    yy, xx = np.mgrid[:64, :64]
    disk = (yy - 32) ** 2 + (xx - 32) ** 2 <= 20 ** 2
    assert 39 <= longest_diameter_mm(disk, (1.0, 1.0))[0] <= 40
    cube = np.zeros((12, 20, 20), bool)
    cube[1:11, 5:15, 5:15] = True
    assert volume_ml(cube, (2.0, 0.5, 0.5)) == pytest.approx(0.5)
    lo, hi = volume_range_ml(cube, (2.0, 0.5, 0.5))
    assert lo < 0.5 < hi


def test_seed_rule_keeps_compact_blobs_and_leaves_vessels_out():
    # mostly background, as in a breast: the seed threshold is a percentile of the region, so
    # the bright objects must stay well under 0.5% of its voxels
    rng = np.random.default_rng(0)
    sub = rng.normal(0, 1, (64, 160, 128))
    zz, yy, xx = np.mgrid[:64, :160, :128]
    sub[(zz - 15) ** 2 + (yy - 20) ** 2 + (xx - 20) ** 2 <= 16] += 50  # a 4-voxel-radius mass
    sub[(zz - 10) ** 2 + (yy - 22) ** 2 + (xx - 45) ** 2 <= 9] += 45   # a smaller one
    sub[19:36, 19:21, 19:21] += 60    # a thin vessel off the mass: the opening takes it off
    sub[2:26, 37:43, 27:33] += 60     # a thick vessel along z: survives, left out as vessel-like
    sub[30:54, 77:83, 5:29] += 60     # a plate (chest wall): left out as plate-like
    sub[12:18, 146:152, 50:56] += 50  # cut by the posterior limit at row 152
    region = np.ones_like(sub, bool)
    region[:, 152:, :] = False
    found, info = candidates(sub, region, (1.0, 1.0, 1.0), limit_row=152)
    assert found[0]["id"] == "C1" and found[0]["bbox"][0] <= 15 < found[0]["bbox"][1] <= 22
    assert abs((found[0]["bbox"][2] + found[0]["bbox"][3]) / 2 - 20) <= 1
    out = info["left_out"]
    assert out["vessel-like"] >= 1 and out["plate-like"] >= 1 and out["at the chest-wall line"] == 1
    assert all(c["elongation"] <= 3 and c["flatness"] <= 3 for c in found) and len(found) == 2
    box = slice_box(info["labels"][15] == found[0]["label"])
    assert box[0] < 20 < box[2] and box[1] < 20 < box[3]


def test_breast_region_stops_at_the_cleft_plus_a_margin():
    vol = np.zeros((4, 80, 100))
    for x in range(100):  # two breasts: skin at row 10 at x=25 and x=75, cleft at row 30
        vol[:, 10 + int(20 * abs(np.cos(np.pi * x / 50))):, x] = 100.0
    region, info = breast_region(vol, (1.0, 1.0, 1.0))
    assert 28 <= info["cleft_row"] <= 31 and info["limit_row"] == info["cleft_row"] + 10
    assert not region[:, info["limit_row"]:, :].any() and region[:, 20, 25].all()
    assert cleft_row(np.full((3, 50), -1)) is None


def test_dense_fraction_is_a_pixel_share():
    img = np.zeros((100, 100))
    img[:, :50] = 200.0   # dense half
    img[:, 50:80] = 60.0  # fatty part
    out = dense_fraction(img, background=10)
    assert out["dense_fraction"] == pytest.approx(50 / 80, abs=0.01)
    assert out["status"] == "implemented, placeholder rule"


def test_search_answers_honestly():
    reads = imaging_reads(EVENTS)
    assert [r["month"] for r in search("liver", reads)["reads"]] == [12]
    assert search("lung", reads)["answer"].startswith("0 read(s) naming lung")
    assert len(search("progression", reads)["reads"]) == 2
    assert not search("lesion size", reads, cannot_see=REPORT_CANNOT_SEE)["understood"]
    hit = search("PIK3CA mutation", [], [])
    assert not hit["understood"] and "sequencing" in hit["answer"].lower()
    lesions = [{"id": "C1", "volume_ml": 2.0, "kinetics": {"delayed": "washout"}},
               {"id": "C2", "volume_ml": 3.0, "kinetics": {"delayed": "plateau"}}]
    assert [c["id"] for c in search("washout", [], lesions)["lesions"]] == ["C1"]
    assert [c["id"] for c in search("largest", [], lesions)["lesions"]] == ["C2"]
    assert search("liver", [], lesions)["answer"].startswith("This test can't see that")
    assert len(CANNOT_SEE) >= 5


def test_imaging_tests_open_the_workbench_and_marks_have_a_kind():
    tl = json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
    pf = synthetic_file(tl)
    imaging = [t for t in pf.tests if t.kind == "Imaging"]
    assert {(t.workbench, t.status) for t in imaging} == {("imaging", IMPLEMENTED)}
    key = finding_key(pf, "imaging", "report", 12, "Liver")
    assert key == "SYNTHETIC-001|imaging|report|12|Liver"


def test_each_file_reads_only_its_own_imaging_reports():
    from types import SimpleNamespace

    from muffle.workspace import Test, case_file

    tl = json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
    pf = synthetic_file(tl)
    assert [r["month"] for r in imaging_reads(file_events(pf))] == [-1, 7, 12, 19, 24]
    month12 = next(i for i, v in enumerate(pf.versions) if v.month == 12)
    assert max(e["month"] for e in file_events(pf, month12)) == 12
    case = SimpleNamespace(index=1, mutations=None, layers=["clinical"], missing=[], stage=None,
                           age=None, percentile=50.0, group="intermediate", site="site-1")
    tcga = case_file(case, None)
    assert file_events(tcga) == []  # no imports: never the synthetic record
    event = {"month": 3, "kind": "Imaging", "progression": True, "sites": ["Liver"],
             "text": "Imaging (imported report): read as progression; new liver named"}
    tcga.versions[0].tests.append(Test("Imaging", 3, "CT chest and abdomen", "read as "
                                       "progression", "imaging", IMPLEMENTED, {"event": event}))
    reads = imaging_reads(file_events(tcga))
    assert [(r["month"], r["read"], r["new_sites"]) for r in reads] == [(3, PROGRESSION, ["Liver"])]


def test_placeholders_list_every_unvalidated_cutoff():
    names = [what for what, _ in PLACEHOLDERS]
    assert "seed_percentile" in names and "delayed_band_pct" in names  # literature placeholders too
    assert "box_pad" not in names and "mask_threshold" not in names    # design choices are not
    assert len(PLACEHOLDERS) == sum(1 for _, tag, _ in CUTOFFS.values() if tag != "design")


def test_shipped_studies_are_small_and_attributed():
    index = load_index(RESULTS)
    if not index:
        pytest.skip("no processed studies in this checkout")
    for studies in index.values():
        for s in studies:
            folder = RESULTS / s["folder"]
            study = load_study(folder)
            assert study["source"]["license"] == "CC BY 3.0" and "doi" in study["source"]
            assert sum(p.stat().st_size for p in folder.iterdir()) < 5_000_000
            for c in study.get("candidates", []):
                assert c["evidence"] == "model inference" and c["longest_diameter_mm"] > 0
            monai = study.get("density_monai", {})
            if monai.get("status") == "implemented":  # one class per shipped view, A-D
                assert set(monai["views"]) == {v["key"] for v in study["views"]}
                assert {v["density_class"] for v in monai["views"].values()} <= set("ABCD")
                assert "not to be used for diagnostic purposes" in monai["card"]["intended_use"]
