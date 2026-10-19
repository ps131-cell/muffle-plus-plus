"""CIViC treatment evidence for a patient's observed variants (civicdb.org, CC0).

Evidence for clinician review, never a recommendation. Loads CIViC's nightly clinical evidence
summaries (downloaded once, cached under data/raw/civic/) and returns accepted therapy-related
("Predictive") evidence items for a gene + protein change in a disease. A molecular profile
matches when it is the variant itself ("PIK3CA H1047R"), a disjunction of alternatives that
includes it ("PIK3CA H1047R OR PIK3CA H1047Y OR PIK3CA H1047L"), or a gene-level profile
("PIK3CA Mutation", also inside a disjunction); profiles joined with AND or NOT never match.
All matches are ranked together by evidence level (A validated ... E inferential), then the
curators' rating, then how specific the match is (the variant, a disjunction covering it, the
gene), and only then cut to ``k``. Every item keeps its level, significance, citation and
CIViC link.
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


def _match(profile: str, gene: str, variant: str) -> tuple[int, str] | None:
    """(specificity rank, match text) for a CIViC molecular profile, or None if it does not
    cover ``gene variant``. CIViC writes compound profiles as alternatives joined by " OR "
    (each repeating the gene symbol) or conjunctions with " AND " / " AND NOT "."""
    if " AND " in profile or " NOT " in profile:
        return None
    alts = profile.split(" OR ")
    target, gene_level = f"{gene} {variant}", {f"{gene} {g}" for g in GENE_LEVEL}
    if target in alts:
        rank, text = 0, "this variant"
    elif gene_level & set(alts):
        rank, text = 2, "any mutation in the gene"
    else:
        return None
    others = [a.removeprefix(f"{gene} ") for a in alts if a != target and a not in gene_level]
    if others:  # a disjunction: the item also covers other alterations
        rank += 1
        text += f" (the profile also covers {', '.join(others)})"
    return rank, text


def evidence(gene: str, change: str, disease: str = "breast", k: int = 3,
             table: pd.DataFrame | None = None) -> list[dict]:
    """Up to ``k`` evidence items for ``gene`` with protein ``change`` ("H1047R" or "p.H1047R")
    in diseases whose name contains ``disease``, strongest evidence first."""
    t = load_table() if table is None else table
    if t is None or t.empty:
        return []
    variant = change.removeprefix("p.")
    d = t[t["disease"].str.contains(disease, case=False, regex=False)]
    matches = d["molecular_profile"].map(lambda p: _match(p, gene, variant))
    d = d[matches.notna()]
    d = d.assign(_rank=matches.dropna().map(lambda m: m[0]),
                 _match=matches.dropna().map(lambda m: m[1]),
                 _level=d["evidence_level"].map(lambda v: "ABCDE".find(v) % 6),
                 _rating=pd.to_numeric(d["rating"], errors="coerce").fillna(0))
    d = d.sort_values(["_level", "_rating", "_rank"], ascending=[True, False, True]).head(k)
    return [{"molecular_profile": r["molecular_profile"], "match": r["_match"],
             "therapies": r["therapies"] or "none named",
             "evidence_level": r["evidence_level"],
             "level_meaning": LEVELS.get(r["evidence_level"], "unknown"),
             "significance": r["significance"], "direction": r["evidence_direction"],
             "disease": r["disease"], "citation": r["citation"], "url": r["evidence_civic_url"]}
            for _, r in d.iterrows()]
