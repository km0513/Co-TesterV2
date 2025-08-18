/**
 * Auto-Healing Test Recorder
 * Advanced Playwright integration with multi-locator strategies
 */

class AutoHealingRecorder {
    constructor() {
        this.sessionId = null;
        this.isRecording = false;
        this.recordedActions = [];
        this.locatorStrategies = [];
        this.initializeEventListeners();
        this.setupMCPIntegration();
    }

    initializeEventListeners() {
        document.getElementById('startRecording')?.addEventListener('click', () => {
            this.startRecording();
        });

        document.getElementById('viewInstructions')?.addEventListener('click', () => {
            this.showInstructions();
        });

        document.getElementById('launchBrowser')?.addEventListener('click', () => {
            this.launchBrowser();
        });

        document.getElementById('stopRecording')?.addEventListener('click', () => {
            this.stopRecording();
        });

        document.getElementById('generateTest')?.addEventListener('click', () => {
            this.generateTestCode();
        });

        document.getElementById('recordAction')?.addEventListener('click', () => {
            this.showActionRecorder();
        });
    }

    setupMCPIntegration() {
        // Listen for MCP Playwright events if available
        if (window.mcpPlaywright) {
            window.mcpPlaywright.on('action_recorded', (action) => {
                this.handleRecordedAction(action);
            });

            window.mcpPlaywright.on('element_identified', (element) => {
                this.generateElementLocators(element);
            });
        }
    }

