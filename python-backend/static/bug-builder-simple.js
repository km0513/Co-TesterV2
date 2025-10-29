let sessionId = null;
let recordedSteps = [];
let recordedScript = '';  // Store the actual Playwright script
let recordedBlob = null;
let mediaRecorder = null;
let recordingStream = null;

function generateId() {
  return 'session_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// Step 1: Start Playwright
async function startPlaywright() {
  const url = prompt('Enter the URL to test (e.g., https://stage-lxp.upgrad.com):');
  if (!url) return;
  
  // Disable button and show launching indicator
  const startBtn = document.getElementById('startPlaywrightBtn');
  startBtn.disabled = true;
  startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Launching...';
  document.getElementById('launchingIndicator').style.display = 'block';
  
  try {
    const response = await fetch('/api/bug-builder/start-playwright-recording', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    
    const data = await response.json();
    console.log('Start Playwright response:', data);
    
    if (data.success) {
      sessionId = data.session_id;
      console.log('Session ID from backend:', sessionId);
      
      // Wait for browser to actually launch
      await waitForBrowserLaunch();
      
    } else {
      showStatus('status1', 'Error: ' + data.error, 'error');
      startBtn.disabled = false;
      startBtn.innerHTML = '<i class="fas fa-robot"></i> Start Playwright Browser';
      document.getElementById('launchingIndicator').style.display = 'none';
    }
  } catch (error) {
    showStatus('status1', 'Error: ' + error.message, 'error');
    startBtn.disabled = false;
    startBtn.innerHTML = '<i class="fas fa-robot"></i> Start Playwright Browser';
    document.getElementById('launchingIndicator').style.display = 'none';
  }
}

async function waitForBrowserLaunch() {
  console.log('Waiting for browser to launch...');
  let attempts = 0;
  const maxAttempts = 30; // 30 seconds max
  
  const checkBrowser = async () => {
    attempts++;
    
    try {
      // Check if session exists and is recording
      const response = await fetch(`/api/bug-builder/get-playwright-recording/${sessionId}`);
      const data = await response.json();
      
      if (data.status === 'recording' || data.playwright_status === 'recording') {
        // Browser is launched!
        console.log('✅ Browser launched successfully!');
        onBrowserLaunched();
        return true;
      } else if (data.status === 'failed') {
        throw new Error('Browser launch failed');
      }
    } catch (error) {
      // Session might not exist yet, keep trying
      console.log(`Attempt ${attempts}/${maxAttempts}...`);
    }
    
    if (attempts < maxAttempts) {
      await sleep(1000);
      return checkBrowser();
    } else {
      throw new Error('Browser launch timeout');
    }
  };
  
  try {
    await checkBrowser();
  } catch (error) {
    console.error('Browser launch error:', error);
    showStatus('status1', 'Browser launch timeout. Please try again.', 'error');
    document.getElementById('startPlaywrightBtn').disabled = false;
    document.getElementById('startPlaywrightBtn').innerHTML = '<i class="fas fa-robot"></i> Start Playwright Browser';
    document.getElementById('launchingIndicator').style.display = 'none';
  }
}

function onBrowserLaunched() {
  console.log('Browser process started!');
  
  // Hide launching indicator
  document.getElementById('launchingIndicator').style.display = 'none';
  
  // Show confirmation prompt
  const confirmDiv = document.createElement('div');
  confirmDiv.id = 'browserConfirm';
  confirmDiv.style.cssText = 'margin-top: 2rem; padding: 2rem; background: #dbeafe; border: 2px solid #3b82f6; border-radius: 12px;';
  confirmDiv.innerHTML = `
    <div style="text-align: center;">
      <i class="fas fa-browser" style="font-size: 3rem; color: #3b82f6; margin-bottom: 1rem;"></i>
      <h3 style="margin: 0 0 1rem 0; color: #1e40af;">Waiting for Browser Window</h3>
      <p style="margin: 0 0 1.5rem 0; color: #1e40af;">
        The Playwright browser is launching on your system.<br>
        <strong>Please wait for the browser window to appear on your screen.</strong><br>
        <small>This may take 5-30 seconds depending on your system resources.</small>
      </p>
      <button class="primary-btn" onclick="confirmBrowserVisible()" style="margin: 0 auto;">
        <i class="fas fa-check"></i>
        I Can See the Browser - Continue
      </button>
    </div>
  `;
  
  document.getElementById('status1').appendChild(confirmDiv);
}

function confirmBrowserVisible() {
  console.log('✅ User confirmed browser is visible');
  
  // Remove confirmation prompt
  const confirmDiv = document.getElementById('browserConfirm');
  if (confirmDiv) {
    confirmDiv.remove();
  }
  
  // Show success message
  showStatus('status1', '✅ Great! Now perform your bug reproduction steps in the Playwright browser.', 'success');
  
  // Move to step 2
  setTimeout(() => {
    document.getElementById('step1').style.display = 'none';
    document.getElementById('step2').style.display = 'block';
    document.getElementById('step2').scrollIntoView({ behavior: 'smooth' });
  }, 1500);
  
  // Start polling for completion
  pollPlaywright();
}

// Step 2: Start Video Recording
async function startVideoRecording() {
  try {
    recordingStream = await navigator.mediaDevices.getDisplayMedia({
      video: { mediaSource: 'screen' },
      audio: false
    });
    
    showStatus('status2', 'Select the Playwright browser window to record', 'info');
    
    mediaRecorder = new MediaRecorder(recordingStream, {
      mimeType: 'video/webm;codecs=vp9'
    });
    
    const chunks = [];
    
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    
    mediaRecorder.onstop = () => {
      recordedBlob = new Blob(chunks, { type: 'video/webm' });
      console.log('Video recording stopped, blob size:', recordedBlob.size);
    };
    
    mediaRecorder.start();
    
    showStatus('status2', 'Video recording started! Now perform your bug steps in the Playwright browser.', 'success');
    
    // Show video status
    document.getElementById('videoStatus').style.display = 'flex';
    
    // Move to step 3
    setTimeout(() => {
      document.getElementById('step2').style.display = 'none';
      document.getElementById('step3').style.display = 'block';
    }, 2000);
    
    // Handle when user stops sharing
    recordingStream.getVideoTracks()[0].addEventListener('ended', () => {
      console.log('Screen sharing stopped by user');
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop();
      }
      
      // Show detecting overlay as user likely closed browser
      document.getElementById('detectingOverlay').style.display = 'block';
    });
    
  } catch (error) {
    showStatus('status2', 'Error: ' + error.message + '. Make sure to select the Playwright browser window.', 'error');
  }
}

function skipVideo() {
  showStatus('status2', 'Skipping video recording. Steps only will be captured.', 'info');
  
  setTimeout(() => {
    document.getElementById('step2').style.display = 'none';
    document.getElementById('step3').style.display = 'block';
  }, 1500);
}

// Poll Playwright for completion
async function pollPlaywright() {
  let pollCount = 0;
  const maxPolls = 300; // 10 minutes max (300 * 2 seconds)
  let wasRecording = true;
  
  const check = async () => {
    try {
      pollCount++;
      console.log(`Polling attempt ${pollCount}...`);
      
      const response = await fetch(`/api/bug-builder/get-playwright-recording/${sessionId}`);
      const data = await response.json();
      
      console.log('Poll response:', data);
      
      if (data.status === 'completed') {
        // Browser just closed! Show detecting overlay immediately
        if (wasRecording) {
          console.log('🔍 Browser closed detected! Showing overlay...');
          document.getElementById('detectingOverlay').style.display = 'block';
          wasRecording = false;
          
          // Give a brief moment for the overlay to appear
          await sleep(500);
        }
        
        recordedSteps = data.steps || [];
        recordedScript = data.script || '';  // Store the actual Playwright script
        console.log('✅ Recording completed! Steps:', recordedSteps.length);
        console.log('✅ Script length:', recordedScript.length);
        
        // Hide detecting overlay and show processing overlay
        document.getElementById('detectingOverlay').style.display = 'none';
        document.getElementById('step3').style.display = 'none';
        document.getElementById('processingOverlay').style.display = 'block';
        
        // Stop video recording if active
        if (mediaRecorder && mediaRecorder.state === 'recording') {
          console.log('Stopping video recording...');
          mediaRecorder.stop();
          if (recordingStream) {
            recordingStream.getTracks().forEach(t => t.stop());
          }
        }
        
        // Start processing
        await processRecording();
        
      } else if (data.status === 'failed') {
        console.error('Recording failed:', data.error);
        document.getElementById('detectingOverlay').style.display = 'none';
        showStatus('status3', 'Recording failed: ' + (data.error || 'Unknown error'), 'error');
      } else {
        // Still recording
        if (pollCount < maxPolls) {
          setTimeout(check, 2000);
        } else {
          document.getElementById('detectingOverlay').style.display = 'none';
          showStatus('status3', 'Recording timeout. Please try again.', 'error');
        }
      }
    } catch (error) {
      console.error('Poll error:', error);
      if (pollCount < maxPolls) {
        setTimeout(check, 2000);
      }
    }
  };
  
  // Start polling
  check();
}

async function processRecording() {
  console.log('🔄 Starting processing...');
  
  // Step 1: Extract steps (already done)
  await sleep(800);
  completeProcessingStep('step-extract');
  console.log('✅ Step extraction complete');
  
  // Step 2: Process video (if available)
  if (recordedBlob) {
    showProcessingStep('step-video');
    await sleep(1000);
    completeProcessingStep('step-video');
    console.log('✅ Video processing complete');
  }
  
  // Step 3: AI Enhancement
  showProcessingStep('step-ai');
  console.log('🤖 Starting AI enhancement...');
  await enhanceWithAI();
  await sleep(500);
  completeProcessingStep('step-ai');
  console.log('✅ AI enhancement complete');
  
  // Step 4: Complete
  await sleep(300);
  showProcessingStep('step-complete');
  console.log('✅ All processing complete!');
  
  // Wait a bit then show review
  await sleep(1200);
  document.getElementById('processingOverlay').style.display = 'none';
  showReview();
}

function showProcessingStep(stepId) {
  document.getElementById(stepId).style.display = 'flex';
}

function completeProcessingStep(stepId) {
  const step = document.getElementById(stepId);
  step.classList.add('complete');
  const icon = step.querySelector('i');
  icon.className = 'fas fa-check-circle';
  icon.style.color = '#10b981';
}

async function enhanceWithAI() {
  if (recordedSteps.length === 0) {
    console.log('No steps to enhance');
    return;
  }
  
  const originalSteps = [...recordedSteps];
  
  try {
    console.log('Enhancing steps with AI...');
    console.log('Original steps:', originalSteps);
    
    const response = await fetch('/api/bug-builder/generate-steps', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        steps_text: recordedSteps.join('\n')
      })
    });
    
    const data = await response.json();
    console.log('AI response:', data);
    
    if (data.steps && data.steps.length > 0) {
      console.log('✅ AI enhanced steps:', data.steps);
      console.log(`Improved from ${originalSteps.length} to ${data.steps.length} steps`);
      recordedSteps = data.steps;
      
      // Show a visual indicator that AI worked
      const aiStep = document.getElementById('step-ai');
      const aiText = aiStep.querySelector('span');
      aiText.textContent = `Enhanced ${data.steps.length} steps with AI`;
    } else {
      console.log('⚠️ AI returned no steps, keeping original');
    }
  } catch (error) {
    console.error('❌ AI enhancement error:', error);
    // Continue with original steps if AI fails
    console.log('Continuing with original steps');
  }
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function showReview() {
  console.log('showReview called');
  console.log('Recorded steps:', recordedSteps);
  console.log('Recorded blob:', recordedBlob);
  
  // Show step 4: Complete Bug Report
  const step4 = document.getElementById('step4');
  step4.style.display = 'block';
  step4.scrollIntoView({ behavior: 'smooth' });
  
  // Show video if available
  if (recordedBlob && recordedBlob.size > 0) {
    console.log('Showing video, size:', recordedBlob.size);
    document.getElementById('videoSection').style.display = 'block';
    const video = document.getElementById('videoPlayer');
    video.src = URL.createObjectURL(recordedBlob);
  }
  
  // Display editable steps
  displayEditableSteps();
  
  console.log('Review display complete');
}

