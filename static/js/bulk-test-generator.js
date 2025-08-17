// Bulk Test Generator JavaScript
class BulkTestGenerator {
    constructor() {
        this.currentStep = 1;
        this.sessionId = null;
        this.stories = [];
        this.currentPage = 1;
        this.itemsPerPage = 10;
        this.allSelectedStories = new Set();
        this.generationProgress = {
            total: 0,
            processed: 0,
            failed: 0
        };
        
        this.initializeEventListeners();
    }
    
    initializeEventListeners() {
        // Step 1: JQL Query
        document.getElementById('validateJqlBtn')?.addEventListener('click', () => this.validateJQL());
        document.getElementById('fetchStoriesBtn')?.addEventListener('click', () => this.fetchStories());
        
        // Step 2: Story Selection
        document.getElementById('backToJqlBtn')?.addEventListener('click', () => this.showStep(1));
        document.getElementById('generateTestsBtn')?.addEventListener('click', () => this.generateTests());
        
        // Step 3: Generation Progress
        document.getElementById('backToStoriesBtn')?.addEventListener('click', () => this.showStep(2));
        document.getElementById('cancelGenerationBtn')?.addEventListener('click', () => this.cancelGeneration());
        
        // Step 4: Export
        document.getElementById('backToProgressBtn')?.addEventListener('click', () => this.showStep(3));
        document.getElementById('exportExcelBtn')?.addEventListener('click', () => this.exportToExcel());
        document.getElementById('exportJsonBtn')?.addEventListener('click', () => this.exportToJson());
        document.getElementById('exportJiraBtn')?.addEventListener('click', () => this.exportToJira());
        document.getElementById('newSessionBtn')?.addEventListener('click', () => this.startNewSession());
        document.getElementById('refreshStatusBtn')?.addEventListener('click', () => this.manualRefreshStatus());
        document.getElementById('debugSessionBtn')?.addEventListener('click', () => this.debugSession());
    }
    
