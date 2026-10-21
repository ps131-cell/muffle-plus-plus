"""Test import for a patient file (docs/WORKSPACE.md, "Import tests"): each input adapter checks
its file at the boundary and turns what it accepts into tests for ``workspace.add_version``.

* Lab results, CSV with columns month (or date), marker, value, unit and an optional reference
  limit or interval: one Lab test per accepted row, rejected rows listed with the reason. Any
  analyte: the reference table's (``muffle.workbench.labs_reference``) are converted to its
  canonical unit, others are kept as reported under a ``lab:<name>`` key.
* A report as text or PDF (pypdf's text layer; no OCR) and a clinician's note: a document test,
  read by the documents rules (``muffle.workbench.documents``).
* Sequencing results, an annotated VCF (VEP's CSQ or SnpEff's ANN) or a MAF: one Sequencing test
  with the protein-altering variants in the file's breast driver panel; other rows are rejected
  with the reason.
* An imaging report as text or PDF: an Imaging test with the read its sentences state
  (``imaging_read``: progression, response or stable, and the metastatic sites named new),
  negated and hedged sentences set aside.
* A slide region image (PNG or JPEG) and a DICOM file (header only, never the pixels or the
  patient's identifiers): tests queued for the local pipeline, since the hosted app runs no
  models.

Imports live in the browser session only and never touch the bundle or the repo's data. Only
public or synthetic data may be imported (docs/WORKSPACE.md). Pure functions; the dialog is
``app/workbenches/imports.py``.
"""

from __future__ import annotations

import csv
import gzip
import io
import re
from datetime import date

from muffle.data.tcga import PROTEIN_ALTERING
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
MAX_TEXT = 5 * 2**20    # bytes: a CSV, a text report, a PDF, or a VCF or MAF once unzipped
MAX_IMAGE = 20 * 2**20  # bytes: a slide region image or a DICOM file
MAX_ROWS = 500
MAX_RECORDS = 20_000    # variant records in a VCF or MAF
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
    line = documents.facts_line(documents.extract(text, doc_id))
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


# --- sequencing results: an annotated VCF or a MAF --------------------------------------------
AA3 = {"Ala": "A", "Arg": "R", "Asn": "N", "Asp": "D", "Cys": "C", "Gln": "Q", "Glu": "E",
       "Gly": "G", "His": "H", "Ile": "I", "Leu": "L", "Lys": "K", "Met": "M", "Phe": "F",
       "Pro": "P", "Ser": "S", "Thr": "T", "Trp": "W", "Tyr": "Y", "Val": "V", "Ter": "*",
       "Sec": "U", "Xaa": "X"}
MAF_ALTERING = {"Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Del", "Frame_Shift_Ins",
                "In_Frame_Del", "In_Frame_Ins", "Splice_Site", "Translation_Start_Site",
                "Nonstop_Mutation"}
ANN_FIELDS = {"gene": 3, "consequence": 1, "hgvsp": 10}  # SnpEff's fixed ANN layout
CSQ_NEEDS = ("SYMBOL", "Consequence", "HGVSp")
VCF_COLUMNS = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]
MSK_SAMPLE = re.compile(r"P-\d{7}-T\d{2}-IM\d")  # an MSK-IMPACT sample id, as in MSK-CHORD
NO_VAF_VCF = "allele fraction: not read from a VCF (callers store it differently)"
NO_VAF_MAF = "allele fraction: not in the file (no t_alt_count and t_depth)"


def _unzip(data: bytes, what: str) -> str:
    """A text file, gunzipped when it is gzip (read no further than the size limit)."""
    _size(data, MAX_TEXT, what)
    if data[:2] == b"\x1f\x8b":
        try:
            data = gzip.GzipFile(fileobj=io.BytesIO(data)).read(MAX_TEXT + 1)
        except (OSError, EOFError):
            raise IntakeError(f"The {what} is not a readable gzip file.") from None
        _size(data, MAX_TEXT, f"{what} (unzipped)")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IntakeError(f"The {what} is not UTF-8 text.") from None


