"""Local, no-LLM reading of card balances from a /sync screenshot.

Used by handlers/balance_sync.py *before* the vision-LLM call, which stays
as the fallback whenever this abstains. Two things make that safe:

1. It either returns a fully-verified read or None -- never a partial
   guess. A wrong ABSTAIN costs one ordinary LLM call; a wrong ACCEPT
   would silently corrupt the tracked balance, so ``verify_read`` below is
   deliberately strict (see its docstring for each guard).
2. balance_sync.py shows the itemized per-card amounts in the confirmation
   message, so a misread digit is visible to the user before anything is
   applied.

### Why RapidOCR and not Tesseract

Measured against three real Uzum Bank screenshots (12 amounts, 4 cards
each): RapidOCR's PP-OCRv4 ONNX models read every amount and every card
number exactly, on both the full screenshot and a cropped card region --
so no crop geometry is assumed here, only the "sum" suffix every balance
carries. Tesseract on the same images misread digits in a consistent
"3" -> "5" way (868,32 -> 868,52) in every configuration tried
(inverted, upscaled, per-row single-line, LSTM-only) and once dropped an
entire card line, undercounting by ~1.48M. That dropped-line case is the
exact failure ``verify_read`` exists to catch.

### Why a subprocess

``run_ocr_lines`` is invoked as ``python -m expense_ai.card_ocr <image>``
rather than in the bot process, for two measured reasons:

* **Memory is never returned in-process.** onnxruntime's allocator arenas
  and the mapped native libraries (cv2, onnxruntime) stay resident: after
  one inference RSS was ~176 MB, and ``del engine; gc.collect()`` brought
  it back only to ~168 MB against an 8 MB baseline. A process that exits
  hands all of it back to the OS, so /sync costs nothing between uses --
  which matters because it's used occasionally, not constantly.
* **Inference is ~1.1s of solid CPU work.** Run inline it would block the
  bot's asyncio event loop and stall every other handler; awaited as a
  subprocess it doesn't.

Cold start is cheap enough to make this basically free: interpreter
startup + imports + model load + inference measured ~1.1s end to end,
still faster than the vision-LLM call it replaces.

The subprocess only ever does OCR and prints the raw text lines as JSON;
all parsing and verification happens back in the parent (the pure
functions below), so the logic that decides what reaches the database is
testable without the models installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# How long to wait for the OCR subprocess before giving up and falling
# back to the LLM. Measured cold-start end-to-end is ~1.1s; this is a
# generous ceiling for a loaded machine, not a target.
OCR_TIMEOUT_SECONDS = 60.0

# An amount line, matched against the text with all spaces stripped, e.g.
# "8268,32sum", "32626,7sum". Notes on the two deliberate strictnesses:
#
# * The decimal separator is REQUIRED (the engine reports it inconsistently
#   as "." or ","). If it were ever dropped, "103422606sum" would parse
#   100x too large; demanding it means such a read abstains to the LLM
#   instead. Thousands separators are spaces, which the engine drops
#   entirely, so whatever separator survives is unambiguously the decimal.
# * One OR two decimal digits, and the whole line must be *nothing but*
#   the amount and "sum" (fullmatch). Requiring exactly two digits was a
#   real bug: the app drops a trailing zero, so a live screenshot showed
#   "32 626,7 sum", which failed to parse and made /sync abstain on every
#   attempt. The fullmatch is what keeps loosening the digit count safe --
#   on a mangled number where a thousands space was misread as a comma
#   ("1,034226,06sum"), an unanchored search would happily match the
#   *tail* and silently return 34,226.06 instead of 1,034,226.06.
_AMOUNT_RE = re.compile(r"(\d+)[.,](\d{1,2})sum", re.IGNORECASE)

# A card line, e.g. "1111 · Uzum Card", "2222·Agrobank". The trailing
# letter requirement is what stops "8068.32sum" from being read as card
# "8068" -- after the separator there a digit follows, not a bank name.
_CARD_RE = re.compile(r"(\d{4})\s*[·•∙.\-]\s*(?=[A-Za-z])")


@dataclass(frozen=True)
class CardRead:
    """One screenshot's worth of extracted balances.

    ``items`` pairs each amount with the card last-4 it belongs to when
    document order allows it (the engine emits an amount line immediately
    before its card line), else ``None`` for that label -- labels are
    presentation-only, never used for any financial decision.
    """

    items: list[tuple[str | None, float]]
    cards: frozenset[str]

    @property
    def amounts(self) -> list[float]:
        return [amount for _label, amount in self.items]

    @property
    def total(self) -> float:
        return round(sum(self.amounts), 2)


def parse_ocr_lines(lines: list[str]) -> CardRead:
    """Raw OCR text lines -> amounts, card numbers, and their pairing.

    Anchoring amounts on the "sum" suffix is what keeps promo banners and
    the prize-wheel graphics ("Win prizes", "3% cashback") from being read
    as balances -- verified against real screenshots, where running this
    on the *whole* uncropped image still found exactly the four real
    amounts.
    """
    items: list[tuple[str | None, float]] = []
    cards: list[str] = []
    # The engine emits each amount line just before its card line, so an
    # amount waits here until the next card line claims it as its label.
    pending: float | None = None

    for line in lines:
        match = _AMOUNT_RE.fullmatch(re.sub(r"\s", "", line))
        if match is not None:
            if pending is not None:  # two amounts in a row -> no label for the first
                items.append((None, pending))
            pending = round(float(f"{match.group(1)}.{match.group(2)}"), 2)
        for card_match in _CARD_RE.finditer(line):
            cards.append(card_match.group(1))
            if pending is not None:
                items.append((card_match.group(1), pending))
                pending = None
    if pending is not None:
        items.append((None, pending))

    return CardRead(items=items, cards=frozenset(cards))


def verify_read(read: CardRead, expected_cards: frozenset[str]) -> bool:
    """Whether ``read`` is trustworthy enough to skip the LLM entirely.

    Every guard here exists to catch a failure actually observed while
    testing OCR engines on real screenshots:

    * no configured card list -> never trust local OCR (opt-in only);
    * no amounts found -> nothing was read, or it's a different screen;
    * a missing expected card -> a whole line was dropped, which is the
      failure that would otherwise silently undercount the total;
    * amount count != card count -> lines were merged/dropped, or the
      screen shows a balance this guard can't attribute (a deposit, a new
      card not in the configured list), so the totals can't be trusted.
    """
    if not expected_cards:
        return False
    if not read.amounts:
        return False
    if not expected_cards.issubset(read.cards):
        logger.info(
            "Local card OCR abstaining: expected cards %s, found %s",
            sorted(expected_cards),
            sorted(read.cards),
        )
        return False
    if len(read.amounts) != len(expected_cards):
        logger.info(
            "Local card OCR abstaining: read %d amounts for %d expected cards",
            len(read.amounts),
            len(expected_cards),
        )
        return False
    return True


def run_ocr_lines(image_path: str | Path) -> list[str]:
    """Recognized text lines from an image. Imports the OCR stack lazily,
    so it's only ever loaded inside the short-lived subprocess."""
    import numpy as np
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR

    with Image.open(image_path) as image:
        array = np.array(image.convert("RGB"))
    result, _elapsed = RapidOCR()(array)
    return [text for _box, text, _confidence in (result or [])]


