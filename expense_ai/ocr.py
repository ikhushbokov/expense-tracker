"""OCR using Tesseract via pytesseract.

Extraction is intentionally "dumb" (just raw text) -- the LLM (see
handlers/photo.py and handlers/balance_sync.py) is responsible for
interpreting the OCR'd text (receipt layouts and banking-app screenshots
both vary too much for regex alone).
"""

from __future__ import annotations

from pathlib import Path

import pytesseract
from PIL import Image

from expense_ai.config import settings

pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


def extract_image_text(image_path: Path) -> str:
    """Run OCR on an image and return the raw extracted text."""
    image = Image.open(image_path)
    return pytesseract.image_to_string(image, lang=settings.ocr_languages)
