"""The pathology slide page on a patient's own scored section (app/workbenches/slides_results)."""

import importlib.util
import json
from pathlib import Path

import pandas as pd

from muffle.workbench import invasion as inv

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "app" / "workbenches" / "slides_results"


def first_case():
    index = RESULTS / "cases.json"
    if not index.exists():
        return None, []
    cases = json.loads(index.read_text())
    for idx, names in cases.items():
        names = [n for n in names if (RESULTS / n / "summary.json").exists()]
        if names:
            return idx, names
    return None, []


def shipped_sections() -> list[str]:
    index = RESULTS / "cases.json"
    if not index.exists():
        return []
    return [n for names in json.loads(index.read_text()).values() for n in names
            if (RESULTS / n / "summary.json").exists()]


def test_results_hold_only_derived_numbers_and_small_crops():
    for name in shipped_sections():
        folder = RESULTS / name
        size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        assert size < 3e6, (name, size)
        crops = list((folder / "crops").glob("*.jpg"))
        assert len(crops) <= 60
        tiles = pd.read_json(folder / "tiles.json", orient="split")
        assert {"row", "col", "qc"} <= set(tiles.columns)
        assert not any(c.startswith("emb") for c in tiles.columns)
        meta = json.loads((folder / "summary.json").read_text())
        assert meta["slide"] == name and meta["head"]["classes"]
        assert "not validated on breast" in meta["status"] or "pretrained" in meta["status"]
        assert meta["scored"]["scored_tiles"] + meta["scored"]["skipped_tiles"] == \
            meta["scored"]["tissue_tiles_total"]
        res = inv.analyze_slide(tiles, meta["head"]["classes"])
        assert res["summary"]["usable_tiles"] > 0


def test_every_section_and_the_example_read_one_open_encoder():
    """Never a mix: every shipped section and the example region come from one encoder, an
    open-license one, under the head trained on its embeddings (one held-out accuracy)."""
    spec = importlib.util.spec_from_file_location("slide_spike",
                                                  ROOT / "scripts" / "slide_spike.py")
    spike = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(spike)
    metas = [json.loads((RESULTS / n / "summary.json").read_text()) for n in shipped_sections()]
    example = RESULTS.parent / "slides_example" / "summary.json"
    if example.exists():
        metas.append(json.loads(example.read_text()))
    if not metas:
        return
    assert len({m["encoder"]["name"] for m in metas}) == 1
    assert len({(m["head"]["accuracy"], m["head"]["balanced_accuracy"]) for m in metas}) == 1
    enc = spike.ENCODERS[metas[0]["encoder"]["name"]]
    assert not enc["local_only"] and metas[0]["encoder"]["license"] == enc["license"]
    assert {"name", "license", "access", "kind", "tiles_per_s_cpu"} <= set(metas[0]["encoder"])


def test_stored_numbers_are_what_the_page_computes():
    """The summary's headline numbers (the comparison of sections reads them) agree with the
    analysis the page runs on the shipped tiles and nuclei counts, up to the rounding of the
    shipped probabilities (3 decimals; the pipeline analyses 4): 1% on areas and lengths, one
    on counts."""
    for name in shipped_sections():
        folder = RESULTS / name
        meta = json.loads((folder / "summary.json").read_text())
        tiles = pd.read_json(folder / "tiles.json", orient="split")
        nuc = json.loads((folder / "nuclei.json").read_text())
        if nuc.get("tiles") and nuc["tiles"].get("data"):
            summ = pd.DataFrame(nuc["tiles"]["data"], columns=nuc["tiles"]["columns"])
            tiles = tiles.merge(summ, on=["row", "col"], how="left")
        got = inv.analyze_slide(tiles, meta["head"]["classes"])["numbers"]
        want = meta["numbers"]
        for key in ("tumor_mm2", "front_length_mm"):
            assert abs(got[key] - want[key]) <= 0.01 * max(want[key], 1), (name, key)
        for key in ("arcs", "islands", "counted_tiles"):
            assert abs(got[key] - want[key]) <= 1, (name, key)
        assert got["immune_pattern"] == want["immune_pattern"], name


