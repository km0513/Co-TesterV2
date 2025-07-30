"""
Optimized Curlrunner Flask Application
Focused on core routes: home, manual-co-test, screen-analysis, browseruse-automation, data
"""
import os
import base64
os.environ["PLAYWRIGHT_HEADLESS"] = "true"
from dotenv import load_dotenv
load_dotenv()  # This will load variables from .env into os.environ
import logging
import json
from datetime import datetime
import re
from urllib.parse import urlparse
import time
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, Response
import requests
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import pytesseract
from PIL import Image
import google.generativeai as genai

# Jira OAuth constants
JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import Playwright if available
try:
    from playwright.sync_api import sync_playwright
    playwright_available = True
    logger.info("Playwright is available for browser automation")
except ImportError:
    playwright_available = False
    logger.warning("Playwright is not installed. Browser automation will not be available.")

# Import Google AI for AI-powered step generation
try:
    import google.generativeai as genai
    # Initialize Google Generative AI with API key
    if os.getenv('GOOGLE_API_KEY'):
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        logging.info("Google Generative AI initialized successfully")
    else:
        logging.warning("GOOGLE_API_KEY not found in environment variables")
except ImportError:
    # Google AI is optional - we'll fall back to basic step generation if not available
    genai = None
    logging.warning("Google Generative AI library not installed")

