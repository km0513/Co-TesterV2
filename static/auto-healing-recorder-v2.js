/**
 * Simplified Auto-Healing Test Recorder
 * Production-ready implementation with MCP Playwright integration
 */

class AutoHealingRecorderV2 {
    constructor() {
        this.sessionId = null;
        this.isRecording = false;
        this.recordedActions = [];
        this.init();
    }

    async importCodegen() {
        if (!this.sessionId) {
            this.showError('No active session. Start a session first.');
            return;
        }
        const ta = document.getElementById('codegenImportText');
        const status = document.getElementById('importCodegenStatus');
        const code = (ta && ta.value) || '';
        if (!code.trim()) {
            if (status) status.textContent = 'Paste codegen output above first.';
            return;
        }
        if (status) status.textContent = 'Parsing codegen and importing actions...';
        try {
            const res = await fetch('/api/recorder-v2/import-codegen', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.sessionId, code })
            });
            const data = await res.json();
            if (data.success) {
                // Refresh actions list from server status to get canonical locators
                await this.refreshActionsFromServer();
                if (status) status.textContent = `Imported ${data.imported_count} actions from codegen.`;
                this.showStatus(`✅ Imported ${data.imported_count} actions from codegen`, 'success');
            } else {
                if (status) status.textContent = `Failed: ${data.error}`;
                this.showError(`Import failed: ${data.error}`);
            }
        } catch (e) {
            if (status) status.textContent = `Error: ${e.message}`;
            this.showError(`Error importing codegen: ${e.message}`);
        }
    }

    async refreshActionsFromServer() {
        try {
            const res = await fetch('/api/recorder-v2/session-status');
            const data = await res.json();
            if (data.success && data.session_active) {
                // We only get last 5; but we care to update locators. Merge conservatively.
                const last = data.actions || [];
                if (last.length) {
                    // naive merge: if counts differ, just replace client cache
                    this.recordedActions = (data.actions_count === this.recordedActions.length)
                        ? this.recordedActions.map((a, i) => last[i] || a)
                        : last; 
                }
                this.updateActionsDisplay();
            }
        } catch (e) {
            console.warn('Failed refreshing actions:', e);
        }
    }

    async enrichLocators() {
        if (!this.sessionId) {
            this.showError('No active session. Start a session first.');
            return;
        }
        const status = document.getElementById('enrichLocatorsStatus');
        if (status) status.textContent = 'Enriching locators from live page...';
        try {
            const payload = { session_id: this.sessionId };
            const res = await fetch('/api/recorder-v2/enrich-locators', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (data.success) {
                await this.refreshActionsFromServer();
                if (status) status.textContent = `Enriched ${data.enriched_count} actions.`;
                this.showStatus(`✅ Enriched ${data.enriched_count} actions`, 'success');
            } else {
                if (status) status.textContent = `Failed: ${data.error}`;
                this.showError(`Enrichment failed: ${data.error}`);
            }
        } catch (e) {
            if (status) status.textContent = `Error: ${e.message}`;
            this.showError(`Error enriching locators: ${e.message}`);
        }
    }
    displayCodegenOutput(code, path) {
        const container = document.getElementById('codegenOutputDisplay');
        if (!container) return;
        const safe = this.escapeHtml(code || '');
        const pathInfo = path ? `<div class="small text-muted">Saved to: ${this.escapeHtml(path)}</div>` : '';
        container.innerHTML = `
            <div class="test-code-container">
                <div class="test-code-header">
                    <h4>🎥 Playwright Codegen Output</h4>
                    <button onclick="navigator.clipboard.writeText(\`${(code || '').replace(/`/g, '\\`')}\`)" class="copy-btn">📋 Copy</button>
                </div>
                ${pathInfo}
                <pre><code class="language-javascript">${safe}</code></pre>
            </div>
        `;
    }

    async launchCodegen() {
        try {
            if (!this.sessionId) {
                this.showError('No active session. Start a session first.');
                return;
            }
            const urlInput = document.getElementById('targetUrl');
            const url = urlInput ? urlInput.value : undefined;
            this.showStatus('⚡ Launching Playwright codegen...', 'info');
            const res = await fetch('/api/recorder-v2/launch-codegen', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.sessionId, url })
            });
            const data = await res.json();
            if (data.success) {
                this.showStatus(`✅ Codegen launched (pid ${data.pid})`, 'success');
                this.updateUI({ codegenActive: true });
            } else {
                this.showError(`Failed to launch codegen: ${data.error}`);
            }
        } catch (e) {
            console.error(e);
            this.showError(`Error launching codegen: ${e.message}`);
        }
    }

    async stopCodegen() {
        try {
            if (!this.sessionId) {
                this.showError('No active session. Start a session first.');
                return;
            }
            this.showStatus('⏹️ Stopping codegen...', 'info');
            const res = await fetch('/api/recorder-v2/stop-codegen', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.sessionId })
            });
            const data = await res.json();
            if (data.success) {
                this.showStatus('✅ Codegen stopped', 'success');
                this.updateUI({ codegenActive: false });
                if (data.codegen_code) {
                    this.displayCodegenOutput(data.codegen_code, data.output_path);
                } else if (data.output_path) {
                    this.displayCodegenOutput('// No code captured. If your Playwright version does not support --output, use the Copy button in the codegen window and paste here.', data.output_path);
                }
            } else {
                this.showError(`Failed to stop codegen: ${data.error}`);
            }
        } catch (e) {
            console.error(e);
            this.showError(`Error stopping codegen: ${e.message}`);
        }
    }

    init() {
        console.log('🚀 Auto-Healing Recorder V2 initialized');
        this.setupEventListeners();
        this.updateUI();
    }

    setupEventListeners() {
        // Start session button
        const startBtn = document.getElementById('startSession');
        if (startBtn) {
            startBtn.addEventListener('click', () => this.startSession());
        }

        // Record action button
        const recordBtn = document.getElementById('recordAction');
        if (recordBtn) {
            recordBtn.addEventListener('click', () => this.recordSampleAction());
        }

        // Generate test button
        const generateBtn = document.getElementById('generateTest');
        if (generateBtn) {
            generateBtn.addEventListener('click', () => this.generateTest());
        }

        // Close session button
        const closeBtn = document.getElementById('closeSession');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.closeSession());
        }

        // MCP commands button
        const mcpBtn = document.getElementById('showMcpCommands');
        if (mcpBtn) {
            mcpBtn.addEventListener('click', () => this.showMcpCommands());
        }

        // Launch codegen
        const launchBtn = document.getElementById('launchCodegen');
        if (launchBtn) {
            launchBtn.addEventListener('click', () => this.launchCodegen());
        }

        // Stop codegen
        const stopBtn = document.getElementById('stopCodegen');
        if (stopBtn) {
            stopBtn.addEventListener('click', () => this.stopCodegen());
        }

        // Import codegen
        const importBtn = document.getElementById('importCodegenBtn');
        if (importBtn) {
            importBtn.addEventListener('click', () => this.importCodegen());
        }

        // Enrich locators
        const enrichBtn = document.getElementById('enrichLocatorsBtn');
        if (enrichBtn) enrichBtn.addEventListener('click', () => this.enrichLocators());
    }

    async startSession() {
        try {
            const urlInput = document.getElementById('targetUrl');
            const url = urlInput ? urlInput.value : '';

            if (!url || !this.isValidUrl(url)) {
                this.showError('Please enter a valid URL');
                return;
            }

            this.showStatus('🚀 Starting recording session...', 'info');

            const response = await fetch('/api/recorder-v2/start-session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url })
            });

            const data = await response.json();

            if (data.success) {
                this.sessionId = data.session_id;
                this.isRecording = true;
                this.recordedActions = [];
                
                this.showStatus(`✅ Session started! ID: ${this.sessionId}`, 'success');
                this.updateUI();
                this.displayMcpCommands(data.mcp_commands);
                
                // Show instructions
                this.showInstructions([
                    '1. Use the MCP commands below to control the browser',
                    '2. Navigate to your target URL and interact with elements',
                    '3. Use "Record Action" to manually log interactions',
                    '4. Generate test code when done'
                ]);
                
            } else {
                this.showError(`Failed to start session: ${data.error}`);
            }

        } catch (error) {
            console.error('Error starting session:', error);
            this.showError(`Error starting session: ${error.message}`);
        }
    }

    async recordSampleAction() {
        if (!this.sessionId) {
            this.showError('No active session. Start a session first.');
            return;
        }

        try {
            this.showStatus('📝 Recording sample action...', 'info');

            // Sample element data with multiple locator strategies
            const sampleElementData = {
                id: 'submit-button',
                'data-testid': 'submit-btn',
                name: 'submit',
                class: 'btn btn-primary',
                text: 'Submit',
                role: 'button',
                css_selector: '.btn.btn-primary',
                xpath: '//button[@id="submit-button"]'
            };

            const response = await fetch('/api/recorder-v2/record-action', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    action_type: 'click',
                    element_data: sampleElementData,
                    additional_data: { timestamp: new Date().toISOString() }
                })
            });

            const data = await response.json();

            if (data.success) {
                this.recordedActions.push(data.action);
                this.showStatus(`✅ Action recorded! ${data.locators_generated} locators generated`, 'success');
                this.updateActionsDisplay();
            } else {
                this.showError(`Failed to record action: ${data.error}`);
            }

        } catch (error) {
            console.error('Error recording action:', error);
            this.showError(`Error recording action: ${error.message}`);
        }
    }

    async generateTest() {
        if (!this.sessionId) {
            this.showError('No active session. Start a session first.');
            return;
        }

        try {
            this.showStatus('🔧 Generating test code...', 'info');

            const response = await fetch('/api/recorder-v2/generate-test', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId
                })
            });

            const data = await response.json();

            if (data.success) {
                this.showStatus('✅ Test code generated successfully!', 'success');
                this.displayTestCode(data.test_code);
            } else {
                this.showError(`Failed to generate test: ${data.error}`);
            }

        } catch (error) {
            console.error('Error generating test:', error);
            this.showError(`Error generating test: ${error.message}`);
        }
    }

    async closeSession() {
        if (!this.sessionId) {
            this.showError('No active session to close.');
            return;
        }

        try {
            this.showStatus('🔒 Closing session...', 'info');

            const response = await fetch('/api/recorder-v2/close-session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId
                })
            });

            const data = await response.json();

            if (data.success) {
                this.sessionId = null;
                this.isRecording = false;
                this.recordedActions = [];
                this.showStatus('✅ Session closed successfully', 'success');
                this.updateUI();
                this.clearDisplays();
            } else {
                this.showError(`Failed to close session: ${data.error}`);
            }

        } catch (error) {
            console.error('Error closing session:', error);
            this.showError(`Error closing session: ${error.message}`);
        }
    }

    showMcpCommands() {
        const commands = {
            'Navigate to URL': 'mcp0_playwright_navigate --url "https://example.com" --headless false',
            'Start Code Generation': 'mcp0_start_codegen_session --outputPath "./tests" --testNamePrefix "AutoHealing"',
            'Take Screenshot': 'mcp0_playwright_screenshot --name "test-screenshot"',
            'Click Element': 'mcp0_playwright_click --selector "#button-id"',
            'Fill Input': 'mcp0_playwright_fill --selector "input[name=\\"username\\"]" --value "testuser"',
            'Get Page Content': 'mcp0_playwright_get_visible_text',
            'End Code Generation': 'mcp0_end_codegen_session --sessionId "your-session-id"'
        };

        this.displayMcpCommands(commands);
    }

    displayMcpCommands(commands) {
        const container = document.getElementById('mcpCommandsDisplay');
        if (!container) return;

        let html = '<div class="mcp-commands"><h4>🎭 MCP Playwright Commands</h4>';
        
        for (const [name, command] of Object.entries(commands)) {
            html += `
                <div class="command-item">
                    <div class="command-name">${name}</div>
                    <div class="command-code">
                        <code>${command}</code>
                        <button onclick="navigator.clipboard.writeText('${command}')" class="copy-btn">📋</button>
                    </div>
                </div>
            `;
        }
        
        html += '</div>';
        container.innerHTML = html;
    }

    displayTestCode(testCode) {
        const container = document.getElementById('testCodeDisplay');
        if (!container) return;

        container.innerHTML = `
            <div class="test-code-container">
                <div class="test-code-header">
                    <h4>🧪 Generated Auto-Healing Test Code</h4>
                    <button onclick="navigator.clipboard.writeText(\`${testCode.replace(/`/g, '\\`')}\`)" class="copy-btn">📋 Copy</button>
                </div>
                <pre><code class="language-javascript">${this.escapeHtml(testCode)}</code></pre>
            </div>
        `;
    }

    updateActionsDisplay() {
        const container = document.getElementById('actionsDisplay');
        if (!container) return;

        if (this.recordedActions.length === 0) {
            container.innerHTML = '<p class="no-actions">No actions recorded yet</p>';
            return;
        }

        let html = '<div class="recorded-actions"><h4>📝 Recorded Actions</h4>';
        
        this.recordedActions.forEach((action, index) => {
            html += `
                <div class="action-item">
                    <div class="action-header">
                        <span class="action-number">${index + 1}</span>
                        <span class="action-type">${action.type}</span>
                        <span class="action-time">${new Date(action.timestamp).toLocaleTimeString()}</span>
                    </div>
                    <div class="action-locators">
                        <strong>Auto-healing locators (${action.locators.length}):</strong>
                        ${action.locators.map(loc => `
                            <div class="locator-item priority-${loc.priority}">
                                <span class="locator-type">${loc.type}</span>: 
                                <code>${loc.value}</code>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        });
        
        html += '</div>';
        container.innerHTML = html;
    }

    showInstructions(instructions) {
        const container = document.getElementById('instructionsDisplay');
        if (!container) return;

        const html = `
            <div class="instructions">
                <h4>📋 Instructions</h4>
                <ul>
                    ${instructions.map(instruction => `<li>${instruction}</li>`).join('')}
                </ul>
            </div>
        `;
        container.innerHTML = html;
    }

    updateUI(state = {}) {
        // Update button states
        const startBtn = document.getElementById('startSession');
        const recordBtn = document.getElementById('recordAction');
        const generateBtn = document.getElementById('generateTest');
        const closeBtn = document.getElementById('closeSession');
        const launchBtn = document.getElementById('launchCodegen');
        const stopBtn = document.getElementById('stopCodegen');

        const codegenActive = !!state.codegenActive;

        if (startBtn) startBtn.disabled = this.isRecording;
        if (recordBtn) recordBtn.disabled = !this.isRecording;
        if (generateBtn) generateBtn.disabled = !this.isRecording;
        if (closeBtn) closeBtn.disabled = !this.isRecording;
        if (launchBtn) launchBtn.disabled = !this.isRecording || codegenActive;
        if (stopBtn) stopBtn.disabled = !this.isRecording || !codegenActive;

        // Update session info
        const sessionInfo = document.getElementById('sessionInfo');
        if (sessionInfo) {
            if (this.isRecording) {
                sessionInfo.innerHTML = `
                    <div class="session-active">
                        <span class="status-indicator">🟢</span>
                        <span>Session Active: ${this.sessionId}</span>
                        <span class="actions-count">${this.recordedActions.length} actions recorded</span>
                    </div>
                `;
            } else {
                sessionInfo.innerHTML = `
                    <div class="session-inactive">
                        <span class="status-indicator">🔴</span>
                        <span>No active session</span>
                    </div>
                `;
            }
        }
    }

    clearDisplays() {
        const displays = ['mcpCommandsDisplay', 'testCodeDisplay', 'actionsDisplay', 'instructionsDisplay'];
        displays.forEach(id => {
            const element = document.getElementById(id);
            if (element) element.innerHTML = '';
        });
    }

    showStatus(message, type = 'info') {
        const statusElement = document.getElementById('statusMessage');
        if (!statusElement) return;

        const icons = {
            info: 'ℹ️',
            success: '✅',
            error: '❌',
            warning: '⚠️'
        };

        statusElement.className = `status-message ${type}`;
        statusElement.innerHTML = `${icons[type]} ${message}`;
        
        // Auto-hide after 5 seconds for non-error messages
        if (type !== 'error') {
            setTimeout(() => {
                statusElement.innerHTML = '';
                statusElement.className = 'status-message';
            }, 5000);
        }
    }

    showError(message) {
        this.showStatus(message, 'error');
        console.error('Auto-Healing Recorder Error:', message);
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
        return text.replace(/[&<>"']/g, m => map[m]);
    }

}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.autoHealingRecorder = new AutoHealingRecorderV2();
});
