"""Radiology workbench: the report reads of the synthetic record, the lesion table, lead and lag,
kinetics, measurements on hand-made masks, the seed rule on a hand-made volume, and the page."""

import json
from pathlib import Path

import numpy as np
import pytest

from muffle.imports import imaging_read, imaging_test
from muffle.timeline import EVENTS
from muffle.workbench.radiology import (
    CANNOT_SEE,
    CUTOFFS,
    NO_MEASUREMENTS,
    NOT_STATED,
    PLACEHOLDERS,
    PROGRESSION,
    REPORT_CANNOT_SEE,
    RESPONSE,
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
    queue,
    read_of,
    search,
    sites_named_new,
    summary,
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


def test_report_reading_sets_aside_negated_and_hedged_mentions_like_the_import():
    # the import's rule (muffle.imports.imaging_read): a negated clause states nothing
    read = read_of("No evidence of disease progression. Bone lesions stable.")
    assert read == (STABLE, "stable")
    assert sites_named_new("No new liver lesions.") == []
    # a hedged one neither
    assert read_of("Findings suspicious for progression.") == (NOT_STATED, "")
    assert sites_named_new("Possible new liver lesions; new bone lesions.") == ["Bone"]
    # the lesion table keeps local and regional sites; the import's alert counts distant only
    assert sites_named_new("New chest wall nodule.") == ["Chest wall"]
    assert imaging_read("New chest wall nodule.")["new_sites"] == []
    # an imported report's one-line read, and the record's flag over the words
    read = read_of("Imaging (imported report): read as response")
    assert read == (RESPONSE, "read as response")
    flagged = imaging_reads([{"month": 3, "kind": "Imaging", "progression": True,
                              "text": "Imaging: no evidence of progression"}])
    assert flagged[0]["read"] == PROGRESSION and flagged[0]["words"].startswith("the record's")


def test_an_imported_reports_new_site_is_moderate_trust_like_its_alert():
    from types import SimpleNamespace

    from muffle.workspace import case_file

    case = SimpleNamespace(index=1, mutations=None, layers=["clinical"], missing=[], stage=None,
                           age=None, percentile=50.0, group="intermediate", site="site-1")
    pf = case_file(case, None)
    pf.versions[0].tests.append(imaging_test(
        "CT chest and abdomen", "New hepatic lesions. No new osseous lesions.", 3, "doc-1", "test"))
    items = [q for q in queue(pf) if q["pointer"]]
    assert [q["pointer"] for q in items] == ["Liver"]  # the negated bone mention names no site
    assert items[0]["trust"] == "moderate" and "import's text rule" in items[0]["why"]
    assert items[0]["opens"] == ("Tests", "Imaging", 3, "Imaging report")
    assert summary(pf)["cards"][0]["trust"] == "moderate"


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


# --- round 2: change over time, multiplanar views, mammography geometry --------------------------
def _phantom(shape=(28, 40, 44), spacing=(3.0, 1.5, 1.5), seed=1):
    """A body-like ellipsoid with smooth texture, [Z, Y, X] at ``spacing``."""
    from scipy import ndimage

    rng = np.random.default_rng(seed)
    tex = ndimage.gaussian_filter(rng.normal(0, 1, shape), (1.0, 2.0, 2.0))
    zz, yy, xx = np.indices(shape) * np.asarray(spacing)[:, None, None, None]
    c = (np.array(shape) - 1) * np.asarray(spacing) / 2
    body = ((zz - c[0]) / 36) ** 2 + ((yy - c[1]) / 24) ** 2 + ((xx - c[2]) / 26) ** 2 <= 1
    return np.where(body, 100 + 40 * tex, 0.0).astype(np.float32)


def test_rigid_registration_recovers_a_known_shift_and_rotation():
    from muffle.workbench.radiology import _sample, map_points, register, rigid_matrix

    sp_f, sp_m = (3.0, 1.5, 1.5), (2.0, 1.25, 1.5)  # anisotropic, and not the same voxels
    fixed = _phantom(spacing=sp_f)
    true = {"matrix": rigid_matrix([3.0, 0.0, 0.0]), "center_mm": [40.0, 30.0, 32.0],
            "shift_mm": [4.0, -3.0, 5.0]}
    shape_m = (42, 48, 44)
    q = np.indices(shape_m).reshape(3, -1).T * np.asarray(sp_m)
    moving = _sample(fixed, sp_f, map_points(q, true, inverse=True))  # m(T(p)) = f(p)
    moving = np.nan_to_num(moving).reshape(shape_m).astype(np.float32)
    est = register(fixed, moving, sp_f, sp_m)
    probe = np.array([[30.0, 25.0, 25.0], [50.0, 35.0, 40.0], [40.0, 30.0, 32.0]])
    err = np.linalg.norm(map_points(probe, est) - map_points(probe, true), axis=1)
    assert err.max() < 1.5, (err, est)
    assert est["nmi_after"] > est["nmi_start"] and "mutual information" in est["method"]


def test_local_residual_finds_what_the_rigid_alignment_left():
    from muffle.workbench.radiology import local_residual, rigid_matrix

    vol = _phantom(spacing=(2.0, 2.0, 2.0), shape=(30, 30, 30))
    ident = {"matrix": rigid_matrix([0, 0, 0]), "center_mm": [0, 0, 0], "shift_mm": [0, 0, 0]}
    same = local_residual(vol, vol, (2.0,) * 3, (2.0,) * 3, ident, [30.0, 30.0, 30.0], 12.0)
    assert same["residual_mm"] == 0 and same["reliable"] and same["ncc_best"] > 0.99
    moved = np.roll(vol, 4, axis=1)  # 8 mm along Y, which the "alignment" missed
    off = local_residual(vol, moved, (2.0,) * 3, (2.0,) * 3, ident, [30.0, 30.0, 30.0], 12.0)
    assert off["shift_mm"] == [0.0, 8.0, 0.0] and not off["reliable"]
    assert "8 mm apart" in off["why"]
    air = local_residual(np.zeros_like(vol), vol, (2.0,) * 3, (2.0,) * 3, ident, [30.0] * 3)
    assert not air["reliable"] and air["residual_mm"] is None


def test_candidates_are_matched_across_dates_by_position_after_alignment():
    from muffle.workbench.radiology import match_candidates, rigid_matrix

    t = {"matrix": rigid_matrix([0, 0, 0]), "center_mm": [0, 0, 0], "shift_mm": [10, -5, 2]}
    earlier = [{"id": "C1", "centroid_mm": [60, 40, 80]},
               {"id": "C2", "centroid_mm": [20, 30, 150]},
               {"id": "C3", "centroid_mm": [90, 90, 90]}]
    later = [{"id": "C1", "centroid_mm": [12, 36, 146]},  # earlier C2 after the shift
             {"id": "C2", "centroid_mm": [52, 44, 77]},   # earlier C1, 2 mm off
             {"id": "C3", "centroid_mm": [0, 0, 0]}]      # nothing near it
    pairs = {(p["earlier"], p["later"]): p for p in match_candidates(earlier, later, t)}
    assert ("C1", "C2") in pairs and ("C2", "C1") in pairs
    assert pairs[("C1", "C2")]["distance_mm"] == pytest.approx(np.sqrt(6), abs=0.1)
    assert (None, "C3") in pairs and ("C3", None) in pairs
    # the local residual's shift moves a later candidate onto its partner
    near = match_candidates(earlier[:1], [{"id": "C9", "centroid_mm": [50, 45, 60]}], t,
                            {"C9": {"shift_mm": [0, 0, 18]}})
    assert near[0]["earlier"] == "C1" and near[0]["later"] == "C9"


def test_change_rules_and_the_computed_sum_are_never_a_response_call():
    from muffle.workbench.radiology import computed_sum, lesion_change

    def cand(ld, ml=1.0):
        return {"longest_diameter_mm": ld, "volume_ml": ml, "volume_range_ml": [ml * .8, ml * 1.2],
                "ld_uncertainty_mm": 0.9}

    assert lesion_change(cand(10), cand(16))["status"].startswith("grew")
    assert lesion_change(cand(20), cand(23))["status"].startswith("within")  # +15%, under 20%
    assert lesion_change(cand(20), cand(13))["status"].startswith("shrank")
    assert lesion_change(cand(4), cand(6))["status"].startswith("within")  # +50% but only 2 mm
    gone = lesion_change(cand(12), None)
    assert gone["status"] == "not proposed on the later date" and gone["ld_change_mm"] is None
    ch = lesion_change(cand(12, 1.0), cand(18, 2.5))
    assert ch["ld_change_mm"] == 6 and ch["ld_change_pct"] == 50 and not ch["volume_overlap"]
    rows = [{"earlier": e, "later": e, "change": lesion_change(cand(a), cand(b))}
            for e, a, b in (("C1", 12, 18), ("C2", 8, 9), ("C3", 15, 15), ("C4", 11, 30))]
    rows.append({"earlier": "C5", "later": None, "change": lesion_change(cand(25), None)})
    s = computed_sum(rows)
    assert s["targets"] == ["C3→C3", "C1→C1"] and s["sum_mm"] == [27, 33]  # two per organ
    assert s["change_pct"] == 22 and s["left_out"] == ["C5"]
    assert "not a RECIST response call" in s["note"]
    assert computed_sum(rows[1:2])["sum_mm"] is None  # nothing of 10 mm or more


def test_report_text_gets_the_same_change_view_without_sizes():
    from muffle.workbench.radiology import report_change

    reads = imaging_reads(EVENTS)
    ch = report_change(reads, 7, 12)
    rows = {r["lesion"]: r for r in ch["rows"]}
    assert rows["Liver"]["change"] == "first named on the later read"
    assert rows["Bone"]["change"].startswith("named before the earlier read")
    assert {r["measurements"] for r in ch["rows"]} == {NO_MEASUREMENTS}
    assert ch["sum"]["sum_mm"] is None and "no sum of diameters" in ch["what_changed"]
    assert all("stable" != r["later"] for r in ch["rows"])


def test_protocol_differences_come_before_any_larger_or_smaller():
    from muffle.workbench.radiology import protocol_differences

    def study(scanner, plane, times):
        return {"study": {"scanner": scanner, "field_t": 1.5, "contrast": "gad",
                          "sequence": {"tr_ms": 6.0, "te_ms": 3.0, "flip_deg": 10}},
                "display": {"acquisition": {"plane": plane, "slice_mm": 3.0, "pixel_mm": [0.9]}},
                "phases": [{"time_s": t} for t in times]}

    same = study("GE SIGNA", "sagittal", [0, 200])
    assert protocol_differences(same, same) == []
    diff = protocol_differences(same, study("GE SIGNA HDx", "sagittal", [0, 170]))
    assert diff[0] == "scanner: GE SIGNA → GE SIGNA HDx" and "not directly comparable" in diff[1]


def test_multiplanar_reslicing_keeps_millimetres_with_anisotropic_slices():
    from muffle.workbench.radiology import (aligned_view, anisotropy, candidate_mask,
                                            reslice, reslice_row, rigid_matrix)

    display = {"slices": 10, "slice_step": 1, "slice_mm": 3.0, "pixel_mm": 1.0, "rows": 20,
               "cols": 30}
    vol = np.zeros((10, 20, 30), np.uint8)
    vol[4, 7, 12] = 200
    sag = reslice(vol, "sagittal", 12, display, order=0)
    cor = reslice(vol, "coronal", 7, display, order=0)
    assert sag.shape == (28, 20) and cor.shape == (28, 30)  # 9 gaps × 3 mm + 1 rows of 1 mm
    row = reslice_row(4, display)
    assert row == 15 and sag[15, 7] == 200 and cor[15, 12] == 200  # anterior left, head up
    assert sag[27 - 9 * 3, 7] == 0 and reslice(vol, "axial", 4, display)[7, 12] == 200
    assert "3.0× longer along the body axis" in anisotropy(display)
    c = {"per_slice": {"4": {"contours": [[[10, 5], [14, 5], [14, 9], [10, 9]]]}}}
    m = candidate_mask(c, vol.shape)
    assert m[4, 7, 12] and not m[3].any() and 16 <= m[4].sum() <= 25
    ring = {"per_slice": {"2": {"contours": [[[2, 2], [12, 2], [12, 12], [2, 12]],
                                             [[5, 5], [9, 5], [9, 9], [5, 9]]]}}}
    assert not candidate_mask(ring, vol.shape)[2, 7, 7]  # the hole stays a hole
    ident = {"matrix": rigid_matrix([0, 0, 0]), "center_mm": [0, 0, 0], "shift_mm": [0, 0, 0]}
    assert (aligned_view(vol, display, display, ident, "axial", 4) == vol[4]).all()
    moved = {**ident, "shift_mm": [0, 2.0, 0]}  # the earlier study sits 2 mm further back
    assert aligned_view(vol, display, display, moved, "axial", 4)[5, 12] == 200


def test_mammography_outline_band_and_asymmetry_are_geometry_with_placeholders():
    from muffle.workbench.radiology import asymmetry, asymmetry_map, breast_outline, nipple_band

    yy, xx = np.mgrid[:200, :120]
    img = np.where(((yy - 100) / 90) ** 2 + (xx / 80) ** 2 <= 1, 120, 5).astype(np.uint8)
    o = breast_outline(img)
    assert o["chest"] == "left" and abs(o["nipple"][0] - 79) <= 2 and abs(o["nipple"][1] - 100) <= 2
    x0, x1 = nipple_band(o, depth_mm=20, half_mm=5, pixel_mm=0.5)
    assert (x0, x1) == (o["nipple"][0] - 50, o["nipple"][0] - 30)
    flipped = breast_outline(img[:, ::-1])
    assert flipped["chest"] == "right"
    assert nipple_band(flipped, 20, 5, 0.5)[0] > flipped["nipple"][0]
    views = [{"laterality": s, "view": v, "dense": {"dense_fraction": f}}
             for s, v, f in (("R", "CC", 0.40), ("L", "CC", 0.25), ("R", "MLO", 0.30),
                             ("L", "MLO", 0.28))]
    a = {x["view"]: x for x in asymmetry(views)}
    assert a["CC"]["asymmetric"] and a["CC"]["difference_points"] == 15
    assert not a["MLO"]["asymmetric"] and "placeholder" in a["CC"]["rule"]
    dense = img.copy()
    dense[60:140, 10:50] = 250  # dense on the right breast only
    m = asymmetry_map(dense, img[:, ::-1])
    assert m["right_only"] > 0.05 and m["left_only"] < 0.01
    assert CUTOFFS["asymmetry_points"][1] == "placeholder"


def _example_file():
    from types import SimpleNamespace

    from muffle.workbench.radiology import example_studies
    from muffle.workspace import case_file

    studies = example_studies()
    if not studies:
        pytest.skip("the example pair is not in this checkout")
    case = SimpleNamespace(index=0, mutations=None, layers=["clinical"], missing=[], stage=None,
                           age=None, percentile=50.0, group="intermediate", site="example")
    pf = case_file(case, None, imaging=studies)
    for t in pf.tests:
        if t.workbench == "imaging":
            t.details["root"] = "example"
    return pf


def test_the_example_pair_is_labeled_small_attributed_and_aligned():
    from muffle.workbench.radiology import EXAMPLE, load_pair, pair_change

    loaded = load_pair(EXAMPLE)
    if not loaded:
        pytest.skip("the example pair is not in this checkout")
    pair, earlier, later = loaded
    for s in (earlier, later):
        folder = Path(s["folder"])
        assert sum(p.stat().st_size for p in folder.iterdir()) < 5_000_000
        assert s["source"]["license"] == "CC BY 3.0" and "not a patient file" in s["example"]
        assert s["cohort_index"] is None and s["display"]["acquisition"]["plane"] == "sagittal"
        for key in ("pre", "early", "late", "sub", *s["shipped"]["between"]):
            assert (folder / f"{key}.jpg").exists(), key
    assert earlier["study"]["date"] < later["study"]["date"]
    assert all(b["barcode"] != earlier["barcode"] for v in load_index(RESULTS).values() for b in v)
    reg = pair["registration"]
    assert max(abs(a) for a in reg["angles_deg"]) < 15 and reg["nmi_after"] > reg["nmi_start"]
    ch = pair_change(pair, earlier, later)
    assert ch["label"] and ch["protocol"][0].startswith("scanner")  # EXCITE, then HDx
    assert ch["what_changed"].index("Before any") < ch["what_changed"].index("longest diameter")
    assert {r["evidence"] for r in ch["rows"]} == {"model inference"}
    assert "not a RECIST response call" in ch["what_changed"] or ch["sum"]["sum_mm"] is None
    assert all(b["half_mm"] == 15 and "reliable" in b for b in ch["blocks"])


def test_a_file_with_two_dates_reports_its_change_in_summary_and_queue():
    pf = _example_file()
    card = summary(pf)["cards"][0]
    assert card["what"] == "Imaging change" and card["trust"] == "weak"
    assert card["evidence"] == "model inference" and "placeholder" in card["threshold"]
    changes = [q for q in queue(pf) if " to " in q["key"].split("|")[3]]
    assert all(q["trust"] == "weak" and q["evidence"] == "model inference" for q in changes)
    assert all(q["threshold"].startswith("placeholder") for q in changes)
    assert all(q["consequence"] == 3 for q in changes if "grew" in q["what"])
    # a file with one date has no change item and says so in the Spot panel's words
    one = [q for q in queue(_example_file()) if " to " in q["key"].split("|")[3]]
    assert len(one) == len(changes)


def test_shipped_round_two_studies_open_every_phase_in_the_cine():
    index = load_index(RESULTS)
    mri = [s for v in index.values() for s in v if s["modality"] == "MR"]
    if not mri:
        pytest.skip("no processed studies in this checkout")
    for s in mri:
        study = load_study(RESULTS / s["folder"])
        if study["pipeline"]["version"] == "1":
            continue
        between = study["shipped"]["between"]
        assert len(between) == len(study["phases"]) - 3
        assert all((Path(study["folder"]) / f"{k}.jpg").exists() for k in between)
        assert study["display"]["acquisition"]["plane"] in ("axial", "sagittal", "coronal")


def test_the_mri_viewer_fits_an_800px_page_and_its_outlines_sit_on_the_slice():
    """QA round 2: the slice is drawn at most ``VIEW_PX`` wide (the page column is 468 px at
    800 px with the sidebar open), and the chart's plot is exactly the image (autosize pad, no
    padding), so the boxes and the measure line share the image's scale."""
    import sys

    sys.path.insert(0, str(ROOT / "app"))
    from workbenches import radiology as page

    index = load_index(RESULTS)
    mri = [s for v in index.values() for s in v if s["modality"] == "MR"]
    if not mri:
        pytest.skip("no processed studies in this checkout")
    for s in mri:
        study = load_study(RESULTS / s["folder"])
        d, cands = study["display"], study.get("candidates", [])
        w, h = d["cols"], d["rows"]
        assert page.VIEW_PX <= 468
        for c in [None] + cands[:1]:
            i = int(next(iter(c["per_slice"]))) if c else 0
            view = page.view_of(study, c, i, zoom=c is not None)
            x0, y0, vw, vh, k = view
            assert vw * k <= page.VIEW_PX + 1e-9 and vw * k == pytest.approx(w * min(2, 460 / w))
            img = page.overlay(np.zeros((h, w), np.uint8), cands, i, True, view)
            assert img.size == (int(vw * k), int(vh * k))
            spec = page.viewer_chart(img, cands, i, True, True, view).to_dict()
            assert spec["autosize"] == {"type": "pad"} and spec["padding"] == 0
            assert (spec["width"], spec["height"]) == (vw * k, vh * k)
