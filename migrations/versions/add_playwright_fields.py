"""Add Playwright fields to BugSession

Revision ID: add_playwright_fields
Revises: 
Create Date: 2025-10-20 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = 'add_playwright_fields'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    """Add Playwright fields to bug_session table"""
    try:
        # Check if table exists
        conn = op.get_bind()
        inspector = sa.inspect(conn)
        
        if 'bug_session' in inspector.get_table_names():
            existing_columns = [col['name'] for col in inspector.get_columns('bug_session')]
            
            # Add columns if they don't exist
            if 'playwright_script_path' not in existing_columns:
                op.add_column('bug_session', sa.Column('playwright_script_path', sa.Text(), nullable=True))
            
            if 'playwright_trace_path' not in existing_columns:
                op.add_column('bug_session', sa.Column('playwright_trace_path', sa.Text(), nullable=True))
                
            if 'playwright_video_path' not in existing_columns:
                op.add_column('bug_session', sa.Column('playwright_video_path', sa.Text(), nullable=True))
                
            if 'playwright_status' not in existing_columns:
                op.add_column('bug_session', sa.Column('playwright_status', sa.String(50), nullable=True))
                
            if 'playwright_error' not in existing_columns:
                op.add_column('bug_session', sa.Column('playwright_error', sa.Text(), nullable=True))
                
        print("Playwright fields migration completed successfully")
    except Exception as e:
        print(f"Migration warning: {e}")
        # Don't fail deployment for migration issues
        pass

def downgrade():
    """Remove Playwright fields from bug_session table"""
    try:
        op.drop_column('bug_session', 'playwright_error')
        op.drop_column('bug_session', 'playwright_status') 
        op.drop_column('bug_session', 'playwright_video_path')
        op.drop_column('bug_session', 'playwright_trace_path')
        op.drop_column('bug_session', 'playwright_script_path')
    except Exception as e:
        print(f"Downgrade warning: {e}")
        pass