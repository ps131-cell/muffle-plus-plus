"""Pathology slide workbench, round 2: the invasion geometry, nuclei counting, counting field,
risk map, queue, search and comparison on hand-made grids."""

import numpy as np
import pandas as pd

from muffle.workbench import invasion as inv
from muffle.workbench.slides import CLASSES, PLACEHOLDER


def fake_tiles(h=30, w=30) -> pd.DataFrame:
    """A 30×30 region: a tumor disk of radius 6 at (15, 15) with a one-tile finger to the right
    (rows 14–15, cols 22–25), a 3×3 satellite at rows 3–5, cols 24–26, necrosis in the disk's
    centre, a lymphocyte band at cols 7–9 beside the tumor, fat on the right half (col ≥ 20),
    stroma elsewhere."""
    rows = []
    for r in range(h):
        for c in range(w):
            p = {k: 0.02 for k in CLASSES}
            d = np.hypot(r - 15, c - 15)
            if d <= 6 or (14 <= r <= 15 and 22 <= c <= 25) or (3 <= r <= 5 and 24 <= c <= 26):
                p["tumor"] = 0.9
            elif np.hypot(r - 15, c - 15) <= 1:
                p["necrosis"] = 0.9
            elif 7 <= c <= 9 and 10 <= r <= 20:
                p["lymphocytes"] = 0.9
            elif c >= 20:
                p["fat"] = 0.9
            else:
                p["stroma"] = 0.9
            if np.hypot(r - 15, c - 15) <= 1:
                p = {k: 0.02 for k in CLASSES}
                p["necrosis"] = 0.9
            rows.append({"row": r, "col": c, "x": c * 448, "y": r * 448, "edges": 0.1,
                         "structure_cov": 0.9, "ink_bluegreen": 0.0, "ink_black": 0.0,
                         "ink_red": 0.0, "blur": 0.01, **{f"p_{k}": v for k, v in p.items()}})
    return pd.DataFrame(rows)


def test_front_normals_point_outward_and_push_reads_the_tissue_beyond():
    res = inv.analyze_slide(fake_tiles())
    n = res["normals"].set_index(["row", "col"])
    right = n.loc[(15, n.reset_index().query("row == 15")["col"].max())]
    assert abs(((right["angle"] - 0) + 180) % 360 - 180) < 30          # points right
    top_row = n.reset_index().query("col == 15")["row"].min()
    assert abs(((n.loc[(top_row, 15), "angle"] - 90) + 180) % 360 - 180) < 30  # points up
    assert (n["push"] >= 0).all() and (n["push"] <= 1).all()
    assert len(n) == int(res["tiles"]["front"].sum())


def test_fingers_and_arcs_name_the_protrusion_and_what_each_arc_faces():
    res = inv.analyze_slide(fake_tiles())
    t = res["tiles"].set_index(["row", "col"])
    assert res["fingers"]["judged"] and res["fingers"]["n"] >= 1
    assert t.loc[(15, 24), "finger"] and not t.loc[(15, 15), "finger"]
    arcs = res["arcs"]
    assert 1 <= len(arcs) <= 12 and [a["arc"] for a in arcs] == [f"A{i + 1}" for i in
                                                                  range(len(arcs))]
    east = [a for a in arcs if a["from_deg"] in (0, 330)]
    assert any(a["pattern"] == "infiltrative" for a in east)
    assert any(a["faces_top"] == "fat" for a in east)
    west = [a for a in arcs if 150 <= a["from_deg"] < 210]
    assert any(a["faces_top"] == "lymphocytes" for a in west)
    assert all(0 <= a["direction_deg"] < 360 and a["length_mm"] > 0 for a in arcs)
    r = res["rose"]
    assert len(r) == 12 and sum(b["tiles"] for b in r) == len(res["normals"])
    assert inv.compass(0) == "right" and inv.compass(90) == "up" and inv.compass(200) == "left"
    tiny = np.zeros((10, 10), bool)
    tiny[5, 5:7] = True
    assert not inv.fingers(tiny)["judged"]


