"""Clinical documents workbench and test import: the extraction rules on sample sentences,
conflicts, search, the documents of a file, intake checks, and a new report version with its
alerts from an imported lab series."""

import io
import json
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from muffle import crosstest
from muffle.imports import (
    QUEUED,
    IntakeError,
    document_test,
    image_test,
    lab_tests,
    parse_labs,
    read_text,
)
from muffle.timeline import EVENTS
from muffle.workbench import documents as wb
from muffle.workspace import (
    add_version,
    case_file,
    finding_key,
    record_events,
    report_markdown,
    synthetic_file,
)

ROOT = Path(__file__).resolve().parents[1]


def values(text: str) -> dict:
    """field -> the values the rules find, in reading order."""
    out = {}
    for f in wb.extract(text, "d"):
        out.setdefault(f["field"], []).append(f["value"])
    return out


def synthetic():
    return synthetic_file(json.loads((ROOT / "app" / "timeline_synthetic.json")
                                     .read_text(encoding="utf-8")))


# ----------------------------------------------------------------------------- extraction

def test_synoptic_report_facts_with_their_characters():
    text = ("NOTTINGHAM GRADE: POORLY DIFFERENTIATED (G3). NOTTINGHAM SCORE: 9 (Tubules= 3, "
            "Nuclei= 3, Mitoses= 3 mitotic count. > 12 per 10 HPF). TUMOR SIZE (GREATEST "
            "DIMENSION) : 3.5 CM. VENOUS / LYMPHATIC INVASION: ABSENT. MARGINS : NEGATIVE. "
            "-DISTANCE OF TUMOR FROM NEAREST MARGIN IS 2.0 CM. LYMPH NODES POSITIVE: 0. LYMPH "
            "NODES EXAMINED: 10. PATHOLOGIC STAGE: pT2 NO MX. BREAST, LEFT, MASTECTOMY: "
            "INFILTRATING DUCTAL CARCINOMA.")
    v = values(text)
    assert v["grade"] == ["3"] and v["nottingham_score"] == ["9"]
    assert (v["tubules"], v["pleomorphism"], v["mitoses"]) == (["3"], ["3"], ["3"])
    assert v["size"] == ["3.5 cm"] and v["margins"] == ["negative"]
    assert v["margin_distance"] == ["2 cm"] and v["lvi"] == ["absent"]
    assert v["nodes_positive"] == ["0"] and v["nodes_examined"] == ["10"]
    assert v["pT"] == ["pT2"] and v["pN"] == ["pN0"]  # OCR's letter O read as zero
    assert v["laterality"] == ["left"] and v["specimen"] == ["mastectomy"]
    assert v["histologic_type"] == ["invasive ductal carcinoma"]
    for f in wb.extract(text):  # offsets point at the text, inside the quoted sentence
        assert f["status"] == "documented" and f["start"] < f["end"]
        s, e = f["sentence"]
        assert s <= f["start"] and f["end"] <= e and f["quote"] == text[s:e].strip()
    size = next(f for f in wb.extract(text) if f["field"] == "size")
    assert text[size["start"]:size["end"]].endswith("3.5 CM")


def test_receptors_their_numbers_and_what_is_not_a_result():
    v = values("ER: positive, 98%. PR: positive, 8%. Her-2neu: equivocal 2+ by IHC, not "
               "amplified by FISH (ratio: 1.14). Ki-67: 20% positive cells.")
    assert (v["er"], v["er_percent"], v["pr"], v["pr_percent"]) == (
        ["positive"], ["98%"], ["positive"], ["8%"])
    assert (v["her2"], v["her2_ihc"], v["her2_ish"], v["her2_ratio"]) == (
        ["equivocal"], ["2+"], ["not amplified"], ["1.14"])
    assert v["ki67"] == ["20%"]
    v = values("BOTH TUMORS ARE POSITIVE FOR ESTROGEN AND PROGESTERONE RECEPTORS, AND NEGATIVE "
               "FOR HER-2/NEU (BY FISH).")
    assert (v["er"], v["pr"], v["her2"]) == (["positive"], ["positive"], ["negative"])
    v = values("lobular carcinoma (ER+ PR+ Her2/neu-). ER-C. PR-C. HER2-C. NEG-HER2.")
    assert (v["er"], v["pr"], v["her2"]) == (["positive"], ["positive"], ["negative"])
    v = values("ESTROGEN RECEPTOR - POSITIVE, PROGESTERONE RECEPTOR - NEGATIVE. ER/PR "
               "IMMUNOSTAINS ARE STRONGLY POSITIVE.")
    assert v["er"] == ["positive"] and v["pr"] == ["negative", "positive"]
    v = values("ER: Positive. Allred Score: 8 = Proportion Score 5 + Intensity Score 3. "
               "PR: Negative. Allred Score: 0.")
    assert (v["er_allred"], v["pr_allred"], v["pr"]) == (["8"], ["0"], ["negative"])
    # definitions, reference ranges and form labels are not results
    v = values("Interpretation: ER. Negative < 6.5. Positive >= 6.5. ER/PR positive is defined as "
               "an Allred score of >2. Ki-67: LOW. Reference Range: Low <10%. Borderline 10-20%. "
               "Her-2/neu (0-3+,n/a) : 1. SURGICAL MARGINS INVOLVED BY INVASIVE COMPONENT: none.")
    assert "er" not in v and "pr" not in v and "her2_ihc" not in v and "margins" not in v
    assert v["ki67"] == ["low"]
    v = values("HER2 IHC score 0. Estrogen receptors found in over 75% of tumor cell nuclei.")
    assert v["her2_ihc"] == ["0"] and v["er_percent"] == ["75%"] and "er" not in v


