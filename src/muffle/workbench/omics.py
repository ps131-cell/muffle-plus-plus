"""Expression, methylation and protein workbench (docs/WORKBENCHES.md §7): pure functions.

Two halves, both plain arithmetic:

* Offline, on the local TCGA-BRCA files (``scripts/omics_scores.py``): the PAM50 nearest-centroid
  call, cohort z-scored gene-set scores, cutoffs calibrated against recorded IHC, and agreement
  with published calls. The script ships only derived numbers (``app/omics_scores.json``).
* In the app (``app/workbenches/omics.py``): a feature's cohort percentile from the shipped
  quantiles, the receptor consistency lines, the layer cards, search and the exports.

Round 2 adds the protein pathway scores (RPPA, Akbani et al. 2014), promoter methylation of six
genes with the hypermethylation index, the immune and stromal signatures and the immune picture
read across RNA, protein and the slides.

Every finding keeps its evidence type: an IHC status, a measured value or a promoter beta is
observed; a subtype call, a pathway or immune score or a layer's contribution is a model
inference; the CpG island hypermethylation index is a hypothesis. Thresholds name their source
(guideline, literature, calibrated, placeholder).
"""

from __future__ import annotations

import csv
import io
import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from muffle.data.preprocess import zscore
from muffle.demo import ordinal
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import ASSAYS, card, finding_key, look

IMPLEMENTED, VALIDATED, PLANNED = "implemented", "experimentally validated", "planned"
AGREE, DISAGREE, NO_COMPARISON = "agree", "disagree", "nothing to compare"

SUBTYPES = {"LumA": "Luminal A", "LumB": "Luminal B", "Her2": "HER2-enriched",
            "Basal": "Basal-like", "Normal": "Normal-like"}
# genefu's centroid table uses the symbols of 2009; GENCODE v36 names these genes differently
PAM50_ALIASES = {"CDCA1": "NUF2", "KNTC2": "NDC80", "ORC6L": "ORC6"}
# Parker et al. 2009: the proliferation score is the mean expression of these 11 PAM50 genes
PROLIFERATION = ("BIRC5", "CCNB1", "CDC20", "NUF2", "CEP55", "NDC80", "MKI67", "PTTG1", "RRM2",
                 "TYMS", "UBE2C")
CYTOLYTIC = ("GZMA", "PRF1")  # Rooney et al. 2015: immune cytolytic activity
# receptor -> (gene, RPPA antibody in the TCGA protein file)
RECEPTORS = {"ER": ("ESR1", "ERALPHA"), "PR": ("PGR", "PR"), "HER2": ("ERBB2", "HER2")}
ANTIBODY_NAMES = {"ERALPHA": "ER-alpha", "PR": "PR", "HER2": "HER2"}

REFERENCES = {
    "pam50": "Parker JS et al. Supervised risk predictor of breast cancer based on intrinsic "
             "subtypes. J Clin Oncol 2009;27:1160-7. doi:10.1200/JCO.2008.18.1370",
    "genefu": "Gendoo DMA et al. Genefu: an R/Bioconductor package for computation of gene "
              "expression-based signatures in breast cancer. Bioinformatics 2016;32:1097-9. "
              "doi:10.1093/bioinformatics/btv693 (centroids: genefu data/pam50.rda, Artistic-2.0)",
    "hallmark": "Liberzon A et al. The Molecular Signatures Database Hallmark gene set "
                "collection. Cell Syst 2015;1:417-25. doi:10.1016/j.cels.2015.12.004 (MSigDB "
                "v2025.1.Hs, CC BY 4.0)",
    "zscore": "Lee E et al. Inferring pathway activity toward precise disease classification. "
              "PLoS Comput Biol 2008;4:e1000217. doi:10.1371/journal.pcbi.1000217 (z-score "
              "averaging)",
    "cytolytic": "Rooney MS et al. Molecular and genetic properties of tumors associated with "
                 "local immune cytolytic activity. Cell 2015;160:48-61. "
                 "doi:10.1016/j.cell.2014.12.033",
    "published": "TCGA PanCanAtlas clinical data in cBioPortal (study brca_tcga_pan_can_atlas_2018,"
                 " column SUBTYPE; Hoadley KA et al. Cell 2018;173:291-304, "
                 "doi:10.1016/j.cell.2018.03.022)",
    "ihc": "TCGA clinical data (GDAC Firehose 2016-01-28) in cBioPortal (study brca_tcga): "
           "ER_STATUS_BY_IHC, PR_STATUS_BY_IHC, IHC_HER2, HER2_FISH_STATUS",
    "her2": "ASCO/CAP HER2 testing guideline (Wolff AC et al. J Clin Oncol 2018;36:2105-22, "
            "doi:10.1200/JCO.2018.77.8738): IHC 3+ positive, 0 or 1+ negative, 2+ equivocal and "
            "settled by in situ hybridization",
    "akbani": "Akbani R et al. A pan-cancer proteomic perspective on The Cancer Genome Atlas. Nat "
              "Commun 2014;5:3887. doi:10.1038/ncomms4887 (RPPA pathway scores: Supplementary "
              "Table 13, the members and their signs)",
    "manifest": "Illumina HumanMethylation450 v1.2 manifest (humanmethylation450_15017482_v1-2."
                "csv): UCSC_RefGene_Name, _Accession and _Group (TSS200 and 1stExon = a gene's "
                "core promoter; TSS1500, TSS200, 5'UTR, 1stExon = any promoter) and "
                "Relation_to_UCSC_CpG_Island",
    "estimate": "Yoshihara K et al. Inferring tumour purity and stromal and immune cell admixture "
                "from expression data. Nat Commun 2013;4:2612. doi:10.1038/ncomms3612 "
                "(Supplementary Data 1: the 141-gene stromal and immune signatures; the ESTIMATE "
                "package itself is not used)",
    "bcimp": "Fang F et al. Breast cancer methylomes establish an epigenomic foundation for "
             "metastasis. Sci Transl Med 2011;3:75ra25. doi:10.1126/scitranslmed.3001875 (the "
             "breast CpG island methylator phenotype, B-CIMP)",
}

# --- round 2: protein pathways (RPPA), promoter methylation, immune and stromal ----------------

