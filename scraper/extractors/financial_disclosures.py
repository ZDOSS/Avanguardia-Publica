import io
import re
import zipfile
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests

from source_health import SourceHealthTracker

logger = logging.getLogger(__name__)

# Official U.S. House Clerk bulk financial-disclosure feed — free, authoritative, keyless.
# The annual ZIP holds an XML INDEX of every filing (member, type, date, DocID) but NOT the
# per-transaction asset/value rows, which live only in the linked PDF. We surface the filing
# plus a link to the official document. (The community Stock Watcher transaction feed that
# offered parsed trades is offline.) Senators and state legislators are not in this feed.
_HOUSE_ZIP_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.ZIP"

# We ingest only the two unambiguous, substantive financial-disclosure filing types and skip
# procedural ones (extensions, candidate/withdrawal paperwork, etc.) so the profile tab stays
# meaningful and correctly labeled. Easy to extend if more codes are confirmed.
_FILING_TYPE_LABELS = {
    "P": "Periodic Transaction Report",
    "O": "Annual Financial Disclosure",
}

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[.,]")
_STATE_DISTRICT_RE = re.compile(r"^([A-Z]{2})[- ]?([0-9]{1,2}|AL)?$")

# Honorifics/suffixes that the House Clerk feed embeds in the First/Last name fields (real
# example: First="Marjorie Taylor Mrs", Last="Greene"). Left in, they inflate the token count
# and break the first+last fallback key. Stripped from every name on BOTH the index and lookup
# side so matching stays symmetric. (Bare single-letter suffixes like "V" are deliberately
# excluded — they're indistinguishable from a middle initial.)
_NAME_NOISE = {"mr", "mrs", "ms", "miss", "dr", "hon", "jr", "sr", "ii", "iii", "iv"}


def _normalize_name(name: str) -> str:
    """Lowercased, punctuation-stripped, honorific/suffix-free, whitespace-collapsed name."""
    if not name:
        return ""
    cleaned = _WS_RE.sub(" ", _PUNCT_RE.sub(" ", name.lower())).strip()
    return " ".join(t for t in cleaned.split(" ") if t and t not in _NAME_NOISE)


def _no_middle(norm: str) -> str:
    """
    'richard w allen' -> 'richard allen' (drop a single middle name/initial token).

    Honorifics/suffixes are already removed by _normalize_name, so a 3-token name here is a
    genuine first/middle/last. With 4+ real tokens the structure is ambiguous (e.g. a compound
    first name), so we leave matching to the full normalized key rather than emit a wrong one.
    """
    parts = norm.split(" ")
    return f"{parts[0]} {parts[-1]}" if len(parts) == 3 else norm


def _parse_date(raw: str):
    """House FilingDate is M/D/YYYY; return ISO YYYY-MM-DD, or None if unparseable."""
    if not raw:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _normalize_district(value) -> str | None:
    raw = str(value or "").strip().upper().replace(" ", "-")
    if not raw:
        return None
    if raw in {"0", "00", "AL", "AT-LARGE", "AT-LARGE-DISTRICT"}:
        return "AT-LARGE"
    return raw.lstrip("0") or "0"


def _parse_state_district(raw: str | None) -> tuple[str | None, str | None]:
    value = str(raw or "").strip().upper()
    match = _STATE_DISTRICT_RE.match(value)
    if not match:
        return None, None
    return match.group(1), _normalize_district(match.group(2))


def _doc_url(doc_id: str, year: str) -> str:
    # Electronically-filed DocIDs start with '2' and live under ptr-pdfs/; scanned paper
    # filings start with '1' and live under financial-pdfs/. (Verified against live PDFs.)
    folder = "ptr-pdfs" if doc_id.startswith("2") else "financial-pdfs"
    return f"https://disclosures-clerk.house.gov/public_disc/{folder}/{year}/{doc_id}.pdf"


