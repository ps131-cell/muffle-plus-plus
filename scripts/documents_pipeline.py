"""The clinical documents' local pipeline: the models the hosted app does not run.

    # the model's reading of the bundled reports -> app/documents/<barcode>.ner.json
    python scripts/documents_pipeline.py ner --docs app/documents
    # the same on the held-out half of TCGA-Reports, for the measurement (kept local)
    python scripts/documents_pipeline.py ner --half test \
        --clinical ~/muffle-documents/xena/BRCA_clinicalMatrix \
        --reports ~/muffle-documents/download/TCGA_Reports.csv \
        --out ~/muffle-documents2/out/ner_reports.json
    # a scanned report (a PDF without a text layer): text, the rules' facts, the model's spans
    python scripts/documents_pipeline.py scan report.pdf --out ~/muffle-documents2/out/scans
    # text accuracy of the scan reader on page images whose text is known
    python scripts/documents_pipeline.py scan-eval --pdf <image-only PDF> --truth <text> ...

Models (both Apache-2.0, docs/registry.md), run on a local CPU only, never in the hosted app:
  * OpenMed/OpenMed-ZeroShot-NER-Oncology-Base-220M (GLiNER; ``muffle.workbench.documents
    .NER_LABELS`` are its zero-shot labels, ``NER_THRESHOLD`` its score cut). Only derived spans
    are written (label, start, end, score); the text stays where it was.
  * ibm-granite/granite-docling-258M (an Idefics3 page-to-DocTags model), for page images.

Needs ``gliner``, ``transformers``, ``torch`` (CPU), ``docling-core``, ``pypdfium2``, ``pypdf``
and ``rapidfuzz`` in its own environment (not the app's): see docs/documents.md. No report text
leaves the machine (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from muffle.workbench.documents import (  # noqa: E402
    NER_LABELS,
    NER_LICENSE,
    NER_MODEL,
    NER_THRESHOLD,
    extract,
    measurement_half,
    sentences,
)

NER_REVISION = "147a2d914ce0659133607f1c39e035fb7f0c24c6"
OCR_MODEL = "ibm-granite/granite-docling-258M"
OCR_REVISION = "982fe3b40f2fa73c365bdb1bcacf6c81b7184bfe"
CHUNK = 1500  # characters per model call: whole sentences, well under GLiNER's 1,024 words


def _threads() -> int:
    import torch

    n = int(os.environ.get("OMP_NUM_THREADS", "2"))
    torch.set_num_threads(n)
    return n


def load_ner():
    """The GLiNER model. Its config asks for gliner's "universal" splitter, which newer gliner
    releases turned into a multilingual one needing Korean and Chinese tokenizers; these reports
    are English, and the English splitter is the regex the model was trained with."""
    import gliner.data_processing.tokenizer as tk

    tk.MultiLangWordsSplitter = tk.WhitespaceTokenSplitter
    from gliner import GLiNER

    return GLiNER.from_pretrained(NER_MODEL, revision=NER_REVISION)


def chunks(text: str, size: int = CHUNK) -> list[tuple[int, int]]:
    """(start, end) pieces of ``text`` made of whole sentences, at most ``size`` characters (a
    longer sentence is cut at a space)."""
    out, a, b = [], None, None
    for s, e in sentences(text):
        while e - s > size:  # one long OCR line: cut it at the last space before the limit
            cut = text.rfind(" ", s, s + size)
            cut = cut if cut > s else s + size
            if a is not None:
                out.append((a, b))
                a = None
            out.append((s, cut))
            s = cut
        if a is None:
            a, b = s, e
        elif e - a <= size:
            b = e
        else:
            out.append((a, b))
            a, b = s, e
    if a is not None:
        out.append((a, b))
    return out


def spans(model, text: str) -> list[dict]:
    """The model's spans in ``text`` at ``NER_THRESHOLD``: [{"label", "start", "end", "score"}]."""
    out = []
    for a, b in chunks(text):
        for e in model.predict_entities(text[a:b], list(NER_LABELS), threshold=NER_THRESHOLD,
                                        flat_ner=True):
            out.append({"label": e["label"], "start": a + e["start"], "end": a + e["end"],
                        "score": round(float(e["score"]), 3)})
    return out


def run_ner(model, docs: dict[str, str]) -> tuple[dict[str, list[dict]], dict]:
    """Spans for each document id -> text, and the run's record (time, size, CPU load)."""
    load = os.getloadavg()[0]
    t0, out = time.perf_counter(), {}
    for doc, text in docs.items():
        out[doc] = spans(model, text)
    secs = time.perf_counter() - t0
    chars = sum(map(len, docs.values()))
    return out, {"date": date.today().isoformat(), "documents": len(docs), "characters": chars,
                 "seconds": round(secs, 1), "seconds_per_1000_characters":
                 round(1000 * secs / chars, 2) if chars else None, "threads": _threads(),
                 "load_before": round(load, 1), "load_after": round(os.getloadavg()[0], 1),
                 "machine": "WSL2 on the team's Windows PC, CPU only"}


