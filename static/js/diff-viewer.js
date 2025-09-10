// File Diff Viewer JavaScript
// This file contains all functionality for viewing and managing file diffs

// =============================================================================
// FILE DIFF VIEWER FUNCTIONALITY
// =============================================================================

// Diff viewer variables
let currentDiffs = [];
let pendingDiffsCount = 0;

// Initialize diff viewer when DOM is loaded
function initializeDiffViewer() {
    // Add event listeners for diff controls
    const acceptAllBtn = document.getElementById('acceptAllDiffs');
    const refreshBtn = document.getElementById('refreshDiffs');
    
    if (acceptAllBtn) {
        acceptAllBtn.addEventListener('click', acceptAllDiffs);
    }
    
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshDiffs);
    }
    
    // Load initial diffs if session is active
    if (typeof currentSessionId !== 'undefined' && currentSessionId) {
        loadSessionDiffs();
    }
}

// Load diffs for current session
async function loadSessionDiffs() {
    if (typeof currentSessionId === 'undefined' || !currentSessionId) return;
    
    try {
        const response = await fetch(`/api/diffs/${currentSessionId}`, { cache: 'no-store' });
        // Handle empty or bad responses gracefully
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const text = await response.text();
        if (!text) {
            throw new Error('Empty response');
        }
        const data = JSON.parse(text);
        
        if (data.success) {
            currentDiffs = data.diffs;
            renderDiffs();
            updateDiffNotifications();
        } else {
            console.error('Failed to load diffs:', data.error);
        }
    } catch (error) {
        console.error('Error loading diffs:', error);
        if (typeof showToast === 'function') {
            showToast('Diffs Error', 'Failed to load diffs for this session', 'error');
        }
    }
}

// Render diffs in the UI
function renderDiffs() {
    const container = document.getElementById('diffsContainer');
    const bulkActions = document.getElementById('diffBulkActions');
    
    if (!container) return;
    
    // Count pending diffs
    pendingDiffsCount = currentDiffs.filter(diff => diff.status === 'pending').length;
    
    if (currentDiffs.length === 0) {
        container.innerHTML = `
            <div class="diff-no-changes">
                <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
                    <path d="M9 12L11 14L15 10" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <p>No file changes detected</p>
                <p style="font-size: 12px; margin-top: 8px;">File changes will appear here when the AI modifies files in your working directory</p>
            </div>
        `;
        if (bulkActions) bulkActions.style.display = 'none';
        return;
    }
    
    // Show bulk actions if there are pending diffs
    if (bulkActions) {
        bulkActions.style.display = pendingDiffsCount > 0 ? 'flex' : 'none';
        const pendingCount = document.getElementById('pendingDiffsCount');
        if (pendingCount) {
            pendingCount.textContent = pendingDiffsCount;
        }
    }
    
    // Render each diff
    container.innerHTML = currentDiffs.map(diff => renderSingleDiff(diff)).join('');
    
    // Add event listeners to diff buttons
    addDiffEventListeners();
}

