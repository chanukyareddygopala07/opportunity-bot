"""Phase 8 — deterministic field extraction from free text.

Regex patterns only; anything not found stays None. Nothing is invented.
"""
import re
from datetime import datetime

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

DEADLINE_KEYWORDS = (
    "deadline", "last date", "last day", "closing date", "closes",
    "apply by", "due", "on or before", "no later than", "ends on",
    "submission date", "cutoff date", "last date of submission",
)

ISO_DATE = re.compile(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b")
DMY_DATE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?\s+(20\d{2})\b")
MDY_DATE = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})\b")
SLASH_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")

DURATION_PAT = re.compile(r"\b(\d{1,3})\s*(?:-|\s)?(week|month|year)s?\b", re.IGNORECASE)
DURATION_KEYWORDS = ("duration", "tenure", "period", "spread over", "for a")

STIPEND_PAT = re.compile(
    r"(?:stipend|honorarium|salary|remuneration)\s*(?:of|:)?\s*"
    r"((?:₹|rs\.?|inr|usd|\$|€|eur|£|gbp)\s*)?([\d,]+(?:\.\d+)?)\s*"
    r"(?:per\s*|\s*/\s*)?(month|monthly|annum|year|week|mo\.?)?",
    re.IGNORECASE,
)

CURRENCY_MAP = {
    "₹": "INR", "rs.": "INR", "rs": "INR", "inr": "INR",
    "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR",
    "£": "GBP", "gbp": "GBP",
}

FUNDING_PATTERNS = (
    ("Unpaid", re.compile(r"\bunpaid\b", re.IGNORECASE)),
    ("Fully funded", re.compile(r"fully\s+funded", re.IGNORECASE)),
    ("Paid", re.compile(r"\bpaid\b", re.IGNORECASE)),
    ("Stipend provided", re.compile(r"stipend", re.IGNORECASE)),
    ("Funded", re.compile(r"\bfunded\b", re.IGNORECASE)),
    ("Honorarium", re.compile(r"honorarium", re.IGNORECASE)),
)

