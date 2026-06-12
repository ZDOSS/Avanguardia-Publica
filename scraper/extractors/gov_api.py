import requests
import yaml

def get_congress_members():
    """
    Fetches the active members of the US Congress (Senators and Representatives).
    Uses the official open-source repository maintained by the @unitedstates project.
    """
    url = "https://raw.githubusercontent.com/unitedstates/congress-legislators/main/legislators-current.yaml"
    print("Fetching active members of US Congress from @unitedstates repository...")
    
    # Removed try-except block based on Greptile review to prevent silent failures.
    # If the network request fails, the script will crash loudly and alert the scheduler.
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    data = yaml.safe_load(response.text)
    
    if not data:
        raise ValueError("Failed to parse YAML: the returned data is empty or invalid.")
    
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
