class BugBuilder {
  constructor() {
    this.isRecording = false;
    this.recordingStartTime = null;
    this.recordingTimer = null;
    this.mediaRecorder = null;
    this.recordedChunks = [];
    this.currentSessionId = null;
    this.videoAlreadyUploaded = false;
    this.actions = [];  // Track user actions during recording
    this.annotations = [];  // Track user annotations
    
    this.initializeElements();
    this.bindEvents();
    this.checkJiraConnection();
    this.setupActionLogging();
  }

  initializeElements() {
    console.log('Initializing elements...');
    
    // Recording elements
    this.recordBtn = document.getElementById('recordBtn');
    this.recordingStatus = document.getElementById('recordingStatus');
    this.timerEl = document.getElementById('timer');
    
    // Video preview elements
    this.videoPreviewSection = document.getElementById('videoPreviewSection');
    this.recordingPreview = document.getElementById('recordingPreview');
    this.videoLoadingOverlay = document.getElementById('videoLoadingOverlay');
    this.generateStepsBtn = document.getElementById('generateStepsBtn');
    this.retakeBtn = document.getElementById('retakeBtn');
    
    // Generated steps elements
    this.generatedStepsSection = document.getElementById('generatedStepsSection');
    this.aiGeneratedSteps = document.getElementById('aiGeneratedSteps');
    this.generateFinalReportBtn = document.getElementById('generateFinalReportBtn');
    this.backToVideoBtn = document.getElementById('backToVideoBtn');
    this.retakeBtn2 = document.getElementById('retakeBtn2');
    
    // Bug report elements
    this.bugReportSection = document.getElementById('bugReportSection');
    this.submitBtn = document.getElementById('submitBtn');
    this.editBtn = document.getElementById('editBtn');
    this.loadingOverlay = document.getElementById('loadingOverlay');

    console.log('Elements initialized:', {
      recordBtn: !!this.recordBtn,
      generateStepsBtn: !!this.generateStepsBtn,
      generatedStepsSection: !!this.generatedStepsSection
    });
  }

