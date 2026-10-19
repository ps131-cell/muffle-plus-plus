"""Download MSK-CHORD (cBioPortal msk_chord_2024, ~47 MB) into data/raw/msk_chord/ (git-ignored).

MSK-CHORD is CC BY-NC-ND 4.0 (Jee et al., Nature 2024): local use only; never commit, host or
share individual patients. Only code and aggregate results are published (docs/longitudinal.md).
"""

import tarfile
import urllib.request
from pathlib import Path

URL = "https://datahub.assets.cbioportal.org/msk_chord_2024.tar.gz"
RAW = Path("data/raw/msk_chord")

if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    tgz = RAW / "msk_chord_2024.tar.gz"
    if not tgz.exists():
        urllib.request.urlretrieve(URL, tgz.with_name(tgz.name + ".part"))
        tgz.with_name(tgz.name + ".part").rename(tgz)
    with tarfile.open(tgz) as t:
        t.extractall(RAW / "extract", filter="data")  # data filter: no links or paths outside
    print(f"-> {RAW / 'extract' / 'msk_chord_2024'}")
