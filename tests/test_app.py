"""The workspace pages render: the patient list and both kinds of patient file in every view
(Streamlit's AppTest, on a bundle built from the test cohort; no network, no keys)."""

import hashlib
import json

import pytest

from muffle import evolution, workspace
from muffle.imports import imaging_test, lab_tests, parse_labs, sequencing_test
from tests.appfixture import APP, button, shown
from tests.skeleton import assert_skeleton

pytestmark = pytest.mark.filterwarnings("error")  # a warning from a page fails the test
VIEWS = ("Tests", "Timeline", "Evolution", "Import tests", "Report")


def test_patient_files_render_in_every_view(app):
    demo, shipped = app.demo, app.shipped
    at = app.new().run()
    assert not at.exception
    patients = at.dataframe[0].value["Patient"].tolist()
    case = f"Case {demo.cases[0].index}"
    assert patients[0] == "SYNTHETIC-001" and case in patients
    # the list searches genes and filters by what the files hold
    at.text_input(key="list-search").set_value("pik3ca").run()
    assert set(at.dataframe[0].value["Patient"]) == {"SYNTHETIC-001", case}
    at.text_input(key="list-search").set_value("").run()
    at.pills(key="list-holds").set_value(["Imaging"]).run()  # reports, and the case's MRI
    assert at.dataframe[0].value["Patient"].tolist() == ["SYNTHETIC-001", case]
    at.pills(key="list-holds").set_value([]).run()
    at.toggle(key="list-sos").set_value(True).run()
    assert at.dataframe[0].value["Patient"].tolist() == ["SYNTHETIC-001"]
    assert at.dataframe[0].value["Open SOS"].tolist() == ["🔴 7 open"]
    at.toggle(key="list-sos").set_value(False).run()

    at.selectbox(key="patient").select("SYNTHETIC-001").run()
    assert not at.exception and "Synthetic patient" in at.warning[0].value
    assert workspace.DISCLAIMER in shown(at)  # in the file's header, sidebar collapsed or not
    for view in VIEWS:
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, view
    at.select_slider(key="version-SYNTHETIC-001").set_value(11).run()  # month 12
    text = shown(at)
    # the header: recorded and documented side by side, drivers, imaging, risk, open SOS alerts
    assert "*Recorded:* stage II, HR+, HER2−" in text and "*Documented:* Stage II" in text
    assert "PIK3CA H1047R (CIViC level A)" in text and "**:red[SOS]** · 7 open" in text
    assert "**Source test:**" in text and "**Method and version:**" in text  # the Why? popovers
    # one queue: SOS alerts, tests that disagree, the workbenches' items; strongest first
    assert "**Attention** · 15 items: 7 SOS, 0 where tests disagree, 8 from the workbenches" in text
    assert "1/15 · Progression on imaging" in text and "New metastatic site: liver" in text
    queue = "queue-SYNTHETIC-001-11"
    at.button(key=f"open-{queue}").click().run()  # lands on the imaging report behind the alert
    assert at.segmented_control(key="view").value == "Tests"
    assert "Imaging report, month 12" in shown(at) and "Radiology workbench" in shown(at)
    assert "no measurements recorded" in shown(at) and not at.exception
    assert_skeleton(at, "radiology")
    at.segmented_control(key="view").set_value("Report").run()
    for _ in range(5):
        at.button(key=f"next-{queue}").click().run()
    assert "6/15 · `L4` CA 15-3 rose from 30 to 52" in shown(at)  # the alert took the lab pointer
    assert "also raised by the labs workbench (L4)" in shown(at)
    at.button(key=f"open-{queue}").click().run()  # the lab workbench opens on L4
    assert at.selectbox(key="SYNTHETIC-001_spot").value.startswith("L4 · month 11")
    at.segmented_control(key="view").set_value("Report").run()
    at.button(key=f"next-{queue}").click().run()  # 7: the ctDNA ESR1 item (PADA-1 situation)
    assert "7/15 · `C2` ESR1 D538G new at month -2" in shown(at)
    at.button(key=f"next-{queue}").click().run()
    assert "8/15 · 12-month risk up" in shown(at) and "placeholder threshold" in shown(at)
    at.button(key=f"reviewed-{queue}").click().run()
    assert "✓ reviewed" in shown(at) and not at.exception
    at.button(key=f"unsure-{queue}").click().run()  # u: weak trust or marked second look
    assert "**unsure list**" in shown(at) and "1/8 · 12-month risk up" in shown(at)
    at.button(key=f"unsure-{queue}").click().run()
    assert [b.label for b in at.main.get("download_button")] == [
        "Download this report version (Markdown)"]
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state["picked-SYNTHETIC-001"] = ("Lab", 11, "CA 15-3")
    at.run()  # the lab page as of month 12: the month-11 rise is a flagged result
    assert "Blood and lab workbench · SYNTHETIC-001 · CA 15-3, month 11" in shown(at)
    assert not at.exception
    spot = at.selectbox(key="SYNTHETIC-001_spot")
    assert any("month 11 · CA 15-3 52" in o for o in spot.options)
    parts = assert_skeleton(at, "labs")  # the page skeleton, its counts in the details headers
    assert ("spot", "Spot panel") in parts
    assert any(h.startswith("Flagged results (") for _, h in parts)
    at.session_state["picked-SYNTHETIC-001"] = ("Pathology report", -40, "Diagnosis")
    at.run()  # the slide workbench, on a public example region, saying it isn't this patient
    assert "Pathology slide workbench" in shown(at)
    assert "nothing below is this patient's tissue" in shown(at) and not at.exception
    assert_skeleton(at, "slides")
    at.segmented_control(key="view").set_value("Timeline").run()  # compare month 11 with 12
    assert "~ Metastatic sites" in shown(at) and "12-month risk" in shown(at)
    # the timeline: what this version brought, and time travel from it and back
    assert "You are viewing **month 12**" in shown(at) and not at.exception
    assert "New in this version** · month 12 · Imaging" in shown(at)
    assert "SOS alerts raised** · 3" in shown(at) and "Workbench findings that changed" in shown(at)
    at.button(key="jump-from-SYNTHETIC-001-11").click().run()  # the compare's From side
    assert at.select_slider(key="version-SYNTHETIC-001").value == 10 and not at.exception
    assert "New in this version** · month 11 · Lab" in shown(at)
    at.button(key="new-SYNTHETIC-001-10-report").click().run()  # its report, as it was then
    assert at.segmented_control(key="view").value == "Report" and "(as it was then)" in shown(at)
    at.button(key="latest-SYNTHETIC-001").click().run()  # the banner's way back
    assert at.select_slider(key="version-SYNTHETIC-001").value == 15
    assert "You are viewing" not in shown(at) and not at.exception
    at.select_slider(key="version-SYNTHETIC-001").set_value(11).run()
    at.segmented_control(key="view").set_value("Report").run()
    button(at, "Open the Evolution view").click().run()  # the report's hook, as of month 12
    assert at.segmented_control(key="view").value == "Evolution"
    assert "Tumor evolution and treatment evidence" in shown(at) and not at.exception
    watch = next(d.value for d in at.dataframe if "What to watch" in d.value.columns)
    assert any("ESR1 ligand-binding-domain mutation" in e for e in watch["What to watch"])
    assert "snapshot" in shown(at)
    assert_skeleton(at, "evolution")
    tl = json.loads((APP.parent / "timeline_synthetic.json").read_text(encoding="utf-8"))
    key = evolution.hypothesis_set(workspace.synthetic_file(tl), 11)["items"][0]["key"]
    mark = f"evo-mark-{hashlib.sha1(key.encode()).hexdigest()[:10]}"
    at.segmented_control(key=mark).set_value("agree").run()  # joins the file's review list
    assert at.session_state["reviews"][key]["mark"] == "agree"
    at.segmented_control(key="view").set_value("Report").run()
    assert any("2 marked" in e.label for e in at.expander)  # the alert above and this one
    at.select_slider(key="version-SYNTHETIC-001").set_value(10).run()  # month 11
    assert "CA 15-3 rising while the latest imaging read stable" in shown(at)
    assert "Repeat CA 15-3 specimen within a month" in shown(at) and not at.exception

    # the clinical documents workbench opens from a clinic note
    at.select_slider(key="version-SYNTHETIC-001").set_value(15).run()
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state["picked-SYNTHETIC-001"] = ("Clinic note", 13, "Clinic visit")
    at.run()
    assert "Clinical documents" in shown(at) and "documented facts" in shown(at)
    assert not at.exception
    # the ctDNA monitor opens from a ctDNA test, labeled synthetic, and links to Evolution
    at.session_state["picked-SYNTHETIC-001"] = ("ctDNA (liquid biopsy)", 9,
                                                "ctDNA panel (synthetic series)")
    at.run()
    assert "ctDNA monitor (liquid biopsy)" in shown(at) and not at.exception
    assert any(w.value.startswith("Synthetic series") for w in at.warning)
    assert_skeleton(at, "ctdna")
    button(at, "Open the Evolution view: what to watch next").click().run()
    assert at.segmented_control(key="view").value == "Evolution" and not at.exception
    at.segmented_control(key="view").set_value("Tests").run()
    # an import (what the Import tests dialog stores) adds a version and re-runs the rise rule
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,45,U/mL\n", after=24)
    tests, observed = lab_tests(ok)
    at.session_state["imports"] = {"SYNTHETIC-001": [{"kind": "Lab results", "rejected": [],
                                                      "version": {
        "tests": tests, "month": 27, "event": "Imported lab results", "observed": observed,
        "by": "AB", "at": "14:03"}}]}
    at.session_state["picked-SYNTHETIC-001"] = ("Lab", 27, "CA 15-3")
    at.run()
    at.select_slider(key="version-SYNTHETIC-001").set_value(16).run()
    spot = at.selectbox(key="SYNTHETIC-001_spot")
    assert any("month 27 · CA 15-3 45" in o for o in spot.options) and not at.exception
    at.segmented_control(key="view").set_value("Report").run()
    assert "month 27 · imported by AB at 14:03" in shown(at)
    assert "CA 15-3 rose from 31 to 45 U/mL (+45%)" in shown(at) and not at.exception
    at.segmented_control(key="view").set_value("Import tests").run()
    assert "Imported in this session" in shown(at) and "kept for this browser session only" in \
        shown(at)
    assert_skeleton(at, "imports")
    at.segmented_control(key="view").set_value("Timeline").run()
    assert not at.exception  # the import is a node, and its card names who, the test and alert
    assert "New in this version** · month 27 · imported by AB at 14:03" in shown(at)
    assert "imported by AB at 14:03; kept for this browser session only" in shown(at)
    assert "CA 15-3 rose from 31 to 45" in shown(at)
    spec = " ".join(c.proto.spec for c in at.get("vega_lite_chart"))
    assert "Imported tests" in spec and '"node"' in spec
    # imported sequencing joins the genomics workbench; an imported imaging report raises its
    # alerts and opens on its text and what the rule read, above the radiology report page
    seq = sequencing_test([{"variant": "ESR1 Y537S", "allele_fraction": "not read"}],
                          {"format": "VCF", "sample": "T"}, 27, "s.vcf", ["ESR1"], "")
    scan = imaging_test("CT CAP", "New pulmonary nodules, consistent with progression.", 27,
                        "import-3", "")
    imports = at.session_state["imports"]
    imports["SYNTHETIC-001"] = imports["SYNTHETIC-001"] + [
        {"kind": kind, "rejected": [], "version": {"tests": [t], "month": 27, "event": kind,
                                                   "observed": [], "by": "AB", "at": "14:05"}}
        for kind, t in (("Sequencing", seq), ("Imaging report", scan))]
    at.session_state["imports"] = imports
    at.run()
    at.select_slider(key="version-SYNTHETIC-001").set_value(18).run()
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state["picked-SYNTHETIC-001"] = ("Sequencing", 27, seq.name)
    at.run()
    assert "Genomics workbench" in shown(at) and "ESR1 Y537S" in shown(at) and not at.exception
    assert_skeleton(at, "genomics")
    at.session_state["picked-SYNTHETIC-001"] = ("Imaging", 27, "Imaging report")
    at.run()
    assert "New distant sites named:** Lung" in shown(at) and "Radiology workbench" in shown(at)
    assert not at.exception
    at.segmented_control(key="view").set_value("Report").run()
    assert 'Progression on imaging: "New pulmonary nodules' in shown(at)
    # the new-site alert and the radiology workbench's item for that site are one finding, both
    # trust moderate (the import's text rule read the site): the alert is kept, on the item's
    # pointer
    assert "`Lung` New metastatic site: lung" in shown(at) and not at.exception

    at.selectbox(key="patient").select(case).run()
    at.segmented_control(key="view").set_value("Tests").run()
    assert "Genomics workbench" in shown(at) and "PIK3CA H1047R" in shown(at)
    for kind, layer in (("Data layer", "rna"), ("Clinical record", "clinical")):
        at.session_state[f"picked-{case}"] = (kind, None, workspace.ASSAYS[layer])
        at.run()  # the omics workbench; this test cohort has no precomputed scores
        assert "Expression, methylation and protein" in shown(at) and not at.exception, layer
        assert "No precomputed subtype" in " ".join(w.value for w in at.warning)
        assert_skeleton(at, "omics")
    at.selectbox(key=f"omics-spot-{case}").select_index(0).run()
    next(s for s in at.segmented_control if s.label == "Your mark").set_value("agree").run()
    assert any(k.startswith(f"{case}|omics|") for k in at.session_state.reviews)
    if shipped:  # the imaging test opens the image viewer on the shipped study
        at.session_state[f"picked-{case}"] = ("Imaging", None, shipped[0]["name"])
        at.run()
        assert "Radiology workbench" in shown(at) and "**C1** ·" in shown(at)
        assert "not validated on breast mri here" in shown(at).lower() and not at.exception
        labels = [e.label for e in at.expander]
        assert any(x.startswith("Three planes") for x in labels)
        assert any(x.startswith("Since the last study") for x in labels)
        assert_skeleton(at, "radiology")
    for view in VIEWS:
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, view
    assert "Tumor-board note" in shown(at) and "nothing alarming" in shown(at)

    # an import on a TCGA file reaches the report's queue and the timeline's version diff
    ok, _ = parse_labs(b"month,marker,value,unit\n0,CA 15-3,20,U/mL\n1,CA 15-3,45,U/mL\n")
    tests, observed = lab_tests(ok)
    at.session_state["imports"] = {case: [{"kind": "Lab results", "rejected": [], "version": {
        "tests": tests, "month": 1, "event": "Imported lab results", "observed": observed,
        "by": "AB", "at": "14:10"}}]}
    at.run()
    assert "CA 15-3 rose from 20 to 45 U/mL (+125%)" in shown(at) and not at.exception
    assert "**:red[SOS]** · 1 open" in shown(at)
    at.segmented_control(key="view").set_value("Timeline").run()
    assert "+ Lab: CA 15-3 (month 1)" in shown(at) and not at.exception
    assert "One sample; the timeline grows with imports" in shown(at)

    # Methods and validation: a card per model and rule, one list of failures and placeholders
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]  # switch_page() takes page files, not callable pages
    at.run()
    assert not at.exception
    heads = [h.value for h in at.header]
    assert heads[:2] == ["Models", "Rules"] and heads[-3:] == [
        "Known failures", "Every placeholder in the app", "Limits"]
    cards = " ".join(s.value for s in at.subheader)
    for card in ("Multi-omic survival model", "MSK-CHORD landmark models", "Breast tissue head",
                 "Nuclei (StarDist)", "Case note", "SOS alerts", "Lab result rules",
                 "Slide geometry", "Genomics", "Clinical documents", "Tumor evolution",
                 "Lesion contours (MedSAM", "Screening score (mammoscreen", "Radiology: report",
                 "Change over time (rigid alignment", "Multiplanar views and cine",
                 "Mammography geometry"):
        assert card in cards, card
    placeholders = next(d.value for d in at.dataframe if "Placeholder" in d.value.columns)
    assert f"{workspace.RISK_JUMP} points of 12-month risk" in placeholders["Value"].tolist()
