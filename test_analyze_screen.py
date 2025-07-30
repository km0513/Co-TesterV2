import requests
import base64
import json
import os
import sys

def test_analyze_screen_endpoint():
    # Path to a test image
    image_path = sys.argv[1] if len(sys.argv) > 1 else "test_screenshot.png"
    
    if not os.path.exists(image_path):
        print(f"Error: Image file not found at {image_path}")
        return
    
    # Convert image to base64
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
    
    # Prepare request data
    data = {
        "image": base64_image,
        "options": {
            "alignment": True,
            "text": True,
            "contrast": True,
            "consistency": True
        }
    }
    
    # Send request to the endpoint
    url = "http://localhost:5050/api/analyze-screen"
    print(f"Sending request to {url}...")
    
    try:
        response = requests.post(url, json=data)
        
        # Print response status and headers
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {response.headers}")
        
        # Print response content
        if response.status_code == 200:
            result = response.json()
            
            # Print OCR text (truncated)
            ocr_text = result.get('ocr_text', '')
            print(f"\nOCR Text (first 200 chars): {ocr_text[:200]}...")
            
            # Print issues
            issues = result.get('issues', [])
            print(f"\nIssues found: {len(issues)}")
            for i, issue in enumerate(issues):
                print(f"\nIssue {i+1}:")
                print(f"  Title: {issue.get('title', 'No title')}")
                print(f"  Severity: {issue.get('severity', 'No severity')}")
                print(f"  Description: {issue.get('description', 'No description')[:100]}...")
            
            # Print recommendations
            recommendations = result.get('recommendations', [])
            print(f"\nRecommendations: {len(recommendations)}")
            for i, rec in enumerate(recommendations):
                print(f"  {i+1}. {rec[:100]}...")
            
            # Save full response to file for detailed inspection
            with open("analyze_screen_response.json", "w") as f:
                json.dump(result, f, indent=2)
            print("\nFull response saved to analyze_screen_response.json")
            
        else:
            print(f"Error response: {response.text}")
    
    except Exception as e:
        print(f"Exception occurred: {str(e)}")

if __name__ == "__main__":
    test_analyze_screen_endpoint()
