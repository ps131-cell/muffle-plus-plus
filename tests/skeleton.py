"""The page skeleton every workbench follows (docs/ux.md), checked on a page AppTest rendered:
the parts the page recorded come in ``grammar.SKELETON``'s order, the required ones are there,
and their headings appear in that order in the rendered page."""

from muffle.workbench.grammar import REQUIRED, SKELETON


def headings(at) -> list[str]:
    """The main area's subheaders, '####' headings and expander labels, in page order."""
    out: list[str] = []

    def walk(node) -> None:
        kind = getattr(node, "type", None)
        if kind == "subheader":
            out.append(node.value)
        elif kind == "markdown" and str(node.value).startswith("#### "):
            out.append(node.value[5:])
        elif kind == "expander":
            out.append(node.label)
        children = getattr(node, "children", None) or {}
        for k in sorted(children):
            walk(children[k])

    walk(at.main)
    return out


def assert_skeleton(at, workbench: str) -> list[tuple[str, str]]:
    """The page ``workbench`` drew follows the skeleton; returns its parts."""
    parts = at.session_state["page_parts"][workbench]
    names = [p for p, _ in parts]
    ranks = [SKELETON.index(p) for p in names]
    assert ranks == sorted(ranks), (workbench, names)
    assert all(names.count(p) == 1 for p in set(names) if p != "details"), (workbench, names)
    assert all(p in names for p in REQUIRED), (workbench, names)
    seen = iter(headings(at))
    wanted = [h for p, h in parts if p != "chips"]
    assert all(any(h == s for s in seen) for h in wanted), (workbench, wanted, headings(at))
    return parts
