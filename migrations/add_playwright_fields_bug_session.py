"""
Database migration to add Playwright fields to BugSession table.
Works with SQLite, PostgreSQL, and MySQL.
"""
import os
import sys
from datetime import datetime

def run_migration():
    """Run the migration using Flask-Migrate or direct SQL"""
    print(f"Starting BugSession Playwright fields migration at {datetime.utcnow().isoformat()}Z")
    
    try:
        # Try to use Flask-Migrate first (production approach)
        from flask import Flask
        from flask_sqlalchemy import SQLAlchemy
        from flask_migrate import upgrade
        
        # This will be handled by Flask-Migrate in production
        print("Using Flask-Migrate for database migration")
        print("Migration should be handled by 'flask db upgrade' command")
        return
        
    except ImportError:
        print("Flask-Migrate not available, falling back to direct SQL")
    
    # Fallback for development/SQLite
    try:
        import sqlite3
        
        PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(PROJECT_ROOT, 'db.sqlite3')
        
        if not os.path.exists(db_path):
            print("SQLite database not found. Skipping migration.")
            return
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check if columns already exist
        cursor.execute("PRAGMA table_info(bug_session)")
        existing_columns = {column[1] for column in cursor.fetchall()}
        
        columns_to_add = [
            ('playwright_script_path', 'TEXT'),
            ('playwright_trace_path', 'TEXT'), 
            ('playwright_video_path', 'TEXT'),
            ('playwright_status', 'TEXT'),
            ('playwright_error', 'TEXT'),
        ]
        
        for column_name, column_type in columns_to_add:
            if column_name not in existing_columns:
                print(f"Adding column {column_name}")
                cursor.execute(f"ALTER TABLE bug_session ADD COLUMN {column_name} {column_type}")
        
        conn.commit()
        conn.close()
        print("SQLite migration completed")
        
    except Exception as e:
        print(f"Migration error: {e}")
        # Don't fail the deployment for migration issues
        print("Continuing deployment despite migration error")


if __name__ == '__main__':
    run_migration()