def test_her2_legends_and_answers_that_slid_a_row_are_not_results():
    # case 545's form: PR's "positive" slid under HER2's label, whose own answer is "zero or 1+"
    v = values("TUMOR PREVIOUSLY REPORTED TO BE POSITIVE FOR ER AND PR, AND NEGATIVE FOR "
               "HER-2/NEU. ESTROGEN RECEPTORS: PROGESTERONE RECEPTORS: positive. HER2/NEU: "
               "positive. zero or 1+.")
    assert (v["pr"], v["her2"], v["her2_ihc"]) == (["positive"], ["negative"], ["0 or 1+"])
    assert values(wb.case_documents(545)[0]["text"])["her2"] == ["negative"]
    # scoring legends and reference ranges
    v = values("Scores of 0 or 1 are considered negative for over-expression of HER2/neu "
               "oncoprotein. Those with a staining intensity score of 2 are considered borderline. "
               "HER2/neu: 0,1=NEGATIVE FOR OVEREXPRESSION, 2=INDETERMINATE. HER-2/NEU "
               "IMMUNOHISTOCHEMISTRY [NEGATIVE:0,1+ EQUIVOCAL: 2+; POSITIVE: 3+]. Her2 Negative "
               "<10.7 Positive 11.5 Equivocal = 10.7 - 11.4.")
    assert "her2" not in v and "her2_ihc" not in v
    v = values("Her-2/neu: NEGATIVE. Score: 1+. Reference Range: Negative 0 - 1+. Equivocal 2+.")
    assert (v["her2"], v["her2_ihc"]) == (["negative"], ["1+"])  # the result before its legend
    v = values("HER-2/neu (c-erb B2). Negative (0). Negative (0 - 1+). p53. Negative.")
    assert v["her2"] == ["negative"]  # a table row (result, normal range) is not a legend
    # a status word its own IHC score argues against: "weakly positive (2+)", a comment that
    # runs on; a word the score agrees with, or 2+ with amplification, is still read
    v = values("HER2/NEU: WEAKLY POSITIVE BY IMMUNOHISTOCHEMISTRY (2+). NEGATIVE BY. FISH.")
    assert "her2" not in v and v["her2_ihc"] == ["2+"]
    assert "her2" not in values(wb.case_documents(58)[0]["text"])
    assert "her2" not in values("HER2/NEU: 1+. Comment: since the sentinel node is positive,")
    v = values("HER2: Positive (3+). HER-2/neu: positive (2+), amplified by FISH. ERBB2: "
               "negative (0 / 1+).")
    assert (v["her2"], v["her2_ihc"]) == (["positive", "negative"], ["3+", "2+", "0 or 1+"])


def test_stage_tnm_nodes_drugs_and_dates():
    v = values("pT1c(m)NOMX. Summary stage: 2B. T Stage: 2 N Stage: 1. Metastatic carcinoma in 2 "
               "of 14 lymph nodes. ONE LYMPH NODE, FREE OF CARCINOMA (0/1). Seen 3/10/2011. No "
               "lymphovascular space invasion is noted. ECOG 1; adds alpelisib to fulvestrant.")
    assert v["pT"] == ["pT1c"] and v["pN"] == ["pN0"] and v["stage"] == ["Stage IIB"]
    assert v["nodes_positive"] == ["2", "0"] and v["nodes_examined"] == ["14", "1"]
    assert v["date"] == ["3/10/2011"] and v["lvi"] == ["absent"] and v["ecog"] == ["1"]
    assert v["drug"] == ["alpelisib", "fulvestrant"]
    v = values("treatment decision for stage II, node-positive breast cancer patients")
    assert "stage" not in v  # an assay's boilerplate, not this patient's stage
    v = values("Invasive ductal carcinoma, stage II, hormone-receptor positive, HER2 negative")
    assert (v["stage"], v["hr"], v["her2"]) == (["Stage II"], ["positive"], ["negative"])


