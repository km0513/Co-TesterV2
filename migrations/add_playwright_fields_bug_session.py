import sqlite3
import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _detect_db_path() -> str:
    """Return the SQLite DB path used by the Flask app."""
    try:
        import importlib.util
        import importlib.machinery

        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)

        app_path = os.path.join(PROJECT_ROOT, 'app.py')
        spec = importlib.util.spec_from_file_location('co_test_app', app_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules['co_test_app'] = module
            spec.loader.exec_module(module)
            app = getattr(module, 'app')
            db = getattr(module, 'db')

        with app.app_context():
            url = db.engine.url
            if url.get_backend_name() == 'sqlite':
                db_path = url.database or ''
                if db_path and not os.path.isabs(db_path):
                    db_path = os.path.join(PROJECT_ROOT, db_path)
                if db_path:
                    return db_path
    except Exception as exc:
        print(f"WARNING: Could not load Flask app for DB detection ({exc}). Falling back to heuristics.")

    # Default used by app.py -> sqlite:///db.sqlite3
    default_path = os.path.join(PROJECT_ROOT, 'db.sqlite3')
    if os.path.exists(default_path):
        return default_path

    # Legacy fallback
    legacy_path = os.path.join(PROJECT_ROOT, 'co_test.db')
    if os.path.exists(legacy_path):
        print("WARNING: Active database not found; falling back to co_test.db")
        return legacy_path

    return default_path


DB_PATH = _detect_db_path()

COLUMNS_TO_ADD = [
    ('playwright_script_path', 'TEXT'),
    ('playwright_trace_path', 'TEXT'),
    ('playwright_video_path', 'TEXT'),
    ('playwright_status', 'TEXT'),
    ('playwright_error', 'TEXT'),
]


def run_migration():
    print(f"Starting BugSession Playwright fields migration at {datetime.utcnow().isoformat()}Z")
    print(f"Database: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("Database file not found. Aborting migration.")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(bug_session)")
        existing_columns = {column[1] for column in cursor.fetchall()}

        pending_columns = [col for col in COLUMNS_TO_ADD if col[0] not in existing_columns]
        if not pending_columns:
            print("All Playwright fields already exist. Nothing to do.")
            return

        for column_name, column_type in pending_columns:
            print(f"Adding column {column_name} ({column_type}) to bug_session")
            cursor.execute(f"ALTER TABLE bug_session ADD COLUMN {column_name} {column_type}")

        conn.commit()
        print("Migration completed successfully.")
    except Exception as exc:
        conn.rollback()
        print(f"Migration failed: {exc}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == '__main__':
    run_migration()
