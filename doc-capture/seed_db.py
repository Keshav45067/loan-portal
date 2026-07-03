import json
import psycopg2

DATABASE_URL = "postgresql://postgres:nImr1327!@34.14.191.93:5432/smart-mudraa"

# Paths to the JSON configs
AADHAAR_JSON_PATH = "../../hindi/aadhaar.json"
SCHEME_JSON_PATH = "../../hindi/scheme.json"

def seed():
    print("Seeding database...")
    
    # Load JSON files
    with open(AADHAAR_JSON_PATH, "r", encoding="utf-8") as f:
        aadhaar_data = json.load(f)
        
    with open(SCHEME_JSON_PATH, "r", encoding="utf-8") as f:
        scheme_data = json.load(f)
        
    document_id = aadhaar_data.get("document_id")
    scheme_id = scheme_data.get("scheme_id")
    
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    
    try:
        with conn.cursor() as cur:
            # Upsert Document
            print(f"Inserting document config for ID: {document_id}")
            cur.execute("""
                INSERT INTO documents_json (id, json) 
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET json = EXCLUDED.json, updated_at = NOW()
            """, (document_id, json.dumps(aadhaar_data)))
            
            # Upsert Scheme
            print(f"Inserting scheme config for ID: {scheme_id}")
            cur.execute("""
                INSERT INTO schemes_json (id, json) 
                VALUES (%s, %s)
                ON CONFLICT (id) DO UPDATE SET json = EXCLUDED.json, updated_at = NOW()
            """, (scheme_id, json.dumps(scheme_data)))
            
            print("Successfully inserted DB entries.")
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    seed()
