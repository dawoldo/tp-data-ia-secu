"""Synthetic scans: native PDFs turned into images that look like the real scans.

Their exact content is known from the text layer. The degradation copies what was
measured on the 50 real scans: 200 dpi grey JPEG, skew, blur, background, noise.
Deterministic: the same PDF always gives the same file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pymupdf

DPI = 200
WIDTH, HEIGHT = 1654, 2339          # A4 at 200 dpi, as the real scans
JPEG_QUALITY = 75


def _blur(a: np.ndarray) -> np.ndarray:
    """Slight blur; the weight gives the noise correlation of the real scans (0.57)."""
    for axis in (0, 1):
        a = 0.21 * np.roll(a, 1, axis) + 0.58 * a + 0.21 * np.roll(a, -1, axis)
    return a


def make_scan(pdf: bytes) -> bytes:
    rng = np.random.default_rng(int.from_bytes(hashlib.sha256(pdf).digest()[:8], "big"))
    out = pymupdf.open()
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        for page in doc:
            angle = float(np.clip(rng.normal(0.2, 0.57), -1.5, 1.6))
            zoom = DPI / 72
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom).prerotate(angle),
                                  colorspace=pymupdf.csGRAY)
            full = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)
            image = np.full((HEIGHT, WIDTH), 255.0)
            top, left = (pix.height - HEIGHT) // 2, (pix.width - WIDTH) // 2
            rows, cols = min(HEIGHT, pix.height), min(WIDTH, pix.width)
            y, x = max(top, 0), max(left, 0)
            image[:rows, :cols] = full[y:y + rows, x:x + cols]
            background = rng.uniform(237, 253)
            image = _blur(image) * background / 255
            image += _blur(rng.normal(0, 5.6, image.shape))
            samples = np.clip(image, 0, 255).astype(np.uint8).tobytes()
            scan = pymupdf.Pixmap(pymupdf.csGRAY, WIDTH, HEIGHT, samples, False)
            new = out.new_page(width=page.rect.width, height=page.rect.height)
            new.insert_image(new.rect, stream=scan.tobytes("jpeg", jpg_quality=JPEG_QUALITY))
    return out.tobytes(no_new_id=True)


def pick(sources: list[str], count: int) -> list[str]:
    """Deterministic sample, spread over suppliers (prefix of the invoice number)."""
    groups: dict[str, list[str]] = {}
    for name in sorted(sources, key=lambda n: hashlib.sha256(n.encode()).hexdigest()):
        groups.setdefault(name.split("-")[0], []).append(name)
    picked: list[str] = []
    while len(picked) < min(count, len(sources)):
        for group in sorted(groups):
            if groups[group] and len(picked) < count:
                picked.append(groups[group].pop(0))
    return sorted(picked)


def prepare(landing: Path, names: list[str], out: Path) -> dict[str, str]:
    """Create the missing scans; return scan name -> native source."""
    out.mkdir(parents=True, exist_ok=True)
    scans = {}
    for name in names:
        scan = name.replace("_texte.pdf", "_synth.pdf")
        path = out / scan
        if not path.exists():
            tmp = path.with_suffix(".part")
            tmp.write_bytes(make_scan((landing / name).read_bytes()))
            tmp.replace(path)
        scans[scan] = name
    return scans