def short_change(hgvsp: str) -> str | None:
    """A protein change in the app's short form: "ENSP…:p.His1047Arg" → "H1047R",
    "p.(Lys103AsnfsTer5)" → "K103Nfs*5", "p.E545K" → "E545K"; None for a synonymous, unknown
    or empty change."""
    p = hgvsp.split(":")[-1].strip().removeprefix("p.").strip("()")
    if p in ("", ".", "-", "?", "0") or "=" in p or "%3D" in p:
        return None
    return re.sub("|".join(AA3), lambda m: AA3[m.group()], p)


def _reject_msk(samples) -> None:
    if any(MSK_SAMPLE.search(s or "") for s in samples):
        raise IntakeError("The file names MSK-IMPACT samples (MSK-CHORD): that data stays local "
                          "under its license and may not be imported. Only public or synthetic "
                          "data may be imported.")


def parse_variants(data: bytes, panel) -> tuple[list[dict], list[dict], dict]:
    """A VCF (annotated by VEP or SnpEff, plain or gzip) or a MAF → (accepted, rejected, meta).
    Accepted: {"row", "gene", "change", "variant", "consequence", "allele_fraction"}; rejected:
    {"row", "reason"}, row = the line in the file; meta: {"format", "sample"}. Kept:
    protein-altering variants in ``panel`` (the genes the file's genomics workbench reads). A VCF
    keeps PASS calls only; a MAF is taken as filtered by its pipeline, as the TCGA files are.
    Raises ``IntakeError`` for a file that can't be read at all."""
    lines = _unzip(data, "sequencing file").splitlines()
    vcf = bool(lines) and lines[0].startswith("##fileformat=VCF")
    sample, rows = (_vcf if vcf else _maf)(lines, set(panel))
    accepted, rejected, seen = [], [], {}
    for r in rows:
        if "reason" in r:
            rejected.append(r)
        elif r["variant"] in seen:
            rejected.append({"row": r["row"], "reason": f"{r['variant']} repeats row "
                                                        f"{seen[r['variant']]}"})
        else:
            seen[r["variant"]] = r["row"]
            accepted.append(r)
    if not accepted and not rejected:
        raise IntakeError("The file has a header but no variant records.")
    return accepted, rejected, {"format": "VCF" if vcf else "MAF", "sample": sample}


def _vcf(lines: list[str], panel: set[str]) -> tuple[str | None, list[dict]]:
    csq = next((ln for ln in lines if ln.startswith("##INFO=<ID=CSQ,")), None)
    if csq:
        fmt = csq.split("Format: ")[-1].split('"')[0].split("|")
        missing = [f for f in CSQ_NEEDS if f not in fmt]
        if missing:
            raise IntakeError(f"The VCF's CSQ annotation lacks {', '.join(missing)}: run VEP with "
                              "--symbol and --hgvs.")
        key, idx = "CSQ", {"gene": fmt.index("SYMBOL"), "consequence": fmt.index("Consequence"),
                           "hgvsp": fmt.index("HGVSp")}
        canonical = fmt.index("CANONICAL") if "CANONICAL" in fmt else None
    elif any(ln.startswith("##INFO=<ID=ANN,") for ln in lines):
        key, idx, canonical = "ANN", ANN_FIELDS, None
    else:
        raise IntakeError("The VCF carries no gene annotation: annotate it with VEP (INFO CSQ "
                          "with SYMBOL and HGVSp) or SnpEff (INFO ANN) first. Genes and protein "
                          "changes are not called on intake.")
    head = next((n for n, ln in enumerate(lines) if ln.startswith("#CHROM")), None)
    if head is None or lines[head].split("\t")[:8] != VCF_COLUMNS:
        raise IntakeError("The VCF has no tab-separated header line " + " ".join(VCF_COLUMNS)
                          + ".")
    samples = lines[head].split("\t")[9:]
    _reject_msk(samples)
    out = []
    for n, line in enumerate(lines[head + 1:], start=head + 2):
        if not line.strip():
            continue
        if len(out) >= MAX_RECORDS:
            raise IntakeError(f"More than {MAX_RECORDS:,} variant records: filter the file to the "
                              "panel's genes first.")
        f = line.split("\t")
        if len(f) < 8:
            out.append({"row": n, "reason": "fewer than the 8 VCF columns"})
            continue
        if f[6] not in ("PASS", "."):
            out.append({"row": n, "reason": f"FILTER is {f[6]}: only PASS calls are kept"})
            continue
        info = dict(kv.partition("=")[::2] for kv in f[7].split(";"))
        if key not in info:
            out.append({"row": n, "reason": f"no {key} annotation on this record"})
            continue
        anns = [{"gene": p[idx["gene"]], "consequence": p[idx["consequence"]],
                 "hgvsp": p[idx["hgvsp"]],
                 "canonical": canonical is not None and p[canonical:canonical + 1] == ["YES"]}
                for p in (a.split("|") for a in info[key].split(","))
                if len(p) > max(idx.values())]
        out.append(_pick(n, anns, panel, NO_VAF_VCF))
    return ", ".join(samples) or None, out


