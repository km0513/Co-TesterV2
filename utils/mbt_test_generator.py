"""
Model-Based Testing - Test Generator
Converts XState state machines to Playwright test code
"""

import json
from typing import Dict, List, Any
import os


class MBTTestGenerator:
    """Generate Playwright tests from state machine definitions"""
    
    def __init__(self, state_machine_definition: Dict[str, Any]):
        self.definition = state_machine_definition
        self.states = state_machine_definition.get('states', {})
        self.events = state_machine_definition.get('events', {})
        self.initial = state_machine_definition.get('initial', 'idle')
        
    def generate_xstate_machine(self) -> str:
        """Generate XState machine TypeScript code"""
        machine_id = self.definition.get('id', 'testMachine')
        
        code = f"""import {{ createMachine }} from 'xstate';
import {{ expect }} from '@playwright/test';

export const {machine_id} = createMachine({{
  id: '{machine_id}',
  initial: '{self.initial}',
  states: {{
"""
        
        # Generate states
        for state_name, state_config in self.states.items():
            code += self._generate_state_code(state_name, state_config, indent=4)
        
        code += """  }
});
"""
        return code
    
    def _generate_state_code(self, state_name: str, config: Dict, indent: int = 4) -> str:
        """Generate code for a single state"""
        spaces = ' ' * indent
        code = f"{spaces}{state_name}: {{\n"
        
        # Add transitions
        if 'on' in config:
            code += f"{spaces}  on: {{\n"
            for event, target in config['on'].items():
                code += f"{spaces}    {event}: '{target}',\n"
            code += f"{spaces}  }},\n"
        
        # Add type if final
        if config.get('type') == 'final':
            code += f"{spaces}  type: 'final',\n"
        
        # Add meta test assertions
        if 'meta' in config and 'test' in config['meta']:
            test_config = config['meta']['test']
            code += f"{spaces}  meta: {{\n"
            code += f"{spaces}    test: {{\n"
            
            # Add action if present
            if isinstance(test_config, dict) and 'action' in test_config:
                action = test_config['action']
                code += f"{spaces}      action: `{action}`,\n"
            
            # Add assertion if present
            if isinstance(test_config, dict) and 'assertion' in test_config:
                assertion = test_config['assertion']
                code += f"{spaces}      assertion: `{assertion}`,\n"
            
            code += f"{spaces}    }}\n"
            code += f"{spaces}  }},\n"
        
        code += f"{spaces}}},\n"
        return code
    
    def generate_test_model(self) -> str:
        """Generate test model with events"""
        machine_id = self.definition.get('id', 'testMachine')
        
        code = f"""import {{ createModel }} from '@xstate/test';
import {{ {machine_id} }} from './{machine_id}';
import {{ Page }} from '@playwright/test';

type TestContext = {{ page: Page }};

const testModel = createModel({machine_id}).withEvents({{
"""
        
        # Generate event implementations
        for event_name, event_config in self.events.items():
            action = event_config.get('action', '')
            code += f"""  {event_name}: async (context: unknown) => {{
    const {{ page }} = context as TestContext;
    {action}
  }},
"""
        
        code += """});

export default testModel;
"""
        return code
    
    def generate_test_suite(self, base_url: str = 'http://localhost:3000') -> str:
        """Generate complete Playwright test suite"""
        machine_id = self.definition.get('id', 'testMachine')
        machine_name = self.definition.get('name', 'Test Machine')
        
        code = f"""import {{ test }} from '@playwright/test';
import testModel from './testModel';

test.describe('{machine_name} - Model-based Tests', () => {{
  test.beforeEach(async ({{ page }}) => {{
    await page.goto('{base_url}');
  }});

  // Generate test plans using shortest path strategy
  const testPlans = testModel.getShortestPathPlans();

  // Execute each test path
  for (const plan of testPlans) {{
    for (const path of plan.paths) {{
      test(path.description, async ({{ page }}) => {{
        await path.test({{ page }});
      }});
    }}
  }}

  // Verify all states and transitions are covered
  test('should cover all states and transitions', async () => {{
    testModel.testCoverage();
  }});
}});
"""
        return code
    
    def generate_all_files(self, output_dir: str, base_url: str = 'http://localhost:3000') -> Dict[str, str]:
        """Generate all necessary files"""
        machine_id = self.definition.get('id', 'testMachine')
        
        files = {
            f'{machine_id}.ts': self.generate_xstate_machine(),
            'testModel.ts': self.generate_test_model(),
            f'{machine_id}.spec.ts': self.generate_test_suite(base_url)
        }
        
        return files
    
    def calculate_test_paths(self, strategy: str = 'shortest') -> List[List[str]]:
        """Calculate test paths based on strategy"""
        paths = []
        
        if strategy == 'shortest':
            # BFS to find shortest paths to all states
            paths = self._bfs_shortest_paths()
        elif strategy == 'all_paths':
            # DFS to find all possible paths
            paths = self._dfs_all_paths()
        elif strategy == 'edge_coverage':
            # Paths that cover all transitions
            paths = self._edge_coverage_paths()
        
        return paths
    
    def _bfs_shortest_paths(self) -> List[List[str]]:
        """BFS to find shortest path to each state"""
        from collections import deque
        
        visited = set()
        paths = []
        queue = deque([(self.initial, [self.initial])])
        
        while queue:
            current_state, path = queue.popleft()
            
            if current_state in visited:
                continue
            
            visited.add(current_state)
            paths.append(path)
            
            # Get transitions from current state
            state_config = self.states.get(current_state, {})
            transitions = state_config.get('on', {})
            
            for event, target_state in transitions.items():
                if target_state not in visited:
                    queue.append((target_state, path + [target_state]))
        
        return paths
    
    def _dfs_all_paths(self, max_depth: int = 10) -> List[List[str]]:
        """DFS to find all possible paths (with depth limit)"""
        all_paths = []
        
        def dfs(current, path, depth):
            if depth > max_depth:
                return
            
            state_config = self.states.get(current, {})
            
            # If final state, save path
            if state_config.get('type') == 'final':
                all_paths.append(path)
                return
            
            # Explore all transitions
            transitions = state_config.get('on', {})
            if not transitions:
                all_paths.append(path)
                return
            
            for event, target_state in transitions.items():
                # Avoid infinite loops (but allow revisiting states once)
                if path.count(target_state) < 2:
                    dfs(target_state, path + [target_state], depth + 1)
        
        dfs(self.initial, [self.initial], 0)
        return all_paths
    
    def _edge_coverage_paths(self) -> List[List[str]]:
        """Generate paths that cover all transitions at least once"""
        covered_edges = set()
        paths = []
        
        def find_path_covering_edge(from_state, to_state, current_path):
            if (from_state, to_state) in covered_edges:
                return None
            
            # Simple path finding (can be improved with proper graph algorithms)
            if current_path[-1] == from_state:
                covered_edges.add((from_state, to_state))
                return current_path + [to_state]
            
            return None
        
        # Get all edges
        for state_name, state_config in self.states.items():
            for event, target in state_config.get('on', {}).items():
                if (state_name, target) not in covered_edges:
                    path = self._find_path_to_state(state_name)
                    if path:
                        path.append(target)
                        paths.append(path)
                        covered_edges.add((state_name, target))
        
        return paths
    
    def _find_path_to_state(self, target_state: str) -> List[str]:
        """Find a path from initial state to target state"""
        from collections import deque
        
        if target_state == self.initial:
            return [self.initial]
        
        queue = deque([(self.initial, [self.initial])])
        visited = set()
        
        while queue:
            current, path = queue.popleft()
            
            if current == target_state:
                return path
            
            if current in visited:
                continue
            
            visited.add(current)
            
            state_config = self.states.get(current, {})
            for event, next_state in state_config.get('on', {}).items():
                if next_state not in visited:
                    queue.append((next_state, path + [next_state]))
        
        return [self.initial]
    
    def get_coverage_info(self) -> Dict[str, Any]:
        """Get information about potential coverage"""
        total_states = len(self.states)
        total_transitions = sum(
            len(state.get('on', {})) 
            for state in self.states.values()
        )
        
        return {
            'total_states': total_states,
            'total_transitions': total_transitions,
            'state_names': list(self.states.keys()),
            'initial_state': self.initial,
            'final_states': [
                name for name, config in self.states.items() 
                if config.get('type') == 'final'
            ]
        }