def test_conflicts_are_across_documents_and_kept_side_by_side():
    docs = [{"id": "a", "text": "ER: positive. HER2: negative. Specimen: lumpectomy."},
            {"id": "b", "text": "ER: negative. HER2: negative. Specimen: core biopsy."},
            {"id": "c", "text": "PR: positive. PR: negative."}]  # one document: two facts
    facts = [f for d in docs for f in wb.extract(d["text"], d["id"])]
    c = wb.conflicts(facts)
    assert [x["field"] for x in c] == ["er"]  # HER2 agrees; specimens may differ; c is one doc
    assert [(v["value"], v["docs"]) for v in c[0]["values"]] == [("positive", ["a"]),
                                                                   ("negative", ["b"])]
    assert "Ki-67 %" in wb.missing_fields(facts) and "ER status" not in wb.missing_fields(facts)


def test_search_in_plain_words_with_synonyms():
    docs = [{"id": "a", "title": "Report", "text": "ER: positive (95%). Margins: negative."},
            {"id": "b", "title": "Note", "text": "Started letrozole. Her2 negative."}]
    hits = wb.search(docs, "estrogen positive")
    assert [(h["doc"], h["quote"]) for h in hits] == [("a", "ER: positive (95%).")]
    assert [h["doc"] for h in wb.search(docs, "letrozole")] == ["b"]
    assert wb.search(docs, "her") == []  # a short word matches whole words only ("Her2" != her)
    assert wb.search(docs, "brain metastasis") == [] and wb.search(docs, "the") == []
    a, b = wb.search(docs, "margin")[0]["spans"][0]
    assert docs[0]["text"][a:b] == "Margin"


# ------------------------------------------------------------------------ documents of a file

def test_synthetic_documents_follow_the_report_version_and_clinic_notes_are_tests():
    pf = synthetic()
    notes = [t for t in pf.tests if t.kind == "Clinic note"]
    assert [(t.month, t.workbench, t.status) for t in notes] == [
        (1, "documents", "implemented"), (13, "documents", "implemented"),
        (24, "documents", "implemented")]
    docs = wb.file_documents(pf)
    assert len(docs) == len(EVENTS) and docs[0]["title"] == "Diagnosis, month -40"
    assert notes[0].details["document"] in {d["id"] for d in docs}
    month1 = next(k for k, v in enumerate(pf.versions) if v.month == 1)
    assert max(d["month"] for d in wb.file_documents(pf, month1)) == 1
    facts = wb.facts(docs)
    assert {("histologic_type", "invasive ductal carcinoma"), ("drug", "palbociclib"),
            ("ecog", "1")} <= {(f["field"], f["value"]) for f in facts}
    assert [r["when"] for r in wb.timeline(docs)][:2] == ["month -40", "month -39"]


def test_bundled_tcga_reports_load_by_case_index():
    files = sorted(p for p in (ROOT / "app" / "documents").glob("TCGA-*.json")
                   if not p.name.endswith(".ner.json"))
    assert 30 <= len(files) <= 40  # the bundled cases with a report, and only those
    data = json.loads(files[0].read_text())
    docs = wb.case_documents(data["case_index"])
    assert docs and docs[0]["id"].startswith(data["barcode"]) and "CC BY 4.0" in docs[0]["source"]
    case = SimpleNamespace(index=data["case_index"], site="site-1", percentile=50.0, group="mid",
                           age=60.0, stage="II", layers=["clinical"], missing=[], mutations=None)
    pf = case_file(case, 0.7, documents=docs)
    t = next(t for t in pf.tests if t.kind == "Document")
    assert (t.workbench, t.details["document"]) == ("documents", docs[0]["id"])
    assert wb.file_documents(pf)[0]["text"] == docs[0]["text"]
    assert wb.timeline(wb.file_documents(pf))[0]["when"] in ("undated", *[
        f["value"] for f in wb.extract(docs[0]["text"]) if f["field"] == "date"])
    assert wb.case_documents(-1) == []
    v = json.loads((ROOT / "app" / "documents" / "validation.json").read_text())
    assert {"dev", "test", "bundled"} == set(v["sets"])
    assert {r["field"] for r in v["sets"]["test"]["fields"]} >= {"er", "pr", "her2", "stage"}


