"""Test import for a patient file (docs/WORKSPACE.md, "Import tests"): each input adapter checks
its file at the boundary and turns what it accepts into tests for ``workspace.add_version``.

* Lab results, CSV with columns month (or date), marker, value, unit and an optional reference
  limit or interval: one Lab test per accepted row, rejected rows listed with the reason. Any
  analyte: the reference table's (``muffle.workbench.labs_reference``) are converted to its
  canonical unit, others are kept as reported under a ``lab:<name>`` key.
* A report as text or PDF (pypdf's text layer; no OCR) and a clinician's note: a document test,
  read by the documents rules (``muffle.workbench.documents``).
* A slide region image (PNG or JPEG) and a DICOM file (header only, never the pixels or the
  patient's identifiers): tests queued for the local pipeline, since the hosted app runs no
  models.

Imports live in the browser session only and never touch the bundle or the repo's data. Only
public or synthetic data may be imported (docs/WORKSPACE.md). Pure functions; the dialog is
``app/workbenches/imports.py``.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from muffle.longitudinal import DAYS_PER_MONTH
from muffle.workbench import documents
from muffle.workbench import labs_reference as ref
from muffle.workspace import IMPLEMENTED, Test

QUEUED = "queued for the local pipeline"
# An example lab CSV (synthetic values, months after SYNTHETIC-001's latest report): tumor
# markers, liver and bone chemistry, kidney, a CBC and one analyte the reference table does not
# list, in mixed units, some with the lab report's own interval.
LAB_EXAMPLE = """month,marker,value,unit,reference interval
25,CA 15-3,44,U/mL,<30
25,CEA,3.6,ng/mL,<5
25,Alkaline phosphatase,128,U/L,35-104
25,ALT,38,U/L,7-45
25,GGT,30,U/L,5-36
25,Calcium,2.58,mmol/L,2.15-2.55
25,Albumin,34,g/L,35-50
25,Creatinine,72,umol/L,45-90
25,Hemoglobin,11.2,g/dL,
25,WBC,3.6,x10^9/L,
25,Neutrophils,1.7,x10^9/L,
25,Platelets,168,x10^9/L,
25,Glucose,7.4,mmol/L,3.9-5.5
27,CA 15-3,58,U/mL,<30
27,CEA,4.1,ng/mL,<5
27,Alkaline phosphatase,188,U/L,35-104
27,ALT,61,U/L,7-45
27,AST,52,U/L,8-43
27,GGT,34,U/L,5-36
27,Bilirubin,22,umol/L,
27,Calcium,2.71,mmol/L,2.15-2.55
27,Albumin,33,g/L,35-50
27,Creatinine,80,umol/L,45-90
27,Hemoglobin,10.9,g/dL,
27,WBC,3.1,x10^9/L,
27,Neutrophils,1.2,x10^9/L,
27,Platelets,142,x10^9/L,
27,LDH,260,U/L,
27,Glucose,8.1,mmol/L,3.9-5.5
"""
MAX_TEXT = 5 * 2**20    # bytes: a CSV, a text report or a PDF
MAX_IMAGE = 20 * 2**20  # bytes: a slide region image or a DICOM file
MAX_ROWS = 500
MAX_CHARS = 200_000     # characters of document text
COLUMNS = {"month": "month", "date": "date", "marker": "marker", "test": "marker",
           "analyte": "marker", "value": "value", "result": "value", "unit": "unit",
           "units": "unit", "reference limit": "limit", "reference": "limit", "limit": "limit",
           "upper limit": "limit", "reference interval": "limit", "reference range": "limit",
           "normal range": "limit", "range": "limit"}
DICOM_FIELDS = ("Modality", "BodyPartExamined", "Manufacturer", "ManufacturerModelName", "Rows",
                "Columns", "NumberOfFrames", "SliceThickness", "PixelSpacing", "SeriesNumber")
IDENTIFIERS = ("PatientName", "PatientID", "PatientBirthDate", "OtherPatientIDs",
               "InstitutionName", "ReferringPhysicianName", "AccessionNumber")


class IntakeError(ValueError):
    """A file the import cannot take, with the reason in words for the clinician."""


def _size(data: bytes, limit: int, what: str) -> None:
    if not data:
        raise IntakeError(f"The {what} is empty.")
    if len(data) > limit:
        raise IntakeError(f"The {what} is {len(data) / 2**20:.1f} MB; the limit is "
                          f"{limit / 2**20:.0f} MB.")


def parse_labs(data: bytes, after: int | None = None, anchor: date | None = None,
               existing: set[tuple[str, int]] = frozenset()) -> tuple[list[dict], list[dict]]:
    """A lab-results CSV → (accepted, rejected) rows. Accepted: {"row", "month", "key",
    "marker", "value", "unit", "limit" (the upper reference limit), "low" (the lower one),
    "reported" (the value as reported, when it was converted)}; rejected: {"row", "reason"}.
    A reference table analyte is converted to the table's unit (a unit it does not know is
    rejected with the reason); any other analyte is kept as reported, one unit per file.
    ``after``: the latest report version's month (None: a baseline without months, so month 0
    on); earlier months are rejected, since earlier versions are never rewritten. ``anchor``:
    the date of month 0, needed when the CSV has dates (counted in whole months, rounded).
    ``existing``: (marker key, month) pairs the file already holds. Raises ``IntakeError`` for
    a file that can't be read at all."""
    _size(data, MAX_TEXT, "CSV file")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IntakeError("The CSV file is not UTF-8 text.") from None
    reader = csv.DictReader(io.StringIO(text))
    cols = {h: COLUMNS.get(" ".join((h or "").lower().replace("_", " ").split()))
            for h in reader.fieldnames or []}
    have = set(cols.values())
    need = [c for c in ("marker", "value", "unit") if c not in have]
    if "month" not in have and "date" not in have:
        need.insert(0, "month or date")
    if need:
        raise IntakeError(f"Missing column(s): {', '.join(need)}. Expected: month (or date), "
                          "marker, value, unit, and optionally reference limit.")
    if "month" not in have and anchor is None:
        raise IntakeError("The CSV has dates: set the date of month 0 to place them on this "
                          "file's timeline.")
    lo = 0 if after is None else after
    accepted, rejected, seen, units = [], [], set(existing), {}
    for n, raw in enumerate(reader, start=2):  # row 1 is the header
        if n - 1 > MAX_ROWS:
            raise IntakeError(f"More than {MAX_ROWS} rows; split the file.")
        r = {cols[k]: (v or "").strip() for k, v in raw.items() if k in cols and cols[k]}
        if not any(r.values()):
            continue
        name = " ".join(r.get("marker", "").split())
        if not name:
            rejected.append({"row": n, "reason": "no marker name"})
            continue
        key = ref.lookup(name)
        try:
            value = float(r.get("value", ""))
        except ValueError:
            rejected.append({"row": n, "reason": f"value \"{r.get('value', '')}\" is not a "
                             "number"})
            continue
        if not value > 0:
            rejected.append({"row": n, "reason": f"value {value:g} is not above 0"})
            continue
        unit = r.get("unit", "")
        if key is None:  # not in the reference table: kept as reported, in one unit per file
            key = ref.custom_key(name)
            if not unit:
                rejected.append({"row": n, "reason": f"{name} is not in the reference table, so "
                                 "it needs a unit"})
                continue
            if units.setdefault(key, unit) != unit:
                rejected.append({"row": n, "reason": f"unit \"{unit}\" differs from this file's "
                                 f"earlier {units[key]} for {name}; not converted"})
                continue
            factor, canonical = 1.0, unit
        else:
            name = ref.ANALYTES[key]["name"]
            try:
                factor, canonical = ref.convert(key, 1.0, unit)
            except ValueError as e:
                rejected.append({"row": n, "reason": str(e)})
                continue
        try:
            if r.get("month"):
                month = int(float(r["month"]))
                if month != float(r["month"]):
                    raise ValueError
            else:
                month = round((date.fromisoformat(r.get("date", "")) - anchor).days
                              / DAYS_PER_MONTH)
        except (ValueError, TypeError):
            rejected.append({"row": n, "reason": "month must be a whole number, or date "
                             "YYYY-MM-DD"})
            continue
        if month < lo:
            rejected.append({"row": n, "reason": f"month {month} is before the latest report "
                             f"(month {lo}); earlier versions are never rewritten"})
            continue
        if (key, month) in seen:
            rejected.append({"row": n, "reason": f"{name} already has a value at month {month}"})
            continue
        low = limit = None
        if r.get("limit"):
            try:
                low, limit = reference_interval(r["limit"])
            except ValueError:
                rejected.append({"row": n, "reason": f"reference \"{r['limit']}\" is not a "
                                 "number or an interval (3.5-5.0, <30, >60)"})
                continue
        seen.add((key, month))
        accepted.append({
            "row": n, "month": month, "key": key, "marker": name,
            "value": _scaled(value, factor), "unit": canonical, "limit": _scaled(limit, factor),
            "low": _scaled(low, factor), "reported": None if factor == 1 else f"{value:g} {unit}"})
    if not accepted and not rejected:
        raise IntakeError("The CSV file has a header but no rows.")
    return accepted, rejected


