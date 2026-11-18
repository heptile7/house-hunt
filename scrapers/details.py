"""
Shared parsing for listing details that sites express as free text:
posted/updated dates, move-in availability, and pets / non-veg restrictions.

All dates are returned as ISO strings (YYYY-MM-DD) in India time.
"""

import re
from datetime import date, datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {
    m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)
}
_MON = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"


def today_ist() -> date:
    return datetime.now(IST).date()


def ms_to_date(ms) -> str:
    """Epoch milliseconds (NoBroker) → ISO date in IST; '' if missing."""
    try:
        return datetime.fromtimestamp(int(ms) / 1000, IST).date().isoformat() if ms else ""
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def parse_date_text(text, today: date | None = None) -> str:
    """Parse the many ways sites write dates. Returns ISO date or ''.

    Handles: "Posted: Nov 06, '26", "Posted : 4 days ago", "Updated today", "Yesterday",
    "3 weeks ago", "16 Nov 2026", "Jun'27", "Dec 2026", "16/11/2026", ISO timestamps.
    """
    if not text:
        return ""
    t = str(text).strip().lower()
    today = today or today_ist()

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)  # ISO / ISO timestamp
    if m:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    if "just now" in t or "today" in t or re.search(r"\b\d+\s*(min|minute|hour|hr)s?\b", t):
        return today.isoformat()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    m = re.search(r"\b(\d+|a|an)\s*(day|week|month|year)s?\s+ago", t)
    if m:
        n = 1 if m[1] in ("a", "an") else int(m[1])
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[m[2]] * n
        return (today - timedelta(days=days)).isoformat()
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b", t)  # dd/mm/yyyy (Indian order)
    if m:
        try:
            return date(_year(m[3]), int(m[2]), int(m[1])).isoformat()
        except ValueError:
            return ""
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+{_MON},?\s*'?(\d{{2,4}})\b", t)  # 16 Nov 2026
    if m:
        return _safe_date(_year(m[3]), _MONTHS[m[2][:3]], int(m[1]))
    m = re.search(rf"\b{_MON}\s+(\d{{1,2}})(?!\d),?\s*'?(\d{{2,4}})\b", t)  # Nov 06, '26 (not "Dec 2026")
    if m:
        return _safe_date(_year(m[3]), _MONTHS[m[1][:3]], int(m[2]))
    m = re.search(rf"\b{_MON}\s*['’]?\s*(\d{{2,4}})\b", t)  # Jun'27 / Dec 2026 → 1st of month
    if m:
        return _safe_date(_year(m[2]), _MONTHS[m[1][:3]], 1)
    return ""


def _safe_date(y: int, mo: int, d: int) -> str:
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def parse_availability(text, today: date | None = None) -> str:
    """Move-in availability → ISO date when a date is given, else a short phrase
    ("Immediately", "Ready to move", "Under construction"). '' if unknown."""
    if not text:
        return ""
    t = str(text).strip()
    low = t.lower()
    if low in ("na", "n/a", "-", "--", "not available", "null", "none"):
        return ""
    if "immediate" in low or low in ("now", "available now"):
        return "Immediately"
    if "ready to move" in low or "ready-to-move" in low:
        return "Ready to move"
    d = parse_date_text(t, today)
    if d:
        return d
    if "under construction" in low:
        return "Under construction"
    return t[:40]


# Explicit phrases only — no guessing. "No" patterns are checked before "yes" ones.
_PETS_NO = re.compile(r"\b(no|not)\s+(pets?|pet animals|animals)\b|\bpets?\s+(are\s+)?not\s+(allowed|permitted)\b")
_PETS_YES = re.compile(r"\bpets?\s+(are\s+)?(allowed|welcome|permitted|ok)\b|\bpet[- ]friendly\b")
_NONVEG_NO = re.compile(
    r"\b(veg(etarian)?s?\s+only|only\s+veg(etarian)?s?|pure\s+veg(etarian)?|strictly\s+veg(etarian)?"
    r"|no\s+non[- ]?veg(etarian)?|non[- ]?veg(etarian)?\s+(is\s+|food\s+)?not\s+(allowed|permitted))\b"
)
_NONVEG_YES = re.compile(r"\bnon[- ]?veg(etarian)?\s+(food\s+)?(is\s+)?(allowed|ok|fine|welcome|permitted)\b")


def infer_restrictions(text) -> tuple[int | None, int | None]:
    """(pets_allowed, non_veg_allowed) from explicit phrases in a description: 1/0/None."""
    if not text:
        return None, None
    t = str(text).lower()
    pets = 0 if _PETS_NO.search(t) else 1 if _PETS_YES.search(t) else None
    nonveg = 0 if _NONVEG_NO.search(t) else 1 if _NONVEG_YES.search(t) else None
    return pets, nonveg


def yes_no(value) -> int | None:
    """'Yes'/'No'/True/False/'NON_VEG_ALLOWED' → 1/0; anything else → None."""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    v = str(value).strip().upper()
    if v in ("YES", "Y", "TRUE", "1", "ALLOWED", "NON_VEG_ALLOWED"):
        return 1
    if v in ("NO", "N", "FALSE", "0", "NOT_ALLOWED", "NON_VEG_NOT_ALLOWED", "VEG_ONLY"):
        return 0
    return None
