"""Grounding check: every number, gene and link in a note must come from the tool outputs."""

from muffle.report.grounding import check_note, describe

EVIDENCE = {
    "case": {"model_validation_c_index": 0.693, "missing_data_layers": ["protein"]},
    "tool_outputs": [
        {"tool": "predict_risk", "result": {"log_risk": -0.412, "cohort_percentile": 81.3,
                                            "risk_group": "high", "cohort_size": 1064}},
        {"tool": "modality_contributions",
         "result": {"log_risk_added_by_layer": {"clinical": 0.31, "rna": -0.12}}},
        {"tool": "top_features", "arguments": {"modality": "rna"},
         "result": {"features": [{"name": "GATA3", "score": -0.0412},
                                 {"name": "RNU6-607P", "score": 0.02}]}},
        {"tool": "search_literature",
         "result": {"results": [{"title": "GATA3 in 2019", "url": "https://example.org/a"}]}},
    ],
}
NAMES = {"rna": ["GATA3", "ESR1", "RNU6-607P", "AC124067.4"], "clinical": ["age", "stage"]}


def kinds(text):
    return {(i["kind"], i["text"]) for i in check_note(text, EVIDENCE, NAMES)}


def test_supported_note_passes():
    note = ("**Summary** High risk: 81st percentile of 1,064 patients (C-index 0.69, 69%).\n"
            "**Drivers** clinical +0.31; RNA lowers risk by 0.12. GATA3 (score -0.041) and "
            "RNU6-607P; GATA3-high tumours. Stage T2N0M0, HER2 status unknown, 3 layers.\n"
            "**Literature** [GATA3 in 2019](https://example.org/a/).")
    assert kinds(note) == set()


def test_invented_items_are_flagged():
    note = ("Risk 0.95, about 2.5x the median, 99th percentile, 40% five-year risk. "
            "ESR1-positive, TP53 and AC124067.4. See https://made.up/x.")
    assert kinds(note) == {("number", "0.95"), ("number", "2.5"), ("number", "99th"),
                           ("number", "40%"), ("gene", "ESR1"), ("gene", "TP53"),
                           ("gene", "AC124067.4"), ("url", "https://made.up/x")}


def test_describe_groups_by_kind():
    issues = check_note("TP53 at 0.95", EVIDENCE, NAMES)
    assert describe(issues) == "numbers: 0.95; genes/features: TP53"
