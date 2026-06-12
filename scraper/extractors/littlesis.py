import os
import requests

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
