import os
import base64
import json
import subprocess
import shlex
import re
# Configure browser visibility (false means browser will be visible)
os.environ["PLAYWRIGHT_HEADLESS"] = "false"  # browseruse needs visible browser
from dotenv import load_dotenv
load_dotenv()  # This will load variables from .env into os.environ
import logging
from datetime import datetime, timedelta
from collections import defaultdict

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
from flask import Flask, request, jsonify, render_template, session, redirect, url_for, send_file, make_response, Response, current_app
import requests
from requests.exceptions import RequestException
import json
from datetime import datetime
import re
from urllib.parse import urlparse, urlencode, parse_qs, urljoin
import threading
import time
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth
from flask_cors import CORS
import tempfile
import base64
from zip_utils import create_gradle_zip
import openai
from dotenv import load_dotenv
import pytesseract
from PIL import Image
import google.generativeai as genai
import asyncio
from browser_use import Agent
from langchain_openai import AzureChatOpenAI
import codecs
import socket

# Initialize logger
logger = logging.getLogger('curlrunner')
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    handler = logging.StreamHandler()
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# Initialize APScheduler
scheduler = BackgroundScheduler()
scheduler.start()

app = Flask(__name__, 
                static_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'), 
                static_url_path='/static',
                template_folder=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', 'devsecret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# Define Jira OAuth URLs
JIRA_AUTH_URL = 'https://auth.atlassian.com/authorize'
JIRA_TOKEN_URL = 'https://auth.atlassian.com/oauth/token'

# Configure Google Generative AI
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-pro-vision')
login_manager = LoginManager(app)
oauth = OAuth(app)

# Define public routes that don't require authentication
public_routes = [
    '/',  # Home page only
    '/home',  # Home redirect (dashboard is now public for welcome screen)
    '/index',  # Home redirect
    '/api/jira/oauth/login',
    '/api/jira/oauth/callback',
    '/api/jira/status',
    '/api/jira/logout',  # Allow logout without authentication
    '/static/',  # CSS, JS, and other static assets
    '/favicon.ico'
]

# Jira authentication decorator for additional security
def jira_auth_required(f):
    """Decorator to ensure Jira authentication for specific routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Check if user has valid Jira access token
        access_token = session.get('jira_access_token')
        if not access_token:
            logger.warning(f"Access denied to {request.endpoint}: No Jira access token")
            return redirect(url_for('index'))
        
        # Check if token is expired
        token_expires = session.get('jira_token_expires', 0)
        if time.time() > token_expires:
            # Try to refresh the token
            if not refresh_jira_token():
                logger.warning(f"Access denied to {request.endpoint}: Token expired and refresh failed")
                return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

@app.before_request
def check_jira_auth():
    """Check if user is authenticated with Jira before processing any request"""
    # Skip authentication check only for essential public routes
    is_public = False
    for route in public_routes:
        if request.path == route or (route.endswith('/') and request.path.startswith(route)) or \
           (not route.endswith('/') and request.path.startswith(route + '/')):
            is_public = True
            break
    
    if is_public:
        logger.debug(f"Allowing access to public route: {request.path}")
        return  # Allow access to public routes without authentication
    
    logger.info(f"Checking Jira authentication for non-public route: {request.path}")

    # Check for API requests that might need special handling
    is_api_request = request.path.startswith('/api/')
    
    # Log the path being checked
    logger.debug(f"Checking Jira auth for path: {request.path}")
    
    # Check if Jira access token exists
    access_token = session.get('jira_access_token')
    if not access_token:
        # No token found, redirect to home page
        logger.info(f"No Jira token found, redirecting to home page for path: {request.path}")
        
        # For API requests, return 401 Unauthorized instead of redirecting
        if is_api_request and not request.path.startswith('/api/jira/'):
            return jsonify({
                'error': 'Jira authentication required', 
                'login_url': url_for('index', _external=True)
            }), 401
            
        # For regular requests, redirect to home page
        return redirect(url_for('index'))
    
    # Check if token is expired
    token_expires = session.get('jira_token_expires', 0)
    if time.time() > token_expires:
        # Try to refresh the token
        if not refresh_jira_token():
            # Token refresh failed
            logger.info(f"Token refresh failed, redirecting to home page for path: {request.path}")
            
            # For API requests, return 401 Unauthorized
            if is_api_request and not request.path.startswith('/api/jira/'):
                return jsonify({
                    'error': 'Jira authentication expired', 
                    'login_url': url_for('index', _external=True)
                }), 401
            
            # For regular requests, redirect to home page
            return redirect(url_for('index'))
    
    # Token is valid, continue with the request
    logger.debug(f"Jira authentication valid for path: {request.path}")

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

@app.route('/api/jira/user-info')
def jira_user_info():
    """Get current Jira user information and welcome status"""
    logger.info("=== User Info API Called ===")
    logger.info(f"Session keys: {list(session.keys())}")
    logger.info(f"Has access token: {bool(session.get('jira_access_token'))}")
    
    if not session.get('jira_access_token'):
        logger.warning("No access token found in session")
        return jsonify({"authenticated": False}), 401
    
    # Check if we have user info, if not try to fetch it
    user_name = session.get('jira_user_name')
    user_email = session.get('jira_user_email')
    
    logger.info(f"Current session user info: name='{user_name}', email='{user_email}'")
    
    # If we don't have proper user info (default fallback values), try to fetch it again
    if not user_name or user_name == 'Jira User' or not user_email or user_email == 'Connected to Jira':
        logger.info("Missing or default user info, attempting to fetch from Atlassian API...")
        try:
            access_token = session.get('jira_access_token')
            headers = {
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/json'
            }
            
            user_info_resp = requests.get(
                'https://api.atlassian.com/me',
                headers=headers,
                timeout=10
            )
            
            logger.info(f"Atlassian API response status: {user_info_resp.status_code}")
            
            if user_info_resp.status_code == 200:
                user_data = user_info_resp.json()
                logger.info(f"Successfully fetched user data: {user_data}")
                
                # Extract user info
                user_name = (user_data.get('name') or 
                           user_data.get('displayName') or 
                           user_data.get('display_name') or 
                           user_data.get('nickname') or 
                           session.get('jira_user_name', 'User'))
                
                user_email = (user_data.get('email') or 
                            user_data.get('emailAddress') or 
                            user_data.get('email_address') or 
                            session.get('jira_user_email', ''))
                
                user_avatar = (user_data.get('picture') or 
                             user_data.get('avatar') or 
                             user_data.get('avatarUrl') or 
                             user_data.get('avatar_url') or 
                             user_data.get('avatarUrls', {}).get('48x48') or 
                             session.get('jira_user_avatar', ''))
                
                # Update session with fresh data
                session['jira_user_name'] = user_name
                session['jira_user_email'] = user_email
                session['jira_user_avatar'] = user_avatar
                
                logger.info(f"Updated session with user info: name='{user_name}', email='{user_email}'")
            else:
                logger.warning(f"Failed to fetch user info: {user_info_resp.status_code}, Response: {user_info_resp.text}")
                user_name = session.get('jira_user_name', 'User')
                user_email = session.get('jira_user_email', '')
        except Exception as e:
            logger.error(f"Error fetching user info: {str(e)}")
            user_name = session.get('jira_user_name', 'User')
            user_email = session.get('jira_user_email', '')
    
    response_data = {
        "authenticated": True,
        "user_name": user_name,
        "user_email": user_email,
        "user_avatar": session.get('jira_user_avatar', ''),
        "login_time": session.get('jira_login_time'),
        "show_welcome": session.get('show_welcome_message', False),
        "jira_domain": session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    }
    
    logger.info(f"Returning user info response: {response_data}")
    
    # Clear the welcome message flag after sending it once
    if session.get('show_welcome_message'):
        session['show_welcome_message'] = False
    
    return jsonify(response_data)

@app.route('/api/jira/debug-session')
def debug_session():
    """Debug endpoint to see what's in the session"""
    session_data = {
        "all_session_keys": list(session.keys()),
        "jira_access_token": "***PRESENT***" if session.get('jira_access_token') else None,
        "jira_user_name": session.get('jira_user_name'),
        "jira_user_email": session.get('jira_user_email'),
        "jira_user_avatar": session.get('jira_user_avatar'),
        "jira_login_time": session.get('jira_login_time'),
        "jira_domain": session.get('jira_domain'),
        "jira_cloud_id": session.get('jira_cloud_id'),
        "show_welcome_message": session.get('show_welcome_message'),
        "has_access_token": bool(session.get('jira_access_token')),
        "session_id": id(session)
    }
    return jsonify(session_data)

@app.route('/api/test-session', methods=['GET', 'POST'])
def test_session():
    """Test basic session functionality"""
    if request.method == 'POST':
        # Set test data
        session['test_name'] = 'Test User'
        session['test_email'] = 'test@example.com'
        session['test_time'] = time.time()
        return jsonify({
            "message": "Test data stored in session",
            "stored_data": {
                "test_name": session['test_name'],
                "test_email": session['test_email'],
                "test_time": session['test_time']
            }
        })
    else:
        # Get test data
        return jsonify({
            "message": "Reading test data from session",
            "session_keys": list(session.keys()),
            "test_data": {
                "test_name": session.get('test_name'),
                "test_email": session.get('test_email'),
                "test_time": session.get('test_time')
            }
        })

@app.route('/api/jira/refresh-user-info', methods=['POST'])
def refresh_user_info():
    """Manually refresh user info from Atlassian API"""
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({"error": "Not authenticated"}), 401
    
    headers = {
        'Authorization': f"Bearer {access_token}",
        'Accept': 'application/json'
    }
    
    try:
        logger.info("Manually refreshing user info from Atlassian API...")
        user_info_resp = requests.get(
            'https://api.atlassian.com/me',
            headers=headers,
            timeout=10
        )
        logger.info(f"Manual user info response status: {user_info_resp.status_code}")
        
        if user_info_resp.status_code == 200:
            user_data = user_info_resp.json()
            logger.info(f"Manual fetch - Raw user data: {user_data}")
            
            # Try different field names that Atlassian might use
            user_name = (user_data.get('name') or 
                        user_data.get('displayName') or 
                        user_data.get('display_name') or 
                        user_data.get('nickname') or 
                        user_data.get('account_id') or
                        'Jira User')
            
            user_email = (user_data.get('email') or 
                         user_data.get('emailAddress') or 
                         user_data.get('email_address') or 
                         'Connected to Jira')
            
            user_avatar = (user_data.get('picture') or 
                          user_data.get('avatar') or 
                          user_data.get('avatarUrl') or 
                          user_data.get('avatar_url') or 
                          user_data.get('avatarUrls', {}).get('48x48') or
                          '')
            
            session['jira_user_name'] = user_name
            session['jira_user_email'] = user_email
            session['jira_user_avatar'] = user_avatar
            session['jira_login_time'] = time.time()
            
            return jsonify({
                "success": True,
                "user_name": user_name,
                "user_email": user_email,
                "user_avatar": user_avatar,
                "raw_data": user_data
            })
        else:
            logger.error(f"Manual fetch failed. Status: {user_info_resp.status_code}, Response: {user_info_resp.text}")
            return jsonify({
                "success": False,
                "error": f"API returned status {user_info_resp.status_code}",
                "response": user_info_resp.text
            }), 400
    except Exception as e:
        logger.error(f"Exception during manual user info fetch: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route('/api/jira/logout', methods=['POST'])
def jira_logout():
    """Logout from Jira by removing tokens from session"""
    try:
        # Remove all Jira-related tokens and user info from session
        session.pop('jira_access_token', None)
        session.pop('jira_refresh_token', None)
        session.pop('jira_token_expires', None)
        session.pop('jira_cloud_id', None)
        session.pop('jira_domain', None)
        session.pop('jira_user_name', None)
        session.pop('jira_user_email', None)
        session.pop('jira_user_avatar', None)
        session.pop('jira_login_time', None)
        session.pop('show_welcome_message', None)
        
        logger.info("User logged out from Jira")
        return jsonify({'success': True, 'message': 'Successfully logged out from Jira'})
    except Exception as e:
        logger.error(f"Error during Jira logout: {str(e)}")
        return jsonify({'success': False, 'message': f'Error during logout: {str(e)}'}), 500

# OAuth config (replace with your credentials)
app.config['GOOGLE_CLIENT_ID'] = os.environ.get('GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_ID')
app.config['GOOGLE_CLIENT_SECRET'] = os.environ.get('GOOGLE_CLIENT_SECRET', 'GOOGLE_CLIENT_SECRET')
app.config['GITHUB_CLIENT_ID'] = os.environ.get('GITHUB_CLIENT_ID', 'GITHUB_CLIENT_ID')
app.config['GITHUB_CLIENT_SECRET'] = os.environ.get('GITHUB_CLIENT_SECRET', 'GITHUB_CLIENT_SECRET')

# Jira OAuth config (local vs prod)
FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
if FLASK_ENV == 'development':
    app.config['JIRA_CLIENT_ID'] = os.environ.get('JIRA_CLIENT_ID_LOCAL', 'JIRA_CLIENT_ID_LOCAL')
    app.config['JIRA_CLIENT_SECRET'] = os.environ.get('JIRA_CLIENT_SECRET_LOCAL', 'JIRA_CLIENT_SECRET_LOCAL')
    app.config['JIRA_CALLBACK_URL'] = os.environ.get('JIRA_CALLBACK_URL_LOCAL', 'JIRA_CALLBACK_URL_LOCAL')
else:
    app.config['JIRA_CLIENT_ID'] = os.environ.get('JIRA_CLIENT_ID', 'JIRA_CLIENT_ID')
    app.config['JIRA_CLIENT_SECRET'] = os.environ.get('JIRA_CLIENT_SECRET', 'JIRA_CLIENT_SECRET')
    app.config['JIRA_CALLBACK_URL'] = os.environ.get('JIRA_CALLBACK_URL', 'JIRA_CALLBACK_URL')

# LLM Rate Limiting Configuration
DAILY_LLM_LIMIT = int(os.environ.get('DAILY_LLM_LIMIT', '20'))  # 20 calls per user per day
user_llm_usage = defaultdict(lambda: {'count': 0, 'date': None})

def get_user_identifier():
    """Get a unique identifier for the current user"""
    # Try to get Jira user email first (most reliable for authenticated users)
    user_email = session.get('jira_user_email')
    if user_email and user_email != 'Connected to Jira':
        return user_email
    
    # Check if user has Jira access token (they're authenticated but email might not be set yet)
    access_token = session.get('jira_access_token')
    if access_token:
        # Try to get user info from Jira to get the email
        try:
            # If they have an access token, they should have a jira_user_name too
            user_name = session.get('jira_user_name')
            if user_name:
                # Create a stable identifier based on their Jira user name
                # This should be consistent across login sessions
                return f"jira_user_{user_name.lower().replace(' ', '_')}"
        except:
            pass
    
    # For truly anonymous users, generate or get session ID
    if 'persistent_user_id' not in session:
        import uuid
        session['persistent_user_id'] = f"user_{uuid.uuid4().hex[:12]}"
    
    return session.get('persistent_user_id')

def migrate_user_usage_if_needed():
    """Migrate usage from old session ID to new stable identifier if user just authenticated"""
    current_id = get_user_identifier()
    
    # If current ID is email or jira-based, check for old session data to migrate
    if '@' in current_id or current_id.startswith('jira_user_'):
        # Look for any session-based usage data for this session that we can migrate
        old_session_id = session.get('persistent_user_id')
        if old_session_id and old_session_id != current_id and old_session_id in user_llm_usage:
            # Migrate the usage data from the old session ID to the new stable ID
            old_data = user_llm_usage[old_session_id]
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Only migrate if it's from today
            if old_data.get('date') == today:
                current_data = user_llm_usage.get(current_id, {'count': 0, 'date': today})
                # Take the maximum count to avoid losing usage
                current_data['count'] = max(current_data.get('count', 0), old_data['count'])
                current_data['date'] = today
                user_llm_usage[current_id] = current_data
                
                # Remove the old session data
                del user_llm_usage[old_session_id]
                logger.info(f"Migrated LLM usage from {old_session_id} to {current_id}: {current_data['count']} requests")

def get_user_display_info():
    """Get user information for display purposes"""
    user_id = get_user_identifier()
    user_email = session.get('jira_user_email')
    
    if user_email and user_email != 'Connected to Jira':
        return {
            'user_id': user_id,
            'display_name': user_email,
            'user_type': 'authenticated',
            'jira_connected': True
        }
    else:
        return {
            'user_id': user_id,
            'display_name': f"Anonymous User ({user_id})",
            'user_type': 'anonymous',
            'jira_connected': False
        }

def check_and_increment_llm_usage(user_id=None):
    """Check if user has exceeded daily LLM limit and increment usage"""
    if user_id is None:
        user_id = get_user_identifier()
    
    # Try to migrate old usage data if user just authenticated
    migrate_user_usage_if_needed()
    
    today = datetime.now().strftime('%Y-%m-%d')
    user_data = user_llm_usage[user_id]
    
    # Reset count if it's a new day
    if user_data['date'] != today:
        user_data['count'] = 0
        user_data['date'] = today
    
    # Check if limit exceeded
    if user_data['count'] >= DAILY_LLM_LIMIT:
        return False, user_data['count']
    
    # Increment usage
    user_data['count'] += 1
    logger.info(f"LLM usage for user {user_id}: {user_data['count']}/{DAILY_LLM_LIMIT}")
    return True, user_data['count']

def get_user_llm_usage(user_id=None):
    """Get current LLM usage for user"""
    if user_id is None:
        user_id = get_user_identifier()
    
    # Try to migrate old usage data if user just authenticated
    migrate_user_usage_if_needed()
    
    today = datetime.now().strftime('%Y-%m-%d')
    user_data = user_llm_usage[user_id]
    
    # Reset count if it's a new day
    if user_data['date'] != today:
        user_data['count'] = 0
        user_data['date'] = today
    
    return user_data['count'], DAILY_LLM_LIMIT

def llm_rate_limit(f):
    """Decorator to apply LLM rate limiting to endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        allowed, current_count = check_and_increment_llm_usage()
        if not allowed:
            logger.warning(f"LLM rate limit exceeded for user {get_user_identifier()}: {current_count}/{DAILY_LLM_LIMIT}")
            return jsonify({
                'error': f'Daily LLM usage limit exceeded ({DAILY_LLM_LIMIT} calls per day). Current usage: {current_count}',
                'rate_limit': {
                    'limit': DAILY_LLM_LIMIT,
                    'used': current_count,
                    'remaining': 0,
                    'reset_time': 'Next day at 00:00 UTC'
                }
            }), 429  # Too Many Requests
        return f(*args, **kwargs)
    return decorated_function

google = oauth.register(
    name='google',
    client_id=app.config['GOOGLE_CLIENT_ID'],
    client_secret=app.config['GOOGLE_CLIENT_SECRET'],
    access_token_url='https://accounts.google.com/o/oauth2/token',
    access_token_params=None,
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={'scope': 'openid email profile'},
)

github = oauth.register(
    name='github',
    client_id=app.config['GITHUB_CLIENT_ID'],
    client_secret=app.config['GITHUB_CLIENT_SECRET'],
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    api_base_url='https://api.github.com/',
    userinfo_endpoint='https://api.github.com/user',
    client_kwargs={'scope': 'user:email'},
)

JIRA_AUTH_URL = "https://auth.atlassian.com/authorize"
JIRA_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=True)
    password_hash = db.Column(db.String(256))
    oauth_provider = db.Column(db.String(50))
    oauth_id = db.Column(db.String(150))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    collections = db.relationship('Collection', backref='user', lazy=True)
    environments = db.relationship('Environment', backref='user', lazy=True)

class Collection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150))
    data = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Environment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    name = db.Column(db.String(150))
    data = db.Column(db.Text)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ScheduledJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    collection_id = db.Column(db.Integer, nullable=False)
    environment_id = db.Column(db.Integer, nullable=False)
    frequency = db.Column(db.String(50), nullable=False)
    cron = db.Column(db.String(100), nullable=True)
    last_run = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Helper functions

def sanitize_headers(headers):
    # Remove any headers that shouldn't be sent
    # (can be expanded as needed)
    forbidden = {'host', 'content-length', 'accept-encoding', 'connection'}
    return {k: v for k, v in headers.items() if k.lower() not in forbidden}

def validate_url(url):
    # Basic URL validation
    try:
        result = urlparse(url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except Exception:
        return False

def parse_form_data(body):
    # Try to parse JSON or URL-encoded form data
    try:
        if isinstance(body, dict):
            return body
        if isinstance(body, str):
            try:
                return json.loads(body)
            except Exception:
                # fallback: parse query string style
                return dict(parse_qs(body))
        return {}
    except Exception:
        return {}

def extract_requests(items):
    result = []
    for item in items:
        if 'request' in item:
            result.append(item)
        elif 'item' in item:
            result.extend(extract_requests(item['item']))
    return result

# Dummy for process_request_with_environment (to avoid runtime errors)
def process_request_with_environment(request, environment):
    # Replace variables in request with environment values (implement as needed)
    return request

# E2E Test Model
class E2ETest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    test_name = db.Column(db.String(200), nullable=False)
    steps = db.Column(db.Text, nullable=False)  # Store as JSON string
    created_by = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Test Context Model
class TestContext(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(500))
    context_data = db.Column(db.Text)  # JSON string
    # Structured fields for better querying
    feature_summary = db.Column(db.Text)
    requirements = db.Column(db.Text)  # JSON string of array
    user_flows = db.Column(db.Text)  # JSON string of array
    validation_points = db.Column(db.Text)  # JSON string of array
    dependencies = db.Column(db.Text)  # JSON string of array
    edge_cases = db.Column(db.Text)  # JSON string of array
    data_requirements = db.Column(db.Text)  # JSON string of array
    # New fields from enhanced prompt
    performance_criteria = db.Column(db.Text)  # JSON string of array
    security_considerations = db.Column(db.Text)  # JSON string of array
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<TestContext {self.name}>'

# --- TEMP: Create all tables if not present ---
with app.app_context():
    db.create_all()

def save_data(data):
    # Implement persistent storage as needed
    pass

@app.route('/')
def index():
    return render_template('home.html', active_tab='home')

@app.route('/home')
@app.route('/index')
def home_redirect():
    return redirect(url_for('index'))

@app.route('/download-logo')
def download_logo():
    return render_template('download-logo.html')

@app.route('/learning-resources')
def learning_resources():
    return render_template('learning-resources.html', active_tab='learning')

@app.route('/context-builder')
@jira_auth_required
def context_builder():
    return render_template('context-builder.html', active_tab='context-builder')

@app.route('/api/process-context', methods=['POST'])
@jira_auth_required
@llm_rate_limit
def process_context():
    try:
        # Get uploaded file or text
        content = ''
        if 'document' in request.files:
            file = request.files['document']
            if file and allowed_file(file.filename):
                # Extract text from document
                if file.filename.endswith('.pdf'):
                    # For PDF files
                    import io
                    from PyPDF2 import PdfReader
                    pdf_reader = PdfReader(io.BytesIO(file.read()))
                    for page in pdf_reader.pages:
                        content += page.extract_text() + '\n'
                elif file.filename.endswith(('.doc', '.docx')):
                    # For Word documents
                    import io
                    import docx
                    doc = docx.Document(io.BytesIO(file.read()))
                    for para in doc.paragraphs:
                        content += para.text + '\n'
                else:
                    # For text files
                    content = file.read().decode('utf-8')
        else:
            content = request.form.get('raw_text', '')
            
        if not content:
            return jsonify({'error': 'No content provided'}), 400
            
        # Process with AI
        context_data = generate_structured_context(content)
        
        # Save to database if requested
        if request.form.get('save', 'false').lower() == 'true':
            name = request.form.get('name', 'Untitled Context')
            description = request.form.get('description', '')
            context_id = save_context_to_db(context_data, name, description)
            return jsonify({
                'success': True,
                'context_id': context_id,
                'context': context_data
            })
        else:
            return jsonify({
                'success': True,
                'context': context_data
            })
    except Exception as e:
        app.logger.error(f"Error processing context: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/contexts', methods=['GET'])
@jira_auth_required
def list_contexts():
    try:
        user_id = get_user_identifier()
        contexts = TestContext.query.filter_by(user_id=user_id).all()
        result = []
        for context in contexts:
            result.append({
                'id': context.id,
                'name': context.name,
                'description': context.description,
                'created_at': context.created_at.isoformat(),
                'updated_at': context.updated_at.isoformat()
            })
        return jsonify({'contexts': result})
    except Exception as e:
        app.logger.error(f"Error listing contexts: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/contexts/<int:context_id>', methods=['GET'])
@jira_auth_required
def get_context(context_id):
    try:
        user_id = get_user_identifier()
        context = TestContext.query.filter_by(id=context_id, user_id=user_id).first()
        if not context:
            return jsonify({'error': 'Context not found'}), 404
        
        # Parse all JSON fields
        context_data = json.loads(context.context_data) if context.context_data else {}
        
        # Build response with all structured fields
        response = {
            'id': context.id,
            'name': context.name,
            'description': context.description,
            'feature_summary': context.feature_summary,
            'requirements': json.loads(context.requirements) if context.requirements else [],
            'user_flows': json.loads(context.user_flows) if context.user_flows else [],
            'validation_points': json.loads(context.validation_points) if context.validation_points else [],
            'dependencies': json.loads(context.dependencies) if context.dependencies else [],
            'edge_cases': json.loads(context.edge_cases) if context.edge_cases else [],
            'data_requirements': json.loads(context.data_requirements) if context.data_requirements else [],
            # Include new fields
            'performance_criteria': json.loads(context.performance_criteria) if context.performance_criteria else [],
            'security_considerations': json.loads(context.security_considerations) if context.security_considerations else [],
            'created_at': context.created_at.isoformat(),
            'updated_at': context.updated_at.isoformat()
        }
        
        return jsonify(response)
    except Exception as e:
        app.logger.error(f"Error getting context: {str(e)}")
        return jsonify({'error': f'Error retrieving context: {str(e)}'}), 500

@app.route('/api/contexts/<int:context_id>', methods=['DELETE'])
@jira_auth_required
def delete_context(context_id):
    try:
        user_id = get_user_identifier()
        context = TestContext.query.filter_by(id=context_id, user_id=user_id).first()
        if not context:
            return jsonify({'error': 'Context not found'}), 404
        
        db.session.delete(context)
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f"Error deleting context: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api-co-test')
@jira_auth_required
def api_co_test():
    return render_template('api.html', active_tab='api')

# Keep old route for backward compatibility
@app.route('/code')
@jira_auth_required
def code():
    return redirect('/api-co-test', code=301)

def detect_graphql_request(url, headers, body):
    """Detect if a cURL request is a GraphQL request"""
    # Check URL patterns
    url_indicators = [
        '/graphql' in url.lower(),
        url.lower().endswith('/graphql'),
        '/gql' in url.lower(),
        url.lower().endswith('/gql')
    ]
    
    # Check headers for GraphQL content type or specific headers
    header_indicators = []
    if headers:
        content_type = headers.get('Content-Type', '').lower()
        header_indicators = [
            'application/json' in content_type and any(url_indicators),
            any('graphql' in str(v).lower() for v in headers.values())
        ]
    
    # Check body for GraphQL query structure
    body_indicators = []
    if body:
        try:
            # Try to parse as JSON and check for GraphQL structure
            import json
            body_json = json.loads(body)
            body_indicators = [
                'query' in body_json,
                'mutation' in body_json,
                any(key in body_json for key in ['query', 'mutation', 'subscription'])
            ]
        except (json.JSONDecodeError, TypeError):
            # Check raw body for GraphQL keywords
            body_lower = body.lower()
            body_indicators = [
                'query' in body_lower and ('{' in body_lower or 'mutation' in body_lower),
                'mutation' in body_lower and '{' in body_lower,
                'subscription' in body_lower and '{' in body_lower
            ]
    
    # Return True if any strong indicators are present
    return any(url_indicators) or any(header_indicators) or any(body_indicators)

def process_graphql_request(body, headers):
    """Process and validate GraphQL request body and headers"""
    import json
    
    # Ensure Content-Type is set for GraphQL
    if 'Content-Type' not in headers:
        headers['Content-Type'] = 'application/json'
    
    if body:
        try:
            # Try to parse and validate the JSON structure
            body_json = json.loads(body)
            
            # Ensure the body has a proper GraphQL structure
            if 'query' not in body_json and 'mutation' not in body_json and 'subscription' not in body_json:
                # If raw GraphQL query is provided, wrap it in proper JSON structure
                if isinstance(body_json, str) or (isinstance(body_json, dict) and len(body_json) == 0):
                    body_json = {'query': body.strip('"\'') if isinstance(body, str) else str(body_json)}
            
            # Ensure variables field exists if not present
            if 'variables' not in body_json:
                body_json['variables'] = {}
                
            # Convert back to JSON string
            body = json.dumps(body_json)
            
        except json.JSONDecodeError:
            # If body is not valid JSON, try to construct proper GraphQL request
            body_clean = body.strip().strip('"\'')
            if body_clean.startswith(('query', 'mutation', 'subscription')):
                body = json.dumps({
                    'query': body_clean,
                    'variables': {}
                })
    
    return body, headers

def format_graphql_response(json_data):
    """Format GraphQL response with proper error highlighting"""
    import json
    
    # Check if this is a GraphQL response with errors
    if isinstance(json_data, dict) and 'errors' in json_data:
        # Highlight errors in the response
        formatted_response = {
            "🚨 GraphQL Errors": json_data.get('errors', []),
            "data": json_data.get('data'),
            "extensions": json_data.get('extensions')
        }
        # Remove None values
        formatted_response = {k: v for k, v in formatted_response.items() if v is not None}
        return json.dumps(formatted_response, indent=2)
    else:
        # Standard JSON formatting for successful responses
        return json.dumps(json_data, indent=2)

@app.route('/execute_curl', methods=['POST'])
def execute_curl():
    """Execute a curl command and return the results"""
    try:
        data = request.get_json()
        if not data or 'command' not in data:
            return jsonify({'error': 'No curl command provided'}), 400
            
        curl_command = data['command']
        
        # Basic security check - only allow curl commands
        if not curl_command.strip().startswith('curl '):
            return jsonify({'error': 'Invalid command. Only curl commands are allowed.'}), 400
        
        # Parse the curl command to extract method, URL, headers, and body
        try:
            # Use regex-based parsing for better multi-line support
            command = curl_command
            
            # Initialize variables
            method = 'GET'  # Default method
            url = None
            headers = {}
            body = None
            
            # Extract URL first - look for quoted URLs
            url_patterns = [
                r"'(https?://[^']*)'",  # Single quoted URLs
                r'"(https?://[^"]*)"',  # Double quoted URLs
                r'(https?://\S+)'       # Unquoted URLs
            ]
            
            for pattern in url_patterns:
                url_match = re.search(pattern, command)
                if url_match:
                    url = url_match.group(1)
                    break
            
            # Extract method
            method_match = re.search(r'(?:-X|--request)\s+([A-Z]+)', command)
            if method_match:
                method = method_match.group(1)
            
            # Extract headers - handle both single and double quotes
            header_patterns = [
                r"(?:-H|--header)\s+'([^']+)'",   # Single quoted headers
                r'(?:-H|--header)\s+"([^"]+)"'    # Double quoted headers
            ]
            
            for pattern in header_patterns:
                for match in re.finditer(pattern, command):
                    header_text = match.group(1)
                    if ':' in header_text:
                        key, value = header_text.split(':', 1)
                        headers[key.strip()] = value.strip()
            
            # Extract body - handle multi-line JSON properly
            body_patterns = [
                r"--data-raw\s+'([^']*(?:\\'[^']*)*)'",  # Single quotes, handling escaped quotes
                r'--data-raw\s+"([^"]*(?:\\"[^"]*)*)"',  # Double quotes, handling escaped quotes
                r"--data-raw\s+['\"](.*?)['\"]",         # Generic quoted content
                r"--data\s+'([^']*(?:\\'[^']*)*)'",
                r'--data\s+"([^"]*(?:\\"[^"]*)*)"',
                r"--data\s+['\"](.*?)['\"]",
                r"-d\s+'([^']*(?:\\'[^']*)*)'",
                r'-d\s+"([^"]*(?:\\"[^"]*)*)"',
                r"-d\s+['\"](.*?)['\"]"
            ]
            
            for pattern in body_patterns:
                body_match = re.search(pattern, command, re.DOTALL)
                if body_match:
                    body = body_match.group(1)
                    # Unescape quotes
                    body = body.replace("\\'", "'").replace('\\"', '"')
                    break
            
            # If we have a body but no explicit method, assume POST
            if body and method == 'GET':
                method = 'POST'
            
            # Ensure Content-Type is set for JSON data
            if body and 'Content-Type' not in headers and body.strip().startswith('{'):
                headers['Content-Type'] = 'application/json'
            
            if not url:
                return jsonify({'error': 'No URL found in curl command'}), 400
                
            # Detect if this is a GraphQL request
            is_graphql_request = detect_graphql_request(url, headers, body)
            
            # Handle GraphQL-specific processing
            if is_graphql_request:
                body, headers = process_graphql_request(body, headers)
            
            # Debug logging
            logger.info(f"Parsed cURL - Method: {method}, URL: {url}, Body length: {len(body) if body else 0}, GraphQL: {is_graphql_request}")
            
            # Check for --location flag (follow redirects)
            follow_redirects = '--location' in command or '-L' in command
            
            # Measure execution time
            start_time = time.time()
            
            # Make the request
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                allow_redirects=follow_redirects,
                timeout=30
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            # Parse and format response body
            response_body = response.text
            try:
                # Try to parse as JSON and format it
                if response.headers.get('content-type', '').startswith('application/json'):
                    json_data = response.json()
                    
                    # Special handling for GraphQL responses
                    if is_graphql_request:
                        response_body = format_graphql_response(json_data)
                    else:
                        response_body = json.dumps(json_data, indent=2)
            except:
                # If JSON parsing fails, keep as text
                pass
            
            # Return the response in consistent format
            return jsonify({
                'success': True,
                'status': response.status_code,
                'statusText': response.reason,
                'headers': dict(response.headers),
                'body': response_body,
                'time': round(execution_time, 2),
                'size': len(response.content),
                'cookies': [{'name': k, 'value': v} for k, v in response.cookies.items()]
            })
            
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'error': 'Request timeout',
                'time': round((time.time() - start_time) * 1000, 2) if 'start_time' in locals() else 0
            }), 408
        except requests.exceptions.ConnectionError as e:
            return jsonify({
                'success': False,
                'error': f'Connection error: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2) if 'start_time' in locals() else 0
            }), 503
        except Exception as e:
            logger.error(f"Error parsing curl command: {str(e)}")
            return jsonify({
                'success': False,
                'error': f'Error parsing curl command: {str(e)}'
            }), 400
            
    except Exception as e:
        logger.error(f"Error executing curl command: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Error: {str(e)}'
        }), 500

@app.route('/execute_request', methods=['POST'])
def execute_request():
    """Execute a request from a Postman collection"""
    try:
        data = request.get_json()
        if not data or 'request' not in data:
            return jsonify({'error': 'No request data provided'}), 400
            
        postman_request = data['request']
        
        # Extract method
        method = postman_request.get('method', 'GET')
        
        # Extract URL
        url = ''
        if isinstance(postman_request['url'], str):
            url = postman_request['url']
        elif isinstance(postman_request['url'], dict) and 'raw' in postman_request['url']:
            url = postman_request['url']['raw']
        else:
            return jsonify({'error': 'Invalid URL format in request'}), 400
            
        # Extract headers
        headers = {}
        if 'header' in postman_request and postman_request['header']:
            for header in postman_request['header']:
                if 'key' in header and 'value' in header:
                    headers[header['key']] = header['value']
        
        # Extract body
        body = None
        if 'body' in postman_request and postman_request['body']:
            body_mode = postman_request['body'].get('mode')
            
            if body_mode == 'raw' and 'raw' in postman_request['body']:
                body = postman_request['body']['raw']
            elif body_mode == 'urlencoded' and 'urlencoded' in postman_request['body']:
                body = {}
                for param in postman_request['body']['urlencoded']:
                    if 'key' in param and 'value' in param:
                        body[param['key']] = param['value']
            elif body_mode == 'formdata' and 'formdata' in postman_request['body']:
                body = {}
                for param in postman_request['body']['formdata']:
                    if 'key' in param and 'value' in param:
                        body[param['key']] = param['value']
        
        # Measure execution time and make the request
        start_time = time.time()
        response = requests.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=30
        )
        execution_time = (time.time() - start_time) * 1000
        
        # Parse response body
        response_body = response.text
        try:
            if response.headers.get('content-type', '').startswith('application/json'):
                response_body = response.json()
        except:
            pass
        
        # Return comprehensive response
        return jsonify({
            'status_code': response.status_code,
            'status_text': response.reason,
            'headers': dict(response.headers),
            'body': response_body,
            'time': round(execution_time, 2),
            'size': len(response.content),
            'cookies': [{'name': k, 'value': v} for k, v in response.cookies.items()]
        })
        
    except requests.exceptions.Timeout:
        return jsonify({'error': 'Request timeout'}), 408
    except requests.exceptions.ConnectionError:
        return jsonify({'error': 'Connection error - Could not connect to server'}), 503
    except requests.exceptions.SSLError:
        return jsonify({'error': 'SSL verification failed'}), 495
    except Exception as e:
        logger.error(f"Error executing request: {str(e)}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/execute_graphql', methods=['POST'])
def execute_graphql():
    """Execute a GraphQL query"""
    try:
        data = request.get_json()
        if not data or 'endpoint' not in data or 'payload' not in data:
            return jsonify({'error': 'Missing required fields: endpoint and payload'}), 400
            
        endpoint = data['endpoint']
        headers = data.get('headers', {})
        payload = data['payload']
        
        # Ensure content type is set for GraphQL
        if 'Content-Type' not in headers:
            headers['Content-Type'] = 'application/json'
        
        # Make the GraphQL request
        response = requests.post(
            url=endpoint,
            headers=headers,
            json=payload
        )
        
        # Try to parse response as JSON
        try:
            body = response.json()
        except:
            body = response.text
        
        # Return the response
        return jsonify({
            'status_code': response.status_code,
            'headers': dict(response.headers),
            'body': body
        })
        
    except Exception as e:
        logger.error(f"Error executing GraphQL query: {str(e)}")
        return jsonify({'error': f'Error: {str(e)}'}), 500

@app.route('/ui-recorder')
def ui_recorder():
    return render_template('ui-recorder.html')

@app.route('/recorder-target')
def recorder_target():
    """
    Single-tab recording interface that shows steps in real-time.
    """
    target_url = request.args.get('url', 'https://example.com')
    response = make_response(render_template('recorder-target.html', target_url=target_url))
    # Add headers to allow iframe embedding for the recorder-target page itself
    response.headers['X-Frame-Options'] = 'ALLOWALL'
    response.headers['Access-Control-Allow-Origin'] = '*'
    return response

@app.route('/api/signup', methods=['POST'])
def signup():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    if not email or not password:
        return jsonify({'error': 'Email and password required'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Email already registered'}), 400
    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    login_user(user)
    return jsonify({'message': 'Signup successful', 'user': {'email': user.email}})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    email = data.get('email')
    password = data.get('password')
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Invalid credentials'}), 401
    login_user(user)
    return jsonify({'message': 'Login successful', 'user': {'email': user.email}})

@app.route('/api/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return jsonify({'message': 'Logged out'})

@app.route('/api/user')
def get_user():
    if current_user.is_authenticated:
        return jsonify({'user': {'email': current_user.email}})
    return jsonify({'user': None})

# Google OAuth
@app.route('/api/oauth/google')
def oauth_google():
    redirect_uri = url_for('oauth_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/api/oauth/google/callback')
def oauth_google_callback():
    token = google.authorize_access_token()
    resp = google.get('userinfo')
    user_info = resp.json()
    user = User.query.filter_by(oauth_provider='google', oauth_id=user_info['sub']).first()
    if not user:
        user = User(email=user_info.get('email'), oauth_provider='google', oauth_id=user_info['sub'])
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect('/')

# GitHub OAuth
@app.route('/api/oauth/github')
def oauth_github():
    redirect_uri = url_for('oauth_github_callback', _external=True)
    return github.authorize_redirect(redirect_uri)

@app.route('/api/oauth/github/callback')
def oauth_github_callback():
    token = github.authorize_access_token()
    resp = github.get('user')
    user_info = resp.json()
    user = User.query.filter_by(oauth_provider='github', oauth_id=str(user_info['id'])).first()
    if not user:
        user = User(email=user_info.get('email'), oauth_provider='github', oauth_id=str(user_info['id']))
        db.session.add(user)
        db.session.commit()
    login_user(user)
    return redirect('/')

# User-specific collections
@app.route('/api/collections', methods=['GET', 'POST'])
@login_required
def user_collections():
    if request.method == 'GET':
        collections = Collection.query.filter_by(user_id=current_user.id).all()
        return jsonify([{'id': c.id, 'name': c.name, 'data': c.data} for c in collections])
    else:
        data = request.json
        name = data.get('name')
        collection_data = data.get('data')
        c = Collection(user_id=current_user.id, name=name, data=collection_data)
        db.session.add(c)
        db.session.commit()
        return jsonify({'id': c.id, 'name': c.name, 'data': c.data})

# User-specific environments
@app.route('/api/environments', methods=['GET', 'POST'])
@login_required
def user_environments():
    if request.method == 'GET':
        envs = Environment.query.filter_by(user_id=current_user.id).all()
        return jsonify([{'id': e.id, 'name': e.name, 'data': e.data} for e in envs])
    else:
        data = request.json
        name = data.get('name')
        env_data = data.get('data')
        e = Environment(user_id=current_user.id, name=name, data=env_data)
        db.session.add(e)
        db.session.commit()
        return jsonify({'id': e.id, 'name': e.name, 'data': e.data})

# --- E2E Test Save API ---
@app.route('/api/e2e-tests', methods=['POST'])
def save_e2e_test():
    data = request.json
    test_name = data.get('testName')
    steps = data.get('steps')
    created_by = data.get('createdBy')
    user_id = None
    if current_user.is_authenticated:
        user_id = current_user.id
    if not test_name:
        return jsonify({'error': 'Missing testName'}), 400
    if steps is None:
        steps = []
    # Store steps as JSON string
    steps_json = json.dumps(steps)
    e2e_test = E2ETest(
        user_id=user_id,
        test_name=test_name,
        steps=steps_json,
        created_by=created_by
    )
    db.session.add(e2e_test)
    db.session.commit()
    # Always return JSON
    return jsonify({'success': True, 'testId': e2e_test.id})

# --- E2E Test List API ---

@app.route('/api/e2e-tests/<int:test_id>', methods=['PUT'])
def update_e2e_test(test_id):
    data = request.json
    test = E2ETest.query.get_or_404(test_id)
    test.test_name = data.get('testName', test.test_name)
    test.steps = json.dumps(data.get('steps', json.loads(test.steps)))
    test.created_by = data.get('createdBy', test.created_by)
    db.session.commit()
    # Always return JSON
    return jsonify({'success': True, 'testId': test.id})

@app.route('/api/e2e-tests', methods=['GET'])
def list_e2e_tests():
    tests = E2ETest.query.all()
    return jsonify([
        {
            'id': t.id,
            'testName': t.test_name,
            'createdBy': t.created_by,
            'createdAt': t.created_at.isoformat()
        } for t in tests
    ])

# --- E2E Test Get by ID API ---
@app.route('/api/e2e-tests/<int:test_id>', methods=['GET'])
def get_e2e_test(test_id):
    t = E2ETest.query.get_or_404(test_id)
    return jsonify({
        'id': t.id,
        'testName': t.test_name,
        'steps': json.loads(t.steps),
        'createdBy': t.created_by,
        'createdAt': t.created_at.isoformat()
    })

# --- E2E Test Delete by ID API ---
@app.route('/api/e2e-tests/<int:test_id>', methods=['DELETE'])
def delete_e2e_test(test_id):
    t = E2ETest.query.get_or_404(test_id)
    db.session.delete(t)
    db.session.commit()
    return jsonify({'success': True})

# --- E2E Generate Zip API ---
@app.route('/api/generate-e2e-zip', methods=['POST'])
def generate_e2e_zip():
    data = request.json or {}
    test_ids = data.get('testIds')  # Optional: list of IDs
    if test_ids:
        tests = E2ETest.query.filter(E2ETest.id.in_(test_ids)).all()
    else:
        tests = E2ETest.query.all()
    steps = []
    for t in tests:
        steps.append({
            'testName': t.test_name,
            'steps': json.loads(t.steps)
        })
    import io
    zip_bytes = create_gradle_zip(steps, mode='e2e')
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype='application/zip',
        as_attachment=True,
        download_name='e2e-tests.zip'
    )

@app.route('/test-generator')
@jira_auth_required
def test_generator():
    return render_template('manual-test-generator.html', active_tab='manual', is_development=FLASK_ENV == 'development')

# Keep old route for backward compatibility
@app.route('/manual-co-test')
@jira_auth_required
def manual_co_test():
    return redirect('/test-generator', code=301)

@app.route('/api/scheduled-jobs', methods=['GET', 'POST'])
def handle_scheduled_jobs():
    if request.method == 'GET':
        jobs = ScheduledJob.query.all()
        return jsonify([
            {
                'id': j.id,
                'user_id': j.user_id,
                'collection_id': j.collection_id,
                'environment_id': j.environment_id,
                'frequency': j.frequency,
                'cron': j.cron,
                'last_run': j.last_run.isoformat() if j.last_run else None,
                'created_at': j.created_at.isoformat() if j.created_at else None
            } for j in jobs
        ])
    else:
        data = request.json
        collection_id = data.get('collection_id')
        environment_id = data.get('environment_id')
        frequency = data.get('frequency')
        cron = data.get('cron')
        job = ScheduledJob(
            user_id=current_user.id if current_user.is_authenticated else None,
            collection_id=collection_id,
            environment_id=environment_id,
            frequency=frequency,
            cron=cron
        )
        db.session.add(job)
        db.session.commit()

        # Schedule the job
        if frequency == 'custom' and cron:
            trigger = CronTrigger.from_crontab(cron)
        else:
            trigger = frequency  # e.g., 'interval', 'date', etc. (should be validated)

        scheduler.add_job(
            run_scheduled_job,
            trigger=trigger,
            args=[job.id],
            id=f'scheduled_job_{job.id}',
            replace_existing=True
        )
        return jsonify({'id': job.id})

def run_scheduled_job(job_id):
    try:
        job = ScheduledJob.query.get(job_id)
        if not job:
            logger.error(f"Scheduled job {job_id} not found.")
            return
        collection = Collection.query.get(job.collection_id)
        environment = Environment.query.get(job.environment_id)
        if not collection or not environment:
            logger.error(f"Collection or environment not found for job {job_id}")
            return
        # Assume collection.data is JSON string
        collection_data = json.loads(collection.data) if collection.data else {}
        for request_obj in collection_data.get('requests', []):
            processed_request = process_request_with_environment(request_obj, environment)
            send_request(processed_request)
        job.last_run = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        logger.error(f"Error running scheduled job {job_id}: {str(e)}")

@app.route('/send-request', methods=['POST'])
def send_request():
    try:
        data = request.json
        method = data.get('method', 'GET').upper()
        url = data.get('url', '').strip()
        headers = data.get('headers', {})
        body = data.get('body')

        # Input validation
        if not url:
            return jsonify({"error": "URL is required"}), 400

        if not validate_url(url):
            return jsonify({"error": "Invalid URL format"}), 400

        if method not in ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS']:
            return jsonify({"error": "Invalid HTTP method"}), 400

        # Validate headers JSON
        if not isinstance(headers, dict):
            return jsonify({"error": "Headers must be a valid JSON object"}), 400

        # Sanitize headers but preserve content-type and other important headers
        content_type = headers.get('content-type', '')
        origin = headers.get('origin', '')
        referer = headers.get('referer', '')
        headers = sanitize_headers(headers)
        
        # Restore important headers
        if content_type:
            headers['content-type'] = content_type
        if origin:
            headers['origin'] = origin
        if referer:
            headers['referer'] = referer

        # Handle form-urlencoded data
        if body and 'application/x-www-form-urlencoded' in content_type.lower():
            form_data = parse_form_data(body)
            body = urlencode(form_data, doseq=True)
            logger.info(f"Form data: {form_data}")

        # Make the request
        logger.info(f"Making {method} request to {url}")
        logger.info(f"Headers: {headers}")
        logger.info(f"Body: {body}")

        session = requests.Session()
        response = session.request(
            method=method,
            url=url,
            headers=headers,
            data=body,
            timeout=30,
            verify=True,
            allow_redirects=True
        )

        # Prepare response
        response_data = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": response.text,
            "timestamp": datetime.utcnow().isoformat(),
            "request_time": response.elapsed.total_seconds()
        }

        # Try to parse JSON response
        try:
            response_data["body"] = response.json()
            response_data["is_json"] = True
        except:
            response_data["is_json"] = False

        return jsonify(response_data)

    except RequestException as e:
        logger.error(f"Request error: {str(e)}")
        return jsonify({
            "error": f"Request failed: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }), 500
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return jsonify({
            "error": f"An unexpected error occurred: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }), 500

@app.route('/convert_collection', methods=['POST'])
def convert_collection():
    mode = request.form.get('mode', 'deterministic')
    if 'collection' not in request.files:
        return 'No file uploaded', 400
    file = request.files['collection']
    try:
        collection = json.load(file)
    except Exception as e:
        return f'Invalid JSON: {e}', 400

    if mode == 'upgrad':
        # Upgrad Context: Use Upgrad project utilities
        import re
        items = extract_requests(collection.get('item', []))
        variable_setup = [
            '        String firstName = RandomGenerator.randomfirstname();',
            '        String lastName = RandomGenerator.randomlastname();',
            '        String email = RandomGenerator.randomEmail();',
            '        String phone = "9" + (long)(Math.random() * 1_000_000_000L);',
            '        String password = "password";'
        ]
        variable_map = {
            'first_name': 'firstName',
            'last_name': 'lastName',
            'user_email_OMS': 'email',
            'phone_number': 'phone',
            'password': 'password',
        }
        scenario_steps = []
        property_writes = []
        last_response_var = None
        for idx, item in enumerate(items):
            req = item.get('request', {})
            step_lines = []
            payload_decl = ''
            method = req.get('method', 'GET').upper()
            # --- Build payload using JSONObject ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                try:
                    import json as pyjson
                    body_dict = pyjson.loads(req['body']['raw'])
                except Exception:
                    body_dict = None
                if body_dict:
                    step_lines.append('        JSONObject payload = new JSONObject();')
                    for k, v in body_dict.items():
                        m = re.match(r'{{(.+?)}}', str(v))
                        if m and m.group(1) in variable_map:
                            step_lines.append(f'        payload.put("{k}", {variable_map[m.group(1)]});')
                        else:
                            if isinstance(v, str):
                                step_lines.append(f'        payload.put("{k}", "{v}");')
                            else:
                                step_lines.append(f'        payload.put("{k}", {v});')
                else:
                    payload = req['body']['raw']
                    for k, v in variable_map.items():
                        payload = payload.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    step_lines.append(f'        JSONObject payload = new JSONObject("{payload}");')
            elif req.get('body', {}).get('mode') == 'graphql':
                gql = req['body'].get('graphql', {})
                query = gql.get('query', '').replace('"', '\\"').replace('\n', ' ')
                variables = gql.get('variables', '').replace('"', '\\"').replace('\n', ' ')
                for k, v in variable_map.items():
                    query = query.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    variables = variables.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                step_lines.append(f'        String gqlPayload = "{{\\"query\\":\\"{query}\\",\\"variables\\":{variables}}}";')
            # --- Build request ---
            url = ''
            if isinstance(req.get('url'), dict):
                url = req['url'].get('raw') or ''
            elif isinstance(req.get('url'), str):
                url = req['url']
            for k, v in variable_map.items():
                url = url.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
            # --- Query params ---
            query_params = ''
            if isinstance(req.get('url'), dict) and req['url'].get('query'):
                for qp in req['url']['query']:
                    k = qp.get('key')
                    v = qp.get('value')
                    for vk, vv in variable_map.items():
                        v = v.replace(f"{{{{{vk}}}}}", '" + ' + vv + ' + "')
                    query_params += f'.queryParam("{k}", "{v}")\n'
            # --- URL Handling for RestAssured ---
            use_direct_url = False
            base_uri, base_path = '', ''
            if url.startswith('http'):
                from urllib.parse import urlparse
                u = urlparse(url)
                base_uri = f'{u.scheme}://{u.netloc}'
                base_path = u.path
            elif url.startswith('{{') and '}}' in url:
                # variable-based url, e.g. {{Stage_Auth_APIs}}/auth/v5/login
                var_end = url.index('}}') + 2
                base_uri = url[:var_end]
                base_path = url[var_end:]
                if base_path.startswith('/'):
                    pass
                else:
                    base_path = '/' + base_path if base_path else ''
            elif url:
                use_direct_url = True
            # --- Get a safe Java variable name from request name ---
            req_name = item.get('name', f'request{idx+1}')
            safe_req_name = re.sub(r'[^0-9a-zA-Z_]', '_', req_name.strip().replace(' ', '_'))
            response_var = f'response_{safe_req_name}'
            if use_direct_url:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
            else:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
                if base_uri:
                    step_lines.append(f'                .baseUri("{base_uri}")')
                if base_path:
                    step_lines.append(f'                .basePath("{base_path}")')
            # --- Headers ---
            header_keys = set()
            for h in req.get('header', []):
                h_val = h.get('value', '')
                for k, v in variable_map.items():
                    h_val = h_val.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                if h.get("key") not in header_keys:
                    step_lines.append(f'                .header("{h.get("key")}", "{h_val}")')
                    header_keys.add(h.get("key"))
            # --- Query Params ---
            if query_params:
                for qline in query_params.strip().split('\n'):
                    step_lines.append(f'                {qline}')
            # --- Auth (Bearer) ---
            if req.get('auth', {}).get('type') == 'bearer':
                for b in req['auth'].get('bearer', []):
                    if 'Authorization' not in header_keys:
                        step_lines.append(f'                .header("Authorization", "Bearer {b.get("value")}")')
                        header_keys.add('Authorization')
            # --- Body ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                step_lines.append('                .body(payload.toString())')
            elif req.get('body', {}).get('mode') == 'graphql':
                step_lines.append('                .body(gqlPayload)')
            # --- HTTP Method and URL ---
            if use_direct_url:
                if method == 'GET':
                    step_lines.append(f'                .get("{url}")')
                elif method == 'POST':
                    step_lines.append(f'                .post("{url}")')
                elif method == 'PUT':
                    step_lines.append(f'                .put("{url}")')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete("{url}")')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch("{url}")')
                else:
                    step_lines.append(f'                .request("{method}", "{url}")')
            else:
                if method == 'GET':
                    step_lines.append(f'                .get()')
                elif method == 'POST':
                    step_lines.append(f'                .post()')
                elif method == 'PUT':
                    step_lines.append(f'                .put()')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete()')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch()')
                else:
                    step_lines.append(f'                .request("{method}")')
            step_lines.append(f'        ;')
            step_lines.append(f'        if ({response_var}.statusCode() != 200) {{')
            step_lines.append(f'            throw new RuntimeException("Request failed: " + {response_var}.asString());')
            step_lines.append('        }')
            # --- Extract variables from response (test script) ---
            for event in item.get('event', []):
                if event.get('listen') == 'test':
                    script = '\n'.join(event['script'].get('exec', []))
                    m = re.search(r'pm\\.environment\\.set\\([\"\'](\\w+)[\"\'],\\s*jsondata\\.(\\w+)\\)', script)
                    if m:
                        varname, respfield = m.group(1), m.group(2)
                        variable_map[varname] = varname
                        step_lines.append(f'        String {varname} = {response_var}.jsonPath().getString("{respfield}");')
            if idx == len(items)-1:
                property_writes.append('        try {')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "FIRSTNAME", firstName);')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "LASTNAME", lastName);')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "PHONE", phone);')
                property_writes.append('            PropertyHandler.writeProperty("src/test/resources/TestData/Prism/PrismTestData.properties", "USERNAME", email);')
                property_writes.append('            System.out.println("[JAVA] USERNAME property written to: src/test/resources/TestData/Prism/PrismTestData.properties");')
                property_writes.append('        } catch (Exception e) { e.printStackTrace(); }')
            scenario_steps.extend(step_lines)
        class_code = (
            'import io.restassured.RestAssured;\n'
            'import io.restassured.response.Response;\n'
            'import org.json.JSONObject;\n'
            'import org.junit.Test;\n'
            'import static io.restassured.RestAssured.*;\n'
            'import static org.hamcrest.Matchers.*;\n'
            'import java.time.LocalDateTime;\n'
            'import java.time.format.DateTimeFormatter;\n'
            'import com.Upgrad.CommonLibrary.utilities.RandomGenerator;\n'
            'import com.Upgrad.CommonLibrary.utilities.PropertyHandler;\n'
            'public class RestAssuredTests {\n'
            '    @Test\n'
            '    public void scenario() throws Exception {\n'
            + ('\n'.join(variable_setup) + '\n' if variable_setup else '')
            + '\n'.join(scenario_steps) + '\n'
            + ('\n'.join(property_writes) + '\n' if property_writes else '')
            + '    }\n'
            + '}'
        )
        collection_name = collection.get('info', {}).get('name', 'RestAssuredTests')
        safe_collection_name = re.sub(r'[^0-9a-zA-Z_]', '_', collection_name.strip().replace(' ', '_'))
        java_filename = f"{safe_collection_name}.java"
        fd, path = tempfile.mkstemp(suffix='.java')
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(class_code)
        return send_file(path, as_attachment=True, download_name=java_filename, mimetype='text/x-java-source')
    elif mode == 'general':
        # General Purpose: Use only standard Java and open-source libraries
        import re
        items = extract_requests(collection.get('item', []))
        variable_setup = [
            '        DateTimeFormatter dtf = DateTimeFormatter.ofPattern("ssmmddMMyy");',
            '        String uniqueNumber = LocalDateTime.now().format(dtf);',
            '        String firstName = "Auto" + uniqueNumber;',
            '        String lastName = "User" + uniqueNumber;',
            '        String email = firstName + lastName + "@mailinator.com";',
            '        String phone = "9" + (long)(Math.random() * 1_000_000_000L);',
            '        String password = "password";'
        ]
        variable_map = {
            'first_name': 'firstName',
            'last_name': 'lastName',
            'user_email_OMS': 'email',
            'phone_number': 'phone',
            'password': 'password',
        }
        scenario_steps = []
        property_writes = []
        last_response_var = None
        for idx, item in enumerate(items):
            req = item.get('request', {})
            step_lines = []
            payload_decl = ''
            method = req.get('method', 'GET').upper()
            # --- Build payload using JSONObject ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                try:
                    import json as pyjson
                    body_dict = pyjson.loads(req['body']['raw'])
                except Exception:
                    body_dict = None
                if body_dict:
                    step_lines.append('        JSONObject payload = new JSONObject();')
                    for k, v in body_dict.items():
                        m = re.match(r'{{(.+?)}}', str(v))
                        if m and m.group(1) in variable_map:
                            step_lines.append(f'        payload.put("{k}", {variable_map[m.group(1)]});')
                        else:
                            if isinstance(v, str):
                                step_lines.append(f'        payload.put("{k}", "{v}");')
                            else:
                                step_lines.append(f'        payload.put("{k}", {v});')
                else:
                    payload = req['body']['raw']
                    for k, v in variable_map.items():
                        payload = payload.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    step_lines.append(f'        JSONObject payload = new JSONObject("{payload}");')
            elif req.get('body', {}).get('mode') == 'graphql':
                gql = req['body'].get('graphql', {})
                query = gql.get('query', '').replace('"', '\\"').replace('\n', ' ')
                variables = gql.get('variables', '').replace('"', '\\"').replace('\n', ' ')
                for k, v in variable_map.items():
                    query = query.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                    variables = variables.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                step_lines.append(f'        String gqlPayload = "{{\\"query\\":\\"{query}\\",\\"variables\\":{variables}}}";')
            # --- Build request ---
            url = ''
            if isinstance(req.get('url'), dict):
                url = req['url'].get('raw') or ''
            elif isinstance(req.get('url'), str):
                url = req['url']
            for k, v in variable_map.items():
                url = url.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
            # --- Query params ---
            query_params = ''
            if isinstance(req.get('url'), dict) and req['url'].get('query'):
                for qp in req['url']['query']:
                    k = qp.get('key')
                    v = qp.get('value')
                    for vk, vv in variable_map.items():
                        v = v.replace(f"{{{{{vk}}}}}", '" + ' + vv + ' + "')
                    query_params += f'.queryParam("{k}", "{v}")\n'
            # --- URL Handling for RestAssured ---
            use_direct_url = False
            base_uri, base_path = '', ''
            if url.startswith('http'):
                from urllib.parse import urlparse
                u = urlparse(url)
                base_uri = f'{u.scheme}://{u.netloc}'
                base_path = u.path
            elif url.startswith('{{') and '}}' in url:
                # variable-based url, e.g. {{Stage_Auth_APIs}}/auth/v5/login
                var_end = url.index('}}') + 2
                base_uri = url[:var_end]
                base_path = url[var_end:]
                if base_path.startswith('/'):
                    pass
                else:
                    base_path = '/' + base_path if base_path else ''
            elif url:
                use_direct_url = True
            # --- Get a safe Java variable name from request name ---
            req_name = item.get('name', f'request{idx+1}')
            safe_req_name = re.sub(r'[^0-9a-zA-Z_]', '_', req_name.strip().replace(' ', '_'))
            response_var = f'response_{safe_req_name}'
            if use_direct_url:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
            else:
                step_lines.append(f'        Response {response_var} = RestAssured.given()')
                if base_uri:
                    step_lines.append(f'                .baseUri("{base_uri}")')
                if base_path:
                    step_lines.append(f'                .basePath("{base_path}")')
            # --- Headers ---
            header_keys = set()
            for h in req.get('header', []):
                h_val = h.get('value', '')
                for k, v in variable_map.items():
                    h_val = h_val.replace(f"{{{{{k}}}}}", '" + ' + v + ' + "')
                if h.get("key") not in header_keys:
                    step_lines.append(f'                .header("{h.get("key")}", "{h_val}")')
                    header_keys.add(h.get("key"))
            # --- Query Params ---
            if query_params:
                for qline in query_params.strip().split('\n'):
                    step_lines.append(f'                {qline}')
            # --- Auth (Bearer) ---
            if req.get('auth', {}).get('type') == 'bearer':
                for b in req['auth'].get('bearer', []):
                    if 'Authorization' not in header_keys:
                        step_lines.append(f'                .header("Authorization", "Bearer {b.get("value")}")')
                        header_keys.add('Authorization')
            # --- Body ---
            if req.get('body', {}).get('mode') == 'raw' and req['body'].get('raw'):
                step_lines.append('                .body(payload.toString())')
            elif req.get('body', {}).get('mode') == 'graphql':
                step_lines.append('                .body(gqlPayload)')
            # --- HTTP Method and URL ---
            if use_direct_url:
                if method == 'GET':
                    step_lines.append(f'                .get("{url}")')
                elif method == 'POST':
                    step_lines.append(f'                .post("{url}")')
                elif method == 'PUT':
                    step_lines.append(f'                .put("{url}")')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete("{url}")')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch("{url}")')
                else:
                    step_lines.append(f'                .request("{method}", "{url}")')
            else:
                if method == 'GET':
                    step_lines.append(f'                .get()')
                elif method == 'POST':
                    step_lines.append(f'                .post()')
                elif method == 'PUT':
                    step_lines.append(f'                .put()')
                elif method == 'DELETE':
                    step_lines.append(f'                .delete()')
                elif method == 'PATCH':
                    step_lines.append(f'                .patch()')
                else:
                    step_lines.append(f'                .request("{method}")')
            step_lines.append(f'        ;')
            step_lines.append(f'        if ({response_var}.statusCode() != 200) {{')
            step_lines.append(f'            throw new RuntimeException("Request failed: " + {response_var}.asString());')
            step_lines.append('        }')
            for event in item.get('event', []):
                if event.get('listen') == 'test':
                    script = '\n'.join(event['script'].get('exec', []))
                    m = re.search(r'pm\\.environment\\.set\\([\"\'](\\w+)[\"\'],\\s*jsondata\\.(\\w+)\\)', script)
                    if m:
                        varname, respfield = m.group(1), m.group(2)
                        variable_map[varname] = varname
                        step_lines.append(f'        String {varname} = {response_var}.jsonPath().getString("{respfield}");')
            if idx == len(items)-1:
                property_writes.append('        try {')
                property_writes.append('            Properties props = new Properties();')
                property_writes.append('            File file = new File("src/test/resources/TestData/Prism/PrismTestData.properties");')
                property_writes.append('            if (file.exists()) {')
                property_writes.append('                try (FileInputStream fis = new FileInputStream(file)) {')
                property_writes.append('                    props.load(fis);')
                property_writes.append('                }')
                property_writes.append('            }')
                property_writes.append('            props.setProperty("FIRSTNAME", firstName);')
                property_writes.append('            props.setProperty("LASTNAME", lastName);')
                property_writes.append('            props.setProperty("PHONE", phone);')
                property_writes.append('            props.setProperty("USERNAME", email);')
                property_writes.append('            try (FileOutputStream fos = new FileOutputStream(file)) {')
                property_writes.append('                props.store(fos, "Updated by SelfPacedLearnerEnrollmentHook");')
                property_writes.append('            }')
                property_writes.append('            System.out.println("[JAVA] USERNAME property written to: " + file.getAbsolutePath());')
                property_writes.append('        } catch (Exception e) { e.printStackTrace(); }')
            scenario_steps.extend(step_lines)
        class_code = (
            'import io.restassured.RestAssured;\n'
            'import io.restassured.response.Response;\n'
            'import org.json.JSONObject;\n'
            'import org.junit.Test;\n'
            'import static io.restassured.RestAssured.*;\n'
            'import static org.hamcrest.Matchers.*;\n'
            'import java.time.LocalDateTime;\n'
            'import java.time.format.DateTimeFormatter;\n'
            'import java.io.*;\n'
            'import java.util.Properties;\n'
            'public class RestAssuredTests {\n'
            '    @Test\n'
            '    public void scenario() throws Exception {\n'
            + ('\n'.join(variable_setup) + '\n' if variable_setup else '')
            + '\n'.join(scenario_steps) + '\n'
            + ('\n'.join(property_writes) + '\n' if property_writes else '')
            + '    }\n'
            + '}'
        )
        collection_name = collection.get('info', {}).get('name', 'RestAssuredTests')
        safe_collection_name = re.sub(r'[^0-9a-zA-Z_]', '_', collection_name.strip().replace(' ', '_'))
        java_filename = f"{safe_collection_name}.java"
        fd, path = tempfile.mkstemp(suffix='.java')
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
            tmp.write(class_code)
        return send_file(path, as_attachment=True, download_name=java_filename, mimetype='text/x-java-source')
    else:
        return 'AI mode not implemented yet', 400

@app.route('/proxy')
def proxy():
    """
    Acts as a proxy for external websites to bypass X-Frame-Options restrictions.
    """
    url = request.args.get('url')
    if not url:
        return "Missing URL parameter", 400
    
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    try:
        # Fetch the target website
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        content_type = response.headers.get('Content-Type', 'text/html')
        
        # Process the HTML content to fix relative URLs
        if 'text/html' in content_type:
            html = response.text
            
            # Fix relative URLs for images, scripts, stylesheets, etc.
            parsed_url = urlparse(url)
            base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
            
            # Fix relative URLs in src and href attributes
            html = re.sub(r'(src|href)=[\'"](?!http)([^\'"]+)[\'"]', 
                         lambda m: f'{m.group(1)}="{urljoin(base_url, m.group(2))}"', 
                         html)
            
            # Add our recording script
            inject_script = """
            <script>
            // UI Recording script will be injected here
            console.log('UI Recorder proxy is active on this page');
            
            // Connect back to parent window for recording events
            window.addEventListener('click', function(e) {
                window.parent.postMessage({
                    type: 'recorder_event',
                    eventType: 'click',
                    selector: e.target.tagName.toLowerCase(),
                    innerText: e.target.innerText
                }, '*');
            }, true);
            
            // More event listeners could be added here
            </script>
            """
            html = html.replace('</body>', inject_script + '</body>')
            
            return html
        else:
            # For non-HTML content, just pass it through
            return response.content, 200, {'Content-Type': content_type}
            
    except Exception as e:
        return f"Error proxying content: {str(e)}", 500

@app.route('/direct-recorder')
def direct_recorder():
    """
    An alternative recorder that uses a bookmarklet approach
    to handle websites with X-Frame-Options restrictions.
    """
    # Create a much simpler bookmarklet
    bookmarklet_code = """
    (function(){
      // Create UI
      var d = document.createElement('div');
      d.style.position = 'fixed';
      d.style.top = '0';
      d.style.right = '0';
      d.style.zIndex = '9999999';
      d.style.background = 'red';
      d.style.color = 'white';
      d.style.padding = '10px';
      d.innerHTML = '🔴 Recording';
      document.body.appendChild(d);
      
      // Store actions
      var acts = [];
      
      // Record navigation
      acts.push({type:'nav', url:location.href});
      
      // Record clicks
      document.addEventListener('click', function(e){
        var t = e.target;
        var s = t.id ? '#'+t.id : t.tagName;
        acts.push({type:'click', sel:s, txt:t.innerText});
        d.innerHTML = '🔴 Click recorded';
        setTimeout(function(){d.innerHTML='🔴 Recording';}, 1000);
      }, true);
      
      // Stop button
      var b = document.createElement('button');
      b.innerHTML = 'Stop';
      b.style.marginLeft = '10px';
      b.onclick = function(){
        var w = window.open();
        w.document.write('<h1>Recorded Actions</h1><pre>'+JSON.stringify(acts,null,2)+'</pre>');
        w.document.write('<h1>Java Code</h1><pre>'+genCode(acts)+'</pre>');
        document.body.removeChild(d);
      };
      d.appendChild(b);
      
      // Generate code
      function genCode(a){
        var c = 'import org.openqa.selenium.*;\n';
        c += 'import org.openqa.selenium.chrome.ChromeDriver;\n\n';
        c += 'public class UiTest {\n';
        c += '    public static void main(String[] args) {\n';
        c += '        WebDriver driver = new ChromeDriver();\n';
        
        a.forEach(function(x){
          if(x.type == 'nav') {
            c += '        driver.get("'+x.url+'");\n';
          } else if(x.type == 'click') {
            c += '        driver.findElement(By.cssSelector("'+x.sel+'")).click();\n';
          }
        });
        
        c += '        driver.quit();\n';
        c += '    }\n';
        c += '}';
        return c;
      }
    })();
    """
    
    # Clean up the code
    bookmarklet_code = "javascript:" + bookmarklet_code.replace('\n', '').replace('    ', '').replace('  ', '')
    
    return render_template('direct-recorder.html', bookmarklet=bookmarklet_code)

@app.route('/simple-recorder')
def simple_recorder():
    """
    Redirect to the static recorder page that has a guaranteed working bookmarklet
    """
    return redirect('/static/record.html')

@app.route('/selenium-recorder')
def selenium_recorder():
    return render_template('selenium-recorder.html')

@app.route('/download-extension')
def download_extension():
    return render_template('download_extension.html')

@app.route('/dom-extractor')
def dom_extractor():
    return render_template('dom-extractor.html', active_tab='ui')

@app.route('/upload-session', methods=['POST'])
def upload_session():
    file = request.files.get('sessionfile')
    if not file:
        return 'No file uploaded.', 400
    # Save the uploaded file to a directory (e.g., uploads/)
    import os
    upload_dir = os.path.join(os.path.dirname(__file__), 'uploads')
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, file.filename)
    file.save(filepath)
    return f'Session uploaded successfully as {file.filename}!'

@app.route('/convert_curl', methods=['POST'])
def convert_curl():
    """
    Convert a curl command to Java RestAssured code
    """
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        curl_command = data.get('curl')
        mode = data.get('mode', 'general')
        
        if not curl_command:
            return jsonify({"error": "No curl command provided"}), 400
        
        # Parse the curl command
        parsed_curl = parse_curl_command(curl_command)
        
        # Generate Java code based on mode
        if mode == 'upgrad':
            java_code = generate_upgrad_java_code(parsed_curl)
        else:  # general or any other mode
            java_code = generate_general_java_code(parsed_curl)
            
        # If requested as file download
        if data.get('download'):
            # Extract endpoint name from URL for naming
            url_parts = parsed_curl['url'].split('/')
            endpoint = url_parts[-1] if url_parts[-1] else 'endpoint'
            class_name = 'Test' + endpoint.capitalize().replace('-', '_')
            
            fd, path = tempfile.mkstemp(suffix='.java')
            with os.fdopen(fd, 'w', encoding='utf-8') as tmp:
                tmp.write(java_code)
            return send_file(path, as_attachment=True, download_name=f"{class_name}.java", mimetype='text/x-java-source')
        
        # Otherwise return as JSON
        return jsonify({"code": java_code})
        
    except Exception as e:
        logger.error(f"Error converting curl: {str(e)}")
        return jsonify({"error": str(e)}), 500

def parse_curl_command(curl):
    """
    Parse a curl command into its components
    """
    result = {
        'method': 'GET',
        'url': '',
        'headers': {},
        'body': '',
        'content_type': 'application/json'
    }
    
    # Extract URL - looking for the first URL-like string
    url_match = re.search(r'https?://[^\s\'"]+', curl)
    if url_match:
        result['url'] = url_match.group(0).strip('"\'')
    
    # Extract method
    method_match = re.search(r'-X\s+([A-Z]+)', curl)
    if method_match:
        result['method'] = method_match.group(1)
    
    # Extract headers
    header_matches = re.finditer(r'-H\s+[\'"]([^:]+):\s*([^\'"]+)[\'"]', curl)
    for match in header_matches:
        header_name = match.group(1).strip()
        header_value = match.group(2).strip()
        result['headers'][header_name] = header_value
        
        # Check for content type
        if header_name.lower() == 'content-type':
            result['content_type'] = header_value
    
    # Extract body - look for -d or --data or --data-raw (handle multi-line)
    # First try to find quoted multi-line JSON
    body_patterns = [
        r'--data-raw\s+[\'"](.*?)[\'"]\s',
        r'--data\s+[\'"](.*?)[\'"]\s', 
        r'-d\s+[\'"](.*?)[\'"]\s'
    ]
    
    for pattern in body_patterns:
        body_match = re.search(pattern, curl + ' ', re.DOTALL)
        if body_match:
            body_text = body_match.group(1)
            # Clean up the body text - remove extra whitespace but preserve JSON structure
            result['body'] = body_text.strip()
            break
    
    # If method is GET but we have a body, assume it's actually POST
    if result['method'] == 'GET' and result['body']:
        result['method'] = 'POST'
    
    return result

def generate_upgrad_java_code(parsed_curl):
    """
    Generate Java code for Upgrad context using their utilities
    """
    method = parsed_curl['method']
    url = parsed_curl['url']
    headers = parsed_curl['headers']
    body = parsed_curl['body']
    content_type = parsed_curl.get('content_type', 'application/json')

    # Fix Content-Type header if needed
    fixed_headers = {}
    for k, v in headers.items():
        if k.lower() == 'content-type' and v.lower().startswith('application/json'):
            fixed_headers[k] = 'application/json'
        else:
            fixed_headers[k] = v
    headers = fixed_headers

    # Extract endpoint for naming
    url_parts = url.split('/')
    endpoint = url_parts[-1] if url_parts[-1] else 'endpoint'
    class_name = 'Test' + ''.join(word.capitalize() for word in re.sub(r'[^a-zA-Z0-9]', ' ', endpoint).split())
    
    # Start building the Java code
    java = f"""package com.upgrad.test.api;

import com.upgrad.test.base.TestBase;
import com.upgrad.test.util.PropertyHandler;
import com.upgrad.test.util.RandomGenerator;
import io.restassured.response.Response;
import org.testng.annotations.Test;
import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.*;

public class {class_name} extends TestBase {{

    @Test
    public void test{method.lower()}{endpoint.capitalize()}() {{
        // Set base URI from config
        String baseURI = PropertyHandler.getProperty("api.base.url");

        // Build request
        Response response = given()
            .spec(getRequestSpecification())
"""
    
    # Add headers
    if headers:
        java += "            // Add headers\n"
        for key, value in headers.items():
                java += f'            .header("{key}", PropertyHandler.getProperty("api.auth.token"))\n'
    
    # Add body if present
    if body:
        java += "            // Add request body\n"
        if 'json' in content_type.lower():
            try:
                # Try to parse as JSON to see if it's valid
                json_body = json.loads(body)
                java += '            .body(' + repr(json.dumps(json_body, indent=4)) + ')\n'
            except:
                # Not valid JSON, use as string
                body_escaped = body.replace('"', '\\"')
                java += f'            .body("{body_escaped}")\n'
        else:
            body_escaped = body.replace('"', '\\"')
            java += f'            .body("{body_escaped}")\n'
    
    # Add request method and path
    base_url_parts = url.split('/')[:3]  # http(s)://domain.com
    base_url = '/'.join(base_url_parts)
    path = '/' + '/'.join(url.split('/')[3:])
    
    java += f"""            // Send request
            .when()
            .{method.lower()}("{path}")
            // Process response
            .then()
            .log().all()
            .assertThat().statusCode(200)
            .extract().response();

        // Validate response
        validateResponse(response, "{endpoint}");
    }}
}}
"""
    
    return java

def generate_general_java_code(parsed_curl):
    """
    Generate general-purpose Java code using standard RestAssured
    """
    method = parsed_curl['method']
    url = parsed_curl['url']
    headers = parsed_curl['headers']
    body = parsed_curl['body']
    content_type = parsed_curl.get('content_type', 'application/json')

    # Fix Content-Type header if needed
    fixed_headers = {}
    for k, v in headers.items():
        if k.lower() == 'content-type' and v.lower().startswith('application/json'):
            fixed_headers[k] = 'application/json'
        else:
            fixed_headers[k] = v
    headers = fixed_headers

    # Extract endpoint for naming
    url_parts = url.split('/')
    endpoint = url_parts[-1] if url_parts[-1] else 'endpoint'
    class_name = 'Test' + ''.join(word.capitalize() for word in re.sub(r'[^a-zA-Z0-9]', ' ', endpoint).split())
    
    # Start building the Java code
    java_code = []
    java_code.append("import io.restassured.RestAssured;")
    java_code.append("import io.restassured.response.Response;")
    java_code.append("import io.restassured.http.ContentType;")
    java_code.append("import org.junit.Test;")
    java_code.append("import static io.restassured.RestAssured.*;")
    java_code.append("import static org.hamcrest.Matchers.*;")
    java_code.append("")
    java_code.append(f"public class {class_name} {{")
    java_code.append("")
    java_code.append(f"    @Test")
    java_code.append(f"    public void test{method.lower()}{endpoint.capitalize()}() {{")
    java_code.append(f"        // Set base URI")
    java_code.append(f"        RestAssured.baseURI = \"{'/'.join(url.split('/')[:3])}\";")
    java_code.append("")
    java_code.append(f"        // Build request")
    java_code.append(f"        Response response = given()")
    
    # Add headers
    if headers:
        java_code.append("            // Add headers")
        for key, value in headers.items():
            java_code.append(f'            .header("{key}", "{value}")')
    
    # Add body if present
    if body:
        if 'json' in content_type.lower():
            try:
                # Try to parse as JSON to see if it's valid
                json_body = json.loads(body)
                java_code.append("            // Add JSON body")
                # Use a different approach that doesn't cause syntax errors
                java_code.append('            .body(' + repr(json.dumps(json_body, indent=4)) + ')\n')
            except:
                # Not valid JSON, use as string
                java_code.append("            // Add request body")
                body_escaped = body.replace('"', '\\"')
                body_escaped = body.replace('"', '\\"')
                java_code.append(f'            .body("{body_escaped}")')
        else:
            java_code.append("            // Add request body")
            body_escaped = body.replace('"', '\\"')
            java_code.append(f'            .body("{body_escaped}")')
    
    # Add request method and path
    path = '/' + '/'.join(url.split('/')[3:])
    
    java_code.append("            // Send request")
    java_code.append("            .when()")
    java_code.append(f"            .{method.lower()}(\"{path}\")")
    java_code.append("            // Process response")
    java_code.append("            .then()")
    java_code.append("            .log().all()")
    java_code.append("            .assertThat().statusCode(200)")
    java_code.append("            .extract().response();")
    java_code.append("")
    java_code.append("        // Print response details")
    java_code.append("        System.out.println(\"Status Code: \" + response.getStatusCode());")
    java_code.append("        System.out.println(\"Response Body: \" + response.getBody().asString());")
    java_code.append("    }")
    java_code.append("}")
    
    return "\n".join(java_code)

@app.route('/convert_json', methods=['POST'])
def convert_json():
    """Convert JSON payload to Java code."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
            
        json_str = data.get('json')
        mode = data.get('mode', 'general')
        
        if not json_str:
            return jsonify({'error': 'No JSON string provided'}), 400
            
        try:
            json_obj = json.loads(json_str)
        except json.JSONDecodeError as e:
            return jsonify({'error': f'Invalid JSON: {str(e)}'}), 400
            
        code = generate_java_from_json(json_obj, mode)
        return jsonify({'code': code})
        
    except Exception as e:
        logger.error(f"Error converting JSON to Java: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-zip', methods=['POST'])
def generate_zip():
    try:
        data = request.get_json()
        steps = data.get('steps', [])
        mode = data.get('mode', 'general')
        # Validate all UI steps have a non-empty pageName
        for s in steps:
            if s.get('type') == 'ui' and (not s.get('pageName') or not s.get('pageName').strip()):
                return jsonify({'error': 'All UI Steps must have a non-empty Page Name.'}), 400
        # Optionally, get user email if logged in
        user_email = getattr(current_user, 'email', None) if hasattr(current_user, 'email') else None
        zip_path = create_gradle_zip(steps, mode, user_email)
        return send_file(zip_path, mimetype='application/zip', as_attachment=True, download_name='e2e-test-project.zip')
    except Exception as e:
        logging.exception('Error generating zip')
        return jsonify({'error': str(e)}), 500

CONTEXT_DIR = "context"

def save_context_to_db(context_data, name, description=''):
    """Save context data to database"""
    try:
        # Get user ID
        user_id = get_user_identifier()
        
        # Create a new context record
        new_context = TestContext(
            user_id=user_id,
            name=name,
            description=description,
            # Store the full JSON for backward compatibility
            context_data=json.dumps(context_data),
            # Store individual fields for better querying
            feature_summary=context_data.get('feature_summary', ''),
            # Renamed from 'requirements' to 'functional_requirements' in the prompt
            requirements=json.dumps(context_data.get('functional_requirements', context_data.get('requirements', []))),
            user_flows=json.dumps(context_data.get('user_flows', [])),
            validation_points=json.dumps(context_data.get('validation_points', [])),
            dependencies=json.dumps(context_data.get('dependencies', [])),
            edge_cases=json.dumps(context_data.get('edge_cases', [])),
            data_requirements=json.dumps(context_data.get('data_requirements', [])),
            # Add new fields from enhanced prompt
            performance_criteria=json.dumps(context_data.get('performance_criteria', [])),
            security_considerations=json.dumps(context_data.get('security_considerations', [])),
        )
        
        db.session.add(new_context)
        db.session.commit()
        
        return new_context.id
    except Exception as e:
        app.logger.error(f"Error saving context to database: {str(e)}")
        db.session.rollback()
        return None

def generate_structured_context(content):
    """
    Process raw requirements document with AI to generate structured context
    """
    try:
        # Prepare the prompt for the AI
        prompt = f"""
        You are an advanced analysis system designed explicitly to deeply interpret complex software requirements and generate exhaustive, structured context optimized for automated test case generation using advanced LLMs, specifically Gemini Pro.

        Conduct a meticulous and comprehensive analysis of the provided detailed software requirements document:

        {content}

        Upon completion of your analysis, deliver a highly detailed and structured JSON object containing the following explicitly defined and comprehensive sections:

        1. **"feature_summary"**: Provide an in-depth, clear, and precise summary of the primary features, functionalities, and objectives captured by the requirements, highlighting core purpose and scope.

        2. **"requirements"**: Detail each explicitly stated functional requirement individually, ensuring precision, completeness, and clarity. Organize requirements logically and cohesively, capturing all key functionalities.

        3. **"user_flows"**: Clearly articulate each critical user journey or workflow in detailed, sequential steps. Include clear entry and exit points, decision branches, alternative paths, and interactions within the workflow.

        4. **"validation_points"**: Identify exhaustive validation checks critical for ensuring comprehensive quality standards. Cover aspects such as functionality, usability, accessibility, performance, security, compliance, and user experience considerations.

        5. **"dependencies"**: Thoroughly list and describe all necessary system dependencies, integrations with external or internal services, APIs, databases, infrastructure requirements, and other resources needed for successful implementation and validation.

        6. **"edge_cases"**: Meticulously identify and detail all possible edge cases, exceptional conditions, boundary scenarios, error handling situations, and unexpected user interactions requiring rigorous testing.

        7. **"data_requirements"**: Clearly and comprehensively specify all data-related needs and constraints. Include test data requirements, data formats, expected data types, database schema details, data volume considerations, and any constraints or limitations that impact testing scenarios.

        8. **"performance_criteria"**: Define precise performance metrics, scalability expectations, load conditions, response times, throughput expectations, and other relevant benchmarks critical for validating system performance under realistic conditions.

        9. **"security_considerations"**: Explicitly outline security requirements, including access controls, authentication, authorization protocols, encryption standards, data privacy measures, compliance with relevant security standards, and any vulnerability points that must be rigorously tested.

        Format your output strictly as a clearly structured, valid JSON object containing exactly these keys. Ensure exhaustive coverage, clarity, completeness, and accuracy optimized specifically for use with Gemini Pro-driven automated test generation systems.
        """
        
        # Call Google Generative AI
        genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
        # Use gemini-1.5-pro instead of gemini-pro for newer API compatibility
        model = genai.GenerativeModel('gemini-1.5-pro')
        response = model.generate_content(prompt)
        
        # Extract and parse the JSON from the response
        response_text = response.text
        # Find JSON content between triple backticks if present
        json_match = re.search(r'```json\n(.+?)\n```', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # If no code blocks, try to find a JSON object directly
            json_match = re.search(r'(\{.+\})', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = response_text
                
        # Clean up and parse JSON
        context_data = json.loads(json_str)
        return context_data
    except Exception as e:
        app.logger.error(f"Error generating structured context: {str(e)}")
        raise

def get_context_text(context_name):
    """
    Reads the content of a context file and formats it for the prompt.
    Extracts related scenarios and key terms for better test case generation.
    """
    if not context_name:
        return ""
    path = os.path.join(CONTEXT_DIR, f"{context_name}.txt")
    try:
        with open(path, "r", encoding="utf-8") as f:
            context_content = f.read()

            # Extract key terms (words in all caps or after "Verify", "Test", "Check")
            key_term_pattern = r"(?:Verify|Test|Check)\s+([A-Za-z\s]+)|([A-Z]{2,})"
            key_terms = re.findall(key_term_pattern, context_content)
            key_terms = list(set(term[0].strip() or term[1].strip() for term in key_terms if term[0] or term[1]))

            # Look for scenario patterns
            scenario_pattern = r"(?:Scenario|Test Scenario|Test Case)\s*\d*:\s*(.*?)(?=(?:Scenario|Test Scenario|Test Case)\s*\d*:|$)"
            scenarios = re.findall(scenario_pattern, context_content, re.DOTALL)
            scenarios = [s.strip() for s in scenarios if s.strip()]

            # Format the context with clear sections
            formatted_context = (
                "Context Information:\n"
                f"{context_content}\n\n"
                "Related Scenarios:\n"
                + "\n".join(f"- {scenario}" for scenario in scenarios) + "\n\n"
                "Key Terms and Dependencies:\n"
                + "\n".join(f"- {term}" for term in key_terms) + "\n\n"
                "Instructions:\n"
                "Based on the information above, generate comprehensive manual test scenarios for the described functionality. Ensure your test cases:\n"
                "1. Directly relate to and build upon the 'Context Information'.\n"
                "2. Extend and validate the 'Related Scenarios'.\n"
                "3. Thoroughly test all 'Key Terms and Dependencies'.\n"
                "4. Cover functional flows, edge cases, negative cases, and validations.\n"
                "5. Consider API interactions and UI/UX aspects if relevant to the context.\n"
                "6. Do NOT assume login or unrelated features.\n"
            )
            return formatted_context
    except FileNotFoundError:
        logger.error(f"Context file not found: {path}")
        return ""
    except Exception as e:
        logger.error(f"Error reading context file: {str(e)}")
        return ""

import os
import traceback
import stat
from flask import send_from_directory
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'gif', 'doc', 'docx', 'txt'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        if 'file' not in request.files:
            app.logger.warning('Upload attempt with no file part')
            return jsonify({'error': 'No file part'}), 400
            
        file = request.files['file']
        if file.filename == '':
            app.logger.warning('Upload attempt with empty filename')
            return jsonify({'error': 'No selected file'}), 400
            
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            
            # Ensure upload folder exists
            if not os.path.exists(UPLOAD_FOLDER):
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                app.logger.info(f"Created upload folder: {UPLOAD_FOLDER}")
                
            # Get absolute path for logging
            abs_upload_folder = os.path.abspath(UPLOAD_FOLDER)
            save_path = os.path.join(UPLOAD_FOLDER, filename)
            
            # Save the file
            file.save(save_path)
            app.logger.info(f"File saved successfully: {save_path}")
            
            # Get server name and protocol for absolute URL
            server_name = request.headers.get('Host', '')
            protocol = 'https' if request.is_secure else 'http'
            
            # Create both relative and absolute URLs
            relative_url = f'/uploads/{filename}'
            absolute_url = f"{protocol}://{server_name}{relative_url}"
            
            app.logger.info(f"File URL: {absolute_url}")
            return jsonify({
                'url': relative_url,
                'absolute_url': absolute_url,
                'filename': filename
            })
        else:
            app.logger.warning(f"Invalid file type: {file.filename}")
            return jsonify({'error': 'File type not allowed'}), 400
    except Exception as e:
        app.logger.error(f"Error in upload_file: {str(e)}")
        return jsonify({'error': f'Upload failed: {str(e)}'}), 500

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    try:
        # Log request details
        request_id = id(request)
        app.logger.info(f"[{request_id}] File access request for: {filename}")
        app.logger.info(f"[{request_id}] Request headers: {dict(request.headers)}")
        app.logger.info(f"[{request_id}] Request remote addr: {request.remote_addr}")
        
        # Ensure the upload folder exists
        if not os.path.exists(UPLOAD_FOLDER):
            os.makedirs(UPLOAD_FOLDER, exist_ok=True)
            app.logger.warning(f"[{request_id}] Upload folder {UPLOAD_FOLDER} did not exist, created it")
            
        # Check if the file exists
        file_path = os.path.join(UPLOAD_FOLDER, filename)
        app.logger.info(f"[{request_id}] Looking for file at: {os.path.abspath(file_path)}")
        
        if not os.path.isfile(file_path):
            app.logger.error(f"[{request_id}] File not found: {file_path}")
            app.logger.info(f"[{request_id}] Directory contents: {os.listdir(UPLOAD_FOLDER) if os.path.exists(UPLOAD_FOLDER) else 'upload folder does not exist'}")
            return jsonify({'error': 'File not found'}), 404
            
        # Log successful file access
        app.logger.info(f"[{request_id}] File found, size: {os.path.getsize(file_path)} bytes, serving file...")
        
        # Get server name and protocol for logging
        server_name = request.headers.get('Host', '')
        protocol = 'https' if request.is_secure else 'http'
        app.logger.info(f"[{request_id}] Serving from: {protocol}://{server_name}/uploads/{filename}")
        
        app.logger.info(f"Serving file: {file_path}")
        return send_from_directory(UPLOAD_FOLDER, filename)
    except Exception as e:
        request_id = id(request)
        app.logger.error(f"[{request_id}] Error serving file {filename}: {str(e)}")
        app.logger.error(f"[{request_id}] Exception type: {type(e).__name__}")
        app.logger.error(f"[{request_id}] Exception traceback: {traceback.format_exc()}")
        
        # Check file permissions
        try:
            if os.path.exists(file_path):
                stat_info = os.stat(file_path)
                app.logger.info(f"[{request_id}] File permissions: {stat.filemode(stat_info.st_mode)}")
                app.logger.info(f"[{request_id}] File owner: {stat_info.st_uid}, group: {stat_info.st_gid}")
        except Exception as perm_error:
            app.logger.error(f"[{request_id}] Error checking file permissions: {str(perm_error)}")
            
        return jsonify({
            'error': f'Error serving file: {str(e)}',
            'filename': filename,
            'path': file_path,
            'exception_type': type(e).__name__
        }), 500

# Add this helper function near the top (with other helpers)
def chunk_text(text, chunk_size=15000, overlap=1000):
    """Yield successive chunk_size character chunks from text, with optional overlap."""
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        yield text[start:end]
        start += chunk_size - overlap  # overlap to preserve context continuity

@app.route('/api/generate-testcases', methods=['POST'])
@llm_rate_limit
def generate_testcases():
    import logging
    import json
    import re
    try:
        data = request.json
        scenario = data.get('scenario', '')
        context_name = data.get('context', '')
        visual_image_urls = data.get('visual_image_urls', [])
        visual_doc_url = data.get('visual_doc_url', '')
        jira_image_urls = data.get('jira_image_urls', [])
        if not scenario:
            return jsonify({'error': 'No scenario provided'}), 400

        context_text = get_context_text(context_name)

        # Build visual context section for the prompt
        visual_section = ""
        if visual_doc_url:
            visual_section = (
                f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url}\n"
                "Use the images in the document to infer layout, field positions, and user flow.\n\n"
            )
        # If both doc and images, combine all image URLs
        all_image_urls = []
        
        # Process visual_image_urls to prefer absolute URLs when available
        if visual_image_urls:
            processed_urls = []
            for url_data in visual_image_urls:
                # Check if this is a dict with absolute_url (from our enhanced upload endpoint)
                if isinstance(url_data, dict) and 'absolute_url' in url_data:
                    processed_urls.append(url_data['absolute_url'])
                    app.logger.info(f"Using absolute URL for image: {url_data['absolute_url']}")
                # Check if this is a dict with url (fallback to relative)
                elif isinstance(url_data, dict) and 'url' in url_data:
                    processed_urls.append(url_data['url'])
                    app.logger.info(f"Using relative URL for image: {url_data['url']}")
                # If it's just a string URL
                else:
                    processed_urls.append(url_data)
                    app.logger.info(f"Using provided URL for image: {url_data}")
            all_image_urls.extend(processed_urls)
            
        # Add Jira image URLs
        if jira_image_urls:
            all_image_urls.extend(jira_image_urls)
            
        # Process visual_doc_url to prefer absolute URL if available
        if visual_doc_url:
            if isinstance(visual_doc_url, dict) and 'absolute_url' in visual_doc_url:
                visual_section = (
                    f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url['absolute_url']}\n"
                    "Use the images in the document to infer layout, field positions, and user flow.\n\n"
                )
                app.logger.info(f"Using absolute URL for document: {visual_doc_url['absolute_url']}")
            elif isinstance(visual_doc_url, dict) and 'url' in visual_doc_url:
                visual_section = (
                    f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url['url']}\n"
                    "Use the images in the document to infer layout, field positions, and user flow.\n\n"
                )
                app.logger.info(f"Using relative URL for document: {visual_doc_url['url']}")
            else:
                visual_section = (
                    f"Refer to the attached document containing UI screenshots or design walkthroughs:\n{visual_doc_url}\n"
                    "Use the images in the document to infer layout, field positions, and user flow.\n\n"
                )
                app.logger.info(f"Using provided URL for document: {visual_doc_url}")
                
        # Add all image URLs to the visual section
        if all_image_urls:
            visual_section += (
                "Refer to the following UI image(s) that show screen layout, component states, and user flow:\n" +
                "\n".join(all_image_urls) + "\n"
                "Use these visuals to derive field visibility, workflows, and validation points.\n\n"
            )
            app.logger.info(f"Added {len(all_image_urls)} image URLs to prompt")

        # --- CHUNKED CONTEXT LOGIC ---
        if context_name and context_text and len(context_text) > 15000:
            chunk_size = 15000
            overlap = 1000
            all_testcases = []
            context_chunks = list(chunk_text(context_text, chunk_size, overlap))
            for idx, chunk in enumerate(context_chunks):
                chunk_prompt = (
    f"Context chunk {idx+1} of {len(context_chunks)}:\n"
    f"{chunk}\n\n"
    f"{visual_section if visual_section else ''}"
    "You are a **Senior QA Engineer** responsible for ensuring deep functional coverage across API, UI, and data workflows.\n\n"
    
    "Your task is to generate a **thorough and exhaustive list of manual test scenarios** based on the following functionality.\n"
    "Design tests that validate functionality from every angle — core workflows, edge behaviors, data conditions, and integrations.\n"
    
    "Each test case must be formatted as a **JSON object** with the following keys ONLY:\n"
    "- 'step': Describes the exact user/system action or precondition\n"
    "- 'expected': Describes the precise, observable, verifiable outcome\n"
    "- 'estimate_minutes': A realistic duration to execute, including setup, execution, validation, and evidence collection\n\n"

    "Allowed values for 'estimate_minutes' are: **5, 10, 15, 20, 30, 45, or 60** — based on the depth and complexity of the scenario. Choose wisely:\n"
    "- 5 mins → Atomic checks (simple UI visibility, tooltip, toggle states)\n"
    "- 10 mins → One-step validations (basic API, single-form validation)\n"
    "- 15 mins → Medium-complex UI/API workflows (validation + feedback + transition)\n"
    "- 20 mins → State-dependent logic or cross-condition checks\n"
    "- 30 mins → Composite flows (multi-role or chained interaction across components)\n"
    "- 45 mins → Partial end-to-end journeys or integration with environment dependency\n"
    "- 60 mins → Full-scale integration flows involving multiple modules or roles\n\n"

    "You are expected to generate **30–50 well-formed test cases**, ensuring coverage in the following categories:\n\n"
    
    "🔹 **API-Level Scenarios** (if applicable):\n"
    "- Valid/invalid payloads\n"
    "- Required vs optional fields\n"
    "- Status codes (200, 400, 403, 404, 500, etc.)\n"
    "- Header behavior and auth dependencies\n"
    "- Data returned, field types, nullability, pagination, and contract schema\n\n"

    "🔹 **UI and UX Scenarios** (if applicable):\n"
    "- Element visibility, state changes (enabled/disabled)\n"
    "- Input validation, field behavior, UI error/success messages\n"
    "- Modal handling, transitions, scroll behavior, tab flow\n"
    "- Accessibility implications (if implied)\n"

    "🔹 **Data-Intensive Scenarios**:\n"
    "- Input limits, boundary value tests, malformed values\n"
    "- Data lifecycle (create, update, delete, restore)\n"
    "- Pre-existing data states, data merging/overwrites\n"
    "- Audit trails or log validation (if applicable)\n"

    "🔹 **Negative, Role-Based, and Integration Scenarios**:\n"
    "- Unauthorized actions, permission-denied responses\n"
    "- Multi-role workflows (if scenario suggests)\n"
    "- Cross-module dependencies or configuration-driven behaviors\n"
    "- Conditional rendering, auto-calculated values, time-based rules\n\n"

    "⚠️ **Constraints:**\n"
    "- DO NOT assume anything outside the described scope (e.g., login, navigation, unrelated features)\n"
    "- DO NOT add extra keys, markdown, explanation, comments, or grouping in the output\n"
    "- DO NOT summarize — only return test cases\n\n"

    "✅ **Your final output must be a single JSON array** like this:\n"
    "[\n"
    "  {'step': '...', 'expected': '...', 'estimate_minutes': 10},\n"
    "  {'step': '...', 'expected': '...', 'estimate_minutes': 30},\n"
    "  ...\n"
    "]\n\n"

    f"Scenario:\n{scenario}\n\n"
    "Test Cases:"
)

                try:
                    api_key = os.environ.get("GOOGLE_API_KEY")
                    if not api_key:
                        logging.error("GOOGLE_API_KEY is not set in environment variables.")
                        continue
                    genai.configure(api_key=api_key)

                    model_name = os.environ.get('GOOGLE_API_MODEL')
                    if not model_name:
                        logging.error("GOOGLE_API_MODEL is not set in environment variables.")
                        continue
                    model = genai.GenerativeModel(model_name)
                    response = model.generate_content(chunk_prompt)
                    content = response.text
                    match = re.search(r'(\[.*\])', content, re.DOTALL)
                    if match:
                        try:
                            testcases = json.loads(match.group(1))
                            all_testcases.extend(testcases)
                        except Exception as e:
                            continue  # skip this chunk if JSON is invalid
                except Exception as e:
                    continue  # skip this chunk if LLM call fails

            # Deduplicate test cases
            unique_testcases = []
            seen = set()
            for tc in all_testcases:
                key = (tc.get('step'), tc.get('expected'))
                if key not in seen:
                    unique_testcases.append(tc)
                    seen.add(key)
            total_estimated_time = sum(tc.get('estimate_minutes', 0) for tc in unique_testcases if isinstance(tc, dict))
            return jsonify({'testcases': unique_testcases, 'total_estimated_time': total_estimated_time})

        # --- ORIGINAL LOGIC FOR SMALL CONTEXT OR NO CONTEXT ---
        prompt = (
    (context_text + "\n\n" if context_text else "") +
    (visual_section if visual_section else "") +
    "You are a senior QA engineer with deep expertise in functional, UI, API, and data validation testing. "
    "Your task is to create a **comprehensive, well-categorized, and exhaustive set of manual test scenarios** for the following functionality.\n\n"

    "Each test case must be a **JSON object** with these exact keys:\n"
    "- 'step': The specific user/system action or starting condition\n"
    "- 'expected': The precise, verifiable, and observable system behavior\n"
    "- 'estimate_minutes': A realistic execution time that includes setup, action, validation, and documentation\n\n"

    "Allowed values for 'estimate_minutes': **5, 10, 15, 20, 30, 45, 60**\n"
    "Use the following guidelines for estimates:\n"
    "- 5 mins → Basic UI checks (e.g., visibility, button states, tooltips)\n"
    "- 10 mins → Single interaction or API hit with straightforward validation\n"
    "- 15 mins → Multi-step flows or validations with intermediate logic\n"
    "- 20 mins → Tests involving multiple dependencies or permission-based conditions\n"
    "- 30 mins → Full user workflows or partial integration checks\n"
    "- 45–60 mins → End-to-end journeys with environment/data setup, multi-role interaction, or cross-module validation\n\n"

    "Ensure your test cases **thoroughly cover the following dimensions**:\n"
    "- Core happy path workflows and expected flows\n"
    "- Edge and boundary conditions (length, values, state switches)\n"
    "- Negative test cases (invalid inputs, forbidden actions, missing dependencies)\n"
    "- Input/output data validation and transformation\n"
    "- API responses, contract structure, and error handling (if applicable)\n"
    "- UI/UX behaviors (feedback messages, element state, dynamic rendering)\n"
    "- Role-based or conditional behaviors (if implied)\n"
    "- Cross-module or integrated system logic (only if within scenario scope)\n\n"

    "⚠️ Do **NOT** assume anything beyond the described functionality (e.g., login, unrelated features, system-wide settings).\n"
    "⚠️ Your output must be a **single JSON array**. Each object must follow this format exactly:\n"
    "{'step': '...', 'expected': '...', 'estimate_minutes': 15}\n"
    "⚠️ Do **NOT** include headings, explanations, markdown, groupings, or extra fields.\n\n"

    f"Scenario:\n{scenario}\n\n"
    "Test Cases:"
)


        prompt = prompt[:20000]  # Truncate prompt if too long

        try:
            api_key = os.environ.get("GOOGLE_API_KEY")
            if not api_key:
                logging.error("GOOGLE_API_KEY is not set in environment variables.")
                return jsonify({'error': 'GOOGLE_API_KEY is not set'}), 500
            genai.configure(api_key=api_key)

            model_name = os.environ.get('GOOGLE_API_MODEL')
            if not model_name:
                logging.error("GOOGLE_API_MODEL is not set in environment variables.")
                return jsonify({'error': 'GOOGLE_API_MODEL is not set'}), 500
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            content = response.text
            logging.info(f"Model output: {content}")
            match = re.search(r'(\[.*\])', content, re.DOTALL)
            logging.info(f"Regex matched: {match.group(1)[:500]}" if match else "No match found in model output.")
            if match:
                try:
                    testcases = json.loads(match.group(1))
                    total_estimated_time = sum(tc.get('estimate_minutes', 0) for tc in testcases if isinstance(tc, dict))
                    return jsonify({'testcases': testcases, 'total_estimated_time': total_estimated_time})
                except Exception as e:
                    return jsonify({'error': 'Gemini returned invalid JSON', 'raw': content}), 500
            return jsonify({'error': 'Gemini did not return a JSON array', 'raw': content}), 500

        except Exception as e:
            import traceback
            logging.error(f'Error generating test cases: {str(e)}\n{traceback.format_exc()}')
            return jsonify({'error': f'Error generating test cases: {str(e)}'}), 500

    except Exception as e:
        import traceback
        logging.error(f'Internal server error: {str(e)}\n{traceback.format_exc()}')
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500

@app.route('/e2e-co-test')
def e2e_co_test():
    return render_template('e2e-co-test.html', active_tab='e2e')

@app.route('/api/fetch-html')
def fetch_html():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'Missing URL'}), 400
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        return jsonify({'html': resp.text})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

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
            "scope": "read:jira-work write:jira-work read:me",
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
    # Check if user denied access
    error = request.args.get("error")
    if error == "access_denied":
        # User cancelled the authorization, redirect to dashboard
        return redirect(url_for('index'))
    
    code = request.args.get("code")
    if not code:
        # No code and no error, redirect to dashboard with error message
        return redirect(url_for('index'))
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
        return f"Token exchange failed: {resp.text}", 400
    tokens = resp.json()
    
    # Store both access and refresh tokens
    session['jira_access_token'] = tokens['access_token']
    session['jira_refresh_token'] = tokens.get('refresh_token')
    session['jira_token_expires'] = time.time() + tokens.get('expires_in', 3600)
    
    # Get accessible Jira resources and find the correct one
    headers = {
        'Authorization': f"Bearer {tokens['access_token']}",
        'Accept': 'application/json'
    }
    cloud_id_resp = requests.get(
        'https://api.atlassian.com/oauth/token/accessible-resources',
        headers=headers
    )
    if cloud_id_resp.status_code == 200:
        cloud_id_data = cloud_id_resp.json()
        logger.info(f"Available Jira resources: {cloud_id_data}")
        
        if cloud_id_data and isinstance(cloud_id_data, list) and len(cloud_id_data) > 0:
            # Look for upgrad-jira.atlassian.net specifically
            target_resource = None
            for resource in cloud_id_data:
                resource_url = resource.get('url', '')
                if 'upgrad-jira.atlassian.net' in resource_url:
                    target_resource = resource
                    break
            
            # If we found the target, use it; otherwise use the first one
            if target_resource:
                session['jira_cloud_id'] = target_resource['id']
                session['jira_domain'] = target_resource['url']
                logger.info(f"Found target Jira resource: {target_resource['url']}")
            else:
                # Fallback to first available resource
                session['jira_cloud_id'] = cloud_id_data[0]['id']
                session['jira_domain'] = cloud_id_data[0]['url']
                logger.info(f"Using first available Jira resource: {cloud_id_data[0]['url']}")
            
            logger.info(f"Stored Jira cloud ID: {session['jira_cloud_id']}")
            logger.info(f"Using Jira domain: {session['jira_domain']}")
    else:
        # Fallback to default domain if API call fails
        session['jira_domain'] = 'https://upgrad-jira.atlassian.net'
        logger.warning(f"Failed to get accessible resources, using default domain")
    
    # Fetch user information
    try:
        logger.info("Attempting to fetch user info from Atlassian API...")
        user_info_resp = requests.get(
            'https://api.atlassian.com/me',
            headers=headers,
            timeout=10
        )
        logger.info(f"User info response status: {user_info_resp.status_code}")
        logger.info(f"User info response headers: {dict(user_info_resp.headers)}")
        
        if user_info_resp.status_code == 200:
            user_data = user_info_resp.json()
            logger.info(f"Raw user data from Atlassian: {user_data}")
            
            # Try different field names that Atlassian might use
            user_name = (user_data.get('name') or 
                        user_data.get('displayName') or 
                        user_data.get('display_name') or 
                        user_data.get('nickname') or 
                        user_data.get('account_id') or  # Sometimes Atlassian uses account_id
                        'User')
            
            user_email = (user_data.get('email') or 
                         user_data.get('emailAddress') or 
                         user_data.get('email_address') or 
                         '')
            
            user_avatar = (user_data.get('picture') or 
                          user_data.get('avatar') or 
                          user_data.get('avatarUrl') or 
                          user_data.get('avatar_url') or 
                          user_data.get('avatarUrls', {}).get('48x48') or  # Atlassian format
                          '')
            
            session['jira_user_name'] = user_name
            session['jira_user_email'] = user_email
            session['jira_user_avatar'] = user_avatar
            session['jira_login_time'] = time.time()
            session['show_welcome_message'] = True
            logger.info(f"Successfully stored user info: {user_name} ({user_email})")
        else:
            logger.error(f"Failed to fetch user info. Status: {user_info_resp.status_code}, Response: {user_info_resp.text}")
            # Store default values so the profile still shows
            session['jira_user_name'] = 'Jira User'
            session['jira_user_email'] = 'Connected to Jira'
            session['jira_user_avatar'] = ''
            session['jira_login_time'] = time.time()
            session['show_welcome_message'] = True
    except Exception as e:
        logger.error(f"Exception while fetching user info: {str(e)}")
        # Store default values so the profile still shows
        session['jira_user_name'] = 'Jira User'
        session['jira_user_email'] = 'Connected to Jira'
        session['jira_user_avatar'] = ''
        session['jira_login_time'] = time.time()
        session['show_welcome_message'] = True
    
    return redirect(url_for('index'))

