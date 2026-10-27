"""The guide inside the app (docs/ux.md §4): "How to read this" behind the help icon on every
screen, a four-step walk-through the first time the Patients page opens in a browser session,
and a one-sentence glossary behind every status chip (``chip_row``: clicking "model
inference" says what it means)."""

from __future__ import annotations

import hashlib

import streamlit as st

from muffle.workbench.grammar import GLOSSARY, WORKBENCH_GUIDE, chip, glossary

SHORTCUTS = [  # the report's attention queue (docs/WORKBENCHES.md §2)
    ("j", "next item in the attention queue"),
    ("k", "previous item"),
    ("p", "pin or unpin the item"),
    ("m", "mark the item reviewed (Streamlit keeps r for its own rerun)"),
    ("u", "the unsure list: items marked second look, or of weak trust"),
    ("o", "open the item's evidence in its workbench"),
]
STEPS = [
    ("Your patients", "Begin with **Start here**: **Open the longitudinal example** "
     "(SYNTHETIC-001, a synthetic patient over 24 months) or **Open a case with its own slide "
     "and sequencing** (Case 299). Below, the patient list holds every file with its diagnosis, "
     "subtype, mutated genes, the workbenches that hold its data and its open SOS alerts: search "
     "it, sort it, click a row to open a file. Files you pin or open come back as buttons above "
     "the list."),
    ("A file opens on its latest report", "Under the views, the file's buttons: **Attention "
     "queue**, **Import a test**, **Compare versions**, **Export this report**, **Your marks**, "
     "**Pin this file** and **How to read this**. The report starts with finding cards (each "
     "card's **Open** lands on its evidence) and one attention queue, strongest first: "
     "**Next step** says what to do, and the keys j, k, p, m, u and o walk it."),
    ("Every test has its workbench", "**Tests** opens on a tile per test: **Open** (or a month) "
     "opens its workbench below, all laid out the same way: overview with the look-here list, "
     "the picture, details (collapsed, counted), the Spot panel, the model and validation card, "
     "what the test cannot see, export. **Timeline** lays the record out over time: click any "
     "point to open the file as it was then, compare any two versions."),
    ("Read the labels", "Every finding says whether it is **observed**, **model inference** "
     "or a **hypothesis**, how far to trust it, and where its threshold comes from; a "
     "placeholder is always orange. Click a label to see what it means; **How to read this** "
     "(or the **?**) on every screen opens this guide. Research and decision support, not a "
     "diagnosis or a prescription."),
]


def chip_row(*labels: str, colors: dict | None = None, key: str = "chips") -> None:
    """Status chips that explain themselves: each opens its one-sentence meaning on a click.
    The chip keeps its text and color (color is never the only signal)."""
    with st.container(horizontal=True, gap="xsmall", key=f"{key}-row"):
        for n, label in enumerate(x for x in labels if x):
            h = hashlib.sha1(f"{key}|{label}".encode()).hexdigest()[:8]
            with st.popover(chip(label, (colors or {}).get(label)), type="tertiary",
                            key=f"chip-{h}-{n}", help="What this label means"):
                st.markdown(glossary(label))


def how_to_read(screen: str | None = None) -> None:
    """The guide's panel: the labels, trust and placeholders; what the screen's workbench shows
    and cannot; the keyboard shortcuts."""
    st.markdown("**How to read this**")
    st.caption("Research and decision support for clinicians; not a diagnosis or a "
               "prescription.")
    labels, page, keys = st.tabs(["Labels", "This screen", "Keys"])
    with labels:
        for label in ("observed", "model inference", "hypothesis", "trust", "placeholder",
                      "implemented", "experimentally validated", "planned", "synthetic", "SOS"):
            st.markdown(f"{chip(label)} {GLOSSARY[label]}")
    with page:
        shows, cannot = WORKBENCH_GUIDE.get(screen or "", WORKBENCH_GUIDE["patients"])
        st.markdown(f"**What it shows:** {shows}")
        st.markdown(f"**What it cannot see:** {cannot}")
        st.caption("Every workbench page has the same parts in the same order: overview with "
                   "the look-here list, the picture, details (collapsed, each with its count), "
                   "the Spot panel, the model and validation card, what the test cannot see, "
                   "export.")
    with keys:
        st.markdown("\n".join(f"- `{k}` {what}" for k, what in SHORTCUTS))
        st.caption("Keys work while the report's attention queue is on screen. Tab moves "
                   "through the queue's buttons in order: previous, next, pin, mark reviewed, "
                   "unsure list, open.")


def help_icon(screen: str | None = None, label: str = "?") -> None:
    """The help icon every screen carries, opening "How to read this" (``label`` "?"; the
    file's action row draws it as a button named so). Its content runs only while it is open
    (about half a rerun's time on a shared CPU otherwise)."""
    icon = label == "?"
    with st.popover(label, type="tertiary" if icon else "secondary",
                    icon=None if icon else ":material/menu_book:",
                    key=f"{'help' if icon else 'guide'}-{screen or 'screen'}", on_change="rerun",
                    help="How to read this screen: labels, trust, placeholders, keys") as pop:
        if pop.open:
            how_to_read(screen)


def walkthrough() -> None:
    """Four short steps on the Patients page the first time it opens in a browser session;
    dismissed (or finished) it stays away for the session."""
    ss = st.session_state
    if ss.get("walkthrough_done"):
        return
    step = ss.setdefault("walkthrough_step", 0)
    title, text = STEPS[step]
    with st.container(border=True, key="walkthrough"):
        st.markdown(f"**First time here? {step + 1} of {len(STEPS)} · {title}**")
        st.markdown(text)
        with st.container(horizontal=True, gap="small"):
            st.button("Back", key="walk-back", disabled=step == 0,
                      on_click=lambda: ss.update(walkthrough_step=step - 1))
            if step < len(STEPS) - 1:
                st.button("Next", key="walk-next",
                          on_click=lambda: ss.update(walkthrough_step=step + 1))
            else:
                st.button("Start", key="walk-done",
                          on_click=lambda: ss.update(walkthrough_done=True))
            st.button("Skip the tour", key="walk-skip", type="tertiary",
                      on_click=lambda: ss.update(walkthrough_done=True))