# Akbani et al. 2014, Supplementary Table 13: each RPPA pathway score's antibodies with the sign
# they enter with (-1: a negative regulator, subtracted). Names as the Xena GDC hub's RPPA file
# spells them (Akbani's HER3PY1298 is this file's HER3_pY1289). "map" is the genomics workbench's
# pathway-map name (muffle.workbench.genome.PATHWAYS) the score sits beside; "also" lists
# antibodies of the same proteins on the array that are shown but not in the score.
RPPA_PATHWAYS = {
    "PI3K/AKT": {"map": "PI3K / AKT / mTOR", "also": ("AKT", "PI3KP110ALPHA", "PI3KP85"),
                 "members": {"AKT_pS473": 1, "AKT_pT308": 1, "GSK3ALPHABETA_pS21S9": 1,
                             "GSK3_pS9": 1, "P27_pT157": 1, "P27_pT198": 1, "PRAS40_pT246": 1,
                             "TUBERIN_pT1462": 1, "INPP4B": -1, "PTEN": -1}},
    "TSC/mTOR": {"map": "PI3K / AKT / mTOR", "also": ("MTOR", "S6", "P70S6K1"),
                 "members": {"4EBP1_pS65": 1, "4EBP1_pT37T46": 1, "4EBP1_pT70": 1,
                             "P70S6K_pT389": 1, "MTOR_pS2448": 1, "S6_pS235S236": 1,
                             "S6_pS240S244": 1, "RICTOR_pT1135": 1}},
    "Hormone receptor": {"map": "ER signaling", "also": (),
                         "members": {"ERALPHA": 1, "ERALPHA_pS118": 1, "PR": 1}},
    "Hormone signaling": {"map": "ER signaling", "also": (),
                          "members": {"AR": 1, "INPP4B": 1, "GATA3": 1, "BCL2": 1}},
    "RTK": {"map": "HER2 / RTK", "also": ("HER2", "EGFR", "HER3"),
            "members": {"EGFR_pY1068": 1, "EGFR_pY1173": 1, "HER2_pY1248": 1, "HER3_pY1289": 1,
                        "SHC_pY317": 1, "SRC_pY416": 1, "SRC_pY527": 1}},
    "Cell cycle": {"map": "Cell cycle", "also": ("RB", "RB_pS807S811", "P16INK4A", "CMYC"),
                   "members": {"CDK1": 1, "CYCLINB1": 1, "CYCLIND1": 1, "CYCLINE1": 1,
                               "CYCLINE2": 1, "P27_pT157": 1, "P27_pT198": 1, "PCNA": 1}},
    "DNA damage response": {"map": "TP53 and DNA repair", "also": (),
                            "members": {"53BP1": 1, "ATM": 1, "BRCA2": 1, "CHK1_pS345": 1,
                                        "CHK2_pT68": 1, "KU80": 1, "MRE11": 1, "P53": 1,
                                        "RAD50": 1, "RAD51": 1, "XRCC1": 1}},
    "RAS/MAPK": {"map": "MAP kinase", "also": (),
                 "members": {"ARAF_pS299": 1, "CJUN_pS73": 1, "CRAF_pS338": 1,
                             "JNK_pT183Y185": 1, "MAPK_pT202Y204": 1, "MEK1_pS217S221": 1,
                             "P38_pT180Y182": 1, "P90RSK_pT359S363": 1, "SHC_pY317": 1,
                             "YB1_pS102": 1}},
    "Apoptosis": {"map": None, "also": (),
                  "members": {"BAK": 1, "BAX": 1, "BID": 1, "BIM": 1, "CASPASE7CLEAVEDD198": 1,
                              "BAD_pS112": -1, "BCL2": -1, "BCLXL": -1, "CIAP": -1}},
    "EMT": {"map": None, "also": ("BETACATENIN", "SNAIL"),
            "members": {"FIBRONECTIN": 1, "NCADHERIN": 1, "COLLAGENVI": 1, "CLAUDIN7": -1,
                        "ECADHERIN": -1}},
}
# Immune-cell antibodies on the array, grouped here (not from a paper): lymphocyte-lineage and
# cytotoxic markers, read against the RNA immune scores across the cohort.
RPPA_IMMUNE = ("LCK", "ZAP-70", "Granzyme-B", "CD20", "CD4", "CD45", "VAV1", "CD38")
# The gene whose RNA each antibody reads: the HGNC symbol of its target protein, curated here from
# the target names (a pan-AKT antibody reads AKT1-3; AKT1 stands for them; ERK1/2 by MAPK3).
ANTIBODY_GENES = {
    "AKT_pS473": "AKT1", "AKT_pT308": "AKT1", "AKT": "AKT1", "GSK3ALPHABETA_pS21S9": "GSK3A",
    "GSK3_pS9": "GSK3B", "P27_pT157": "CDKN1B", "P27_pT198": "CDKN1B", "PRAS40_pT246": "AKT1S1",
    "TUBERIN_pT1462": "TSC2", "INPP4B": "INPP4B", "PTEN": "PTEN", "PI3KP110ALPHA": "PIK3CA",
    "PI3KP85": "PIK3R1", "4EBP1_pS65": "EIF4EBP1", "4EBP1_pT37T46": "EIF4EBP1",
    "4EBP1_pT70": "EIF4EBP1", "P70S6K_pT389": "RPS6KB1", "P70S6K1": "RPS6KB1",
    "MTOR_pS2448": "MTOR", "MTOR": "MTOR", "S6_pS235S236": "RPS6", "S6_pS240S244": "RPS6",
    "S6": "RPS6", "RICTOR_pT1135": "RICTOR", "ERALPHA": "ESR1", "ERALPHA_pS118": "ESR1",
    "PR": "PGR", "AR": "AR", "GATA3": "GATA3", "BCL2": "BCL2", "EGFR_pY1068": "EGFR",
    "EGFR_pY1173": "EGFR", "EGFR": "EGFR", "HER2_pY1248": "ERBB2", "HER2": "ERBB2",
    "HER3_pY1289": "ERBB3", "HER3": "ERBB3", "SHC_pY317": "SHC1", "SRC_pY416": "SRC",
    "SRC_pY527": "SRC", "CDK1": "CDK1", "CYCLINB1": "CCNB1", "CYCLIND1": "CCND1",
    "CYCLINE1": "CCNE1", "CYCLINE2": "CCNE2", "PCNA": "PCNA", "RB": "RB1", "RB_pS807S811": "RB1",
    "P16INK4A": "CDKN2A", "CMYC": "MYC", "53BP1": "TP53BP1", "ATM": "ATM", "BRCA2": "BRCA2",
    "CHK1_pS345": "CHEK1", "CHK2_pT68": "CHEK2", "KU80": "XRCC5", "MRE11": "MRE11", "P53": "TP53",
    "RAD50": "RAD50", "RAD51": "RAD51", "XRCC1": "XRCC1", "ARAF_pS299": "ARAF",
    "CJUN_pS73": "JUN", "CRAF_pS338": "RAF1", "JNK_pT183Y185": "MAPK8", "MAPK_pT202Y204": "MAPK3",
    "MEK1_pS217S221": "MAP2K1", "P38_pT180Y182": "MAPK14", "P90RSK_pT359S363": "RPS6KA1",
    "YB1_pS102": "YBX1", "BAK": "BAK1", "BAX": "BAX", "BID": "BID", "BIM": "BCL2L11",
    "CASPASE7CLEAVEDD198": "CASP7", "BAD_pS112": "BAD", "BCLXL": "BCL2L1", "CIAP": "BIRC2",
    "FIBRONECTIN": "FN1", "NCADHERIN": "CDH2", "COLLAGENVI": "COL6A1", "CLAUDIN7": "CLDN7",
    "ECADHERIN": "CDH1", "BETACATENIN": "CTNNB1", "SNAIL": "SNAI1", "LCK": "LCK",
    "ZAP-70": "ZAP70", "Granzyme-B": "GZMB", "CD20": "MS4A1", "CD4": "CD4", "CD45": "PTPRC",
    "VAV1": "VAV1", "CD38": "CD38",
}
# what the array does not carry, said where a clinician would look for it
RPPA_ABSENT = "Ki-67 is not on this array (the slide's IHC or the RNA proliferation score reads it)"
WEAK_RHO = 0.3  # PLACEHOLDER: an antibody whose RNA correlation is below this is "weak agreement"