def ner_header(run: dict) -> dict:
    return {"model": NER_MODEL, "revision": NER_REVISION, "license": NER_LICENSE,
            "labels": NER_LABELS, "threshold": NER_THRESHOLD, "run": run,
            "note": "Derived spans only (label, start, end, score) over the document text in the "
                    "matching <barcode>.json; the model itself is not shipped or run here."}


def cmd_ner(a) -> None:
    model = load_ner()
    _threads()
    if a.docs:  # the bundled reports: one .ner.json beside each report file
        for p in sorted(a.docs.glob("TCGA-*.json")):
            if p.name.endswith(".ner.json"):
                continue
            d = json.loads(p.read_text(encoding="utf-8"))
            got, run = run_ner(model, {x["id"]: x["text"] for x in d["documents"]})
            (a.docs / f"{d['barcode']}.ner.json").write_text(json.dumps(
                {"barcode": d["barcode"], **ner_header(run), "documents": got}, indent=1) + "\n",
                encoding="utf-8")
            print(f"{d['barcode']}: {sum(map(len, got.values()))} spans, {run['seconds']} s, "
                  f"load {run['load_before']}")
        return
    csv.field_size_limit(10**9)
    with open(a.clinical, newline="") as f:  # TCGA-Reports covers every cancer: BRCA only
        brca = {r["sampleID"][:12] for r in csv.DictReader(f, delimiter="\t")
                if r["sampleID"].endswith("-01")}
    docs, of = {}, {}
    with open(a.reports, newline="") as f:
        for r in csv.DictReader(f):
            bc = r["patient_filename"][:12]
            if bc in brca and measurement_half(bc) == a.half:
                docs[r["patient_filename"]], of[r["patient_filename"]] = r["text"], bc
    got, run = run_ner(model, docs)
    by_patient: dict[str, dict] = {}
    for doc, sp in got.items():
        by_patient.setdefault(of[doc], {})[doc] = sp
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps({**ner_header(run), "half": a.half, "patients": by_patient}))
    print(json.dumps(run))


# ------------------------------------------------------------------------- scanned reports

def pdf_pages(data: bytes, scale: float) -> list:
    """The PDF's pages as RGB images (pypdfium2), ``scale`` x 72 dpi."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    return [pdf[i].render(scale=scale).to_pil().convert("RGB") for i in range(len(pdf))]


def text_layer(data: bytes) -> str:
    from pypdf import PdfReader

    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).strip()


def load_ocr():
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    proc = AutoProcessor.from_pretrained(OCR_MODEL, revision=OCR_REVISION)
    # float32: the checkpoint's bfloat16 runs ~10x slower on a CPU without bf16 matmuls
    model = AutoModelForImageTextToText.from_pretrained(OCR_MODEL, revision=OCR_REVISION,
                                                        dtype=torch.float32)
    return proc, model.eval()


def read_page(proc, model, image, max_tokens: int = 4096) -> str:
    """One page image to text: granite-docling's DocTags, converted by docling-core."""
    import torch
    from docling_core.types.doc.document import DocTagsDocument, DoclingDocument

    ask = {"type": "text", "text": "Convert this page to docling."}  # the card's prompt
    messages = [{"role": "user", "content": [{"type": "image"}, ask]}]
    prompt = proc.apply_chat_template(messages, add_generation_prompt=True)
    inputs = proc(text=prompt, images=[image], return_tensors="pt")
    with torch.inference_mode():
        ids = model.generate(**inputs, max_new_tokens=max_tokens, do_sample=False,
                             use_cache=True)  # its generation config turns the cache off
    tags = proc.batch_decode(ids[:, inputs["input_ids"].shape[1]:],
                             skip_special_tokens=False)[0].lstrip()
    pair = DocTagsDocument.from_doctags_and_image_pairs([tags], [image])
    doc = DoclingDocument.load_from_doctags(pair, document_name="page")
    return doc.export_to_text().strip()


def bands_of(image, n: int) -> list:
    """A page cut into ``n`` horizontal bands, each cut at the whitest row within 4% of the
    page's height of the even cut, so no line of text is split; n = 1 keeps the page whole. A
    dense page read in bands is seen at twice the resolution (the model resizes each image to
    2,048 px on its longest edge)."""
    if n <= 1:
        return [image]
    import numpy as np

    rows = np.asarray(image.convert("L"), dtype=float).mean(axis=1)
    h, slack, cuts = image.height, int(0.04 * image.height), [0]
    for k in range(1, n):
        mid = k * h // n
        lo, hi = max(cuts[-1] + 1, mid - slack), min(h - 1, mid + slack)
        cuts.append(lo + int(np.argmax(rows[lo:hi + 1])))
    cuts.append(h)
    return [image.crop((0, a, image.width, b)) for a, b in zip(cuts, cuts[1:], strict=False)]


