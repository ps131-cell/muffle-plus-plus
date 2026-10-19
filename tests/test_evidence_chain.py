"""Evidence chain: every sentence of a case note linked to the tool outputs behind it."""

import json
from pathlib import Path

import pytest

from muffle.report.evidence_chain import note_chain, sentences
from muffle.report.grounding import check_note
from muffle.report.nemotron import CaseReport, ToolCall

ROOT = Path(__file__).resolve().parents[1]
NOTES = json.loads((ROOT / "app" / "saved_notes.json").read_text(encoding="utf-8"))
HEADER = {"model_validation_c_index": 0.728}  # the demo bundle's header, not saved with a note
LINK_KEYS = {"item", "tool", "path", "value", "trust", "call"}


@pytest.mark.parametrize("key", sorted(NOTES))
def test_saved_notes_are_fully_linked(key):
    report = CaseReport.from_dict(NOTES[key]["report"])
    chain = note_chain(report, header=HEADER)
    assert chain and all(set(i) == {"sentence", "evidence_type", "links", "unsupported"}
                         for i in chain)
    tagged = [i for i in chain if i["evidence_type"]]
    assert {i["evidence_type"] for i in tagged} <= {"observed", "model inference", "hypothesis"}
    # every tagged bullet keeps its type; the only untagged bullet is note 926's last caveat
    untagged = [i["sentence"] for i in chain if i["evidence_type"] is None
                and "- " + i["sentence"] in report.text]
    assert untagged == (["Research prototype for clinician review only; not a diagnosis or "
                         "treatment recommendation."] if key == "926" else [])
    assert not report.issues
    assert [u for i in chain for u in i["unsupported"]] == []
    for i in chain:
        for link in i["links"]:
            assert set(link) == LINK_KEYS and link["trust"] in ("strong", "weak")
            if link["call"] is None:
                assert link["tool"] == "case"
            else:
                assert report.trace[link["call"]].name == link["tool"]
                assert link["path"]
    # the percentile in the summary sentence reaches predict_risk
    first = chain[0]
    assert first["evidence_type"] is None
    pct = next(link for link in first["links"] if link["item"].endswith(("th", "st", "rd", "nd")))
    assert pct["tool"] == "predict_risk" and pct["path"] == "cohort_percentile"
    assert pct["trust"] == "strong"


def test_links_reach_contributions_and_features_and_civic_urls():
    report = CaseReport.from_dict(NOTES["1043"]["report"])
    chain = {i["sentence"]: i for i in note_chain(report, header=HEADER)}
    genomic = next(i for s, i in chain.items() if s.startswith("Genomic raises risk by 0.053"))
    links = {link["item"]: link for link in genomic["links"]}
    assert links["0.053"]["path"] == "log_risk_added_by_layer.genomic"
    assert links["0.053"]["tool"] == "modality_contributions"
    assert links["LINC01300"]["tool"] == "top_features" and links["LINC01300"]["trust"] == "strong"
    path = links["LINC01300"]["path"]
    assert path.startswith("features[") and path.endswith(".name")
    civic = next(i for s, i in chain.items() if "evidence_items/2784" in s)
    assert civic["evidence_type"] == "hypothesis"
    url = next(link for link in civic["links"] if link["item"].startswith("https://"))
    assert url["tool"] == "treatment_evidence" and url["path"].endswith(".url")
    assert url["trust"] == "strong"
    assert chain["Validation C-index: 0.728."]["links"][0] == {
        "item": "0.728", "tool": "case", "path": "model_validation_c_index", "value": "0.728",
        "trust": "strong", "call": None}


def test_rounded_numbers_link_weakly_and_invented_ones_are_unsupported():
    trace = [ToolCall(1, "predict_risk", {}, {"cohort_percentile": 81.3, "risk_group": "high",
                                              "log_risk": -0.412}),
             ToolCall(2, "top_features", {"modality": "rna"},
                      {"features": [{"name": "GATA3", "score": -0.0412}]}),
             ToolCall(3, "search_literature", {"genes": ["GATA3"]},
                      {"results": [{"title": "ESR1 and GATA3 in 2019",
                                    "url": "https://example.org/a"}]})]
    text = ("**Summary**  \nHigh risk: 81st percentile. Risk 0.95 is invented.\n\n"
            "**Model inferences**  \n- [Model inference] GATA3 (score -0.041), ESR1-driven, "
            "TP53 at 2.5x.  \n- [Hypothesis] See https://example.org/a/ and https://made.up/x.")
    report = CaseReport(text, trace, "agent")
    chain = note_chain(report, names={"rna": ["GATA3", "ESR1"]})
    assert [(i["sentence"], i["evidence_type"]) for i in chain] == [
        ("High risk: 81st percentile.", None), ("Risk 0.95 is invented.", None),
        ("GATA3 (score -0.041), ESR1-driven, TP53 at 2.5x.", "model inference"),
        ("See https://example.org/a/ and https://made.up/x.", "hypothesis")]
    pct, invented, genes, urls = chain
    assert pct["links"][0]["trust"] == "weak" and pct["links"][0]["path"] == "cohort_percentile"
    assert pct["links"][0]["value"] == "81.3"  # 81st is 81.3 rounded
    assert invented["links"] == [] and invented["unsupported"] == ["0.95"]
    by = {link["item"]: link for link in genes["links"]}
    assert by["GATA3"]["trust"] == "strong" and by["GATA3"]["path"] == "features[0].name"
    assert by["-0.041"]["trust"] == "weak" and by["-0.041"]["value"] == "-0.0412"
    assert by["ESR1-driven"]["trust"] == "weak"   # only the hyphen part ESR1 is in the trace
    assert by["ESR1-driven"]["tool"] == "search_literature"
    assert "TP53" not in by and set(genes["unsupported"]) == {"2.5", "TP53"}
    assert "ESR1" not in genes["unsupported"]  # a hyphen part found in the trace, as in check_note
    assert [link["item"] for link in urls["links"]] == ["https://example.org/a"]
    assert urls["links"][0]["trust"] == "strong" and urls["unsupported"] == ["https://made.up/x"]
    # the per-sentence verdicts agree with the whole-note grounding check
    evidence = {"case": {}, "tool_outputs": [{"tool": c.name, "arguments": c.arguments,
                                              "result": c.result} for c in trace]}
    whole = {i["text"] for i in check_note(text, evidence, {"rna": ["GATA3", "ESR1"]})}
    assert whole == {u for i in chain for u in i["unsupported"]}


def test_sentences_skip_headings_and_keep_bullets_whole():
    text = ("## Summary\nOne. Two (with 0.5).\n**Observed**  \n- [Observed] Stage I. Age 65+.  \n"
            "[Hypothesis] No search.\n- untagged bullet\n")
    assert sentences(text) == [("One.", None), ("Two (with 0.5).", None),
                               ("Stage I. Age 65+.", "observed"), ("No search.", "hypothesis"),
                               ("untagged bullet", None)]