# promoter CpGs from the Illumina manifest; why each gene is read (each source checked in PubMed)
METHYLATION_GENES = {
    "ESR1": "methylation of the ESR1 CpG island marks loss of ER expression (Ottaviano 1994, "
            "Cancer Res 54:2552, PMID 8168078)",
    "PGR": "the gene behind the PR readout; read beside its RNA (no promoter-silencing study "
           "checked here)",
    "BRCA1": "BRCA1 promoter hypermethylation silences BRCA1 in sporadic breast tumors (Esteller "
             "2000, J Natl Cancer Inst 92:564, doi:10.1093/jnci/92.7.564)",
    "RASSF1": "RASSF1A promoter hypermethylation is frequent in breast and other carcinomas "
              "(Dammann 2005, Histol Histopathol 20:645, doi:10.14670/HH-20.645)",
    "GSTP1": "GSTP1 promoter hypermethylation in about 30% of breast carcinomas, with loss of "
             "the protein (Esteller 1998, Cancer Res 58:4515, PMID 9788592)",
    "CDKN2A": "de novo methylation of the CDKN2A (p16) CpG island in primary breast tumors "
              "(Herman 1995, Cancer Res 55:4525, PMID 7553621)",
}
PROMOTER_GROUPS = ("TSS1500", "TSS200", "5'UTR", "1stExon")  # the manifest's UCSC_RefGene_Group
CORE_GROUPS = ("TSS200", "1stExon")  # a gene's core promoter: within 200 bp of the TSS, exon 1
# the RefSeq transcript whose promoter is read, where the gene has two studied ones
TRANSCRIPTS = {"RASSF1": "NM_007182",   # RASSF1A, not RASSF1C (Dammann 2005)
               "CDKN2A": "NM_000077"}   # p16INK4a, not p14ARF (Herman 1995)
NORMAL_MAX = 0.2  # PLACEHOLDER: a probe is kept when its median beta in normal breast is below
METHYLATED = 0.3  # PLACEHOLDER: mean promoter beta from which a promoter is "methylated"
RNA_LOW = 25      # PLACEHOLDER: an RNA level at or under this cohort percentile is "low"
PATHWAY_HIGH, PATHWAY_LOW = 75, 25  # PLACEHOLDER: cohort percentiles, "high" / "low" activity
IMMUNE_HIGH, IMMUNE_LOW = 75, 25  # PLACEHOLDER: cohort percentiles (the cross-test rule's high: 75)
CONSISTENT, NOT_CONSISTENT = "consistent", "not consistent"
# round 2's placeholders, as the Methods page and the exports list them (what, value)
PLACEHOLDERS = [
    ("promoter probe kept", f"median beta in TCGA's normal breast under {NORMAL_MAX}"),
    ("promoter methylated", f"mean core-promoter beta of {METHYLATED} or more"),
    ("RNA low beside a promoter", f"at or under the {RNA_LOW}th cohort percentile"),
    ("protein pathway high / low (PIK3CA queue item)",
     f"from the {PATHWAY_HIGH}th / to the {PATHWAY_LOW}th cohort percentile"),
    ("immune score high / low (immune picture)",
     f"from the {IMMUNE_HIGH}th / to the {IMMUNE_LOW}th cohort percentile"),
    ("protein against RNA agreement called weak", f"Spearman under {WEAK_RHO}"),
]

# One card per data layer: how the model input was made (scripts/prepare_tcga.py), its own
# validation (app/results_tcga_brca.json, single-layer rows), what to check and what it can't see.
LAYERS = {
    "clinical": {
        "name": "Clinical record", "result": "only_clinical",
        "normalization": "age, stage, T and N median-imputed and z-scored over the cohort; M1, "
                         "ductal, lobular and 'stage unknown' as 0/1 flags",
        "check": "the pathology report for stage, T and N; a missing stage was imputed",
        "cannot": "the tumor's biology (the omic layers), receptors (IHC), mutations "
                  "(genomics workbench)",
        "failure": "",
    },
    "genomic": {
        "name": "Copy number", "result": "only_genomic",
        "normalization": "ASCAT3 absolute gene-level copy number turned into calls relative to "
                         "the tumor's ploidy (its median gene copy number): −2 deep deletion, −1 "
                         "loss, 0 neutral, +1 gain, +2 amplification (at least twice the ploidy); "
                         "the 200 most variable genes",
        "check": "tumor purity and the ploidy estimate; an arm-level gain versus a focal "
                 "amplification",
        "cannot": "whether a gained gene is expressed (RNA layer) or made into protein (protein "
                  "layer); point mutations (genomics workbench)",
        "failure": "Known failure: on its own this layer ranks patients worse than chance on "
                   "hospitals it never saw, a sign of site and batch effects. Its contribution to "
                   "this patient's risk is shown, but read it with that in mind.",
    },
    "rna": {
        "name": "RNA expression", "result": "only_rna",
        "normalization": "STAR TPM, log(1 + TPM), z-scored per gene over the TCGA-BRCA primary "
                         "tumors; the 1,000 most variable genes",
        "check": "tumor content of the bulk sample: stroma, immune cells and normal breast dilute "
                 "or add expression",
        "cannot": "protein level (protein layer, IHC); where in the tumor a gene is expressed "
                  "(slides)",
        "failure": "",
    },
    "methylation": {
        "name": "DNA methylation", "result": "only_methylation",
        "normalization": "450K array beta values as M-values, log2(β / (1 − β)); the 500 most "
                         "variable CpGs; a missing value is filled with the cohort mean",
        "check": "tumor purity; a CpG is linked to a gene by position only, which does not prove "
                 "the gene is silenced",
        "cannot": "the expression of the nearby gene (RNA layer)",
        "failure": "",
    },
    "protein": {
        "name": "Protein (RPPA)", "result": "only_protein",
        "normalization": "reverse-phase protein array (TCPA), log2 and median-centered by the "
                         "provider, z-scored per antibody over the cohort; the 100 most variable "
                         "antibodies",
        "check": "antibody validation status; RPPA measures a lysate of the whole sample, not "
                 "the tumor cells alone",
        "cannot": "where in the tissue the protein sits (IHC on a slide)",
        "failure": "",
    },
}
OMIC_LAYERS = ("genomic", "rna", "methylation", "protein")


# --- offline: scores on the cohort ---------------------------------------------------------

def centroid_call(x: pd.Series, centroids: pd.DataFrame) -> dict:
    """Nearest-centroid subtype (Parker et al. 2009): Spearman correlation of one tumor's
    median-centered log expression ``x`` (by gene) with each centroid (``centroids``: genes x
    subtypes). Genes ``x`` lacks are left out. Returns the call, every correlation, the margin
    from the best to the second best, and how many genes were used."""
    genes = centroids.index.intersection(x.dropna().index)
    cor = centroids.loc[genes].corrwith(x[genes], method="spearman").sort_values(ascending=False)
    return {"call": str(cor.index[0]), "cor": {str(k): round(float(v), 3) for k, v in cor.items()},
            "margin": round(float(cor.iloc[0] - cor.iloc[1]), 3), "genes": int(len(genes))}


