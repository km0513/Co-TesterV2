import os
import sys
import importlib.util

# Add the current directory to the path so we can import app
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import the Flask app and db
try:
    from app import app, db
    
    print("Initializing database with updated models...")
    
    with app.app_context():
        # Create all tables
        db.create_all()
        print("Database tables created successfully!")
        
        # List all tables for verification
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"Tables in database: {tables}")
        
        # Check if TestContext table was created
        if 'test_context' in tables:
            print("TestContext table created successfully!")
            # Show columns in TestContext table
            columns = [column['name'] for column in inspector.get_columns('test_context')]
            print(f"Columns in TestContext table: {columns}")
        else:
            print("WARNING: TestContext table was not created!")
            
except Exception as e:
    print(f"Error initializing database: {str(e)}")
    sys.exit(1)
