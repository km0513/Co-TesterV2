from flask import current_app
from flask_sqlalchemy import SQLAlchemy

def run_migration():
    """Run database migrations to ensure all tables exist"""
    try:
        db = current_app.extensions['sqlalchemy']
        
        # Create all tables
        db.create_all()
        
        print("✅ Database migration completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Database migration failed: {str(e)}")
        return False

def upgrade_database():
    """Upgrade database schema if needed"""
    try:
        # Import models module to ensure all models are registered
        import models.api_cotest
        run_migration()
        return True
    except Exception as e:
        print(f"Database upgrade error: {str(e)}")
        return False