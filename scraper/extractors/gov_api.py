import requests
from bs4 import BeautifulSoup

def get_cabinet_members():
    """
    Fetches the current US Cabinet members.
    For Phase 0.1, we'll parse a reliable public source or use a static fallback if the page structure changes.
    Here we use a hardcoded list of key roles to simulate the extraction, 
    as official APIs for this specific list are sparse.
    """
    # In a fully productionized version, this could parse WhiteHouse.gov or Congress.gov APIs.
    # For now, providing a robust initial dataset for the pipeline.
    cabinet = [
        {"full_name": "Joe Biden", "current_office": "President of the United States", "party": "Democratic"},
        {"full_name": "Kamala Harris", "current_office": "Vice President of the United States", "party": "Democratic"},
        {"full_name": "Antony Blinken", "current_office": "Secretary of State", "party": "Democratic"},
        {"full_name": "Janet Yellen", "current_office": "Secretary of the Treasury", "party": "Democratic"},
        {"full_name": "Lloyd Austin", "current_office": "Secretary of Defense", "party": "Independent"},
        {"full_name": "Merrick Garland", "current_office": "Attorney General", "party": "Independent"},
        {"full_name": "Deb Haaland", "current_office": "Secretary of the Interior", "party": "Democratic"},
        {"full_name": "Tom Vilsack", "current_office": "Secretary of Agriculture", "party": "Democratic"},
        {"full_name": "Gina Raimondo", "current_office": "Secretary of Commerce", "party": "Democratic"},
        {"full_name": "Julie Su", "current_office": "Acting Secretary of Labor", "party": "Democratic"},
        {"full_name": "Xavier Becerra", "current_office": "Secretary of Health and Human Services", "party": "Democratic"},
        {"full_name": "Marcia Fudge", "current_office": "Secretary of Housing and Urban Development", "party": "Democratic"},
        {"full_name": "Pete Buttigieg", "current_office": "Secretary of Transportation", "party": "Democratic"},
        {"full_name": "Jennifer Granholm", "current_office": "Secretary of Energy", "party": "Democratic"},
        {"full_name": "Miguel Cardona", "current_office": "Secretary of Education", "party": "Democratic"},
        {"full_name": "Denis McDonough", "current_office": "Secretary of Veterans Affairs", "party": "Democratic"},
        {"full_name": "Alejandro Mayorkas", "current_office": "Secretary of Homeland Security", "party": "Democratic"}
    ]
    return cabinet
