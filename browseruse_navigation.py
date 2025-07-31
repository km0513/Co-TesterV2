"""
Browser automation module for Curlrunner using Playwright
"""
import base64
import logging
import os
from flask import jsonify, request, current_app
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Check if Playwright is available
try:
    from playwright.sync_api import sync_playwright
    playwright_available = True
    logger.info("Playwright is available for browser automation")
except ImportError:
    playwright_available = False
    logger.warning("Playwright is not available. Browser automation will be disabled.")

# Check if we should run in headless mode (default to True)
PLAYWRIGHT_HEADLESS = os.environ.get('PLAYWRIGHT_HEADLESS', 'true').lower() == 'true'

def browseruse_navigation_executor():
    """Handle browser automation requests from the frontend"""
    logger.info("Browser automation endpoint called")
    logger.info(f"Running in {'production' if os.environ.get('FLASK_ENV') == 'production' else 'development'} mode")
    logger.info(f"Playwright headless mode: {PLAYWRIGHT_HEADLESS}")
    
    # Log system information
    import platform
    logger.info(f"System: {platform.system()}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"Python version: {platform.python_version()}")
    
    try:
        # Check if Playwright is available (this should be defined in the main app)
        if 'playwright_available' in globals() and not playwright_available:
            logger.error("Playwright is not installed. Cannot run browser automation.")
            return jsonify({
                'success': False,
                'error': 'Playwright is not installed. Please install it with: pip install playwright && playwright install',
                'report': {
                    'message': 'Browser automation is not available. Playwright is not installed.'
                }
            }), 500
        
        # Parse request data
        data = request.get_json()
        logger.info(f"Received data: {data is not None}")
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        prompt = data.get('prompt')
        steps = data.get('steps')
        capture_screenshot = data.get('captureScreenshotOnFailure', True)
        
        logger.info(f"Prompt: {prompt[:50] if prompt else 'None'}... Steps: {len(steps) if steps else 0}")
        
        if not prompt or not steps:
            return jsonify({'success': False, 'error': 'Missing prompt or steps'}), 400
        
        logger.info(f"Running browser automation with {len(steps)} steps")
        
        # Initialize variables
        results = []
        failure_screenshot = None
        success = True
        
        # Run browser automation
        with sync_playwright() as p:
            # Configure browser launch options for both local and production
            browser_options = {
                'headless': PLAYWRIGHT_HEADLESS,  # True in prod, configurable locally
                'args': [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--no-first-run',
                    '--no-zygote',
                    '--disable-gpu',
                    '--disable-audio-output',
                    '--window-size=1920,1080'
                ]
            }
            browser = p.chromium.launch(**browser_options)
            context = browser.new_context()
            page = context.new_page()
            
            try:
                # Execute each automation step
                for i, step in enumerate(steps):
                    action = step.get('action')
                    logger.info(f"Executing step {i+1}/{len(steps)}: {action}")
                    
                    if action == 'navigate':
                        url = step.get('url')
                        if not url:
                            raise ValueError("URL is required for navigate action")
                        page.goto(url, wait_until='networkidle')
                        results.append({'step': i, 'action': action, 'success': True})
                    
                    elif action == 'click':
                        selector = step.get('selector')
                        if not selector:
                            raise ValueError("Selector is required for click action")
                        page.click(selector)
                        results.append({'step': i, 'action': action, 'success': True})
                    
                    elif action == 'fill':
                        selector = step.get('selector')
                        value = step.get('value')
                        if not selector or value is None:
                            raise ValueError("Selector and value are required for fill action")
                        page.fill(selector, value)
                        results.append({'step': i, 'action': action, 'success': True})
                    
                    elif action == 'wait_for_element':
                        selector = step.get('selector')
                        if not selector:
                            raise ValueError("Selector is required for wait_for_element action")
                        page.wait_for_selector(selector)
                        results.append({'step': i, 'action': action, 'success': True})
                    
                    elif action == 'wait_for_navigation':
                        page.wait_for_load_state('networkidle')
                        results.append({'step': i, 'action': action, 'success': True})
                    
                    elif action == 'screenshot':
                        screenshot = page.screenshot()
                        screenshot_base64 = base64.b64encode(screenshot).decode('utf-8')
                        results.append({
                            'step': i, 
                            'action': action, 
                            'success': True,
                            'screenshot': f"data:image/png;base64,{screenshot_base64}"
                        })
                    
                    elif action == 'custom':
                        # Custom instructions are just logged, not executed
                        instruction = step.get('instruction', '')
                        results.append({'step': i, 'action': action, 'success': True, 'instruction': instruction})
                    
                    else:
                        # For unsupported actions, log a warning but continue
                        logger.warning(f"Unsupported action: {action}")
                        results.append({'step': i, 'action': action, 'success': False, 'error': 'Unsupported action'})
            
            except Exception as e:
                logger.error(f"Error during browser automation: {str(e)}")
                success = False
                if capture_screenshot:
                    try:
                        screenshot = page.screenshot()
                        failure_screenshot = f"data:image/png;base64,{base64.b64encode(screenshot).decode('utf-8')}"
                    except Exception as screenshot_error:
                        logger.error(f"Failed to capture failure screenshot: {str(screenshot_error)}")
            
            finally:
                browser.close()
        
        # Prepare response
        report = {
            'steps_executed': len(results),
            'total_steps': len(steps),
            'success': success,
            'message': 'Automation completed successfully' if success else 'Automation failed'
        }
        
        if failure_screenshot:
            report['failureScreenshot'] = failure_screenshot
        
        return jsonify({
            'success': success,
            'steps': results,
            'report': report,
            'rawOutput': f"ActionResult(is_done=True, success={success})\n{prompt}\n{len(results)}/{len(steps)} steps executed."
        })
    
    except Exception as unexpected_error:
        logger.error(f"Unexpected error in browser automation endpoint: {str(unexpected_error)}")
        return jsonify({
            'success': False,
            'error': 'An unexpected error occurred',
            'report': {
                'message': 'Browser automation failed due to an unexpected error. Please check server logs.'
            }
        }), 500
