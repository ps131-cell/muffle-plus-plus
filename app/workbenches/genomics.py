"""Genomics (tumor sequencing) workbench page for one patient file.

The workspace pages call ``render(file, events=None, evidence=None, version=None)`` with a
``muffle.workspace.PatientFile``; ``evidence`` maps "GENE CHANGE" to CIViC items (the
``civic.evidence`` results), ``version`` is an index into ``file.versions`` (the variants known
as of that version's month; the latest when None), ``lookup`` an optional
``(gene, change) -> items`` callable. ``render`` draws inside the current container only: no
page config, no sidebar. Standalone page, with two example files (the synthetic patient and one
TCGA case):

    streamlit run app/workbenches/genomics.py

Everything shown is observed (a sequenced mutation) or a hypothesis (a CIViC item, for clinician
review, never a recommendation); planned parts are shown as planned rows, never as results.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report.civic import LEVELS  # noqa: E402
from muffle.workbench import genomics as wb  # noqa: E402

COLORS = {wb.IMPLEMENTED: "green", wb.PLANNED: "gray", "observed": "blue", "hypothesis": "orange",
          wb.FOUND: "blue", wb.NOT_FOUND: "green", wb.NOT_TESTED: "gray",
          wb.PANEL_NOT_STATED: "gray"}
QUEUE_WHY = {wb.ESTABLISHED: "a CIViC item of level A or B",
             wb.UNCERTAIN: "CIViC items of level C, D or E only",
             wb.NO_ITEMS: "no CIViC item in breast cancer"}
ITEM_COLUMNS = {"evidence_level": "Level", "therapies": "Therapies",
                "significance": "Significance", "direction": "Direction", "url": "CIViC",
                "level_meaning": "Level meaning", "citation": "Citation", "disease": "Disease",
                "match": "Profile match"}


def badge(text: str, color: str | None = None) -> str:
    return f":{color or COLORS.get(text, 'gray')}-badge[{text}]"


def _level_text(level: str | None) -> str:
    return f"{level} ({LEVELS[level]})" if level in LEVELS else "none"


def _items_table(items: list[dict]) -> None:
    df = pd.DataFrame(items).reindex(columns=list(ITEM_COLUMNS)).fillna("")
    df["level_meaning"] = df["evidence_level"].map(lambda v: LEVELS.get(v, "unknown"))
    st.dataframe(df.rename(columns=ITEM_COLUMNS), hide_index=True, width="stretch",
                 column_config={"CIViC": st.column_config.LinkColumn(display_text="evidence item")})


def _variant_details(v: dict) -> None:
    d = v["detection"]
    st.markdown(f"**[Observed] Detection** {badge(d['evidence'])}")
    st.table(pd.DataFrame({"": ["Test", "When", "Sample", "Assay", "Allele fraction"],
                           "value": [d["test"], d["when"], d["sample"], d["assay"],
                                     d["allele_fraction"]]}).set_index(""))
    i = v["interpretation"]
    st.markdown(f"**[Hypothesis] Interpretation** {badge(i['evidence'])} · {i['source']} · "
                "for clinician review, never a recommendation")
    if i["items"]:
        _items_table(i["items"])
    else:
        st.info(i["note"])
    e = v["effect"]
    st.markdown(f"**[Hypothesis] Predicted effect** {badge(e['evidence'])}")
    for s in e["statements"]:
        st.markdown(f"- {s}")
    st.caption(e["note"])


def render(file, events=None, evidence: dict | None = None, version: int | None = None,
           lookup=None) -> None:
    key = f"genomics-{file.id}"
    month = None if version is None else file.versions[version].month
    events = wb.events_until(events, month)
    vs = wb.variants(file, events, evidence, lookup)
    queue = wb.review_queue(vs)
    card = wb.data_card()
    lon = wb.longitudinal(file, events)
    levels = sorted(v["strongest_level"] for v in vs if v["strongest_level"])

    st.subheader(f"Genomics workbench · {file.id}"
                 + (f" · as of {file.versions[version].label}" if version is not None else ""))
    if file.kind == "synthetic":
        st.warning(file.note)  # "Synthetic patient: made up by hand ..."
    else:
        st.caption(file.title)
    st.markdown(" ".join([badge(wb.IMPLEMENTED), *(badge(f"{w}: planned", "gray")
                                                   for w, _ in wb.PLANNED_ROWS)]))

    # overview
    cols = st.columns(5)
    cols[0].metric("Variants observed", len(vs))
    cols[1].metric("Strongest CIViC level", levels[0] if levels else "none")
    for col, name in zip(cols[2:], queue, strict=True):
        col.metric(name.capitalize(), len(queue[name]))
    if vs:
        strongest = _level_text(levels[0] if levels else None)
        st.markdown("Observed: " + ", ".join(f"**{v['variant']}**" for v in vs)
                    + f". Strongest evidence level present: {strongest}."
                    " CIViC items are evidence **for clinician review, never a recommendation**.")
    elif not lon["timepoints"]:
        st.info("Not sequenced: the mutation status of every panel gene is unknown, not wild type.")
    else:
        st.info("Sequenced: none of the panel's genes mutated (panel genes only; purity and depth "
                "unknown, so this is not proof of absence).")

    # variant browser
    st.markdown("#### Variant browser")
    if vs:
        c1, c2 = st.columns([2, 3])
        search = c1.text_input("Search by gene", key=f"{key}-search").strip().upper()
        options = [_level_text(lv) for lv in dict.fromkeys(levels)] + (
            ["none"] if any(v["strongest_level"] is None for v in vs) else [])
        chosen = c2.multiselect("Strongest evidence level", options, default=options,
                                key=f"{key}-levels")
        shown = [v for v in vs if search in v["gene"].upper()
                 and _level_text(v["strongest_level"]) in chosen]
        table = pd.DataFrame([{"Gene": v["gene"], "Change": v["change"], "Sample": v["sample"],
                               "Month": "—" if v["month"] is None else v["month"],
                               "Strongest level": _level_text(v["strongest_level"]),
                               "CIViC items": len(v["interpretation"]["items"]),
                               "Queue": next(q for q, names in queue.items()
                                             if v["variant"] in names)} for v in shown])
        st.dataframe(table, hide_index=True, width="stretch")
        for v in shown:
            with st.expander(f"More info: {v['variant']} · {v['sample']}"
                             + (f" · month {v['month']}" if v["month"] is not None else "")):
                _variant_details(v)
    else:
        st.caption("No variant to browse.")

    # panel coverage
    st.markdown("#### Panel coverage")
    cov = wb.panel_coverage(file, events)
    counts = pd.Series([c["status"] for c in cov]).value_counts()
    st.markdown(" · ".join(f"{badge(s)} {n}" for s, n in counts.items()))
    st.dataframe(pd.DataFrame(cov).rename(columns={"gene": "Gene", "status": "Status"}),
                 hide_index=True, width="stretch", height=200)
    st.caption("The 16 breast cancer driver genes of the TCGA panel (src/muffle/data/tcga.py). "
               "A gene that was not tested, or whose panel is not stated, is unknown: never read "
               "it as wild type.")

    # review queue
    st.markdown("#### Review queue")
    for col, (name, names) in zip(st.columns(3), queue.items(), strict=True):
        col.markdown(f"**{name.capitalize()}** ({len(names)})  \n{QUEUE_WHY[name]}")
        for n in names:
            col.markdown(f"- {n}")
        if not names:
            col.caption("none")

    # longitudinal
    st.markdown("#### Over time")
    if lon["timepoints"]:
        st.dataframe(pd.DataFrame(lon["timepoints"]).rename(
            columns={"month": "Month", "sample": "Sample", "found": "Found"}),
            hide_index=True, width="stretch")
    statement = lon["statement"][0].upper() + lon["statement"][1:]
    st.markdown(f"{statement}. {badge('ctDNA: ' + lon['ctdna'], 'gray')}")

    # limits, data card, planned
    st.markdown("#### Limits")
    for limit in card["limits"]:
        st.markdown(f"- {limit}")
    st.markdown("#### Data and method card")
    rows = [("Status", card["status"]), ("Model", card["model"]),
            *((f"Data: {k}", v) for k, v in card["data"].items()),
            *((f"Label: {k}", v) for k, v in card["labels"].items()),
            ("Evidence levels", "; ".join(f"{k} {v}" for k, v in card["evidence_levels"].items()))]
    st.table(pd.DataFrame(rows, columns=["", "value"]).set_index(""))
    st.markdown("#### Planned, not results")
    st.dataframe(pd.DataFrame(card["planned"]).rename(
        columns={"what": "What", "note": "Note", "status": "Status"}),
        hide_index=True, width="stretch")


# ---------------------------------------------------------------- standalone page

EXAMPLE_CASE = SimpleNamespace(index=926, site="site-2", stage="III", age=55.0, percentile=99.0,
                            group="high", layers=["clinical", "genomic", "rna", "protein"],
                            missing=["methylation"], mutations=["PIK3CA p.H1047R", "TP53 p.R175H"])


@st.cache_resource(show_spinner="Loading CIViC evidence (CC0, ~4 MB, once)...")
def _civic_lookup():
    """``civic.evidence`` bound to the nightly table, or None when it cannot load."""
    from muffle.report import civic
    try:
        table = civic.load_table()
    except Exception:  # offline: the page still renders, with no CIViC items
        return None
    return lambda gene, change: civic.evidence(gene, change, "breast", 3, table)


def main() -> None:
    from muffle.workspace import case_file, synthetic_file
    st.set_page_config(page_title="Genomics workbench", layout="wide")
    tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
    choice = st.radio("Example file", ["SYNTHETIC-001 (synthetic patient)",
                                       f"Case {EXAMPLE_CASE.index} (TCGA-BRCA public data)"],
                      horizontal=True)
    if choice.startswith("SYNTHETIC"):
        render(synthetic_file(tl), evidence=tl.get("evidence"))
    else:
        lookup = _civic_lookup()
        if lookup is None:
            st.caption("CIViC table not available on this machine: no evidence items shown.")
        render(case_file(EXAMPLE_CASE), lookup=lookup)


if __name__ == "__main__":
    main()
