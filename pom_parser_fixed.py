import re
import os
import json
import logging

logger = logging.getLogger('curlrunner')

def extract_elements_and_functions(page_file):
    """
    Extract elements and functions from a Page Object Model file
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        tuple: (elements, functions)
            - elements: List of element dictionaries with name and selector
            - functions: List of function dictionaries with name and parameters
    """
    elements = []
    functions = []
    
    try:
        with open(page_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract all selectors from defineElements - this is the main way elements are defined in your POM
        define_elements_pattern = r'this\.defineElements\(\s*{([^}]+)}\s*\)'
        define_elements_match = re.search(define_elements_pattern, content, re.DOTALL)
        
        if define_elements_match:
            elements_section = define_elements_match.group(1)
            logger.info(f"Found defineElements section in {page_file}")
            
            # Extract individual element definitions - looking for 'element_name': { ... }
            element_pattern = r'[\'"](\w+)[\'"]\s*:\s*{([^{}]+)}'
            element_matches = re.findall(element_pattern, elements_section, re.DOTALL)
            
            for element_name, element_def in element_matches:
                # This is a valid element from defineElements
                # Extract the best selector
                selector = extract_best_selector(element_def)
                if selector:
                    elements.append({
                        'name': element_name,
                        'selector': selector
                    })
                    logger.info(f"Found element from defineElements: {element_name} with selector: {selector}")
                else:
                    # If we couldn't extract a selector, still add the element with a placeholder
                    elements.append({
                        'name': element_name,
                        'selector': f"Element: {element_name}"
                    })
                    logger.info(f"Added element without selector: {element_name}")
        
        # Extract all async functions
        function_pattern = r'async\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)\s*{([^}]+)}'
        function_matches = re.findall(function_pattern, content, re.DOTALL)
        
        for func_name, params, body in function_matches:
            # Skip constructor and utility methods
            if func_name not in ['constructor', 'defineElements']:
                # Extract parameters
                param_list = [p.strip() for p in params.split(',') if p.strip()]
                
                # Extract actions from function body
                actions = extract_actions_from_function(body)
                
                functions.append({
                    'name': func_name,
                    'parameters': param_list,
                    'actions': actions
                })
                logger.info(f"Found function: {func_name} with {len(actions)} actions")
        
        # If no elements found from defineElements, try other patterns
        if not elements:
            # Look for elements defined in 'this.elements'
            property_pattern = r'this\.elements\.([a-zA-Z0-9_]+)\s*=\s*[\'"](.+?)[\'"]'
            property_matches = re.findall(property_pattern, content)
            
            for name, selector in property_matches:
                elements.append({
                    'name': name,
                    'selector': selector
                })
                logger.info(f"Found element property: {name} with selector: {selector}")
            
            # Look for elements defined in an elements object
            elements_obj_pattern = r'elements\s*=\s*{([^}]+)}'
            elements_obj_match = re.search(elements_obj_pattern, content, re.DOTALL)
            
            if elements_obj_match:
                elements_obj = elements_obj_match.group(1)
                element_def_pattern = r'([a-zA-Z0-9_]+)\s*:\s*[\'"](.+?)[\'"]'
                element_defs = re.findall(element_def_pattern, elements_obj)
                
                for name, selector in element_defs:
                    if not any(e['name'] == name for e in elements):
                        elements.append({
                            'name': name,
                            'selector': selector
                        })
                        logger.info(f"Found element in object: {name} with selector: {selector}")
    
    except Exception as e:
        logger.error(f"Error extracting from {page_file}: {str(e)}")
    
    return elements, functions

def extract_best_selector(element_def):
    """
    Extract the best selector from an element definition
    
    Args:
        element_def (str): Element definition string
        
    Returns:
        str: Best selector found
    """
    # Look for selectors array
    selectors_pattern = r'selectors\s*:\s*\[(.*?)\]'
    selectors_match = re.search(selectors_pattern, element_def, re.DOTALL)
    
    if selectors_match:
        selectors_array = selectors_match.group(1)
        
        # Try to find CSS selector first
        css_pattern = r'{[^}]*type\s*:\s*[\'"]css[\'"]\s*,\s*value\s*:\s*[\'"](.*?)[\'"]\s*}'
        css_match = re.search(css_pattern, selectors_array)
        if css_match:
            return css_match.group(1)
        
        # Then try to find any selector with a value
        value_pattern = r'value\s*:\s*[\'"](.*?)[\'"]\s*'
        value_match = re.search(value_pattern, selectors_array)
        if value_match:
            return value_match.group(1)
    
    return None

def extract_actions_from_function(function_body):
    """
    Extract actions from a function body
    
    Args:
        function_body (str): Function body text
        
    Returns:
        list: List of action dictionaries
    """
    actions = []
    
    # Common actions to look for
    action_patterns = [
        (r'await\s+this\.click\([\'"]([^\'"]*)[\'"](\)|,)', 'click'),
        (r'await\s+this\.fill\([\'"]([^\'"]*)[\'"](\)|,)', 'fill'),
        (r'await\s+this\.selectOption\([\'"]([^\'"]*)[\'"](\)|,)', 'select'),
        (r'await\s+this\.check\([\'"]([^\'"]*)[\'"](\)|,)', 'check'),
        (r'await\s+this\.waitForElement\([\'"]([^\'"]*)[\'"](\)|,)', 'wait'),
        (r'await\s+this\.navigate\(([^)]*)\)', 'navigate'),
        (r'await\s+this\.getText\([\'"]([^\'"]*)[\'"](\)|,)', 'verify')
    ]
    
    for pattern, action_type in action_patterns:
        matches = re.findall(pattern, function_body)
        for match in matches:
            element_name = match[0] if isinstance(match, tuple) else match
            actions.append({
                'type': action_type,
                'element': element_name
            })
    
    return actions

def get_page_elements(page_file):
    """
    Get all elements from a page file
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        list: List of element dictionaries
    """
    elements, _ = extract_elements_and_functions(page_file)
    
    # If no elements found, add some default ones
    if not elements:
        elements = [
            {'name': 'usernameInput', 'selector': '#username'},
            {'name': 'passwordInput', 'selector': '#password'},
            {'name': 'loginButton', 'selector': 'button[type="submit"]'},
            {'name': 'errorMessage', 'selector': '.error-message'}
        ]
    
    return elements

def get_page_functions(page_file):
    """
    Get all functions from a page file
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        list: List of function dictionaries
    """
    _, functions = extract_elements_and_functions(page_file)
    return functions