def reference_interval(text: str) -> tuple[float | None, float | None]:
    """A lab report's reference as (low, high): "3.5-5.0", "<30" or "≤30", ">60" or "≥60", or a
    plain number, read as the upper limit. Raises ValueError for anything else."""
    t = text.strip().replace("–", "-").replace("—", "-").replace(" ", "")
    if t[:1] in ("<", "≤"):
        return None, float(t.lstrip("<≤="))
    if t[:1] in (">", "≥"):
        return float(t.lstrip(">≥=")), None
    lo, sep, hi = t.partition("-")
    return (float(lo), float(hi)) if sep and lo else (None, float(t))


def _scaled(v: float | None, factor: float) -> float | None:
    """A converted value to 4 significant digits; an unconverted one as reported."""
    return None if v is None else v if factor == 1 else float(f"{v * factor:.4g}")


def lab_tests(rows: list[dict]) -> tuple[list[Test], list[list[str]]]:
    """Accepted lab rows → Lab tests (each carrying its record event for the lab workbench) and
    the report's "Latest <marker>" rows. An imported reference interval and, for an analyte the
    reference table does not list, its name and unit go into the event's ``meta``."""
    tests, latest = [], {}
    for r in sorted(rows, key=lambda r: r["month"]):
        lo, hi = r.get("low"), r["limit"]
        limit = ("" if lo is None and hi is None else f"; reference below {hi:g}" if lo is None
                 else f"; reference {lo:g} or above" if hi is None
                 else f"; reference {lo:g}-{hi:g}")
        reported = f"; reported as {r['reported']}" if r.get("reported") else ""
        event = {"month": r["month"], "kind": "Lab", r["key"]: r["value"],
                 "text": f"{r['marker']} {r['value']:g} {r['unit']} (imported{limit}{reported})"}
        meta = {} if r["key"] in ref.ANALYTES else {"name": r["marker"], "unit": r["unit"]}
        if limit:
            meta["ref"] = (lo, hi, f"the imported lab report (month {r['month']})")
        if meta:
            event["meta"] = {r["key"]: meta}
        tests.append(Test(
            "Lab", r["month"], r["marker"], f"{r['value']:g} {r['unit']}", "labs", IMPLEMENTED,
            {"marker": r["key"], "value": r["value"],
             "limit": (hi, "the imported lab result") if hi else None, "event": event}))
        latest[f"Latest {r['marker']}"] = f"{r['value']:g} {r['unit']} (month {r['month']}, " \
                                          "imported)"
    return tests, [[k, v] for k, v in latest.items()]


