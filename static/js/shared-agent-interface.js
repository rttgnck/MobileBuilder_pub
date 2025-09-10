// Shared Agent Interface JavaScript
// This file contains all common functionality shared across Claude, Gemini, and Cursor agents

// DEFAULT_WORKING_DIR will be set from the template
let DEFAULT_WORKING_DIR = window.DEFAULT_WORKING_DIR || '/tmp';

// Global Variables
const socket = io();
let isConnected = false;
let socketReady = false;
let currentSessionId = null;
let currentAgentMessage = null;
let agentMessageBuffer = '';
let messageTimeout = null;
let ansiUp = new AnsiUp();
let sessionTimer = null;
let sessionStartTime = null;
let activeTime = 0;
let deviceId = localStorage.getItem('deviceId') || generateDeviceId();
let disconnectInProgress = false;
let sessionStarting = false;
let endSessionFallbackTimeoutId = null;
let redirectOnDisconnect = false;

// Project Tree and Editor Variables
let projectTree = null;
let aceEditor = null;
let currentFilePath = null;
let currentFileContent = null;
let fileModified = false;

// Agent configuration - will be set by the specific agent page
let agentConfig = {
    type: 'agent',
    name: 'Agent',
    subtitle: 'AI Assistant',
    logo: 'A',
    exitCommand: '/exit',
    avatar: 'A',
    welcomeMessage: 'Welcome to Agent Interface'
};

// Mobile Keyboard Detection Variables
let initialViewportHeight = window.innerHeight;
let keyboardVisible = false;
let keyboardHeight = 0;

// Configure ANSI converter
ansiUp.use_classes = true;
ansiUp.escape_for_html = false;

// Store device ID
localStorage.setItem('deviceId', deviceId);

// Utility Functions
function generateDeviceId() {
    return 'device_' + Math.random().toString(36).substr(2, 9);
}

