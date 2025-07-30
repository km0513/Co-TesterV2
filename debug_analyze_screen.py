import os
import base64
import json
import re
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('debug_analyze_screen')

# Mock the Azure OpenAI response for testing
MOCK_RESPONSE = {
    "issues": [
        {
            "title": "Inconsistent Button Styling",
            "severity": "Medium",
            "description": "The primary action buttons have inconsistent styling. Some use rounded corners while others have sharp corners.",
            "location": "Throughout the interface"
        },
        {
            "title": "Poor Text Contrast",
            "severity": "High",
            "description": "The light gray text on white background in the sidebar has insufficient contrast, making it difficult to read.",
            "location": "Left sidebar"
        }
    ],
    "recommendations": [
        "Standardize button styling across the interface for better visual consistency.",
        "Increase text contrast in the sidebar to meet WCAG AA accessibility standards.",
        "Consider adding more spacing between UI elements to improve readability."
    ]
}

def debug_analyze_screen():
    """Debug function to simulate the analyze_screen endpoint behavior"""
    logger.info("Starting debug analysis")
    
    # Load a test image
    image_path = "automation/demoScreenshot/image.png"
    if not os.path.exists(image_path):
        logger.error(f"Test image not found at {image_path}")
        return
    
    logger.info(f"Using test image: {image_path}")
    
    # Convert image to base64
    with open(image_path, "rb") as image_file:
        base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        logger.info(f"Image converted to base64 (first 20 chars): {base64_image[:20]}...")
    
    # Simulate the AI response parsing logic from app.py
    ai_response = json.dumps(MOCK_RESPONSE)
    logger.info(f"Mock AI response: {ai_response}")
    
    # Try to parse JSON from AI response (simulating the updated app.py logic)
    try:
        logger.info("Attempting to parse AI response")
        
        # Find JSON content in the response (it might be wrapped in markdown code blocks)
        json_match = re.search(r'```json\n(.+?)\n```', ai_response, re.DOTALL)
        if json_match:
            logger.info("Found JSON in code block")
            json_content = json_match.group(1)
            logger.info(f"Extracted JSON: {json_content}")
            ai_results = json.loads(json_content)
        else:
            # First try to parse the entire response as JSON directly
            try:
                logger.info("Attempting to parse entire response as JSON")
                ai_results = json.loads(ai_response)
                logger.info("Successfully parsed entire response as JSON")
            except json.JSONDecodeError:
                # If that fails, try to extract JSON from the response
                logger.info("Direct JSON parsing failed, trying to extract JSON")
                
                # Look for a JSON object that contains both issues and recommendations
                # Use a more robust regex pattern that captures the entire JSON object
                json_match = re.search(r'\{[\s\S]*?"issues"[\s\S]*?"recommendations"[\s\S]*?\}', ai_response)
                if json_match:
                    logger.info("Found JSON-like content with issues and recommendations")
                    json_content = json_match.group(0)
                    logger.info(f"Extracted JSON-like content: {json_content}")
                    # Try to clean up and parse
                    try:
                        ai_results = json.loads(json_content)
                    except json.JSONDecodeError:
                        logger.warning("Could not parse JSON-like content, using manual extraction")
                        # Create a structured response manually from the AI text
                        ai_results = {
                            'issues': [],
                            'recommendations': []
                        }
            else:
                logger.info("Attempting to parse entire response as JSON")
                # Try to parse the entire response as JSON
                try:
                    ai_results = json.loads(ai_response)
                except json.JSONDecodeError:
                    logger.warning("Failed to parse response as JSON, creating manual structure")
                    # Create a structured response manually from the AI text
                    ai_results = {
                        'issues': [{
                            'title': 'UI Analysis',
                            'severity': 'Medium',
                            'description': ai_response[:200]
                        }],
                        'recommendations': ['Review the complete analysis for detailed recommendations.']
                    }
        
        logger.info(f"Parsed AI results: {ai_results}")
        
        # Force issues to be found - NEVER return "no issues found"
        # If no issues were detected or parsing failed, create default issues
        if 'issues' not in ai_results or not ai_results['issues']:
            logger.info("No issues found in AI response, creating default issues")
            
            # Always create at least one issue
            default_issues = [{
                'title': 'UI Enhancement Opportunity',
                'severity': 'Low',
                'description': 'While no critical issues were detected, consider reviewing the UI for potential improvements in alignment, spacing, and visual hierarchy.'
            }]
            
            ai_results['issues'] = default_issues
        
        # Ensure we have recommendations
        if 'recommendations' not in ai_results or not ai_results['recommendations']:
            logger.info("No recommendations found, adding defaults")
            ai_results['recommendations'] = [
                'Review the UI with actual users to validate the design and identify any usability concerns.',
                'Consider A/B testing different UI variations to optimize user experience.',
                'Ensure the UI follows accessibility guidelines for all users.'
            ]
            
        # Return the final result structure
        result = {
            'ocr_text': "Sample OCR text for testing",
            'issues': ai_results.get('issues', []),
            'recommendations': ai_results.get('recommendations', [])
        }
        
        logger.info(f"Final result: {json.dumps(result, indent=2)}")
        
        # Save the result to a file for inspection
        with open("debug_analyze_screen_result.json", "w") as f:
            json.dump(result, f, indent=2)
        logger.info("Result saved to debug_analyze_screen_result.json")
        
        return result
        
    except Exception as e:
        logger.error(f"Error in debug analysis: {str(e)}")
        return {'error': str(e)}

if __name__ == "__main__":
    debug_analyze_screen()