def read_text(name: str, data: bytes) -> str:
    """A report's text: a PDF's text layer (pypdf) or a UTF-8 text file. Raises
    ``IntakeError`` for an empty, oversize, encrypted or image-only file."""
    _size(data, MAX_TEXT, "file")
    if name.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        try:
            from pypdf import PdfReader
            from pypdf.errors import PdfReadError
        except ImportError:  # pragma: no cover - app/requirements.txt lists pypdf
            raise IntakeError("PDF reading is not installed here (pypdf).") from None
        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise IntakeError("The PDF is encrypted; export it without a password.")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as e:
            raise IntakeError(f"The PDF could not be read ({e}).") from None
        if not text.strip():
            raise IntakeError("The PDF has no text layer (a scanned image?): text is not "
                              "recognized from images on intake.")
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise IntakeError("The file is not UTF-8 text or a PDF.") from None
    text = text.strip()
    if not text:
        raise IntakeError("The document is empty.")
    if len(text) > MAX_CHARS:
        raise IntakeError(f"The document has {len(text):,} characters; the limit is "
                          f"{MAX_CHARS:,}.")
    return text


def document_test(kind: str, title: str, text: str, month: int, doc_id: str,
                  source: str) -> tuple[Test, list[list[str]]]:
    """A document as a test of the documents workbench, with the facts the rules found as its
    result and one report row naming them (none when the rules found nothing)."""
    line = documents.summary(documents.extract(text, doc_id))
    test = Test(kind, month, title, line or "no key pathology fact found by the rules",
                "documents", IMPLEMENTED,
                {"document": doc_id, "title": title, "text": text, "source": source})
    return test, ([[f"Documented in {title} (month {month})", line]] if line else [])