# Example usage
if __name__ == '__main__':
    # Example state machine
    login_machine = {
        'id': 'loginMachine',
        'name': 'Login Flow',
        'initial': 'idle',
        'states': {
            'idle': {
                'on': {
                    'FILL_FORM': 'formFilledValid',
                    'FILL_FORM_INVALID': 'formFilledInvalid'
                },
                'meta': {
                    'test': """await expect(page.getByPlaceholder('Email')).toBeVisible();
await expect(page.getByPlaceholder('Password')).toBeVisible();"""
                }
            },
            'formFilledValid': {
                'on': {
                    'SUBMIT': 'success'
                },
                'meta': {
                    'test': """await expect(page.getByPlaceholder('Email')).toHaveValue('user@example.com');"""
                }
            },
            'formFilledInvalid': {
                'on': {
                    'SUBMIT': 'failure'
                },
                'meta': {
                    'test': """await expect(page.getByPlaceholder('Email')).toHaveValue('wrong@example.com');"""
                }
            },
            'success': {
                'type': 'final',
                'meta': {
                    'test': """await expect(page.locator('#message')).toHaveText('Welcome!');"""
                }
            },
            'failure': {
                'type': 'final',
                'meta': {
                    'test': """await expect(page.locator('#message')).toHaveText('Invalid credentials.');"""
                }
            }
        },
        'events': {
            'FILL_FORM': {
                'action': "await page.fill('#email', 'user@example.com');\nawait page.fill('#password', 'password');"
            },
            'FILL_FORM_INVALID': {
                'action': "await page.fill('#email', 'wrong@example.com');\nawait page.fill('#password', 'wrongpass');"
            },
            'SUBMIT': {
                'action': "await page.click('button[type=\"submit\"]');"
            }
        }
    }
    
    generator = MBTTestGenerator(login_machine)
    
    print("=== Coverage Info ===")
    print(json.dumps(generator.get_coverage_info(), indent=2))
    
    print("\n=== Shortest Paths ===")
    paths = generator.calculate_test_paths('shortest')
    for i, path in enumerate(paths, 1):
        print(f"Path {i}: {' -> '.join(path)}")
    
    print("\n=== Generated XState Machine ===")
    print(generator.generate_xstate_machine())
