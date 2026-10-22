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
import logging
import os
import sys
import tempfile
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
if getattr(sys, "_muffle_code_digest", None) != CODE_DIGEST:
    purge_modules(("charts", "methods_page", "muffle", "timeline_page", "workbenches"))
    st.cache_resource.clear()
    st.cache_data.clear()
    sys._muffle_code_digest = CODE_DIGEST

import charts  # noqa: E402
import timeline_page  # noqa: E402
from workbenches import evolution as evolution_page  # noqa: E402
from workbenches import genomics, labs, omics  # noqa: E402
from workbenches._page import land, strict  # noqa: E402

import guide  # noqa: E402
import navigation as nav  # noqa: E402

from muffle import crosstest, evolution, overview, workspace  # noqa: E402
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
FILES, CASES = {}, {}  # patient id -> PatientFile; and for a TCGA file, its held-out case
if TL:
    synthetic = workspace.synthetic_file(TL)
    FILES[synthetic.id] = synthetic
SLIDE_CASES = APP / "workbenches" / "slides_results" / "cases.json"  # index -> scored slides
SLIDE_CASES = json.loads(SLIDE_CASES.read_text()) if SLIDE_CASES.exists() else {}
IMAGING = load_index(APP / "workbenches" / "radiology_results")  # public TCIA studies by case
for c in sorted(demo.cases, key=lambda c: (c.index not in demo.notes, -c.percentile)):
    pf = workspace.case_file(c, demo.c_index, slides=SLIDE_CASES.get(str(c.index), ()),
                             documents=case_documents(c.index),
                             imaging=IMAGING.get(c.index))
    FILES[pf.id], CASES[pf.id] = pf, c


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


BUNDLE_FILES = dict(FILES)  # as the bundle and the repo hold them, before this session's imports
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
    """A recently opened file's button: open it on its report."""
    st.session_state.update(patient=pid, view="Report")


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
        st.space("stretch")
        help_slot = st.empty()  # the guide's "?", for the screen drawn below
    if pid is None:
        first.markdown("**Patients**", width="content")
        with help_slot.container():
            guide.help_icon("patients")
        st.title("MuFFLe++")
        st.markdown("An evidence-linked picture of each patient's breast cancer, updated as "
                    "the record grows. Every finding is marked **observed**, **model "
                    "inference** or **hypothesis**.")
        st.caption(DISCLAIMER)
        guide.walkthrough()
        recent = [p for p in st.session_state.get("recent", []) if p in FILES]
        if recent:
            with st.container(horizontal=True, gap="small", vertical_alignment="center"):
                st.caption("Recently opened:", width="content")
                for p in recent:
                    st.button(p, key=f"recent-{p}", on_click=open_file, args=(p,),
                              help=f"Open {p} on its latest report")
        nav.sync(None, None, None, None)  # no file open: no test, pointer or version
        safely("The patient list", patient_list)
    else:
        first.button("Patients", type="tertiary", key="crumb-patients", on_click=to_list,
                     help="Back to the patient list")
        screen = patient_file(FILES[pid], header, tail)
        with help_slot.container():
            guide.help_icon(screen)


def open_selected():
    """Row click in the patient list: open that file (with a fresh list for next time)."""
    rows = st.session_state[f"list-{st.session_state.list_n}"].selection.rows
    if rows:
        st.session_state.patient = st.session_state.list_ids[rows[0]]
        st.session_state.list_n += 1


SOURCE = args.bundle or (f"{args.ckpt}|{args.data}" if Path(args.ckpt).exists() and
                         (Path(args.data) / "cohort.npz").exists() else BUNDLE_URL)


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
    q, sos = st.columns([3, 1], vertical_alignment="center")
    query = q.text_input("Search", key="list-search", label_visibility="collapsed",
                         placeholder="Search a patient, a gene (PIK3CA), a subtype (luminal), a "
                                     "stage (stage III) or a workbench (slides)")
    open_sos = sos.toggle("Open SOS alerts only", key="list-sos",
                          help="Files with an alert no reviewer has marked yet.")
    f = st.columns([2, 2, 1, 2])
    subtypes = f[0].multiselect("PAM50 subtype", sorted({r["subtype"] for r in rows}),
                                key="list-subtype", placeholder="Any subtype")
    genes = f[1].multiselect("Mutated gene", sorted({g for r in rows for g in r["genes"]}),
                             key="list-gene", placeholder="Any gene")
    stages = f[2].multiselect("Stage", [s for s in ("I", "II", "III", "IV", "not recorded")
                                        if any(r["stage"] == s for r in rows)],
                              key="list-stage", placeholder="Any")
    holds = f[3].pills("Has", ["Slides", "Imaging", "Documents"], selection_mode="multi",
                       key="list-holds")
    by = st.segmented_control("Sort by", overview.SORTS, default=overview.SORTS[0],
                              required=True, key="list-sort",
                              help="Last update: an import of this session, then the record's "
                                   "latest month. Risk: the cohort percentile of the TCGA files "
                                   "(the synthetic patient's 12-month risk is another measure, "
                                   "listed after them). Open SOS: alerts no reviewer has marked.")
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


