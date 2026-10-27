import gc
from dataclasses import dataclass

from muffle import memo


@dataclass
class File:
    id: str


def test_per_file_computes_once_per_file_and_arguments_and_hands_out_copies():
    seen = []

    @memo.per_file
    def summary(pf, version=None, lookup=None):
        seen.append((pf.id, version))
        return {"cards": [{"what": pf.id, "version": version}]}

    a, b = File("A"), File("B")
    first = summary(a, 1)
    first["cards"].append("changed by a caller")
    assert summary(a, 1) == {"cards": [{"what": "A", "version": 1}]}  # the caller's change stays
    assert summary(a, 1) is not summary(a, 1)
    summary(a, 2), summary(b, 1), summary(a, 1, lookup=len)
    assert seen == [("A", 1), ("A", 2), ("B", 1), ("A", 1)]
    assert summary(File("A"), 1)["cards"][0]["what"] == "A"  # another file object: its own
    assert len(seen) == 5


def test_per_file_never_keeps_results_by_a_lambda_or_an_unhashable_argument():
    n = []

    @memo.per_file
    def queue(pf, version=None, lookup=None, hs=None):
        n.append(1)
        return []

    pf = File("A")
    queue(pf, 0, lookup=lambda v: v)
    queue(pf, 0, lookup=lambda v: v)
    queue(pf, 0, hs={"items": []})
    queue(pf, 0, hs={"items": []})
    assert len(n) == 4


def test_a_files_results_go_with_it():
    @memo.per_file
    def summary(pf, version=None):
        return {"what": pf.id}

    pf = File("gone")
    summary(pf, 0)
    assert id(pf) in memo._files
    key = id(pf)
    del pf
    gc.collect()
    assert key not in memo._files


def test_calls_keeps_results_by_argument_and_hands_out_copies():
    n = []

    @memo.calls
    def lookup(gene, change, k=3):
        n.append(1)
        return [{"gene": gene, "change": change, "k": k}]

    got = lookup("PIK3CA", "H1047R")
    got[0]["gene"] = "changed"
    assert lookup("PIK3CA", "H1047R") == [{"gene": "PIK3CA", "change": "H1047R", "k": 3}]
    lookup("PIK3CA", "H1047R", k=5)
    assert len(n) == 2