function displayEditableSteps() {
  const container = document.getElementById('editableStepsList');
  container.innerHTML = '';
  
  if (recordedSteps.length === 0) {
    container.innerHTML = '<p style="color: #666; padding: 2rem; text-align: center;">No steps recorded. Click "Add Step" to add manually.</p>';
    return;
  }
  
  recordedSteps.forEach((step, index) => {
    const div = document.createElement('div');
    div.className = 'editable-step';
    div.dataset.index = index;
    div.dataset.failed = 'false';
    
    div.innerHTML = `
      <div class="step-number-badge">${index + 1}</div>
      <input type="text" class="step-input-field" value="${step.replace(/"/g, '&quot;')}" 
             onchange="updateStep(${index}, this.value)">
      <div class="step-actions">
        <button class="step-action-btn btn-fail" onclick="toggleFail(${index})" title="Mark as Failed Step">
          <i class="fas fa-exclamation-triangle"></i>
        </button>
        ${index > 0 ? `<button class="step-action-btn btn-move" onclick="moveStepUp(${index})" title="Move Up">
          <i class="fas fa-arrow-up"></i>
        </button>` : ''}
        ${index < recordedSteps.length - 1 ? `<button class="step-action-btn btn-move" onclick="moveStepDown(${index})" title="Move Down">
          <i class="fas fa-arrow-down"></i>
        </button>` : ''}
        <button class="step-action-btn btn-delete" onclick="deleteStep(${index})" title="Delete">
          <i class="fas fa-trash"></i>
        </button>
      </div>
    `;
    
    container.appendChild(div);
  });
}