# --------------------------------------------------------------------------------- intake

def test_lab_csv_is_checked_row_by_row():
    csv = (b"month,marker,value,unit,reference limit\n27,CA 15-3,45,U/mL,30\n27,CA 15-3,46,U/mL,"
           b"\n28,ALT,30,U/L,\n28,CEA,abc,ng/mL,\n28,CEA,3,mmol/L,\n20,CEA,3,ng/mL,\n29,cea,6.5,"
           b"ng/mL,5\n,,,,\n")
    ok, bad = parse_labs(csv, after=24, existing={("ca153", 24)})
    assert [(r["month"], r["key"], r["value"], r["limit"]) for r in ok] == [
        (27, "ca153", 45.0, 30.0), (28, "alt", 30.0, None), (29, "cea", 6.5, 5.0)]
    reasons = {r["row"]: r["reason"] for r in bad}
    assert "already has a value at month 27" in reasons[3] and "not a number" in reasons[5]
    assert "not one the reference table converts for CEA" in reasons[6]
    assert "before the latest report" in reasons[7]
    with pytest.raises(IntakeError, match="Missing column"):
        parse_labs(b"marker,value\nCEA,3\n")
    with pytest.raises(IntakeError, match="empty"):
        parse_labs(b"")
    with pytest.raises(IntakeError, match="limit is 5 MB"):
        parse_labs(b"x" * (5 * 2**20 + 1))
    with pytest.raises(IntakeError, match="date of month 0"):
        parse_labs(b"date,marker,value,unit\n2026-01-01,CEA,3,ng/mL\n")
    ok, _ = parse_labs(b"date,marker,value,unit\n2026-04-01,CEA,3,ng/mL\n", after=None,
                       anchor=date(2026, 1, 1))
    assert ok[0]["month"] == 3  # 90 days, in whole months


def test_documents_text_and_pdf_intake():
    assert read_text("r.txt", "  ER: positive.  ".encode()) == "ER: positive."
    with pytest.raises(IntakeError, match="empty"):
        read_text("r.txt", b"   ")
    with pytest.raises(IntakeError, match="not UTF-8"):
        read_text("r.txt", b"\xff\xfe\x00bad")
    pypdf = pytest.importorskip("pypdf")
    w, buf = pypdf.PdfWriter(), io.BytesIO()
    w.add_blank_page(200, 200)
    w.write(buf)
    with pytest.raises(IntakeError, match="no text layer"):
        read_text("scan.pdf", buf.getvalue())
    test, observed = document_test("Document", "Outside report", "ER: negative. pT2 N1a.", 26,
                                   "import-1", "imported by AB")
    assert (test.workbench, test.details["text"], test.month) == ("documents",
                                                                  "ER: negative. pT2 N1a.", 26)
    assert test.result == "pT pT2; pN pN1a; ER status negative"
    assert observed == [["Documented in Outside report (month 26)", test.result]]


def test_images_and_dicom_are_queued_not_analyzed():
    pil = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    pil.new("RGB", (640, 480), "white").save(buf, "PNG")
    t = image_test("region.png", buf.getvalue(), 25)
    assert (t.status, t.workbench, t.details["width"], t.details["pipeline"]) == (
        QUEUED, "intake", 640, "slides")
    with pytest.raises(IntakeError, match="PNG or JPEG"):
        image_test("x.png", b"not an image", 25)
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    from muffle.imports import dicom_test

    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT image storage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta, ds.SOPClassUID, ds.Modality, ds.Rows = meta, meta.MediaStorageSOPClassUID, "CT", 4
    ds.PatientName = "Doe^Jane"
    out = io.BytesIO()
    pydicom.dcmwrite(out, ds, enforce_file_format=True)
    t = dicom_test("scan.dcm", out.getvalue(), 25)
    assert t.details["header"]["Modality"] == "CT" and t.status == QUEUED
    assert t.details["identifiers_present"] == ["PatientName"]
    assert "Doe" not in json.dumps(t.details, default=str)  # identifiers are never read in
    with pytest.raises(IntakeError, match="not a DICOM"):
        dicom_test("x.dcm", b"plain text", 25)


# --------------------------------------------------------------------- a new report version

