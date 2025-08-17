#!/usr/bin/env python3
"""
Production deployment script for Bulk Test Generator
Applies necessary production configurations and optimizations
"""

import os
import sys
import sqlite3
from datetime import datetime

def apply_production_optimizations():
    """Apply production-specific optimizations to app.py"""
    
    optimizations = [
        {
            'file': 'app.py',
            'changes': [
                # Add rate limiting imports
                'from flask_limiter import Limiter\nfrom flask_limiter.util import get_remote_address',
                
                # Add bulk generator rate limiting
                '''
# Rate limiting for bulk generator
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Apply specific limits to bulk generator endpoints
@limiter.limit("10 per minute")
@app.route('/api/bulk-generator/validate-jql', methods=['POST'])

@limiter.limit("5 per minute") 
@app.route('/api/bulk-generator/fetch-stories', methods=['POST'])

@limiter.limit("2 per minute")
@app.route('/api/bulk-generator/generate-tests', methods=['POST'])
''',
                
                # Add batch processing for story generation
                '''
def generate_bulk_tests_batched(session_id, batch_size=5):
    """Generate test cases in batches to prevent API overload"""
    bulk_session = JQLSession.query.filter_by(session_id=session_id).first()
    stories = JQLStory.query.filter_by(session_id=bulk_session.id).all()
    
    # Process in batches
    for i in range(0, len(stories), batch_size):
        batch = stories[i:i + batch_size]
        for story in batch:
            try:
                story.test_generation_status = 'generating'
                db.session.commit()
                
                test_cases = generate_test_cases_for_story(story)
                story.test_cases = json.dumps(test_cases)
                story.test_generation_status = 'completed'
                story.generated_at = datetime.utcnow()
                bulk_session.processed_stories += 1
                
            except Exception as e:
                logger.error(f"Error generating tests for {story.jira_key}: {str(e)}")
                story.test_generation_status = 'failed'
                story.generation_error = str(e)
                bulk_session.failed_stories += 1
            
            db.session.commit()
        
        # Add delay between batches to respect API limits
        import time
        time.sleep(2)
''',
                
                # Add session cleanup
                '''
def cleanup_old_sessions():
    """Clean up sessions older than 24 hours"""
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(hours=24)
    
    old_sessions = JQLSession.query.filter(
        JQLSession.created_at < cutoff,
        JQLSession.status.in_(['completed', 'failed'])
    ).all()
    
    for session in old_sessions:
        db.session.delete(session)
    
    db.session.commit()
    logger.info(f"Cleaned up {len(old_sessions)} old sessions")
'''
            ]
        }
    ]
    
    return optimizations

def create_production_migration():
    """Create production database migration"""
    migration_sql = """
    -- Production migration for Bulk Test Generator
    -- Run this on your production database
    
    BEGIN TRANSACTION;
    
    -- Create tables if they don't exist
    CREATE TABLE IF NOT EXISTS jql_session (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        session_id VARCHAR(100) UNIQUE NOT NULL,
        jql_query TEXT NOT NULL,
        jira_project_url VARCHAR(500),
        total_stories INTEGER DEFAULT 0,
        processed_stories INTEGER DEFAULT 0,
        failed_stories INTEGER DEFAULT 0,
        status VARCHAR(20) DEFAULT 'created',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        completed_at DATETIME,
        FOREIGN KEY (user_id) REFERENCES user (id)
    );
    
    CREATE TABLE IF NOT EXISTS jql_story (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        jira_key VARCHAR(50) NOT NULL,
        title VARCHAR(500) NOT NULL,
        description TEXT,
        story_type VARCHAR(50),
        priority VARCHAR(20),
        status VARCHAR(50),
        assignee VARCHAR(100),
        labels TEXT,
        components TEXT,
        acceptance_criteria TEXT,
        test_generation_status VARCHAR(20) DEFAULT 'pending',
        test_cases TEXT,
        generation_error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        generated_at DATETIME,
        FOREIGN KEY (session_id) REFERENCES jql_session (id) ON DELETE CASCADE
    );
    
    -- Create performance indexes
    CREATE INDEX IF NOT EXISTS idx_jql_session_user_id ON jql_session (user_id);
    CREATE INDEX IF NOT EXISTS idx_jql_session_session_id ON jql_session (session_id);
    CREATE INDEX IF NOT EXISTS idx_jql_session_created_at ON jql_session (created_at);
    CREATE INDEX IF NOT EXISTS idx_jql_story_session_id ON jql_story (session_id);
    CREATE INDEX IF NOT EXISTS idx_jql_story_jira_key ON jql_story (jira_key);
    CREATE INDEX IF NOT EXISTS idx_jql_story_generation_status ON jql_story (test_generation_status);
    
    COMMIT;
    """
    
    with open('production_migration.sql', 'w') as f:
        f.write(migration_sql)
    
    print("✅ Created production_migration.sql")

def create_deployment_checklist():
    """Create deployment checklist"""
    checklist = """
# 🚀 PRODUCTION DEPLOYMENT CHECKLIST

## Pre-Deployment
- [ ] Run database migration: `psql -d your_db < production_migration.sql`
- [ ] Set environment variables:
  - [ ] GOOGLE_API_KEY
  - [ ] GOOGLE_API_MODEL  
  - [ ] FLASK_ENV=production
  - [ ] SECRET_KEY
- [ ] Install rate limiting: `pip install Flask-Limiter`
- [ ] Configure logging and monitoring
- [ ] Set up SSL certificates
- [ ] Configure reverse proxy (nginx/Apache)

## Deployment Steps
1. [ ] Backup current database
2. [ ] Deploy new code to staging
3. [ ] Run migration on staging
4. [ ] Test bulk generator on staging
5. [ ] Deploy to production
6. [ ] Run migration on production
7. [ ] Verify all endpoints work
8. [ ] Monitor logs for errors

## Post-Deployment Verification
- [ ] Test JQL validation: `/api/bulk-generator/validate-jql`
- [ ] Test story fetching: `/api/bulk-generator/fetch-stories`  
- [ ] Test bulk generation: `/api/bulk-generator/generate-tests`
- [ ] Verify UI loads: `/test-generator/bulk`
- [ ] Check rate limiting is working
- [ ] Monitor AI API usage and costs
- [ ] Verify session cleanup runs

## Monitoring & Alerts
- [ ] Set up alerts for failed generations
- [ ] Monitor AI API rate limits
- [ ] Track session cleanup job
- [ ] Monitor database performance
- [ ] Set up error tracking (Sentry/etc)

## Security Checklist
- [ ] Validate JQL input sanitization
- [ ] Verify Jira domain whitelist
- [ ] Check session timeout handling
- [ ] Audit user permissions
- [ ] Review API rate limits
"""
    
    with open('DEPLOYMENT_CHECKLIST.md', 'w') as f:
        f.write(checklist)
    
    print("✅ Created DEPLOYMENT_CHECKLIST.md")

if __name__ == "__main__":
    print("🚀 Preparing production deployment for Bulk Test Generator...")
    
    create_production_migration()
    create_deployment_checklist()
    
    print("\n📋 Next Steps:")
    print("1. Review production_migration.sql")
    print("2. Follow DEPLOYMENT_CHECKLIST.md")
    print("3. Install: pip install Flask-Limiter")
    print("4. Set environment variables")
    print("5. Run migration on production DB")
    print("6. Deploy and test!")