    async validateJQL() {
        const jqlQuery = document.getElementById('jqlQuery').value.trim();
        const validateBtn = document.getElementById('validateJqlBtn');
        const validationResult = document.getElementById('jqlResult');
        
        if (!jqlQuery) {
            this.showError(validationResult, 'Please enter a JQL query');
            return;
        }
        
        try {
            validateBtn.disabled = true;
            validateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Validating...';
            
            const response = await fetch('/api/bulk-generator/validate-jql', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ jql_query: jqlQuery })
            });
            
            const result = await response.json();
            
            // Debug logging
            console.log('Validation response:', result);
            console.log('Response status:', response.status);
            console.log('Success:', result.success, 'Valid:', result.valid);
            
            if (response.status === 401) {
                this.showError(validationResult, result.error || 'Authentication failed. Please refresh the page and reconnect to Jira.');
                document.getElementById('fetchStoriesBtn').disabled = true;
                // Optionally redirect to home page for re-authentication
                if (result.action === 'reconnect') {
                    setTimeout(() => {
                        window.location.href = '/';
                    }, 3000);
                }
            } else if (result.success && result.valid) {
                this.showSuccess(validationResult, result.message);
                const fetchBtn = document.getElementById('fetchStoriesBtn');
                fetchBtn.disabled = false;
                console.log('Fetch Stories button enabled');
            } else {
                this.showError(validationResult, result.error || 'Invalid JQL query');
                document.getElementById('fetchStoriesBtn').disabled = true;
            }
            
        } catch (error) {
            this.showError(validationResult, 'Error validating JQL: ' + error.message);
        } finally {
            validateBtn.disabled = false;
            validateBtn.innerHTML = '<i class="fas fa-check"></i> Validate JQL';
        }
    }
    
    async fetchStories() {
        const jqlQuery = document.getElementById('jqlQuery').value.trim();
        const fetchBtn = document.getElementById('fetchStoriesBtn');
        
        try {
            fetchBtn.disabled = true;
            fetchBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Fetching Stories...';
            
            // Create session
            const sessionResponse = await fetch('/api/bulk-generator/create-session', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ jql_query: jqlQuery })
            });
            
            const sessionResult = await sessionResponse.json();
            if (!sessionResult.success) {
                throw new Error(sessionResult.error);
            }
            
            this.sessionId = sessionResult.session_id;
            
            // Fetch stories
            const storiesResponse = await fetch('/api/bulk-generator/fetch-stories', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ session_id: this.sessionId })
            });
            
            const storiesResult = await storiesResponse.json();
            if (!storiesResult.success) {
                throw new Error(storiesResult.error);
            }
            
            this.stories = storiesResult.stories;
            this.displayStories(this.stories);
            
            // Show Step 2 (Story Selection)
            document.getElementById('step-jql').style.display = 'none';
            document.getElementById('step-stories').style.display = 'block';
            
        } catch (error) {
            this.showError(document.getElementById('jqlResult'), 'Error fetching stories: ' + error.message);
        } finally {
            fetchBtn.disabled = false;
            fetchBtn.innerHTML = '<i class="fas fa-download"></i> Fetch Stories';
        }
    }
    
    displayStories(stories) {
        this.stories = stories;
        this.currentPage = 1;
        // Initialize all stories as selected by default
        this.allSelectedStories = new Set(stories.map(story => story.key));
        
        this.renderCurrentPage();
        this.updatePagination();
        
        // Initialize event listeners for bulk actions
        this.initializeStoryEventListeners();
        
        // Update initial stats including cost
        this.updateStoryStats();
        
        // Enable generate button
        document.getElementById('generateTestsBtn').disabled = false;
    }
    
    renderCurrentPage() {
        const storyList = document.getElementById('storyList');
        const totalStoriesEl = document.getElementById('totalStories');
        
        const totalCount = this.stories.length;
        if (totalStoriesEl) totalStoriesEl.textContent = totalCount;
        
        // Calculate pagination
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = Math.min(startIndex + this.itemsPerPage, totalCount);
        const currentPageStories = this.stories.slice(startIndex, endIndex);
        
        // Display current page stories
        storyList.innerHTML = currentPageStories.map(story => `
            <div class="story-item">
                <div class="story-checkbox">
                    <input type="checkbox" id="story-${story.key}" value="${story.key}" 
                           ${this.allSelectedStories.has(story.key) ? 'checked' : ''} 
                           onchange="bulkGenerator.handleStorySelection('${story.key}', this.checked)">
                </div>
                <div class="story-details" onclick="document.getElementById('story-${story.key}').click()">
                    <div class="story-header">
                        <span class="story-key">${story.key}</span>
                        <span class="badge story-type">${story.type}</span>
                        <span class="badge story-priority priority-${story.priority?.toLowerCase()}">${story.priority}</span>
                    </div>
                    <div class="story-title">${story.title}</div>
                    <div class="story-status">Status: ${story.status}</div>
                </div>
            </div>
        `).join('');
    }
    
    updatePagination() {
        const totalCount = this.stories.length;
        const totalPages = Math.ceil(totalCount / this.itemsPerPage);
        const paginationContainer = document.getElementById('paginationContainer');
        const paginationInfo = document.getElementById('paginationInfo');
        const pageNumbers = document.getElementById('pageNumbers');
        const prevBtn = document.getElementById('prevPage');
        const nextBtn = document.getElementById('nextPage');
        
        if (totalPages <= 1) {
            paginationContainer.style.display = 'none';
            return;
        }
        
        paginationContainer.style.display = 'flex';
        
        // Update pagination info
        const startIndex = (this.currentPage - 1) * this.itemsPerPage + 1;
        const endIndex = Math.min(this.currentPage * this.itemsPerPage, totalCount);
        paginationInfo.textContent = `Showing ${startIndex}-${endIndex} of ${totalCount} stories`;
        
        // Update page numbers
        let pageNumbersHTML = '';
        const maxVisiblePages = 5;
        let startPage = Math.max(1, this.currentPage - Math.floor(maxVisiblePages / 2));
        let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);
        
        if (endPage - startPage < maxVisiblePages - 1) {
            startPage = Math.max(1, endPage - maxVisiblePages + 1);
        }
        
        for (let i = startPage; i <= endPage; i++) {
            pageNumbersHTML += `
                <button class="${i === this.currentPage ? 'active' : ''}" onclick="bulkGenerator.goToPage(${i})">
                    ${i}
                </button>
            `;
        }
        pageNumbers.innerHTML = pageNumbersHTML;
        
        // Update prev/next buttons
        prevBtn.disabled = this.currentPage === 1;
        nextBtn.disabled = this.currentPage === totalPages;
    }
    
    goToPage(page) {
        this.currentPage = page;
        this.renderCurrentPage();
        this.updatePagination();
        this.updateStoryStats();
    }
    
    previousPage() {
        if (this.currentPage > 1) {
            this.goToPage(this.currentPage - 1);
        }
    }
    
    nextPage() {
        const totalPages = Math.ceil(this.stories.length / this.itemsPerPage);
        if (this.currentPage < totalPages) {
            this.goToPage(this.currentPage + 1);
        }
    }
    
    initializeStoryEventListeners() {
        // Select All button
        const selectAllBtn = document.getElementById('selectAllBtn');
        if (selectAllBtn) {
            selectAllBtn.addEventListener('click', () => {
                this.selectAllStories();
                this.updateStoryStats();
            });
        }
        
        // Deselect All button
        const deselectAllBtn = document.getElementById('deselectAllBtn');
        if (deselectAllBtn) {
            deselectAllBtn.addEventListener('click', () => {
                this.deselectAllStories();
                this.updateStoryStats();
            });
        }
    }
    
    handleStorySelection(storyKey, isSelected) {
        if (isSelected) {
            this.allSelectedStories.add(storyKey);
        } else {
            this.allSelectedStories.delete(storyKey);
        }
        this.updateStoryStats();
    }
    
    updateStoryStats() {
        const totalCount = this.stories.length;
        const selectedCount = this.allSelectedStories.size;
        
        // Update counts
        const totalStoriesEl = document.getElementById('totalStories');
        const selectedStoriesEl = document.getElementById('selectedStories');
        const estimatedCostEl = document.getElementById('estimatedCost');
        
        if (totalStoriesEl) totalStoriesEl.textContent = totalCount;
        if (selectedStoriesEl) selectedStoriesEl.textContent = selectedCount;
        
        // Calculate estimated cost (approximately $0.10 per story for AI generation)
        const costPerStory = 0.10;
        const totalCost = selectedCount * costPerStory;
        if (estimatedCostEl) estimatedCostEl.textContent = `$${totalCost.toFixed(2)}`;
        
        // Enable/disable generate button based on selection
        const generateBtn = document.getElementById('generateTestsBtn');
        if (generateBtn) {
            generateBtn.disabled = selectedCount === 0;
        }
    }
    
    selectAllStories() {
        // Select all stories across all pages
        this.allSelectedStories = new Set(this.stories.map(story => story.key));
        
        // Update checkboxes on current page
        const checkboxes = document.querySelectorAll('#storyList input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = true);
    }
    
    deselectAllStories() {
        // Deselect all stories across all pages
        this.allSelectedStories = new Set();
        
        // Update checkboxes on current page
        const checkboxes = document.querySelectorAll('#storyList input[type="checkbox"]');
        checkboxes.forEach(cb => cb.checked = false);
    }
    
    async generateTests() {
        const selectedStories = this.getSelectedStories();
        const contextSelect = document.getElementById('contextSelect');
        const selectedContext = contextSelect ? contextSelect.value : '';
        
        if (selectedStories.length === 0) {
            alert('Please select at least one story to generate tests for.');
            return;
        }
        
        if (selectedStories.length > 10) {
            alert('Maximum 10 stories can be selected for bulk generation. Please reduce your selection.');
            return;
        }
        
        if (!selectedContext) {
            alert('Please select a context for test generation.');
            contextSelect?.focus();
            return;
        }
        
        try {
            this.showStep(3);
            this.generationProgress.total = selectedStories.length;
            this.updateProgressDisplay();
            
            // Start generation with selected stories
            const response = await fetch('/api/bulk-generator/generate-tests', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ 
                    session_id: this.sessionId,
                    selected_stories: selectedStories,
                    context: selectedContext
                })
            });
            
            const result = await response.json();
            if (!result.success) {
                throw new Error(result.error);
            }
            
            // Since we're using synchronous processing, load results immediately
            this.loadGeneratedTests();
            this.showStep(4);
            
        } catch (error) {
            console.error('Generation error:', error);
            this.showError(document.getElementById('generationStatus'), 'Error generating tests: ' + error.message);
        }
    }
    
    updateProgressDisplay() {
        const progressBar = document.getElementById('progressFill');
        const progressText = document.getElementById('progressText');
        const progressPercent = document.getElementById('progressPercent');
        const completedCount = document.getElementById('completedCount');
        const remainingCount = document.getElementById('remainingCount');
        
        const percentage = this.generationProgress.total > 0 ? 
            (this.generationProgress.processed + this.generationProgress.failed) / this.generationProgress.total * 100 : 0;
        
        console.log('Updating progress display:', {
            progressBar: !!progressBar,
            progressText: !!progressText,
            percentage: percentage.toFixed(1),
            processed: this.generationProgress.processed,
            failed: this.generationProgress.failed,
            total: this.generationProgress.total
        });
        
        if (progressBar) progressBar.style.width = `${percentage}%`;
        if (progressText) progressText.textContent = `Processing ${this.generationProgress.processed + this.generationProgress.failed} of ${this.generationProgress.total} stories`;
        if (progressPercent) progressPercent.textContent = `${Math.round(percentage)}%`;
        if (completedCount) completedCount.textContent = this.generationProgress.processed;
        if (remainingCount) remainingCount.textContent = this.generationProgress.total - this.generationProgress.processed - this.generationProgress.failed;
        
    }

    loadGeneratedTests() {
        if (!this.sessionId) {
            console.error('No session ID available');
            return;
        }
        
        console.log('Loading generated tests for session:', this.sessionId);
        
        fetch(`/api/bulk-generator/debug-session/${this.sessionId}`)
            .then(response => response.json())
            .then(result => {
                console.log('Stories result:', result);
                if (result.success) {
                    // Store stories for pagination
                    this.currentStories = result.stories;
                    this.displayTestCasesReview(result.stories);
                } else {
                    console.error('Error loading stories:', result.error);
                    const reviewContainer = document.getElementById('testCasesReview');
                    if (reviewContainer) {
                        reviewContainer.innerHTML = '<div class="error-message">Error loading test cases: ' + result.error + '</div>';
                    }
                }
            })
            .catch(error => {
                console.error('Error loading generated tests:', error);
                const reviewContainer = document.getElementById('testCasesReview');
                if (reviewContainer) {
                    reviewContainer.innerHTML = '<div class="error-message">Error loading test cases: ' + error.message + '</div>';
                }
            });
    }
    displayTestCasesReview(stories) {
        console.log('Displaying test cases for stories:', stories);
        
        // Filter to only show stories that have test cases or were processed
        const processedStories = stories.filter(story => 
            story.test_cases || 
            story.test_generation_status === 'completed' || 
            story.test_generation_status === 'failed'
        );
        
        console.log(`Filtered to ${processedStories.length} processed stories out of ${stories.length} total stories`);
        
        // Wait for DOM to be ready
        setTimeout(() => {
            const reviewContainer = document.getElementById('testCasesReview');
            if (!reviewContainer) {
                console.error('testCasesReview element not found');
                return;
            }
            
            let html = '';
            let storiesWithTests = 0;
            
            if (processedStories.length === 0) {
                html = '<div class="no-test-cases" style="text-align: center; padding: 40px; color: #666;">No stories were processed for test generation. Please check your selection and try again.</div>';
                reviewContainer.innerHTML = html;
                return;
            }
            
            processedStories.forEach((story, index) => {
                console.log('Processing story', story.jira_key + ', has_test_cases:', !!story.test_cases, 'status:', story.test_generation_status);
                console.log('Story test_cases raw data:', story.test_cases);
                console.log('Story test_cases type:', typeof story.test_cases);
                console.log('Story test_cases length:', story.test_cases ? story.test_cases.length : 'null');
                
                let testCases = [];
                let hasValidTestCases = false;
                
                if (story.test_cases) {
                    try {
                        testCases = JSON.parse(story.test_cases || '[]');
                        hasValidTestCases = testCases.length > 0;
                        console.log(`Parsed ${testCases.length} test cases for ${story.jira_key}`);
                    } catch (e) {
                        console.error('Error parsing test cases for story:', story.jira_key, e);
                    }
                }
                
                // Show story even if generation failed
                storiesWithTests++;
                
                const statusColor = story.test_generation_status === 'failed' ? '#dc3545' : 
                                   story.test_generation_status === 'completed' ? '#28a745' : '#6c757d';
                const statusText = story.test_generation_status === 'failed' ? 'Failed' : 
                                  story.test_generation_status === 'completed' ? 'Completed' : 'Processing';
                
                html += `
                    <div class="story-test-cases" style="margin-bottom: 20px; border: 1px solid #ddd; border-radius: 8px; padding: 15px;">
                        <div class="story-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
                            <div class="story-info">
                                <h4 style="margin: 0; color: #333;">${story.jira_key}: ${story.title}</h4>
                                <div style="display: flex; gap: 10px; align-items: center;">
                                    <span class="test-count" style="color: #666; font-size: 14px;">${testCases.length} test cases</span>
                                    <span class="status-badge" style="background: ${statusColor}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px;">${statusText}</span>
                                </div>
                            </div>
                            ${hasValidTestCases ? `
                            <button class="toggle-tests" style="background: none; border: 1px solid #ccc; padding: 8px 12px; border-radius: 4px; cursor: pointer;" onclick="toggleTestCases(this)">
                                <i class="fas fa-chevron-up"></i>
                            </button>
                            ` : ''}
                        </div>
                        
                        <div class="test-cases-list" style="display: block;">
                            ${story.test_generation_status === 'failed' ? `
                                <div class="error-message" style="padding: 12px; background: #f8d7da; border: 1px solid #f5c6cb; border-radius: 6px; color: #721c24;">
                                    <strong>Generation Failed:</strong> ${story.generation_error || 'Unknown error occurred during test case generation'}
                                </div>
                            ` : hasValidTestCases ? `
                                <div class="story-actions" style="margin-bottom: 15px; display: flex; gap: 10px; flex-wrap: wrap;">
                                    <button class="btn-export" onclick="bulkGenerator.exportStoryToExcel('${story.jira_key}')" style="background: #28a745; color: white; border: none; padding: 6px 12px; border-radius: 4px; font-size: 12px; cursor: pointer;">
                                        <i class="fas fa-file-excel"></i> Export Excel
                                    </button>
                                    <button class="btn-export" onclick="bulkGenerator.exportStoryToJson('${story.jira_key}')" style="background: #17a2b8; color: white; border: none; padding: 6px 12px; border-radius: 4px; font-size: 12px; cursor: pointer;">
                                        <i class="fas fa-file-code"></i> Export JSON
                                    </button>
                                    <button class="btn-jira" onclick="bulkGenerator.addToJira('${story.jira_key}')" style="background: #0052cc; color: white; border: none; padding: 6px 12px; border-radius: 4px; font-size: 12px; cursor: pointer;">
                                        <i class="fab fa-jira"></i> Add to Jira
                                    </button>
                                    <button class="btn-add-test" onclick="bulkGenerator.addNewTestCase('${story.jira_key}')" style="background: #6f42c1; color: white; border: none; padding: 6px 12px; border-radius: 4px; font-size: 12px; cursor: pointer;">
                                        <i class="fas fa-plus"></i> Add Test Case
                                    </button>
                                </div>
                                <div class="test-cases-pagination" id="pagination-${story.jira_key}">
                                    ${this.renderTestCasesWithPagination(testCases, story.jira_key)}
                                </div>
                            ` : `
                                <div class="no-test-cases" style="padding: 12px; background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 6px; color: #856404;">
                                    <strong>No test cases generated:</strong> The story was processed but no test cases were created. This might be due to insufficient story details or AI generation issues.
                                </div>
                            `}
                        </div>
                    </div>
                `;
            });
            
            if (html === '') {
                html = '<div class="no-test-cases" style="text-align: center; padding: 40px; color: #666;">No test cases generated yet.</div>';
            }
            
            console.log(`Generated HTML for ${storiesWithTests} stories with test cases`);
            console.log('Setting innerHTML on reviewContainer:', reviewContainer);
            console.log('HTML content length:', html.length);
            console.log('First 500 chars of HTML:', html.substring(0, 500));
            
            reviewContainer.innerHTML = html;
            
            // Verify the content was set
            setTimeout(() => {
                console.log('After setting innerHTML, reviewContainer children count:', reviewContainer.children.length);
                console.log('reviewContainer innerHTML length:', reviewContainer.innerHTML.length);
            }, 50);
        }, 100);
    }
    
    updateReviewStats(stories) {
        let totalTestCases = 0;
        let totalTime = 0;
        let successfulStories = 0;
        
        stories.forEach(story => {
            if (story.test_cases) {
                successfulStories++;
                try {
                    const testCases = JSON.parse(story.test_cases || '[]');
                    totalTestCases += testCases.length;
                    totalTime += testCases.reduce((sum, tc) => sum + (tc.estimate_minutes || 15), 0);
                } catch (e) {
                    console.error('Error parsing test cases for stats:', story.jira_key, e);
                }
            }
        });
        
        const successRate = stories.length > 0 ? (successfulStories / stories.length * 100).toFixed(0) : 100;
        const totalHours = Math.round(totalTime / 60 * 10) / 10;
        
        console.log('Updating stats:', { totalTestCases, totalHours, successRate });
        
        setTimeout(() => {
            const generatedTestsEl = document.getElementById('generatedTests');
            const totalTimeEl = document.getElementById('totalTime');
            const successRateEl = document.getElementById('successRate');
            
            if (generatedTestsEl) generatedTestsEl.textContent = totalTestCases;
            if (totalTimeEl) totalTimeEl.textContent = `${totalHours}h`;
            if (successRateEl) successRateEl.textContent = `${successRate}%`;
        }, 150);
    }
    
    cancelGeneration() {
        // Implementation for canceling generation
        if (confirm('Are you sure you want to cancel test generation?')) {
            // Cancel the generation process
            this.showStep(2);
        }
    }
    
    getSelectedStories() {
        return Array.from(this.allSelectedStories);
    }
    
    async manualRefreshStatus() {
        if (!this.sessionId) {
            alert('No active session found');
            return;
        }
        
        try {
            const response = await fetch(`/api/bulk-generator/session-status/${this.sessionId}`);
            const result = await response.json();
            
            console.log('Manual status check:', result);
            
            if (result.success) {
                this.generationProgress.processed = result.processed_stories || 0;
                this.generationProgress.failed = result.failed_stories || 0;
                this.generationProgress.total = result.total_stories || this.generationProgress.total;
                this.updateProgressDisplay();
                
                // Show detailed status in alert
                alert(`Status: ${result.status}\nProcessed: ${result.processed_stories}\nFailed: ${result.failed_stories}\nTotal: ${result.total_stories}\nProgress: ${result.progress_percentage.toFixed(1)}%`);
                
                // Check if complete
                if (result.status === 'completed') {
                    this.loadGeneratedTests();
                    this.showStep(4);
                } else if (result.status === 'failed') {
                    this.showError(document.getElementById('generationStatus'), 'Generation failed');
                }
            } else {
                alert('Error: ' + result.error);
            }
        } catch (error) {
            console.error('Manual refresh error:', error);
            alert('Error checking status: ' + error.message);
        }
    }
    
    async debugSession() {
        if (!this.sessionId) {
            alert('No active session found');
            return;
        }
        
        try {
            const response = await fetch(`/api/bulk-generator/debug-session/${this.sessionId}`);
            const result = await response.json();
            
            console.log('Debug session info:', result);
            
            if (result.success) {
                const session = result.session;
                const stories = result.stories;
                
                let debugInfo = `=== SESSION DEBUG INFO ===\n`;
                debugInfo += `Session ID: ${session.id}\n`;
                debugInfo += `Status: ${session.status}\n`;
                debugInfo += `Total Stories: ${session.total_stories}\n`;
                debugInfo += `Processed: ${session.processed_stories}\n`;
                debugInfo += `Failed: ${session.failed_stories}\n`;
                debugInfo += `Created: ${session.created_at}\n`;
                debugInfo += `Completed: ${session.completed_at || 'Not completed'}\n\n`;
                
                debugInfo += `=== STORIES (${stories.length}) ===\n`;
                stories.forEach((story, i) => {
                    debugInfo += `${i+1}. ${story.jira_key}: ${story.title}\n`;
                    debugInfo += `   Status: ${story.test_generation_status || 'Not started'}\n`;
                    debugInfo += `   Has Test Cases: ${story.has_test_cases}\n`;
                    if (story.generation_error) {
                        debugInfo += `   Error: ${story.generation_error}\n`;
                    }
                    debugInfo += `\n`;
                });
                
                // Show in console and alert
                console.log(debugInfo);
                alert(debugInfo);
            } else {
                alert('Debug Error: ' + result.error);
            }
        } catch (error) {
            console.error('Debug session error:', error);
            alert('Error debugging session: ' + error.message);
        }
    }
    
    showStep(stepNumber) {
        console.log(`Showing step ${stepNumber}`);
        
        // Hide all steps
        for (let i = 1; i <= 4; i++) {
            const stepId = `step-${i === 1 ? 'jql' : i === 2 ? 'stories' : i === 3 ? 'progress' : 'review'}`;
            const step = document.getElementById(stepId);
            if (step) {
                step.style.display = 'none';
                console.log(`Hidden step: ${stepId}`);
            } else {
                console.log(`Step not found: ${stepId}`);
            }
        }
        
        // Show current step
        const stepNames = ['', 'jql', 'stories', 'progress', 'review'];
        const currentStepId = `step-${stepNames[stepNumber]}`;
        const currentStep = document.getElementById(currentStepId);
        if (currentStep) {
            currentStep.style.display = 'block';
            console.log(`Shown step: ${currentStepId}`);
            
            // If showing results step, ensure testCasesReview element exists
            if (stepNumber === 4) {
                setTimeout(() => {
                    const reviewEl = document.getElementById('testCasesReview');
                    console.log('testCasesReview element in results step:', reviewEl);
                    if (reviewEl) {
                        console.log('testCasesReview current content length:', reviewEl.innerHTML.length);
                    }
                }, 100);
            }
        } else {
            console.log(`Current step not found: ${currentStepId}`);
        }
        
        this.currentStep = stepNumber;
    }
    
    showError(element, message) {
        if (element) {
            element.innerHTML = `
                <div class="alert alert-danger">
                    <i class="fas fa-exclamation-triangle"></i>
                    ${message}
                </div>
            `;
        } else {
            console.error('showError: element is null', message);
        }
    }
    
    showSuccess(element, message) {
        if (element) {
            element.innerHTML = `
                <div class="alert alert-success">
                    <i class="fas fa-check-circle"></i>
                    ${message}
                </div>
            `;
        } else {
            console.error('showSuccess: element is null', message);
        }
    }
    
    startNewSession() {
        // Reset the entire session and go back to step 1
        if (confirm('Are you sure you want to start a new session? This will clear all current data.')) {
            this.currentStep = 1;
            this.sessionId = null;
            this.stories = [];
            this.currentPage = 1;
            this.allSelectedStories = new Set();
            this.generationProgress = {
                total: 0,
                processed: 0,
                failed: 0
            };
            
            // Clear form data
            document.getElementById('jqlQuery').value = '';
            document.getElementById('jqlResult').innerHTML = '';
            document.getElementById('fetchStoriesBtn').disabled = true;
            
            // Show step 1
            this.showStep(1);
        }
    }

    // Export functions (placeholder implementations)
    exportToExcel() {
        alert('Excel export functionality coming soon!');
    }
    
    exportToJson() {
        alert('JSON export functionality coming soon!');
    }
    
    exportToJira() {
        alert('Jira export functionality coming soon!');
    }
    
    // Individual story management functions
    async exportStoryToExcel(storyKey) {
        try {
            const story = await this.getStoryData(storyKey);
            if (!story || !story.test_cases) {
                alert('No test cases found for this story');
                return;
            }
            
            const testCases = JSON.parse(story.test_cases);
            this.downloadExcel(testCases, `${storyKey}_test_cases.xlsx`);
        } catch (error) {
            console.error('Error exporting to Excel:', error);
            alert('Error exporting to Excel: ' + error.message);
        }
    }
    
    async exportStoryToJson(storyKey) {
        try {
            const story = await this.getStoryData(storyKey);
            if (!story || !story.test_cases) {
                alert('No test cases found for this story');
                return;
            }
            
            const testCases = JSON.parse(story.test_cases);
            const exportData = {
                story_key: storyKey,
                story_title: story.title,
                test_cases: testCases,
                exported_at: new Date().toISOString()
            };
            
            this.downloadJson(exportData, `${storyKey}_test_cases.json`);
        } catch (error) {
            console.error('Error exporting to JSON:', error);
            alert('Error exporting to JSON: ' + error.message);
        }
    }
    
    async addStoryToJira(storyKey) {
        try {
            const story = await this.getStoryData(storyKey);
            if (!story || !story.test_cases) {
                alert('No test cases found for this story');
                return;
            }
            
            const testCases = JSON.parse(story.test_cases);
            const confirmed = confirm(`Add ${testCases.length} test cases to Jira story ${storyKey}?`);
            
            if (confirmed) {
                const response = await fetch('/api/bulk-generator/add-to-jira', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        story_key: storyKey,
                        test_cases: testCases
                    })
                });
                
                const result = await response.json();
                if (result.success) {
                    alert(`Successfully added ${testCases.length} test cases to ${storyKey}`);
                } else {
                    alert('Error adding to Jira: ' + result.error);
                }
            }
        } catch (error) {
            console.error('Error adding to Jira:', error);
            alert('Error adding to Jira: ' + error.message);
        }
    }
    
    editTestCase(storyKey, testIndex) {
        const contentEl = document.getElementById(`content-${storyKey}-${testIndex}`);
        const stepEl = contentEl.querySelector('.step-text');
        const expectedEl = contentEl.querySelector('.expected-text');
        
        const currentStep = stepEl.textContent;
        const currentExpected = expectedEl.textContent;
        
        // Create edit form
        const editForm = `
            <div class="edit-form" style="background: white; padding: 15px; border: 1px solid #ddd; border-radius: 6px;">
                <div style="margin-bottom: 10px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px;">Step:</label>
                    <textarea id="edit-step-${storyKey}-${testIndex}" style="width: 100%; height: 60px; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">${currentStep}</textarea>
                </div>
                <div style="margin-bottom: 10px;">
                    <label style="display: block; font-weight: bold; margin-bottom: 5px;">Expected:</label>
                    <textarea id="edit-expected-${storyKey}-${testIndex}" style="width: 100%; height: 60px; padding: 8px; border: 1px solid #ccc; border-radius: 4px;">${currentExpected}</textarea>
                </div>
                <div style="display: flex; gap: 10px;">
                    <button onclick="bulkGenerator.saveTestCase('${storyKey}', ${testIndex})" style="background: #28a745; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
                        <i class="fas fa-save"></i> Save
                    </button>
                    <button onclick="bulkGenerator.cancelEdit('${storyKey}', ${testIndex})" style="background: #6c757d; color: white; border: none; padding: 8px 16px; border-radius: 4px; cursor: pointer;">
                        <i class="fas fa-times"></i> Cancel
                    </button>
                </div>
            </div>
        `;
        
        contentEl.innerHTML = editForm;
    }
    
    async saveTestCase(storyKey, testIndex) {
        const stepEl = document.getElementById(`edit-step-${storyKey}-${testIndex}`);
        const expectedEl = document.getElementById(`edit-expected-${storyKey}-${testIndex}`);
        
        const newStep = stepEl.value.trim();
        const newExpected = expectedEl.value.trim();
        
        if (!newStep || !newExpected) {
            alert('Both step and expected result are required');
            return;
        }
        
        try {
            const response = await fetch('/api/bulk-generator/update-test-case', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    story_key: storyKey,
                    test_index: testIndex,
                    step: newStep,
                    expected: newExpected
                })
            });
            
            const result = await response.json();
            if (result.success) {
                // Update the display
                const contentEl = document.getElementById(`content-${storyKey}-${testIndex}`);
                contentEl.innerHTML = `
                    <div class="test-step" style="margin-bottom: 8px;">
                        <strong>Step:</strong> <span class="step-text">${newStep}</span>
                    </div>
                    <div class="test-expected">
                        <strong>Expected:</strong> <span class="expected-text">${newExpected}</span>
                    </div>
                `;
            } else {
                alert('Error saving test case: ' + result.error);
            }
        } catch (error) {
            console.error('Error saving test case:', error);
            alert('Error saving test case: ' + error.message);
        }
    }
    
    cancelEdit(storyKey, testIndex) {
        // Reload the original content
        this.loadGeneratedTests();
    }
    
    async deleteTestCase(storyKey, testIndex) {
        const confirmed = confirm('Are you sure you want to delete this test case?');
        if (!confirmed) return;
        
        try {
            const response = await fetch('/api/bulk-generator/delete-test-case', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    story_key: storyKey,
                    test_index: testIndex
                })
            });
            
            const result = await response.json();
            if (result.success) {
                // Remove the test case element
                const testCaseEl = document.getElementById(`test-case-${storyKey}-${testIndex}`);
                testCaseEl.remove();
                
                // Reload to update numbering
                this.loadGeneratedTests();
            } else {
                alert('Error deleting test case: ' + result.error);
            }
        } catch (error) {
            console.error('Error deleting test case:', error);
            alert('Error deleting test case: ' + error.message);
        }
    }
    
    addNewTestCase(storyKey) {
        const newStep = prompt('Enter the test step:');
        if (!newStep) return;
        
        const newExpected = prompt('Enter the expected result:');
        if (!newExpected) return;
        
        const estimateMinutes = prompt('Enter estimated minutes (5, 10, 15, 20, 30, 45, or 60):', '15');
        const validMinutes = [5, 10, 15, 20, 30, 45, 60];
        const minutes = parseInt(estimateMinutes);
        
        if (!validMinutes.includes(minutes)) {
            alert('Please enter a valid estimate: 5, 10, 15, 20, 30, 45, or 60 minutes');
            return;
        }
        
        this.saveNewTestCase(storyKey, newStep, newExpected, minutes);
    }
    
    async saveNewTestCase(storyKey, step, expected, estimateMinutes) {
        try {
            const response = await fetch('/api/bulk-generator/add-test-case', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    session_id: this.sessionId,
                    story_key: storyKey,
                    step: step,
                    expected: expected,
                    estimate_minutes: estimateMinutes
                })
            });
            
            const result = await response.json();
            if (result.success) {
                // Reload to show the new test case
                this.loadGeneratedTests();
            } else {
                alert('Error adding test case: ' + result.error);
            }
        } catch (error) {
            console.error('Error adding test case:', error);
            alert('Error adding test case: ' + error.message);
        }
    }
    
    async getStoryData(storyKey) {
        try {
            const response = await fetch(`/api/bulk-generator/debug-session/${this.sessionId}`);
            const result = await response.json();
            
            if (result.success) {
                return result.stories.find(story => story.jira_key === storyKey);
            }
            return null;
        } catch (error) {
            console.error('Error getting story data:', error);
            return null;
        }
    }
    
    downloadExcel(testCases, filename) {
        // Create CSV content (simple Excel alternative)
        const headers = ['Test Case #', 'Step', 'Expected Result', 'Estimate (minutes)'];
        const csvContent = [
            headers.join(','),
            ...testCases.map((tc, index) => [
                index + 1,
                `"${tc.step.replace(/"/g, '""')}"`,
                `"${tc.expected.replace(/"/g, '""')}"`,
                tc.estimate_minutes || 15
            ].join(','))
        ].join('\n');
        
        this.downloadFile(csvContent, filename.replace('.xlsx', '.csv'), 'text/csv');
    }
    
    downloadJson(data, filename) {
        const jsonContent = JSON.stringify(data, null, 2);
        this.downloadFile(jsonContent, filename, 'application/json');
    }
    
    downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }
    
    renderTestCasesWithPagination(testCases, storyKey) {
        const itemsPerPage = 5;
        const totalPages = Math.ceil(testCases.length / itemsPerPage);
        
        if (testCases.length <= itemsPerPage) {
            // No pagination needed
            return testCases.map((testCase, tcIndex) => this.renderTestCase(testCase, tcIndex, storyKey)).join('');
        }
        
        // Render first page initially
        const firstPageCases = testCases.slice(0, itemsPerPage);
        const testCasesHtml = firstPageCases.map((testCase, tcIndex) => this.renderTestCase(testCase, tcIndex, storyKey)).join('');
        
        // Pagination controls
        const paginationControls = `
            <div class="pagination-controls" style="margin-top: 15px; text-align: center; display: flex; justify-content: space-between; align-items: center;">
                <div class="pagination-info" style="font-size: 12px; color: #666;">
                    Showing <span id="page-info-${storyKey}">1-${Math.min(itemsPerPage, testCases.length)} of ${testCases.length}</span> test cases
                </div>
                <div class="pagination-buttons">
                    <button onclick="bulkGenerator.changePage('${storyKey}', -1)" id="prev-${storyKey}" style="background: #6c757d; color: white; border: none; padding: 5px 10px; border-radius: 3px; font-size: 11px; cursor: pointer; margin-right: 5px;" disabled>
                        <i class="fas fa-chevron-left"></i> Previous
                    </button>
                    <span id="page-display-${storyKey}" style="margin: 0 10px; font-size: 12px; font-weight: bold;">1 / ${totalPages}</span>
                    <button onclick="bulkGenerator.changePage('${storyKey}', 1)" id="next-${storyKey}" style="background: #007bff; color: white; border: none; padding: 5px 10px; border-radius: 3px; font-size: 11px; cursor: pointer; margin-left: 5px;">
                        Next <i class="fas fa-chevron-right"></i>
                    </button>
                </div>
            </div>
        `;
        
        return `
            <div class="test-cases-container" id="test-cases-${storyKey}">
                ${testCasesHtml}
            </div>
            ${paginationControls}
        `;
    }
    
    renderTestCase(testCase, tcIndex, storyKey) {
        return `
            <div class="test-case-item" id="test-case-${storyKey}-${tcIndex}" style="margin-bottom: 15px; padding: 12px; background: #f9f9f9; border-radius: 6px; position: relative;">
                <div class="test-case-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span class="test-case-number" style="font-weight: bold; color: #007bff;">Test Case #${tcIndex + 1}</span>
                    <div style="display: flex; gap: 5px; align-items: center;">
                        <span class="test-case-time" style="background: #e9ecef; padding: 4px 8px; border-radius: 4px; font-size: 12px;">${testCase.estimate_minutes || 15} min</span>
                        <button class="btn-edit" onclick="bulkGenerator.editTestCase('${storyKey}', ${tcIndex})" style="background: #ffc107; color: #212529; border: none; padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer;">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn-delete" onclick="bulkGenerator.deleteTestCase('${storyKey}', ${tcIndex})" style="background: #dc3545; color: white; border: none; padding: 4px 8px; border-radius: 3px; font-size: 11px; cursor: pointer;">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="test-case-content" id="content-${storyKey}-${tcIndex}">
                    <div class="test-step" style="margin-bottom: 8px;">
                        <strong>Step:</strong> <span class="step-text">${testCase.step || 'No step provided'}</span>
                    </div>
                    <div class="test-expected">
                        <strong>Expected:</strong> <span class="expected-text">${testCase.expected || 'No expected result provided'}</span>
                    </div>
                </div>
            </div>
        `;
    }
    
    changePage(storyKey, direction) {
        const story = this.currentStories.find(s => s.jira_key === storyKey);
        if (!story || !story.test_cases) return;
        
        const testCases = JSON.parse(story.test_cases);
        const itemsPerPage = 5;
        const totalPages = Math.ceil(testCases.length / itemsPerPage);
        
        // Get current page from display
        const pageDisplay = document.getElementById(`page-display-${storyKey}`);
        const currentPage = parseInt(pageDisplay.textContent.split(' / ')[0]);
        
        let newPage = currentPage + direction;
        if (newPage < 1) newPage = 1;
        if (newPage > totalPages) newPage = totalPages;
        
        if (newPage === currentPage) return; // No change needed
        
        // Calculate slice indices
        const startIndex = (newPage - 1) * itemsPerPage;
        const endIndex = Math.min(startIndex + itemsPerPage, testCases.length);
        const pageCases = testCases.slice(startIndex, endIndex);
        
        // Update test cases display
        const container = document.getElementById(`test-cases-${storyKey}`);
        container.innerHTML = pageCases.map((testCase, localIndex) => 
            this.renderTestCase(testCase, startIndex + localIndex, storyKey)
        ).join('');
        
        // Update pagination info
        document.getElementById(`page-info-${storyKey}`).textContent = 
            `${startIndex + 1}-${endIndex} of ${testCases.length}`;
        document.getElementById(`page-display-${storyKey}`).textContent = 
            `${newPage} / ${totalPages}`;
        
        // Update button states
        document.getElementById(`prev-${storyKey}`).disabled = newPage === 1;
        document.getElementById(`next-${storyKey}`).disabled = newPage === totalPages;
    }
}

// Global function for toggling test cases
function toggleTestCases(button) {
    const list = button.parentElement.parentElement.querySelector('.test-cases-list');
    const isHidden = list.style.display === 'none';
    list.style.display = isHidden ? 'block' : 'none';
    button.innerHTML = isHidden ? '<i class="fas fa-chevron-up"></i>' : '<i class="fas fa-chevron-down"></i>';
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    window.bulkGenerator = new BulkTestGenerator();
});