def test_an_imported_lab_series_adds_a_version_and_re_runs_the_rise_rule():
    pf = synthetic()
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,45,U/mL\n", after=pf.latest.month)
    tests, observed = lab_tests(ok)
    new = add_version(pf, tests, 27, "Imported lab results", "AB", "14:03", observed)
    assert len(new.versions) == len(pf.versions) + 1 and new.versions[:-1] == pf.versions
    v = new.latest
    assert v.label == "month 27 · imported by AB at 14:03" and "this browser session" in v.imported
    assert v.risk is None and "not run on imported results" in v.summary
    assert dict(v.observed)["Latest CA 15-3"] == "45 U/mL (month 27, imported)"
    assert [a.what for a in v.alerts] == [
        "CA 15-3 rose from 31 to 45 U/mL (+45%), above the reference limit of 30"]
    assert v.alerts[0].opens == ("Tests", "Lab", 27, "CA 15-3")
    assert record_events(new)[-1] == {"month": 27, "kind": "Lab", "ca153": 45.0,
                                      "text": "CA 15-3 45 U/mL (imported)"}
    i = len(new.versions) - 1
    assert crosstest.uncertainty_reducers(new, i)[0]["test"] == "Repeat CA 15-3 specimen within " \
                                                                 "a month"
    assert any(d["finding"] == "Lab: CA 15-3 (month 27)" for d in
               crosstest.diff_versions(new, i - 1, i))
    page = report_markdown(new, i)
    assert "## Imported in this session" in page and "Lab CA 15-3 (implemented)" in page
    # a value below the 25% rise raises nothing
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,35,U/mL\n", after=24)
    assert not add_version(pf, lab_tests(ok)[0], 27, "", "AB", "14:03").latest.alerts


def test_imports_on_a_tcga_file_keep_its_risk_and_use_an_imported_limit():
    case = SimpleNamespace(index=1, site="site-1", percentile=80.0, group="high", age=60.0,
                           stage="II", layers=["clinical"], missing=[], mutations=None)
    pf = case_file(case, 0.7)
    ok, _ = parse_labs(b"month,marker,value,unit,reference limit\n3,CEA,4,ng/mL,5\n")
    pf = add_version(pf, lab_tests(ok)[0], 3, "labs", "AB", "09:00", lab_tests(ok)[1])
    assert pf.latest.risk == pf.versions[0].risk and not pf.latest.alerts
    ok, _ = parse_labs(b"month,marker,value,unit,reference limit\n5,CEA,6,ng/mL,5\n", after=3,
                       existing={("cea", 3)})
    pf = add_version(pf, lab_tests(ok)[0], 5, "labs", "AB", "09:05")
    a = pf.latest.alerts[0]
    assert a.what.startswith("CEA rose from 4 to 6 ng/mL (+50%)")
    assert "the imported lab result" in a.threshold
    assert [e["month"] for e in record_events(pf)] == [3, 5]
    note, rows = document_test("Clinic note", "Clinician note (AB)", "Started letrozole.", 5,
                               "import-3", "imported by AB")
    pf = add_version(pf, [note], 5, "note", "AB", "09:10", rows)
    assert wb.file_documents(pf)[-1]["text"] == "Started letrozole." and rows == []
    assert finding_key(pf, "document", "import-3", "Drug named: letrozole") == \
        "Case 1|document|import-3|Drug named: letrozole"


def test_the_documents_page_renders_standalone():
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    at = AppTest.from_file(str(ROOT / "app" / "workbenches" / "documents.py"),
                           default_timeout=60).run()
    assert not at.exception
    text = " ".join(e.value for e in [*at.markdown, *at.subheader, *at.caption])
    assert "Clinical documents" in text and "documented facts" in text
    at.text_input(key="docs-q-SYNTHETIC-001").set_value("palbociclib").run()
    assert not at.exception
    at.text_input(key="docs-q-SYNTHETIC-001").set_value("brain metastasis").run()
    assert 'No document in this file mentions "brain metastasis"' in at.info[0].value
    dx = wb.extract(EVENTS[0]["text"], "m-40-diagnosis")[0]  # what a facts-table row click sets
    at.session_state["docs-jump-SYNTHETIC-001"] = ("m-40-diagnosis", tuple(dx["sentence"]))
    at.run()
    assert "Jumped to **Histologic type invasive ductal carcinoma**" in " ".join(
        e.value for e in at.markdown) and not at.exception


# ------------------------------------------------- round 2: the model's reading, scans, time

DOCS = ROOT / "app" / "documents"


