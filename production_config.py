# Production Configuration for Bulk Test Generator

# Rate limiting for API endpoints
BULK_GENERATOR_RATE_LIMITS = {
    'validate_jql': '10 per minute',
    'fetch_stories': '5 per minute', 
    'generate_tests': '2 per minute'
}

# Batch processing limits
MAX_STORIES_PER_SESSION = 100  # Limit to prevent overwhelming AI API
MAX_CONCURRENT_GENERATIONS = 5  # Process stories in batches
GENERATION_TIMEOUT_MINUTES = 30  # Timeout for long-running sessions

# AI API configuration
AI_REQUEST_TIMEOUT = 60  # seconds
AI_RETRY_ATTEMPTS = 3
AI_BACKOFF_FACTOR = 2

# Database connection pooling (if using PostgreSQL)
SQLALCHEMY_ENGINE_OPTIONS = {
    'pool_size': 10,
    'pool_recycle': 3600,
    'pool_pre_ping': True
}

# Logging configuration
BULK_GENERATOR_LOG_LEVEL = 'INFO'
LOG_FILE_PATH = '/var/log/co-test/bulk_generator.log'

# Security settings
JIRA_API_TIMEOUT = 30  # seconds
MAX_JQL_QUERY_LENGTH = 2000  # characters
ALLOWED_JIRA_DOMAINS = ['your-company.atlassian.net']  # Whitelist domains