  bindEvents() {
    if (this.recordBtn) this.recordBtn.addEventListener('click', () => this.toggleRecording());
    if (this.generateStepsBtn) this.generateStepsBtn.addEventListener('click', () => this.generateSteps());
    if (this.generateFinalReportBtn) this.generateFinalReportBtn.addEventListener('click', () => this.generateFinalBugReport());
    if (this.backToVideoBtn) this.backToVideoBtn.addEventListener('click', () => this.backToVideo());
    if (this.retakeBtn) this.retakeBtn.addEventListener('click', () => this.retakeRecording());
    if (this.retakeBtn2) this.retakeBtn2.addEventListener('click', () => this.retakeRecording());
    if (this.submitBtn) this.submitBtn.addEventListener('click', () => this.submitToJira());
    if (this.editBtn) this.editBtn.addEventListener('click', () => this.editReport());
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

  setupActionLogging() {
    if (this.actionLoggingInitialized) {
      return;
    }

    this.actionLoggingInitialized = true;
    console.log('✅ Bug Builder action logging initialized');

    const captureClick = (event) => {
      if (!this.isRecording) return;
      const target = event.target;
      this.recordAction({
        type: 'click',
        target: this.describeElement(target),
        coordinates: { x: event.clientX, y: event.clientY },
        button: event.button,
        modifiers: {
          altKey: event.altKey,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          shiftKey: event.shiftKey
        }
      });
    };

    const captureInput = (event) => {
      if (!this.isRecording) return;
      const target = event.target;
      if (!target) return;
      this.recordAction({
        type: event.type === 'change' ? 'change' : 'input',
        target: this.describeElement(target),
        value: this.truncate(target.value, 200)
      });
    };

    const captureSubmit = (event) => {
      if (!this.isRecording) return;
      const target = event.target;
      if (!target) return;
      const formData = new FormData(target);
      const entries = {};
      formData.forEach((value, key) => {
        entries[key] = this.truncate(value, 120);
      });
      this.recordAction({
        type: 'submit',
        target: this.describeElement(target),
        formData: entries
      });
    };

    const captureKeydown = (event) => {
      if (!this.isRecording) return;
      const interestingKeys = ['Enter', 'Escape', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'];
      if (!interestingKeys.includes(event.key) && !(event.ctrlKey || event.metaKey)) {
        return;
      }
      this.recordAction({
        type: 'keydown',
        key: event.key,
        target: this.describeElement(event.target),
        modifiers: {
          altKey: event.altKey,
          ctrlKey: event.ctrlKey,
          metaKey: event.metaKey,
          shiftKey: event.shiftKey
        }
      });
    };

    const captureMessage = (event) => {
      if (!this.isRecording) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (['UI_ACTION', 'RECORD_ACTION', 'bb-action'].includes(data.type)) {
        this.recordAction({
          type: data.actionType || data.action || data.type,
          target: data.target || {},
          value: data.value,
          pageUrl: data.url || data.pageUrl,
          metadata: data.metadata || data.meta
        });
      }
    };

    document.addEventListener('click', captureClick, true);
    document.addEventListener('input', captureInput, true);
    document.addEventListener('change', captureInput, true);
    document.addEventListener('submit', captureSubmit, true);
    document.addEventListener('keydown', captureKeydown, true);
    window.addEventListener('message', captureMessage);

    const recordNavigation = (source) => {
      if (!this.isRecording) return;
      this.recordAction({
        type: 'navigation',
        source,
        url: window.location.href
      });
    };

    if (!this.historyPatched) {
      const originalPushState = history.pushState;
      const originalReplaceState = history.replaceState;
      history.pushState = (...args) => {
        const result = originalPushState.apply(history, args);
        recordNavigation('pushState');
        return result;
      };
      history.replaceState = (...args) => {
        const result = originalReplaceState.apply(history, args);
        recordNavigation('replaceState');
        return result;
      };
      window.addEventListener('popstate', () => recordNavigation('popstate'));
      window.addEventListener('hashchange', () => recordNavigation('hashchange'));
      this.historyPatched = true;
    }

    const originalFetch = window.fetch.bind(window);
    if (!this.fetchPatched) {
      const self = this;
      window.fetch = async function(...args) {
        const [resource, config] = args;
        const url = typeof resource === 'string' ? resource : resource.url;
        const method = (config && config.method) || 'GET';
        const requestId = `fetch_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
        if (self.isRecording) {
          self.recordAction({ type: 'fetch_request', method, url, requestId });
        }
        try {
          const response = await originalFetch(...args);
          if (self.isRecording) {
            self.recordAction({
              type: 'fetch_response',
              method,
              url,
              status: response.status,
              ok: response.ok,
              requestId
            });
          }
          return response;
        } catch (error) {
          if (self.isRecording) {
            self.recordAction({
              type: 'fetch_error',
              method,
              url,
              message: error.message,
              requestId
            });
          }
          throw error;
        }
      };
      this.fetchPatched = true;
    }

    if (!this.xhrPatched) {
      const self = this;
      const originalOpen = XMLHttpRequest.prototype.open;
      const originalSend = XMLHttpRequest.prototype.send;

      XMLHttpRequest.prototype.open = function(method, url, async, user, password) {
        this.__bugBuilderMeta = { method, url };
        return originalOpen.call(this, method, url, async, user, password);
      };

      XMLHttpRequest.prototype.send = function(body) {
        const meta = this.__bugBuilderMeta || { method: 'GET', url: '' };
        const requestId = `xhr_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
        if (self.isRecording) {
          let serializedBody = null;
          try {
            serializedBody = body ? self.truncate(typeof body === 'string' ? body : JSON.stringify(body), 200) : null;
          } catch (error) {
            serializedBody = '[unserializable body]';
          }
          self.recordAction({
            type: 'xhr_request',
            method: meta.method,
            url: meta.url,
            body: serializedBody,
            requestId
          });
        }

        this.addEventListener('load', function() {
          if (self.isRecording) {
            self.recordAction({
              type: 'xhr_response',
              method: meta.method,
              url: meta.url,
              status: this.status,
              requestId
            });
          }
        });

        this.addEventListener('error', function() {
          if (self.isRecording) {
            self.recordAction({
              type: 'xhr_error',
              method: meta.method,
              url: meta.url,
              status: this.status,
              requestId
            });
          }
        });

        return originalSend.call(this, body);
      };

      this.xhrPatched = true;
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

      // Listen for when the user stops screen sharing
      const videoTrack = stream.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.addEventListener('ended', () => {
          console.log('Screen sharing ended by user');
          this.handleScreenSharingEnded();
        });
      }

      this.mediaRecorder = new MediaRecorder(stream);
      this.recordedChunks = [];
      this.actions = [];  // Reset actions for new recording
      this.annotations = [];  // Reset annotations for new recording

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

      this.recordAction({
        type: 'recording_started',
        url: window.location.href
      }, { force: true });
      this.recordAction({
        type: 'navigation',
        source: 'initial_state',
        url: window.location.href
      }, { force: true });

      this.updateRecordingState('recording');
      this.startCrossPageSync();

      this.recordBtn.classList.add('recording');
      this.recordBtn.innerHTML = '<i class="fas fa-stop"></i> Stop Recording';
      this.recordingStatus.classList.add('active');

      this.startTimer();
      this.currentSessionId = await this.initializeSession();
      this.updateRecordingState('recording');

      console.log('🎬 Recording started - video capture enabled');
      console.log('📹 AI will analyze video frames to generate reproduction steps');

    } catch (error) {
      console.error('Error starting recording:', error);

      // Handle user cancellation
      if (error.name === 'NotAllowedError') {
        console.log('User cancelled screen sharing');
        this.resetRecordingUI();
        return;
      }

      alert('Failed to start recording. Please ensure you grant screen capture permissions.');
    }
  }

  async stopRecording() {
    if (this.mediaRecorder && this.isRecording) {
      console.log('⏹️ Stopping recording...');

      this.mediaRecorder.stop();
      this.isRecording = false;
      
      if (this.recordingTimer) {
        clearInterval(this.recordingTimer);
      }
      
      this.recordBtn.innerHTML = '<i class="fas fa-cog fa-spin"></i> Processing...';
      this.recordBtn.disabled = true;
      
      console.log(`✅ Recording stopped. Video will be analyzed by AI.`);
    }
  }

  handleScreenSharingEnded() {
    console.log('Screen sharing ended, auto-stopping recording');

    // Auto-stop recording when user stops screen sharing
    if (this.isRecording && this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
      this.isRecording = false;

      if (this.recordingTimer) {
        clearInterval(this.recordingTimer);
      }

      // Update UI to show recording has ended
      this.recordBtn.classList.remove('recording');
      this.recordBtn.innerHTML = '<i class="fas fa-check"></i> Recording Complete';
      this.recordBtn.disabled = true;
      this.recordingStatus.classList.remove('active');

      // Show message to user
      setTimeout(() => {
        alert('Screen sharing ended. Your recording is being processed...');
      }, 100);
    }
  }

  startTimer() {
    this.recordingTimer = setInterval(() => {
      const elapsed = Date.now() - this.recordingStartTime;
      const minutes = Math.floor(elapsed / 60000);
      const seconds = Math.floor((elapsed % 60000) / 1000);
      if (this.timerEl) {
        this.timerEl.textContent = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
      }
    }, 1000);
  }

  async initializeSession() {
    try {
      const response = await fetch('/api/bug-builder/start-session', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          timestamp: new Date().toISOString()
        })
      });
      const data = await response.json();
      return data.session_id;
    } catch (error) {
      console.error('Failed to initialize session:', error);
      return null;
    }
  }

  async showVideoPreview() {
    try {
      // Show video preview section first
      this.videoPreviewSection.style.display = 'block';
      this.videoPreviewSection.scrollIntoView({ behavior: 'smooth' });
      
      // Show loading overlay
      if (this.videoLoadingOverlay) {
        this.videoLoadingOverlay.style.display = 'flex';
      }
      
      // Upload video to server for AI analysis
      const videoBlob = new Blob(this.recordedChunks, { type: 'video/webm' });
      const formData = new FormData();
      formData.append('video', videoBlob, 'bug-recording.webm');
      formData.append('session_id', this.currentSessionId);
      const imported = this.flushExternalActions();
      if (imported > 0) {
        console.log(`🔁 Imported ${imported} cross-page actions prior to upload`);
      }
      if (this.actions && this.actions.length > 0) {
        formData.append('actions', JSON.stringify(this.actions));
        console.log(`📝 Uploading ${this.actions.length} captured actions with video`);
      } else {
        console.warn('⚠️ No user actions captured during recording');
      }
      
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
      if (this.recordingPreview && this.videoLoadingOverlay) {
        this.recordingPreview.onloadeddata = () => {
          this.videoLoadingOverlay.style.display = 'none';
        };

        this.recordingPreview.onerror = () => {
          this.videoLoadingOverlay.style.display = 'none';
          console.error('Video playback error');
        };
      }

      // Reset recording UI
      this.resetRecordingUI();
      
    } catch (error) {
      console.error('Error showing video preview:', error);
      if (this.videoLoadingOverlay) {
        this.videoLoadingOverlay.style.display = 'none';
      }
      
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

  async generateSteps() {
    if (!this.currentSessionId) {
      alert('No video session found. Please record a video first.');
      return;
    }

    this.loadingOverlay.classList.add('active');
    
    // Add progress indicator
    const progressDiv = document.createElement('div');
    progressDiv.innerHTML = `
      <div style="text-align: center; color: #374151; margin-top: 1rem;">
        <div style="margin-bottom: 0.5rem;">🎥 Analyzing video frames...</div>
        <div style="font-size: 0.9rem; color: #6b7280;">This may take 30-60 seconds</div>
      </div>
    `;
    this.loadingOverlay.appendChild(progressDiv);
    
    try {
      console.log('Starting video analysis for session:', this.currentSessionId);
      
      const response = await fetch('/api/bug-builder/generate-steps', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.currentSessionId
        })
      });
      
      const result = await response.json();
      console.log('Video analysis result:', result);
      
      if (result.success) {
        this.displayGeneratedSteps(result.steps);
        this.showGeneratedStepsSection();
        
        // Show analysis method info
        if (result.analysis_method) {
          const methodInfo = document.createElement('div');
          methodInfo.style.cssText = 'margin-top: 1rem; padding: 0.75rem; background: #f0f9ff; border: 1px solid #0ea5e9; border-radius: 8px; font-size: 0.9rem;';
          
          if (result.analysis_method === 'video_frame_analysis') {
            methodInfo.innerHTML = `
              <div style="color: #0369a1; font-weight: 600;">✅ Real Video Analysis</div>
              <div style="color: #075985; margin-top: 0.25rem;">
                Analyzed ${result.frames_analyzed || 'multiple'} video frames using AI vision
              </div>
            `;
          } else if (result.analysis_method === 'fallback') {
            methodInfo.innerHTML = `
              <div style="color: #dc2626; font-weight: 600;">⚠️ Fallback Mode</div>
              <div style="color: #991b1b; margin-top: 0.25rem;">
                ${result.error_reason || 'Video analysis failed'} - Using intelligent defaults
              </div>
            `;
          }
          
          this.aiGeneratedSteps.appendChild(methodInfo);
        }
        
      } else {
        throw new Error(result.error || 'Failed to generate steps from video');
      }
      
    } catch (error) {
      console.error('Error generating steps:', error);
      alert('Failed to generate steps from video. Please try again.');
    } finally {
      this.loadingOverlay.classList.remove('active');
      // Remove progress indicator
      if (progressDiv && progressDiv.parentNode) {
        progressDiv.parentNode.removeChild(progressDiv);
      }
    }
  }

  displayGeneratedSteps(steps) {
    if (!this.aiGeneratedSteps) return;

    this.aiGeneratedSteps.innerHTML = '';
    
    if (Array.isArray(steps) && steps.length > 0) {
      const stepsList = document.createElement('ol');
      stepsList.style.cssText = 'margin: 0; padding-left: 1.5rem; color: #374151;';
      
      steps.forEach(step => {
        const listItem = document.createElement('li');
        listItem.style.cssText = 'margin-bottom: 0.75rem; line-height: 1.6;';
        listItem.textContent = step;
        stepsList.appendChild(listItem);
      });
      
      this.aiGeneratedSteps.appendChild(stepsList);
    } else {
      this.aiGeneratedSteps.innerHTML = '<p style="color: #6b7280; text-align: center;">No steps could be generated from the video. Please try recording again with clearer actions.</p>';
    }
  }

  showGeneratedStepsSection() {
    // Hide video preview section
    this.videoPreviewSection.style.display = 'none';
    
    // Show generated steps section
    this.generatedStepsSection.style.display = 'block';
    this.generatedStepsSection.scrollIntoView({ behavior: 'smooth' });
  }

  backToVideo() {
    // Hide generated steps section
    this.generatedStepsSection.style.display = 'none';
    
    // Show video preview section
    this.videoPreviewSection.style.display = 'block';
    this.videoPreviewSection.scrollIntoView({ behavior: 'smooth' });
  }

  async generateFinalBugReport() {
    // Validate required fields
    const expectedResult = document.getElementById('expectedResultInput').value.trim();
    const actualResult = document.getElementById('actualResultInput').value.trim();
    
    if (!expectedResult || !actualResult) {
      alert('Please fill in both Expected and Actual results to generate the bug report.');
      return;
    }

    this.loadingOverlay.classList.add('active');
    
    try {
      const additionalData = document.getElementById('additionalData').value.trim();
      
      const response = await fetch('/api/bug-builder/generate-final-report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: this.currentSessionId,
          expected_result: expectedResult,
          actual_result: actualResult,
          additional_data: additionalData
        })
      });
      
      const result = await response.json();
      
      if (result.success) {
        this.populateBugReport(result.bug_report);
        this.showBugReport();
      } else {
        throw new Error(result.error || 'Failed to generate final bug report');
      }
      
    } catch (error) {
      console.error('Error generating final bug report:', error);
      alert('Failed to generate bug report. Please try again.');
    } finally {
      this.loadingOverlay.classList.remove('active');
    }
  }

  retakeRecording() {
    // Hide all sections
    this.videoPreviewSection.style.display = 'none';
    this.generatedStepsSection.style.display = 'none';
    this.bugReportSection.style.display = 'none';
    
    // Clean up video URL
    if (this.recordingPreview.src) {
      URL.revokeObjectURL(this.recordingPreview.src);
      this.recordingPreview.src = '';
    }
    
    // Reset data
    this.recordedChunks = [];
    this.currentSessionId = null;
    this.videoAlreadyUploaded = false;
    
    // Reset UI
    this.resetRecordingUI();
    
    // Scroll back to recording section
    document.querySelector('.recording-section').scrollIntoView({ behavior: 'smooth' });
  }

  populateBugReport(bugReport) {
    document.getElementById('bugSummary').value = bugReport.summary || '';
    document.getElementById('bugDescription').value = bugReport.description || '';
    document.getElementById('stepsToReproduce').value = bugReport.steps_to_reproduce || '';
    document.getElementById('expectedResult').value = bugReport.expected || '';
    document.getElementById('actualResult').value = bugReport.actual || '';
  }

  showBugReport() {
    // Hide generated steps section
    this.generatedStepsSection.style.display = 'none';
    
    // Show bug report section
    this.bugReportSection.style.display = 'block';
    this.bugReportSection.scrollIntoView({ behavior: 'smooth' });
  }

  resetRecordingUI() {
    this.recordBtn.classList.remove('recording');
    this.recordBtn.innerHTML = '<i class="fas fa-circle"></i> Start Recording';
    this.recordBtn.disabled = false;
    this.recordingStatus.classList.remove('active');
  }

  editReport() {
    // Hide bug report section and show generated steps section again
    this.bugReportSection.style.display = 'none';
    this.generatedStepsSection.style.display = 'block';
    this.generatedStepsSection.scrollIntoView({ behavior: 'smooth' });
  }

  async submitToJira() {
    const bugData = {
      summary: document.getElementById('bugSummary').value,
      description: document.getElementById('bugDescription').value,
      steps_to_reproduce: document.getElementById('stepsToReproduce').value,
      expected: document.getElementById('expectedResult').value,
      actual: document.getElementById('actualResult').value,
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
        // Reset the entire form
        this.resetEverything();
      } else {
        throw new Error(result.error || 'Failed to submit to Jira');
      }
    } catch (error) {
      console.error('Error submitting to Jira:', error);
      alert('Failed to submit bug report to Jira. Please try again.');
    }
  }

  resetEverything() {
    // Hide all sections
    this.videoPreviewSection.style.display = 'none';
    this.generatedStepsSection.style.display = 'none';
    this.bugReportSection.style.display = 'none';
    
    // Reset data
    this.recordedChunks = [];
    this.currentSessionId = null;
    this.videoAlreadyUploaded = false;
    
    // Reset forms
    if (document.getElementById('resultsForm')) {
      document.getElementById('resultsForm').reset();
    }
    if (document.getElementById('bugReportForm')) {
      document.getElementById('bugReportForm').reset();
    }
    
    // Reset UI
    this.resetRecordingUI();
    
    // Scroll back to top
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
  window.bugBuilder = new BugBuilder();
});

