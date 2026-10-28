"""MuFFLe++: the clinician app of a breast cancer intelligence platform (milestone 1).

streamlit run app/streamlit_app.py -- --ckpt outputs/tcga_fedavg.pt --data data/tcga_brca
streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic
streamlit run app/streamlit_app.py -- --bundle outputs/demo_bundle.pt     # the hosted setup

Without the checkpoint and cohort (the hosted demo), it loads a demo bundle instead: --bundle or
MUFFLE_BUNDLE (a path or URL; default: the GitHub release asset). For a private repo's release,
set GITHUB_TOKEN to a token that can read the repo.

Three pages (docs/WORKSPACE.md, "Product framing"). Patients is the clinician workspace: a list of
patient files, the synthetic timeline patient first (its 12-month risk re-predicted at each event
by the MSK-CHORD models; app/timeline_synthetic.json from `make demo-timeline`), then the held-out
TCGA cases. A file opens on its latest report, with an SOS tile, its tests and their workbenches,
and a timeline of report versions; ?patient=<id> opens one. Methods and validation holds the model
cards, alert rules, how the case note is made, federated training and the data sources. Feedback
(app/feedback_page.py) holds the session's review marks as a ledger (docs/feedback.md). No
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
import logging
import os
import sys
import tempfile
import threading
from collections import Counter
from datetime import datetime
from functools import partial
from pathlib import Path

APP = Path(__file__).parent
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import torch  # noqa: E402

# The app scores one patient at a time; torch's thread pool only adds contention on a shared
# CPU (single-row masked effects: 1.8 s with 8 threads at load ~3, 8 ms with 1). Per thread,
# so it runs on every rerun: Streamlit runs each in a new thread.
torch.set_num_threads(1)

from muffle.hotreload import purge_modules, source_digest  # noqa: E402

# ponytail: Streamlit Cloud hot-updates this file but keeps the modules this process already
# imported (charts.py, src/muffle), which crashed the hosted app twice on Oct 19 (AttributeError
# on charts.risk_timeline, ImportError on muffle.demo.evidence_lookup). When the sources differ
# from what this process last ran, drop those modules and the caches their old code built.
CODE_DIGEST = source_digest([APP, APP.parent / "src" / "muffle"])
if getattr(sys, "_muffle_code_digest", None) != CODE_DIGEST:  # every module of app/ and src/muffle
    purge_modules((*(p.stem for p in APP.glob("*.py") if p.stem != "streamlit_app"),
                   "muffle", "workbenches"))
    st.cache_resource.clear()
    st.cache_data.clear()
    sys._muffle_code_digest = CODE_DIGEST

import charts  # noqa: E402
import timeline_page  # noqa: E402
from workbenches import evolution as evolution_page  # noqa: E402
from workbenches import genomics, labs, omics  # noqa: E402
from workbenches._page import dated_focus, land, line_and_action, strict  # noqa: E402

import guide  # noqa: E402
import navigation as nav  # noqa: E402

from muffle import cohort, crosstest, evolution, memo, overview, workspace  # noqa: E402
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
from muffle.workbench.radiology import load_index  # noqa: E402
from muffle.report.grounding import describe  # noqa: E402
from muffle.report.nemotron import (  # noqa: E402
    DEFAULT_MODEL,
    WRITER_MODEL,
    CaseReport,
    model_name,
    run_case_agent,
    tavily_search,
)
from muffle.workbench.documents import case_documents  # noqa: E402
from muffle.workbench.grammar import WORKBENCHES as WORKBENCH_NAMES  # noqa: E402
from muffle.workbench.grammar import chip, esc  # noqa: E402

REPO = "https://github.com/ps131-cell/muffle-plus-plus"
LOG = logging.getLogger("muffle.app")
BUNDLE_RELEASE = "demo-bundle-v2"  # bump once the next release exists (scripts/make_demo_bundle.py)
BUNDLE_URL = f"{REPO}/releases/download/{BUNDLE_RELEASE}/demo_bundle.pt"
LAYER_NAMES = {"clinical": "Clinical", "rna": "RNA expression", "genomic": "Copy number",
               "methylation": "Methylation", "protein": "Protein"}
PLANNED_WORKBENCHES: dict[str, str] = {}  # workbench -> what it will show, for planned ones

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
    """CIViC's table once per process; None (no treatment_evidence tool) if it can't load. Each
    variant is looked up in it once (``muffle.memo.calls``)."""
    lookup = evidence_lookup()
    return None if lookup is None else memo.calls(lookup)


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
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE, HYPOTHESIS) if e in text)


def badge(status: str) -> str:
    return chip(status)


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
st.session_state.setdefault("imports", {})  # patient id -> this session's imports

TL = timeline()
SOURCE = args.bundle or (f"{args.ckpt}|{args.data}" if Path(args.ckpt).exists() and
                         (Path(args.data) / "cohort.npz").exists() else BUNDLE_URL)


@st.cache_resource(show_spinner=False)
def bundle_files(source: str, notes: str, code: str) -> tuple[dict, dict]:
    """The patient files the bundle (``source``) and the repo's data hold, and each TCGA file's
    held-out case: built once per bundle, saved notes and code version, and shared by every
    session. A file is never changed in place (an import makes a new one), so what is computed
    from it is kept with it (``muffle.memo``)."""
    files, cases = {}, {}  # patient id -> PatientFile; and for a TCGA file, its held-out case
    if TL:
        synthetic = workspace.synthetic_file(TL)
        files[synthetic.id] = synthetic
    slide_cases = APP / "workbenches" / "slides_results" / "cases.json"  # index -> scored slides
    slide_cases = json.loads(slide_cases.read_text()) if slide_cases.exists() else {}
    imaging = load_index(APP / "workbenches" / "radiology_results")  # public TCIA studies by case
    for c in sorted(demo.cases, key=lambda c: (c.index not in demo.notes, -c.percentile)):
        pf = workspace.case_file(c, demo.c_index, slides=slide_cases.get(str(c.index), ()),
                                 documents=case_documents(c.index),
                                 imaging=imaging.get(c.index))
        files[pf.id], cases[pf.id] = pf, c
    return files, cases


BUNDLE_FILES, CASES = bundle_files(SOURCE, args.notes, CODE_DIGEST)  # read-only: shared
FILES = dict(BUNDLE_FILES)  # this session's: its imports replace files below


def civic_items(pf: workspace.PatientFile, variant: str) -> list[dict] | None:
    """CIViC items for a variant: the synthetic patient's record variants are frozen with the
    timeline file; others (a TCGA file's, an imported one's) come from the live table (None if
    it couldn't load)."""
    if pf.kind == "synthetic" and variant in TL["evidence"]:
        return TL["evidence"][variant]
    if EVIDENCE is None:
        return None
    gene, change = variant.split(maxsplit=1)
    return EVIDENCE(gene, change)


for pid, records in st.session_state.imports.items():  # each import adds a report version
    for r in records:
        FILES[pid] = workspace.add_version(FILES[pid], **r["version"],
                                           evidence=partial(civic_items, FILES[pid]))

# --- sidebar: what is running, and this session ------------------------------------------------
with st.sidebar:
    st.markdown("### MuFFLe++")
    st.caption("Breast cancer intelligence: an evidence-linked patient profile that updates as "
               f"the record grows. {DISCLAIMER}")
    with st.expander("About this system"):  # provenance: the model, the agent, the evidence
        civic_line = ("CIViC (CC0), for clinician review" if EVIDENCE else
                      "off (CIViC table unavailable)")
        st.markdown(
            f"**Model** · FedAvg across {len(demo.sites)} simulated hospitals (NVIDIA FLARE)  \n"
            f"**Held-out C-index** · {demo.c_index:.3f}  \n"
            f"**Case agent** · {'live' if LIVE else 'offline (no key)'}: "
            f"{model_name(DEFAULT_MODEL)} plans, {model_name(WRITER_MODEL)} writes, on Nebius "
            f"Token Factory  \n"
            f"**Treatment evidence** · {civic_line}  \n"
            f"**Literature** · {'Tavily search on' if SEARCH else 'off (no Tavily key)'}")
        st.caption("Every model, rule and data source: the Methods and validation page. "
                   f"[Source code]({REPO})")
    st.markdown("**Session**")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5,
                  help="Saved with each review mark. Marks and pins stay in this browser "
                       "session and go into the report export.")
    budget_slot = st.empty()  # filled at the end, after this run's live note (if any)
    marks_slot = st.empty()   # this session's marks, filled at the end of the run


def session_marks(slot):
    """The sidebar's tally of this session's review marks and pins, with their export (they
    also go into each report version's export)."""
    reviews, pins = st.session_state.reviews, st.session_state.pins
    with slot.container():
        st.caption(f"{len(reviews)} review mark{'' if len(reviews) == 1 else 's'} and "
                   f"{len(pins)} pin{'' if len(pins) == 1 else 's'} in this session, kept in this "
                   "browser session and in each report's export.")
        if reviews or pins:
            rows = [{"patient": k.split("|")[0], "kind": k.split("|")[1], "finding": r["what"],
                     "mark": r["mark"], "by": r["by"], "at": r["at"]}
                    for k, r in reviews.items()] + [
                {"patient": k.split("|")[0], "kind": k.split("|")[1], "finding": w,
                 "mark": "pinned", "by": "", "at": ""} for k, w in pins.items()]
            st.download_button("Download this session's marks (CSV)",
                               pd.DataFrame(rows).to_csv(index=False),
                               file_name="review_marks_this_session.csv", mime="text/csv",
                               key="session-marks-csv",
                               help="Every mark and pin of this session, with the reviewer's "
                                    "initials and time")


# --- Patients: the list -----------------------------------------------------------------------
def to_list():
    st.session_state.update(patient=None, view="Report")


def open_file(pid: str):
    """A start, pinned or recently opened file's button: open it on its report."""
    st.session_state.update(patient=pid, view="Report")


START = (  # the first visit's two files: (id, the button, what the file shows)
    ("SYNTHETIC-001", "Open the longitudinal example: SYNTHETIC-001",
     "One synthetic patient over 24 months, written by hand: labs, ctDNA, imaging reads, "
     "clinic notes and the 12-month risk at each step."),
    ("Case 299", "Open a case with its own slide and sequencing: Case 299",
     "A public TCGA-BRCA case: its own H&E section scored tile by tile, its mutations and its "
     "pathology report, read by rules."),
)


