"""
Quick test to verify Google Computer Use is working

Run this while Flask app is running to test the endpoint.
"""

import requests
import json
import time

BASE_URL = "http://localhost:5000"
ENDPOINT = f"{BASE_URL}/api/browseruse/custom-instruction"

def test_simple():
    """Test with a very simple instruction"""
    print("\n" + "="*60)
    print("🧪 TESTING GOOGLE COMPUTER USE")
    print("="*60)
    
    instruction = "Go to google.com"
    
    print(f"\n📝 Instruction: {instruction}")
    print("⏳ Sending request...")
    
    start_time = time.time()
    
    try:
        response = requests.post(
            ENDPOINT, 
            json={"instruction": instruction},
            timeout=120  # 2 minute timeout
        )
        
        elapsed = time.time() - start_time
        
        print(f"\n⏱️  Response time: {elapsed:.2f} seconds")
        print(f"📡 Status code: {response.status_code}")
        
        result = response.json()
        print(f"\n📦 Response:")
        print(json.dumps(result, indent=2))
        
        if result.get("success"):
            print("\n✅ SUCCESS!")
            print(f"✅ Steps: {result.get('steps_executed')}")
            print(f"✅ Final URL: {result.get('final_url')}")
            print(f"✅ Result: {result.get('result')}")
        else:
            print("\n❌ FAILED!")
            print(f"❌ Error: {result.get('error')}")
            if result.get('details'):
                print(f"📄 Details:\n{result.get('details')}")
        
    except requests.exceptions.Timeout:
        print("\n⏱️  TIMEOUT - Request took longer than 2 minutes")
        print("Check Flask console for logs")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ CONNECTION ERROR")
        print("Is Flask running? Start with: python app.py")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
    
    print("\n" + "="*60)

if __name__ == "__main__":
    print("\n🚀 Google Computer Use Test")
    print("Make sure Flask app is running!")
    print("You should see a browser window open...")
    print("\nPress Ctrl+C to cancel\n")
    
    time.sleep(2)
    test_simple()