# Initialize Flask app
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get('SECRET_KEY', 'devsecret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# Jira OAuth configuration
app.config['JIRA_CLIENT_ID'] = os.environ.get('JIRA_CLIENT_ID_LOCAL', os.environ.get('JIRA_CLIENT_ID', ''))
app.config['JIRA_CLIENT_SECRET'] = os.environ.get('JIRA_CLIENT_SECRET_LOCAL', os.environ.get('JIRA_CLIENT_SECRET', ''))
app.config['JIRA_CALLBACK_URL'] = 'http://127.0.0.1:5000/api/jira/oauth/callback'

# Configure Google Generative AI
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-pro-vision')

# Upload folder for images
UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ===== Database Models =====
# Only keeping essential models needed for the core routes

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password_hash = db.Column(db.String(256))
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Create all tables if not present
with app.app_context():
    db.create_all()

# ===== Helper Functions =====

def chunk_text(text, chunk_size=15000, overlap=1000):
    """Yield successive chunk_size character chunks from text, with optional overlap."""
    if not text:
        return []
    
    chunks = []
    start = 0
    text_len = len(text)
    
    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunks.append(text[start:end])
        start = end - overlap if end < text_len else text_len
    
    return chunks

def find_potential_misspellings(text):
    """
    Analyze OCR text to find potential misspellings or unusual words.
    Returns a list of potentially misspelled words.
    """
    if not text:
        return []
    
    # Split text into words and normalize
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    
    # Common words to ignore (extend as needed)
    common_words = {
        'the', 'and', 'that', 'have', 'for', 'not', 'with', 'you', 'this', 'but',
        'his', 'from', 'they', 'say', 'her', 'she', 'will', 'one', 'all', 'would',
        'there', 'their', 'what', 'out', 'about', 'who', 'get', 'which', 'when', 'make',
        'can', 'like', 'time', 'just', 'him', 'know', 'take', 'people', 'into', 'year',
        'your', 'good', 'some', 'could', 'them', 'see', 'other', 'than', 'then', 'now',
        'look', 'only', 'come', 'its', 'over', 'think', 'also', 'back', 'after', 'use',
        'two', 'how', 'our', 'work', 'first', 'well', 'way', 'even', 'new', 'want',
        'because', 'any', 'these', 'give', 'day', 'most', 'user', 'data', 'system',
        'error', 'file', 'information', 'should', 'product', 'line', 'need', 'test',
        'page', 'form', 'search', 'free', 'article', 'email', 'updated', 'review',
        'software', 'video', 'music', 'people', 'mobile', 'social', 'google', 'twitter',
        'facebook', 'apple', 'amazon', 'microsoft', 'view', 'tools', 'reply', 'message',
        'security', 'login', 'account', 'password', 'username', 'profile', 'settings'
    }
    
    # UI-specific terms to ignore
    ui_terms = {
        'dropdown', 'button', 'checkbox', 'radio', 'toggle', 'slider', 'menu',
        'navbar', 'sidebar', 'footer', 'header', 'modal', 'dialog', 'tooltip',
        'pagination', 'breadcrumb', 'carousel', 'accordion', 'tab', 'navigation',
        'alert', 'badge', 'card', 'progress', 'spinner', 'toast', 'popover',
        'collapse', 'input', 'textarea', 'select', 'option', 'label', 'form',
        'submit', 'reset', 'cancel', 'save', 'delete', 'edit', 'view', 'add',
        'remove', 'update', 'create', 'list', 'table', 'grid', 'column', 'row',
        'cell', 'header', 'footer', 'body', 'container', 'wrapper', 'section',
        'article', 'aside', 'main', 'content', 'layout', 'template', 'theme',
        'style', 'color', 'size', 'width', 'height', 'margin', 'padding', 'border',
        'background', 'foreground', 'text', 'font', 'icon', 'image', 'avatar',
        'logo', 'banner', 'slider', 'carousel', 'gallery', 'lightbox', 'tooltip',
        'popover', 'notification', 'alert', 'message', 'error', 'warning', 'success',
        'info', 'primary', 'secondary', 'tertiary', 'default', 'custom', 'loading',
        'spinner', 'progress', 'status', 'state', 'active', 'inactive', 'disabled',
        'enabled', 'selected', 'unselected', 'checked', 'unchecked', 'expanded',
        'collapsed', 'visible', 'hidden', 'shown', 'login', 'logout', 'signup',
        'register', 'profile', 'account', 'dashboard', 'admin', 'user', 'member',
        'guest', 'anonymous', 'authenticated', 'authorized', 'unauthorized'
    }
    
    # Combine ignore lists
    ignore_words = common_words.union(ui_terms)
    
    # Filter out common words and short words
    unusual_words = [word for word in words if word not in ignore_words and len(word) > 3]
    
    # Count occurrences
    word_counts = {}
    for word in unusual_words:
        word_counts[word] = word_counts.get(word, 0) + 1
    
    # Find potential misspellings (words that appear only once or twice)
    potential_misspellings = [word for word, count in word_counts.items() if count < 3]
    
    return potential_misspellings[:20]  # Limit to top 20 to avoid overwhelming

def extract_issues_manually(text):
    """
    Extract issues and recommendations from raw AI response text when JSON parsing fails.
    Uses regex patterns to find issues and recommendations in the text.
    """
    if not text:
        return []
    
    issues = []
    
    # Pattern for numbered issues with descriptions and recommendations
    pattern = r'(?:Issue|Problem|Error)\s*(?:\d+|#\d+)?:?\s*([^\n]+)(?:\n|.)*?(?:Recommendation|Solution|Fix|Suggestion):?\s*([^\n]+)'
    
    matches = re.finditer(pattern, text, re.IGNORECASE)
    
    for match in matches:
        if len(match.groups()) >= 2:
            issue = match.group(1).strip()
            recommendation = match.group(2).strip()
            
            # Skip if either is too short
            if len(issue) < 5 or len(recommendation) < 5:
                continue
                
            issues.append({
                'issue': issue,
                'recommendation': recommendation,
                'severity': 'medium',  # Default severity
                'category': 'UI/UX'    # Default category
            })
    
    # If no structured issues found, try to extract any bullet points or numbered items
    if not issues:
        # Look for bullet points or numbered items
        bullet_pattern = r'(?:•|\*|\-|\d+\.)\s+([^\n]+)'
        bullet_matches = re.finditer(bullet_pattern, text)
        
        for match in bullet_matches:
            bullet_text = match.group(1).strip()
            if len(bullet_text) > 10:  # Minimum length to be considered meaningful
                issues.append({
                    'issue': bullet_text,
                    'recommendation': 'Review and address this item.',
                    'severity': 'low',
                    'category': 'General'
                })
    
    return issues

# ===== Routes =====

@app.route('/')
@app.route('/index')
def home_redirect():
    """Redirect to home page"""
    return redirect(url_for('home'))

@app.route('/home')
def home():
    """Serve the home page"""
    return render_template('home.html', active_tab='home')

@app.route('/manual-co-test')
def manual_co_test():
    """Serve the manual co-test page"""
    return render_template('manual-test-generator.html')

@app.route('/screen-analysis')
def screen_analysis():
    """Serve the screen analysis page"""
    return render_template('screen-analysis.html')

@app.route('/api/analyze-screen', methods=['POST'])
def analyze_screen():
    """Analyze a screenshot for UI/UX issues using AI"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        screenshot_data = data.get('screenshot')
        prompt = data.get('prompt', '')
        ocr_enabled = data.get('ocr', True)
        
        if not screenshot_data:
            return jsonify({'error': 'No screenshot provided'}), 400
        
        # Extract the base64 data
        if ',' in screenshot_data:
            screenshot_data = screenshot_data.split(',')[1]
        
        # Decode the image
        image_data = base64.b64decode(screenshot_data)
        
        # Save to a temporary file
        temp_image_path = os.path.join(UPLOAD_FOLDER, f"temp_screenshot_{int(time.time())}.png")
        with open(temp_image_path, 'wb') as f:
            f.write(image_data)
        
        # OCR processing if enabled
        ocr_text = ""
        if ocr_enabled:
            try:
                img = Image.open(temp_image_path)
                ocr_text = pytesseract.image_to_string(img)
                logger.info(f"OCR extracted {len(ocr_text)} characters")
                
                # Find potential misspellings
                misspellings = find_potential_misspellings(ocr_text)
            except Exception as e:
                logger.error(f"OCR processing error: {str(e)}")
                ocr_text = f"OCR processing error: {str(e)}"
                misspellings = []
        else:
            misspellings = []
        
        # Prepare prompt for Gemini
        analysis_prompt = f"""
        Analyze this UI screenshot and provide detailed feedback on UI/UX issues.
        
        {prompt if prompt else 'Focus on usability, accessibility, and design consistency.'}
        
        Provide your analysis in this JSON format:
        {{
            "issues": [
                {{
                    "issue": "Description of the issue",
                    "recommendation": "How to fix it",
                    "severity": "high|medium|low",
                    "category": "UI/UX|Accessibility|Performance|etc"
                }}
            ],
            "summary": "Overall assessment of the UI"
        }}
        
        If you see any text in the image that appears to be misspelled or unusual, please note it.
        """
        
        # If we have OCR text, add it to the prompt
        if ocr_text:
            analysis_prompt += f"\n\nOCR extracted text:\n{ocr_text}\n"
            
            if misspellings:
                analysis_prompt += f"\nPotential unusual words or misspellings detected: {', '.join(misspellings)}\n"
        
        # Call Gemini API
        try:
            model = genai.GenerativeModel(model_name)
            
            # Create image part from the file
            image_part = {"mime_type": "image/png", "data": image_data}
            
            # Generate content with both text and image
            response = model.generate_content([analysis_prompt, image_part])
            
            # Extract the response text
            ai_response = response.text
            
            # Try to parse as JSON
            try:
                result = json.loads(ai_response)
            except json.JSONDecodeError:
                # If JSON parsing fails, try to extract structured data manually
                logger.warning("Failed to parse AI response as JSON, extracting manually")
                extracted_issues = extract_issues_manually(ai_response)
                
                result = {
                    "issues": extracted_issues,
                    "summary": "Analysis completed, but structured output was not available. See raw output for details."
                }
            
            # Add OCR text to the response if available
            if ocr_text:
                result["ocr_text"] = ocr_text
                result["potential_misspellings"] = misspellings
            
            # Add raw response for debugging
            result["raw_response"] = ai_response
            
            # Clean up the temporary file
            try:
                os.remove(temp_image_path)
            except:
                pass
                
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"Error calling Gemini API: {str(e)}")
            return jsonify({
                'error': f"Error calling Gemini API: {str(e)}",
                'ocr_text': ocr_text if ocr_text else "No OCR text available"
            }), 500
            
    except Exception as e:
        logger.error(f"Error in analyze_screen: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/data')
def data():
    """Redirect to data generator page"""
    return redirect(url_for('data_generator'))

@app.route('/data-generator')
def data_generator():
    """Serve the data generator page"""
    return render_template('data-generator.html')

@app.route('/data-generation')
def data_generation():
    """Serve the data generation page"""
    return render_template('data-generation.html')

@app.route('/browseruse-automation', methods=['GET'])
def browseruse_automation_page():
    """Serve the browseruse automation page"""
    return render_template('browseruse-automation-stepwise.html')

@app.route('/api/browseruse/navigation', methods=['POST'])
def browseruse_navigation_executor():
    """Handle browser automation requests from the frontend"""
    logger.info("Browser automation endpoint called")
    
    # Catch all exceptions at the top level to ensure we always return a valid response
    try:
        if not playwright_available:
            logger.error("Playwright is not installed. Cannot run browser automation.")
            return jsonify({
                'success': False,
                'error': 'Playwright is not installed. Please install it with: pip install playwright && playwright install',
                'report': {
                    'message': 'Browser automation is not available. Playwright is not installed.'
                }
            }), 500
        
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
        
        results = []
        failure_screenshot = None
        success = True
        
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                
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
                
                browser.close()
        
        except Exception as e:
            logger.error(f"Error during browser automation: {str(e)}")
            success = False
            if capture_screenshot:
                try:
                    screenshot = page.screenshot()
                    failure_screenshot = f"data:image/png;base64,{base64.b64encode(screenshot).decode('utf-8')}"
                except Exception as screenshot_error:
                    logger.error(f"Failed to capture failure screenshot: {str(screenshot_error)}")
            
            # Add the error to results
            results.append({
                'step': len(results), 
                'action': 'error', 
                'success': False,
                'error': str(e)
            })
        
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

# ===== Jira OAuth Routes =====

def refresh_jira_token():
    """Refresh the Jira access token using the refresh token."""
    refresh_token = session.get('jira_refresh_token')
    if not refresh_token:
        logger.warning("No refresh token available for Jira OAuth. User may need to reconnect.")
        return False
    
    try:
        client_id = app.config['JIRA_CLIENT_ID']
        client_secret = app.config['JIRA_CLIENT_SECRET']
        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token
        }
        resp = requests.post(JIRA_TOKEN_URL, json=data)
        if resp.status_code == 200:
            tokens = resp.json()
            session['jira_access_token'] = tokens['access_token']
            session['jira_token_expires'] = time.time() + tokens.get('expires_in', 3600)
            return True
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
    return False

@app.route('/api/jira/oauth/login')
def jira_oauth_login():
    try:
        client_id = app.config['JIRA_CLIENT_ID']
        redirect_uri = app.config['JIRA_CALLBACK_URL']
        if not client_id or client_id == "your-client-id-here":
            logger.error("JIRA_CLIENT_ID not configured")
            return "Jira OAuth client ID not configured. Please set JIRA_CLIENT_ID in environment variables.", 500
            
        params = {
            "audience": "api.atlassian.com",
            "client_id": client_id,
            "scope": "read:jira-work write:jira-work",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "prompt": "consent"
        }
        
        logger.info(f"Starting Jira OAuth flow with params: {params}")
        url = JIRA_AUTH_URL + "?" + "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
        return redirect(url)
    except Exception as e:
        logger.error(f"Error in Jira OAuth login: {str(e)}")
        return f"Error starting Jira OAuth flow: {str(e)}", 500

@app.route('/api/jira/oauth/callback')
def jira_oauth_callback():
    code = request.args.get("code")
    if not code:
        return "No code provided", 400
    client_id = app.config['JIRA_CLIENT_ID']
    client_secret = app.config['JIRA_CLIENT_SECRET']
    redirect_uri = app.config['JIRA_CALLBACK_URL']
    data = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "redirect_uri": redirect_uri
    }
    resp = requests.post(JIRA_TOKEN_URL, json=data)
    if resp.status_code != 200:
        logger.error(f"Error getting token: {resp.status_code} {resp.text}")
        return f"Error getting token: {resp.status_code}", 500
    
    tokens = resp.json()
    session['jira_access_token'] = tokens['access_token']
    # Some OAuth flows don't include refresh tokens, so make it optional
    if 'refresh_token' in tokens:
        session['jira_refresh_token'] = tokens['refresh_token']
    session['jira_token_expires'] = time.time() + tokens.get('expires_in', 3600)
    
    # Get the Jira domain from the access token claims
    try:
        import jwt
        decoded = jwt.decode(tokens['access_token'], options={"verify_signature": False})
        session['jira_domain'] = decoded.get('iss', 'https://upgrad-jira.atlassian.net')
    except Exception as e:
        logger.error(f"Error decoding JWT: {str(e)}")
        session['jira_domain'] = 'https://upgrad-jira.atlassian.net'  # Default domain
    
    # Get the cloud ID
    headers = {
        'Authorization': f'Bearer {tokens["access_token"]}',
        'Accept': 'application/json'
    }
    cloud_id_resp = requests.get(
        'https://api.atlassian.com/oauth/token/accessible-resources',
        headers=headers
    )
    if cloud_id_resp.status_code == 200:
        cloud_id_data = cloud_id_resp.json()
        if cloud_id_data and isinstance(cloud_id_data, list) and len(cloud_id_data) > 0:
            session['jira_cloud_id'] = cloud_id_data[0]['id']
            logger.info(f"Stored Jira cloud ID: {cloud_id_data[0]['id']}")
            logger.info(f"Using Jira domain: {session['jira_domain']}")
    
    return redirect(url_for('manual_co_test'))

@app.route('/api/jira/status')
def jira_status():
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({'connected': False})
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    # Use a lightweight endpoint to check validity
    resp = requests.get('https://api.atlassian.com/me', headers=headers)
    if resp.status_code == 401:
        session.pop('jira_access_token', None)
        return jsonify({'connected': False})
    return jsonify({'connected': True})

@app.route('/api/jira/disconnect', methods=['POST'])
def disconnect_jira():
    for k in ['jira_access_token', 'jira_refresh_token', 'jira_token_expires', 'jira_cloud_id', 'jira_domain']:
        session.pop(k, None)
    return jsonify({'success': True})

@app.route('/api/jira/attachment')
def jira_attachment():
    attachment_id = request.args.get('id')
    collection = request.args.get('collection') or 'jira-issue'
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    if not (attachment_id and access_token and cloud_id):
        app.logger.error(f'Missing info: id={attachment_id}, token={bool(access_token)}, cloud_id={cloud_id}')
        return '', 404
    # Distinguish numeric (classic) vs UUID (media)
    if re.match(r'^\d+$', attachment_id):
        # Classic attachment
        url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/attachment/content/{attachment_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        img_resp = requests.get(url, headers=headers, stream=True)
        app.logger.info(f'Jira attachment GET {url} status={img_resp.status_code}')
        if img_resp.status_code != 200:
            app.logger.error(f'Attachment fetch failed: {img_resp.text}')
            return '', 404
        return Response(img_resp.iter_content(chunk_size=4096), content_type=img_resp.headers.get('Content-Type', 'image/png'))
    else:
        # Media API attachment
        media_url = f'https://api.media.atlassian.com/file/{attachment_id}/binary?collection={collection}'
        headers = {'Authorization': f'Bearer {access_token}'}
        img_resp = requests.get(media_url, headers=headers, stream=True)
        app.logger.info(f'Jira media service GET {media_url} status={img_resp.status_code}')
        if img_resp.status_code != 200:
            app.logger.error(f'Media service fetch failed: {img_resp.text}')
            return '', 404
        return Response(img_resp.iter_content(chunk_size=4096), content_type=img_resp.headers.get('Content-Type', 'image/png'))

@app.route('/api/jira/issues', methods=['GET'])
def fetch_jira_issues():
    """
    Fetch Jira issues using the stored access token.
    Supports filtering by project, status, and search query.
    """
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira. Please connect first.'}), 401
    if not cloud_id:
        return jsonify({'error': 'No Jira cloud ID found. Please reconnect to Jira.'}), 401
    
    # Get query parameters - frontend uses 'search' parameter
    issue_key = request.args.get('search', request.args.get('key', ''))
    
    # If we have a specific issue key, fetch that issue
    if issue_key:
        try:
            # Token might be expired, try to refresh it
            if session.get('jira_token_expires', 0) < time.time():
                if not refresh_jira_token():
                    return jsonify({'error': 'Jira token expired. Please reconnect.'}), 401
            
            access_token = session.get('jira_access_token')  # Get refreshed token
            
            url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{issue_key}"
            headers = {
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json"
            }
            
            response = requests.get(url, headers=headers)
            
            # Check if issue exists
            if response.status_code == 404:
                logger.warning(f"Jira issue not found: {issue_key}")
                return jsonify({'error': f'No Jira story found with this ID: {issue_key}'}), 404
                
            # Check content type to detect HTML error pages
            content_type = response.headers.get('Content-Type', '')
            if 'text/html' in content_type:
                return jsonify({
                    'error': 'Received HTML response instead of JSON. Token may be invalid or expired.',
                    'status_code': response.status_code,
                    'content_type': content_type
                }), 401
            
            if response.status_code != 200:
                return jsonify({
                    'error': 'Failed to fetch Jira issue',
                    'status_code': response.status_code
                }), response.status_code
            
            issue_data = response.json()
            
            # Extract relevant fields
            summary = issue_data.get('fields', {}).get('summary', '')
            description = issue_data.get('fields', {}).get('description', '')
            
            # Process description - it could be in various formats
            description_text = ''
            if isinstance(description, dict) and 'content' in description:
                # Process Atlassian Document Format
                description_text = extract_text_from_adf(description)
            elif isinstance(description, str):
                description_text = description
                
            # Create response object
            issue = {
                'key': issue_data.get('key', ''),
                'summary': summary,
                'description': description_text,
                'status': issue_data.get('fields', {}).get('status', {}).get('name', ''),
                'issueType': issue_data.get('fields', {}).get('issuetype', {}).get('name', '')
            }
            
            return jsonify({'issue': issue})
            
        except Exception as e:
            logger.error(f"Error fetching Jira issue: {str(e)}")
            return jsonify({'error': f"Error fetching Jira issue: {str(e)}"}), 500
    
    # Return empty result if no key provided
    return jsonify({'error': 'No issue key provided'}), 400

@app.route('/api/jira/create-subtasks', methods=['POST'])
def create_jira_subtasks():
    """Create subtasks in Jira for each test case"""
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira. Please connect first.'}), 401
    if not cloud_id:
        return jsonify({'error': 'No Jira cloud ID found. Please reconnect to Jira.'}), 401

    try:
        # Get request data
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400
        
        # The frontend sends parentIssueKey instead of parentKey
        parent_key = data.get('parentIssueKey')
        test_cases = data.get('testCases', [])
        
        if not parent_key:
            return jsonify({'error': 'No parent issue key provided'}), 400
        if not test_cases:
            return jsonify({'error': 'No test cases provided'}), 400
        
        # Extract project key from parent key
        project_key = parent_key.split('-')[0] if '-' in parent_key else None
        if not project_key:
            return jsonify({'error': 'Invalid parent key format'}), 400
        
        # Token might be expired, try to refresh it
        if session.get('jira_token_expires', 0) < time.time():
            if not refresh_jira_token():
                return jsonify({'error': 'Jira token expired. Please reconnect.'}), 401
        
        access_token = session.get('jira_access_token')  # Get refreshed token
        
        # Get available fields for subtasks to ensure we only include valid fields
        available_fields_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/createmeta/{project_key}/issuetypes/10003'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        fields_response = requests.get(available_fields_url, headers=headers)
        if fields_response.status_code != 200:
            logger.error(f"Error getting available fields: {fields_response.status_code} {fields_response.text}")
            return jsonify({'error': 'Failed to get available fields for subtasks'}), fields_response.status_code
        
        available_fields = fields_response.json().get('values', [])
        available_field_keys = [field.get('key') for field in available_fields]
        logger.info(f"Available fields for subtasks: {available_field_keys}")
        
        # Create subtasks
        created_count = 0
        failed_count = 0
        
        error_details = []
        
        for idx, test_case in enumerate(test_cases):
            step = test_case.get('step', '')
            expected = test_case.get('expected', '')
            estimate_minutes = test_case.get('estimate_minutes', 10)
            
            # Log the test case we're creating
            logger.info(f"Creating subtask {idx+1}/{len(test_cases)}: '{step[:50]}...'")
            
            # Create a subtask for this test case with only the fields that are available
            fields = {
                'project': {
                    'key': project_key
                },
                'parent': {
                    'key': parent_key
                },
                'issuetype': {
                    'id': '10003'  # Subtask type
                },
                'summary': step[:255],  # Limit summary to 255 chars
            }
            
            # Add description if available
            if expected:
                fields['description'] = {
                    'type': 'doc',
                    'version': 1,
                    'content': [
                        {
                            'type': 'paragraph',
                            'content': [
                                {
                                    'type': 'text',
                                    'text': f"Expected Result: {expected}"
                                }
                            ]
                        }
                    ]
                }
            
            # Create the subtask
            create_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue'
            create_payload = {'fields': fields}
            
            try:
                create_response = requests.post(create_url, headers=headers, json=create_payload)
                
                if create_response.status_code == 201:
                    created_count += 1
                else:
                    failed_count += 1
                    error_details.append({
                        'step': step[:50],
                        'status_code': create_response.status_code,
                        'error': create_response.text[:200]
                    })
                    logger.error(f"Failed to create subtask: {create_response.status_code} {create_response.text}")
            except Exception as e:
                failed_count += 1
                error_details.append({
                    'step': step[:50],
                    'error': str(e)
                })
                logger.error(f"Exception creating subtask: {str(e)}")
        
        return jsonify({
            'success': created_count > 0,
            'createdCount': created_count,
            'failedCount': failed_count,
            'errors': error_details[:5]  # Limit error details to avoid huge responses
        })
        
    except Exception as e:
        logger.error(f"Error creating Jira subtasks: {str(e)}")
        return jsonify({'error': f"Error creating Jira subtasks: {str(e)}"}), 500

# Helper function to extract text from Atlassian Document Format
def extract_text_from_adf(adf_doc):
    """Extract plain text from Atlassian Document Format"""
    if not adf_doc or not isinstance(adf_doc, dict):
        return ""
    
    text = []
    
    def process_content(content_list):
        if not content_list or not isinstance(content_list, list):
            return ""
        
        result = []
        for item in content_list:
            if isinstance(item, dict):
                if item.get('type') == 'text':
                    result.append(item.get('text', ''))
                elif 'content' in item and isinstance(item['content'], list):
                    result.append(process_content(item['content']))
        
        return ' '.join(result)
    
    content = adf_doc.get('content', [])
    for block in content:
        if isinstance(block, dict):
            if block.get('type') == 'paragraph':
                text.append(process_content(block.get('content', [])))
            elif block.get('type') == 'heading':
                text.append(process_content(block.get('content', [])))
            elif block.get('type') == 'bulletList' or block.get('type') == 'orderedList':
                for li in block.get('content', []):
                    for li_item in li.get('content', []):
                        text.append(process_content(li_item.get('content', [])))
    
    return '\n'.join(text)

# Helper function to rewrite blob URLs
def blob_rewrite(match):
    attrs = match.group(1)
    blob_url = match.group(2)
    m = re.search(r'id=([a-f0-9\-]+)', blob_url)
    id = m.group(1) if m else ''
    m2 = re.search(r'collection=([a-zA-Z0-9\-_]*)', blob_url)
    collection = m2.group(1) if m2 else 'jira-issue'
    return f'<img{attrs}src="/api/jira/attachment?id={id}&collection={collection}"'

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5050)