def refresh_jira_token():
    """Refresh the Jira access token using the refresh token."""
    refresh_token = session.get('jira_refresh_token')
    if not refresh_token:
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

    # Check if token needs refresh
    token_expires = session.get('jira_token_expires', 0)
    if time.time() >= token_expires:
        if not refresh_jira_token():
            return jsonify({'error': 'Token expired. Please reconnect to Jira.'}), 401
        access_token = session['jira_access_token']

    try:
        # Get query parameters
        project = request.args.get('project')
        status = request.args.get('status')
        search = request.args.get('search')
        max_results = request.args.get('maxResults', '50')

        # Build JQL query
        jql_parts = []
        
        # Handle specific issue key search (e.g., "IRA-62215")
        if search and '-' in search:
            # If search looks like an issue key (contains a hyphen), search by key
            jql_parts.append(f'key = "{search}"')
        else:
            # For My Details page, default to showing user's assigned issues
            user_email = session.get('jira_user_email')
            if user_email and not search and not project and not status:
                jql_parts.append(f'assignee = "{user_email}"')
                
            # Otherwise use the regular search parameters
            if project:
                jql_parts.append(f'project = "{project}"')
            if status:
                jql_parts.append(f'status = "{status}"')
            if search:
                jql_parts.append(f'text ~ "{search}"')
        
        # Add ordering and default fallback
        if jql_parts:
            jql = ' AND '.join(jql_parts) + ' ORDER BY updated DESC'
        else:
            # Fallback for My Details: show recent issues for the user
            user_email = session.get('jira_user_email')
            if user_email:
                jql = f'assignee = "{user_email}" ORDER BY updated DESC'
            else:
                jql = 'assignee = currentUser() ORDER BY updated DESC'
        logger.info(f"Generated JQL query: {jql}")

        # Make request to Jira API
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }

        # Now fetch issues using stored cloud ID
        issues_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search'
        params = {
            'jql': jql,
            'maxResults': max_results,
            'fields': 'summary,description,status,assignee,created,updated',
            'expand': 'renderedFields'
        }
        
        logger.info(f"Fetching issues from: {issues_url}")
        logger.info(f"With params: {params}")
        logger.info(f"Using headers: {headers}")
        
        # Add timeout and verify SSL
        response = requests.get(
            issues_url, 
            headers=headers, 
            params=params,
            timeout=30,
            verify=True
        )
        
        # Log the response for debugging
        logger.info(f"Issues Response Status: {response.status_code}")
        logger.info(f"Issues Response Headers: {dict(response.headers)}")
        logger.info(f"Issues Response Body: {response.text[:1000]}")  # Log first 1000 chars
        
        # Check if response is HTML instead of JSON
        content_type = response.headers.get('content-type', '').lower()
        if 'text/html' in content_type:
            logger.error(f"Received HTML instead of JSON. Response: {response.text[:1000]}")
            # Try to refresh token and retry once
            if refresh_jira_token():
                # Retry the request with new token
                headers['Authorization'] = f'Bearer {session["jira_access_token"]}'
                response = requests.get(
                    issues_url, 
                    headers=headers, 
                    params=params,
                    timeout=30,
                    verify=True
                )
                content_type = response.headers.get('content-type', '').lower()
                if 'text/html' in content_type:
                    return jsonify({
                        'error': 'Authentication failed even after token refresh. Please reconnect to Jira.',
                        'status_code': response.status_code,
                        'content_type': content_type,
                        'response': response.text[:1000]
                    }), 401
            
            return jsonify({
                'error': 'Received HTML response instead of JSON. Token may be invalid or expired.',
                'status_code': response.status_code,
                'content_type': content_type,
                'response': response.text[:1000]
            }), 401
        
        if response.status_code != 200:
            return jsonify({
                'error': 'Failed to fetch Jira issues',
                'status_code': response.status_code,
                'response': response.text[:1000]  # Limit response size
            }), response.status_code

        try:
            data = response.json()
        except Exception as e:
            logger.error(f"Error parsing issues response: {str(e)}")
            return jsonify({
                'error': 'Invalid JSON response from Jira API',
                'details': str(e),
                'response': response.text[:1000]  # Limit response size
            }), 500

        # Process and format the response
        issues = []
        
        for issue in data.get('issues', []):
            fields = issue.get('fields') or {}
            rendered = fields.get('renderedFields') or issue.get('renderedFields') or {}
            issue_key = issue.get('key')
            description = fields.get('description')
            description_html = ''
            # Prefer rendered HTML if available
            if rendered and rendered.get('description'):
                description_html = rendered['description']
                # --- Rewrite Jira attachment image URLs (classic and blob) ---
                # Classic attachment: /rest/api/3/attachment/content/145995
                description_html = re.sub(
                    r'<img([^>]+)src=["\"]/rest/api/3/attachment/content/(\d+)["\"]',
                    r'<img\1src="/api/jira/attachment?id=\2"',
                    description_html
                )
                # Media Service blob: blob:https://...id=UUID...&collection=COLLECTION
                def blob_rewrite(match):
                    attrs = match.group(1)
                    blob_url = match.group(2)
                    m = re.search(r'id=([a-f0-9\-]+)', blob_url)
                    id = m.group(1) if m else ''
                    m2 = re.search(r'collection=([a-zA-Z0-9\-_]*)', blob_url)
                    collection = m2.group(1) if m2 else 'jira-issue'
                    return f'<img{attrs}src="/api/jira/attachment?id={id}&collection={collection}"'
                description_html = re.sub(
                    r'<img([^>]+)src=["\"]blob:[^"\"]*id=([a-f0-9\-]+)[^"\"]*collection=([a-zA-Z0-9\-_]*)["\"]',
                    blob_rewrite,
                    description_html
                )
            elif isinstance(description, dict) and description.get('type') == 'doc':
                description_html = adf_to_html(description)
            elif isinstance(description, str):
                description_html = f'<p>{description}</p>'
            else:
                description_html = ''
            issues.append({
                'key': issue_key,
                'summary': fields.get('summary') or '',
                'description': description or '',
                'description_html': description_html,
                'status': (fields.get('status') or {}).get('name'),
                'assignee': (fields.get('assignee') or {}).get('displayName'),
                'created': fields.get('created'),
                'updated': fields.get('updated'),
                'url': f"{domain}/browse/{issue_key}" if issue_key else None
            })

        return jsonify({
            'issues': issues,
            'total': data.get('total', 0),
            'jira_domain': session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        })

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while fetching Jira issues: {str(e)}")
        return jsonify({
            'error': 'Network error while connecting to Jira',
            'details': str(e)
        }), 500
    except Exception as e:
        logger.error(f"Error fetching Jira issues: {str(e)}")
        return jsonify({
            'error': 'Failed to fetch Jira issues',
            'details': str(e)
        }), 500

