"""Build the hosted demo's bundle -> outputs/demo_bundle.pt (git-ignored; a release asset).

It holds the model weights and, for ~40 held-out patients (every one with a saved note, plus a
spread over the risk range), their model inputs. Everything else is derived: cohort risks,
offsets, per-site C-index, and risk-group survival curves. No other patient-level data.

python scripts/make_demo_bundle.py
python scripts/make_demo_bundle.py --base outputs/demo_bundle_v1.pt   # v1 plus observed mutations
gh release create demo-bundle-v2 outputs/demo_bundle.pt --title "Demo bundle v2" --notes "..."
# then bump BUNDLE_RELEASE in app/streamlit_app.py (the hosted app pins the tag) and reboot it.

Cases carry their sequenced driver mutations (``Case.mutations``, GDC open-access calls); a
bundle written before that field existed loads with ``mutations=None`` ("not sequenced").

``--base`` keeps a published bundle's model, cases and every number, and only adds each case's
mutations from --data's cohort. A cohort rebuilt later can differ slightly (on 2026-10-19 the
GDC copy-number file had changed one of 200 genes), so this keeps the demo's numbers as published.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from muffle.demo import (
    build_demo,
    load_bundle,
    pick_cases,
    save_bundle,
    sequenced_mutations,
    subset,
)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default="outputs/tcga_fedavg.pt")
    p.add_argument("--data", default="data/tcga_brca")
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--cases", type=int, default=40)
    p.add_argument("--notes", type=Path, default=Path("app/saved_notes.json"))
    p.add_argument("--out", type=Path, default=Path("outputs/demo_bundle.pt"))
    p.add_argument("--base", type=Path, default=None,
                   help="keep this bundle's model, cases and numbers; only add each case's "
                        "sequenced driver mutations from --data's cohort")
    a = p.parse_args(argv)

    keep = [int(k) for k in json.loads(a.notes.read_text())] if a.notes.exists() else []
    if a.base:
        small = load_bundle(a.base)
        with np.load(Path(a.data) / "cohort.npz") as f:
            cohort = {k: f[k] for k in ("x_clinical", "mut_status", "mut_changes")}
        for c in small.cases:  # the same row must be the same patient in both
            if not np.allclose(small.x["clinical"][c.row].numpy(), cohort["x_clinical"][c.index],
                               atol=1e-5):
                raise SystemExit(f"case {c.index}: {a.data}'s cohort doesn't match {a.base}")
            c.mutations = sequenced_mutations(cohort, c.index)
    else:
        demo = build_demo(a.ckpt, a.data, a.n_clients)
        small = subset(demo, pick_cases(demo, a.cases, keep))
    save_bundle(small, a.out)
    check = load_bundle(a.out)  # what the app will see
    assert [c.index for c in check.cases] == [c.index for c in small.cases]
    missing = [i for i in keep if i not in {c.index for c in check.cases}]
    digest = hashlib.sha256(a.out.read_bytes()).hexdigest()[:16]
    print(f"wrote {a.out}: {a.out.stat().st_size / 1e6:.1f} MB, {len(check.cases)} of "
          f"{check.heldout_patients} held-out cases, sha256 {digest}"
          + (f"; saved notes without a case: {missing}" if missing else ""))


if __name__ == "__main__":
    main()
