/**
 * Shared utility functions for Co-Test application
 */

// Toast notification function
function showToast(message, type = 'info') {
  try {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <div class="toast-content">
        <i class="fas ${type === 'success' ? 'fa-check-circle' : type === 'error' ? 'fa-exclamation-circle' : 'fa-info-circle'}"></i>
        <span>${message}</span>
      </div>
      <button class="toast-close"><i class="fas fa-times"></i></button>
    `;
    
    if (document.body) {
      document.body.appendChild(toast);
      
      // Show toast
      setTimeout(() => {
        toast.classList.add('show');
      }, 10);
      
      // Auto hide after 3 seconds
      setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
          toast.remove();
        }, 300);
      }, 3000);
      
      // Close button
      const closeButton = toast.querySelector('.toast-close');
      if (closeButton) {
        closeButton.addEventListener('click', () => {
          toast.classList.remove('show');
          setTimeout(() => {
            toast.remove();
          }, 300);
        });
      }
    }
  } catch (error) {
    console.error('Error showing toast:', error);
  }
}

// Safe event listener function that checks if element exists
function addSafeEventListener(selector, eventType, callback) {
  const element = typeof selector === 'string' ? document.querySelector(selector) : selector;
  if (element) {
    element.addEventListener(eventType, callback);
    return true;
  }
  return false;
}

// Safe query selector that returns null if element doesn't exist
function safeQuerySelector(selector) {
  try {
    return document.querySelector(selector);
  } catch (error) {
    console.error(`Error finding element ${selector}:`, error);
    return null;
  }
}

// Safe query selector all that returns empty array if elements don't exist
function safeQuerySelectorAll(selector) {
  try {
    return document.querySelectorAll(selector);
  } catch (error) {
    console.error(`Error finding elements ${selector}:`, error);
    return [];
  }
}

// Initialize tabs functionality
function initializeTabs(tabSelector, contentSelector, defaultTab = null) {
  const tabs = document.querySelectorAll(tabSelector);
  
  if (!tabs || tabs.length === 0) return;
  
  tabs.forEach(tab => {
    if (!tab) return;
    
    tab.addEventListener('click', function() {
      const tabName = this.dataset.tab;
      
      // Remove active class from all tabs
      tabs.forEach(t => t.classList.remove('active'));
      
      // Hide all tab contents
      const contents = document.querySelectorAll(contentSelector);
      contents.forEach(content => content.classList.remove('active'));
      
      // Add active class to selected tab
      this.classList.add('active');
      
      // Show selected tab content
      const selectedContent = document.getElementById(`${tabName}-tab`);
      if (selectedContent) {
        selectedContent.classList.add('active');
      }
    });
  });
  
  // Activate default tab if specified
  if (defaultTab) {
    const defaultTabElement = document.querySelector(`${tabSelector}[data-tab="${defaultTab}"]`);
    if (defaultTabElement) {
      defaultTabElement.click();
    }
  }
}

// Document ready function
function onDocumentReady(callback) {
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', callback);
  } else {
    callback();
  }
}