@app.route('/data-generator')
@jira_auth_required
def data_generator():
    return render_template('data-generation.html')

# Keep old route for backward compatibility
@app.route('/data')
@jira_auth_required
def data():
    return redirect('/data-generator', code=301)

# Jira API endpoints

@app.route('/api/jira/issues')
def jira_issues():
    """Fetch Jira issues for the authenticated user"""
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira'}), 401
    
    # Get query parameters
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    project_filter = request.args.get('project', '')
    
    # Get Jira cloud ID from session
    cloud_id = session.get('jira_cloud_id')
    if not cloud_id:
        return jsonify({'error': 'Jira cloud ID not found in session'}), 400
    
    # Construct JQL query
    jql_parts = []
    if project_filter:
        jql_parts.append(f"project = '{project_filter}'")
    if status_filter:
        jql_parts.append(f"status = '{status_filter}'")
    if search_query:
        jql_parts.append(f"summary ~ '{search_query}*' OR description ~ '{search_query}*'")
    
    # Add assignee filter to show only the user's issues if no specific filters
    if not jql_parts:
        jql_parts.append("assignee = currentUser() OR reporter = currentUser()")
    
    jql_query = " AND ".join(jql_parts)
    
    # Prepare API request
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json',
        'Content-Type': 'application/json'
    }
    
    # API endpoint for searching issues
    url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search"
    
    try:
        # Make the API request
        response = requests.post(
            url,
            headers=headers,
            json={
                'jql': jql_query,
                'maxResults': 50,
                'fields': [
                    'summary',
                    'description',
                    'status',
                    'assignee',
                    'reporter',
                    'created',
                    'updated',
                    'priority',
                    'issuetype',
                    'project'
                ]
            }
        )
        
        # Check for errors
        if response.status_code != 200:
            return jsonify({
                'error': 'Failed to fetch Jira issues',
                'details': response.text
            }), response.status_code
        
        # Process the response
        data = response.json()
        issues = []
        
        for issue in data.get('issues', []):
            # Extract issue fields
            fields = issue.get('fields', {})
            
            # Process description to handle attachments
            description = ''
            if fields.get('description'):
                # Handle different description formats
                if isinstance(fields['description'], dict) and 'content' in fields['description']:
                    # Process Atlassian Document Format
                    description_content = fields['description'].get('content', [])
                    for content in description_content:
                        if content.get('type') == 'paragraph' and 'content' in content:
                            for text_content in content.get('content', []):
                                if text_content.get('type') == 'text':
                                    description += text_content.get('text', '')
                            description += '\n'
                else:
                    # Handle plain text description
                    description = str(fields.get('description', ''))
            
            # Get assignee information
            assignee = None
            if fields.get('assignee'):
                assignee = {
                    'name': fields['assignee'].get('displayName', 'Unassigned'),
                    'email': fields['assignee'].get('emailAddress', ''),
                    'avatar': fields['assignee'].get('avatarUrls', {}).get('48x48', '')
                }
            
            # Get status information
            status = None
            if fields.get('status'):
                status = fields['status'].get('name', 'Unknown')
            
            # Format created and updated dates
            created = fields.get('created')
            updated = fields.get('updated')
            
            # Build issue URL
            domain = session.get('jira_domain', '')
            issue_url = f"https://{domain}/browse/{issue.get('key')}" if domain else ''
            
            # Add processed issue to the list
            issues.append({
                'key': issue.get('key', ''),
                'summary': fields.get('summary', ''),
                'description': description,
                'status': status,
                'assignee': assignee,
                'created': created,
                'updated': updated,
                'url': issue_url
            })
        
        # Return the processed issues
        return jsonify({
            'issues': issues,
            'total': data.get('total', 0),
            'jira_domain': session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
        })
    
    except Exception as e:
        return jsonify({
            'error': 'Failed to fetch Jira issues',
            'details': str(e)
        }), 500

