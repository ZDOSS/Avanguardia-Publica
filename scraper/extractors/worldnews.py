import os
import requests

def get_news_data(full_name: str) -> list:
    """
    Queries World News API for recent articles mentioning the politician.
    Returns a list of unconfirmed mentions.
    """
    api_key = os.environ.get("WORLDNEWS_API_KEY")
    if not api_key:
        print("WORLDNEWS_API_KEY not found, skipping World News extraction.")
        return []

    # Example endpoint for World News API
    url = "https://api.worldnewsapi.com/search-news"
    params = {
        "text": full_name,
        "language": "en",
        "number": 10, # Spec limits to top 10 articles
        "api-key": api_key
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for article in data.get('news', []):
            results.append({
                "content_summary": article.get('title', '') + " - " + article.get('summary', '')[:200],
                "url": article.get('url', ''),
                "sentiment_score": article.get('sentiment', 0.0)
            })
        return results
    except Exception as e:
        print(f"Error fetching World News data for {full_name}: {e}")
        return []
