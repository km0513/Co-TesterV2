/**
 * Cross-Tool Integration Utilities
 * Enables seamless data transfer between Codegen, AI Agent, and MCP
 */

class CrossToolIntegration {
    constructor() {
        this.sessionKey = 'crossToolContext';
        this.apiBase = '/api/integration';
    }

    /**
     * Export test from Codegen/Agent to MCP for refinement
     */
    async exportToMCP(testData) {
        try {
            const response = await fetch(`${this.apiBase}/export-to-mcp`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    source: testData.source || 'codegen',
                    code: testData.code,
                    actions: testData.actions || [],
                    url: testData.url || '',
                    metadata: testData.metadata || {}
                })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('✅ Exported to MCP successfully!', 'success');
                // Redirect to MCP with context
                setTimeout(() => {
                    window.location.href = result.redirect_url;
                }, 1000);
            } else {
                throw new Error(result.error);
            }

            return result;
        } catch (error) {
            console.error('Export to MCP error:', error);
            this.showNotification(`❌ Export failed: ${error.message}`, 'error');
            throw error;
        }
    }

    /**
     * Export AI Agent exploration to Codegen
     */
    async exportAgentExploration(explorationData) {
        try {
            const response = await fetch(`${this.apiBase}/export-agent-exploration`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    exploration_id: explorationData.id,
                    successful_paths: explorationData.paths || [],
                    selectors: explorationData.selectors || {},
                    interactions: explorationData.interactions || [],
                    screenshots: explorationData.screenshots || []
                })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification('✅ Exploration exported to Codegen!', 'success');
                setTimeout(() => {
                    window.location.href = result.redirect_url;
                }, 1000);
            } else {
                throw new Error(result.error);
            }

            return result;
        } catch (error) {
            console.error('Export exploration error:', error);
            this.showNotification(`❌ Export failed: ${error.message}`, 'error');
            throw error;
        }
    }

    /**
     * Import test data from another tool
     */
    async importFromSource(integrationId, targetTool) {
        try {
            const response = await fetch(`${this.apiBase}/import-from-source`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    integration_id: integrationId,
                    target_tool: targetTool
                })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`✅ Imported from ${result.data.original_source}`, 'success');
                return result.data;
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            console.error('Import error:', error);
            this.showNotification(`❌ Import failed: ${error.message}`, 'error');
            throw error;
        }
    }

    /**
     * Merge multiple tests into one
     */
    async mergeTests(sourceIds, strategy = 'sequential') {
        try {
            const response = await fetch(`${this.apiBase}/merge-tests`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sources: sourceIds,
                    strategy: strategy
                })
            });

            const result = await response.json();
            
            if (result.success) {
                this.showNotification(`✅ ${result.source_count} tests merged successfully!`, 'success');
                return result;
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            console.error('Merge error:', error);
            this.showNotification(`❌ Merge failed: ${error.message}`, 'error');
            throw error;
        }
    }

    /**
     * Get integration context by ID
     */
    async getContext(integrationId) {
        try {
            const response = await fetch(`${this.apiBase}/get-context?id=${integrationId}`);
            const result = await response.json();
            
            if (result.success) {
                return result.context;
            } else {
                throw new Error(result.error);
            }
        } catch (error) {
            console.error('Get context error:', error);
            return null;
        }
    }

    /**
     * Check if current page has import context from URL
     */
    checkForImportContext() {
        const urlParams = new URLSearchParams(window.location.search);
        const importId = urlParams.get('import');
        
        if (importId) {
            return importId;
        }
        
        return null;
    }

    /**
     * Auto-import if context exists in URL
     */
    async autoImport(targetTool) {
        const importId = this.checkForImportContext();
        
        if (importId) {
            try {
                const context = await this.getContext(importId);
                
                if (context) {
                    this.showNotification(`📥 Auto-importing from ${context.source}...`, 'info');
                    return context;
                }
            } catch (error) {
                console.error('Auto-import error:', error);
            }
        }
        
        return null;
    }

    /**
     * Show notification to user
     */
    showNotification(message, type = 'info') {
        // Check if notification container exists
        let container = document.getElementById('cross-tool-notifications');
        
        if (!container) {
            container = document.createElement('div');
            container.id = 'cross-tool-notifications';
            container.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 10000;
                display: flex;
                flex-direction: column;
                gap: 10px;
            `;
            document.body.appendChild(container);
        }

        const notification = document.createElement('div');
        notification.className = `cross-tool-notification ${type}`;
        notification.style.cssText = `
            background: ${type === 'success' ? '#10b981' : type === 'error' ? '#ef4444' : '#3b82f6'};
            color: white;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            font-weight: 500;
            animation: slideInRight 0.3s ease;
            max-width: 350px;
        `;
        notification.textContent = message;

        container.appendChild(notification);

        // Auto-remove after 4 seconds
        setTimeout(() => {
            notification.style.animation = 'slideOutRight 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 4000);
    }

    /**
     * Add export buttons to UI
     */
    addExportButtons(container, testData) {
        const exportSection = document.createElement('div');
        exportSection.className = 'cross-tool-export-section';
        exportSection.style.cssText = `
            margin-top: 1.5rem;
            padding: 1rem;
            background: linear-gradient(135deg, #f1f5f9 0%, #e2e8f0 100%);
            border-radius: 8px;
            border-left: 4px solid #64748b;
        `;

        exportSection.innerHTML = `
            <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem;">
                <i class="fas fa-network-wired" style="color: #64748b;"></i>
                <strong style="color: #1e293b;">Cross-Tool Integration</strong>
            </div>
            <div style="display: flex; gap: 0.75rem; flex-wrap: wrap;">
                <button class="export-to-mcp-btn" style="
                    padding: 0.5rem 1rem;
                    background: #3b82f6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 0.875rem;
                    font-weight: 500;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    transition: all 0.2s;
                ">
                    <i class="fas fa-comments"></i>
                    Refine in MCP
                </button>
                <button class="export-to-agent-btn" style="
                    padding: 0.5rem 1rem;
                    background: #8b5cf6;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    font-size: 0.875rem;
                    font-weight: 500;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    gap: 0.5rem;
                    transition: all 0.2s;
                ">
                    <i class="fas fa-robot"></i>
                    Execute with Agent
                </button>
            </div>
        `;

        // Add event listeners
        const mcpBtn = exportSection.querySelector('.export-to-mcp-btn');
        const agentBtn = exportSection.querySelector('.export-to-agent-btn');

        mcpBtn.addEventListener('click', () => this.exportToMCP(testData));
        mcpBtn.addEventListener('mouseenter', (e) => {
            e.target.style.background = '#2563eb';
            e.target.style.transform = 'translateY(-2px)';
        });
        mcpBtn.addEventListener('mouseleave', (e) => {
            e.target.style.background = '#3b82f6';
            e.target.style.transform = 'translateY(0)';
        });

        agentBtn.addEventListener('click', () => {
            this.showNotification('🚀 Agent execution coming soon!', 'info');
        });
        agentBtn.addEventListener('mouseenter', (e) => {
            e.target.style.background = '#7c3aed';
            e.target.style.transform = 'translateY(-2px)';
        });
        agentBtn.addEventListener('mouseleave', (e) => {
            e.target.style.background = '#8b5cf6';
            e.target.style.transform = 'translateY(0)';
        });

        container.appendChild(exportSection);
    }

    /**
     * Show import suggestions
     */
    showImportSuggestions(context) {
        const suggestionsHtml = `
            <div class="import-suggestions" style="
                margin: 1rem 0;
                padding: 1rem;
                background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
                border-radius: 8px;
                border-left: 4px solid #f59e0b;
            ">
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.75rem;">
                    <i class="fas fa-lightbulb" style="color: #d97706;"></i>
                    <strong style="color: #78350f;">AI Suggestions</strong>
                </div>
                <ul style="margin: 0; padding-left: 1.5rem; color: #92400e;">
                    ${(context.suggestions || []).map(s => `<li>${s}</li>`).join('')}
                </ul>
            </div>
        `;
        
        return suggestionsHtml;
    }
}

// Add animation styles
const style = document.createElement('style');
style.textContent = `
    @keyframes slideInRight {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOutRight {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);

// Create global instance
window.crossToolIntegration = new CrossToolIntegration();

console.log('✅ Cross-Tool Integration utilities loaded');
