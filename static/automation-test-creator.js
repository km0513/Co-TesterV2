/**
 * Automation Test Creator - Enhanced with Video Recording and AI Analysis
 * Similar workflow to Bug Builder but focused on test creation
 */

let sessionId = null;
let recordedCode = '';
let recordedVideo = null;
let mediaRecorder = null;
let recordingStream = null;
let generatedManualSteps = [];
let generatedAutomatedSteps = [];
let currentTestData = {};

// ========================================
// Tab Navigation
// ========================================

function goToTab(tabName) {
  document.querySelectorAll('.workflow-tab').forEach(tab => tab.classList.remove('active'));
  document.querySelectorAll('.workflow-content').forEach(content => content.classList.remove('active'));
  
  document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
  document.getElementById(`${tabName}-content`).classList.add('active');
  
  // Do NOT automatically mark tabs as completed when navigating
  // Tabs should only be marked completed when actual work is done
  
  if (tabName === 'export') updateJiraPreview();
  if (tabName === 'generate') updateVideoIndicators();
}

document.querySelectorAll('.workflow-tab').forEach(tab => {
  tab.addEventListener('click', () => goToTab(tab.getAttribute('data-tab')));
});

// Export tabs
document.querySelectorAll('.export-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    // Remove active state from all tabs
    document.querySelectorAll('.export-tab').forEach(t => {
      t.classList.remove('active');
      t.style.borderBottom = 'none';
      t.style.color = '#666';
    });
    
    // Hide all sections
    document.querySelectorAll('.export-section').forEach(s => s.style.display = 'none');
    
    // Add active state to clicked tab
    tab.classList.add('active');
    tab.style.borderBottom = '3px solid #667eea';
    tab.style.color = '#667eea';
    
    const exportType = tab.getAttribute('data-export');
    document.getElementById(`${exportType}ExportSection`).style.display = 'block';
  });
});

// ========================================
// Step 1: Recording with Playwright + Video
// ========================================

document.getElementById('startRecordBtn').addEventListener('click', startPlaywrightRecording);

async function startPlaywrightRecording() {
  const url = document.getElementById('recordUrl').value.trim();
  if (!url) {
    showNotification('Please enter a URL to test', 'error');
    return;
  }
  
  try {
    const startBtn = document.getElementById('startRecordBtn');
    startBtn.disabled = true;
    startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Launching...';
    document.getElementById('launchingIndicator').style.display = 'block';
    
    const response = await fetch('/api/automation-test-creator/start-recording', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    
    const data = await response.json();
    
    if (data.success) {
      sessionId = data.session_id;
      showNotification('Playwright browser launching...', 'success');
      await waitForBrowserLaunch();
    } else {
      throw new Error(data.error || 'Failed to start recording');
    }
  } catch (error) {
    showNotification('Failed to start: ' + error.message, 'error');
    resetRecordingUI();
  }
}

async function waitForBrowserLaunch() {
  let attempts = 0;
  const maxAttempts = 30;
  
  const checkBrowser = async () => {
    attempts++;
    try {
      const response = await fetch(`/api/automation-test-creator/recording-status/${sessionId}`);
      const data = await response.json();
      
      if (data.status === 'recording') {
        onBrowserLaunched();
        return true;
      } else if (data.status === 'failed') {
        throw new Error('Browser launch failed');
      }
    } catch (error) {
      console.log(`Attempt ${attempts}/${maxAttempts}...`);
    }
    
    if (attempts < maxAttempts) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      return checkBrowser();
    } else {
      throw new Error('Browser launch timeout');
    }
  };
  
  try {
    await checkBrowser();
  } catch (error) {
    showNotification('Browser launch timeout', 'error');
    resetRecordingUI();
  }
}

function onBrowserLaunched() {
  document.getElementById('launchingIndicator').style.display = 'none';
  
  const confirmDiv = document.getElementById('browserConfirm');
  confirmDiv.style.display = 'block';
  confirmDiv.innerHTML = `
    <div style="text-align: center; padding: 25px; background: #dbeafe; border: 2px solid #3b82f6; border-radius: 12px;">
      <i class="fas fa-browser" style="font-size: 3rem; color: #3b82f6; margin-bottom: 1rem;"></i>
      <h3 style="margin: 0 0 1rem 0; color: #1e40af;">Browser Launching</h3>
      <p style="margin: 0 0 1.5rem 0; color: #1e40af;">
        The Playwright browser is starting on your system.<br>
        <strong>Please wait for the browser window to appear.</strong>
      </p>
      <button class="btn btn-primary" onclick="confirmBrowserVisible()">
        <i class="fas fa-check"></i> I See the Browser - Continue
      </button>
    </div>
  `;
}