// Render a single diff
function renderSingleDiff(diff) {
    const fileName = diff.file_path.split('/').pop();
    const relativePath = diff.file_path;
    const timestamp = new Date(diff.timestamp).toLocaleString();
    
    // Parse diff lines for better display
    const diffLines = parseDiffLines(diff.diff_lines);
    
    return `
        <div class="diff-viewer ${diff.status === 'pending' ? 'new-diff' : ''}" data-diff-id="${diff.diff_id}">
            <div class="diff-header">
                <div class="diff-file-info">
                    <div class="diff-file-path">${fileName}</div>
                    <div class="diff-file-meta">
                        <span class="diff-change-type ${diff.change_type}">${diff.change_type}</span>
                        <span>${relativePath}</span>
                        <span>${timestamp}</span>
                    </div>
                </div>
                <div class="diff-actions">
                    <span class="diff-status ${diff.status}">${diff.status}</span>
                    ${diff.status === 'pending' ? `
                        <button class="diff-btn accept" data-diff-id="${diff.diff_id}" data-action="accept">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                <path d="M20 6L9 17L4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            Accept
                        </button>
                        <button class="diff-btn deny" data-diff-id="${diff.diff_id}" data-action="deny">
                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                                <path d="M18 6L6 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M6 6L18 18" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                            Deny
                        </button>
                    ` : ''}
                    <button class="diff-btn toggle" data-diff-id="${diff.diff_id}" data-action="toggle">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                            <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        ${diffLines.length > 0 ? 'Show' : 'Hide'}
                    </button>
                </div>
            </div>
            <div class="diff-content collapsed">
                ${diffLines.map(line => `
                    <div class="diff-line ${line.type}">
                        <div class="diff-line-number">${line.lineNumber || ''}</div>
                        <div class="diff-line-content">${escapeHtml(line.content)}</div>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

// Parse diff lines for better display
function parseDiffLines(diffLines) {
    const parsedLines = [];
    let oldLineNumber = 0;
    let newLineNumber = 0;
    
    for (const line of diffLines) {
        if (line.startsWith('@@')) {
            // Hunk header
            const match = line.match(/@@ -(\d+),?\d* \+(\d+),?\d* @@/);
            if (match) {
                oldLineNumber = parseInt(match[1]);
                newLineNumber = parseInt(match[2]);
            }
            parsedLines.push({
                type: 'hunk-header',
                content: line,
                lineNumber: ''
            });
        } else if (line.startsWith('+')) {
            parsedLines.push({
                type: 'added',
                content: line.substring(1),
                lineNumber: newLineNumber++
            });
        } else if (line.startsWith('-')) {
            parsedLines.push({
                type: 'removed',
                content: line.substring(1),
                lineNumber: oldLineNumber++
            });
        } else if (line.startsWith(' ')) {
            parsedLines.push({
                type: 'context',
                content: line.substring(1),
                lineNumber: `${oldLineNumber++}/${newLineNumber++}`
            });
        } else if (line.trim()) {
            // Other lines (like file headers)
            parsedLines.push({
                type: 'context',
                content: line,
                lineNumber: ''
            });
        }
    }
    
    return parsedLines;
}

// Add event listeners to diff buttons
function addDiffEventListeners() {
    // Accept/Deny buttons
    document.querySelectorAll('.diff-btn[data-action="accept"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const diffId = e.target.closest('[data-diff-id]').dataset.diffId;
            acceptDiff(diffId);
        });
    });
    
    document.querySelectorAll('.diff-btn[data-action="deny"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const diffId = e.target.closest('[data-diff-id]').dataset.diffId;
            denyDiff(diffId);
        });
    });
    
    // Toggle buttons
    document.querySelectorAll('.diff-btn[data-action="toggle"]').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const diffViewer = e.target.closest('.diff-viewer');
            const diffContent = diffViewer.querySelector('.diff-content');
            const isCollapsed = diffContent.classList.contains('collapsed');
            
            if (isCollapsed) {
                diffContent.classList.remove('collapsed');
                e.target.innerHTML = `
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                        <path d="M18 15L12 9L6 15" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    Hide
                `;
            } else {
                diffContent.classList.add('collapsed');
                e.target.innerHTML = `
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                        <path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                    Show
                `;
            }
        });
    });
}

// Accept a specific diff
async function acceptDiff(diffId) {
    if (typeof currentSessionId === 'undefined' || !currentSessionId) return;
    
    try {
        const response = await fetch(`/api/diffs/${currentSessionId}/${diffId}/accept`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            // Use showToast if available, otherwise console log
            if (typeof showToast === 'function') {
                showToast('Diff Accepted', 'File change has been accepted', 'success');
            } else {
                console.log('Diff accepted:', diffId);
            }
            
            // Update local diff status
            const diff = currentDiffs.find(d => d.diff_id === diffId);
            if (diff) {
                diff.status = 'accepted';
            }
            renderDiffs();
            updateDiffNotifications();
        } else {
            if (typeof showToast === 'function') {
                showToast('Error', data.error, 'error');
            } else {
                console.error('Error accepting diff:', data.error);
            }
        }
    } catch (error) {
        console.error('Error accepting diff:', error);
        if (typeof showToast === 'function') {
            showToast('Error', 'Failed to accept diff', 'error');
        }
    }
}

// Deny a specific diff
async function denyDiff(diffId) {
    if (typeof currentSessionId === 'undefined' || !currentSessionId) return;
    
    try {
        const response = await fetch(`/api/diffs/${currentSessionId}/${diffId}/deny`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            if (typeof showToast === 'function') {
                showToast('Diff Denied', 'File change has been denied and reverted', 'warning');
            } else {
                console.log('Diff denied and reverted:', diffId);
            }
            
            // Update local diff status
            const diff = currentDiffs.find(d => d.diff_id === diffId);
            if (diff) {
                diff.status = 'denied';
            }
            renderDiffs();
            updateDiffNotifications();
        } else {
            if (typeof showToast === 'function') {
                showToast('Error', data.error, 'error');
            } else {
                console.error('Error denying diff:', data.error);
            }
        }
    } catch (error) {
        console.error('Error denying diff:', error);
        if (typeof showToast === 'function') {
            showToast('Error', 'Failed to deny diff', 'error');
        }
    }
}

