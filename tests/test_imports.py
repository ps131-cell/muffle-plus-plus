"""Sequencing and imaging-report import: the VCF and MAF checks, the imaging-report rule on
sample sentences, and the report version each adds, with its alerts, on both kinds of file."""

import gzip
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from muffle import crosstest, evolution
from muffle.data.tcga import DRIVERS as TCGA_PANEL
from muffle.imports import (
    IntakeError,
    imaging_read,
    imaging_test,
    lab_tests,
    parse_labs,
    parse_variants,
    sequencing_test,
    short_change,
)
from muffle.longitudinal import DRIVERS as SYNTHETIC_PANEL
from muffle.workbench import documents
from muffle.workbench import genomics as g
from muffle.workbench import radiology
from muffle.workspace import (
    add_version,
    case_file,
    record_events,
    report_markdown,
    sequencing_tests,
    synthetic_file,
)

ROOT = Path(__file__).resolve().parents[1]
CSQ = ("##INFO=<ID=CSQ,Number=.,Type=String,Description=\"Consequence annotations from "
       "Ensembl VEP. Format: Allele|Consequence|IMPACT|SYMBOL|HGVSp|CANONICAL\">")
COLS = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tTUMOR"


def vcf(*records: str, header: str = CSQ) -> bytes:
    return "\n".join(["##fileformat=VCFv4.2", header, COLS, *records]).encode()


def rec(filt: str, csq: str) -> str:
    return f"3\t179234297\t.\tA\tG\t50\t{filt}\tDP=80;CSQ={csq}\tGT\t0/1"


def maf(*rows: str, sample: str = "TCGA-A1-A0SB-01A") -> bytes:
    head = "Hugo_Symbol\tVariant_Classification\tHGVSp_Short\tTumor_Sample_Barcode\tt_alt_count" \
           "\tt_depth"
    return "\n".join(["#version 2.4", head, *(f"{r}\t{sample}" if r.count("\t") == 2 else r
                                              for r in rows)]).encode()


def synthetic():
    return synthetic_file(json.loads((ROOT / "app" / "timeline_synthetic.json")
                                     .read_text(encoding="utf-8")))


def tcga(mutations=("PIK3CA p.H1047R",)):
    case = SimpleNamespace(index=1, site="site-1", percentile=80.0, group="high", age=60.0,
                           stage="II", layers=["clinical"], missing=[],
                           mutations=None if mutations is None else list(mutations))
    return case_file(case, 0.7)


LEVEL_A = [{"evidence_level": "A"}]


# ----------------------------------------------------------------------- VCF and MAF checks

def test_short_change_reads_hgvs_in_three_letter_and_short_form():
    assert short_change("ENSP00000263967.3:p.His1047Arg") == "H1047R"
    assert short_change("p.(Lys103AsnfsTer5)") == "K103Nfs*5"
    assert short_change("p.E545K") == "E545K" and short_change("p.Leu466Ter") == "L466*"
    assert short_change("p.Leu10=") is None and short_change("p.Leu10%3D") is None
    assert short_change("") is None and short_change("p.?") is None