def _pick(n: int, anns: list[dict], panel: set[str], vaf: str) -> dict:
    """A record's variant: its first protein-altering panel annotation with a protein change,
    the canonical transcript first; else the reason it is not kept."""
    genes = list(dict.fromkeys(a["gene"] for a in anns if a["gene"])) or ["no gene"]
    on = [a for a in anns if a["gene"] in panel]
    if not on:
        return {"row": n, "reason": f"{', '.join(genes)}: not on the breast panel the genomics "
                                    f"workbench reads ({', '.join(sorted(panel))})"}
    altering = [a for a in on if set(a["consequence"].split("&")) & PROTEIN_ALTERING]
    if not altering:
        return {"row": n, "reason": f"{on[0]['gene']} {on[0]['consequence'] or 'no consequence'}"
                                    ": not protein-altering"}
    named = sorted((a for a in altering if short_change(a["hgvsp"])),
                   key=lambda a: not a["canonical"])
    if not named:
        return {"row": n, "reason": f"{altering[0]['gene']}: no protein change (HGVSp) in the "
                                    "annotation"}
    a, change = named[0], short_change(named[0]["hgvsp"])
    return {"row": n, "gene": a["gene"], "change": change, "variant": f"{a['gene']} {change}",
            "consequence": a["consequence"], "allele_fraction": vaf}


def _maf(lines: list[str], panel: set[str]) -> tuple[str | None, list[dict]]:
    body = [(n, ln) for n, ln in enumerate(lines, start=1) if ln.strip() and ln[0] != "#"]
    head = body[0][1].split("\t") if body else []
    hgvsp = "HGVSp_Short" if "HGVSp_Short" in head else "HGVSp"
    missing = [c for c in ("Hugo_Symbol", "Variant_Classification", hgvsp) if c not in head]
    if missing:
        raise IntakeError("Neither a VCF (its first line is ##fileformat=VCF) nor a MAF: missing "
                          f"column(s) {', '.join(missing)} (a tab-separated GDC or cBioPortal "
                          "MAF).")
    if len(body) - 1 > MAX_RECORDS:
        raise IntakeError(f"More than {MAX_RECORDS:,} variant records: filter the file to the "
                          "panel's genes first.")
    records = [(n, dict(zip(head, ln.split("\t"), strict=False))) for n, ln in body[1:]]
    samples = sorted({r.get("Tumor_Sample_Barcode", "") for _, r in records} - {""})
    _reject_msk(samples)
    if len(samples) > 1:
        raise IntakeError(f"The MAF holds {len(samples)} tumor samples ({', '.join(samples[:3])}"
                          f"{'…' if len(samples) > 3 else ''}): import one sample's calls at a "
                          "time.")
    out = []
    for n, r in records:
        cls, gene = r.get("Variant_Classification", ""), r.get("Hugo_Symbol", "")
        try:
            alt, depth = int(r["t_alt_count"]), int(r["t_depth"])
            vaf = f"allele fraction {alt / depth:.2f} ({alt} of {depth} reads)"
        except (KeyError, ValueError, ZeroDivisionError):
            vaf = NO_VAF_MAF
        # a MAF classifies the variant itself: map its protein-altering classes onto one
        # protein-altering consequence, so _pick applies the same panel and HGVSp checks
        row = _pick(n, [{"gene": gene, "hgvsp": r.get(hgvsp, ""), "canonical": True,
                         "consequence": "missense_variant" if cls in MAF_ALTERING else cls}],
                    panel, vaf)
        out.append(row | {"consequence": cls} if "variant" in row else row)
    return (samples[0] if samples else None), out