def set_scores(z: pd.DataFrame, sets: dict[str, list[str]] | dict[str, tuple]) -> pd.DataFrame:
    """Per tumor and gene set: the mean of the set's measured gene-wise cohort z-scores (``z``:
    tumors x genes), z-scored again over the cohort, so 0 is the cohort average and 1 one standard
    deviation above it (z-score averaging, Lee et al. 2008, up to scale)."""
    return zscore(pd.DataFrame({name: z[z.columns.intersection(list(genes))].mean(axis=1)
                                for name, genes in sets.items()}))


def signed_scores(z: pd.DataFrame, sets: dict[str, dict[str, int]]) -> pd.DataFrame:
    """Akbani et al. 2014's RPPA pathway score up to scale: per tumor, the mean of the measured
    members' z-scores (``z``: tumors x antibodies), a negative regulator's subtracted, z-scored
    again over the cohort. A tumor with none of a set's members measured gets NaN."""
    out = {}
    for name, members in sets.items():
        cols = [a for a in members if a in z.columns]
        out[name] = (z[cols] * pd.Series({a: members[a] for a in cols})).mean(axis=1)
    return zscore(pd.DataFrame(out))


def promoter_probes(manifest: pd.DataFrame, genes: dict[str, str | None]
                    ) -> tuple[dict[str, list[str]], list[str]]:
    """From the Illumina 450K manifest (IlmnID, CHR, UCSC_RefGene_Name, UCSC_RefGene_Accession,
    UCSC_RefGene_Group, Relation_to_UCSC_CpG_Island): each gene's core-promoter probes (CORE_GROUPS
    of the gene, of one RefSeq transcript where ``genes`` names it), and every autosomal CpG-island
    probe in any gene's promoter (PROMOTER_GROUPS; the hypermethylation index's candidates).
    Island status is not required of a gene's probes: the manifest's UCSC island lies upstream of
    BRCA1's core promoter, whose probes it calls shore."""
    m = manifest.fillna("")
    entries = [list(zip(n.split(";"), a.split(";"), g.split(";"), strict=False)) for n, a, g in
               zip(m["UCSC_RefGene_Name"], m["UCSC_RefGene_Accession"], m["UCSC_RefGene_Group"],
                   strict=True)]
    ids = m["IlmnID"].to_numpy()
    out = {gene: [str(i) for i, e in zip(ids, entries, strict=True)
                  if any(n == gene and g in CORE_GROUPS and (tx is None or a == tx)
                         for n, a, g in e)] for gene, tx in genes.items()}
    island = (m["Relation_to_UCSC_CpG_Island"] == "Island").to_numpy()
    auto = ~m["CHR"].astype(str).isin(["X", "Y"]).to_numpy()
    promoter = np.array([any(g in PROMOTER_GROUPS for _, _, g in e) for e in entries], bool)
    return out, [str(i) for i in ids[island & auto & promoter]]


def promoter_beta(betas: pd.DataFrame, probes: dict[str, list[str]]) -> pd.DataFrame:
    """Per tumor and gene, the mean beta over the gene's promoter probes (``probes``: gene ->
    probe ids) that ``betas`` (tumors x probes) measured; NaN when none was."""
    return pd.DataFrame({g: betas[betas.columns.intersection(p)].mean(axis=1)
                         for g, p in probes.items()})


def youden(values, positive) -> dict:
    """The cutoff on ``values`` that best separates recorded positives from negatives (highest
    sensitivity + specificity − 1), with the AUC: a threshold calibrated on this data."""
    v, pos = np.asarray(values, float), np.asarray(positive, bool)
    cuts = np.unique(v)
    sens = (v[pos][:, None] >= cuts).mean(0)
    spec = (v[~pos][:, None] < cuts).mean(0)
    k = int(np.argmax(sens + spec - 1))
    ranks = pd.Series(v).rank().to_numpy()
    n1, n0 = pos.sum(), (~pos).sum()
    auc = (ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    return {"cutoff": float(cuts[k]), "sensitivity": round(float(sens[k]), 3),
            "specificity": round(float(spec[k]), 3), "auc": round(float(auc), 3),
            "positives": int(n1), "negatives": int(n0)}


def agreement(pred, truth) -> dict:
    """Agreement of calls ``pred`` with reference calls ``truth`` (pairs with a missing side are
    dropped): share agreeing, Cohen's kappa and the confusion matrix {reference: {call: n}}."""
    t = pd.DataFrame({"pred": list(pred), "truth": list(truth)}).dropna()
    po = float((t["pred"] == t["truth"]).mean())
    p, r = t["pred"].value_counts(normalize=True), t["truth"].value_counts(normalize=True)
    pe = float((p * r.reindex(p.index).fillna(0)).sum())
    conf = pd.crosstab(t["truth"], t["pred"])
    return {"n": len(t), "agree": int((t["pred"] == t["truth"]).sum()),
            "share": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3),
            "confusion": {str(a): {str(b): int(n) for b, n in row.items()}
                          for a, row in conf.iterrows()}}


def her2_status(ihc: str | None, fish: str | None) -> str | None:
    """Clinical HER2 status per ASCO/CAP: IHC positive (3+) or negative (0, 1+) stands; IHC
    equivocal (2+) is settled by in situ hybridization; anything else is unknown (None)."""
    if ihc in ("Positive", "Negative"):
        return ihc
    if ihc == "Equivocal" and fish in ("Positive", "Negative"):
        return fish
    return None


# --- in the app ----------------------------------------------------------------------------

def percentile(value: float, quantiles: list[float]) -> float:
    """A value's cohort percentile from the cohort's quantiles at 0, 5, ..., 100 % (linear
    interpolation; outside the range, 0 or 100)."""
    q = np.asarray(quantiles, float)
    return float(np.interp(value, q, np.linspace(0, 100, len(q))))


def _pos(status: str | None) -> bool | None:
    return {"Positive": True, "Negative": False}.get(status)