@app.route('/api/jira/time-entries', methods=['GET'])
def get_jira_time_entries():
    """Get time entries for Jira issues for a specific date"""
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira'}), 401
    
    # Get Jira cloud ID from session
    cloud_id = session.get('jira_cloud_id')
    if not cloud_id:
        return jsonify({'error': 'Jira cloud ID not found in session'}), 400
    
    # Get date filter from query parameters
    date_filter = request.args.get('date', '')
    
    # Prepare API request
    headers = {
        'Authorization': f'Bearer {access_token}',
        'Accept': 'application/json'
    }
    
    try:
        # Get the current user's account ID for filtering
        user_email = session.get('jira_user_email')
        if not user_email:
            return jsonify({'error': 'User email not found in session'}), 400
        
        # First, get the user's account ID
        user_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/user/search?query={user_email}'
        logger.info(f"Searching for user with URL: {user_url}")
        user_response = requests.get(user_url, headers=headers, timeout=30)
        
        logger.info(f"User search response status: {user_response.status_code}")
        if user_response.status_code != 200:
            logger.error(f"User search failed: {user_response.text}")
            return jsonify({
                'timeEntries': [],
                'total': 0,
                'date': date_filter,
                'error': f'Failed to get user information from Jira (status: {user_response.status_code})',
                'debug_info': {
                    'user_url': user_url,
                    'response_text': user_response.text[:500],  # First 500 chars
                    'user_email': user_email,
                    'cloud_id': cloud_id
                }
            }), 200
            
        user_data = user_response.json()
        logger.info(f"User search returned {len(user_data) if user_data else 0} users")
        
        if not user_data:
            return jsonify({
                'timeEntries': [],
                'total': 0,
                'date': date_filter,
                'error': 'User not found in Jira',
                'debug_info': {
                    'user_email': user_email,
                    'search_response': user_data
                }
            }), 200
            
        user_account_id = user_data[0]['accountId']
        logger.info(f"Found user account ID: {user_account_id}")
        
        # Build JQL to find issues with worklogs by the current user
        if date_filter:
            # Search for issues with worklogs by this user on the specified date
            worklog_jql = f'worklogAuthor = "{user_account_id}" AND worklogDate = "{date_filter}"'
        else:
            # Get recent worklogs by this user
            worklog_jql = f'worklogAuthor = "{user_account_id}"'
        
        # Search for issues with worklogs
        search_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/search'
        search_params = {
            'jql': worklog_jql,
            'fields': 'summary,worklog',
            'expand': 'worklog',
            'maxResults': 100
        }
        
        search_response = requests.get(search_url, headers=headers, params=search_params, timeout=30)
        
        if search_response.status_code != 200:
            return jsonify({'error': 'Failed to search for issues with worklogs'}), 500
        
        search_data = search_response.json()
        all_time_entries = []
        
        # Process each issue and extract relevant worklogs
        for issue in search_data.get('issues', []):
            issue_key = issue['key']
            issue_summary = issue['fields']['summary']
            
            # Get worklogs for this issue
            worklog_data = issue['fields'].get('worklog', {})
            worklogs = worklog_data.get('worklogs', [])
            
            # Filter worklogs by author and date if specified
            for worklog in worklogs:
                worklog_author_id = worklog.get('author', {}).get('accountId', '')
                worklog_started = worklog.get('started', '')
                
                # Only include worklogs by the current user
                if worklog_author_id == user_account_id:
                    # If date filter is specified, check if worklog is on that date
                    if date_filter:
                        worklog_date = worklog_started.split('T')[0] if 'T' in worklog_started else worklog_started
                        if worklog_date != date_filter:
                            continue
                    
                    time_spent_seconds = worklog.get('timeSpentSeconds', 0)
                    hours = time_spent_seconds // 3600
                    minutes = (time_spent_seconds % 3600) // 60
                    time_spent_display = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
                    
                    all_time_entries.append({
                        'id': worklog.get('id', ''),
                        'issueKey': issue_key,
                        'issueSummary': issue_summary,
                        'timeSpent': time_spent_display,
                        'timeSpentSeconds': time_spent_seconds,
                        'comment': worklog.get('comment', ''),
                        'started': worklog_started,
                        'author': worklog.get('author', {}).get('displayName', session.get('jira_user_name', 'User'))
                    })
    
    except Exception as e:
        logger.error(f"Error fetching time entries: {str(e)}")
        # Return error details for debugging but don't crash
        return jsonify({
            'timeEntries': [],
            'total': 0,
            'date': date_filter,
            'error': f"Failed to fetch time entries: {str(e)}",
            'debug_info': {
                'has_access_token': bool(access_token),
                'has_cloud_id': bool(cloud_id),
                'user_email': session.get('jira_user_email', 'N/A')
            }
        }), 200  # Return 200 instead of 500 to prevent frontend errors
    
    # Sort time entries by date (most recent first)
    all_time_entries.sort(key=lambda x: x.get('started', ''), reverse=True)
    
    return jsonify({
        'timeEntries': all_time_entries,
        'total': len(all_time_entries),
        'date': date_filter
    })