# --- Patients: one patient file ----------------------------------------------------------------
VIEWS = ("Report", "Tests", "Timeline", "Evolution", "Import tests")


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
        st.page_link(METHODS, label="Methods and validation", icon="📖")
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
        view = st.segmented_control("View", VIEWS, required=True, key="view",
                                    bind="query-params", label_visibility="collapsed")
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
    with tail:
        st.markdown(nav.SEP, width="content")
        st.markdown(view if shown is None else f"{view} {nav.SEP} **{nav.crumb(shown)}**",
                    width="content")
    test = nav.test_id(shown) if shown is not None else None
    p = ss.get("_pointer") or {}
    here = (p.get("pid"), p.get("view"), p.get("test")) == (pf.id, view, test)
    nav.sync(pf.id, test, p.get("pointer") if here else None, None if i == last else i)
    return SCREENS.get(shown.workbench, "report") if shown is not None else {
        "Report": "report", "Timeline": "timeline", "Evolution": "evolution",
        "Import tests": "imports"}.get(view, "report")


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
    if t and any((x.kind, x.month, x.name) == t for x in pf.tests):
        ss[f"picked-{pf.id}"] = t
        ss[f"kinds-{pf.id}"] = []  # a type filter must not hide the test
        ss.tests_n += 1
        return t
    return None


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

    left, right = st.columns(2)
    with left:
        st.markdown(f"**Characterization and record** {tags(OBSERVED)}")
        st.markdown("\n".join(f"- **{k}:** {esc(val)}" for k, val in v.observed))
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
              on_click=lambda: st.session_state.update(view="Evolution"))
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
    with st.expander("Caveats, data sources and model versions"):
        st.markdown(f"- **Model:** {pf.model['name']} ({pf.model['status']}); endpoint: "
                    f"{pf.model['endpoint']}.\n" + "\n".join(f"- {s}" for s in sources(pf)))
    page = workspace.report_markdown(pf, i, {var: civic_items(pf, var) for var in variants},
                                     st.session_state.reviews, sources(pf), disagree, reducers,
                                     ov["sums"], ov["queue"])
    when = "baseline" if v.month is None else f"month{v.month}"
    st.download_button("Download this report version (Markdown)", page,
                       file_name=f"{pf.id.replace(' ', '_')}_{when}.md", mime="text/markdown",
                       help="One page: numbers, sources, placeholders, model versions and your "
                            "review marks.")
    if case is not None:
        case_note(case)


TRUST_COLORS = {"strong": "green", "moderate": "orange", "weak": "red"}
CARD_WIDTH, CARD_TEXT = 240, 150  # px; characters a card shows before "more"


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
        memo[key] = {"sums": overview.summaries(pf, i, lookup), "disagree": disagree,
                     "reducers": crosstest.uncertainty_reducers(pf, i),
                     "queue": overview.attention(pf, i, overview.queues(pf, i, lookup),
                                                 disagree)}
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
    gaps = overview.absent(ov["sums"])
    if gaps:
        st.caption("Not in this file: " + "; ".join(gaps) + ".")


