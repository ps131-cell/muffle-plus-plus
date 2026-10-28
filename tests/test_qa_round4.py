"""Regression tests for QA round 4 (docs/qa.md "Round 4") that no other module's tests hold."""

from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.filterwarnings("error")
APP = Path(__file__).resolve().parents[1] / "app"


# the ids Chromium gave the Methods page's headings (QA round 4 walk, Streamlit 1.66)
BROWSER_IDS = {
    "Nuclei (StarDist)": "nuclei-star-dist",
    "Lesion contours (MedSAM, breast MRI)": "lesion-contours-med-sam-breast-mri",
    "ctDNA monitor rules": "ct-dna-monitor-rules",
    "MSK-CHORD landmark models": "msk-chord-landmark-models",
    "Breast tissue head (pathology slides)": "breast-tissue-head-pathology-slides",
    "Mammography geometry (left-right, CC and MLO)": "mammography-geometry-left-right-cc-and-mlo",
    "Breast density, second opinion (MONAI, mammography)":
        "breast-density-second-opinion-monai-mammography",
    "Radiology: report reading, seed and kinetics rules":
        "radiology-report-reading-seed-and-kinetics-rules",
    "SOS alerts and their order": "sos-alerts-and-their-order",
    "Planned: infrared chemical imaging": "planned-infrared-chemical-imaging",
    "Across the files: search, similar patients, where a patient sits":
        "across-the-files-search-similar-patients-where-a-patient-sits",
    "Every placeholder in the app": "every-placeholder-in-the-app",
}


def test_every_methods_contents_link_names_the_id_the_browser_gives(monkeypatch):
    """R4-5: the contents' links to "Nuclei (StarDist)", "Lesion contours (MedSAM, …)" and "ctDNA
    monitor rules" led nowhere: Streamlit splits a heading's words at a case change."""
    monkeypatch.syspath_prepend(str(APP))
    import methods_page

    for title, want in BROWSER_IDS.items():
        assert methods_page.anchor(title) == want, title
    titles = [t for cards in methods_page.CONTENTS.values() for t in cards]
    assert {"Nuclei (StarDist)", "ctDNA monitor rules"} <= set(titles)


def test_a_click_on_any_cell_of_the_versions_table_opens_that_version(monkeypatch):
    """R4-4: "click a row to open the file as of that version", but a click on a cell selected
    the cell and nothing happened; only the row marker worked. A cell now picks its row."""
    monkeypatch.syspath_prepend(str(APP))
    import timeline_page as tp

    went = []
    monkeypatch.setattr(tp, "travel", lambda pf, k: went.append(k))
    shown = [15, 14, 13, 12]
    for sel, want in (({"rows": [], "cells": [(2, "What arrived")]}, 13),
                      ({"rows": [1], "cells": []}, 14), ({"rows": [], "cells": []}, None)):
        went.clear()
        monkeypatch.setattr(tp.st, "session_state", {"k": SimpleNamespace(selection=sel)})
        tp._row_picked(None, "k", shown)
        assert went == ([] if want is None else [want])


def test_the_theme_sheet_arrives_with_the_first_text(app):
    """R4-3: app/theme.css rides in the page's first Markdown element (drawn with the first
    text), not in st.html (a script chunk of its own: 1.5–4.6 s of Streamlit's default gutters
    on a first visit), and the element that carries it hides itself."""
    at = app.new().run()
    sheet = (APP / "theme.css").read_text(encoding="utf-8")
    style = next(m.value for m in at.markdown if m.value.startswith("<style>"))
    assert sheet in style and ":has(> [data-testid=\"stMarkdown\"] style)" in style
    assert "display: none" in style.rsplit("}", 2)[-2]
    assert not [h for h in at.html if "--mf-mono" in h.value]
    assert not at.exception
