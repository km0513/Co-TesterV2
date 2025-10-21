/**
 * API Co-Test V2 - Modern API Testing Interface
 * Workspace, Environment, and Variable Management
 */

// Global state
const state = {
    currentWorkspace: null,
    currentEnvironment: null,
    workspaces: [],
    environments: [],
    variables: [],
    globalVariables: [],
    history: [],
    favorites: []
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', async () => {
    console.log('🚀 Initializing API Co-Test V2...');
    await loadWorkspaces();
    await loadHistory();
    await loadFavorites();
    setupEventListeners();
    console.log('✅ API Co-Test V2 initialized');
});

// ============================================================================
// WORKSPACE MANAGEMENT
// ============================================================================

async function loadWorkspaces() {
    try {
        const response = await fetch('/api/v1/workspaces');
        const data = await response.json();
        
        if (data.success) {
            state.workspaces = data.workspaces;
            
            // Set first workspace as current if none selected
            if (!state.currentWorkspace && state.workspaces.length > 0) {
                state.currentWorkspace = state.workspaces[0];
                await loadEnvironments(state.currentWorkspace.id);
            }
            
            renderWorkspaceSelector();
            renderWorkspaceList();
        }
    } catch (error) {
        console.error('Error loading workspaces:', error);
        showNotification('Failed to load workspaces', 'error');
    }
}

async function createWorkspace(name, description) {
    try {
        const response = await fetch('/api/v1/workspaces', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, description })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Workspace created successfully', 'success');
            await loadWorkspaces();
            return data.workspace;
        } else {
            throw new Error(data.error);
        }
    } catch (error) {
        console.error('Error creating workspace:', error);
        showNotification('Failed to create workspace', 'error');
    }
}

async function deleteWorkspace(workspaceId) {
    if (!confirm('Are you sure you want to delete this workspace? All data will be lost.')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/v1/workspaces/${workspaceId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Workspace deleted', 'success');
            await loadWorkspaces();
        }
    } catch (error) {
        console.error('Error deleting workspace:', error);
        showNotification('Failed to delete workspace', 'error');
    }
}

function renderWorkspaceSelector() {
    const selector = document.getElementById('workspace-selector');
    if (!selector) return;
    
    selector.innerHTML = `
        <div class="workspace-dropdown">
            <button class="workspace-btn" onclick="toggleWorkspaceMenu()">
                <i class="fas fa-briefcase"></i>
                <span>${state.currentWorkspace?.name || 'Select Workspace'}</span>
                <i class="fas fa-chevron-down"></i>
            </button>
            <div class="workspace-menu" id="workspace-menu" style="display: none;">
                ${state.workspaces.map(ws => `
                    <div class="workspace-item ${ws.id === state.currentWorkspace?.id ? 'active' : ''}"
                         onclick="selectWorkspace(${ws.id})">
                        <i class="fas fa-briefcase"></i>
                        <span>${ws.name}</span>
                        ${ws.id === state.currentWorkspace?.id ? '<i class="fas fa-check"></i>' : ''}
                    </div>
                `).join('')}
                <div class="workspace-divider"></div>
                <div class="workspace-item" onclick="showCreateWorkspaceModal()">
                    <i class="fas fa-plus"></i>
                    <span>Create Workspace</span>
                </div>
            </div>
        </div>
    `;
}

