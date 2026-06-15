import re
import requests

# Wikidata entity ids look like Q42 / Q22250. Validate before interpolating into a
# query so a value can never break out of the SPARQL (the old name-based lookup
# injected raw display names like  Eric A. "Rick" Crawford  and returned HTTP 400).
_QID_RE = re.compile(r"^Q\d+$")

_ENDPOINT = "https://query.wikidata.org/sparql"
_HEADERS = {
    "Accept": "application/sparql-results+json",
    "User-Agent": "AvanguardiaPublica/1.0 (https://github.com/Avanguardia-Publica)",
}


def get_wikidata_bio_by_qid(qid: str) -> dict:
    """
    Queries Wikidata for biographical properties using a stable entity QID
    (sourced from the congress-legislators crosswalk, e.g. id.wikidata = "Q22250").

    Looking up by QID instead of by display-name label is both injection-proof and
    far more reliable — bioguide_id should already come from the YAML, so this is for
    optional enrichment (image, etc.). Returns {} on any failure.
    """
    if not qid or not _QID_RE.match(qid):
        return {}

    query = (
        "SELECT ?bioguide ?image WHERE { "
        f"OPTIONAL {{ wd:{qid} wdt:P1157 ?bioguide. }} "
        f"OPTIONAL {{ wd:{qid} wdt:P18 ?image. }} "
        "}"
    )

    try:
        response = requests.get(
            _ENDPOINT, params={"query": query}, headers=_HEADERS, timeout=10
        )
        response.raise_for_status()
        bindings = response.json().get("results", {}).get("bindings", [])
        if not bindings:
            return {}
        first = bindings[0]
        return {
            "bioguide_id": first.get("bioguide", {}).get("value"),
            "image_url": first.get("image", {}).get("value"),
        }
    except Exception as e:
        print(f"Error fetching Wikidata for {qid}: {e}")
        return {}
