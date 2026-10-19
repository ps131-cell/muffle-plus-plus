"""Workspace patient files: versions, tests and SOS alerts from data the demo already has."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from muffle.timeline import EVENTS
from muffle.workspace import PLANNED, case_file, lab_series, synthetic_file

ROOT = Path(__file__).resolve().parents[1]


def timeline() -> dict:
    return json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))


def test_synthetic_file_has_a_version_per_event_and_alerts_where_the_record_turns():
    tl = timeline()
    # the committed JSON was built from this record
    assert [(e["month"], e["kind"], e["text"]) for e in tl["events"]] == \
        [(e["month"], e["kind"], e["text"]) for e in EVENTS]
    pf = synthetic_file(tl)
    assert pf.kind == "synthetic" and len(pf.versions) == len(EVENTS) == 16
    v = {ver.month: ver for ver in pf.versions}
    assert all((ver.risk is None) == (ver.month < 0) for ver in pf.versions)  # scored from month 0

    assert not v[7].alerts and not v[1].alerts  # stable imaging; a +14-point change is below 20
    assert v[11].alerts[0].what.startswith("CA 15-3 rose from 30 to 52 U/mL (+73%)")
    month12 = [a.what for a in v[12].alerts]
    assert any(w.startswith("Progression on imaging") for w in month12)
    assert any(w == "New metastatic site: liver" for w in month12)
    assert any(w.startswith("12-month risk up +51 points") for w in month12)
    for ver in pf.versions:
        for a in ver.alerts:
            assert a.evidence and a.rule and a.threshold and a.source

    tests = pf.tests
    assert [t.month for t in tests if t.kind == "Lab"] == [-2, 1, 4, 7, 11, 16, 19, 24]
    imaging = [t for t in tests if t.kind == "Imaging"]
    assert [t.month for t in imaging] == [-1, 7, 12, 19]
    assert {t.status for t in imaging} == {PLANNED}
    assert [(t.month, t.workbench) for t in tests if t.kind == "Sequencing"] == [(0, "mutations")]
    assert v[1].treatments == ["palbociclib", "fulvestrant"] and v[13].treatments == ["alpelisib"]


def test_a_new_driver_raises_an_alert_only_with_level_a_or_b_evidence():
    tl = timeline()
    tl["evidence"] = {"PIK3CA H1047R": [{"evidence_level": "C"}, {"evidence_level": "D"}]}
    assert not {v.month: v for v in synthetic_file(tl).versions}[0].alerts
    tl["evidence"] = {"PIK3CA H1047R": [{"evidence_level": "D"}, {"evidence_level": "A"}]}
    alerts = {v.month: v for v in synthetic_file(tl).versions}[0].alerts
    assert len(alerts) == 1 and "level A" in alerts[0].what and "hypothesis" in alerts[0].evidence


def test_lab_series_changes_from_previous_and_nadir():
    rows = lab_series(EVENTS, "ca153")
    assert [r["month"] for r in rows] == [-2, 1, 4, 7, 11, 16, 19, 24]
    assert "change" not in rows[0] and "from_nadir" not in rows[0]
    month11 = rows[4]  # 52 after 30 at month 7, the lowest so far
    assert month11["value"] == 52 and month11["per_month"] == 5.5
    assert round(month11["change"], 2) == round(month11["from_nadir"], 2) == 0.73
    assert lab_series(EVENTS, "cea") == []


def test_tcga_case_file_has_one_version_its_layers_and_no_alerts():
    case = SimpleNamespace(index=661, site="site-2", percentile=99.2, group="high", age=57.0,
                           stage="III", layers=["genomic", "rna", "protein", "clinical"],
                           missing=["methylation"],
                           mutations=["PIK3CA p.H1047R", "TP53 p.N131Tfs*39"])
    pf = case_file(case, 0.728)
    assert pf.id == "Case 661" and len(pf.versions) == 1 and not pf.latest.alerts
    assert "99th percentile" in pf.latest.summary and pf.latest.risk["c_index"] == 0.728
    assert [t.workbench for t in pf.tests] == ["omics", "omics", "omics", "record", "mutations"]
    assert pf.tests[-1].result == "PIK3CA H1047R, TP53 N131Tfs*39"
    observed = dict(pf.latest.observed)
    assert observed["Not measured"] == "methylation" and observed["Age band"] == "50-64"

    unsequenced = case_file(SimpleNamespace(**{**vars(case), "mutations": None}))
    assert "mutations" not in [t.workbench for t in unsequenced.tests]
    assert dict(unsequenced.latest.observed)["Driver mutations"].startswith("not sequenced")


def test_the_hosted_app_can_build_files_without_scikit_learn():
    # the hosted install (app/requirements.txt) has no scikit-learn
    code = "import sys, muffle.workspace; assert 'sklearn' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True,
                   env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
