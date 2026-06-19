import os
import re
import requests

_BASE = "https://littlesis.org"
_TIMEOUT = 20

# LittleSis relationship category_id → readable label. Mirrors the public category list;
# unknown/missing ids fall back to the relationship's own description text.
_CATEGORY_LABELS = {
    1: "Position",
    2: "Education",
    3: "Membership",
    4: "Family",
    5: "Donation",
    6: "Transaction",
    7: "Lobbying",
    8: "Social",
    9: "Professional",
    10: "Ownership",
    11: "Hierarchy",
    12: "Connection",
}

# Cap relationships pulled per politician — keeps the unverified lane bounded and the
# Connections mini-graph readable.
_MAX_RELATIONSHIPS = 25


def _parse_entity_slug(url: str):
    """
    Pull (entity_id, display_name) out of a LittleSis entity path like
    '/person/13503-Barack_Obama' or '/org/123-Acme_Inc'. Returns (None, None) if the
    path doesn't match — the relationship endpoint exposes the related entity's name
    only via these slugs (there is no name field on the relationship object).
    """
    if not url:
        return None, None
    m = re.search(r"/(?:person|org)/(\d+)-([^/?#]+)", url)
    if not m:
        return None, None
    entity_id = m.group(1)
    name = m.group(2).replace("_", " ").strip()
    return entity_id, name


def _top_entity_id(full_name: str):
    """Best-match LittleSis entity id for a name, or None. Same search the mention
    flow uses; the top hit is good enough for the unverified lane."""
    try:
        resp = requests.get(
            f"{_BASE}/api/entities/search",
            params={"q": full_name},
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return data[0].get("id") if data else None
    except Exception as e:
        print(f"Error searching LittleSis entity for {full_name}: {e}")
        return None


def get_littlesis_relationships(full_name: str) -> list:
    """
    Return structured network ties for a politician as a list of edge dicts:
        {related_name, relationship_type, url, source_api}

    Resolves the person's LittleSis entity, then walks /api/entities/{id}/relationships.
    The related entity's name is parsed from the link slug (the relationship object
    carries only numeric ids). Returns [] on any failure — this is a best-effort,
    unverified-lane enrichment.
    """
    entity_id = _top_entity_id(full_name)
    if not entity_id:
        return []

    try:
        resp = requests.get(
            f"{_BASE}/api/entities/{entity_id}/relationships",
            headers={"Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        rels = resp.json().get("data") or []
    except Exception as e:
        print(f"Error fetching LittleSis relationships for {full_name}: {e}")
        return []

    edges = []
    seen = set()
    for rel in rels:
        attrs = rel.get("attributes") or {}
        links = rel.get("links") or {}
        # The "other" entity is whichever side isn't our own entity_id.
        candidates = [_parse_entity_slug(links.get("entity")), _parse_entity_slug(links.get("related"))]
        other = next(((eid, name) for eid, name in candidates if eid and eid != str(entity_id)), (None, None))
        other_id, related_name = other
        if not related_name or related_name in seen:
            continue
        seen.add(related_name)

        rel_type = _CATEGORY_LABELS.get(attrs.get("category_id")) or attrs.get("description1") or "Connection"
        url = f"{_BASE}/person/{other_id}" if other_id else f"{_BASE}/entities/{entity_id}"
        edges.append({
            "related_name": related_name,
            "relationship_type": rel_type,
            "url": url,
            "source_api": "LittleSis",
        })
        if len(edges) >= _MAX_RELATIONSHIPS:
            break
    return edges


def get_littlesis_data(full_name: str) -> list:
    """
    Queries LittleSis API for a given politician's name.
    Returns a list of unconfirmed mentions/relationships.
    """
    # LittleSis Entities Search Endpoint
    # Format: https://littlesis.org/api/entities/search?q=NAME
    
    url = f"https://littlesis.org/api/entities/search?q={full_name}"
    headers = {"Accept": "application/json"}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for entity in data.get('data', [])[:5]: # Get top 5 matches
            attr = entity.get('attributes', {})
            summary = attr.get('summary', '')
            if not summary:
                summary = f"Found entity {attr.get('name')} with LittleSis ID {entity.get('id')}"
            
            results.append({
                "content_summary": summary,
                "url": attr.get('uri', f"https://littlesis.org/entities/{entity.get('id')}"),
                "sentiment_score": None # LittleSis doesn't natively provide sentiment
            })
        return results
    except Exception as e:
        print(f"Error fetching LittleSis data for {full_name}: {e}")
        return []