    async startRecording() {
        const url = document.getElementById('targetUrl').value;
        const startBtn = document.getElementById('startRecording');
        
        if (!url) {
            this.updateStatus('Please enter a valid URL', 'error');
            return;
        }

        // Validate URL format
        if (!this.isValidUrl(url)) {
            this.updateStatus('Please enter a valid URL (e.g., https://example.com)', 'error');
            return;
        }

        // Update UI
        startBtn.innerHTML = '<span class="loading-spinner"></span> Starting...';
        startBtn.disabled = true;
        this.updateStatus('Initializing Playwright codegen session...', 'info');

        try {
            const response = await fetch('/api/auto-healing/start-codegen', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ url })
            });

            const data = await response.json();

            if (data.success) {
                this.sessionId = data.session_id;
                this.updateStatus(
                    `✅ ${data.message}<br>` +
                    `<strong>Session ID:</strong> ${this.sessionId}<br><br>` +
                    `<strong>Next Steps:</strong><br>` +
                    data.next_steps.map((step, i) => `${i + 1}. ${step}`).join('<br>'),
                    'success'
                );
                
                startBtn.innerHTML = '<i class="fas fa-check"></i> Session Initialized';
                startBtn.disabled = true;
                
                // Show browser launch controls
                this.showBrowserControls();
            } else {
                throw new Error(data.error || 'Failed to start recording session');
            }
        } catch (error) {
            console.error('Error starting recording:', error);
            this.updateStatus(`❌ Error: ${error.message}`, 'error');
            
            startBtn.innerHTML = '<i class="fas fa-record-vinyl"></i> Start Playwright Codegen';
            startBtn.disabled = false;
        }
    }

    async launchBrowser() {
        if (!this.sessionId) {
            this.updateStatus('❌ Please start a session first', 'error');
            return;
        }

        const url = document.getElementById('targetUrl').value;
        const launchBtn = document.getElementById('launchBrowser');
        
        launchBtn.innerHTML = '<span class="loading-spinner"></span> Launching...';
        launchBtn.disabled = true;
        this.updateStatus('🚀 Launching Playwright browser...', 'info');

        try {
            const response = await fetch('/api/auto-healing/launch-browser', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    session_id: this.sessionId,
                    url: url 
                })
            });

            const data = await response.json();

            if (data.success) {
                if (data.browser_launched) {
                    // Browser actually launched
                    this.updateStatus(
                        `🎉 ${data.message}<br><br>` +
                        `<strong>Browser Status:</strong> ✅ Launched and navigated to ${data.url}<br><br>` +
                        `<strong>Next Steps:</strong><br>` +
                        data.instructions.map((instruction, i) => `${i + 1}. ${instruction}`).join('<br>'),
                        'success'
                    );
                    
                    launchBtn.innerHTML = '✅ Browser Active';
                    launchBtn.style.background = 'linear-gradient(135deg, #48bb78, #38a169)';
                } else {
                    // Fallback to MCP commands
                    this.updateStatus(
                        `⚠️ ${data.message}<br><br>` +
                        `<strong>Available MCP Commands:</strong><br>` +
                        `<code>${data.mcp_commands.navigate || 'N/A'}</code><br>` +
                        `<code>${data.mcp_commands.start_codegen || 'N/A'}</code><br><br>` +
                        `<strong>Copy and paste these commands in Windsurf:</strong><br>` +
                        `1. Navigate to your URL<br>` +
                        `2. Start codegen session<br>` +
                        `3. Interact with the page - actions will be recorded!`,
                        'warning'
                    );
                    
                    launchBtn.innerHTML = '⚠️ Use MCP Commands';
                    launchBtn.style.background = 'linear-gradient(135deg, #ed8936, #f6ad55)';
                }
                
                this.isRecording = true;
                
                // Show recording controls
                this.showRecordingControls();
                if (data.mcp_commands) {
                    this.showMCPCommands(data.mcp_commands);
                }
                
                // Show session management controls
                this.showSessionControls(data.session_id);
            } else {
                throw new Error(data.error || 'Failed to launch browser');
            }
        } catch (error) {
            console.error('Error launching browser:', error);
            this.updateStatus(`❌ Error: ${error.message}`, 'error');
            
            launchBtn.innerHTML = '🚀 Launch Browser';
            launchBtn.disabled = false;
        }
    }

    async stopRecording() {
        if (!this.isRecording) return;

        try {
            this.isRecording = false;
            this.updateStatus('🛑 Recording stopped. Generating auto-healing test code...', 'info');
            
            // Process recorded actions and generate test
            await this.generateTestCode();
            
        } catch (error) {
            console.error('Error stopping recording:', error);
            this.updateStatus(`❌ Error stopping recording: ${error.message}`, 'error');
        }
    }

    async generateTestCode() {
        if (!this.sessionId) {
            this.updateStatus('❌ Please start a session first', 'error');
            return;
        }

        try {
            this.updateStatus('🔄 Generating auto-healing test code...', 'info');
            
            const response = await fetch('/api/auto-healing/generate-test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    session_id: this.sessionId
                })
            });

            const data = await response.json();

            if (data.success) {
                this.displayGeneratedCode(data.test_code);
                this.updateStatus(`✅ Auto-healing test code generated successfully! (${data.actions_count} actions)`, 'success');
            } else {
                throw new Error(data.error || 'Failed to generate test code');
            }
            
        } catch (error) {
            console.error('Error generating test code:', error);
            this.updateStatus(`❌ Error generating test: ${error.message}`, 'error');
        }
    }

    handleRecordedAction(action) {
        // Add auto-healing locator strategies to the action
        const enhancedAction = {
            ...action,
            locators: this.generateMultipleLocators(action.element),
            timestamp: new Date().toISOString(),
            autoHealing: true
        };

        this.recordedActions.push(enhancedAction);
        this.updateActionsList();
    }

    generateMultipleLocators(element) {
        const locators = [];

        // Strategy 1: ID-based (highest priority)
        if (element.id) {
            locators.push({
                strategy: 'id',
                locator: `#${element.id}`,
                playwright: `page.locator('#${element.id}')`,
                priority: 1,
                description: 'ID-based locator (most reliable)'
            });
        }

        // Strategy 2: Data attributes
        const dataAttrs = ['data-testid', 'data-test', 'data-cy', 'data-automation'];
        dataAttrs.forEach(attr => {
            if (element[attr]) {
                locators.push({
                    strategy: 'data-attribute',
                    locator: `[${attr}="${element[attr]}"]`,
                    playwright: `page.locator('[${attr}="${element[attr]}"]')`,
                    priority: 2,
                    description: `${attr} attribute locator`
                });
            }
        });

        // Strategy 3: Role-based (accessibility)
        if (element.role) {
            const nameAttr = element.ariaLabel || element.title || element.textContent;
            const roleLocator = nameAttr ? 
                `page.get_by_role('${element.role}', { name: '${nameAttr}' })` :
                `page.get_by_role('${element.role}')`;
            
            locators.push({
                strategy: 'role',
                locator: `role=${element.role}`,
                playwright: roleLocator,
                priority: 3,
                description: 'Role-based locator (accessibility-friendly)'
            });
        }

        // Strategy 4: Text-based
        if (element.textContent && element.textContent.trim()) {
            locators.push({
                strategy: 'text',
                locator: `text=${element.textContent.trim()}`,
                playwright: `page.get_by_text('${element.textContent.trim()}')`,
                priority: 4,
                description: 'Text-based locator'
            });
        }

        // Strategy 5: CSS class combination
        if (element.classList && element.classList.length > 0) {
            const classSelector = '.' + Array.from(element.classList).join('.');
            locators.push({
                strategy: 'css-class',
                locator: classSelector,
                playwright: `page.locator('${classSelector}')`,
                priority: 5,
                description: 'CSS class-based locator'
            });
        }

        // Strategy 6: XPath (last resort)
        if (element.xpath) {
            locators.push({
                strategy: 'xpath',
                locator: element.xpath,
                playwright: `page.locator('xpath=${element.xpath}')`,
                priority: 6,
                description: 'XPath locator (fallback)'
            });
        }

        // Sort by priority
        return locators.sort((a, b) => a.priority - b.priority);
    }

    buildAutoHealingTest() {
        const testName = `AutoHealingTest_${Date.now()}`;
        const url = document.getElementById('targetUrl').value;
        
        let testCode = `
import { test, expect } from '@playwright/test';

/**
 * Auto-Healing Test Generated by Co-Test
 * Generated: ${new Date().toISOString()}
 * Target URL: ${url}
 */

class AutoHealingLocator {
    constructor(page, strategies) {
        this.page = page;
        this.strategies = strategies;
    }

    async locate() {
        for (const strategy of this.strategies) {
            try {
                const locator = eval(strategy.playwright);
                await locator.waitFor({ timeout: 5000 });
                console.log(\`✅ Located element using \${strategy.strategy}: \${strategy.locator}\`);
                return locator;
            } catch (error) {
                console.log(\`❌ Failed to locate using \${strategy.strategy}: \${strategy.locator}\`);
                continue;
            }
        }
        throw new Error('All locator strategies failed');
    }
}

test('${testName}', async ({ page }) => {
    // Navigate to the target URL
    await page.goto('${url}');
    
`;

        // Generate test steps for each recorded action
        this.recordedActions.forEach((action, index) => {
            testCode += `
    // Step ${index + 1}: ${action.type} action
    {
        const strategies = ${JSON.stringify(action.locators, null, 8)};
        const autoLocator = new AutoHealingLocator(page, strategies);
        const element = await autoLocator.locate();
        
`;

            switch (action.type) {
                case 'click':
                    testCode += `        await element.click();\n`;
                    break;
                case 'fill':
                    testCode += `        await element.fill('${action.value || ''}');\n`;
                    break;
                case 'type':
                    testCode += `        await element.type('${action.value || ''}');\n`;
                    break;
                case 'select':
                    testCode += `        await element.selectOption('${action.value || ''}');\n`;
                    break;
                default:
                    testCode += `        // ${action.type} action\n`;
            }

            testCode += `    }\n`;
        });

        testCode += `
    // Add assertions as needed
    // await expect(page).toHaveURL(/expected-url/);
    // await expect(page.locator('selector')).toBeVisible();
});
`;

        return testCode;
    }

    displayGeneratedCode(testCode) {
        // Create or update code display area
        let codeDisplay = document.getElementById('generatedCodeDisplay');
        if (!codeDisplay) {
            codeDisplay = document.createElement('div');
            codeDisplay.id = 'generatedCodeDisplay';
            codeDisplay.className = 'generated-code-section';
            document.querySelector('.recorder-container').appendChild(codeDisplay);
        }

        codeDisplay.innerHTML = `
            <div class="code-section-header">
                <h3><i class="fas fa-code"></i> Generated Auto-Healing Test</h3>
                <div class="code-actions">
                    <button onclick="this.copyCode()" class="btn-secondary">
                        <i class="fas fa-copy"></i> Copy Code
                    </button>
                    <button onclick="this.downloadCode()" class="btn-secondary">
                        <i class="fas fa-download"></i> Download
                    </button>
                </div>
            </div>
            <pre class="code-display"><code class="language-javascript">${this.escapeHtml(testCode)}</code></pre>
        `;

        // Add copy and download functionality
        codeDisplay.querySelector('button[onclick*="copyCode"]').onclick = () => {
            navigator.clipboard.writeText(testCode);
            this.updateStatus('✅ Test code copied to clipboard!', 'success');
        };

        codeDisplay.querySelector('button[onclick*="downloadCode"]').onclick = () => {
            this.downloadTestFile(testCode);
        };
    }

    downloadTestFile(testCode) {
        const blob = new Blob([testCode], { type: 'text/javascript' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `auto-healing-test-${Date.now()}.spec.js`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    updateActionsList() {
        let actionsList = document.getElementById('recordedActionsList');
        if (!actionsList) {
            actionsList = document.createElement('div');
            actionsList.id = 'recordedActionsList';
            actionsList.className = 'recorded-actions-section';
            document.querySelector('.recorder-container').appendChild(actionsList);
        }

        const actionsHtml = this.recordedActions.map((action, index) => `
            <div class="action-item">
                <div class="action-header">
                    <span class="action-number">${index + 1}</span>
                    <span class="action-type">${action.type}</span>
                    <span class="action-time">${new Date(action.timestamp).toLocaleTimeString()}</span>
                </div>
                <div class="action-locators">
                    ${action.locators.slice(0, 3).map(loc => 
                        `<code class="locator-preview">${loc.locator}</code>`
                    ).join('')}
                    ${action.locators.length > 3 ? `<span class="more-locators">+${action.locators.length - 3} more</span>` : ''}
                </div>
            </div>
        `).join('');

        actionsList.innerHTML = `
            <div class="actions-header">
                <h3><i class="fas fa-list"></i> Recorded Actions (${this.recordedActions.length})</h3>
            </div>
            <div class="actions-list">${actionsHtml}</div>
        `;
    }

    startMCPInstructions() {
        // Show MCP command instructions
        this.updateStatus(`
            🚀 <strong>Ready to record!</strong><br><br>
            <strong>Use these MCP commands in Windsurf:</strong><br>
            <code>mcp0_playwright_navigate(url="${document.getElementById('targetUrl').value}")</code><br>
            <code>mcp0_start_codegen_session(options={"outputPath": "C:/path/to/tests", "includeComments": true})</code><br><br>
            Then interact with your page - each action will be enhanced with auto-healing locators!
        `, 'info');
    }

    showBrowserControls() {
        const controlsSection = document.querySelector('.recorder-controls');
        
        const browserControls = document.createElement('div');
        browserControls.className = 'browser-controls-section';
        browserControls.innerHTML = `
            <div class="control-section">
                <h3 class="control-label">
                    🎆 Browser Controls
                </h3>
                <div class="button-group">
                    <button id="launchBrowser" class="btn-primary">
                        <i class="fas fa-rocket"></i>
                        Launch Browser
                    </button>
                    <button id="recordAction" class="btn-secondary">
                        <i class="fas fa-plus"></i>
                        Record Manual Action
                    </button>
                </div>
            </div>
        `;
        
        controlsSection.appendChild(browserControls);
        
        // Re-bind event listeners for new buttons
        document.getElementById('launchBrowser').addEventListener('click', () => {
            this.launchBrowser();
        });
        
        document.getElementById('recordAction').addEventListener('click', () => {
            this.showActionRecorder();
        });
    }

    showRecordingControls() {
        const controlsSection = document.querySelector('.recorder-controls');
        
        const additionalControls = document.createElement('div');
        additionalControls.className = 'recording-controls-section';
        additionalControls.innerHTML = `
            <div class="control-section">
                <h3 class="control-label">
                    <i class="fas fa-tools"></i>
                    Recording Controls
                </h3>
                <div class="button-group">
                    <button id="stopRecording" class="btn-secondary">
                        <i class="fas fa-stop"></i>
                        Stop Recording
                    </button>
                    <button id="generateTest" class="btn-primary">
                        <i class="fas fa-magic"></i>
                        Generate Test Code
                    </button>
                    <button id="recordManualAction" class="btn-secondary">
                        <i class="fas fa-hand-pointer"></i>
                        Record Manual Action
                    </button>
                </div>
            </div>
        `;
        
        controlsSection.appendChild(additionalControls);
        
        // Re-bind event listeners for new buttons
        document.getElementById('stopRecording').addEventListener('click', () => {
            this.stopRecording();
        });
        
        document.getElementById('generateTest').addEventListener('click', () => {
            this.generateTestCode();
        });
        
        document.getElementById('recordManualAction').addEventListener('click', () => {
            this.showActionRecorder();
        });
    }

    showMCPCommands(commands) {
        let commandsSection = document.getElementById('mcpCommandsSection');
        if (!commandsSection) {
            commandsSection = document.createElement('div');
            commandsSection.id = 'mcpCommandsSection';
            commandsSection.className = 'mcp-commands-section';
            document.querySelector('.recorder-container').appendChild(commandsSection);
        }

        commandsSection.innerHTML = `
            <div class="commands-header">
                <h3><i class="fas fa-terminal"></i> MCP Playwright Commands</h3>
                <p>Copy and paste these commands in the Windsurf sidebar:</p>
            </div>
            <div class="commands-grid">
                <div class="command-card">
                    <h4>1. Navigate to URL</h4>
                    <div class="command-code">
                        <code>${commands.navigate}</code>
                        <button onclick="navigator.clipboard.writeText('${commands.navigate}')" class="copy-btn">
                            <i class="fas fa-copy"></i>
                        </button>
                    </div>
                </div>
                <div class="command-card">
                    <h4>2. Start Recording</h4>
                    <div class="command-code">
                        <code>${commands.start_codegen}</code>
                        <button onclick="navigator.clipboard.writeText('${commands.start_codegen}')" class="copy-btn">
                            <i class="fas fa-copy"></i>
                        </button>
                    </div>
                </div>
                <div class="command-card">
                    <h4>3. Take Screenshot</h4>
                    <div class="command-code">
                        <code>${commands.screenshot}</code>
                        <button onclick="navigator.clipboard.writeText('${commands.screenshot}')" class="copy-btn">
                            <i class="fas fa-copy"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    showActionRecorder() {
        const modal = document.createElement('div');
        modal.className = 'action-recorder-modal';
        modal.innerHTML = `
            <div class="modal-overlay">
                <div class="modal-content">
                    <div class="modal-header">
                        <h2><i class="fas fa-hand-pointer"></i> Record Manual Action</h2>
                        <button class="modal-close" onclick="this.closest('.action-recorder-modal').remove()">&times;</button>
                    </div>
                    
                    <div class="modal-body">
                        <div class="form-group">
                            <label>Action Type:</label>
                            <select id="actionType" class="form-control">
                                <option value="click">Click</option>
                                <option value="fill">Fill Input</option>
                                <option value="type">Type Text</option>
                                <option value="select">Select Option</option>
                            </select>
                        </div>
                        
                        <div class="form-group">
                            <label>Element ID:</label>
                            <input type="text" id="elementId" class="form-control" placeholder="button-submit">
                        </div>
                        
                        <div class="form-group">
                            <label>Element Text:</label>
                            <input type="text" id="elementText" class="form-control" placeholder="Submit">
                        </div>
                        
                        <div class="form-group">
                            <label>CSS Classes:</label>
                            <input type="text" id="elementClasses" class="form-control" placeholder="btn btn-primary">
                        </div>
                        
                        <div class="form-group" id="valueGroup" style="display: none;">
                            <label>Value:</label>
                            <input type="text" id="actionValue" class="form-control" placeholder="Text to type or select">
                        </div>
                    </div>
                    
                    <div class="modal-footer">
                        <button onclick="this.closest('.action-recorder-modal').remove()" class="btn-secondary">
                            Cancel
                        </button>
                        <button onclick="window.autoHealingRecorder.recordManualAction()" class="btn-primary">
                            <i class="fas fa-plus"></i> Record Action
                        </button>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        
        // Show/hide value field based on action type
        document.getElementById('actionType').addEventListener('change', (e) => {
            const valueGroup = document.getElementById('valueGroup');
            if (['fill', 'type', 'select'].includes(e.target.value)) {
                valueGroup.style.display = 'block';
            } else {
                valueGroup.style.display = 'none';
            }
        });
    }

    async recordManualAction() {
        const actionType = document.getElementById('actionType').value;
        const elementId = document.getElementById('elementId').value;
        const elementText = document.getElementById('elementText').value;
        const elementClasses = document.getElementById('elementClasses').value.split(' ').filter(c => c);
        const actionValue = document.getElementById('actionValue').value;
        
        const action = {
            type: actionType,
            element: {
                id: elementId,
                textContent: elementText,
                classList: elementClasses
            },
            value: actionValue
        };
        
        try {
            const response = await fetch('/api/auto-healing/record-action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ 
                    session_id: this.sessionId,
                    action: action 
                })
            });

            const data = await response.json();

            if (data.success) {
                this.recordedActions.push(data.action_recorded);
                this.updateActionsList();
                this.updateStatus(`✅ Action recorded! Total actions: ${data.total_actions}`, 'success');
                
                // Close modal
                document.querySelector('.action-recorder-modal').remove();
            } else {
                throw new Error(data.error || 'Failed to record action');
            }
        } catch (error) {
            console.error('Error recording action:', error);
            this.updateStatus(`❌ Error recording action: ${error.message}`, 'error');
        }
    }

    updateStatus(message, type = 'info') {
        const statusContent = document.getElementById('statusContent');
        const statusPanel = document.getElementById('statusPanel');
        
        statusContent.innerHTML = message;
        
        // Update panel styling based on status type
        statusPanel.className = 'status-panel';
        if (type === 'success') {
            statusPanel.style.borderLeft = '4px solid var(--success)';
        } else if (type === 'error') {
            statusPanel.style.borderLeft = '4px solid var(--error)';
        } else if (type === 'warning') {
            statusPanel.style.borderLeft = '4px solid var(--warning)';
        } else {
            statusPanel.style.borderLeft = '4px solid var(--primary)';
        }
    }

    showInstructions() {
        const modal = document.createElement('div');
        modal.className = 'instructions-modal';
        modal.innerHTML = `
            <div class="modal-overlay">
                <div class="modal-content">
                    <div class="modal-header">
                        <h2><i class="fas fa-info-circle"></i> Auto-Healing Test Recorder Guide</h2>
                        <button class="modal-close" onclick="this.closest('.instructions-modal').remove()">&times;</button>
                    </div>
                    
                    <div class="modal-body">
                        <div class="instruction-section">
                            <h3>🚀 Getting Started</h3>
                            <ol>
                                <li>Enter your target URL in the input field</li>
                                <li>Click "Start Playwright Codegen" to initialize a session</li>
                                <li>Use the MCP Playwright tools in the Windsurf sidebar</li>
                                <li>Navigate and interact with your application</li>
                                <li>Generate your auto-healing test code</li>
                            </ol>
                        </div>
                        
                        <div class="instruction-section">
                            <h3>🛡️ Auto-Healing Features</h3>
                            <ul>
                                <li><strong>Multiple Locators:</strong> Each element gets 6 different locator strategies</li>
                                <li><strong>Priority System:</strong> ID-based locators have highest priority</li>
                                <li><strong>Accessibility Focus:</strong> Role-based locators for better maintainability</li>
                                <li><strong>Fallback System:</strong> XPath as last resort when other strategies fail</li>
                                <li><strong>Smart Recovery:</strong> Automatically tries alternative locators</li>
                            </ul>
                        </div>
                        
                        <div class="instruction-section">
                            <h3>📋 MCP Commands</h3>
                            <div class="code-block">
# Navigate to your target URL
mcp0_playwright_navigate(url="https://your-site.com")

# Start code generation session
mcp0_start_codegen_session(options={
    "outputPath": "./tests",
    "testNamePrefix": "AutoHealing"
})

# Interact with elements
mcp0_playwright_click(selector="#button")
mcp0_playwright_fill(selector="#input", value="test")
mcp0_playwright_screenshot(name="test-result")
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
    }
    
    showSessionControls(sessionId) {
        const controlsHtml = `
            <div class="session-controls" style="margin-top: 20px; padding: 15px; background: var(--glass-bg); border-radius: 12px; border: 1px solid var(--glass-border);">
                <h4 style="color: var(--primary-color); margin-bottom: 15px;">🎛️ Session Management</h4>
                <div style="display: flex; gap: 10px; flex-wrap: wrap;">
                    <button id="check-status-btn" class="btn btn-secondary" onclick="autoHealingRecorder.checkSessionStatus('${sessionId}')">
                        📊 Check Status
                    </button>
                    <button id="close-browser-btn" class="btn btn-danger" onclick="autoHealingRecorder.closeBrowserSession('${sessionId}')">
                        ❌ Close Browser
                    </button>
                    <button id="refresh-session-btn" class="btn btn-secondary" onclick="autoHealingRecorder.refreshSession()">
                        🔄 Refresh
                    </button>
                    <button id="debug-session-btn" class="btn btn-info" onclick="autoHealingRecorder.debugSession('${sessionId}')">
                        🐛 Debug Session
                    </button>
                </div>
                <div id="session-status" style="margin-top: 15px; padding: 10px; background: rgba(255,255,255,0.1); border-radius: 8px; display: none;">
                    <div id="session-status-content"></div>
                </div>
            </div>
        `;
        
        const statusPanel = document.getElementById('status-panel');
        if (statusPanel) {
            statusPanel.insertAdjacentHTML('beforeend', controlsHtml);
        }
    }
    
    async checkSessionStatus(sessionId) {
        try {
            const response = await fetch(`/api/auto-healing/session-status?session_id=${sessionId}`);
            const data = await response.json();
            
            const statusDiv = document.getElementById('session-status');
            const statusContent = document.getElementById('session-status-content');
            
            if (data.success) {
                if (data.active) {
                    statusContent.innerHTML = `
                        <div style="color: #48bb78;">✅ Session Active</div>
                        <div><strong>URL:</strong> ${data.url}</div>
                        <div><strong>Created:</strong> ${new Date(data.created_at).toLocaleString()}</div>
                        <div><strong>Actions Recorded:</strong> ${data.actions_count}</div>
                    `;
                } else {
                    statusContent.innerHTML = `
                        <div style="color: #f56565;">❌ Session Inactive</div>
                        <div>Browser session may have been closed or expired.</div>
                    `;
                }
                statusDiv.style.display = 'block';
            } else {
                throw new Error(data.error || 'Failed to check session status');
            }
        } catch (error) {
            console.error('Error checking session status:', error);
            this.updateStatus(`❌ Error checking session status: ${error.message}`, 'error');
        }
    }
    
    async closeBrowserSession(sessionId) {
        try {
            const response = await fetch('/api/auto-healing/close-browser', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ session_id: sessionId })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.updateStatus('🎉 Browser session closed successfully!', 'success');
                
                // Update UI state
                const launchBtn = document.getElementById('launch-browser-btn');
                if (launchBtn) {
                    launchBtn.innerHTML = '🚀 Launch Browser';
                    launchBtn.style.background = '';
                }
                
                this.isRecording = false;
                
                // Hide session controls
                const sessionControls = document.querySelector('.session-controls');
                if (sessionControls) {
                    sessionControls.remove();
                }
                
            } else {
                throw new Error(data.error || 'Failed to close browser session');
            }
        } catch (error) {
            console.error('Error closing browser session:', error);
            this.updateStatus(`❌ Error closing browser session: ${error.message}`, 'error');
        }
    }
    
    refreshSession() {
        // Refresh the page to reset session state
        window.location.reload();
    }
    
    async debugSession(sessionId) {
        try {
            const response = await fetch(`/api/auto-healing/debug-session?session_id=${sessionId}`);
            const data = await response.json();
            
            if (data.success) {
                const debugInfo = data.debug_info;
                let debugHtml = `
                    <div style="background: rgba(0,0,0,0.8); color: white; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 12px; max-height: 400px; overflow-y: auto;">
                        <h4 style="color: #4CAF50; margin-bottom: 10px;">🐛 Debug Session: ${sessionId}</h4>
                        
                        <div style="margin-bottom: 15px;">
                            <strong style="color: #2196F3;">Browser Session:</strong><br>
                            ${debugInfo.browser_session ? `
                                URL: ${debugInfo.browser_session.url}<br>
                                Created: ${debugInfo.browser_session.created_at}<br>
                                Actions: ${debugInfo.browser_session.actions_count}<br>
                                <details style="margin-top: 5px;">
                                    <summary style="color: #FFC107; cursor: pointer;">View Actions</summary>
                                    <pre style="background: rgba(255,255,255,0.1); padding: 5px; margin: 5px 0; border-radius: 4px; font-size: 10px;">${JSON.stringify(debugInfo.browser_session.actions, null, 2)}</pre>
                                </details>
                            ` : 'None'}
                        </div>
                        
                        <div style="margin-bottom: 15px;">
                            <strong style="color: #2196F3;">Flask Session:</strong><br>
                            ${debugInfo.flask_session ? `
                                Status: ${debugInfo.flask_session.status}<br>
                                URL: ${debugInfo.flask_session.url}<br>
                                Browser URL: ${debugInfo.flask_session.browser_url}<br>
                                Actions: ${debugInfo.flask_session.actions_count}<br>
                                <details style="margin-top: 5px;">
                                    <summary style="color: #FFC107; cursor: pointer;">View Actions</summary>
                                    <pre style="background: rgba(255,255,255,0.1); padding: 5px; margin: 5px 0; border-radius: 4px; font-size: 10px;">${JSON.stringify(debugInfo.flask_session.actions, null, 2)}</pre>
                                </details>
                            ` : 'None'}
                        </div>
                        
                        <div>
                            <strong style="color: #2196F3;">All Browser Sessions:</strong><br>
                            Total: ${debugInfo.total_browser_sessions}<br>
                            IDs: ${debugInfo.all_browser_sessions.join(', ') || 'None'}
                        </div>
                    </div>
                `;
                
                // Create debug modal
                const modal = document.createElement('div');
                modal.className = 'debug-modal';
                modal.style.cssText = `
                    position: fixed; top: 0; left: 0; width: 100%; height: 100%; 
                    background: rgba(0,0,0,0.8); z-index: 10000; 
                    display: flex; align-items: center; justify-content: center;
                `;
                
                modal.innerHTML = `
                    <div style="background: white; padding: 20px; border-radius: 12px; max-width: 80%; max-height: 80%; overflow-y: auto;">
                        ${debugHtml}
                        <div style="text-align: center; margin-top: 15px;">
                            <button onclick="this.closest('.debug-modal').remove()" class="btn btn-primary">
                                Close Debug Info
                            </button>
                        </div>
                    </div>
                `;
                
                document.body.appendChild(modal);
                
            } else {
                throw new Error(data.error || 'Failed to get debug info');
            }
        } catch (error) {
            console.error('Error debugging session:', error);
            this.updateStatus(`❌ Error debugging session: ${error.message}`, 'error');
        }
    }
    
    isValidUrl(string) {
        try {
            new URL(string);
            return true;
        } catch (_) {
            return false;
        }
    }
    
    escapeHtml(text) {
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.replace(/[&<>"']/g, (m) => map[m]);
    }
    
    async recordTestAction() {
        if (!this.sessionId) {
            this.updateStatus('❌ Please start a session first', 'error');
            return;
        }
        
        // Create a sample test action
        const testAction = {
            type: 'click',
            element: {
                id: 'test-button',
                text: 'Test Button',
                classes: 'btn btn-primary',
                tagName: 'BUTTON',
                xpath: '//button[@id="test-button"]'
            },
            value: null,
            timestamp: new Date().toISOString()
        };
        
        try {
            const response = await fetch('/api/auto-healing/record-action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    action: testAction
                })
            });
            
            const data = await response.json();
            
            if (data.success) {
                this.updateStatus(`✅ Test action recorded! Total actions: ${data.total_actions}`, 'success');
                console.log('Recorded action:', data.action_recorded);
            } else {
                throw new Error(data.error || 'Failed to record action');
            }
        } catch (error) {
            console.error('Error recording test action:', error);
            this.updateStatus(`❌ Error recording action: ${error.message}`, 'error');
        }
    }
    
    async testBrowserLaunch() {
        const url = document.getElementById('targetUrl').value || 'https://example.com';
        
        try {
            this.updateStatus('🧪 Testing browser launch...', 'info');
            
            const response = await fetch('/api/auto-healing/test-browser', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ url: url })
            });
            
            const data = await response.json();
            
            console.log('Full response data:', data);
            
            if (data.success) {
                this.updateStatus(`✅ Browser test successful! Session: ${data.session_id}`, 'success');
                console.log('Test browser launch result:', data);
            } else {
                console.error('Browser test failed with data:', data);
                const errorMsg = data.error || 'Browser test failed';
                this.updateStatus(`❌ Browser test failed: ${errorMsg}`, 'error');
                throw new Error(errorMsg);
            }
        } catch (error) {
            console.error('Error testing browser launch:', error);
            this.updateStatus(`❌ Browser test failed: ${error.message}`, 'error');
        }
    }
    
    async checkPlaywrightStatus() {
        try {
            this.updateStatus('🔍 Checking Playwright status...', 'info');
            
            const response = await fetch('/api/auto-healing/check-playwright');
            const data = await response.json();
            
            console.log('Playwright status:', data);
            
            if (data.success) {
                this.updateStatus(`✅ Playwright is working! Browsers: ${Object.keys(data.browsers).join(', ')}`, 'success');
            } else {
                this.updateStatus(`❌ Playwright issue: ${data.error}`, 'error');
            }
        } catch (error) {
            console.error('Error checking Playwright:', error);
            this.updateStatus(`❌ Error checking Playwright: ${error.message}`, 'error');
        }
    }
}

// Initialize the recorder when the page loads
let autoHealingRecorder;
document.addEventListener('DOMContentLoaded', () => {
    autoHealingRecorder = new AutoHealingRecorder();
    window.autoHealingRecorder = autoHealingRecorder;
});

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = AutoHealingRecorder;
}