def test_slides_page_renders_the_patients_own_section():
    from streamlit.testing.v1 import AppTest

    idx, names = first_case()
    if idx is None:
        return
    at = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from types import SimpleNamespace
from workbenches.slides import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index={idx}, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None), slides={names!r}))
""", default_timeout=180).run()
    assert not at.exception, at.exception
    text = " ".join([*(e.value for e in [*at.markdown, *at.caption, *at.info, *at.warning]),
                     *(e.label for e in at.expander)]).lower()
    assert "the patient's own" in text and "2d snapshot" in text
    assert "weak until validated" in text and "placeholder" in text
    assert "what this test cannot see" in text and "not reviewed by a pathologist" in text
    assert "known failures" in text and "0.785" in text
    assert not any(w in text for w in ("demo", "hackathon"))
    labels = [b.label for b in at.get("download_button")]
    assert any("JSON" in lab for lab in labels) and any("PNG" in lab for lab in labels)
    if len(names) > 1:
        assert "the sections compared" in text
    if (RESULTS / names[0] / "til.json").exists():  # the second lymphocyte model scored it
        assert "second opinion" in text and "disagree" in text and "auroc" in text


def test_a_scored_case_opens_its_own_section_through_the_shell(app, monkeypatch):
    """The app shell gives a case with scored sections a pathology slide test, which opens the
    workbench on that section with the encoder and the head's held-out accuracy it was made with
    (the test cohort's first case stands in for the scored case)."""
    from tests.appfixture import shown

    names = shipped_sections()
    if not names:
        return
    meta = json.loads((RESULTS / names[0] / "summary.json").read_text())
    index = json.dumps({str(app.demo.cases[0].index): names[:1]})
    real = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: index if (
        self.name == "cases.json" and self.parent.name == "slides_results") else
        real(self, *a, **k))
    at = app.new().run()
    at.selectbox(key="patient").select(app.case).run()
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state[f"picked-{app.case}"] = ("Pathology slide", None,
                                              "Diagnostic H&E section(s) (GDC, open access)")
    at.run()
    assert not at.exception, at.exception
    text = shown(at)
    assert "Pathology slide workbench" in text and meta["slide"] in text
    assert meta["encoder"]["name"] in text and f"{meta['head']['accuracy']:.1%}" in text


def test_unlike_training_tissue_is_a_calibrated_exclusion_recorded_per_section():
    """Tiles unlike every tile the head was trained on are a quality exclusion: each section
    records the calibrated cutoff (the one on the page's cutoff table) and how many tiles it
    took out; the section checked by eye carries its known failure."""
    from muffle.workbench.slides import CUTOFFS, QC_UNLIKE

    for name in shipped_sections():
        meta = json.loads((RESULTS / name / "summary.json").read_text())
        nov = meta.get("novelty")
        assert nov and nov["cutoff"] == CUTOFFS["unlike_training_cosine"][0], name
        assert nov["encoder"] == meta["encoder"]["name"] and nov["held_out_flagged"] < 0.01
        tiles = pd.read_json(RESULTS / name / "tiles.json", orient="split")
        assert int((tiles["qc"] == QC_UNLIKE).sum()) == nov["excluded_tiles"], name
        if name == "TCGA-EW-A1J2-DX1":
            assert any("check" in f and "margin" in f for f in meta["known_failures"])


def test_novelty_distance_is_small_near_the_training_tiles_and_large_away():
    import numpy as np

    spec = importlib.util.spec_from_file_location("slide_pipeline",
                                                  ROOT / "scripts" / "slide_pipeline.py")
    pipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipe)
    rng = np.random.default_rng(0)
    ref = np.eye(8)[0] + 0.05 * rng.normal(size=(40, 8))
    ref /= np.linalg.norm(ref, axis=1, keepdims=True)
    near = np.eye(8)[0] + 0.05 * rng.normal(size=(3, 8))
    d = pipe.novelty_distance(np.vstack([near, 3 * np.eye(8)[1:4]]), ref, 5)
    assert (d[:3] < 0.05).all() and (d[3:] > 0.8).all()
