"""MuFFLe++: the clinician app of a breast cancer intelligence platform (milestone 1).

streamlit run app/streamlit_app.py -- --ckpt outputs/tcga_fedavg.pt --data data/tcga_brca
streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic
streamlit run app/streamlit_app.py -- --bundle outputs/demo_bundle.pt     # the hosted setup

Without the checkpoint and cohort (the hosted demo), it loads a demo bundle instead: --bundle or
MUFFLE_BUNDLE (a path or URL; default: the GitHub release asset). For a private repo's release,
set GITHUB_TOKEN to a token that can read the repo.

Two pages (docs/WORKSPACE.md, "Product framing"). Patients is the clinician workspace: a list of
patient files, the synthetic timeline patient first (its 12-month risk re-predicted at each event
by the MSK-CHORD models; app/timeline_synthetic.json from `make demo-timeline`), then the held-out
TCGA cases. A file opens on its latest report, with an SOS tile, its tests and their workbenches,
and a timeline of report versions; ?patient=<id> opens one. Methods and validation holds the model
cards, alert rules, how the case note is made, federated training and the data sources. No
hackathon or "demo" wording in the app's text. Live notes are capped per session
(DEMO_LIVE_NOTES_PER_SESSION, default 5); saved notes (app/saved_notes.json,
scripts/save_demo_notes.py) show without a key or once the cap is reached. CIViC's evidence table
(CC0, ~4 MB) is downloaded once per process into data/raw/civic/; if that fails, the agent runs
without the treatment_evidence tool and the sidebar says so.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

APP = Path(__file__).parent
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import torch  # noqa: E402

from muffle.hotreload import purge_modules, source_digest  # noqa: E402

# ponytail: Streamlit Cloud hot-updates this file but keeps the modules this process already
# imported (charts.py, src/muffle), which crashed the hosted app twice on Oct 19 (AttributeError
# on charts.risk_timeline, ImportError on muffle.demo.evidence_lookup). When the sources differ
# from what this process last ran, drop those modules and the caches their old code built.
CODE_DIGEST = source_digest([APP, APP.parent / "src" / "muffle"])
if getattr(sys, "_muffle_code_digest", None) != CODE_DIGEST:
    purge_modules(("charts", "muffle", "workbenches"))
    st.cache_resource.clear()
    st.cache_data.clear()
    sys._muffle_code_digest = CODE_DIGEST

import charts  # noqa: E402
from workbenches import genomics, labs  # noqa: E402

from muffle import crosstest, workspace  # noqa: E402
from muffle.demo import (  # noqa: E402
    build_demo,
    evidence_lookup,
    fetch_bundle,
    load_bundle,
    ordinal,
)
from muffle.explain import modality_contributions, risk_percentile  # noqa: E402
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED  # noqa: E402
from muffle.report import civic  # noqa: E402
from muffle.report.evidence_chain import note_chain  # noqa: E402
from muffle.report.grounding import describe  # noqa: E402
from muffle.report.nemotron import (  # noqa: E402
    DEFAULT_MODEL,
    WRITER_MODEL,
    CaseReport,
    model_name,
    run_case_agent,
    tavily_search,
)
from muffle.timeline import EVENTS  # noqa: E402

REPO = "https://github.com/ps131-cell/muffle-plus-plus"
BUNDLE_RELEASE = "demo-bundle-v2"  # bump once the next release exists (scripts/make_demo_bundle.py)
BUNDLE_URL = f"{REPO}/releases/download/{BUNDLE_RELEASE}/demo_bundle.pt"
LAYER_NAMES = {"clinical": "Clinical", "rna": "RNA expression", "genomic": "Copy number",
               "methylation": "Methylation", "protein": "Protein"}
EVIDENCE_COLORS = {OBSERVED: "blue", INFERENCE: "violet", HYPOTHESIS: "orange"}
STATUS_COLORS = {workspace.IMPLEMENTED: "blue", workspace.VALIDATED: "green",
                 workspace.PLANNED: "gray"}
PLANNED_WORKBENCHES = {
    "imaging": "Radiology workbench: a slice viewer with window and level, lesion contours, size "
               "and volume, and the same lesion tracked across scans.",
}

p = argparse.ArgumentParser()
p.add_argument("--ckpt", default="outputs/tcga_fedavg.pt")
p.add_argument("--data", default="data/tcga_brca")
p.add_argument("--cancer", default="breast")
p.add_argument("--n-clients", type=int, default=3)
p.add_argument("--config", default=None, help="only for checkpoints without a stored config")
p.add_argument("--notes", default=str(APP / "saved_notes.json"))
p.add_argument("--bundle", default=os.getenv("MUFFLE_BUNDLE") or None,
               help="demo bundle path or URL (default when the data isn't here: the release)")
args, _ = p.parse_known_args()


@st.cache_resource(show_spinner="Loading the model and the held-out patients…")
def load(ckpt: str, data: str, n_clients: int, config: str | None, cancer: str, notes: str,
         bundle: str | None):
    if bundle is None and Path(ckpt).exists() and (Path(data) / "cohort.npz").exists():
        demo = build_demo(ckpt, data, n_clients, config, cancer)
    else:
        source = bundle or BUNDLE_URL
        if source.startswith("https://"):
            # one file per URL, so a new release isn't masked by the previous release's file
            name = f"muffle_bundle_{hashlib.sha1(source.encode()).hexdigest()[:12]}.pt"
            source = fetch_bundle(source, Path(tempfile.gettempdir()) / name,
                                  os.getenv("GITHUB_TOKEN"))
        demo = load_bundle(source)
    if Path(notes).exists():
        demo.notes = {int(k): v for k, v in json.loads(Path(notes).read_text()).items()}
    return demo


@st.cache_resource(show_spinner="Loading CIViC treatment evidence…")
def evidence():
    """CIViC's table once per process; None (no treatment_evidence tool) if it can't load."""
    return evidence_lookup()


@st.cache_data
def results() -> dict | None:
    path = APP / "results_tcga_brca.json"
    return json.loads(path.read_text()) if path.exists() else None


@st.cache_data
def timeline() -> dict | None:
    path = APP / "timeline_synthetic.json"
    return json.loads(path.read_text()) if path.exists() else None


def secrets_to_env() -> None:
    """Streamlit Community Cloud keeps the app's secrets in st.secrets; copy the top-level
    values into the environment, where the agent and the spending cap read them. Real
    environment variables win; without a secrets file (local runs use .env) nothing happens."""
    try:
        items = dict(st.secrets)
    except Exception:  # no secrets.toml
        return
    for key, value in items.items():
        if isinstance(value, (str, int, float)) and key not in os.environ:
            os.environ[key] = str(value)


def tags(text: str) -> str:
    """Badges for the evidence types ``text`` names ("observed (mutation), hypothesis (...)")."""
    return " ".join(f":{c}-badge[{e}]" for e, c in EVIDENCE_COLORS.items() if e in text)


def badge(status: str) -> str:
    return f":{STATUS_COLORS[status]}-badge[{status}]"


st.set_page_config(page_title="MuFFLe++ · breast cancer intelligence", page_icon="🧬",
                   layout="wide")
DISCLAIMER = workspace.DISCLAIMER
secrets_to_env()
demo = load(args.ckpt, args.data, args.n_clients, args.config, args.cancer, args.notes,
            args.bundle)
LIVE = bool(os.getenv("NEBIUS_API_KEY"))
SEARCH = tavily_search if os.getenv("TAVILY_API_KEY") else None
EVIDENCE = evidence()
CAP = int(os.getenv("DEMO_LIVE_NOTES_PER_SESSION") or 5)  # "" (an empty .env line) = default
st.session_state.setdefault("live_used", 0)
st.session_state.setdefault("reports", {})  # cohort index -> (CaseReport, source)
st.session_state.setdefault("list_n", 0)    # a new patient-list key drops its old selection
st.session_state.setdefault("tests_n", 0)   # likewise for the tests table after "open the test"
st.session_state.setdefault("reviews", {})  # finding key -> {"what", "mark", "by", "at"}
st.session_state.setdefault("pins", {})     # finding key -> what it is

TL = timeline()
FILES, CASES = {}, {}  # patient id -> PatientFile; and for a TCGA file, its held-out case
if TL:
    synthetic = workspace.synthetic_file(TL)
    FILES[synthetic.id] = synthetic
for c in sorted(demo.cases, key=lambda c: (c.index not in demo.notes, -c.percentile)):
    pf = workspace.case_file(c, demo.c_index)
    FILES[pf.id], CASES[pf.id] = pf, c

# --- sidebar: what is running ----------------------------------------------------------------
with st.sidebar:
    st.markdown("### MuFFLe++")
    st.caption("Breast cancer intelligence: an evidence-linked patient profile that updates as "
               "the record grows.")
    st.markdown(
        f"**Model** · FedAvg across {len(demo.sites)} simulated hospitals (NVIDIA FLARE)  \n"
        f"**Held-out C-index** · {demo.c_index:.3f}  \n"
        f"**Case agent** · {'live' if LIVE else 'offline (no key)'}: "
        f"{model_name(DEFAULT_MODEL)} plans, {model_name(WRITER_MODEL)} writes, on Nebius "
        f"Token Factory  \n"
        f"**Treatment evidence** · "
        f"{'CIViC (CC0), for clinician review' if EVIDENCE else 'off (CIViC table unavailable)'}"
        f"  \n**Literature** · {'Tavily search on' if SEARCH else 'off (no Tavily key)'}")
    budget_slot = st.empty()  # filled at the end, after this run's live note (if any)
    st.text_input("Reviewer initials", key="reviewer", max_chars=5,
                  help="Saved with each review mark. Marks and pins stay in this browser "
                       "session and go into the report export.")
    st.caption(f"{DISCLAIMER} [Source code]({REPO})")


# --- Patients: the list -----------------------------------------------------------------------
def patients_page():
    top = st.container()  # the list's title goes above the picker
    pid = st.selectbox(
        "Patient file", list(FILES), index=None, key="patient", bind="query-params",
        placeholder="Type a patient ID to open the file (the list below searches everything)",
        help="Every patient file has its own address (…?patient=<id>).")
    if pid is None:
        with top:
            st.title("MuFFLe++")
            st.markdown("An evidence-linked picture of each patient's breast cancer, updated as "
                        "the record grows. Every finding is marked **observed**, **model "
                        "inference** or **hypothesis**.")
            st.caption(DISCLAIMER)
        patient_list()
    else:
        patient_file(FILES[pid])


def open_selected():
    """Row click in the patient list: open that file (with a fresh list for next time)."""
    rows = st.session_state[f"list-{st.session_state.list_n}"].selection.rows
    if rows:
        st.session_state.patient = st.session_state.list_ids[rows[0]]
        st.session_state.list_n += 1


def patient_list():
    rows = []
    for pid, pf in FILES.items():
        case = CASES.get(pid)
        rows.append({
            "Patient": pid,
            "Kind": "Synthetic (written by hand)" if case is None
                    else f"TCGA-BRCA · simulated {case.site}",
            "Diagnosis": pf.diagnosis,
            "Driver mutations": dict(pf.latest.observed).get("Driver mutations"),
            "Latest report": pf.latest.label,
            "SOS now": len(pf.latest.alerts),
            "SOS before": sum(len(v.alerts) for v in pf.versions[:-1]),
            "Tests": ", ".join(dict.fromkeys(t.kind for t in pf.tests)),
            "Saved note": "★" if case and case.index in demo.notes else "",
        })
    table = pd.DataFrame(rows)
    if st.toggle("Only files with SOS alerts"):
        table = table[table["SOS now"] + table["SOS before"] > 0]
    st.session_state.list_ids = table["Patient"].tolist()
    st.dataframe(table, hide_index=True, on_select=open_selected, selection_mode="single-row",
                 key=f"list-{st.session_state.list_n}", width="stretch")
    st.caption(
        "Click a row to open the file; the table's search icon filters it. SYNTHETIC-001 is a "
        "synthetic patient, written by hand. The TCGA cases are public TCGA-BRCA patients the "
        "risk model never trained on, each assigned to one of the simulated hospitals; TCGA holds "
        "one tumor sample per patient, so their files have one version. ★ = a saved case note.")


# --- Patients: one patient file ----------------------------------------------------------------
def patient_file(pf: workspace.PatientFile):
    st.button("← All patients",
              on_click=lambda: st.session_state.update(patient=None, view="Report"))
    st.header(pf.id)
    st.caption(f"{pf.title} · {pf.diagnosis}")
    if pf.kind == "synthetic":
        st.warning(f"**{pf.id} is synthetic.** {pf.note}", icon="🧪")
    last = len(pf.versions) - 1
    i = last if not last else st.select_slider(
        "Report version", options=range(last + 1), value=last, key=f"version-{pf.id}",
        format_func=lambda k: pf.versions[k].label + (" (latest)" if k == last else ""),
        help="Every new test or event adds a version; earlier versions are kept. Move back to "
             "open the report, its tests and its timeline as they were then.")
    if "view" not in st.session_state and "view" not in st.query_params:
        st.session_state.view = "Report"  # no default=: "open the test" sets the view in code
    view = st.segmented_control("View", ["Report", "Tests", "Timeline", "Import tests"],
                                required=True, key="view", bind="query-params",
                                label_visibility="collapsed")
    {"Report": report_view, "Tests": tests_view, "Timeline": timeline_view,
     "Import tests": import_view}[view](pf, i)


def report_view(pf: workspace.PatientFile, i: int):
    v, case = pf.versions[i], CASES.get(pf.id)
    st.subheader(f"Report · {v.label}" + ("" if i == len(pf.versions) - 1 else
                                         " (as it was then)"))
    arrived = v.event + ("" if v.month is None else f" (month {v.month})")
    st.markdown(f"**Summary** · {pf.diagnosis}. Latest in the record: {arrived}. "
                f"{tags(OBSERVED)}  \n{v.summary} {tags(INFERENCE) if v.risk else ''}")
    sos_tile(pf, i)
    review_panel(pf)

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Characterization and record** {tags(OBSERVED)}")
        st.markdown("\n".join(f"- **{k}:** {val}" for k, val in v.observed))
    with right:
        head, box = st.columns([4, 1])
        head.markdown(f"**Risk** {tags(INFERENCE)} {badge(pf.model['status'])}")
        with box:
            review_box(workspace.finding_key(pf, "risk", v.month), f"Risk estimate, {v.label}")
        if case is None:
            synthetic_risk(pf, i)
        else:
            case_risk(case)

    if case is None:
        st.markdown(f"**What changed since the last version, and why** {tags(INFERENCE)}")
        if v.changes:
            st.altair_chart(charts.contributions(
                {c["what"]: c["points"] for c in v.changes}, title="change in risk (points)",
                fmt="+.0f"), width="stretch")
            st.caption("One change at a time against the previous record, scored by the current "
                       "model; changes interact, so the rest is shown.")
        else:
            st.caption(v.summary)
        sites = dict(v.observed).get("Metastatic sites", "none")
        st.markdown(f"**Areas of risk** {tags(OBSERVED)} · metastatic sites: {sites}")
    else:
        case_why(case)

    st.markdown(f"**Mutations** {tags(OBSERVED)} **and treatment evidence for clinician "
                f"review** {tags(HYPOTHESIS)}")
    seq = workspace.sequencing_tests(pf, i)
    if not seq:
        st.caption("Not sequenced: driver mutations are unknown, not wild type.")
    for t in seq:
        st.markdown(f"- {t.name}" + ("" if t.month is None else f", month {t.month}")
                    + f": {t.result}")
    variants = [var for t in seq for var in t.details["variants"]]
    quiet = [var for var in variants if civic_items(pf, var) == []]
    for var in variants:
        if var not in quiet:
            civic_block(pf, var, k=3)
    if quiet:
        st.caption("No CIViC breast cancer evidence for " + ", ".join(quiet) + ".")

    st.markdown(f"**Evolutionary hypotheses** {badge(workspace.PLANNED)} · the likely next "
                "alterations and escape routes, with their confidence (docs/VISION.md).")
    st.markdown(f"**Missing data and what it limits** {tags(OBSERVED)}")
    st.markdown("\n".join(f"- {line}" for line in workspace.missing_data(pf, i)))
    disagree = crosstest.discrepancies(pf, i)
    if disagree:
        st.markdown(f"**Tests that disagree** · {len(disagree)}")
        for d in disagree:
            with st.container(border=True):
                st.markdown(f"**{d['what']}** {tags(d['evidence'])}")
                st.caption(" · ".join(d["sources"]) + f" · {d['why']}")
                st.markdown(f"What would settle it: {d['would_settle']}")
    reducers = crosstest.uncertainty_reducers(pf, i)
    if reducers:
        st.markdown(f"**What would reduce uncertainty** {tags(HYPOTHESIS)} · evidence for your "
                    "judgment, not an order")
        st.markdown("\n".join(
            f"- **{r['open_question']}** → {r['test']}: {r['expectation']} "
            f"{tags(r['evidence'])}  \n  Source: {r['source']}" for r in reducers))
    with st.expander("Caveats, data sources and model versions"):
        st.markdown(f"- **Model:** {pf.model['name']} ({pf.model['status']}); endpoint: "
                    f"{pf.model['endpoint']}.\n" + "\n".join(f"- {s}" for s in sources(pf)))
    page = workspace.report_markdown(pf, i, {var: civic_items(pf, var) for var in variants},
                                     st.session_state.reviews, sources(pf), disagree, reducers)
    when = "baseline" if v.month is None else f"month{v.month}"
    st.download_button("Download this report version (Markdown)", page,
                       file_name=f"{pf.id.replace(' ', '_')}_{when}.md", mime="text/markdown",
                       help="One page: numbers, sources, placeholders, model versions and your "
                            "review marks.")
    if case is not None:
        case_note(case)


TRUST_COLORS = {"strong": "green", "moderate": "orange", "weak": "red"}
MARKS = workspace.MARKS[1:]  # "reviewed" comes from the "Mark reviewed" button


def sos_tile(pf: workspace.PatientFile, i: int):
    """The alert queue: this version's alerts, then earlier ones (latest first), each list ordered
    by consequence × trust. One alert at a time is open, with its actions; next / previous step
    through the queue."""
    v = pf.versions[i]
    queue = v.alerts + [a for w in reversed(pf.versions[:i]) for a in w.alerts]
    with st.container(border=True):
        if not queue:
            st.markdown("**SOS** · nothing alarming in this version")
            if len(pf.versions) == 1:
                st.caption(pf.note)
            return
        earlier = len(queue) - len(v.alerts)
        head = (f"**:red[SOS]** · {len(v.alerts)} alarming in this version" if v.alerts
                else "**SOS** · nothing new in this version")
        st.markdown(head + (f", {earlier} earlier" if earlier else ""))
        pos = f"sos-{pf.id}-{i}"
        k = st.session_state.get(pos, 0) % len(queue)
        a = queue[k]
        key = workspace.finding_key(pf, "alert", a.month, a.what)
        done = st.session_state.reviews.get(key)
        flag = " :orange-badge[placeholder threshold]" if "placeholder" in a.threshold else ""
        st.markdown(f"**{k + 1}/{len(queue)} · {a.what}** {tags(a.evidence)} "
                    f":{TRUST_COLORS[a.trust]}-badge[trust: {a.trust}]{flag}")
        since = f"month {a.month}" + ("" if a.month == v.month or v.month is None
                                      else f", {v.month - a.month} months before this version")
        st.caption(f"Since {since} · source: {a.source} · rule: {a.rule} · threshold: "
                   f"{a.threshold} · trust {a.trust}: {a.why_trust}"
                   + (f" · {done['mark']} by {done['by'] or 'no initials'}, {done['at']}"
                      if done else ""))
        c = st.columns([3, 3, 2, 2, 3])
        if a.opens:
            c[0].button("Open the test" if a.opens[0] == "Tests" else "Open the timeline",
                        key=f"open-{key}", on_click=open_evidence, args=(pf, a))
        c[1].button("Mark reviewed", key=f"reviewed-{key}", disabled=done is not None,
                    on_click=mark, args=(key, a.what, "reviewed"))
        c[2].button("◀", key=f"prev-{pos}", help="Previous alert",
                    on_click=lambda: st.session_state.update({pos: k - 1}))
        c[3].button("▶", key=f"next-{pos}", help="Next alert",
                    on_click=lambda: st.session_state.update({pos: k + 1}))
        with c[4]:
            review_box(key, a.what)
        lines = []
        for n, b in enumerate(queue):
            line = f"{b.what} · month {b.month} · trust {b.trust}"
            seen = st.session_state.reviews.get(workspace.finding_key(pf, "alert", b.month, b.what))
            lines.append(f"{n + 1}. " + (f"**{line}**" if n == k else line)
                         + (f" · ✓ {seen['mark']}" if seen else ""))
        st.markdown("\n".join(lines))
        st.caption("Ordered by consequence × trust, this version first: a fixed ordering rule "
                   "with placeholder weights, not a validated score.")


def open_evidence(pf: workspace.PatientFile, a: workspace.Alert):
    """"Open the test": switch the file to the view that holds the alert's evidence."""
    if a.opens[0] == "Tests":
        st.session_state[f"picked-{pf.id}"] = a.opens[1:]
        st.session_state.tests_n += 1  # a fresh tests table, so no old row selection wins
    st.session_state.view = a.opens[0]


