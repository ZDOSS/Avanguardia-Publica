import os
from supabase import create_client, Client

class SupabaseLoader:
    def __init__(self, url: str, key: str):
        if url and key:
            self.supabase: Client = create_client(url, key)
            print("Supabase client initialized.")
        else:
            self.supabase = None
            print("Warning: SUPABASE_URL or SUPABASE_KEY is not set. Running in dry-run mode.")

    def upsert_politician(self, member_data: dict):
        """
        Upserts a politician into the Hub table and returns the UUID.
        """
        if not self.supabase:
            print(f"  [Dry-run] Upserting politician {member_data['full_name']}")
            return "dummy-uuid"
            
        try:
            # We use full_name as the primary match constraint since bioguide_id isn't always present
            # However, Supabase upsert requires a unique constraint. If full_name is unique, we could upsert.
            # For this pipeline, we will check if they exist first, if not insert.
            response = self.supabase.table('politicians').select('id').eq('full_name', member_data['full_name']).execute()
            
            data_to_insert = {
                "full_name": member_data.get('full_name'),
                "current_office": member_data.get('current_office'),
                "party": member_data.get('party'),
            }
            if member_data.get('bioguide_id'):
                data_to_insert['bioguide_id'] = member_data['bioguide_id']

            if response.data:
                # Update existing
                p_id = response.data[0]['id']
                self.supabase.table('politicians').update(data_to_insert).eq('id', p_id).execute()
                print(f"  [+] Updated Hub for {member_data['full_name']}")
                return p_id
            else:
                # Insert new
                insert_resp = self.supabase.table('politicians').insert(data_to_insert).execute()
                if insert_resp.data:
                    p_id = insert_resp.data[0]['id']
                    print(f"  [+] Inserted new Hub for {member_data['full_name']}")
                    return p_id
        except Exception as e:
            print(f"  [!] Error upserting politician {member_data['full_name']}: {e}")
        
        return None

    def process_mentions(self, politician_id: str, data_list: list, source_api: str):
        """
        Takes third party data and links it to the politician as an unconfirmed mention.
        """
        if not data_list:
            return
            
        if not self.supabase:
            print(f"  [Dry-run] Inserted {len(data_list)} mentions from {source_api}")
            return
            
        inserted_count = 0
        for item in data_list:
            mention_data = {
                "politician_id": politician_id,
                "source_api": source_api,
                "content_summary": item.get('content_summary', ''),
                "url": item.get('url'),
                "sentiment_score": item.get('sentiment_score')
            }
            try:
                # Insert without failing on duplicate url per politician (can be handled by UNIQUE constraint)
                # But to avoid crashing the loop, we catch exceptions.
                self.supabase.table('unconfirmed_mentions').insert(mention_data).execute()
                inserted_count += 1
            except Exception as e:
                # Could be a unique constraint violation if the URL was already logged, which is fine
                pass
                
        print(f"  [+] Added {inserted_count} new mentions from {source_api}")