@app.route('/api/jira/time-entries', methods=['POST'])
def add_jira_time_entry():
    """Add a new time entry for a Jira issue"""
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira'}), 401
    
    # Get Jira cloud ID from session
    cloud_id = session.get('jira_cloud_id')
    if not cloud_id:
        return jsonify({'error': 'Jira cloud ID not found in session'}), 400
    
    # Get request data
    data = request.json
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    # Validate required fields
    required_fields = ['issueKey', 'timeSpent', 'started']
    for field in required_fields:
        if field not in data:
            return jsonify({'error': f'Missing required field: {field}'}), 400
    
    # In a real implementation, you would make an API call to Jira
    # to add the worklog entry. For this demo, we'll simulate success.
    
    # Return success response
    return jsonify({
        'success': True,
        'message': 'Time entry added successfully',
        'timeEntry': {
            'id': '123', # This would be returned by the Jira API
            'issueKey': data['issueKey'],
            'timeSpent': data['timeSpent'],
            'started': data['started'],
            'comment': data.get('comment', ''),
            'author': session.get('jira_user_name', 'User')
        }
    })

@app.route('/my-details')
@jira_auth_required
def my_details():
    """My Details page - shows user profile, Jira issues, and worklog activity"""
    return render_template('my-jira.html', active_tab='jira')

# Keep old route for backward compatibility
@app.route('/my-jira')
@jira_auth_required
def my_jira():
    return redirect('/my-details', code=301)

def extract_issues_manually(text):
    """
    Extract issues and recommendations from raw AI response text when JSON parsing fails.
    Uses regex patterns to find issues and recommendations in the text.
    """
    logger.info("Attempting to extract issues manually from text")
    
    result = {
        'issues': [],
        'recommendations': [],
        'overallScore': 70,  # Default moderate score for manual extraction
        'factorScores': {
            'accessibility': 70,
            'designConsistency': 70,
            'usability': 70,
            'visualHierarchy': 70,
            'responsiveness': 70
        },
        'summary': 'UI analysis completed using manual text extraction due to parsing issues.'
    }
    
    # Extract issues
    issue_patterns = [
        r'(?:Issue|Problem|Concern)\s*\d*\s*:\s*([^\n.]+)',  # Issue: Text
        r'"title"\s*:\s*"([^"]+)"',  # "title": "Text"
        r'\*\*([^*]+)\*\*',  # **Text** (markdown bold)
        r'- ([A-Z][^\n.]+)'  # - Capitalized text
    ]
    
    for pattern in issue_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            logger.info(f"Found {len(matches)} issues using pattern: {pattern}")
            for i, match in enumerate(matches):
                issue_title = match.group(1).strip()
                # Skip if it looks like a recommendation
                if any(rec_word in issue_title.lower() for rec_word in ['recommend', 'suggestion', 'improve', 'enhance']):
                    continue
                    
                # Create a structured issue
                severity = 'Medium'  # Default severity
                # Try to detect severity
                if any(high_word in text[max(0, match.start()-50):match.start()+len(match.group(0))+50].lower() 
                       for high_word in ['critical', 'high', 'severe', 'major']):
                    severity = 'High'
                elif any(low_word in text[max(0, match.start()-50):match.start()+len(match.group(0))+50].lower() 
                         for low_word in ['minor', 'low', 'small', 'slight']):
                    severity = 'Low'
                
                result['issues'].append({
                    'title': issue_title,
                    'severity': severity,
                    'description': issue_title,  # Use title as description if no specific description found
                    'location': 'UI Element'  # Default location
                })
                
                # Limit to 5 issues to avoid noise
                if len(result['issues']) >= 5:
                    break
            
            if result['issues']:
                break  # Stop after finding issues with one pattern
    
    # Extract recommendations
    rec_patterns = [
        r'(?:Recommendation|Suggestion)\s*\d*\s*:\s*([^\n.]+)',  # Recommendation: Text
        r'- ([Rr]ecommend[^\n.]+)',  # - Recommend...
        r'"recommendation"\s*:\s*"([^"]+)"'  # "recommendation": "Text"
    ]
    
    for pattern in rec_patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            logger.info(f"Found {len(matches)} recommendations using pattern: {pattern}")
            for match in matches:
                result['recommendations'].append(match.group(1).strip())
            break  # Stop after finding recommendations with one pattern
    
    return result

def find_potential_misspellings(text):
    """
    Analyze OCR text to find potential misspellings or unusual words.
    Returns a list of potentially misspelled words.
    """
    if not text or text == "OCR text extraction not available (Tesseract not installed)":
        return []
        
    # Split text into words
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text)
    
    # Common UI words that might be flagged incorrectly
    common_ui_words = {
        'login', 'signup', 'navbar', 'dropdown', 'checkbox', 'tooltip', 'popup',
        'modal', 'sidebar', 'footer', 'header', 'button', 'submit', 'cancel',
        'username', 'password', 'email', 'admin', 'dashboard', 'logout', 'profile',
        'settings', 'notification', 'menu', 'toggle', 'slider', 'checkbox',
        'radio', 'input', 'form', 'label', 'placeholder', 'textarea', 'select',
        'option', 'datepicker', 'timepicker', 'calendar', 'pagination', 'breadcrumb',
        'accordion', 'tab', 'panel', 'dialog', 'alert', 'toast', 'badge', 'card',
        'carousel', 'spinner', 'loader', 'progress', 'avatar', 'icon', 'tooltip',
        'popover', 'navbar', 'toolbar', 'sidebar', 'offcanvas', 'collapse', 'dropdown'
    }
    
    # Simple heuristic: words with unusual character patterns
    potential_misspellings = []
    for word in words:
        word_lower = word.lower()
        
        # Skip common UI words
        if word_lower in common_ui_words:
            continue
            
        # Check for unusual character patterns
        if (len(word) >= 4 and 
            ('zx' in word_lower or 'qp' in word_lower or 'vf' in word_lower) or
            (word_lower.count('z') > 1) or
            (word_lower.count('q') > 1) or
            (word_lower.count('x') > 1)):
            potential_misspellings.append(word)
            
        # Check for repeated characters (more than 2)
        for i in range(len(word) - 2):
            if word[i] == word[i+1] == word[i+2]:
                potential_misspellings.append(word)
                break
    
    return potential_misspellings[:5]  # Limit to 5 potential issues

@app.route('/ui-analyzer')
@jira_auth_required
def ui_analyzer():
    return render_template('screen-analysis-redesigned.html', active_tab='screen-analysis')

# Keep old route for backward compatibility
@app.route('/screen-analysis')
@jira_auth_required
def screen_analysis():
    return redirect('/ui-analyzer', code=301)