function updateStep(index, value) {
  recordedSteps[index] = value;
  console.log(`Step ${index + 1} updated:`, value);
}

function toggleFail(index) {
  const stepDiv = document.querySelector(`.editable-step[data-index="${index}"]`);
  const failBtn = stepDiv.querySelector('.btn-fail');
  const isFailed = stepDiv.dataset.failed === 'true';
  
  if (isFailed) {
    stepDiv.dataset.failed = 'false';
    stepDiv.classList.remove('failed');
    failBtn.classList.remove('active');
  } else {
    stepDiv.dataset.failed = 'true';
    stepDiv.classList.add('failed');
    failBtn.classList.add('active');
  }
  
  console.log(`Step ${index + 1} marked as ${isFailed ? 'passed' : 'failed'}`);
}

function deleteStep(index) {
  if (confirm('Delete this step?')) {
    recordedSteps.splice(index, 1);
    displayEditableSteps();
  }
}

function moveStepUp(index) {
  if (index > 0) {
    [recordedSteps[index], recordedSteps[index - 1]] = [recordedSteps[index - 1], recordedSteps[index]];
    displayEditableSteps();
  }
}

function moveStepDown(index) {
  if (index < recordedSteps.length - 1) {
    [recordedSteps[index], recordedSteps[index + 1]] = [recordedSteps[index + 1], recordedSteps[index]];
    displayEditableSteps();
  }
}