def receptor_lines(receptors: dict, calibration: dict) -> list[dict]:
    """One line per comparison, each with its status and evidence: recorded IHC (observed) against
    the gene's RNA level, ERBB2 copy number against HER2, RPPA protein against RNA. ``receptors``
    is one case's block of ``omics_scores.json``; ``calibration`` the cutoffs calibrated on the
    cohort ("validation" → "receptors")."""
    out = []
    for name, r in receptors.items():
        gene, antibody = RECEPTORS[name]
        ihc = r.get("status")
        recorded = (f"{name} IHC {r['ihc'].lower()}" if r.get("ihc") else f"{name} IHC not "
                    "recorded")
        if name == "HER2" and r.get("ihc") == "Equivocal":
            recorded += f", in situ hybridization {(r.get('fish') or 'not recorded').lower()}"
        cal = calibration.get(name, {})
        rna, prot, cn = r.get("rna"), r.get("protein"), r.get("cn")
        if rna is not None:
            side = "above" if rna["high"] else "below"
            text = (f"{recorded}; {gene} RNA at the {ordinal(rna['pct'])} percentile, {side} the "
                    "cutoff that best separates recorded-positive from recorded-negative tumors "
                    f"in this cohort ({ordinal(cal['rna']['cutoff_pct'])} percentile)")
            short = (f"{recorded}, {gene} RNA {'high' if rna['high'] else 'low'} "
                     f"({ordinal(rna['pct'])} percentile)")
            out.append(_line(name, "IHC vs RNA", text, short, _pos(ihc), rna["high"],
                             "the specimen and its tumor content; RNA is not protein",
                             f"{OBSERVED} (IHC, RNA); cutoff calibrated on this cohort's IHC "
                             f"(AUC {cal['rna']['auc']:.2f}, in-sample)"))
        if cn is not None:
            amp = cn["copies"] >= 2 * cn["ploidy"]
            text = (f"{recorded}; ERBB2 copy number {cn['copies']:g} at a tumor ploidy of "
                    f"{cn['ploidy']:g}: {'amplified' if amp else 'not amplified'}")
            short = (f"{recorded}, ERBB2 {'amplified' if amp else 'not amplified'} "
                     f"({cn['copies']:g} copies at ploidy {cn['ploidy']:g})")
            out.append(_line(name, "IHC vs copy number", text, short, _pos(ihc), amp,
                             "tumor purity and the ploidy estimate; in situ hybridization is the "
                             "clinical test for amplification",
                             f"{OBSERVED} (IHC, copy number); amplification = at least twice the "
                             "ploidy (placeholder, by analogy with the ASCO/CAP ISH ratio of 2.0; "
                             "not validated on ASCAT calls)"))
        if prot is not None:
            pname = ANTIBODY_NAMES[antibody]
            side = "above" if prot["high"] else "below"
            vs, other = ("RNA", rna["high"]) if rna is not None else ("IHC", _pos(ihc))
            text = (f"{pname} protein (RPPA) at the {ordinal(prot['pct'])} percentile, {side} its "
                    f"IHC-calibrated cutoff ({ordinal(cal['protein']['cutoff_pct'])} percentile)"
                    + (f"; {gene} RNA {'above' if rna['high'] else 'below'} its cutoff"
                       if rna is not None else "") + f"; {recorded}")
            short = (f"{pname} protein {'high' if prot['high'] else 'low'} "
                     f"({ordinal(prot['pct'])} percentile), {gene} RNA "
                     f"{'high' if rna['high'] else 'low'}" if rna is not None else
                     f"{recorded}, {pname} protein {'high' if prot['high'] else 'low'}")
            out.append(_line(name, f"protein vs {vs}", text, short, other, prot["high"],
                             "RNA is not protein: RPPA measures the whole sample's lysate, IHC "
                             "the tumor cells",
                             f"{OBSERVED} (RPPA, {vs}); cutoff calibrated on this cohort's IHC "
                             f"(AUC {cal['protein']['auc']:.2f}, in-sample)"))
    return out


def _line(receptor, compare, text, short, reference, measured, check, evidence) -> dict:
    status = NO_COMPARISON if reference is None else AGREE if reference == measured else DISAGREE
    tail = {AGREE: "agree", DISAGREE: "disagree, worth a second look",
            NO_COMPARISON: "nothing recorded to compare with"}[status]
    return {"receptor": receptor, "compare": compare, "text": f"{text}. {compare}: {tail}.",
            "short": short, "status": status, "check": check, "evidence": evidence}


def look_here(case: dict | None, lines: list[dict], measured: list[str]) -> list[str]:
    """What to check by eye, in order: receptor disagreements, a subtype call that differs from
    the published one or barely beats the runner-up, and the copy-number layer's known failure."""
    out = [f"{x['receptor']}, {x['compare']} disagree: {x['short']}" for x in lines
           if x["status"] == DISAGREE]
    sub = (case or {}).get("pam50")
    if sub and sub.get("published") and not sub["agrees"]:
        out.append(f"PAM50 call {SUBTYPES[sub['call']]} differs from TCGA's published call "
                   f"{SUBTYPES[sub['published']]}")
    if sub and sub["margin"] < LOW_MARGIN:
        out.append(f"PAM50 call {SUBTYPES[sub['call']]} beats the runner-up by only "
                   f"{sub['margin']:.2f} in correlation: a borderline call")
    if "genomic" in measured:
        out.append("Copy number: a known failure across hospitals (see its layer card)")
    return out


LOW_MARGIN = 0.1  # PLACEHOLDER: a centroid correlation margin under which a call is borderline


# --- round 2 in the app: protein pathways, promoters, the immune picture ------------------------

TILS = ("International TILs Working Group recommendations (Salgado et al., Ann Oncol "
        "2015;26:259-71; PMID 25214542, doi:10.1093/annonc/mdu450)")
PI3K_MAP = "PI3K / AKT / mTOR"


def rppa_rows(cs: dict, data: dict) -> list[dict]:
    """One row per RPPA pathway score of this case: z, cohort percentile, members measured, each
    member with its sign, z-score and percentile (the hover text), and the genomics pathway-map
    name it sits beside. [] without RPPA."""
    rp, left = cs.get("rppa") or {}, set((data.get("rppa") or {}).get("left_out", []))
    out = []
    for name, (z, p, n) in rp.get("pathways", {}).items():
        pw = RPPA_PATHWAYS[name]
        members = [{"antibody": a, "sign": s, "value": rp["antibodies"].get(a), "gene":
                    ANTIBODY_GENES[a]} for a, s in pw["members"].items() if a not in left]
        out.append({"pathway": name, "z": z, "pct": p, "measured": n, "of": len(members),
                    "map": pw["map"], "members": members, "hover": "; ".join(
                        f"{'−' if m['sign'] < 0 else '+'}{m['antibody']} " + (
                            "not measured" if m["value"] is None else
                            f"z {m['value'][0]:+.2f} ({ordinal(m['value'][1])})")
                        for m in members)})
    return out


def methylation_lines(cs: dict) -> list[dict]:
    """One line per promoter gene: the case's mean promoter-island beta and its cohort percentile,
    the call at METHYLATED (placeholder), the gene's RNA percentile beside it and whether the two
    are consistent with silencing (RNA low at RNA_LOW, placeholder)."""
    m, rna, rec = cs.get("methylation") or {}, cs.get("rna_pct") or {}, cs.get("receptors") or {}
    out = []
    for g, (beta, p, n) in m.get("genes", {}).items():
        meth, r = beta >= METHYLATED, rna.get(g)
        head = (f"{g} promoter {'methylated' if meth else 'unmethylated'} (mean β {beta:.2f} over "
                f"{n} CpG{'s' if n != 1 else ''}, the {ordinal(p)} percentile of this cohort)")
        if r is None:
            status, tail = NO_COMPARISON, "RNA not measured"
        elif g in TRANSCRIPTS:  # the promoter of one transcript; the RNA layer reads the gene
            status = NO_COMPARISON
            tail = (f"RNA at the {ordinal(r)} percentile, but the RNA layer reads the whole gene "
                    f"({'RASSF1A with RASSF1C' if g == 'RASSF1' else 'p16INK4a with p14ARF'}), "
                    "so it cannot confirm silencing of this promoter's transcript")
        elif meth:
            status = CONSISTENT if r <= RNA_LOW else NOT_CONSISTENT
            tail = (f"RNA at the {ordinal(r)} percentile: " + (
                "consistent with silencing" if status == CONSISTENT else
                "not consistent with silencing (part of the sample unmethylated, another promoter "
                "in use, or the call itself)"))
        else:
            status = "unmethylated"
            tail = (f"RNA at the {ordinal(r)} percentile: " + (
                "low for another reason (a deletion, regulation), not promoter methylation"
                if r <= RNA_LOW else "no sign of silencing"))
        receptor = {"ESR1": "ER", "PGR": "PR"}.get(g)
        if receptor and (rec.get(receptor) or {}).get("status"):
            tail += f"; {receptor} recorded {rec[receptor]['status'].lower()} by IHC"
        out.append({"gene": g, "beta": beta, "pct": p, "probes": n, "methylated": meth,
                    "rna_pct": r, "status": status, "text": f"{head}; {tail}.",
                    "short": f"{g} {'methylated' if meth else 'unmethylated'}, RNA "
                             + ("not measured" if r is None else f"{ordinal(r)} percentile")})
    return out


