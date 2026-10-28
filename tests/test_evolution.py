"""Tumor evolution and treatment evidence: the cited table, the per-patient hypothesis set, the
record's events, clonal order from allele fractions, CIViC matching, trials with their offline
snapshot, and the export."""

import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from muffle import evolution as ev
from muffle.imports import document_test
from muffle.report import trials
from muffle.report.case_tools import HYPOTHESIS, INFERENCE
from muffle.workbench.documents import case_documents
from muffle.workspace import add_version, case_file, finding_key, synthetic_file

ROOT = Path(__file__).resolve().parents[1]
CASE = dict(index=43, site="site-2", stage="II", age=67.0, percentile=73.4, group="high",
            layers=["genomic", "rna", "protein", "clinical"], missing=["methylation"],
            mutations=["PIK3CA p.G1049R", "RUNX1 p.D96Gfs*15", "TP53 p.R196*"])


def synthetic():
    tl = json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
    return synthetic_file(tl)


def test_every_row_has_a_verified_identifier_and_a_source():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", ev.VERIFIED)
    for row in ev.TABLE:
        assert row["support"], row["id"]
        assert row["detect"] and row["matters"] and row["event"], row["id"]
        for e in row["support"] + row["against"]:
            s = ev.source(e["source"])
            assert re.fullmatch(r"\d{7,8}", s["pmid"]), s
            assert s["doi"].startswith("10.") and s["title"] and s["cite"], s
            assert e["says"].strip(), row["id"]
    used = {e["source"] for r in ev.TABLE for e in r["support"] + r["against"]}
    used |= {s for c in ev.CONSTRAINTS for s in c["sources"]}
    assert used == set(ev.SOURCES)  # no source cited without a row, none listed unused
    assert len({r["id"] for r in ev.TABLE}) == len(ev.TABLE)


def test_docs_list_every_row_and_source():
    doc = (ROOT / "docs" / "evolution.md").read_text(encoding="utf-8")
    for row in ev.TABLE:
        assert row["event"] in doc, row["id"]
    for key, (_, _, pmid, doi, _) in ev.SOURCES.items():
        assert pmid in doc and doi in doc, key