def test_a_vep_vcf_keeps_pass_protein_altering_panel_variants_and_says_why_not_the_rest():
    data = vcf(
        rec("PASS", "G|missense_variant|MODERATE|PIK3CA|ENSP1:p.His1047Leu|,"
                    "G|missense_variant|MODERATE|PIK3CA|ENSP2:p.His1047Arg|YES"),
        rec(".", "G|missense_variant|MODERATE|ESR1|ENSP3:p.Tyr537Ser|YES"),
        rec("PASS", "G|synonymous_variant|LOW|TP53|ENSP4:p.Leu10=|YES"),
        rec("PASS", "G|missense_variant|MODERATE|BRCA2|ENSP5:p.Asp2723His|YES"),
        rec("germline_risk", "G|missense_variant|MODERATE|AKT1|ENSP6:p.Glu17Lys|YES"),
        rec("PASS", "G|missense_variant|MODERATE|PIK3CA|ENSP2:p.His1047Arg|YES"),
        rec("PASS", "G|missense_variant|MODERATE|GATA3|.|YES"),
        "3\t1\t.\tA\tG")
    ok, bad, meta = parse_variants(data, SYNTHETIC_PANEL)
    assert [r["variant"] for r in ok] == ["PIK3CA H1047R", "ESR1 Y537S"]  # the canonical one
    assert meta == {"format": "VCF", "sample": "TUMOR"}
    assert ok[0]["row"] == 4 and "not read from a VCF" in ok[0]["allele_fraction"]
    reasons = {r["row"]: r["reason"] for r in bad}
    assert reasons[6] == "TP53 synonymous_variant: not protein-altering"
    assert reasons[7].startswith("BRCA2: not on the breast panel")
    assert reasons[8] == "FILTER is germline_risk: only PASS calls are kept"
    assert reasons[9] == "PIK3CA H1047R repeats row 4"
    assert reasons[10] == "GATA3: no protein change (HGVSp) in the annotation"
    assert reasons[11] == "fewer than the 8 VCF columns"


def test_a_gzip_snpeff_vcf_and_the_files_the_import_refuses():
    ann = ("##INFO=<ID=ANN,Number=.,Type=String,Description=\"Functional annotations: 'Allele "
           "| Annotation | ...'\">")
    snpeff = ("G|frameshift_variant|HIGH|AKT1|ENSG1|transcript|ENST1|protein_coding|3/14|"
              "c.307del|p.Lys103AsnfsTer5|")
    data = gzip.compress(vcf(f"14\t1\t.\tA\tG\t50\tPASS\tANN={snpeff}", header=ann))
    ok, bad, _ = parse_variants(data, SYNTHETIC_PANEL)
    assert [r["variant"] for r in ok] == ["AKT1 K103Nfs*5"] and bad == []
    with pytest.raises(IntakeError, match="no gene annotation"):
        parse_variants(vcf(rec("PASS", "x"), header="##source=caller"), SYNTHETIC_PANEL)
    with pytest.raises(IntakeError, match="lacks HGVSp"):
        parse_variants(vcf(header=CSQ.replace("|HGVSp", "")), SYNTHETIC_PANEL)
    with pytest.raises(IntakeError, match="MSK-IMPACT"):
        parse_variants(vcf(header=CSQ).replace(b"TUMOR", b"P-0001234-T01-IM6"), SYNTHETIC_PANEL)
    with pytest.raises(IntakeError, match="Neither a VCF"):
        parse_variants(b"gene,change\nPIK3CA,H1047R\n", SYNTHETIC_PANEL)
    with pytest.raises(IntakeError, match="no variant records"):
        parse_variants(vcf(), SYNTHETIC_PANEL)
    with pytest.raises(IntakeError, match="not a readable gzip"):
        parse_variants(b"\x1f\x8bnot gzip", SYNTHETIC_PANEL)


