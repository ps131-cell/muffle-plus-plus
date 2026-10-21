"""Import tests for a patient file (docs/WORKSPACE.md, "Import tests").

The patient file's Import tests view calls ``render_view(file)``: a button opens a dialog with
one input adapter per test type (lab results CSV, a report as text or PDF, a slide region image,
a DICOM file, a clinician's note). Each checks its file on intake (``muffle.imports``), shows
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

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle import imports as intake  # noqa: E402
from muffle.workbench.documents import FIELDS, extract  # noqa: E402
from muffle.workspace import MARKERS, PatientFile, Test  # noqa: E402

KINDS = ("Lab results (CSV)", "Report (text or PDF)", "Slide region image", "DICOM file",
         "Clinician note")
SESSION_ONLY = ("Imports are kept for this browser session only: nothing is saved to the server, "
                "the patient data or the repository, and closing the tab discards them. Only "
                "public or synthetic data may be imported.")
EXAMPLE = "month,marker,value,unit,reference limit\n27,CA 15-3,58,U/mL,30\n27,CEA,4.1,ng/mL,5\n"


def render_view(file: PatientFile) -> None:
    """The Import tests view: the button that opens the dialog, and this session's imports."""
    st.markdown("#### Import tests :green-badge[implemented]")
    st.markdown("Lab results, a report (text or PDF), a slide region image, a DICOM file or a "
                "clinician's note. Each import is checked on intake, joins the file as tests and "
                "adds a report version; earlier versions are never overwritten.")
    st.caption(SESSION_ONLY)
    if st.button("Import a test…", type="primary", key=f"import-open-{file.id}"):
        dialog(file)
    records = st.session_state.get("imports", {}).get(file.id, [])
    versions = [v for v in file.versions if v.imported]
    if not records:
        st.caption("Nothing imported into this file in this session.")
        return
    st.markdown(f"**Imported in this session** · {len(records)}")
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


def _add(file_id: str, record: dict) -> None:
    """Store an import; the file then opens on its new latest version."""
    st.session_state.setdefault("imports", {}).setdefault(file_id, []).append(record)
    st.session_state.pop(f"version-{file_id}", None)  # the slider starts again at the latest
    st.session_state["import-added"] = True


@st.dialog("Import a test", width="large")
def dialog(file: PatientFile) -> None:
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
    if kind == KINDS[0]:
        record = _labs(file, when)
    else:
        month = int(st.number_input(f"Month of the test ({when[0].lower()}{when[1:]}; the "
                                    f"latest report is month {lo})", min_value=lo, value=lo,
                                    step=1, key="import-month"))
        source = f"imported by {by or 'no initials'} at {at}, this session"
        doc_id = f"import-{n}"
        if kind == KINDS[1]:
            record = _report(month, doc_id, source)
        elif kind == KINDS[2]:
            record = _queued(intake.image_test, ["png", "jpg", "jpeg"], month, "Slide region "
                             "image (PNG or JPEG)")
        elif kind == KINDS[3]:
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


def _labs(file: PatientFile, when: str) -> dict | None:
    up = st.file_uploader("Lab results (CSV): month or date, marker, value, unit, and optionally "
                          "reference limit", type=["csv"], key="import-csv")
    st.caption(f"Markers read: {', '.join(name for name, _ in MARKERS.values())}, in the record's "
               f"units ({', '.join(u for _, u in MARKERS.values())}). {when}; a value must be at "
               f"or after the latest report. Example: `{EXAMPLE.splitlines()[1]}`")
    st.download_button("Example CSV", EXAMPLE, file_name="lab_results_example.csv",
                       mime="text/csv", key="import-example")
    anchor = st.date_input("Date of month 0 (only for a CSV with dates)", value=None,
                           key="import-anchor", min_value=date(1990, 1, 1))
    if up is None:
        return None
    existing = {(t.details["marker"], t.month) for t in file.tests
                if t.kind == "Lab" and "marker" in t.details}
    try:
        ok, bad = intake.parse_labs(up.getvalue(), file.latest.month, anchor, existing)
    except intake.IntakeError as e:
        st.error(str(e))
        return None
    if ok:
        st.markdown(f"**Accepted** · {len(ok)} row(s)")
        st.dataframe(pd.DataFrame(ok)[["row", "month", "marker", "value", "unit", "limit"]],
                     hide_index=True, width="stretch")
    if bad:
        st.markdown(f"**Rejected** · {len(bad)} row(s), with the reason")
        st.dataframe(pd.DataFrame(bad), hide_index=True, width="stretch")
    if not ok:
        st.error("No row was accepted: nothing to add.")
        return None
    for r in ok:
        if r["key"] == "ca153" and r["limit"] and r["limit"] != 30:
            st.caption(f"Row {r['row']}: its reference limit {r['limit']:g} differs from the "
                       "record's 30; the alert rule uses the imported limit, the lab "
                       "workbench's chart still draws the record's.")
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
        st.dataframe(pd.DataFrame([{"Fact": FIELDS[f["field"]], "Value": f["value"],
                                    "Source sentence": f["quote"][:120]} for f in facts]),
                     hide_index=True, width="stretch")
    st.caption(f"{len(facts)} documented facts found by the rules; the documents workbench "
               "shows each at its sentence.")


def _report(month: int, doc_id: str, source: str) -> dict | None:
    up = st.file_uploader("Report (text or PDF with a text layer)", type=["txt", "pdf", "md"],
                          key="import-report")
    pasted = st.text_area("Or paste the report's text", key="import-report-text", height=120)
    if up is None and not pasted.strip():
        return None
    try:
        text = (intake.read_text(up.name, up.getvalue()) if up is not None
                else intake.read_text("pasted.txt", pasted.encode()))
    except intake.IntakeError as e:
        st.error(str(e))
        return None
    title = st.text_input("Title", value=up.name if up is not None else "Pathology report",
                          key="import-title", max_chars=80) or "Report"
    _facts_preview(text)
    test, observed = intake.document_test("Document", title, text, month, doc_id, source)
    return {"kind": "Report", "rejected": [], "version": {
        "tests": [test], "month": month, "observed": observed,
        "event": f"Imported report: {title} ({len(text):,} characters)"}}


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
                                       f"{d['bytes'] / 1024:,.0f} KB as received (preview)")
    if "header" in d:
        st.dataframe(pd.DataFrame(list(d["header"].items()), columns=["Header field", "Value"]),
                     hide_index=True, width="stretch")
        if d["identifiers_present"]:
            st.warning("This header carries identifying fields (" + ", ".join(
                d["identifiers_present"]) + "). They were not read into the file. Only public "
                "or de-identified data may be imported.")


def render_test(file: PatientFile, t: Test) -> None:
    """The page of an imported image or DICOM test, queued for the local pipeline."""
    st.markdown(f"#### {t.kind}: {t.name}, month {t.month} :orange-badge[{intake.QUEUED}]")
    st.info("Queued for the local pipeline: the hosted app runs no models, so this file is "
            "registered, checked and kept for this session, not analyzed. "
            + ("The slide workbench's tissue map runs on a local machine with its encoder."
               if t.details.get("pipeline") == "slides" else
               "The radiology workbench's image viewer and lesion measurements are planned.")
            + " Nothing below is a result.", icon="⏳")
    _details(t)
    st.caption(SESSION_ONLY)