function toggleWorkspaceMenu() {
    const menu = document.getElementById('workspace-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

async function selectWorkspace(workspaceId) {
    const workspace = state.workspaces.find(w => w.id === workspaceId);
    if (workspace) {
        state.currentWorkspace = workspace;
        await loadEnvironments(workspaceId);
        await loadGlobalVariables(workspaceId);
        await loadHistory();
        renderWorkspaceSelector();
        toggleWorkspaceMenu();
    }
}

// ============================================================================
// ENVIRONMENT MANAGEMENT
// ============================================================================

async function loadEnvironments(workspaceId) {
    try {
        const response = await fetch(`/api/v1/workspaces/${workspaceId}/environments`);
        const data = await response.json();
        
        if (data.success) {
            state.environments = data.environments;
            
            // Set active environment as current
            const activeEnv = state.environments.find(e => e.is_active);
            if (activeEnv) {
                state.currentEnvironment = activeEnv;
                state.variables = activeEnv.variables || [];
            } else if (state.environments.length > 0) {
                state.currentEnvironment = state.environments[0];
                state.variables = state.currentEnvironment.variables || [];
            }
            
            renderEnvironmentSelector();
            renderVariableEditor();
        }
    } catch (error) {
        console.error('Error loading environments:', error);
        showNotification('Failed to load environments', 'error');
    }
}

async function createEnvironment(name) {
    if (!state.currentWorkspace) {
        showNotification('Please select a workspace first', 'warning');
        return;
    }
    
    try {
        const response = await fetch(`/api/v1/workspaces/${state.currentWorkspace.id}/environments`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, is_active: false })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Environment created', 'success');
            await loadEnvironments(state.currentWorkspace.id);
        }
    } catch (error) {
        console.error('Error creating environment:', error);
        showNotification('Failed to create environment', 'error');
    }
}