def test_a_maf_keeps_one_samples_panel_variants_with_their_allele_fractions():
    data = maf("PIK3CA\tMissense_Mutation\tp.H1047R\tTCGA-A1-A0SB-01A\t30\t100",
               "MAP3K1\tFrame_Shift_Del\tp.K103Nfs*5",
               "TP53\tSilent\tp.L10=",
               "BRCA1\tMissense_Mutation\tp.C61G",
               "CDH1\tSplice_Site\t")
    ok, bad, meta = parse_variants(data, TCGA_PANEL)
    assert [(r["variant"], r["consequence"]) for r in ok] == [
        ("PIK3CA H1047R", "Missense_Mutation"), ("MAP3K1 K103Nfs*5", "Frame_Shift_Del")]
    assert ok[0]["allele_fraction"] == "allele fraction 0.30 (30 of 100 reads)"
    assert ok[1]["allele_fraction"].startswith("allele fraction: not in the file")
    assert meta == {"format": "MAF", "sample": "TCGA-A1-A0SB-01A"}
    assert [r["reason"] for r in bad] == [
        "TP53 Silent: not protein-altering",
        "BRCA1: not on the breast panel the genomics workbench reads (" + ", ".join(
            sorted(TCGA_PANEL)) + ")",
        "CDH1: no protein change (HGVSp) in the annotation"]
    assert parse_variants(data, SYNTHETIC_PANEL)[0][0]["variant"] == "PIK3CA H1047R"  # 8 genes
    with pytest.raises(IntakeError, match="2 tumor samples"):
        parse_variants(maf("PIK3CA\tMissense_Mutation\tp.H1047R\tS1\t1\t2",
                           "TP53\tMissense_Mutation\tp.R175H\tS2\t1\t2"), TCGA_PANEL)
    with pytest.raises(IntakeError, match="MSK-IMPACT"):
        parse_variants(maf("TP53\tMissense_Mutation\tp.R175H", sample="P-0012345-T01-IM5"),
                       TCGA_PANEL)
    with pytest.raises(IntakeError, match="missing column.*Variant_Classification"):
        parse_variants(b"Hugo_Symbol\tHGVSp_Short\nTP53\tp.R175H\n", TCGA_PANEL)


# -------------------------------------------------------------- the imaging-report rule

@pytest.mark.parametrize("text, read, sites", [
    ("Interval development of new hepatic lesions, consistent with progression.",
     "progression", ["Liver"]),
    ("No evidence of disease progression. Stable osseous metastases.", "stable", []),
    ("Findings suspicious for progression.", "not stated", []),
    ("Progression cannot be excluded.", "not stated", []),
    ("Progression of disease is not seen.", "not stated", []),
    ("No new liver lesions.", "not stated", []),
    ("New lesions in the right lobe of the liver and stable bone lesions.", "stable", ["Liver"]),
    ("Partial response in the liver; new 1.2 cm pulmonary nodule.", "response", ["Lung"]),
    ("CT of 12 May 2024: progressive disease in bone.", "progression", []),
    ("New left axillary lymph node.", "not stated", []),  # regional, not a distant site
    ("Stable disease but new brain metastases.", "stable", ["Brain"]),
    ("There is no interval change.", "stable", []),
    ("New liver and lung lesions are not seen.", "not stated", []),
    ("New lytic lesion in the T8 vertebra.", "not stated", ["Bone"]),  # QA round 2
    ("New hypodense lesion in segment 6 of the liver.", "not stated", ["Liver"]),
    ("No new lytic lesions.", "not stated", []),
])
def test_the_imaging_rule_reads_only_what_a_clause_states(text, read, sites):
    r = imaging_read(text)
    assert (r["read"], r["new_sites"]) == (read, sites)


def test_the_imaging_rule_says_which_clauses_it_set_aside_and_why():
    r = imaging_read("No evidence of progression. Possible new hepatic lesions. Stable bones.")
    assert r["read"] == "stable" and r["words"] == "Stable bones."
    assert [a["why"] for a in r["set_aside"]] == ["negated: progression",
                                                  "hedged: new hepatic lesions"]


# ------------------------------------------------------------------ the version an import adds