@app.route('/api/rest/execute', methods=['POST'])
def execute_rest_request():
    """Execute a comprehensive REST API request with advanced features"""
    try:
        data = request.get_json()
        
        # Extract comprehensive request details
        url = data.get('url', '')
        method = data.get('method', 'GET').upper()
        headers = data.get('headers', {})
        params = data.get('params', {})
        body = data.get('body', '')
        body_type = data.get('bodyType', 'none')
        auth = data.get('auth', {})
        environment = data.get('environment', {})
        timeout = data.get('timeout', 30)
        follow_redirects = data.get('followRedirects', True)
        verify_ssl = data.get('verifySsl', True)
        
        # Apply environment variables
        url = substitute_environment_variables(url, environment)
        headers = {k: substitute_environment_variables(str(v), environment) for k, v in headers.items() if v}
        params = {k: substitute_environment_variables(str(v), environment) for k, v in params.items() if v}
        
        # Handle authentication
        auth_obj = None
        if auth.get('type') == 'basic':
            auth_obj = (auth.get('username', ''), auth.get('password', ''))
        elif auth.get('type') == 'bearer':
            headers['Authorization'] = f"Bearer {auth.get('token', '')}"
        elif auth.get('type') == 'api_key':
            if auth.get('in') == 'header':
                headers[auth.get('key', 'X-API-Key')] = auth.get('value', '')
            elif auth.get('in') == 'query':
                params[auth.get('key', 'api_key')] = auth.get('value', '')
        
        # Handle request body based on type
        request_kwargs = {}
        if body and body_type != 'none':
            if body_type == 'json':
                try:
                    request_kwargs['json'] = json.loads(body) if isinstance(body, str) else body
                    if 'Content-Type' not in headers:
                        headers['Content-Type'] = 'application/json'
                except json.JSONDecodeError:
                    return jsonify({'error': 'Invalid JSON in request body'}), 400
            elif body_type == 'text':
                request_kwargs['data'] = body
            elif body_type == 'form':
                try:
                    form_data = json.loads(body) if isinstance(body, str) else body
                    request_kwargs['data'] = form_data
                    if 'Content-Type' not in headers:
                        headers['Content-Type'] = 'application/x-www-form-urlencoded'
                except:
                    request_kwargs['data'] = body
            elif body_type == 'xml':
                request_kwargs['data'] = body
                if 'Content-Type' not in headers:
                    headers['Content-Type'] = 'application/xml'
        
        # Measure execution time
        start_time = time.time()
        
        # Make the request with comprehensive error handling
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                params=params,
                auth=auth_obj,
                timeout=timeout,
                allow_redirects=follow_redirects,
                verify=verify_ssl,
                **request_kwargs
            )
            
            execution_time = (time.time() - start_time) * 1000
            
            # Parse response body
            response_body = response.text
            content_type = response.headers.get('content-type', '').lower()
            
            try:
                if 'application/json' in content_type:
                    json_data = response.json()
                    # Return formatted JSON for better readability
                    response_body = json.dumps(json_data, indent=2)
                elif 'application/xml' in content_type or 'text/xml' in content_type:
                    # Keep as text for XML
                    pass
            except:
                pass
            
            # Extract cookies
            cookies = []
            for cookie in response.cookies:
                cookies.append({
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain,
                    'path': cookie.path,
                    'secure': cookie.secure,
                    'httpOnly': cookie.has_nonstandard_attr('HttpOnly')
                })
            
            # Response headers as list for better display
            response_headers = [{'key': k, 'value': v} for k, v in response.headers.items()]
            
            return jsonify({
                'success': True,
                'status': response.status_code,
                'statusText': response.reason,
                'headers': response_headers,
                'body': response_body,
                'cookies': cookies,
                'time': round(execution_time, 2),
                'size': len(response.content),
                'redirects': len(response.history) if hasattr(response, 'history') else 0,
                'finalUrl': response.url
            })
            
        except requests.exceptions.Timeout:
            return jsonify({
                'success': False,
                'error': 'Request timeout',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 408
        except requests.exceptions.ConnectionError as e:
            return jsonify({
                'success': False,
                'error': f'Connection error: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 503
        except requests.exceptions.SSLError as e:
            return jsonify({
                'success': False,
                'error': f'SSL verification failed: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 495
        except requests.exceptions.HTTPError as e:
            return jsonify({
                'success': False,
                'error': f'HTTP error: {str(e)}',
                'time': round((time.time() - start_time) * 1000, 2)
            }), 400
            
    except Exception as e:
        logger.error(f"Error executing REST request: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Internal server error: {str(e)}'
        }), 500

def substitute_environment_variables(text, environment):
    """Replace {{variable}} with environment values"""
    if not isinstance(text, str) or not environment:
        return text
    
    import re
    def replace_var(match):
        var_name = match.group(1)
        return environment.get(var_name, match.group(0))
    
    return re.sub(r'\{\{(\w+)\}\}', replace_var, text)

@app.route('/api/environment/validate', methods=['POST'])
def validate_environment():
    """Validate environment variables in a request"""
    try:
        data = request.get_json()
        url = data.get('url', '')
        headers = data.get('headers', {})
        body = data.get('body', '')
        environment = data.get('environment', {})
        
        # Find all variables
        import re
        variables_found = set()
        
        # Search in URL
        variables_found.update(re.findall(r'\{\{(\w+)\}\}', url))
        
        # Search in headers
        for value in headers.values():
            if isinstance(value, str):
                variables_found.update(re.findall(r'\{\{(\w+)\}\}', value))
        
        # Search in body
        if isinstance(body, str):
            variables_found.update(re.findall(r'\{\{(\w+)\}\}', body))
        
        # Check which variables are missing
        missing_variables = []
        available_variables = []
        
        for var in variables_found:
            if var in environment:
                available_variables.append(var)
            else:
                missing_variables.append(var)
        
        return jsonify({
            'variables': list(variables_found),
            'available': available_variables,
            'missing': missing_variables,
            'isValid': len(missing_variables) == 0
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/capture-url', methods=['POST'])
def capture_url():
    """Capture a screenshot of a website URL"""
    try:
        data = request.get_json()
        if not data or 'url' not in data:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
        
        url = data['url']
        
        # Auto-resolve URL if needed (add https:// if no protocol)
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Validate URL format
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            if not parsed.netloc:
                return jsonify({'success': False, 'error': 'Invalid URL format'}), 400
        except Exception:
            return jsonify({'success': False, 'error': 'Invalid URL format'}), 400
        
        # Import selenium for web scraping
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            import base64
            import time
        except ImportError:
            return jsonify({
                'success': False, 
                'error': 'Selenium not installed. Please install selenium and chromedriver for URL capture functionality.'
            }), 500
        
        # Setup Chrome options
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--disable-extensions')
        chrome_options.add_argument('--disable-plugins')
        chrome_options.add_argument('--disable-images')  # Speed up loading
        
        driver = None
        urls_to_try = [url]
        
        # If we're trying HTTPS, also prepare HTTP fallback
        if url.startswith('https://'):
            http_url = url.replace('https://', 'http://', 1)
            urls_to_try.append(http_url)
        
        last_error = None
        
        for attempt_url in urls_to_try:
            try:
                # Initialize Chrome driver
                driver = webdriver.Chrome(options=chrome_options)
                driver.set_page_load_timeout(30)  # 30 second timeout
                
                # Navigate to URL
                driver.get(attempt_url)
                
                # Wait for page to load
                time.sleep(3)
                
                # Take screenshot
                screenshot_base64 = driver.get_screenshot_as_base64()
                
                return jsonify({
                    'success': True,
                    'image': screenshot_base64,
                    'url': attempt_url
                })
                
            except Exception as e:
                last_error = e
                logging.warning(f"Failed to capture {attempt_url}: {str(e)}")
                
                if driver:
                    driver.quit()
                    driver = None
                
                # If this was HTTPS and we have HTTP to try, continue
                if attempt_url.startswith('https://') and len(urls_to_try) > 1:
                    continue
                else:
                    break
            
            finally:
                if driver:
                    driver.quit()
                    driver = None
        
        # If we get here, all attempts failed
        error_message = f'Failed to capture screenshot: {str(last_error)}'
        if len(urls_to_try) > 1:
            error_message += ' (tried both HTTPS and HTTP)'
            
        logging.error(f"Error capturing URL screenshot after all attempts: {error_message}")
        return jsonify({
            'success': False,
            'error': error_message
        }), 500
                
    except Exception as e:
        logging.error(f"URL capture error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analyze-screen', methods=['POST'])
@llm_rate_limit
def analyze_screen():
    # Handle both FormData (new frontend) and JSON (legacy)
    if request.content_type and 'multipart/form-data' in request.content_type:
        # New FormData approach
        screenshots = []
        figma_file = None
        options = {}
        
        # Get screenshots
        for key in request.files:
            if key.startswith('screenshot_'):
                screenshots.append(request.files[key])
            elif key == 'url_screenshot':
                screenshots.append(request.files[key])
        
        # Get URL source if available
        url_source = request.form.get('url_source', '')
        
        # Get figma file
        if 'figma_design' in request.files:
            figma_file = request.files['figma_design']
        
        # Get options
        if 'options' in request.form:
            try:
                options = json.loads(request.form['options'])
            except:
                options = {}
        
        if not screenshots:
            return jsonify({'error': 'No screenshot files provided'}), 400
        
        # Process first screenshot for now
        main_screenshot = screenshots[0]
        
        # Save screenshot to temporary file with proper handle management
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.close()  # Close the file handle immediately
        
        # Now save the screenshot to the closed temp file
        main_screenshot.save(temp_path)
    else:
        # Legacy JSON approach
        data = request.get_json()
        
        if not data or 'screenshot' not in data:
            return jsonify({'error': 'No screenshot data provided'}), 400
    
        # Extract image data from base64 string
        image_data = data['screenshot']
        if image_data.startswith('data:image'):
            # Remove the data URL prefix
            image_data = image_data.split(',')[1]
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        
        # Create a temporary file to save the image with proper handle management
        temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        temp_path = temp_file.name
        temp_file.write(image_bytes)
        temp_file.close()  # Close the file handle immediately
        # Extract options and figma data
        options = data.get('options', {})
        figma_design = data.get('figmaDesign', None)
        comparison_focus = data.get('comparisonFocus', {})
    
    try:
        # Handle figma file for FormData requests
        if request.content_type and 'multipart/form-data' in request.content_type and figma_file:
            # Process Figma file
            figma_design = {
                'type': 'image' if figma_file.content_type.startswith('image/') else 'text',
                'filename': figma_file.filename
            }
            
            if figma_design['type'] == 'image':
                # Save figma file temporarily and encode as base64 with proper handle management
                figma_temp = tempfile.NamedTemporaryFile(delete=False)
                figma_temp_path = figma_temp.name
                figma_temp.close()  # Close handle immediately
                
                try:
                    figma_file.save(figma_temp_path)
                    with open(figma_temp_path, 'rb') as f:
                        figma_base64 = base64.b64encode(f.read()).decode()
                    figma_design['data'] = f"data:{figma_file.content_type};base64,{figma_base64}"
                finally:
                    # Clean up immediately
                    if os.path.exists(figma_temp_path):
                        try:
                            os.unlink(figma_temp_path)
                        except Exception as cleanup_error:
                            logger.warning(f"Failed to cleanup Figma temp file: {cleanup_error}")
            else:
                # Read text/json content
                figma_content = figma_file.read().decode('utf-8')
                if figma_file.filename.endswith('.json'):
                    try:
                        figma_design['data'] = json.loads(figma_content)
                        figma_design['type'] = 'json'
                    except:
                        figma_design['data'] = figma_content
                        figma_design['type'] = 'text'
                else:
                    figma_design['data'] = figma_content
        
        # Extract Figma comparison options if present
        figma_compare = options.get('figma', False)  # Updated key name
        comparison_focus = options  # Use options directly for focus areas
        
        # Open image with PIL for analysis
        image = None
        try:
            image = Image.open(temp_path)
            
            # Try to extract text using OCR if Tesseract is available
            ocr_text = ""
            ocr_available = True
            try:
                ocr_text = pytesseract.image_to_string(image)
                logger.info("Successfully extracted text using OCR")
            except Exception as e:
                logger.warning(f"OCR extraction failed: {str(e)}. Continuing without OCR.")
                ocr_text = ""
                ocr_available = False
        except Exception as e:
            logger.error(f"Error opening image: {str(e)}")
            return jsonify({'error': 'Failed to process image'}), 500
        
            # Close the image to release file handle
            image.close()
            image = None
            
        except Exception as e:
            logger.error(f"Error opening image: {str(e)}")
            ocr_text = ""
            ocr_available = False
            if image:
                image.close()
        
        # Prepare image for AI analysis
        with open(temp_path, 'rb') as f:
            image_bytes = f.read()
        
        # Create prompt for AI analysis based on selected options
        prompt = "You are an expert UI/UX analyst specializing in identifying UI issues from screenshots. Analyze this UI screenshot and identify potential issues. BE CRITICAL, THOROUGH and SPECIFIC in your analysis. Even minor issues should be reported with clear explanations. "
        if options.get('alignment', True):
            prompt += "Check for alignment issues, uneven spacing, and layout problems. Look for elements that are not properly aligned or have inconsistent spacing. Identify specific misalignments with their exact locations. "
        if options.get('text', True):
            prompt += "Identify any text quality issues, spelling errors, typos, grammatical errors, or readability problems. Pay special attention to text that appears cut off, overlapping, or has poor contrast. Quote the problematic text when possible. "
        if options.get('contrast', True):
            prompt += "Evaluate color contrast and accessibility concerns. Check if text is readable against its background and if colors meet WCAG accessibility standards. Specify which elements have contrast issues and why they're problematic. "
        if options.get('consistency', True):
            prompt += "Look for UI inconsistencies in styling, fonts, or component usage. Check for mismatched styles, font sizes, or inconsistent UI elements. Point out specific inconsistencies between elements. "
        
        prompt += "\n\nIMPORTANT INSTRUCTIONS:\n"
        prompt += "1. You MUST identify at least one issue if anything in the UI could be improved, even slightly.\n"
        prompt += "2. Be specific about the location of each issue.\n"
        prompt += "3. Provide actionable recommendations for each issue.\n"
        prompt += "4. ALWAYS respond in valid JSON format.\n"
        prompt += "5. Do not say 'no issues found' unless the UI is absolutely perfect.\n\n"
        
        prompt += "Format your response STRICTLY as a JSON object with these properties: \n"
        prompt += "1. 'overallScore': Overall UI health score (0-100)\n"
        prompt += "2. 'factorScores': Object with scores for each factor: accessibility (0-100), designConsistency (0-100), usability (0-100), visualHierarchy (0-100), responsiveness (0-100)\n"
        prompt += "3. 'issues': Array of objects with {title, severity (High/Medium/Low), description, location, impact (0-10)}\n"
        prompt += "4. 'recommendations': Array of objects with {title, priority (High/Medium/Low), description, expectedImprovement (0-10)}\n"
        prompt += "5. 'summary': Brief summary of the overall assessment\n\n"
        prompt += "SCORING GUIDELINES:\n"
        prompt += "- Overall Score: 90-100 (Excellent), 80-89 (Good), 70-79 (Fair), 60-69 (Poor), <60 (Critical Issues)\n"
        prompt += "- Factor Scores: Rate each factor independently based on best practices\n"
        prompt += "- Impact: How much each issue affects user experience (1=minimal, 10=critical)\n"
        prompt += "- Expected Improvement: How much fixing the recommendation would improve the score\n\n"
        prompt += "Example response format:\n"
        prompt += "```json\n{"
        prompt += "\n  \"overallScore\": 75,"
        prompt += "\n  \"factorScores\": {\"accessibility\": 70, \"designConsistency\": 80, \"usability\": 75, \"visualHierarchy\": 70, \"responsiveness\": 85},"
        prompt += "\n  \"issues\": [{\"title\": \"Issue Title\", \"severity\": \"Medium\", \"description\": \"Detailed description\", \"location\": \"Top navigation bar\", \"impact\": 6}],"
        prompt += "\n  \"recommendations\": [{\"title\": \"Recommendation Title\", \"priority\": \"High\", \"description\": \"Detailed recommendation\", \"expectedImprovement\": 8}],"
        prompt += "\n  \"summary\": \"Overall assessment summary\""
        prompt += "\n}"
        prompt += "\n```"
        
        logger.info(f"Screen analysis prompt: {prompt}")
        
        try:
            # Use Google Gemini API for image analysis (already configured in the app)
            logger.info("Using Google Gemini API for screenshot analysis")
            
            # Check if Gemini API key is set
            if not os.getenv('GOOGLE_API_KEY'):
                logger.error("GOOGLE_API_KEY environment variable is not set")
                raise ValueError("GOOGLE_API_KEY environment variable is not set")
                
            logger.info(f"Using Gemini model: {model_name}")
            
            # Load the image for Gemini with proper file handling
            with open(temp_path, "rb") as img_file:
                image_data = img_file.read()
            
            image_parts = [
                {"mime_type": "image/png", "data": image_data}
            ]
            
            # Create Gemini model
            generation_config = {
                "temperature": 0.2,
                "top_p": 0.95,
                "top_k": 64,
                "max_output_tokens": 2048,
            }
            
            # Initialize the Gemini model
            model = genai.GenerativeModel(
                model_name=model_name,
                generation_config=generation_config
            )
            
            # Send request to Gemini
            logger.info("Sending image to Gemini API for analysis")
            response = model.generate_content(
                [
                    prompt,
                    image_parts[0]
                ]
            )
            
            # Extract the AI response
            ai_response = response.text
            logger.info(f"Received response from Gemini (length: {len(ai_response)})")
            
            # Log a sample of the response for debugging
            sample_length = min(500, len(ai_response))
            logger.info(f"Sample of Gemini response: {ai_response[:sample_length]}...")
            
            # Process Figma comparison if requested
            figma_comparison_results = None
            if figma_compare and figma_design:
                try:
                    logger.info("Processing Figma comparison")
                    # Process Figma design data
                    figma_type = figma_design.get('type')
                    figma_data = figma_design.get('data')
                    
                    # Create a prompt for Figma comparison
                    comparison_prompt = f"""
                    Compare this UI screenshot with the provided Figma design specification and identify meaningful mismatches.
                    Focus on issues that affect design fidelity or user experience, not minor pixel-level differences.
                    
                    Comparison areas to focus on:
                    {"Missing or extra UI elements" if comparison_focus.get('elements', True) else ""}
                    {"Text value differences" if comparison_focus.get('textValues', True) else ""}
                    {"Layout and alignment issues" if comparison_focus.get('layout', True) else ""}
                    {"Font property differences" if comparison_focus.get('fonts', True) else ""}
                    {"Color and styling differences" if comparison_focus.get('colors', True) else ""}
                    
                    For each issue found, provide:
                    1. A brief summary of the issue
                    2. Severity level (Critical, Major, or Minor)
                    3. Element details (what component has the issue)
                    4. Expected design (from Figma)
                    5. Actual implementation (from screenshot)
                    6. Brief rationale for why this matters to users or design fidelity
                    
                    For alignment issues, provide specific measurements or coordinates when possible.
                    
                    Calculate comprehensive design fidelity scores and provide actionable insights.
                    
                    Format your response as a JSON object with this structure:
                    {{"summary": "Overall comparison summary",
                     "overallScore": 85,
                     "comparisonMetrics": {{"designFidelity": 85, "elementAccuracy": 90, "textAccuracy": 85, "layoutAccuracy": 80, "styleAccuracy": 85, "interactionFidelity": 88}},
                     "issues": [
                        {{"title": "Issue title",
                         "severity": "Critical|Major|Minor",
                         "element": "Element description",
                         "expected": "Expected design from Figma",
                         "actual": "Actual implementation in screenshot",
                         "impact": 8,
                         "description": "Why this matters for user experience"}},
                        ...
                     ],
                     "recommendations": [
                        {{"title": "Recommendation title",
                         "priority": "High|Medium|Low",
                         "description": "Specific improvement suggestion",
                         "expectedImprovement": 7,
                         "effort": "Low|Medium|High"}},
                        ...
                     ]}}
                    
                    SCORING GUIDELINES:
                    - Overall Score: Average of all comparison metrics (0-100)
                    - Design Fidelity: How closely the implementation matches the design intent
                    - Element Accuracy: Presence and positioning of UI elements
                    - Text Accuracy: Correctness of text content, fonts, and typography
                    - Layout Accuracy: Spacing, alignment, and structural fidelity
                    - Style Accuracy: Colors, borders, shadows, and visual styling
                    - Interaction Fidelity: Button states, hover effects, and interactive elements
                    - Impact: How much each issue affects the design-implementation gap (1-10)
                    - Expected Improvement: How much fixing the recommendation would improve the overall score (1-10)
                    """
                    
                    logger.info("Figma comparison prompt created")
                    
                    # Add Figma design as second image if it's an image
                    if figma_type == 'image':
                        logger.info("Processing Figma image data")
                        # Extract base64 data if needed
                        if ',' in figma_data:
                            figma_data = figma_data.split(',')[1]
                        
                        # Decode the image
                        figma_image_data = base64.b64decode(figma_data)
                        
                        # Create a temporary file for the Figma image with proper handle management
                        figma_temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                        figma_temp_path = figma_temp_file.name
                        figma_temp_file.write(figma_image_data)
                        figma_temp_file.close()  # Close handle immediately
                        
                        # Add to image parts with proper file handling
                        with open(temp_path, "rb") as main_img_file:
                            main_img_data = main_img_file.read()
                        
                        with open(figma_temp_path, "rb") as figma_img_file:
                            figma_img_data = figma_img_file.read()
                        
                        figma_image_parts = [
                            {"mime_type": "image/png", "data": main_img_data},
                            {"mime_type": "image/png", "data": figma_img_data}
                        ]
                        
                        # Generate comparison content
                        logger.info("Sending Figma comparison request to Gemini")
                        comparison_response = model.generate_content(
                            [
                                comparison_prompt,
                                *figma_image_parts
                            ]
                        )
                        comparison_text = comparison_response.text
                        
                        # Clean up temporary file
                        os.unlink(figma_temp_path)
                        
                    elif figma_type == 'json':
                        logger.info("Processing Figma JSON data")
                        # For JSON data, extract design specs and include in prompt
                        figma_specs = json.dumps(figma_data, indent=2)
                        figma_prompt = f"{comparison_prompt}\n\nFigma Design Specifications:\n{figma_specs}"
                        
                        # Generate comparison content
                        comparison_response = model.generate_content(
                            [
                                figma_prompt,
                                image_parts[0]
                            ]
                        )
                        comparison_text = comparison_response.text
                    else:
                        logger.info("Processing Figma text data")
                        # Text data, use as is
                        figma_prompt = f"{comparison_prompt}\n\nFigma Design Specifications:\n{figma_data}"
                        
                        # Generate comparison content
                        comparison_response = model.generate_content(
                            [
                                figma_prompt,
                                image_parts[0]
                            ]
                        )
                        comparison_text = comparison_response.text
                    
                    logger.info(f"Received Figma comparison response (length: {len(comparison_text)})")
                    sample_length = min(500, len(comparison_text))
                    logger.info(f"Sample of Figma comparison response: {comparison_text[:sample_length]}...")
                    
                    # Try to parse JSON from the comparison response
                    try:
                        # Extract JSON from markdown code blocks if present
                        json_match = re.search(r'```(?:json)?\s*({[\s\S]*?})\s*```', comparison_text)
                        if json_match:
                            json_str = json_match.group(1)
                            figma_comparison_results = json.loads(json_str)
                            logger.info("Successfully parsed Figma comparison JSON from code block")
                        else:
                            # Try to find any JSON-like structure
                            json_pattern = r'{[\s\S]*?"issues"[\s\S]*?}'
                            json_match = re.search(json_pattern, comparison_text)
                            if json_match:
                                json_str = json_match.group(0)
                                figma_comparison_results = json.loads(json_str)
                                logger.info("Successfully parsed Figma comparison JSON from text")
                            else:
                                # Create a basic structure if no JSON found
                                logger.warning("Could not find JSON in Figma comparison response")
                                figma_comparison_results = {
                                    'summary': 'Comparison completed but structured results could not be extracted.',
                                    'issues': [{
                                        'summary': 'Unstructured comparison results',
                                        'severity': 'Minor',
                                        'description': comparison_text,
                                        'element': 'N/A',
                                        'expected': 'See description',
                                        'actual': 'See description'
                                    }]
                                }
                    except json.JSONDecodeError as e:
                        # Create a basic structure if JSON parsing fails
                        logger.error(f"JSON decode error in Figma comparison: {str(e)}")
                        figma_comparison_results = {
                            'summary': 'Comparison completed but results could not be parsed as JSON.',
                            'issues': [{
                                'summary': 'JSON parsing error',
                                'severity': 'Minor',
                                'description': 'The comparison results could not be parsed as JSON. Please try again.',
                                'element': 'N/A',
                                'expected': 'Valid JSON response',
                                'actual': 'Invalid JSON format'
                            }]
                        }
                except Exception as e:
                    logger.error(f"Error in Figma comparison: {str(e)}")
                    figma_comparison_results = {
                        'summary': f"Error during Figma comparison: {str(e)}",
                        'issues': [{
                            'summary': 'Comparison error',
                            'severity': 'Major',
                            'description': f"An error occurred during the comparison: {str(e)}",
                            'element': 'N/A',
                            'expected': 'Successful comparison',
                            'actual': 'Error during processing'
                        }]
                    }
            
            logger.info("Used Google Gemini API for screen analysis")
            # Log the AI response for debugging
            logger.info(f"AI response (truncated): {ai_response[:500]}...")
        
        except Exception as e:
            logger.error(f"Error in AI analysis: {str(e)}")
            # Create a default response with the error
            ai_response = json.dumps({
                "issues": [{
                    "title": "AI Analysis Error",
                    "severity": "High",
                    "description": f"Error during analysis: {str(e)}"
                }],
                "recommendations": ["Please try again with a different image or check system logs."]
            })
        
        # Define helper function for finding potential misspellings
        def find_potential_misspellings(text):
            common_words = set(['the', 'to', 'and', 'a', 'in', 'is', 'it', 'you', 'that', 'was', 'for', 'on', 'are', 'with', 'as', 'I', 'his', 'they', 'be', 'at', 'one', 'have', 'this', 'from', 'by', 'hot', 'word', 'but', 'what', 'some', 'we', 'can', 'out', 'other', 'were', 'all', 'there', 'when', 'up', 'use', 'your', 'how', 'said', 'an', 'each', 'she', 'which', 'do', 'their', 'time', 'if', 'will', 'way', 'about', 'many', 'then', 'them', 'write', 'would', 'like', 'so', 'these', 'her', 'long', 'make', 'thing', 'see', 'him', 'two', 'has', 'look', 'more', 'day', 'could', 'go', 'come', 'did', 'number', 'sound', 'no', 'most', 'people', 'my', 'over', 'know', 'water', 'than', 'call', 'first', 'who', 'may', 'down', 'side', 'been', 'now', 'find', 'any', 'new', 'work', 'part', 'take', 'get', 'place', 'made', 'live', 'where', 'after', 'back', 'little', 'only', 'round', 'man', 'year', 'came', 'show', 'every', 'good', 'me', 'give', 'our', 'under', 'name', 'very', 'through', 'just', 'form', 'sentence', 'great', 'think', 'say', 'help', 'low', 'line', 'differ', 'turn', 'cause', 'much', 'mean', 'before', 'move', 'right', 'boy', 'old', 'too', 'same', 'tell', 'does', 'set', 'three', 'want', 'air', 'well', 'also', 'play', 'small', 'end', 'put', 'home', 'read', 'hand', 'port', 'large', 'spell', 'add', 'even', 'land', 'here', 'must', 'big', 'high', 'such', 'follow', 'act', 'why', 'ask', 'men', 'change', 'went', 'light', 'kind', 'off', 'need', 'house', 'picture', 'try', 'us', 'again', 'animal', 'point', 'mother', 'world', 'near', 'build', 'self', 'earth', 'father'])
            words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
            unusual_words = [word for word in words if word not in common_words and len(word) > 3]
            
            # Look for potential typos (repeated characters, unusual character combinations)
            typos = []
            for word in unusual_words:
                if len(word) > 7 and word not in ['information', 'available', 'different', 'important', 'something', 'everything', 'development', 'management', 'experience', 'technology']:
                    typos.append(word)
                elif re.search(r'(.)\1{2,}', word):  # Repeated characters more than twice
                    typos.append(word)
                    
            return typos[:5]  # Return up to 5 potential issues
            
        # Define helper function for manual extraction
        def extract_issues_manually(text):
            logger.info("Extracting issues manually from text")
            result = {
                'issues': [],
                'recommendations': [],
                'overallScore': 70,  # Default moderate score for manual extraction
                'factorScores': {
                    'accessibility': 70,
                    'designConsistency': 70,
                    'usability': 70,
                    'visualHierarchy': 70,
                    'responsiveness': 70
                },
                'summary': 'UI analysis completed using manual text extraction due to parsing issues.'
            }
            
            # Extract issues using various patterns
            issue_patterns = [
                r'(?:issue|problem)\s*(?:\d+)?\s*:?\s*([^\n.]+)',  # Issue: Description
                r'(?:\d+\.\s*|-)\s*([^\n.]+)(?=\s*(?:issue|problem))',  # 1. Description (issue)
                r'"title"\s*:\s*"([^"]+)"',  # "title": "Description"
                r'<issue>\s*([^<]+)\s*</issue>'  # <issue>Description</issue>
            ]
            
            for pattern in issue_patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                if matches:
                    logger.info(f"Found {len(matches)} issues using pattern: {pattern}")
                    for i, match in enumerate(matches):
                        result['issues'].append({
                            'title': f"UI Issue {i+1}",
                            'severity': 'Medium',
                            'description': match.group(1).strip(),
                            'location': 'Unknown'
                        })
                    break  # Stop after finding issues with one pattern
            
            # Extract recommendations
            rec_patterns = [
                r'(?:recommendation|suggestion)\s*(?:\d+)?\s*:?\s*([^\n.]+)',  # Recommendation: Text
                r'(?:\d+\.\s*|-)\s*([^\n.]+)(?=\s*(?:recommend|suggest))',  # 1. Text (recommendation)
                r'"recommendation"\s*:\s*"([^"]+)"'  # "recommendation": "Text"
            ]
            
            for pattern in rec_patterns:
                matches = list(re.finditer(pattern, text, re.IGNORECASE))
                if matches:
                    logger.info(f"Found {len(matches)} recommendations using pattern: {pattern}")
                    for match in matches:
                        result['recommendations'].append(match.group(1).strip())
                    break  # Stop after finding recommendations with one pattern
            
            return result
            
        # Try to parse JSON from AI response
        try:
            logger.info(f"Full AI response: {ai_response}")
            
            # Step 1: First try to parse the entire response as JSON directly (most likely with response_format=json_object)
            try:
                logger.info("Attempting to parse entire response as JSON")
                ai_results = json.loads(ai_response)
                logger.info("Successfully parsed entire response as JSON")
            except json.JSONDecodeError:
                logger.info("Direct JSON parsing failed, trying alternative methods")
                
                # Step 2: Look for JSON in code blocks (common in LLM responses)
                json_match = re.search(r'```(?:json)?\s*\n(.+?)\n```', ai_response, re.DOTALL)
                if json_match:
                    logger.info("Found JSON in code block")
                    json_content = json_match.group(1).strip()
                    logger.info(f"Extracted JSON from code block: {json_content[:200]}...")
                    try:
                        ai_results = json.loads(json_content)
                        logger.info("Successfully parsed JSON from code block")
                    except json.JSONDecodeError as e:
                        logger.warning(f"Error parsing JSON from code block: {str(e)}")
                        # Try to clean up common JSON formatting issues
                        cleaned_json = re.sub(r'(?<!\\)\\n', '\n', json_content)  # Fix escaped newlines
                        cleaned_json = re.sub(r',\s*}', '}', cleaned_json)  # Fix trailing commas
                        cleaned_json = re.sub(r',\s*]', ']', cleaned_json)  # Fix trailing commas in arrays
                        
                        try:
                            ai_results = json.loads(cleaned_json)
                            logger.info("Successfully parsed cleaned JSON from code block")
                        except json.JSONDecodeError:
                            logger.warning("Could not parse cleaned JSON from code block, trying pattern extraction")
                            raise  # Continue to the next method
                else:
                    # Step 3: Try to extract JSON-like content with a robust pattern
                    logger.info("No code block found, trying to extract JSON pattern")
                    # Look for a complete JSON object from the start of a line
                    json_pattern = re.search(r'(?m)^\s*(\{[\s\S]*?\})\s*$', ai_response)
                    if not json_pattern:
                        # Try to find any JSON-like structure with both issues and recommendations
                        json_pattern = re.search(r'\{[\s\S]*?"issues"[\s\S]*?"recommendations"[\s\S]*?\}', ai_response)
                    
                    if json_pattern:
                        logger.info("Found JSON-like pattern")
                        json_content = json_pattern.group(0)
                        logger.info(f"Extracted JSON-like content: {json_content[:200]}...")
                        
                        # Try to clean up and parse
                        try:
                            ai_results = json.loads(json_content)
                            logger.info("Successfully parsed extracted JSON pattern")
                        except json.JSONDecodeError:
                            logger.warning("Could not parse JSON pattern, using manual extraction")
                            # Step 4: Manual extraction as last resort
                            ai_results = extract_issues_manually(ai_response)
                    else:
                        logger.warning("No JSON pattern found, using manual extraction")
                        # Step 4: Manual extraction as last resort
                        ai_results = extract_issues_manually(ai_response)
            
            # Validate the structure of the parsed results
            if not isinstance(ai_results, dict):
                logger.warning(f"Parsed result is not a dictionary: {type(ai_results)}")
                ai_results = {'issues': [], 'recommendations': []}
            
            # Ensure required fields exist
            if 'issues' not in ai_results:
                logger.warning("No 'issues' field in parsed results, adding empty array")
                ai_results['issues'] = []
                
            if 'recommendations' not in ai_results:
                logger.warning("No 'recommendations' field in parsed results, adding empty array")
                ai_results['recommendations'] = []
                
            # Validate each issue has required fields
            for i, issue in enumerate(ai_results['issues']):
                if not isinstance(issue, dict):
                    logger.warning(f"Issue {i} is not a dictionary: {issue}")
                    ai_results['issues'][i] = {
                        'title': 'Invalid Issue Format',
                        'severity': 'Medium',
                        'description': str(issue)
                    }
                    continue
                    
                # Ensure required fields
                if 'title' not in issue or not issue['title']:
                    issue['title'] = f"UI Issue {i+1}"
                    
                if 'severity' not in issue or not issue['severity'] or issue['severity'] not in ['High', 'Medium', 'Low']:
                    issue['severity'] = 'Medium'
                    
                if 'description' not in issue or not issue['description']:
                    issue['description'] = "No description provided"
                    
                if 'location' not in issue or not issue['location']:
                    issue['location'] = "Unknown location"
            
            logger.info(f"Validated AI results structure with {len(ai_results['issues'])} issues and {len(ai_results['recommendations'])} recommendations")
            
        except Exception as e:
            logger.error(f"Error parsing AI response: {str(e)}")
            # Create a default response with the error including scoring fields
            ai_results = {
                'issues': [{
                    'title': 'Response Parsing Error',
                    'severity': 'Medium',
                    'description': f"Could not parse the AI analysis response: {str(e)}",
                    'location': 'Unknown'
                }],
                'recommendations': ['Try again with a clearer screenshot or check system logs for details.'],
                'overallScore': 70,  # Default moderate score
                'factorScores': {
                    'accessibility': 70,
                    'designConsistency': 70,
                    'usability': 70,
                    'visualHierarchy': 70,
                    'responsiveness': 70
                },
                'summary': 'Analysis completed but response could not be fully parsed.'
            }
        os.unlink(temp_path)
        
        logger.info(f"Parsed AI results: {ai_results}")
        
        # Force issues to be found - NEVER return "no issues found"
        # If no issues were detected or parsing failed, create default issues
        if 'issues' not in ai_results or not ai_results['issues']:
            logger.info("No issues found in AI response, creating default issues")
            
            # Always create at least one issue
            default_issues = [{
                'title': 'UI Enhancement Opportunity',
                'severity': 'Low',
                'description': 'While no critical issues were detected, consider reviewing the UI for potential improvements in alignment, spacing, and visual hierarchy.',
                'location': 'Overall UI'
            }]
            
            # If OCR text is available, try to find potential issues
            if ocr_text and len(ocr_text.strip()) > 0:
                logger.info(f"OCR text available, analyzing for issues: {ocr_text[:100]}...")
                # Look for potential issues in the OCR text
                potential_issues = []
                
                # Check for common typos or misspellings
                misspelled_words = find_potential_misspellings(ocr_text)
                if misspelled_words:
                    logger.info(f"Found potential misspellings: {misspelled_words}")
                    potential_issues.append({
                        'title': 'Potential Text Issues',
                        'severity': 'Medium',
                        'description': f"Possible misspelled or unusual words detected: {', '.join(misspelled_words)}",
                        'location': 'Text content'
                    })
                
                # Check for potential layout issues
                if '  ' in ocr_text or ocr_text.count('\n\n') > 2:
                    logger.info("Found potential layout issues based on text spacing")
                    potential_issues.append({
                        'title': 'Potential Layout Issues',
                        'severity': 'Low',
                        'description': 'Text spacing appears inconsistent, which may indicate layout problems.',
                        'location': 'Text layout'
                    })
                
                # Add any found issues
                if potential_issues:
                    ai_results['issues'] = potential_issues
                else:
                    ai_results['issues'] = default_issues
            else:
                logger.info("No OCR text available, using default issues")
                ai_results['issues'] = default_issues
        
        # Ensure we have recommendations
        if 'recommendations' not in ai_results or not ai_results['recommendations']:
            logger.info("No recommendations found, adding defaults")
            ai_results['recommendations'] = [
                'Review the UI with actual users to validate the design and identify any usability concerns.',
                'Consider A/B testing different UI variations to optimize user experience.',
                'Ensure the UI follows accessibility guidelines for all users.'
            ]
            
        # Ensure we have scoring fields
        if 'overallScore' not in ai_results:
            logger.info("No overall score found, adding default")
            ai_results['overallScore'] = 75  # Default moderate score
            
        if 'factorScores' not in ai_results:
            logger.info("No factor scores found, adding defaults")
            ai_results['factorScores'] = {
                'accessibility': 75,
                'designConsistency': 75,
                'usability': 75,
                'visualHierarchy': 75,
                'responsiveness': 75
            }
            
        if 'summary' not in ai_results:
            logger.info("No summary found, adding default")
            ai_results['summary'] = f"Analyzed UI screenshot and found {len(ai_results.get('issues', []))} issues with actionable recommendations."
            
        # Clean up temporary files before returning response
        # Force garbage collection and add delay on Windows to ensure file handles are released
        import gc
        import platform
        
        # Force garbage collection to release any remaining file references
        gc.collect()
        
        if platform.system() == 'Windows':
            import time
            # Longer delay on Windows to ensure all file handles are fully released
            time.sleep(0.5)
        
        # Clean up main screenshot temporary file with retry mechanism
        def safe_delete_file(file_path, max_attempts=3):
            for attempt in range(max_attempts):
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                        logger.info(f"Successfully cleaned up temp file: {file_path}")
                        return True
                except Exception as e:
                    if attempt < max_attempts - 1:
                        logger.warning(f"Attempt {attempt + 1} failed to delete {file_path}: {e}. Retrying...")
                        time.sleep(0.2)  # Brief pause before retry
                    else:
                        logger.warning(f"Failed to delete {file_path} after {max_attempts} attempts: {e}")
                        return False
            return False
        
        safe_delete_file(temp_path)
        
        # Clean up any Figma temporary files
        if 'figma_temp_path' in locals():
            safe_delete_file(figma_temp_path)
            
        # Prepare response data with scoring information
        response_data = {
            'issues': ai_results.get('issues', []),
            'recommendations': ai_results.get('recommendations', []),
            'overallScore': ai_results.get('overallScore', 0),
            'factorScores': ai_results.get('factorScores', {}),
            'summary': ai_results.get('summary', '')
        }
        
        # Add OCR text if available
        if ocr_available and ocr_text and ocr_text.strip():
            response_data['ocr'] = ocr_text
            
        # Add Figma comparison results if available
        if figma_comparison_results:
            response_data['figmaComparison'] = figma_comparison_results
            # Include comparison metrics in main response for unified scoring display
            if 'comparisonMetrics' in figma_comparison_results:
                response_data['comparisonMetrics'] = figma_comparison_results['comparisonMetrics']
            if 'overallScore' in figma_comparison_results:
                response_data['overallScore'] = figma_comparison_results['overallScore']
            if 'summary' in figma_comparison_results:
                response_data['summary'] = figma_comparison_results['summary']
            
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in screen analysis: {str(e)}")
        
        # Clean up temporary files even on error
        import gc
        import platform
        
        # Force garbage collection to release any remaining file references
        gc.collect()
        
        if platform.system() == 'Windows':
            import time
            # Longer delay on Windows to ensure all file handles are fully released
            time.sleep(0.5)
        
        # Clean up temporary files using robust deletion
        def safe_delete_file_on_error(file_path, max_attempts=3):
            for attempt in range(max_attempts):
                try:
                    if os.path.exists(file_path):
                        os.unlink(file_path)
                        logger.info(f"Cleaned up temp file on error: {file_path}")
                        return True
                except Exception as e:
                    if attempt < max_attempts - 1:
                        logger.warning(f"Cleanup attempt {attempt + 1} failed for {file_path}: {e}. Retrying...")
                        time.sleep(0.2)
                    else:
                        logger.warning(f"Failed to cleanup {file_path} after {max_attempts} attempts: {e}")
                        return False
            return False
        
        # Clean up main screenshot temporary file
        if 'temp_path' in locals():
            safe_delete_file_on_error(temp_path)
        
        # Clean up any Figma temporary files
        if 'figma_temp_path' in locals():
            safe_delete_file_on_error(figma_temp_path)
        
        return jsonify({'error': str(e)}), 500

@app.route('/parse_curl_to_json', methods=['POST'])
def parse_curl_to_json():
    data = request.get_json()
    curl = data.get('curl', '')
    if not curl:
        return jsonify({'error': 'No curl command provided'}), 400
    try:
        parsed = parse_curl_command(curl)
        return jsonify({'json': parsed})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Helper: Convert Jira ADF to HTML (basic, extend as needed) ---
def adf_to_html(adf):
    if not adf:
        return ''
    t = adf.get('type') if isinstance(adf, dict) else None
    if t == 'text':
        text = adf.get('text', '')
        marks = adf.get('marks', [])
        for mark in marks:
            if mark['type'] == 'strong':
                text = f'<strong>{text}</strong>'
            elif mark['type'] == 'em':
                text = f'<em>{text}</em>'
            elif mark['type'] == 'underline':
                text = f'<u>{text}</u>'
            elif mark['type'] == 'link':
                href = mark.get('attrs', {}).get('href', '#')
                text = f'<a href="{href}" target="_blank">{text}</a>'
        return text
    elif t == 'paragraph':
        return '<p>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</p>'
    elif t == 'heading':
        level = adf.get('attrs', {}).get('level', 1)
        return f'<h{level}>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + f'</h{level}>'
    elif t == 'bulletList':
        return '<ul>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</ul>'
    elif t == 'orderedList':
        return '<ol>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</ol>'
    elif t == 'listItem':
        return '<li>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</li>'
    elif t == 'media':
        attrs = adf.get('attrs', {})
        media_id = attrs.get('id')
        collection = attrs.get('collection') or 'jira-issue'
        if media_id:
            return f'<img src="/api/jira/attachment?id={media_id}&collection={collection}" alt="Jira Image" style="max-width:100%;">'
        url = attrs.get('url') or attrs.get('dataURI')
        if url:
            return f'<img src="{url}" alt="Jira Image" style="max-width:100%;">'
        return ''
    elif t == 'table':
        return '<table class="table table-bordered">' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</table>'
    elif t == 'tableRow':
        return '<tr>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</tr>'
    elif t == 'tableCell' or t == 'tableHeader':
        tag = 'th' if t == 'tableHeader' else 'td'
        return f'<{tag}>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + f'</{tag}>'
    elif t == 'blockquote':
        return '<blockquote>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</blockquote>'
    elif t == 'codeBlock':
        return '<pre><code>' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</code></pre>'
    elif t == 'panel':
        return '<div class="panel" style="border:1px solid #eee;padding:0.5em;margin:0.5em 0;background:#f8f9fa;">' + ''.join(adf_to_html(child) for child in adf.get('content', [])) + '</div>'
    elif t == 'rule':
        return '<hr>'
    elif t == 'hardBreak':
        return '<br>'
    elif t == 'emoji':
        return adf.get('attrs', {}).get('shortName', '')
    elif isinstance(adf, dict) and 'content' in adf:
        return ''.join(adf_to_html(child) for child in adf['content'])
    elif isinstance(adf, list):
        return ''.join(adf_to_html(child) for child in adf)
    return ''

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
        url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/attachment/{attachment_id}'
        headers = {'Authorization': f'Bearer {access_token}'}
        resp = requests.get(url, headers=headers)
        app.logger.info(f'Jira attachment metadata GET {url} status={resp.status_code}')
        if resp.status_code != 200:
            app.logger.error(f'Attachment metadata fetch failed: {resp.text}')
            return '', 404
        data = resp.json()
        content_url = data.get('content')
        if not content_url:
            app.logger.error(f'No content URL in attachment metadata: {data}')
            return '', 404
        img_resp = requests.get(content_url, headers=headers, stream=True)
        app.logger.info(f'Jira attachment content GET {content_url} status={img_resp.status_code}')
        if img_resp.status_code != 200:
            app.logger.error(f'Attachment content fetch failed: {img_resp.text}')
            return '', 404
        return Response(img_resp.iter_content(chunk_size=4096), content_type=img_resp.headers.get('Content-Type', 'image/png'))
    else:
        # Media Service (UUID)
        media_url = f'https://api.media.atlassian.com/file/{attachment_id}/binary?collection={collection}'
        headers = {'Authorization': f'Bearer {access_token}'}
        img_resp = requests.get(media_url, headers=headers, stream=True)
        app.logger.info(f'Jira media service GET {media_url} status={img_resp.status_code}')
        if img_resp.status_code != 200:
            app.logger.error(f'Media service fetch failed: {img_resp.text}')
            return '', 404
        return Response(img_resp.iter_content(chunk_size=4096), content_type=img_resp.headers.get('Content-Type', 'image/png'))

@app.route('/api/jira/disconnect', methods=['POST'])
def disconnect_jira():
    for k in ['jira_access_token', 'jira_refresh_token', 'jira_token_expires', 'jira_cloud_id', 'jira_domain']:
        session.pop(k, None)
    return jsonify({'success': True})

@app.route('/api/jira/create-subtasks', methods=['POST'])
def create_jira_subtasks():
    """Create subtasks in Jira for each test case"""
    # Check if feature is enabled (development mode only)
    if FLASK_ENV != 'development':
        return jsonify({'error': 'Create subtasks feature is only available in development mode.'}), 403
    
    # Check if user is authenticated with Jira
    access_token = session.get('jira_access_token')
    cloud_id = session.get('jira_cloud_id')
    domain = session.get('jira_domain', 'https://upgrad-jira.atlassian.net')
    
    if not access_token:
        return jsonify({'error': 'Not authenticated with Jira. Please connect first.'}), 401
    if not cloud_id:
        return jsonify({'error': 'No Jira cloud ID found. Please reconnect to Jira.'}), 401

    # Check if token needs refresh
    token_expires = session.get('jira_token_expires', 0)
    if time.time() >= token_expires:
        if not refresh_jira_token():
            return jsonify({'error': 'Token expired. Please reconnect to Jira.'}), 401
        access_token = session['jira_access_token']
    
    # Get data from request
    try:
        data = request.json
        parent_issue_key = data.get('parentIssueKey')
        test_cases = data.get('testCases', [])
        
        if not parent_issue_key:
            return jsonify({'error': 'Parent issue key is required'}), 400
        if not test_cases:
            return jsonify({'error': 'No test cases provided'}), 400
        
        # Create subtasks
        created_count = 0
        failed_count = 0
        created_keys = []
        
        # Make request to Jira API
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        
        # Get the parent issue to get the project key
        issue_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/{parent_issue_key}'
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Accept': 'application/json'
        }
        
        response = requests.get(issue_url, headers=headers)
        if response.status_code != 200:
            logger.error(f"Error fetching parent issue: {response.text}")
            return jsonify({'error': f'Error fetching parent issue: {response.status_code}'}), response.status_code
        
        issue_data = response.json()
        project_key = issue_data.get('fields', {}).get('project', {}).get('key')
        
        if not project_key:
            return jsonify({'error': 'Could not determine project key from parent issue'}), 400
        
        # Get the subtask issue type ID and available fields
        meta_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue/createmeta?projectKeys={project_key}&issuetypeNames=Sub-task&expand=projects.issuetypes.fields'
        response = requests.get(meta_url, headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Error fetching issue metadata: {response.text}")
            return jsonify({'error': f'Error fetching issue metadata: {response.status_code}'}), response.status_code
        
        meta_data = response.json()
        subtask_type_id = None
        available_fields = {}
        
        # Extract available fields for subtasks
        for project in meta_data.get('projects', []):
            if project.get('key') == project_key:
                for issue_type in project.get('issuetypes', []):
                    if issue_type.get('subtask', False) or issue_type.get('name') == 'Sub-task':
                        subtask_type_id = issue_type.get('id')
                        available_fields = issue_type.get('fields', {})
                        break
        
        if not subtask_type_id:
            return jsonify({'error': 'Could not find subtask issue type'}), 400
        
        logger.info(f"Available fields for subtasks: {list(available_fields.keys())}")
        
        # Initialize counters
        created_count = 0
        failed_count = 0
        created_keys = []
        
        # Create each subtask
        create_url = f'https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/issue'
        
        # Log detailed information for debugging
        logger.info(f"Creating subtasks for parent issue: {parent_issue_key}")
        logger.info(f"Project key: {project_key}")
        logger.info(f"Subtask type ID: {subtask_type_id}")
        logger.info(f"Number of test cases to create: {len(test_cases)}")
        
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
                    'key': parent_issue_key
                },
                'issuetype': {
                    'id': subtask_type_id
                },
                'summary': f'Test: {step[:80]}' + ('...' if len(step) > 80 else ''),
                'description': {
                    'type': 'doc',
                    'version': 1,
                    'content': [
                        {
                            'type': 'heading',
                            'attrs': {'level': 3},
                            'content': [{'type': 'text', 'text': 'Test Step'}]
                        },
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': step}]
                        },
                        {
                            'type': 'heading',
                            'attrs': {'level': 3},
                            'content': [{'type': 'text', 'text': 'Expected Result'}]
                        },
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': expected}]
                        },
                        {
                            'type': 'heading',
                            'attrs': {'level': 3},
                            'content': [{'type': 'text', 'text': 'Estimated Time'}]
                        },
                        {
                            'type': 'paragraph',
                            'content': [{'type': 'text', 'text': f'{estimate_minutes} minutes'}]
                        }
                    ]
                }
            }
            
            # Try to set the original estimate if the timetracking field exists in available fields
            if 'timetracking' in available_fields:
                fields['timetracking'] = {
                    'originalEstimate': f'{estimate_minutes}m'
                }
                logger.info("Added timetracking field to subtask")
            
            # Look for any field that might be related to task type in the available fields
            logger.info("Examining available fields for task type fields")
            
            # Check if customfield_10010 is in available fields - this is often used for task type
            if 'customfield_10010' in available_fields:
                logger.info("Found customfield_10010 in available fields")
                field_info = available_fields['customfield_10010']
                
                # Check if this field has allowed values
                if 'allowedValues' in field_info:
                    logger.info(f"customfield_10010 has {len(field_info['allowedValues'])} allowed values")
                    
                    # Try to find a value that matches QA Testing or Test Execution
                    for value in field_info['allowedValues']:
                        value_name = value.get('value', '')
                        logger.info(f"Available value: {value_name}")
                        
                        if 'qa testing' in value_name.lower() or 'test execution' in value_name.lower():
                            if 'id' in value:
                                fields['customfield_10010'] = {'id': value['id']}
                                logger.info(f"Setting customfield_10010 to id: {value['id']} (value: {value_name})")
                            else:
                                fields['customfield_10010'] = {'value': value_name}
                                logger.info(f"Setting customfield_10010 to value: {value_name}")
                            break
                    else:
                        # If no matching value found, use the first one
                        if field_info['allowedValues']:
                            first_value = field_info['allowedValues'][0]
                            if 'id' in first_value:
                                fields['customfield_10010'] = {'id': first_value['id']}
                                logger.info(f"Setting customfield_10010 to first available id: {first_value['id']}")
                            else:
                                fields['customfield_10010'] = {'value': first_value['value']}
                                logger.info(f"Setting customfield_10010 to first available value: {first_value['value']}")
            
            # Look for any other fields that might be task type related
            for field_id, field_info in available_fields.items():
                field_name = field_info.get('name', '').lower()
                
                # Skip customfield_10010 as we already handled it
                if field_id == 'customfield_10010':
                    continue
                    
                # If this looks like a task type field and has allowed values
                if ('task' in field_name or 'type' in field_name) and 'allowedValues' in field_info:
                    logger.info(f"Found potential task type field: {field_id} ({field_name})")
                    
                    # Try to find a value that matches QA Testing or Test Execution
                    for value in field_info['allowedValues']:
                        value_name = value.get('value', '')
                        if 'qa testing' in value_name.lower() or 'test execution' in value_name.lower():
                            if 'id' in value:
                                fields[field_id] = {'id': value['id']}
                                logger.info(f"Setting {field_id} to id: {value['id']} (value: {value_name})")
                            else:
                                fields[field_id] = {'value': value_name}
                                logger.info(f"Setting {field_id} to value: {value_name}")
                            break
                    else:
                        # If no matching value found, use the first one
                        if field_info['allowedValues']:
                            first_value = field_info['allowedValues'][0]
                            if 'id' in first_value:
                                fields[field_id] = {'id': first_value['id']}
                                logger.info(f"Setting {field_id} to first available id: {first_value['id']}")
                            else:
                                fields[field_id] = {'value': first_value['value']}
                                logger.info(f"Setting {field_id} to first available value: {first_value['value']}")
            
            # Only use fields that are available in the metadata
            # Do not try to set fields that aren't available
            
            # DO NOT set any fields that aren't in the metadata
            # This was causing the errors we saw
            
            # Create the final payload with the fields
            payload = {'fields': fields}
            
            try:
                logger.info(f"Sending payload for subtask creation: {payload}")
                response = requests.post(create_url, headers=headers, json=payload, timeout=30)
                
                if response.status_code in (200, 201):
                    created_count += 1
                    created_keys.append(response.json().get('key'))
                    logger.info(f"Successfully created subtask {response.json().get('key')}")
                else:
                    failed_count += 1
                    error_message = f"Failed to create subtask: HTTP {response.status_code}: {response.text}"
                    logger.error(error_message)
                    error_details.append({
                        'step': step[:50] + '...',
                        'status_code': response.status_code,
                        'response': response.text[:200] + ('...' if len(response.text) > 200 else '')
                    })
            except Exception as e:
                failed_count += 1
                error_message = f"Exception creating subtask: {str(e)}"
                logger.error(error_message)
                error_details.append({
                    'step': step[:50] + '...',
                    'exception': str(e)
                })
        
        return jsonify({
            'status': 'success',
            'createdCount': created_count,
            'failedCount': failed_count,
            'createdKeys': created_keys,
            'errorDetails': error_details if failed_count > 0 else []
        })
        
    except Exception as e:
        logger.error(f"Error creating Jira subtasks: {str(e)}")
        return jsonify({'error': f'Error creating subtasks: {str(e)}'}), 500

# --- OCR and Vision API Hybrid Endpoint ---
import pytesseract
from PIL import Image
import requests
from flask import request, jsonify
# If Tesseract is not in PATH, uncomment and set the path below:
# pytesseract.pytesseract.tesseract_cmd = r'C:\\Program Files\\Tesseract-OCR\\tesseract.exe'

@app.route('/api/image-to-text', methods=['POST'])
def image_to_text():
    data = request.json
    image_url = data.get('image_url')
    if not image_url:
        return jsonify({'error': 'No image_url provided'}), 400
    try:
        img = Image.open(requests.get(image_url, stream=True).raw)
        text = pytesseract.image_to_string(img)
        if text.strip():
            return jsonify({'text': text.strip(), 'source': 'ocr'})
        # Fallback: Vision API (dummy)
        caption = call_vision_api(image_url)
        return jsonify({'text': caption, 'source': 'vision'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def call_vision_api(image_url):
    # TODO: Integrate with a real vision API if needed
    return "No text found, and vision API not implemented."
# --- End OCR and Vision API Hybrid Endpoint ---

def step_to_description(step):
    action = step.get('action', '')
    if action == 'navigate':
        return f"Navigate to URL: {step.get('url', '')}"
    elif action == 'click':
        return f"Click element: {step.get('selector', '')}"
    elif action == 'fill':
        return f"Fill form field: {step.get('selector', '')} with {step.get('value', '')}"
    elif action == 'extract_text':
        return f"Extract text from element: {step.get('selector', '')}"
    elif action == 'assert_visible':
        return f"Assert element is visible: {step.get('selector', '')}"
    elif action == 'assert_text':
        return f"Assert element contains text: {step.get('selector', '')} '{step.get('text', '')}'"
    elif action == 'wait_for_element':
        return f"Wait for element: {step.get('selector', '')}"
    elif action == 'custom':
        return step.get('instruction', '[custom instruction]')
    elif action == 'page_html':
        return "Extract page HTML"
    elif action == 'select':
        return f"Select from dropdown: {step.get('selector', '')} value {step.get('value', '')}"
    elif action == 'type':
        return f"Type text: {step.get('selector', '')} '{step.get('text', '')}'"
    elif action == 'press_key':
        return f"Press key: {step.get('key', '')}"
    elif action == 'assert_url':
        return f"Assert URL: {step.get('url', '')}"
    elif action == 'assert_title':
        return f"Assert page title: {step.get('title', '')}"
    # Add more actions as needed, matching UI labels
    else:
        return f"{action}: {step}" if action else str(step)

@app.route('/api/browseruse/navigation', methods=['POST'])
@llm_rate_limit
def browseruse_navigation():
    print("DEBUG: /api/browseruse/navigation endpoint was called")
    import os
    import json
    data = request.get_json() or {}
    steps = data.get('steps')
    task_prompt = data.get('prompt')
    # Initialize AzureChatOpenAI without proxies parameter which is causing the error
    llm = AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        openai_api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_key=os.getenv("AZURE_OPENAI_KEY"),
        temperature=0.0,
        max_tokens=300,
        http_client=None  # Explicitly set to None to avoid proxies issue
    )
    
    # Define a function to analyze screenshots for issues
    def analyze_screenshot(screenshot_data):
        """Analyze a screenshot for visual issues using Azure OpenAI."""
        if not screenshot_data:
            return None
            
        try:
            # Use the same LLM to analyze the screenshot
            analysis_prompt = (
                "Analyze this screenshot for visual issues such as: \n"
                "1. UI rendering problems (overlapping elements, misaligned components)\n"
                "2. Error messages or warnings visible on screen\n"
                "3. Missing content or broken images\n"
                "4. Unexpected popups or dialogs\n"
                "5. Form validation errors\n"
                "6. Responsive design issues\n\n"
                "If any issues are found, describe them in detail. If no issues are found, explicitly state 'No issues found'."
            )
            
            # Create a message with the screenshot as content
            messages = [
                {"role": "system", "content": analysis_prompt},
                {"role": "user", "content": f"Analyze this screenshot: {screenshot_data}"}
            ]
            
            # Use the Azure OpenAI client to analyze the screenshot
            response = openai.ChatCompletion.create(
                deployment_id=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview"),
                api_base=os.getenv("AZURE_OPENAI_ENDPOINT"),
                api_key=os.getenv("AZURE_OPENAI_KEY"),
                messages=messages
            )
            
            analysis_result = response.choices[0].message.content
            
            # Check if the analysis found any issues
            if "no issues found" in analysis_result.lower():
                return {"has_issues": False, "analysis": analysis_result}
            else:
                return {"has_issues": True, "analysis": analysis_result}
                
        except Exception as e:
            logger.error(f"Error analyzing screenshot: {str(e)}")
            return {"has_issues": False, "analysis": f"Error during analysis: {str(e)}"}

    step_reports = []
    nav_data = None
    screenshot_url = None
    table_data = None
    error_count = 0
    # If steps are provided, build a single prompt and run the agent once
    if steps and isinstance(steps, list):
        # Build a single prompt from all steps
        prompt = '. '.join([step_to_description(step) for step in steps])
        agent = Agent(task=prompt, llm=llm)
        try:
            result = asyncio.run(agent.run())
            error_val = getattr(result, 'error', None)
            status = "pass" if not error_val else "fail"
            actual = getattr(result, 'extracted_content', None) or str(result)
            
            # Check if a screenshot was captured and analyze it
            screenshot_data = getattr(result, 'screenshot', None)
            if screenshot_data:
                # Analyze the screenshot for issues
                screenshot_analysis = analyze_screenshot(screenshot_data)
                if screenshot_analysis and screenshot_analysis.get('has_issues'):
                    # If issues were found, update the status and error
                    status = "fail"
                    error_val = f"Screenshot analysis found issues: {screenshot_analysis.get('analysis')}"
                    # Store the analysis in the result
                    setattr(result, 'screenshot_analysis', screenshot_analysis.get('analysis'))
        except Exception as e:
            status = "fail"
            error_val = str(e)
            actual = ""
        # Return a single step report for the whole flow
        def safe_serialize(val):
            # Only allow JSON-serializable types, else convert to string
            if isinstance(val, (str, int, float, bool)) or val is None:
                return val
            if isinstance(val, (list, dict)):
                return val
            return str(val)

        step_reports.append({
            "step": 1,
            "description": safe_serialize(prompt),
            "actual": safe_serialize(actual),
            "status": safe_serialize(status),
            "error": safe_serialize(error_val),
            "extracted_content": safe_serialize(getattr(result, 'extracted_content', None) if 'result' in locals() else None),
            "screenshot_analysis": safe_serialize(getattr(result, 'screenshot_analysis', None) if 'result' in locals() else None),
            "raw": str(result) if 'result' in locals() else ""
        })
        # Only include the raw output (no summary, errors, or step execution)
        raw_section = step_reports[0].get('raw', '') if step_reports and step_reports[0].get('raw') else 'No raw output.'
        details = raw_section
        # Build a summary report
        report = {
            "summary": f"Ran {len(steps)} steps as a single flow.",
            "error_count": 1 if status == "fail" else 0,
            "details": details
        }
        # Return as a single step in the response
        combined_steps = [{
            "intent": {"description": prompt},
            "result": step_reports[0]
        }]
        return jsonify({
            "steps": combined_steps,
            "report": report
        })
    # Fallback: single prompt mode (legacy)
    if not task_prompt or not task_prompt.strip():
        return jsonify({"error": "Prompt is required."}), 400
    agent = Agent(task=task_prompt, llm=llm)
    result = asyncio.run(agent.run())
    print("DEBUG: type(result) =", type(result))
    print("DEBUG: result repr =", repr(result))
    nav_data = None
    screenshot_url = None
    table_data = None
    error_count = 0
    # Build step-by-step report from agent history (robust: supports string or object)
    step_reports = []
    print("DEBUG: type(result) =", type(result))
    print("DEBUG: result repr =", repr(result))
    print("DEBUG: dir(result) =", dir(result))
    try:
        print("DEBUG: hasattr(result, 'all_results') =", hasattr(result, 'all_results'))
        print("DEBUG: type(result.all_results) =", type(result.all_results))
        print("DEBUG: result.all_results =", repr(result.all_results))
        print("DEBUG: bool(result.all_results) =", bool(result.all_results))
        print("DEBUG: len(result.all_results) =", len(result.all_results))
    except Exception as e:
        print("DEBUG: Exception accessing result.all_results:", e)
    # Try to get steps array from request
    steps = data.get('steps') if 'data' in locals() else None
    if hasattr(result, 'all_results'):
        all_results = result.all_results
        if all_results and hasattr(all_results, '__iter__'):
            for idx, action in enumerate(all_results):
                error_val = getattr(action, 'error', None)
                status = "pass" if not error_val else "fail"
                if steps and idx < len(steps):
                    description = step_to_description(steps[idx])
                else:
                    description = getattr(action, 'description', getattr(action, 'tool_input', ''))
                actual = getattr(action, 'extracted_content', None) or str(action)
                
                # Check if this action has a screenshot and analyze it
                screenshot_data = getattr(action, 'screenshot', None)
                screenshot_analysis = None
                if screenshot_data:
                    # Analyze the screenshot for issues
                    analysis_result = analyze_screenshot(screenshot_data)
                    if analysis_result and analysis_result.get('has_issues'):
                        # If issues were found, update the status and error
                        status = "fail"
                        error_val = f"Screenshot analysis found issues: {analysis_result.get('analysis')}"
                        # Store the analysis
                        screenshot_analysis = analysis_result.get('analysis')
                    else:
                        screenshot_analysis = analysis_result.get('analysis') if analysis_result else None
                step_reports.append({
                    "step": idx + 1,
                    "description": description,
                    "actual": actual,
                    "status": status,
                    "error": error_val,
                    "extracted_content": getattr(action, 'extracted_content', None),
                    "screenshot_analysis": screenshot_analysis,
                    "raw": str(action)
                })
    else:
        # Fallback: parse ActionResult blocks from repr(result)
        print("DEBUG: Fallback to parsing ActionResult blocks from repr(result)")
        result_str = repr(result)
        import re
        def extract_action_results(raw):
            results = []
            start = 0
            while True:
                idx = raw.find('ActionResult(', start)
                if idx == -1:
                    break
                depth = 0
                for i in range(idx + len('ActionResult('), len(raw)):
                    if raw[i] == '(': depth += 1
                    elif raw[i] == ')':
                        if depth == 0:
                            results.append(raw[idx + len('ActionResult('):i])
                            start = i + 1
                            break
                        else:
                            depth -= 1
                else:
                    break
            return results
        matches = extract_action_results(result_str)
        print(f"DEBUG: Found {len(matches)} ActionResult blocks.")
        for idx, match in enumerate(matches):
            is_done = 'is_done=True' in match
            success = 'success=True' in match
            error_match = re.search(r"error=([^,)]*)", match)
            error_val = error_match.group(1) if error_match else None
            extracted_content_match = re.search(r"extracted_content='(.*?)'", match, re.DOTALL)
            extracted_content_val = extracted_content_match.group(1) if extracted_content_match else None
            status = "pass" if not error_val or error_val == 'None' else "fail"
            if steps and idx < len(steps):
                description = step_to_description(steps[idx])
            elif 'task_prompt' in locals() and task_prompt:
                description = task_prompt
            elif 'desc' in locals() and desc:
                description = desc
            else:
                description = ''
            actual = extracted_content_val or match
            step_reports.append({
                "step": idx + 1,
                "description": description,
                "actual": actual,
                "status": status,
                "error": None if error_val == 'None' else error_val,
                "extracted_content": extracted_content_val,
                "raw": match
            })
    combined_steps = []
    for idx, step_report in enumerate(step_reports):
        combined_steps.append({
            "intent": {"description": step_report.get("description", "")},
            "result": step_report
        })
    if 'report' not in locals():
        report = {
            "summary": f"Processed {len(step_reports)} steps." if step_reports else "No steps found.",
            "details": str(result)[:1000] if 'result' in locals() else ""
        }
    return jsonify({
        "navigation": nav_data or [],
        "screenshot_url": screenshot_url,
        "table_data": table_data,
        "raw": str(result),
        "report": report,
        "steps": combined_steps
    })

@app.route('/browseruse-automation')
def browseruse_automation():
    return render_template('browseruse-automation-stepwise.html', active_tab='browseruse')

@app.route('/browseruse-automation-stepwise')
def browseruse_automation_stepwise():
    return render_template('browseruse-automation-stepwise.html', active_tab='browseruse-stepwise')

@app.route('/pom-step-builder')
def pom_step_builder():
    return render_template('pom-step-builder-integrated.html', active_tab='pom-step-builder')

@app.route('/pom-builder')
@jira_auth_required
def pom_builder():
    """Integrated POM Builder - combines element extraction and POM generation"""
    return render_template('pom-builder.html', active_tab='pom-builder')

@app.route('/automation-studio-element-extractor')
@jira_auth_required
def element_extractor():
    """Original Element Extractor (legacy)"""
    return render_template('AutomationStudio-ElementExtractor.html', active_tab='element-extractor')

@app.route('/automation-studio-pom-generator')
@jira_auth_required
def pom_generator():
    """Original POM Generator (legacy)"""
    return render_template('AutomationStudio-pomgenerator.html', active_tab='pom-generator')

@app.route('/api/extract-elements', methods=['POST'])
def extract_elements():
    """Extract UI elements from uploaded screenshots or HTML files"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        # Get file extension
        filename = file.filename.lower()
        
        if filename.endswith(('.png', '.jpg', '.jpeg')):
            # For image files, return mock elements (in production, use OCR/CV)
            elements = [
                {'id': 1, 'type': 'button', 'text': 'Submit', 'selector': 'button[type="submit"]', 'x': 100, 'y': 200, 'width': 80, 'height': 32},
                {'id': 2, 'type': 'input', 'text': 'Email', 'selector': 'input[type="email"]', 'x': 50, 'y': 150, 'width': 200, 'height': 32},
                {'id': 3, 'type': 'input', 'text': 'Password', 'selector': 'input[type="password"]', 'x': 50, 'y': 190, 'width': 200, 'height': 32},
                {'id': 4, 'type': 'link', 'text': 'Sign Up', 'selector': 'a[href="/signup"]', 'x': 260, 'y': 250, 'width': 60, 'height': 20},
                {'id': 5, 'type': 'text', 'text': 'Welcome', 'selector': '.welcome-message', 'x': 50, 'y': 100, 'width': 200, 'height': 24}
            ]
        elif filename.endswith(('.html', '.htm')):
            # For HTML files, parse the content
            content = file.read().decode('utf-8')
            elements = parse_html_elements(content)
        else:
            return jsonify({'error': 'Unsupported file type. Please upload PNG, JPG, or HTML files.'}), 400
            
        return jsonify({
            'success': True,
            'elements': elements,
            'filename': file.filename
        })
        
    except Exception as e:
        logger.error(f"Error extracting elements: {str(e)}")
        return jsonify({'error': str(e)}), 500

def parse_html_elements(html_content):
    """Parse HTML content and extract UI elements"""
    from bs4 import BeautifulSoup
    import re
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        elements = []
        element_id = 1
        
        # Extract different types of elements
        element_types = [
            ('button', 'button'),
            ('input', 'input'),
            ('link', 'a'),
            ('text', 'h1, h2, h3, h4, h5, h6, p, span, div.text'),
            ('image', 'img'),
            ('select', 'select'),
            ('textarea', 'textarea')
        ]
        
        for elem_type, selector in element_types:
            found_elements = soup.select(selector)
            
            for elem in found_elements[:10]:  # Limit to 10 elements per type
                # Generate selector
                css_selector = generate_css_selector(elem)
                
                # Get text content
                text = elem.get_text(strip=True) if elem_type != 'image' else elem.get('alt', 'Image')
                if elem_type == 'input':
                    text = elem.get('placeholder') or elem.get('name') or elem.get('id') or f'{elem.get("type", "text")} input'
                elif elem_type == 'link':
                    text = text or elem.get('href', 'Link')
                elif elem_type == 'button':
                    text = text or 'Button'
                
                if text and len(text.strip()) > 0:
                    elements.append({
                        'id': element_id,
                        'type': elem_type,
                        'text': text[:50],  # Truncate long text
                        'selector': css_selector,
                        'x': 0,  # HTML parsing doesn't provide coordinates
                        'y': 0,
                        'width': 0,
                        'height': 0
                    })
                    element_id += 1
        
        return elements[:20]  # Return max 20 elements
        
    except ImportError:
        # If BeautifulSoup is not available, return mock elements
        logger.warning("BeautifulSoup not available, returning mock elements")
        return [
            {'id': 1, 'type': 'button', 'text': 'Submit Button', 'selector': 'button.submit', 'x': 0, 'y': 0, 'width': 0, 'height': 0},
            {'id': 2, 'type': 'input', 'text': 'Username Field', 'selector': 'input#username', 'x': 0, 'y': 0, 'width': 0, 'height': 0},
            {'id': 3, 'type': 'input', 'text': 'Password Field', 'selector': 'input#password', 'x': 0, 'y': 0, 'width': 0, 'height': 0}
        ]
    except Exception as e:
        logger.error(f"Error parsing HTML: {str(e)}")
        return []

def generate_css_selector(element):
    """Generate a CSS selector for a BeautifulSoup element"""
    try:
        # Try ID first
        if element.get('id'):
            return f"#{element['id']}"
        
        # Try class names
        if element.get('class'):
            classes = ' '.join(element['class'])
            return f"{element.name}.{classes.replace(' ', '.')}"
        
        # Try name attribute
        if element.get('name'):
            return f"{element.name}[name='{element['name']}']"
        
        # Try type for inputs
        if element.name == 'input' and element.get('type'):
            return f"input[type='{element['type']}']"
        
        # Try placeholder for inputs
        if element.name == 'input' and element.get('placeholder'):
            return f"input[placeholder='{element['placeholder']}']"
        
        # Try href for links
        if element.name == 'a' and element.get('href'):
            return f"a[href='{element['href']}']"
        
        # Fallback to tag name
        return element.name
        
    except Exception:
        return element.name if element.name else 'element'

@app.route('/api/pom/pages', methods=['POST'])
def get_pom_pages():
    data = request.json
    pom_path = data.get('path')
    
    if not pom_path or not os.path.exists(pom_path):
        return jsonify({'error': 'Invalid POM path'}), 400
    
    try:
        # Find all JavaScript files that might be page objects
        pages = []
        
        # If the path already ends with 'pages', use it directly
        if os.path.basename(pom_path) == 'pages':
            pages_dir = pom_path
        else:
            # Try different possible locations for page objects
            possible_paths = [
                os.path.join(pom_path, 'pages'),
                os.path.join(pom_path, 'features', 'pages')
            ]
            
            pages_dir = None
            for path in possible_paths:
                if os.path.exists(path):
                    pages_dir = path
                    break
            
            if not pages_dir:
                return jsonify({'error': 'Could not find pages directory'}), 404
        
        logger.info(f"Looking for page objects in: {pages_dir}")
        
        # Track page names to avoid duplicates
        added_pages = set()
        
        # Look for JS files in the pages directory
        if os.path.exists(pages_dir):
            for file in os.listdir(pages_dir):
                if file.endswith('.js') and file != 'BasePage.js':
                    page_name = file.replace('.js', '')
                    if page_name not in added_pages:
                        pages.append({
                            'name': page_name,
                            'path': os.path.join(pages_dir, file)
                        })
                        added_pages.add(page_name)
        
        # Also check for page objects in subdirectories
        for root, dirs, files in os.walk(pages_dir):
            # Skip the root directory as we already processed it above
            if root == pages_dir:
                continue
                
            for file in files:
                if file.endswith('.js') and file != 'BasePage.js':
                    page_name = file.replace('.js', '')
                    if page_name not in added_pages:
                        pages.append({
                            'name': page_name,
                            'path': os.path.join(root, file)
                        })
                        added_pages.add(page_name)
        
        return jsonify({'pages': pages})
    except Exception as e:
        logger.error(f"Error getting POM pages: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/elements', methods=['POST'])
def get_pom_elements():
    data = request.json
    pom_path = data.get('path')
    page_name = data.get('page')
    
    if not pom_path or not os.path.exists(pom_path) or not page_name:
        return jsonify({'error': 'Invalid POM path or page name'}), 400
    
    try:
        # Find the page file
        page_file = None
        
        # If the path already ends with 'pages', use it directly
        if os.path.basename(pom_path) == 'pages':
            pages_dir = pom_path
        else:
            # Try different possible locations for page objects
            possible_paths = [
                os.path.join(pom_path, 'pages'),
                os.path.join(pom_path, 'features', 'pages')
            ]
            
            pages_dir = None
            for path in possible_paths:
                if os.path.exists(path):
                    pages_dir = path
                    break
            
            if not pages_dir:
                return jsonify({'error': 'Could not find pages directory'}), 404
        
        logger.info(f"Looking for page {page_name} in: {pages_dir}")
        
        # Check direct file
        direct_file = os.path.join(pages_dir, f"{page_name}.js")
        if os.path.exists(direct_file):
            page_file = direct_file
        else:
            # Search in subdirectories
            for root, dirs, files in os.walk(pages_dir):
                for file in files:
                    if file == f"{page_name}.js":
                        page_file = os.path.join(root, file)
                        break
                if page_file:
                    break
        
        if not page_file:
            return jsonify({'error': f'Page file for {page_name} not found'}), 404
        
        # Import our simple POM parser
        from simple_pom_parser import get_page_elements
        
        # Parse the page file to extract elements
        logger.info(f"Parsing page file: {page_file}")
        elements = get_page_elements(page_file)
        
        return jsonify({'elements': elements})
    except Exception as e:
        logger.error(f"Error getting POM elements: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/functions', methods=['POST'])
def get_pom_functions():
    data = request.json
    pom_path = data.get('path')
    page_name = data.get('page')
    
    if not pom_path or not os.path.exists(pom_path) or not page_name:
        return jsonify({'error': 'Invalid POM path or page name'}), 400
    
    try:
        # Find the page file
        page_file = None
        
        # If the path already ends with 'pages', use it directly
        if os.path.basename(pom_path) == 'pages':
            pages_dir = pom_path
        else:
            # Try different possible locations for page objects
            possible_paths = [
                os.path.join(pom_path, 'pages'),
                os.path.join(pom_path, 'features', 'pages')
            ]
            
            pages_dir = None
            for path in possible_paths:
                if os.path.exists(path):
                    pages_dir = path
                    break
            
            if not pages_dir:
                return jsonify({'error': 'Could not find pages directory'}), 404
        
        logger.info(f"Looking for page {page_name} in: {pages_dir}")
        
        # Check direct file
        direct_file = os.path.join(pages_dir, f"{page_name}.js")
        if os.path.exists(direct_file):
            page_file = direct_file
        else:
            # Search in subdirectories
            for root, dirs, files in os.walk(pages_dir):
                for file in files:
                    if file == f"{page_name}.js":
                        page_file = os.path.join(root, file)
                        break
                if page_file:
                    break
        
        if not page_file:
            return jsonify({'error': f'Page file for {page_name} not found'}), 404
        
        # Import our simple POM parser
        from simple_pom_parser import get_page_functions
        
        # Parse the page file to extract functions
        logger.info(f"Parsing page file for functions: {page_file}")
        functions = get_page_functions(page_file)
        
        return jsonify({'functions': functions})
    except Exception as e:
        logger.error(f"Error getting POM functions: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/generate-steps', methods=['POST'])
@llm_rate_limit
def generate_ai_steps():
    data = request.json
    steps = data.get('steps')
    feature_name = data.get('feature_name')
    scenario_name = data.get('scenario_name')
    
    if not steps or not isinstance(steps, list):
        return jsonify({'error': 'Invalid steps data'}), 400
    
    try:
        # Create a prompt for the AI
        prompt = f"""Generate high-quality Cucumber step definitions in JavaScript for the following feature:

Feature: {feature_name}
  Scenario: {scenario_name}
"""
        
        # Add steps to the prompt
        for i, step in enumerate(steps):
            step_text = ""
            
            if step.get('action') == 'navigate':
                step_text = f"Given I navigate to {step.get('page')}"
            elif step.get('action') == 'click':
                step_text = f"When I click the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'fill':
                step_text = f"When I fill the {step.get('element')} with \"{step.get('value')}\" on {step.get('page')}"
            elif step.get('action') == 'select':
                step_text = f"When I select \"{step.get('value')}\" from the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'check':
                step_text = f"When I check the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'verify':
                step_text = f"Then I should see \"{step.get('value')}\" in the {step.get('element')} on {step.get('page')}"
            elif step.get('action') == 'wait':
                step_text = f"When I wait for the {step.get('element')} on {step.get('page')}"
            else:
                step_text = f"When I {step.get('action')} the {step.get('element')} on {step.get('page')}"
            
            prompt += f"\n    {step_text}"
        
        prompt += "\n\nGenerate JavaScript step definitions that use the Page Object Model pattern. Include proper imports, hooks for setup, and well-structured step definitions with async/await. Make sure to handle element selectors properly and include error handling. The step definitions should be compatible with Cucumber.js and Playwright."
        
        # Use Google AI to generate step definitions
        try:
            google_api_key = os.environ.get('GOOGLE_API_KEY')
            google_api_model = os.environ.get('GOOGLE_API_MODEL', 'gemini-pro')
            
            if not google_api_key or not genai:
                # Fall back to basic step definitions if no API key or module
                return generate_basic_step_definitions(steps, feature_name, scenario_name)
            
            # Configure the API
            genai.configure(api_key=google_api_key)
            
            # Set up the model
            model = genai.GenerativeModel(google_api_model)
            
            # Generate content
            system_instruction = "You are an expert test automation engineer specializing in Cucumber.js, Playwright, and Page Object Model pattern."
            
            response = model.generate_content(
                [
                    system_instruction,
                    prompt
                ],
                generation_config={
                    "temperature": 0.2,
                    "max_output_tokens": 2048,
                }
            )
            
            # Extract the generated step definitions
            step_definitions = response.text
            
            # Clean up the response if needed
            if '```javascript' in step_definitions:
                step_definitions = step_definitions.split('```javascript')[1].split('```')[0].strip()
            elif '```js' in step_definitions:
                step_definitions = step_definitions.split('```js')[1].split('```')[0].strip()
            
            return jsonify({
                'step_definitions': step_definitions,
                'ai_generated': True
            })
            
        except Exception as e:
            logger.error(f"Error generating AI step definitions: {str(e)}")
            # Fall back to basic step definitions
            return generate_basic_step_definitions(steps, feature_name, scenario_name)
            
    except Exception as e:
        logger.error(f"Error in generate_ai_steps: {str(e)}")
        return jsonify({'error': str(e)}), 500

def generate_basic_step_definitions(steps, feature_name, scenario_name):
    """Generate basic step definitions without AI"""
    try:
        # Create basic step definitions
        step_defs = "const { Given, When, Then } = require('@cucumber/cucumber');\n\n"
        
        # Add page imports
        unique_pages = set()
        for step in steps:
            if 'page' in step:
                unique_pages.add(step['page'])
        
        for page in unique_pages:
            step_defs += f"const {page} = require('../pages/{page}');\n"
        
        step_defs += "\n// Page objects initialization\nlet pageObjects = {};\n\n"
        step_defs += "// Before hook to initialize page objects\nBefore(async function() {\n"
        step_defs += "  const { page } = this;\n"
        
        for page in unique_pages:
            step_defs += f"  pageObjects.{page} = new {page}(page);\n"
        
        step_defs += "});\n\n"
        
        # Generate step definitions
        step_patterns = set()
        
        for step in steps:
            action = step.get('action', '')
            element = step.get('element', '')
            page = step.get('page', '')
            value = step.get('value', '')
            
            if action == 'navigate':
                pattern = "I navigate to (.*)"
                impl = "async function(page) {\n  await pageObjects[page].navigate();\n}"
                prefix = "Given"
            elif action == 'click':
                pattern = "I click the (.*) on (.*)"
                impl = f"async function(element, page) {{\n  await pageObjects[page].click('{element}');\n}}"
                prefix = "When"
            elif action == 'fill':
                pattern = "I fill the (.*) with \"(.*)\" on (.*)"
                impl = f"async function(element, value, page) {{\n  await pageObjects[page].fill('{element}', value);\n}}"
                prefix = "When"
            elif action == 'select':
                pattern = "I select \"(.*)\" from the (.*) on (.*)"
                impl = f"async function(value, element, page) {{\n  await pageObjects[page].selectOption('{element}', value);\n}}"
                prefix = "When"
            elif action == 'check':
                pattern = "I check the (.*) on (.*)"
                impl = f"async function(element, page) {{\n  await pageObjects[page].check('{element}');\n}}"
                prefix = "When"
            elif action == 'verify':
                pattern = "I should see \"(.*)\" in the (.*) on (.*)"
                impl = f"async function(text, element, page) {{\n  const actualText = await pageObjects[page].getText('{element}');\n  expect(actualText).to.include(text);\n}}"
                prefix = "Then"
            elif action == 'wait':
                pattern = "I wait for the (.*) on (.*)"
                impl = f"async function(element, page) {{\n  await pageObjects[page].waitForElement('{element}');\n}}"
                prefix = "When"
            else:
                pattern = f"I {action} the (.*) on (.*)"
                impl = "async function(element, page) {\n  // Implement custom action\n}"
                prefix = "When"
            
            step_def = f"{prefix}(/^{pattern}$/, {impl});"
            step_patterns.add(step_def)
        
        for step_def in step_patterns:
            step_defs += step_def + "\n\n"
        
        return jsonify({
            'step_definitions': step_defs,
            'ai_generated': False
        })
        
    except Exception as e:
        logger.error(f"Error generating basic step definitions: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pom/save', methods=['POST'])
def save_pom_file():
    data = request.json
    pom_path = data.get('path')
    filename = data.get('filename')
    content = data.get('content')
    file_type = data.get('type')  # 'feature' or 'steps'
    
    if not all([pom_path, filename, content, file_type]):
        return jsonify({'error': 'Missing required parameters'}), 400
    
    try:
        # Handle path that might already include 'features'
        if 'features' in pom_path:
            # Extract the base path (remove everything from 'features' onwards)
            base_path = pom_path.split('features')[0].rstrip('\\')
        else:
            base_path = pom_path
            
        logger.info(f"Base path for saving files: {base_path}")
        
        # Determine the target directory based on file type
        if file_type == 'feature':
            target_dir = os.path.join(base_path, 'features')
        else:  # steps
            target_dir = os.path.join(base_path, 'features', 'step_definitions')
        
        logger.info(f"Saving {file_type} file to: {target_dir}")
        
        # Create directory if it doesn't exist
        os.makedirs(target_dir, exist_ok=True)
        
        # Write the file
        file_path = os.path.join(target_dir, filename)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({'success': True, 'path': file_path})
    except Exception as e:
        logger.error(f"Error saving POM file: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/extract-text', methods=['POST'])
def extract_text_from_document():
    """Extract text from uploaded documents (PDF, Word, etc)"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
        
    file = request.files['file']
    if not file.filename:
        return jsonify({'error': 'No file selected'}), 400
        
    try:
        # Create a temporary file to save the uploaded document
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp:
            file.save(temp.name)
            temp_path = temp.name
        
        extracted_text = ''
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext == '.pdf':
            # Use PyPDF2 to extract text from PDF
            try:
                import PyPDF2
                with open(temp_path, 'rb') as pdf_file:
                    pdf_reader = PyPDF2.PdfReader(pdf_file)
                    for page_num in range(len(pdf_reader.pages)):
                        page = pdf_reader.pages[page_num]
                        extracted_text += page.extract_text() + '\n'
            except ImportError:
                return jsonify({'error': 'PDF extraction library not available'}), 500
                
        elif file_ext in ['.doc', '.docx']:
            # Use python-docx to extract text from Word documents
            try:
                import docx
                doc = docx.Document(temp_path)
                extracted_text = '\n'.join([para.text for para in doc.paragraphs])
            except ImportError:
                return jsonify({'error': 'Word document extraction library not available'}), 500
                
        else:
            # For other file types, try to read as text
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    extracted_text = f.read()
            except UnicodeDecodeError:
                return jsonify({'error': 'Unsupported file format'}), 400
        
        # Clean up the temporary file
        try:
            os.unlink(temp_path)
        except:
            pass
            
        return jsonify({
            'text': extracted_text,
            'filename': file.filename
        })
        
    except Exception as e:
        logger.error(f"Error extracting text from document: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/browseruse/navigation', methods=['POST'])
@llm_rate_limit
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

@app.route('/browseruse-automation', methods=['GET'])
def browseruse_automation_page():
    """Serve the browseruse automation page"""
    return render_template('browseruse-automation-stepwise.html')

@app.route('/api/llm-usage', methods=['GET'])
def check_llm_usage():
    """Check current LLM usage for the user"""
    try:
        user_id = get_user_identifier()
        current_usage, limit = get_user_llm_usage()
        remaining = max(0, limit - current_usage)
        
        user_info = get_user_display_info()
        return jsonify({
            'user': user_info,
            'usage': {
                'used': current_usage,
                'limit': limit,
                'remaining': remaining,
                'percentage': (current_usage / limit) * 100 if limit > 0 else 0
            },
            'reset_time': 'Next day at 00:00 UTC',
            'date': datetime.now().strftime('%Y-%m-%d')
        })
    except Exception as e:
        logger.error(f"Error checking LLM usage: {str(e)}")
        return jsonify({'error': 'Failed to check LLM usage'}), 500

@app.route('/api/llm-usage/reset', methods=['POST'])
def reset_llm_usage():
    """Reset LLM usage for the current user (admin only in production)"""
    try:
        # Only allow reset in development mode for now
        if FLASK_ENV != 'development':
            return jsonify({'error': 'Usage reset is only available in development mode'}), 403
        
        user_id = get_user_identifier()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Reset the user's usage
        user_llm_usage[user_id] = {'count': 0, 'date': today}
        
        logger.info(f"LLM usage reset for user {user_id}")
        user_info = get_user_display_info()
        return jsonify({
            'message': 'LLM usage has been reset successfully',
            'user': user_info,
            'usage': {
                'new_usage': 0,
                'limit': DAILY_LLM_LIMIT,
                'remaining': DAILY_LLM_LIMIT
            },
            'reset_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
        })
    except Exception as e:
        logger.error(f"Error resetting LLM usage: {str(e)}")
        return jsonify({'error': 'Failed to reset LLM usage'}), 500

@app.route('/api/llm-usage/user/<user_id>', methods=['GET'])
def check_llm_usage_for_user(user_id):
    """Check LLM usage for a specific user ID"""
    try:
        # Validate user_id parameter
        if not user_id or len(user_id.strip()) == 0:
            return jsonify({'error': 'User ID is required'}), 400
        
        user_id = user_id.strip()
        today = datetime.now().strftime('%Y-%m-%d')
        user_data = user_llm_usage.get(user_id, {'count': 0, 'date': None})
        
        # Reset count if it's a new day for this user
        if user_data['date'] != today:
            user_data = {'count': 0, 'date': today}
            user_llm_usage[user_id] = user_data
        
        current_usage = user_data['count']
        limit = DAILY_LLM_LIMIT
        remaining = max(0, limit - current_usage)
        
        return jsonify({
            'target_user': {
                'user_id': user_id,
                'display_name': f'User: {user_id}',
                'query_type': 'specific_user'
            },
            'usage': {
                'used': current_usage,
                'limit': limit,
                'remaining': remaining,
                'percentage': (current_usage / limit) * 100 if limit > 0 else 0
            },
            'reset_time': 'Next day at 00:00 UTC',
            'date': today,
            'status': 'within_limit' if remaining > 0 else 'limit_exceeded'
        })
    except Exception as e:
        logger.error(f"Error checking LLM usage for user {user_id}: {str(e)}")
        return jsonify({'error': 'Failed to check LLM usage for user'}), 500

@app.route('/api/llm-usage/reset/<user_id>', methods=['POST'])
def reset_llm_usage_for_user(user_id):
    """Reset LLM usage for a specific user ID (development mode only)"""
    try:
        # Check if feature is enabled (development mode only)
        if FLASK_ENV != 'development':
            return jsonify({'error': 'Reset user usage feature is only available in development mode.'}), 403
        
        # Validate user_id parameter
        if not user_id or len(user_id.strip()) == 0:
            return jsonify({'error': 'User ID is required'}), 400
        
        user_id = user_id.strip()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Reset the user's usage
        user_llm_usage[user_id] = {'count': 0, 'date': today}
        
        logger.info(f"LLM usage reset for user {user_id} by admin")
        return jsonify({
            'message': f'LLM usage has been reset successfully for user: {user_id}',
            'target_user': {
                'user_id': user_id,
                'display_name': f'User: {user_id}',
                'reset_by': 'administrator'
            },
            'usage': {
                'new_usage': 0,
                'limit': DAILY_LLM_LIMIT,
                'remaining': DAILY_LLM_LIMIT
            },
            'reset_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
            'environment': FLASK_ENV
        })
    except Exception as e:
        logger.error(f"Error resetting LLM usage for user {user_id}: {str(e)}")
        return jsonify({'error': 'Failed to reset LLM usage for user'}), 500

# =============================================================================
# BUG BUILDER ROUTES
# =============================================================================

# Bug Builder Models
class BugSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_id = db.Column(db.String(100), unique=True, nullable=False)
    video_path = db.Column(db.String(500))
    annotations = db.Column(db.Text)  # JSON string
    action_logs = db.Column(db.Text)  # JSON string
    bug_report = db.Column(db.Text)  # JSON string
    jira_issue_key = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default='recording')  # recording, processing, completed

@app.route('/bug-builder')
def bug_builder():
    """Bug Builder main page"""
    return render_template('bug-builder.html', active_tab='bug-builder')

@app.route('/api/bug-builder/start-session', methods=['POST'])
def start_bug_session():
    """Initialize a new bug recording session"""
    try:
        data = request.get_json()
        user_id = get_user_identifier()
        
        # Generate unique session ID
        import uuid
        session_id = str(uuid.uuid4())
        
        # Create new session
        session = BugSession(
            user_id=user_id,
            session_id=session_id,
            status='recording'
        )
        db.session.add(session)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'session_id': session_id
        })
        
    except Exception as e:
        logger.error(f"Error starting bug session: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/bug-builder/process-recording', methods=['POST'])
@llm_rate_limit
def process_bug_recording():
    """Process recorded video and generate bug report using AI"""
    try:
        session_id = request.form.get('session_id')
        annotations = json.loads(request.form.get('annotations', '[]'))
        action_logs = json.loads(request.form.get('actions', '[]'))
        
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Save video file
        video_file = request.files.get('video')
        if video_file:
            import os
            video_filename = f"bug_recording_{session_id}.webm"
            video_path = os.path.join('uploads', video_filename)
            
            # Ensure uploads directory exists
            os.makedirs('uploads', exist_ok=True)
            video_file.save(video_path)
            session.video_path = video_path
        
        # Update session with data
        session.annotations = json.dumps(annotations)
        session.action_logs = json.dumps(action_logs)
        session.status = 'processing'
        db.session.commit()
        
        # Generate bug report using AI
        bug_report = generate_ai_bug_report(action_logs, annotations)
        
        # Save bug report
        session.bug_report = json.dumps(bug_report)
        session.status = 'completed'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'bug_report': bug_report
        })
        
    except Exception as e:
        logger.error(f"Error processing bug recording: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def generate_ai_bug_report(action_logs, annotations):
    """Generate bug report using AI analysis"""
    try:
        # Prepare context for AI
        context = {
            'actions': action_logs,
            'annotations': annotations,
            'total_actions': len(action_logs),
            'total_annotations': len(annotations)
        }
        
        # Create prompt for AI
        action_summary = analyze_action_patterns(action_logs)
        
        prompt = f"""
Analyze this comprehensive bug recording data and generate a detailed bug report.

=== RECORDING SUMMARY ===
Total Actions Recorded: {len(action_logs)}
User Annotations: {len(annotations)}
Recording Duration: {action_logs[-1]['timestamp'] if action_logs else 0}ms

=== ACTION ANALYSIS ===
{action_summary}

=== DETAILED ACTION LOG ===
{format_action_logs_for_ai(action_logs[:15])}

=== USER ANNOTATIONS ===
{format_annotations_for_ai(annotations)}

=== ANALYSIS REQUIREMENTS ===
Generate a comprehensive bug report with:
1. Clear, descriptive title that captures the core issue
2. Detailed description including context and impact
3. Step-by-step reproduction steps (extracted from actions)
4. Expected vs actual results (from annotations and behavior)
5. Priority assessment based on error severity and user impact
6. Technical details (API calls, errors, data mismatches)

Pay special attention to:
- Behavioral issues where data doesn't match expectations
- API response inconsistencies
- JavaScript errors or console warnings
- Form submission issues
- Navigation problems
- Performance or timing issues

Format the response as a structured bug report.
"""
        
        # Use Google AI if available
        if genai:
            model = genai.GenerativeModel('gemini-pro')
            response = model.generate_content(prompt)
            ai_analysis = response.text
        else:
            # Fallback to basic analysis
            ai_analysis = generate_basic_bug_report(action_logs, annotations)
        
        # Parse AI response into structured format
        bug_report = parse_ai_bug_report(ai_analysis, action_logs, annotations)
        
        return bug_report
        
    except Exception as e:
        logger.error(f"Error generating AI bug report: {str(e)}")
        return generate_basic_bug_report(action_logs, annotations)

def analyze_action_patterns(action_logs):
    """Analyze action patterns to identify potential issues"""
    if not action_logs:
        return "No actions recorded."
    
    analysis = []
    
    # Count action types
    action_counts = {}
    error_count = 0
    api_calls = 0
    form_submissions = 0
    navigation_count = 0
    
    for action in action_logs:
        action_type = action.get('type', 'unknown')
        action_counts[action_type] = action_counts.get(action_type, 0) + 1
        
        if action_type in ['javascript_error', 'console_error', 'unhandled_promise_rejection']:
            error_count += 1
        elif action_type in ['xhr_request', 'fetch_request']:
            api_calls += 1
        elif action_type == 'submit':
            form_submissions += 1
        elif action_type == 'navigation':
            navigation_count += 1
    
    # Generate analysis summary
    analysis.append(f"Action Types: {', '.join([f'{k}: {v}' for k, v in sorted(action_counts.items())])}")
    
    if error_count > 0:
        analysis.append(f"⚠️ {error_count} JavaScript/Console errors detected")
    
    if api_calls > 0:
        analysis.append(f"🌐 {api_calls} API calls made")
        
        # Analyze API response patterns
        failed_apis = []
        for action in action_logs:
            if action.get('type') in ['xhr_response', 'fetch_response']:
                status = action.get('status', 0)
                if status >= 400:
                    failed_apis.append(f"{action.get('method', 'GET')} {action.get('url', 'unknown')} ({status})")
        
        if failed_apis:
            analysis.append(f"❌ Failed API calls: {', '.join(failed_apis[:3])}")
    
    if form_submissions > 0:
        analysis.append(f"📝 {form_submissions} form submissions")
    
    if navigation_count > 0:
        analysis.append(f"🔄 {navigation_count} page navigations")
    
    # Identify potential issues
    issues = []
    
    # Check for rapid clicking (potential UI responsiveness issue)
    click_times = [action['timestamp'] for action in action_logs if action.get('type') == 'click']
    if len(click_times) > 1:
        rapid_clicks = sum(1 for i in range(1, len(click_times)) if click_times[i] - click_times[i-1] < 500)
        if rapid_clicks > 2:
            issues.append(f"Rapid clicking detected ({rapid_clicks} instances) - possible UI responsiveness issue")
    
    # Check for repeated actions (potential confusion)
    repeated_actions = {}
    for action in action_logs:
        if action.get('type') in ['click', 'input']:
            target = str(action.get('target', ''))
            repeated_actions[target] = repeated_actions.get(target, 0) + 1
    
    high_repeat = [target for target, count in repeated_actions.items() if count > 3]
    if high_repeat:
        issues.append(f"Repeated interactions with same elements: {len(high_repeat)} elements")
    
    if issues:
        analysis.append("\n🔍 Potential Issues Identified:")
        analysis.extend([f"  - {issue}" for issue in issues])
    
    return '\n'.join(analysis)

def format_action_logs_for_ai(actions):
    """Format action logs for AI analysis with enhanced detail"""
    formatted = []
    for i, action in enumerate(actions):
        timestamp = action.get('timestamp', 0)
        action_type = action.get('type', 'unknown')
        
        if action_type == 'click':
            target = action.get('target', {})
            if isinstance(target, dict):
                element_desc = get_element_description(target)
                coords = action.get('coordinates', {})
                formatted.append(f"{i+1}. [{timestamp}ms] Click on {element_desc} at ({coords.get('x', 0)}, {coords.get('y', 0)})")
            else:
                formatted.append(f"{i+1}. [{timestamp}ms] Click on {target}")
                
        elif action_type == 'input':
            target = action.get('target', {})
            value = action.get('value', '')
            if isinstance(target, dict):
                element_desc = get_element_description(target)
                formatted.append(f"{i+1}. [{timestamp}ms] Input '{value[:30]}' in {element_desc}")
            else:
                formatted.append(f"{i+1}. [{timestamp}ms] Input '{value[:30]}' in {target}")
                
        elif action_type in ['xhr_request', 'fetch_request']:
            method = action.get('method', 'GET')
            url = action.get('url', 'unknown')
            formatted.append(f"{i+1}. [{timestamp}ms] API {method} request to {url}")
            
        elif action_type in ['xhr_response', 'fetch_response']:
            method = action.get('method', 'GET')
            url = action.get('url', 'unknown')
            status = action.get('status', 'unknown')
            formatted.append(f"{i+1}. [{timestamp}ms] API {method} response from {url} (Status: {status})")
            
        elif action_type in ['javascript_error', 'console_error']:
            message = action.get('message', 'Unknown error')
            formatted.append(f"{i+1}. [{timestamp}ms] ❌ Error: {message[:50]}")
            
        elif action_type == 'navigation':
            from_url = action.get('fromUrl', '')
            to_url = action.get('toUrl', '')
            formatted.append(f"{i+1}. [{timestamp}ms] Navigate from {from_url} to {to_url}")
            
        elif action_type == 'submit':
            target = action.get('target', {})
            if isinstance(target, dict):
                element_desc = get_element_description(target)
                formatted.append(f"{i+1}. [{timestamp}ms] Submit {element_desc}")
            else:
                formatted.append(f"{i+1}. [{timestamp}ms] Submit form")
                
        else:
            formatted.append(f"{i+1}. [{timestamp}ms] {action_type} on {action.get('target', 'unknown')}")
    
    return '\n'.join(formatted)

def format_annotations_for_ai(annotations):
    """Format annotations for AI analysis"""
    if not annotations:
        return "No user annotations provided."
    
    formatted = []
    for i, annotation in enumerate(annotations, 1):
        formatted.append(f"{i}. At {annotation['timestamp']}ms: {annotation['text']}")
    return '\n'.join(formatted)

def parse_ai_bug_report(ai_text, action_logs, annotations):
    """Parse AI-generated text into structured bug report"""
    # Basic parsing - can be enhanced with more sophisticated NLP
    lines = ai_text.split('\n')
    
    bug_report = {
        'title': 'Bug Report Generated from Recording',
        'description': ai_text[:500] + '...' if len(ai_text) > 500 else ai_text,
        'steps_to_reproduce': extract_steps_from_actions(action_logs),
        'expected_result': extract_expected_from_annotations(annotations),
        'actual_result': extract_actual_from_annotations(annotations),
        'priority': 'medium',
        'evidence': [
            {'type': 'video', 'name': 'Screen Recording', 'description': 'Complete user session recording'},
            {'type': 'logs', 'name': 'Action Logs', 'description': f'{len(action_logs)} user interactions captured'},
            {'type': 'annotations', 'name': 'User Notes', 'description': f'{len(annotations)} behavioral observations'}
        ]
    }
    
    # Try to extract title from AI response
    for line in lines:
        if 'title:' in line.lower() or line.startswith('#'):
            bug_report['title'] = line.replace('Title:', '').replace('#', '').strip()
            break
    
    return bug_report

def extract_steps_from_actions(action_logs):
    """Convert comprehensive action logs to detailed reproduction steps"""
    steps = []
    step_num = 1
    
    # Group related actions and create meaningful steps
    i = 0
    while i < len(action_logs) and step_num <= 20:  # Limit to 20 steps
        action = action_logs[i]
        
        if action['type'] == 'navigation':
            steps.append(f"{step_num}. Navigate to {action.get('toUrl', action.get('url', 'page'))}")
            step_num += 1
            
        elif action['type'] == 'click':
            target_info = action.get('target', {})
            if isinstance(target_info, dict):
                element_desc = get_element_description(target_info)
                coordinates = action.get('coordinates', {})
                steps.append(f"{step_num}. Click on {element_desc}")
            else:
                steps.append(f"{step_num}. Click on {target_info}")
            step_num += 1
            
        elif action['type'] == 'input' and action.get('value'):
            target_info = action.get('target', {})
            value = action.get('value', '')
            if isinstance(target_info, dict):
                element_desc = get_element_description(target_info)
                if value != '[SENSITIVE_DATA_HIDDEN]':
                    steps.append(f"{step_num}. Enter '{value[:50]}' in {element_desc}")
                else:
                    steps.append(f"{step_num}. Enter sensitive data in {element_desc}")
            else:
                steps.append(f"{step_num}. Enter '{value[:50]}' in {target_info}")
            step_num += 1
            
        elif action['type'] == 'submit':
            target_info = action.get('target', {})
            if isinstance(target_info, dict):
                element_desc = get_element_description(target_info)
                steps.append(f"{step_num}. Submit {element_desc}")
            else:
                steps.append(f"{step_num}. Submit form")
            step_num += 1
        
        i += 1
    
    return '\n'.join(steps) if steps else 'Steps will be extracted from recording analysis'

def get_element_description(target_info):
    """Generate human-readable description of an element"""
    if not isinstance(target_info, dict):
        return str(target_info)
    
    # Priority order for element identification
    if target_info.get('id'):
        return f"element with ID '{target_info['id']}'"
    elif target_info.get('name'):
        return f"'{target_info['name']}' field"
    elif target_info.get('placeholder'):
        return f"field with placeholder '{target_info['placeholder']}'"
    elif target_info.get('text') and len(target_info['text'].strip()) > 0:
        return f"'{target_info['text'][:30]}' element"
    elif target_info.get('type'):
        return f"{target_info['type']} input"
    elif target_info.get('tagName'):
        return f"{target_info['tagName']} element"
    else:
        return "element"

def extract_expected_from_annotations(annotations):
    """Extract expected behavior from user annotations"""
    expected_parts = []
    for annotation in annotations:
        text = annotation['text'].lower()
        if 'expected' in text or 'should' in text:
            expected_parts.append(annotation['text'])
    
    return ' '.join(expected_parts) if expected_parts else 'Expected behavior as per requirements'

def extract_actual_from_annotations(annotations):
    """Extract actual behavior from user annotations"""
    actual_parts = []
    for annotation in annotations:
        text = annotation['text'].lower()
        if 'actual' in text or 'but' in text or 'instead' in text:
            actual_parts.append(annotation['text'])
    
    return ' '.join(actual_parts) if actual_parts else 'Actual behavior differs from expected'

def generate_basic_bug_report(action_logs, annotations):
    """Generate basic bug report without AI"""
    return {
        'title': f'Bug Report - {len(action_logs)} actions recorded',
        'description': f'Bug identified during testing session with {len(annotations)} user observations.',
        'steps_to_reproduce': extract_steps_from_actions(action_logs),
        'expected_result': extract_expected_from_annotations(annotations),
        'actual_result': extract_actual_from_annotations(annotations),
        'priority': 'medium',
        'evidence': [
            {'type': 'video', 'name': 'Screen Recording'},
            {'type': 'logs', 'name': f'{len(action_logs)} Action Logs'},
            {'type': 'annotations', 'name': f'{len(annotations)} User Notes'}
        ]
    }

@app.route('/api/bug-builder/upload-video', methods=['POST'])
def upload_bug_video():
    """Upload video for preview"""
    try:
        session_id = request.form.get('session_id')
        if not session_id:
            return jsonify({'success': False, 'error': 'Session ID required'}), 400
        
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'success': False, 'error': 'Unauthorized'}), 403
        
        # Save video file
        video_file = request.files.get('video')
        if video_file:
            import os
            video_filename = f"bug_recording_{session_id}.webm"
            video_path = os.path.join('uploads', video_filename)
            
            # Ensure uploads directory exists
            os.makedirs('uploads', exist_ok=True)
            video_file.save(video_path)
            
            # Update session with video path
            session.video_path = video_path
            db.session.commit()
            
            return jsonify({
                'success': True,
                'video_url': f'/api/bug-builder/video/{session_id}'
            })
        else:
            return jsonify({'success': False, 'error': 'No video file provided'}), 400
            
    except Exception as e:
        logger.error(f"Error uploading video: {str(e)}")
        return jsonify({'success': False, 'error': 'Failed to upload video'}), 500

@app.route('/api/bug-builder/video/<session_id>')
def serve_bug_video(session_id):
    """Serve recorded video for preview"""
    try:
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session or not session.video_path:
            return jsonify({'error': 'Video not found'}), 404
        
        # Check if user owns this session
        user_id = get_user_identifier()
        if session.user_id != user_id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        # Serve video file
        import os
        if os.path.exists(session.video_path):
            return send_file(session.video_path, mimetype='video/webm')
        else:
            return jsonify({'error': 'Video file not found'}), 404
            
    except Exception as e:
        logger.error(f"Error serving video: {str(e)}")
        return jsonify({'error': 'Failed to serve video'}), 500

@app.route('/api/bug-builder/submit-to-jira', methods=['POST'])
@jira_auth_required
def submit_bug_to_jira():
    """Submit bug report to Jira"""
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        # Get session
        session = BugSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Get Jira credentials from session
        jira_token = session.get('jira_access_token')
        jira_site = session.get('jira_site')
        
        if not jira_token or not jira_site:
            return jsonify({'success': False, 'error': 'Jira authentication required'}), 401
        
        # Prepare Jira issue data
        issue_data = {
            "fields": {
                "project": {"key": "TEST"},  # Default project, should be configurable
                "summary": data.get('title', 'Bug Report from Co-Tester'),
                "description": format_jira_description(data),
                "issuetype": {"name": "Bug"},
                "priority": {"name": data.get('priority', 'Medium').title()}
            }
        }
        
        # Create Jira issue
        jira_response = requests.post(
            f"https://{jira_site}.atlassian.net/rest/api/3/issue",
            headers={
                'Authorization': f'Bearer {jira_token}',
                'Content-Type': 'application/json'
            },
            json=issue_data
        )
        
        if jira_response.status_code == 201:
            issue_key = jira_response.json()['key']
            
            # Update session with Jira issue key
            session.jira_issue_key = issue_key
            db.session.commit()
            
            return jsonify({
                'success': True,
                'jira_key': issue_key,
                'jira_url': f"https://{jira_site}.atlassian.net/browse/{issue_key}"
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Jira API error: {jira_response.text}'
            }), 400
            
    except Exception as e:
        logger.error(f"Error submitting to Jira: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

def format_jira_description(bug_data):
    """Format bug report for Jira description"""
    description = f"""
*Description:*
{bug_data.get('description', '')}

*Steps to Reproduce:*
{bug_data.get('steps_to_reproduce', '')}

*Expected Result:*
{bug_data.get('expected_result', '')}

*Actual Result:*
{bug_data.get('actual_result', '')}

*Generated by:* Co-Tester Bug Builder
*Session ID:* {bug_data.get('session_id', '')}
"""
    return description

# Create tables for bug builder
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
