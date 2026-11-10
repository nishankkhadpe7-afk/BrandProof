"""Round 3 · OCR for creatives and scanned PDFs.

Reads text inside banners and scanned pages, keeps a bounding box for every word,
and maps each text finding back to an image region so the reviewer sees exactly
where on the creative the problem is.

Engines (first available wins):
  1. Tesseract via pytesseract (word boxes)     -- install tesseract-ocr; Docker image includes it
  2. Gemini vision (text only, no boxes)        -- when LLM_PROVIDER=gemini
  3. none                                       -- visual checks still run; the finding list says OCR was unavailable
"""
from __future__ import annotations

import base64
import io
import logging
import os
import shutil

import httpx

from . import llm

log = logging.getLogger("brandproof.ocr")
MIN_CONF = 55
MAX_PDF_PAGES = 10
_WIN_PATHS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]


def _tesseract():
    try:
        import pytesseract
    except ImportError:
        return None
    cmd = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract") or next((p for p in _WIN_PATHS if os.path.exists(p)), None)
    if not cmd:
        return None
    pytesseract.pytesseract.tesseract_cmd = cmd
    return pytesseract


def engine() -> str | None:
    if os.environ.get("OCR_DISABLED") == "1":
        return None
    if _tesseract():
        return "tesseract"
    if llm.provider() == "gemini":
        return "gemini-vision"
    return None


def _tess_words(img, page: int):
    pt = _tesseract()
    scale = 1.0
    work = img
    if max(img.size) < 1400:  # upscale small creatives; tesseract likes ~30px glyphs
        scale = 1400 / max(img.size)
        work = img.resize((int(img.width * scale), int(img.height * scale)))
    best = None
    for psm in (3, 11):  # 3 = layout analysis, 11 = sparse text (banners)
        d = pt.image_to_data(work.convert("L"), output_type=pt.Output.DICT, config=f"--psm {psm}")
        words = []
        for i, w in enumerate(d["text"]):
            w = (w or "").strip()
            try:
                conf = float(d["conf"][i])
            except ValueError:
                conf = -1
            if not w or conf < MIN_CONF:
                continue
            words.append({"text": w, "conf": conf, "line": (d["block_num"][i], d["par_num"][i], d["line_num"][i]),
                          "x": int(d["left"][i] / scale), "y": int(d["top"][i] / scale),
                          "w": max(1, int(d["width"][i] / scale)), "h": max(1, int(d["height"][i] / scale))})
        if best is None or len(words) > len(best):
            best = words
    return best or []


def ocr_image(img, page: int = 0, offset: int = 0) -> tuple[str, list[dict], str | None]:
    """Return (text, words-with-char-offsets, engine)."""
    eng = engine()
    if eng == "tesseract":
        try:
            words = _tess_words(img, page)
        except Exception as e:
            log.warning("tesseract failed: %s", e)
            words, eng = [], None
        parts, out, pos, last_line = [], [], offset, None
        for w in words:
            sep = "" if last_line is None else (" " if w["line"] == last_line else "\n")
            parts.append(sep + w["text"])
            pos += len(sep)
            out.append({"start": pos, "end": pos + len(w["text"]), "x": w["x"], "y": w["y"], "w": w["w"], "h": w["h"],
                        "page": page, "img_w": img.width, "img_h": img.height, "conf": round(w["conf"])})
            pos += len(w["text"])
            last_line = w["line"]
        return "".join(parts), out, eng
    if eng == "gemini-vision":
        return _gemini_text(img), [], eng
    return "", [], None


def _gemini_text(img) -> str:
    key = os.environ.get("GEMINI_API_KEY", "")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    try:
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{os.environ.get('LLM_MODEL') or 'gemini-2.5-flash'}:generateContent",
                       headers={"x-goog-api-key": key}, timeout=30,
                       json={"contents": [{"role": "user", "parts": [
                           {"text": "Transcribe all visible text in this image exactly, line by line. Output only the text."},
                           {"inline_data": {"mime_type": "image/png", "data": base64.b64encode(buf.getvalue()).decode()}}]}],
                             "generationConfig": {"temperature": 0}})
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception as e:
        log.warning("gemini OCR failed: %s", str(e).replace(key, "***") if key else e)
        return ""


def read_pdf(data: bytes) -> dict:
    """Text layer first; pages without one are rendered and OCR'd. Returns text, words, page images, engine."""
    import pymupdf
    from PIL import Image

    text_parts, words, images, eng_used = [], [], [], None
    pos = 0
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for pno, page in enumerate(doc):
            if pno >= MAX_PDF_PAGES:
                break
            if text_parts:
                text_parts.append("\n")
                pos += 1
            layer = page.get_text().strip()
            if len(layer) >= 25:
                text_parts.append(layer)
                pos += len(layer)
                continue
            pix = page.get_pixmap(dpi=150)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            page_idx = len(images)
            images.append(img)
            t, ws, eng = ocr_image(img, page=page_idx, offset=pos)
            eng_used = eng_used or eng
            text_parts.append(t)
            words += ws
            pos += len(t)
    return {"text": "".join(text_parts), "words": words, "images": images, "engine": eng_used, "scanned": bool(images)}


def region_for(start: int, end: int, words: list[dict]) -> dict | None:
    """Union box of OCR words overlapping [start, end) on the first page they appear."""
    hit = [w for w in words if w["start"] < end and start < w["end"]] if end > start else []
    if not hit:
        return None
    page = hit[0]["page"]
    hit = [w for w in hit if w["page"] == page]
    x0 = min(w["x"] for w in hit)
    y0 = min(w["y"] for w in hit)
    x1 = max(w["x"] + w["w"] for w in hit)
    y1 = max(w["y"] + w["h"] for w in hit)
    pad = 4
    return {"x": max(0, x0 - pad), "y": max(0, y0 - pad), "w": x1 - x0 + 2 * pad, "h": y1 - y0 + 2 * pad,
            "img_w": hit[0]["img_w"], "img_h": hit[0]["img_h"], "page": page, "source": "ocr"}