function addStep() {
  const newStep = prompt('Enter new step:');
  if (newStep && newStep.trim()) {
    recordedSteps.push(newStep.trim());
    displayEditableSteps();
  }
}

function generateBugReport() {
  const title = document.getElementById('bugTitle').value.trim();
  const expected = document.getElementById('expectedResult').value.trim();
  const actual = document.getElementById('actualResult').value.trim();
  
  if (!title) {
    alert('Please enter a bug title');
    document.getElementById('bugTitle').focus();
    return;
  }
  
  if (recordedSteps.length === 0) {
    alert('Please add at least one step to reproduce');
    return;
  }
  
  if (!expected) {
    alert('Please enter the expected result');
    document.getElementById('expectedResult').focus();
    return;
  }
  
  if (!actual) {
    alert('Please enter the actual result');
    document.getElementById('actualResult').focus();
    return;
  }
  
  // Generate report preview
  const failedSteps = [];
  document.querySelectorAll('.editable-step[data-failed="true"]').forEach(step => {
    failedSteps.push(parseInt(step.dataset.index) + 1);
  });
  
  let report = `BUG REPORT
===========

Title: ${title}

Steps to Reproduce:
${recordedSteps.map((s, i) => {
    const stepNum = i + 1;
    const isFailed = failedSteps.includes(stepNum);
    return `${stepNum}. ${s}${isFailed ? ' ❌ [FAILED]' : ''}`;
  }).join('\n')}

Expected Result:
${expected}

Actual Result:
${actual}

${recordedBlob ? 'Video Recording: Attached\n' : ''}
Generated by Co-Tester Bug Builder
Date: ${new Date().toLocaleString()}`;
  
  // Show preview
  document.getElementById('bugReportPreview').textContent = report;
  document.getElementById('step4').style.display = 'none';
  document.getElementById('step5').style.display = 'block';
  document.getElementById('step5').scrollIntoView({ behavior: 'smooth' });
}

function editReport() {
  document.getElementById('step5').style.display = 'none';
  document.getElementById('step4').style.display = 'block';
  document.getElementById('step4').scrollIntoView({ behavior: 'smooth' });
}

function showExportOptions() {
  document.getElementById('step5').style.display = 'none';
  document.getElementById('step6').style.display = 'block';
  document.getElementById('step6').scrollIntoView({ behavior: 'smooth' });
  
  // Hide video download button if no video
  if (!recordedBlob) {
    document.getElementById('downloadVideoBtn').style.display = 'none';
  }
}