def sequencing_test(rows: list[dict], meta: dict, month: int, name: str, panel,
                    source: str) -> Test:
    """Accepted variants → one Sequencing test, read by the genomics workbench and the
    newly-sequenced-driver alert (``workspace.add_version``)."""
    found = [r["variant"] for r in rows]
    return Test("Sequencing", month, f"Tumor sequencing ({meta['format']}, imported)",
                ", ".join(found) or "no panel driver in the file", "mutations", IMPLEMENTED,
                {"variants": found, "panel": list(panel), "file": name,
                 "sample": meta["sample"] or "sample not named in the file",
                 "assay": f"imported {meta['format']} file", "source": source,
                 "allele_fractions": {r["variant"]: r["allele_fraction"] for r in rows}})


# --- an imaging report: the read its sentences state ------------------------------------------
PROGRESSION, RESPONSE, STABLE, NOT_STATED = "progression", "response", "stable", "not stated"
READS = [  # the first read stated in a kept clause wins, in this order (a new lesion outranks)
    (PROGRESSION, r"progressi(?:on|ve disease)|progressed|progressing"),
    (RESPONSE, r"(?:partial|complete) response|responding|decrease[ds]? in size|"
               r"interval decrease|smaller"),
    (STABLE, r"stable|unchanged|no (?:significant |interval )?change"),
]
# Distant metastatic sites only: breast, skin, chest wall and nodes are local or regional, and a
# report naming them new raises no "new metastatic site" alert
SITE_WORDS = {"bone": "Bone", "osseous": "Bone", "skeletal": "Bone", "bony": "Bone",
              "liver": "Liver", "hepatic": "Liver", "lung": "Lung", "pulmonary": "Lung",
              "brain": "Brain", "cerebral": "Brain", "intracranial": "Brain",
              "pleura": "Pleura", "pleural": "Pleura", "adrenal": "Adrenal",
              "peritoneum": "Peritoneum", "peritoneal": "Peritoneum"}
LESION = r"(?:lesions?|metasta(?:ses|sis|tic deposits?)|deposits?|nodules?|masses|mass|foci|focus)"
NEW_SITE = [  # "new 1.2 cm hepatic lesions"; "new lesions in the right lobe of the liver"
    re.compile(rf"\bnew\s+((?:[\w.-]+\s+){{1,4}}?){LESION}\b"),
    re.compile(rf"\bnew\s+{LESION}\s+(?:in|within|involving)\s+((?:(?!and\b|with\b)[\w-]+\s*)"
               r"{1,6})")]
NEGATION = re.compile(r"\b(?:no|not|without|negative for|free of|absence of|resolved|"
                      r"rule[ds]? out)\b")
NEGATED_AFTER = re.compile(r"\b(?:not (?:seen|identified|present|demonstrated|evident)|absent|"
                           r"ruled out|excluded)\b")
