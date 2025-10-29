"""Add Playwright fields to BugSession

Revision ID: add_playwright_fields
Revises: 
Create Date: 2025-10-21 17:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_playwright_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Add Playwright-related columns to bug_session table"""
    
    # Check if we're using SQLite, PostgreSQL, or MySQL
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Get existing columns
    existing_columns = [col['name'] for col in inspector.get_columns('bug_session')]
    
    # Add columns only if they don't exist
    columns_to_add = [
        ('playwright_script_path', sa.String(500)),
        ('playwright_trace_path', sa.String(500)),
        ('playwright_video_path', sa.String(500)),
        ('playwright_status', sa.String(20)),
        ('playwright_error', sa.Text()),
    ]
    
    for column_name, column_type in columns_to_add:
        if column_name not in existing_columns:
            try:
                with op.batch_alter_table('bug_session', schema=None) as batch_op:
                    batch_op.add_column(sa.Column(column_name, column_type, nullable=True))
                print(f"✓ Added column: {column_name}")
            except Exception as e:
                print(f"⚠ Column {column_name} might already exist or error: {e}")
                # Continue with other columns even if one fails


def downgrade():
    """Remove Playwright-related columns from bug_session table"""
    
    columns_to_remove = [
        'playwright_script_path',
        'playwright_trace_path', 
        'playwright_video_path',
        'playwright_status',
        'playwright_error',
    ]
    
    for column_name in columns_to_remove:
        try:
            with op.batch_alter_table('bug_session', schema=None) as batch_op:
                batch_op.drop_column(column_name)
            print(f"✓ Removed column: {column_name}")
        except Exception as e:
            print(f"⚠ Could not remove column {column_name}: {e}")