def slide_immune(pf, cs: dict, version: int | None = None) -> list[dict]:
    """The patient's scored sections' stromal lymphocytes near the front, as the slide workbench
    computes them: the precomputed numbers with the second lymphocyte model when the section's
    method version matches, else the section's own summary (tile head only)."""
    from muffle.workbench import slides  # the slide workbench's own reader

    out = []
    for s in slides.sections(pf, version):
        pre = (cs.get("slides") or {}).get(s["slide"])
        if not pre or pre.get("method_version") != s["meta"].get("method_version"):
            pre = {**s["meta"].get("immune", {}), "til_model": None}
        zones = pre.get("zones") or {}
        zone = next((z for z in ("front band", "peritumoral") if (zones.get(z) or {}).get("tiles")),
                    None)
        rec = zones.get(zone) or {}
        share = rec.get("til_lymph_share")
        out.append({"slide": s["slide"], "opens": s["opens"], "pattern": pre.get("pattern"),
                    "zone": zone, "til_share": share, "head_share": rec.get("lymph_tile_share"),
                    "til_model": pre.get("til_model") if share is not None else None,
                    "nuclei_per_mm2": rec.get("lymph_nuclei_per_mm2")})
    return out


def immune_picture(cs: dict, secs: list[dict]) -> dict | None:
    """The immune picture read across layers: the RNA immune signature (ESTIMATE genes) and
    cytolytic activity, the immune-cell proteins (RPPA) and each scored section's stromal
    lymphocytes near the front (the second lymphocyte model where it scored, else the tile head;
    a desert below the slide workbench's placeholder 5%). Agree when every side that makes a call
    is high or every one low, disagree when one is high and another low; what would settle it is
    a pathologist's TILs read. None without RNA."""
    from muffle.workbench.invasion import CUTOFFS as SLIDE_CUTOFFS

    est, cyt = (cs.get("estimate") or {}).get("immune"), (cs.get("scores") or {}).get("immune")
    if est is None:
        return None
    prot = (cs.get("rppa") or {}).get("immune")

    def level(p):
        return "high" if p >= IMMUNE_HIGH else "low" if p <= IMMUNE_LOW else None

    calls = {"RNA": level(est[1])}
    bits = [f"RNA immune signature at the {ordinal(est[1])} percentile"
            + (f" (cytolytic activity {ordinal(cyt[1])})" if cyt else "")]
    if prot:
        calls["protein"] = level(prot[1])
        bits.append(f"immune-cell proteins (RPPA, {prot[2]} antibodies) at the {ordinal(prot[1])}")
    desert = SLIDE_CUTOFFS["immune_desert"][0]
    crosstest = False
    for s in secs:
        share = s["til_share"] if s["til_share"] is not None else s["head_share"]
        if share is None:
            bits.append(f"section {s['slide']}: no front, lymphocytes not assessed")
            continue
        calls[s["slide"]] = "low" if share < desert else None  # not a desert is not inflamed
        by = "the second lymphocyte model" if s["til_share"] is not None else "the tile head"
        bits.append(f"section {s['slide']}: lymphocytes in {share:.0%} of the {s['zone']} tiles by "
                    f"{by} (" + (f"a desert, under {desert:.0%}" if share < desert else
                                 f"not a desert at {desert:.0%}, which is not the same as "
                                 "inflamed") + "; placeholder)")
        crosstest |= (str(s["pattern"] or "").startswith("desert") and bool(cyt)
                      and cyt[1] >= IMMUNE_HIGH)  # crosstest's "slide immune vs RNA immune"
    made = {k: v for k, v in calls.items() if v}
    status = (DISAGREE if {"high", "low"} <= set(made.values()) else
              AGREE if len(made) >= 2 and len(set(made.values())) == 1 else NO_COMPARISON)
    tail = {AGREE: "agree", DISAGREE: "disagree: " + ", ".join(f"{k} {v}" for k, v in made.items()),
            NO_COMPARISON: "no clear call to compare (a score between the "
                           f"{ordinal(IMMUNE_LOW)} and {ordinal(IMMUNE_HIGH)} percentiles, a "
                           "section that is not a desert, or one layer only)"}[status]
    return {"status": status, "text": "; ".join(bits) + f". Immune picture: {tail}.",
            "short": f"immune picture: {status}", "calls": calls, "crosstest": crosstest,
            "settle": f"a pathologist's stromal TILs read on the H&E section ({TILS})",
            "evidence": f"{INFERENCE} (RNA and protein scores, slide tile classes)"}


def genomics_pathways(pf) -> dict[str, dict]:
    """The genomics workbench's pathway map for this file, by map name (``genome.pathway_summary``:
    the altered genes, observed, and those not measured); {} when the file has neither copy
    number nor sequencing."""
    from muffle.workbench import genome, genomics

    data = genome.load(genome.CN_JSON) or {}
    block = genome.case_block(data, pf)
    rows = genome.landscape(block, data["genes"]) if block else []
    names = [f"{d['gene']} {d['change']}" for d in genomics._detections(pf, [])]
    sequenced = any(t.workbench == "mutations" for t in pf.tests)
    if not rows and not sequenced:
        return {}
    return {p["pathway"]: p for p in genome.pathway_summary(
        genome.pathway_map(names, rows, sequenced))}


def pi3k_mutations(pf) -> list[str]:
    """Observed mutations ("PIK3CA H1047R") in the genes of the genomics map's PI3K / AKT / mTOR
    pathway."""
    from muffle.workbench import genome, genomics

    genes = genome.PATHWAYS[PI3K_MAP]["genes"]
    return [f"{d['gene']} {d['change']}" for d in genomics._detections(pf, [])
            if d["gene"] in genes]


def search(query: str, items: list[dict]) -> dict:
    """Items (each {"kind", "name", "text"}) matching ``query`` in plain words, every word of it:
    a gene or feature name, a pathway ("PI3K pathway", "proliferation"), or a status
    ("disagree", "methylated"). An unanswerable query gets an honest answer naming the test that
    could answer it."""
    q = (query or "").strip().lower()
    if not q:
        return {"hits": items, "note": None}
    words = [re.compile(rf"\b{re.escape(w)}") for w in q.split()]  # "methylated" ≠ "unmethylated"
    hits = [i for i in items if all(w.search(f"{i['name']} {i['text']}".lower()) for w in words)]
    note = None if hits else (
        f"\"{query}\" is not in these layers. Mutations: the genomics workbench; tissue and "
        "cells: the slide workbench; blood markers: the lab workbench; a gene outside the "
        "model's 1,000 most variable genes is not read here.")
    return {"hits": hits, "note": note}


