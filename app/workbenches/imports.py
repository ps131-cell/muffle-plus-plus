"""Import tests for a patient file (docs/WORKSPACE.md, "Import tests").

The patient file's Import tests view calls ``render_view(file)``: a button opens a dialog with
one input adapter per test type (lab results CSV, a report as text or PDF, sequencing results as
VCF or MAF, an imaging report, a slide region image, a DICOM file, a clinician's note). Each
checks its file on intake (``muffle.imports``), shows
what it accepts and rejects and why, and adds the tests as a new report version, signed with the
reviewer's initials. Records go to ``st.session_state.imports[file id]`` as {"kind", "version"
(``workspace.add_version``'s arguments), "rejected"}; the shell applies them on every run, so
imports last for the browser session only and never touch the bundle or the repository.
``render_test(file, test)`` is the page of an image or DICOM test queued for the local pipeline.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle import imports as intake  # noqa: E402
from muffle.data.tcga import DRIVERS as TCGA_PANEL  # noqa: E402
from muffle.longitudinal import DRIVERS as SYNTHETIC_PANEL  # noqa: E402
from muffle.report.case_tools import OBSERVED  # noqa: E402
from muffle.workbench.documents import FIELDS, extract  # noqa: E402
from muffle.workbench import labs_reference as ref  # noqa: E402
from muffle.workbench.grammar import chip, esc  # noqa: E402
from muffle.workspace import IMPLEMENTED, PatientFile, Test  # noqa: E402
from workbenches._howto import how_to, instruct  # noqa: E402
from workbenches._page import Page, table  # noqa: E402

LABS, REPORT, SEQUENCING, IMAGING = ("Lab results (CSV)", "Report (text or PDF)",
                                     "Sequencing (VCF or MAF)", "Imaging report (text or PDF)")
IMAGE, DICOM, NOTE = "Slide region image", "DICOM file", "Clinician note"
KINDS = (LABS, REPORT, SEQUENCING, IMAGING, IMAGE, DICOM, NOTE)
SESSION_ONLY = ("Imports are kept for this browser session only: nothing is saved to the server, "
                "the patient data or the repository, and closing the tab discards them. Only "
                "public or synthetic data may be imported.")
EXAMPLE = intake.LAB_EXAMPLE
HOW_TO = ("**Import a test…** opens one form per test type; each file is checked on intake. "
          "**Imported in this session** lists what arrived, as new report versions. **Look "
          "here**: what the alert rules raised on arrival. The example files below show each "
          "format.")
AFTER = ("**What happens after an import:** the file gains a new report version signed with "
         "your initials (earlier versions stay as they were); the tests open in their "
         "workbenches (lab values in Blood and lab, a report or a note in Clinical documents, "
         "sequencing in Genomics, an imaging report in Radiology); the alert rules run on what "
         "arrived, and anything they raise joins the report's attention queue. Kept for this "
         "browser session only.")
EXAMPLES = [  # one click away on the Import tests view; all written by hand, not a person's
    ("Example lab results (CSV)", intake.LAB_EXAMPLE, "lab_results_example.csv", "text/csv"),
    ("Example sequencing (MAF)", intake.MAF_EXAMPLE, "sequencing_example.maf",
     "text/tab-separated-values"),
    ("Example pathology report (text)", intake.REPORT_EXAMPLE, "pathology_report_example.txt",
     "text/plain"),
]


ADAPTERS = [  # what each adapter accepts, what it checks on intake and what the file gains
    (LABS, "month or date, marker, value, unit and optionally the lab report's interval",
     f"at most {intake.MAX_ROWS} rows; an unknown unit, a value before the latest report or a "
     "value the record already holds is rejected with the reason; units converted to the "
     "reference table's", "one Lab test per row, read by the blood and lab workbench"),
    (REPORT, "a text file or a PDF; a PDF without a text layer is a scan",
     f"at most {intake.MAX_CHARS:,} characters", "a document, read by the documents rules; a "
     "scanned PDF is queued for the local pipeline's page reader (its name and page count kept)"),
    (SEQUENCING, "an annotated VCF (VEP CSQ or SnpEff ANN) or a MAF, plain or gzip",
     f"at most {intake.MAX_RECORDS:,} records; PASS calls only; protein-altering variants in the "
     "file's breast panel; other rows rejected with the reason",
     "a Sequencing test, read by the genomics workbench"),
    (IMAGING, "a text file or a PDF (a scanned PDF is queued for the local pipeline)",
     "the read its clauses state; negated and hedged clauses set aside and listed",
     "an Imaging test, read by the radiology workbench"),
    (IMAGE, "a PNG or JPEG", f"at most {intake.MAX_IMAGE // 2**20} MB",
     "a test queued for the local pipeline (the hosted app runs no models)"),
    (DICOM, "a .dcm file", "header only; identifying fields are never read",
     "a test queued for the local pipeline"),
    (NOTE, "text typed here, signed with your initials", f"at most {intake.MAX_CHARS:,} "
     "characters", "a document, read by the documents rules"),
]
CANNOT_IMPORT = [
    "expression, methylation or protein data: no adapter yet (the TCGA cases carry theirs)",
    "images and scans are registered, not analyzed: the hosted app runs no models",
    "anything beyond this browser session: imports are not saved, and closing the tab discards "
    "them",
    "whether a file matches the source system: an import is checked for form, not verified "
    "against the laboratory or the scanner",
]


def _alert_items(file: PatientFile) -> list[dict]:
    """What this session's imports raised, as look-here items (the alerts the shell's rules
    raised on arrival)."""
    from muffle.overview import alert_key

    return [{"pointer": None, "what": a.what, "why": f"{a.rule}; threshold: {a.threshold}",
             "evidence": a.evidence, "trust": a.trust, "consequence": a.consequence,
             "month": a.month, "key": alert_key(file, a), "focus": None}
            for v in file.versions if v.imported for a in v.alerts]


def render_view(file: PatientFile) -> None:
    """The Import tests view: the button that opens the dialog, and this session's imports, in
    the shared page skeleton (``workbenches._page``)."""
    page = Page("imports", file)
    page.title(IMPLEMENTED, "kept for this browser session")
    how_to("imports", HOW_TO, spot=False)
    st.caption(SESSION_ONLY)
    records = st.session_state.get("imports", {}).get(file.id, [])
    versions = [v for v in file.versions if v.imported]
    with page.overview():
        st.markdown("Lab results, a report (text or PDF), sequencing results (VCF or MAF), an "
                    "imaging report, a slide region image, a DICOM file or a clinician's note. "
                    "Each import is checked on intake, joins the file as tests and adds a report "
                    "version; earlier versions are never overwritten. The alert rules run on "
                    f"what arrives. **{len(records)} imported** into this file in this session.")
        st.markdown(AFTER)
        with st.container(horizontal=True, gap="small", vertical_alignment="center"):
            opened = st.button("Import a test…", type="primary", key=f"import-open-{file.id}")
            for label, data, name, mime in EXAMPLES:
                st.download_button(label, data, file_name=name, mime=mime,
                                   key=f"import-example-{name}",
                                   help="A synthetic example of the format, written by hand; "
                                        "import it to see what the file gains")
        if opened:
            dialog(file)
        page.look_here(instruct(_alert_items(file)),
                       empty="Nothing raised by this session's imports.")
    with page.picture("Imported in this session"):
        if not records:
            st.caption("Nothing imported into this file in this session. Use **Import a test…** "
                       "above.")
        for v, r in zip(versions, records, strict=False):
            with st.container(border=True):
                st.markdown(f"**{v.label}** · {r['kind']} · {v.event}")
                st.caption("Tests: " + "; ".join(
                    f"{t.kind} {t.name}: {t.result}" + ("" if t.result == t.status else
                                                        f" ({t.status})") for t in v.tests)
                    + (f" · alerts raised: {len(v.alerts)}" if v.alerts else ""))
                if r["rejected"]:
                    st.caption(f"Rejected on intake: {len(r['rejected'])} row(s): " + "; ".join(
                        f"row {x['row']}: {x['reason']}" for x in r["rejected"]))
    rejected = [{"import": v.label, "kind": r["kind"], "row": x["row"], "reason": x["reason"]}
                for v, r in zip(versions, records, strict=False) for x in r["rejected"]]
    with page.details("Rejected on intake", len(rejected)):
        if rejected:
            table(rejected)
        else:
            st.caption("No row rejected in this session.")
    with page.details("What each adapter accepts", len(ADAPTERS)):
        table(pd.DataFrame(ADAPTERS, columns=["Adapter", "Accepts", "Checked on intake",
                                              "Joins the file as"]))
    with page.card():
        st.caption(chip(IMPLEMENTED))
        st.markdown("**Intake rules** · rules, no model. Each adapter checks the file's form "
                    "at the boundary (columns, units, sizes, annotations, a text layer), keeps "
                    "what it can read and lists every rejected row with the reason; nothing is "
                    "forced into a result the data can't support. **Validation:** tested on "
                    "sample files by the platform's automated tests, not validated on a set of "
                    "real laboratory exports or reports. **Signed:** every import carries the "
                    "initials and time of the person who added it.")
        st.markdown("**Known failures:** a scanned PDF without a text layer has no text to read; "
                    "a VCF stores allele fractions differently by caller, so they are not read "
                    "from a VCF; the imaging rule reads clauses, not images, and was tested on "
                    "sample sentences only.")
    with page.cannot_see(CANNOT_IMPORT):
        pass
    with page.export(empty=None if records else "Nothing to export: nothing imported in this "
                                                "session. The report export lists every import."):
        if records:
            st.download_button(
                "Download this session's imports (CSV)",
                pd.DataFrame([{"version": v.label, "kind": r["kind"], "month": v.month,
                               "event": v.event, "imported": v.imported,
                               "tests": "; ".join(f"{t.kind} {t.name}: {t.result}"
                                                  for t in v.tests),
                               "alerts": "; ".join(a.what for a in v.alerts),
                               "rejected rows": len(r["rejected"])}
                              for v, r in zip(versions, records, strict=False)]
                             ).to_csv(index=False),
                file_name=f"imports_{file.id.replace(' ', '_')}.csv", mime="text/csv",
                key=f"import-csv-{file.id}")
            st.caption("The report export (Report view) lists every import with its version.")


def _add(file_id: str, record: dict) -> None:
    """Store an import; the file then opens on its new latest version."""
    st.session_state.setdefault("imports", {}).setdefault(file_id, []).append(record)
    st.session_state.pop(f"version-{file_id}", None)  # the slider starts again at the latest
    st.session_state["import-added"] = True


def open_dialog(file: PatientFile, prefill: dict | None = None) -> None:
    """Open the import dialog; ``prefill`` ({"marker", "unit"}, from the lab workbench's "Add
    values") opens it on lab results with that analyte typed in."""
    if prefill:
        st.session_state["import-kind"] = LABS
    dialog(file, prefill)


@st.dialog("Import a test", width="large")
def dialog(file: PatientFile, prefill: dict | None = None) -> None:
    st.caption(SESSION_ONLY)
    by = st.text_input("Your initials (every import is signed)", max_chars=5, key="import-by",
                       value=st.session_state.get("reviewer") or "").strip()
    kind = st.segmented_control("Test type", KINDS, default=KINDS[0], key="import-kind") \
        or KINDS[0]
    lo = file.latest.month if file.latest.month is not None else 0
    when = ("Months count from the first tumor sequencing (month 0)" if file.kind == "synthetic"
            else "Months count from the TCGA tumor sample (month 0)")
    at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")  # the server's clock
    n = len(st.session_state.get("imports", {}).get(file.id, [])) + 1
    record = None
    if kind == LABS:
        record = _labs(file, when, prefill)
    else:
        month = int(st.number_input(f"Month of the test ({when[0].lower()}{when[1:]}; the "
                                    f"latest report is month {lo})", min_value=lo, value=lo,
                                    step=1, key="import-month"))
        source = f"imported by {by or 'no initials'} at {at}, this session"
        doc_id = f"import-{n}"
        if kind == REPORT:
            record = _report(month, doc_id, source)
        elif kind == SEQUENCING:
            record = _sequencing(file, month, source)
        elif kind == IMAGING:
            record = _imaging(month, doc_id, source)
        elif kind == IMAGE:
            record = _queued(intake.image_test, ["png", "jpg", "jpeg"], month, "Slide region "
                             "image (PNG or JPEG)")
        elif kind == DICOM:
            record = _queued(intake.dicom_test, ["dcm", "dicom"], month, "DICOM file (.dcm)")
        else:
            record = _note(month, doc_id, source, by)
    if record is not None:
        record["version"].update(by=by, at=at)
        if not by:
            st.warning("Enter your initials to sign the import.")
        st.button("Add to the file", type="primary", disabled=not by, key="import-add",
                  on_click=_add, args=(file.id, record))
    if st.session_state.pop("import-added", False):
        st.rerun()


def typed_csv(rows: pd.DataFrame) -> bytes | None:
    """The values typed into the dialog's table as the lab CSV the intake reads; None while no
    row has a value."""
    rows = rows.dropna(subset=["value"])
    rows = rows[rows["value"].astype(str).str.strip() != ""]
    return None if rows.empty else rows.to_csv(index=False).encode()


def _labs(file: PatientFile, when: str, prefill: dict | None = None) -> dict | None:
    lo = file.latest.month if file.latest.month is not None else 0
    st.markdown("**Type the values** (one row per result), or upload a CSV below")
    pre = prefill or {}
    typed = st.data_editor(
        pd.DataFrame([{"month": lo, "marker": pre.get("marker", ""), "value": float("nan"),
                       "unit": pre.get("unit", ""), "reference interval": ""}]),
        num_rows="dynamic", hide_index=True, width="stretch",
        key=f"import-typed-{pre.get('marker', '')}",
        column_config={"month": st.column_config.NumberColumn(min_value=lo, step=1),
                       "value": st.column_config.NumberColumn(),
                       "reference interval": st.column_config.TextColumn(
                           help="Optional: the lab report's own interval, as 3.5-5.0, <30 or "
                                ">60; it wins over the reference table's")})
    up = st.file_uploader("Lab results (CSV): month or date, marker, value, unit, and optionally "
                          "the lab report's reference interval", type=["csv"], key="import-csv")
    known = [a["name"] for a in ref.ANALYTES.values() if not a.get("derived")]
    st.caption(f"Any analyte. The reference table knows {len(known)} ({', '.join(known)}) and "
               "converts their usual units (µmol/L, mmol/L, g/L, µkat/L, /µL ...); any other "
               "analyte is kept as reported, flagged only against its own interval. A reference "
               "interval reads 3.5-5.0, <30 or >60; the lab report's own interval wins over the "
               f"table's. {when}; a value must be at or after the latest report. Example: "
               f"`{EXAMPLE.splitlines()[1]}`")
    st.download_button("Example CSV", EXAMPLE, file_name="lab_results_example.csv",
                       mime="text/csv", key="import-example")
    anchor = st.date_input("Date of month 0 (only for a CSV with dates)", value=None,
                           key="import-anchor", min_value=date(1990, 1, 1))
    data = up.getvalue() if up is not None else typed_csv(typed)
    if data is None:
        return None
    existing = {(t.details["marker"], t.month) for t in file.tests
                if t.kind == "Lab" and "marker" in t.details}
    try:
        ok, bad = intake.parse_labs(data, file.latest.month, anchor, existing)
    except intake.IntakeError as e:
        st.error(str(e))
        return None
    if ok:
        st.markdown(f"**Accepted** · {len(ok)} row(s)")
        shown = pd.DataFrame(ok)[["row", "month", "marker", "value", "unit", "low", "limit",
                                  "reported"]]
        shown[["low", "limit"]] = shown[["low", "limit"]].map(  # "—", not "None", where none
            lambda v: "—" if pd.isna(v) else f"{v:g}")
        shown["reported"] = shown["reported"].fillna("—")
        table(shown.rename(columns={"low": "lower limit", "limit": "upper limit",
                                    "reported": "as reported (converted)"}),
              mono=("lower limit", "upper limit", "as reported (converted)"))
    if bad:
        st.markdown(f"**Rejected** · {len(bad)} row(s), with the reason")
        table(bad)
    if not ok:
        st.error("No row was accepted: nothing to add.")
        return None
    unlisted = sorted({r["marker"] for r in ok if r["key"] not in ref.ANALYTES})
    if unlisted:
        st.caption(f"{', '.join(unlisted)}: {ref.UNLISTED}; kept in the unit reported and flagged "
                   "only against the interval given with it.")
    tests, observed = intake.lab_tests(ok)
    month = max(r["month"] for r in ok)
    return {"kind": "Lab results", "rejected": bad, "version": {
        "tests": tests, "month": month, "observed": observed,
        "event": "Imported lab results: " + "; ".join(
            f"{r['marker']} {r['value']:g} {r['unit']}"
            + ("" if r["month"] == month else f" (month {r['month']})") for r in ok)}}


def _facts_preview(text: str) -> None:
    facts = extract(text)
    if facts:
        table([{"Fact": FIELDS[f["field"]], "Value": f["value"],
                "Source sentence": f["quote"][:120], "Status": "documented"} for f in facts],
              colors={"documented": "blue"})
    st.caption(f"{len(facts)} documented facts found by the rules; the documents workbench "
               "shows each at its sentence.")


def _upload_text(label: str, key: str, default: str, month: int = 0):
    """A report uploaded (text or PDF) or pasted, checked on intake → (text, title); a scanned
    PDF → its queued record (a dict)."""
    up = st.file_uploader(f"{label} (text or PDF; a scanned PDF is queued for the local "
                          "pipeline)", type=["txt", "pdf", "md"], key=key)
    pasted = st.text_area("Or paste the report's text", key=f"{key}-text", height=120)
    if up is None and not pasted.strip():
        return None
    try:
        text = (intake.read_text(up.name, up.getvalue()) if up is not None
                else intake.read_text("pasted.txt", pasted.encode()))
    except intake.ScannedPDF as e:
        test = intake.scanned_test(up.name, up.getvalue(), month, e.pages, label)
        st.info(f"{e} The hosted app runs no models: the local pipeline reads the pages, then "
                "the rules and the named-entity model read the text exactly as a text report's. "
                "Kept here: the file's name and page count.", icon="⏳")
        return {"kind": f"{label} (scanned)", "rejected": [], "version": {
            "tests": [test], "month": month, "observed": [],
            "event": f"Imported scanned report: {up.name} ({e.pages} pages, {intake.QUEUED})"}}
    except intake.IntakeError as e:
        st.error(str(e))
        return None
    title = st.text_input("Title", value=up.name if up is not None else default,
                          key=f"{key}-title", max_chars=80) or default
    return text, title


def _report(month: int, doc_id: str, source: str) -> dict | None:
    got = _upload_text("Report", "import-report", "Pathology report", month)
    if got is None or isinstance(got, dict):
        return got
    text, title = got
    _facts_preview(text)
    test, observed = intake.document_test("Document", title, text, month, doc_id, source)
    return {"kind": "Report", "rejected": [], "version": {
        "tests": [test], "month": month, "observed": observed,
        "event": f"Imported report: {title} ({len(text):,} characters)"}}


def _sequencing(file: PatientFile, month: int, source: str) -> dict | None:
    panel = SYNTHETIC_PANEL if file.kind == "synthetic" else TCGA_PANEL
    up = st.file_uploader("Sequencing results: a VCF annotated by VEP (CSQ) or SnpEff (ANN), or "
                          "a MAF; plain or gzip", type=["vcf", "maf", "tsv", "txt", "gz"],
                          key="import-vcf")
    st.caption(f"Kept: protein-altering variants in the {len(panel)} breast panel genes this "
               f"file's genomics workbench reads ({', '.join(panel)}); from a VCF, PASS calls "
               "only. Genes and protein changes come from the file's own annotation: nothing is "
               "called on intake. One sample per file.")
    if up is None:
        return None
    try:
        ok, bad, meta = intake.parse_variants(up.getvalue(), panel)
    except intake.IntakeError as e:
        st.error(str(e))
        return None
    if ok:
        st.markdown(f"**Accepted** · {len(ok)} variant(s) · {meta['format']}, sample "
                    f"{meta['sample'] or 'not named in the file'}")
        table(pd.DataFrame(ok)[["row", "variant", "consequence", "allele_fraction"]],
              mono=("allele_fraction",))
    if bad:
        st.markdown(f"**Rejected** · {len(bad)} row(s), with the reason (row = line in the file)")
        table(bad)
    if not ok:
        st.error("No panel variant was accepted: nothing to add. A variant file lists calls, "
                 "not coverage, so it can't show that the panel's genes are unmutated.")
        return None
    seen = {var for t in file.tests if t.workbench == "mutations" for var in t.details["variants"]}
    again = [r["variant"] for r in ok if r["variant"] in seen]
    if again:
        st.caption(f"Sequenced before in this file: {', '.join(again)}; observed again at month "
                   f"{month}. The newly-sequenced-driver alert runs on the others.")
    test = intake.sequencing_test(ok, meta, month, up.name, panel, source)
    return {"kind": "Sequencing", "rejected": bad, "version": {
        "tests": [test], "month": month, "observed": [],
        "event": f"Imported sequencing ({meta['format']}): {test.result}"}}


def _imaging(month: int, doc_id: str, source: str) -> dict | None:
    got = _upload_text("Imaging report", "import-imaging", "Imaging report", month)
    if got is None or isinstance(got, dict):
        return got
    text, title = got
    test = intake.imaging_test(title, text, month, doc_id, source)
    read_details(test.details)
    return {"kind": "Imaging report", "rejected": [], "version": {
        "tests": [test], "month": month, "observed": [],
        "event": f"Imported imaging report: {title} ({test.result})"}}


def read_details(d: dict) -> None:
    """What the intake rule read in an imaging report, and the clauses it set aside."""
    words = f' · "{esc(d["words"])}"' if d["words"] else ""
    st.markdown(f"**Read** {chip(OBSERVED)}: {d['read']}{words}  \n**New distant sites named:** "
                + (", ".join(d["new_sites"]) or "none"))
    if d["set_aside"]:
        table(pd.DataFrame(d["set_aside"]).rename(
            columns={"clause": "Clause set aside", "why": "Why"}))
    st.caption(f"Rule: {d['rule']}. It raises progression on imaging when the read is "
               "progression, and a new metastatic site for a named site not in the record "
               "before. Tested on sample sentences, not validated on a set of real reports: the "
               "report itself is the record.")


def _note(month: int, doc_id: str, source: str, by: str) -> dict | None:
    text = st.text_area("Clinician note (signed with your initials)", key="import-note",
                        height=160, max_chars=intake.MAX_CHARS)
    if not text.strip():
        return None
    _facts_preview(text)
    test, observed = intake.document_test("Clinic note", f"Clinician note ({by or '?'})",
                                          text.strip(), month, doc_id, source)
    return {"kind": "Clinician note", "rejected": [], "version": {
        "tests": [test], "month": month, "observed": observed,
        "event": f"Clinician note by {by or 'no initials'}"}}


def _queued(make, types: list[str], month: int, label: str) -> dict | None:
    up = st.file_uploader(label, type=types, key=f"import-{types[0]}")
    st.caption("Registered as a test queued for the local pipeline: the hosted app runs no "
               "models, so nothing is analyzed here.")
    if up is None:
        return None
    try:
        test = make(up.name, up.getvalue(), month)
    except intake.IntakeError as e:
        st.error(str(e))
        return None
    _details(test)
    return {"kind": test.kind, "rejected": [], "version": {
        "tests": [test], "month": month, "observed": [],
        "event": f"Imported {test.kind.lower()}: {test.name} ({intake.QUEUED})"}}


def _details(t: Test) -> None:
    d = t.details
    if "preview" in d:
        st.image(d["preview"], caption=f"{d['width']}×{d['height']} px {d['format']}, "
                                       f"{d['bytes'] / 1024:,.0f} KB as received (preview)",
                 alt=f"Preview of the imported image {d.get('file', '')}".strip())
    if "pages" in d:
        st.markdown(f"**{d['file']}** · scanned PDF, {d['pages']} page"
                    f"{'s' if d['pages'] != 1 else ''}, {d['bytes'] / 1024:,.0f} KB, no text "
                    "layer")
    if "header" in d:
        table(pd.DataFrame(list(d["header"].items()), columns=["Header field", "Value"]))
        if d["identifiers_present"]:
            st.warning("This header carries identifying fields (" + ", ".join(
                d["identifiers_present"]) + "). They were not read into the file. Only public "
                "or de-identified data may be imported.")


def render_test(file: PatientFile, t: Test) -> None:
    """The page of an imported image or DICOM test, queued for the local pipeline, in the shared
    page skeleton."""
    page = Page("intake", file, t)
    page.title(intake.QUEUED, colors={intake.QUEUED: "orange"})
    st.caption(SESSION_ONLY)
    with page.overview():
        st.info("Queued for the local pipeline: the hosted app runs no models, so this file is "
                "registered, checked and kept for this session, not analyzed. "
                + ("The slide workbench's tissue map runs on a local machine with its encoder."
                   if t.details.get("pipeline") == "slides" else
                   "Scanned PDF: the local pipeline, on a machine outside this app, reads "
                   "each page with ibm-granite/granite-docling-258M, then the documents rules and "
                   "the named-entity model read the text exactly as a text report's; the text it "
                   "writes is checked by a person and imported as a report. Text accuracy on "
                   "four scans: Methods and validation."
                   if t.details.get("pipeline") == "documents" else
                   "The radiology workbench's image viewer and lesion measurements run on a "
                   "local machine.")
                + " Nothing below is a result.", icon="⏳")
        page.look_here([], empty="Nothing to look at: the file is registered, not analyzed.")
    with page.picture("What arrived"):
        _details(t)
    with page.card():
        st.markdown("**Intake rules** · rules, no model: the file's type and size are checked "
                    f"(at most {intake.MAX_IMAGE // 2**20} MB); a DICOM file's header is read "
                    "for its acquisition fields only, never its pixels or the patient's "
                    "identifying fields; a PDF without a text layer is kept by its name and page "
                    "count. Tested on sample files, not validated.")
    with page.cannot_see(["anything in the image: nothing was analyzed here",
                          "the patient's identity: identifying header fields are never read"]):
        pass
    with page.export(empty="Nothing to export: nothing was analyzed."):
        pass