def start_here():
    """Before any file is opened in this browser session: two files to begin with."""
    picks = [s for s in START if s[0] in FILES]
    if st.session_state.get("recent") or not picks:
        return
    with st.container(border=True, key="start-here"):
        st.markdown("**Start here** · two files that show what the app does")
        with st.container(horizontal=True, gap="medium"):  # side by side; stacked when narrow
            for n, (pid, label, what) in enumerate(picks):
                with st.container(width=340):
                    st.button(label, key=f"start-{pid}", on_click=open_file, args=(pid,),
                              type="primary" if n == 0 else "secondary", help=what)
                    st.caption(what)


def toggle_file_pin(pid: str):
    """"Pin this file": it sits at the top of the Patients page for this browser session."""
    pinned = st.session_state.setdefault("pinned_files", [])
    if pid in pinned:
        pinned.remove(pid)
    else:
        pinned.append(pid)


def patients_page():
    """The breadcrumbs (whose file crumb is the file picker, bound to ?patient) head every
    screen of this page; the sticky patient header holds them while a file is open."""
    header = st.container(key="patient-header")
    with header:
        row = st.container(horizontal=True, gap="xsmall", vertical_alignment="center")
    with row:
        first = st.empty()
        st.markdown(nav.SEP, width="content")
        pid = st.selectbox(
            "Patient file", list(FILES), index=None, key="patient", bind="query-params",
            placeholder="Open a file by its ID", label_visibility="collapsed", width=240,
            help="Every patient file has its own address (…?patient=<id>); the list below "
                 "searches everything.")
        tail = st.container(horizontal=True, gap="xsmall", vertical_alignment="center",
                            width="content")
        st.space("stretch")  # pushes the guide's "?" to the line's right end
        help_slot = st.container(width="content")  # the "?", for the screen drawn below
    if pid is None:
        first.markdown("**Patients**", width="content")
        with help_slot:
            guide.help_icon("patients")
        st.title("MuFFLe++")
        st.markdown("An evidence-linked picture of each patient's breast cancer, updated as "
                    "the record grows. Every finding is marked **observed**, **model "
                    "inference** or **hypothesis**.")
        st.caption(DISCLAIMER)
        start_here()
        guide.walkthrough()
        for name, key, prefix in (("Pinned", "pinned_files", "pinned"),
                                  ("Recently opened", "recent", "recent")):
            files = [p for p in st.session_state.get(key, []) if p in FILES]
            if files:
                with st.container(horizontal=True, gap="small", vertical_alignment="center"):
                    st.caption(f"{name}:", width="content")
                    for p in files:
                        st.button(p, key=f"{prefix}-{p}", on_click=open_file, args=(p,),
                                  help=f"Open {p} on its latest report")
        nav.sync(None, None, None, None)  # no file open: no test, pointer or version
        # cohort-search hook 1 of 2 (muffle.cohort, docs/cohort.md): "Search every file", above
        # the patient list and apart from its search. Keep this call when reshaping the page.
        safely("The search across every file", cohort_search)
        safely("The patient list", patient_list)
    else:
        first.button("Patients", type="tertiary", key="crumb-patients", on_click=to_list,
                     help="Back to the patient list")
        screen = patient_file(FILES[pid], header, tail)
        with help_slot:
            guide.help_icon(screen)


def open_selected():
    """Row click in the patient list: open that file (with a fresh list for next time)."""
    rows = st.session_state[f"list-{st.session_state.list_n}"].selection.rows
    if rows:
        st.session_state.patient = st.session_state.list_ids[rows[0]]
        st.session_state.list_n += 1


@st.cache_data(show_spinner=False)
def bundle_rows(source: str, code: str) -> dict[str, dict]:
    """The list's search and filter fields of the files the bundle (``source``) and the repo's
    data hold, once per bundle and code version; a file an import changed is read live."""
    return {pid: overview.list_row(pf) for pid, pf in BUNDLE_FILES.items()}


def risk_text(pf: workspace.PatientFile, case) -> str:
    """The list's risk column: the cohort percentile of a TCGA file, the synthetic patient's
    latest 12-month risk (another measure, said so)."""
    if case is not None:
        return f"{ordinal(case.percentile)} percentile ({case.group})"
    r = next((v.risk for v in reversed(pf.versions) if v.risk and "value" in v.risk), None)
    return f"12-month {r['value']:.0%}" if r else "not estimated"


def sos_badge(n: int) -> str:
    """Open SOS alerts in words, marked so the count never rests on color alone."""
    return f"🔴 {n} open" if n else "none"


def patient_list():
    base, reviews, rows = bundle_rows(SOURCE, CODE_DIGEST), st.session_state.reviews, []
    for pid, pf in FILES.items():
        case = CASES.get(pid)
        rows.append({**(base[pid] if pf is BUNDLE_FILES.get(pid) else overview.list_row(pf)),
                     "diagnosis": pf.diagnosis, "latest": pf.latest.label,
                     "kind": "Synthetic (written by hand)" if case is None
                             else f"TCGA-BRCA · simulated {case.site}",
                     "note": "★" if case and case.index in demo.notes else "",
                     "percentile": None if case is None else case.percentile,
                     "risk": risk_text(pf, case), "updated": pf.latest.month,
                     "imported": bool(pf.versions[-1].imported)})
    st.markdown("**Your patient files.** Open one to see its latest report, its tests in their "
                "workbenches and how the report changed over time.")
    q, sos = line_and_action()
    query = q.text_input("Search", key="list-search", label_visibility="collapsed",
                         placeholder="Find by ID, diagnosis, gene (PIK3CA), subtype (luminal), "
                                     "stage (III) or workbench (slides)",
                         help="Every word must match the file's ID, diagnosis, PAM50 subtype, "
                              "stage, mutated genes or the workbenches that hold its data")
    open_sos = sos.toggle("Open SOS alerts only", key="list-sos",
                          help="Files with an alert no reviewer has marked yet.")
    f = st.columns([2, 2, 1])
    subtypes = f[0].multiselect("PAM50 subtype", sorted({r["subtype"] for r in rows}),
                                key="list-subtype", placeholder="Any subtype",
                                help="Model inference from bulk RNA; 'not called' without RNA")
    genes = f[1].multiselect("Mutated gene", sorted({g for r in rows for g in r["genes"]}),
                             key="list-gene", placeholder="Any gene",
                             help="Files with an observed driver mutation in any of these genes")
    stages = f[2].multiselect("Stage", [s for s in ("I", "II", "III", "IV", "not recorded")
                                        if any(r["stage"] == s for r in rows)],
                              key="list-stage", placeholder="Any",
                              help="The recorded stage; 'not recorded' when the record has none")
    with st.container(horizontal=True, gap="large"):  # wraps on a narrow screen, never cuts
        holds = st.pills("Has", ["Slides", "Imaging", "Documents"], selection_mode="multi",
                         key="list-holds",
                         help="Files that hold their own data for each one chosen")
        by = st.segmented_control("Sort by", overview.SORTS, default=overview.SORTS[0],
                                  required=True, key="list-sort",
                                  help="Last update: an import of this session, then the "
                                       "record's latest month. Risk: the cohort percentile of the "
                                       "TCGA files (the synthetic patient's 12-month risk is "
                                       "another measure, listed after them). Open SOS: alerts no "
                                       "reviewer has marked.")
    shown = overview.sort_rows(overview.filter_rows(rows, query, subtypes, genes, stages,
                                                    open_sos, holds or (), reviews), by, reviews)
    table = pd.DataFrame([{
        "Patient": r["id"], "Open SOS": sos_badge(overview.open_alerts(r, reviews)),
        "Kind": r["kind"], "Diagnosis": r["diagnosis"],
        "Risk": r["risk"], "Subtype (PAM50)": r["subtype"], "Mutated genes": r["genes"],
        "Workbenches with data": r["holds"], "Latest report": r["latest"],
        "Saved note": r["note"]}
        for r in shown], columns=["Patient", "Open SOS", "Kind", "Diagnosis", "Risk",
                                  "Subtype (PAM50)", "Mutated genes", "Workbenches with data",
                                  "Latest report", "Saved note"])
    st.session_state.list_ids = table["Patient"].tolist()
    st.dataframe(table, hide_index=True, on_select=open_selected, selection_mode="single-row",
                 key=f"list-{st.session_state.list_n}", width="stretch", column_config={
                     "Patient": st.column_config.TextColumn(pinned=True),
                     "Open SOS": st.column_config.TextColumn(
                         help="SOS alerts no reviewer has marked yet, in this session"),
                     "Risk": st.column_config.TextColumn(
                         help="Model inference. TCGA files: the cohort percentile of overall "
                              "survival risk (group by tertile); the synthetic patient: the "
                              "latest 12-month risk of progression or death, another model"),
                     "Mutated genes": st.column_config.ListColumn(
                         help="Observed driver mutations; an empty cell is not sequenced or "
                              "none found (the file says which)"),
                     "Workbenches with data": st.column_config.ListColumn(
                         help="The workbenches that hold this patient's own data"),
                     "Subtype (PAM50)": st.column_config.TextColumn(
                         help="Model inference from bulk RNA (Methods and validation); 'not "
                              "called' without RNA")})
    st.caption(
        f"{len(shown)} of {len(rows)} files. Click a row to open the file. SYNTHETIC-001 is a "
        "synthetic patient, written by hand. The TCGA cases are public TCGA-BRCA patients the "
        "risk model never trained on, each assigned to one of the simulated hospitals; TCGA holds "
        "one tumor sample per patient, so their files have one version. ★ = a saved case note.")


# --- Across the files: one search, similar patients, where a patient sits (muffle.cohort) -------
SHOW_FOUND = 12  # files a search lists before "narrow the search"


@st.cache_data(show_spinner="Reading every file's findings (once per server start)…")
def bundle_index(source: str, code: str, civic: bool) -> list[dict]:
    """Every finding of the files the bundle (``source``) and the repo's data hold, once per
    bundle, code version and CIViC availability (``civic``: levels in the variants' text)."""
    return cohort.build_index(BUNDLE_FILES, EVIDENCE)


