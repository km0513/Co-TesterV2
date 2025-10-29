"""
AI-Powered State Machine Discovery
Analyzes recordings, DOM, and user flows to generate state machines
"""

import json
import os
import google.generativeai as genai
from typing import Dict, List, Any


class AIStateMachineDiscovery:
    """Use AI to discover states, transitions, and generate state machines"""
    
    def __init__(self):
        genai.configure(api_key=os.getenv('GOOGLE_API_KEY'))
        self.model = genai.GenerativeModel(
            model_name='gemini-2.0-flash-exp',
            generation_config={
                'temperature': 0.3,
                'top_p': 0.95,
                'max_output_tokens': 4096,
            }
        )
    
    def analyze_recording_to_states(self, recording_actions: List[Dict]) -> Dict[str, Any]:
        """
        Convert Playwright recording actions into a state machine
        
        Args:
            recording_actions: List of recorded actions from Codegen
            
        Returns:
            State machine definition
        """
        prompt = f"""Analyze these recorded Playwright actions and convert them into a state machine model for Model-Based Testing.

Recorded Actions:
{json.dumps(recording_actions, indent=2)}

Create a state machine with:
1. **States**: Identify distinct UI states (e.g., idle, formFilled, success, error)
2. **Transitions**: Define events that move between states
3. **Events**: Actions that trigger transitions (e.g., FILL_FORM, SUBMIT, CLICK_BUTTON)
4. **Assertions**: For each state, define what should be verified

Return ONLY valid JSON in this exact format:
{{
  "id": "descriptiveMachineName",
  "name": "Human Readable Name",
  "description": "What this flow tests",
  "initial": "initialStateName",
  "states": {{
    "stateName": {{
      "on": {{
        "EVENT_NAME": "targetStateName"
      }},
      "meta": {{
        "test": "await expect(page.locator('#element')).toBeVisible();",
        "description": "What this state represents"
      }}
    }}
  }},
  "events": {{
    "EVENT_NAME": {{
      "action": "await page.click('#button');",
      "description": "What this event does"
    }}
  }}
}}

Important:
- Use descriptive state names (camelCase)
- Identify logical groupings of actions as states
- Mark final states with "type": "final"
- Include realistic assertions in meta.test
- Make events reusable across transitions
"""
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            # Remove markdown code blocks
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            state_machine = json.loads(response_text)
            return {
                'success': True,
                'state_machine': state_machine,
                'source': 'recording_analysis'
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'source': 'recording_analysis'
            }
    
    def discover_states_from_url(self, url: str, page_description: str = '') -> Dict[str, Any]:
        """
        AI analyzes a URL/page and suggests possible states and flows
        
        Args:
            url: The application URL to analyze
            page_description: Optional description of the page/feature
            
        Returns:
            Suggested state machine
        """
        prompt = f"""Analyze this web application feature and create a comprehensive state machine for testing.

URL: {url}
Description: {page_description or 'Analyze the URL to determine the feature'}

Based on common patterns for this type of application, create a state machine that covers:
1. Happy path (successful flow)
2. Error states (validation errors, failures)
3. Edge cases (empty states, loading states)
4. Navigation states (back/forward, cancel)

Return a complete state machine in JSON format with:
- Descriptive state names
- All possible transitions
- Realistic assertions for each state
- Event implementations

JSON format:
{{
  "id": "machineName",
  "name": "Feature Name",
  "description": "What this tests",
  "initial": "idle",
  "states": {{ ... }},
  "events": {{ ... }}
}}
"""
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            state_machine = json.loads(response_text)
            return {
                'success': True,
                'state_machine': state_machine,
                'source': 'url_analysis'
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'source': 'url_analysis'
            }
    
    def suggest_missing_states(self, current_machine: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze existing state machine and suggest missing states/transitions
        
        Args:
            current_machine: Current state machine definition
            
        Returns:
            Suggestions for improvements
        """
        prompt = f"""Analyze this state machine and suggest improvements for comprehensive testing coverage.

Current State Machine:
{json.dumps(current_machine, indent=2)}

Identify:
1. **Missing Error States**: What error scenarios aren't covered?
2. **Missing Transitions**: Are there logical paths not represented?
3. **Missing Validation**: What edge cases should be tested?
4. **Incomplete Assertions**: Which states need better verification?

Return JSON with suggestions:
{{
  "missing_states": [
    {{
      "name": "stateName",
      "reason": "Why this state is needed",
      "definition": {{ ... }}
    }}
  ],
  "missing_transitions": [
    {{
      "from": "state1",
      "to": "state2", 
      "event": "EVENT_NAME",
      "reason": "Why this transition matters"
    }}
  ],
  "improved_assertions": [
    {{
      "state": "stateName",
      "current": "current assertion",
      "suggested": "improved assertion",
      "reason": "Why this is better"
    }}
  ],
  "coverage_gaps": [
    "Description of what's not tested"
  ]
}}
"""
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            suggestions = json.loads(response_text)
            return {
                'success': True,
                'suggestions': suggestions
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def validate_state_machine(self, machine: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate state machine completeness and quality
        
        Returns:
            Validation results with issues and recommendations
        """
        issues = []
        warnings = []
        
        # Check basic structure
        if 'initial' not in machine:
            issues.append("Missing 'initial' state definition")
        
        if 'states' not in machine or not machine['states']:
            issues.append("No states defined")
            return {'valid': False, 'issues': issues, 'warnings': warnings}
        
        states = machine.get('states', {})
        initial = machine.get('initial')
        
        # Validate initial state exists
        if initial and initial not in states:
            issues.append(f"Initial state '{initial}' not found in states")
        
        # Check for unreachable states
        reachable = {initial}
        to_visit = [initial]
        
        while to_visit:
            current = to_visit.pop()
            if current not in states:
                continue
            
            transitions = states[current].get('on', {})
            for target in transitions.values():
                if target not in reachable:
                    reachable.add(target)
                    to_visit.append(target)
        
        unreachable = set(states.keys()) - reachable
        if unreachable:
            warnings.append(f"Unreachable states: {', '.join(unreachable)}")
        
        # Check for missing assertions
        for state_name, state_config in states.items():
            meta = state_config.get('meta', {})
            if 'test' not in meta:
                warnings.append(f"State '{state_name}' missing test assertions")
        
        # Check for final states
        has_final = any(
            state.get('type') == 'final' 
            for state in states.values()
        )
        if not has_final:
            warnings.append("No final states defined - tests may not have clear end points")
        
        # Check for dead-end states (non-final states with no transitions)
        for state_name, state_config in states.items():
            if state_config.get('type') != 'final':
                transitions = state_config.get('on', {})
                if not transitions:
                    warnings.append(f"State '{state_name}' has no transitions and is not final")
        
        return {
            'valid': len(issues) == 0,
            'issues': issues,
            'warnings': warnings,
            'stats': {
                'total_states': len(states),
                'reachable_states': len(reachable),
                'final_states': sum(1 for s in states.values() if s.get('type') == 'final'),
                'total_transitions': sum(len(s.get('on', {})) for s in states.values())
            }
        }
    
    def merge_state_machines(self, machines: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Merge multiple state machines into one comprehensive model
        
        Args:
            machines: List of state machine definitions
            
        Returns:
            Merged state machine
        """
        prompt = f"""Merge these state machines into one comprehensive model that covers all scenarios.

State Machines to Merge:
{json.dumps(machines, indent=2)}

Create a unified state machine that:
1. Combines all unique states
2. Merges similar/duplicate states
3. Preserves all transitions
4. Combines assertions logically
5. Maintains flow integrity

Return the merged state machine in JSON format.
"""
        
        try:
            response = self.model.generate_content(prompt)
            response_text = response.text.strip()
            
            if response_text.startswith('```'):
                response_text = response_text.split('```')[1]
                if response_text.startswith('json'):
                    response_text = response_text[4:]
                response_text = response_text.strip()
            
            merged = json.loads(response_text)
            return {
                'success': True,
                'merged_machine': merged,
                'source_count': len(machines)
            }
        
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


# Example usage
if __name__ == '__main__':
    discovery = AIStateMachineDiscovery()
    
    # Example: Analyze recording
    example_actions = [
        {'type': 'fill', 'selector': '#email', 'value': 'user@example.com'},
        {'type': 'fill', 'selector': '#password', 'value': 'password'},
        {'type': 'click', 'selector': 'button[type="submit"]'},
        {'type': 'waitFor', 'selector': '#dashboard'},
    ]
    
    result = discovery.analyze_recording_to_states(example_actions)
    if result['success']:
        print(json.dumps(result['state_machine'], indent=2))