async function setActiveEnvironment(environmentId) {
    try {
        const response = await fetch(`/api/v1/environments/${environmentId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: true })
        });
        
        const data = await response.json();
        
        if (data.success) {
            await loadEnvironments(state.currentWorkspace.id);
            showNotification(`Switched to ${data.environment.name}`, 'success');
        }
    } catch (error) {
        console.error('Error setting active environment:', error);
        showNotification('Failed to switch environment', 'error');
    }
}

async function deleteEnvironment(environmentId) {
    if (!confirm('Delete this environment and all its variables?')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/v1/environments/${environmentId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Environment deleted', 'success');
            await loadEnvironments(state.currentWorkspace.id);
        }
    } catch (error) {
        console.error('Error deleting environment:', error);
        showNotification('Failed to delete environment', 'error');
    }
}

function renderEnvironmentSelector() {
    const selector = document.getElementById('environment-selector');
    if (!selector) return;
    
    selector.innerHTML = `
        <div class="environment-dropdown">
            <button class="environment-btn" onclick="toggleEnvironmentMenu()">
                <i class="fas fa-globe"></i>
                <span>${state.currentEnvironment?.name || 'No Environment'}</span>
                <i class="fas fa-chevron-down"></i>
            </button>
            <div class="environment-menu" id="environment-menu" style="display: none;">
                ${state.environments.map(env => `
                    <div class="environment-item ${env.id === state.currentEnvironment?.id ? 'active' : ''}"
                         onclick="setActiveEnvironment(${env.id})">
                        <i class="fas ${env.is_active ? 'fa-check-circle' : 'fa-circle'}"></i>
                        <span>${env.name}</span>
                        <button class="delete-btn" onclick="event.stopPropagation(); deleteEnvironment(${env.id})">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                `).join('')}
                <div class="environment-divider"></div>
                <div class="environment-item" onclick="showCreateEnvironmentModal()">
                    <i class="fas fa-plus"></i>
                    <span>Create Environment</span>
                </div>
                <div class="environment-item" onclick="showManageVariablesModal()">
                    <i class="fas fa-cog"></i>
                    <span>Manage Variables</span>
                </div>
            </div>
        </div>
    `;
}

function toggleEnvironmentMenu() {
    const menu = document.getElementById('environment-menu');
    menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}

// ============================================================================
// VARIABLE MANAGEMENT
// ============================================================================

async function loadGlobalVariables(workspaceId) {
    try {
        const response = await fetch(`/api/v1/workspaces/${workspaceId}/global-variables`);
        const data = await response.json();
        
        if (data.success) {
            state.globalVariables = data.variables;
        }
    } catch (error) {
        console.error('Error loading global variables:', error);
    }
}

async function saveVariable(environmentId, variable) {
    try {
        const response = await fetch(`/api/v1/environments/${environmentId}/variables`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(variable)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Variable saved', 'success');
            await loadEnvironments(state.currentWorkspace.id);
            return data.variable;
        }
    } catch (error) {
        console.error('Error saving variable:', error);
        showNotification('Failed to save variable', 'error');
    }
}

async function bulkUpdateVariables(environmentId, variables) {
    try {
        const response = await fetch(`/api/v1/environments/${environmentId}/variables/bulk`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ variables })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Variables updated', 'success');
            await loadEnvironments(state.currentWorkspace.id);
        }
    } catch (error) {
        console.error('Error updating variables:', error);
        showNotification('Failed to update variables', 'error');
    }
}

function renderVariableEditor() {
    const editor = document.getElementById('variable-editor');
    if (!editor) return;
    
    const variables = state.variables || [];
    
    editor.innerHTML = `
        <div class="variable-editor-header">
            <h3>Environment Variables</h3>
            <button class="btn-primary" onclick="addVariableRow()">
                <i class="fas fa-plus"></i> Add Variable
            </button>
        </div>
        <div class="variable-table">
            <div class="variable-table-header">
                <div>Key</div>
                <div>Value</div>
                <div>Secret</div>
                <div>Actions</div>
            </div>
            <div id="variable-rows">
                ${variables.map((v, i) => renderVariableRow(v, i)).join('')}
            </div>
        </div>
        <div class="variable-editor-footer">
            <button class="btn-secondary" onclick="cancelVariableEdit()">Cancel</button>
            <button class="btn-primary" onclick="saveAllVariables()">Save All</button>
        </div>
    `;
}

function renderVariableRow(variable, index) {
    return `
        <div class="variable-row" data-index="${index}">
            <input type="text" class="var-key" value="${variable.key || ''}" placeholder="KEY">
            <input type="${variable.is_secret ? 'password' : 'text'}" class="var-value" 
                   value="${variable.value || ''}" placeholder="value">
            <input type="checkbox" class="var-secret" ${variable.is_secret ? 'checked' : ''}>
            <button class="btn-icon" onclick="removeVariableRow(${index})">
                <i class="fas fa-trash"></i>
            </button>
        </div>
    `;
}

function addVariableRow() {
    state.variables.push({ key: '', value: '', is_secret: false });
    renderVariableEditor();
}

function removeVariableRow(index) {
    state.variables.splice(index, 1);
    renderVariableEditor();
}

async function saveAllVariables() {
    if (!state.currentEnvironment) {
        showNotification('No environment selected', 'warning');
        return;
    }
    
    // Collect variables from UI
    const rows = document.querySelectorAll('.variable-row');
    const variables = Array.from(rows).map(row => ({
        key: row.querySelector('.var-key').value,
        value: row.querySelector('.var-value').value,
        is_secret: row.querySelector('.var-secret').checked
    })).filter(v => v.key); // Only include rows with keys
    
    await bulkUpdateVariables(state.currentEnvironment.id, variables);
}

function cancelVariableEdit() {
    loadEnvironments(state.currentWorkspace.id);
}

// ============================================================================
// REQUEST HISTORY
// ============================================================================

async function loadHistory() {
    if (!state.currentWorkspace) return;
    
    try {
        const response = await fetch(`/api/v1/workspaces/${state.currentWorkspace.id}/history?limit=50`);
        const data = await response.json();
        
        if (data.success) {
            state.history = data.history;
            renderHistory();
        }
    } catch (error) {
        console.error('Error loading history:', error);
    }
}

function renderHistory() {
    const historyPanel = document.getElementById('history-panel');
    if (!historyPanel) return;
    
    if (state.history.length === 0) {
        historyPanel.innerHTML = '<div class="empty-state">No request history yet</div>';
        return;
    }
    
    historyPanel.innerHTML = state.history.map(item => `
        <div class="history-item" onclick="loadHistoryItem(${item.id})">
            <div class="history-method method-${item.method.toLowerCase()}">${item.method}</div>
            <div class="history-url">${item.url}</div>
            <div class="history-status status-${Math.floor(item.response_status / 100)}xx">
                ${item.response_status || '-'}
            </div>
            <div class="history-time">${item.response_time || '-'}ms</div>
            <div class="history-date">${formatDate(item.executed_at)}</div>
        </div>
    `).join('');
}

function loadHistoryItem(historyId) {
    const item = state.history.find(h => h.id === historyId);
    if (item) {
        // Populate request builder with history item
        document.getElementById('request-method').value = item.method;
        document.getElementById('request-url').value = item.url;
        // TODO: Load headers and body
        showNotification('Request loaded from history', 'info');
    }
}

// ============================================================================
// FAVORITES
// ============================================================================

async function loadFavorites() {
    try {
        const response = await fetch('/api/v1/favorites');
        const data = await response.json();
        
        if (data.success) {
            state.favorites = data.favorites;
            renderFavorites();
        }
    } catch (error) {
        console.error('Error loading favorites:', error);
    }
}

async function addToFavorites(request) {
    try {
        const response = await fetch('/api/v1/favorites', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(request)
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Added to favorites', 'success');
            await loadFavorites();
        }
    } catch (error) {
        console.error('Error adding to favorites:', error);
        showNotification('Failed to add to favorites', 'error');
    }
}

async function removeFromFavorites(favoriteId) {
    try {
        const response = await fetch(`/api/v1/favorites/${favoriteId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showNotification('Removed from favorites', 'success');
            await loadFavorites();
        }
    } catch (error) {
        console.error('Error removing from favorites:', error);
    }
}

function renderFavorites() {
    const favoritesPanel = document.getElementById('favorites-panel');
    if (!favoritesPanel) return;
    
    if (state.favorites.length === 0) {
        favoritesPanel.innerHTML = '<div class="empty-state">No favorites yet</div>';
        return;
    }
    
    favoritesPanel.innerHTML = state.favorites.map(fav => `
        <div class="favorite-item" onclick="loadFavorite(${fav.id})">
            <div class="favorite-method method-${fav.method.toLowerCase()}">${fav.method}</div>
            <div class="favorite-name">${fav.name || fav.url}</div>
            <button class="btn-icon" onclick="event.stopPropagation(); removeFromFavorites(${fav.id})">
                <i class="fas fa-star"></i>
            </button>
        </div>
    `).join('');
}

function loadFavorite(favoriteId) {
    const fav = state.favorites.find(f => f.id === favoriteId);
    if (fav) {
        document.getElementById('request-method').value = fav.method;
        document.getElementById('request-url').value = fav.url;
        // TODO: Load headers and body
        showNotification('Request loaded from favorites', 'info');
    }
}

// ============================================================================
// MODALS
// ============================================================================

function showCreateWorkspaceModal() {
    toggleWorkspaceMenu();
    const modal = document.getElementById('create-workspace-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function showCreateEnvironmentModal() {
    toggleEnvironmentMenu();
    const modal = document.getElementById('create-environment-modal');
    if (modal) {
        modal.style.display = 'flex';
    }
}

function showManageVariablesModal() {
    toggleEnvironmentMenu();
    const modal = document.getElementById('manage-variables-modal');
    if (modal) {
        renderVariableEditor();
        modal.style.display = 'flex';
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
    }
}

// ============================================================================
// UTILITIES
// ============================================================================

function showNotification(message, type = 'info') {
    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
        <span>${message}</span>
    `;
    
    document.body.appendChild(notification);
    
    setTimeout(() => {
        notification.classList.add('show');
    }, 10);
    
    setTimeout(() => {
        notification.classList.remove('show');
        setTimeout(() => notification.remove(), 300);
    }, 3000);
}

function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return date.toLocaleDateString();
}

function setupEventListeners() {
    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.workspace-dropdown')) {
            const menu = document.getElementById('workspace-menu');
            if (menu) menu.style.display = 'none';
        }
        if (!e.target.closest('.environment-dropdown')) {
            const menu = document.getElementById('environment-menu');
            if (menu) menu.style.display = 'none';
        }
    });
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + E - Switch environment
        if ((e.ctrlKey || e.metaKey) && e.key === 'e') {
            e.preventDefault();
            toggleEnvironmentMenu();
        }
        
        // Ctrl/Cmd + K - Quick search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            // TODO: Implement quick search
        }
    });
}

// Export functions for global access
window.apiCoTest = {
    loadWorkspaces,
    createWorkspace,
    deleteWorkspace,
    selectWorkspace,
    loadEnvironments,
    createEnvironment,
    setActiveEnvironment,
    deleteEnvironment,
    saveVariable,
    bulkUpdateVariables,
    addToFavorites,
    removeFromFavorites,
    showNotification
};
