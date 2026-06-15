import os
import sys
import time
import logging
from dotenv import load_dotenv
from loader import SupabaseLoader
from extractors.gov_api import get_congress_members
from extractors.littlesis import get_littlesis_data
from extractors.news_aggregator import get_news_data

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
)

def main():
    load_dotenv()
    print("Starting Avanguardia-Publica Phase 1 Scraper Pipeline...")
    
    # Initialize DB connection
    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_KEY")
    loader = SupabaseLoader(supabase_url, supabase_key)
    
    # 1. Fetch active Congress members
    members = get_congress_members()
    print(f"Found {len(members)} Congress members.")
    
    # 2. Iterate through each member and scrape third-party data sequentially
    total = len(members)
    errors_caught = 0
    for index, member in enumerate(members, start=1):
        try:
            print(f"\n--- [{index}/{total}] Scraping data for {member['full_name']} ---")

            # bioguide_id + the full ID crosswalk now come straight from the free
            # congress-legislators dataset (see gov_api.py) — no fragile Wikidata
            # name lookup required.
            if member.get('bioguide_id'):
                print(f"  [+] bioguide_id: {member['bioguide_id']}")

            # Upsert Hub (politicians table)
            politician_id = loader.upsert_politician(member)

            # Only proceed with third-party data if we successfully upserted the politician
            if politician_id and politician_id != "dummy-uuid":
                # Store official contact info (verified spoke, sourced from the dataset)
                loader.upsert_contact_info(politician_id, member.get('contact', {}))

                # Scrape LittleSis
                print("  [*] Fetching LittleSis data...")
                ls_data = get_littlesis_data(member['full_name'])
                loader.process_mentions(politician_id, ls_data, 'LittleSis')
                
                # Fetch news via multi-tier aggregator (Currents → NewsData → TheNewsAPI → GDELT)
                print("  [*] Fetching news data (multi-tier aggregator)...")
                news_data = get_news_data(member['full_name'])
                loader.process_mentions(politician_id, news_data, 'NewsAggregator')
        except Exception as e:
            print(f"  [!] Error scraping {member['full_name']}: {e}")
            errors_caught += 1
        finally:
            # Respect API rate limits for downstream services
            time.sleep(1)
        
    if errors_caught == 0:
        print("\nPipeline finished successfully.")
    else:
        print(f"\nPipeline finished with {errors_caught} errors.")
        sys.exit(1)

if __name__ == "__main__":
    main()