def mark(key: str, what: str, value: str | None):
    """Store (or, with None, clear) a reviewer's mark on one finding."""
    if value is None:
        st.session_state.reviews.pop(key, None)
    else:
        st.session_state.reviews[key] = {"what": what, "mark": value,
                                         "by": st.session_state.get("reviewer") or "",
                                         "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def toggle_pin(key: str, what: str):
    if st.session_state.pins.pop(key, None) is None:
        st.session_state.pins[key] = what


def review_box(key: str, what: str):
    """Agree / disagree / second look and a pin for one finding, in a small popover."""
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    done = st.session_state.reviews.get(key)
    with st.popover(f"✓ {done['mark']}" if done else "Review",
                    help="Mark this finding; marks go into the report export"):
        st.segmented_control(
            "Your mark", MARKS, key=f"mark-{h}",
            default=done["mark"] if done and done["mark"] in MARKS else None,
            on_change=lambda: mark(key, what, st.session_state[f"mark-{h}"]))
        st.checkbox("Pin to the top of the report", key=f"pin-{h}",
                    value=key in st.session_state.pins, on_change=toggle_pin, args=(key, what))
        if done:
            st.caption(f"{done['mark']} · {done['by'] or 'no initials'} · {done['at']}")


def review_panel(pf: workspace.PatientFile):
    """Pinned findings and every review mark in this file, with a filter."""
    marks = {k: r for k, r in st.session_state.reviews.items() if k.startswith(pf.id + "|")}
    pins = {k: w for k, w in st.session_state.pins.items() if k.startswith(pf.id + "|")}
    if not marks and not pins:
        return
    with st.expander(f"Pinned and reviewed: {len(pins)} pinned, {len(marks)} marked",
                     expanded=bool(pins)):
        show = st.pills("Show", ["pinned", "reviewed", *MARKS], selection_mode="multi",
                        key=f"review-filter-{pf.id}")
        rows = [("pinned", w, "", "") for w in pins.values()] + [
            (r["mark"], r["what"], r["by"], r["at"]) for r in marks.values()]
        st.dataframe(pd.DataFrame([r for r in rows if not show or r[0] in show],
                                  columns=["Mark", "Finding", "By", "When"]),
                     hide_index=True, width="stretch")


def synthetic_risk(pf: workspace.PatientFile, i: int):
    r = pf.versions[i].risk
    if r is None:
        st.caption(pf.versions[i].summary)
        return
    prev = next((v.risk["value"] for v in reversed(pf.versions[:i]) if v.risk), None)
    m = TL["models"][str(r["landmark"])]
    c1, c2 = st.columns(2)
    c1.metric("12-month risk", f"{r['value']:.0%}",
              None if prev is None else f"{100 * (r['value'] - prev):+.0f} points",
              delta_color="inverse", help=pf.model["endpoint"].capitalize() + ".")
    c2.metric("Range, 5 models", "{:.0%}–{:.0%}".format(*r["range"]),
              help="The same model trained on five different 80% splits (seeds 0–4).")
    c3, c4 = st.columns(2)
    c3.metric("Diagnosis only", f"{r['baseline']:.0%}",
              help="Baseline: stage, HR and HER2 alone, same patients and learner.")
    c4.metric("Model AUROC", f"{r['auroc']:.2f}",
              help=f"Held-out AUROC of the month-{r['landmark']} model on MSK-CHORD, mean of 5 "
                   f"seeds (diagnosis only: {r['baseline_auroc']:.2f}; {m['n']:,} patients, "
                   f"event rate {m['event_rate']:.0%}).")
    st.caption(f"{pf.model['endpoint'].capitalize()}, from the month-{r['landmark']} "
               f"{pf.model['name']}. Whether these probabilities are calibrated has not been "
               "checked.")


def case_risk(case):
    c1, c2 = st.columns(2)
    c1.metric("Risk percentile", ordinal(case.percentile),
              help="Share of all patients with a lower predicted risk.")
    c2.metric("Risk group", case.group.capitalize(), help="Cohort tertiles of predicted risk.")
    c3, c4 = st.columns(2)
    c3.metric("Simulated hospital", case.site,
              help="The FL client this patient belongs to: a group of TCGA tissue source sites.")
    c4.metric("Data layers", f"{len(case.layers)} of {len(demo.model.names)}",
              help="Missing: " + (", ".join(case.missing) or "none"))
    st.caption(f"Overall survival, ranked against all {len(demo.cohort_risks):,} patients by the "
               f"federated model (held-out C-index {demo.c_index:.3f}). It ranks patients; its "
               "absolute risks are only roughly calibrated.")


def case_why(case):
    x, mask = demo.inputs(case)
    left, right = st.columns(2)
    with left:
        st.markdown(f"**Where this patient sits among all patients** {tags(INFERENCE)}")
        st.altair_chart(charts.risk_position(demo.cohort_risks, case.log_risk,
                                             f"{ordinal(case.percentile)} percentile"),
                        width="stretch")
    with right:
        st.markdown(f"**What drives this patient's risk** {tags(INFERENCE)}")
        _, contrib = modality_contributions(demo.model, x, mask, demo.offsets)
        st.altair_chart(charts.contributions(
            {LAYER_NAMES.get(m, m): v for m, v in contrib.items()}), width="stretch")
        st.caption("Each layer's effect on this patient's predicted log-risk, compared with its "
                   "effect on a typical patient in the cohort.")

    with st.expander("What if a data layer were missing?"):
        st.caption("Hospitals collect different data. MuFFLe++ masks a missing layer instead of "
                   "dropping the patient, so the same model scores everyone.")
        hide = st.pills("Hide layers", case.layers, selection_mode="multi",
                        format_func=lambda m: LAYER_NAMES.get(m, m), key=f"hide-{case.index}")
        if hide and len(hide) == len(case.layers):
            st.warning("Keep at least one layer.")
        elif hide:
            hx, hmask = demo.inputs(case, hide)
            with torch.no_grad():
                risk = demo.model(hx, hmask).item()
            pct = risk_percentile(risk, demo.cohort_risks)
            st.metric("Risk percentile without " + ", ".join(LAYER_NAMES.get(m, m) for m in hide),
                      ordinal(pct), f"{int(pct) - int(case.percentile):+d} percentile points",
                      delta_color="inverse")


def civic_items(pf: workspace.PatientFile, variant: str) -> list[dict] | None:
    """CIViC items for a variant: frozen with the timeline file for the synthetic patient, else
    from the live table (None if it couldn't load)."""
    if pf.kind == "synthetic":
        return TL["evidence"].get(variant, [])
    if EVIDENCE is None:
        return None
    gene, change = variant.split(maxsplit=1)
    return EVIDENCE(gene, change)


def civic_block(pf: workspace.PatientFile, variant: str, k: int | None = None):
    items = civic_items(pf, variant)
    with st.container(border=True):
        st.markdown(f"**{variant}** · CIViC treatment evidence, for clinician review "
                    f"{tags(HYPOTHESIS)}")
        if items is None:
            st.caption("The CIViC table could not be loaded here.")
        elif not items:
            st.caption("No CIViC breast cancer evidence for this variant.")
        for e in (items or [])[:k]:
            text, box = st.columns([6, 1])
            text.markdown(f"- Level **{e['evidence_level']}** ({e['level_meaning']}) · "
                          f"{e['therapies'].replace(',', ', ')} · "
                          f"{str(e['significance']).lower()} · matches "
                          f"{e.get('match', 'this variant')} · [{e['citation']}]({e['url']})")
            with box:
                review_box(workspace.finding_key(pf, "civic", variant, e["url"]),
                           f"{variant}: CIViC level {e['evidence_level']}, "
                           f"{e['therapies'].replace(',', ', ')} ({e['citation']})")


def sources(pf: workspace.PatientFile) -> list[str]:
    if pf.kind == "synthetic":
        return [pf.model["note"],
                "Record: written by hand (src/muffle/timeline.py); not a real person.",
                "Treatment evidence: CIViC (CC0), as of the timeline file's build.",
                "These scores never go to a language model, so this file has no case note."]
    return ["Data: TCGA-BRCA open access (GDC, UCSC Xena); mutations from GDC's open-access "
            "masked somatic calls.",
            "Treatment evidence: CIViC (CC0), nightly table.",
            f"Case note: {model_name(DEFAULT_MODEL)} plans and {model_name(WRITER_MODEL)} "
            "writes, on Nebius Token Factory; a grounding check verifies it.",
            DISCLAIMER]


def case_note(case):
    st.subheader("Tumor-board note")
    saved = demo.notes.get(case.index)
    can_live = LIVE and st.session_state.live_used < CAP
    b1, b2, _ = st.columns([2, 2, 3])
    write = b1.button("Write the note with Nemotron", type="primary", disabled=not can_live,
                      help=None if can_live else ("Set NEBIUS_API_KEY for live notes." if not LIVE
                                                  else "This session's live notes are used up."))
    show_saved = b2.button("Show the saved note", disabled=saved is None)
    if not can_live:
        st.caption("Live notes are off here; ★ patients have a saved case note."
                   if saved is None or not LIVE else
                   "This session's live notes are used up; showing saved notes.")

    if write:
        with st.status("Nemotron is working on the case…", expanded=True) as status:
            report = run_case_agent(demo.tools(case, SEARCH, EVIDENCE), on_step=status.write)
            status.update(label="Note ready", state="complete", expanded=False)
        if report.mode != "offline":
            st.session_state.live_used += 1
        st.session_state.reports[case.index] = (report, "live")
    elif show_saved and saved:
        st.session_state.reports[case.index] = (CaseReport.from_dict(saved["report"]),
                                                f"saved on {saved['created']}")

    if case.index in st.session_state.reports:
        report, source = st.session_state.reports[case.index]
        note, trace = st.columns([3, 2])
        with note:
            st.markdown(report.text)
            if report.mode != "offline":
                if report.issues:
                    st.warning("Grounding check: not found in the tool outputs: "
                               + describe(report.issues))
                else:
                    st.success("Grounding check: every number, gene and link in this note comes "
                               "from the tool outputs" + (" (rewritten once after the check)."
                                                          if report.revised else "."))
            evidence_chain(case, report)
            header = (f"# MuFFLe++ tumor-board note: case {case.index}\n\n"
                      f"_{case.label} · {source} · written by {model_name(report.writer)} on "
                      f"Nebius Token Factory. {DISCLAIMER}_\n\n")
            st.download_button("Download the note (Markdown)", header + report.text,
                               file_name=f"muffle_case_{case.index}.md", mime="text/markdown")
        with trace:
            st.markdown("**How the agent got there**")
            st.caption({
                "agent": f"{model_name(report.model)} chose these tool calls; "
                         f"{model_name(report.writer)} wrote the note, on Nebius Token Factory "
                         f"· {report.tokens:,} tokens · {source}",
                "fixed plan": f"Tool calling unavailable: the tools ran in a fixed order and "
                              f"{model_name(report.writer)} wrote the note · {source}",
                "offline": "Offline: the tools ran in a fixed order and a template wrote the "
                           "note.",
            }[report.mode])
            for line in report.notes:
                st.caption(line)
            for n, call in enumerate(report.trace, 1):
                shown = ", ".join(f"{k}={json.dumps(v)}" for k, v in call.arguments.items())
                flag = " ⚠️" if "error" in call.result else ""
                with st.expander(f"{n}. {call.name}({shown}){flag}"):
                    st.json(call.result)
            st.caption("Only these derived numbers and gene names were sent to Token Factory; "
                       "the patient's omics never leave the hospital.")


def evidence_chain(case, report: CaseReport):
    """Each sentence of the note → the tool output behind it → the field → its value, with how
    exactly they match (strong: exact; weak: rounded or part of a word)."""
    chain = note_chain(report, demo.names, header=demo.tools(case).case_header())
    rows = [{"#": n, "Sentence": c["sentence"], "Says": c["evidence_type"] or "",
             "Item": link["item"], "Tool": link["tool"], "Field": link["path"],
             "Value": str(link["value"]), "Match": link["trust"]}
            for n, c in enumerate(chain, 1) for link in c["links"]]
    loose = [(n, c) for n, c in enumerate(chain, 1) if not c["links"] and c["evidence_type"]]
    unsupported = [(n, u) for n, c in enumerate(chain, 1) for u in c["unsupported"]]
    with st.expander(f"Evidence chain: {len(rows)} links from {len(chain)} sentences to the "
                     "tool outputs" + (f", {len(unsupported)} unsupported" if unsupported else "")):
        if unsupported:
            st.warning("Not in the tool outputs: " + "; ".join(
                f"sentence {n}: {u}" for n, u in unsupported))
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        if loose:
            st.caption("Labeled sentences with no number, gene or link to check: "
                       + ", ".join(str(n) for n, _ in loose) + ".")
        st.caption("Match: strong = the exact value; weak = rounded, or part of a longer word. "
                   "The same check as the grounding check above, sentence by sentence.")


def tests_view(pf: workspace.PatientFile, i: int):
    tests = [t for v in pf.versions[: i + 1] for t in v.tests]
    kinds = st.pills("Type", list(dict.fromkeys(t.kind for t in tests)), selection_mode="multi",
                     key=f"kinds-{pf.id}")
    shown = [t for t in tests if not kinds or t.kind in kinds]
    table = pd.DataFrame([{"Type": t.kind, "Month": t.month, "Test": t.name, "Result": t.result,
                           "Workbench": t.workbench, "Status": t.status + (
                               f": {t.details['scope']}" if "scope" in t.details else "")}
                          for t in shown])
    rows = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                        key=f"tests-{pf.id}-{i}-{'.'.join(kinds)}-{st.session_state.tests_n}",
                        width="stretch").selection.rows
    st.caption("Select a test to open its workbench. " + (
        "Months count from the first tumor sequencing." if pf.kind == "synthetic" else
        "TCGA holds one sample per patient, so its tests carry no dates."))
    if not shown:
        return
    picked = f"picked-{pf.id}"  # the last test opened here or from an alert
    if rows:
        st.session_state[picked] = (shown[rows[0]].kind, shown[rows[0]].month, shown[rows[0]].name)
    t = next((t for t in shown if (t.kind, t.month, t.name) == st.session_state.get(picked)),
             None) or next((t for w in ("labs", "mutations", "omics", "record") for t in shown
                            if t.workbench == w), shown[0])
    st.divider()
    if t.workbench == "labs":
        labs.render(pf, version=i)
    elif t.workbench == "mutations":  # CIViC's table adds the resistance items when it loaded
        genomics.render(pf, version=i, lookup=EVIDENCE,
                        table=civic.load_table() if EVIDENCE else None)
    elif t.workbench == "slides":  # a public example region; the page says it isn't this patient
        from workbenches import slides  # here, so a missing scipy can't break the whole app

        slides.render(pf, version=i)
    elif t.workbench in ("omics", "record"):
        layer_workbench(CASES[pf.id], t.details["layer"], pf.versions[i])
    else:
        st.markdown(f"#### {t.name}, month {t.month} {badge(t.status)}")
        st.markdown(f"**Report text** {tags(OBSERVED)}: {t.result}")
        st.info(PLANNED_WORKBENCHES[t.workbench] + " Planned, pending the model and dataset "
                "survey's shortlist (docs/WORKSPACE.md).", icon="🧭")


