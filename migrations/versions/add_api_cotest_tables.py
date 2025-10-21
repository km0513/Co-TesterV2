"""Add API Co-Test workspace, environment, and collection tables

Revision ID: api_cotest_v1
Revises: 
Create Date: 2025-10-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = 'api_cotest_v1'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Workspaces table
    op.create_table(
        'api_workspaces',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('is_team', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_workspace_user', 'api_workspaces', ['user_id'])

    # Environments table
    op.create_table(
        'api_environments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('is_active', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['api_workspaces.id'], ondelete='CASCADE')
    )
    op.create_index('idx_env_workspace', 'api_environments', ['workspace_id'])

    # Environment variables table
    op.create_table(
        'api_environment_variables',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('environment_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('is_secret', sa.Boolean(), default=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['environment_id'], ['api_environments.id'], ondelete='CASCADE')
    )
    op.create_index('idx_envvar_environment', 'api_environment_variables', ['environment_id'])

    # Global variables table
    op.create_table(
        'api_global_variables',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('key', sa.String(255), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('is_secret', sa.Boolean(), default=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['api_workspaces.id'], ondelete='CASCADE')
    )
    op.create_index('idx_globalvar_workspace', 'api_global_variables', ['workspace_id'])

    # Collections table
    op.create_table(
        'api_collections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('auth_type', sa.String(50), nullable=True),
        sa.Column('auth_config', postgresql.JSONB(), nullable=True),
        sa.Column('variables', postgresql.JSONB(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['api_workspaces.id'], ondelete='CASCADE')
    )
    op.create_index('idx_collection_workspace', 'api_collections', ['workspace_id'])

    # Collection folders table
    op.create_table(
        'api_collection_folders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_id', sa.Integer(), nullable=False),
        sa.Column('parent_folder_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['collection_id'], ['api_collections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_folder_id'], ['api_collection_folders.id'], ondelete='CASCADE')
    )
    op.create_index('idx_folder_collection', 'api_collection_folders', ['collection_id'])

    # Collection requests table
    op.create_table(
        'api_collection_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('collection_id', sa.Integer(), nullable=False),
        sa.Column('folder_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('headers', postgresql.JSONB(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('body_type', sa.String(50), nullable=True),
        sa.Column('pre_request_script', sa.Text(), nullable=True),
        sa.Column('test_script', sa.Text(), nullable=True),
        sa.Column('order_index', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['collection_id'], ['api_collections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['folder_id'], ['api_collection_folders.id'], ondelete='CASCADE')
    )
    op.create_index('idx_request_collection', 'api_collection_requests', ['collection_id'])

    # Request history table
    op.create_table(
        'api_request_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('headers', postgresql.JSONB(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_time', sa.Integer(), nullable=True),
        sa.Column('response_body', sa.Text(), nullable=True),
        sa.Column('response_headers', postgresql.JSONB(), nullable=True),
        sa.Column('environment_id', sa.Integer(), nullable=True),
        sa.Column('executed_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workspace_id'], ['api_workspaces.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['environment_id'], ['api_environments.id'], ondelete='SET NULL')
    )
    op.create_index('idx_history_workspace_user', 'api_request_history', ['workspace_id', 'user_id'])
    op.create_index('idx_history_executed', 'api_request_history', ['executed_at'])

    # Favorites table
    op.create_table(
        'api_favorites',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('request_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(255), nullable=True),
        sa.Column('tags', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('headers', postgresql.JSONB(), nullable=True),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_favorites_user', 'api_favorites', ['user_id'])


def downgrade():
    op.drop_table('api_favorites')
    op.drop_table('api_request_history')
    op.drop_table('api_collection_requests')
    op.drop_table('api_collection_folders')
    op.drop_table('api_collections')
    op.drop_table('api_global_variables')
    op.drop_table('api_environment_variables')
    op.drop_table('api_environments')
    op.drop_table('api_workspaces')