def looped(text: str) -> bool:
    """The reader repeated itself (a known failure on dense or noisy scans): one line makes up
    30% or more of 12 lines or more."""
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    return len(lines) >= 12 and max(lines.count(x) for x in set(lines)) >= 0.3 * len(lines)


def scan(proc, model, data: bytes, scale: float, bands: int = 1) -> dict:
    """A PDF to text: its own text layer when it has one, else each page (or each of its
    ``bands``) read by the model. "looped" flags text the reader repeated: read that scan by
    eye, its text is not a report."""
    layer = text_layer(data)
    pages = pdf_pages(data, scale)
    if layer:
        return {"text": layer, "pages": len(pages), "method": "the PDF's own text layer (pypdf)",
                "seconds": 0.0, "looped": False}
    t0 = time.perf_counter()
    text = "\n\n".join("\n".join(read_page(proc, model, b) for b in bands_of(im, bands))
                       for im in pages)
    return {"text": text, "pages": len(pages), "seconds": round(time.perf_counter() - t0, 1),
            "looped": looped(text),
            "method": f"{OCR_MODEL} ({OCR_REVISION[:7]}, Apache-2.0) on page images at "
                      f"{72 * scale:.0f} dpi" + (f", {bands} bands per page" if bands > 1
                                                 else "")}


def read_scanned(path: Path, scale: float, out: Path, ocr=None, ner=None, bands: int = 1) -> dict:
    """A scanned report through the pipeline: text, then the rules and the model exactly as a
    text report. Writes <name>.txt (import it as a report) and <name>.json (facts, spans)."""
    proc, model = ocr or load_ocr()
    got = scan(proc, model, path.read_bytes(), scale, bands)
    ner = ner or load_ner()
    got["facts"] = extract(got["text"], path.stem)
    got["ner"] = spans(ner, got["text"])
    got["ner_model"] = ner_header({"date": date.today().isoformat()})
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{path.stem}.txt").write_text(got["text"] + "\n", encoding="utf-8")
    (out / f"{path.stem}.json").write_text(json.dumps(got, indent=1, default=str),
                                           encoding="utf-8")
    return got


def cmd_scan(a) -> None:
    _threads()
    ocr, ner = load_ocr(), load_ner()
    for p in a.pdf:
        got = read_scanned(p, a.scale, a.out, ocr, ner, a.bands)
        print(f"{p.name}: {got['pages']} pages, {len(got['text'])} characters by {got['method']} "
              f"in {got['seconds']} s; {len(got['facts'])} facts, {len(got['ner'])} spans"
              + ("; THE READER LOOPED: read this scan by eye" if got["looped"] else ""))


def norm(text: str) -> str:
    """Text compared by its words: case and runs of whitespace ignored."""
    return re.sub(r"\s+", " ", text).strip().lower()


def accuracy(got: str, truth: str) -> dict:
    """Character accuracy 1 - edit distance / reference length and word accuracy, on
    normalized text (rapidfuzz's Levenshtein)."""
    from rapidfuzz.distance import Levenshtein

    g, t = norm(got), norm(truth)
    return {"characters": len(t),
            "char_accuracy": round(1 - Levenshtein.distance(g, t) / max(1, len(t)), 4),
            "word_accuracy": round(1 - Levenshtein.distance(g.split(), t.split())
                                   / max(1, len(t.split())), 4)}


def fact_agreement(got: str, truth: str) -> dict:
    """The rules' facts on the scan's text against the rules' facts on the reference text."""
    key = lambda t: {(f["field"], f["value"]) for f in extract(t)}  # noqa: E731
    g, t = key(got), key(truth)
    return {"facts_reference": len(t), "facts_scan": len(g), "facts_same": len(g & t)}