@st.cache_data(show_spinner=False)
def bundle_profiles(source: str, code: str) -> dict[str, dict]:
    """The similarity and position fields of the bundle's files (``cohort.profile``)."""
    rows = bundle_rows(source, code)
    return {pid: cohort.profile(pf, rows[pid]) for pid, pf in BUNDLE_FILES.items()}


def changed_files() -> list[str]:
    """Files an import of this session changed: read live, not from the bundle's caches."""
    return [pid for pid, pf in FILES.items() if pf is not BUNDLE_FILES.get(pid)]


def search_index() -> list[dict]:
    """The bundle's index with this session's imported files read again (once per version)."""
    base, changed = bundle_index(SOURCE, CODE_DIGEST, EVIDENCE is not None), changed_files()
    if not changed:
        return base
    memo = st.session_state.setdefault("cohort_entries", {})
    for pid in changed:
        pf = FILES[pid]
        key = (CODE_DIGEST, pid, len(pf.versions))
        if key not in memo:
            memo[key] = cohort.entries(pf, None if pf.kind == "synthetic" else EVIDENCE)
    return [e for e in base if e["patient"] not in changed] + [
        e for pid in changed for e in memo[(CODE_DIGEST, pid, len(FILES[pid].versions))]]


def profiles() -> dict[str, dict]:
    base, changed = bundle_profiles(SOURCE, CODE_DIGEST), changed_files()
    return {pid: cohort.profile(pf) if pid in changed else base[pid] for pid, pf in FILES.items()}


def cohort_search():
    """"Search every file": every file's findings at once (finding cards, attention items, tests
    that disagree, documented facts, variants, methylation calls, hypotheses, the file profile),
    in plain words; each matching file with its best finding, its evidence label and an Open
    that lands on it (the deep link in its help)."""
    with st.container(border=True, key="cohort-search-box"):
        query = st.text_input(
            "Search every file", key="cohort-search",
            placeholder="Search every file's findings: ESR1 methylated, HER2 disagree, breakaway, "
                        "washout, level A, basal, stage III PIK3CA",
            help="Every word must be in one finding of a file (else, said so, across its "
                 "findings), at a word's start: 'basal' finds Basal-like, 'methylated' not "
                 "unmethylated. 'level A', 'stage III', 'grade 3', 'ER positive' and 'ESR1 "
                 "methylated' read as phrases; \"quotes\" make any phrase. Files rank by how many "
                 "of their findings match. The box above the list searches patients by ID, "
                 "gene, subtype or stage.")
        if not query.strip():
            st.caption("Searches the findings of all files at once: the workbenches' cards and "
                       "attention items, tests that disagree, documented facts, variants, "
                       "methylation calls and evolution hypotheses, each with its evidence label.")
            return
        labels = st.pills("Evidence", cohort.LABELS, selection_mode="multi",
                          key="cohort-labels", help="Keep only findings of these labels")
        found = cohort.search(search_index(), query, labels or ())
        pats = found["patients"]
        if not pats:
            st.info(f"No finding in any file matches “{query}”" + (
                " with the evidence chosen" if labels else "") + ". Imported tests of this "
                "session are searched too; a word must start a word of the finding.", icon="🔎")
            return
        st.caption(f"{len(pats)} file{'s' if len(pats) != 1 else ''} · "
                   + ("no single finding holds every word, so these files hold them across "
                      "their findings · " if found["across"] else "")
                   + "ranked by matching findings, then how close the words sit, then evidence "
                     "(observed, model inference, hypothesis) · a text lookup, not a model")
        for n, p in enumerate(pats[:SHOW_FOUND]):
            f, rest = p["findings"][0], p["findings"][1:]
            body = f["text"] if f["text"].startswith(f["what"]) else f"{f['what']}: {f['text']}"
            synthetic = " (synthetic)" if FILES[p["patient"]].kind == "synthetic" else ""
            line, act = line_and_action()
            line.markdown(f"**{p['patient']}**{synthetic} · {esc(shorten(body, 200))}  \n"
                          f"{chip(f['label'])} {chip(f['workbench'])} {chip(f['kind'])}")
            if rest:
                with act.popover(f"+{len(rest)}", help="This file's other matching findings"):
                    st.markdown("\n".join(f"- {esc(shorten(r['what'] + ': ' + r['text'], 160))} "
                                          f"{chip(r['label'])}" for r in rest[:10]))
                    if len(rest) > 10:
                        st.caption(f"and {len(rest) - 10} more")
            act.button("Open", key=f"cohort-open-{n}", on_click=open_finding,
                       args=(f["patient"], f["opens"], f["focus"], f["pointer"]),
                       help=f"Opens {p['patient']} at this finding: {f['link']}")
        if len(pats) > SHOW_FOUND:
            st.caption(f"Showing {SHOW_FOUND} of {len(pats)} files: add a word to narrow it.")


@st.cache_data(show_spinner=False, max_entries=64)
def strip_specs(pid: str, source: str, code: str) -> list[dict]:
    """A bundle file's cohort position with one small chart per score, built once per file."""
    base = bundle_profiles(source, code)
    pos = cohort.cohort_position(base[pid], base)
    return [{**m, "spec": charts.cohort_strip(m["values"], pid, m["axis"]).to_dict()}
            for m in pos["metrics"]]


STRIP_WIDTH = 190  # px: cards of one width wrap, two a row at 800 px, four at 1280


def cohort_sections(pf: workspace.PatientFile):
    """Where this patient sits among the TCGA files (a small chart per score, the patient
    marked) and the five most similar TCGA files (the fields shared and those that differ):
    lookups and percentiles on the file's latest fields, never a model or a prognosis."""
    profs = profiles()
    p, n_tcga = profs[pf.id], sum(q["kind"] == "TCGA-BRCA" for q in profs.values())
    st.markdown(f"**Where this patient sits** among the {n_tcga} TCGA files "
                f"{chip('lookup, not a prognosis')}")
    if pf.kind != "TCGA-BRCA":
        st.caption(f"{pf.id} is a synthetic patient, written by hand, and is not in this cohort: "
                   "its 12-month risk comes from other models (MSK-CHORD) and it has no scores "
                   "measured the way the TCGA files' are.")
    else:
        metrics = strip_specs(pf.id, SOURCE, CODE_DIGEST) if pf.id not in changed_files() else [
            {**m, "spec": charts.cohort_strip(m["values"], pf.id, m["axis"]).to_dict()}
            for m in cohort.cohort_position(p, profs)["metrics"]]
        with st.container(horizontal=True, gap="small"):
            for m in metrics:
                with st.container(border=True, width=STRIP_WIDTH, gap="xsmall"):
                    st.markdown(f"**{m['name']}**  \n{ordinal(m['percentile'])} percentile of "
                                f"{m['n']}  \n{tags(m['label'])}",
                                help=f"{m['source']}; this patient {m['value']:.2f} "
                                     f"({m['axis']})")
                    st.vega_lite_chart(spec=m["spec"], width="stretch",
                                       alt=f"{m['name']} of {m['n']} TCGA files, this patient "
                                           f"at the {m['text']}")
                    st.caption(m["axis"])
        st.caption("Each tick is a TCGA file, the blue dot this patient; the percentile is the "
                   "share of the other files with a lower value. These percentiles are among "
                   f"these {n_tcga} files: the workbenches' percentiles are against the whole TCGA "
                   "cohort, so they differ. The synthetic patient is not in this cohort. "
                   "Percentiles, not a prognosis.")
    sim = cohort.similar_patients(p, profs)
    st.markdown(f"**Similar patients** · the {len(sim['nearest'])} nearest of "
                f"{sim['candidates']} TCGA files {chip(cohort.LOOKUP)} "
                f"{chip('placeholder weights')}")
    fields = len(cohort.FIELDS)
    with st.container(border=True):
        for n, r in enumerate(sim["nearest"]):
            line, act = line_and_action()
            line.markdown(f"**{r['patient']}** · agrees on {r['score'] * fields:.1f} of {fields}"
                          " · shares " + (esc(" · ".join(shorten(x["said"], 70)
                                                         for x in r["shared"])) or "no field"))
            differ = [f"{x['field']}: {shorten(x['here'] or 'none', 50)} here, "
                      f"{shorten(x['there'] or 'none', 50)} there"
                      + (f" (both: {shorten(x['both'], 40)})" if x["both"] else "")
                      for x in r["differ"]]
            line.caption(esc("Differs · " + "; ".join(differ) if differ else "Differs on no "
                             "field compared") + (" · not compared: " + ", ".join(r["missing"])
                                                  if r["missing"] else ""))
            act.button("Open", key=f"similar-{pf.id}-{n}", on_click=open_file,
                       args=(r["patient"],), help=f"Open {r['patient']} on its latest report")
    st.caption("A lookup on recorded and derived fields, not a model and not a prognosis: the "
               "share of " + ", ".join(name for name, _ in cohort.FIELDS.values()) + " on which "
               "the two files agree (sets by the share of items in common), every field weighing "
               "the same (placeholder); a field either file lacks counts as not shared. "
               "Candidates are the TCGA files only; the synthetic patient is never one. Each "
               "file's latest report is compared.")


# --- Patients: one patient file ----------------------------------------------------------------
VIEWS = ("Report", "Tests", "Timeline", "Evolution", "Import tests")
VIEW_ICONS = {"Timeline": ":material/timeline:", "Evolution": ":material/account_tree:",
              "Import tests": ":material/upload_file:"}  # on every button that opens the view


