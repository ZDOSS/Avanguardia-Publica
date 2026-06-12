import requests

def get_wikidata_bio(full_name: str) -> dict:
    """
    Queries Wikidata for additional biographical data (like bioguide_id).
    Returns a dictionary of confirmed biographical properties.
    """
    # Wikidata SPARQL endpoint
    url = "https://query.wikidata.org/sparql"
    
    # We search for the person by English label and see if they have a US Congress Bio ID (P1157)
    query = f"""
    SELECT ?item ?itemLabel ?bioguide WHERE {{
      ?item rdfs:label "{full_name}"@en.
      OPTIONAL {{ ?item wdt:P1157 ?bioguide. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
    }} LIMIT 1
    """
    
    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": "AvanguardiaPublica/1.0 (https://github.com/Avanguardia-Publica)"
    }
    
    try:
        response = requests.get(url, params={'query': query}, headers=headers)
        response.raise_for_status()
        data = response.json()
        
        results = data.get('results', {}).get('bindings', [])
        if results:
            first_match = results[0]
            return {
                "bioguide_id": first_match.get("bioguide", {}).get("value")
            }
        return {}
    except Exception as e:
        print(f"Error fetching Wikidata for {full_name}: {e}")
        return {}
