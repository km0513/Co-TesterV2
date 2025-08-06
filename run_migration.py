import os
import sys
from migrations.add_performance_security_fields import run_migration

if __name__ == "__main__":
    print("Running database migration to add performance_criteria and security_considerations fields")
    run_migration()
    print("Migration completed. Please restart the Flask application to apply changes.")