def test_sources_match_pubmed():
    """Every PMID's DOI as PubMed lists it (NCBI E-utilities); skipped offline."""
    ids = ",".join(ev.SOURCES[k][2] for k in ev.SOURCES)
    try:
        with urllib.request.urlopen("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                                    f"?db=pubmed&retmode=json&id={ids}", timeout=20) as r:
            result = json.load(r)["result"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
        pytest.skip(f"PubMed not reachable: {e}")
    for key, (_, _, pmid, doi, _) in ev.SOURCES.items():
        dois = {a["value"].lower() for a in result[pmid]["articleids"] if a["idtype"] == "doi"}
        assert doi.lower() in dois, key


def test_nothing_in_the_table_is_worded_as_advice():
    text = json.dumps(ev.TABLE) + json.dumps(ev.CONSTRAINTS)
    for word in (r"\bshould\b", r"\brecommend", r"\bconsider\b", r"\bwe advise\b"):
        assert not re.search(word, text, re.I), word


def test_synthetic_file_names_esr1_under_aromatase_inhibitors():
    hs = ev.hypothesis_set(synthetic())
    by = {it["id"]: it for it in hs["items"]}
    esr1 = by["esr1-ai"]
    assert esr1["evidence"] == HYPOTHESIS and "ESR1" in esr1["event"]
    assert any("letrozole (aromatase inhibitor)" in w for w in esr1["why"])
    assert any(a["applies_here"] for a in esr1["against"])  # the letrozole was adjuvant only
    assert {e["source"]["pmid"] for e in esr1["support"]} >= {"26560360", "36183733"}
    assert hs["items"][0]["id"] == "pten-loss"  # alpelisib (month 13): the latest matching drug
    assert {"rb1-cdk46", "esr1-serd", "erbb2-endocrine", "er-loss"} <= set(by)
    skipped = {s["id"]: s["reason"] for s in hs["not_raised"]}
    assert "HER2-positive" in skipped["pik3ca-her2"]  # the record says HER2 negative
    assert "ESR1" in skipped["esr1-f404"] and "BRCA" in skipped["brca-reversion"]
    assert all(it["civic"] is None for it in hs["items"])  # no lookup given
    assert by["esr1-ai"]["key"] == finding_key(synthetic(), "evolution", esr1["event"],
                                               "26560360")


def test_hypotheses_follow_the_report_version():
    pf = synthetic()
    at_dx = ev.hypothesis_set(pf, 0)  # month -40: diagnosis only, nothing treated yet
    assert {it["id"] for it in at_dx["items"]} == {"er-loss", "her2-change", "metastatic-drivers"}
    assert at_dx["notes"] == ["No treatment recorded as of this version."]
    month1 = next(k for k, v in enumerate(pf.versions) if v.month == 1)
    ids = [it["id"] for it in ev.hypothesis_set(pf, month1)["items"]]
    assert "rb1-cdk46" in ids and "pten-loss" in ids and ids.index("esr1-ai") > ids.index(
        "rb1-cdk46")


def test_tcga_file_uses_drivers_only_and_assumes_no_treatment():
    hs = ev.hypothesis_set(case_file(SimpleNamespace(**CASE)))
    assert "No treatment recorded; these hypotheses assume none." in hs["notes"]
    assert any("not recorded" in n for n in hs["notes"])  # receptor status unknown
    by = {it["id"]: it for it in hs["items"]}
    assert by["tp53-subtype"]["status"].startswith("already observed: TP53 R196*")
    assert any("applies if HER2-positive" in w for w in by["pik3ca-her2"]["why"])
    skipped = {s["id"]: s["reason"] for s in hs["not_raised"]}
    assert "none is assumed" in skipped["rb1-cdk46"]


def reported(*texts):
    """The hypothesis set of CASE with made-up pathology report texts (not a patient's)."""
    docs = [{"id": f"rep-{n}", "title": "Pathology report", "kind": "Document", "month": None,
             "text": t, "source": "written for this test"} for n, t in enumerate(texts, 1)]
    return ev.hypothesis_set(case_file(SimpleNamespace(**CASE), documents=docs))


def test_a_reports_receptor_status_makes_rows_definite_and_is_named():
    hs = reported("ER: positive (95%). PR: positive. HER2: negative (1+).")
    by = {it["id"]: it for it in hs["items"]}
    assert "hormone-receptor-positive observed in document rep-1" in by["er-loss"]["why"]
    assert "HER2-negative observed in document rep-1" in by["metastatic-drivers"]["why"]
    skipped = {s["id"]: s["reason"] for s in hs["not_raised"]}
    assert "HER2 negative observed in document rep-1" in skipped["pik3ca-her2"]  # HER2+ only
    notes = " ".join(hs["notes"])
    assert "rep-1 states ER status positive, PR status positive" in notes
    assert "conditional" not in notes and "Document statuses are read by the documents" in notes
    doc = case_documents(43)[0]["id"]  # case 43's own report states ER and PR, not HER2
    real = ev.hypothesis_set(case_file(SimpleNamespace(**CASE), documents=case_documents(43)))
    by = {it["id"]: it for it in real["items"]}
    assert f"hormone-receptor-positive observed in document {doc}" in by["er-loss"]["why"]
    assert "applies if HER2-positive: not recorded in this file" in by["pik3ca-her2"]["why"]


def test_a_reports_receptor_status_can_rule_rows_out():
    hs = reported("ER: negative. PR: negative. HER2: negative.")
    assert {it["id"] for it in hs["items"]} == {"her2-change", "tp53-subtype"}
    skipped = {s["id"]: s["reason"] for s in hs["not_raised"]}
    assert "hormone receptor negative observed in document rep-1" in skipped["er-loss"]
    assert {"metastatic-drivers", "pik3ca-her2"} <= set(skipped)
    by = {it["id"]: it for it in reported("ER: negative. HER2: negative.")["items"]}
    assert ("applies if hormone-receptor-positive: not settled by document rep-1"  # PR unknown
            in by["er-loss"]["why"])


def test_disagreeing_receptor_statuses_are_shown_not_picked():
    hs = reported("ER: positive. PR: positive.", "ER: negative. PR: negative.")
    by = {it["id"]: it for it in hs["items"]}
    assert ("applies if hormone-receptor-positive: conflicting statuses in documents rep-1, "
            "rep-2") in by["er-loss"]["why"]
    assert any("conflicting statuses, rep-1 states ER status positive, PR status positive; "
               "rep-2 states ER status negative, PR status negative" in n for n in hs["notes"])
    pf = synthetic()  # the record says HR+: its own status is used, the document is named
    test, rows = document_test("Document", "Outside report", "ER: negative. PR: negative.", 26,
                               "import-1", "imported by AB")
    hs = ev.hypothesis_set(add_version(pf, [test], 26, "Imported document", "AB", "14:03", rows))
    by = {it["id"]: it for it in hs["items"]}
    assert ("hormone-receptor-positive in the record (document import-1 states otherwise)"
            in by["er-loss"]["why"])
    assert any(n.startswith("Hormone receptor status: the record says positive; import-1 states "
                            "ER status negative, PR status negative") for n in hs["notes"])


def test_only_the_cited_esr1_hotspots_count_as_the_lbd_event():
    def hs(mutation):
        return ev.hypothesis_set(case_file(SimpleNamespace(**{**CASE, "mutations": [mutation]})))

    ids = {it["id"] for it in hs("ESR1 p.P222S")["items"]}  # outside L536-D538
    assert "esr1-ai" not in ids and "esr1-fusion" not in ids and "metastatic-drivers" in ids
    by = {it["id"]: it for it in hs("ESR1 p.Y537S")["items"]}
    assert by["esr1-ai"]["status"].startswith("already observed: ESR1 Y537S")
    assert "esr1-fusion" not in by and "esr1-f404" not in by  # no SERD recorded


def test_events_are_the_record_over_time():
    pf = synthetic()
    month12 = next(k for k, v in enumerate(pf.versions) if v.month == 12)
    rows = ev.events(pf, month12)
    assert all(r["evidence"] == "observed" for r in rows)
    liver = [r for r in rows if r["month"] == 12]
    assert liver[0]["kind"] == "alert" and "liver" in liver[0]["label"]
    assert {r["label"] for r in rows if r["lane"] == "Treatment"} >= {
        "letrozole", "palbociclib + fulvestrant"}  # drugs started together stay one event
    assert not any(r["month"] > 12 for r in rows)
    assert ev.events(case_file(SimpleNamespace(**CASE))) == []


def test_vaf_ordering_on_synthetic_calls():
    lo, hi = ev.wilson(50, 100)
    assert lo == pytest.approx(0.404, abs=0.002) and hi == pytest.approx(0.596, abs=0.002)
    assert ev.wilson(0, 0) == (0.0, 1.0)
    calls = [  # made-up calls, not a patient
        {"variant": "GENE1 A1B", "alt": 400, "depth": 1000, "copies": 2.0},  # 0.40
        {"variant": "GENE2 C2D", "alt": 200, "depth": 1000, "copies": 2.0},  # 0.20
        {"variant": "GENE3 E3F", "alt": 190, "depth": 1000, "copies": 2.0},  # 0.19
        {"variant": "GENE4 G4H", "alt": 60, "depth": 1000, "copies": 2.0},   # 0.06
        {"variant": "GENE5 I5J", "alt": 100, "depth": 1000, "copies": 4.0},  # 0.10, 4 copies
    ]
    out = ev.clonal(calls)
    assert out["evidence"] == INFERENCE
    assert [v["variant"] for v in out["variants"]][:2] == ["GENE1 A1B", "GENE2 C2D"]
    rel = {(p["a"], p["b"]): p for p in out["pairs"]}
    assert rel[("GENE1 A1B", "GENE2 C2D")]["relation"] == "nested"  # 2 x (0.37 + 0.18) > 1
    assert rel[("GENE2 C2D", "GENE3 E3F")]["relation"] == "indistinguishable"
    assert rel[("GENE2 C2D", "GENE4 G4H")]["relation"] == "ordered, nesting open"
    assert "separate subclones" in rel[("GENE2 C2D", "GENE4 G4H")]["alternatives"]
    assert rel[("GENE1 A1B", "GENE5 I5J")]["relation"] == "copy number differs"
    linear = out["orderings"][0]
    assert linear.index("GENE1 A1B") < linear.index("GENE2 C2D = GENE3 E3F")
    assert any(o.startswith("Branching: GENE2 C2D and GENE4 G4H") for o in out["orderings"])
    assert any(o.startswith("Either order: GENE1 A1B and GENE5 I5J") for o in out["orderings"])


def test_clonal_panel_says_what_is_missing():
    assert "not available" in ev.clonal_panel(synthetic())["status"]
    tcga = case_file(SimpleNamespace(**CASE))
    panel = ev.clonal_panel(tcga)  # the shipped app/evolution_vaf.json
    assert panel["status"] == "allele fraction only, purity unknown"
    assert {v["variant"] for v in panel["variants"]} == {"PIK3CA G1049R", "RUNX1 D96Gfs*15",
                                                         "TP53 R196*"}
    assert all(v["depth"] > 0 for v in panel["variants"])
    other = case_file(SimpleNamespace(**{**CASE, "index": 99999}))
    assert ev.clonal_panel(other)["status"] == "allele fraction not available in these calls"
    unsequenced = case_file(SimpleNamespace(**{**CASE, "mutations": None}))
    assert ev.clonal_panel(unsequenced)["status"].startswith("not sequenced")


def test_civic_items_match_the_event_profile():
    cols = ["molecular_profile", "disease", "therapies", "evidence_direction", "evidence_level",
            "significance", "citation", "evidence_civic_url"]
    table = pd.DataFrame([
        ["RB1 Loss-of-function", "Breast Cancer", "Palbociclib", "Supports", "D", "Resistance",
         "Condorelli, 2018", "https://civicdb.org/e/1"],
        ["RB1 PHOSPHORYLATION", "Breast Cancer", "Palbociclib", "Supports", "D",
         "Sensitivity/Response", "X, 2020", "https://civicdb.org/e/2"],
        ["PIK3CA H1047R", "Breast Cancer", "Trastuzumab", "Supports", "B", "Resistance",
         "Kim, 2016", "https://civicdb.org/e/3"],
        ["PIK3CA H1047R", "Breast Cancer", "Alpelisib", "Supports", "A", "Sensitivity/Response",
         "Andre, 2019", "https://civicdb.org/e/4"],
        ["RB1 Loss-of-function", "Lung Cancer", "Palbociclib", "Supports", "C", "Resistance",
         "Y, 2019", "https://civicdb.org/e/5"],
    ], columns=cols)
    row = {r["id"]: r for r in ev.TABLE}
    rb1 = ev.civic_items(row["rb1-cdk46"], table)
    assert rb1["total"] == 1 and rb1["items"][0]["url"] == "https://civicdb.org/e/1"
    her2 = ev.civic_items(row["pik3ca-her2"], table)
    assert [i["therapies"] for i in her2["items"]] == ["Trastuzumab"]
    assert ev.civic_items(row["er-loss"], table) == {"items": [], "total": 0}
    assert ev.civic_items(row["rb1-cdk46"], None) == {"items": [], "total": 0}
    hs = ev.hypothesis_set(synthetic(), lookup=lambda r: ev.civic_items(r, table))
    assert next(it for it in hs["items"] if it["id"] == "rb1-cdk46")["civic"]["total"] == 1


def test_trials_fall_back_to_the_snapshot_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(trials, "CACHE", tmp_path)

    def offline(*a, **k):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(trials, "_get", offline)
    snap = trials.load_snapshot()
    assert snap["snapshot"] and set(snap["genes"]) >= {"PIK3CA", "ESR1", "TP53"}
    r = trials.studies("PIK3CA")
    assert r["source"] == "snapshot" and snap["snapshot"] in r["note"]
    assert r["studies"] and all(s["nct"].startswith("NCT") for s in r["studies"])
    assert r["term"] == "PIK3CA mutation"  # only the gene name goes to the registry
    assert trials.studies("NOTAGENE")["source"] == "none"
    (tmp_path / "TP53.json").write_text(json.dumps({**snap["genes"]["TP53"],
                                                    "fetched": "2026-10-20 10:00 UTC"}))
    assert trials.studies("TP53")["source"] == "cache"  # written today: still fresh


def test_trials_live_query_is_parsed(tmp_path, monkeypatch):
    monkeypatch.setattr(trials, "CACHE", tmp_path)
    monkeypatch.setattr(trials, "data_timestamp", lambda: "2026-10-20T09:00:04")
    sent = []

    def fake(url, timeout=8):
        sent.append(url)
        return {"totalCount": 1, "studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT00000001", "briefTitle": "A trial"},
            "statusModule": {"overallStatus": "NOT_YET_RECRUITING",
                             "lastUpdatePostDateStruct": {"date": "2026-10-01"}},
            "designModule": {"phases": ["PHASE1", "PHASE2"]},
            "armsInterventionsModule": {"interventions": [{"name": "Drug A"}]},
            "contactsLocationsModule": {"locations": [{"country": "France"},
                                                      {"country": "France"}]}}}]}

    monkeypatch.setattr(trials, "_get", fake)
    r = trials.studies("ESR1")
    assert r["source"] == "live" and (tmp_path / "ESR1.json").exists()
    s = r["studies"][0]
    assert (s["phase"], s["status"], s["countries"]) == ("phase 1, phase 2", "not yet recruiting",
                                                         ["France"])
    assert "query.term=ESR1+mutation" in sent[0] and "breast+cancer" in sent[0]