def test_shipped_ner_payloads_are_derived_spans_over_their_reports():
    reports = {p.name[:-5]: json.loads(p.read_text()) for p in DOCS.glob("TCGA-*.json")
               if not p.name.endswith(".ner.json")}
    payloads = sorted(DOCS.glob("TCGA-*.ner.json"))
    assert len(payloads) == len(reports)  # one per bundled report file
    for p in payloads:
        d = json.loads(p.read_text())
        assert d["model"] == wb.NER_MODEL and d["license"] == "Apache-2.0"
        assert d["labels"] == wb.NER_LABELS and d["threshold"] == wb.NER_THRESHOLD
        texts = {x["id"]: x["text"] for x in reports[d["barcode"]]["documents"]}
        assert set(d["documents"]) == set(texts)
        for doc, spans in d["documents"].items():
            for s in spans:  # label, start, end, score: never the text or the model
                assert set(s) == {"label", "start", "end", "score"}
                assert s["label"] in wb.NER_LABELS
                assert 0 <= s["start"] < s["end"] <= len(texts[doc])
                assert wb.NER_THRESHOLD <= s["score"] <= 1
    first = json.loads(payloads[0].read_text())
    doc = next(iter(first["documents"]))
    assert wb.doc_spans(doc) == first["documents"][doc] and wb.doc_spans("import-1") is None


def test_two_highlight_layers_are_cut_where_either_starts_or_ends():
    runs = wb.layers("ER positive HER2 2+", [(0, 11, "rules"), (3, 19, "model 0.62"),
                                             (12, 16, "rules")])
    assert runs == [("ER ", ("rules",)), ("positive", ("rules", "model 0.62")),
                    (" ", ("model 0.62",)), ("HER2", ("model 0.62", "rules")),
                    (" 2+", ("model 0.62",))]
    assert wb.layers("abc", []) == [("abc", ())]
    assert "".join(p for p, _ in wb.layers("x" * 9, [(2, 5, "a"), (0, 30, "b")])) == "x" * 9


def test_the_model_s_value_is_only_what_its_span_says():
    assert wb.ner_values("er", "ESTROGEN") == []  # a mention, no result
    assert wb.ner_values("er", "ER: POSITIVE") == [("er", "positive")]
    assert wb.ner_values("er", "E-. cadherin") == []  # a sign only right after the name
    assert wb.ner_values("her2", "HER2 2+") == [("her2_ihc", "2+")]
    assert wb.ner_values("her2", "HER2 weakly positive (2+)") == [("her2_ihc", "2+")]
    assert wb.ner_values("pT", "pT2") == [("pT", "pT2")]
    assert wb.ner_values("pT", "pN2a") == []
    assert wb.ner_values("nodes", "2/14 lymph nodes") == [("nodes_positive", "2"),
                                                          ("nodes_examined", "14")]
    text = "HER2 status: negative. Legend: Negative 0-1+, Equivocal 2+, Positive 3+. pT2."
    spans = [{"label": "HER2 status", "start": 0, "end": 4, "score": 0.7},
             {"label": "pathologic T stage", "start": text.index("pT2"),
              "end": text.index("pT2") + 3, "score": 0.6},
             {"label": "not a label", "start": 0, "end": 3, "score": 0.9}]
    got = wb.ner_facts(text, spans, "d")
    assert [(f["field"], f["value"], f["status"]) for f in got] == [
        ("her2", None, "model inference"), ("pT", "pT2", "model inference")]


def test_agreement_between_the_rules_and_the_model_on_hand_made_spans():
    text = ("ER: positive. PR: negative. HER2: negative. Legend: Negative 0-1+, Equivocal 2+, "
            "Positive 3+. MARGINS: NEGATIVE. pT2 pN1a.")

    def span(label, words):
        a = text.index(words)
        return {"label": label, "start": a, "end": a + len(words), "score": 0.66}

    model = wb.ner_facts(text, [span("estrogen receptor status", "ER: positive"),
                                span("progesterone receptor status", "PR: negative"),
                                span("HER2 status", "Equivocal 2+"),
                                span("pathologic T stage", "pT2")], "d")
    rows = {r["field"]: r for r in wb.agreement(text, wb.extract(text, "d"), model)}
    assert rows["er"]["kind"] == "agree" and rows["pr"]["kind"] == "agree"
    assert rows["margins"]["kind"] == "rules only" and rows["pT"]["kind"] == "agree"
    her2 = rows["her2"]  # the rules read negative; the model's span sits inside the legend
    assert (her2["kind"], her2["rules"], her2["model"]) == ("disagree", "negative", "equivocal")
    assert "the rules read HER2 status negative at sentence 3" in her2["line"]
    assert "the model marked 'Equivocal 2+' as HER2 status (0.66) at sentence 4" in her2["line"]
    alone = wb.agreement("See legend: Equivocal 2+.", [], wb.ner_facts(
        "See legend: Equivocal 2+.", [{"label": "HER2 status", "start": 12, "end": 24,
                                       "score": 0.5}]))
    assert alone[0]["kind"] == "model only" and "where the rules read no result" in alone[0]["line"]
    legend = "Negative 0-1+, Equivocal 2+, Positive 3+."
    inside = wb.agreement(legend, [], wb.ner_facts(legend, [
        {"label": "HER2 status", "start": 15, "end": 27, "score": 0.5}]))
    assert "which the rules took for a legend" in inside[0]["line"]


