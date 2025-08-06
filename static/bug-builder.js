class BugBuilder {
  constructor() {
    this.isRecording = false;
    this.recordingStartTime = null;
    this.recordingTimer = null;
    this.mediaRecorder = null;
    this.recordedChunks = [];
    this.annotations = [];
    this.actionLogs = [];
    this.currentSessionId = null;
    this.videoAlreadyUploaded = false;
    
    this.initializeElements();
    this.bindEvents();
    this.checkJiraConnection();
  }

  initializeElements() {
    this.recordBtn = document.getElementById('recordBtn');
    this.recordingStatus = document.getElementById('recordingStatus');
    this.timerEl = document.getElementById('timer');
    this.videoPreviewSection = document.getElementById('videoPreviewSection');
    this.recordingPreview = document.getElementById('recordingPreview');
    this.videoLoadingOverlay = document.getElementById('videoLoadingOverlay');
    this.actionSummary = document.getElementById('actionSummary');
    this.retakeBtn = document.getElementById('retakeBtn');
    this.proceedBtn = document.getElementById('proceedBtn');
    this.bugReportSection = document.getElementById('bugReportSection');
    this.loadingOverlay = document.getElementById('loadingOverlay');
    this.submitBtn = document.getElementById('submitBtn');
  }

  bindEvents() {
    this.recordBtn.addEventListener('click', () => this.toggleRecording());
    this.retakeBtn.addEventListener('click', () => this.retakeRecording());
    this.proceedBtn.addEventListener('click', () => this.proceedToBugReport());
    this.submitBtn.addEventListener('click', () => this.submitToJira());
  }

  async checkJiraConnection() {
    try {
      const response = await fetch('/api/jira/status');
      const data = await response.json();
      
      if (!data.authenticated) {
        this.submitBtn.innerHTML = '<i class="fas fa-link"></i> Connect to Jira First';
        this.submitBtn.onclick = () => window.location.href = '/api/jira/oauth/login';
      }
    } catch (error) {
      console.error('Failed to check Jira status:', error);
    }
  }

  async toggleRecording() {
    if (!this.isRecording) {
      await this.startRecording();
    } else {
      await this.stopRecording();
    }
  }

  async startRecording() {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { mediaSource: 'screen' },
        audio: true
      });

      this.mediaRecorder = new MediaRecorder(stream);
      this.recordedChunks = [];
      this.annotations = [];
      this.actionLogs = [];

      this.mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          this.recordedChunks.push(event.data);
        }
      };

      this.mediaRecorder.onstop = () => {
        this.showVideoPreview();
      };

      this.mediaRecorder.start();
      this.isRecording = true;
      this.recordingStartTime = Date.now();
      
      this.recordBtn.classList.add('recording');
      this.recordBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Recording';
      this.recordingStatus.classList.add('active');
      
      this.startTimer();
      this.currentSessionId = await this.initializeSession();
      this.startActionLogging();

    } catch (error) {
      console.error('Error starting recording:', error);
      alert('Failed to start recording. Please ensure you grant screen capture permissions.');
    }
  }

  async stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
      this.mediaRecorder.stop();
      this.isRecording = false;
      
      if (this.recordingTimer) {
        clearInterval(this.recordingTimer);
      }
      
      this.recordBtn.innerHTML = '<i class="fas fa-cog fa-spin"></i> Processing...';
      this.recordBtn.disabled = true;
      
      this.stopActionLogging();
    }
  }

  startTimer() {
    this.recordingTimer = setInterval(() => {
      const elapsed = Date.now() - this.recordingStartTime;
      const minutes = Math.floor(elapsed / 60000);
      const seconds = Math.floor((elapsed % 60000) / 1000);
      this.timerEl.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
    }, 1000);
  }

  async initializeSession() {
    try {
      const response = await fetch('/api/bug-builder/start-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timestamp: Date.now(),
          url: window.location.href
        })
      });
      const data = await response.json();
      return data.session_id;
    } catch (error) {
      console.error('Failed to initialize session:', error);
      return null;
    }
  }

  startActionLogging() {
    // Bind all event handlers
    this.clickHandler = this.logClick.bind(this);
    this.inputHandler = this.logInput.bind(this);
    this.changeHandler = this.logChange.bind(this);
    this.keydownHandler = this.logKeydown.bind(this);
    this.mousemoveHandler = this.throttle(this.logMouseMove.bind(this), 500);
    this.scrollHandler = this.throttle(this.logScroll.bind(this), 300);
    this.focusHandler = this.logFocus.bind(this);
    this.blurHandler = this.logBlur.bind(this);
    this.submitHandler = this.logSubmit.bind(this);
    this.contextmenuHandler = this.logContextMenu.bind(this);
    this.dragHandler = this.logDrag.bind(this);
    this.dropHandler = this.logDrop.bind(this);
    
    // Add comprehensive event listeners
    document.addEventListener('click', this.clickHandler, true);
    document.addEventListener('input', this.inputHandler, true);
    document.addEventListener('change', this.changeHandler, true);
    document.addEventListener('keydown', this.keydownHandler, true);
    document.addEventListener('mousemove', this.mousemoveHandler, true);
    document.addEventListener('scroll', this.scrollHandler, true);
    document.addEventListener('focus', this.focusHandler, true);
    document.addEventListener('blur', this.blurHandler, true);
    document.addEventListener('submit', this.submitHandler, true);
    document.addEventListener('contextmenu', this.contextmenuHandler, true);
    document.addEventListener('dragstart', this.dragHandler, true);
    document.addEventListener('drop', this.dropHandler, true);
    
    // Monitor page navigation
    this.originalPushState = history.pushState;
    this.originalReplaceState = history.replaceState;
    
    history.pushState = (...args) => {
      this.logNavigation('pushState', args[2]);
      return this.originalPushState.apply(history, args);
    };
    
    history.replaceState = (...args) => {
      this.logNavigation('replaceState', args[2]);
      return this.originalReplaceState.apply(history, args);
    };
    
    window.addEventListener('popstate', (e) => {
      this.logNavigation('popstate', window.location.href);
    });
    
    // Monitor AJAX requests
    this.interceptXHR();
    this.interceptFetch();
    
    // Monitor console errors
    this.originalConsoleError = console.error;
    console.error = (...args) => {
      this.logConsoleError(args);
      return this.originalConsoleError.apply(console, args);
    };
    
    // Monitor window errors
    window.addEventListener('error', this.logWindowError.bind(this));
    window.addEventListener('unhandledrejection', this.logUnhandledRejection.bind(this));
  }

  stopActionLogging() {
    // Remove all event listeners
    document.removeEventListener('click', this.clickHandler, true);
    document.removeEventListener('input', this.inputHandler, true);
    document.removeEventListener('change', this.changeHandler, true);
    document.removeEventListener('keydown', this.keydownHandler, true);
    document.removeEventListener('mousemove', this.mousemoveHandler, true);
    document.removeEventListener('scroll', this.scrollHandler, true);
    document.removeEventListener('focus', this.focusHandler, true);
    document.removeEventListener('blur', this.blurHandler, true);
    document.removeEventListener('submit', this.submitHandler, true);
    document.removeEventListener('contextmenu', this.contextmenuHandler, true);
    document.removeEventListener('dragstart', this.dragHandler, true);
    document.removeEventListener('drop', this.dropHandler, true);
    
    // Restore original functions
    if (this.originalPushState) {
      history.pushState = this.originalPushState;
    }
    if (this.originalReplaceState) {
      history.replaceState = this.originalReplaceState;
    }
    if (this.originalConsoleError) {
      console.error = this.originalConsoleError;
    }
    
    window.removeEventListener('error', this.logWindowError.bind(this));
    window.removeEventListener('unhandledrejection', this.logUnhandledRejection.bind(this));
  }

  logClick(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const element = event.target;
    const action = {
      timestamp,
      type: 'click',
      target: this.getDetailedElementInfo(element),
      coordinates: { x: event.clientX, y: event.clientY },
      button: event.button, // 0=left, 1=middle, 2=right
      modifiers: {
        ctrl: event.ctrlKey,
        shift: event.shiftKey,
        alt: event.altKey,
        meta: event.metaKey
      },
      url: window.location.href,
      viewport: { width: window.innerWidth, height: window.innerHeight }
    };
    
    this.actionLogs.push(action);
  }

  logInput(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const element = event.target;
    const action = {
      timestamp,
      type: 'input',
      target: this.getDetailedElementInfo(element),
      value: this.sanitizeValue(element.value),
      inputType: event.inputType,
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logChange(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const element = event.target;
    const action = {
      timestamp,
      type: 'change',
      target: this.getDetailedElementInfo(element),
      value: this.sanitizeValue(element.value),
      checked: element.checked,
      selected: element.selected,
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logKeydown(event) {
    if (!this.isRecording) return;
    
    // Only log significant keystrokes
    const significantKeys = ['Enter', 'Tab', 'Escape', 'Backspace', 'Delete', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
    if (!significantKeys.includes(event.key) && !event.ctrlKey && !event.altKey && !event.metaKey) {
      return;
    }
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'keydown',
      key: event.key,
      code: event.code,
      target: this.getDetailedElementInfo(event.target),
      modifiers: {
        ctrl: event.ctrlKey,
        shift: event.shiftKey,
        alt: event.altKey,
        meta: event.metaKey
      },
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logMouseMove(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'mousemove',
      coordinates: { x: event.clientX, y: event.clientY },
      target: this.getElementSelector(event.target),
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logScroll(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'scroll',
      scrollX: window.scrollX,
      scrollY: window.scrollY,
      target: event.target === document ? 'document' : this.getElementSelector(event.target),
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logFocus(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'focus',
      target: this.getDetailedElementInfo(event.target),
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logBlur(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'blur',
      target: this.getDetailedElementInfo(event.target),
      value: this.sanitizeValue(event.target.value),
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logSubmit(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const form = event.target;
    const formData = new FormData(form);
    const formFields = {};
    
    for (let [key, value] of formData.entries()) {
      formFields[key] = this.sanitizeValue(value);
    }
    
    const action = {
      timestamp,
      type: 'submit',
      target: this.getDetailedElementInfo(form),
      formData: formFields,
      action: form.action,
      method: form.method,
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logContextMenu(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'contextmenu',
      target: this.getDetailedElementInfo(event.target),
      coordinates: { x: event.clientX, y: event.clientY },
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logDrag(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'dragstart',
      target: this.getDetailedElementInfo(event.target),
      coordinates: { x: event.clientX, y: event.clientY },
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logDrop(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'drop',
      target: this.getDetailedElementInfo(event.target),
      coordinates: { x: event.clientX, y: event.clientY },
      files: event.dataTransfer.files.length,
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logNavigation(type, url) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'navigation',
      navigationMethod: type,
      fromUrl: this.currentUrl || window.location.href,
      toUrl: url,
      title: document.title
    };
    
    this.currentUrl = url;
    this.actionLogs.push(action);
  }

  logConsoleError(args) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'console_error',
      message: args.map(arg => String(arg)).join(' '),
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logWindowError(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'javascript_error',
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
      stack: event.error?.stack,
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  logUnhandledRejection(event) {
    if (!this.isRecording) return;
    
    const timestamp = Date.now() - this.recordingStartTime;
    const action = {
      timestamp,
      type: 'unhandled_promise_rejection',
      reason: String(event.reason),
      url: window.location.href
    };
    
    this.actionLogs.push(action);
  }

  interceptXHR() {
    const originalOpen = XMLHttpRequest.prototype.open;
    const originalSend = XMLHttpRequest.prototype.send;
    const self = this;
    
    XMLHttpRequest.prototype.open = function(method, url, ...args) {
      this._bugBuilderMethod = method;
      this._bugBuilderUrl = url;
      return originalOpen.apply(this, [method, url, ...args]);
    };
    
    XMLHttpRequest.prototype.send = function(data) {
      if (self.isRecording) {
        const timestamp = Date.now() - self.recordingStartTime;
        const action = {
          timestamp,
          type: 'xhr_request',
          method: this._bugBuilderMethod,
          url: this._bugBuilderUrl,
          data: data ? String(data).slice(0, 200) : null,
          currentUrl: window.location.href
        };
        
        this.addEventListener('load', function() {
          if (self.isRecording) {
            const responseAction = {
              timestamp: Date.now() - self.recordingStartTime,
              type: 'xhr_response',
              method: this._bugBuilderMethod,
              url: this._bugBuilderUrl,
              status: this.status,
              statusText: this.statusText,
              response: this.responseText ? this.responseText.slice(0, 500) : null,
              currentUrl: window.location.href
            };
            self.actionLogs.push(responseAction);
          }
        });
        
        self.actionLogs.push(action);
      }
      
      return originalSend.apply(this, arguments);
    };
  }

  interceptFetch() {
    const originalFetch = window.fetch;
    const self = this;
    
    window.fetch = async function(resource, options = {}) {
      if (self.isRecording) {
        const timestamp = Date.now() - self.recordingStartTime;
        const url = typeof resource === 'string' ? resource : resource.url;
        const method = options.method || 'GET';
        
        const action = {
          timestamp,
          type: 'fetch_request',
          method,
          url,
          data: options.body ? String(options.body).slice(0, 200) : null,
          currentUrl: window.location.href
        };
        
        self.actionLogs.push(action);
        
        try {
          const response = await originalFetch.apply(this, arguments);
          
          if (self.isRecording) {
            const responseAction = {
              timestamp: Date.now() - self.recordingStartTime,
              type: 'fetch_response',
              method,
              url,
              status: response.status,
              statusText: response.statusText,
              currentUrl: window.location.href
            };
            self.actionLogs.push(responseAction);
          }
          
          return response;
        } catch (error) {
          if (self.isRecording) {
            const errorAction = {
              timestamp: Date.now() - self.recordingStartTime,
              type: 'fetch_error',
              method,
              url,
              error: String(error),
              currentUrl: window.location.href
            };
            self.actionLogs.push(errorAction);
          }
          throw error;
        }
      }
      
      return originalFetch.apply(this, arguments);
    };
  }

  throttle(func, limit) {
    let inThrottle;
    return function() {
      const args = arguments;
      const context = this;
      if (!inThrottle) {
        func.apply(context, args);
        inThrottle = true;
        setTimeout(() => inThrottle = false, limit);
      }
    };
  }

  sanitizeValue(value) {
    if (!value) return value;
    
    // Don't log sensitive information
    const sensitivePatterns = [
      /password/i,
      /ssn/i,
      /social.security/i,
      /credit.card/i,
      /cvv/i,
      /pin/i
    ];
    
    const valueStr = String(value);
    for (let pattern of sensitivePatterns) {
      if (pattern.test(valueStr)) {
        return '[SENSITIVE_DATA_HIDDEN]';
      }
    }
    
    return valueStr.slice(0, 200); // Limit length
  }

  getDetailedElementInfo(element) {
    const info = {
      tagName: element.tagName?.toLowerCase(),
      id: element.id,
      className: element.className,
      name: element.name,
      type: element.type,
      placeholder: element.placeholder,
      title: element.title,
      text: element.textContent?.slice(0, 100),
      selector: this.getElementSelector(element),
      attributes: {}
    };
    
    // Capture important attributes
    const importantAttrs = ['data-testid', 'data-cy', 'aria-label', 'role', 'href', 'src', 'alt'];
    importantAttrs.forEach(attr => {
      if (element.hasAttribute(attr)) {
        info.attributes[attr] = element.getAttribute(attr);
      }
    });
    
    return info;
  }

  getElementSelector(element) {
    if (element.id) return `#${element.id}`;
    if (element.className) return `.${element.className.split(' ')[0]}`;
    return element.tagName.toLowerCase();
  }

  async showVideoPreview() {
    try {
      // Show video preview section first
      this.videoPreviewSection.style.display = 'block';
      this.videoPreviewSection.scrollIntoView({ behavior: 'smooth' });
      
      // Show loading overlay
      this.videoLoadingOverlay.style.display = 'flex';
      
      // Upload video to server first for reliable playback
      const videoBlob = new Blob(this.recordedChunks, { type: 'video/webm' });
      const formData = new FormData();
      formData.append('video', videoBlob, 'bug-recording.webm');
      formData.append('session_id', this.currentSessionId);
      
      const uploadResponse = await fetch('/api/bug-builder/upload-video', {
        method: 'POST',
        body: formData
      });
      
      if (uploadResponse.ok) {
        const uploadResult = await uploadResponse.json();
        if (uploadResult.success) {
          // Use server-hosted video URL
          this.recordingPreview.src = `/api/bug-builder/video/${this.currentSessionId}`;
          this.videoAlreadyUploaded = true;
        } else {
          throw new Error('Failed to upload video');
        }
      } else {
        // Fallback to blob URL if server upload fails
        const videoUrl = URL.createObjectURL(videoBlob);
        this.recordingPreview.src = videoUrl;
      }
      
      // Set up video preview events
      this.recordingPreview.onloadeddata = () => {
        this.videoLoadingOverlay.style.display = 'none';
      };
      
      this.recordingPreview.onerror = () => {
        this.videoLoadingOverlay.style.display = 'none';
        console.error('Video playback error');
      };
      
      // Populate action summary
      this.populateActionSummary();
      
      // Reset recording UI
      this.resetRecordingUI();
      
    } catch (error) {
      console.error('Error showing video preview:', error);
      this.videoLoadingOverlay.style.display = 'none';
      
      // Fallback to blob URL
      try {
        const videoBlob = new Blob(this.recordedChunks, { type: 'video/webm' });
        const videoUrl = URL.createObjectURL(videoBlob);
        this.recordingPreview.src = videoUrl;
        this.recordingPreview.onloadeddata = () => {
          // Video loaded successfully with fallback
        };
      } catch (fallbackError) {
        console.error('Fallback video preview failed:', fallbackError);
        alert('Failed to create video preview. Please try recording again.');
        this.retakeRecording();
      }
    }
  }

  retakeRecording() {
    // Hide video preview
    this.videoPreviewSection.style.display = 'none';
    
    // Clean up video URL
    if (this.recordingPreview.src) {
      URL.revokeObjectURL(this.recordingPreview.src);
      this.recordingPreview.src = '';
    }
    
    // Reset data
    this.recordedChunks = [];
    this.annotations = [];
    this.actionLogs = [];
    this.videoAlreadyUploaded = false;
    
    // Reset UI
    this.resetRecordingUI();
    
    // Scroll back to recording section
    document.querySelector('.recording-section').scrollIntoView({ behavior: 'smooth' });
  }

  async proceedToBugReport() {
    this.loadingOverlay.classList.add('active');
    
    try {
      await this.processRecording();
    } catch (error) {
      console.error('Error proceeding to bug report:', error);
      this.loadingOverlay.classList.remove('active');
    }
  }

  populateActionSummary() {
    const summary = {
      'Total Actions': this.actionLogs.length,
      'Clicks': this.actionLogs.filter(a => a.type === 'click').length,
      'Inputs': this.actionLogs.filter(a => a.type === 'input').length,
      'API Calls': this.actionLogs.filter(a => a.type.includes('request')).length,
      'Errors': this.actionLogs.filter(a => a.type.includes('error')).length,
      'Annotations': this.annotations.length
    };
    
    this.actionSummary.innerHTML = '';
    
    Object.entries(summary).forEach(([key, value]) => {
      const summaryItem = document.createElement('div');
      summaryItem.style.cssText = `
        background: white;
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #e2e8f0;
        text-align: center;
      `;
      
      const icon = this.getSummaryIcon(key);
      
      summaryItem.innerHTML = `
        <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">${icon}</div>
        <div style="font-size: 1.5rem; font-weight: 600; color: #1f2937; margin-bottom: 0.25rem;">${value}</div>
        <div style="font-size: 0.875rem; color: #6b7280;">${key}</div>
      `;
      
      this.actionSummary.appendChild(summaryItem);
    });
  }

  getSummaryIcon(type) {
    const icons = {
      'Total Actions': '📊',
      'Clicks': '👆',
      'Inputs': '⌨️',
      'API Calls': '🌐',
      'Errors': '❌',
      'Annotations': '📝'
    };
    return icons[type] || '📋';
  }

  async processRecording() {
    try {
      const formData = new FormData();
      
      // Only upload video if not already uploaded during preview
      if (!this.videoAlreadyUploaded) {
        const videoBlob = new Blob(this.recordedChunks, { type: 'video/webm' });
        formData.append('video', videoBlob, 'bug-recording.webm');
      }
      
      formData.append('annotations', JSON.stringify(this.annotations));
      formData.append('actions', JSON.stringify(this.actionLogs));
      formData.append('session_id', this.currentSessionId);
      
      const response = await fetch('/api/bug-builder/process-recording', {
        method: 'POST',
        body: formData
      });
      
      const result = await response.json();
      
      if (result.success) {
        this.populateBugReport(result.bug_report);
        this.showBugReport();
        
        // Hide video preview section
        this.videoPreviewSection.style.display = 'none';
      } else {
        throw new Error(result.error || 'Failed to process recording');
      }
      
    } catch (error) {
      console.error('Error processing recording:', error);
      alert('Failed to process recording. Please try again.');
    } finally {
      this.loadingOverlay.classList.remove('active');
    }
  }

  populateBugReport(bugReport) {
    document.getElementById('bugTitle').value = bugReport.title || '';
    document.getElementById('bugDescription').value = bugReport.description || '';
    document.getElementById('stepsToReproduce').value = bugReport.steps_to_reproduce || '';
  }

  showBugReport() {
    this.bugReportSection.style.display = 'block';
    this.bugReportSection.scrollIntoView({ behavior: 'smooth' });
  }

  resetRecordingUI() {
    this.recordBtn.classList.remove('recording');
    this.recordBtn.innerHTML = '<i class="fas fa-circle"></i> Start Recording';
    this.recordBtn.disabled = false;
    this.recordingStatus.classList.remove('active');
  }

  async submitToJira() {
    const bugData = {
      title: document.getElementById('bugTitle').value,
      description: document.getElementById('bugDescription').value,
      steps_to_reproduce: document.getElementById('stepsToReproduce').value,
      session_id: this.currentSessionId
    };

    try {
      const response = await fetch('/api/bug-builder/submit-to-jira', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bugData)
      });

      const result = await response.json();
      
      if (result.success) {
        alert('Bug report submitted to Jira successfully!');
        window.open(result.jira_url, '_blank');
      } else {
        throw new Error(result.error || 'Failed to submit to Jira');
      }
    } catch (error) {
      console.error('Error submitting to Jira:', error);
      alert('Failed to submit bug report to Jira. Please try again.');
    }
  }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  new BugBuilder();
});