function backToReview() {
  document.getElementById('step6').style.display = 'none';
  document.getElementById('step5').style.display = 'block';
  document.getElementById('step5').scrollIntoView({ behavior: 'smooth' });
}

function manualContinue() {
  console.log('Manual continue clicked');
  
  // Stop video if still recording
  if (mediaRecorder && mediaRecorder.state === 'recording') {
    mediaRecorder.stop();
    if (recordingStream) {
      recordingStream.getTracks().forEach(t => t.stop());
    }
  }
  
  // Force check for steps
  if (sessionId) {
    fetch(`/api/bug-builder/get-playwright-recording/${sessionId}`)
      .then(res => res.json())
      .then(data => {
        console.log('Manual fetch result:', data);
        if (data.steps && data.steps.length > 0) {
          recordedSteps = data.steps;
        }
        showReview();
      })
      .catch(error => {
        console.error('Manual fetch error:', error);
        // Show review anyway
        showReview();
      });
  } else {
    // No session, just show review with what we have
    showReview();
  }
}



async function exportJira() {
  const title = document.getElementById('bugTitle').value;
  const expected = document.getElementById('expectedResult').value;
  const actual = document.getElementById('actualResult').value;
  
  if (!title) {
    showNotification('Please enter a bug title', 'error');
    return;
  }
  
  // Show Jira export modal
  showJiraExportModal();
}

function showJiraExportModal() {
  // Create simplified modal HTML
  const modalHTML = `
    <div class="jira-modal-overlay" id="jiraModalOverlay">
      <div class="jira-modal jira-modal-large">
        <div class="jira-modal-header">
          <h3><i class="fab fa-jira"></i> Export to Jira</h3>
          <button class="modal-close-btn" onclick="closeJiraModal()">
            <i class="fas fa-times"></i>
          </button>
        </div>
        <div class="jira-modal-body" id="jiraModalBody">
          <div class="form-group">
            <label for="jiraProjectKey">Project Key *</label>
            <input type="text" id="jiraProjectKey" placeholder="e.g., PROJ, BUG, TEST" class="form-input" style="text-transform: uppercase;">
            <small>Enter your Jira project key</small>
          </div>
          
          <div class="form-group">
            <label for="jiraSummary">Summary *</label>
            <input type="text" id="jiraSummary" class="form-input" value="${document.getElementById('bugTitle').value}" required>
          </div>
          
          <div class="form-group">
            <label for="jiraDescription">Description *</label>
            <textarea id="jiraDescription" class="form-input" rows="5" required></textarea>
            <small>This will include your bug description, steps, expected and actual results</small>
          </div>
          
          <div class="form-group">
            <label for="jiraPriority">Priority *</label>
            <select id="jiraPriority" class="form-input" required>
              <option value="Highest">Highest</option>
              <option value="High">High</option>
              <option value="Medium" selected>Medium</option>
              <option value="Low">Low</option>
              <option value="Lowest">Lowest</option>
            </select>
          </div>
          
          <div class="form-group">
            <label for="jiraTrivialBug">Trivial Bug *</label>
            <select id="jiraTrivialBug" class="form-input" required>
              <option value="No" selected>No</option>
              <option value="Yes">Yes</option>
            </select>
            <small>Is this a trivial/minor bug?</small>
          </div>
          
          <div class="form-group">
            <label style="display: block; margin-bottom: 0.5rem;">
              <input type="checkbox" id="jiraAttachVideo" ${recordedBlob ? 'checked' : 'disabled'}>
              Attach video recording ${!recordedBlob ? '(no video available)' : ''}
            </label>
            <label style="display: block;">
              <input type="checkbox" id="jiraAttachScript" ${recordedSteps.length > 0 ? 'checked' : 'disabled'}>
              Attach Playwright script ${recordedSteps.length === 0 ? '(no steps recorded)' : ''}
            </label>
          </div>
        </div>
        <div class="jira-modal-footer">
          <button class="btn-secondary" onclick="closeJiraModal()">Cancel</button>
          <button class="btn-primary" id="jiraSubmitBtn" onclick="submitToJira()">
            <i class="fab fa-jira"></i> Create Jira Issue
          </button>
        </div>
      </div>
    </div>
  `;
  
  // Add modal to page
  document.body.insertAdjacentHTML('beforeend', modalHTML);
  
  // Build description from bug details
  const bugDesc = document.getElementById('bugDescription').value;
  const expected = document.getElementById('expectedResult').value;
  const actual = document.getElementById('actualResult').value;
  
  // Get failed steps
  const failedSteps = [];
  document.querySelectorAll('.editable-step[data-failed="true"]').forEach(step => {
    failedSteps.push(parseInt(step.dataset.index) + 1);
  });
  
  // Build description with failed step markers
  const stepsText = recordedSteps.map((s, i) => {
    const stepNum = i + 1;
    const isFailed = failedSteps.includes(stepNum);
    return `${stepNum}. ${s}${isFailed ? ' ❌ [FAILED]' : ''}`;
  }).join('\n');
  
  const fullDescription = `${bugDesc ? bugDesc + '\n\n' : ''}h3. Steps to Reproduce
${stepsText}

h3. Expected Result
${expected}

h3. Actual Result
${actual}

${recordedBlob ? '_Video recording will be attached_\n' : ''}_Generated by Co-Tester Bug Builder on ${new Date().toLocaleString()}_`;
  
  // Set description
  setTimeout(() => {
    document.getElementById('jiraDescription').value = fullDescription;
    document.getElementById('jiraProjectKey').focus();
  }, 100);
}



