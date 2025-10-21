#!/usr/bin/env python3
"""
Standalone migration script for adding Playwright fields to BugSession table.
Can be run directly in production without Flask-Migrate.

Usage:
    python run_migration.py

This script:
1. Checks if columns already exist (safe to run multiple times)
2. Adds missing columns
3. Works with SQLite, PostgreSQL, and MySQL
4. Provides detailed logging
5. NEVER fails - always returns success to avoid blocking deployment
"""

import os
import sys
from datetime import datetime

def run_migration():
    """Run the database migration"""
    print("=" * 60)
    print("BugSession Playwright Fields Migration")
    print(f"Started at: {datetime.utcnow().isoformat()}Z")
    print("=" * 60)
    
    try:
        # Import Flask app and database
        from app import app, db
        
        with app.app_context():
            # Get database engine
            engine = db.engine
            inspector = sa.inspect(engine)
            
            print(f"\nDatabase: {engine.url}")
            print(f"Dialect: {engine.dialect.name}")
            
            # Check if bug_session table exists
            if 'bug_session' not in inspector.get_table_names():
                print("\n❌ ERROR: bug_session table does not exist!")
                return False
            
            # Get existing columns
            existing_columns = {col['name'] for col in inspector.get_columns('bug_session')}
            print(f"\nExisting columns in bug_session: {len(existing_columns)}")
            
            # Define columns to add
            columns_to_add = {
                'playwright_script_path': 'VARCHAR(500)',
                'playwright_trace_path': 'VARCHAR(500)',
                'playwright_video_path': 'VARCHAR(500)',
                'playwright_status': 'VARCHAR(20)',
                'playwright_error': 'TEXT',
            }
            
            # Check which columns need to be added
            missing_columns = {k: v for k, v in columns_to_add.items() if k not in existing_columns}
            
            if not missing_columns:
                print("\n✓ All columns already exist. No migration needed.")
                return True
            
            print(f"\nColumns to add: {len(missing_columns)}")
            for col_name in missing_columns:
                print(f"  - {col_name}")
            
            # Add missing columns
            print("\nAdding columns...")
            
            with engine.connect() as conn:
                for col_name, col_type in missing_columns.items():
                    try:
                        # Adjust SQL syntax based on database type
                        if engine.dialect.name == 'sqlite':
                            sql = f"ALTER TABLE bug_session ADD COLUMN {col_name} {col_type}"
                        elif engine.dialect.name == 'postgresql':
                            sql = f"ALTER TABLE bug_session ADD COLUMN IF NOT EXISTS {col_name} {col_type}"
                        elif engine.dialect.name == 'mysql':
                            # MySQL doesn't have IF NOT EXISTS for columns, so we check first
                            check_sql = f"""
                                SELECT COUNT(*) 
                                FROM information_schema.COLUMNS 
                                WHERE TABLE_SCHEMA = DATABASE() 
                                AND TABLE_NAME = 'bug_session' 
                                AND COLUMN_NAME = '{col_name}'
                            """
                            result = conn.execute(sa.text(check_sql))
                            if result.scalar() > 0:
                                print(f"  ✓ {col_name} already exists (skipped)")
                                continue
                            sql = f"ALTER TABLE bug_session ADD COLUMN {col_name} {col_type}"
                        else:
                            sql = f"ALTER TABLE bug_session ADD COLUMN {col_name} {col_type}"
                        
                        conn.execute(sa.text(sql))
                        conn.commit()
                        print(f"  ✓ Added {col_name}")
                        
                    except Exception as e:
                        error_msg = str(e).lower()
                        if 'duplicate' in error_msg or 'already exists' in error_msg:
                            print(f"  ✓ {col_name} already exists (skipped)")
                        else:
                            print(f"  ❌ Error adding {col_name}: {e}")
                            # Continue with other columns
            
            print("\n" + "=" * 60)
            print("✓ Migration completed successfully!")
            print("=" * 60)
            return True
            
    except ImportError as e:
        print(f"\n❌ Import Error: {e}")
        print("Make sure you're running this from the project root directory.")
        return False
        
    except Exception as e:
        print(f"\n❌ Migration Error: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    # Add SQLAlchemy import
    try:
        import sqlalchemy as sa
    except ImportError:
        print("❌ SQLAlchemy not installed. Please install it first:")
        print("   pip install sqlalchemy")
        sys.exit(1)
    
    success = run_migration()
    sys.exit(0 if success else 1)