def safely(what: str, draw, *args, spin: str | None = None, **kwargs):
    """Draw one part of a screen, with a spinner saying what loads (``spin``). When it fails,
    say which part in plain words and where its method and known failures are described, never
    a traceback; the server's log keeps the traceback, and the tests re-raise
    (``_page.strict``)."""
    try:
        if spin:
            with st.spinner(spin):
                return draw(*args, **kwargs)
        return draw(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 - the clinician gets a sentence, the log the traceback
        if strict():
            raise
        LOG.exception("%s could not be drawn", what)
        st.error(f"{what} could not be drawn. The rest of the file works: the other views and "
                 "tests open as usual. How this part is built, and its known failures, are on "
                 "the Methods and validation page.", icon="⚠️")
        st.page_link(METHODS, label="Methods and validation", icon="📖",
                     help="Every model and rule, with its numbers and known failures")
        st.caption(f"Logged for the team: {type(e).__name__}.")
        return None
SCREENS = {"labs": "labs", "mutations": "genomics", "slides": "slides", "omics": "omics",
           "record": "omics", "documents": "documents", "imaging": "radiology",
           "ctdna": "ctdna", "intake": "imports"}  # a test's workbench -> its guide entry


def patient_file(pf: workspace.PatientFile, header, tail):
    """One file: the sticky header (breadcrumbs, the patient, open SOS alerts, the views), the
    report version, then the view. A deep link's ?test, ?pointer and ?version are applied once
    (``navigation.fresh``); after the view is drawn the address is written back
    (``navigation.sync``) so that it reopens this screen."""
    ss = st.session_state
    nav.remember(pf.id)
    nav.sticky_css()
    last = len(pf.versions) - 1
    link = nav.fresh(pf.id)
    linked = apply_link(pf, link, last) if link else None
    with header:
        ident = st.empty()
        if "view" not in ss and "view" not in st.query_params:
            ss.view = "Report"  # no default=: "open the test" sets the view in code
        # no format_func (icons): a bound widget puts its formatted label in the address, so
        # ?view=Tests would no longer open Tests; an address naming no view opens the report
        view = st.segmented_control("View", VIEWS, required=True, key="view",
                                    bind="query-params", label_visibility="collapsed",
                                    help="This file's views: its report, its tests in their "
                                         "workbenches, the timeline, evolution, imports") \
            or "Report"
    # right under the sticky header, filled once the view is drawn: it scrolls away with the
    # page (two lines of buttons would make the header a third of a laptop screen)
    actions = st.container(horizontal=True, gap="small", vertical_alignment="center",
                           key="file-actions")
    st.caption(f"{pf.title} · {pf.diagnosis}  \n{DISCLAIMER}")
    if pf.kind == "synthetic":
        st.warning(pf.note, icon="🧪")
    key = f"version-{pf.id}"
    if last and key not in ss:
        ss[key] = last
    i = last if not last else st.select_slider(
        "Report version", options=range(last + 1), key=key,
        format_func=lambda k: pf.versions[k].label + (" (latest)" if k == last else ""),
        help="Every new test or event adds a version; earlier versions are kept. Move back to "
             "open the report, its tests and its timeline as they were then.")
    timeline_page.banner(pf, i)
    reviews = ss.reviews
    alerts = {overview.alert_key(pf, a) for v in pf.versions[: i + 1] for a in v.alerts}
    still = len(alerts - set(reviews))
    ident.markdown(f"**{pf.id}** · {esc(pf.diagnosis)} · "
                   + (f":red-badge[SOS: {still} open]" if still else
                      ":gray-badge[SOS: none open]")
                   + ("" if i == last else f" · as of {pf.versions[i].label}"),
                   help="Open SOS alerts: alerts no reviewer has marked yet, as of this report "
                        "version (Report › Attention).")
    if link and link.get("pointer"):
        land_pointer(pf, i, link["pointer"], linked)
    back_buttons(pf, view)
    shown = safely(f"The {view.lower()} view" if view != "Import tests" else "Import tests",
                   {"Report": report_view, "Tests": tests_view, "Timeline": timeline_view,
                    "Evolution": evolution_view, "Import tests": import_view}[view], pf, i,
                   spin={"Report": "Gathering the report: every workbench's findings and the "
                                   "attention queue…",
                         "Evolution": "Reading the evolution table and the trials…"}.get(view))
    with tail:  # where am I: the view, the workbench open (unless the test names it), the test
        st.markdown(nav.SEP, width="content")
        if shown is None:
            st.markdown(view, width="content")
        else:
            wb = overview.NAMES.get(SCREENS.get(shown.workbench, ""), "")  # the queue's names
            crumb = nav.crumb(shown)
            st.markdown(f" {nav.SEP} ".join([view, *([wb] if wb and not crumb.startswith(wb)
                                                     else []), f"**{crumb}**"]),
                        width="content")
    test = nav.test_id(shown) if shown is not None else None
    p = ss.get("_pointer") or {}
    here = (p.get("pid"), p.get("view"), p.get("test")) == (pf.id, view, test)
    nav.sync(pf.id, test, p.get("pointer") if here else None, None if i == last else i)
    screen = SCREENS.get(shown.workbench, "report") if shown is not None else {
        "Report": "report", "Timeline": "timeline", "Evolution": "evolution",
        "Import tests": "imports"}.get(view, "report")
    with actions:
        safely("The file's actions", action_row, pf, i, screen)
    return screen


def action_row(pf: workspace.PatientFile, i: int, screen: str):
    """The file's actions on every view, under the view control (docs/ux.md §2): the attention
    queue, Import a test, Compare versions, the report's export, the reviewer's marks (the
    Feedback page) and the guide, each saying on hover what it does."""
    ss = st.session_state
    with st.spinner("Counting the attention queue…"):  # shown after 0.5 s: once per version
        ov = overview_data(pf, i)
    queue = ov["queue"]
    left = sum(x["key"] not in ss.reviews for x in queue)
    st.button(f"Attention queue ({left})", key="act-queue", icon=":material/checklist:",
              on_click=to_queue, args=(pf, i, queue),
              help=f"{len(queue)} item{'' if len(queue) == 1 else 's'} in this version's queue, "
                   f"{left} not marked yet: the report's queue at the first of them (there, j "
                   "and k walk it, o opens one)")
    st.button("Import a test", key="act-import", icon=VIEW_ICONS["Import tests"],
              on_click=lambda: ss.update(view="Import tests"),
              help="Lab results, a report, sequencing (VCF or MAF), an imaging report, a slide "
                   "image or a DICOM file: each is checked on intake and adds a report version")
    st.button("Compare versions", key="act-compare", icon=VIEW_ICONS["Timeline"],
              disabled=i == 0, on_click=lambda: ss.update(view="Timeline"),
              help="The Timeline compares any two report versions: what changed and why" if i
              else "One report version so far: each import adds the next")
    v = pf.versions[i]
    st.download_button("Export this report (Markdown)",
                       partial(report_page, pf, i, ov, dict(ss.reviews)),  # built on the click
                       file_name=f"{pf.id.replace(' ', '_')}_"
                                 f"{'baseline' if v.month is None else f'month{v.month}'}.md",
                       mime="text/markdown", key="act-export", icon=":material/download:",
                       on_click="ignore", help="This report version as one page: numbers, "
                                               "sources, placeholders, model versions and your "
                                               "review marks")
    marks = sum(k.startswith(pf.id + "|") for k in ss.reviews)
    # a page link, as the sidebar's: st.switch_page can't leave a page whose ?patient is bound
    st.page_link(FEEDBACK, label=f"Your marks ({marks})", icon=":material/how_to_vote:",
                 help=f"{marks} review mark{'' if marks == 1 else 's'} on this file, "
                      f"{len(ss.reviews)} in this session: the Feedback page lists them as a "
                      "ledger, with its download")
    pinned = pf.id in ss.get("pinned_files", [])
    st.button("Unpin this file" if pinned else "Pin this file", key="act-pin",
              icon=":material/push_pin:", on_click=toggle_file_pin, args=(pf.id,),
              help="Pinned files sit at the top of the Patients page, for this browser session")
    st.page_link(METHODS, label="Methods and validation", icon=":material/fact_check:",
                 help="Every model and rule behind this file, with its numbers, sources and "
                      "known failures")
    guide.help_icon(screen, label="How to read this")


def to_queue(pf: workspace.PatientFile, i: int, queue: list):
    """"Attention queue": the report, its queue on the first item not marked yet."""
    ss = st.session_state
    ss.update({"view": "Report", f"unsure-{pf.id}": False,
               f"queue-{pf.id}-{i}": next((n for n, x in enumerate(queue)
                                           if x["key"] not in ss.reviews), 0)})


def apply_link(pf: workspace.PatientFile, link: dict, last: int) -> tuple | None:
    """A new address's ?version and ?test: the report version and the test to open (the view
    comes with ?view, bound to its control). Returns the test, if the file has it."""
    ss = st.session_state
    version = link.get("version") or ""
    if version.isdigit() and 0 < int(version) <= last:
        ss[f"version-{pf.id}"] = int(version)
    elif link.get("version") is None and last:
        ss[f"version-{pf.id}"] = last
    t = nav.parse_test_id(link.get("test"))
    test = next((x for x in pf.tests if (x.kind, x.month, x.name) == t), None)
    if test is None:
        return None
    ss[f"picked-{pf.id}"] = t
    ss[f"kinds-{pf.id}"] = []  # a type filter must not hide the test
    ss.tests_n += 1
    if not link.get("pointer") and (focus := dated_focus(test)):  # its own value, not the latest
        land(pf, ss.get(f"version-{pf.id}", last), focus)
    return t


def land_pointer(pf: workspace.PatientFile, i: int, pointer: str, test: tuple | None):
    """A deep link's ?pointer: land on the finding of this version's queue with that pointer
    (in the linked test, when there is one), as an "Open" would."""
    x = next((x for x in overview_data(pf, i)["queue"] if x["pointer"] == pointer
              and (test is None or tuple(x["opens"][1:]) == test)), None)
    if x is not None:
        land(pf, i, x["focus"] or {})
        st.session_state["_pointer"] = {"pid": pf.id, "view": st.session_state.get("view"),
                                        "test": None if test is None else "|".join(
                                            "" if v is None else str(v) for v in test),
                                        "pointer": pointer}


def back_buttons(pf: workspace.PatientFile, view: str):
    """After an "Open" from the report: back to the file (its report), and back to the
    attention queue's item it was opened from."""
    ss = st.session_state
    fr = ss.get("_from")
    if not fr or fr["pid"] != pf.id:
        return
    if view == "Report":
        ss.pop("_from", None)
        return
    with st.container(horizontal=True, gap="small"):
        st.button("← Back to the file", key="back-report", on_click=back_to, args=(fr, False),
                  help="The file's front page: its latest report, at the top")
        if "pos" in fr:
            st.button(f"← Back to the queue, item {fr['n'] + 1} of {fr['total']}",
                      key="back-queue", on_click=back_to, args=(fr, True),
                      help=f"The attention queue at the item opened: {fr['what']}")


def back_to(fr: dict, queue: bool):
    ss = st.session_state
    ss.view = "Report"
    if queue:
        ss[fr["pos"]] = fr["n"]
    ss.pop("_from", None)


def report_view(pf: workspace.PatientFile, i: int):
    v, case = pf.versions[i], CASES.get(pf.id)
    st.subheader(f"Report · {v.label}" + ("" if i == len(pf.versions) - 1 else
                                         " (as it was then)"))
    guide.chip_row(OBSERVED, INFERENCE, HYPOTHESIS, "trust", "placeholder", "SOS",
                   key="report-labels")
    arrived = v.event + ("" if v.month is None else f" (month {v.month})")
    st.markdown(f"**Summary** · {pf.diagnosis}. Latest in the record: {arrived}. "
                f"{tags(OBSERVED)}  \n{v.summary} {tags(INFERENCE) if v.risk else ''}")
    ov = overview_data(pf, i)
    overview_header(pf, i, ov)
    attention_queue(pf, i, ov)
    review_panel(pf)
    # cohort-search hook 2 of 2 (muffle.cohort, docs/cohort.md): "Where this patient sits" and
    # "Similar patients", under the overview cards and the queue. Keep this call when reshaping.
    safely("Where this patient sits and the similar patients", cohort_sections, pf)

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Characterization and record** {tags(OBSERVED)}")
        st.markdown("\n".join(f"- **{k}:** {esc(val)}" for k, val in v.observed))
    with right:
        head, box = line_and_action()
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
                    + f": {esc(t.result)}")
    variants = [var for t in seq for var in t.details["variants"]]
    quiet = [var for var in variants if civic_items(pf, var) == []]
    for var in variants:
        if var not in quiet:
            civic_block(pf, var, k=3)
    if quiet:
        st.caption("No CIViC breast cancer evidence for " + esc(", ".join(quiet)) + ".")

    watch = evolution.hypothesis_set(pf, i)["items"]
    st.markdown(f"**Evolutionary hypotheses** {tags(HYPOTHESIS)} {badge(workspace.IMPLEMENTED)}"
                " · what to watch next, ranked, with sources and the test that would detect it: "
                + ("; ".join(it["event"] for it in watch[:3]) if watch else "none raised")
                + " (Evolution view)")
    st.button("Open the Evolution view", key=f"evolution-{pf.id}-{i}",
              icon=VIEW_ICONS["Evolution"],
              on_click=lambda: st.session_state.update(view="Evolution"),
              help="What to watch next, ranked, with the evidence for and against")
    st.markdown(f"**Missing data and what it limits** {tags(OBSERVED)}")
    st.markdown("\n".join(f"- {line}" for line in workspace.missing_data(pf, i)))
    disagree = ov["disagree"]
    if disagree:
        st.markdown(f"**Tests that disagree** · {len(disagree)}")
        for d in disagree:
            with st.container(border=True):
                st.markdown(f"**{esc(d['what'])}** {tags(d['evidence'])} "
                            f":{TRUST_COLORS[d['trust']]}-badge[trust: {d['trust']}]")
                st.caption(" vs ".join(d["sources"]) + f" · {esc(d['why'])}")
                st.markdown(f"What would settle it: {esc(d['would_settle'])}")
                if d["basis"] and d["basis"] not in d["would_settle"]:
                    st.caption(f"Basis: {d['basis']}")
    reducers = ov["reducers"]
    if reducers:
        st.markdown(f"**What would reduce uncertainty** {tags(HYPOTHESIS)} · evidence for your "
                    "judgment, not an order")
        st.markdown("\n".join(
            f"- **{r['open_question']}** → {r['test']}: {r['expectation']} "
            f"{tags(r['evidence'])}  \n  Source: {r['source']}" for r in reducers))
    with st.expander(f"Show the caveats, data sources and model versions "
                     f"({1 + len(sources(pf))})"):
        st.markdown(f"- **Model:** {pf.model['name']} ({pf.model['status']}); endpoint: "
                    f"{pf.model['endpoint']}.\n" + "\n".join(f"- {s}" for s in sources(pf)))
    page = report_page(pf, i, ov, st.session_state.reviews)
    when = "baseline" if v.month is None else f"month{v.month}"
    st.download_button("Download this report version (Markdown)", page,
                       file_name=f"{pf.id.replace(' ', '_')}_{when}.md", mime="text/markdown",
                       help="One page: numbers, sources, placeholders, model versions and your "
                            "review marks.")
    if case is not None:
        case_note(case)


