import os
import time
from dotenv import load_dotenv
from loader import SupabaseLoader
from extractors.gov_api import get_cabinet_members
from extractors.littlesis import get_littlesis_data
from extractors.worldnews import get_news_data
from extractors.wikidata import get_wikidata_bio

def main():
    load_dotenv()
    print("Starting Avanguardia-Publica Phase 0.1 Scraper Pipeline...")
    
    # Initialize DB connection
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    loader = SupabaseLoader(supabase_url, supabase_key)
    
    # 1. Fetch active cabinet members
    members = get_cabinet_members()
    print(f"Found {len(members)} cabinet members.")
    
    # 2. Iterate through each member and scrape third-party data sequentially
    total = len(members)
    for index, member in enumerate(members, start=1):
        print(f"\n--- [{index}/{total}] Scraping data for {member['full_name']} ---")
        
        # Try to augment with Wikidata (e.g. get bioguide_id)
        wiki_bio = get_wikidata_bio(member['full_name'])
        if wiki_bio.get('bioguide_id'):
            member['bioguide_id'] = wiki_bio['bioguide_id']
            print(f"  [+] Found bioguide_id: {member['bioguide_id']}")

        # Upsert Hub (politicians table)
        politician_id = loader.upsert_politician(member)
        
        # Only proceed with third-party data if we successfully upserted the politician
        if politician_id and politician_id != "dummy-uuid":
            # Scrape LittleSis
            print("  [*] Fetching LittleSis data...")
            ls_data = get_littlesis_data(member['full_name'])
            loader.process_mentions(politician_id, ls_data, 'LittleSis')
            
            # Scrape World News
            print("  [*] Fetching World News data...")
            news_data = get_news_data(member['full_name'])
            loader.process_mentions(politician_id, news_data, 'WorldNews')
            
        # Respect API rate limits for downstream services
        time.sleep(1)
        
    print("\nPipeline finished successfully.")

if __name__ == "__main__":
    main()
