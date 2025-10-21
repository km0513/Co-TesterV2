"""
Run API Co-Test database migration
Creates tables for workspaces, environments, collections, and requests
"""
import os
import sys

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

def run_api_cotest_migration():
    """Run the API Co-Test migration"""
    try:
        from app import app, db
        from models import api_cotest
        
        # Set db reference in models
        api_cotest.db = db
        
        with app.app_context():
            print("🔄 Running API Co-Test migration...")
            
            # Import all models to ensure they're registered
            from models.api_cotest import (
                APIWorkspace, APIEnvironment, APIEnvironmentVariable,
                APIGlobalVariable, APICollection, APICollectionFolder,
                APICollectionRequest, APIRequestHistory, APIFavorite
            )
            
            # Create all tables
            db.create_all()
            
            print("✅ API Co-Test tables created successfully!")
            
            # Create a default workspace for testing
            existing_workspace = APIWorkspace.query.first()
            if not existing_workspace:
                print("📦 Creating default workspace...")
                workspace = APIWorkspace(
                    name="My Workspace",
                    description="Default workspace for API testing",
                    user_id=1
                )
                db.session.add(workspace)
                db.session.commit()
                
                # Create default environments
                print("🌍 Creating default environments...")
                environments = [
                    {"name": "Development", "is_active": True},
                    {"name": "Staging", "is_active": False},
                    {"name": "Production", "is_active": False}
                ]
                
                for env_data in environments:
                    env = APIEnvironment(
                        workspace_id=workspace.id,
                        name=env_data["name"],
                        is_active=env_data["is_active"]
                    )
                    db.session.add(env)
                
                db.session.commit()
                print(f"✅ Created workspace '{workspace.name}' with {len(environments)} environments")
            else:
                print(f"ℹ️  Workspace already exists: {existing_workspace.name}")
            
            return True
            
    except Exception as e:
        print(f"❌ Migration failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_api_cotest_migration()
    sys.exit(0 if success else 1)
