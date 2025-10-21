"""
API Co-Test Routes
RESTful API endpoints for workspaces, environments, collections, and requests
"""
from flask import Blueprint, request, jsonify, session, current_app
from functools import wraps
import logging

# Models will be imported from app when blueprint is registered
db = None
APIWorkspace = None
APIEnvironment = None
APIEnvironmentVariable = None
APIGlobalVariable = None
APIRequestHistory = None
APIFavorite = None

logger = logging.getLogger(__name__)

api_cotest_bp = Blueprint('api_cotest', __name__, url_prefix='/api/v1')


def get_current_user_id():
    """Get current user ID from session (placeholder for now)"""
    return session.get('user_id', 1)  # Default to 1 for now


# ============================================================================
# WORKSPACE ENDPOINTS
# ============================================================================

@api_cotest_bp.route('/workspaces', methods=['GET'])
def list_workspaces():
    """List all workspaces for current user"""
    try:
        user_id = get_current_user_id()
        workspaces = APIWorkspace.query.filter_by(user_id=user_id).all()
        return jsonify({
            'success': True,
            'workspaces': [w.to_dict() for w in workspaces]
        })
    except Exception as e:
        logger.error(f"Error listing workspaces: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces', methods=['POST'])
def create_workspace():
    """Create a new workspace"""
    try:
        data = request.get_json()
        user_id = get_current_user_id()
        
        workspace = APIWorkspace(
            name=data.get('name'),
            description=data.get('description'),
            user_id=user_id,
            is_team=data.get('is_team', False)
        )
        
        db.session.add(workspace)
        db.session.commit()
        
        # Create default environment
        default_env = APIEnvironment(
            workspace_id=workspace.id,
            name='Development',
            is_active=True
        )
        db.session.add(default_env)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'workspace': workspace.to_dict(),
            'message': 'Workspace created successfully'
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating workspace: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces/<int:workspace_id>', methods=['GET'])
def get_workspace(workspace_id):
    """Get workspace details"""
    try:
        workspace = APIWorkspace.query.get_or_404(workspace_id)
        return jsonify({
            'success': True,
            'workspace': workspace.to_dict()
        })
    except Exception as e:
        logger.error(f"Error getting workspace: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces/<int:workspace_id>', methods=['PUT'])
def update_workspace(workspace_id):
    """Update workspace"""
    try:
        workspace = APIWorkspace.query.get_or_404(workspace_id)
        data = request.get_json()
        
        if 'name' in data:
            workspace.name = data['name']
        if 'description' in data:
            workspace.description = data['description']
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'workspace': workspace.to_dict(),
            'message': 'Workspace updated successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating workspace: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces/<int:workspace_id>', methods=['DELETE'])
def delete_workspace(workspace_id):
    """Delete workspace"""
    try:
        workspace = APIWorkspace.query.get_or_404(workspace_id)
        db.session.delete(workspace)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Workspace deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting workspace: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ENVIRONMENT ENDPOINTS
# ============================================================================

@api_cotest_bp.route('/workspaces/<int:workspace_id>/environments', methods=['GET'])
def list_environments(workspace_id):
    """List all environments in a workspace"""
    try:
        environments = APIEnvironment.query.filter_by(workspace_id=workspace_id).all()
        return jsonify({
            'success': True,
            'environments': [e.to_dict(include_variables=True) for e in environments]
        })
    except Exception as e:
        logger.error(f"Error listing environments: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces/<int:workspace_id>/environments', methods=['POST'])
def create_environment(workspace_id):
    """Create a new environment"""
    try:
        data = request.get_json()
        
        # If this is set as active, deactivate others
        if data.get('is_active', False):
            APIEnvironment.query.filter_by(workspace_id=workspace_id).update({'is_active': False})
        
        environment = APIEnvironment(
            workspace_id=workspace_id,
            name=data.get('name'),
            is_active=data.get('is_active', False)
        )
        
        db.session.add(environment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'environment': environment.to_dict(),
            'message': 'Environment created successfully'
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating environment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/environments/<int:environment_id>', methods=['PUT'])
def update_environment(environment_id):
    """Update environment"""
    try:
        environment = APIEnvironment.query.get_or_404(environment_id)
        data = request.get_json()
        
        if 'name' in data:
            environment.name = data['name']
        
        if 'is_active' in data and data['is_active']:
            # Deactivate other environments in the same workspace
            APIEnvironment.query.filter_by(workspace_id=environment.workspace_id).update({'is_active': False})
            environment.is_active = True
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'environment': environment.to_dict(),
            'message': 'Environment updated successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error updating environment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/environments/<int:environment_id>', methods=['DELETE'])
def delete_environment(environment_id):
    """Delete environment"""
    try:
        environment = APIEnvironment.query.get_or_404(environment_id)
        db.session.delete(environment)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Environment deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting environment: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# ENVIRONMENT VARIABLES ENDPOINTS
# ============================================================================

@api_cotest_bp.route('/environments/<int:environment_id>/variables', methods=['GET'])
def list_environment_variables(environment_id):
    """List all variables in an environment"""
    try:
        variables = APIEnvironmentVariable.query.filter_by(environment_id=environment_id).all()
        mask_secrets = request.args.get('mask_secrets', 'true').lower() == 'true'
        
        return jsonify({
            'success': True,
            'variables': [v.to_dict(mask_secrets=mask_secrets) for v in variables]
        })
    except Exception as e:
        logger.error(f"Error listing environment variables: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/environments/<int:environment_id>/variables', methods=['POST'])
def create_environment_variable(environment_id):
    """Create or update environment variable"""
    try:
        data = request.get_json()
        
        # Check if variable already exists
        existing = APIEnvironmentVariable.query.filter_by(
            environment_id=environment_id,
            key=data.get('key')
        ).first()
        
        if existing:
            # Update existing
            existing.value = data.get('value')
            existing.is_secret = data.get('is_secret', False)
            existing.description = data.get('description')
            variable = existing
            message = 'Variable updated successfully'
        else:
            # Create new
            variable = APIEnvironmentVariable(
                environment_id=environment_id,
                key=data.get('key'),
                value=data.get('value'),
                is_secret=data.get('is_secret', False),
                description=data.get('description')
            )
            db.session.add(variable)
            message = 'Variable created successfully'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'variable': variable.to_dict(mask_secrets=False),
            'message': message
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating environment variable: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/environments/<int:environment_id>/variables/bulk', methods=['POST'])
def bulk_update_environment_variables(environment_id):
    """Bulk update environment variables"""
    try:
        data = request.get_json()
        variables_data = data.get('variables', [])
        
        # Delete all existing variables
        APIEnvironmentVariable.query.filter_by(environment_id=environment_id).delete()
        
        # Create new variables
        for var_data in variables_data:
            if var_data.get('key'):  # Only create if key is not empty
                variable = APIEnvironmentVariable(
                    environment_id=environment_id,
                    key=var_data.get('key'),
                    value=var_data.get('value'),
                    is_secret=var_data.get('is_secret', False),
                    description=var_data.get('description')
                )
                db.session.add(variable)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'{len(variables_data)} variables updated successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error bulk updating variables: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/variables/<int:variable_id>', methods=['DELETE'])
def delete_environment_variable(variable_id):
    """Delete environment variable"""
    try:
        variable = APIEnvironmentVariable.query.get_or_404(variable_id)
        db.session.delete(variable)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Variable deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting variable: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# GLOBAL VARIABLES ENDPOINTS
# ============================================================================

@api_cotest_bp.route('/workspaces/<int:workspace_id>/global-variables', methods=['GET'])
def list_global_variables(workspace_id):
    """List all global variables in a workspace"""
    try:
        variables = APIGlobalVariable.query.filter_by(workspace_id=workspace_id).all()
        mask_secrets = request.args.get('mask_secrets', 'true').lower() == 'true'
        
        return jsonify({
            'success': True,
            'variables': [v.to_dict(mask_secrets=mask_secrets) for v in variables]
        })
    except Exception as e:
        logger.error(f"Error listing global variables: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces/<int:workspace_id>/global-variables', methods=['POST'])
def create_global_variable(workspace_id):
    """Create or update global variable"""
    try:
        data = request.get_json()
        
        # Check if variable already exists
        existing = APIGlobalVariable.query.filter_by(
            workspace_id=workspace_id,
            key=data.get('key')
        ).first()
        
        if existing:
            # Update existing
            existing.value = data.get('value')
            existing.is_secret = data.get('is_secret', False)
            existing.description = data.get('description')
            variable = existing
            message = 'Global variable updated successfully'
        else:
            # Create new
            variable = APIGlobalVariable(
                workspace_id=workspace_id,
                key=data.get('key'),
                value=data.get('value'),
                is_secret=data.get('is_secret', False),
                description=data.get('description')
            )
            db.session.add(variable)
            message = 'Global variable created successfully'
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'variable': variable.to_dict(mask_secrets=False),
            'message': message
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating global variable: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# REQUEST HISTORY ENDPOINTS
# ============================================================================

@api_cotest_bp.route('/workspaces/<int:workspace_id>/history', methods=['GET'])
def list_request_history(workspace_id):
    """List request history for a workspace"""
    try:
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        history = APIRequestHistory.query.filter_by(workspace_id=workspace_id)\
            .order_by(APIRequestHistory.executed_at.desc())\
            .limit(limit)\
            .offset(offset)\
            .all()
        
        total = APIRequestHistory.query.filter_by(workspace_id=workspace_id).count()
        
        return jsonify({
            'success': True,
            'history': [h.to_dict() for h in history],
            'total': total,
            'limit': limit,
            'offset': offset
        })
    except Exception as e:
        logger.error(f"Error listing request history: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/history/<int:history_id>', methods=['DELETE'])
def delete_history_item(history_id):
    """Delete a history item"""
    try:
        history = APIRequestHistory.query.get_or_404(history_id)
        db.session.delete(history)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'History item deleted successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting history item: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/workspaces/<int:workspace_id>/history/clear', methods=['DELETE'])
def clear_history(workspace_id):
    """Clear all history for a workspace"""
    try:
        APIRequestHistory.query.filter_by(workspace_id=workspace_id).delete()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'History cleared successfully'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error clearing history: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ============================================================================
# FAVORITES ENDPOINTS
# ============================================================================

@api_cotest_bp.route('/favorites', methods=['GET'])
def list_favorites():
    """List all favorites for current user"""
    try:
        user_id = get_current_user_id()
        favorites = APIFavorite.query.filter_by(user_id=user_id).all()
        
        return jsonify({
            'success': True,
            'favorites': [f.to_dict() for f in favorites]
        })
    except Exception as e:
        logger.error(f"Error listing favorites: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/favorites', methods=['POST'])
def create_favorite():
    """Add a request to favorites"""
    try:
        data = request.get_json()
        user_id = get_current_user_id()
        
        favorite = APIFavorite(
            user_id=user_id,
            name=data.get('name'),
            method=data.get('method'),
            url=data.get('url'),
            headers=data.get('headers'),
            body=data.get('body'),
            tags=data.get('tags', [])
        )
        
        db.session.add(favorite)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'favorite': favorite.to_dict(),
            'message': 'Added to favorites'
        }), 201
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error creating favorite: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500


@api_cotest_bp.route('/favorites/<int:favorite_id>', methods=['DELETE'])
def delete_favorite(favorite_id):
    """Remove from favorites"""
    try:
        favorite = APIFavorite.query.get_or_404(favorite_id)
        db.session.delete(favorite)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'Removed from favorites'
        })
    except Exception as e:
        db.session.rollback()
        logger.error(f"Error deleting favorite: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500
