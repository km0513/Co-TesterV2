import os
import base64
os.environ["PLAYWRIGHT_HEADLESS"] = "true"
from dotenv import load_dotenv
load_dotenv()  # This will load variables from .env into os.environ
import logging

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

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.secret_key = os.environ.get('SECRET_KEY', 'devsecret')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
CORS(app, supports_credentials=True)
db = SQLAlchemy(app)

# Configure Google Generative AI
genai.configure(api_key=os.environ.get('GOOGLE_API_KEY'))
model_name = os.environ.get('GOOGLE_API_MODEL', 'gemini-pro-vision')
login_manager = LoginManager(app)
oauth = OAuth(app)

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

@app.route('/code')
def code():
    return render_template('code.html', active_tab='api')



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

@app.route('/manual-co-test')
def manual_co_test():
    return render_template('manual-test-generator.html', active_tab='manual')

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
    
    # Extract body - look for -d or --data or --data-raw
    body_match = re.search(r'-d\s+[\'"](.*?)[\'"]\s|--data\s+[\'"](.*?)[\'"]\s|--data-raw\s+[\'"](.*?)[\'"]\s', curl + ' ')
    if body_match:
        # Get the first non-None group
        for group in body_match.groups():
            if group is not None:
                result['body'] = group
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
from flask import send_from_directory
from werkzeug.utils import secure_filename

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': 'File type not allowed'}), 400
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)
    url = f'/uploads/{filename}'
    return jsonify({'url': url})

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

# Add this helper function near the top (with other helpers)
def chunk_text(text, chunk_size=15000, overlap=1000):
    """Yield successive chunk_size character chunks from text, with optional overlap."""
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        yield text[start:end]
        start += chunk_size - overlap  # overlap to preserve context continuity