function closeJiraModal() {
  const modal = document.getElementById('jiraModalOverlay');
  if (modal) {
    modal.remove();
  }
}

async function submitToJira() {
  const projectKey = document.getElementById('jiraProjectKey').value.trim().toUpperCase();
  const summary = document.getElementById('jiraSummary').value.trim();
  const description = document.getElementById('jiraDescription').value.trim();
  const priority = document.getElementById('jiraPriority').value;
  const trivialBug = document.getElementById('jiraTrivialBug').value;
  const attachVideo = document.getElementById('jiraAttachVideo').checked;
  
  // Validation
  if (!projectKey) {
    showNotification('Please enter a project key', 'error');
    document.getElementById('jiraProjectKey').focus();
    return;
  }
  
  if (!summary) {
    showNotification('Please enter a summary', 'error');
    document.getElementById('jiraSummary').focus();
    return;
  }
  
  if (!description) {
    showNotification('Please enter a description', 'error');
    document.getElementById('jiraDescription').focus();
    return;
  }
  
  // Show loading state
  const submitBtn = document.getElementById('jiraSubmitBtn');
  const originalHTML = submitBtn.innerHTML;
  submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Creating...';
  submitBtn.disabled = true;
  
  try {
    // Create Jira issue
    const payload = {
      project_key: projectKey,
      summary: summary,
      description: description,
      priority: priority,
      trivial_bug: trivialBug
    };
    
    const response = await fetch('/api/jira/create-issue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    
    const data = await response.json();
    
    if (data.success && data.issue_key) {
      const attachScript = document.getElementById('jiraAttachScript').checked;
      
      // Upload attachments
      let uploadCount = 0;
      const totalUploads = (attachVideo && recordedBlob ? 1 : 0) + (attachScript && recordedSteps.length > 0 ? 1 : 0);
      
      if (attachVideo && recordedBlob) {
        uploadCount++;
        submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Uploading video (${uploadCount}/${totalUploads})...`;
        await uploadVideoToJira(data.issue_key);
      }
      
      if (attachScript && recordedSteps.length > 0) {
        uploadCount++;
        submitBtn.innerHTML = `<i class="fas fa-spinner fa-spin"></i> Uploading script (${uploadCount}/${totalUploads})...`;
        await uploadScriptToJira(data.issue_key);
      }
      
      // Close modal
      closeJiraModal();
      
      // Show success notification
      const attachmentText = totalUploads > 0 ? ` with ${totalUploads} attachment${totalUploads > 1 ? 's' : ''}` : '';
      showNotification(`✅ Bug created successfully: ${data.issue_key}${attachmentText}`, 'success');
      
      // Open Jira issue in new tab
      if (data.issue_url) {
        setTimeout(() => {
          window.open(data.issue_url, '_blank');
        }, 500);
      }
    } else {
      showNotification('Error creating Jira issue: ' + (data.error || 'Unknown error'), 'error');
    }
  } catch (error) {
    console.error('Jira export error:', error);
    showNotification('Error exporting to Jira: ' + error.message, 'error');
  } finally {
    submitBtn.innerHTML = originalHTML;
    submitBtn.disabled = false;
  }
}

async function uploadVideoToJira(issueKey) {
  if (!recordedBlob) return;
  
  try {
    const formData = new FormData();
    formData.append('file', recordedBlob, 'bug-recording.webm');
    formData.append('issue_key', issueKey);
    
    const response = await fetch('/api/jira/attach-file', {
      method: 'POST',
      body: formData
    });
    
    const data = await response.json();
    if (data.success) {
      console.log('✅ Video attached to Jira issue');
    } else {
      console.error('Failed to attach video:', data.error);
    }
  } catch (error) {
    console.error('Error uploading video to Jira:', error);
  }
}

async function uploadScriptToJira(issueKey) {
  if (recordedSteps.length === 0) return;
  
  try {
    // Use the actual Playwright script if available, otherwise generate from steps
    let script = recordedScript;
    
    if (!script || script.trim() === '') {
      // Fallback: generate script from steps
      script = `from playwright.sync_api import sync_playwright

def test_bug_reproduction():
    """
    Automated test script for bug reproduction
    Generated by Co-Tester Bug Builder
    Date: ${new Date().toLocaleString()}
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        # Recorded steps:
${recordedSteps.map((s, i) => `        # Step ${i + 1}: ${s}`).join('\n')}
        
        # Add your assertions here
        
        context.close()
        browser.close()

if __name__ == "__main__":
    test_bug_reproduction()
`;
    }
    
    // Convert script to blob
    const scriptBlob = new Blob([script], { type: 'text/plain' });
    
    const formData = new FormData();
    formData.append('file', scriptBlob, 'bug_test.py');
    formData.append('issue_key', issueKey);
    
    const response = await fetch('/api/jira/attach-file', {
      method: 'POST',
      body: formData
    });
    
    const data = await response.json();
    if (data.success) {
      console.log('✅ Playwright script attached to Jira issue');
    } else {
      console.error('Failed to attach script:', data.error);
    }
  } catch (error) {
    console.error('Error uploading script to Jira:', error);
  }
}

function downloadScript() {
  if (recordedSteps.length === 0) {
    alert('No steps recorded');
    return;
  }
  
  // Use the actual Playwright script if available, otherwise generate from steps
  let script = recordedScript;
  
  if (!script || script.trim() === '') {
    // Fallback: generate script from steps
    script = `from playwright.sync_api import sync_playwright

def test_bug_reproduction():
    """
    Automated test script for bug reproduction
    Generated by Co-Tester Bug Builder
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
        # Recorded steps:
${recordedSteps.map((s, i) => `        # Step ${i + 1}: ${s}`).join('\n')}
        
        # Add your assertions here
        
        context.close()
        browser.close()

if __name__ == "__main__":
    test_bug_reproduction()
`;
  }
  
  downloadFile(script, 'bug_test.py', 'text/plain');
}

function downloadVideo() {
  if (!recordedBlob) {
    alert('No video recorded');
    return;
  }
  
  const url = URL.createObjectURL(recordedBlob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'bug_recording_' + Date.now() + '.webm';
  a.click();
}

async function downloadAll() {
  if (!window.JSZip) {
    alert('Loading ZIP library...');
    return;
  }
  
  const zip = new JSZip();
  const timestamp = Date.now();
  const title = document.getElementById('bugTitle').value || 'Bug Report';
  const expected = document.getElementById('expectedResult').value;
  const actual = document.getElementById('actualResult').value;
  
  // 1. Add Playwright script - use actual script if available
  if (recordedSteps.length > 0) {
    let script = recordedScript;
    
    // If no actual script, generate from steps
    if (!script || script.trim() === '') {
      // Convert steps to actual Playwright code
      let playwrightCode = '';
      let hasNavigate = false;
      
      recordedSteps.forEach((step, i) => {
        const stepLower = step.toLowerCase();
        
        if (stepLower.includes('navigate to')) {
          const url = step.match(/navigate to (.+)/i)?.[1] || 'URL';
          playwrightCode += `        page.goto("${url}")\n`;
          hasNavigate = true;
        } else if (stepLower.includes('click')) {
          const text = step.match(/click (?:on )?['"]?(.+?)['"]?$/i)?.[1] || step.replace(/click (?:on )?/i, '');
          playwrightCode += `        page.get_by_text("${text}").click()\n`;
        } else if (stepLower.includes('enter text') || stepLower.includes('fill')) {
          const field = step.match(/(?:enter text in|fill) (.+)/i)?.[1] || 'input';
          playwrightCode += `        page.fill("${field}", "your_text_here")\n`;
        } else if (stepLower.includes('press')) {
          const key = step.match(/press (.+)/i)?.[1] || 'Enter';
          playwrightCode += `        page.press("body", "${key}")\n`;
        } else {
          // Generic comment for other actions
          playwrightCode += `        # ${step}\n`;
        }
      });
      
      script = `from playwright.sync_api import sync_playwright

def test_bug_reproduction():
    """
    Automated test script for bug reproduction
    Generated by Co-Tester Bug Builder
    
    Bug: ${title}
    Date: ${new Date().toLocaleString()}
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        
${playwrightCode}
        # Add your assertions here
        # Example: assert page.title() == "Expected Title"
        
        context.close()
        browser.close()

if __name__ == "__main__":
    test_bug_reproduction()
`;
    }
    
    zip.file('bug_test.py', script);
  }
  
  // 2. Add video if available
  if (recordedBlob) {
    zip.file('bug_recording.webm', recordedBlob);
  }
  
  // 3. Add bug report (TXT)
  const reportTxt = `
BUG REPORT
==========

Title: ${title}

Steps to Reproduce:
${recordedSteps.map((s, i) => `${i + 1}. ${s}`).join('\n')}

Expected Result:
${expected}

Actual Result:
${actual}

Generated by Co-Tester Bug Builder
Date: ${new Date().toLocaleString()}
  `.trim();
  zip.file('bug_report.txt', reportTxt);
  
  // 4. Add bug report (Markdown)
  const reportMd = `# Bug Report: ${title}

## Steps to Reproduce

${recordedSteps.map((s, i) => `${i + 1}. ${s}`).join('\n')}

## Expected Result

${expected}

## Actual Result

${actual}

---

*Generated by Co-Tester Bug Builder on ${new Date().toLocaleString()}*
  `.trim();
  zip.file('bug_report.md', reportMd);
  
  // 5. Add README
  const readme = `# Bug Report Package

This package contains all the files related to the bug report: "${title}"

## Contents

- **bug_test.py** - Runnable Playwright test script
${recordedBlob ? '- **bug_recording.webm** - Screen recording of the bug\n' : ''}- **bug_report.txt** - Bug report in plain text format
- **bug_report.md** - Bug report in Markdown format
- **README.md** - This file

## How to Run the Test

1. Install Playwright:
   \`\`\`
   pip install playwright
   playwright install
   \`\`\`

2. Run the test:
   \`\`\`
   python bug_test.py
   \`\`\`

## Generated By

Co-Tester Bug Builder
${new Date().toLocaleString()}
  `.trim();
  zip.file('README.md', readme);
  
  // Generate and download ZIP
  try {
    const content = await zip.generateAsync({ type: 'blob' });
    saveAs(content, `bug_report_${timestamp}.zip`);
  } catch (error) {
    console.error('Error creating ZIP:', error);
    alert('Error creating ZIP file: ' + error.message);
  }
}