def _with_import(pf, text, month, doc="import-1"):
    test, rows = document_test("Document", "Outside report", text, month, doc, "imported by AB")
    return add_version(pf, [test], month, "report", "AB", "10:00", rows)


def test_models_disagree_in_the_queue_and_the_summary(monkeypatch):
    text = "HER2/neu: negative. Legend: Negative 0-1+, Equivocal 2+, Positive 3+."
    pf = _with_import(synthetic(), text, 25)
    a = text.index("Equivocal 2+")
    monkeypatch.setattr(wb, "doc_spans", lambda doc, folder=None: [
        {"label": "HER2 status", "start": a, "end": a + 12, "score": 0.71}]
        if doc == "import-1" else None)
    items = [x for x in wb.queue(pf) if x["pointer"].startswith("M")]
    assert len(items) == 1 and items[0]["what"] == "HER2 status: the rules and the model disagree"
    assert items[0]["trust"] == "weak" and items[0]["consequence"] == 2
    assert "which the rules took for a legend" in items[0]["why"]
    assert items[0]["key"] == finding_key(pf, "document", "models disagree", "import-1",
                                          "HER2 status")
    card = next(c for c in wb.summary(pf)["cards"] if c["what"].startswith("The model's"))
    assert card["evidence"] == "model inference" and "1 disagree (HER2 status)" in card["text"]


def test_documents_over_time_changes_and_the_record_says_otherwise():
    pf = _with_import(synthetic(), "Liver biopsy. HER2: positive (3+). Stage IV.", 25)
    docs = wb.file_documents(pf)
    facts = wb.facts(docs)
    ch = {c["field"]: c for c in wb.changes(docs, facts)}
    assert (ch["her2"]["from"], ch["her2"]["to"], ch["her2"]["to_month"]) == ("negative",
                                                                              "positive", 25)
    assert ch["stage"]["kind"] == "stage" and ch["her2"]["kind"] == "receptor"
    hist = wb.history(docs, facts)
    assert hist[0]["month"] == -40 and hist[-1]["facts"]["her2"]["value"] == "positive"
    d = next(x for x in wb.queue(pf) if x["what"] == "HER2 status: documents disagree")
    assert "over time: negative at month -40, positive at month 25" in d["why"]
    i = len(pf.versions) - 1
    found = {x["rule"]: x for x in crosstest.discrepancies(pf, i)
             if x["rule"].startswith("documented vs recorded")}
    assert "HER2: documented positive in Outside report" in found[
        "documented vs recorded receptor"]["what"]
    assert found["documented vs recorded"]["what"] == ("Stage: restaged Stage IV at month 25, "
                                                       "recorded II")
    assert wb.resolution(None).startswith("open")
    assert wb.resolution({"mark": "reviewed", "by": "AB", "stands": "positive"}) == \
        "marked reviewed by AB, positive stands"


def test_search_across_facts_and_model_spans():
    text = "HER2: negative. Margins: negative. Lymph nodes positive: 2. ESTROGEN receptor."
    facts = wb.extract(text, "d")
    a = text.index("ESTROGEN")
    model = wb.ner_facts(text, [{"label": "estrogen receptor status", "start": a, "end": a + 8,
                                 "score": 0.55}], "d")
    assert {f["field"] for f in wb.search_findings(facts + model, "HER2")} == {"her2"}
    assert [f["field"] for f in wb.search_findings(facts + model, "margin")] == ["margins"]
    assert [f["field"] for f in wb.search_findings(facts, "node positive")] == ["nodes_positive"]
    assert wb.search_findings(model, "estrogen")[0]["rule"] == "model"
    assert wb.search_findings(facts, "the") == []
    m = wb.measured_against("her2_ihc")
    assert m["field"] == "her2" and "her2_neu" in m["tcga_field"]
    assert m["rules"]["precision"] > 0.5 and m["model"] is not None
    assert wb.measured_against("drug") is None


