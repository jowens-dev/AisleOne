import requests
import sys
import uuid

# Default Render URL (override via command line: python test_live_api.py https://custom-url.onrender.com)
BASE_URL = "https://aisleone-api.onrender.com"
if len(sys.argv) > 1:
    BASE_URL = sys.argv[1].rstrip("/")

def test_production_api():
    print(f"Pinging production API at: {BASE_URL}...")
    
    try:
        # Step 1: Check server uptime with /health
        health_resp = requests.get(f"{BASE_URL}/health", timeout=15)
        health_resp.raise_for_status()
        print("✅ [SERVER] API is live and accepting requests!")
        
        # Step 2: Register a temporary user to verify DB writes
        temp_username = f"testuser_{uuid.uuid4().hex[:6]}"
        temp_password = "TestPassword123!"
        print(f"Registering temporary user: {temp_username}...")
        
        reg_resp = requests.post(
            f"{BASE_URL}/auth/register",
            json={"username": temp_username, "password": temp_password},
            timeout=15
        )
        reg_resp.raise_for_status()
        print("✅ [DATABASE] Registration successful (Write verified)!")
        
        # Step 3: Authenticate and get JWT Token
        print("Logging in to retrieve token...")
        token_resp = requests.post(
            f"{BASE_URL}/auth/token",
            json={"username": temp_username, "password": temp_password},
            timeout=15
        )
        token_resp.raise_for_status()
        token_data = token_resp.json()
        token = token_data.get("access_token")
        print("✅ [AUTHENTICATION] Obtained token successfully!")
        
        # Step 4: Perform search query (reads database)
        headers = {"Authorization": f"Bearer {token}"}
        print("Searching for product: 'milk'...")
        search_resp = requests.get(
            f"{BASE_URL}/search",
            params={"q": "milk"},
            headers=headers,
            timeout=15
        )
        search_resp.raise_for_status()
        results = search_resp.json()
        
        # Verify that the Turso DB actually returned rows
        if len(results) > 0:
            print(f"✅ [DATABASE] Turso query verified! Retrieved {len(results)} records.")
            sample = results[0]
            print(f"   -> Sample: {sample.get('raw_name', 'Unknown')} at ${sample.get('price', 'Unknown price')}")
        else:
            print("⚠️ [WARNING] API responded, but returned empty search results. Ensure the Turso database was seeded.")
            
    except requests.exceptions.ConnectionError:
        print("❌ [ERROR] Could not connect. Is the Render URL correct and has the build finished?")
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(f"❌ [ERROR] HTTP Error returned: {e}")
        sys.exit(1)
    except requests.exceptions.Timeout:
        print("❌ [ERROR] Request timed out. The Render server might be waking up from sleep.")
        sys.exit(1)

if __name__ == "__main__":
    test_production_api()
