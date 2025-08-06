import sqlite3
import os

# Get the absolute path to the database file
db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'co_test.db')
print(f"Checking database at {db_path}")

# Connect to the database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [row[0] for row in cursor.fetchall()]
print(f"Tables in database: {tables}")

# Check if test_context table exists
if 'test_context' in tables:
    print("test_context table exists")
    # Get column info
    cursor.execute("PRAGMA table_info(test_context)")
    columns = [(column[1], column[2]) for column in cursor.fetchall()]
    print(f"Columns in test_context table: {columns}")
else:
    print("test_context table does not exist")
    
    # Check for similar tables
    context_tables = [table for table in tables if 'context' in table.lower()]
    if context_tables:
        print(f"Found similar tables: {context_tables}")
        
        # Check columns of the first similar table
        if context_tables:
            first_table = context_tables[0]
            cursor.execute(f"PRAGMA table_info({first_table})")
            columns = [(column[1], column[2]) for column in cursor.fetchall()]
            print(f"Columns in {first_table} table: {columns}")

conn.close()