MARK_KINDS = ("omics", "pathway_protein", "methylation")  # this workbench's finding kinds


def report_json(file_id: str, findings: list[dict], reviews: dict, provenance: dict) -> str:
    """The workbench's findings, the reviewers' marks on this file and the provenance, as JSON."""
    marks = {k: r for k, r in reviews.items() if k.startswith(file_id + "|")
             and k.split("|")[1] in MARK_KINDS}
    return json.dumps({"file": file_id, "provenance": provenance, "findings": findings,
                       "review_marks": marks}, indent=2)


def report_csv(findings: list[dict], reviews: dict) -> str:
    """One row per finding with its mark (if any)."""
    out = io.StringIO()
    cols = ["kind", "layer", "name", "value", "percentile", "evidence", "status", "key"]
    w = csv.DictWriter(out, [*cols, "mark", "by", "at"], extrasaction="ignore")
    w.writeheader()
    for f in findings:
        r = reviews.get(f.get("key"), {})
        w.writerow({**f, "mark": r.get("mark", ""), "by": r.get("by", ""), "at": r.get("at", "")})
    return out.getvalue()


# --- the workbench contract (docs/WORKBENCHES.md §1): the patient file's overview ----------------

SCORES = Path(__file__).resolve().parents[3] / "app" / "omics_scores.json"


@lru_cache(maxsize=2)
def scores(path: Path = SCORES) -> dict:
    """``app/omics_scores.json`` (scripts/omics_scores.py), read once; {} when absent."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def case_scores(pf) -> dict | None:
    """A TCGA file's precomputed block of ``omics_scores.json``, or None: not a TCGA file, not
    computed, or computed for another build of the cohort (its log-risk differs, the page's
    guard)."""
    if pf.kind != "TCGA-BRCA":
        return None
    cs = scores().get("cases", {}).get(pf.id.removeprefix("Case "))
    log_risk = (pf.versions[0].risk or {}).get("log_risk")
    if cs is None or log_risk is None or abs(cs["log_risk"] - log_risk) > 1e-3:
        return None
    return cs


def file_lines(pf) -> list[dict]:
    """``receptor_lines`` of a TCGA file with the cohort's calibration ([] without scores)."""
    cs = case_scores(pf)
    return [] if cs is None else receptor_lines(
        cs["receptors"], scores().get("validation", {}).get("receptors", {}))


def _opens(pf) -> tuple:
    """The omics workbench opens from the RNA layer's test, else any data-layer test."""
    tests = [t for t in pf.tests if t.workbench in ("omics", "record")]
    t = next((t for t in tests if t.details.get("layer") == "rna"), tests[0] if tests else None)
    return () if t is None else ("Tests", t.kind, t.month, t.name)


def published(sub: dict) -> str:
    if sub.get("published") is None:
        return "no published call"
    return ("agrees with TCGA's published call" if sub["agrees"] else
            f"differs from TCGA's published call ({SUBTYPES[sub['published']]})")


def recorded_text(receptors: dict) -> str:
    """"ER positive, PR positive, HER2 negative (IHC equivocal, ISH negative)": the recorded
    status, per ASCO/CAP for HER2 (``status``), with the IHC and ISH it rests on."""
    out = []
    for name, r in receptors.items():
        status = (r.get("status") or "not recorded").lower()
        if name == "HER2" and r.get("ihc") == "Equivocal":
            status += f" (IHC equivocal, ISH {(r.get('fish') or 'not recorded').lower()})"
        out.append(f"{name} {status}")
    return ", ".join(out)


def summary(pf, version: int | None = None) -> dict:
    """The PAM50 call with its margin, the recorded receptor status, how RNA, copy number and
    protein agree with it, and the proliferation and immune scores."""
    cs = case_scores(pf)
    if cs is None:
        return {"workbench": "omics", "title": "Expression, methylation, protein", "cards": [],
                "note": "no expression, methylation or protein scores in this file"}
    data, sub, opens = scores(), cs["pam50"], _opens(pf)
    runner = sorted(sub["cor"], key=lambda k: -sub["cor"][k])[1]
    focus = {"omics": finding_key(pf, "omics", "subtype", "PAM50")}
    trust = ("weak" if sub["margin"] < LOW_MARGIN else
             "moderate" if sub.get("published") and not sub["agrees"] else "strong")
    val = data.get("validation", {}).get("pam50", {})
    cards = [card(
        "PAM50 subtype", f"{SUBTYPES[sub['call']]}, margin {sub['margin']:.2f} over "
        f"{SUBTYPES[runner]}; {published(sub)}", INFERENCE, ASSAYS["rna"],
        f"PAM50 nearest centroid (Parker 2009, genefu), ER-balanced centering; "
        f"{data.get('version', '?')}; agrees with TCGA's published calls for "
        f"{val.get('share', 0):.1%} of {val.get('n', '?')} tumors",
        f"a margin under {LOW_MARGIN} is called borderline (placeholder)", trust, opens, focus)]
    lines = file_lines(pf)
    compared = [x for x in lines if x["status"] != NO_COMPARISON]
    off = [x for x in compared if x["status"] == DISAGREE]
    first = (off or compared or lines or [None])[0]
    receptor = None if first is None else {"omics": finding_key(
        pf, "omics", "receptor", f"{first['receptor']}: {first['compare']}")}
    cards.append(card(
        "Recorded receptors", recorded_text(cs["receptors"]), OBSERVED,
        "TCGA clinical data (IHC; ISH for HER2)", REFERENCES["ihc"],
        "the recording laboratory's; HER2 per ASCO/CAP (IHC 3+, or 2+ with ISH)", "strong",
        opens, receptor))
    if compared:
        cards.append(card(
            "Receptors in RNA and protein", f"{len(compared) - len(off)} of {len(compared)} "
            "comparisons agree with the recorded status" + (
                "; disagree: " + "; ".join(x["short"] for x in off) if off else ""),
            f"{OBSERVED} (IHC, RNA, copy number, protein)", "RNA, copy number and RPPA layers",
            "receptor consistency (omics workbench)", "cutoffs calibrated in-sample on this "
            "cohort's IHC (Youden); ERBB2 amplified at twice the ploidy (placeholder)",
            "moderate", opens, receptor))
    prolif, immune = cs["scores"]["proliferation"], cs["scores"]["immune"]
    cards.append(card(
        "Proliferation and immune", f"proliferation at the {ordinal(prolif[1])} percentile, "
        f"immune cytolytic activity at the {ordinal(immune[1])} (this cohort)", INFERENCE,
        ASSAYS["rna"], "cohort z-scores of the PAM50 proliferation genes and of GZMA and PRF1 "
        "(Rooney 2015)", "none: relative to this cohort", "moderate", opens,
        {"omics": finding_key(pf, "omics", "score", "immune")}))
    rows = sorted(rppa_rows(cs, data), key=lambda r: -r["pct"])
    if rows:
        hi, lo = rows[0], rows[-1]
        cards.append(card(
            "Protein pathways (RPPA)", f"{hi['pathway']} highest at the {ordinal(hi['pct'])} "
            f"percentile, {lo['pathway']} lowest at the {ordinal(lo['pct'])} ({len(rows)} pathway "
            "scores, this cohort)", INFERENCE, ASSAYS["protein"],
            "RPPA pathway scores (Akbani et al. 2014): signed mean of the member antibodies' "
            f"cohort z-scores, z-scored again; {data.get('version2', '?')}",
            "none: relative to this cohort", "moderate", opens,
            {"omics": finding_key(pf, "pathway_protein", hi["pathway"])}))
    meth = methylation_lines(cs)
    if meth:
        called = [x for x in meth if x["methylated"]]
        index = cs["methylation"]["index"]
        cards.append(card(
            "Promoter methylation", ("; ".join(x["gene"] + " methylated" + {
                CONSISTENT: " with low RNA", NOT_CONSISTENT: " but RNA not low"}.get(
                    x["status"], "") for x in called) or
                                     f"none of {', '.join(x['gene'] for x in meth)} methylated")
            + f"; CpG island hypermethylation index at the {ordinal(index[1])} percentile",
            f"{OBSERVED} (beta), {HYPOTHESIS} (the index)", ASSAYS["methylation"],
            "mean beta over each gene's CpG-island promoter probes (Illumina 450K manifest); index"
            " = mean beta over every autosomal CpG-island promoter probe", f"methylated from a "
            f"mean beta of {METHYLATED} on, RNA low at or under the {ordinal(RNA_LOW)} percentile "
            "(both placeholders)", "weak", opens,
            {"omics": finding_key(pf, "methylation", (called or meth)[0]["gene"])}))
    pic = immune_picture(cs, slide_immune(pf, cs, version))
    if pic:
        est = cs["estimate"]
        cards.append(card(
            "Immune picture", f"RNA immune signature at the {ordinal(est['immune'][1])} "
            f"percentile, stromal at the {ordinal(est['stromal'][1])}; {pic['short']}"
            + ("" if pic["status"] != DISAGREE else f" (settles it: {pic['settle']})"),
            pic["evidence"], f"{ASSAYS['rna']}, RPPA and the scored sections",
            "z-score averaging of the ESTIMATE immune and stromal genes (Yoshihara et al. 2013), "
            "the RPPA immune-cell antibodies, the slide workbench's lymphocytes by zone",
            f"high from the {ordinal(IMMUNE_HIGH)}, low to the {ordinal(IMMUNE_LOW)} percentile; "
            "slide desert under 5% lymphocyte tiles (placeholders)", "weak", opens,
            {"omics": finding_key(pf, "omics", "immune", "immune picture")}))
    return {"workbench": "omics", "title": "Expression, methylation, protein", "cards": cards,
            "note": None}