GPA_PAT = re.compile(r"(?:cgpa|gpa)\s*(?:of|:)?\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
PERCENT_PAT = re.compile(r"(?:minimum|min\.?|at\s+least|aggregate)\s*([0-9]{2})\s*%", re.IGNORECASE)

DEGREE_PATTERNS = (
    ("b.tech", re.compile(r"\bb\.?\s?tech\b", re.IGNORECASE)),
    ("b.e.", re.compile(r"\bb\.\s?e\.?\b", re.IGNORECASE)),
    ("b.sc", re.compile(r"\bb\.\s?sc\b", re.IGNORECASE)),
    ("m.tech", re.compile(r"\bm\.?\s?tech\b", re.IGNORECASE)),
    ("m.sc", re.compile(r"\bm\.\s?sc\b", re.IGNORECASE)),
    ("ph.d", re.compile(r"\bph\.?\s?d\b", re.IGNORECASE)),
    ("b.a.", re.compile(r"\bb\.\s?a\.?\b", re.IGNORECASE)),
    ("undergraduate", re.compile(r"undergraduate|under-graduate", re.IGNORECASE)),
    ("postgraduate", re.compile(r"postgraduate|post-graduate|post\s+graduate", re.IGNORECASE)),
)

YEAR_PATTERNS = (
    ("1st year", re.compile(r"\b1st\s*-?\s*year\b", re.IGNORECASE)),
    ("2nd year", re.compile(r"\b2nd\s*-?\s*year\b", re.IGNORECASE)),
    ("3rd year", re.compile(r"\b3rd\s*-?\s*year\b", re.IGNORECASE)),
    ("4th year", re.compile(r"\b4th\s*-?\s*year\b", re.IGNORECASE)),
    ("5th year", re.compile(r"\b5th\s*-?\s*year\b", re.IGNORECASE)),
    ("final year", re.compile(r"\bfinal\s*-?\s*year\b", re.IGNORECASE)),
    ("1st year", re.compile(
        r"\bfirst\s+-?\s*year\s+(?:undergraduate|student|of\s+study|b\.?\s?tech|engineering)",
        re.IGNORECASE)),
    ("2nd year", re.compile(
        r"\bsecond\s+-?\s*year\s+(?:undergraduate|student|of\s+study|b\.?\s?tech|engineering)",
        re.IGNORECASE)),
    ("3rd year", re.compile(
        r"\bthird\s+-?\s*year\s+(?:undergraduate|student|of\s+study|b\.?\s?tech|engineering)",
        re.IGNORECASE)),
    ("4th year", re.compile(
        r"\bfourth\s+-?\s*year\s+(?:undergraduate|student|of\s+study|b\.?\s?tech|engineering)",
        re.IGNORECASE)),
    ("5th year", re.compile(
        r"\bfifth\s+-?\s*year\s+(?:undergraduate|student|of\s+study|b\.?\s?tech|engineering)",
        re.IGNORECASE)),
)

BRANCH_PATTERNS = (
    ("computer science", re.compile(r"computer\s+science|cs\b|software\s+engineering", re.IGNORECASE)),
    ("electronics", re.compile(r"electronics|ece\b", re.IGNORECASE)),
    ("electrical", re.compile(r"electrical\b", re.IGNORECASE)),
    ("mechanical", re.compile(r"mechanical\b", re.IGNORECASE)),
    ("civil", re.compile(r"\bcivil\b", re.IGNORECASE)),
    ("mathematics", re.compile(r"mathematics|maths?\b", re.IGNORECASE)),
    ("physics", re.compile(r"\bphysics\b", re.IGNORECASE)),
    ("chemistry", re.compile(r"\bchemistry\b", re.IGNORECASE)),
    ("biology", re.compile(r"\bbiology\b|\blife\s+sciences\b", re.IGNORECASE)),
    ("biotechnology", re.compile(r"biotechnology|bio-tech", re.IGNORECASE)),
    ("data science", re.compile(r"data\s+science\b", re.IGNORECASE)),
    ("all branches", re.compile(r"all\s+branches|any\s+branch", re.IGNORECASE)),
)

COUNTRY_PATTERNS = (
    ("India", re.compile(
        r"indian\s+(undergraduates|nationals?|students?|citizens?)|"
        r"students?\s+from\s+india|citizens?\s+of\s+india|based\s+in\s+india",
        re.IGNORECASE)),
    ("International", re.compile(
        r"international\s+students?|from\s+any\s+country|all\s+nationalities|"
        r"around\s+the\s+world|worldwide|open\s+to\s+all\s+countries",
        re.IGNORECASE)),
    ("USA", re.compile(r"u\.?s\.?\s+citizens?|united\s+states\s+citizens?", re.IGNORECASE)),
    ("UK", re.compile(r"uk\s+nationals?|united\s+kingdom\s+nationals?", re.IGNORECASE)),
)

SKILL_PATTERNS = (
    ("C", re.compile(r"\bc\b")),
    ("C++", re.compile(r"\bc\+\+")),
    ("Python", re.compile(r"\bpython\b", re.IGNORECASE)),
    ("Java", re.compile(r"\bjava\b", re.IGNORECASE)),
    ("JavaScript", re.compile(r"\bjavascript\b", re.IGNORECASE)),
    ("TypeScript", re.compile(r"\btypescript\b", re.IGNORECASE)),
    ("Go", re.compile(r"\bgo\b", re.IGNORECASE)),
    ("Rust", re.compile(r"\brust\b", re.IGNORECASE)),
    ("SQL", re.compile(r"\bsql\b", re.IGNORECASE)),
    ("TensorFlow", re.compile(r"\btensorflow\b", re.IGNORECASE)),
    ("PyTorch", re.compile(r"\bpytorch\b", re.IGNORECASE)),
    ("Machine Learning", re.compile(r"machine\s+learning", re.IGNORECASE)),
    ("Deep Learning", re.compile(r"deep\s+learning", re.IGNORECASE)),
    ("NLP", re.compile(r"\bnlp\b|\bnatural\s+language\s+processing\b", re.IGNORECASE)),
    ("LLM", re.compile(r"\bllm\b|\blarge\s+language\s+models?\b", re.IGNORECASE)),
    ("CUDA", re.compile(r"\bcuda\b", re.IGNORECASE)),
    ("React", re.compile(r"\breact\b", re.IGNORECASE)),
    ("Node.js", re.compile(r"\bnode\.?js\b", re.IGNORECASE)),
    ("Django", re.compile(r"\bdjango\b", re.IGNORECASE)),
    ("Flask", re.compile(r"\bflask\b", re.IGNORECASE)),
    ("Git", re.compile(r"\bgit\b", re.IGNORECASE)),
    ("Docker", re.compile(r"\bdocker\b", re.IGNORECASE)),
    ("Kubernetes", re.compile(r"\bkubernetes\b", re.IGNORECASE)),
    ("Linux", re.compile(r"\blinux\b", re.IGNORECASE)),
    ("Data Structures", re.compile(r"data\s+structures", re.IGNORECASE)),
    ("Algorithms", re.compile(r"\balgorithms?\b", re.IGNORECASE)),
    ("Competitive Programming", re.compile(r"competitive\s+programming", re.IGNORECASE)),
    ("Statistics", re.compile(r"\bstatistics?\b", re.IGNORECASE)),
    ("Probability", re.compile(r"\bprobability\b", re.IGNORECASE)),
    ("Linear Algebra", re.compile(r"linear\s+algebra", re.IGNORECASE)),
    ("Calculus", re.compile(r"\bcalculus\b", re.IGNORECASE)),
    ("Quantitative", re.compile(r"\bquantitative\b", re.IGNORECASE)),
    ("Finance", re.compile(r"\bfinance\b|\bfinancial\b", re.IGNORECASE)),
    ("Trading", re.compile(r"\btrading\b", re.IGNORECASE)),
    ("Security", re.compile(r"\bsecurity\b|\bcryptography\b", re.IGNORECASE)),
    ("Distributed Systems", re.compile(r"distributed\s+systems", re.IGNORECASE)),
    ("Operating Systems", re.compile(r"operating\s+systems?", re.IGNORECASE)),
    ("Cloud", re.compile(r"\bcloud\b|\baws\b", re.IGNORECASE)),
    ("Matlab", re.compile(r"\bmatlab\b", re.IGNORECASE)),
    ("Julia", re.compile(r"\bjulia\b", re.IGNORECASE)),
)


def _valid_date(year, month, day):
    try:
        datetime(year, month, day)
        return True
    except ValueError:
        return False


def _month_number(name):
    return MONTHS.get(str(name)[:3].lower())


def _to_iso(match, pattern):
    if pattern is ISO_DATE:
        year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
    elif pattern is DMY_DATE:
        day, month, year = int(match.group(1)), _month_number(match.group(2)), int(match.group(3))
    elif pattern is MDY_DATE:
        month, day, year = _month_number(match.group(1)), int(match.group(2)), int(match.group(3))
    else:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
    if month is None or not _valid_date(year, month, day):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def find_deadline(text):
    candidates = []
    for pattern in (ISO_DATE, DMY_DATE, MDY_DATE, SLASH_DATE):
        for match in pattern.finditer(text):
            iso = _to_iso(match, pattern)
            if iso:
                candidates.append((match.start(), iso))
    if not candidates:
        return None
    lowered = text.lower()
    keyword_positions = []
    for keyword in DEADLINE_KEYWORDS:
        start = 0
        while True:
            pos = lowered.find(keyword, start)
            if pos == -1:
                break
            keyword_positions.append(pos)
            start = pos + 1
    if keyword_positions:
        best, best_distance = None, None
        for pos, iso in candidates:
            distance = min(abs(pos - kp) for kp in keyword_positions)
            if best_distance is None or distance < best_distance:
                best_distance, best = distance, iso
        return best
    if len(candidates) == 1:
        return candidates[0][1]
    return None


def find_duration(text):
    lowered = text.lower()
    for match in DURATION_PAT.finditer(text):
        window = lowered[max(0, match.start() - 60):match.end() + 20]
        if any(keyword in window for keyword in DURATION_KEYWORDS):
            count = int(match.group(1))
            unit = match.group(2).lower()
            return f"{count} {unit}{'s' if count != 1 else ''}"
    standalone = re.search(r"\b(\d{1,3})-week\b", lowered)
    if standalone:
        return f"{standalone.group(1)} weeks"
    return None


def find_stipend(text):
    match = STIPEND_PAT.search(text)
    if not match:
        return None, None
    symbol = (match.group(1) or "").strip()
    amount = match.group(2)
    period_raw = (match.group(3) or "").lower()
    period = {"mo.": "month", "monthly": "month", "annum": "year"}.get(period_raw, period_raw)
    stipend = f"{symbol}{amount}"
    if period:
        stipend += f"/{period}"
    currency = CURRENCY_MAP.get(symbol.lower(), CURRENCY_MAP.get(symbol))
    return stipend, currency


def find_funding(text):
    for label, pattern in FUNDING_PATTERNS:
        if pattern.search(text):
            stipend, currency = find_stipend(text)
            return label, stipend, currency
    return None, None, None


def find_gpa(text):
    match = GPA_PAT.search(text)
    if match:
        return match.group(1)
    match = PERCENT_PAT.search(text)
    if match:
        return f"{match.group(1)}%"
    return None


def _find_by_patterns(text, patterns):
    return [name for name, pattern in patterns if pattern.search(text)]


def find_degrees(text):
    return _find_by_patterns(text, DEGREE_PATTERNS)


def find_years(text):
    return _find_by_patterns(text, YEAR_PATTERNS)


def find_branches(text):
    return _find_by_patterns(text, BRANCH_PATTERNS)


def find_countries(text):
    return _find_by_patterns(text, COUNTRY_PATTERNS)


def find_skills(text):
    return _find_by_patterns(text, SKILL_PATTERNS)


def extract_fields(text):
    if not text:
        return {}
    funding, stipend, currency = find_funding(text)
    return {
        "deadline": find_deadline(text),
        "duration": find_duration(text),
        "funding": funding,
        "stipend": stipend,
        "currency": currency,
        "minimum_gpa": find_gpa(text),
        "eligible_degrees": find_degrees(text) or None,
        "eligible_years": find_years(text) or None,
        "eligible_branches": find_branches(text) or None,
        "eligible_countries": find_countries(text) or None,
        "preferred_skills": find_skills(text) or None,
    }