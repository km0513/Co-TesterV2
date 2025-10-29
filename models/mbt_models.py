"""
Model-Based Testing Database Models
State machines, states, transitions, and test executions
"""

from datetime import datetime
from app import db
import json

class StateMachine(db.Model):
    """State machine definition"""
    __tablename__ = 'state_machines'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    initial_state = db.Column(db.String(100), nullable=False)
    definition = db.Column(db.JSON, nullable=False)  # XState machine definition
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    # Relationships
    test_executions = db.relationship('MBTTestExecution', backref='state_machine', lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'initial_state': self.initial_state,
            'definition': self.definition,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'is_active': self.is_active
        }
    
    def get_states(self):
        """Extract all states from definition"""
        return list(self.definition.get('states', {}).keys())
    
    def get_transitions(self):
        """Extract all transitions from definition"""
        transitions = []
        for state_name, state_config in self.definition.get('states', {}).items():
            for event, target in state_config.get('on', {}).items():
                transitions.append({
                    'from': state_name,
                    'event': event,
                    'to': target
                })
        return transitions


class MBTTestExecution(db.Model):
    """Model-based test execution record"""
    __tablename__ = 'mbt_test_executions'
    
    id = db.Column(db.Integer, primary_key=True)
    state_machine_id = db.Column(db.Integer, db.ForeignKey('state_machines.id'), nullable=False)
    strategy = db.Column(db.String(50))  # shortest, all_paths, edge_coverage
    status = db.Column(db.String(20))  # running, completed, failed
    
    # Coverage metrics
    states_covered = db.Column(db.JSON)  # List of covered state names
    transitions_covered = db.Column(db.JSON)  # List of covered transitions
    paths_executed = db.Column(db.JSON)  # List of executed paths
    
    # Results
    total_tests = db.Column(db.Integer, default=0)
    passed_tests = db.Column(db.Integer, default=0)
    failed_tests = db.Column(db.Integer, default=0)
    execution_time = db.Column(db.Float)  # In seconds
    
    # Test code
    generated_code = db.Column(db.Text)  # Generated Playwright test code
    error_log = db.Column(db.Text)
    
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    completed_at = db.Column(db.DateTime)
    
    def to_dict(self):
        return {
            'id': self.id,
            'state_machine_id': self.state_machine_id,
            'strategy': self.strategy,
            'status': self.status,
            'coverage': {
                'states': self.states_covered or [],
                'transitions': self.transitions_covered or [],
                'state_coverage_percent': self.calculate_state_coverage(),
                'transition_coverage_percent': self.calculate_transition_coverage()
            },
            'results': {
                'total': self.total_tests,
                'passed': self.passed_tests,
                'failed': self.failed_tests,
                'pass_rate': self.passed_tests / self.total_tests * 100 if self.total_tests > 0 else 0
            },
            'execution_time': self.execution_time,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
    
    def calculate_state_coverage(self):
        """Calculate percentage of states covered"""
        if not self.state_machine or not self.states_covered:
            return 0
        total_states = len(self.state_machine.get_states())
        covered_states = len(self.states_covered)
        return (covered_states / total_states * 100) if total_states > 0 else 0
    
    def calculate_transition_coverage(self):
        """Calculate percentage of transitions covered"""
        if not self.state_machine or not self.transitions_covered:
            return 0
        total_transitions = len(self.state_machine.get_transitions())
        covered_transitions = len(self.transitions_covered)
        return (covered_transitions / total_transitions * 100) if total_transitions > 0 else 0


class MBTTemplate(db.Model):
    """Pre-built state machine templates"""
    __tablename__ = 'mbt_templates'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(100))  # login, checkout, form, navigation
    description = db.Column(db.Text)
    definition = db.Column(db.JSON, nullable=False)
    thumbnail = db.Column(db.String(500))  # URL to preview image
    usage_count = db.Column(db.Integer, default=0)
    is_public = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'description': self.description,
            'definition': self.definition,
            'thumbnail': self.thumbnail,
            'usage_count': self.usage_count,
            'created_at': self.created_at.isoformat()
        }