function downloadFile(content, filename, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function showStatus(elementId, message, type) {
  const status = document.getElementById(elementId);
  status.textContent = message;
  status.style.display = 'block';
  status.style.padding = '1rem';
  status.style.borderRadius = '8px';
  status.style.marginTop = '1rem';
  
  if (type === 'success') {
    status.style.background = '#d1fae5';
    status.style.color = '#065f46';
    status.style.border = '1px solid #a7f3d0';
  } else if (type === 'error') {
    status.style.background = '#fee2e2';
    status.style.color = '#991b1b';
    status.style.border = '1px solid #fecaca';
  } else {
    status.style.background = '#dbeafe';
    status.style.color = '#1e40af';
    status.style.border = '1px solid #bfdbfe';
  }
}


// Notification system
function showNotification(message, type = 'info') {
  // Remove existing notifications
  const existing = document.querySelectorAll('.bug-notification');
  existing.forEach(n => n.remove());
  
  // Create notification
  const notification = document.createElement('div');
  notification.className = `bug-notification bug-notification-${type}`;
  
  let icon = 'fa-info-circle';
  if (type === 'success') icon = 'fa-check-circle';
  if (type === 'error') icon = 'fa-exclamation-circle';
  if (type === 'warning') icon = 'fa-exclamation-triangle';
  
  notification.innerHTML = `
    <i class="fas ${icon}"></i>
    <span>${message}</span>
    <button class="notification-close" onclick="this.parentElement.remove()">
      <i class="fas fa-times"></i>
    </button>
  `;
  
  document.body.appendChild(notification);
  
  // Auto-remove after 5 seconds
  setTimeout(() => {
    if (notification.parentElement) {
      notification.style.opacity = '0';
      setTimeout(() => notification.remove(), 300);
    }
  }, 5000);
}