def queue(pf, version: int | None = None) -> list[dict]:
    """Receptor comparisons that disagree with the recorded status (consequence 2 for ER and
    HER2, which decide endocrine and anti-HER2 eligibility; 1 for PR), a subtype call that differs
    from the published one or barely beats the runner-up. The copy-number layer's known failure
    is a standing caveat of the page, not a finding about this patient."""
    cs = case_scores(pf)
    if cs is None:
        return []
    opens, out = _opens(pf), []
    for x in file_lines(pf):
        if x["status"] != DISAGREE:
            continue
        name = f"{x['receptor']}: {x['compare']}"
        out.append(look(
            name, f"{x['receptor']}, {x['compare']}: disagree", f"{x['short']}; check: "
            f"{x['check']}", x["evidence"], "weak" if "copy number" in x["compare"] else
            "moderate", 2 if x["receptor"] in ("ER", "HER2") else 1, opens,
            source=f"{ASSAYS['rna']} and the recorded {x['receptor']} status",
            key=finding_key(pf, "omics", "receptor", name),
            focus={"omics": finding_key(pf, "omics", "receptor", name)},
            threshold=x["evidence"].split("; ", 1)[-1]))
    sub = cs["pam50"]
    pam50 = {"omics": finding_key(pf, "omics", "subtype", "PAM50")}
    if sub.get("published") and not sub["agrees"]:
        out.append(look(
            "PAM50", f"PAM50 {SUBTYPES[sub['call']]} {published(sub)}", "the same method agrees "
            "with the published calls for most tumors of this cohort; a differing call is worth "
            "a look at its correlations", INFERENCE, "moderate", 1, opens, source=ASSAYS["rna"],
            key=finding_key(pf, "omics", "subtype", "PAM50"), focus=pam50,
            threshold="nearest centroid, experimentally validated on this cohort"))
    elif sub["margin"] < LOW_MARGIN:
        out.append(look(
            "PAM50", f"PAM50 {SUBTYPES[sub['call']]} is borderline (margin {sub['margin']:.2f})",
            f"the call beats the runner-up by under {LOW_MARGIN} in correlation", INFERENCE,
            "weak", 1, opens, source=ASSAYS["rna"],
            key=finding_key(pf, "omics", "subtype", "PAM50"), focus=pam50,
            threshold=f"margin {LOW_MARGIN} (placeholder)"))
    pi3k = (cs.get("rppa") or {}).get("pathways", {}).get("PI3K/AKT")
    muts = pi3k_mutations(pf) if pi3k else []
    if muts and (pi3k[1] >= PATHWAY_HIGH or pi3k[1] <= PATHWAY_LOW):
        high, key = pi3k[1] >= PATHWAY_HIGH, finding_key(pf, "pathway_protein", "PI3K/AKT")
        out.append(look(
            "PI3K/AKT", f"{', '.join(muts)} with {'high' if high else 'low'} PI3K/AKT protein "
            f"activity ({ordinal(pi3k[1])} percentile)",
            ("the mutation (observed) and the pathway's phospho-proteins in the lysate point the "
             "same way" if high else "a PI3K-pathway mutation without raised phospho-AKT in the "
             "lysate: tumor content, the RPPA batch, or a variant of weak effect (its predicted "
             "effect is in the genomics workbench)")
            + "; the variant's CIViC evidence is in the genomics workbench, for clinician review",
            f"{OBSERVED} (mutation), {INFERENCE} (pathway score)", "moderate" if high else "weak",
            1, opens, source=f"{ASSAYS['protein']} and the tumor's sequencing", key=key,
            focus={"omics": key}, threshold=f"high from the {ordinal(PATHWAY_HIGH)}, low to the "
            f"{ordinal(PATHWAY_LOW)} percentile of this cohort (placeholders)"))
    rec = cs.get("receptors") or {}
    for x in methylation_lines(cs):
        receptor = {"ESR1": "ER", "PGR": "PR"}.get(x["gene"])
        against = receptor and (rec.get(receptor) or {}).get("status") == "Positive"
        if not x["methylated"] or not (x["gene"] == "BRCA1" or against):
            continue
        key = finding_key(pf, "methylation", x["gene"])
        out.append(look(
            f"{x['gene']} promoter", f"{x['gene']} promoter methylated" + (
                f" while {receptor} is IHC positive" if against else ""),
            x["text"] + (" BRCA1 germline testing and a homologous-recombination assay are the "
                         "clinical tests." if x["gene"] == "BRCA1" else
                         " IHC reads the protein in the tumor cells; the array reads the whole "
                         "sample's DNA."),
            f"{OBSERVED} (beta); call at a placeholder cutoff", "weak", 1, opens,
            source=ASSAYS["methylation"], key=key, focus={"omics": key},
            threshold=f"methylated from a mean promoter beta of {METHYLATED} (placeholder)"))
    return out