def test_imported_sequencing_on_the_synthetic_file_raises_the_driver_alert_once():
    pf = synthetic()
    ok, _, meta = parse_variants(vcf(
        rec("PASS", "G|missense_variant|MODERATE|PIK3CA|p.His1047Arg|YES"),
        rec("PASS", "G|missense_variant|MODERATE|ESR1|p.Tyr537Ser|YES")), SYNTHETIC_PANEL)
    test = sequencing_test(ok, meta, 27, "ctdna.vcf", SYNTHETIC_PANEL, "imported by AB")
    new = add_version(pf, [test], 27, "Imported sequencing", "AB", "14:03",
                      evidence=lambda var: LEVEL_A)
    v, i = new.latest, len(new.versions) - 1
    assert [a.what for a in v.alerts] == [  # PIK3CA H1047R was sequenced at month 0
        "Newly sequenced driver ESR1 Y537S has CIViC level A treatment evidence, for clinician "
        "review"]
    assert v.alerts[0].opens == ("Tests", "Sequencing", 27, "Tumor sequencing (VCF, imported)")
    rows = dict(v.observed)
    assert rows["Driver mutations"] == "PIK3CA H1047R (month 0), ESR1 Y537S (month 27, imported)"
    assert "ESR1" not in rows["Sequenced, not found"] and "TP53" in rows["Sequenced, not found"]
    assert sequencing_tests(new, i)[-1] is test
    assert not add_version(pf, [test], 27, "", "AB", "14:03", evidence=None).latest.alerts
    assert not add_version(pf, [test], 27, "", "AB", "14:03",
                           evidence=lambda var: [{"evidence_level": "C"}]).latest.alerts
    # the genomics workbench reads the imported test, with its own sample and assay
    vs = g.variants(new, evidence={"ESR1 Y537S": LEVEL_A})
    assert [(d["variant"], d["detection"]["sample"], d["detection"]["when"]) for d in vs] == [
        ("PIK3CA H1047R", "bone biopsy", "month 0"), ("PIK3CA H1047R", "TUMOR", "month 27"),
        ("ESR1 Y537S", "TUMOR", "month 27")]
    assert vs[2]["detection"]["assay"] == "imported VCF file" and vs[2]["strongest_level"] == "A"
    assert [r["month"] for r in g.longitudinal(new)["timepoints"]] == [0, 27]
    assert dict(g.provenance(new))["sample"] == "TUMOR"
    earlier = replace(new, versions=new.versions[:-1])  # the workbench as of an earlier version
    assert "ESR1 Y537S" not in {d["variant"] for d in g.variants(earlier, evidence={})}
    assert "ESR1 Y537S" in report_markdown(new, i, {"ESR1 Y537S": []})
    assert crosstest.diff_versions(new, i - 1, i)  # the Timeline and Evolution views
    assert "ESR1" in evolution.context(new, i)["drivers"] and evolution.hypothesis_set(new, i)


def test_imported_sequencing_on_a_tcga_file_adds_to_its_panel_calls():
    pf = tcga()
    ok, _, meta = parse_variants(maf("PIK3CA\tMissense_Mutation\tp.H1047R",
                                     "MAP3K1\tFrame_Shift_Del\tp.K103Nfs*5"), TCGA_PANEL)
    new = add_version(pf, [sequencing_test(ok, meta, 3, "s.maf", TCGA_PANEL, "")], 3, "seq",
                      "AB", "09:00", evidence=lambda var: [])
    assert not new.latest.alerts and new.latest.risk == pf.latest.risk
    assert dict(new.latest.observed)["Driver mutations"] == \
        "PIK3CA H1047R, MAP3K1 K103Nfs*5 (month 3, imported)"
    assert [d["variant"] for d in g.variants(new, evidence={})] == [
        "PIK3CA H1047R", "PIK3CA H1047R", "MAP3K1 K103Nfs*5"]  # baseline, then month 3
    unsequenced = add_version(tcga(None), [sequencing_test(ok[1:], meta, 3, "s.maf", TCGA_PANEL,
                                                           "")], 3, "", "AB", "09:00")
    assert dict(unsequenced.latest.observed)["Driver mutations"] == \
        "MAP3K1 K103Nfs*5 (month 3, imported)"


