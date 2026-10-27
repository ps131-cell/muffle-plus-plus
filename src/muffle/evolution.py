"""Tumor evolution and treatment evidence for a patient file (docs/VISION.md parts two and three;
docs/evolution.md): a cited table of escape routes, the per-patient "what to watch next" set, the
record's events over time and clonal order from allele fractions. Pure functions, no Streamlit.

Everything here is evidence and hypothesis for clinician review, never advice and never a
regimen. Each row of ``TABLE`` names the context that raises it (a recorded treatment class, the
receptor status, an observed driver), the event, what each source's abstract reports (cohort and
frequency included, nothing beyond it), the test that would detect the event and when it would
matter. Every source's PMID and DOI was checked against PubMed (NCBI E-utilities) on
``VERIFIED``; a row whose source could not be verified was dropped. A frequency is a cohort's
figure, never this patient's probability. Nothing here runs a model.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from muffle.memo import per_file
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench import documents
from muffle.workspace import (
    DISCLAIMER,
    PatientFile,
    card,
    finding_key,
    look,
    sequencing_tests,
)

VERIFIED = "2026-10-20"  # every PMID and DOI in SOURCES, checked against PubMed that day
VAF_JSON = Path(__file__).resolve().parents[2] / "app" / "evolution_vaf.json"

SOURCES = {  # key -> the paper as PubMed lists it
    "angus2019": ("Angus et al. 2019", "Nat Genet", "31570896", "10.1038/s41588-019-0507-7",
                  "The genomic landscape of metastatic breast cancer highlights changes in "
                  "mutation and signature frequencies"),
    "aurilio2014": ("Aurilio et al. 2014", "Eur J Cancer", "24269135",
                    "10.1016/j.ejca.2013.10.004",
                    "A meta-analysis of oestrogen receptor, progesterone receptor and human "
                    "epidermal growth factor receptor 2 discordance between primary breast cancer "
                    "and metastases"),
    "bertheau2013": ("Bertheau et al. 2013", "Breast", "24074787", "10.1016/j.breast.2013.07.005",
                     "p53 in breast cancer subtypes and new insights into response to "
                     "chemotherapy"),
    "bertucci2019": ("Bertucci et al. 2019", "Nature", "31118521", "10.1038/s41586-019-1056-z",
                     "Genomic characterization of metastatic breast cancers"),
    "bidard2022": ("Bidard et al. 2022 (PADA-1)", "Lancet Oncol", "36183733",
                   "10.1016/S1470-2045(22)00555-1",
                   "Switch to fulvestrant and palbociclib versus no switch in advanced breast "
                   "cancer with rising ESR1 mutation during aromatase inhibitor and palbociclib "
                   "therapy (PADA-1)"),
    "bidard2025": ("Bidard et al. 2025 (SERENA-6)", "N Engl J Med", "40454637",
                   "10.1056/NEJMoa2502929",
                   "First-Line Camizestrant for Emerging ESR1-Mutated Advanced Breast Cancer"),
    "condorelli2018": ("Condorelli et al. 2018", "Ann Oncol", "29236940",
                       "10.1093/annonc/mdx784",
                       "Polyclonal RB1 mutations and acquired resistance to CDK 4/6 inhibitors "
                       "in patients with metastatic breast cancer"),
    "costa2020": ("Costa et al. 2020", "Cancer Discov", "31594766",
                  "10.1158/2159-8290.CD-18-0830",
                  "PTEN Loss Mediates Clinical Cross-Resistance to CDK4/6 and PI3Kα "
                  "Inhibitors in Breast Cancer"),
    "dumay2013": ("Dumay et al. 2013", "Int J Cancer", "22886769", "10.1002/ijc.27767",
                  "Distinct tumor protein p53 mutants in breast cancer subgroups"),
    "fribbens2016": ("Fribbens et al. 2016", "J Clin Oncol", "27269946",
                     "10.1200/JCO.2016.67.3061",
                     "Plasma ESR1 Mutations and the Treatment of Estrogen Receptor-Positive "
                     "Advanced Breast Cancer"),
    "gerstung2020": ("Gerstung et al. 2020", "Nature", "32025013", "10.1038/s41586-019-1907-7",
                     "The evolutionary history of 2,658 cancers"),
    "harveyjones2024": ("Harvey-Jones et al. 2024", "Ann Oncol", "38244928",
                        "10.1016/j.annonc.2024.01.003",
                        "Longitudinal profiling identifies co-occurring BRCA1/2 reversions, "
                        "TP53BP1, RIF1 and PAXIP1 mutations in PARP inhibitor-resistant "
                        "advanced breast cancer"),
    "hartmaier2018": ("Hartmaier et al. 2018", "Ann Oncol", "29360925", "10.1093/annonc/mdy025",
                      "Recurrent hyperactive ESR1 fusion proteins in endocrine therapy-resistant "
                      "breast cancer"),
    "juric2015": ("Juric et al. 2015", "Nature", "25409150", "10.1038/nature13948",
                  "Convergent loss of PTEN leads to clinical resistance to a PI(3)Kα "
                  "inhibitor"),
    "kingston2024": ("Kingston et al. 2024", "Cancer Discov", "37982575",
                     "10.1158/2159-8290.CD-22-1387",
                     "ESR1 F404 Mutations and Acquired Resistance to Fulvestrant in ESR1-Mutant "
                     "Breast Cancer"),
    "lefebvre2016": ("Lefebvre et al. 2016", "PLoS Med", "28027327",
                     "10.1371/journal.pmed.1002201",
                     "Mutational Profile of Metastatic Breast Cancers: A Retrospective Analysis"),
    "li2018": ("Li et al. 2018", "Cancer Cell", "30537512", "10.1016/j.ccell.2018.11.006",
               "Loss of the FAT1 Tumor Suppressor Promotes Resistance to CDK4/6 Inhibitors via "
               "the Hippo Pathway"),
    "loibl2014": ("Loibl et al. 2014", "J Clin Oncol", "25199759", "10.1200/JCO.2014.55.7876",
                  "PIK3CA mutations are associated with lower rates of pathologic complete "
                  "response to anti-human epidermal growth factor receptor 2 (her2) therapy in "
                  "primary HER2-overexpressing breast cancer"),
    "majewski2015": ("Majewski et al. 2015", "J Clin Oncol", "25559818",
                     "10.1200/JCO.2014.55.2158",
                     "PIK3CA mutations are associated with decreased benefit to neoadjuvant "
                     "human epidermal growth factor receptor 2-targeted therapies in breast "
                     "cancer"),
    "mao2020": ("Mao et al. 2020", "Clin Cancer Res", "32723837",
                "10.1158/1078-0432.CCR-19-3958",
                "Acquired FGFR and FGF Alterations Confer Resistance to Estrogen Receptor (ER) "
                "Targeted Therapy in ER(+) Metastatic Breast Cancer"),
    "nayar2019": ("Nayar et al. 2019", "Nat Genet", "30531871", "10.1038/s41588-018-0287-5",
                  "Acquired HER2 mutations in ER(+) metastatic breast cancer confer resistance "
                  "to estrogen receptor-directed therapies"),
    "oleary2018": ("O'Leary et al. 2018 (PALOMA-3)", "Cancer Discov", "30206110",
                   "10.1158/2159-8290.CD-18-0264",
                   "The Genetic Landscape and Clonal Evolution of Breast Cancer Resistance to "
                   "Palbociclib plus Fulvestrant in the PALOMA-3 Trial"),
    "pearson2020": ("Pearson et al. 2020", "Clin Cancer Res", "31591187",
                    "10.1158/1078-0432.CCR-18-4044",
                    "Inactivating NF1 Mutations Are Enriched in Advanced Breast Cancer and "
                    "Contribute to Endocrine Therapy Resistance"),
    "razavi2018": ("Razavi et al. 2018", "Cancer Cell", "30205045",
                   "10.1016/j.ccell.2018.08.008",
                   "The Genomic Landscape of Endocrine-Resistant Advanced Breast Cancers"),
    "razavi2019": ("Razavi et al. 2019", "Nat Med", "31768066", "10.1038/s41591-019-0652-7",
                   "High-intensity sequencing reveals the sources of plasma circulating "
                   "cell-free DNA variants"),
    "razavi2020": ("Razavi et al. 2020", "Nat Cancer", "32864625", "10.1038/s43018-020-0047-1",
                   "Alterations in PTEN and ESR1 promote clinical resistance to alpelisib plus "
                   "aromatase inhibitors"),
    "robinson2013": ("Robinson et al. 2013", "Nat Genet", "24185510", "10.1038/ng.2823",
                     "Activating ESR1 mutations in hormone-resistant metastatic breast cancer"),
    "schiavon2015": ("Schiavon et al. 2015", "Sci Transl Med", "26560360",
                     "10.1126/scitranslmed.aac7551",
                     "Analysis of ESR1 mutation in circulating tumor DNA demonstrates evolution "
                     "during therapy for metastatic breast cancer"),
    "schrijver2018": ("Schrijver et al. 2018", "J Natl Cancer Inst", "29315431",
                      "10.1093/jnci/djx273",
                      "Receptor Conversion in Distant Breast Cancer Metastases: A Systematic "
                      "Review and Meta-analysis"),
    "shah2012": ("Shah et al. 2012", "Nature", "22495314", "10.1038/nature10933",
                 "The clonal and mutational evolution spectrum of primary triple-negative breast "
                 "cancers"),
    "silwalpandit2014": ("Silwal-Pandit et al. 2014", "Clin Cancer Res", "24803582",
                         "10.1158/1078-0432.CCR-13-2943",
                         "TP53 mutation spectrum in breast cancer is subtype specific and has "
                         "distinct prognostic relevance"),
    "toy2013": ("Toy et al. 2013", "Nat Genet", "24185512", "10.1038/ng.2822",
                "ESR1 ligand-binding domain mutations in hormone-resistant breast cancer"),
    "waks2020": ("Waks et al. 2020", "Ann Oncol", "32245699", "10.1016/j.annonc.2020.02.008",
                 "Reversion and non-reversion mechanisms of resistance to PARP inhibitor or "
                 "platinum chemotherapy in BRCA1/2-mutant metastatic breast cancer"),
    "wander2020": ("Wander et al. 2020", "Cancer Discov", "32404308",
                   "10.1158/2159-8290.CD-19-1390",
                   "The Genomic Landscape of Intrinsic and Acquired Resistance to "
                   "Cyclin-Dependent Kinase 4/6 Inhibitors in Patients with Hormone "
                   "Receptor-Positive Metastatic Breast Cancer"),
    "xu2020": ("Xu et al. 2020", "Nat Genet", "31932695", "10.1038/s41588-019-0554-0",
               "ARID1A determines luminal identity and therapeutic response in "
               "estrogen-receptor-positive breast cancer"),
    "yates2015": ("Yates et al. 2015", "Nat Med", "26099045", "10.1038/nm.3886",
                  "Subclonal diversification of primary breast cancer revealed by multiregion "
                  "sequencing"),
    "yates2017": ("Yates et al. 2017", "Cancer Cell", "28810143", "10.1016/j.ccell.2017.07.005",
                  "Genomic Evolution of Breast Cancer Metastasis and Relapse"),
}

# drug (as the record names it, lower case) -> class; rows name classes, never single drugs
CLASSES = {
    "aromatase inhibitor": ("letrozole", "anastrozole", "exemestane"),
    "SERM": ("tamoxifen", "toremifene"),
    "SERD": ("fulvestrant", "elacestrant", "camizestrant", "imlunestrant", "giredestrant"),
    "CDK4/6 inhibitor": ("palbociclib", "ribociclib", "abemaciclib"),
    "PI3Kα inhibitor": ("alpelisib", "inavolisib", "taselisib"),
    "PARP inhibitor": ("olaparib", "talazoparib", "niraparib", "rucaparib", "veliparib"),
    "platinum": ("carboplatin", "cisplatin"),
}
DRUG_CLASS = {d: c for c, drugs in CLASSES.items() for d in drugs}
ENDOCRINE = ("aromatase inhibitor", "SERM", "SERD")
STRENGTH = {1: "randomized trials", 2: "trial cohorts or meta-analyses",
            3: "clinical cohorts", 4: "case series or laboratory models"}
HR_POS, HR_POS_HER2_NEG, HER2_POS = {"HR": True}, {"HR": True, "HER2": False}, {"HER2": True}
CTDNA = "ctDNA with matched white-cell sequencing"
# the ligand-binding-domain hotspots the cited abstracts name (L536Q, Y537S/N/C, D538G): an ESR1
# change elsewhere is not counted as "already observed" for the ESR1 rows
ESR1_LBD = r"^ESR1 [A-Z]53[678][A-Z]$"
NOT_STATED = "not stated in the abstract"


def _e(source: str, says: str, cohort: str = "", frequency: str = "") -> dict:
    """One piece of evidence: the paper and what its abstract reports, nothing more."""
    return {"source": source, "says": says, "cohort": cohort,
            "frequency": frequency or NOT_STATED}


TABLE: list[dict] = [
    {"id": "esr1-ai", "event": "ESR1 ligand-binding-domain mutation", "genes": ["ESR1"],
     "under": ["aromatase inhibitor"], "needs": [], "subtype": HR_POS, "strength": 1,
     "observed_as": ESR1_LBD,
     "detect": CTDNA + "; every 2 to 3 months in SERENA-6. Or sequencing of a progressing lesion",
     "matters": "During aromatase-inhibitor therapy for metastatic disease, before progression: "
                "the setting in which PADA-1 and SERENA-6 looked for it",
     "civic": r"\bESR1 (?:[A-Z]\d+[A-Z]|Mutation)\b",
     "support": [
         _e("schiavon2015", "ESR1 mutations were found only in ER-positive patients previously "
            "exposed to an aromatase inhibitor, and were commonly selected by therapy for "
            "metastatic disease", "171 women with advanced breast cancer; ctDNA by digital PCR",
            "36.4% (16 of 44) when the aromatase inhibitor was first given for metastatic "
            "disease"),
         _e("fribbens2016", "Plasma ESR1 mutations were associated with acquired resistance to a "
            "prior aromatase inhibitor", "baseline plasma of two phase 3 trials (SoFEA, "
            "PALOMA-3)", "39.1% (63 of 161) in SoFEA; 25.3% (91 of 360) in PALOMA-3"),
         _e("toy2013", "Ligand-binding-domain mutations (Y537S, Y537N, D538G) drove ER-dependent "
            "transcription without hormone and reduced the efficacy of ER antagonists",
            "two cohorts of metastatic ER-positive tumors", "14 of 80"),
         _e("robinson2013", "Activating ligand-binding-domain mutations, all in patients treated "
            "with anti-estrogens and estrogen deprivation", "11 patients with ER-positive "
            "metastatic breast cancer (exome and transcriptome)", "6 of 11"),
         _e("bidard2022", "A rising ESR1 mutation in blood during first-line aromatase inhibitor "
            "plus palbociclib; the randomized switch to fulvestrant plus palbociclib before "
            "progression gave a median PFS of 11.9 vs 5.7 months", "randomized phase 3: 1,017 "
            "monitored, 172 randomized", "279 of 1,017 (27%) developed a rising ESR1 "
            "mutation"),
         _e("bidard2025", "ESR1 mutations are the most common mechanism of acquired resistance "
            "to an aromatase inhibitor plus a CDK4/6 inhibitor; found by ctDNA every 2 to 3 "
            "months, the randomized switch to camizestrant gave a median PFS of 16.0 vs 9.2 "
            "months", "randomized phase 3: 3,256 tested",
            "315 of 3,256 tested were eligible and randomized (not a mutation rate)"),
         _e("razavi2020", "ESR1 activating mutations expanded in number and allele fraction "
            "during alpelisib plus an aromatase inhibitor and were associated with resistance",
            "phase I/II trial, 44 evaluable patients, tumor and plasma"),
     ],
     "against": [
         _e("schiavon2015", "Rarely acquired during adjuvant aromatase-inhibitor therapy: 5.8% "
            "(3 of 52) when the first exposure was adjuvant, and 0 of 32 biopsies after "
            "progression on an adjuvant aromatase inhibitor (an independent cohort)") | {
             "applies": "adjuvant"},
         _e("bidard2022", "Monitoring and switching were studied during first-line aromatase "
            "inhibitor plus palbociclib for ER-positive, HER2-negative advanced disease; other "
            "settings are outside the trial"),
     ]},
    {"id": "esr1-serd", "event": "New ESR1 mutation (notably Y537S) under fulvestrant",
     "genes": ["ESR1"], "under": ["SERD"], "needs": [], "subtype": HR_POS, "strength": 2,
     "observed_as": ESR1_LBD,
     "detect": CTDNA + ", compared with an earlier sample",
     "matters": "At progression on fulvestrant, with or without a CDK4/6 inhibitor; in PALOMA-3 "
                "it was common in patients progressing later and uncommon in those progressing "
                "early",
     "civic": r"\bESR1 (?:[A-Z]\d+[A-Z]|Mutation)\b",
     "support": [
         _e("oleary2018", "Paired baseline and end-of-treatment ctDNA: new driver mutations "
            "emerged in PIK3CA and ESR1 after fulvestrant with or without palbociclib, in "
            "particular ESR1 Y537S; acquired mutations from fulvestrant are a major driver of "
            "resistance to the combination", "195 patients with paired ctDNA"),
     ],
     "against": [
         _e("oleary2018", "Evolution of driver mutations was uncommon in patients progressing "
            "early on palbociclib plus fulvestrant"),
     ]},
    {"id": "esr1-f404", "event": "ESR1 F404 mutation in cis with an activating ESR1 mutation",
     "genes": ["ESR1"], "under": ["SERD"], "needs": ["ESR1"], "subtype": HR_POS, "strength": 2,
     "observed_as": r"^ESR1 F404",
     "detect": "ctDNA covering ESR1 codon 404, with matched white-cell sequencing",
     "matters": "Under fulvestrant once an activating ESR1 mutation is present",
     "civic": r"\bESR1 F404",
     "support": [
         _e("kingston2024", "Novel ESR1 F404 mutations (F404L, F404I, F404V) were acquired in "
            "cis with activating ESR1 mutations; compound mutants were resistant to fulvestrant "
            "in cell models", "PlasmaMATCH cohort A: fulvestrant for activating ESR1 mutations "
            "in ctDNA; 69 patients with baseline and end-of-treatment ctDNA", "3 of 69 (4%)"),
     ],
     "against": []},
    {"id": "rb1-cdk46", "event": "RB1 loss-of-function mutation", "genes": ["RB1"],
     "under": ["CDK4/6 inhibitor"], "needs": [], "subtype": HR_POS, "strength": 2,
     "detect": CTDNA + "; or sequencing of a progressing lesion",
     "matters": "At progression on a CDK4/6 inhibitor (after 5, 8 and 13 months in Condorelli "
                "et al.'s three patients)",
     "civic": r"\bRB1 (?!PHOSPHORYLATION)",
     "support": [
         _e("oleary2018", "RB1 mutations emerged only in the palbociclib plus fulvestrant arm, "
            "in a minority of patients", "195 patients with paired ctDNA",
            "6 of 127 (4.7%)"),
         _e("condorelli2018", "Acquired RB1 mutations in ctDNA after a CDK4/6 inhibitor, absent "
            "from the specimens taken before it", "3 patients with metastatic breast cancer",
            "3 patients (a case series)"),
         _e("li2018", "Loss-of-function mutations in FAT1 and RB1 were linked to CDK4/6-inhibitor "
            "resistance", "348 ER-positive breast cancers treated with CDK4/6 inhibitors"),
         _e("wander2020", "RB1 loss was one of eight resistance mechanisms",
            "exome sequencing of 59 tumors exposed to CDK4/6 inhibitors",
            "the eight mechanisms together in 66% of resistant tumors"),
         _e("costa2020", "Some tumors acquired RB loss at progression",
            "serial biopsies and rapid autopsies, ribociclib plus letrozole"),
     ],
     "against": [
         _e("oleary2018", "A minority event: 4.7% of patients on palbociclib plus fulvestrant"),
     ]},
    {"id": "fat1-cdk46", "event": "FAT1 loss-of-function mutation", "genes": ["FAT1"],
     "under": ["CDK4/6 inhibitor"], "needs": [], "subtype": HR_POS, "strength": 3,
     "detect": "Sequencing of a progressing lesion with a panel that covers FAT1 (the TCGA "
               "driver panel in this app does not)",
     "matters": "At progression on a CDK4/6 inhibitor",
     "civic": r"\bFAT1\b",
     "support": [
         _e("li2018", "FAT1 loss raised CDK6 through the Hippo pathway (YAP and TAZ), and "
            "loss-of-function FAT1 mutations were linked to CDK4/6-inhibitor resistance",
            "348 ER-positive breast cancers treated with CDK4/6 inhibitors"),
     ],
     "against": []},
    {"id": "akt1-cdk46", "event": "Activating AKT1 alteration", "genes": ["AKT1"],
     "under": ["CDK4/6 inhibitor"], "needs": [], "subtype": HR_POS, "strength": 3,
     "detect": CTDNA + "; or sequencing of a progressing lesion",
     "matters": "At progression on a CDK4/6 inhibitor",
     "civic": r"\bAKT1\b",
     "support": [
         _e("wander2020", "Activating AKT1 alterations were among eight resistance mechanisms "
            "(with RB1 loss, activating RAS, AURKA, CCNE2, ERBB2 and FGFR2 alterations, and loss "
            "of ER expression)", "exome sequencing of 59 tumors exposed to CDK4/6 inhibitors",
            "the eight mechanisms together in 66% of resistant tumors"),
         _e("pearson2020", "AKT1 mutations were enriched in advanced compared with primary "
            "breast cancer", "ABC-Bio: 210 advanced breast cancer samples, 41-gene panel",
            "7.14% of samples"),
         _e("bertucci2019", "AKT1 was mutated more often in HR-positive, HER2-negative "
            "metastatic cancers than in early cancers (TCGA)", "617 metastatic breast cancers, "
            "381 HR-positive and HER2-negative"),
     ],
     "against": [
         _e("wander2020", "AKT1, RAS and AURKA were, to the authors' knowledge, not shown before "
            "as CDK4/6-inhibitor resistance mechanisms: one study so far"),
     ]},
    {"id": "pten-loss", "event": "PTEN loss", "genes": ["PTEN"],
     "under": ["CDK4/6 inhibitor", "PI3Kα inhibitor"], "needs": [], "subtype": HR_POS,
     "strength": 2,
     "detect": "ctDNA for PTEN mutations, with matched white-cell sequencing; a biopsy for PTEN "
               "copy loss or lost expression",
     "matters": "At progression on a CDK4/6 inhibitor or a PI3Kα inhibitor; Costa et al. "
                "describe one event that may limit both",
     "civic": r"\bPTEN (?!Expression)",
     "support": [
         _e("razavi2020", "Loss-of-function PTEN mutations in patients with resistance to "
            "alpelisib plus an aromatase inhibitor", "phase I/II trial, 44 evaluable patients, "
            "tumor and plasma", "25% of patients with resistance"),
         _e("costa2020", "Some tumors lost PTEN expression at progression; PTEN loss promoted "
            "CDK4/6-inhibitor resistance in models, and the authors note it also causes "
            "resistance to PI3Kα inhibitors (cross-resistance)",
            "serial biopsies and rapid autopsies, ribociclib plus letrozole"),
         _e("juric2015", "Under the PI3Kα inhibitor alpelisib (BYL719) all 14 metastatic "
            "sites of the index patient had PTEN copy loss, and refractory lesions had further, "
            "different PTEN alterations: convergent loss of PTEN", "an index patient (rapid "
            "autopsy, 14 sites) and 6 other patients on alpelisib",
            "acquired biallelic PTEN loss in 1 of the 6 others"),
     ],
     "against": [
         _e("juric2015", "A small series: seven patients"),
     ]},
    {"id": "brca-reversion", "event": "BRCA1/2 reversion (a secondary mutation restoring the "
     "protein)", "genes": ["BRCA1", "BRCA2"], "under": ["PARP inhibitor", "platinum"],
     "needs": ["BRCA1", "BRCA2"], "subtype": {}, "strength": 3,
     "detect": CTDNA + "; RAD51 foci on a biopsy for restored homologous recombination",
     "matters": "During PARP-inhibitor or platinum therapy: in 10 of Harvey-Jones et al.'s "
                "patients the reversion was in ctDNA before clinical progression",
     "civic": r"\bBRCA[12]\b",
     "support": [
         _e("harveyjones2024", "Reversions were the most prevalent resistance; reversions seen "
            "before the next treatment were associated with a shorter time to progression",
            "47 patients with BRCA1/2- or PALB2-mutant metastatic breast cancer progressing on "
            "HRD-targeted therapy; serial ctDNA", "60% of patients"),
         _e("waks2020", "After progression on a PARP inhibitor or platinum, half the patients "
            "had acquired at least one somatic reversion likely to restore BRCA1/2 protein, with "
            "RAD51 foci after resistance", "8 patients with BRCA1/2-mutant metastatic breast "
            "cancer, biopsies before and after resistance", "4 of 8 (50%)"),
     ],
     "against": [
         _e("harveyjones2024", "Non-reversion mechanisms (loss of TP53BP1, RIF1 or PAXIP1) "
            "were seen too, sometimes with a reversion"),
     ]},
    {"id": "erbb2-endocrine", "event": "Activating ERBB2 (HER2) mutation", "genes": ["ERBB2"],
     "under": list(ENDOCRINE), "needs": [], "subtype": HR_POS, "strength": 3,
     "detect": CTDNA + "; or sequencing of a progressing lesion",
     "matters": "After resistance to endocrine therapy; Nayar et al.'s models were also "
                "resistant to palbociclib",
     "civic": r"\bERBB2 (?!Amplification|Overexpression|Expression)[A-Z]",
     "support": [
         _e("pearson2020", "HER2 mutations were enriched in advanced compared with primary "
            "breast cancer", "ABC-Bio: 210 advanced breast cancer samples", "6.19% of samples"),
         _e("nayar2019", "Activating HER2 mutations in metastatic biopsies after resistance to "
            "aromatase inhibitors, tamoxifen or fulvestrant, absent from the treatment-naive "
            "primary in 4 of 5 and mutually exclusive with ESR1 mutations; resistant to "
            "tamoxifen, fulvestrant and palbociclib in cell models",
            "8 patients with ER-positive metastatic breast cancer", "8 patients (no rate given)"),
         _e("razavi2018", "Activating ERBB2 mutations were more than twice as common in "
            "endocrine-resistant tumors", "1,918 breast cancers, 692 previously exposed to "
            "hormonal therapy", "with the other MAPK and ER-regulator alterations, 22% of tumors"),
     ],
     "against": []},
    {"id": "nf1-endocrine", "event": "NF1 loss-of-function mutation", "genes": ["NF1"],
     "under": list(ENDOCRINE), "needs": [], "subtype": HR_POS, "strength": 3,
     "detect": CTDNA + "; or sequencing of a progressing lesion",
     "matters": "After resistance to endocrine therapy",
     "civic": r"\bNF1\b",
     "support": [
         _e("pearson2020", "NF1 mutations were frequently acquired in advanced disease, absent "
            "from the primary; NF1 loss caused endocrine resistance in ER-positive cell lines",
            "ABC-Bio: 210 advanced breast cancer samples, with matched primaries in a subset",
            "8.10% of samples"),
         _e("razavi2018", "NF1 loss-of-function mutations were more than twice as common in "
            "endocrine-resistant tumors and, with the other MAPK alterations, mutually exclusive "
            "with ESR1 mutations", "1,918 breast cancers, 692 previously exposed to hormonal "
            "therapy", "with the other MAPK and ER-regulator alterations, 22% of tumors"),
         _e("bertucci2019", "NF1 was mutated more often in HR-positive, HER2-negative metastatic "
            "cancers than in early cancers and was associated with poor outcome",
            "617 metastatic breast cancers, 381 HR-positive and HER2-negative"),
     ],
     "against": []},
    {"id": "fgfr-endocrine", "event": "FGFR pathway alteration (FGFR1, FGFR2 or FGF3 "
     "amplification; FGFR2 mutation)", "genes": ["FGFR1", "FGFR2", "FGF3"],
     "under": list(ENDOCRINE), "needs": [], "subtype": HR_POS, "strength": 3,
     "detect": "Sequencing of a progressing lesion (or ctDNA) that reports amplifications and "
               "FGFR2 mutations",
     "matters": "After resistance to ER-directed therapy; Mao et al. saw cross-resistance to "
                "palbociclib in cell models",
     "civic": r"\bFGFR[12]\b|\bFGF3\b",
     "support": [
         _e("mao2020", "FGFR pathway alterations in post-resistance biopsies, half of them "
            "acquired or enriched under ER-directed therapy", "paired pre- and post-resistance "
            "biopsies from 60 patients (exome)", "24 of 60 (40%) after resistance; 12 of the 24 "
            "acquired or enriched"),
         _e("wander2020", "Activating FGFR2 alterations were among eight CDK4/6-inhibitor "
            "resistance mechanisms", "exome sequencing of 59 tumors exposed to CDK4/6 "
            "inhibitors"),
     ],
     "against": []},
    {"id": "esr1-fusion", "event": "ESR1 fusion (a rearrangement that loses the ligand-binding "
     "domain)", "genes": ["ESR1"], "under": list(ENDOCRINE), "needs": [], "subtype": HR_POS,
     "strength": 3, "observed_as": None,  # no point mutation is a fusion
     "detect": "Sequencing able to call rearrangements (the authors used mate-pair, RNA and "
               "targeted DNA sequencing); a test for ESR1 point mutations alone does not report "
               "them",
     "matters": "Under endocrine therapy for metastatic disease; the authors suggest the "
                "enrichment may follow more aggressive endocrine therapy after ESR1 point "
                "mutations",
     "civic": r"\bESR1\b.*(?:Fusion|::)",
     "support": [
         _e("hartmaier2018", "ESR1 rearrangements were enriched in ER-positive metastatic "
            "disease and co-occurred with ESR1 missense mutations; the fusions lack the "
            "ligand-binding domain and were ligand-independent and hyperactive in vitro",
            "three cohorts, including 9,542 profiled solid tumors and 254 ctDNA samples",
            "at least 1% of metastatic breast cancers (a lower bound), at least 10 times "
            "enriched in ctDNA"),
     ],
     "against": []},
    {"id": "arid1a-endocrine", "event": "ARID1A inactivating mutation", "genes": ["ARID1A"],
     "under": list(ENDOCRINE), "needs": [], "subtype": HR_POS, "strength": 3,
     "detect": CTDNA + "; or sequencing of a progressing lesion",
     "matters": "After resistance to endocrine therapy; the mechanism was shown for ER "
                "degraders such as fulvestrant",
     "civic": r"\bARID1A\b",
     "support": [
         _e("xu2020", "ARID1A inactivating mutations were frequent in advanced "
            "endocrine-resistant ER-positive breast cancer; ARID1A loss caused resistance to ER "
            "degraders by a switch from ER-dependent luminal to ER-independent basal-like "
            "cells", "advanced endocrine-resistant ER-positive breast cancers and a CRISPR "
            "screen", "'high frequency' (no rate in the abstract)"),
         _e("yates2017", "Most distant metastases had acquired driver mutations not seen in "
            "the primary, including mutations inactivating SWI-SNF", "299 samples from 170 "
            "patients with relapsed or metastatic breast cancer"),
     ],
     "against": []},
    {"id": "er-loss", "event": "Loss of ER positivity in a metastasis (receptor conversion)",
     "genes": [], "under": [], "needs": [], "subtype": HR_POS, "strength": 2,
     "detect": "IHC for ER (and PR, HER2) on a biopsy of a new or progressing lesion",
     "matters": "At relapse or at a new lesion; the meta-analysis authors encourage reassessing "
                "receptor status in metastases",
     "civic": None,
     "support": [
         _e("schrijver2018", "ER positive-to-negative conversion between primary tumors and "
            "paired distant metastases", "meta-analysis of 39 studies",
            "22.5% (95% CI 16.4 to 30.0%)"),
         _e("aurilio2014", "Pooled ER shift from positive to negative between primary and "
            "recurrent tumors", "meta-analysis of 48 articles (4,200 tumors for ER)", "24%"),
         _e("wander2020", "Loss of ER expression was one of eight CDK4/6-inhibitor resistance "
            "mechanisms", "exome sequencing of 59 tumors exposed to CDK4/6 inhibitors"),
     ],
     "against": [
         _e("aurilio2014", "Heterogeneity between the studies was high (I² 91% for ER) and "
            "most were retrospective"),
     ]},
    {"id": "her2-change", "event": "HER2 status change in a metastasis (gain or loss)",
     "genes": [], "under": [], "needs": [], "subtype": {}, "strength": 2,
     "detect": "IHC and in situ hybridization for HER2 on a biopsy of a new lesion",
     "matters": "At relapse or at a new lesion",
     "civic": None,
     "support": [
         _e("schrijver2018", "HER2 conversion between primary tumors and paired distant "
            "metastases", "meta-analysis of 39 studies", "negative to positive 9.5% (95% CI 7.4 "
            "to 12.1%); positive to negative 21.3% (14.3 to 30.5%)"),
         _e("aurilio2014", "Pooled HER2 shifts between primary and recurrent tumors",
            "meta-analysis of 48 articles (2,987 tumors for HER2)",
            "negative to positive 5%; positive to negative 13%"),
     ],
     "against": [
         _e("schrijver2018", "Conversion rates varied widely between studies"),
     ]},
    {"id": "metastatic-drivers", "event": "Drivers mutated more often in metastatic than in "
     "early HR-positive, HER2-negative disease", "genes": ["TP53", "ESR1", "GATA3", "KMT2C",
                                                         "NCOR1", "AKT1", "NF1", "RIC8A", "RB1"],
     "under": [], "needs": [], "subtype": HR_POS_HER2_NEG, "strength": 3,
     "detect": CTDNA + "; or a biopsy of a metastasis with a panel covering these genes",
     "matters": "Whenever a later sample is sequenced: what it may show that the first did not",
     "civic": None,
     "support": [
         _e("bertucci2019", "Nine drivers (TP53, ESR1, GATA3, KMT2C, NCOR1, AKT1, NF1, RIC8A, "
            "RB1) were mutated more often in HR-positive, HER2-negative metastatic cancers than "
            "in early cancers (TCGA); TP53, RB1 and NF1 mutations were associated with poor "
            "outcome", "617 metastatic breast cancers, 381 HR-positive and HER2-negative"),
         _e("lefebvre2016", "ESR1 was both a driver and a metastatic gene; TSC1 and TSC2 "
            "mutations were more common in HR-positive, HER2-negative metastatic than early "
            "cancers (6% vs 0.7%)", "216 metastatic tumor-blood pairs (exome) against 772 TCGA "
            "primaries", "ESR1 mutated or amplified in 27 HR-positive, HER2-negative metastatic "
            "cancers (19%)"),
         _e("angus2019", "Tumor mutational burden doubled and six known drivers were mutated "
            "more often in metastatic than in primary breast cancer", "whole genomes of "
            "metastatic biopsies from 442 patients"),
         _e("yates2017", "Most distant metastases acquired drivers not seen in the primary, from "
            "a wider repertoire of cancer genes than early drivers", "299 samples from 170 "
            "patients with relapsed or metastatic breast cancer"),
     ],
     "against": [
         _e("bertucci2019", "A comparison with other patients' early cancers (TCGA), not with "
            "the same patients' primaries"),
     ]},
    {"id": "tp53-subtype", "event": "TP53 mutation: frequent in basal-like and HER2-amplified "
     "tumors", "genes": ["TP53"], "under": [], "needs": ["TP53"], "subtype": {}, "strength": 3,
     "detect": "IHC for ER, PR and HER2, or an expression subtype from a validated model, to "
               "place the tumor",
     "matters": "At diagnosis: the subtype decides which rows of this table apply",
     "civic": r"\bTP53\b",
     "support": [
         _e("dumay2013", "TP53 mutation frequency differs widely between subgroups: lowest in "
            "luminal, highest in basal tumors", "572 breast tumors",
            "luminal 26%, basal 88%"),
         _e("bertheau2013", "TP53 mutations by subtype; the first important event in luminal "
            "tumors, after PTEN loss in basal-like tumors", "a review",
            "luminal A 17%, luminal B 41%, HER2-amplified 50%, basal-like 88%"),
         _e("shah2012", "In triple-negative cancers TP53, PIK3CA and PTEN mutations seemed "
            "clonally dominant compared with other genes", "104 triple-negative breast cancers"),
         _e("silwalpandit2014", "TP53 mutations carried worse overall and breast-cancer-specific "
            "survival, independently in ER-positive cases", "1,420 tumors (METABRIC)",
            "28.3% of tumors"),
     ],
     "against": [
         _e("shah2012", "In some tumors the clonal frequencies of TP53, PIK3CA and PTEN "
            "mutations were incompatible with founder status"),
     ]},
    {"id": "pik3ca-her2", "event": "PIK3CA mutation in HER2-positive disease: fewer complete "
     "responses to HER2-targeted therapy", "genes": ["PIK3CA"], "under": [],
     "needs": ["PIK3CA"], "subtype": HER2_POS, "strength": 2,
     "detect": "HER2 status by IHC and in situ hybridization, which decides whether this row "
               "applies; the PIK3CA mutation itself is already observed by tumor sequencing",
     "matters": "Before or during neoadjuvant HER2-targeted therapy, the trials' setting",
     "civic": r"\bPIK3CA\b", "civic_therapy": r"trastuzumab|lapatinib|pertuzumab|neratinib",
     "support": [
         _e("majewski2015", "Activating PIK3CA mutations predicted fewer pathologic complete "
            "responses with neoadjuvant trastuzumab plus lapatinib (28.6% vs 53.1% in wild "
            "type)", "NeoALTTO, HER2-positive early breast cancer",
            "23% of HER2-positive tumors"),
         _e("loibl2014", "PIK3CA mutations were associated with a lower pathologic complete "
            "response rate (19.4% vs 32.8%; OR 0.49)", "504 HER2-positive tumors from "
            "GeparQuattro, GeparQuinto and GeparSixto", "21.4% of patients"),
     ],
     "against": [
         _e("loibl2014", "Disease-free and overall survival did not differ significantly "
            "between mutant and wild type"),
     ]},
]

# the rules this view applies, each with its source; stated once (VISION part two)
CONSTRAINTS = [
    {"rule": "Drivers do not revert here",
     "text": "An observed driver stays in the file. A later sample that misses it is read as "
             "another place, too little tumor DNA or another lineage, never as the mutation "
             "going away: Juric et al. 2015 found primary-tumor PIK3CA mutations no longer "
             "detected at progression in 2 of 7 patients. A BRCA1/2 reversion is a new "
             "secondary mutation, not the loss of the first.",
     "sources": ["juric2015", "waks2020"]},
    {"rule": "Metastases do not regress in the record",
     "text": "A metastatic site, once recorded, stays a site the disease reached, even after it "
             "responds: the set of sites only grows. A rule of this view, not a finding.",
     "sources": []},
    {"rule": "A section or one biopsy is not the tumor",
     "text": "A 2D section, or one biopsy, is one place at one time: multiregion sequencing "
             "found subclonal diversification with spatial patterns, and potentially targetable "
             "mutations that were subclonal in 13 of 50 primary breast cancers. A single biopsy "
             "is a snapshot.",
     "sources": ["yates2015", "gerstung2020"]},
    {"rule": "Blood is not only tumor",
     "text": "Most cell-free DNA mutations in patients with cancer (53.2%) had features of "
             "clonal hematopoiesis: a ctDNA variant needs matched white-cell sequencing before it "
             "counts as the tumor's.",
     "sources": ["razavi2019"]},
    {"rule": "Order is not fixed",
     "text": "The same drivers (PIK3CA, TP53, PTEN, BRCA2, MYC) arose early in some tumors and "
             "late in others; clonal order is read per tumor, as alternatives.",
     "sources": ["yates2015", "shah2012"]},
    {"rule": "A cohort's frequency is not this patient's probability",
     "text": "Every frequency below is what a cohort showed, under its own treatments and "
             "tests; none is a forecast for this patient. A rule of this view.",
     "sources": []},
]


def source(key: str) -> dict:
    cite, journal, pmid, doi, title = SOURCES[key]
    return {"key": key, "cite": cite, "journal": journal, "pmid": pmid, "doi": doi,
            "title": title, "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "doi_url": f"https://doi.org/{doi}"}


# ------------------------------------------------------------------------- what the file says

def _receptor(text: str, short: str, long: str) -> bool | None:
    m = re.search(rf"\b{short}\s*([+−-])", text) or re.search(
        rf"\b{long}[- ](positive|negative)", text, re.I)
    if not m:
        return None
    return m.group(1).lower() in ("+", "positive")


NAMES = {"HR": "hormone receptor", "HER2": "HER2"}
WORDS = {True: "positive", False: "negative", None: "not recorded"}
RECEPTOR_FACTS = {"HR": ("er", "pr", "hr"), "HER2": ("her2",)}  # the documents fields they read


def _documented(facts: list[dict]) -> dict:
    """"HR" and "HER2" -> {document id: (the statuses it states, its words)}, from the ER, PR,
    hormone-receptor and HER2 status facts of ``muffle.workbench.documents``. Positive or negative
    only: "equivocal", an IHC score or an ISH result is never turned into a status. A document
    states hormone-receptor positive when it states ER or PR positive, negative when it states
    both negative (or hormone receptors negative); ER or PR negative alone settles neither (no
    status, its words kept). One document can state both (two specimens, or a legend read as a
    result)."""
    out = {k: {} for k in NAMES}
    for doc in dict.fromkeys(f["doc"] for f in facts):
        mine = [f for f in facts if f["doc"] == doc and f["value"] in ("positive", "negative")]
        said = {(f["field"], f["value"]) for f in mine}
        states = {"HER2": {v == "positive" for k, v in said if k == "her2"},
                  "HR": {True} if said & {("er", "positive"), ("pr", "positive"),
                                          ("hr", "positive")} else set()}
        if ("hr", "negative") in said or {("er", "negative"), ("pr", "negative")} <= said:
            states["HR"].add(False)
        for k, fields in RECEPTOR_FACTS.items():
            stated = [f"{f['label']} {f['value']}" for f in mine if f["field"] in fields]
            if stated:
                out[k][doc] = (states[k], ", ".join(stated))
    return out


def _docs(ids) -> str:
    return ("document " if len(ids) == 1 else "documents ") + ", ".join(ids)


def _rules_note() -> str:
    """How far a document's status can be trusted: the rules' precision on held-out reports."""
    path = documents.DOCS_DIR / "validation.json"
    if not path.exists():
        return f"Document statuses are read by the {documents.RULES_VERSION}."
    test = json.loads(path.read_text())["sets"]["test"]
    p = {r["field"]: r["precision"] for r in test["fields"]}
    return (f"Document statuses are read by the {documents.RULES_VERSION}, precision on "
            f"{test['patients']} held-out TCGA reports: ER {p['er']:.0%}, PR {p['pr']:.0%}, "
            f"HER2 {p['her2']:.0%}. A rule match is not a pathologist's read: the sentence is in "
            "the Clinical documents workbench.")


def _receptor_status(record: dict, said: dict) -> tuple[dict, dict, list[str]]:
    """Each receptor status with where it comes from: the record's own when it has one (a
    document stating otherwise is named, never outvoted), else the documents' when they agree,
    else unknown (documents that disagree are named, none is picked)."""
    status, origin, notes = {}, {}, []
    for k, name in NAMES.items():
        docs, label = said[k], name[0].upper() + name[1:]
        states = {s for st, _ in docs.values() for s in st}
        settling = [d for d, (st, _) in docs.items() if st]
        other = [d for d in settling if record[k] is not None and docs[d][0] - {record[k]}]
        words = "; ".join(f"{d} states {docs[d][1]}" for d in other or docs)
        if record[k] is not None:
            status[k], origin[k] = record[k], "in the record"
            if other:
                origin[k] += (f" ({_docs(other)} "
                              f"{'states' if len(other) == 1 else 'state'} otherwise)")
                notes.append(f"{label} status: the record says {WORDS[record[k]]}; {words}. The "
                             "record's status is used; which is right is not settled here.")
        elif len(states) == 1:
            status[k], origin[k] = states.pop(), f"observed in {_docs(settling)}"
            notes.append(f"{label} status {WORDS[status[k]]}, observed: {words}.")
        elif states:
            status[k], origin[k] = None, f"conflicting statuses in {_docs(settling)}"
            notes.append(f"{label} status: conflicting statuses, {words}. None is picked; rows "
                         "that need it are shown as conditional.")
        else:
            status[k], origin[k] = None, f"not settled by {_docs(docs)}" if docs else ""
            if docs:
                notes.append(f"{label} status: {words}, which settles neither (positive needs "
                             "ER or PR positive, negative needs both negative).")
    return status, origin, notes + ([_rules_note()] if notes else [])


def context(pf: PatientFile, version: int | None = None) -> dict:
    """What the file says as of report version ``version`` (the latest when None): receptor
    status with its source (``receptor_from``; ``receptor_notes`` give what each document states
    and every disagreement), observed drivers, recorded treatments with their class and setting,
    the first recorded metastatic site. All observed; nothing inferred."""
    i = len(pf.versions) - 1 if version is None else version
    vs = pf.versions[: i + 1]
    dx = dict(vs[-1].observed).get("Diagnosis", "") + " " + pf.diagnosis
    record = {"HR": _receptor(dx, "HR", "hormone[- ]receptor"),
              "HER2": _receptor(dx, "HER2", "HER2")}
    said = _documented(documents.facts(documents.file_documents(pf, i)))
    receptors, receptor_from, receptor_notes = _receptor_status(record, said)
    drivers = {}
    for t in sequencing_tests(pf, i):
        for v in t.details.get("variants", []):
            drivers.setdefault(v.split()[0], (v, t.month))
    mets = [a.month for v in vs for a in v.alerts if a.what.startswith("New metastatic site")]
    first_met = min(mets) if mets else None
    treatments = []
    for v in vs:
        for agent in v.treatments:
            cls = DRUG_CLASS.get(agent)
            setting = ("no metastatic site recorded" if first_met is None or v.month is None
                       else "before the first recorded metastatic site"
                       if v.month < first_met else "after the first recorded metastatic site")
            treatments.append({"agent": agent, "class": cls, "month": v.month,
                               "setting": setting})
    return {"version": i, "month": vs[-1].month, "receptors": receptors,
            "receptor_from": receptor_from, "receptor_notes": receptor_notes, "drivers": drivers,
            "treatments": treatments, "first_met": first_met, "kind": pf.kind}


def receptor_text(receptors: dict, sources: dict | None = None, keys=NAMES) -> str:
    """"hormone receptor positive in the record, HER2 not recorded": each status (of ``keys``),
    with where it comes from when ``sources`` (``context``'s "receptor_from") is given."""
    out = []
    for k in keys:
        src = (sources or {}).get(k, "")
        word = "unknown:" if receptors[k] is None and src else WORDS[receptors[k]]
        out.append(f"{NAMES[k]} {word} {src}".strip())
    return ", ".join(out)


def _subtype(want: dict, receptors: dict) -> str:
    """"met", "not met" or "unknown" (a status the file doesn't record)."""
    if not want:
        return "none required"
    states = [receptors.get(k) for k in want]
    if any(s is not None and s != want[k] for k, s in zip(want, states, strict=True)):
        return "not met"
    return "met" if all(s is not None for s in states) else "unknown"


def _wanted(want: dict) -> str:
    words = {"HR": "hormone-receptor", "HER2": "HER2"}
    return ", ".join(f"{words[k]}-{'positive' if v else 'negative'}" for k, v in want.items())


# --------------------------------------------------------------------------- hypothesis set

@per_file
def hypothesis_set(pf: PatientFile, version: int | None = None, lookup=None) -> dict:
    """"What to watch next" for one file as of a report version: the table rows its observed
    drivers, receptor status and recorded treatments raise, ranked, each labeled hypothesis
    with its supporting and non-supporting evidence, frequency and cohort, the test that would
    detect the event and when it would matter. ``lookup(row)`` returns CIViC items for a row's
    event (``civic_items``); without it the items are None (not loaded here). Rows the file
    does not raise are listed in ``not_raised`` with the reason. Never advice."""
    ctx = context(pf, version)
    rec, drivers, rx = ctx["receptors"], ctx["drivers"], ctx["treatments"]
    src = ctx["receptor_from"]
    notes = []
    if not rx:
        notes.append("No treatment recorded as of this version." if pf.kind == "synthetic"
                     else "No treatment recorded; these hypotheses assume none.")
    if ctx["receptor_notes"]:
        notes.append(" ".join(ctx["receptor_notes"]))
    if None in rec.values():
        notes.append(f"Receptor status in this file: {receptor_text(rec, src)}; rows that need "
                     "it are shown as conditional.")
    ranked, skipped = [], []
    for n, row in enumerate(TABLE):
        sub = _subtype(row["subtype"], rec)
        under = [t for t in rx if t["class"] in row["under"]]
        need = [g for g in row["needs"] if g in drivers]
        present = _present(row, drivers)
        reason = None
        if sub == "not met":
            reason = (f"needs {_wanted(row['subtype'])} disease; this file: "
                      f"{receptor_text(rec, src, row['subtype'])}")
        elif row["needs"] and not need:
            reason = f"needs an observed {' or '.join(row['needs'])} alteration; none in this file"
        elif row["under"] and not under and not present:
            reason = (f"needs a recorded {' or '.join(row['under'])}; "
                      + ("no treatment recorded, and none is assumed" if not rx else
                         "none of this file's treatments is one"))
        if reason:
            skipped.append({"id": row["id"], "event": row["event"], "reason": reason})
            continue
        why = [f"{t['agent']} ({t['class']}) recorded from month {t['month']}, {t['setting']}"
               for t in under]
        why += [f"observed {drivers[g][0]}" + ("" if drivers[g][1] is None else
                                              f" (month {drivers[g][1]})")
                for g in dict.fromkeys(need + present)]
        why += [f"{_wanted({k: want})} {src[k]}" if rec[k] is not None else
                f"applies if {_wanted({k: want})}: {src[k] or 'not recorded in this file'}"
                for k, want in row["subtype"].items()]
        status = (f"already observed: {', '.join(drivers[g][0] for g in present)}; this table "
                  "does not judge whether the exact change is the event described"
                  if present else "not observed in this file")
        support = [{**e, "source": source(e["source"])} for e in row["support"]]
        against = [{**a, "source": source(a["source"]), "applies_here": _applies(a, under)}
                   for a in row["against"]]
        lead = next((e for e in support if e["frequency"] != NOT_STATED), support[0])
        score = 2 * bool(under) + bool(need or present) + (sub == "met")
        latest = max((t["month"] for t in under if t["month"] is not None), default=-999)
        ranked.append(((-score, -latest, row["strength"], n), {
            "id": row["id"], "event": row["event"], "genes": row["genes"],
            "evidence": HYPOTHESIS, "status": status,
            "why": why or ["applies to any breast cancer in this table"],
            "support": support, "against": against,
            "frequency": f"{lead['frequency']} · {lead['source']['cite']}, {lead['cohort']}",
            "detect": row["detect"], "matters": row["matters"],
            "strength": STRENGTH[row["strength"]],
            "civic": lookup(row) if lookup else None,
            "key": finding_key(pf, "evolution", row["event"], support[0]["source"]["pmid"])}))
    items = [item for _, item in sorted(ranked, key=lambda r: r[0])]
    return {"items": items, "not_raised": skipped, "notes": notes, "context": ctx,
            "rule": "Ordered by how much of the row's context this file shows (a recorded "
                    "treatment of the row's class counts most, then an observed driver, then "
                    "the receptor status), then by the most recent matching treatment, then by "
                    "the strength of the evidence: a fixed ordering rule, not a probability.",
            "evidence": HYPOTHESIS, "use": "what to watch, for clinician review; never advice"}


def _present(row: dict, drivers: dict) -> list[str]:
    """The row's genes whose observed change counts as the event itself: any change unless the
    row names one (``observed_as``, a regex on "GENE CHANGE"; None: never, e.g. a fusion)."""
    pattern = row.get("observed_as", "")
    return [] if pattern is None else [g for g in row["genes"] if g in drivers
                                       and re.search(pattern, drivers[g][0])]


def _applies(against: dict, under: list[dict]) -> bool | None:
    """Whether a setting-specific caveat applies to this file: an "adjuvant" caveat applies
    when every matching treatment began before the first recorded metastatic site."""
    if against.get("applies") != "adjuvant":
        return None
    return bool(under) and all(t["setting"].startswith("before") for t in under)


def civic_items(row: dict, table, k: int = 3) -> dict:
    """CIViC's accepted predictive items in breast cancer whose molecular profile matches the
    row's event (``row["civic"]``, a regex; None: no CIViC event to match), strongest level
    first: {"items": first k, "total": all matches}. Evidence for clinician review."""
    if table is None or table.empty or not row.get("civic"):
        return {"items": [], "total": 0}
    t = table[table["disease"].str.contains("breast", case=False, regex=False)
              & table["molecular_profile"].str.contains(row["civic"], regex=True)]
    if row.get("civic_therapy"):
        t = t[t["therapies"].str.contains(row["civic_therapy"], case=False, regex=True)]
    t = t.assign(_level=t["evidence_level"].map(lambda v: "ABCDE".find(v) % 6))
    t = t.sort_values(["_level", "molecular_profile"])
    return {"total": len(t), "items": [
        {"molecular_profile": r["molecular_profile"], "therapies": r["therapies"] or "none named",
         "evidence_level": r["evidence_level"], "significance": r["significance"],
         "direction": r["evidence_direction"], "citation": r["citation"],
         "url": r["evidence_civic_url"]} for _, r in t.head(k).iterrows()]}


# ------------------------------------------------------------------------------- events

LANES = ["Diagnosis", "Treatment", "Imaging", "Sequencing", "Tumor marker"]


def events(pf: PatientFile, version: int | None = None) -> list[dict]:
    """The record's dated events up to a version, one row per thing that happened, all
    observed: diagnosis, treatment starts, imaging (progression and new sites flagged),
    sequencing, tumor-marker values (rises flagged by the record's alerts). A TCGA file has no
    dated event."""
    i = len(pf.versions) - 1 if version is None else version
    out = []
    for v in pf.versions[: i + 1]:
        if v.month is None:
            continue
        flags = [a.what for a in v.alerts]
        for t in v.tests:
            lane = {"Pathology report": "Diagnosis", "Imaging": "Imaging",
                    "Sequencing": "Sequencing", "Lab": "Tumor marker"}.get(t.kind)
            if lane is None:
                continue
            hits = [f for f in flags if (lane == "Imaging" and ("Progression" in f
                                                                 or "metastatic site" in f))
                    or (lane == "Tumor marker" and f.startswith(t.name))]
            label = {"Diagnosis": "diagnosis", "Sequencing": t.result,
                     "Tumor marker": f"{t.result} (rise)" if hits else "",
                     "Imaging": "; ".join("progression" if f.startswith("Progression")
                                          else f.split(": ", 1)[-1] for f in hits)}[lane]
            out.append({"month": v.month, "lane": lane, "what": f"{t.name}: {t.result}",
                        "label": label, "flag": "; ".join(hits),
                        "kind": "alert" if hits else lane.split()[-1].lower(),
                        "evidence": OBSERVED, "source": v.label})
        if v.treatments:  # one point per treatment event: drugs started together stay together
            out.append({"month": v.month, "lane": "Treatment",
                        "what": "starts " + " + ".join(v.treatments),
                        "label": " + ".join(v.treatments),
                        "flag": ", ".join(dict.fromkeys(DRUG_CLASS.get(a, "other")
                                                        for a in v.treatments)),
                        "kind": "treatment", "evidence": OBSERVED, "source": v.label})
    return out


# ------------------------------------------------------------------- clonal order (inference)

def wilson(alt: int, depth: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval of an allele fraction from read counts."""
    if depth <= 0:
        return (0.0, 1.0)
    p = alt / depth
    half = z * math.sqrt(p * (1 - p) / depth + z * z / (4 * depth * depth)) / (1 + z * z / depth)
    mid = (p + z * z / (2 * depth)) / (1 + z * z / depth)
    return (max(0.0, mid - half), min(1.0, mid + half))


def load_vaf(path: Path = VAF_JSON) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def clonal(variants: list[dict]) -> dict:
    """Clonal order from one sample's allele fractions, as alternatives (model inference).

    ``variants``: [{"variant", "alt", "depth", "copies"}]; ``copies`` is the gene's total copy
    number in the tumor (None: unknown, two assumed). Assumes each mutation sits on one copy of
    its gene. Then a tumor-cell fraction is at least copies x allele fraction whatever the
    purity, so two variants whose lower bounds sum past 1 must share cells: the higher one came
    first and the other arose inside its lineage. Otherwise they may also sit in separate
    subclones. Overlapping 95% intervals cannot be ordered; different copy numbers at the two
    genes break the comparison. Purity is unknown, so no variant is called clonal."""
    vs = []
    for v in variants:
        lo, hi = wilson(v["alt"], v["depth"])
        n = v.get("copies")
        vaf = v["alt"] / v["depth"] if v["depth"] else 0.0
        bound = (n or 2) * vaf
        vs.append({**v, "vaf": vaf, "lo": lo, "hi": hi, "copies_used": n or 2,
                   "cells_at_least": min(1.0, bound),
                   "one_copy_fits": bound <= 1 or (n or 2) * lo <= 1})
    vs.sort(key=lambda v: -v["vaf"])
    pairs = []
    for a_i, a in enumerate(vs):
        for b in vs[a_i + 1:]:
            if a["copies"] and b["copies"] and a["copies"] != b["copies"]:
                rel, alts = "copy number differs", [
                    f"{a['variant']} first", f"{b['variant']} first", "separate subclones"]
                why = (f"{a['copies']:g} vs {b['copies']:g} copies: allele fractions do not order "
                       "these two")
            elif a["lo"] <= b["hi"]:
                rel, alts = "indistinguishable", [
                    "the same clone", f"{a['variant']} first", f"{b['variant']} first"]
                why = "their 95% intervals overlap at this depth"
            elif not (a["one_copy_fits"] and b["one_copy_fits"]):
                rel, alts = "ordered, nesting open", [
                    f"{a['variant']} first, {b['variant']} inside its lineage",
                    "separate subclones"]
                why = "an allele fraction too high for one copy: the one-copy assumption fails"
            elif a["copies_used"] * a["lo"] + b["copies_used"] * b["lo"] > 1:
                rel, alts = "nested", [f"{a['variant']} first, {b['variant']} inside its lineage"]
                why = ("their cell fractions must overlap (lower bounds sum past 100% of cells), "
                       "so one lineage carries both")
            else:
                rel, alts = "ordered, nesting open", [
                    f"{a['variant']} first, {b['variant']} inside its lineage",
                    "separate subclones"]
                why = "room for both in separate cells, so a branch is possible"
            pairs.append({"a": a["variant"], "b": b["variant"], "relation": rel,
                          "alternatives": alts, "why": why})
    orderings = []
    if len(vs) > 1:
        groups = [[vs[0]]]
        for v in vs[1:]:
            if groups[-1][-1]["lo"] <= v["hi"]:  # overlaps the previous one: can't be ordered
                groups[-1].append(v)
            else:
                groups.append([v])
        orderings.append("Linear, by allele fraction: " + " → ".join(
            " = ".join(v["variant"] for v in g) for g in groups)
            + " (each arising in a cell carrying the ones before; = cannot be ordered; "
              "meaningful only between genes with the same copy number)")
        orderings += [f"Either order: {p['a']} and {p['b']}, or separate subclones ({p['why']})"
                      if p["relation"] == "copy number differs" else
                      f"Branching: {p['a']} and {p['b']} in separate subclones"
                      for p in pairs if "separate subclones" in p["alternatives"]]
    return {"evidence": INFERENCE, "variants": vs, "pairs": pairs, "orderings": orderings,
            "assumptions": "each mutation on one copy of its gene; copy number from the gene "
                           "level (two when unknown); purity unknown, so only lower bounds on "
                           "cell fractions; one sample, one place and time"}


def clonal_panel(pf: PatientFile, version: int | None = None, vaf: dict | None = None) -> dict:
    """The clonal panel for a file: the computed order where allele fractions exist, else what
    is missing, in words (never an empty chart)."""
    vaf = load_vaf() if vaf is None else vaf
    seq = sequencing_tests(pf, len(pf.versions) - 1 if version is None else version)
    if not seq:
        return {"status": "not sequenced: no driver call to order"}
    if pf.kind == "synthetic":
        return {"status": "allele fraction not available in these calls: the record names the "
                          "variant only"}
    case = vaf.get("cases", {}).get(pf.id.removeprefix("Case "))
    names = [v for t in seq for v in t.details.get("variants", [])]
    if not names:
        return {"status": "sequenced: no driver call in the panel, nothing to order"}
    if case is None or not case.get("variants"):
        return {"status": "allele fraction not available in these calls"}
    known = [v for v in case["variants"] if v.get("depth")]
    if not known:
        return {"status": "allele fraction not available in these calls"}
    out = clonal(known)
    out["status"] = "allele fraction only, purity unknown"
    out["source"] = vaf.get("source", "")
    out["missing"] = [n for n in names if n not in {v["variant"] for v in known}]
    return out


# ------------------------------------------------------------------------------- export

def report_markdown(pf: PatientFile, version: int | None, hs: dict, panel: dict,
                    trials: list[dict], trials_note: str, reviews: dict | None = None) -> str:
    """The Evolution view as one Markdown page: constraints, what to watch next with sources,
    rows not raised, the clonal panel, trials and this view's review marks."""
    i = len(pf.versions) - 1 if version is None else version
    v, reviews = pf.versions[i], reviews or {}
    out = [f"# {pf.id} · tumor evolution and treatment evidence · {v.label}", "",
           f"_{pf.title} · {pf.diagnosis}_", "", f"_{DISCLAIMER}_", ""]
    if pf.kind == "synthetic":
        out += [f"> {pf.note}", ""]
    out += [f"## What to watch next [{HYPOTHESIS}; for clinician review, never advice]", "",
            hs["rule"], ""] + [f"- {n}" for n in hs["notes"]]
    for n, it in enumerate(hs["items"], 1):
        out += ["", f"### {n}. {it['event']}", f"- Status: {it['status']}",
                f"- Why it is listed: {'; '.join(it['why'])}",
                f"- Frequency: {it['frequency']}", f"- Would be detected by: {it['detect']}",
                f"- When it would matter: {it['matters']}",
                f"- Evidence: {it['strength']}"]
        out += [f"  - for: {e['says']} ({e['source']['cite']}, {e['source']['journal']}; "
                f"PMID {e['source']['pmid']}, doi:{e['source']['doi']})" for e in it["support"]]
        out += [f"  - against or limits: {e['says']} ({e['source']['cite']}; PMID "
                f"{e['source']['pmid']})" + (" [applies to this file]" if e["applies_here"]
                                             else "") for e in it["against"]]
        civ = it["civic"]
        if civ is not None:
            out += [f"  - CIViC ({civ['total']} items): " + "; ".join(
                f"{c['molecular_profile']} · {c['therapies']} · level {c['evidence_level']} · "
                f"{c['significance']} · {c['url']}" for c in civ["items"]) if civ["items"]
                else "  - CIViC: no item for this event in breast cancer"]
    out += ["", "## Rows not raised for this file"] + (
        [f"- {s['event']}: {s['reason']}" for s in hs["not_raised"]] or ["- none"])
    out += ["", f"## Clonal order [{INFERENCE}]", f"- {panel['status']}"]
    for c in panel.get("variants", []):
        out.append(f"- {c['variant']}: allele fraction {c['vaf']:.2f} (95% CI {c['lo']:.2f} to "
                   f"{c['hi']:.2f}; {c['alt']} of {c['depth']} reads); {c['copies_used']:g} "
                   f"copies; at least {c['cells_at_least']:.0%} of tumor cells if on one copy")
    out += [f"- {o}" for o in panel.get("orderings", [])]
    if panel.get("assumptions"):
        out.append(f"- Assumptions: {panel['assumptions']}")
    out += ["", "## Trials that mention this patient's observed markers "
            "(for clinician review; eligibility is not assessed here)", f"_{trials_note}_", ""]
    out += [f"- {t['nct']} · {t['title']} · {t['phase']} · {t['status']} · {t['mentions']} · "
            f"https://clinicaltrials.gov/study/{t['nct']}" for t in trials] or ["- none"]
    out += ["", "## Constraints this view applies"] + [
        f"- {c['rule']}: {c['text']}" + (" (" + "; ".join(
            f"{source(s)['cite']}, PMID {source(s)['pmid']}" for s in c["sources"]) + ")"
            if c["sources"] else "") for c in CONSTRAINTS]
    marks = [r for k, r in reviews.items() if k.startswith(f"{pf.id}|evolution|")]
    out += ["", "## Review marks"] + ([f"- {r['what']}: {r['mark']} ({r['by'] or 'no initials'}"
                                       f", {r['at']})" for r in marks] or ["- none"])
    out += ["", f"Table checked against PubMed on {VERIFIED}; frequencies are cohort figures, "
            "not this patient's probability.", ""]
    return "\n".join(out)


# --------------------------------------------- the workbench contract (docs/WORKBENCHES.md §1)

def _raised(item: dict) -> bool:
    """A row this file raises itself (a recorded treatment or an observed driver), not one that
    applies to any breast cancer."""
    return any("recorded from month" in w or w.startswith("observed") for w in item["why"])


@per_file
def summary(pf: PatientFile, version: int | None = None) -> dict:
    """The top hypothesis of what to watch next, with why this file raises it."""
    hs = hypothesis_set(pf, version)
    if not hs["items"]:
        return {"workbench": "evolution", "title": "Evolution", "cards": [],
                "note": "no row of the evolution table is raised by this file"}
    it = hs["items"][0]
    return {"workbench": "evolution", "title": "Evolution", "note": None, "cards": [card(
        "What to watch next", f"{it['event']}: {'; '.join(it['why'])}", HYPOTHESIS,
        "this file's recorded treatments, drivers and receptor status",
        f"a cited table of {len(TABLE)} rows (PubMed checked {VERIFIED}), ranked by a fixed "
        f"rule; strongest support: {it['strength']}",
        f"none: a hypothesis to watch, never advice; detect with {it['detect']}", "weak",
        ("Evolution",))]}


@per_file
def queue(pf: PatientFile, version: int | None = None, k: int = 3,
          hs: dict | None = None) -> list[dict]:
    """The first ``k`` rows the file raises itself, as hypotheses worth a look (consequence 1,
    trust weak); the Evolution view holds the rest and the rows that apply to any patient.
    ``hs``: the file's ``hypothesis_set`` when the caller has it already."""
    out = []
    hs = hypothesis_set(pf, version) if hs is None else hs
    for it in [it for it in hs["items"] if _raised(it)][:k]:
        out.append(look(
            it["id"], f"Watch for {it['event']}", f"{'; '.join(it['why'])}; when it would "
            f"matter: {it['matters']}; detect with {it['detect']}", HYPOTHESIS, "weak", 1,
            ("Evolution",), source="the Evolution view's cited table", key=it["key"],
            focus={"evolution": it["key"]},
            threshold=f"none: a hypothesis ({it['strength']}); frequency {it['frequency']}"))
    return out