BugBuilder.prototype.recordAction = function(action, { force = false } = {}) {
  if (!force && !this.isRecording) {
    return;
  }

  const timestamp = this.recordingStartTime ? Date.now() - this.recordingStartTime : 0;
  const actionEntry = {
    timestamp,
    pageUrl: action.url || action.pageUrl || window.location.href,
    type: action.type,
    target: action.target,
    value: action.value,
    coordinates: action.coordinates,
    button: action.button,
    modifiers: action.modifiers,
    formData: action.formData,
    key: action.key,
    status: action.status,
    method: action.method,
    requestId: action.requestId,
    metadata: action.metadata,
    message: action.message,
    ok: action.ok,
    body: action.body,
    source: action.source
  };

  this.actions.push(actionEntry);
  if (this.actions.length > this.maxActions) {
    this.actions = this.actions.slice(-this.maxActions);
  }

  console.debug('📝 Action logged:', actionEntry);
};

BugBuilder.prototype.updateRecordingState = function(status) {
  try {
    const payload = {
      status,
      sessionId: this.currentSessionId,
      startTime: this.recordingStartTime,
      timestamp: Date.now()
    };
    localStorage.setItem('bugBuilderRecording', JSON.stringify(payload));
  } catch (error) {
    console.warn('Unable to update recording state:', error);
  }
};