async def extract_card_read(image_bytes: bytes, expected_cards: frozenset[str]) -> CardRead | None:
    """Verified local read of a /sync screenshot, or None to defer to the
    vision LLM. Never raises: any failure (OCR stack missing, subprocess
    crash, timeout, unparseable output) is just an abstain, since the
    caller always has the LLM path to fall back on."""
    if not expected_cards:
        return None

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
        handle.write(image_bytes)
        temp_path = handle.name

    try:
        lines = await _run_worker(temp_path)
    except Exception as exc:  # noqa: BLE001 -- abstaining is always safe here
        logger.warning("Local card OCR failed, falling back to the LLM: %s", exc)
        return None
    finally:
        Path(temp_path).unlink(missing_ok=True)

    if lines is None:
        return None

    read = parse_ocr_lines(lines)
    if not verify_read(read, expected_cards):
        return None
    return read


async def _run_worker(image_path: str) -> list[str] | None:
    # cwd is pinned to the directory *containing* the expense_ai package so
    # `-m expense_ai.card_ocr` resolves regardless of where the bot process
    # happens to be running from, rather than relying on an inherited cwd.
    package_root = Path(__file__).resolve().parent.parent
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "expense_ai.card_ocr",
        image_path,
        cwd=str(package_root),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=OCR_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        logger.warning("Local card OCR timed out after %.0fs", OCR_TIMEOUT_SECONDS)
        return None

    if process.returncode != 0:
        logger.warning(
            "Local card OCR subprocess exited %s: %s",
            process.returncode,
            stderr.decode(errors="replace").strip()[:300],
        )
        return None

    # The OCR stack writes assorted warnings to stderr and can log to
    # stdout too, so take the last non-empty stdout line as the payload.
    payload = next(
        (line for line in reversed(stdout.decode(errors="replace").splitlines()) if line.strip()),
        "",
    )
    if not payload:
        return None
    return list(json.loads(payload)["lines"])


def _main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m expense_ai.card_ocr <image_path>", file=sys.stderr)
        return 2
    print(json.dumps({"lines": run_ocr_lines(argv[1])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
