/**
 * Shared Authentication Utilities
 * This script provides consistent authentication checking across the application
 */

// Global authentication state
window.authUtils = {
  isCheckingAuth: false,
  authCallbacks: [],

  // Check if user is authenticated with Jira
  checkAuthentication: function() {
    return new Promise((resolve, reject) => {
      fetch('/api/jira/status')
        .then(response => response.json())
        .then(data => {
          resolve(data.connected);
        })
        .catch(error => {
          console.error('Error checking authentication status:', error);
          reject(error);
        });
    });
  },

  // Navigate to a page with authentication check
  navigateWithAuth: function(targetUrl, skipAuthCheck = false) {
    if (skipAuthCheck) {
      this.navigateToPage(targetUrl);
      return;
    }

    this.showLoader();
    
    this.checkAuthentication()
      .then(isAuthenticated => {
        this.hideLoader();
        
        if (isAuthenticated) {
          this.navigateToPage(targetUrl);
        } else {
          this.showLoginPrompt(targetUrl);
        }
      })
      .catch(error => {
        this.hideLoader();
        console.error('Authentication check failed:', error);
        this.showLoginPrompt(targetUrl);
      });
  },

  // Navigate to page with smooth transition
  navigateToPage: function(url) {
    document.body.style.opacity = '0.98';
    document.body.style.transition = 'opacity 0.15s ease';
    
    setTimeout(() => {
      window.location.href = url;
    }, 50);
  },

  // Show authentication loader
  showLoader: function() {
    let loader = document.getElementById('global-auth-loader');
    if (!loader) {
      loader = document.createElement('div');
      loader.id = 'global-auth-loader';
      loader.innerHTML = `
        <div style="position: fixed; top: 0; left: 0; right: 0; background: rgba(99, 102, 241, 0.1); height: 3px; z-index: 9999;">
          <div style="height: 100%; background: #6366f1; width: 0; animation: authProgress 1s ease-in-out infinite alternate;"></div>
        </div>
      `;
      document.body.appendChild(loader);
      
      // Add progress animation if not exists
      if (!document.getElementById('auth-progress-style')) {
        const style = document.createElement('style');
        style.id = 'auth-progress-style';
        style.textContent = `
          @keyframes authProgress {
            0% { width: 0%; }
            100% { width: 100%; }
          }
        `;
        document.head.appendChild(style);
      }
    }
    loader.style.display = 'block';
  },

  // Hide authentication loader
  hideLoader: function() {
    const loader = document.getElementById('global-auth-loader');
    if (loader) {
      loader.style.display = 'none';
    }
  },

  // Show login prompt
  showLoginPrompt: function(targetUrl) {
    // Try to use the existing modal from sidebar if available
    if (typeof window.showJiraLoginModal === 'function') {
      window.showJiraLoginModal(targetUrl);
      return;
    }
    
    // Fallback: show confirmation dialog
    const message = 'Jira authentication is required to access this feature. Would you like to login now?';
    if (confirm(message)) {
      const loginUrl = '/api/jira/oauth/login';
      if (targetUrl) {
        // Store target URL for post-login redirect
        sessionStorage.setItem('postLoginRedirect', targetUrl);
      }
      window.location.href = loginUrl;
    }
  },

  // Initialize authentication checking on page load
  init: function() {
    // Check for post-login redirect
    const postLoginRedirect = sessionStorage.getItem('postLoginRedirect');
    if (postLoginRedirect) {
      sessionStorage.removeItem('postLoginRedirect');
      
      // Wait a moment for any login processes to complete
      setTimeout(() => {
        this.checkAuthentication()
          .then(isAuthenticated => {
            if (isAuthenticated) {
              this.navigateToPage(postLoginRedirect);
            }
          })
          .catch(error => {
            console.error('Post-login auth check failed:', error);
          });
      }, 1000);
    }

    // Add click handlers to any data-auth-required links
    if (document.body) {
      document.addEventListener('click', (e) => {
        const link = e.target.closest('[data-auth-required]');
        if (link) {
          e.preventDefault();
          e.stopPropagation();
          
          const targetUrl = link.getAttribute('data-href') || link.getAttribute('href');
          if (targetUrl && targetUrl !== '#') {
            this.navigateWithAuth(targetUrl);
          }
        }
      });
    }
  }
};

// Initialize when DOM is ready - with safety checks
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    if (window.authUtils && typeof window.authUtils.init === 'function') {
      window.authUtils.init();
    }
  });
} else {
  if (window.authUtils && typeof window.authUtils.init === 'function') {
    window.authUtils.init();
  }
}