// Accept all pending diffs
async function acceptAllDiffs() {
    if (typeof currentSessionId === 'undefined' || !currentSessionId) return;
    
    try {
        const response = await fetch(`/api/diffs/${currentSessionId}/accept_all`, {
            method: 'POST'
        });
        const data = await response.json();
        
        if (data.success) {
            if (typeof showToast === 'function') {
                showToast('All Diffs Accepted', `${data.count} changes accepted`, 'success');
            } else {
                console.log(`All diffs accepted: ${data.count} changes`);
            }
            
            // Update local diff statuses
            currentDiffs.forEach(diff => {
                if (diff.status === 'pending') {
                    diff.status = 'accepted';
                }
            });
            renderDiffs();
            updateDiffNotifications();
        } else {
            if (typeof showToast === 'function') {
                showToast('Error', data.error, 'error');
            } else {
                console.error('Error accepting all diffs:', data.error);
            }
        }
    } catch (error) {
        console.error('Error accepting all diffs:', error);
        if (typeof showToast === 'function') {
            showToast('Error', 'Failed to accept all diffs', 'error');
        }
    }
}

// Refresh diffs
function refreshDiffs() {
    loadSessionDiffs();
    if (typeof showToast === 'function') {
        showToast('Refreshed', 'Diff list has been refreshed', 'info');
    } else {
        console.log('Diff list refreshed');
    }
}

// Update diff notifications
function updateDiffNotifications() {
    const badge = document.getElementById('diffsNotificationBadge');
    const diffsTab = document.getElementById('diffsTabButton');
    
    if (badge && diffsTab) {
        if (pendingDiffsCount > 0) {
            badge.textContent = pendingDiffsCount;
            badge.style.display = 'inline-block';
            diffsTab.classList.add('file-change-indicator');
        } else {
            badge.style.display = 'none';
            diffsTab.classList.remove('file-change-indicator');
        }
    }
}

// Handle file change events from SocketIO
function handleFileChangeEvent(data) {
    console.log('File change event received:', data);
    
    switch (data.type) {
        case 'diff_created':
            // Add new diff to the list
            currentDiffs.unshift(data.diff); // Add to beginning
            renderDiffs();
            updateDiffNotifications();
            
            // Show notification
            const fileName = data.diff.file_path.split('/').pop();
            if (typeof showToast === 'function') {
                showToast('File Changed', `${fileName} was modified`, 'info');
            } else {
                console.log(`File changed: ${fileName}`);
            }
            
            // Flash the diffs tab
            flashDiffsTab();
            break;
            
        case 'diff_accepted':
            // Update diff status
            const acceptedDiff = currentDiffs.find(d => d.diff_id === data.diff_id);
            if (acceptedDiff) {
                acceptedDiff.status = 'accepted';
                renderDiffs();
                updateDiffNotifications();
            }
            break;
            
        case 'diff_denied':
            // Update diff status
            const deniedDiff = currentDiffs.find(d => d.diff_id === data.diff_id);
            if (deniedDiff) {
                deniedDiff.status = 'denied';
                renderDiffs();
                updateDiffNotifications();
            }
            break;
            
        case 'all_diffs_accepted':
            // Update all pending diffs
            currentDiffs.forEach(diff => {
                if (diff.status === 'pending') {
                    diff.status = 'accepted';
                }
            });
            renderDiffs();
            updateDiffNotifications();
            break;
    }
}

// Flash the diffs tab to draw attention
function flashDiffsTab() {
    const diffsTab = document.getElementById('diffsTabButton');
    if (diffsTab) {
        diffsTab.style.animation = 'flash 2s ease-in-out';
        setTimeout(() => {
            diffsTab.style.animation = '';
        }, 2000);
    }
}

// Utility function to escape HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Add CSS for flash animation if not already added
if (!document.getElementById('diff-viewer-styles')) {
    const style = document.createElement('style');
    style.id = 'diff-viewer-styles';
    style.textContent = `
        @keyframes flash {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; background-color: var(--accent-color, #007bff); }
        }
    `;
    document.head.appendChild(style);
}

// Clear diffs (used when session ends)
function clearDiffs() {
    currentDiffs = [];
    pendingDiffsCount = 0;
    renderDiffs();
    updateDiffNotifications();
}

// Export functions for global access (if needed)
window.diffViewer = {
    initializeDiffViewer,
    loadSessionDiffs,
    handleFileChangeEvent,
    acceptDiff,
    denyDiff,
    acceptAllDiffs,
    refreshDiffs,
    updateDiffNotifications,
    clearDiffs
};
