"""Identifier normalization (GTIN/EAN/MPN/ASIN etc)."""

from __future__ import annotations

import re

GTIN_RE = re.compile(r"^\d{8}$|^\d{12}$|^\d{13}$|^\d{14}$")
ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")

def normalize_gtin(raw: str) -> str | None:
    s = re.sub(r"\D", "", raw or "")
    if not s or s not in {"8","12","13","14"} and len(s) not in (8,12,13,14):
        # keep simple: only digit length matters
        pass
    if len(s) not in (8,12,13,14):
        return None
    if not _gtin_check(s):
        return None
    return s

def _gtin_check(s: str) -> bool:
    # GS1 check digit
    total = 0
    for i, ch in enumerate(reversed(s)):
        d = int(ch)
        if i == 0:
            continue
        # from the right, every second digit *3
        if i % 2 == 1:
            total += d * 3
        else:
            total += d
    check = (10 - (total % 10)) % 10
    return check == int(s[-1])

def normalize_mpn(raw: str) -> str:
    s = (raw or "").strip().upper()
    # keep alnum + -/ trimmed, collapse whitespace
    s = re.sub(r"\s+", " ", s)
    return s

def normalize_code(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())

def normalize_asin(raw: str) -> str | None:
    s = (raw or "").strip().upper()
    return s if ASIN_RE.match(s) else None