def test_an_imported_imaging_report_raises_progression_and_only_truly_new_sites():
    pf = synthetic()  # its record names bone (month -1) and liver (month 12)
    text = ("CT chest, abdomen and pelvis. New hepatic and pulmonary lesions, consistent with "
            "progression. No pleural effusion.")
    test = imaging_test("CT CAP", text, 27, "import-1", "imported by AB")
    assert test.result == "read as progression; new liver, lung named"
    new = add_version(pf, [test], 27, "Imported imaging report", "AB", "14:03")
    v = new.latest
    assert [a.what for a in v.alerts] == [
        'Progression on imaging: "New hepatic and pulmonary lesions, consistent with '
        'progression."', "New metastatic site: lung"]
    assert {a.trust for a in v.alerts} == {"moderate"} and v.alerts[0].evidence == "observed"
    assert v.alerts[1].opens == ("Tests", "Imaging", 27, "Imaging report")
    rows = dict(v.observed)
    assert rows["Metastatic sites"] == ("Bone (month -1), Liver (month 12), Lung (month 27, "
                                        "imported report)")
    assert rows["Progressions on imaging"] == "3, last at month 27"
    assert record_events(new)[-1]["progression"] is True  # the lab workbench's lead-lag reads it
    read = radiology.imaging_reads(radiology.file_events(new))[-1]  # and the radiology page
    assert (read["month"], read["read"], read["new_sites"]) == (27, "progression",
                                                                 ["Liver", "Lung"])
    assert documents.file_documents(new)[-1]["text"] == text
    # a stable read raises nothing, and a marker rise after it is a discrepancy
    stable = add_version(pf, [imaging_test("CT", "Imaging stable.", 25, "import-1", "")], 25,
                         "", "AB", "14:00")
    assert not stable.latest.alerts
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,45,U/mL\n", after=25)
    both = add_version(stable, lab_tests(ok)[0], 27, "", "AB", "14:05")
    assert any(d["what"] == "CA 15-3 rising while the latest imaging read stable"
               for d in crosstest.discrepancies(both, len(both.versions) - 1))


def test_an_imaging_report_on_a_tcga_file_starts_its_sites_and_progressions():
    text = "New osseous metastases. Findings consistent with progressive disease."
    new = add_version(tcga(), [imaging_test("Bone scan", text, 4, "import-1", "")], 4, "", "AB",
                      "09:00")
    assert [a.what.split(":")[0] for a in new.latest.alerts] == [
        "Progression on imaging", "New metastatic site"]
    rows = dict(new.latest.observed)
    assert rows["Metastatic sites"] == "Bone (month 4, imported report)"
    assert rows["Progressions on imaging"] == "1, last at month 4"


def test_the_example_files_import_as_their_format_reads_them():
    from muffle import imports as intake
    from muffle.workbench.documents import extract

    ok, bad, meta = parse_variants(intake.MAF_EXAMPLE.encode(), SYNTHETIC_PANEL)
    assert [r["variant"] for r in ok] == ["ESR1 Y537S", "PIK3CA H1047R"] and not bad
    assert meta["format"] == "MAF"
    fields = {f["field"] for f in extract(intake.REPORT_EXAMPLE)}
    assert {"histologic_type", "grade", "er", "pr", "her2", "ki67", "laterality"} <= fields
    assert intake.REPORT_EXAMPLE.startswith("Synthetic example")


def test_the_import_view_says_what_happens_and_offers_the_examples():
    from streamlit.testing.v1 import AppTest

    def page():
        import json as j
        import sys as s
        from pathlib import Path as P

        s.path.insert(0, str(P.cwd() / "app"))
        from workbenches import imports as page_im

        from muffle.workspace import synthetic_file as sf

        tl = j.loads((P.cwd() / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
        page_im.render_view(sf(tl))

    at = AppTest.from_function(page, default_timeout=60).run()
    assert not at.exception, at.exception
    text = " ".join(m.value for m in at.markdown)
    assert "**What happens after an import:** the file gains a new report version" in text
    labels = [d.proto.label for d in at.get("download_button")]
    assert labels == ["Example lab results (CSV)", "Example sequencing (MAF)",
                      "Example pathology report (text)"]