def image_test(name: str, data: bytes, month: int) -> Test:
    """A slide region image (PNG or JPEG), checked and kept as a small preview; queued."""
    _size(data, MAX_IMAGE, "image")
    from PIL import Image, UnidentifiedImageError  # Streamlit's own dependency

    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt, (w, h) = im.format, im.size
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            im.thumbnail((512, 512))
            out = io.BytesIO()
            im.convert("RGB").save(out, "PNG")
    except (UnidentifiedImageError, OSError, SyntaxError):
        raise IntakeError("The file is not a readable PNG or JPEG image.") from None
    if fmt not in ("PNG", "JPEG"):
        raise IntakeError(f"The image is {fmt}; PNG or JPEG only.")
    return Test("Slide region", month, name, QUEUED, "intake", QUEUED,
                {"file": name, "bytes": len(data), "format": fmt, "width": w, "height": h,
                 "preview": out.getvalue(), "pipeline": "slides"})


def dicom_test(name: str, data: bytes, month: int) -> Test:
    """A DICOM file's technical header (pydicom, pixels not read); queued. Identifying fields
    are never read into the test: only whether the header carries any."""
    _size(data, MAX_IMAGE, "DICOM file")
    try:
        import pydicom
        from pydicom.errors import InvalidDicomError
    except ImportError:  # pragma: no cover - app/requirements.txt lists pydicom
        raise IntakeError("DICOM reading is not installed here (pydicom).") from None
    try:
        ds = pydicom.dcmread(io.BytesIO(data), stop_before_pixels=True)
    except (InvalidDicomError, EOFError, ValueError, TypeError):
        raise IntakeError("The file is not a DICOM file (no DICM header).") from None
    header = {}
    for f in DICOM_FIELDS:
        v = ds.get(f)
        if v is not None and str(v).strip():
            header[f] = str(v)
    sop = ds.get("SOPClassUID")
    if sop is not None:
        header["SOPClass"] = getattr(sop, "name", str(sop))
    ids = [f for f in IDENTIFIERS if str(ds.get(f) or "").strip()]
    return Test("Scan (DICOM)", month, name, QUEUED, "intake", QUEUED,
                {"file": name, "bytes": len(data), "header": header,
                 "identifiers_present": ids, "pipeline": "imaging"})