def layer_workbench(case, layer: str, v: workspace.Version):
    tools = demo.tools(case)
    effect = tools.modality_contributions()["log_risk_added_by_layer"].get(layer)
    st.markdown(f"#### {'Clinical record' if layer == 'clinical' else LAYER_NAMES[layer]} "
                f"{badge(workspace.IMPLEMENTED)}")
    st.markdown(f"Measured {tags(OBSERVED)}: {workspace.ASSAYS[layer]}.")
    if layer == "clinical":
        st.markdown("\n".join(f"- **{k}:** {val}" for k, val in v.observed))
    if effect is not None:
        st.markdown(f"Effect on this patient's predicted log-risk compared with a typical patient: "
                    f"**{effect:+.3f}** {tags(INFERENCE)}")
    feats = tools.top_features(layer, 10)["features"]
    if feats:
        st.altair_chart(charts.contributions({f["name"]: f["score"] for f in feats},
                                             title="effect on log-risk (gradient × input)",
                                             fmt="+.4f"), width="stretch")
        st.caption("The features that move this patient's predicted risk most: an inference "
                   "about the model, not a biological finding about the tumor.")
    else:
        st.caption("No single feature in this layer moves this patient's risk measurably.")
    st.info(f"{badge(workspace.PLANNED)} " + (
        "Clinical documents with their source sentences highlighted: extracted diagnoses, "
        "procedures, drugs and dates." if layer == "clinical" else
        "Expression distributions and ranked genes against the cohort, pathway and subtype "
        "scores (PAM50) with their reference definitions, batch and quality checks."))