BugBuilder.prototype.startCrossPageSync = function() {
  if (this.crossPageActionInterval) {
    clearInterval(this.crossPageActionInterval);
  }
  this.crossPageActionInterval = setInterval(() => {
    const imported = this.flushExternalActions();
    if (imported > 0) {
      console.debug(`🔄 Synced ${imported} actions from other tabs`);
    }
  }, 750);
};

BugBuilder.prototype.stopCrossPageSync = function() {
  if (this.crossPageActionInterval) {
    clearInterval(this.crossPageActionInterval);
    this.crossPageActionInterval = null;
  }
};

BugBuilder.prototype.flushExternalActions = function() {
  try {
    const stored = localStorage.getItem('bugBuilderActions');
    if (!stored) {
      return 0;
    }
    const actions = JSON.parse(stored);
    if (!Array.isArray(actions) || actions.length === 0) {
      localStorage.removeItem('bugBuilderActions');
      return 0;
    }
    actions.forEach(action => {
      this.recordAction({ ...action, pageUrl: action.url || action.pageUrl }, { force: true });
    });
    localStorage.removeItem('bugBuilderActions');
    return actions.length;
  } catch (error) {
    console.warn('Failed to import cross-page actions:', error);
    return 0;
  }
};

BugBuilder.prototype.describeElement = function(element) {
  if (!element) return null;
  return {
    tagName: element.tagName || null,
    id: element.id || null,
    className: element.className || null,
    name: element.name || null,
    text: this.truncate(element.innerText || element.value || '', 80),
    role: element.getAttribute && element.getAttribute('role') || null,
    ariaLabel: element.getAttribute && element.getAttribute('aria-label') || null,
    placeholder: element.getAttribute && element.getAttribute('placeholder') || null,
    href: element.href || null
  };
};

BugBuilder.prototype.truncate = function(value, maxLength = 100) {
  if (value === null || value === undefined) return value;
  const stringValue = String(value);
  if (stringValue.length <= maxLength) return stringValue;
  return `${stringValue.slice(0, maxLength)}…`;
};

BugBuilder.prototype.addAnnotation = function(note) {
  const sanitizedNote = this.truncate(note, 200);
  this.annotations.push({
    timestamp: Date.now() - (this.recordingStartTime || Date.now()),
    note: sanitizedNote
  });
  this.recordAction({
    type: 'annotation',
    value: sanitizedNote
  }, { force: true });
};
