#!/usr/bin/env python3
"""
Migration: Add Bulk Test Generator Models
Creates JQLSession and JQLStory tables for bulk test generation functionality
"""

import sqlite3
import os
import sys

def run_migration():
    """Run the migration to add bulk test generator tables"""
    
    # Database path
    db_path = os.path.join(os.path.dirname(__file__), '..', 'co_test.db')
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        print("Starting bulk test generator models migration...")
        
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
        
        # Create indexes for better performance
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_session_user_id ON jql_session (user_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_session_session_id ON jql_session (session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_story_session_id ON jql_story (session_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_story_jira_key ON jql_story (jira_key)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_jql_story_generation_status ON jql_story (test_generation_status)')
        
        conn.commit()
        print("✅ Successfully created JQLSession and JQLStory tables")
        print("✅ Created performance indexes")
        
        # Verify tables were created
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('jql_session', 'jql_story')")
        tables = cursor.fetchall()
        
        if len(tables) == 2:
            print("✅ Migration completed successfully")
            print("   - jql_session table created")
            print("   - jql_story table created")
        else:
            print("❌ Migration may have failed - not all tables were created")
            return False
            
    except sqlite3.Error as e:
        print(f"❌ Database error during migration: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during migration: {e}")
        return False
    finally:
        if conn:
            conn.close()
    
    return True

if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