def test_report_markdown_carries_sources_and_marks():
    pf = synthetic()
    hs = ev.hypothesis_set(pf)
    key = hs["items"][0]["key"]
    page = ev.report_markdown(pf, None, hs, ev.clonal_panel(pf), [], "offline",
                              {key: {"what": "Evolution: PTEN loss", "mark": "agree", "by": "AB",
                                     "at": "2026-10-20 10:00"}})
    assert "## What to watch next" in page and "PMID 26560360" in page
    assert "## Rows not raised for this file" in page and "HER2-positive" in page
    assert "Evolution: PTEN loss: agree (AB" in page and "allele fraction not available" in page
    assert "Synthetic patient" in page


def test_the_page_watches_a_hypothesis_with_its_source_and_opens_a_trial():
    from streamlit.testing.v1 import AppTest

    def page():
        import json as j
        import sys as s
        from pathlib import Path as P

        s.path.insert(0, str(P.cwd() / "app"))
        from workbenches import evolution as page_ev

        from muffle.report import trials as tr
        from muffle.workspace import synthetic_file as sf

        def offline(*a, **k):
            raise OSError("no registry calls in tests")

        tr._get = offline  # the trials come from the snapshot
        tl = j.loads((P.cwd() / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
        page_ev.render(sf(tl), 11)

    at = AppTest.from_function(page, default_timeout=90).run()
    assert not at.exception, at.exception
    assert any(m.value.startswith(":material/lightbulb: **How to use this page:**")
               for m in at.markdown)
    assert any(m.value.startswith("##### ") for m in at.markdown)  # the Spot panel's hypothesis
    watch = next(b for b in at.button if b.label == "Watch this")
    key = watch.key.removeprefix("watch-")
    watch.click().run()
    pinned = at.session_state["pins"][key]
    assert pinned.startswith("Watch for ") and "PMID" in pinned and "detect with" in pinned
    assert any(b.label == "Watching: stop" for b in at.button)
    trial = at.selectbox(key="evolution-SYNTHETIC-001-11-trial")
    if trial.options:  # the snapshot's trials for the observed drivers
        trial.select(trial.options[0]).run()
        assert any(b.proto.label == "Open the trial on ClinicalTrials.gov"
                   for b in at.get("link_button"))


def test_a_tcga_files_recorded_receptors_are_the_records_status(monkeypatch):
    """QA R3-15: the report shows a TCGA file's recorded ER, PR and HER2 (TCGA clinical data,
    IHC and ISH); the Evolution view said "not recorded in this file" beside it."""
    from muffle.workbench import omics

    rec = {"ER": {"status": "Positive"}, "PR": {"status": "Negative"},
           "HER2": {"status": "Negative"}}
    monkeypatch.setattr(omics, "case_scores", lambda pf: {"receptors": rec})
    hs = ev.hypothesis_set(case_file(SimpleNamespace(**CASE)))
    by = {it["id"]: it for it in hs["items"]}
    assert any("hormone-receptor-positive in the record" in w for w in by["er-loss"]["why"])
    assert any("HER2-negative in the record" in w for w in by["metastatic-drivers"]["why"])
    assert not any("not recorded" in w for it in hs["items"] for w in it["why"])
    skipped = {s["id"] for s in hs["not_raised"]}
    assert "pik3ca-her2" in skipped  # HER2-positive only
    monkeypatch.setattr(omics, "case_scores", lambda pf: {"receptors": {
        "ER": {"status": "Negative"}, "PR": {"status": None}, "HER2": {"status": "Equivocal"}}})
    assert ev._tcga_receptors(case_file(SimpleNamespace(**CASE))) == {}  # neither settles