@app.route('/api/generate-testcases', methods=['POST'])
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
        if visual_image_urls:
            all_image_urls.extend(visual_image_urls)
        if jira_image_urls:
            all_image_urls.extend(jira_image_urls)
        if all_image_urls:
            visual_section += (
                "Refer to the following UI image(s) that show screen layout, component states, and user flow:\n" +
                "\n".join(all_image_urls) + "\n"
                "Use these visuals to derive field visibility, workflows, and validation points.\n\n"
            )

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
                    "As a senior QA engineer specializing in functional testing, your task is to create a comprehensive and exhaustive set of manual test scenarios for the following functionality. "
                    "Consider all relevant aspects, including API interactions (if applicable), UI/UX elements (if present), and underlying logic. "
                    "Each test scenario must be represented as a JSON object with exactly three keys: "
                    "'step' (describing the precise action to be performed or the initial system state), "
                    "'expected' (detailing the exact, verifiable outcome), and "
                    "'estimate_minutes' (a realistic estimate of how long it will take to execute the test manually, including setup, execution, validation, and evidence capture). "
                    "IMPORTANT: The value of 'estimate_minutes' must be either 5, 10, or 15. No other values are allowed.\n\n"
                    "Choose the time estimate based on complexity:\n"
                    "- Use 5 minutes for very simple validations (e.g., filters, button visibility).\n"
                    "- Use 10 minutes for moderate checks involving user actions and validations.\n"
                    "- Use 15 minutes for end-to-end flows or multi-step functional scenarios.\n\n"
                    "Your test scenarios should thoroughly cover:\n"
                    "- Core functional workflows and happy path scenarios\n"
                    "- Edge cases and boundary conditions\n"
                    "- Negative test cases with invalid inputs or unexpected actions\n"
                    "- Data validation (input/output)\n"
                    "- API behavior (if applicable)\n"
                    "- UI/UX expectations (element visibility, user feedback, error handling)\n"
                    "- Any implicit logic or dependencies derived from the description\n\n"
                    "Do NOT assume anything beyond the scope of the described functionality (e.g., login, unrelated modules).\n"
                    "The final output MUST be a single JSON array containing only test case objects. Each object must strictly follow this format:\n"
                    "{'step': '...', 'expected': '...', 'estimate_minutes': 15}\n"
                    "Do NOT include extra fields, comments, headings, or explanations.\n\n"
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
            "As a senior QA engineer specializing in functional testing, your task is to create a comprehensive and exhaustive set of manual test scenarios for the following functionality. "
            "Consider all relevant aspects, including API interactions (if applicable), UI/UX elements (if present), and underlying logic. "
            "Each test scenario must be represented as a JSON object with exactly three keys: "
            "'step' (describing the precise action to be performed or the initial system state), "
            "'expected' (detailing the exact, verifiable outcome), and "
            "'estimate_minutes' (a realistic estimate of how long it will take to execute the test manually, including setup, execution, validation, and evidence capture). "
            "IMPORTANT: The value of 'estimate_minutes' must be either 5, 10, or 15. No other values are allowed.\n\n"
            "Choose the time estimate based on complexity:\n"
            "- Use 5 minutes for very simple validations (e.g., filters, button visibility).\n"
            "- Use 10 minutes for moderate checks involving user actions and validations.\n"
            "- Use 15 minutes for end-to-end flows or multi-step functional scenarios.\n\n"
            "Your test scenarios should thoroughly cover:\n"
            "- Core functional workflows and happy path scenarios\n"
            "- Edge cases and boundary conditions\n"
            "- Negative test cases with invalid inputs or unexpected actions\n"
            "- Data validation (input/output)\n"
            "- API behavior (if applicable)\n"
            "- UI/UX expectations (element visibility, user feedback, error handling)\n"
            "- Any implicit logic or dependencies derived from the description\n\n"
            "Do NOT assume anything beyond the scope of the described functionality (e.g., login, unrelated modules).\n"
            "The final output MUST be a single JSON array containing only test case objects. Each object must strictly follow this format:\n"
            "{'step': '...', 'expected': '...', 'estimate_minutes': 15}\n"
            "Do NOT include extra fields, comments, headings, or explanations.\n\n"
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
        return f"Token exchange failed: {resp.text}", 400
    tokens = resp.json()
    
    # Store both access and refresh tokens
    session['jira_access_token'] = tokens['access_token']
    session['jira_refresh_token'] = tokens.get('refresh_token')
    session['jira_token_expires'] = time.time() + tokens.get('expires_in', 3600)
    
    # For Upgrad Jira, we know the domain
    session['jira_domain'] = 'https://upgrad-jira.atlassian.net'
    
    # Get and store the cloud ID
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
        if cloud_id_data and isinstance(cloud_id_data, list) and len(cloud_id_data) > 0:
            session['jira_cloud_id'] = cloud_id_data[0]['id']
            logger.info(f"Stored Jira cloud ID: {cloud_id_data[0]['id']}")
            logger.info(f"Using Jira domain: {session['jira_domain']}")
    
    return redirect(url_for('manual_co_test'))

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
            jql_parts.append(f'key = {search}')
        else:
            # Otherwise use the regular search parameters
            if project:
                jql_parts.append(f'project = {project}')
            if status:
                jql_parts.append(f'status = {status}')
            if search:
                jql_parts.append(f'text ~ "{search}"')
        
        jql = ' AND '.join(jql_parts) if jql_parts else 'ORDER BY created DESC'
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
                'description_html': description_html,
                'status': (fields.get('status') or {}).get('name'),
                'assignee': (fields.get('assignee') or {}).get('displayName'),
                'created': fields.get('created'),
                'updated': fields.get('updated'),
                'url': f"{domain}/browse/{issue_key}" if issue_key else None
            })

        return jsonify({
            'issues': issues,
            'total': data.get('total', 0)
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

@app.route('/data')
def data_generator():
    return render_template('data-generation.html', active_tab='data')

@app.route('/data-generation')
def data_generation():
    return render_template('data-generation.html')

def extract_issues_manually(text):
    """
    Extract issues and recommendations from raw AI response text when JSON parsing fails.
    Uses regex patterns to find issues and recommendations in the text.
    """
    logger.info("Attempting to extract issues manually from text")
    
    result = {
        'issues': [],
        'recommendations': []
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

@app.route('/screen-analysis')
def screen_analysis():
    return render_template('screen-analysis.html', active_tab='screen-analysis')

@app.route('/api/analyze-screen', methods=['POST'])
def analyze_screen():
    data = request.get_json()
    
    if not data or 'screenshot' not in data:
        return jsonify({'error': 'No screenshot data provided'}), 400
    
    try:
        # Extract image data from base64 string
        image_data = data['screenshot']
        if image_data.startswith('data:image'):
            # Remove the data URL prefix
            image_data = image_data.split(',')[1]
        
        # Decode base64 image
        image_bytes = base64.b64decode(image_data)
        
        # Create a temporary file to save the image
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as temp_file:
            temp_file.write(image_bytes)
            temp_path = temp_file.name
        
        # Open image with PIL for analysis
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
        
        # Get analysis options
        options = data.get('options', {})
        
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
        prompt += "1. 'issues': Array of objects with {title, severity (High/Medium/Low), description, location}\n"
        prompt += "2. 'recommendations': Array of specific improvement suggestions\n\n"
        prompt += "Example response format:\n"
        prompt += "```json\n{"
        prompt += "\n  \"issues\": [\n    {\"title\": \"Issue Title\", \"severity\": \"Medium\", \"description\": \"Detailed description\", \"location\": \"Top navigation bar\"}\n  ],"
        prompt += "\n  \"recommendations\": [\"Specific recommendation 1\", \"Specific recommendation 2\"]\n}"
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
            
            # Load the image for Gemini
            image_parts = [
                {"mime_type": "image/png", "data": open(temp_path, "rb").read()}
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
                'recommendations': []
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
            # Create a default response with the error
            ai_results = {
                'issues': [{
                    'title': 'Response Parsing Error',
                    'severity': 'Medium',
                    'description': f"Could not parse the AI analysis response: {str(e)}",
                    'location': 'Unknown'
                }],
                'recommendations': ['Try again with a clearer screenshot or check system logs for details.']
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
            
        # Clean up temporary file before returning response
        try:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception as e:
            logger.warning(f"Failed to clean up temporary file: {str(e)}")
        
        # Return combined results
        response_data = {
            'issues': ai_results.get('issues', []),
            'recommendations': ai_results.get('recommendations', [])
        }
        
        # Only include OCR text if it's available and not empty
        if ocr_available and ocr_text and ocr_text.strip():
            response_data['ocr_text'] = ocr_text
        else:
            # Don't include OCR text field at all
            logger.info("OCR text not available or empty, excluding from response")
            
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Error in screen analysis: {str(e)}")
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

def find_available_port():
    """Find and return an available port by letting OS assign one"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('', 0))
    port = sock.getsockname()[1]
    sock.close()
    return port

if __name__ == '__main__':
    port = int(os.environ.get('PORT', find_available_port()))
    print(f"Starting server on port {port}")
    app.run(debug=True, host='0.0.0.0', port=port)
