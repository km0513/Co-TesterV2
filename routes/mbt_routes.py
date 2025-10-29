"""
Model-Based Testing Routes
API endpoints for state machine management, test generation, and execution
"""

from flask import Blueprint, request, jsonify, render_template
from models.mbt_models import StateMachine, MBTTestExecution, MBTTemplate
from utils.mbt_test_generator import MBTTestGenerator
from utils.ai_state_discovery import AIStateMachineDiscovery
from extensions import db
import json
import os
from datetime import datetime

mbt_bp = Blueprint('mbt', __name__, url_prefix='/mbt')

# Initialize utilities
test_generator = MBTTestGenerator()
ai_discovery = AIStateMachineDiscovery()


# ==================== Main UI Route ====================

@mbt_bp.route('/')
def index():
    """Render the Model-Based Testing Studio UI"""
    return render_template('model-based-testing.html')


# ==================== State Machine CRUD ====================

@mbt_bp.route('/api/state-machines', methods=['GET'])
def list_state_machines():
    """Get all state machines"""
    try:
        machines = StateMachine.query.filter_by(is_active=True).order_by(StateMachine.created_at.desc()).all()
        return jsonify({
            'success': True,
            'machines': [machine.to_dict() for machine in machines]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/state-machines/<int:machine_id>', methods=['GET'])
def get_state_machine(machine_id):
    """Get a specific state machine by ID"""
    try:
        machine = StateMachine.query.get_or_404(machine_id)
        return jsonify({
            'success': True,
            'machine': machine.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 404


@mbt_bp.route('/api/state-machines', methods=['POST'])
def create_state_machine():
    """Create a new state machine"""
    try:
        data = request.json
        
        # Validate required fields
        if not data.get('name'):
            return jsonify({'success': False, 'error': 'Name is required'}), 400
        
        if not data.get('definition'):
            return jsonify({'success': False, 'error': 'State machine definition is required'}), 400
        
        # Validate state machine structure
        validation = ai_discovery.validate_state_machine(data['definition'])
        if not validation['is_valid']:
            return jsonify({
                'success': False,
                'error': 'Invalid state machine',
                'validation': validation
            }), 400
        
        # Create state machine
        machine = StateMachine(
            name=data['name'],
            description=data.get('description', ''),
            definition=data['definition'],
            created_by=data.get('created_by', 'user')
        )
        
        db.session.add(machine)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'State machine created successfully',
            'machine': machine.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/state-machines/<int:machine_id>', methods=['PUT'])
def update_state_machine(machine_id):
    """Update an existing state machine"""
    try:
        machine = StateMachine.query.get_or_404(machine_id)
        data = request.json
        
        # Update fields if provided
        if 'name' in data:
            machine.name = data['name']
        
        if 'description' in data:
            machine.description = data['description']
        
        if 'definition' in data:
            # Validate state machine structure
            validation = ai_discovery.validate_state_machine(data['definition'])
            if not validation['is_valid']:
                return jsonify({
                    'success': False,
                    'error': 'Invalid state machine',
                    'validation': validation
                }), 400
            machine.definition = data['definition']
        
        machine.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'State machine updated successfully',
            'machine': machine.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/state-machines/<int:machine_id>', methods=['DELETE'])
def delete_state_machine(machine_id):
    """Soft delete a state machine"""
    try:
        machine = StateMachine.query.get_or_404(machine_id)
        machine.is_active = False
        machine.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'State machine deleted successfully'
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== AI-Powered Generation ====================

@mbt_bp.route('/api/analyze-recording', methods=['POST'])
def analyze_recording():
    """Convert a Codegen recording to a state machine using AI"""
    try:
        data = request.json
        actions = data.get('actions', [])
        
        if not actions:
            return jsonify({'success': False, 'error': 'No actions provided'}), 400
        
        # Use AI to analyze recording
        result = ai_discovery.analyze_recording_to_states(actions)
        
        return jsonify({
            'success': True,
            'state_machine': result['state_machine'],
            'analysis': result.get('analysis', {})
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/discover-states', methods=['POST'])
def discover_states():
    """Discover states from a URL using AI"""
    try:
        data = request.json
        url = data.get('url', '')
        description = data.get('description', '')
        
        if not url:
            return jsonify({'success': False, 'error': 'URL is required'}), 400
        
        # Use AI to discover states
        result = ai_discovery.discover_states_from_url(url, description)
        
        return jsonify({
            'success': True,
            'state_machine': result['state_machine'],
            'suggestions': result.get('suggestions', [])
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/suggest-missing-states', methods=['POST'])
def suggest_missing_states():
    """Suggest missing states and transitions for a state machine"""
    try:
        data = request.json
        machine_definition = data.get('definition', {})
        
        if not machine_definition:
            return jsonify({'success': False, 'error': 'State machine definition is required'}), 400
        
        # Use AI to suggest improvements
        result = ai_discovery.suggest_missing_states(machine_definition)
        
        return jsonify({
            'success': True,
            'suggestions': result['suggestions'],
            'enhanced_machine': result.get('enhanced_machine')
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/validate-machine', methods=['POST'])
def validate_machine():
    """Validate a state machine structure"""
    try:
        data = request.json
        machine_definition = data.get('definition', {})
        
        if not machine_definition:
            return jsonify({'success': False, 'error': 'State machine definition is required'}), 400
        
        # Validate structure
        validation = ai_discovery.validate_state_machine(machine_definition)
        
        return jsonify({
            'success': True,
            'validation': validation
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Test Generation & Execution ====================

@mbt_bp.route('/api/generate-tests', methods=['POST'])
def generate_tests():
    """Generate Playwright tests from a state machine"""
    try:
        data = request.json
        machine_id = data.get('machine_id')
        output_dir = data.get('output_dir', 'playwright-output/mbt-tests')
        
        if not machine_id:
            return jsonify({'success': False, 'error': 'Machine ID is required'}), 400
        
        # Get state machine
        machine = StateMachine.query.get_or_404(machine_id)
        
        # Generate tests
        files = test_generator.generate_all_files(
            machine_definition=machine.definition,
            machine_name=machine.name,
            output_dir=output_dir
        )
        
        return jsonify({
            'success': True,
            'message': 'Tests generated successfully',
            'files': files,
            'machine': machine.to_dict()
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/list-paths', methods=['POST'])
def list_paths():
    """Calculate test paths for a state machine"""
    try:
        data = request.json
        machine_definition = data.get('definition', {})
        strategy = data.get('strategy', 'shortest')  # shortest, all, edge
        
        if not machine_definition:
            return jsonify({'success': False, 'error': 'State machine definition is required'}), 400
        
        # Calculate paths
        paths = test_generator.calculate_test_paths(machine_definition, strategy)
        coverage = test_generator.get_coverage_info(machine_definition)
        
        return jsonify({
            'success': True,
            'paths': paths,
            'coverage': coverage,
            'strategy': strategy
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/execute-tests', methods=['POST'])
def execute_tests():
    """Execute generated tests and record results"""
    try:
        data = request.json
        machine_id = data.get('machine_id')
        test_files = data.get('test_files', [])
        
        if not machine_id:
            return jsonify({'success': False, 'error': 'Machine ID is required'}), 400
        
        machine = StateMachine.query.get_or_404(machine_id)
        
        # Create execution record
        execution = MBTTestExecution(
            state_machine_id=machine_id,
            test_files=json.dumps(test_files),
            status='running'
        )
        db.session.add(execution)
        db.session.commit()
        
        # TODO: Integrate with actual Playwright test runner
        # For now, return execution record
        
        return jsonify({
            'success': True,
            'message': 'Test execution started',
            'execution': execution.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/executions/<int:execution_id>', methods=['GET'])
def get_execution(execution_id):
    """Get test execution results"""
    try:
        execution = MBTTestExecution.query.get_or_404(execution_id)
        return jsonify({
            'success': True,
            'execution': execution.to_dict()
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 404


@mbt_bp.route('/api/get-coverage/<int:machine_id>', methods=['GET'])
def get_coverage(machine_id):
    """Get coverage information for a state machine"""
    try:
        machine = StateMachine.query.get_or_404(machine_id)
        
        # Get latest execution
        latest_execution = MBTTestExecution.query.filter_by(
            state_machine_id=machine_id,
            status='completed'
        ).order_by(MBTTestExecution.completed_at.desc()).first()
        
        coverage_info = test_generator.get_coverage_info(machine.definition)
        
        result = {
            'success': True,
            'machine': machine.to_dict(),
            'coverage': coverage_info
        }
        
        if latest_execution:
            result['latest_execution'] = latest_execution.to_dict()
            result['state_coverage'] = latest_execution.calculate_state_coverage()
            result['transition_coverage'] = latest_execution.calculate_transition_coverage()
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Templates ====================

@mbt_bp.route('/api/templates', methods=['GET'])
def list_templates():
    """Get all available templates"""
    try:
        templates = MBTTemplate.query.filter_by(is_active=True).order_by(MBTTemplate.name).all()
        return jsonify({
            'success': True,
            'templates': [template.to_dict() for template in templates]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/templates/<int:template_id>/use', methods=['POST'])
def use_template(template_id):
    """Create a new state machine from a template"""
    try:
        template = MBTTemplate.query.get_or_404(template_id)
        data = request.json
        
        # Create state machine from template
        machine = StateMachine(
            name=data.get('name', f"{template.name} - Copy"),
            description=data.get('description', template.description),
            definition=template.definition,
            created_by=data.get('created_by', 'user')
        )
        
        # Increment usage count
        template.usage_count += 1
        
        db.session.add(machine)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': 'State machine created from template',
            'machine': machine.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== Helper Endpoints ====================

@mbt_bp.route('/api/merge-machines', methods=['POST'])
def merge_machines():
    """Merge multiple state machines into one"""
    try:
        data = request.json
        machine_ids = data.get('machine_ids', [])
        
        if len(machine_ids) < 2:
            return jsonify({'success': False, 'error': 'At least 2 machines required'}), 400
        
        # Get machines
        machines = [StateMachine.query.get_or_404(mid) for mid in machine_ids]
        definitions = [m.definition for m in machines]
        
        # Merge using AI
        result = ai_discovery.merge_state_machines(definitions)
        
        return jsonify({
            'success': True,
            'merged_machine': result['merged_machine'],
            'merge_info': result.get('merge_info', {})
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@mbt_bp.route('/api/stats', methods=['GET'])
def get_stats():
    """Get overall MBT statistics"""
    try:
        total_machines = StateMachine.query.filter_by(is_active=True).count()
        total_executions = MBTTestExecution.query.count()
        completed_executions = MBTTestExecution.query.filter_by(status='completed').count()
        
        # Calculate success rate
        if completed_executions > 0:
            successful = MBTTestExecution.query.filter_by(status='completed').all()
            success_count = sum(1 for e in successful if e.total_tests > 0 and e.failed_tests == 0)
            success_rate = (success_count / completed_executions) * 100
        else:
            success_rate = 0
        
        return jsonify({
            'success': True,
            'stats': {
                'total_machines': total_machines,
                'total_executions': total_executions,
                'completed_executions': completed_executions,
                'success_rate': round(success_rate, 2)
            }
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
