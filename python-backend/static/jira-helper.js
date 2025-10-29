class JiraBuckets {
    constructor() {
        this.parentAggregates = new Map();
        this.assigneeGroups = [];
        this.jiraBaseUrl = (window.JIRA_BASE_URL || 'https://upgrad-jira.atlassian.net').replace(/\/+$/, '');
        this.apiEndpoint = window.API_ENDPOINT || '/api/jira-helper/jql';
        this.initializeElements();
        this.bindEvents();
        this.loadSampleQuery();
        this.restoreQuerySectionState();
        this._treeExpansionState = { releases: [], parents: [], childKey: null };
    }

    initializeElements() {
        this.jqlInput = document.getElementById('jql');
        this.runButton = document.getElementById('runQuery');
        this.clearButton = document.getElementById('clearQuery');
        this.favoriteFilterSelect = document.getElementById('favoriteFilterSelect');
        this.loadingDiv = document.getElementById('loading');
        this.errorDiv = document.getElementById('error');
        this.resultsDiv = document.getElementById('results');
        this.parentOverviewContainer = document.getElementById('parentOverview');

        // Layout toggle buttons
        this.cardViewBtn = document.getElementById('cardViewBtn');
        this.listViewBtn = document.getElementById('listViewBtn');
        this.currentLayout = 'card'; // default layout

        // Feature expand/collapse buttons
        this.expandAllFeaturesBtn = document.getElementById('expandAllFeatures');
        this.collapseAllFeaturesBtn = document.getElementById('collapseAllFeatures');

        this.buckets = {
            dev: document.getElementById('devBucket'),
            qa: document.getElementById('qaBucket'),
            product: document.getElementById('productBucket'),
            completed: document.getElementById('completedBucket'),
            dropped: document.getElementById('droppedBucket'),
            deployed: document.getElementById('deployedBucket'),
            other: document.getElementById('otherBucket')
        };

        this.counts = {
            dev: document.getElementById('devCount'),
            qa: document.getElementById('qaCount'),
            product: document.getElementById('productCount'),
            completed: document.getElementById('completedCount'),
            dropped: document.getElementById('droppedCount'),
            deployed: document.getElementById('deployedCount'),
            other: document.getElementById('otherCount')
        };

        this.totalCountSpan = document.getElementById('totalCount');
        this.bucketSummarySpan = document.getElementById('bucketSummary');

        // Modal elements
        this.modal = document.getElementById('featureModal');
        this.modalBody = document.getElementById('modalBody');
        this.modalClose = this.modal?.querySelector('.modal-close');
        this.modalBackdrop = this.modal?.querySelector('.modal-backdrop');

        // View toggle elements
        this.featureViewBtn = document.getElementById('featureViewBtn');
        this.teamViewBtn = document.getElementById('teamViewBtn');
        this.assigneeViewBtn = document.getElementById('assigneeViewBtn');
        this.featureView = document.getElementById('featureView');
        this.teamView = document.getElementById('teamView');
        this.assigneeView = document.getElementById('assigneeView');
        this.assigneeContainer = document.getElementById('assigneeContainer');

        // Control buttons
        this.expandAllTeamsBtn = document.getElementById('expandAllTeams');
        this.collapseAllTeamsBtn = document.getElementById('collapseAllTeams');
        this.expandAllAssigneesBtn = document.getElementById('expandAllAssignees');
        this.collapseAllAssigneesBtn = document.getElementById('collapseAllAssignees');

        // Query section toggle
        this.querySectionHeader = document.getElementById('querySectionHeader');
        this.queryToggle = document.getElementById('queryToggle');
        this.querySectionContent = document.getElementById('querySectionContent');
        this.queryToggleIcon = this.queryToggle?.querySelector('.toggle-icon');

        // Current view state (default: feature)
        this.currentView = 'feature';

        this.bucketContainers = {
            dev: document.querySelector('[data-bucket="dev"]'),
            qa: document.querySelector('[data-bucket="qa"]'),
            product: document.querySelector('[data-bucket="product"]'),
            completed: document.querySelector('[data-bucket="completed"]'),
            dropped: document.querySelector('[data-bucket="dropped"]'),
            deployed: document.querySelector('[data-bucket="deployed"]'),
            other: document.querySelector('[data-bucket="other"]')
        };

        this.bucketHeaders = {};
        this.bucketToggleIcons = {};

        Object.entries(this.bucketContainers).forEach(([bucket, container]) => {
            if (!container) return;
            const header = container.querySelector('.bucket-header');
            if (!header) return;

            const icon = document.createElement('span');
            icon.className = 'bucket-toggle';
            icon.setAttribute('aria-hidden', 'true');
            icon.textContent = 'v';
            header.insertBefore(icon, header.firstChild);

            header.setAttribute('role', 'button');
            header.setAttribute('tabindex', '0');
            header.setAttribute('aria-expanded', 'false');
            header.classList.add('bucket-header-collapsible');

            this.bucketHeaders[bucket] = header;
            this.bucketToggleIcons[bucket] = icon;

            // Set buckets to collapsed by default
            container.classList.add('collapsed');
            icon.textContent = '>';
        });

        this.refreshResultsBtn = document.getElementById('refreshResultsBtn');
        this.downloadReportBtn = document.getElementById('downloadReportBtn');
        this.generateSummaryBtn = document.getElementById('generateSummaryBtn');
    }

    bindEvents() {
        this.runButton.addEventListener('click', () => this.runQuery());
        this.clearButton.addEventListener('click', () => this.clearQuery());

        // Favorite filter dropdown
        this.setupFavoriteFilters();

        this.jqlInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.ctrlKey) {
                e.preventDefault();
                this.runQuery();
            }
        });

        Object.entries(this.bucketHeaders).forEach(([bucket, header]) => {
            header.addEventListener('click', () => this.toggleBucket(bucket));
            header.addEventListener('keydown', (event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    this.toggleBucket(bucket);
                }
            });
        });

        // Modal event listeners
        if (this.modalClose) {
            this.modalClose.addEventListener('click', () => this.closeModal());
        }
        if (this.modalBackdrop) {
            this.modalBackdrop.addEventListener('click', () => this.closeModal());
        }

        // Close modal on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal && !this.modal.classList.contains('hidden')) {
                this.closeModal();
            }
        });

        // View toggle event listeners
        if (this.featureViewBtn) {
            this.featureViewBtn.addEventListener('click', () => this.switchToFeatureView());
        }
        if (this.teamViewBtn) {
            this.teamViewBtn.addEventListener('click', () => this.switchToTeamView());
        }
        if (this.assigneeViewBtn) {
            this.assigneeViewBtn.addEventListener('click', () => this.switchToAssigneeView());
        }

        // Layout toggle event listeners
        if (this.cardViewBtn) {
            this.cardViewBtn.addEventListener('click', () => this.switchToCardView());
        }
        if (this.listViewBtn) {
            this.listViewBtn.addEventListener('click', () => this.switchToListView());
        }

        // Expand/Collapse All buttons
        if (this.expandAllTeamsBtn) {
            this.expandAllTeamsBtn.addEventListener('click', () => this.expandAllTeams());
        }
        if (this.collapseAllTeamsBtn) {
            this.collapseAllTeamsBtn.addEventListener('click', () => this.collapseAllTeams());
        }
        if (this.expandAllAssigneesBtn) {
            this.expandAllAssigneesBtn.addEventListener('click', () => this.expandAllAssignees());
        }
        if (this.collapseAllAssigneesBtn) {
            this.collapseAllAssigneesBtn.addEventListener('click', () => this.collapseAllAssignees());
        }

        // Feature expand/collapse buttons
        if (this.expandAllFeaturesBtn) {
            this.expandAllFeaturesBtn.addEventListener('click', () => this.expandAllFeatures());
        }
        if (this.collapseAllFeaturesBtn) {
            this.collapseAllFeaturesBtn.addEventListener('click', () => this.collapseAllFeatures());
        }

        // Query section toggle
        if (this.queryToggle) {
            this.queryToggle.addEventListener('click', () => this.toggleQuerySection());
        }
        if (this.querySectionHeader) {
            this.querySectionHeader.addEventListener('click', (e) => {
                if (e.target !== this.queryToggle && !this.queryToggle?.contains(e.target)) {
                    this.toggleQuerySection();
                }
            });
        }

        this.downloadReportBtn?.addEventListener('click', () => {
            this.downloadReport();
        });

        this.generateSummaryBtn?.addEventListener('click', () => {
            this.generateSummary();
        });

        this.refreshResultsBtn?.addEventListener('click', () => {
            // Capture currently expanded releases in the DOM
            const expandedReleases = Array.from(document.querySelectorAll('.release-section:not(.collapsed)'))
                .map(sec => sec.querySelector('.release-header h3')?.innerText || '');

            // For tree nodes: find those expanded
            const expandedParents = Array.from(document.querySelectorAll('.tree-node.expanded'))
                .map(node => node.getAttribute('data-parent-key'));
            // Also record last active/expanded child (use a class, e.g. .tree-child-node.active, or store on click)

            this._treeExpansionState = {
                releases: expandedReleases,
                parents: expandedParents,
                // Save last child key if any (see below for binding click)
                childKey: window._lastActiveChildNodeKey || null
            };
            this.runQuery();
        });
    }

    setupFavoriteFilters() {
        if (!this.favoriteFilterSelect) return;

        this.favoriteFilterSelect.addEventListener('change', () => {
            const filter = this.favoriteFilterSelect.value;
            if (!filter) return;

            this.jqlInput.value = filter;
            this.runQuery();
        });
    }

    toggleBucket(bucket) {
        const container = this.bucketContainers[bucket];
        const header = this.bucketHeaders[bucket];
        if (!container || !header) return;

        const isCollapsed = container.classList.toggle('collapsed');
        header.setAttribute('aria-expanded', (!isCollapsed).toString());

        const icon = this.bucketToggleIcons[bucket];
        if (icon) {
            icon.textContent = isCollapsed ? '>' : 'v';
        }
    }

    expandAllTeams() {
        Object.entries(this.bucketContainers).forEach(([bucket, container]) => {
            if (!container) return;
            const header = this.bucketHeaders[bucket];
            const icon = this.bucketToggleIcons[bucket];

            container.classList.remove('collapsed');
            if (header) header.setAttribute('aria-expanded', 'true');
            if (icon) icon.textContent = 'v';
        });
    }

    collapseAllTeams() {
        Object.entries(this.bucketContainers).forEach(([bucket, container]) => {
            if (!container) return;
            const header = this.bucketHeaders[bucket];
            const icon = this.bucketToggleIcons[bucket];

            container.classList.add('collapsed');
            if (header) header.setAttribute('aria-expanded', 'false');
            if (icon) icon.textContent = '>';
        });
    }

    expandAllAssignees() {
        if (!this.assigneeContainer) return;

        const headers = this.assigneeContainer.querySelectorAll('.assignee-header');
        headers.forEach(header => {
            const content = header.nextElementSibling;
            const icon = header.querySelector('.bucket-toggle');

            if (content) content.classList.remove('collapsed');
            header.setAttribute('aria-expanded', 'true');
            if (icon) icon.textContent = 'v';
        });
    }

    collapseAllAssignees() {
        if (!this.assigneeContainer) return;

        const headers = this.assigneeContainer.querySelectorAll('.assignee-header');
        headers.forEach(header => {
            const content = header.nextElementSibling;
            const icon = header.querySelector('.bucket-toggle');

            if (content) content.classList.add('collapsed');
            header.setAttribute('aria-expanded', 'false');
            if (icon) icon.textContent = '>';
        });
    }

    toggleQuerySection() {
        if (!this.querySectionContent || !this.queryToggleIcon) return;

        const isCollapsed = this.querySectionContent.classList.toggle('collapsed');
        this.queryToggleIcon.textContent = isCollapsed ? '>' : 'v';

        // Store preference
        localStorage.setItem('querySectionCollapsed', isCollapsed ? 'true' : 'false');
    }

    restoreQuerySectionState() {
        const isCollapsed = localStorage.getItem('querySectionCollapsed') === 'true';
        if (isCollapsed && this.querySectionContent && this.queryToggleIcon) {
            this.querySectionContent.classList.add('collapsed');
            this.queryToggleIcon.textContent = '>';
        }
    }

    collapseQuerySection() {
        if (!this.querySectionContent || !this.queryToggleIcon) return;

        this.querySectionContent.classList.add('collapsed');
        this.queryToggleIcon.textContent = '>';
        localStorage.setItem('querySectionCollapsed', 'true');
    }

    loadSampleQuery() {
        const sampleQuery = 'project = "YOUR_PROJECT" AND assignee = currentUser() ORDER BY updated DESC';
        this.jqlInput.value = sampleQuery;
        this.jqlInput.select();
    }

    clearQuery() {
        this.jqlInput.value = '';
        if (this.favoriteFilterSelect) {
            this.favoriteFilterSelect.value = '';
        }
        this.hideResults();
        this.hideError();
        this.jqlInput.focus();
    }

    async runQuery() {
        const jql = this.jqlInput.value.trim();
        if (!jql) {
            this.showError('Please enter a JQL query');
            return;
        }

        // Set maxResults to 5000 (Jira API maximum limit)
        const maxResults = 5000;

        const payload = {
            jql,
            maxResults,
            fields: [
                'id',
                'key',
                'summary',
                'status',
                'assignee',
                'priority',
                'updated',
                'created',
                'issuetype',
                'project',
                'parent',
                'fixVersions',
                'timetracking',
                'timeoriginalestimate',
                'timeestimate',
                'timespent',
                'aggregatetimeoriginalestimate',
                'aggregatetimeestimate',
                'aggregatetimespent'
            ]
        };

        this.showLoading();
        this.hideError();
        this.hideResults();

        try {
            const response = await fetch(this.apiEndpoint, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (!response.ok) {
                const details = Array.isArray(data.details) ? data.details.join(', ') : data.error;
                throw new Error(details || 'Unknown error');
            }

            this.displayResults(data);
        } catch (error) {
            console.error('Query error:', error);
            this.showError(`Failed to fetch issues: ${error.message}`);
        } finally {
            this.hideLoading();
        }
    }

    computeBucketCounts(data) {
        return {
            dev: data.bucketCounts?.dev ?? 0,
            qa: data.bucketCounts?.qa ?? 0,
            product: data.bucketCounts?.product ?? 0,
            completed: data.bucketCounts?.completed ?? 0,
            dropped: data.bucketCounts?.dropped ?? 0,
            deployed: data.bucketCounts?.deployed ?? 0,
            other: data.bucketCounts?.other ?? 0
        };
    }

    updateSummary(bucketCounts, data) {
        const totalIssues = typeof data.total === 'number'
            ? data.total
            : (Array.isArray(data.issues)
                ? data.issues.length
                : Object.values(bucketCounts).reduce((sum, count) => sum + count, 0));

        // Animated counter for total issues
        const counterSpan = document.createElement('span');
        counterSpan.className = 'animated-counter';
        counterSpan.textContent = '0';
        this.totalCountSpan.innerHTML = '';
        this.totalCountSpan.appendChild(counterSpan);
        this.totalCountSpan.appendChild(document.createTextNode(` issue${totalIssues !== 1 ? 's' : ''}`));
        this.animateCounter(counterSpan, totalIssues, 800);

        const summaryParts = [];
        if (bucketCounts.dev > 0) summaryParts.push(`${bucketCounts.dev} Dev`);
        if (bucketCounts.qa > 0) summaryParts.push(`${bucketCounts.qa} QA`);
        if (bucketCounts.product > 0) summaryParts.push(`${bucketCounts.product} UAT`);
        if (bucketCounts.completed > 0) summaryParts.push(`${bucketCounts.completed} Completed`);
        if (bucketCounts.dropped > 0) summaryParts.push(`${bucketCounts.dropped} Dropped`);
        if (bucketCounts.deployed > 0) summaryParts.push(`${bucketCounts.deployed} Deployed`);
        if (bucketCounts.other > 0) summaryParts.push(`${bucketCounts.other} Other`);

        this.bucketSummarySpan.textContent = summaryParts.join(' | ');

        Object.keys(this.counts).forEach(bucket => {
            this.counts[bucket].textContent = bucketCounts[bucket] || 0;
        });
    }

    displayResults(data) {
        const bucketCounts = this.computeBucketCounts(data);
        this.updateSummary(bucketCounts, data);

        const allIssues = Array.isArray(data.issues) ? data.issues : [];
        this.parentAggregates = this.buildParentAggregates(allIssues);
        this.renderParentOverview();

        const bucketOrder = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed', 'other'];
        bucketOrder.forEach(bucket => {
            const bucketIssues = (data.buckets && Array.isArray(data.buckets[bucket])) ? data.buckets[bucket] : [];
            const groups = this.groupIssuesByParent(bucketIssues);
            this.renderBucket(bucket, groups);
        });

        this.renderAssigneeView(allIssues);

        this.assigneeGroups = this.groupIssuesByAssignee(allIssues);

        this.applyCurrentView();

        this.showResults();

        // Auto-collapse query section after displaying results
        this.collapseQuerySection();

        // After renderParentOverview (end), restore previously expanded states & optionally scroll
        setTimeout(() => {
            const state = this._treeExpansionState;
            if (!state) return;
            // Restore release sections
            state.releases.forEach(name => {
                const releaseSections = Array.from(document.querySelectorAll('.release-section'));
                releaseSections.forEach(sec => {
                    const h3 = sec.querySelector('.release-header h3');
                    if (h3 && h3.innerText === name && sec.classList.contains('collapsed'))
                        sec.classList.remove('collapsed');
                });
            });
            // Restore tree parent expansions
            state.parents.forEach(key => {
                const node = document.querySelector(`.tree-node[data-parent-key='${key}']`);
                if (node && !node.classList.contains('expanded')) {
                    node.classList.add('expanded');
                    const btn = node.querySelector('.tree-expand-btn');
                    if (btn) btn.innerHTML = '▼';
                }
            });
            // Scroll to last child
            if (state.childKey) {
                const activeChild = document.querySelector(`.tree-child-node span.tree-child-key`);
                if (activeChild && activeChild.innerText === state.childKey) {
                    activeChild.parentElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
                }
            }
            // Clear after restore
            this._treeExpansionState = { releases: [], parents: [], childKey: null };
            window._lastActiveChildNodeKey = null;
        }, 100);
    }

    renderBucket(bucket, groups) {
        const bucketContainer = this.buckets[bucket];
        if (!bucketContainer) {
            return;
        }

        bucketContainer.innerHTML = '';

        if (!Array.isArray(groups) || groups.length === 0) {
            bucketContainer.innerHTML = '<div class=\"empty-bucket\">No issues in this bucket</div>';
            return;
        }

        groups.forEach(group => {
            bucketContainer.appendChild(this.createParentGroup(group));
        });
    }
    buildParentAggregates(issues) {
        const aggregates = new Map();

        issues.forEach(issue => {
            const parentKey = issue.fields?.parent?.key || issue.key;
            const parentSummary = issue.fields?.parent?.fields?.summary
                || issue.fields?.summary
                || parentKey;
            const bucket = issue.bucket || 'other';
            const normalizedBucket = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed'].includes(bucket) ? bucket : 'other';

            // Get fix version from parent or current issue
            const fixVersions = issue.fields?.parent?.fields?.fixVersions || issue.fields?.fixVersions || [];
            const fixVersion = fixVersions.length > 0 ? fixVersions[0].name : null;

            if (!aggregates.has(parentKey)) {
                aggregates.set(parentKey, {
                    parentKey,
                    parentSummary,
                    fixVersion,
                    total: 0,
                    done: 0,
                    bucketCounts: {
                        dev: 0,
                        qa: 0,
                        product: 0,
                        completed: 0,
                        dropped: 0,
                        deployed: 0,
                        other: 0
                    },
                    timeTracking: {
                        originalEstimate: 0,
                        remainingEstimate: 0,
                        timeSpent: 0
                    },
                    issues: []
                });
            }

            const entry = aggregates.get(parentKey);
            // Update fix version if not set yet and current issue has one
            if (!entry.fixVersion && fixVersion) {
                entry.fixVersion = fixVersion;
            }
            entry.total += 1;
            entry.bucketCounts[normalizedBucket] += 1;
            entry.issues.push(issue);

            // Add time tracking data - check multiple field sources
            const timeTracking = issue.fields?.timetracking || {};

            // Access the correct time tracking fields
            const originalEstimate = timeTracking.originalEstimate || 
                                   timeTracking.originalEstimateSeconds || 
                                   issue.fields?.timeoriginalestimate || 0;
            const remainingEstimate = timeTracking.remainingEstimate || 
                                    timeTracking.remainingEstimateSeconds || 
                                    issue.fields?.timeestimate || 0;
            const timeSpent = timeTracking.timeSpent || 
                            timeTracking.timeSpentSeconds || 
                            issue.fields?.timespent || 0;

            // Debug logging for first few issues with time data
            if ((originalEstimate || remainingEstimate || timeSpent) && entry.total <= 3) {
                console.log(`Issue ${issue.key} time values:`, {
                    originalEstimate,
                    remainingEstimate,
                    timeSpent,
                    types: {
                        original: typeof originalEstimate,
                        remaining: typeof remainingEstimate,
                        spent: typeof timeSpent
                    }
                });
            }

            entry.timeTracking.originalEstimate += originalEstimate;
            entry.timeTracking.remainingEstimate += remainingEstimate;
            entry.timeTracking.timeSpent += timeSpent;

            if (normalizedBucket !== 'dev' && normalizedBucket !== 'qa') {
                entry.done += 1;
            }
        });

        aggregates.forEach(entry => {
            entry.progress = entry.total === 0
                ? 100
                : Math.round((entry.done / entry.total) * 100);
        });

        return aggregates;
    }

    groupIssuesByParent(bucketIssues) {
        const groups = new Map();

        bucketIssues.forEach(issue => {
            const parentKey = issue.fields?.parent?.key || issue.key;
            let group = groups.get(parentKey);

            if (!group) {
                const aggregate = this.parentAggregates.get(parentKey);
                group = {
                    parentKey,
                    parentSummary: aggregate?.parentSummary || issue.fields?.summary || parentKey,
                    progress: aggregate?.progress ?? 100,
                    issues: []
                };
                groups.set(parentKey, group);
            }

            group.issues.push(issue);
        });

        return Array.from(groups.values()).sort((a, b) => a.parentKey.localeCompare(b.parentKey));
    }

    renderParentOverview() {
        if (!this.parentOverviewContainer) {
            return;
        }

        const container = this.parentOverviewContainer;
        container.innerHTML = '';

        // Filter to only show top-level parents (epics/features), not stories with sub-tasks
        const parents = Array.from(this.parentAggregates.values())
            .filter(parent => {
                // Check if this parent is actually a child of another parent
                // If it has a parent field pointing to a different issue, it's a story, not an epic
                const parentIssue = parent.issues.find(issue => issue.key === parent.parentKey);
                const hasParent = parentIssue?.fields?.parent?.key &&
                    parentIssue.fields.parent.key !== parent.parentKey;
                return !hasParent; // Only include if it doesn't have a parent (i.e., it's a top-level epic)
            })
            .sort((a, b) => a.parentKey.localeCompare(b.parentKey));

        if (parents.length === 0) {
            container.innerHTML = '<div class="parent-overview-empty">No parent issues found for this query.</div>';
            return;
        }

        // Group parents by release
        const releaseGroups = new Map();
        parents.forEach(parent => {
            const release = parent.fixVersion || 'No Release';
            if (!releaseGroups.has(release)) {
                releaseGroups.set(release, []);
            }
            releaseGroups.get(release).push(parent);
        });

        // Sort releases (No Release last)
        let sortedReleases = Array.from(releaseGroups.keys()).sort((a, b) => {
            if (a === 'No Release') return 1;
            if (b === 'No Release') return -1;
            return a.localeCompare(b);
        });

        // Filter out "No Release" if there are actual releases (user is filtering by release)
        const hasActualReleases = sortedReleases.some(r => r !== 'No Release');
        if (hasActualReleases) {
            sortedReleases = sortedReleases.filter(r => r !== 'No Release');
        }

        // Render each release section
        sortedReleases.forEach(release => {
            const releaseSection = document.createElement('div');
            releaseSection.className = 'release-section';

            // Create release header (clickable to toggle)
            const releaseHeader = document.createElement('div');
            releaseHeader.className = 'release-header';

            const releaseTitle = document.createElement('h3');
            releaseTitle.innerHTML = release === 'No Release'
                ? '<span class="release-collapse-icon">▼</span> No Release Assigned'
                : `<span class="release-collapse-icon">▼</span> ${release}`;

            const releaseCount = document.createElement('span');
            releaseCount.className = 'release-count';
            releaseCount.textContent = `${releaseGroups.get(release).length} features`;

            releaseHeader.appendChild(releaseTitle);
            releaseHeader.appendChild(releaseCount);

            // Make header clickable for collapse/expand
            releaseHeader.style.cursor = 'pointer';
            releaseHeader.addEventListener('click', () => {
                releaseSection.classList.toggle('collapsed');
                const collapseIcon = releaseTitle.querySelector('.release-collapse-icon');
                if (collapseIcon) {
                    collapseIcon.textContent = releaseSection.classList.contains('collapsed') ? '▶' : '▼';
                }
            });

            releaseSection.appendChild(releaseHeader);

            // Create appropriate view based on current layout
            if (this.currentLayout === 'list') {
                const treeContainer = document.createElement('div');
                treeContainer.className = 'release-tree-container';

                // Render tree nodes for this release
                releaseGroups.get(release).forEach(parent => {
                    const treeNode = this.createTreeNode(parent);
                    treeContainer.appendChild(treeNode);
                });

                releaseSection.appendChild(treeContainer);
            } else {
                const cardsGrid = document.createElement('div');
                cardsGrid.className = 'release-cards-grid';

                // Render cards for this release
                releaseGroups.get(release).forEach(parent => {
                    const card = this.createFeatureCard(parent);
                    cardsGrid.appendChild(card);
                });

                releaseSection.appendChild(cardsGrid);
            }
            container.appendChild(releaseSection);
        });
    }

    createFeatureCard(parent) {
        const card = document.createElement('div');
        card.className = 'parent-overview-card';

        // Add achievement badge for 100% completion
        const completedPercentage = parent.total > 0 
            ? Math.round(((parent.bucketCounts?.completed || 0) + (parent.bucketCounts?.deployed || 0)) / parent.total * 100)
            : 0;
        
        if (completedPercentage === 100) {
            const achievementBadge = document.createElement('div');
            achievementBadge.className = 'achievement-badge';
            achievementBadge.innerHTML = '🏆';
            achievementBadge.title = 'All issues completed!';
            card.appendChild(achievementBadge);
        }

        const header = document.createElement('div');
        header.className = 'parent-header';

        const topRow = document.createElement('div');
        topRow.className = 'parent-header-top';

        const keyEl = document.createElement('span');
        keyEl.className = 'parent-key';
        keyEl.textContent = parent.parentKey;
        topRow.appendChild(keyEl);

        // Add priority badge if available
        if (parent.priority) {
            const priorityBadge = this.createPriorityBadge(parent.priority);
            topRow.appendChild(priorityBadge);
        }

        header.appendChild(topRow);

        const summaryContainer = document.createElement('div');
        summaryContainer.className = 'feature-summary';

        const summaryButton = document.createElement('div');
        summaryButton.className = 'feature-summary-trigger';
        summaryButton.textContent = parent.parentSummary;
        summaryButton.title = parent.parentSummary; // Add tooltip for long titles

        summaryContainer.appendChild(summaryButton);
        header.appendChild(summaryContainer);

        // Add time tracking section
        const timeTrackingSection = document.createElement('div');
        timeTrackingSection.className = 'time-tracking-section';

        const originalEst = parent.timeTracking?.originalEstimate || 0;
        const timeSpent = parent.timeTracking?.timeSpent || 0;
        const remaining = parent.timeTracking?.remainingEstimate || 0;

        // Convert to seconds for calculations
        const originalSeconds = this.parseTimeToSeconds(originalEst);
        const spentSeconds = this.parseTimeToSeconds(timeSpent);
        const remainingSeconds = this.parseTimeToSeconds(remaining);

        // Determine color coding - red if remaining > (original - spent)
        const expectedRemainingSeconds = Math.max(0, originalSeconds - spentSeconds);
        const isOverBudget = remainingSeconds > expectedRemainingSeconds && originalSeconds > 0;
        const timeTrackingClass = isOverBudget ? 'time-over-estimate' : 'time-within-estimate';

        // Debug logging
        console.log(`Feature ${parent.parentKey} time tracking:`, {
            originalEst,
            timeSpent,
            remaining,
            originalSeconds,
            spentSeconds,
            remainingSeconds,
            expectedRemainingSeconds,
            isOverBudget,
            timeTrackingClass,
            condition: `${remainingSeconds} > ${expectedRemainingSeconds} && ${originalSeconds} > 0 = ${remainingSeconds > expectedRemainingSeconds && originalSeconds > 0}`
        });

        timeTrackingSection.innerHTML = `
            <div class="time-tracking-row ${timeTrackingClass}">
                <div class="time-item">
                    <span class="time-label">Est:</span>
                    <span class="time-value">${this.formatTime(originalEst)}</span>
                </div>
                <div class="time-item">
                    <span class="time-label">Spent:</span>
                    <span class="time-value">${this.formatTime(timeSpent)}</span>
                </div>
                <div class="time-item">
                    <span class="time-label">Rem:</span>
                    <span class="time-value">${this.formatTime(remaining)}</span>
                </div>
            </div>
        `;

        header.appendChild(timeTrackingSection);
        card.appendChild(header);

        // Make the entire card clickable
        card.addEventListener('click', () => this.openFeatureModal(parent));
        card.style.cursor = 'pointer';

        // Add team distribution section (at bottom)
        const progressSection = document.createElement('div');
        progressSection.className = 'feature-progress-section';

        // Create single horizontal progress bar
        const progressBar = document.createElement('div');
        progressBar.className = 'team-progress-bar';

        // Calculate team distribution percentages
        const total = parent.total;
        const teamOrder = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed', 'other'];
        const teamLabels = { dev: 'Dev', qa: 'QA', product: 'UAT', completed: 'Completed', dropped: 'Dropped', deployed: 'Deployed', other: 'Other' };
        const teamColors = { dev: '#2563eb', qa: '#059669', product: '#7c3aed', completed: '#10b981', dropped: '#ef4444', deployed: '#8b5cf6', other: '#6b7280' };

        // Create progress track
        const progressTrack = document.createElement('div');
        progressTrack.className = 'progress-track';

        let currentPosition = 0;
        teamOrder.forEach(bucket => {
            const count = parent.bucketCounts?.[bucket] ?? 0;
            if (count > 0) {
                const percentage = Math.round((count / total) * 100);
                const progressSegment = document.createElement('div');
                progressSegment.className = `progress-segment progress-${bucket}`;
                progressSegment.style.width = `${percentage}%`;
                progressSegment.style.backgroundColor = teamColors[bucket];
                progressSegment.title = `${teamLabels[bucket]}: ${count} (${percentage}%)`;
                progressTrack.appendChild(progressSegment);
            }
        });

        progressBar.appendChild(progressTrack);

        // Add percentage labels below the bar
        const labelsContainer = document.createElement('div');
        labelsContainer.className = 'progress-labels';

        teamOrder.forEach(bucket => {
            const count = parent.bucketCounts?.[bucket] ?? 0;
            if (count > 0) {
                const percentage = Math.round((count / total) * 100);
                const label = document.createElement('span');
                label.className = `progress-label progress-label-${bucket}`;
                label.style.color = teamColors[bucket];
                label.textContent = `${teamLabels[bucket]} ${percentage}%`;
                labelsContainer.appendChild(label);
            }
        });

        progressBar.appendChild(labelsContainer);
        progressSection.appendChild(progressBar);

        card.appendChild(progressSection);

        // Add stats section with colored badges (Total at very bottom, just above distribution)
        const stats = document.createElement('div');
        stats.className = 'parent-overview-stats';

        const totalStat = document.createElement('span');
        totalStat.className = 'stat stat-total';
        totalStat.innerHTML = `<span class="stat-icon">📊</span> ${parent.total} Total`;
        stats.appendChild(totalStat);

        card.appendChild(stats);
        return card;
    }

    createTreeNode(parent) {
        const treeNode = document.createElement('div');
        treeNode.className = 'tree-node';
        treeNode.setAttribute('data-parent-key', parent.parentKey);

        // Create parent node
        const parentNode = document.createElement('div');
        parentNode.className = 'tree-parent-node';

        // Expand/collapse button
        const expandButton = document.createElement('button');
        expandButton.className = 'tree-expand-btn';
        expandButton.innerHTML = '▶';
        expandButton.addEventListener('click', (e) => {
            e.stopPropagation();
            const isExpanded = treeNode.classList.contains('expanded');
            treeNode.classList.toggle('expanded');
            expandButton.innerHTML = isExpanded ? '▶' : '▼';
        });

        // Parent info
        const parentInfo = document.createElement('div');
        parentInfo.className = 'tree-parent-info';

        const parentKey = document.createElement('span');
        parentKey.className = 'tree-parent-key';
        parentKey.textContent = parent.parentKey;

        const parentSummary = document.createElement('span');
        parentSummary.className = 'tree-parent-summary';
        parentSummary.textContent = parent.parentSummary;

        // Create metrics container for totals and time tracking
        const metricsContainer = document.createElement('div');
        metricsContainer.className = 'tree-parent-metrics';

        // TOTALS SECTION
        const totalsSection = document.createElement('div');
        totalsSection.className = 'tree-parent-totals';

        // Total count with label
        const totalHeader = document.createElement('span');
        totalHeader.className = 'totals-header';
        totalHeader.textContent = 'Total:';

        const totalCount = document.createElement('span');
        totalCount.className = 'total-count';
        totalCount.textContent = parent.total;

        totalsSection.appendChild(totalHeader);
        totalsSection.appendChild(totalCount);

        // Team distribution breakdown
        const teamOrder = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed', 'other'];
        const teamLabels = { dev: 'Dev', qa: 'QA', product: 'UAT', completed: 'Completed', dropped: 'Dropped', deployed: 'Deployed', other: 'Other' };
        const teamColors = { dev: '#2563eb', qa: '#059669', product: '#7c3aed', completed: '#10b981', dropped: '#ef4444', deployed: '#8b5cf6', other: '#6b7280' };

        const breakdownContainer = document.createElement('div');
        breakdownContainer.className = 'totals-breakdown';

        teamOrder.forEach(bucket => {
            const count = parent.bucketCounts?.[bucket] ?? 0;
            if (count > 0) {
                const stat = document.createElement('span');
                stat.className = `breakdown-item breakdown-${bucket}`;
                stat.style.background = teamColors[bucket] + '15';
                stat.style.color = teamColors[bucket];
                stat.style.borderColor = teamColors[bucket] + '40';
                stat.textContent = `${teamLabels[bucket]} ${count}`;
                breakdownContainer.appendChild(stat);
            }
        });

        totalsSection.appendChild(breakdownContainer);

        // TIME TRACKING SECTION
        const timeSection = document.createElement('div');
        timeSection.className = 'tree-parent-time-section';

        const originalEst = parent.timeTracking?.originalEstimate || 0;
        const timeSpent = parent.timeTracking?.timeSpent || 0;
        const remaining = parent.timeTracking?.remainingEstimate || 0;

        // Check if we have any time data
        const hasTimeData = originalEst || timeSpent || remaining;
        
        if (hasTimeData) {
            const originalSeconds = this.parseTimeToSeconds(originalEst);
            const spentSeconds = this.parseTimeToSeconds(timeSpent);
            const remainingSeconds = this.parseTimeToSeconds(remaining);
            const expectedRemainingSeconds = Math.max(0, originalSeconds - spentSeconds);
            const isOverBudget = remainingSeconds > expectedRemainingSeconds && originalSeconds > 0;
            
            const timeHeader = document.createElement('span');
            timeHeader.className = 'time-header';
            timeHeader.textContent = 'Time:';

            const timeData = document.createElement('div');
            timeData.className = `time-data ${isOverBudget ? 'time-over' : 'time-within'}`;
            
            timeData.innerHTML = `
                <span class="time-item time-est">
                    <span class="time-label">Est:</span>
                    <span class="time-value">${this.formatTime(originalEst)}</span>
                </span>
                <span class="time-item time-spent">
                    <span class="time-label">Spent:</span>
                    <span class="time-value">${this.formatTime(timeSpent)}</span>
                </span>
                <span class="time-item time-rem">
                    <span class="time-label">Rem:</span>
                    <span class="time-value">${this.formatTime(remaining)}</span>
                </span>
            `;

            timeSection.appendChild(timeHeader);
            timeSection.appendChild(timeData);
        } else {
            const timeHeader = document.createElement('span');
            timeHeader.className = 'time-header';
            timeHeader.textContent = 'Time:';

            const noTimeData = document.createElement('span');
            noTimeData.className = 'no-time-data';
            noTimeData.textContent = 'No time data';

            timeSection.appendChild(timeHeader);
            timeSection.appendChild(noTimeData);
        }

        // Assemble the metrics container
        metricsContainer.appendChild(totalsSection);
        metricsContainer.appendChild(timeSection);

        parentInfo.appendChild(parentKey);
        parentInfo.appendChild(parentSummary);
        parentInfo.appendChild(metricsContainer);

        parentNode.appendChild(expandButton);
        parentNode.appendChild(parentInfo);

        // Make parent node clickable
        parentNode.addEventListener('click', () => this.openFeatureModal(parent));
        parentNode.style.cursor = 'pointer';

        // Create children container (under parent)
        const childrenContainer = document.createElement('div');
        childrenContainer.className = 'tree-children-container';
        // Group child issues by bucket (team) - creating proper hierarchy
        const allChildren = this.getChildIssuesForParent(parent.parentKey);
        const bucketGroup = Object.fromEntries(teamOrder.map(b => [b, { stories: [], subtasks: [] }]));

        // Separate stories and sub-tasks, and group sub-tasks under their parent stories
        const storySubtaskMap = new Map(); // Map story key to its sub-tasks

        // First pass: collect all stories and initialize the map
        allChildren.forEach(issue => {
            const isSubtask = issue.fields?.issuetype?.subtask === true ||
                issue.fields?.issuetype?.name === 'Sub-task' ||
                issue.fields?.issuetype?.name?.toLowerCase().includes('sub-task') ||
                issue.fields?.issuetype?.name?.toLowerCase().includes('subtask');

            if (!isSubtask) {
                const bucket = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed', 'other'].includes(issue.bucket) ? issue.bucket : 'other';
                bucketGroup[bucket].stories.push(issue);
                // Initialize empty array for this story's sub-tasks
                storySubtaskMap.set(issue.key, []);

                // Debug specific story
                if (issue.key === 'IRA-69405') {
                    console.log(`Found story IRA-69405 in epic ${parent.parentKey}, parent field: ${issue.fields?.parent?.key}`);
                }
            }
        });

        // Second pass: assign sub-tasks to their parent stories
        allChildren.forEach(issue => {
            const isSubtask = issue.fields?.issuetype?.subtask === true ||
                issue.fields?.issuetype?.name === 'Sub-task' ||
                issue.fields?.issuetype?.name?.toLowerCase().includes('sub-task') ||
                issue.fields?.issuetype?.name?.toLowerCase().includes('subtask');

            if (isSubtask) {
                const parentStoryKey = issue.fields?.parent?.key;
                const bucket = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed', 'other'].includes(issue.bucket) ? issue.bucket : 'other';

                // Debug specific sub-tasks
                if (['IRA-69417', 'IRA-69418', 'IRA-69866'].includes(issue.key)) {
                    console.log(`Sub-task ${issue.key} in epic ${parent.parentKey}: parent=${parentStoryKey}, storyExists=${storySubtaskMap.has(parentStoryKey)}, available stories:`, Array.from(storySubtaskMap.keys()));
                }

                // Check if this sub-task belongs to one of our stories OR directly to this parent
                if (parentStoryKey && (storySubtaskMap.has(parentStoryKey) || parentStoryKey === parent.parentKey)) {
                    if (parentStoryKey === parent.parentKey) {
                        // Sub-task directly under this parent (which might be a story, not an epic)
                        bucketGroup[bucket].subtasks.push(issue);
                        console.log(`✓ Sub-task ${issue.key} directly under parent ${parent.parentKey}`);
                    } else {
                        // Sub-task belongs to a story in this epic
                        storySubtaskMap.get(parentStoryKey).push(issue);
                        console.log(`✓ Sub-task ${issue.key} assigned to story ${parentStoryKey}`);
                    }
                } else {
                    // Sub-task orphaned
                    bucketGroup[bucket].subtasks.push(issue);

                    if (['IRA-69417', 'IRA-69418', 'IRA-69866'].includes(issue.key)) {
                        console.log(`✗ Sub-task ${issue.key} orphaned (parent: ${parentStoryKey})`);
                    }
                }
            }
        });

        // Debug: Check if IRA-69405 has sub-tasks
        if (storySubtaskMap.has('IRA-69405')) {
            const subtasks = storySubtaskMap.get('IRA-69405');
            console.log(`IRA-69405 has ${subtasks.length} sub-tasks:`, subtasks.map(st => st.key));
        }
        let bucketHasAny = false;
        teamOrder.forEach(bucket => {
            const bucketData = bucketGroup[bucket];
            const totalIssues = bucketData.stories.length + bucketData.subtasks.length;
            if (totalIssues === 0) return;

            bucketHasAny = true;
            // Create team bucket expandable node
            const bucketNode = document.createElement('div');
            bucketNode.className = 'tree-bucket-node';
            // Expand/collapse control
            const expBtn = document.createElement('button');
            expBtn.className = 'tree-expand-btn bucket-expand-btn';
            expBtn.type = 'button';
            expBtn.innerHTML = '▼';
            expBtn.setAttribute('aria-label', `Toggle ${teamLabels[bucket]}`);
            bucketNode.classList.add('expanded'); // expanded by default
            expBtn.addEventListener('click', e => {
                e.stopPropagation();
                const isExp = bucketNode.classList.contains('expanded');
                bucketNode.classList.toggle('expanded');
                expBtn.innerHTML = isExp ? '▶' : '▼';
            });
            // Team badge
            const badge = document.createElement('span');
            badge.className = `tree-bucket-label tree-stat-${bucket}`;
            badge.textContent = `${teamLabels[bucket]} (${totalIssues})`;
            badge.style.background = teamColors[bucket] + '22';
            badge.style.color = teamColors[bucket];

            // Header row for bucket
            const bucketHeader = document.createElement('div');
            bucketHeader.className = 'tree-bucket-header';
            bucketHeader.appendChild(expBtn);
            bucketHeader.appendChild(badge);
            bucketNode.appendChild(bucketHeader);

            // Bucket issues list
            const bucketList = document.createElement('div');
            bucketList.className = 'tree-bucket-list';
            // Render stories first
            bucketData.stories.forEach(story => {
                const storyNode = this.createStoryNode(story, storySubtaskMap);
                bucketList.appendChild(storyNode);
            });

            // Render direct sub-tasks (sub-tasks directly under epic, not under stories)
            bucketData.subtasks.forEach(subtask => {
                const subtaskNode = this.createSubtaskNode(subtask);
                bucketList.appendChild(subtaskNode);
            });
            bucketNode.appendChild(bucketList);
            childrenContainer.appendChild(bucketNode);
        });
        if (!bucketHasAny) {
            const noChildrenMsg = document.createElement('div');
            noChildrenMsg.className = 'tree-no-children';
            noChildrenMsg.textContent = 'No child issues found';
            childrenContainer.appendChild(noChildrenMsg);
        }
        treeNode.appendChild(parentNode);
        treeNode.appendChild(childrenContainer);

        return treeNode;
    }

    createStoryNode(story, storySubtaskMap) {
        const storyContainer = document.createElement('div');
        storyContainer.className = 'tree-story-container';

        // Create the story node
        const storyNode = document.createElement('div');
        storyNode.className = 'tree-child-node tree-story-node';

        // Check if this story has sub-tasks
        const subtasks = storySubtaskMap.get(story.key) || [];
        const hasSubtasks = subtasks.length > 0;



        // Expand/collapse button for stories with sub-tasks
        if (hasSubtasks) {
            const expandBtn = document.createElement('button');
            expandBtn.className = 'tree-expand-btn story-expand-btn';
            expandBtn.innerHTML = '▶'; // Start with collapsed icon
            expandBtn.addEventListener('click', e => {
                e.stopPropagation();
                const isExpanded = storyContainer.classList.contains('expanded');
                storyContainer.classList.toggle('expanded');
                expandBtn.innerHTML = isExpanded ? '▶' : '▼';
            });
            storyNode.appendChild(expandBtn);
            // Start collapsed by default
            // storyContainer.classList.add('expanded');
        } else {
            // Add spacing for stories without sub-tasks
            const spacer = document.createElement('span');
            spacer.className = 'tree-spacer';
            spacer.textContent = '  ';
            storyNode.appendChild(spacer);
        }

        // Issue type indicator
        const typeIndicator = document.createElement('span');
        typeIndicator.className = 'tree-child-type';
        typeIndicator.textContent = '├─';
        typeIndicator.title = 'Story/Task';

        // Key
        const storyKey = document.createElement('span');
        storyKey.className = 'tree-child-key';
        storyKey.textContent = story.key;

        // Summary
        const storySummary = document.createElement('span');
        storySummary.className = 'tree-child-summary';
        storySummary.textContent = story.fields?.summary || 'No summary';

        // Issue type badge
        const issueType = document.createElement('span');
        issueType.className = 'tree-child-issue-type story';
        issueType.textContent = story.fields?.issuetype?.name || 'Story';

        // Sub-task count badge
        if (hasSubtasks) {
            const subtaskCount = document.createElement('span');
            subtaskCount.className = 'tree-subtask-count';
            subtaskCount.textContent = `${subtasks.length} subtask${subtasks.length !== 1 ? 's' : ''}`;
            issueType.appendChild(subtaskCount);
        }

        // Time tracking - check multiple field sources
        const timeTracking = story.fields?.timetracking || {};

        const originalEstimate = timeTracking.originalEstimate || 
                               timeTracking.originalEstimateSeconds || 
                               story.fields?.timeoriginalestimate || 0;
        const timeSpent = timeTracking.timeSpent || 
                        timeTracking.timeSpentSeconds || 
                        story.fields?.timespent || 0;
        const remaining = timeTracking.remainingEstimate || 
                        timeTracking.remainingEstimateSeconds || 
                        story.fields?.timeestimate || 0;

        const timeTrackingSpan = document.createElement('span');
        timeTrackingSpan.className = 'tree-child-time';

        // Check if we have any time data (strings or numbers)
        const hasTimeData = originalEstimate || timeSpent || remaining;
        
        if (hasTimeData) {
            const originalSeconds = this.parseTimeToSeconds(originalEstimate);
            const spentSeconds = this.parseTimeToSeconds(timeSpent);
            const remainingSeconds = this.parseTimeToSeconds(remaining);
            const expectedRemainingSeconds = Math.max(0, originalSeconds - spentSeconds);
            const isOverBudget = remainingSeconds > expectedRemainingSeconds && originalSeconds > 0;
            timeTrackingSpan.className += isOverBudget ? ' time-over' : ' time-within';
            timeTrackingSpan.innerHTML = `
                <span class="time-est">${this.formatTime(originalEstimate)}</span>
                <span class="time-spent">${this.formatTime(timeSpent)}</span>
                <span class="time-rem">${this.formatTime(remaining)}</span>
            `;
        } else {
            timeTrackingSpan.textContent = 'No time data';
            timeTrackingSpan.className += ' no-time';
        }

        // Status
        const storyStatus = document.createElement('span');
        let statusName = story.fields?.status?.name?.toLowerCase() || 'unknown';
        storyStatus.className = `tree-child-status tree-child-status-${statusName.replace(/\s+/g, '-')}`;
        storyStatus.textContent = story.fields?.status?.name || 'Unknown';

        // Click handler
        storyNode.addEventListener('click', e => {
            e.stopPropagation();
            window._lastActiveChildNodeKey = story.key;
            window.open(`${this.jiraBaseUrl}/browse/${story.key}`, '_blank');
        });
        storyNode.style.cursor = 'pointer';

        // Compose story row
        storyNode.appendChild(typeIndicator);
        storyNode.appendChild(storyKey);
        storyNode.appendChild(storySummary);
        storyNode.appendChild(issueType);
        storyNode.appendChild(timeTrackingSpan);
        storyNode.appendChild(storyStatus);

        storyContainer.appendChild(storyNode);

        // Add sub-tasks container
        if (hasSubtasks) {
            const subtasksContainer = document.createElement('div');
            subtasksContainer.className = 'tree-subtasks-container';

            subtasks.forEach((subtask) => {
                const subtaskNode = this.createSubtaskNode(subtask);
                subtasksContainer.appendChild(subtaskNode);
            });

            storyContainer.appendChild(subtasksContainer);
        }

        return storyContainer;
    }

    createSubtaskNode(subtask) {
        const subtaskNode = document.createElement('div');
        subtaskNode.className = 'tree-child-node tree-subtask-node';

        // Issue type indicator
        const typeIndicator = document.createElement('span');
        typeIndicator.className = 'tree-child-type';
        typeIndicator.textContent = '└─';
        typeIndicator.title = 'Sub-task';

        // Key
        const subtaskKey = document.createElement('span');
        subtaskKey.className = 'tree-child-key';
        subtaskKey.textContent = subtask.key;

        // Summary
        const subtaskSummary = document.createElement('span');
        subtaskSummary.className = 'tree-child-summary';
        subtaskSummary.textContent = subtask.fields?.summary || 'No summary';

        // Issue type badge
        const issueType = document.createElement('span');
        issueType.className = 'tree-child-issue-type subtask';
        issueType.textContent = subtask.fields?.issuetype?.name || 'Sub-task';

        // Time tracking - check multiple field sources
        const timeTracking = subtask.fields?.timetracking || {};

        const originalEstimate = timeTracking.originalEstimate || 
                               timeTracking.originalEstimateSeconds || 
                               subtask.fields?.timeoriginalestimate || 0;
        const timeSpent = timeTracking.timeSpent || 
                        timeTracking.timeSpentSeconds || 
                        subtask.fields?.timespent || 0;
        const remaining = timeTracking.remainingEstimate || 
                        timeTracking.remainingEstimateSeconds || 
                        subtask.fields?.timeestimate || 0;

        const timeTrackingSpan = document.createElement('span');
        timeTrackingSpan.className = 'tree-child-time';

        // Check if we have any time data (strings or numbers)
        const hasTimeData = originalEstimate || timeSpent || remaining;
        
        if (hasTimeData) {
            const originalSeconds = this.parseTimeToSeconds(originalEstimate);
            const spentSeconds = this.parseTimeToSeconds(timeSpent);
            const remainingSeconds = this.parseTimeToSeconds(remaining);
            const expectedRemainingSeconds = Math.max(0, originalSeconds - spentSeconds);
            const isOverBudget = remainingSeconds > expectedRemainingSeconds && originalSeconds > 0;
            timeTrackingSpan.className += isOverBudget ? ' time-over' : ' time-within';
            timeTrackingSpan.innerHTML = `
                <span class="time-est">${this.formatTime(originalEstimate)}</span>
                <span class="time-spent">${this.formatTime(timeSpent)}</span>
                <span class="time-rem">${this.formatTime(remaining)}</span>
            `;
        } else {
            timeTrackingSpan.textContent = 'No time data';
            timeTrackingSpan.className += ' no-time';
        }

        // Status
        const subtaskStatus = document.createElement('span');
        let statusName = subtask.fields?.status?.name?.toLowerCase() || 'unknown';
        subtaskStatus.className = `tree-child-status tree-child-status-${statusName.replace(/\s+/g, '-')}`;
        subtaskStatus.textContent = subtask.fields?.status?.name || 'Unknown';

        // Click handler
        subtaskNode.addEventListener('click', e => {
            e.stopPropagation();
            window._lastActiveChildNodeKey = subtask.key;
            window.open(`${this.jiraBaseUrl}/browse/${subtask.key}`, '_blank');
        });
        subtaskNode.style.cursor = 'pointer';

        // Compose subtask row
        subtaskNode.appendChild(typeIndicator);
        subtaskNode.appendChild(subtaskKey);
        subtaskNode.appendChild(subtaskSummary);
        subtaskNode.appendChild(issueType);
        subtaskNode.appendChild(timeTrackingSpan);
        subtaskNode.appendChild(subtaskStatus);

        return subtaskNode;
    }

    getChildIssuesForParent(parentKey) {
        // Find the parent aggregate and return its child issues and subtasks
        const parent = this.parentAggregates.get(parentKey);
        if (parent && parent.issues) {
            // Get all issues that belong to this parent (epic/feature)
            const childIssues = parent.issues.filter(issue => {
                // Exclude the parent issue itself
                if (issue.key === parentKey) return false;

                // Include direct children (stories/tasks under epic)
                const isDirectChild = issue.fields?.parent?.key === parentKey;

                return isDirectChild;
            });

            // Also get sub-tasks that belong to any of the stories in this epic
            // We need to look across ALL aggregates because sub-tasks might be in their own aggregate
            const allSubtasks = [];
            const storyKeys = childIssues.map(child => child.key);

            // Look through all parent aggregates to find sub-tasks of our stories
            this.parentAggregates.forEach((aggregate, aggregateKey) => {
                // Check if this aggregate represents a story in our epic
                if (storyKeys.includes(aggregateKey)) {
                    // This aggregate is for one of our stories, get its sub-tasks
                    aggregate.issues.forEach(issue => {
                        const isSubtask = issue.fields?.issuetype?.subtask === true ||
                            issue.fields?.issuetype?.name === 'Sub-task' ||
                            issue.fields?.issuetype?.name?.toLowerCase().includes('sub-task') ||
                            issue.fields?.issuetype?.name?.toLowerCase().includes('subtask');

                        if (isSubtask && issue.fields?.parent?.key === aggregateKey) {
                            allSubtasks.push(issue);
                        }
                    });
                }
            });

            // Combine stories and sub-tasks
            return [...childIssues, ...allSubtasks];
        }
        return [];
    }

    createParentGroup(group) {
        const card = document.createElement('div');
        card.className = 'parent-group-card';

        const header = document.createElement('div');
        header.className = 'group-header';

        const headerMain = document.createElement('div');
        headerMain.className = 'group-header-main';

        // Create clickable feature summary button (same as in feature overview)
        const summaryButton = document.createElement('button');
        summaryButton.type = 'button';
        summaryButton.className = 'group-summary-trigger';
        summaryButton.textContent = group.parentSummary;

        // Get the parent aggregate data for the modal
        const parentAggregate = this.parentAggregates.get(group.parentKey);
        if (parentAggregate) {
            summaryButton.addEventListener('click', () => this.openFeatureModal(parentAggregate));
        }

        const keySpan = document.createElement('span');
        keySpan.className = 'group-key';
        keySpan.textContent = group.parentKey;

        // Add total count for this feature in this bucket
        const totalSpan = document.createElement('span');
        totalSpan.className = 'group-total';
        totalSpan.textContent = `${group.issues.length} total`;

        headerMain.append(summaryButton, keySpan, totalSpan);
        header.appendChild(headerMain);

        const progressMeter = this.createProgressMeter(group.progress, { compact: true });
        header.appendChild(progressMeter);

        card.appendChild(header);

        return card;
    }

    renderAssigneeView(issues) {
        if (!this.assigneeContainer) {
            return;
        }

        const container = this.assigneeContainer;
        container.innerHTML = '';

        const groups = this.groupIssuesByAssignee(issues);
        if (!Array.isArray(groups) || groups.length === 0) {
            container.innerHTML = '<div class="assignee-empty">No issues assigned.</div>';
            return;
        }

        groups.forEach(group => {
            container.appendChild(this.createAssigneeGroup(group));
        });
    }

    groupIssuesByAssignee(issues) {
        const groups = new Map();

        issues.forEach(issue => {
            const assignee = issue.fields?.assignee;
            const identifier = assignee?.accountId || assignee?.name || assignee?.emailAddress || 'unassigned';
            const displayName = assignee?.displayName || assignee?.name || assignee?.emailAddress || 'Unassigned';

            if (!groups.has(identifier)) {
                groups.set(identifier, {
                    key: identifier,
                    displayName,
                    issues: [],
                    parentGroups: new Map(),
                    bucketCounts: {
                        dev: 0,
                        qa: 0,
                        product: 0,
                        other: 0
                    }
                });
            }

            const entry = groups.get(identifier);
            const bucket = issue.bucket || 'other';
            const normalizedBucket = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed'].includes(bucket) ? bucket : 'other';
            entry.bucketCounts[normalizedBucket] += 1;
            entry.issues.push(issue);

            // Group issues by parent within assignee
            const parentKey = issue.fields?.parent?.key || issue.key;
            if (!entry.parentGroups.has(parentKey)) {
                entry.parentGroups.set(parentKey, {
                    parentKey,
                    parentSummary: issue.fields?.parent?.fields?.summary || issue.fields?.summary || parentKey,
                    progress: 100, // Default progress for individual issues
                    issues: []
                });
            }
            entry.parentGroups.get(parentKey).issues.push(issue);
        });

        return Array.from(groups.values()).sort((a, b) => a.displayName.localeCompare(b.displayName));
    }

    createAssigneeGroup(group) {
        const card = document.createElement('div');
        card.className = 'assignee-group-card';

        // Create collapsible header similar to bucket headers
        const header = document.createElement('div');
        header.className = 'assignee-header bucket-header-collapsible';
        header.setAttribute('role', 'button');
        header.setAttribute('tabindex', '0');
        header.setAttribute('aria-expanded', 'false');

        const icon = document.createElement('span');
        icon.className = 'bucket-toggle';
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = '>';
        header.insertBefore(icon, header.firstChild);

        const info = document.createElement('div');
        info.className = 'assignee-info';

        const name = document.createElement('span');
        name.className = 'assignee-name';
        name.textContent = group.displayName;

        info.appendChild(name);

        const count = document.createElement('span');
        count.className = 'assignee-count';
        const issueCount = group.issues.length;
        count.textContent = `${issueCount} issue${issueCount === 1 ? '' : 's'}`;

        header.append(info, count);

        // Add click handler for collapsing
        header.addEventListener('click', () => this.toggleAssigneeSection(group.key, header, icon));
        header.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                this.toggleAssigneeSection(group.key, header, icon);
            }
        });

        card.appendChild(header);

        // Create content container (collapsed by default)
        const content = document.createElement('div');
        content.className = 'assignee-content collapsed';

        // Create parent groups within assignee
        const parentGroups = Array.from(group.parentGroups.values()).sort((a, b) => a.parentKey.localeCompare(b.parentKey));

        parentGroups.forEach(parentGroup => {
            content.appendChild(this.createAssigneeParentGroup(parentGroup, group.key));
        });

        card.appendChild(content);

        return card;
    }

    toggleAssigneeSection(assigneeKey, header, icon) {
        const content = header.nextElementSibling;
        if (!content) return;

        const isCollapsed = content.classList.toggle('collapsed');
        header.setAttribute('aria-expanded', (!isCollapsed).toString());
        icon.textContent = isCollapsed ? '>' : 'v';
    }

    createAssigneeParentGroup(parentGroup, assigneeKey) {
        const card = document.createElement('div');
        card.className = 'assignee-parent-group';

        const header = document.createElement('div');
        header.className = 'assignee-parent-header';

        const headerMain = document.createElement('div');
        headerMain.className = 'assignee-parent-header-main';

        // Create clickable parent summary button
        const summaryButton = document.createElement('button');
        summaryButton.type = 'button';
        summaryButton.className = 'assignee-parent-summary-trigger';
        summaryButton.textContent = parentGroup.parentSummary;

        // Get the parent aggregate data for the modal
        const parentAggregate = this.parentAggregates.get(parentGroup.parentKey);
        if (parentAggregate) {
            summaryButton.addEventListener('click', () => this.openFeatureModal(parentAggregate, assigneeKey));
        } else {
            summaryButton.disabled = true;
            summaryButton.title = 'No aggregate data available for this parent';
        }
        const keySpan = document.createElement('span');
        keySpan.className = 'assignee-parent-key';
        keySpan.textContent = parentGroup.parentKey;

        // Add total count for this parent in this assignee
        const totalSpan = document.createElement('span');
        totalSpan.className = 'assignee-parent-total';
        totalSpan.textContent = `${parentGroup.issues.length} issue${parentGroup.issues.length === 1 ? '' : 's'}`;

        headerMain.append(summaryButton, keySpan, totalSpan);
        header.appendChild(headerMain);

        // Add progress meter if we have aggregate data
        if (parentAggregate) {
            const progressMeter = this.createProgressMeter(parentAggregate.progress, { compact: true });
            header.appendChild(progressMeter);
        }

        card.appendChild(header);

        return card;
    }

    createProgressMeter(value, { compact = false } = {}) {
        const safeValue = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;

        const wrapper = document.createElement('div');
        wrapper.className = 'progress-meter';
        if (compact) {
            wrapper.classList.add('compact');
        }

        const label = document.createElement('span');
        label.className = 'progress-meter-label';
        label.textContent = `Progress ${safeValue}%`;

        const track = document.createElement('div');
        track.className = 'progress-track';

        const fill = document.createElement('div');
        fill.className = 'progress-fill';
        fill.style.width = `${safeValue}%`;

        track.appendChild(fill);
        wrapper.append(label, track);

        return wrapper;
    }

    createParentChildRow(issue) {
        const row = document.createElement('div');
        row.className = 'parent-child-item';

        const summaryLink = document.createElement('a');
        summaryLink.className = 'parent-child-summary';
        summaryLink.href = `${this.jiraBaseUrl}/browse/${issue.key}`;
        summaryLink.target = '_blank';
        summaryLink.rel = 'noopener noreferrer';
        summaryLink.textContent = issue.fields?.summary || issue.key;

        const meta = document.createElement('span');
        meta.className = 'parent-child-meta';
        const statusName = issue.fields?.status?.name || 'Unknown';
        const bucket = issue.bucket || 'other';
        meta.textContent = `${statusName} - ${bucket.toUpperCase()}`;

        row.append(summaryLink, meta);
        return row;
    }

    createIssueTable(issues) {
        const tableContainer = document.createElement('div');
        tableContainer.className = 'issue-table-container';

        const table = document.createElement('table');
        table.className = 'issue-table';

        // Create table header
        const thead = document.createElement('thead');
        thead.innerHTML = `
            <tr>
                <th>Key</th>
                <th>Summary</th>
                <th>Status</th>
                <th>Assignee</th>
                <th>Type</th>
                <th>Time Tracking</th>
            </tr>
        `;
        table.appendChild(thead);

        // Create table body
        const tbody = document.createElement('tbody');

        issues.forEach(issue => {
            const row = document.createElement('tr');
            row.className = 'issue-table-row';

            const jiraUrl = `${this.jiraBaseUrl}/browse/${issue.key}`;
            const assigneeName = issue.fields.assignee ?
                (issue.fields.assignee.displayName || issue.fields.assignee.name) :
                'Unassigned';
            const issueType = issue.fields.issuetype ? issue.fields.issuetype.name : 'Unknown';
            const statusName = issue.fields.status ? issue.fields.status.name : 'Unknown';
            const summary = issue.fields.summary || issue.key;

            // Get time tracking data - check multiple field sources
            const timeTracking = issue.fields?.timetracking || {};
            
            // Try timetracking object first, then fall back to individual fields
            const originalEstimate = timeTracking.originalEstimate || 
                                   timeTracking.originalEstimateSeconds || 
                                   issue.fields?.timeoriginalestimate || 0;
            const timeSpent = timeTracking.timeSpent || 
                            timeTracking.timeSpentSeconds || 
                            issue.fields?.timespent || 0;
            const remaining = timeTracking.remainingEstimate || 
                            timeTracking.remainingEstimateSeconds || 
                            issue.fields?.timeestimate || 0;



            // Calculate if over budget
            const originalSeconds = this.parseTimeToSeconds(originalEstimate);
            const spentSeconds = this.parseTimeToSeconds(timeSpent);
            const remainingSeconds = this.parseTimeToSeconds(remaining);
            const expectedRemainingSeconds = Math.max(0, originalSeconds - spentSeconds);
            const isOverBudget = remainingSeconds > expectedRemainingSeconds && originalSeconds > 0;

            // Create time tracking display
            let timeTrackingDisplay = '';
            if (originalEstimate || timeSpent || remaining) {
                const timeClass = isOverBudget ? 'time-over-budget' : 'time-on-track';
                timeTrackingDisplay = `
                    <div class="issue-time-tracking ${timeClass}">
                        <span class="time-item">E: ${this.formatTime(originalEstimate)}</span>
                        <span class="time-item">S: ${this.formatTime(timeSpent)}</span>
                        <span class="time-item">R: ${this.formatTime(remaining)}</span>
                    </div>
                `;
            } else {
                timeTrackingDisplay = '<span class="no-time-data">No time data</span>';
            }

            row.innerHTML = `
                <td class="issue-table-key">
                    <a href="${jiraUrl}" target="_blank" class="issue-key-link">${this.escapeHtml(issue.key)}</a>
                </td>
                <td class="issue-table-summary" title="${this.escapeHtml(summary)}">
                    <a href="${jiraUrl}" target="_blank" class="issue-summary-link">${this.escapeHtml(summary)}</a>
                </td>
                <td class="issue-table-status">
                    <span class="status-badge">${this.escapeHtml(statusName)}</span>
                </td>
                <td class="issue-table-assignee">${this.escapeHtml(assigneeName)}</td>
                <td class="issue-table-type">${this.escapeHtml(issueType)}</td>
                <td class="issue-table-time">${timeTrackingDisplay}</td>
            `;

            tbody.appendChild(row);
        });

        table.appendChild(tbody);
        tableContainer.appendChild(table);

        return tableContainer;
    }

    createIssueCard(issue) {
        const card = document.createElement('div');
        card.className = 'issue-card';

        const jiraUrl = `${this.jiraBaseUrl}/browse/${issue.key}`;

        const assigneeName = issue.fields.assignee ?
            (issue.fields.assignee.displayName || issue.fields.assignee.name) :
            'Unassigned';

        const issueType = issue.fields.issuetype ? issue.fields.issuetype.name : 'Unknown';
        const priority = issue.fields.priority ? issue.fields.priority.name : 'None';

        const updatedDate = new Date(issue.fields.updated).toLocaleDateString();
        const statusName = issue.fields.status ? issue.fields.status.name : 'Unknown';

        // Get status icon and issue type icon
        const statusIcon = this.getStatusIcon(issue.bucket || 'other');
        const typeIcon = this.getIssueTypeIcon(issueType);
        const priorityBadge = this.createPriorityBadge(priority);

        card.innerHTML = `
            <div class="issue-summary"></div>
            <div class="issue-header">
                <a href="${jiraUrl}" target="_blank" class="issue-key">${issue.key}</a>
                <span class="issue-status">${statusIcon}${this.escapeHtml(statusName)}</span>
            </div>
            <div class="issue-meta">
                <span class="issue-assignee">👤 ${this.escapeHtml(assigneeName)}</span>
                <span class="issue-type">${typeIcon}${this.escapeHtml(issueType)}</span>
                <span class="issue-updated">📅 ${updatedDate}</span>
            </div>
        `;

        // Add priority badge after creating the card
        const issueHeader = card.querySelector('.issue-header');
        issueHeader.appendChild(priorityBadge);

        const summaryEl = card.querySelector('.issue-summary');
        summaryEl.textContent = '';
        const summaryLink = document.createElement('a');
        summaryLink.className = 'issue-summary-link';
        summaryLink.href = jiraUrl;
        summaryLink.textContent = issue.fields.summary || issue.key;
        summaryEl.appendChild(summaryLink);

        // Add click handler to open modal instead of direct Jira link
        card.addEventListener('click', (e) => {
            // Don't open modal if clicking on links
            if (e.target.tagName !== 'A') {
                e.preventDefault();
                this.openIssueModal(issue);
            }
        });

        return card;
    }

    openIssueModal(issue) {
        if (!this.modal || !this.modalBody) {
            console.error('Modal elements not found');
            return;
        }

        const jiraUrl = `${this.jiraBaseUrl}/browse/${issue.key}`;

        // Create detailed issue view with filter controls
        const modalContent = this.createDetailedIssueView(issue, jiraUrl);

        // Clear and populate modal body
        this.modalBody.innerHTML = '';
        this.modalBody.appendChild(modalContent);

        // Show modal
        this.modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden'; // Prevent background scrolling
    }

    createDetailedIssueView(issue, jiraUrl) {
        const container = document.createElement('div');
        container.className = 'issue-detail-view';

        const assigneeName = issue.fields.assignee ?
            (issue.fields.assignee.displayName || issue.fields.assignee.name) :
            'Unassigned';

        const issueType = issue.fields.issuetype ? issue.fields.issuetype.name : 'Unknown';
        const priority = issue.fields.priority ? issue.fields.priority.name : 'None';
        const statusName = issue.fields.status ? issue.fields.status.name : 'Unknown';
        const projectName = issue.fields.project ? issue.fields.project.name : 'Unknown';

        const createdDate = new Date(issue.fields.created).toLocaleString();
        const updatedDate = new Date(issue.fields.updated).toLocaleString();

        // Get description (if available)
        const description = issue.fields.description || 'No description available';

        // Get parent info (if it's a subtask)
        const parentInfo = issue.fields.parent ? `
            <div class="detail-row">
                <span class="detail-label">Parent:</span>
                <span class="detail-value">${issue.fields.parent.key} - ${this.escapeHtml(issue.fields.parent.fields?.summary || '')}</span>
            </div>
        ` : '';

        container.innerHTML = `
            <div class="issue-detail-header">
                <div class="issue-detail-title">
                    <a href="${jiraUrl}" target="_blank" class="issue-summary-title">
                        ${this.escapeHtml(issue.fields.summary || issue.key)} 
                        <span class="issue-key-inline">${issue.key}</span>
                    </a>
                    <span class="issue-detail-status status-${statusName.toLowerCase().replace(/\s+/g, '-')}">${this.escapeHtml(statusName)}</span>
                </div>
            </div>
            
            <div class="issue-detail-description">
                <h3>Description</h3>
                <div class="description-content">${this.formatDescription(description)}</div>
            </div>
            
            <div class="issue-detail-info">
                <h3>Details</h3>
                <div class="detail-grid">
                    <div class="detail-row">
                        <span class="detail-label">Project:</span>
                        <span class="detail-value">${this.escapeHtml(projectName)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Type:</span>
                        <span class="detail-value">${this.escapeHtml(issueType)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Priority:</span>
                        <span class="detail-value">${this.escapeHtml(priority)}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Assignee:</span>
                        <span class="detail-value">${this.escapeHtml(assigneeName)}</span>
                    </div>
                    ${parentInfo}
                    <div class="detail-row">
                        <span class="detail-label">Created:</span>
                        <span class="detail-value">${createdDate}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Updated:</span>
                        <span class="detail-value">${updatedDate}</span>
                    </div>
                    <div class="detail-row">
                        <span class="detail-label">Bucket:</span>
                        <span class="detail-value bucket-${issue.bucket}">${this.getBucketDisplayName(issue.bucket)}</span>
                    </div>
                </div>
            </div>
        `;

        return container;
    }

    formatDescription(description) {
        if (!description || typeof description !== 'string') {
            return '<p class="no-description">No description available</p>';
        }

        // Basic text formatting - convert newlines to paragraphs
        const paragraphs = description.split('\\n\\n').filter(p => p.trim());
        return paragraphs.map(p => `<p>${this.escapeHtml(p.trim())}</p>`).join('');
    }

    getBucketDisplayName(bucket) {
        const bucketNames = {
            dev: '🔧 Development',
            qa: '🧪 QA',
            product: '🚀 UAT',
            completed: '✅ Completed',
            dropped: '❌ Dropped',
            deployed: '🎉 Deployed',
            other: '📋 Other'
        };
        return bucketNames[bucket] || '📋 Other';
    }

    openFeatureModal(parent, assigneeKey = null) {
        if (!this.modal || !this.modalBody) {
            console.error('Modal elements not found');
            return;
        }

        // Filter issues by assignee if assigneeKey is provided
        let filteredParent = parent;
        if (assigneeKey) {
            // Find the assignee group and filter issues to only those assigned to this assignee
            const assigneeGroup = this.assigneeGroups.find(group => group.key === assigneeKey);
            if (assigneeGroup && assigneeGroup.parentGroups.has(parent.parentKey)) {
                const assigneeParentGroup = assigneeGroup.parentGroups.get(parent.parentKey);
                filteredParent = {
                    ...parent,
                    issues: assigneeParentGroup.issues,
                    bucketCounts: assigneeParentGroup.issues.reduce((counts, issue) => {
                        const bucket = issue.bucket || 'other';
                        const normalizedBucket = ['dev', 'qa', 'product', 'completed', 'dropped', 'deployed'].includes(bucket) ? bucket : 'other';
                        counts[normalizedBucket] = (counts[normalizedBucket] || 0) + 1;
                        return counts;
                    }, { dev: 0, qa: 0, product: 0, completed: 0, dropped: 0, deployed: 0, other: 0 })
                };
            }
        }

        // Create feature summary view with clickable bucket stats
        const modalContent = this.createFeatureSummaryView(filteredParent);

        // Clear and populate modal body
        this.modalBody.innerHTML = '';
        this.modalBody.appendChild(modalContent);

        // Show modal
        this.modal.classList.remove('hidden');
        document.body.style.overflow = 'hidden'; // Prevent background scrolling

        // Initialize bucket filtering for this modal
        this.initializeBucketFiltering(filteredParent);
    }

    initializeBucketFiltering(parent) {
        const bucketStats = document.querySelectorAll('.bucket-stat[data-bucket]');
        const issueCountElement = document.querySelector('.modal-issue-count');
        const issueListContainer = document.querySelector('.modal-issue-list');
        const clearButton = document.getElementById('clearFilterBtn');

        if (!bucketStats.length || !issueCountElement || !issueListContainer) return;

        bucketStats.forEach(stat => {
            stat.addEventListener('click', () => {
                const bucket = stat.getAttribute('data-bucket');

                // Remove active class from all bucket stats
                bucketStats.forEach(s => s.classList.remove('active'));

                // Add active class to clicked bucket stat
                stat.classList.add('active');

                // Filter issues
                let filteredIssues = parent.issues;
                if (bucket && bucket !== 'all') {
                    filteredIssues = parent.issues.filter(issue => issue.bucket === bucket);
                }

                // Update issue table
                issueListContainer.innerHTML = '';
                const newTable = this.createIssueTable(filteredIssues);
                issueListContainer.appendChild(newTable);

                // Update count
                issueCountElement.textContent = filteredIssues.length;

                // Update header text to show active filter
                const filterText = bucket === 'all' ? 'All Issues' : this.getBucketDisplayName(bucket);
                const headerElement = document.querySelector('.feature-issues h3');
                if (headerElement) {
                    headerElement.innerHTML = `${filterText} (<span class="modal-issue-count">${filteredIssues.length}</span>)`;
                }
            });

            // Make bucket stats look clickable
            stat.style.cursor = 'pointer';
            stat.setAttribute('role', 'button');
            stat.setAttribute('tabindex', '0');

            // Add keyboard support
            stat.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    stat.click();
                }
            });
        });

        // Set up clear filter button
        if (clearButton) {
            clearButton.addEventListener('click', () => {
                // Remove active class from all bucket stats
                bucketStats.forEach(s => s.classList.remove('active'));

                // Show all issues in table
                issueListContainer.innerHTML = '';
                const newTable = this.createIssueTable(parent.issues);
                issueListContainer.appendChild(newTable);
                issueCountElement.textContent = parent.issues.length;

                // Reset header text
                const headerElement = document.querySelector('.feature-issues h3');
                if (headerElement) {
                    headerElement.innerHTML = `All Issues (<span class="modal-issue-count">${parent.issues.length}</span>)`;
                }
            });
        }
    }

    createFeatureSummaryView(parent) {
        const container = document.createElement('div');
        container.className = 'feature-summary-view';

        const jiraUrl = `${this.jiraBaseUrl}/browse/${parent.parentKey}`;

        container.innerHTML = `
            <div class="feature-summary-header">
                <div class="feature-summary-title">
                    <a href="${jiraUrl}" target="_blank" class="feature-summary-title-link">
                        ${this.escapeHtml(parent.parentSummary)}
                        <span class="issue-key-inline">${parent.parentKey}</span>
                    </a>
                </div>
            </div>

            <div class="feature-buckets">
                <h3>Issue Distribution</h3>
                <div class="bucket-stats-container">
                    <div class="bucket-stats">
                        <div class="bucket-stat dev" data-bucket="dev">
                            <span class="bucket-icon">🔧</span>
                            <span class="bucket-name">Development</span>
                            <span class="bucket-count">${parent.bucketCounts.dev || 0}</span>
                        </div>
                        <div class="bucket-stat qa" data-bucket="qa">
                            <span class="bucket-icon">🧪</span>
                            <span class="bucket-name">QA</span>
                            <span class="bucket-count">${parent.bucketCounts.qa || 0}</span>
                        </div>
                        <div class="bucket-stat product" data-bucket="product">
                            <span class="bucket-icon">🚀</span>
                            <span class="bucket-name">UAT</span>
                            <span class="bucket-count">${parent.bucketCounts.product || 0}</span>
                        </div>
                        <div class="bucket-stat completed" data-bucket="completed">
                            <span class="bucket-icon">✅</span>
                            <span class="bucket-name">Completed</span>
                            <span class="bucket-count">${parent.bucketCounts.completed || 0}</span>
                        </div>
                        <div class="bucket-stat dropped" data-bucket="dropped">
                            <span class="bucket-icon">❌</span>
                            <span class="bucket-name">Dropped</span>
                            <span class="bucket-count">${parent.bucketCounts.dropped || 0}</span>
                        </div>
                        <div class="bucket-stat deployed" data-bucket="deployed">
                            <span class="bucket-icon">🎉</span>
                            <span class="bucket-name">Deployed</span>
                            <span class="bucket-count">${parent.bucketCounts.deployed || 0}</span>
                        </div>
                        <div class="bucket-stat other" data-bucket="other">
                            <span class="bucket-icon">📋</span>
                            <span class="bucket-name">Other</span>
                            <span class="bucket-count">${parent.bucketCounts.other || 0}</span>
                        </div>
                    </div>
                    <button class="clear-filter-btn" id="clearFilterBtn">Clear Filter</button>
                </div>
            </div>

            <div class="feature-issues">
                <h3>All Issues (<span class="modal-issue-count">${parent.issues.length}</span>)</h3>
                <div class="modal-issue-list"></div>
            </div>
        `;

        // Add the issue table
        const issueTable = this.createIssueTable(parent.issues);
        const issueListContainer = container.querySelector('.modal-issue-list');
        issueListContainer.appendChild(issueTable);

        return container;
    }

    createIssueListItem(issue) {
        const jiraUrl = `${this.jiraBaseUrl}/browse/${issue.key}`;
        const statusName = issue.fields.status ? issue.fields.status.name : 'Unknown';
        const assigneeName = issue.fields.assignee ?
            (issue.fields.assignee.displayName || issue.fields.assignee.name) :
            'Unassigned';

        return `
            <div class="issue-list-item" onclick="window.open('${jiraUrl}', '_blank')">
                <div class="issue-list-header">
                    <span class="issue-list-key">${issue.key}</span>
                    <span class="issue-list-status bucket-${issue.bucket}">${this.escapeHtml(statusName)}</span>
                </div>
                <div class="issue-list-summary">${this.escapeHtml(issue.fields.summary || issue.key)}</div>
                <div class="issue-list-meta">
                    <span>👤 ${this.escapeHtml(assigneeName)}</span>
                    <span>📋 ${this.escapeHtml(issue.fields.issuetype?.name || 'Unknown')}</span>
                </div>
            </div>
        `;
    }

    applyCurrentView() {
        const views = [
            { name: 'feature', button: this.featureViewBtn, element: this.featureView },
            { name: 'team', button: this.teamViewBtn, element: this.teamView },
            { name: 'assignee', button: this.assigneeViewBtn, element: this.assigneeView }
        ];

        views.forEach(({ name, button, element }) => {
            if (!button || !element) {
                return;
            }

            if (this.currentView === name) {
                button.classList.add('active');
                element.classList.remove('hidden');
            } else {
                button.classList.remove('active');
                element.classList.add('hidden');
            }
        });
    }

    switchToFeatureView() {
        this.currentView = 'feature';
        this.applyCurrentView();
    }

    switchToTeamView() {
        this.currentView = 'team';
        this.applyCurrentView();
    }

    switchToAssigneeView() {
        this.currentView = 'assignee';
        this.applyCurrentView();
    }

    closeModal() {
        if (this.modal) {
            this.modal.classList.add('hidden');
            document.body.style.overflow = ''; // Restore scrolling
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text ?? '';
        return div.innerHTML;
    }

    showLoading() {
        if (this.loadingDiv) {
            this.loadingDiv.classList.remove('hidden');
        }
        if (this.runButton) {
            this.runButton.disabled = true;
            this.runButton.textContent = 'Loading...';
        }
    }

    hideLoading() {
        if (this.loadingDiv) {
            this.loadingDiv.classList.add('hidden');
        }
        if (this.runButton) {
            this.runButton.disabled = false;
            this.runButton.textContent = 'Run Query';
        }
    }

    showError(message) {
        if (this.errorDiv) {
            this.errorDiv.textContent = message;
            this.errorDiv.classList.remove('hidden');
        } else {
            console.error('Error div not found:', message);
        }
    }

    hideError() {
        if (this.errorDiv) {
            this.errorDiv.classList.add('hidden');
        }
    }

    showResults() {
        if (this.resultsDiv) {
            this.resultsDiv.classList.remove('hidden');
        }
    }

    switchToCardView() {
        this.currentLayout = 'card';
        this.cardViewBtn.classList.add('active');
        this.listViewBtn.classList.remove('active');
        this.parentOverviewContainer.classList.remove('list-view');
        this.parentOverviewContainer.classList.add('card-view');

        // Re-render the content with card layout
        this.renderParentOverview();
    }

    switchToListView() {
        this.currentLayout = 'list';
        this.listViewBtn.classList.add('active');
        this.cardViewBtn.classList.remove('active');
        this.parentOverviewContainer.classList.remove('card-view');
        this.parentOverviewContainer.classList.add('list-view');

        // Re-render the content with tree layout
        this.renderParentOverview();
    }

    expandAllFeatures() {
        const releaseSections = this.parentOverviewContainer.querySelectorAll('.release-section');
        releaseSections.forEach(section => {
            section.classList.remove('collapsed');
            const collapseIcon = section.querySelector('.release-collapse-icon');
            if (collapseIcon) {
                collapseIcon.textContent = '▼';
            }
        });

        // Expand all tree nodes in list view
        if (this.currentLayout === 'list') {
            const treeNodes = this.parentOverviewContainer.querySelectorAll('.tree-node');
            treeNodes.forEach(node => {
                node.classList.add('expanded');
                const expandBtn = node.querySelector('.tree-expand-btn');
                if (expandBtn) expandBtn.innerHTML = '▼';
            });

            // Expand all bucket nodes
            const bucketNodes = this.parentOverviewContainer.querySelectorAll('.tree-bucket-node');
            bucketNodes.forEach(node => {
                node.classList.add('expanded');
                const expandBtn = node.querySelector('.bucket-expand-btn');
                if (expandBtn) expandBtn.innerHTML = '▼';
            });

            // Expand all story containers
            const storyContainers = this.parentOverviewContainer.querySelectorAll('.tree-story-container');
            storyContainers.forEach(container => {
                container.classList.add('expanded');
                const expandBtn = container.querySelector('.story-expand-btn');
                if (expandBtn) expandBtn.innerHTML = '▼';
            });
        }
    }

    collapseAllFeatures() {
        const releaseSections = this.parentOverviewContainer.querySelectorAll('.release-section');
        releaseSections.forEach(section => {
            section.classList.add('collapsed');
            const collapseIcon = section.querySelector('.release-collapse-icon');
            if (collapseIcon) {
                collapseIcon.textContent = '▶';
            }
        });

        // Collapse all tree nodes in list view
        if (this.currentLayout === 'list') {
            const treeNodes = this.parentOverviewContainer.querySelectorAll('.tree-node');
            treeNodes.forEach(node => {
                node.classList.remove('expanded');
                const expandBtn = node.querySelector('.tree-expand-btn');
                if (expandBtn) expandBtn.innerHTML = '▶';
            });

            // Collapse all bucket nodes
            const bucketNodes = this.parentOverviewContainer.querySelectorAll('.tree-bucket-node');
            bucketNodes.forEach(node => {
                node.classList.remove('expanded');
                const expandBtn = node.querySelector('.bucket-expand-btn');
                if (expandBtn) expandBtn.innerHTML = '▶';
            });

            // Collapse all story containers
            const storyContainers = this.parentOverviewContainer.querySelectorAll('.tree-story-container');
            storyContainers.forEach(container => {
                container.classList.remove('expanded');
                const expandBtn = container.querySelector('.story-expand-btn');
                if (expandBtn) expandBtn.innerHTML = '▶';
            });
        }
    }

    hideResults() {
        if (this.resultsDiv) {
            this.resultsDiv.classList.add('hidden');
        }
    }

    parseTimeToSeconds(timeValue) {
        if (!timeValue || timeValue === 0) return 0;

        if (typeof timeValue === 'number') {
            return timeValue;
        }

        if (typeof timeValue === 'string') {
            let seconds = 0;

            // Parse formats like "1h", "30m", "1h 30m", "01h", "1w", etc.
            const weekMatch = timeValue.match(/(\d+)w/);
            const hourMatch = timeValue.match(/(\d+)h/);
            const minuteMatch = timeValue.match(/(\d+)m/);

            if (weekMatch) seconds += parseInt(weekMatch[1]) * 7 * 24 * 3600;
            if (hourMatch) seconds += parseInt(hourMatch[1]) * 3600;
            if (minuteMatch) seconds += parseInt(minuteMatch[1]) * 60;

            return seconds;
        }

        return 0;
    }

    formatTime(timeValue) {
        const seconds = this.parseTimeToSeconds(timeValue);

        if (seconds === 0) return '0h';

        const weeks = Math.floor(seconds / (7 * 24 * 3600));
        const hours = Math.floor((seconds % (7 * 24 * 3600)) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);

        let result = '';
        if (weeks > 0) result += `${weeks}w `;
        if (hours > 0) result += `${hours}h `;
        if (minutes > 0) result += `${minutes}m`;

        return result.trim() || '0h';
    }

    downloadReport() {
        if (!this.parentAggregates || this.parentAggregates.size === 0) {
            alert('No data to download. Please run a query first.');
            return;
        }

        // Generate CSV content
        const headers = ['Epic/Feature Key', 'Summary', 'Release', 'Total Issues', 'Dev', 'QA', 'UAT', 'Completed', 'Dropped', 'Deployed', 'Other', 'Progress %'];
        const rows = [headers];

        Array.from(this.parentAggregates.values()).forEach(parent => {
            const row = [
                parent.parentKey,
                `"${(parent.parentSummary || '').replace(/"/g, '""')}"`,
                parent.fixVersion || 'No Release',
                parent.total,
                parent.bucketCounts.dev || 0,
                parent.bucketCounts.qa || 0,
                parent.bucketCounts.product || 0,
                parent.bucketCounts.completed || 0,
                parent.bucketCounts.dropped || 0,
                parent.bucketCounts.deployed || 0,
                parent.bucketCounts.other || 0,
                parent.progress
            ];
            rows.push(row);
        });

        const csvContent = rows.map(row => row.join(',')).join('\n');

        // Create download
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        const timestamp = new Date().toISOString().split('T')[0];

        link.setAttribute('href', url);
        link.setAttribute('download', `jira-report-${timestamp}.csv`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    generateSummary() {
        if (!this.parentAggregates || this.parentAggregates.size === 0) {
            alert('No data to generate summary. Please run a query first.');
            return;
        }

        // Calculate overall statistics
        const parents = Array.from(this.parentAggregates.values());
        const totalIssues = parents.reduce((sum, p) => sum + p.total, 0);
        const totalDev = parents.reduce((sum, p) => sum + (p.bucketCounts.dev || 0), 0);
        const totalQA = parents.reduce((sum, p) => sum + (p.bucketCounts.qa || 0), 0);
        const totalUAT = parents.reduce((sum, p) => sum + (p.bucketCounts.product || 0), 0);
        const totalCompleted = parents.reduce((sum, p) => sum + (p.bucketCounts.completed || 0), 0);
        const totalDropped = parents.reduce((sum, p) => sum + (p.bucketCounts.dropped || 0), 0);
        const totalDeployed = parents.reduce((sum, p) => sum + (p.bucketCounts.deployed || 0), 0);
        const totalOther = parents.reduce((sum, p) => sum + (p.bucketCounts.other || 0), 0);
        const avgProgress = Math.round(parents.reduce((sum, p) => sum + p.progress, 0) / parents.length);

        // Group by release
        const releaseGroups = new Map();
        parents.forEach(parent => {
            const release = parent.fixVersion || 'No Release';
            if (!releaseGroups.has(release)) {
                releaseGroups.set(release, []);
            }
            releaseGroups.get(release).push(parent);
        });

        const sortedReleases = Array.from(releaseGroups.keys()).sort((a, b) => {
            if (a === 'No Release') return 1;
            if (b === 'No Release') return -1;
            return a.localeCompare(b);
        });

        // Group all issues by status for detailed breakdown
        const allIssues = parents.flatMap(p => p.issues);
        const statusBreakdown = new Map();
        allIssues.forEach(issue => {
            const status = issue.fields?.status?.name || 'Unknown';
            const bucket = issue.bucket || 'other';
            const key = `${bucket}|${status}`;
            if (!statusBreakdown.has(key)) {
                statusBreakdown.set(key, { bucket, status, count: 0, issues: [] });
            }
            const entry = statusBreakdown.get(key);
            entry.count++;
            entry.issues.push(issue);
        });

        const timestamp = new Date().toLocaleString();
        const dateStr = new Date().toISOString().split('T')[0];

        // Generate HTML document
        const html = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Jira Dashboard Summary - ${dateStr}</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            line-height: 1.4;
            color: #333;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px 15px;
            background: #f8f9fa;
            font-size: 14px;
        }
        .header {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            color: white;
            padding: 20px 25px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
        }
        .header h1 {
            margin: 0 0 8px 0;
            font-size: 1.8rem;
            font-weight: 700;
        }
        .header .meta {
            opacity: 0.9;
            font-size: 0.85rem;
        }
        .section {
            background: white;
            padding: 18px 20px;
            margin-bottom: 18px;
            border-radius: 8px;
            box-shadow: 0 1px 4px rgba(0,0,0,0.08);
        }
        h2 {
            color: #1e293b;
            border-bottom: 2px solid #3b82f6;
            padding-bottom: 8px;
            margin: 0 0 15px 0;
            font-size: 1.3rem;
            font-weight: 700;
        }
        h3 {
            color: #475569;
            margin: 18px 0 12px 0;
            font-size: 1.1rem;
            font-weight: 600;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 12px;
            margin: 15px 0;
        }
        .stat-card {
            background: linear-gradient(135deg, #f8fafc 0%, #f1f5f9 100%);
            padding: 12px 15px;
            border-radius: 8px;
            border-left: 3px solid #3b82f6;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
            text-align: center;
        }
        .stat-card.highlight {
            background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
            border-left-color: #2563eb;
        }
        .stat-label {
            font-size: 0.7rem;
            color: #64748b;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 600;
            margin-bottom: 4px;
        }
        .stat-value {
            font-size: 1.5rem;
            font-weight: 700;
            color: #1e293b;
            line-height: 1;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            font-size: 0.85rem;
        }
        th {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            color: white;
            padding: 8px 10px;
            text-align: left;
            font-weight: 600;
            font-size: 0.8rem;
        }
        td {
            padding: 8px 10px;
            border-bottom: 1px solid #e2e8f0;
            vertical-align: middle;
        }
        tr:hover {
            background: #f8fafc;
        }
        .progress-bar {
            background: #e2e8f0;
            height: 18px;
            border-radius: 9px;
            overflow: hidden;
            position: relative;
            min-width: 60px;
        }
        .progress-fill {
            background: linear-gradient(90deg, #10b981 0%, #059669 100%);
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.7rem;
            transition: width 0.3s ease;
        }
        .bucket-dev { background: #dbeafe; color: #1e40af; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .bucket-qa { background: #d1fae5; color: #065f46; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .bucket-product { background: #ede9fe; color: #5b21b6; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .bucket-completed { background: #d1fae5; color: #047857; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .bucket-dropped { background: #fee2e2; color: #991b1b; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .bucket-deployed { background: #e9d5ff; color: #6b21a8; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .bucket-other { background: #f3f4f6; color: #374151; padding: 3px 6px; border-radius: 4px; font-size: 0.75rem; font-weight: 600; white-space: nowrap; }
        .issue-link {
            color: #3b82f6;
            text-decoration: none;
            font-weight: 600;
            font-size: 0.8rem;
        }
        .issue-link:hover {
            text-decoration: underline;
        }
        .release-header {
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            color: white;
            padding: 12px 18px;
            border-radius: 6px;
            margin: 15px 0 12px 0;
        }
        .release-header h2 {
            margin: 0;
            border: none;
            padding: 0;
            color: white;
            font-size: 1.2rem;
        }
        .status-breakdown {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 10px;
            margin: 15px 0;
        }
        .status-card {
            background: #f8fafc;
            padding: 10px 12px;
            border-radius: 6px;
            border-left: 3px solid #64748b;
            text-align: center;
        }
        .status-card h4 {
            margin: 0 0 6px 0;
            font-size: 0.8rem;
            color: #475569;
        }
        .status-count {
            font-size: 1.2rem;
            font-weight: 700;
            color: #1e293b;
            margin-bottom: 2px;
        }
        .status-percentage {
            font-size: 0.7rem;
            color: #64748b;
        }
        @media print {
            body { background: white; }
            .section { box-shadow: none; border: 1px solid #e2e8f0; }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 Jira Dashboard Summary Report</h1>
        <div class="meta">Generated: ${timestamp}</div>
    </div>

    <div class="section">
        <h2>Executive Summary</h2>
        <div class="stats-grid">
            <div class="stat-card highlight">
                <div class="stat-label">Total Features/Epics</div>
                <div class="stat-value">${parents.length}</div>
            </div>
            <div class="stat-card highlight">
                <div class="stat-label">Total Issues</div>
                <div class="stat-value">${totalIssues}</div>
            </div>
            <div class="stat-card highlight">
                <div class="stat-label">Average Progress</div>
                <div class="stat-value">${avgProgress}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Releases</div>
                <div class="stat-value">${sortedReleases.length}</div>
            </div>
        </div>
    </div>

    <div class="section">
        <h2>Issue Distribution by Status Bucket</h2>
        <table>
            <thead>
                <tr>
                    <th>Bucket</th>
                    <th>Count</th>
                    <th>Percentage</th>
                    <th>Progress</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><span class="bucket-dev">🔧 Development</span></td>
                    <td><strong>${totalDev}</strong></td>
                    <td>${Math.round(totalDev / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalDev / totalIssues * 100)}%">
                                ${Math.round(totalDev / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td><span class="bucket-qa">🧪 QA</span></td>
                    <td><strong>${totalQA}</strong></td>
                    <td>${Math.round(totalQA / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalQA / totalIssues * 100)}%">
                                ${Math.round(totalQA / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td><span class="bucket-product">🚀 UAT</span></td>
                    <td><strong>${totalUAT}</strong></td>
                    <td>${Math.round(totalUAT / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalUAT / totalIssues * 100)}%">
                                ${Math.round(totalUAT / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td><span class="bucket-completed">✅ Completed</span></td>
                    <td><strong>${totalCompleted}</strong></td>
                    <td>${Math.round(totalCompleted / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalCompleted / totalIssues * 100)}%">
                                ${Math.round(totalCompleted / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td><span class="bucket-dropped">❌ Dropped</span></td>
                    <td><strong>${totalDropped}</strong></td>
                    <td>${Math.round(totalDropped / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalDropped / totalIssues * 100)}%; background: linear-gradient(90deg, #ef4444 0%, #dc2626 100%);">
                                ${Math.round(totalDropped / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td><span class="bucket-deployed">🎉 Deployed</span></td>
                    <td><strong>${totalDeployed}</strong></td>
                    <td>${Math.round(totalDeployed / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalDeployed / totalIssues * 100)}%; background: linear-gradient(90deg, #a855f7 0%, #9333ea 100%);">
                                ${Math.round(totalDeployed / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td><span class="bucket-other">📋 Other</span></td>
                    <td><strong>${totalOther}</strong></td>
                    <td>${Math.round(totalOther / totalIssues * 100)}%</td>
                    <td>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: ${Math.round(totalOther / totalIssues * 100)}%; background: linear-gradient(90deg, #64748b 0%, #475569 100%);">
                                ${Math.round(totalOther / totalIssues * 100)}%
                            </div>
                        </div>
                    </td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>Detailed Status Breakdown</h2>
        <p>Issues grouped by their actual Jira status within each bucket:</p>
        <div class="status-breakdown">
            ${Array.from(statusBreakdown.values())
                .sort((a, b) => b.count - a.count)
                .map(item => `
                    <div class="status-card">
                        <h4><span class="bucket-${item.bucket}">${item.status}</span></h4>
                        <div class="status-count">${item.count}</div>
                        <div class="status-percentage">${Math.round(item.count / totalIssues * 100)}%</div>
                    </div>
                `).join('')}
        </div>
    </div>

    ${sortedReleases.map(release => {
                    const features = releaseGroups.get(release);
                    const releaseTotal = features.reduce((sum, f) => sum + f.total, 0);
                    const releaseProgress = Math.round(features.reduce((sum, f) => sum + f.progress, 0) / features.length);
                    const releaseDev = features.reduce((sum, f) => sum + (f.bucketCounts.dev || 0), 0);
                    const releaseQA = features.reduce((sum, f) => sum + (f.bucketCounts.qa || 0), 0);
                    const releaseUAT = features.reduce((sum, f) => sum + (f.bucketCounts.product || 0), 0);
                    const releaseCompleted = features.reduce((sum, f) => sum + (f.bucketCounts.completed || 0), 0);
                    const releaseDropped = features.reduce((sum, f) => sum + (f.bucketCounts.dropped || 0), 0);
                    const releaseDeployed = features.reduce((sum, f) => sum + (f.bucketCounts.deployed || 0), 0);
                    const releaseOther = features.reduce((sum, f) => sum + (f.bucketCounts.other || 0), 0);

                    return `
    <div class="section">
        <div class="release-header">
            <h2 style="margin: 0; border: none; padding: 0; color: white;">${release}</h2>
        </div>
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-label">Features</div>
                <div class="stat-value">${features.length}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Total Issues</div>
                <div class="stat-value">${releaseTotal}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Avg Progress</div>
                <div class="stat-value">${releaseProgress}%</div>
            </div>
        </div>

        <h3>Distribution</h3>
        <div class="stats-grid">
            <div class="stat-card"><div class="stat-label">🔧 Dev</div><div class="stat-value">${releaseDev}</div></div>
            <div class="stat-card"><div class="stat-label">🧪 QA</div><div class="stat-value">${releaseQA}</div></div>
            <div class="stat-card"><div class="stat-label">🚀 UAT</div><div class="stat-value">${releaseUAT}</div></div>
            <div class="stat-card"><div class="stat-label">✅ Completed</div><div class="stat-value">${releaseCompleted}</div></div>
            <div class="stat-card"><div class="stat-label">❌ Dropped</div><div class="stat-value">${releaseDropped}</div></div>
            <div class="stat-card"><div class="stat-label">🎉 Deployed</div><div class="stat-value">${releaseDeployed}</div></div>
            <div class="stat-card"><div class="stat-label">📋 Other</div><div class="stat-value">${releaseOther}</div></div>
        </div>

        <h3>Features Detail</h3>
        <table>
            <thead>
                <tr>
                    <th>Feature</th>
                    <th>Summary</th>
                    <th>Total</th>
                    <th>Dev</th>
                    <th>QA</th>
                    <th>UAT</th>
                    <th>Completed</th>
                    <th>Dropped</th>
                    <th>Deployed</th>
                    <th>Other</th>
                    <th>Progress</th>
                </tr>
            </thead>
            <tbody>
                ${features.map(f => `
                    <tr>
                        <td><a href="${this.jiraBaseUrl}/browse/${f.parentKey}" class="issue-link" target="_blank">${f.parentKey}</a></td>
                        <td>${this.escapeHtml(f.parentSummary)}</td>
                        <td><strong>${f.total}</strong></td>
                        <td>${f.bucketCounts.dev || 0}</td>
                        <td>${f.bucketCounts.qa || 0}</td>
                        <td>${f.bucketCounts.product || 0}</td>
                        <td>${f.bucketCounts.completed || 0}</td>
                        <td>${f.bucketCounts.dropped || 0}</td>
                        <td>${f.bucketCounts.deployed || 0}</td>
                        <td>${f.bucketCounts.other || 0}</td>
                        <td>
                            <div class="progress-bar">
                                <div class="progress-fill" style="width: ${f.progress}%">${f.progress}%</div>
                            </div>
                        </td>
                    </tr>
                `).join('')}
            </tbody>
        </table>
    </div>
        `;
                }).join('')}

</body>
</html>`;

        // Download as HTML file
        const blob = new Blob([html], { type: 'text/html;charset=utf-8;' });
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);

        link.setAttribute('href', url);
        link.setAttribute('download', `jira-summary-${dateStr}.html`);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }

    // Create priority badge with color coding and icon
    createPriorityBadge(priority) {
        const badge = document.createElement('span');
        const priorityName = priority.name || priority;
        const priorityLower = priorityName.toLowerCase();
        
        badge.className = `priority-badge priority-${priorityLower}`;
        
        // Add icon based on priority
        let icon = '';
        if (priorityLower.includes('high')) {
            icon = '🔴';
        } else if (priorityLower === 'medium') {
            icon = '🟡';
        } else if (priorityLower.includes('low')) {
            icon = '🟢';
        }
        
        badge.innerHTML = `<span class="priority-icon">${icon}</span>${priorityName}`;
        return badge;
    }

    // Create mini donut chart showing completion percentage
    createDonutChart(parent) {
        const container = document.createElement('div');
        container.className = 'donut-chart-container';
        
        const total = parent.total || 0;
        const completed = (parent.bucketCounts?.completed || 0) + (parent.bucketCounts?.deployed || 0);
        const qa = parent.bucketCounts?.qa || 0;
        const dev = parent.bucketCounts?.dev || 0;
        
        const completedPercent = total > 0 ? Math.round((completed / total) * 100) : 0;
        
        // Determine color based on completion percentage
        let colorClass = 'completion-0';
        let textColorClass = 'text-red';
        if (completedPercent === 100) {
            colorClass = 'completion-100';
            textColorClass = 'text-green';
        } else if (completedPercent > 0) {
            colorClass = 'completion-partial';
            textColorClass = 'text-orange';
        }
        
        // SVG donut chart
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('class', 'donut-chart');
        svg.setAttribute('viewBox', '0 0 36 36');
        
        const radius = 15.9155;
        const circumference = 2 * Math.PI * radius;
        
        // Background ring
        const bgCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        bgCircle.setAttribute('class', 'donut-ring');
        bgCircle.setAttribute('cx', '18');
        bgCircle.setAttribute('cy', '18');
        bgCircle.setAttribute('r', radius);
        svg.appendChild(bgCircle);
        
        // Completed segment with color-coded class
        const completedCircle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        completedCircle.setAttribute('class', `donut-segment ${colorClass}`);
        completedCircle.setAttribute('cx', '18');
        completedCircle.setAttribute('cy', '18');
        completedCircle.setAttribute('r', radius);
        completedCircle.setAttribute('stroke-dasharray', `${completedPercent} ${100 - completedPercent}`);
        svg.appendChild(completedCircle);
        
        container.appendChild(svg);
        
        // Center text showing percentage with matching color
        const text = document.createElement('div');
        text.className = `donut-text ${textColorClass}`;
        text.innerHTML = `${completedPercent}%<span class="donut-label">Done</span>`;
        container.appendChild(text);
        
        return container;
    }

    // Animate counter numbers
    animateCounter(element, target, duration = 1000) {
        const start = 0;
        const increment = target / (duration / 16);
        let current = start;
        
        const timer = setInterval(() => {
            current += increment;
            if (current >= target) {
                element.textContent = target;
                clearInterval(timer);
                element.classList.remove('counting');
            } else {
                element.textContent = Math.floor(current);
            }
        }, 16);
        
        element.classList.add('counting');
    }

    // Get status icon based on bucket
    getStatusIcon(bucket) {
        const icons = {
            dev: '<span class="status-icon status-dev">🔧</span>',
            qa: '<span class="status-icon status-qa">🧪</span>',
            product: '<span class="status-icon status-product">🚀</span>',
            completed: '<span class="status-icon status-completed">✅</span>',
            deployed: '<span class="status-icon status-deployed">🎉</span>',
            dropped: '<span class="status-icon status-dropped">❌</span>',
            other: '<span class="status-icon">📋</span>'
        };
        return icons[bucket] || icons.other;
    }

    // Get issue type icon
    getIssueTypeIcon(issueType) {
        const typeLower = issueType.toLowerCase();
        let icon = '📄';
        let className = 'type-task';
        
        if (typeLower.includes('story')) {
            icon = '📖';
            className = 'type-story';
        } else if (typeLower.includes('bug')) {
            icon = '🐛';
            className = 'type-bug';
        } else if (typeLower.includes('epic')) {
            icon = '🎯';
            className = 'type-epic';
        } else if (typeLower.includes('task')) {
            icon = '✓';
            className = 'type-task';
        }
        
        return `<span class="issue-type-icon ${className}">${icon}</span>`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    window.jiraBucketsApp = new JiraBuckets();
});