def timeline_view(pf: workspace.PatientFile, i: int):
    if len(pf.versions) == 1:
        st.info(pf.note)
    else:
        month = pf.versions[i].month
        updates = TL["updates"][: i + 1]
        if any("risk" in u for u in updates):
            treatments = [{"month": e["month"], "text": e["text"]} for e in EVENTS
                          if e.get("treatments") and e["month"] <= month]
            st.altair_chart(charts.risk_timeline(updates, TL["events"], month, treatments),
                            width="stretch")
            st.caption(f"{tags(INFERENCE)} {TL['task'].capitalize()} at each version from the "
                       "first tumor sequencing (month 0) on: the record-so-far models (the band "
                       "is the range of 5 models) and the diagnosis-only baseline. Dashed "
                       "vertical lines: treatment starts. Move the report version above to open "
                       "any version.")
    st.dataframe(pd.DataFrame([{
        "Month": v.month, "Version": v.label, "What arrived": v.event,
        "12-month risk": v.risk.get("value") if v.risk else None, "SOS": len(v.alerts),
        "Tests added": ", ".join(t.name for t in v.tests),
        "Treatment started": ", ".join(v.treatments)} for v in pf.versions[: i + 1]]),
        hide_index=True, width="stretch",
        column_config={"12-month risk": st.column_config.NumberColumn(format="percent")})
    if i:
        compare(pf, i)


