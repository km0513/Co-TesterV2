# Database Migration Guide - Playwright Fields

## Overview
This migration adds Playwright-related fields to the `bug_session` table to support the new bug builder functionality.

## Fields Being Added
- `playwright_script_path` (VARCHAR 500) - Path to generated Playwright script
- `playwright_trace_path` (VARCHAR 500) - Path to Playwright trace file
- `playwright_video_path` (VARCHAR 500) - Path to Playwright video recording
- `playwright_status` (VARCHAR 20) - Status: pending, running, success, failed
- `playwright_error` (TEXT) - Error message if Playwright recording failed

## Migration Methods

### Method 1: Using Flask-Migrate (Recommended for Production)

```bash
# 1. SSH into your production server
ssh your-production-server

# 2. Navigate to application directory
cd /path/to/co-tester

# 3. Activate virtual environment (if using one)
source venv/bin/activate

# 4. Run Flask-Migrate upgrade
flask db upgrade

# Or using Python
python -m flask db upgrade
```

### Method 2: Using Standalone Script

```bash
# 1. SSH into your production server
ssh your-production-server

# 2. Navigate to application directory
cd /path/to/co-tester

# 3. Run the migration script
python run_migration.py
```

### Method 3: Manual SQL (If above methods don't work)

**For PostgreSQL:**
```sql
ALTER TABLE bug_session ADD COLUMN IF NOT EXISTS playwright_script_path VARCHAR(500);
ALTER TABLE bug_session ADD COLUMN IF NOT EXISTS playwright_trace_path VARCHAR(500);
ALTER TABLE bug_session ADD COLUMN IF NOT EXISTS playwright_video_path VARCHAR(500);
ALTER TABLE bug_session ADD COLUMN IF NOT EXISTS playwright_status VARCHAR(20);
ALTER TABLE bug_session ADD COLUMN IF NOT EXISTS playwright_error TEXT;
```

**For MySQL:**
```sql
ALTER TABLE bug_session ADD COLUMN playwright_script_path VARCHAR(500);
ALTER TABLE bug_session ADD COLUMN playwright_trace_path VARCHAR(500);
ALTER TABLE bug_session ADD COLUMN playwright_video_path VARCHAR(500);
ALTER TABLE bug_session ADD COLUMN playwright_status VARCHAR(20);
ALTER TABLE bug_session ADD COLUMN playwright_error TEXT;
```

**For SQLite:**
```sql
ALTER TABLE bug_session ADD COLUMN playwright_script_path TEXT;
ALTER TABLE bug_session ADD COLUMN playwright_trace_path TEXT;
ALTER TABLE bug_session ADD COLUMN playwright_video_path TEXT;
ALTER TABLE bug_session ADD COLUMN playwright_status TEXT;
ALTER TABLE bug_session ADD COLUMN playwright_error TEXT;
```

## Verification

After running the migration, verify the columns were added:

```bash
# Using Python
python -c "from app import app, db; from app import BugSession; print([c.name for c in BugSession.__table__.columns])"
```

Or connect to your database and run:
```sql
-- PostgreSQL/MySQL
DESCRIBE bug_session;

-- SQLite
PRAGMA table_info(bug_session);
```

## Rollback (If Needed)

If you need to rollback the migration:

```bash
# Using Flask-Migrate
flask db downgrade

# Or manually drop the columns
# ALTER TABLE bug_session DROP COLUMN playwright_script_path;
# (repeat for other columns)
```

## Safety Notes

✅ **Safe to run multiple times** - The migration checks if columns exist before adding them

✅ **Non-destructive** - Only adds new columns, doesn't modify existing data

✅ **Nullable columns** - All new columns are nullable, so existing rows remain valid

⚠️ **Backup recommended** - Always backup your database before running migrations in production

## Deployment Order

1. **First**: Run the database migration
2. **Then**: Deploy the new application code
3. **Verify**: Check that the bug builder works correctly

## Troubleshooting

### Error: "column already exists"
This is safe to ignore - it means the column was already added.

### Error: "table bug_session does not exist"
The bug_session table hasn't been created yet. Run the full database initialization first.

### Error: "permission denied"
Make sure you're running the migration with a database user that has ALTER TABLE permissions.

## Support

If you encounter issues:
1. Check the application logs
2. Verify database connection settings
3. Ensure you have the correct database permissions
4. Contact the development team
