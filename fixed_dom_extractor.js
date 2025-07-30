// Function to generate JavaScript Playwright Page Object Model
function generateJsPlaywrightPageClass(elements, className, autoHealing) {
  const includeActions = document.getElementById('includeActions').value === 'yes';
  let code = '';
  
  // Add JSDoc comment
  if (autoHealing) {
    code += `/**\n * ${className} - Page Object Model for Playwright\n * Generated with auto-healing capabilities\n */\n`;
    code += `const AutoHealingPage = require('../../utils/helpers/auto-healing-page');\n\n`;
  } else {
    code += `/**\n * ${className} - Page Object Model for Playwright\n */\n`;
  }
  
  // Class definition
  if (autoHealing) {
    code += `class ${className} extends AutoHealingPage {\n`;
  } else {
    code += `class ${className} {\n`;
  }
  
  // Constructor
  code += '  /**\n   * @param {import(\'@playwright/test\').Page} page\n   */\n';
  code += '  constructor(page) {\n';
  
  if (autoHealing) {
    code += '    super(page);\n';
    code += '    \n';
    code += '    // Define selectors with auto-healing capabilities\n';
    code += '    this.defineElements({\n';
  } else {
    code += '    this.page = page;\n';
  }
  
  // Define locators in constructor
  const usedFields = new Set();
  elements.forEach((el, i) => {
    // Create descriptive field name with page name prefix and element type
    let elementType = el.type.toLowerCase().replace(/\s+/g, '_');
    if (elementType === 'input_field') elementType = 'textbox';
    if (elementType === 'text_field') elementType = 'textbox';
    
    // Create a descriptive name based on the label or other attributes
    let descriptiveName = '';
    if (el.label && el.label.trim()) {
      descriptiveName = el.label.trim();
    } else if (el.value && el.value.trim()) {
      descriptiveName = el.value.trim();
    } else if (el.selector.startsWith('#')) {
      descriptiveName = el.selector.slice(1);
    } else if (el.selector.startsWith('.')) {
      descriptiveName = el.selector.slice(1);
    } else {
      descriptiveName = 'element' + i;
    }
    
    // Format the field name
    let fieldName = `${descriptiveName}_${elementType}`;
    fieldName = fieldName.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_');
    
    // Make sure it's unique
    let originalFieldName = fieldName;
    let counter = 1;
    while (usedFields.has(fieldName)) {
      fieldName = `${originalFieldName}_${counter}`;
      counter++;
    }
    usedFields.add(fieldName);
    
    if (autoHealing) {
      // Add element to defineElements
      code += `      '${fieldName}': '${el.selector}',\n`;
    } else {
      // Add as direct locator
      code += `    this.${fieldName} = page.locator('${el.selector}');\n`;
    }
  });
  
  if (autoHealing) {
    code += '    });\n';
  }
  
  code += '  }\n\n';
  
  // Only add methods if includeActions is true
  if (includeActions) {
    // Add methods for each element
    usedFields.forEach(fieldName => {
      let methodBase = fieldName.charAt(0).toUpperCase() + fieldName.slice(1);
      
      if (autoHealing) {
        // Auto-healing methods
        
        // Click method
        code += `  /**\n   * Click on ${fieldName}\n   */\n`;
        code += `  async click${methodBase}() {\n`;
        code += `    await this.click('${fieldName}');\n`;
        code += '  }\n\n';
        
        // Get text method
        code += `  /**\n   * Get text from ${fieldName}\n   * @returns {Promise<string>}\n   */\n`;
        code += `  async get${methodBase}Text() {\n`;
        code += `    return await this.getText('${fieldName}');\n`;
        code += '  }\n\n';
        
        // Fill method
        code += `  /**\n   * Fill ${fieldName} with text\n   * @param {string} text - Text to fill\n   */\n`;
        code += `  async fill${methodBase}(text) {\n`;
        code += `    await this.fill('${fieldName}', text);\n`;
        code += '  }\n\n';
        
        // Is visible method
        code += `  /**\n   * Check if ${fieldName} is visible\n   * @returns {Promise<boolean>}\n   */\n`;
        code += `  async is${methodBase}Visible() {\n`;
        code += `    return await this.isVisible('${fieldName}');\n`;
        code += '  }\n\n';
      } else {
        // Standard Playwright methods
        
        // Click method
        code += `  /**\n   * Click on ${fieldName}\n   */\n`;
        code += `  async click${methodBase}() {\n`;
        code += `    await this.${fieldName}.click();\n`;
        code += '  }\n\n';
        
        // Get text method
        code += `  /**\n   * Get text from ${fieldName}\n   * @returns {Promise<string>}\n   */\n`;
        code += `  async get${methodBase}Text() {\n`;
        code += `    return await this.${fieldName}.textContent();\n`;
        code += '  }\n\n';
        
        // Fill method
        code += `  /**\n   * Fill ${fieldName} with text\n   * @param {string} text - Text to fill\n   */\n`;
        code += `  async fill${methodBase}(text) {\n`;
        code += `    await this.${fieldName}.fill(text);\n`;
        code += '  }\n\n';
        
        // Is visible method
        code += `  /**\n   * Check if ${fieldName} is visible\n   * @returns {Promise<boolean>}\n   */\n`;
        code += `  async is${methodBase}Visible() {\n`;
        code += `    return await this.${fieldName}.isVisible();\n`;
        code += '  }\n\n';
      }
    });
    
    // Add navigation method
    code += `  /**\n   * Navigate to the ${className} page\n   */\n`;
    code += `  async navigateTo${className}() {\n`;
    code += `    // You may need to update this with the correct route\n`;
    code += `    await this.page.goto('/${className.toLowerCase()}');\n`;
    if (autoHealing) {
      code += `    await this.isLoaded();\n`;
    } else {
      code += `    await this.page.waitForLoadState('networkidle');\n`;
    }
    code += `    return true;\n`;
    code += '  }\n\n';
    
    // Add form filling method if there are input fields
    const inputFields = Array.from(usedFields).filter(field => field.includes('textbox') || field.includes('input'));
    if (inputFields.length > 0) {
      code += `  /**\n   * Fill form fields\n   * @param {Object} data - Form data\n   */\n`;
      code += `  async fillForm(data) {\n`;
      
      inputFields.forEach((field, index) => {
        code += `    if (data.field${index + 1}) {\n`;
        if (autoHealing) {
          code += `      await this.fill('${field}', data.field${index + 1});\n`;
        } else {
          code += `      await this.${field}.fill(data.field${index + 1});\n`;
        }
        code += '    }\n';
      });
      
      code += '  }\n\n';
    }
  }
  
  // Add isLoaded method for auto-healing pages
  if (autoHealing && includeActions) {
    code += `  /**\n   * Check if page is loaded\n   * @returns {Promise<boolean>} True if page is loaded\n   */\n`;
    code += `  async isLoaded() {\n`;
    code += `    try {\n`;
    code += `      await this.page.waitForLoadState('networkidle', { timeout: this.timeout });\n`;
    code += `      \n`;
    code += `      // Check if any of our key elements are visible\n`;
    code += `      const keyElements = [];\n`;
    
    // Add some key elements to check
    const keyElementTypes = ['button', 'textbox', 'link'];
    let elementsAdded = 0;
    usedFields.forEach(field => {
      for (const type of keyElementTypes) {
        if (field.includes(type) && elementsAdded < 3) {
          code += `      keyElements.push('${field}');\n`;
          elementsAdded++;
          break;
        }
      }
    });
    
    code += `      \n`;
    code += `      if (keyElements.length > 0) {\n`;
    code += `        for (const elementName of keyElements) {\n`;
    code += `          if (await this.isVisible(elementName)) {\n`;
    code += `            return true;\n`;
    code += `          }\n`;
    code += `        }\n`;
    code += `      }\n`;
    code += `      \n`;
    code += `      return true;\n`;
    code += `    } catch (error) {\n`;
    code += `      console.error(\`Error checking if page is loaded: \${error.message}\`);\n`;
    code += `      return false;\n`;
    code += `    }\n`;
    code += '  }\n';
  }
  
  code += '}\n\n';
  code += `module.exports = ${className};\n`;
  return code;
}
