"""Build the hosted demo's bundle -> outputs/demo_bundle.pt (git-ignored; a release asset).

It holds the model weights and, for ~40 held-out patients (every one with a saved note, plus a
spread over the risk range), their model inputs. Everything else is derived: cohort risks,
offsets, per-site C-index, and risk-group survival curves. No other patient-level data.

python scripts/make_demo_bundle.py
gh release create demo-bundle-v2 outputs/demo_bundle.pt --title "Demo bundle v2" --notes "..."
# then bump BUNDLE_RELEASE in app/streamlit_app.py (the hosted app pins the tag) and reboot it.

Cases carry their sequenced driver mutations (``Case.mutations``, GDC open-access calls); a
bundle written before that field existed loads with ``mutations=None`` ("not sequenced").
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from muffle.demo import build_demo, load_bundle, pick_cases, save_bundle, subset


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default="outputs/tcga_fedavg.pt")
    p.add_argument("--data", default="data/tcga_brca")
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--cases", type=int, default=40)
    p.add_argument("--notes", type=Path, default=Path("app/saved_notes.json"))
    p.add_argument("--out", type=Path, default=Path("outputs/demo_bundle.pt"))
    a = p.parse_args(argv)

    demo = build_demo(a.ckpt, a.data, a.n_clients)
    keep = [int(k) for k in json.loads(a.notes.read_text())] if a.notes.exists() else []
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
