"""CIViC treatment evidence for a patient's observed variants (civicdb.org, CC0).

Evidence for clinician review, never a recommendation. Loads CIViC's nightly clinical evidence
summaries (downloaded once, cached under data/raw/civic/) and returns accepted therapy-related
("Predictive") evidence items for a gene + protein change in a disease: exact variant matches
first ("PIK3CA H1047R"), then gene-level profiles ("PIK3CA Mutation"); within each, the
strongest evidence level first (A validated ... E inferential), then the curators' rating.
Every item keeps its level, significance, citation and CIViC link.
"""

from __future__ import annotations

import urllib.request
from functools import lru_cache
from pathlib import Path

import pandas as pd

URL = "https://civicdb.org/downloads/nightly/nightly-ClinicalEvidenceSummaries.tsv"
CACHE = Path("data/raw/civic/nightly-ClinicalEvidenceSummaries.tsv")
LEVELS = {"A": "validated association", "B": "clinical evidence", "C": "case study",
          "D": "preclinical", "E": "inferential"}
GENE_LEVEL = ("Mutation", "Oncogenic Mutation")


@lru_cache(maxsize=4)
def load_table(path: str = str(CACHE), download: bool = True) -> pd.DataFrame | None:
    """Accepted Predictive evidence items, or None if not cached and ``download`` is False."""
    p = Path(path)
    if not p.exists():
        if not download:
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        part = p.with_name(p.name + ".part")
        urllib.request.urlretrieve(URL, part)
        part.rename(p)
    t = pd.read_csv(p, sep="\t", dtype=str).fillna("")
    return t[(t["evidence_status"] == "accepted") & (t["evidence_type"] == "Predictive")]


def evidence(gene: str, change: str, disease: str = "breast", k: int = 3,
             table: pd.DataFrame | None = None) -> list[dict]:
    """Up to ``k`` evidence items for ``gene`` with protein ``change`` ("H1047R" or "p.H1047R")
    in diseases whose name contains ``disease``."""
    t = load_table() if table is None else table
    if t is None or t.empty:
        return []
    variant = change.removeprefix("p.")
    d = t[t["disease"].str.contains(disease, case=False, regex=False)]
    parts = (("this variant", d[d["molecular_profile"] == f"{gene} {variant}"]),
             ("any mutation in the gene",
              d[d["molecular_profile"].isin([f"{gene} {g}" for g in GENE_LEVEL])]))
    out = []
    for match, part in parts:
        part = part.assign(_level=part["evidence_level"].map(lambda v: "ABCDE".find(v) % 6),
                           _rating=pd.to_numeric(part["rating"], errors="coerce").fillna(0))
        for _, r in part.sort_values(["_level", "_rating"], ascending=[True, False]).iterrows():
            out.append({"molecular_profile": r["molecular_profile"], "match": match,
                        "therapies": r["therapies"] or "none named",
                        "evidence_level": r["evidence_level"],
                        "level_meaning": LEVELS.get(r["evidence_level"], "unknown"),
                        "significance": r["significance"], "direction": r["evidence_direction"],
                        "disease": r["disease"], "citation": r["citation"],
                        "url": r["evidence_civic_url"]})
    return out[:k]
