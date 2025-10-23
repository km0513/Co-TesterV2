"""
Test Google Computer Use Implementation

Simple test script to verify the Computer Use endpoint works correctly.
Run this after starting the Flask app.
"""

import requests
import json

BASE_URL = "http://localhost:5000"
ENDPOINT = f"{BASE_URL}/api/browseruse/custom-instruction"

def test_simple_search():
    """Test simple Google search"""
    print("=" * 60)
    print("TEST 1: Simple Google Search")
    print("=" * 60)
    
    payload = {
        "instruction": "Go to google.com and search for 'playwright automation'"
    }
    
    print(f"\n📤 Sending request: {payload['instruction']}")
    
    response = requests.post(ENDPOINT, json=payload)
    result = response.json()
    
    print(f"\n📥 Response Status: {response.status_code}")
    print(f"✅ Success: {result.get('success')}")
    print(f"🔢 Steps: {result.get('steps_executed')}")
    print(f"🌐 Final URL: {result.get('final_url')}")
    print(f"📝 Result: {result.get('result')}")
    
    if result.get('error'):
        print(f"❌ Error: {result.get('error')}")
        print(f"📄 Details: {result.get('details', '')[:500]}")
    
    return result.get('success', False)


def test_amazon_search():
    """Test Amazon product search"""
    print("\n" + "=" * 60)
    print("TEST 2: Amazon Product Search")
    print("=" * 60)
    
    payload = {
        "instruction": "Navigate to amazon.com and search for 'wireless mouse'"
    }
    
    print(f"\n📤 Sending request: {payload['instruction']}")
    
    response = requests.post(ENDPOINT, json=payload)
    result = response.json()
    
    print(f"\n📥 Response Status: {response.status_code}")
    print(f"✅ Success: {result.get('success')}")
    print(f"🔢 Steps: {result.get('steps_executed')}")
    print(f"🌐 Final URL: {result.get('final_url')}")
    print(f"📝 Result: {result.get('result')}")
    
    if result.get('error'):
        print(f"❌ Error: {result.get('error')}")
        print(f"📄 Details: {result.get('details', '')[:500]}")
    
    return result.get('success', False)


def test_github_navigation():
    """Test GitHub navigation"""
    print("\n" + "=" * 60)
    print("TEST 3: GitHub Navigation")
    print("=" * 60)
    
    payload = {
        "instruction": "Go to github.com and search for 'python automation'"
    }
    
    print(f"\n📤 Sending request: {payload['instruction']}")
    
    response = requests.post(ENDPOINT, json=payload)
    result = response.json()
    
    print(f"\n📥 Response Status: {response.status_code}")
    print(f"✅ Success: {result.get('success')}")
    print(f"🔢 Steps: {result.get('steps_executed')}")
    print(f"🌐 Final URL: {result.get('final_url')}")
    print(f"📝 Result: {result.get('result')}")
    
    if result.get('error'):
        print(f"❌ Error: {result.get('error')}")
        print(f"📄 Details: {result.get('details', '')[:500]}")
    
    return result.get('success', False)


def main():
    """Run all tests"""
    print("\n🚀 GOOGLE COMPUTER USE TESTS")
    print("=" * 60)
    print("Testing the new Computer Use implementation")
    print("Make sure Flask app is running on http://localhost:5000")
    print("=" * 60)
    
    results = []
    
    try:
        # Test 1: Simple search
        results.append(("Google Search", test_simple_search()))
        
        # Test 2: Amazon search
        results.append(("Amazon Search", test_amazon_search()))
        
        # Test 3: GitHub navigation
        results.append(("GitHub Navigation", test_github_navigation()))
        
    except Exception as e:
        print(f"\n❌ FATAL ERROR: {e}")
        print("\n⚠️  Make sure:")
        print("   1. Flask app is running: python app.py")
        print("   2. GOOGLE_API_KEY is set in .env")
        print("   3. Playwright is installed: playwright install chromium")
        return
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    total = len(results)
    passed = sum(1 for _, s in results if s)
    
    print(f"\n📈 Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print("💰 Cost: Uses your existing Google AI credits (very low cost!)")
    else:
        print("⚠️  Some tests failed. Check errors above.")


if __name__ == "__main__":
    main()