def test_satellite_island_has_a_distance_and_the_tissue_between():
    res = inv.analyze_slide(fake_tiles())
    isl = res["islands"]
    assert len(isl) == 1 and isl[0]["island"] == "S1"
    assert isl[0]["distance_um"] > 0 and isl[0]["tiles"] >= 5  # 3×3 loses corners to smoothing
    assert isl[0]["between"] in ("fat", "stroma") and sum(isl[0]["between_shares"].values()) > 0.9
    assert res["summary"]["satellite_pieces"] == 1


def nuclei_for(tiles: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Nuclei on three tiles: (15, 18) inside the tumor with tumor nuclei and two lymphocytes,
    one 30 µm away and one 80 µm away; (15, 27) outside the mask in fat with raw P(tumor)
    0.4 holding a 3-nucleus cluster (a bud) and a 6-nucleus nest; (2, 2) stroma, empty."""
    tiles.loc[(tiles.row == 15) & (tiles.col == 27), "p_tumor"] = 0.4
    tiles.loc[(tiles.row == 15) & (tiles.col == 27), "p_fat"] = 0.5
    recs = []
    for i in range(8):  # tumor nuclei, 80 µm² each, spread out
        recs.append((15, 18, 10 + i * 12, 50, 80.0, 0.95))
    recs.append((15, 18, 10, 80, 30.0, 0.95))    # lymphocyte 30 µm from the first tumor nucleus
    recs.append((15, 18, 100, 100, 30.0, 0.95))  # lymphocyte 80 µm from the nearest tumor nucleus
    for i in range(3):  # a bud: 3 nuclei within 10 µm
        recs.append((15, 27, 20 + i * 8, 20, 70.0, 0.9))
    recs.append((15, 27, 60, 60, 20.0, 0.7))  # a small spindle nucleus: not a candidate
    for i in range(6):  # a nest of 6, 60 µm away
        recs.append((15, 27, 80 + i * 8, 90, 70.0, 0.9))
    nuclei = pd.DataFrame(recs, columns=["row", "col", "x_um", "y_um", "area_um2", "solidity"])
    ran = pd.DataFrame({"row": [15, 15, 2], "col": [18, 27, 2]})
    return nuclei, ran


def test_nuclei_summary_counts_lymphocytes_near_tumor_and_breakaway_clusters():
    tiles = fake_tiles()
    nuclei, ran = nuclei_for(tiles)
    base = inv.analyze(tiles)["tiles"]
    s = inv.nuclei_summary(nuclei, base, ran).set_index(["row", "col"])
    core = s.loc[(15, 18)]
    assert (core["n_nuclei"], core["n_lymph"], core["n_tumor_nuc"]) == (10, 2, 8)
    assert s.loc[(15, 27), "n_nuclei"] == 10
    assert core["n_lymph_near_tumor"] == 1 and core["buds"] == 0
    assert np.isclose(core["nuc_area_cv"], 0.0)
    out = s.loc[(15, 27)]
    assert out["buds"] == 1 and out["n_tumor_nuc"] == 0  # 0.4 < 0.5: not tumor candidates
    assert s.loc[(2, 2), "n_nuclei"] == 0 and np.isnan(s.loc[(2, 2), "nuc_area_cv"])
    assert inv.clusters(np.zeros((0, 2))).size == 0
    lab = inv.clusters(np.array([[0, 0], [5, 0], [100, 100]]))
    assert lab[0] == lab[1] != lab[2]


def test_counting_field_sits_on_the_densest_counted_tile_and_reports_coverage():
    tiles = fake_tiles()
    nuclei, ran = nuclei_for(tiles)
    t = inv.analyze(tiles)["tiles"]
    summ = inv.nuclei_summary(nuclei, t, ran)
    merged = t.merge(summ, on=["row", "col"], how="left")
    hs = inv.hotspot_field(merged)
    assert hs["buds_in_field"] == 1 and (hs["row"], hs["col"]) == (15, 27)
    assert 0 < hs["coverage"] < 0.1 and hs["field_mm2"] == 0.785
    assert inv.hotspot_field(t) is None
    assert abs(inv.FIELD_RADIUS_TILES - 4.46) < 0.01


def test_immune_tsr_necrosis_and_risk_map_with_placeholder_points():
    tiles = fake_tiles()
    nuclei, ran = nuclei_for(tiles)
    res = inv.analyze_slide(tiles.merge(
        inv.nuclei_summary(nuclei, inv.analyze(tiles)["tiles"], ran), on=["row", "col"],
        how="left"))
    im = res["immune"]
    assert set(im["zones"]) == {"core", "front band", "peritumoral"}
    assert im["pattern"] in ("desert", "excluded", "inflamed") or "no core" in im["pattern"]
    assert im["zones"]["front band"]["lymph_tile_share"] > 0
    assert res["tsr"]["verdict"] in ("stroma-high", "stroma-low")
    assert res["necrosis"]["necrosis_tiles"] >= 1 and res["necrosis"]["share_touching"] == 1.0
    risk = res["risk"]
    assert all(r["source"] == PLACEHOLDER for r in risk["table"])
    assert risk["points"].max() >= 3 and risk["cards"]
    assert risk["cards"][0]["card"] == "R1" and risk["cards"][0]["level"] >= 2
    assert "breakaway candidates" in risk["cards"][0]["features"] or \
        "infiltrative arc" in risk["cards"][0]["features"]
    t = res["tiles"]
    assert t["risk_level"].max() >= 2 and (t["risk_points"] >= 0).all()
    assert res["numbers"]["counted_tiles"] == 3 and res["numbers"]["buds_in_field"] == 1


def test_queue_pointers_search_and_comparison():
    tiles = fake_tiles()
    nuclei, ran = nuclei_for(tiles)
    res = inv.analyze_slide(tiles.merge(
        inv.nuclei_summary(nuclei, inv.analyze(tiles)["tiles"], ran), on=["row", "col"],
        how="left"))
    q = res["queue"]
    assert [p["pointer"] for p in q] == [f"T{i + 1}" for i in range(len(q))]
    assert any(p["kind"] == "hotspot" for p in q) and any(p["kind"] == "island" for p in q)
    assert all(p["check"] and p["evidence"] and p["status"] for p in q)
    hit = inv.search("budding", res)
    assert hit["understood"] and len(hit["rows"]) == 1
    hit = inv.search("lymphocytes at the border", res)
    assert hit["understood"] and (hit["rows"]["zone"] == "front band").all() \
        and (hit["rows"]["label"] == "lymphocytes").all()
    cant = inv.search("nottingham grade", res)
    assert not cant["understood"] and "can't see" in cant["answer"]
    assert inv.search("T1", res)["pointer"] == "T1"
    assert "arcs read infiltrative" in inv.search("direction of invasion", res)["answer"]
    assert not inv.search("zebra", res)["understood"]
    a = {**res["numbers"], "slide": "DX1"}
    b = {**res["numbers"], "slide": "DX2", "tumor_mm2": res["numbers"]["tumor_mm2"] * 2,
         "immune_pattern": "desert"}
    rows = inv.compare(a, b)
    by = {r["measure"]: r["differs"] for r in rows}
    assert by["Tumor area in the map (mm²)"] == "yes" and by["Immune pattern"] == "yes"
    assert by["Front length (mm)"] == "no"
    from muffle.workbench import slide_export, tile_map  # the map picture, no scan behind it
    from muffle.workbench.slides import CLASSES

    data = tile_map.build(res["tiles"], CLASSES, res["grid_shape"])
    png = slide_export.map_png(None, data, "zones", title="fake section",
                               legend=tile_map.legend_items(data, "zones", res))
    assert png[:4] == b"\x89PNG"


def test_every_cutoff_names_a_source_and_the_literature_ones_cite():
    tags = {tag for _, tag, _ in inv.CUTOFFS.values()}
    assert tags <= {PLACEHOLDER, "literature", "measured", "design"}
    for k, (_, tag, note) in inv.CUTOFFS.items():
        if tag == "literature":
            assert any(w in note for w in ("et al.", "ITBCC")), k
    assert inv.CUTOFFS["bud_max_nuclei"][0] == 4 and inv.CUTOFFS["field_mm2"][0] == 0.785
    assert sum(inv.RISK_POINTS.values()) == 8
    assert len(inv.CANNOT_SEE) >= 5 and all(how for _, _, how in inv.CANNOT_SEE)
    assert "not validated on breast" in inv.MODEL_CARD["nuclei"]


def test_a_slide_without_a_tumor_still_analyzes():
    t = fake_tiles()
    for k in CLASSES:
        t[f"p_{k}"] = 0.02
    t["p_stroma"] = 0.9
    res = inv.analyze_slide(t)
    assert res["arcs"] == [] and res["islands"] == [] and res["hotspot"] is None
    assert res["risk"]["cards"] == [] and res["numbers"]["front_length_mm"] == 0.0
    assert res["immune"]["pattern"] == "no front: not assessed"
    assert not inv.search("T1", res)["understood"]


def test_second_lymphocyte_model_disagreement_feeds_zones_queue_search_and_compare():
    tiles = fake_tiles()
    base = inv.analyze_slide(tiles)["tiles"]
    # the second model scores the front band: it sees lymphocytes where the head says stroma
    # on three tiles, misses two of the head's lymphocyte tiles, and agrees elsewhere
    scored = base[base["zone"] == "front band"].copy()
    p = np.where(scored["label"] == "lymphocytes", 0.9, 0.1).astype(float)
    stroma_idx = np.flatnonzero((scored["label"] == "stroma").to_numpy())[:3]
    lymph_idx = np.flatnonzero((scored["label"] == "lymphocytes").to_numpy())[:2]
    p[stroma_idx], p[lymph_idx] = 0.95, 0.05
    scored["p_til"] = p
    with_til = tiles.merge(scored[["row", "col", "p_til"]], on=["row", "col"], how="left")
    res = inv.analyze_slide(with_til, til_cutoff=0.5, til_calibrated=True)
    d = res["til"]
    assert d["scored"] == len(scored) and d["disagree"] == 5
    assert d["head_only"] == 2 and d["til_only"] == 3 and 0 < d["kappa"] < 1
    assert res["numbers"]["til_disagree_share"] == round(5 / len(scored), 3)
    t = res["tiles"]
    assert t["disagree"].sum() == 5 and t["til_lymph"].notna().sum() == len(scored)
    assert t.loc[t["p_til"].isna(), "disagree"].eq(False).all()
    band = res["immune"]["zones"]["front band"]
    assert band["til_scored_tiles"] == len(scored) and 0 < band["til_lymph_share"] < 1
    assert "til_scored_tiles" not in res["immune"]["zones"]["peritumoral"] or \
        res["immune"]["zones"]["peritumoral"]["til_scored_tiles"] == 0
    q = [p for p in res["queue"] if p["kind"] == "disagree"]
    assert len(q) == 1 and "5 of" in q[0]["what"] and "calibrated" in q[0]["status"]
    assert t[(t.row == q[0]["row"]) & (t.col == q[0]["col"])]["disagree"].item()
    hit = inv.search("where do the models disagree", res)
    assert hit["understood"] and len(hit["rows"]) == 5
    rows = inv.compare({**res["numbers"], "slide": "a"},
                       {**res["numbers"], "slide": "b", "til_disagree_share": 0.9})
    assert {r["measure"]: r["differs"] for r in rows}[
        "Models disagree on lymphocytes (share of scored tiles)"] == "yes"
    # without the second model nothing changes
    plain = inv.analyze_slide(tiles)
    assert plain["til"]["scored"] == 0 and plain["numbers"]["til_disagree_share"] is None
    assert not any(p["kind"] == "disagree" for p in plain["queue"])
    assert not inv.search("disagree", plain)["understood"]
    # a placeholder cutoff when none is given
    fallback = inv.analyze_slide(with_til)
    assert fallback["til"]["cutoff"] == inv.CUTOFFS["til_cutoff_fallback"][0]
    assert "placeholder" in next(p for p in fallback["queue"] if p["kind"] == "disagree")["status"]