HEDGE = re.compile(r"\b(?:possible|possibly|probable|probably|may(?!\s*\d)|might|could|"
                   r"cannot be excluded|cannot exclude|suspicious|suspected|concerning for|"
                   r"equivocal|indeterminate|questionable|likely|suggest\w*|versus|vs)\b|\?")
CLAUSE = re.compile(r"(?<=[.!;])\s+|\n+|\bbut\b|\bhowever\b|\balthough\b|\bexcept\b")
IMAGING_RULE = ("muffle.imports.imaging_read: a clause states the read or names a new distant "
                "site; clauses with a negation before the words (no, not, without, negative "
                "for…) or after them (not seen, absent…) and hedged clauses (possible, "
                "suspicious, cannot be excluded…) are set aside")


def stated(clause: str, m: re.Match) -> str | None:
    """Why a match in a clause does not count (negated or hedged), or None when it is stated."""
    if NEGATION.search(clause[: m.start()]) or NEGATED_AFTER.search(clause[m.end():]):
        return "negated"
    return "hedged" if HEDGE.search(clause) else None


def imaging_read(text: str, site_words: dict[str, str] = SITE_WORDS) -> dict:
    """The read an imaging report's words state: {"read", "words", "new_sites", "set_aside"}.
    ``read`` is progression, response, stable or not stated (the first stated in that order:
    one clause stating progression makes the read progression); ``words`` the clause it rests
    on; ``new_sites`` the distant metastatic sites a clause names new ("new hepatic lesions",
    "new lesions in the liver"; ``site_words`` widens the list, as the radiology workbench's
    lesion table does); ``set_aside`` the negated and hedged clauses, with why. Only the
    report's own words, observed; nothing is inferred from them."""
    reads, sites, aside = {}, [], []
    for clause in (c.strip() for c in CLAUSE.split(text) if c and c.strip()):
        low = clause.lower()
        for read, pattern in READS:
            for m in re.finditer(pattern, low):
                why = stated(low, m)
                if why:
                    aside.append({"clause": clause, "why": f"{why}: {m.group()}"})
                else:
                    reads.setdefault(read, clause)
        for rx in NEW_SITE:
            for m in rx.finditer(low):
                named = [s for w, s in site_words.items() if re.search(rf"\b{w}\b", m.group(1))]
                why = stated(low, m)
                if named and why:
                    aside.append({"clause": clause, "why": f"{why}: {m.group().strip()}"})
                elif named:
                    sites += [s for s in named if s not in sites]
    read = next((r for r, _ in READS if r in reads), NOT_STATED)
    return {"read": read, "words": reads.get(read, ""), "new_sites": sites,
            "set_aside": list({a["clause"] + a["why"]: a for a in aside}.values())}


def imaging_test(title: str, text: str, month: int, doc_id: str, source: str) -> Test:
    """An imaging report as an Imaging test: the read ``imaging_read`` found is its result and
    carries the progression and new-site alerts (``workspace.add_version``); its record event
    feeds the radiology report page and the lab workbench's marker-imaging comparison; the text
    is a document of the file. Named "Imaging report" like the record's, which is where the
    radiology workbench's items open; ``title`` stays with the document."""
    r = imaging_read(text)
    result = ("no overall read stated" if r["read"] == NOT_STATED else f"read as {r['read']}") \
        + (f"; new {', '.join(s.lower() for s in r['new_sites'])} named" if r["new_sites"] else "")
    return Test("Imaging", month, "Imaging report", result, "imaging", IMPLEMENTED,
                {"scope": "imported report text, no images", "document": doc_id, "title": title,
                 "text": text, "source": source, **r,
                 "rule": IMAGING_RULE,
                 "event": {"month": month, "kind": "Imaging",
                           "text": f"Imaging (imported report): {result}",
                           "progression": r["read"] == PROGRESSION, "sites": r["new_sites"],
                           "imported": True}})
