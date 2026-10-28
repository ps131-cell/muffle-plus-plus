"""Where the clinician is and the way back (docs/ux.md §3): breadcrumbs on every screen, the
patient file's sticky header, "back to the report" and "back to the queue" after an "Open",
deep links that reopen a screen, and the recently opened files.

Deep links: Streamlit binds ?patient and ?view to their widgets (``bind="query-params"``); the
shell writes ?test (the test open in the Tests view, ``test_id``), ?pointer (the finding an
"Open" or a look-here "Spot" landed on) and ?version (a report version that isn't the latest)
after each run with ``sync``, and reads them once per new address with ``fresh``, so a link or
a screenshot's address reopens the same screen with the pointer in the Spot panel.
"""

from __future__ import annotations

import streamlit as st

SEP = "›"
RECENT = 5  # files kept in the recently opened list
LINK_KEYS = ("test", "pointer", "version")
PAGES: dict = {}  # the app's pages by address ("methods"), set by the shell for page links


# --- breadcrumbs -------------------------------------------------------------------------------

def crumbs(parts: list[tuple[str, object]], extra=None) -> None:
    """One line "Patients › Case 299 › Tests › Pathology slide": every part but the last is a
    button (``(label, on_click)``; None for plain text); ``extra`` draws at the line's end (the
    guide's help icon)."""
    with st.container(horizontal=True, gap="xsmall", vertical_alignment="center",
                      key="crumbs"):
        for n, (label, go) in enumerate(parts):
            if n:
                st.markdown(SEP, width="content")
            if go is None or n == len(parts) - 1:
                st.markdown(f"**{label}**", width="content")
            else:
                st.button(label, type="tertiary", key=f"crumb-{n}", on_click=go,
                          help=f"Back to {label}")
        if extra is not None:
            st.space("stretch")
            extra()


# --- the patient file's sticky header ---------------------------------------------------------

STICKY_CSS = """<style>
.st-key-patient-header {
  background-color: Canvas;  /* without :has(): the browser's page colour for the app's scheme */
  padding: 0.25rem 0 0.5rem 0; gap: 0.25rem;
  border-bottom: 1px solid rgba(128, 128, 128, 0.3);
}
@supports selector(:has(a)) {
  [data-testid="stApp"] :has(.st-key-patient-header), .st-key-patient-header {
    background-color: inherit;
  }
  @media (min-width: 1024px) {
    .st-key-patient-header, [data-testid="stLayoutWrapper"]:has(> .st-key-patient-header) {
      position: sticky; top: 3.75rem; z-index: 99;
    }
    [data-testid="stLayoutWrapper"]:has(> .st-key-patient-header)::before {
      content: ""; position: absolute; left: 0; right: 0; bottom: 100%; height: 3.75rem;
      background-color: inherit;  /* covers the page under Streamlit's transparent toolbar */
    }
  }
}
.st-key-file-actions [data-testid="stPageLink-NavLink"] {  /* a link among buttons, framed so */
  border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 0.25rem; padding: 0 0.5rem;
  min-height: 1.875rem; display: flex; align-items: center;
}
</style>"""


def sticky_css() -> None:
    """The patient header stays at the top while the page scrolls, below Streamlit's toolbar
    (``st.container`` with key "patient-header" is the element the CSS class
    ``st-key-patient-header`` names). Streamlit 1.66 wraps it in a ``stLayoutWrapper`` of its
    own height, so the wrapper is what sticks, with the strip above it (under Streamlit's
    transparent toolbar) painted too; in a window under 1024 px (a tablet, a phone, a narrow
    browser beside another) the header scrolls away with the page: wrapped onto more lines
    there, it would cover a quarter of the screen. Its background is the app's own,
    light or dark, in CSS: every element between Streamlit's app root (which paints the theme's
    background and sets ``color-scheme``) and the header inherits it, so a change of theme in
    the settings menu needs no rerun, and the text keeps the theme's colour.
    ``st.context.theme`` is not used: Streamlit says it can be wrong on a session's first load
    and after a theme change. A style-only ``st.html`` takes no space on the page."""
    st.html(STICKY_CSS)


# --- deep links --------------------------------------------------------------------------------

GENERIC = {"Lab", "Data layer", "Document", "Clinical record"}  # kinds named by the test instead


def test_key(kind: str, month, name: str) -> str:
    """A test's address: "Lab|11|CA 15-3"; an undated test has an empty month ("Data
    layer||RNA-seq (STAR TPM)")."""
    return f"{kind}|{'' if month is None else month}|{name}"


def test_id(t) -> str:
    return test_key(t.kind, t.month, t.name)


def crumb(t) -> str:
    """The test's breadcrumb: its kind ("Pathology slide"), or its name where the kind says
    little ("CA 15-3"), with its month when it has one."""
    return (t.name if t.kind in GENERIC else t.kind) + ("" if t.month is None else
                                                         f", month {t.month}")


def parse_test_id(text: str | None) -> tuple | None:
    """``test_id``'s (kind, month, name), or None for an address that isn't one."""
    parts = (text or "").split("|", 2)
    if len(parts) != 3:
        return None
    kind, month, name = parts
    try:
        return kind, (int(month) if month.strip() else None), name
    except ValueError:
        return None


def link_state(pid: str) -> tuple:
    """The address as this run sees it: the patient and the unbound parameters."""
    q = st.query_params
    return (pid, *(q.get(k) for k in LINK_KEYS))


def fresh(pid: str) -> dict | None:
    """The unbound parameters of an address this session has not applied yet (a link opened,
    a URL typed or pasted), else None: they are applied once, then the reader moves freely.
    When the reader switched files in this session, the previous file's parameters are stale:
    nothing is applied, and the new file opens on its latest report."""
    state = link_state(pid)
    before = st.session_state.get("_link")
    if before == state:
        return None
    st.session_state["_link"] = state
    if before is not None and before[0] != pid:
        return {k: None for k in LINK_KEYS}
    return dict(zip(LINK_KEYS, state[1:], strict=True))


def sync(pid: str, test: str | None, pointer: str | None, version: int | None) -> None:
    """Write the screen's unbound parameters (None removes one) and remember them as applied,
    so the next run doesn't take its own address for a new link."""
    q = st.query_params
    for k, v in zip(LINK_KEYS, (test, pointer, None if version is None else str(version)),
                    strict=True):
        if v is None:
            if k in q:
                del q[k]
        elif q.get(k) != v:
            q[k] = v
    st.session_state["_link"] = link_state(pid)


def set_pointer(pointer: str | None) -> None:
    """An "Open" or a look-here "Spot" landed on ``pointer``: the address carries it."""
    st.session_state["_pointer"] = pointer


# --- recently opened files ----------------------------------------------------------------------

def remember(pid: str) -> None:
    """A file was opened: it goes first in the recently opened list (this browser session)."""
    recent = st.session_state.setdefault("recent", [])
    if recent[:1] != [pid]:
        if pid in recent:
            recent.remove(pid)
        recent.insert(0, pid)
        del recent[RECENT:]