function formatTime(seconds) {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function showToast(title, message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
        <div class="toast-title">${title}</div>
        <div class="toast-message">${message}</div>
    `;
    
    document.getElementById('toastContainer').appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// Agent Configuration Functions
function initializeAgent(config) {
    agentConfig = { ...agentConfig, ...config };
    
    // Update page elements
    document.getElementById('pageTitle').textContent = `${agentConfig.name} Agent - MobileBuilder`;
    document.getElementById('agentLogo').textContent = agentConfig.logo;
    document.getElementById('agentTitle').textContent = `${agentConfig.name} Agent`;
    document.getElementById('agentSubtitle').textContent = agentConfig.subtitle;
    document.getElementById('inputField').placeholder = `Enter command for ${agentConfig.name}...`;
    document.getElementById('disconnectTitle').textContent = `Disconnect ${agentConfig.name} Session?`;
    document.getElementById('historyBtn').onclick = () => openSessionViewer();
    
    // Update disconnect message
    const disconnectMsg = document.getElementById('disconnectMessage');
    if (agentConfig.exitCommand.startsWith('/')) {
        disconnectMsg.innerHTML = `This will send the <code>${agentConfig.exitCommand}</code> command to ${agentConfig.name} and end the current session. All connected devices will be disconnected.`;
    } else {
        // disconnectMsg.innerHTML = `This will send the <code>${agentConfig.exitCommand}</code> command to ${agentConfig.name} and end the current session. All connected devices will be disconnected.`;
        disconnectMsg.innerHTML = `This will end the session with ${agentConfig.name}. All connected devices will be disconnected.`;
    }
    
    // Apply theme
    loadAgentTheme(agentConfig.type);
    
    // Configure connection screen
    configureConnectionScreen();
    
    // Setup connection form
    setupConnectionForm();
    
    // Update connection button state
    updateConnectionButtonState();
    
    // Check for URL parameters for automatic session resumption
    checkUrlParameters();
    
    // Select agent and check for existing session
    selectAgent();
    
    // Check for session history data
    checkSessionHistoryData();
    
    // Add welcome message
    setTimeout(() => {
        addSystemMessage(agentConfig.welcomeMessage);
    }, 100);
}

function loadAgentTheme(agentType) {
    // Hide all agent-specific CSS files
    document.getElementById('claudeCSS').style.display = 'none';
    document.getElementById('geminiCSS').style.display = 'none';
    document.getElementById('cursorCSS').style.display = 'none';
    document.getElementById('codexCSS').style.display = 'none';
    
    // Show the appropriate agent CSS
    const cssFile = document.getElementById(agentType + 'CSS');
    if (cssFile) {
        cssFile.style.display = 'block';
    }
    
    // Update body class for theming
    document.getElementById('agentBody').className = `${agentType}-theme`;
    
    // Update status text color
    const statusText = document.getElementById('statusText');
    if (statusText) {
        statusText.style.color = `var(--${agentType}-text-light)`;
    }
}

function configureConnectionScreen() {
    console.log('configureConnectionScreen called');
    if (document.getElementById('connectionLogo')) {
        console.log('Connection screen elements found, configuring...');
        document.getElementById('connectionLogo').textContent = agentConfig.logo;
        document.getElementById('connectionTitle').textContent = `${agentConfig.name} Agent Interface`;
        document.getElementById('connectionSubtitle').textContent = agentConfig.subtitle;
        document.getElementById('agentNameNotice').textContent = agentConfig.name;
        document.getElementById('agentNameHint').textContent = agentConfig.name;
        document.getElementById('connectButtonText').textContent = agentConfig.name;
        document.getElementById('workingDirectory').value = DEFAULT_WORKING_DIR;
        console.log('Connection screen configured successfully');
    } else {
        console.error('Connection screen elements not found!');
    }
}

// URL Parameters Functions
function checkUrlParameters() {
    const urlParams = new URLSearchParams(window.location.search);
    const shouldResume = urlParams.get('resume') === 'true';
    
    if (shouldResume) {
        const sessionId = urlParams.get('session_id');
        const agentApiSessionId = urlParams.get('agent_api_session_id');
        const workingDirectory = urlParams.get('working_directory');
        const sessionName = urlParams.get('session_name');
        
        if (sessionId && agentApiSessionId) {
            console.log('URL parameters indicate session resumption:', {
                sessionId, agentApiSessionId, workingDirectory, sessionName
            });
            
            // Store resume data for automatic resumption
            localStorage.setItem('autoResumeData', JSON.stringify({
                session_id: sessionId,
                agent_api_session_id: agentApiSessionId,
                working_directory: workingDirectory,
                session_name: sessionName,
                timestamp: Date.now()
            }));
            
            // Clear URL parameters to avoid re-processing on refresh
            const newUrl = window.location.pathname;
            window.history.replaceState({}, document.title, newUrl);
            
            showToast('Auto-Resume', 'Session resumption parameters detected. Will attempt to resume session automatically.', 'info');
        }
    }
}

// Session History Functions
function checkSessionHistoryData() {
    const sessionData = localStorage.getItem('sessionHistoryData');
    if (sessionData) {
        try {
            const data = JSON.parse(sessionData);
            if (data.working_directory && document.getElementById('workingDirectory')) {
                document.getElementById('workingDirectory').value = data.working_directory;
            }
            if (data.session_name && document.getElementById('sessionName')) {
                document.getElementById('sessionName').value = data.session_name;
            }
            
            // Clear the localStorage data
            localStorage.removeItem('sessionHistoryData');
            
            // Show a toast notification
            showToast('Session Data Loaded', 'Working directory and session name have been set from your previous session history.', 'info');
        } catch (error) {
            console.error('Error parsing session history data:', error);
            localStorage.removeItem('sessionHistoryData');
        }
    }
}

function openSessionViewer() {
    window.open(`/session_viewer?agent=${agentConfig.type}`, '_blank');
}

// Agent Selection
function selectAgent() {
    fetch('/api/select_agent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ agent_type: agentConfig.type })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            console.log(`${agentConfig.name} agent selected:`, data.message);
            checkExistingSession();
        } else {
            showToast('Error', data.error || `Failed to select ${agentConfig.name} agent`, 'error');
        }
    })
    .catch(error => {
        console.error(`Error selecting ${agentConfig.name} agent:`, error);
        showToast('Error', `Failed to select ${agentConfig.name} agent`, 'error');
    });
}

// Socket Event Handlers
socket.on('connect', () => {
    console.log('Socket connected to server');
    socketReady = true;
    updateConnectionButtonState();
});

socket.on('disconnect', () => {
    console.log('Socket disconnected from server');
    socketReady = false;
    updateConnectionButtonState();
});

socket.on('connected', (data) => {
    console.log('Socket connected:', data);
});

socket.on('session_started', (data) => {
    console.log('Session started event received:', data);
    if (data.success) {
        console.log('Session started successfully, hiding connection screen');
        sessionStarting = false;
        updateConnectionButtonState();
        currentSessionId = data.session_id;
        hideConnectionScreen();
        enableInterface();
        startSessionTimer();
        
        // Show working directory
        if (data.working_directory) {
            document.getElementById('workingDirectoryDisplay').style.display = 'flex';
            document.getElementById('wdPath').textContent = data.working_directory;
        }
        
        // Load history if available
        if (data.history && data.history.length > 0) {
            loadMessageHistory(data.history);
        }
        
        addSystemMessage(`Connected to ${agentConfig.name} in ${data.working_directory}`);
        showToast('Connected', `${agentConfig.name} session started successfully`, 'success');
        
        // Load diffs for non-Claude agents only
        if (agentConfig.type !== 'claude' && typeof loadSessionDiffs === 'function') {
            loadSessionDiffs();
        }
    } else {
        showToast('Connection Failed', data.error || `Failed to start ${agentConfig.name} session`, 'error');
        sessionStarting = false;
        updateConnectionButtonState();
    }
});

socket.on('session_resumed', (data) => {
    console.log('Session resumed event received:', data);
    if (data.success) {
        console.log('Session resumed successfully, hiding connection screen');
        sessionStarting = false;
        updateConnectionButtonState();
        currentSessionId = data.session_id;
        hideConnectionScreen();
        enableInterface();
        startSessionTimer();
        
        // Show working directory
        if (data.working_directory) {
            document.getElementById('workingDirectoryDisplay').style.display = 'flex';
            document.getElementById('wdPath').textContent = data.working_directory;
        }

        // Load history
        if (data.history && data.history.length > 0) {
            loadMessageHistory(data.history);
        }

        // Add system message indicating session resumption
        addSystemMessage(`🔄 Resumed ${agentConfig.name} session with agent API session ID: ${data.agent_api_session_id}`);
        showToast('Session Resumed', `${agentConfig.name} session resumed successfully with ${data.message_count || 0} previous messages`, 'success');
        
        // Load diffs for non-Claude agents only
        if (agentConfig.type !== 'claude' && typeof loadSessionDiffs === 'function') {
            loadSessionDiffs();
        }
    } else {
        showToast('Resume Failed', data.error || `Failed to resume ${agentConfig.name} session`, 'error');
        sessionStarting = false;
        updateConnectionButtonState();
    }
});

socket.on('connection_result', (data) => {
    console.log('Connection result:', data);
    if (data.success) {
        currentSessionId = data.session_id;
        hideConnectionScreen();
        enableInterface();
        
        // Load history
        if (data.history && data.history.length > 0) {
            loadMessageHistory(data.history);
        }
        
        // Set remaining time
        if (data.session_time_remaining) {
            activeTime = 18000 - data.session_time_remaining; // 5 hours - remaining
            startSessionTimer();
        }
        
        addSystemMessage(`Connected to existing ${agentConfig.name} session`);
        showToast('Connected', 'Connected to existing session', 'success');
        
        // Load diffs for non-Claude agents only
        if (agentConfig.type !== 'claude' && typeof loadSessionDiffs === 'function') {
            loadSessionDiffs();
        }
    } else {
        showToast('Connection Failed', data.error || 'Failed to connect', 'error');
    }
});

socket.on('agent_output', (data) => {
    console.log(`${agentConfig.name} output received`);
    // For non-Claude agents, use shared terminal output handler
    if (agentConfig.type !== 'claude') {
        handleAgentOutput(data && typeof data.content === 'string' ? data.content : '');
    }
});

socket.on('session_warning', (data) => {
    console.log('Session warning:', data);
    showToast('Session Warning', data.message, 'warning');
    
    // Update timer display
    const timerValue = document.getElementById('timerValue');
    timerValue.classList.add('warning');
    
    if (data.remaining_seconds <= 60) {
        timerValue.classList.add('danger');
    }
});

socket.on('session_timeout', (data) => {
    console.log('Session timeout:', data);
    showToast('Session Timeout', data.message, 'error');
    resetInterface();
    // Optional: return to home on timeout
    // window.location.href = '/';
});

socket.on('session_ended', (data) => {
    console.log('Session ended:', data);
    showToast('Session Ended', data.message || 'Session has been terminated', 'info');
    // Do not immediately redirect; wait for session_closed to show chat message and then return.
    if (endSessionFallbackTimeoutId) {
        clearTimeout(endSessionFallbackTimeoutId);
        endSessionFallbackTimeoutId = null;
    }
    disconnectInProgress = false;
    redirectOnDisconnect = false;
});

socket.on('session_end_result', (data) => {
    console.log('Session end result:', data);
    if (data.success) {
        showToast('Session Ended', 'Session terminated successfully', 'info');
        // Do not immediately reset/redirect; session_closed will handle UX.
        if (endSessionFallbackTimeoutId) {
            clearTimeout(endSessionFallbackTimeoutId);
            endSessionFallbackTimeoutId = null;
        }
        disconnectInProgress = false;
        redirectOnDisconnect = false;
    } else {
        showToast('Error', 'Failed to end session', 'error');
    }
});

// New: unified session closed flow
socket.on('session_closed', (data) => {
    console.log('Session closed:', data);
    
    // Check if this was an empty session that was deleted
    if (data.empty_session) {
        // Show a system message indicating the empty session was not saved
        addSystemMessage('session closed (empty session not saved)');
        showToast('Session Not Saved', 'Empty session was not saved to history', 'info');
    } else {
        // Show normal session closed message
        addSystemMessage('session closed and saved');
        showToast('Session Saved', 'Session was saved to history', 'info');
    }
    
    // After 5 seconds, return to connection screen and close chat
    setTimeout(() => {
        resetInterface();
    }, 5000);
});

socket.on('command_status', (data) => {
    console.log('Command status:', data);
    if (!data.success) {
        showToast('Command Error', data.error || 'Failed to send command', 'error');
    }
});

socket.on('error', (data) => {
    console.error('Socket error:', data);
    showToast('Error', data.message || 'An error occurred', 'error');
});

socket.on('file_change', (data) => {
    console.log('File change event:', data);
    // Delegate to diff viewer if available
    if (typeof handleFileChangeEvent === 'function') {
        handleFileChangeEvent(data);
    }
});

// Connection Functions
function checkExistingSession() {
    fetch(`/api/status/${agentConfig.type}`)
        .then(response => response.json())
        .then(data => {
            const existingSessionNotice = document.getElementById('existingSessionNotice');
            if (existingSessionNotice) {
                if (data.active) {
                    existingSessionNotice.style.display = 'block';
                } else {
                    existingSessionNotice.style.display = 'none';
                }
            }
            
            // Check for auto-resume data
            checkAutoResumeData(data);
        })
        .catch(error => {
            console.error('Error checking existing session:', error);
            // Hide the notice on error to be safe
            const existingSessionNotice = document.getElementById('existingSessionNotice');
            if (existingSessionNotice) {
                existingSessionNotice.style.display = 'none';
            }
            
            // Still check for auto-resume data even on error
            checkAutoResumeData(null);
        });
}

function checkAutoResumeData(sessionStatus) {
    const autoResumeData = localStorage.getItem('autoResumeData');
    if (autoResumeData) {
        try {
            const data = JSON.parse(autoResumeData);
            
            // Check if data is not too old (5 minutes)
            const dataAge = Date.now() - data.timestamp;
            if (dataAge > 5 * 60 * 1000) {
                console.log('Auto-resume data is too old, removing');
                localStorage.removeItem('autoResumeData');
                return;
            }
            
            console.log('Auto-resume data found:', data);
            
            // Clear the auto-resume data to prevent re-processing
            localStorage.removeItem('autoResumeData');
            
            // If there's no active session, attempt to resume
            if (!sessionStatus || !sessionStatus.active) {
                console.log('No active session found, attempting to resume with auto-resume data');
                attemptAutoResume(data);
            } else {
                console.log('Active session already exists, connecting to existing session instead');
                // Connect to existing session instead of resuming
                setTimeout(() => {
                    connectToExisting();
                }, 1000);
            }
        } catch (error) {
            console.error('Error parsing auto-resume data:', error);
            localStorage.removeItem('autoResumeData');
        }
    }
}

function attemptAutoResume(resumeData) {
    console.log('Attempting auto-resume with data:', resumeData);
    
    if (!socketReady) {
        showToast('Connection Error', 'Please wait for the connection to be established', 'warning');
        return;
    }
    
    // Show loading state
    showToast('Auto-Resuming', 'Attempting to resume session automatically...', 'info');
    
    // Emit resume_agent_session event
    socket.emit('resume_agent_session', {
        agent_type: agentConfig.type,
        session_id: resumeData.session_id,
        device_id: deviceId
    });
}

function connectToExisting() {
    if (!socketReady) {
        showToast('Connection Error', 'Please wait for the connection to be established', 'warning');
        return;
    }
    socket.emit('connect_to_session', { agent_type: agentConfig.type, device_id: deviceId });
}

function updateConnectionButtonState() {
    const connectButton = document.getElementById('connectButton');
    const connectToExistingBtn = document.querySelector('[onclick="connectToExisting()"]');
    const statusDot = document.getElementById('connectionStatusDot');
    const statusText = document.getElementById('connectionStatusText');
    
    if (connectButton) {
        if (socketReady && !sessionStarting) {
            connectButton.disabled = false;
            const buttonText = document.getElementById('connectButtonText');
            if (buttonText) {
                buttonText.textContent = agentConfig.name;
            } else {
                connectButton.textContent = `Connect to ${agentConfig.name}`;
            }
        } else {
            connectButton.disabled = true;
            if (sessionStarting) {
                connectButton.textContent = 'Starting...';
            } else {
                connectButton.textContent = 'Connecting...';
            }
        }
    }
    
    if (connectToExistingBtn) {
        connectToExistingBtn.disabled = !socketReady;
    }
    
    // Update visual status indicator
    if (statusDot && statusText) {
        if (socketReady) {
            statusDot.style.background = '#4CAF50'; // Green
            statusText.textContent = sessionStarting ? 'Starting...' : 'Ready to connect';
        } else {
            statusDot.style.background = '#ff6b35'; // Orange
            statusText.textContent = 'Connecting...';
        }
    }
}

// Setup connection form if it exists
function setupConnectionForm() {
    console.log('setupConnectionForm called');
    const connectionForm = document.getElementById('connectionForm');
    if (connectionForm) {
        console.log('Connection form found, setting up event listener');
        connectionForm.addEventListener('submit', (e) => {
            e.preventDefault();
            if (sessionStarting) {
                return;
            }
            
            // Check if socket is ready
            if (!socketReady) {
                showToast('Connection Error', 'Please wait for the connection to be established', 'warning');
                return;
            }
            
            const sessionName = document.getElementById('sessionName').value.trim();
            const workingDirectory = document.getElementById('workingDirectory').value.trim();
            
            if (!workingDirectory) {
                showToast('Error', 'Working directory is required', 'error');
                return;
            }
            
            sessionStarting = true;
            updateConnectionButtonState();

            // Validate directory
            console.log('Validating directory:', workingDirectory);
            fetch('/api/validate_directory', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ directory: workingDirectory })
            })
            .then(response => response.json())
            .then(data => {
                console.log('Directory validation result:', data);
                if (data.valid) {
                    console.log('Emitting start_session event with:', {
                        agent_type: agentConfig.type,
                        session_name: sessionName,
                        working_directory: data.path,
                        device_id: deviceId
                    });
                    socket.emit('start_session', {
                        agent_type: agentConfig.type,
                        session_name: sessionName,
                        working_directory: data.path,
                        device_id: deviceId
                    });
                } else if (data.can_create) {
                    // Ask user if they want to create the directory
                    if (confirm(`The directory "${workingDirectory}" does not exist. Would you like to create it?`)) {
                        createDirectoryAndStartSession(workingDirectory, sessionName);
                    } else {
                        sessionStarting = false;
                        updateConnectionButtonState();
                    }
                } else {
                    showToast('Invalid Directory', data.error, 'error');
                    sessionStarting = false;
                    updateConnectionButtonState();
                }
            })
            .catch(error => {
                console.error('Error validating directory:', error);
                showToast('Error', 'Failed to validate directory', 'error');
                sessionStarting = false;
                updateConnectionButtonState();
            });
        });
    } else {
        console.error('Connection form not found!');
    }
}

function createDirectoryAndStartSession(directory, sessionName) {
    fetch('/api/create_directory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ directory: directory })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Success', 'Directory created successfully', 'success');
            socket.emit('start_session', {
                agent_type: agentConfig.type,
                session_name: sessionName,
                working_directory: data.path,
                device_id: deviceId
            });
        } else {
            showToast('Error', data.error, 'error');
            sessionStarting = false;
            updateConnectionButtonState();
        }
    })
    .catch(error => {
        showToast('Error', 'Failed to create directory', 'error');
        sessionStarting = false;
        updateConnectionButtonState();
    });
}

// UI Functions
function hideConnectionScreen() {
    console.log('hideConnectionScreen called');
    const connectionScreen = document.getElementById('connectionScreen');
    if (connectionScreen) {
        console.log('Connection screen found, adding hidden class');
        connectionScreen.classList.add('hidden');
    } else {
        console.error('Connection screen element not found!');
    }
}

function showConnectionScreen() {
    const connectionScreen = document.getElementById('connectionScreen');
    if (connectionScreen) {
        connectionScreen.classList.remove('hidden');
    }
}

function enableInterface() {
    isConnected = true;
    document.getElementById('inputField').disabled = false;
    document.getElementById('sendButton').disabled = false;
    document.getElementById('enterButton').disabled = false;
    document.getElementById('backspaceButton').disabled = false;
    document.getElementById('disconnectBtn').style.display = 'block';
    document.getElementById('sessionTimer').style.display = 'flex';
    document.getElementById('statusDot').classList.remove('disconnected');
    document.getElementById('statusText').textContent = 'Connected';
    document.getElementById('inputField').focus();
}

function resetInterface() {
    isConnected = false;
    currentSessionId = null;
    document.getElementById('inputField').disabled = true;
    document.getElementById('sendButton').disabled = true;
    document.getElementById('enterButton').disabled = true;
    document.getElementById('backspaceButton').disabled = true;
    document.getElementById('disconnectBtn').style.display = 'none';
    document.getElementById('sessionTimer').style.display = 'none';
    document.getElementById('statusDot').classList.add('disconnected');
    document.getElementById('statusText').textContent = 'Disconnected';
    document.getElementById('workingDirectoryDisplay').style.display = 'none';
    clearInterval(sessionTimer);
    showConnectionScreen();
    finalizeAgentMessage();
    
    // Clear diffs UI if available
    if (typeof clearDiffs === 'function') {
        try { clearDiffs(); } catch (e) { /* no-op */ }
    }
    
    // Refresh session status when returning to connection screen
    setTimeout(() => {
        checkExistingSession();
    }, 500);
}

// Message Handling
function handleAgentOutput(content) {
    // Hide thinking cursor when we start receiving output
    hideThinkingCursor();
    
    if (messageTimeout) {
        clearTimeout(messageTimeout);
    }
    
    agentMessageBuffer += content;
    
    if (!currentAgentMessage) {
        currentAgentMessage = createMessage('', 'agent');
        document.getElementById('chatContainer').appendChild(currentAgentMessage);
    }
    
    const messageContent = currentAgentMessage.querySelector('.message-content');
    const processed = ansiUp.ansi_to_html(agentMessageBuffer);
    messageContent.innerHTML = `<div class="terminal-output">${processed}</div>`;
    
    scrollToBottom();
    
    messageTimeout = setTimeout(() => {
        finalizeAgentMessage();
    }, 500);
}

function finalizeAgentMessage() {
    if (messageTimeout) {
        clearTimeout(messageTimeout);
        messageTimeout = null;
    }
    
    if (currentAgentMessage && agentMessageBuffer) {
        const messageContent = currentAgentMessage.querySelector('.message-content');
        const timestamp = document.createElement('div');
        timestamp.className = 'timestamp';
        timestamp.textContent = new Date().toLocaleTimeString();
        // Set timestamp color based on agent type
        let timestampColor = 'rgba(255, 107, 53, 0.3)'; // Claude default
        if (agentConfig.type === 'gemini') {
            timestampColor = 'rgba(66, 133, 244, 0.3)';
        } else if (agentConfig.type === 'cursor') {
            timestampColor = 'rgba(99, 102, 241, 0.3)';
        } else if (agentConfig.type === 'codex') {
            timestampColor = 'rgba(236, 72, 153, 0.3)';
        }
        timestamp.style = `font-size: 11px; color: ${timestampColor}; margin-top: 5px;`;
        messageContent.appendChild(timestamp);
    }
    
    currentAgentMessage = null;
    agentMessageBuffer = '';
}

function createMessage(content, type = 'user') {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;
    
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = type === 'user' ? 'U' : type === 'agent' ? agentConfig.avatar : 'S';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    if (type === 'agent') {
        contentDiv.innerHTML = `<div class="terminal-output">${content}</div>`;
    } else if (type === 'user') {
        contentDiv.textContent = content;
    } else {
        contentDiv.innerHTML = content;
    }
    
    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);
    
    return messageDiv;
}

function addMessage(content, type = 'user') {
    finalizeAgentMessage();
    const messageDiv = createMessage(content, type);
    document.getElementById('chatContainer').appendChild(messageDiv);
    scrollToBottom();
}

function addSystemMessage(message) {
    addMessage(message, 'system');
}

function loadMessageHistory(messages) {
    const container = document.getElementById('chatContainer');
    container.innerHTML = '';
    
    messages.forEach(msg => {
        if (msg.type === 'agent') {
            const messageDiv = createMessage('', 'agent');
            const messageContent = messageDiv.querySelector('.message-content');
            const processed = ansiUp.ansi_to_html(msg.content);
            messageContent.innerHTML = `<div class="terminal-output">${processed}</div>`;
            container.appendChild(messageDiv);
        } else {
            addMessage(msg.content, msg.type);
        }
    });
    
    scrollToBottom();
}

function scrollToBottom() {
    const container = document.getElementById('chatContainer');
    container.scrollTop = container.scrollHeight;
}

// Thinking Cursor Functions
function showThinkingCursor() {
    // Remove any existing thinking cursor
    hideThinkingCursor();
    
    const container = document.getElementById('chatContainer');
    const thinkingMessage = createMessage('', 'agent');
    thinkingMessage.id = 'thinking-cursor-message';
    
    const messageContent = thinkingMessage.querySelector('.message-content');
    messageContent.innerHTML = `
        <div class="thinking-cursor">
            <div class="thinking-dots">
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
                <span class="thinking-dot"></span>
            </div>
            <span class="thinking-text">${agentConfig.name} is thinking...</span>
        </div>
    `;
    
    container.appendChild(thinkingMessage);
    scrollToBottom();
}

function hideThinkingCursor() {
    const thinkingMessage = document.getElementById('thinking-cursor-message');
    if (thinkingMessage) {
        thinkingMessage.remove();
    }
}

// Send Command
function sendCommand() {
    const command = document.getElementById('inputField').value.trim();
    if (!command || !isConnected) return;
    
    finalizeAgentMessage();
    addMessage(command, 'user');
    
    // Show thinking cursor animation
    showThinkingCursor();
    
    socket.emit('send_command', { 
        agent_type: agentConfig.type,
        command: command,
        device_id: deviceId
    });
    
    document.getElementById('inputField').value = '';
    document.getElementById('inputField').focus();
}

// Send Enter Key Command
function sendEnterKey() {
    if (!isConnected) return;
    
    finalizeAgentMessage();
    
    // Create a special message that shows the enter key action
    const messageDiv = createMessage('', 'user');
    const contentDiv = messageDiv.querySelector('.message-content');
    contentDiv.innerHTML = `
        <span class="special-key">Enter Key</span>
        <span class="command-preview">Send Enter</span>
    `;
    document.getElementById('chatContainer').appendChild(messageDiv);
    
    socket.emit('send_enter_key', { 
        agent_type: agentConfig.type,
        device_id: deviceId
    });
    
    scrollToBottom();
}

// Send Backspace Key Command
function sendBackspaceKey(count = 1) {
    if (!isConnected) return;
    
    finalizeAgentMessage();
    
    // Create a special message that shows the backspace key action
    const messageDiv = createMessage('', 'user');
    const contentDiv = messageDiv.querySelector('.message-content');
    contentDiv.innerHTML = `
        <span class="special-key">Backspace Key</span>
        <span class="command-preview">Send ${count} Backspace${count > 1 ? 's' : ''}</span>
    `;
    document.getElementById('chatContainer').appendChild(messageDiv);
    
    socket.emit('send_backspace_key', { 
        agent_type: agentConfig.type,
        device_id: deviceId,
        count: count
    });
    
    scrollToBottom();
}

// Send Special Command
function sendSpecialCommand(command, keyDescription) {
    if (!isConnected) return;
    
    finalizeAgentMessage();
    
    // Create a special message that shows the key description and command preview
    const messageDiv = createMessage('', 'user');
    const contentDiv = messageDiv.querySelector('.message-content');
    contentDiv.innerHTML = `
        <span class="special-key">${keyDescription}</span>
        <span class="command-preview">${getCommandPreview(command)}</span>
    `;
    document.getElementById('chatContainer').appendChild(messageDiv);
    
    socket.emit('send_command', { 
        agent_type: agentConfig.type,
        command: command,
        device_id: deviceId
    });
    
    scrollToBottom();
}

// Get a human-readable preview of the command
function getCommandPreview(command) {
    const previews = {
        '\x03': 'Interrupt',
        '\x04': 'EOF',
        '\x0c': 'Clear Screen',
        '\x15': 'Clear Line',
        '\x0b': 'Clear to End',
        '\x01': 'Line Start',
        '\x05': 'Line End',
        '\x17': 'Delete Word',
        '\x1a': 'Suspend',
        '\x1b[A': 'Up Arrow',
        '\x1b[B': 'Down Arrow',
        '\x1b[C': 'Right Arrow',
        '\x1b[D': 'Left Arrow',
        '\t': 'Tab',
        '\x1b': 'Escape',
        '\x08': 'Backspace',
        '\x1b[3~': 'Delete',
        '\x1b[H': 'Home',
        '\x1b[F': 'End',
        '\x1b[5~': 'Page Up',
        '\x1b[6~': 'Page Down'
    };
    
    return previews[command] || 'Special Command';
}

// Handle special keys for console interaction
function handleSpecialKeys(e) {
    if (!isConnected) return;
    
    let command = '';
    let shouldSend = false;
    let keyDescription = '';
    
    // Handle Ctrl+key combinations first
    if (e.ctrlKey) {
        switch(e.key) {
            case 'c':
                command = '\x03'; // Ctrl+C (interrupt)
                keyDescription = 'Ctrl+C (Interrupt)';
                shouldSend = true;
                break;
            case 'd':
                command = '\x04'; // Ctrl+D (EOF)
                keyDescription = 'Ctrl+D (EOF)';
                shouldSend = true;
                break;
            case 'l':
                command = '\x0c'; // Ctrl+L (clear screen)
                keyDescription = 'Ctrl+L (Clear Screen)';
                shouldSend = true;
                break;
            case 'u':
                command = '\x15'; // Ctrl+U (clear line)
                keyDescription = 'Ctrl+U (Clear Line)';
                shouldSend = true;
                break;
            case 'k':
                command = '\x0b'; // Ctrl+K (clear from cursor to end)
                keyDescription = 'Ctrl+K (Clear to End)';
                shouldSend = true;
                break;
            case 'a':
                command = '\x01'; // Ctrl+A (move to beginning of line)
                keyDescription = 'Ctrl+A (Line Start)';
                shouldSend = true;
                break;
            case 'e':
                command = '\x05'; // Ctrl+E (move to end of line)
                keyDescription = 'Ctrl+E (Line End)';
                shouldSend = true;
                break;
            case 'w':
                command = '\x17'; // Ctrl+W (delete word backward)
                keyDescription = 'Ctrl+W (Delete Word)';
                shouldSend = true;
                break;
            case 'z':
                command = '\x1a'; // Ctrl+Z (suspend)
                keyDescription = 'Ctrl+Z (Suspend)';
                shouldSend = true;
                break;
        }
    }
    
    // Handle other special keys
    if (!shouldSend) {
        switch(e.key) {
            case 'ArrowUp':
                command = '\x1b[A'; // ANSI escape sequence for up arrow
                keyDescription = '↑ (Up Arrow)';
                shouldSend = true;
                break;
            case 'ArrowDown':
                command = '\x1b[B'; // ANSI escape sequence for down arrow
                keyDescription = '↓ (Down Arrow)';
                shouldSend = true;
                break;
            case 'ArrowLeft':
                command = '\x1b[D'; // ANSI escape sequence for left arrow
                keyDescription = '← (Left Arrow)';
                shouldSend = true;
                break;
            case 'ArrowRight':
                command = '\x1b[C'; // ANSI escape sequence for right arrow
                keyDescription = '→ (Right Arrow)';
                shouldSend = true;
                break;
            case 'Enter':
                if (e.ctrlKey) {
                    command = '\n'; // Ctrl+Enter for newline
                    keyDescription = 'Ctrl+Enter (Newline)';
                    shouldSend = true;
                }
                break;
            case 'Tab':
                e.preventDefault();
                command = '\t'; // Tab for autocomplete
                keyDescription = 'Tab (Autocomplete)';
                shouldSend = true;
                break;
            case 'Escape':
                command = '\x1b'; // Escape key
                keyDescription = 'Escape';
                shouldSend = true;
                break;
            case 'Backspace':
                if (e.ctrlKey) {
                    command = '\x08'; // Ctrl+Backspace
                    keyDescription = 'Ctrl+Backspace';
                    shouldSend = true;
                }
                break;
            case 'Delete':
                command = '\x1b[3~'; // Delete key
                keyDescription = 'Delete';
                shouldSend = true;
                break;
            case 'Home':
                command = '\x1b[H'; // Home key
                keyDescription = 'Home';
                shouldSend = true;
                break;
            case 'End':
                command = '\x1b[F'; // End key
                keyDescription = 'End';
                shouldSend = true;
                break;
            case 'PageUp':
                command = '\x1b[5~'; // Page Up
                keyDescription = 'Page Up';
                shouldSend = true;
                break;
            case 'PageDown':
                command = '\x1b[6~'; // Page Down
                keyDescription = 'Page Down';
                shouldSend = true;
                break;
            case 'F1':
                command = '\x1bOP'; // F1 key
                keyDescription = 'F1';
                shouldSend = true;
                break;
            case 'F2':
                command = '\x1bOQ'; // F2 key
                keyDescription = 'F2';
                shouldSend = true;
                break;
            case 'F3':
                command = '\x1bOR'; // F3 key
                keyDescription = 'F3';
                shouldSend = true;
                break;
            case 'F4':
                command = '\x1bOS'; // F4 key
                keyDescription = 'F4';
                shouldSend = true;
                break;
            case 'F5':
                command = '\x1b[15~'; // F5 key
                keyDescription = 'F5';
                shouldSend = true;
                break;
            case 'F6':
                command = '\x1b[17~'; // F6 key
                keyDescription = 'F6';
                shouldSend = true;
                break;
            case 'F7':
                command = '\x1b[18~'; // F7 key
                keyDescription = 'F7';
                shouldSend = true;
                break;
            case 'F8':
                command = '\x1b[19~'; // F8 key
                keyDescription = 'F8';
                shouldSend = true;
                break;
            case 'F9':
                command = '\x1b[20~'; // F9 key
                keyDescription = 'F9';
                shouldSend = true;
                break;
            case 'F10':
                command = '\x1b[21~'; // F10 key
                keyDescription = 'F10';
                shouldSend = true;
                break;
            case 'F11':
                command = '\x1b[23~'; // F11 key
                keyDescription = 'F11';
                shouldSend = true;
                break;
            case 'F12':
                command = '\x1b[24~'; // F12 key
                keyDescription = 'F12';
                shouldSend = true;
                break;
        }
    }
    
    if (shouldSend) {
        e.preventDefault();
        
        // Send special command with inline display
        sendSpecialCommand(command, keyDescription);
    }
}

// Session Timer
function startSessionTimer() {
    sessionStartTime = Date.now();
    
    sessionTimer = setInterval(() => {
        activeTime++;
        const remaining = 18000 - activeTime; // 5 hours = 18000 seconds
        
        const timerValue = document.getElementById('timerValue');
        timerValue.textContent = formatTime(activeTime);
        
        // Update timer color based on remaining time
        if (remaining <= 60) {
            timerValue.classList.add('danger');
        } else if (remaining <= 600) {
            timerValue.classList.add('warning');
        }
    }, 1000);
}

// Disconnect Dialog
function showDisconnectDialog() {
    document.getElementById('disconnectDialog').classList.add('active');
}

function hideDisconnectDialog() {
    document.getElementById('disconnectDialog').classList.remove('active');
    disconnectInProgress = false;
}

function confirmDisconnect() {
    // Send exit command to agent first
    if (isConnected) {
        disconnectInProgress = true;
        redirectOnDisconnect = true;
        // socket.emit('send_command', { 
        //     agent_type: agentConfig.type,
        //     command: agentConfig.exitCommand,
        //     device_id: deviceId
        // });
        
        // Always proceed with session end after sending exit command
        // Don't wait for command status confirmation
        setTimeout(() => {
            socket.emit('end_session', { agent_type: agentConfig.type, graceful: true });
            // Fallback: if the server doesn't respond in time, reset UI locally and go home
            endSessionFallbackTimeoutId = setTimeout(() => {
                if (disconnectInProgress) {
                    resetInterface();
                    if (typeof clearDiffs === 'function') {
                        try { clearDiffs(); } catch (e) {}
                    }
                    showToast('Disconnected', 'Session ended locally (no server response)', 'warning');
                    hideDisconnectDialog();
                    disconnectInProgress = false;
                    redirectOnDisconnect = false;
                    window.location.href = '/';
                }
            }, 2000);
            
            // Close dialog immediately; handlers will manage state
            hideDisconnectDialog();
        }, 1000); // Reduced timeout to 1 second
    } else {
        socket.emit('end_session', { agent_type: agentConfig.type, graceful: true });
        hideDisconnectDialog();
        // Not connected: go home right away
        window.location.href = '/';
    }
}

// Help Dialog
function showHelpDialog() {
    document.getElementById('helpDialog').classList.add('active');
}

function hideHelpDialog() {
    document.getElementById('helpDialog').classList.remove('active');
}

// Event Listeners Setup
function setupEventListeners() {
    document.getElementById('sendButton').addEventListener('click', sendCommand);
    document.getElementById('enterButton').addEventListener('click', sendEnterKey);
    document.getElementById('backspaceButton').addEventListener('click', () => sendBackspaceKey(1));
    document.getElementById('inputField').addEventListener('keydown', handleSpecialKeys);
    document.getElementById('inputField').addEventListener('keypress', (e) => {
        if (e.key === 'Enter' && !e.shiftKey && !e.ctrlKey) {
            e.preventDefault();
            sendCommand();
        }
    });
}

// Mobile Keyboard Detection Functions
function initializeMobileKeyboardDetection() {
    // Only run on mobile devices
    if (!isMobileDevice()) return;
    
    // Store initial viewport height - prefer visualViewport for accurate mobile measurements
    initialViewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    
    // Use Visual Viewport API if available (modern browsers)
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', handleViewportChange);
    } else {
        // Fallback for older browsers
        window.addEventListener('resize', handleViewportChangeFallback);
    }
    
    // Also listen for focus/blur on input fields
    const inputField = document.getElementById('inputField');
    if (inputField) {
        inputField.addEventListener('focus', handleInputFocus);
        inputField.addEventListener('blur', handleInputBlur);
    }
}

function isMobileDevice() {
    // Check if it's a touch device first
    const hasTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
    
    // Get current viewport dimensions
    const currentWidth = window.innerWidth;
    const currentHeight = window.innerHeight;
    
    // Basic mobile user agent check
    const isMobileUA = /Android|webOS|iPhone|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    
    // iPad detection (often reports as desktop in user agent)
    const isIPad = /iPad/i.test(navigator.userAgent) || 
                   (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
    
    // For keyboard handling, we only want to treat devices as "mobile" if:
    // 1. They have a mobile user agent AND current width is narrow (< 768px)
    // 2. OR they're touch devices with narrow current width (< 768px)
    // This excludes tablets, fold phones when unfolded, and desktop touch screens
    
    if (isMobileUA && currentWidth < 768) {
        return true; // Definitely a phone in portrait/narrow mode
    }
    
    if (hasTouch && currentWidth < 768 && !isIPad) {
        return true; // Touch device in narrow mode, but not iPad
    }
    
    // Special case for very tall narrow screens (some phones in landscape)
    if (hasTouch && currentWidth < 900 && currentHeight < 500 && isMobileUA) {
        return true; // Likely a phone in landscape
    }
    
    return false; // Everything else (tablets, fold phones unfolded, desktops)
}

function handleViewportChange() {
    const currentHeight = window.visualViewport.height;
    const heightDifference = initialViewportHeight - currentHeight;
    
    // Keyboard is likely visible if viewport shrunk by more than 150px
    const wasKeyboardVisible = keyboardVisible;
    keyboardVisible = heightDifference > 150;
    keyboardHeight = keyboardVisible ? heightDifference : 0;
    
    if (keyboardVisible !== wasKeyboardVisible) {
        updateLayoutForKeyboard();
    }
}

function handleViewportChangeFallback() {
    const currentHeight = window.innerHeight;
    const heightDifference = initialViewportHeight - currentHeight;
    
    // Keyboard is likely visible if viewport shrunk by more than 150px
    const wasKeyboardVisible = keyboardVisible;
    keyboardVisible = heightDifference > 150;
    keyboardHeight = keyboardVisible ? heightDifference : 0;
    
    if (keyboardVisible !== wasKeyboardVisible) {
        updateLayoutForKeyboard();
    }
}

function handleInputFocus() {
    // Small delay to allow keyboard to appear
    setTimeout(() => {
        if (!keyboardVisible && window.visualViewport) {
            const currentHeight = window.visualViewport.height;
            const heightDifference = initialViewportHeight - currentHeight;
            if (heightDifference > 150) {
                keyboardVisible = true;
                keyboardHeight = heightDifference;
                updateLayoutForKeyboard();
            }
        }
    }, 300);
}

function handleInputBlur() {
    // Small delay to allow keyboard to disappear
    setTimeout(() => {
        if (keyboardVisible) {
            const currentHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
            const heightDifference = initialViewportHeight - currentHeight;
            if (heightDifference < 150) {
                keyboardVisible = false;
                keyboardHeight = 0;
                updateLayoutForKeyboard();
            }
        }
    }, 300);
}

function updateLayoutForKeyboard() {
    const container = document.querySelector('.container');
    const body = document.body;
    
    if (keyboardVisible) {
        body.classList.add('keyboard-visible');
        container.classList.add('keyboard-active');
        // Set a CSS custom property with the keyboard height
        document.documentElement.style.setProperty('--keyboard-height', keyboardHeight + 'px');
        
        // Ensure chat scrolls to bottom when keyboard appears
        setTimeout(() => {
            scrollToBottom();
        }, 100);
    } else {
        body.classList.remove('keyboard-visible');
        container.classList.remove('keyboard-active');
        document.documentElement.style.removeProperty('--keyboard-height');
        
        // Ensure chat scrolls to bottom when keyboard disappears
        setTimeout(() => {
            scrollToBottom();
        }, 100);
    }
}

// Handle orientation and screen size changes
function handleScreenChange() {
    // Re-evaluate if device should be treated as mobile after orientation change
    const wasMobile = keyboardVisible || document.body.classList.contains('keyboard-visible');
    
    // Clean up existing state if device is no longer considered mobile
    if (!isMobileDevice() && wasMobile) {
        document.body.classList.remove('keyboard-visible');
        const container = document.querySelector('.container');
        if (container) {
            container.classList.remove('keyboard-active');
        }
        document.documentElement.style.removeProperty('--keyboard-height');
        keyboardVisible = false;
        keyboardHeight = 0;
    }
    
    // Re-initialize keyboard detection if needed
    if (isMobileDevice()) {
        // Update the initial viewport height for new orientation
        initialViewportHeight = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    setupEventListeners();
    initializeTabs();
    initializeResponsiveHeader();
    initializeMobileKeyboardDetection();
    // Initialize diff viewer if the function is available
    if (typeof initializeDiffViewer === 'function') {
        initializeDiffViewer();
    }
    
    // Listen for orientation changes and resize events
    window.addEventListener('orientationchange', function() {
        // Small delay to allow orientation change to complete
        setTimeout(handleScreenChange, 100);
    });
    
    window.addEventListener('resize', function() {
        // Debounce resize events
        clearTimeout(window.resizeTimeout);
        window.resizeTimeout = setTimeout(handleScreenChange, 250);
    });
});

// Connection Panel Session History Functions (for compatibility)
function toggleConnectionHistory() {
    const historySection = document.getElementById('connectionSessionHistory');
    const showHistoryBtn = document.getElementById('showHistoryBtn');
    
    if (historySection && showHistoryBtn) {
        if (historySection.style.display === 'none') {
            historySection.style.display = 'block';
            showHistoryBtn.textContent = '📚 Hide Session History';
            loadConnectionSessions();
        } else {
            historySection.style.display = 'none';
            showHistoryBtn.textContent = '📚 View Session History';
        }
    }
}

function loadConnectionSessions() {
    fetch(`/api/sessions/${agentConfig.type}`)
        .then(response => response.json())
        .then(sessions => {
            const container = document.getElementById('connectionSessionList');
            if (!container) return;
            
            container.innerHTML = '';
            
            if (sessions.length === 0) {
                container.innerHTML = `<div style="text-align: center; color: var(--${agentConfig.type}-text-muted); padding: 20px;">No previous sessions found</div>`;
                return;
            }
            
            sessions.forEach(session => {
                const item = document.createElement('div');
                item.className = 'connection-session-item';
                
                const startTime = new Date(session.start_time);
                const hasResumeButton = session.agent_api_session_id ? 
                    `<button class="connection-resume-btn" onclick="resumeConnectionSession('${session.id}', '${session.agent_api_session_id}', event)" title="Resume session">↻</button>` : '';
                
                item.innerHTML = `
                    ${hasResumeButton}
                    <div class="session-name">${session.name || 'Unnamed Session'}</div>
                    <div class="session-meta">
                        <span>${startTime.toLocaleDateString()}</span>
                        <span>${session.message_count} messages</span>
                    </div>
                `;
                
                item.onclick = () => viewConnectionSession(session.id);
                container.appendChild(item);
            });
        })
        .catch(error => {
            console.error('Error loading connection sessions:', error);
            const container = document.getElementById('connectionSessionList');
            if (container) {
                container.innerHTML = `<div style="text-align: center; color: var(--${agentConfig.type}-primary); padding: 20px;">Failed to load sessions</div>`;
            }
        });
}

function viewConnectionSession(sessionId) {
    // Open the session viewer in a new window/tab
    const viewerUrl = `/session_viewer?agent=${agentConfig.type}&session=${sessionId}`;
    window.open(viewerUrl, '_blank');
}

function startSessionFromHistory(workingDirectory, sessionName) {
    // Set the working directory and session name
    if (document.getElementById('workingDirectory')) {
        document.getElementById('workingDirectory').value = workingDirectory;
    }
    if (document.getElementById('sessionName')) {
        document.getElementById('sessionName').value = sessionName;
    }
    
    // Hide the history section
    const historySection = document.getElementById('connectionSessionHistory');
    const showHistoryBtn = document.getElementById('showHistoryBtn');
    if (historySection && showHistoryBtn) {
        historySection.style.display = 'none';
        showHistoryBtn.textContent = '📚 View Session History';
    }
    
    showToast('Info', `Working directory and session name set from history. Click "Connect to ${agentConfig.name}" to start.`, 'info');
}

function resumeConnectionSession(sessionId, agentApiSessionId, event) {
    // Prevent the session item click event from firing
    event.stopPropagation();
    
    if (!socketReady) {
        showToast('Connection Error', 'Please wait for the connection to be established', 'warning');
        return;
    }
    
    // Show loading state
    showToast('Resuming Session', 'Attempting to resume session...', 'info');
    
    // Emit resume_agent_session event
    socket.emit('resume_agent_session', {
        agent_type: agentConfig.type,
        session_id: sessionId,
        device_id: deviceId
    });
}

// Tab Management Functions
function initializeTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const tabName = button.getAttribute('data-tab');
            switchTab(tabName);
        });
    });
}

function switchTab(tabName) {
    // Update tab buttons
    document.querySelectorAll('.tab-button').forEach(btn => {
        btn.classList.remove('active');
    });
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');
    
    // Update tab contents
    document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
    });
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    // Initialize components when switching to their tabs
    if (tabName === 'project' && !projectTree) {
        initializeProjectTree();
    } else if (tabName === 'editor' && !aceEditor) {
        initializeAceEditor();
    }
}

// Project Tree Functions
function initializeProjectTree() {
    const treeContainer = document.getElementById('projectTree');
    if (!treeContainer) return;
    
    // Initialize jstree
    projectTree = $(treeContainer).jstree({
        'core': {
            'data': function(node, callback) {
                // For root node, use empty path (will be resolved to working directory by backend)
                // For other nodes, use the stored relative path from the node data
                let path;
                console.log('node:', node);
                if (node.id === '#') {
                    path = '';
                } else {
                    // Use the relative path stored in node data, or fall back to node.id
                    path = node.original && node.original.relative_path ? node.original.relative_path : node.id;
                }
                
                fetch('/api/files/list', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        path: path,
                        agent_type: agentConfig.type
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const currentPath = data.path;
                        const items = data.items.map(item => {
                            // Calculate relative path from working directory
                            let relativePath;
                            if (path === '' || path === '.') {
                                relativePath = item.name;
                            } else {
                                relativePath = path + '/' + item.name;
                            }
                            
                            return {
                                id: item.path, // Keep full path as ID for uniqueness
                                text: item.name,
                                type: item.is_directory ? 'folder' : getFileType(item.name),
                                children: item.is_directory,
                                original: {
                                    ...item,
                                    relative_path: relativePath // Store relative path for future expansions
                                }
                            };
                        });
                        callback(items);
                    } else {
                        console.error('Error loading files:', data.error);
                        showToast('Error', data.error || 'Failed to load directory', 'error');
                        callback([]);
                    }
                })
                .catch(error => {
                    console.error('Error loading files:', error);
                    showToast('Error', 'Failed to load directory', 'error');
                    callback([]);
                });
            },
            'check_callback': true,
            'themes': {
                'name': 'default',
                'dots': true,
                'icons': true
            }
        },
        'plugins': ['types'],
        'types': {
            'default': {
                'icon': 'jstree-file'
            },
            'folder': {
                'icon': 'jstree-folder'
            },
            'python': {
                'icon': 'file-python'
            },
            'javascript': {
                'icon': 'file-js'
            },
            'html': {
                'icon': 'file-html'
            },
            'css': {
                'icon': 'file-css'
            },
            'json': {
                'icon': 'file-json'
            },
            'text': {
                'icon': 'file-txt'
            }
        }
    });
    
    // Handle node selection
    projectTree.on('select_node.jstree', function(e, data) {
        const node = data.node;
        
        // Check if it's a directory - handle nested original structure
        const nodeData = node.original && node.original.original ? node.original.original : node.original;
        
        if (nodeData && nodeData.is_directory) {
            // If it's a folder, toggle its expansion state
            if (projectTree.jstree('is_open', node)) {
                projectTree.jstree('close_node', node);
            } else {
                projectTree.jstree('open_node', node);
            }
        } else {
            // If it's a file, open it in the editor
            const filePath = nodeData ? nodeData.path : node.id;
            const fileName = node.text;
            openFileInEditor(filePath, fileName);
        }
    });
    
    // Handle refresh button
    document.getElementById('refreshProject').addEventListener('click', () => {
        refreshProjectTree();
    });
}

function refreshProjectTree() {
    if (projectTree) {
        projectTree.jstree('refresh');
    }
}

function getFileType(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const typeMap = {
        'py': 'python',
        'js': 'javascript',
        'html': 'html',
        'htm': 'html',
        'css': 'css',
        'json': 'json',
        'txt': 'text',
        'md': 'text',
        'yml': 'text',
        'yaml': 'text',
        'xml': 'text',
        'sql': 'text',
        'sh': 'text',
        'bash': 'text'
    };
    return typeMap[ext] || 'default';
}

function getAgentTheme() {
    // Return appropriate ace theme based on agent type
    switch(agentConfig.type) {
        case 'claude':
            return 'ace/theme/tomorrow';
        case 'gemini':
            return 'ace/theme/github';
        case 'cursor':
            return 'ace/theme/monokai';
        case 'codex':
            return 'ace/theme/monokai';
        default:
            return 'ace/theme/tomorrow';
    }
}

// Ace Editor Functions
function initializeAceEditor() {
    const editorContainer = document.getElementById('editorContainer');
    if (!editorContainer) return;
    
    // Create editor element
    const editorElement = document.createElement('div');
    editorElement.id = 'aceEditor';
    editorElement.style.width = '100%';
    editorElement.style.height = '100%';
    
    // Clear the container and add editor
    editorContainer.innerHTML = '';
    editorContainer.appendChild(editorElement);
    
    // Initialize Ace Editor
    aceEditor = ace.edit('aceEditor');
    
    // Set theme based on agent type
    const theme = getAgentTheme();
    aceEditor.setTheme(theme);
    
    aceEditor.session.setMode('ace/mode/text');
    aceEditor.setOptions({
        fontSize: '14px',
        showPrintMargin: false,
        wrap: true,
        enableBasicAutocompletion: true,
        enableSnippets: true,
        enableLiveAutocompletion: true
    });
    
    // Handle content changes
    aceEditor.on('change', () => {
        fileModified = true;
        updateSaveButton();
    });
    
    // Handle save button
    document.getElementById('saveFile').addEventListener('click', saveCurrentFile);
    
    // Handle close button
    document.getElementById('closeFile').addEventListener('click', closeCurrentFile);
}

function openFileInEditor(filePath, fileName) {
    if (!filePath) {
        showToast('Error', 'No file path provided', 'error');
        return;
    }
    
    if (!aceEditor) {
        initializeAceEditor();
    }
    
    // Check if current file is modified
    if (fileModified && currentFilePath) {
        if (!confirm('Current file has unsaved changes. Do you want to save before opening a new file?')) {
            return;
        }
        saveCurrentFile();
    }
    
    console.log('Opening file:', filePath, 'with name:', fileName);
    
    // Read file content
    fetch('/api/files/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            path: filePath,
            agent_type: agentConfig.type
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            currentFilePath = data.path;
            currentFileContent = data.content;
            fileModified = false;
            
            // Update editor content
            aceEditor.setValue(data.content);
            aceEditor.clearSelection();
            
            // Set appropriate mode
            const fileType = getFileType(fileName);
            setEditorMode(fileType);
            
            // Update UI
            updateFileInfo(fileName, data.path);
            updateSaveButton();
            
            // Switch to editor tab
            switchTab('editor');
            
            showToast('Success', `Opened ${fileName}`, 'success');
        } else {
            console.error('Error reading file:', data.error);
            showToast('Error', data.error || 'Failed to read file', 'error');
        }
    })
    .catch(error => {
        console.error('Error reading file:', error);
        showToast('Error', 'Failed to read file', 'error');
    });
}

function setEditorMode(fileType) {
    const modeMap = {
        'python': 'ace/mode/python',
        'javascript': 'ace/mode/javascript',
        'html': 'ace/mode/html',
        'css': 'ace/mode/css',
        'json': 'ace/mode/json',
        'text': 'ace/mode/text'
    };
    
    const mode = modeMap[fileType] || 'ace/mode/text';
    aceEditor.session.setMode(mode);
}

function updateFileInfo(fileName, filePath) {
    document.getElementById('currentFileName').textContent = fileName;
    document.getElementById('filePath').textContent = filePath;
}

function updateSaveButton() {
    const saveButton = document.getElementById('saveFile');
    const closeButton = document.getElementById('closeFile');
    
    if (currentFilePath) {
        saveButton.disabled = !fileModified;
        closeButton.disabled = false;
    } else {
        saveButton.disabled = true;
        closeButton.disabled = true;
    }
}

function saveCurrentFile() {
    if (!currentFilePath || !aceEditor) return;
    
    const content = aceEditor.getValue();
    
    fetch('/api/files/write', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            path: currentFilePath,
            content: content,
            agent_type: agentConfig.type
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            fileModified = false;
            currentFileContent = content;
            updateSaveButton();
            showToast('Success', 'File saved successfully', 'success');
            
            // Refresh project tree to show any changes
            refreshProjectTree();
        } else {
            showToast('Error', data.error || 'Failed to save file', 'error');
        }
    })
    .catch(error => {
        console.error('Error saving file:', error);
        showToast('Error', 'Failed to save file', 'error');
    });
}

function closeCurrentFile() {
    if (fileModified) {
        if (!confirm('File has unsaved changes. Do you want to save before closing?')) {
            return;
        }
        saveCurrentFile();
    }
    
    currentFilePath = null;
    currentFileContent = null;
    fileModified = false;
    
    // Clear editor
    if (aceEditor) {
        aceEditor.setValue('');
    }
    
    // Update UI
    document.getElementById('currentFileName').textContent = 'No file selected';
    document.getElementById('filePath').textContent = '';
    updateSaveButton();
    
    // Show no file selected message
    const editorContainer = document.getElementById('editorContainer');
    editorContainer.innerHTML = `
        <div class="no-file-selected">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none">
                <path d="M14 2H6C5.46957 2 4.96086 2.21071 4.58579 2.58579C4.21071 2.96086 4 3.46957 4 4V20C4 20.5304 4.21071 21.0391 4.58579 21.4142C4.96086 21.7893 5.46957 22 6 22H18C18.5304 22 19.0391 21.7893 19.4142 21.4142C19.7893 21.0391 20 20.5304 20 20V8L14 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <path d="M14 2V8H20" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <p>Select a file from the project tree to edit</p>
        </div>
    `;
    
    // Reinitialize editor when needed
    aceEditor = null;
}

// Responsive Header Controls Functions
function initializeResponsiveHeader() {
    const headerControls = document.getElementById('headerControls');
    const headerControlsToggle = document.getElementById('headerControlsToggle');
    const headerControlsDropdown = document.getElementById('headerControlsDropdown');
    
    if (!headerControls) return;
    
    // Set initial state based on screen width
    updateHeaderControlsState();
    
    // Listen for window resize events
    window.addEventListener('resize', debounce(updateHeaderControlsState, 250));
    
    // Close dropdown when clicking outside
    document.addEventListener('click', function(event) {
        const sessionActionsContainer = document.getElementById('sessionActionsContainer');
        if (headerControls && sessionActionsContainer && !headerControls.contains(event.target) && sessionActionsContainer.classList.contains('show')) {
            closeHeaderDropdown();
        }
    });

    document.addEventListener('click', function(event) {
        const sessionStatusContainer = document.getElementById('sessionStatusContainer');
        if (headerControls && sessionStatusContainer && !headerControls.contains(event.target) && sessionStatusContainer.classList.contains('show')) {
            closeStatusDropdown();
        }
    });
    
    // Prevent dropdown from closing when clicking inside it
    const sessionActionsContainer = document.getElementById('sessionActionsContainer');
    if (sessionActionsContainer) {
        sessionActionsContainer.addEventListener('click', function(event) {
            event.stopPropagation();
        });
    }

    const sessionStatusContainer = document.getElementById('sessionStatusContainer');
    if (sessionStatusContainer) {
        sessionStatusContainer.addEventListener('click', function(event) {
            event.stopPropagation();
        });
    }
}

function updateHeaderControlsState() {
    const headerControls = document.getElementById('headerControls');
    
    if (!headerControls) return;
    
    // Check if header controls are overflowing
    const isOverflowing = checkHeaderOverflow();
    const isSmallScreen = window.innerWidth < 1024;
    
    if (isSmallScreen || isOverflowing) {
        headerControls.classList.add('collapsed');
    } else {
        headerControls.classList.remove('collapsed');
        closeHeaderDropdown();
    }
}

function checkHeaderOverflow() {
    const headerControls = document.getElementById('headerControls');
    if (!headerControls) return false;
    
    // Get the container width and controls width
    const container = headerControls.parentElement;
    const containerWidth = container.offsetWidth;
    const controlsWidth = headerControls.scrollWidth;
    
    // Check if controls are wider than available space
    return controlsWidth > containerWidth;
}

function toggleHeaderControls(event) {
    event.preventDefault();
    
    const headerControlsToggle = document.getElementById('headerControlsToggle');
    const sessionActionsContainer = document.getElementById('sessionActionsContainer');
    
    if (sessionActionsContainer && sessionActionsContainer.classList.contains('show')) {
        closeHeaderDropdown();
    } else {
        openHeaderDropdown();
    }
}

function toggleHeaderStatus(event) {
    event.preventDefault();
    
    const headerStatusToggle = document.getElementById('headerStatusToggle');
    const sessionStatusContainer = document.getElementById('sessionStatusContainer');
    
    if (sessionStatusContainer && sessionStatusContainer.classList.contains('show')) {
        closeStatusDropdown();
    } else {
        openStatusDropdown();
    }
}

function openHeaderDropdown() {
    const headerControlsToggle = document.getElementById('headerControlsToggle');
    const sessionActionsContainer = document.getElementById('sessionActionsContainer');
    
    if (headerControlsToggle) headerControlsToggle.classList.add('active');
    if (sessionActionsContainer) sessionActionsContainer.classList.add('show');
}

function closeHeaderDropdown() {
    const headerControlsToggle = document.getElementById('headerControlsToggle');
    const sessionActionsContainer = document.getElementById('sessionActionsContainer');
    
    if (headerControlsToggle) headerControlsToggle.classList.remove('active');
    if (sessionActionsContainer) sessionActionsContainer.classList.remove('show');
}

function openStatusDropdown() {
    const headerStatusToggle = document.getElementById('headerStatusToggle');
    const sessionStatusContainer = document.getElementById('sessionStatusContainer');
    
    if (headerStatusToggle) headerStatusToggle.classList.add('active');
    if (sessionStatusContainer) sessionStatusContainer.classList.add('show');
}

function closeStatusDropdown() {
    const headerStatusToggle = document.getElementById('headerStatusToggle');
    const sessionStatusContainer = document.getElementById('sessionStatusContainer');
    
    if (headerStatusToggle) headerStatusToggle.classList.remove('active');
    if (sessionStatusContainer) sessionStatusContainer.classList.remove('show');
}

// Utility function for debouncing
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
