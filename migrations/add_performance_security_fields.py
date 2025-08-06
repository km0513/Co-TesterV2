import sqlite3
import json
import os
import sys
from datetime import datetime

# Get the absolute path to the database file
db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'co_test.db')

def run_migration():
    """
    Migration script to add performance_criteria and security_considerations fields
    to the TestContext table without losing existing data.
    """
    print(f"Starting migration for database at {db_path}")
    
    # Connect to the database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Check if the columns already exist to avoid errors
        cursor.execute("PRAGMA table_info(test_context)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # Add new columns if they don't exist
        new_columns = []
        if 'feature_summary' not in columns:
            new_columns.append(('feature_summary', 'TEXT'))
        if 'requirements' not in columns:
            new_columns.append(('requirements', 'TEXT'))
        if 'user_flows' not in columns:
            new_columns.append(('user_flows', 'TEXT'))
        if 'validation_points' not in columns:
            new_columns.append(('validation_points', 'TEXT'))
        if 'dependencies' not in columns:
            new_columns.append(('dependencies', 'TEXT'))
        if 'edge_cases' not in columns:
            new_columns.append(('edge_cases', 'TEXT'))
        if 'data_requirements' not in columns:
            new_columns.append(('data_requirements', 'TEXT'))
        if 'performance_criteria' not in columns:
            new_columns.append(('performance_criteria', 'TEXT'))
        if 'security_considerations' not in columns:
            new_columns.append(('security_considerations', 'TEXT'))
        
        # Add each new column
        for column_name, column_type in new_columns:
            print(f"Adding column {column_name} to test_context table")
            cursor.execute(f"ALTER TABLE test_context ADD COLUMN {column_name} {column_type}")
        
        # Migrate existing data from context_data JSON to structured columns
        if new_columns:
            print("Migrating existing data to new columns...")
            cursor.execute("SELECT id, context_data FROM test_context")
            rows = cursor.fetchall()
            
            for row in rows:
                context_id, context_data_str = row
                if not context_data_str:
                    continue
                
                try:
                    # Parse the JSON data
                    context_data = json.loads(context_data_str)
                    
                    # Prepare update query with only the columns that exist
                    update_parts = []
                    params = []
                    
                    # Map JSON fields to columns
                    field_mappings = {
                        'feature_summary': ('feature_summary', lambda x: x),
                        'requirements': ('requirements', json.dumps),
                        'functional_requirements': ('requirements', json.dumps),  # Handle renamed field
                        'user_flows': ('user_flows', json.dumps),
                        'validation_points': ('validation_points', json.dumps),
                        'dependencies': ('dependencies', json.dumps),
                        'edge_cases': ('edge_cases', json.dumps),
                        'data_requirements': ('data_requirements', json.dumps),
                        'performance_criteria': ('performance_criteria', json.dumps),
                        'security_considerations': ('security_considerations', json.dumps)
                    }
                    
                    # Build update query parts
                    for json_field, (column_name, transform_func) in field_mappings.items():
                        if json_field in context_data and column_name in columns:
                            value = context_data.get(json_field)
                            if value is not None:
                                update_parts.append(f"{column_name} = ?")
                                params.append(transform_func(value))
                    
                    # Add context_id to params
                    params.append(context_id)
                    
                    # Execute update if we have fields to update
                    if update_parts:
                        update_query = f"UPDATE test_context SET {', '.join(update_parts)} WHERE id = ?"
                        cursor.execute(update_query, params)
                        print(f"Updated context ID {context_id}")
                    
                except Exception as e:
                    print(f"Error migrating data for context ID {context_id}: {str(e)}")
        
        # Commit the changes
        conn.commit()
        print("Migration completed successfully!")
        
    except Exception as e:
        conn.rollback()
        print(f"Migration failed: {str(e)}")
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    run_migration()