def compare(pf: workspace.PatientFile, i: int):
    st.markdown("**Compare two versions** · what changed and why")
    a, b = st.columns(2)
    ia = a.selectbox("From", range(i + 1), index=i - 1, key=f"from-{pf.id}-{i}",
                     format_func=lambda k: pf.versions[k].label)
    ib = b.selectbox("To", range(i + 1), index=i, key=f"to-{pf.id}-{i}",
                     format_func=lambda k: pf.versions[k].label)
    lo, hi = sorted((ia, ib))
    diff = crosstest.diff_versions(pf, lo, hi)
    if not diff:
        st.caption("Nothing changed between these versions.")
    for col, kind in zip(st.columns(3), (OBSERVED, INFERENCE, HYPOTHESIS), strict=True):
        items = [d for d in diff if d["column"] == kind]
        with col:
            st.markdown(f"**{kind.capitalize()}** {tags(kind)} · {len(items)} changed")
            for d in items:
                st.markdown({
                    "added": f":green[**+ {d['finding']}**]: {d['after']}",
                    "removed": f":red[**− {d['finding']}**]: ~~{d['before']}~~",
                    "changed": f":orange[**~ {d['finding']}**]: {d['before']} → {d['after']}",
                }[d["status"]])
    why = [v for v in pf.versions[lo + 1: hi + 1] if v.changes]
    if why:
        st.markdown(f"**Why the risk changed** {tags(INFERENCE)}")
        st.markdown("\n".join(f"- **{v.label}** · {v.summary}" for v in why))


