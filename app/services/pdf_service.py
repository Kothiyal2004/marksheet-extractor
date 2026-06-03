import logging
from io import BytesIO
from typing import List

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)

# Render at 200 DPI for a good quality / size trade-off
_DPI = 200
_SCALE = _DPI / 72  # fitz works in points (72 pt = 1 inch)
_MAX_PAGES = 10  # marksheets are never more than a few pages; cap to avoid LLM overload


def pdf_to_images(pdf_bytes: bytes) -> List[Image.Image]:
    """Convert each page of a PDF to a RGB PIL Image at 200 DPI."""
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Could not open PDF: {exc}") from exc

    total_pages = len(doc)
    if total_pages > _MAX_PAGES:
        logger.warning(
            "PDF has %d pages; only processing first %d", total_pages, _MAX_PAGES
        )

    images: List[Image.Image] = []
    matrix = fitz.Matrix(_SCALE, _SCALE)

    try:
        for page_index in range(min(total_pages, _MAX_PAGES)):
            page = doc[page_index]
            pix = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
            img = Image.open(BytesIO(pix.tobytes("png"))).convert("RGB")
            images.append(img)
    finally:
        doc.close()

    logger.info("Converted PDF: %d/%d page(s) at %d DPI", len(images), total_pages, _DPI)
    return images
