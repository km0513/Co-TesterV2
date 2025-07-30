import re
import os
import json
import logging

logger = logging.getLogger('curlrunner')

def extract_elements_from_page(page_file):
    """
    Extract elements from a Page Object Model file using a simpler approach
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        list: List of element dictionaries with name and selector
    """
    elements = []
    
    try:
        with open(page_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Look for element definitions in the defineElements section
        define_elements_pattern = r'this\.defineElements\(\s*{(.*?)}\s*\)'
        define_elements_match = re.search(define_elements_pattern, content, re.DOTALL)
        
        if define_elements_match:
            elements_section = define_elements_match.group(1)
            
            # Pattern to extract both name and selector
            # This looks for 'name': 'selector' patterns
            element_pattern = r'[\'"]([^\'"]+)[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]'
            element_matches = re.findall(element_pattern, elements_section)
            
            for name, selector in element_matches:
                # Skip if it's an async function
                if not name.startswith('async'):
                    elements.append({
                        'name': name,
                        'selector': selector
                    })
                    logger.info(f"Added element from defineElements: {name} -> {selector}")
        
        # Also look for this.elements = {...} pattern
        elements_direct_pattern = r'this\.elements\s*=\s*{(.*?)}'
        elements_direct_match = re.search(elements_direct_pattern, content, re.DOTALL)
        
        if elements_direct_match:
            elements_section = elements_direct_match.group(1)
            element_matches = re.findall(element_pattern, elements_section)
            
            for name, selector in element_matches:
                # Skip if it's an async function or already in our list
                if not name.startswith('async') and not any(e['name'] == name for e in elements):
                    elements.append({
                        'name': name,
                        'selector': selector
                    })
                    logger.info(f"Added element from this.elements: {name} -> {selector}")
        
        # Extract locator patterns
        locator_patterns = [
            r'\.locator\([\'"]([^\'"]+)[\'"]\)',
            r'\.getByText\([\'"]([^\'"]+)[\'"]\)',
            r'\.getByRole\([\'"]([^\'"]+)[\'"]\)',
            r'\.getByLabel\([\'"]([^\'"]+)[\'"]\)',
            r'\.getByTestId\([\'"]([^\'"]+)[\'"]\)'
        ]
        
        for pattern in locator_patterns:
            locator_matches = re.findall(pattern, content)
            
            for selector in locator_matches:
                # Create a name from the selector
                name = selector.lower().replace(' ', '_')[:30]
                
                # Check if we already have this selector
                if not any(e['selector'] == selector for e in elements):
                    elements.append({
                        'name': name,
                        'selector': selector
                    })
                    logger.info(f"Added element from locator: {name} -> {selector}")
        
        # Extract element references from method bodies
        method_patterns = [
            r'click\([\'"]([^\'"]+)[\'"]\)',
            r'fill\([\'"]([^\'"]+)[\'"],[^\)]+\)',
            r'selectOption\([\'"]([^\'"]+)[\'"],[^\)]+\)',
            r'check\([\'"]([^\'"]+)[\'"]\)',
            r'waitForElement\([\'"]([^\'"]+)[\'"]\)',
            r'getText\([\'"]([^\'"]+)[\'"]\)'
        ]
        
        for pattern in method_patterns:
            matches = re.findall(pattern, content)
            
            for ref in matches:
                if not any(e['name'] == ref for e in elements):
                    # Try to find a selector for this reference
                    selector_pattern = rf'[\'"]({ref})[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]'
                    selector_match = re.search(selector_pattern, content)
                    
                    if selector_match:
                        selector = selector_match.group(2)
                    else:
                        selector = f"#{ref}"  # Default to ID selector if not found
                    
                    elements.append({
                        'name': ref,
                        'selector': selector
                    })
                    logger.info(f"Added element from method: {ref} -> {selector}")
    
    except Exception as e:
        logger.error(f"Error extracting elements: {str(e)}")
    
    # If no elements found, add some default ones
    if not elements:
        elements = [
            {'name': 'usernameInput', 'selector': '#username'},
            {'name': 'passwordInput', 'selector': '#password'},
            {'name': 'loginButton', 'selector': 'button[type="submit"]'},
            {'name': 'errorMessage', 'selector': '.error-message'}
        ]
    
    return elements

def extract_functions_from_page(page_file):
    """
    Extract functions from a Page Object Model file
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        list: List of function dictionaries
    """
    functions = []
    
    try:
        with open(page_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract all async functions
        function_pattern = r'async\s+([a-zA-Z0-9_]+)\s*\(([^)]*)\)'
        function_matches = re.findall(function_pattern, content)
        
        for func_name, params in function_matches:
            # Skip constructor and utility methods
            if func_name not in ['constructor', 'defineElements']:
                # Extract parameters
                param_list = [p.strip() for p in params.split(',') if p.strip()]
                
                functions.append({
                    'name': func_name,
                    'parameters': param_list,
                    'actions': []
                })
                logger.info(f"Found function: {func_name}")
    
    except Exception as e:
        logger.error(f"Error extracting functions: {str(e)}")
    
    return functions

def get_page_elements(page_file):
    """
    Get all elements from a page file
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        list: List of element dictionaries
    """
    return extract_elements_from_page(page_file)

def get_page_functions(page_file):
    """
    Get all functions from a page file
    
    Args:
        page_file (str): Path to the page file
        
    Returns:
        list: List of function dictionaries
    """
    return extract_functions_from_page(page_file)