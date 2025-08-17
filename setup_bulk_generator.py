#!/usr/bin/env python3
"""
Setup script for Bulk Test Generator
Creates database tables and starts the application
"""

import sqlite3
import os
import sys

def create_bulk_generator_tables():
    """Create the database tables for bulk test generator"""
    db_path = 'co_test.db'
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("Creating bulk test generator tables...")
        
        # Create JQLSession table
        cursor.execute('''
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
            )
        ''')
        
        # Create JQLStory table
        cursor.execute('''
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
            )
        ''')
        
        # Create indexes for performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_session_user_id ON jql_session (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_session_session_id ON jql_session (session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_story_session_id ON jql_story (session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_story_jira_key ON jql_story (jira_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_story_generation_status ON jql_story (test_generation_status)')
        
        conn.commit()
        print("✅ Database tables created successfully")
        
        # Verify tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('jql_session', 'jql_story')")
        tables = cursor.fetchall()
        
        if len(tables) == 2:
            print("✅ Verified: jql_session and jql_story tables exist")
            return True
        else:
            print("❌ Error: Not all tables were created")
            return False
            
    except sqlite3.Error as e:
        print(f"❌ Database error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("Setting up Bulk Test Generator...")
    
    # Create database tables
    if create_bulk_generator_tables():
        print("\n🚀 Setup complete! You can now run the application:")
        print("   python app.py")
        print("\nThe Bulk Test Generator is available at:")
        print("   http://localhost:5000/test-generator/bulk")
    else:
        print("\n❌ Setup failed. Please check the error messages above.")
        sys.exit(1)