def test_validation_holds_both_readers_and_the_scan_accuracy():
    v = json.loads((DOCS / "validation.json").read_text())
    rules = [r["field"] for r in v["sets"]["test"]["fields"]]
    for name in ("test", "bundled"):
        model = v["model"]["sets"][name]
        assert [r["field"] for r in model["fields"]] == rules
        assert model["patients"] == v["sets"][name]["patients"]  # the same reports
    assert v["model"]["run"]["seconds_per_1000_characters"] > 0
    assert v["scan"]["rows"] and all(0 <= r["char_accuracy"] <= 1 for r in v["scan"]["rows"])


def test_a_scanned_pdf_is_queued_and_the_local_pipeline_reads_it(monkeypatch, tmp_path):
    import importlib.util

    from muffle.imports import ScannedPDF, scanned_test

    pil = pytest.importorskip("PIL.Image")
    pytest.importorskip("pypdf")
    buf = io.BytesIO()
    pages = [pil.new("RGB", (300, 400), "white") for _ in range(2)]
    pages[0].save(buf, "PDF", save_all=True, append_images=pages[1:])
    with pytest.raises(ScannedPDF, match=r"Scanned PDF \(2 pages, no text layer\): queued") as e:
        read_text("scan.pdf", buf.getvalue())
    t = scanned_test("scan.pdf", buf.getvalue(), 26, e.value.pages)
    assert (t.status, t.workbench, t.details["pages"], t.details["file"]) == (
        QUEUED, "intake", 2, "scan.pdf")
    spec = importlib.util.spec_from_file_location("documents_pipeline",
                                                  ROOT / "scripts" / "documents_pipeline.py")
    pipe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pipe)
    page_text = "INVASIVE DUCTAL CARCINOMA. ER: positive. HER2: negative (1+)."
    monkeypatch.setattr(pipe, "pdf_pages", lambda data, scale: ["page 1", "page 2"])
    monkeypatch.setattr(pipe, "read_page", lambda proc, model, image: page_text)

    class Ner:  # GLiNER's interface: spans in the text it is given
        def predict_entities(self, text, labels, threshold, flat_ner):
            return [{"label": "estrogen receptor status", "start": m.start(), "end": m.end(),
                     "score": 0.8} for m in re.finditer("ER: positive", text)]

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(buf.getvalue())
    got = pipe.read_scanned(pdf, 2.0, tmp_path / "out", ocr=(None, None), ner=Ner())
    assert got["pages"] == 2 and got["text"] == f"{page_text}\n\n{page_text}"
    assert "granite-docling-258M" in got["method"]
    assert {("er", "positive"), ("her2", "negative")} <= {(f["field"], f["value"])
                                                          for f in got["facts"]}
    assert len(got["ner"]) == 2 and got["ner"][1]["start"] > len(page_text)
    assert (tmp_path / "out" / "scan.txt").read_text().startswith("INVASIVE")
    assert got["looped"] is False
    assert pipe.looped("\n".join(["1", "2", "3"] + ["110"] * 12))  # the reader repeating itself
    page = pil.new("L", (100, 200), 0)  # black, with one white row near the middle
    page.paste(255, (0, 104, 100, 105))
    halves = pipe.bands_of(page, 2)
    assert [h.size for h in halves] == [(100, 104), (100, 96)] and pipe.bands_of(page, 1) == [page]


def test_a_tcga_file_shows_the_model_layer():
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

    def page():
        import json as j
        import sys as s
        from pathlib import Path as P
        from types import SimpleNamespace as N

        s.path.insert(0, str(P.cwd() / "app"))
        from workbenches import documents as page_wb

        from muffle.workbench import documents as w
        from muffle.workspace import case_file as cf

        d = j.loads((P(page_wb.APP) / "documents" / "TCGA-AO-A03R.json").read_text())
        case = N(index=d["case_index"], site="site-1", percentile=50.0, group="mid", age=60.0,
                 stage="II", layers=["clinical"], missing=[], mutations=None)
        page_wb.render(cf(case, 0.7, documents=w.case_documents(d["case_index"])))

    at = AppTest.from_function(page, default_timeout=90).run()
    assert not at.exception, at.exception
    text = " ".join(e.value for e in [*at.markdown, *at.caption])
    assert "The named-entity model read 1 of 1 documents" in text
    assert "underlined in violet" in text and "Spot panel" in text
    index = json.loads((DOCS / "TCGA-AO-A03R.json").read_text())["case_index"]
    at.text_input(key=f"docs-q-Case {index}").set_value("HER2").run()
    assert not at.exception and "**Findings**" in " ".join(e.value for e in at.markdown)