def get_house_disclosure_index(
    years, health: SourceHealthTracker | None = None
):
    """
    Download the House Clerk financial-disclosure index for each year in `years` and return a
    dict mapping a normalized member name -> list of filing dicts:
        {doc_id, filing_type (label), filing_date (ISO), doc_url, year}

    Each filing is keyed under BOTH the full normalized name and a middle-dropped variant to
    widen exact matching against our stored politician names. A network/parse failure for a
    given year is logged and skipped — financial disclosures are enrichment and must never be
    fatal to the pipeline (the caller just gets a smaller/empty index).
    """
    index: dict[str, list] = {}
    for year in years:
        url = _HOUSE_ZIP_URL.format(year=year)
        if health:
            health.record_attempt()
        started_at = time.monotonic()
        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()
            zf = zipfile.ZipFile(io.BytesIO(resp.content))
            xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
            root = ET.fromstring(zf.read(xml_name).decode("utf-8-sig"))
            if health:
                health.record_success(time.monotonic() - started_at)
        except Exception as e:
            logger.warning("House FD index fetch/parse failed for %s: %s", year, e)
            if health:
                reason = "timeout" if isinstance(e, requests.Timeout) else "fetch_or_parse_error"
                health.record_failure(reason, time.monotonic() - started_at)
            continue

        added = 0
        for m in root:
            label = _FILING_TYPE_LABELS.get((m.findtext("FilingType") or "").strip())
            if not label:
                continue  # procedural filing type — skip
            doc_id = (m.findtext("DocID") or "").strip()
            filing_date = _parse_date(m.findtext("FilingDate"))
            if not doc_id or not filing_date:
                continue  # DocID + a valid date are required (filing_date is NOT NULL)
            norm = _normalize_name(f"{m.findtext('First') or ''} {m.findtext('Last') or ''}")
            if not norm:
                continue
            state, district = _parse_state_district(m.findtext("StateDst"))
            if state is None:
                state = (m.findtext("State") or "").strip().upper() or None
            if district is None:
                district = _normalize_district(m.findtext("District"))
            filing = {
                "doc_id": doc_id,
                "filing_type": label,
                "filing_date": filing_date,
                "doc_url": _doc_url(doc_id, str(year)),
                "year": str(year),
                "_filer_name": norm,
                "_state": state,
                "_district": district,
            }
            for key in {norm, _no_middle(norm)}:
                index.setdefault(key, []).append(filing)
            added += 1
        logger.info("House FD index: %d filings ingested for %s", added, year)
    return index


def lookup_disclosures(
    index,
    name_forms,
    *,
    state: str | None = None,
    district: str | None = None,
    health: SourceHealthTracker | None = None,
):
    """
    Return all filings matching any of `name_forms` (a politician's full_name + aliases),
    de-duplicated by DocID. Matching is exact on the normalized (and middle-dropped) name —
    never fuzzy — in keeping with the loader's entity-resolution rule.
    """
    if not index or not name_forms:
        return []
    keys = set()
    for form in name_forms:
        norm = _normalize_name(form)
        if norm:
            keys.add(norm)
            keys.add(_no_middle(norm))

    seen = set()
    candidates = []
    for key in keys:
        for filing in index.get(key, []):
            if filing["doc_id"] not in seen:
                seen.add(filing["doc_id"])
                candidates.append(filing)

    expected_state = str(state or "").strip().upper() or None
    expected_district = _normalize_district(district)
    contextual_matches = []
    for filing in candidates:
        filing_state = filing.get("_state")
        filing_district = filing.get("_district")
        if expected_state and not filing_state:
            if health:
                health.record_skip("missing_state_identity_context")
            continue
        if expected_district and not filing_district:
            if health:
                health.record_skip("missing_district_identity_context")
            continue
        if expected_state and filing_state != expected_state:
            if health:
                health.record_skip("state_identity_context_mismatch")
            continue
        if expected_district and filing_district != expected_district:
            if health:
                health.record_skip("district_identity_context_mismatch")
            continue
        contextual_matches.append(filing)

    filer_keys = {
        (
            filing.get("_filer_name"),
            filing.get("_state"),
            filing.get("_district"),
        )
        for filing in contextual_matches
    }
    if len(filer_keys) > 1:
        logger.warning(
            "House FD ambiguous exact-name match for %s (%s-%s); skipping %d filings",
            sorted(keys),
            expected_state,
            expected_district,
            len(contextual_matches),
        )
        if health:
            health.record_skip("ambiguous_identity_match", len(contextual_matches))
        return []

    return [
        {key: value for key, value in filing.items() if not key.startswith("_")}
        for filing in contextual_matches
    ]