function confirmBrowserVisible() {
  document.getElementById('browserConfirm').style.display = 'none';
  document.getElementById('videoRecordingSection').style.display = 'block';
  showNotification('Browser ready! Perform your test actions now.', 'success');
}

// Video Recording
document.getElementById('startVideoBtn').addEventListener('click', startVideoRecording);
document.getElementById('skipVideoBtn').addEventListener('click', skipVideo);

async function startVideoRecording() {
  try {
    recordingStream = await navigator.mediaDevices.getDisplayMedia({
      video: { mediaSource: 'screen' },
      audio: false
    });
    
    mediaRecorder = new MediaRecorder(recordingStream, {
      mimeType: 'video/webm;codecs=vp9'
    });
    
    const chunks = [];
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    
    mediaRecorder.onstop = () => {
      recordedVideo = new Blob(chunks, { type: 'video/webm' });
      console.log('Video recorded, size:', recordedVideo.size);
    };
    
    mediaRecorder.start();
    
    document.getElementById('videoRecordingSection').style.display = 'none';
    document.getElementById('recordingStatus').style.display = 'block';
    document.getElementById('videoStatusText').textContent = 'Recording';
    document.getElementById('finishRecordingSection').style.display = 'block';
    
    showNotification('Video recording started! Select the Playwright browser window.', 'success');
    
    recordingStream.getVideoTracks()[0].addEventListener('ended', () => {
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
      }
    });
  } catch (error) {
    showNotification('Failed to start video: ' + error.message, 'error');
    skipVideo();
  }
}

function skipVideo() {
  document.getElementById('videoRecordingSection').style.display = 'none';
  document.getElementById('recordingStatus').style.display = 'block';
  document.getElementById('videoStatusText').textContent = 'Skipped';
  document.getElementById('finishRecordingSection').style.display = 'block';
  showNotification('Continuing without video. Only code will be captured.', 'success');
}

// Finish Recording
document.getElementById('stopRecordBtn').addEventListener('click', finishRecording);

async function finishRecording() {
  try {
    document.getElementById('stopRecordBtn').disabled = true;
    document.getElementById('processingIndicator').style.display = 'block';
    
    // Stop video if recording
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    
    if (recordingStream) {
      recordingStream.getTracks().forEach(track => track.stop());
    }
    
    // Get recorded code
    const response = await fetch(`/api/automation-test-creator/stop-recording/${sessionId}`, {
      method: 'POST'
    });
    const data = await response.json();
    
    if (data.success && data.code) {
      recordedCode = data.code;
      
      // Display code
      document.getElementById('recordedCode').textContent = recordedCode;
      document.getElementById('codePreviewSection').style.display = 'block';
      
      // Display video if available
      if (recordedVideo) {
        const videoUrl = URL.createObjectURL(recordedVideo);
        document.getElementById('videoPreview').src = videoUrl;
        document.getElementById('videoPreviewSection').style.display = 'block';
      }
      
      document.getElementById('processingIndicator').style.display = 'none';
      document.getElementById('recordingStatus').style.display = 'none';
      document.getElementById('finishRecordingSection').style.display = 'none';
      document.getElementById('nextStepSection').style.display = 'block';
      
      document.querySelector('[data-tab="record"]').classList.add('completed');
      showNotification('Recording complete!', 'success');
    } else {
      throw new Error(data.error || 'Failed to get recorded code');
    }
  } catch (error) {
    showNotification('Failed to finish recording: ' + error.message, 'error');
    document.getElementById('processingIndicator').style.display = 'none';
  }
}

function resetRecordingUI() {
  document.getElementById('startRecordBtn').disabled = false;
  document.getElementById('startRecordBtn').innerHTML = '<i class="fas fa-robot"></i> Start Playwright Browser';
  document.getElementById('launchingIndicator').style.display = 'none';
  sessionId = null;
}

