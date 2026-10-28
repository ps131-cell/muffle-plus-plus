"""Regression tests for QA round 4 (docs/qa.md "Round 4") that no other module's tests hold."""

from pathlib import Path

import pytest

pytestmark = pytest.mark.filterwarnings("error")
APP = Path(__file__).resolve().parents[1] / "app"


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