def import_view(pf: workspace.PatientFile, i: int):
    st.markdown(f"#### Import tests {badge(workspace.PLANNED)}")
    st.info("Each test type will come in through its own input adapter (slide images, DICOM scan "
            "series, lab results, VCF or MAF sequencing reports, expression data, text reports), "
            "with quality control on intake that shows what was accepted or rejected and why. An "
            "imported test adds a report version; earlier versions are never overwritten. For "
            "now only public or synthetic data can be imported (docs/WORKSPACE.md).")


# --- Methods and validation ------------------------------------------------------------------
def methods_page():
    st.title("Methods and validation")
    st.markdown(
        "How each result in a patient file is produced, how well it holds up, and where the data "
        "come from. In a file, every finding is marked **observed** (measured or recorded), "
        "**model inference** (a prediction, with its uncertainty) or **hypothesis** (evidence "
        "and literature leads); every module is marked implemented, experimentally validated or "
        "planned; every alert names its rule and where its threshold comes from.")
    res = results()
    by = {m["method"]: m for m in res["methods"]} if res else None

    st.header("Model cards")
    st.subheader("Multi-omic survival model")
    st.markdown(f"{badge(workspace.VALIDATED)} · overall survival, ranked by cohort percentile · "
                "TCGA patient files")
    st.markdown(
        f"- **Training data:** TCGA-BRCA open access ({len(demo.cohort_risks):,} patients, "
        "overall survival): copy number, RNA expression, methylation, protein and clinical "
        f"data, split across {len(demo.sites)} simulated hospitals (groups of TCGA tissue source "
        "sites, so their data gaps are real).\n"
        "- **Design:** a clinical risk first, which the omic layers then correct by an amount "
        "chosen on hospitals the model wasn't trained on. A layer a hospital never measured is "
        "masked, not imputed, and training hides layers at random so the model copes. Trained "
        "with FedAvg in NVIDIA FLARE: only model weights leave a hospital.\n"
        f"- **Held-out performance:** C-index {demo.c_index:.3f}, the mean over hospitals ("
        + ", ".join(f"{s} {c:.3f}" for s, c in demo.c_index_by_site.items()) + ").\n"
        "- **Calibration:** the model ranks patients; its absolute risks are only roughly "
        "calibrated, and it is weaker for patients under 50 and within a single stage.")
    if res and demo.names:  # real data (synthetic cohorts have no gene names)
        st.markdown("**Leave one hospital out:** train on two hospitals, test on the third.")
        main = [m for m in res["methods"] if m["group"] == "main"]
        st.altair_chart(charts.results(main), width="stretch")
        st.markdown(
            f"- **Federated ≈ pooled.** FedAvg reaches {by['fedavg_residual']['mean']:.3f} on "
            f"a hospital it never saw, against {by['residual']['mean']:.3f} when the other "
            "hospitals' patients are pooled in one place, without moving any patient data.\n"
            f"- **Better than one hospital alone**, which scores "
            f"{by['local_only']['mean']:.3f}.\n"
            f"- **The omic layers don't add signal yet.** Clinical data alone (stage, age, "
            f"T/N/M) scores {by['only_clinical']['mean']:.3f} on overall survival, so the model "
            "anchors on clinical data and lets the omics correct it.")
        st.caption(res["protocol"] + ".")
        with st.expander("Each omic layer on its own"):
            single = [m for m in res["methods"] if m["group"] == "single layer"]
            st.dataframe(pd.DataFrame(single)[["label", "mean", "sd"]].rename(
                columns={"label": "Layer", "mean": "C-index", "sd": "sd"}), hide_index=True)
            st.caption("Copy number alone ranks patients worse than chance across hospitals "
                       "(below 0.5): a sign of site and batch effects.")
    left, right = st.columns([3, 2])
    with left:
        st.altair_chart(charts.survival_by_group(demo.km), width="stretch")
    with right:
        st.markdown("**Risk groups on the held-out patients**")
        st.caption(f"{demo.heldout_patients} held-out patients, {demo.heldout_deaths} deaths. "
                   "Curves stop at 5 years, where fewer than 20 patients per group remain. The "
                   "risk groups rank patients well; they are not calibrated probabilities of "
                   "death.")

    if TL:
        st.subheader("MSK-CHORD landmark models")
        st.markdown(f"{badge(workspace.VALIDATED)} · {TL['task']} · the synthetic patient's file")
        st.dataframe(pd.DataFrame([{
            "From month": int(k), "Patients": m["n"], "Event rate": m["event_rate"],
            "AUROC, record so far": f"{m['auroc'][0]:.3f} ± {m['auroc'][1]:.3f}",
            "AUROC, diagnosis only": f"{m['baseline_auroc'][0]:.3f} ± "
                                     f"{m['baseline_auroc'][1]:.3f}"}
            for k, m in sorted(TL["models"].items(), key=lambda kv: int(kv[0]))]),
            hide_index=True, column_config={
                "From month": st.column_config.NumberColumn(
                    help="Landmark: months after the first tumor sequencing"),
                "Event rate": st.column_config.NumberColumn(format="percent")})
        st.caption(
            "Gradient boosting on the record so far, against the same learner on the diagnosis "
            "alone (stage, HR, HER2); held-out AUROC, mean ± sd over 5 seeds. "
            + TL["model_note"] + " Some features reflect care, not only biology (how often labs "
            "and treatments are recorded). Whether the probabilities are calibrated has not "
            "been checked.")

    st.subheader("Alert rules")
    st.dataframe(pd.DataFrame([
        ("Progression on imaging", OBSERVED, "the imaging report reads progression",
         "recorded"),
        ("New metastatic site", OBSERVED, "a site not in the record before", "recorded"),
        ("Tumor marker rise", OBSERVED,
         f"above the reference limit and at least {workspace.RISE:.0%} above the previous "
         "value; to be confirmed with a second specimen within a month",
         workspace.EGTM + "; the limit from the patient's lab report"),
        ("Risk jump", INFERENCE,
         f"12-month risk up at least {workspace.RISK_JUMP} points since the previous result",
         "placeholder, not validated"),
        ("Newly sequenced driver", f"{OBSERVED} (mutation), {HYPOTHESIS} (evidence)",
         "level A or B CIViC treatment evidence", "CIViC evidence levels"),
    ], columns=["Alert", "Evidence", "Rule", "Threshold source"]), hide_index=True,
        width="stretch")
    st.caption("A tumor marker out of range is not evidence of progression by itself.")

    st.subheader("Case note")
    st.markdown(f"""
- **{model_name(DEFAULT_MODEL)} plans** on Nebius Token Factory: it decides which tools to call.
  The tools run locally and label what they return: `observed_findings` (*observed*: measured
  and missing data layers, recorded stage, age band, the sequenced driver mutations from GDC
  open-access somatic calls, or "not sequenced"), `predict_risk`, `modality_contributions` and
  `top_features` (*model inference*, with the model's validation C-index as its uncertainty),
  `treatment_evidence` (*hypothesis*: CIViC items for the observed mutations) and
  `search_literature` (*hypothesis*: Tavily search for papers or trials on up to 3 named genes).
- **{model_name(WRITER_MODEL)} writes** the note from the tool outputs, in five sections:
  Summary, Observed, Model inferences, Hypotheses and evidence, Caveats. Every bullet starts
  with [Observed], [Model inference] or [Hypothesis]. If it fails, {model_name(DEFAULT_MODEL)}
  writes.
- **A grounding check** (plain code, no language model) looks for any number, gene or link in
  the note that no tool returned. The writer gets one rewrite; anything left is shown with the
  note.
- **Treatment content is evidence, not advice.** Each CIViC (CC0) item keeps its evidence level
  (A validated … E inferential), significance, citation and link, for clinician review, never
  a recommendation.
- Only derived numbers (risk, percentile, contributions, attribution scores) and gene or
  mutation names go to Token Factory and Tavily, never a patient's omics values, and nothing
  from MSK-CHORD. Every call counts against a hard spending cap; once it is reached, or without
  a key, the same tools run in a fixed order and a template writes the note.
""")

    st.header("Federated training across simulated hospitals")
    left, right = st.columns([2, 3])
    with left:
        dot = ["digraph { rankdir=LR; bgcolor=transparent; size=\"5,3\"; node [shape=box, "
               "style=rounded, fontname=Helvetica, fontsize=11]; edge [fontname=Helvetica, "
               "fontsize=9];",
               'server [label="NVIDIA FLARE server\\nFedAvg", shape=box, style="rounded,bold"];']
        for s in demo.sites:
            dot.append(f'"{s.name}" [label="{s.name} (simulated)\\n{s.patients} patients\\n'
                       f'data stays here"];')
            dot.append(f'"{s.name}" -> server [label="weights", dir=both];')
        st.graphviz_chart("\n".join(dot) + "}", width="content")
    with right:
        table = pd.DataFrame([{
            "Hospital": s.name, "Patients": s.patients, "Deaths": s.deaths,
            "Held out": s.heldout,
            **{LAYER_NAMES.get(m, m): 100 * s.coverage[m] for m in demo.model.names
               if m != "clinical"},
        } for s in demo.sites])
        st.dataframe(table, hide_index=True, column_config={
            LAYER_NAMES.get(m, m): st.column_config.ProgressColumn(
                LAYER_NAMES.get(m, m), format="%.0f%%", min_value=0, max_value=100, width="small")
            for m in demo.model.names if m != "clinical"})
        st.caption("Bars: share of each hospital's patients with that data layer. The hospitals "
                   "are simulated: TCGA tissue source sites grouped into three clients of the "
                   "NVFlare simulator, so the data gaps are real but no real site took part.")

    st.header("Data sources and licenses")
    st.dataframe(pd.DataFrame([
        ("TCGA-BRCA (GDC open access, UCSC Xena)", "the survival model and the TCGA patient files",
         "open access; cite the TCGA Research Network"),
        ("GDC masked somatic mutations (open access)", "observed driver mutations", "as TCGA"),
        ("MSK-CHORD (Jee et al., Nature 2024)",
         "the landmark models behind the synthetic patient's risk; used on this machine only, "
         "aggregate results", "CC BY-NC-ND 4.0"),
        ("CIViC clinical evidence summaries", "treatment evidence for clinician review", "CC0"),
        ("Tavily search", "literature leads in case notes", "Tavily API terms"),
        ("NVIDIA Nemotron 3 Super and Ultra on Nebius Token Factory", "the case note",
         "NVIDIA open model license; Token Factory terms"),
        ("EGTM breast cancer recommendations", "the tumor-marker rise rule", "cited"),
    ], columns=["Source", "Used for", "License or terms"]), hide_index=True, width="stretch")
    st.caption("SYNTHETIC-001's record is written by hand and labeled synthetic; it is not a "
               "real person and was not taken from any dataset.")

    st.header("Limits")
    st.markdown(
        "- On overall survival in TCGA-BRCA the omic layers don't beat clinical data yet; "
        "federation matches pooling and beats a single hospital.\n"
        "- TCGA holds one tumor sample per patient, so its files have one version and no "
        "alerts.\n"
        "- Only the lab, mutation and data-layer workbenches are built; imaging, pathology, "
        "ctDNA and test import are planned and labeled so.\n"
        "- The hospitals are simulated, and SYNTHETIC-001 is synthetic.\n"
        "- Research and decision support for clinicians; not a diagnosis or a prescription.")


st.navigation([
    st.Page(patients_page, title="Patients", icon="🗂️", default=True),
    st.Page(methods_page, title="Methods and validation", icon="📖", url_path="methods"),
]).run()

if LIVE:
    notes_left = max(0, CAP - st.session_state.live_used)
    budget_slot.progress(notes_left / CAP if CAP else 0,
                         text=f"Live notes left this session: {notes_left} of {CAP}")