def report_page(pf: workspace.PatientFile, i: int, ov: dict, reviews: dict) -> str:
    """Report version ``i`` as one Markdown page (the report's download and the file's "Export
    this report"): numbers, sources, placeholders, model versions and the review marks."""
    variants = [var for t in workspace.sequencing_tests(pf, i) for var in t.details["variants"]]
    return workspace.report_markdown(pf, i, {var: civic_items(pf, var) for var in variants},
                                     reviews, sources(pf), ov["disagree"], ov["reducers"],
                                     ov["sums"], ov["queue"])


TRUST_COLORS = {"strong": "green", "moderate": "orange", "weak": "red"}
CARD_WIDTH, CARD_TEXT = 220, 150  # px (two a row at 800 px, sidebar open); characters before "more"


def shorten(text: str, limit: int) -> str:
    """``text`` cut at a word before ``limit`` characters, with an ellipsis."""
    text = str(text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:·") + " …"
MARKS = workspace.MARKS[1:]  # "reviewed" comes from the "Mark reviewed" button
KINDS = {"SOS": chip("SOS", "red"), "discrepancy": chip("tests disagree")}


def overview_data(pf: workspace.PatientFile, i: int) -> dict:
    """Report version ``i``'s overview: every workbench's summary, the tests that disagree, what
    would reduce uncertainty and the attention queue. Once per browser session and version (an
    import adds a version, so it gets its own key; new code gets new keys)."""
    memo = st.session_state.setdefault("overview", {})
    key = (CODE_DIGEST, pf.id, len(pf.versions), i)
    if key not in memo:
        lookup = None if pf.kind == "synthetic" else EVIDENCE  # its CIViC items are frozen
        disagree = crosstest.discrepancies(pf, i)
        queues = overview.queues(pf, i, lookup)  # the Tests view counts them per test
        memo[key] = {"sums": overview.summaries(pf, i, lookup), "disagree": disagree,
                     "reducers": crosstest.uncertainty_reducers(pf, i), "queues": queues,
                     "queue": overview.attention(pf, i, queues, disagree)}
    return memo[key]


def overview_header(pf: workspace.PatientFile, i: int, ov: dict):
    """One row of finding cards from the workbenches' summaries (docs/WORKBENCHES.md §2)."""
    cards = overview.header(pf, i, ov["sums"], ov["queue"], st.session_state.reviews)
    cards = cards[-1:] + cards[:-1]  # the SOS card first
    with st.container(horizontal=True, gap="small"):  # cards of one width wrap: 3 a row at 800 px
        for c in cards:
            with st.container(border=True, width=CARD_WIDTH):
                pointer = c.get("pointer") or next(
                    (x["pointer"] for x in ov["queue"] if c["focus"] and x["focus"] == c["focus"]),
                    None)
                finding_card(pf, i, c, pointer)
        for name, note in overview.absent(ov["sums"]):
            empty_card(pf, name, note)


FILLS = {  # an empty card: the test that would fill it, and whether Import tests takes it
    "labs": ("lab results, a CSV of values with their units", True),
    "ctdna": ("a plasma ctDNA panel (liquid biopsy), repeated under treatment; Import tests "
              "does not take ctDNA yet", False),
    "genomics": ("tumor sequencing, a VCF or MAF file", True),
    "slides": ("a scanned H&E section of this tumor; Import tests registers a slide region "
               "image, not analyzed here", True),
    "omics": ("expression, methylation or protein profiling of the tumor sample; Import tests "
              "does not take it", False),
    "documents": ("a pathology report or a clinic note, as text or PDF", True),
    "radiology": ("an imaging report, or a DICOM study (registered, not analyzed here)", True),
    "evolution": ("tumor sequencing or a treatment in the record raises its rows", True),
}


def empty_card(pf: workspace.PatientFile, name: str, note: str):
    """A workbench with nothing to show in this file: why, what would fill it and, where Import
    tests takes that test, a way there."""
    what, importable = FILLS.get(name, ("its own test", False))
    with st.container(border=True, width=CARD_WIDTH):
        st.markdown(f"**{overview.NAMES[name]}** · nothing to show")
        st.caption(esc(note[0].upper() + note[1:]) + ".")
        st.markdown(f"What would fill it: {esc(what)}.")
        if importable:
            st.button("Import a test", key=f"fill-{pf.id}-{name}", icon=VIEW_ICONS["Import tests"],
                      width="stretch", on_click=lambda: st.session_state.update(
                          view="Import tests"), help="Bring the test in; it adds a report version")


def destination(pf: workspace.PatientFile, opens: tuple) -> str:
    """Where an "Open" lands, in words: the test's breadcrumb ("CA 15-3, month 11", "Pathology
    slide") or the view ("Timeline", "Evolution")."""
    if opens[0] != "Tests":
        return opens[0]
    t = next((t for t in pf.tests if tid(t) == tuple(opens[1:])), None)
    return nav.crumb(t) if t else opens[1]


def finding_card(pf: workspace.PatientFile, i: int, c: dict, pointer: str | None = None):
    """A card: the statement with its evidence label and trust; "Why?" names the source test,
    the method and version, the threshold's source and the trust; its full-width "Open" lands on
    the evidence."""
    title = (f"**:red[SOS]** · {c['open']} open" if c["what"] == "SOS" and c["open"] else
             f"**{c['what']}**")
    st.markdown(f"{title}  \n{tags(c['evidence'])}")
    sides = c["sides"] if "sides" in c else [(None, c["text"], None)]
    cut = [(k, shorten(text, CARD_TEXT // len(sides))) for k, text, _ in sides]
    st.markdown("  \n".join((f"*{k}:* " if k else "") + esc(text) for k, text in cut))
    if any(text != full for (_, text), (_, full, _) in zip(cut, sides, strict=True)):
        with st.popover("more", type="tertiary", help="The card's full text"):
            st.markdown("  \n".join((f"*{k}:* " if k else "") + esc(text)
                                     for k, text, _ in sides))
    placeholder = " " + chip("placeholder threshold") if "placeholder" in c["threshold"] \
        else ""
    st.markdown(f":{TRUST_COLORS[c['trust']]}-badge[trust: {c['trust']}]{placeholder}")
    with st.popover("Why?", help="The source test, the method and its version, the threshold's "
                                 "source and the trust"):
        st.markdown(f"**Source test:** {esc(c['source'])}  \n**Method and version:** "
                    f"{esc(c['method'])}  \n**Threshold:** {esc(c['threshold'])}  \n"
                    f"**Trust:** {c['trust']}  \n**Evidence:** {c['evidence']}")
    if c["opens"]:
        st.button(f"Open · {destination(pf, c['opens'])}", key=f"card-{pf.id}-{i}-{c['what']}",
                  icon=":material/arrow_forward:", width="stretch", on_click=open_evidence,
                  args=(pf, i, c["opens"], c["focus"], pointer, {"card": c["what"]}),
                  help="Opens the test behind this card at its evidence")


def attention_queue(pf: workspace.PatientFile, i: int, ov: dict):
    """The patient's one queue: SOS alerts, tests that disagree and every workbench's look-here
    items, merged and ordered (``muffle.overview.attention``), one item at a time with keyboard
    triage: j next, k previous, p pin, m mark reviewed (Streamlit keeps r for rerun), u the
    unsure list, o open."""
    items, reviews, pins = ov["queue"], st.session_state.reviews, st.session_state.pins
    ss, pos, only = st.session_state, f"queue-{pf.id}-{i}", f"unsure-{pf.id}"
    shown = overview.unsure(items, reviews) if ss.get(only) else items
    sos = sum(x["sos"] for x in items)
    disagree = sum(x["kind"] == "discrepancy" for x in items)
    with st.container(border=True):
        st.markdown(f"**Attention** · {len(items)} item{'s' if len(items) != 1 else ''}: {sos} "
                    f"SOS, {disagree} where tests disagree, {len(items) - sos - disagree} from "
                    "the workbenches" + (" · **unsure list**: marked second look, or weak trust"
                                         if ss.get(only) else ""))
        st.caption(overview.ORDER_RULE.capitalize() + ".")
        if not shown:
            st.caption("Nothing on the unsure list." if ss.get(only) else
                       "Nothing needs attention in this version.")
            if ss.get(only):
                st.button("Whole queue", key=f"unsure-off-{pos}", shortcut="U",
                          on_click=lambda: ss.update({only: False, pos: 0}),
                          help="Back to every item of the queue (key u)")
            return
        k = ss.get(pos, 0) % len(shown)
        cur = shown[k]
        left = sum(x["key"] not in reviews for x in shown)
        st.markdown(f"**Next step:** {left} item{'' if left == 1 else 's'} need"
                    f"{'s' if left == 1 else ''} a look: press **j** for the next one, or click a "
                    "row's **Open**." if left else "**Next step:** every item here is marked; "
                    "**u** shows the unsure list (second looks and weak trust).")
        # in tab order: previous, next, pin, mark reviewed, unsure list, open (docs/ux.md §7);
        # a row that wraps on a narrow screen, never fixed columns that cut "Mark reviewed"
        c = st.container(horizontal=True, gap="small")
        c.button("Previous", key=f"prev-{pos}", shortcut="K",
                 help="The previous item (key k)", on_click=lambda: ss.update({pos: k - 1}))
        c.button("Next", key=f"next-{pos}", shortcut="J",
                 help="The next item (key j)", on_click=lambda: ss.update({pos: k + 1}))
        c.button("Unpin" if cur["key"] in pins else "Pin", key=f"pin-{pos}", shortcut="P",
                 help="Pin it to the top of the report (key p)",
                 on_click=toggle_pin, args=(cur["key"], cur["what"]))
        c.button("Mark reviewed", key=f"reviewed-{pos}", shortcut="M",
                 disabled=cur["key"] in reviews, help="Mark it reviewed, with your initials "
                                                      "(key m)",
                 on_click=mark, args=(cur["key"], cur["what"], "reviewed"))
        c.button("Whole queue" if ss.get(only) else "Unsure list", key=f"unsure-{pos}",
                 shortcut="U", help="Items marked second look, or of weak trust (key u)",
                 on_click=lambda: ss.update({only: not ss.get(only), pos: 0}))
        c.button("Open", key=f"open-{pos}", shortcut="O", type="primary",
                 help="Open its evidence in its workbench (key o)",
                 disabled=not cur["opens"], on_click=open_evidence,
                 args=(pf, i, cur["opens"], cur["focus"], cur["pointer"],
                       {"pos": pos, "n": k, "total": len(shown), "what": cur["what"]}))
        queue_item(cur, k, len(shown), reviews)
        with st.container(height=320 if len(shown) > 8 else "content"):
            for n, x in enumerate(shown):
                line, act = line_and_action()
                done = reviews.get(x["key"])
                text = (f"{x['n']} · " + (f"`{x['pointer']}` " if x["pointer"] else "")
                        + esc(x["what"]) + f" · {kind_badge(x)}"
                        + (" · **new**" if x["new"] else "")
                        + f" :{TRUST_COLORS[x['trust']]}-badge[{x['trust']}]"
                        + (f" · ✓ {done['mark']}" if done else "")
                        + (" · 📌" if x["key"] in pins else ""))
                line.markdown(f"**{text}**" if n == k else text)
                if x["opens"]:
                    act.button("Open", key=f"open-{pos}-{n}", on_click=open_item,
                               args=(pf, i, pos, n, x, len(shown)),
                               help="Open its evidence in its workbench")
        st.caption(":material/keyboard: `j` next · `k` previous · `p` pin · `m` mark reviewed · "
                   "`u` unsure list · `o` open (Streamlit keeps `r` for its rerun). A mark here "
                   "is the same mark the workbench shows.")


def kind_badge(x: dict) -> str:
    return KINDS.get(x["kind"]) or chip(overview.NAMES.get(x["kind"], x["kind"]))


def queue_item(x: dict, k: int, total: int, reviews: dict):
    """The current item in full: what, why, the evidence label, trust, consequence, where else
    it was raised, what would settle it, and its review box."""
    done = reviews.get(x["key"])
    placeholder = " " + chip("placeholder threshold") if "placeholder" in x["threshold"] \
        else ""
    st.markdown(f"**{k + 1}/{total} · " + (f"`{x['pointer']}` " if x["pointer"] else "")
                + f"{esc(x['what'])}** {tags(x['evidence'])} {kind_badge(x)} "
                f":{TRUST_COLORS[x['trust']]}-badge[trust: {x['trust']}]"
                f" {chip('consequence ' + str(x['consequence']))}{placeholder}")
    shown = x["threshold"] and x["threshold"] not in x["settle"]  # a basis the settle line cites
    label = "basis" if x["kind"] == "discrepancy" else "threshold"
    st.caption(f"{esc(x['source'])} · {esc(x['why'])}"
               + (f" · {label}: {esc(x['threshold'])}" if shown else "")
               + (f" · also raised by {', '.join(x['also'])}" if x["also"] else "")
               + (f" · {done['mark']} by {done['by'] or 'no initials'}, {done['at']}"
                  if done else ""))
    if x["settle"]:
        st.markdown(f"What would settle it: {esc(x['settle'])}")
    review_box(x["key"], x["what"])


def open_item(pf: workspace.PatientFile, i: int, pos: str, n: int, x: dict, total: int):
    """A row's "Open": make it the current item, then open its evidence."""
    st.session_state[pos] = n
    open_evidence(pf, i, x["opens"], x["focus"], x["pointer"],
                  {"pos": pos, "n": n, "total": total, "what": x["what"]})


def open_evidence(pf: workspace.PatientFile, i: int, opens: tuple, focus: dict | None = None,
                  pointer: str | None = None, back: dict | None = None):
    """"Open": switch the file to the view that holds the evidence (``opens``, the shape of
    ``Alert.opens``), land the workbench on it (``focus``), let the address carry the pointer
    (?pointer) and remember where it was opened from (``back``: the queue's position and item,
    or a card), for the way back."""
    ss = st.session_state
    if not opens:
        return
    test = None
    if opens[0] == "Tests":
        ss[f"picked-{pf.id}"] = tuple(opens[1:])
        ss[f"kinds-{pf.id}"] = []  # a type filter must not hide the test
        ss.tests_n += 1  # a fresh tests table, so no old row selection wins
        test = nav.test_key(*opens[1:])
        t = next((t for t in pf.tests if tid(t) == tuple(opens[1:])), None)
        focus = focus or (dated_focus(t) if t else None)
    if focus:
        land(pf, i, focus)
    ss.view = opens[0]
    ss["_pointer"] = {"pid": pf.id, "view": opens[0], "test": test, "pointer": pointer}
    ss["_from"] = {"pid": pf.id, **(back or {})}


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
            help="Agree, disagree or a second look, saved with your initials and the time",
            on_change=lambda: mark(key, what, st.session_state[f"mark-{h}"]))
        st.checkbox("Pin to the top of the report", key=f"pin-{h}",
                    value=key in st.session_state.pins, on_change=toggle_pin, args=(key, what),
                    help="Pinned findings head the report's list of what you pinned and "
                         "reviewed")
        if done:
            st.caption(f"{done['mark']} · {done['by'] or 'no initials'} · {done['at']}")


def review_panel(pf: workspace.PatientFile):
    """Pinned findings and every review mark in this file, with a filter."""
    marks = {k: r for k, r in st.session_state.reviews.items() if k.startswith(pf.id + "|")}
    pins = {k: w for k, w in st.session_state.pins.items() if k.startswith(pf.id + "|")}
    if not marks and not pins:
        return
    with st.expander(f"Show what you pinned and reviewed: {len(pins)} pinned, "
                     f"{len(marks)} marked",
                     expanded=bool(pins)):
        show = st.pills("Show", ["pinned", "reviewed", *MARKS], selection_mode="multi",
                        key=f"review-filter-{pf.id}",
                        help="Show only the findings with these marks")
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
    row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
    row.metric("12-month risk", f"{r['value']:.0%}",
               None if prev is None else f"{100 * (r['value'] - prev):+.0f} points",
               delta_color="inverse", help=pf.model["endpoint"].capitalize() + ".",
               width="content")
    row.metric("Range, 5 models", "{:.0%}–{:.0%}".format(*r["range"]), width="content",
               help="The same model trained on five different 80% splits (seeds 0–4).")
    row.metric("Diagnosis only", f"{r['baseline']:.0%}", width="content",
               help="Baseline: stage, HR and HER2 alone, same patients and learner.")
    row.metric("Model AUROC", f"{r['auroc']:.2f}", width="content",
               help=f"Held-out AUROC of the month-{r['landmark']} model on MSK-CHORD, mean of 5 "
                    f"seeds (diagnosis only: {r['baseline_auroc']:.2f}; {m['n']:,} patients, "
                    f"event rate {m['event_rate']:.0%}).")
    st.caption(f"{pf.model['endpoint'].capitalize()}, from the month-{r['landmark']} "
               f"{pf.model['name']}. Whether these probabilities are calibrated has not been "
               "checked.")


def case_risk(case):
    row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
    row.metric("Risk percentile", ordinal(case.percentile), width="content",
               help="Share of all patients with a lower predicted risk.")
    row.metric("Risk group", case.group.capitalize(), width="content",
               help="Cohort tertiles of predicted risk.")
    row.metric("Simulated hospital", case.site, width="content",
               help="The FL client this patient belongs to: a group of TCGA tissue source sites.")
    row.metric("Data layers", f"{len(case.layers)} of {len(demo.model.names)}", width="content",
               help="Missing: " + (", ".join(case.missing) or "none"))
    st.caption(f"Overall survival, ranked against all {len(demo.cohort_risks):,} patients by the "
               f"federated model (held-out C-index {demo.c_index:.3f}). It ranks patients; its "
               "absolute risks are only roughly calibrated.")


@st.cache_resource(show_spinner=False, max_entries=64)
def case_charts(index: int, source: str) -> tuple[dict, dict, dict]:
    """A case's risk position and layer contributions as Vega-Lite specs, with the
    contributions themselves: built once per bundle (``source``) and case, since Altair takes
    about half a second to encode the cohort histogram on a shared CPU."""
    case = next(c for c in demo.cases if c.index == index)
    x, mask = demo.inputs(case)
    _, contrib = modality_contributions(demo.model, x, mask, demo.offsets)
    named = {LAYER_NAMES.get(m, m): v for m, v in contrib.items()}
    return (charts.risk_position(demo.cohort_risks, case.log_risk,
                                 f"{ordinal(case.percentile)} percentile").to_dict(),
            charts.contributions(named).to_dict(), named)


CHART_WIDTH = 380  # px: the risk charts side by side at 1280 px, stacked at 800 px (QA R3-7)


def case_why(case):
    position, drivers, named = case_charts(case.index, SOURCE)
    with st.container(horizontal=True, gap="medium", key="case-why"):  # wraps when narrow
        left, right = (st.container(width=CHART_WIDTH) for _ in range(2))
    with left:
        st.markdown(f"**Where this patient sits among all patients** {tags(INFERENCE)}")
        st.vega_lite_chart(spec=position, width="stretch",
                           alt=f"This patient's predicted risk against all "
                               f"{len(demo.cohort_risks):,} patients: the "
                               f"{ordinal(case.percentile)} percentile")
    with right:
        st.markdown(f"**What drives this patient's risk** {tags(INFERENCE)}")
        st.vega_lite_chart(spec=drivers, width="stretch",
                           alt="Each data layer's effect on this patient's predicted log-risk: "
                               + ", ".join(f"{k} {v:+.2f}" for k, v in named.items()))
        st.caption("Each layer's effect on this patient's predicted log-risk, compared with its "
                   "effect on a typical patient in the cohort.")

    with st.expander(f"Try hiding a data layer ({len(case.layers)} here): what if one were "
                     "missing?"):
        st.caption("Hospitals collect different data. MuFFLe++ masks a missing layer instead of "
                   "dropping the patient, so the same model scores everyone.")
        hide = st.pills("Hide layers", case.layers, selection_mode="multi",
                        format_func=lambda m: LAYER_NAMES.get(m, m), key=f"hide-{case.index}",
                        help="The risk recomputed with these layers masked, as a hospital "
                             "without them would score this patient")
        if hide and len(hide) == len(case.layers):
            st.warning("Keep at least one layer.")
        elif hide:
            hx, hmask = demo.inputs(case, hide)
            with torch.no_grad():
                risk = demo.model(hx, hmask).item()
            pct = risk_percentile(risk, demo.cohort_risks)
            st.metric("Risk percentile without " + ", ".join(LAYER_NAMES.get(m, m) for m in hide),
                      ordinal(pct), f"{int(pct) - int(case.percentile):+d} percentile points",
                      delta_color="inverse", width="content")


def civic_block(pf: workspace.PatientFile, variant: str, k: int | None = None):
    items = civic_items(pf, variant)
    with st.container(border=True):
        st.markdown(f"**{esc(variant)}** · CIViC treatment evidence, for clinician review "
                    f"{tags(HYPOTHESIS)}")
        if items is None:
            st.caption("The CIViC table could not be loaded here.")
        elif not items:
            st.caption("No CIViC breast cancer evidence for this variant.")
        for e in (items or [])[:k]:
            text, box = line_and_action()
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
                "Record: written by hand for this platform; not a real person.",
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
    b1 = b2 = st.container(horizontal=True, gap="small")
    write = b1.button("Write the note with Nemotron", disabled=not can_live,
                      help="Nemotron plans the tool calls and writes the note from this case's "
                           "derived numbers; a grounding check verifies it" if can_live else (
                          "Live notes are not set up on this server." if not LIVE
                          else "This session's live notes are used up."))
    show_saved = b2.button("Show the saved note", disabled=saved is None,
                           help="No saved note for this case" if saved is None else
                           "The tumor-board note saved for this case (★ in the patient list)")
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
            st.markdown(esc(report.text))
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
                               file_name=f"muffle_case_{case.index}.md", mime="text/markdown",
                               help="The note with its header: the case, its source and the "
                                    "model that wrote it")
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
                with st.expander(f"Show tool call {n}: {call.name}({shown}){flag}"):
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
    with st.expander(f"Show the evidence chain: {len(rows)} links from {len(chain)} sentences "
                     "to the tool outputs"
                     + (f", {len(unsupported)} unsupported" if unsupported else "")):
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
    """The launcher (a tile per test, grouped by kind, each with its "Open"), every test as a
    table in an expander under it, then the open test's workbench."""
    tests = [t for v in pf.versions[: i + 1] for t in v.tests]
    kinds = st.pills("Type", list(dict.fromkeys(t.kind for t in tests)), selection_mode="multi",
                     key=f"kinds-{pf.id}", help="Show only the tests of these kinds")
    shown = [t for t in tests if not kinds or t.kind in kinds]
    if not shown:
        st.info("No test to open " + ("of this type " if kinds else "")
                + "as of this report version. Import tests brings in lab results, reports, "
                  "sequencing, imaging reports and slide images; each opens its workbench "
                  "here." + (" Clear the type filter to see every test." if kinds else ""),
                icon="🧪")
        return None
    picked = st.session_state.get(f"picked-{pf.id}")  # the last test opened here or from an alert
    t = next((t for t in shown if (t.kind, t.month, t.name) == picked), None)
    if t is None:  # the first workbench's test, the latest of its series (its Spot panel's value)
        t = next((t for w in ("labs", "mutations", "omics", "record") for t in shown
                  if t.workbench == w), shown[0])
        t = [s for s in shown if (s.kind, s.name) == (t.kind, t.name)][-1]
    launcher(pf, i, shown, t)
    all_tests(pf, i, shown, kinds)
    st.session_state["_test_shown"] = nav.test_id(t)
    st.divider()
    what = workbench_name(t)
    safely(what, draw_test, pf, i, t, spin=f"Opening {what[0].lower() + what[1:]}…")
    return t


def workbench_name(t: workspace.Test) -> str:
    """The workbench a test opens in, as a sentence starts: "The blood and lab workbench", "The
    ctDNA monitor (liquid biopsy)"."""
    name = WORKBENCH_NAMES.get(SCREENS.get(t.workbench, ""), "test's page")
    return "The " + (name[0].lower() + name[1:] if name[1:2].islower() else name)


TILE_WIDTH = 220  # px: two launcher tiles a row at 800 px with the sidebar open, three at 1280


def tid(t: workspace.Test) -> tuple:
    return t.kind, t.month, t.name


def launcher(pf: workspace.PatientFile, i: int, shown: list, active: workspace.Test):
    """A tile per test, grouped by kind; a dated series of one test (CA 15-3 at eight months)
    is one tile with a pill per month, so a long record fits on a screen. A tile holds the kind
    and the name, what the test holds (the latest result), its status, how many look-here items
    of its workbench's ``queue()`` open at it, and "Open"; the open test's tile says it is open
    below."""
    counts = Counter(tuple(x["opens"][1:]) for q in overview_data(pf, i)["queues"].values()
                     for x in q if tuple(x["opens"][:1]) == ("Tests",))
    imported = {tid(t) for v in pf.versions[: i + 1] if v.imported for t in v.tests}
    kinds = list(dict.fromkeys(t.kind for t in shown))
    series: dict[tuple, list] = {}  # undated tests are a tile each
    for n, t in enumerate(shown):
        series.setdefault((t.kind, t.name, n if t.month is None else None), []).append(t)
    st.markdown(f"**Open a test** · {len(shown)} test{'' if len(shown) == 1 else 's'} in "
                f"{len(kinds)} kind{'' if len(kinds) == 1 else 's'}; each opens in its "
                "workbench below.")
    st.caption("Months count from the first tumor sequencing; a month opens that test." if
               pf.kind == "synthetic" else
               "TCGA holds one sample per patient, so its tests carry no dates.")
    with st.container(horizontal=True, gap="small", key="launcher"):  # tiles of one width wrap
        for n, ((kind, name, _), ts) in enumerate(sorted(series.items(),
                                                         key=lambda s: kinds.index(s[0][0]))):
            test_tile(pf, i, kind, name, ts, n, active, counts, imported)


def test_tile(pf: workspace.PatientFile, i: int, kind: str, name: str, ts: list, n: int,
              active: workspace.Test, counts: Counter, imported: set):
    """A launcher tile for one test or a dated series of it (``ts``, in record order): what it
    holds, its status and scope, its look-here count, "Open" (the latest) and, for a series, a
    pill per month."""
    latest = ts[-1]
    here = next((t for t in ts if tid(t) == tid(active)), None)
    look = {t.month: counts[tid(t)] for t in ts if counts[tid(t)]}
    total = sum(look.values())
    with st.container(border=True, width=TILE_WIDTH):
        st.caption(esc(kind))
        span = (f" · {len(ts)} tests, months {ts[0].month} to {latest.month}" if len(ts) > 1
                else "" if latest.month is None else f" · month {latest.month}")
        st.markdown(f"**{esc(name)}**{span}")
        holds = "measured on the tumor sample" if latest.result == "measured" else latest.result
        st.caption(esc(shorten(holds if len(ts) == 1 else f"Latest: {holds}", 90)))
        scopes = list(dict.fromkeys(t.details["scope"] for t in ts if "scope" in t.details))
        chips = [chip(s) for s in dict.fromkeys(t.status for t in ts)]
        if any(tid(t) in imported for t in ts):
            chips.append(chip("imported this session"))
        st.markdown(" ".join(chips) + "".join(f" · {esc(s)}" for s in scopes))
        st.markdown((f"**{total} item{'' if total == 1 else 's'} to look at**" if total else
                     "nothing flagged")
                    + (" (month " + ", ".join(str(m) for m in look) + ")"
                       if total and len(ts) > 1 else ""))
        h = hashlib.sha1(f"{kind}|{name}".encode()).hexdigest()[:10]
        if len(ts) > 1:
            key = f"months-{h}-{n}"
            st.session_state[key] = None if here is None else here.month  # the open test's month
            st.pills(f"Months of {name}", list(dict.fromkeys(t.month for t in ts)), key=key,
                     label_visibility="collapsed", on_change=pick_month, args=(pf, i, key, ts),
                     help=f"Each month opens {name} of that month")
        if here is not None and tid(here) == tid(latest):
            st.markdown(":blue-badge[:material/arrow_downward: open below]")
        else:
            st.button("Open" if len(ts) == 1 else f"Open month {latest.month}",
                      key=f"launch-{h}-{n}", on_click=pick_test, args=(pf, i, latest),
                      help=f"{workbench_name(latest)} opens on this test, below")
            if here is not None:
                st.markdown(f":blue-badge[:material/arrow_downward: month {here.month} open "
                            "below]")


def all_tests(pf: workspace.PatientFile, i: int, shown: list, kinds: list):
    """Every test as a table, collapsed under the launcher; selecting a row opens it too."""
    table = pd.DataFrame([{"Type": t.kind, "Month": t.month, "Test": t.name, "Result": t.result,
                           "Workbench": t.workbench, "Status": t.status + (
                               f": {t.details['scope']}" if "scope" in t.details else "")}
                          for t in shown])
    if table["Month"].isna().all():  # a TCGA file: undated tests (the launcher says why)
        table = table.drop(columns="Month")
    key = f"tests-{pf.id}-{i}-{'.'.join(kinds)}-{st.session_state.tests_n}"
    with st.expander(f"Show all {len(shown)} test{'' if len(shown) == 1 else 's'} as a table"):
        st.dataframe(table, hide_index=True, on_select=partial(pick_row, pf, i, key, shown),
                     selection_mode="single-row", key=key, width="stretch")
        st.caption("Select a row to open that test's workbench below.")


def pick_test(pf: workspace.PatientFile, i: int, t: workspace.Test, row: bool = False):
    """A tile's "Open" (or a row of the tests table): that test's workbench, on its own value
    for a dated lab or ctDNA test; another test drops the address's pointer."""
    ss = st.session_state
    new = (t.kind, t.month, t.name)
    if ss.get(f"picked-{pf.id}") != new:
        ss.pop("_pointer", None)
        if focus := dated_focus(t):
            land(pf, i, focus)
    ss[f"picked-{pf.id}"] = new
    if not row:
        ss.tests_n += 1  # a fresh table: no old row stays selected


def pick_row(pf: workspace.PatientFile, i: int, key: str, shown: list):
    rows = st.session_state[key].selection.rows
    if rows:
        pick_test(pf, i, shown[rows[0]], row=True)


def pick_month(pf: workspace.PatientFile, i: int, key: str, ts: list):
    """A month pill of a series tile: that month's test (a pill clicked off changes nothing)."""
    t = next((t for t in ts if t.month == st.session_state[key]), None)
    if t is not None:
        pick_test(pf, i, t)


def draw_test(pf: workspace.PatientFile, i: int, t: workspace.Test):
    """The opened test's workbench."""
    if t.workbench == "labs":  # the record's results and this session's imported ones
        labs.render(pf, events=workspace.record_events(pf), version=i, test=t)
    elif t.workbench == "mutations":  # CIViC's table adds the resistance items when it loaded
        genomics.render(pf, version=i, lookup=EVIDENCE,
                        table=civic.load_table() if EVIDENCE else None, case=CASES.get(pf.id),
                        demo=demo, test=t)
    elif t.workbench == "slides":  # the patient's own scored sections, or a public example
        from workbenches import slides  # here, so a missing scipy can't break the whole app

        slides.render(pf, version=i, test=t)
    elif t.workbench == "imaging":  # the image viewer, or the reports' words when no images
        from workbenches import radiology  # an imported report: its text and what the rule read

        radiology.render(pf, version=i, test=t)
    elif t.workbench in ("omics", "record"):
        omics.render(pf, version=i, layer=t.details["layer"], case=CASES.get(pf.id), demo=demo,
                     test=t)
    elif t.workbench == "documents":  # rule-based extraction; the case note is shown as inferred
        from workbenches import documents

        saved = demo.notes.get(CASES[pf.id].index) if pf.id in CASES else None
        documents.render(pf, version=i, focus=t.details.get("document"),
                         note=CaseReport.from_dict(saved["report"]).text if saved else None,
                         test=t)
    elif t.workbench == "intake":  # an imported image or scan, queued for the local pipeline
        from workbenches import imports

        imports.render_test(pf, t)
    elif t.workbench == "ctdna":  # the synthetic patient's ctDNA series, labeled synthetic
        from workbenches import ctdna

        ctdna.render(pf, version=i, test=t)
    else:
        st.markdown(f"#### {t.name}, month {t.month} {badge(t.status)}")
        st.markdown(f"**Report text** {tags(OBSERVED)}: {esc(t.result)}")
        st.info(PLANNED_WORKBENCHES.get(t.workbench, "This test's workbench.") + " Planned, "
                "pending the model and dataset survey's shortlist.",
                icon="🧭")


def timeline_view(pf: workspace.PatientFile, i: int):
    timeline_page.render(pf, i, TL, lambda j: overview_data(pf, j)["sums"], open_evidence)


def evolution_view(pf: workspace.PatientFile, i: int):
    table = civic.load_table() if EVIDENCE else None  # cached: loaded once by evidence()
    evolution_page.render(pf, version=i, lookup=None if table is None else
                          (lambda row: evolution.civic_items(row, table)))


def import_view(pf: workspace.PatientFile, i: int):
    from workbenches import imports  # the button and its dialog; imports last for the session

    imports.render_view(pf)


# --- Methods and validation ------------------------------------------------------------------
def methods():
    import methods_page  # a card per model and rule, every known failure and placeholder

    with st.container(horizontal=True, gap="xsmall", vertical_alignment="center"):
        st.page_link(PATIENTS, label="Patients", help="Back to the patient list")
        st.markdown(nav.SEP, width="content")
        st.markdown("**Methods and validation**", width="content")
        st.space("stretch")
        guide.help_icon("methods")
    safely("The Methods and validation page", methods_page.render, demo, TL, results())


# --- Feedback: the review marks as a ledger (app/feedback_page.py, muffle.feedback) ------------
def open_finding(pid: str, opens: tuple, focus: dict | None, pointer: str | None = None):
    """A Feedback queue item's (or a search result's) "Open": the patient file at its latest
    version, landed on the finding as the report's queue lands; on the report when the finding
    has no test behind it."""
    pf = FILES[pid]
    i = len(pf.versions) - 1
    st.session_state.patient = pid
    if i:
        st.session_state[f"version-{pid}"] = i
    if not opens:
        st.session_state.view = "Report"
    open_evidence(pf, i, opens, focus, pointer)


def feedback_view():
    import feedback_page  # the review marks as a ledger; nothing is trained on them

    with st.container(horizontal=True, gap="xsmall", vertical_alignment="center"):
        st.page_link(PATIENTS, label="Patients", help="Back to the patient list")
        st.markdown(nav.SEP, width="content")
        st.markdown("**Feedback**", width="content")
        st.space("stretch")
        guide.help_icon("feedback")
    safely("The Feedback page", feedback_page.render, FILES, CODE_DIGEST[:12], open_finding,
           PATIENTS)


PATIENTS = st.Page(patients_page, title="Patients", icon="🗂️", default=True)
METHODS = st.Page(methods, title="Methods and validation", icon="📖", url_path="methods")
FEEDBACK = st.Page(feedback_view, title="Feedback", icon="🗳️", url_path="feedback")
nav.PAGES.update(methods=METHODS, feedback=FEEDBACK)  # the workbench cards link Methods
st.navigation([PATIENTS, METHODS, FEEDBACK]).run()

if LIVE:
    notes_left = max(0, CAP - st.session_state.live_used)
    budget_slot.progress(notes_left / CAP if CAP else 0,
                         text=f"Live notes left this session: {notes_left} of {CAP}")
session_marks(marks_slot)

# scipy (the slide maths, the omics immune picture) is not needed for the first screen: it loads
# once that screen is drawn, while the reader looks at it, so the first file need not wait for it
if "scipy.spatial" not in sys.modules:
    threading.Thread(target=lambda: (__import__("scipy.ndimage"), __import__("scipy.spatial")),
                     daemon=True).start()
