import requests
import yaml

def get_cabinet_members():
    """
    Fetches the active members of the US Congress (Senators and Representatives).
    Uses the official open-source repository maintained by the @unitedstates project.
    """
    url = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
    print("Fetching active members of US Congress from @unitedstates repository...")
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = yaml.safe_load(response.text)
        
        politicians = []
        for legislator in data:
            name_obj = legislator.get("name", {})
            term_obj = legislator.get("terms", [])[-1] if legislator.get("terms") else {}
            
            # Format Name
            first = name_obj.get("first", "")
            last = name_obj.get("last", "")
            full_name = f"{first} {last}".strip()
            
            # Format Office
            office_type = term_obj.get("type", "")
            state = term_obj.get("state", "")
            if office_type == "sen":
                office = f"US Senator from {state}"
            elif office_type == "rep":
                district = term_obj.get("district", "")
                office = f"US Representative from {state}-{district}"
            else:
                office = "Unknown Office"
                
            # Format Party
            party = term_obj.get("party", "Independent")
            
            politicians.append({
                "full_name": full_name,
                "current_office": office,
                "party": party
            })
            
        print(f"Successfully loaded {len(politicians)} active members of Congress.")
        return politicians
    except Exception as e:
        print(f"Failed to fetch or parse Congress data: {e}")
        return []