// ========================================
// Step 2: AI Generation with Video Analysis
// ========================================

function updateVideoIndicators() {
  if (recordedVideo) {
    // Update video indicator if it exists
    const videoIndicator = document.getElementById('videoGenIndicator');
    if (videoIndicator) {
      videoIndicator.style.display = 'inline';
    }
    
    // Optional: Update other UI elements if they exist
    const videoAnalysisText = document.getElementById('videoAnalysisText');
    if (videoAnalysisText) {
      videoAnalysisText.style.display = 'inline';
    }
    
    const videoStepsText = document.getElementById('videoStepsText');
    if (videoStepsText) {
      videoStepsText.style.display = 'inline';
    }
  }
}

document.getElementById('aiGenerateBtn').addEventListener('click', generateWithAI);

async function generateWithAI() {
  if (!recordedCode) {
    showNotification('Please record a test first', 'error');
    return;
  }
  
  const btn = document.getElementById('aiGenerateBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> AI Analyzing...';
  
  try {
    const formData = new FormData();
    formData.append('code', recordedCode);
    formData.append('session_id', sessionId);
    
    if (recordedVideo) {
      formData.append('video', recordedVideo, 'test-recording.webm');
    }
    
    const response = await fetch('/api/automation-test-creator/generate-with-ai', {
      method: 'POST',
      body: formData
    });
    
    const data = await response.json();
    
    if (data.success) {
      document.getElementById('testSummary').value = data.summary;
      document.getElementById('testDescription').value = data.description;
      
      // Store the automated code (beautified with AI comments and waits)
      const automatedCode = data.automated_code || recordedCode;
      
      // IMPORTANT: Update recordedCode with the beautified version
      // This ensures the edited code, preview, and export all use the AI-enhanced version
      recordedCode = automatedCode;
      
      generatedAutomatedSteps = []; // No longer used
      generatedManualSteps = data.manual_steps || [];
      
      // Display automated code with syntax highlighting
      if (automatedCode) {
        const codeDisplay = document.getElementById('automatedStepsContent');
        codeDisplay.innerHTML = `
          <div class="code-block-wrapper">
            <div class="code-header">
              <span class="code-language">Python (Playwright)</span>
              <span style="background: linear-gradient(135deg, #10b981 0%, #059669 100%); color: white; padding: 4px 10px; border-radius: 4px; font-size: 11px; font-weight: 600; margin-left: 10px;">
                <i class="fas fa-sparkles"></i> AI Enhanced
              </span>
              <button class="copy-code-btn" onclick="copyCodeToClipboard()">
                <i class="fas fa-copy"></i> Copy Code
              </button>
            </div>
            <pre><code class="language-python">${escapeHtml(automatedCode)}</code></pre>
          </div>
        `;
        
        // Apply syntax highlighting if Prism.js is available
        if (typeof Prism !== 'undefined') {
          Prism.highlightAll();
        }
        
        document.getElementById('automatedStepsPreview').style.display = 'block';
      }
      
      // Display manual steps with enhanced styling
      if (generatedManualSteps.length > 0) {
        document.getElementById('manualStepsContent').innerHTML = `
          <div class="manual-steps-list">
            ${generatedManualSteps.map((step, index) => `
              <div class="manual-step-item">
                <div class="step-number">${index + 1}</div>
                <div class="step-content">${escapeHtml(step)}</div>
              </div>
            `).join('')}
          </div>
        `;
        document.getElementById('manualStepsPreview').style.display = 'block';
      }
      
      // Update Jira preview after generation
      updateJiraPreview();
      
      showNotification('✨ Test details generated with AI! Code includes comments, waits, and improvements.', 'success');
      document.querySelector('[data-tab="generate"]').classList.add('completed');
    } else {
      throw new Error(data.error || 'AI generation failed');
    }
  } catch (error) {
    showNotification('AI generation failed: ' + error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-magic"></i> Generate with AI' + 
      (recordedVideo ? ' <span id="videoGenIndicator">(with Video Analysis)</span>' : '');
  }
}

// Helper function to escape HTML
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// Helper function to copy code to clipboard
function copyCodeToClipboard() {
  const codeElement = document.querySelector('#automatedStepsContent pre code');
  const code = codeElement.textContent;
  
  navigator.clipboard.writeText(code).then(() => {
    showNotification('Code copied to clipboard!', 'success');
  }).catch(err => {
    showNotification('Failed to copy code', 'error');
  });
}

// ========================================
// Step 3: Export Options
// ========================================

function updateJiraPreview() {
  document.getElementById('previewSummary').textContent = 
    document.getElementById('testSummary').value || 'Not specified';
  document.getElementById('previewDescription').textContent = 
    document.getElementById('testDescription').value || 'Not specified';
  
  // Display automated code (Playwright test code)
  if (recordedCode) {
    const previewCodeHtml = `
      <div style="background: #f8f9fa; border-left: 4px solid #667eea; padding: 15px; border-radius: 5px; margin-top: 10px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
          <span style="font-weight: 600; color: #667eea; font-size: 13px;">
            <i class="fas fa-code"></i> Automated Test Code (Playwright)
          </span>
          <span style="background: #667eea; color: white; padding: 3px 8px; border-radius: 3px; font-size: 11px;">Python</span>
        </div>
        <pre style="background: #282c34; color: #abb2bf; padding: 15px; border-radius: 5px; overflow-x: auto; margin: 0; font-size: 12px; line-height: 1.5;"><code class="language-python">${escapeHtml(recordedCode)}</code></pre>
      </div>
    `;
    document.getElementById('previewAutomatedSteps').innerHTML = previewCodeHtml;
    
    // Apply syntax highlighting if Prism.js is available
    if (typeof Prism !== 'undefined') {
      Prism.highlightAll();
    }
  } else {
    document.getElementById('previewAutomatedSteps').innerHTML = 
      '<p style="color: #999; font-style: italic;">No automated code available</p>';
  }
  
  // Display manual steps
  if (generatedManualSteps.length > 0) {
    const stepsHtml = `
      <ol style="margin: 0; padding-left: 20px;">
        ${generatedManualSteps.map(step => `
          <li style="margin-bottom: 8px; color: #333; line-height: 1.6;">${escapeHtml(step)}</li>
        `).join('')}
      </ol>
    `;
    document.getElementById('previewManualSteps').innerHTML = stepsHtml;
  } else {
    document.getElementById('previewManualSteps').innerHTML = 
      '<p style="color: #999; font-style: italic;">No manual steps available</p>';
  }
}

// Add event listeners to update preview as user types
document.getElementById('testSummary').addEventListener('input', updateJiraPreview);
document.getElementById('testDescription').addEventListener('input', updateJiraPreview);

// Jira Export
document.getElementById('exportToJiraBtn').addEventListener('click', exportToJira);

async function exportToJira() {
  const summary = document.getElementById('testSummary').value;
  const description = document.getElementById('testDescription').value;
  const project = document.getElementById('jiraProject').value || 'IRA';
  
  if (!summary || !recordedCode) {
    showNotification('Please provide summary and recorded code', 'error');
    return;
  }
  
  const btn = document.getElementById('exportToJiraBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> Creating Task...';
  
  try {
    const response = await fetch('/api/automation-test-creator/export-jira', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        summary,
        description,
        automated_code: recordedCode,
        automated_steps: generatedAutomatedSteps,
        manual_steps: generatedManualSteps,
        project,
        session_id: sessionId
      })
    });
    
    const data = await response.json();
    
    if (data.success) {
      currentTestData.jira_key = data.issue_key;
      document.getElementById('createdTaskInfo').innerHTML = `
        <strong>Task:</strong> <a href="${data.issue_url}" target="_blank">${data.issue_key}</a>
      `;
      document.getElementById('exportSuccess').style.display = 'block';
      document.getElementById('importTicketId').value = data.issue_key;
      showNotification('Jira task created successfully!', 'success');
      document.querySelector('[data-tab="export"]').classList.add('completed');
    } else {
      throw new Error(data.error || 'Export failed');
    }
  } catch (error) {
    showNotification('Failed to create Jira task: ' + error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-cloud-upload-alt"></i> Create Jira Task';
  }
}

// ZIP Download
document.getElementById('downloadZipBtn').addEventListener('click', downloadZip);

async function downloadZip() {
  const testName = document.getElementById('testName').value.trim() || 'automation_test';
  const summary = document.getElementById('testSummary').value;
  
  if (!recordedCode) {
    showNotification('No recorded code to export', 'error');
    return;
  }
  
  const btn = document.getElementById('downloadZipBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> Generating ZIP...';
  
  try {
    const formData = new FormData();
    formData.append('test_name', testName);
    formData.append('summary', summary);
    formData.append('description', document.getElementById('testDescription').value);
    formData.append('automated_code', recordedCode);
    formData.append('automated_steps', JSON.stringify(generatedAutomatedSteps));
    formData.append('manual_steps', JSON.stringify(generatedManualSteps));
    
    if (recordedVideo) {
      formData.append('video', recordedVideo, 'test-recording.webm');
    }
    
    const response = await fetch('/api/automation-test-creator/download-zip', {
      method: 'POST',
      body: formData
    });
    
    if (response.ok) {
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${testName}_${Date.now()}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      
      document.getElementById('downloadSuccess').style.display = 'block';
      showNotification('Test package downloaded!', 'success');
    } else {
      throw new Error('Download failed');
    }
  } catch (error) {
    showNotification('Failed to generate ZIP: ' + error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-download"></i> Download Test Package (.zip)';
  }
}

// ========================================
// Step 4: Import & Execute (Keep existing)
// ========================================

const importFromJiraBtn = document.getElementById('importFromJiraBtn');
const executeTestBtn = document.getElementById('executeTestBtn');
const exportResultsBtn = document.getElementById('exportResultsBtn');

if (importFromJiraBtn) {
  importFromJiraBtn.addEventListener('click', importFromJira);
}
if (executeTestBtn) {
  executeTestBtn.addEventListener('click', executeTest);
}
if (exportResultsBtn) {
  exportResultsBtn.addEventListener('click', exportResultsToJira);
}

async function importFromJira() {
  const ticketId = document.getElementById('importTicketId').value.trim();
  if (!ticketId) {
    showNotification('Enter a ticket ID', 'error');
    return;
  }
  
  const btn = document.getElementById('importFromJiraBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> Importing...';
  
  try {
    const response = await fetch(`/api/automation-test-creator/import-jira/${ticketId}`);
    const data = await response.json();
    
    if (data.success) {
      currentTestData = data.test_data;
      
      // Create beautiful card-based layout for imported test
      document.getElementById('importedTestContent').innerHTML = `
        <!-- Jira ID Card - Displayed at Top -->
        <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 16px 20px; border-radius: 10px; margin-bottom: 20px; box-shadow: 0 4px 12px rgba(102, 126, 234, 0.3);">
          <div style="display: flex; align-items: center; gap: 12px;">
            <i class="fas fa-ticket-alt" style="font-size: 20px;"></i>
            <div>
              <div style="font-size: 12px; opacity: 0.9; font-weight: 500;">Jira Ticket ID</div>
              <div style="font-size: 18px; font-weight: 700; letter-spacing: 0.5px;">${ticketId}</div>
            </div>
          </div>
        </div>

        <!-- Summary Card -->
        <div style="background: white; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #3b82f6; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
            <i class="fas fa-file-alt" style="color: #3b82f6; font-size: 16px;"></i>
            <strong style="color: #1f2937; font-size: 14px;">Summary</strong>
          </div>
          <div style="color: #4b5563; font-size: 15px; line-height: 1.6; padding-left: 26px;">${data.test_data.summary || 'N/A'}</div>
        </div>

        <!-- Description Card -->
        <div style="background: white; padding: 18px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #8b5cf6; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
            <i class="fas fa-align-left" style="color: #8b5cf6; font-size: 16px;"></i>
            <strong style="color: #1f2937; font-size: 14px;">Description</strong>
          </div>
          <div style="color: #4b5563; font-size: 14px; line-height: 1.8; padding-left: 26px; white-space: pre-wrap;">${data.test_data.description || 'N/A'}</div>
        </div>

        <!-- Test Code Card -->
        <div style="background: white; padding: 18px; border-radius: 10px; margin-bottom: 20px; border-left: 4px solid #10b981; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
            <i class="fas fa-code" style="color: #10b981; font-size: 16px;"></i>
            <strong style="color: #1f2937; font-size: 14px;">🤖 Automated Test Code</strong>
          </div>
          <pre class="code-display" style="margin: 0; padding: 16px; background: #1e1e1e; border-radius: 8px; overflow-x: auto; max-height: 400px;"><code class="language-python">${escapeHtml(data.test_data.code || 'No code available')}</code></pre>
        </div>

        <!-- Manual Steps Card (if available) -->
        ${data.test_data.manual_steps ? `
        <div style="background: white; padding: 18px; border-radius: 10px; margin-bottom: 20px; border-left: 4px solid #f59e0b; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
          <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 12px;">
            <i class="fas fa-list-ol" style="color: #f59e0b; font-size: 16px;"></i>
            <strong style="color: #1f2937; font-size: 14px;">📋 Manual Test Steps</strong>
          </div>
          <div style="color: #4b5563; font-size: 14px; line-height: 1.8; padding-left: 26px; white-space: pre-wrap;">${data.test_data.manual_steps}</div>
        </div>
        ` : ''}

        <!-- Execute Button -->
        <button class="btn btn-primary" id="executeTestBtn" style="width: 100%; padding: 14px; font-size: 15px; font-weight: 600; border-radius: 8px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border: none; box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4); transition: all 0.3s ease;">
          <i class="fas fa-play"></i> Execute Test
        </button>
      `;
      
      // Re-apply syntax highlighting
      Prism.highlightAll();
      
      // Re-attach execute button listener
      document.getElementById('executeTestBtn').addEventListener('click', executeTest);
      
      document.getElementById('importedTestPreview').style.display = 'block';
      showNotification('Test imported successfully!', 'success');
    } else {
      throw new Error(data.error || 'Import failed');
    }
  } catch (error) {
    showNotification('Failed to import: ' + error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-download"></i> Import';
  }
}

async function executeTest() {
  if (!currentTestData.code) {
    showNotification('No code to execute', 'error');
    return;
  }
  
  const btn = document.getElementById('executeTestBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> Executing...';
  
  const resultsDiv = document.getElementById('executionResults');
  resultsDiv.style.display = 'block';
  document.getElementById('executionStatus').textContent = 'Running...';
  
  try {
    const response = await fetch('/api/automation-test-creator/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        code: currentTestData.code,
        ticket_id: currentTestData.jira_key || document.getElementById('importTicketId').value
      })
    });
    const data = await response.json();
    
    if (data.success) {
      currentTestData.execution_results = data.results;
      const statusDiv = document.getElementById('executionStatus');
      statusDiv.textContent = data.results.status;
      statusDiv.style.background = data.results.status === 'SUCCESS' ? '#28a745' : '#dc3545';
      statusDiv.style.color = 'white';
      
      showNotification('Test executed!', 'success');
      document.getElementById('exportResultsBtn').style.display = 'block';
    } else {
      throw new Error(data.error || 'Execution failed');
    }
  } catch (error) {
    showNotification('Execution failed: ' + error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-play"></i> Execute Test';
  }
}

async function exportResultsToJira() {
  const ticketId = currentTestData.jira_key || document.getElementById('importTicketId').value;
  if (!ticketId || !currentTestData.execution_results) {
    showNotification('No results to export', 'error');
    return;
  }
  
  const btn = document.getElementById('exportResultsBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="loading-spinner"></span> Exporting...';
  
  try {
    const response = await fetch(`/api/automation-test-creator/export-results/${ticketId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results: currentTestData.execution_results })
    });
    const data = await response.json();
    
    if (data.success) {
      showNotification('Results exported to Jira!', 'success');
      document.querySelector('[data-tab="execute"]').classList.add('completed');
    } else {
      throw new Error(data.error || 'Export failed');
    }
  } catch (error) {
    showNotification('Failed to export: ' + error.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<i class="fas fa-file-export"></i> Export Results to Jira';
  }
}

// ========================================
// Code Editor Functions
// ========================================

let originalCode = ''; // Store original code for cancel operation
let isEditingCode = false;

function toggleCodeEditor() {
  const readOnlyView = document.getElementById('automatedStepsContent');
  const editorContainer = document.getElementById('codeEditorContainer');
  const warningBanner = document.getElementById('editWarningBanner');
  const editBtn = document.getElementById('editCodeBtn');
  const saveBtn = document.getElementById('saveCodeBtn');
  const cancelBtn = document.getElementById('cancelEditBtn');
  const codeEditor = document.getElementById('codeEditor');
  
  if (!recordedCode) {
    showNotification('No code to edit. Please generate code first.', 'error');
    return;
  }
  
  // Store original code
  originalCode = recordedCode;
  
  // Switch to edit mode
  readOnlyView.style.display = 'none';
  editorContainer.style.display = 'block';
  warningBanner.style.display = 'block';
  editBtn.style.display = 'none';
  saveBtn.style.display = 'inline-block';
  cancelBtn.style.display = 'inline-block';
  
  // Populate editor with current code
  codeEditor.value = recordedCode;
  updateLineCounter();
  
  // Add event listener for line counter
  codeEditor.addEventListener('input', updateLineCounter);
  
  // Enable Tab key for indentation
  codeEditor.addEventListener('keydown', handleTabKey);
  
  isEditingCode = true;
  showNotification('Edit mode activated. Remember to save your changes!', 'info');
}

function saveEditedCode() {
  const codeEditor = document.getElementById('codeEditor');
  const editedCode = codeEditor.value;
  
  if (!editedCode.trim()) {
    showNotification('Cannot save empty code', 'error');
    return;
  }
  
  // Update the recorded code with edited version
  recordedCode = editedCode;
  
  // Regenerate the display
  const codeDisplay = document.getElementById('automatedStepsContent');
  codeDisplay.innerHTML = `
    <div class="code-block-wrapper">
      <div class="code-header">
        <span class="code-language">Python (Playwright)</span>
        <button class="copy-code-btn" onclick="copyCodeToClipboard()">
          <i class="fas fa-copy"></i> Copy Code
        </button>
      </div>
      <pre><code class="language-python">${escapeHtml(editedCode)}</code></pre>
    </div>
  `;
  
  // Apply syntax highlighting if Prism.js is available
  if (typeof Prism !== 'undefined') {
    Prism.highlightAll();
  }
  
  // Update preview
  updateJiraPreview();
  
  // Exit edit mode
  exitEditMode();
  
  showNotification('✅ Code saved successfully! Remember to test your changes in the Execute tab.', 'success');
}

function cancelCodeEdit() {
  // Restore original code
  recordedCode = originalCode;
  
  // Exit edit mode without saving
  exitEditMode();
  
  showNotification('Changes discarded', 'info');
}

function exitEditMode() {
  const readOnlyView = document.getElementById('automatedStepsContent');
  const editorContainer = document.getElementById('codeEditorContainer');
  const warningBanner = document.getElementById('editWarningBanner');
  const editBtn = document.getElementById('editCodeBtn');
  const saveBtn = document.getElementById('saveCodeBtn');
  const cancelBtn = document.getElementById('cancelEditBtn');
  
  // Switch back to read-only view
  readOnlyView.style.display = 'block';
  editorContainer.style.display = 'none';
  warningBanner.style.display = 'none';
  editBtn.style.display = 'inline-block';
  saveBtn.style.display = 'none';
  cancelBtn.style.display = 'none';
  
  isEditingCode = false;
}

function updateLineCounter() {
  const codeEditor = document.getElementById('codeEditor');
  const lineCounter = document.getElementById('lineCounter');
  const lines = codeEditor.value.split('\n').length;
  const chars = codeEditor.value.length;
  lineCounter.textContent = `Lines: ${lines} | Characters: ${chars}`;
}

function handleTabKey(e) {
  if (e.key === 'Tab') {
    e.preventDefault();
    const start = this.selectionStart;
    const end = this.selectionEnd;
    const value = this.value;
    
    // Insert 4 spaces at cursor position
    this.value = value.substring(0, start) + '    ' + value.substring(end);
    
    // Move cursor after the inserted spaces
    this.selectionStart = this.selectionEnd = start + 4;
  }
}

// ========================================
// Utility Functions
// ========================================

function showNotification(message, type) {
  const notification = document.getElementById('notification');
  notification.textContent = message;
  notification.className = `notification ${type} visible`;
  setTimeout(() => notification.classList.remove('visible'), 5000);
}