def finding_card(pf: workspace.PatientFile, i: int, c: dict, pointer: str | None = None):
    """A card: the statement with its evidence label and trust; "Why?" names the source test,
    the method and version, the threshold's source and the trust; "Open" lands on the evidence."""
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
    with st.container(horizontal=True, gap="small"):  # wraps in a narrow card
        with st.popover("Why?"):
            st.markdown(f"**Source test:** {esc(c['source'])}  \n**Method and version:** "
                        f"{esc(c['method'])}  \n**Threshold:** {esc(c['threshold'])}  \n"
                        f"**Trust:** {c['trust']}  \n**Evidence:** {c['evidence']}")
        if c["opens"]:
            st.button("Open", key=f"card-{pf.id}-{i}-{c['what']}", on_click=open_evidence,
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
                          on_click=lambda: ss.update({only: False, pos: 0}))
            return
        k = ss.get(pos, 0) % len(shown)
        cur = shown[k]
        c = st.columns(6)
        # in tab order: previous, next, pin, mark reviewed, unsure list, open (docs/ux.md §7)
        c[0].button("Previous", key=f"prev-{pos}", shortcut="K", width="stretch",
                    help="The previous item (key k)", on_click=lambda: ss.update({pos: k - 1}))
        c[1].button("Next", key=f"next-{pos}", shortcut="J", width="stretch",
                    help="The next item (key j)", on_click=lambda: ss.update({pos: k + 1}))
        c[2].button("Unpin" if cur["key"] in pins else "Pin", key=f"pin-{pos}", shortcut="P",
                    width="stretch", help="Pin it to the top of the report (key p)",
                    on_click=toggle_pin, args=(cur["key"], cur["what"]))
        c[3].button("Mark reviewed", key=f"reviewed-{pos}", shortcut="M", width="stretch",
                    disabled=cur["key"] in reviews, help="Mark it reviewed, with your "
                                                         "initials (key m)",
                    on_click=mark, args=(cur["key"], cur["what"], "reviewed"))
        c[4].button("Whole queue" if ss.get(only) else "Unsure list", key=f"unsure-{pos}",
                    shortcut="U", width="stretch",
                    help="Items marked second look, or of weak trust (key u)",
                    on_click=lambda: ss.update({only: not ss.get(only), pos: 0}))
        c[5].button("Open", key=f"open-{pos}", shortcut="O", type="primary", width="stretch",
                    help="Open its evidence in its workbench (key o)",
                    disabled=not cur["opens"], on_click=open_evidence,
                    args=(pf, i, cur["opens"], cur["focus"], cur["pointer"],
                          {"pos": pos, "n": k, "total": len(shown), "what": cur["what"]}))
        queue_item(cur, k, len(shown), reviews)
        with st.container(height=320 if len(shown) > 8 else "content"):
            for n, x in enumerate(shown):
                line, act = st.columns([10, 1], vertical_alignment="center")
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
                               args=(pf, i, pos, n, x, len(shown)))
        st.caption("Keys: j next · k previous · p pin · m mark reviewed (Streamlit keeps r for "
                   "rerun) · u unsure list · o open. A mark here is the same mark the "
                   "workbench shows.")


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


def case_why(case):
    position, drivers, named = case_charts(case.index, SOURCE)
    left, right = st.columns(2)
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
        st.info("No test to open " + ("of this type " if kinds else "")
                + "as of this report version. Import tests brings in lab results, reports, "
                  "sequencing, imaging reports and slide images; each opens its workbench "
                  "here." + (" Clear the type filter to see every test." if kinds else ""),
                icon="🧪")
        return None
    picked = f"picked-{pf.id}"  # the last test opened here or from an alert
    if rows:
        new = (shown[rows[0]].kind, shown[rows[0]].month, shown[rows[0]].name)
        if st.session_state.get(picked) != new:  # another test: the address drops the pointer
            st.session_state.pop("_pointer", None)
        st.session_state[picked] = new
    t = next((t for t in shown if (t.kind, t.month, t.name) == st.session_state.get(picked)),
             None) or next((t for w in ("labs", "mutations", "omics", "record") for t in shown
                            if t.workbench == w), shown[0])
    st.session_state["_test_shown"] = nav.test_id(t)
    st.divider()
    name = WORKBENCH_NAMES.get(SCREENS.get(t.workbench, ""), "test's page")
    what = "The " + (name[0].lower() + name[1:] if name[1:2].islower() else name)
    safely(what, draw_test, pf, i, t, spin=f"Opening {what[0].lower() + what[1:]}…")
    return t


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


PATIENTS = st.Page(patients_page, title="Patients", icon="🗂️", default=True)
METHODS = st.Page(methods, title="Methods and validation", icon="📖", url_path="methods")
st.navigation([PATIENTS, METHODS]).run()

if LIVE:
    notes_left = max(0, CAP - st.session_state.live_used)
    budget_slot.progress(notes_left / CAP if CAP else 0,
                         text=f"Live notes left this session: {notes_left} of {CAP}")
session_marks(marks_slot)
