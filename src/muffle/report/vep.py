"""Ensembl VEP (REST) for the genomics workbench's effect lookup: the consequence of a variant on
its MANE Select transcript, AlphaMissense's score as Ensembl serves it, and the ClinVar
classifications of the co-located variant record (germline clinical significance, somatic
oncogenicity).

Only a variant's name or its GRCh38 position and alleles are sent, never anything from a
patient's record. COSMIC and HGMD identifiers that Ensembl returns alongside are dropped
(COSMIC is excluded from this project, docs/model_survey.md §6). The app reads the bundled
snapshot (``app/genomics_effect.json``, scripts/genomics_effect.py) and calls Ensembl only for a
variant the snapshot lacks; a lookup that fails returns nothing, never a guess.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request

REST = "https://rest.ensembl.org"
OPTIONS = "AlphaMissense=1&canonical=1&mane=1&hgvs=1"
THREE = {"A": "Ala", "R": "Arg", "N": "Asn", "D": "Asp", "C": "Cys", "Q": "Gln", "E": "Glu",
         "G": "Gly", "H": "His", "I": "Ile", "L": "Leu", "K": "Lys", "M": "Met", "F": "Phe",
         "P": "Pro", "S": "Ser", "T": "Thr", "W": "Trp", "Y": "Tyr", "V": "Val", "*": "Ter"}


def hgvs_protein(variant: str) -> str | None:
    """"ESR1 D538G" -> "ESR1:p.Asp538Gly" for a single amino-acid substitution; None otherwise
    (a frameshift or splice change needs its genomic position)."""
    m = re.fullmatch(r"([A-Z0-9-]+) ([A-Z])(\d+)([A-Z*])", variant.strip())
    if not m or m.group(2) not in THREE or m.group(4) not in THREE:
        return None
    return f"{m.group(1)}:p.{THREE[m.group(2)]}{m.group(3)}{THREE[m.group(4)]}"


def region(chrom: str, pos: int, ref: str, alt: str, name: str) -> str:
    """VEP's region notation from a MAF-style call (insertions: ref "-", positions flank it;
    deletions: alt "-")."""
    if ref == "-":
        return f"{chrom} {pos + 1} {pos} -/{alt} + {name.replace(' ', '_')}"
    end = pos + len(ref) - 1
    return f"{chrom} {pos} {end} {ref}/{alt} + {name.replace(' ', '_')}"


def _post(path: str, body: dict, timeout: float, tries: int = 1) -> list[dict]:
    req = urllib.request.Request(f"{REST}{path}?{OPTIONS}", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "Accept": "application/json"})
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except Exception:
            if n == tries - 1:
                raise
            time.sleep(5 * (n + 1))  # Ensembl's REST service sheds load with 5xx at times
    return []


def query_regions(lines: list[str], timeout: float = 60, tries: int = 1) -> list[dict]:
    return _post("/vep/human/region", {"variants": lines}, timeout, tries)


def query_hgvs(notations: list[str], timeout: float = 60, tries: int = 1) -> list[dict]:
    return _post("/vep/human/hgvs", {"hgvs_notations": notations}, timeout, tries)


def release(timeout: float = 20) -> str:
    req = urllib.request.Request(f"{REST}/info/software?content-type=application/json")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return str(json.load(r).get("release", "?"))


def parse(record: dict) -> dict:
    """One VEP result -> {"consequence", "hgvsc", "hgvsp", "transcript", "mane", "position",
    "alphamissense", "clinvar"}: the MANE Select (else canonical) transcript's annotation, and
    ClinVar's classifications from the dbSNP-co-located record only."""
    tcs = record.get("transcript_consequences", [])
    t = (next((t for t in tcs if t.get("mane_select")), None)
         or next((t for t in tcs if t.get("canonical")), None) or (tcs[0] if tcs else {}))
    am = t.get("alphamissense")
    clin = {}
    for c in record.get("colocated_variants", []):
        if not str(c.get("id", "")).startswith("rs"):
            continue  # COSMIC (excluded) and HGMD records are not read
        vcv = [x for x in (c.get("var_synonyms") or {}).get("ClinVar", []) if x.startswith("VCV")]
        if c.get("clin_sig") or c.get("clinvar_somatic_classification") or vcv:
            som = sorted(set((c.get("clinvar_somatic_classification") or "").split(";")) - {""})
            clin = {"germline": sorted(set(c.get("clin_sig") or []) - {"not_provided"}),
                    "somatic": "; ".join(som),
                    "record": (vcv[0] if vcv else c["id"])}
            break
    return {
        "consequence": (t.get("consequence_terms") or [record.get("most_severe_consequence")])[0],
        "hgvsc": t.get("hgvsc"), "hgvsp": t.get("hgvsp"), "transcript": t.get("transcript_id"),
        "mane": t.get("mane_select"),
        "position": f"{record.get('seq_region_name')}:{record.get('start')} "
                    f"{record.get('allele_string')} (GRCh38)",
        "alphamissense": None if not am else {"score": am["am_pathogenicity"],
                                              "class": am["am_class"], "source": "Ensembl VEP"},
        "clinvar": clin,
    }


def lookup(variants: list[str], timeout: float = 12) -> dict[str, dict]:
    """Live annotation of substitution variants by name ("ESR1 D538G"), for variants the snapshot
    lacks; {} when Ensembl can't be reached."""
    names = {hgvs_protein(v): v for v in variants if hgvs_protein(v)}
    if not names:
        return {}
    try:
        out = query_hgvs(list(names), timeout)
    except Exception:
        return {}
    return {names[r["input"]]: parse(r) for r in out if r.get("input") in names}
