"""Modules loaded on first use, for a faster first screen: the patient list draws no chart and
needs none of scipy, so Altair (through the chart and workbench page modules) and scipy load when
a page first uses them, or in the background once the first screen is drawn
(``app/streamlit_app.py``'s last lines). docs/qa.md, "Cold-start pass (2026-10-28)".
"""

from __future__ import annotations

import importlib


class Module:
    """Stands in for ``import <name>``: the module is imported on the first attribute read
    (``charts.contributions``), then each read is a lookup in ``sys.modules``, so a module the
    hot-update guard purged (``muffle.hotreload``) is imported afresh, as a plain import would."""

    __slots__ = ("_name",)

    def __init__(self, name: str):
        self._name = name

    def __getattr__(self, attr: str):
        return getattr(importlib.import_module(self._name), attr)

    def __repr__(self) -> str:
        return f"<module {self._name!r}, loaded on first use>"


def module(name: str) -> Module:
    return Module(name)