def render_scan(text: str, path: Path, width: int = 1700, margin: int = 110, size: int = 26,
                seed: int = 0) -> int:
    """A synthetic scan: ``text`` typeset on US-letter pages at 200 dpi (DejaVu Sans), slightly
    rotated, with speckle noise, saved as an image-only PDF. Returns the page count."""
    import random

    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    rnd = random.Random(seed)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
    height, line_h = int(width * 11 / 8.5), int(size * 1.45)
    per_line = int((width - 2 * margin) / (size * 0.56))
    lines = []
    for para in re.split(r"(?<=[.;])\s+(?=[A-Z0-9])", text):
        words, cur = para.split(), ""
        for w in words:
            if len(cur) + len(w) + 1 > per_line:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        lines.append(cur)
    per_page = (height - 2 * margin) // line_h
    pages = []
    for i in range(0, len(lines), per_page):
        im = Image.new("L", (width, height), 255)
        d = ImageDraw.Draw(im)
        for n, line in enumerate(lines[i:i + per_page]):
            d.text((margin, margin + n * line_h), line, fill=rnd.randint(0, 40), font=font)
        for _ in range(width * height // 4000):  # speckle
            d.point((rnd.randrange(width), rnd.randrange(height)), fill=rnd.randint(0, 120))
        im = im.rotate(rnd.uniform(-0.8, 0.8), fillcolor=255, resample=Image.BICUBIC)
        pages.append(im.filter(ImageFilter.GaussianBlur(0.6)).convert("RGB"))
    pages[0].save(path, save_all=True, append_images=pages[1:], resolution=200)
    return len(pages)


def cmd_scan_eval(a) -> None:
    """Text accuracy on known text: for each (image-only PDF, reference text) pair."""
    _threads()
    proc, model = load_ocr()
    rows = []
    for pdf, truth in zip(a.pdf, a.truth, strict=True):
        ref = truth.read_text(encoding="utf-8")
        got = scan(proc, model, pdf.read_bytes(), a.scale, a.bands)
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / f"{pdf.stem}.txt").write_text(got["text"], encoding="utf-8")
        rows.append({"file": pdf.name, "pages": got["pages"], "seconds": got["seconds"],
                     "method": got["method"], "looped": got["looped"], **accuracy(got["text"], ref),
                     **fact_agreement(got["text"], ref)})
        print(json.dumps(rows[-1]))
    (a.out / "scan_eval.json").write_text(json.dumps(
        {"date": date.today().isoformat(), "load": round(os.getloadavg()[0], 1), "rows": rows},
        indent=1))


def cmd_render(a) -> None:
    """Synthetic scans of shipped reports: an image-only PDF and the exact text it shows."""
    a.out.mkdir(parents=True, exist_ok=True)
    for p in a.report:
        d = json.loads(p.read_text(encoding="utf-8"))
        text = d["documents"][0]["text"][: a.chars]
        n = render_scan(text, a.out / f"{d['barcode']}-synthetic-scan.pdf")
        (a.out / f"{d['barcode']}-synthetic-scan.truth.txt").write_text(text, encoding="utf-8")
        print(f"{d['barcode']}: {n} pages, {len(text)} characters")


def cmd_strip(a) -> None:
    """A real report PDF as a scan: its pages rasterized and saved without the text layer."""
    a.out.mkdir(parents=True, exist_ok=True)
    for p in a.pdf:
        pages = pdf_pages(p.read_bytes(), a.scale)
        dest = a.out / f"{p.stem}-image-only.pdf"
        pages[0].save(dest, save_all=True, append_images=pages[1:], resolution=72 * a.scale)
        print(f"{p.name}: {len(pages)} pages -> {dest}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("ner")
    n.add_argument("--docs", type=Path)
    n.add_argument("--reports", type=Path)
    n.add_argument("--half", default="test", choices=["dev", "test"])
    n.add_argument("--clinical", type=Path, help="the BRCA clinical matrix (UCSC Xena): its "
                   "patients are the ones measured")
    n.add_argument("--out", type=Path)
    s = sub.add_parser("scan")
    s.add_argument("pdf", type=Path, nargs="+")
    s.add_argument("--scale", type=float, default=2.0)
    s.add_argument("--bands", type=int, default=1, help="read each page in this many bands")
    s.add_argument("--out", type=Path, required=True)
    e = sub.add_parser("scan-eval")
    e.add_argument("--pdf", type=Path, nargs="+", required=True)
    e.add_argument("--truth", type=Path, nargs="+", required=True)
    e.add_argument("--scale", type=float, default=2.0)
    e.add_argument("--bands", type=int, default=1)
    e.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("render")
    r.add_argument("report", type=Path, nargs="+")
    r.add_argument("--chars", type=int, default=2500)
    r.add_argument("--out", type=Path, required=True)
    t = sub.add_parser("strip")
    t.add_argument("pdf", type=Path, nargs="+")
    t.add_argument("--scale", type=float, default=2.0)
    t.add_argument("--out", type=Path, required=True)
    a = p.parse_args(argv)
    {"ner": cmd_ner, "scan": cmd_scan, "scan-eval": cmd_scan_eval, "render": cmd_render,
     "strip": cmd_strip}[a.cmd](a)


if __name__ == "__main__":
    main()
