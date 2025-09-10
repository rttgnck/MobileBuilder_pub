#!/usr/bin/env python3
"""
MobileBuilder - Multi-Agent AI Interface
Main application entry point for managing multiple AI agents
"""

import os
import signal
import atexit
import subprocess
import logging
import threading
import time
import requests
import json
import pickle
from flask import Flask, render_template, request, jsonify, Response
from flask_socketio import SocketIO, emit, join_room, leave_room
from agents.generic_agent import GenericAgentManager
from agents.db_manager import DatabaseManager, Message, Session
from dataclasses import asdict
from dotenv import load_dotenv  # <-- 1. IMPORT THE LIBRARY
from datetime import datetime, timedelta
from agents.file_watcher import get_file_tracker

logger = logging.getLogger(__name__)

load_dotenv()

# Configuration
DEFAULT_WORKING_DIR = os.getenv("DEFAULT_WORKING_DIR", "/tmp")

# Agent availability cache
AGENT_CACHE_FILE = 'agents/agent_cache.pkl'
CACHE_EXPIRY_DAYS = 7
_agent_cache = None
_cache_timestamp = None

def load_agent_cache():
    """Load agent cache from file"""
    global _agent_cache, _cache_timestamp
    try:
        if os.path.exists(AGENT_CACHE_FILE):
            with open(AGENT_CACHE_FILE, 'rb') as f:
                cache_data = pickle.load(f)
                _agent_cache = cache_data.get('agents')
                _cache_timestamp = cache_data.get('timestamp')
                
                # Check if cache is still valid (within 7 days)
                if _cache_timestamp and datetime.now() - _cache_timestamp < timedelta(days=CACHE_EXPIRY_DAYS):
                    print(f"✓ Loaded cached agent data from {_cache_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
                    return True
                else:
                    print("✗ Cached agent data expired, will refresh")
                    _agent_cache = None
                    _cache_timestamp = None
    except Exception as e:
        print(f"✗ Error loading agent cache: {e}")
        _agent_cache = None
        _cache_timestamp = None
    return False

def save_agent_cache(agent_status):
    """Save agent cache to file"""
    global _agent_cache, _cache_timestamp
    try:
        _agent_cache = agent_status
        _cache_timestamp = datetime.now()
        
        cache_data = {
            'agents': agent_status,
            'timestamp': _cache_timestamp
        }
        
        with open(AGENT_CACHE_FILE, 'wb') as f:
            pickle.dump(cache_data, f)
        print(f"✓ Saved agent cache at {_cache_timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    except Exception as e:
        print(f"✗ Error saving agent cache: {e}")

def get_cached_agent_status():
    """Get cached agent status if available and valid"""
    global _agent_cache, _cache_timestamp
    
    if _agent_cache and _cache_timestamp:
        # Check if cache is still valid
        if datetime.now() - _cache_timestamp < timedelta(days=CACHE_EXPIRY_DAYS):
            return _agent_cache
    
    return None

def clear_agent_cache():
    """Clear the agent cache"""
    global _agent_cache, _cache_timestamp
    _agent_cache = None
    _cache_timestamp = None
    try:
        if os.path.exists(AGENT_CACHE_FILE):
            os.remove(AGENT_CACHE_FILE)
        print("✓ Agent cache cleared")
    except Exception as e:
        print(f"✗ Error clearing agent cache: {e}")

# Load cache on startup
load_agent_cache()

def background_cache_refresh():
    """Background task to refresh cache when it expires"""
    while True:
        try:
            # Check every hour
            time.sleep(3600)  # 1 hour
            
            # Check if cache is expired
            cached_data = get_cached_agent_status()
            if not cached_data:
                print("Background: Cache expired, refreshing agent availability...")
                check_agent_availability(force_refresh=True)
                print("Background: Agent availability refreshed")
            
        except Exception as e:
            print(f"Background cache refresh error: {e}")
            # Continue the loop even if there's an error

# Start background cache refresh thread
cache_refresh_thread = threading.Thread(target=background_cache_refresh, daemon=True)
cache_refresh_thread.start()

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# Initialize SocketIO
socketio = SocketIO(app, 
                   cors_allowed_origins="*",  # Adjust for security
                   logger=True,               # Enable debugging
                   engineio_logger=True)
# Initialize file tracker
file_tracker = get_file_tracker(socketio)

# Global dictionary to store agent managers for each agent type
agent_managers = {}

pending_approvals = {}  # approval_id -> {request_data, response_event, result}

def check_agent_availability(force_refresh=False):
    """Check which agents are available on the system"""
    # Try to use cached data first unless force refresh is requested
    if not force_refresh:
        cached_status = get_cached_agent_status()
        if cached_status:
            print("Using cached agent availability data")
            return cached_status
    
    print("Checking agent availability..." + (" (forced refresh)" if force_refresh else " (no cache available)"))
    
    agents = {
        'claude': {
            'name': 'Claude',
            'command': 'claude',
            'description': "Anthropic's Claude - Coding assistance with deep understanding of complex problems",
            'features': ['Code Generation', 'Debugging', 'Documentation'],
            'icon': 'C',
            'install_url': 'https://docs.anthropic.com/en/docs/claude-code/setup',
            'install_text': 'Install Claude CLI'
        },
        'gemini': {
            'name': 'Gemini',
            'command': 'gemini',
            'description': "Google's Gemini - Multimodal AI with coding capabilities and visual understanding",
            'features': ['Multimodal', 'Code Review', 'Testing'],
            'icon': 'G',
            'install_url': 'https://github.com/google-gemini/gemini-cli',
            'install_text': 'Install Gemini CLI'
        },
        'cursor': {
            'name': 'Cursor',
            'command': 'cursor-agent',
            'description': "Cursor's AI Agent - Specialized in development workflows and automation",
            'features': ['Workflow', 'Integration', 'Automation'],
            'icon': 'CU',
            'install_url': 'https://cursor.com/cli',
            'install_text': 'Install Cursor'
        },
        'codex': {
            'name': 'Codex',
            'command': 'codex',
            'description': "OpenAI's Codex - Specialized in development workflows and automation",
            'features': ['Code Agent', 'Testing', 'Debugging'],
            'icon': 'CX',
            'install_url': 'https://developers.openai.com/codex/cli/',
            'install_text': 'Install Codex'
        }
    }
    
    available_agents = {}
    all_installed = True
    
    for agent_type, agent_info in agents.items():
        # if agent_type == "gemini": continue
        # if agent_type == "cursor": continue
        try:
            # Check if the agent command exists in PATH
            result = subprocess.run(['which', agent_info['command']], 
                                  capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0:
                # Agent is available
                agent_info['available'] = True
                agent_info['path'] = result.stdout.strip()
                available_agents[agent_type] = agent_info
                print(f"✓ {agent_info['name']} found at: {agent_info['path']}")
            else:
                # Agent is not available
                agent_info['available'] = False
                agent_info['path'] = None
                all_installed = False
                print(f"✗ {agent_info['name']} not found in PATH")
                
        except subprocess.TimeoutExpired:
            # Timeout checking
            agent_info['available'] = False
            agent_info['path'] = None
            all_installed = False
            print(f"✗ {agent_info['name']} check timed out")
        except FileNotFoundError:
            # which command not found (unlikely on Linux)
            agent_info['available'] = False
            agent_info['path'] = None
            all_installed = False
            print(f"✗ {agent_info['name']} check failed - 'which' command not found")
        except Exception as e:
            # Other errors
            agent_info['available'] = False
            agent_info['path'] = None
            all_installed = False
            print(f"✗ {agent_info['name']} check failed with error: {e}")
    
    print(f"Agent availability summary: {len(available_agents)}/{len(agents)} agents available")
    
    # Determine if we should show the expand button
    # Show expand button when some agents are available but not all
    show_expand = len(available_agents) > 0 and len(available_agents) < len(agents)
    
    agent_status = {
        'agents': agents,
        'available_agents': available_agents,
        'all_installed': all_installed,
        'any_installed': len(available_agents) > 0,
        'show_expand': show_expand,
        'unavailable_count': len(agents) - len(available_agents),
        'cache_timestamp': datetime.now().isoformat()
    }
    
    # Save to cache
    save_agent_cache(agent_status)
    
    return agent_status


def get_or_create_agent_manager(agent_type):
    """Get existing agent manager or create a new one for the specified agent type"""
    print(f"Getting or creating agent manager for type: {agent_type}")
    if agent_type not in agent_managers:
        print(f"Creating new agent manager for {agent_type}")
        if agent_type == "claude":
            from agents.claude_code import create_claude_manager
            agent_managers[agent_type] = create_claude_manager(socketio)
        elif agent_type == "gemini":
            from agents.gemini_cli import create_gemini_manager
            agent_managers[agent_type] = create_gemini_manager(socketio)
        elif agent_type == "cursor":
            from agents.cursor_agent import create_cursor_manager
            agent_managers[agent_type] = create_cursor_manager(socketio)
        elif agent_type == "codex":
            from agents.codex_cli import create_codex_manager
            agent_managers[agent_type] = create_codex_manager(socketio)
        else:
            raise ValueError(f"Unknown agent type: {agent_type}")
        print(f"Successfully created agent manager for {agent_type}")
    else:
        print(f"Using existing agent manager for {agent_type}")
    
    return agent_managers[agent_type]

def get_agent_manager(agent_type):
    """Get existing agent manager for the specified agent type"""
    #if agent manager length is 0, get_or_create_agent_manager first
    if len(agent_managers) == 0:
        get_or_create_agent_manager(agent_type)

    return agent_managers.get(agent_type)

def cleanup_agent_manager(agent_type):
    """Clean up and remove an agent manager"""
    if agent_type in agent_managers:
        try:
            agent_managers[agent_type].end_session()
            del agent_managers[agent_type]
        except Exception as e:
            print(f"Error cleaning up {agent_type} agent manager: {e}")

# Flask routes
@app.route('/')
def index():
    """Serve the main landing page"""
    agent_status = check_agent_availability()
    return render_template('index.html', agent_status=agent_status)

# PWA routes
@app.route('/manifest.json')
def manifest():
    """Serve the PWA manifest"""
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    """Serve the service worker"""
    return app.send_static_file('sw.js')

@app.route('/claude')
def claude_interface():
    """Serve the Claude agent interface"""
    try:
        get_or_create_agent_manager("claude")
    except Exception as e:
        print(f"Error creating Claude agent manager: {e}")
    # logger.error(f"Serving Claude agent interface with DEFAULT_WORKING_DIR: {DEFAULT_WORKING_DIR}")
    return render_template('claude.html', DEFAULT_WORKING_DIR=DEFAULT_WORKING_DIR)

@app.route('/gemini')
def gemini_interface():
    """Serve the Gemini agent interface"""
    try:
        get_or_create_agent_manager("gemini")
    except Exception as e:
        print(f"Error creating Gemini agent manager: {e}")
    return render_template('gemini.html', DEFAULT_WORKING_DIR=DEFAULT_WORKING_DIR)

@app.route('/cursor')
def cursor_interface():
    """Serve the Cursor agent interface"""
    try:
        get_or_create_agent_manager("cursor")
    except Exception as e:
        print(f"Error creating Cursor agent manager: {e}")
    return render_template('cursor.html', DEFAULT_WORKING_DIR=DEFAULT_WORKING_DIR)

@app.route('/codex')
def codex_interface():
    """Serve the Codex agent interface"""
    try:
        get_or_create_agent_manager("codex")
    except Exception as e:
        print(f"Error creating Codex agent manager: {e}")
    return render_template('codex.html', DEFAULT_WORKING_DIR=DEFAULT_WORKING_DIR)

# @app.route('/session_history_viewer')
# def session_history_viewer():
#     """Serve the session history viewer interface"""
#     return render_template('session_history_viewer.html')

@app.route('/session_viewer')
def session_viewer():
    """Serve the new session viewer interface"""
    return render_template('session_viewer.html')

# API endpoints
@app.route('/api/status/<agent_type>')
def get_agent_status(agent_type):
    """Get the current agent status for a specific agent type"""
    agent_manager = get_agent_manager(agent_type)
    if agent_manager:
        status = agent_manager.get_status()
        return jsonify({
            'active': status['active'],
            'agent_type': agent_manager.agent_command,
            'working_directory': status.get('working_directory', ''),
            'session_id': status.get('session_id'),
            'connected_clients': status.get('connected_clients', 0),
            'elapsed_time': status.get('elapsed_time', 0),
            'remaining_time': status.get('remaining_time', 0)
        })
    return jsonify({'active': False, 'agent_type': agent_type, 'working_directory': ''})

@app.route('/api/status')
def get_status():
    """Get the current agent status for all agents"""
    all_status = {}
    for agent_type in ["claude", "gemini", "cursor", "codex"]:
        agent_manager = get_agent_manager(agent_type)
        if agent_manager:
            status = agent_manager.get_status()
            all_status[agent_type] = {
                'active': status['active'],
                'agent_type': agent_manager.agent_command,
                'working_directory': status.get('working_directory', ''),
                'session_id': status.get('session_id'),
                'connected_clients': status.get('connected_clients', 0),
                'elapsed_time': status.get('elapsed_time', 0),
                'remaining_time': status.get('remaining_time', 0)
            }
        else:
            all_status[agent_type] = {'active': False, 'agent_type': agent_type, 'working_directory': ''}
    
    return jsonify(all_status)

@app.route('/api/sessions/<agent_type>')
def get_agent_sessions(agent_type):
    """Get all sessions for a specific agent type"""
    agent_manager = get_agent_manager(agent_type)
    if agent_manager:
        sessions = agent_manager.db.list_sessions()
        return jsonify([asdict(session) for session in sessions])
    return jsonify([])

@app.route('/api/sessions')
def get_sessions():
    """Get all sessions for all agents"""
    all_sessions = {}
    for agent_type in ["claude", "gemini", "cursor", "codex"]:
        agent_manager = get_agent_manager(agent_type)
        if agent_manager:
            sessions = agent_manager.db.list_sessions()
            all_sessions[agent_type] = [asdict(session) for session in sessions]
        else:
            all_sessions[agent_type] = []
    
    return jsonify(all_sessions)

@app.route('/api/sessions/<agent_type>/<session_id>')
def get_agent_session(agent_type, session_id):
    """Get specific session details and messages for a specific agent type"""
    agent_manager = get_agent_manager(agent_type)
    if agent_manager:
        session_obj = agent_manager.db.get_session(session_id)
        if not session_obj:
            return jsonify({'error': 'Session not found'}), 404
        
        messages = agent_manager.db.get_session_messages(session_id)
        return jsonify({
            'session': asdict(session_obj),
            'messages': [asdict(m) for m in messages]
        })
    return jsonify({'error': 'Agent not found'}), 400

@app.route('/api/sessions/<agent_type>/<session_id>/resume', methods=['POST'])
def resume_agent_session(agent_type, session_id):
    """Resume a specific session for a specific agent type"""
    try:
        agent_manager = get_agent_manager(agent_type)
        if not agent_manager:
            return jsonify({'success': False, 'error': 'Agent not found'}), 400
        
        # Get the session to retrieve the agent_api_session_id
        session_obj = agent_manager.db.get_session(session_id)
        if not session_obj:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        if not session_obj.agent_api_session_id:
            return jsonify({'success': False, 'error': 'Session does not have an agent API session ID for resumption'}), 400
        
        # For Claude, use the resume_session method
        if agent_type == 'claude' and hasattr(agent_manager, 'resume_session'):
            result = agent_manager.resume_session(
                session_id=session_id,
                agent_api_session_id=session_obj.agent_api_session_id,
                working_dir=session_obj.working_directory,
                session_name=session_obj.name
            )
            return jsonify(result)
        else:
            return jsonify({'success': False, 'error': f'Resume not supported for {agent_type} agent'}), 400
            
    except Exception as e:
        logger.error(f"Error resuming session: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/validate_directory', methods=['POST'])
def validate_directory():
    """Validate a working directory path"""
    data = request.get_json()
    directory = data.get('directory', '')
    
    if not directory:
        return jsonify({'valid': False, 'error': 'No directory specified'})
    
    if not os.path.exists(directory):
        return jsonify({'valid': False, 'error': 'Directory does not exist', 'can_create': True})
    
    if not os.path.isdir(directory):
        return jsonify({'valid': False, 'error': 'Path is not a directory'})
    
    return jsonify({'valid': True, 'path': directory})

@app.route('/api/create_directory', methods=['POST'])
def create_directory():
    """Create a working directory if it doesn't exist"""
    data = request.get_json()
    directory = data.get('directory', '')
    
    if not directory:
        return jsonify({'success': False, 'error': 'No directory specified'})
    
    try:
        # Create directory and all parent directories
        os.makedirs(directory, exist_ok=True)
        
        # Verify it was created successfully
        if os.path.exists(directory) and os.path.isdir(directory):
            return jsonify({'success': True, 'path': directory})
        else:
            return jsonify({'success': False, 'error': 'Failed to create directory'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error creating directory: {str(e)}'})

@app.route('/api/select_agent', methods=['POST'])
def select_agent():
    """Select and initialize an agent"""
    data = request.get_json()
    agent_type = data.get('agent_type')
    
    try:
        get_or_create_agent_manager(agent_type)
        return jsonify({'success': True, 'agent_type': agent_type})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 400

# File System API endpoints
@app.route('/api/files/list', methods=['POST'])
def list_files():
    """List files and directories in a given path"""
    data = request.get_json()
    path = data.get('path', '')
    agent_type = data.get('agent_type', 'claude')
    
    # Allow empty path - it will resolve to working directory
    # Convert empty path to current directory for os.path.join
    if not path:
        path = ''
    
    try:
        # Get the agent manager to get the working directory
        agent_manager = get_agent_manager(agent_type)
        if not agent_manager:
            return jsonify({'success': False, 'error': 'Agent not found'}), 400
        
        # Use the agent's working directory as base if path is relative
        if not os.path.isabs(path):
            working_dir = agent_manager.get_status().get('working_directory', os.getcwd())
            if working_dir.endswith('/'):
                working_dir = working_dir[:-1]
            full_path = os.path.join(working_dir, path)
        else:
            full_path = path
        
        # Expand user home directory
        full_path = os.path.expanduser(full_path)
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'error': 'Path does not exist'}), 404
        
        if not os.path.isdir(full_path):
            return jsonify({'success': False, 'error': 'Path is not a directory'}), 400
        
        # List directory contents
        items = []
        try:
            for item in sorted(os.listdir(full_path)):
                item_path = os.path.join(full_path, item)
                is_dir = os.path.isdir(item_path)
                
                # Skip hidden files and directories by default
                if item.startswith('.'):
                    continue
                
                items.append({
                    'name': item,
                    'path': item_path,
                    'is_directory': is_dir,
                    'size': os.path.getsize(item_path) if not is_dir else 0
                })
        except PermissionError:
            return jsonify({'success': False, 'error': 'Permission denied'}), 403
        
        return jsonify({
            'success': True,
            'path': full_path,
            'items': items
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/read', methods=['POST'])
def read_file():
    """Read the contents of a file"""
    data = request.get_json()
    file_path = data.get('path', '')
    agent_type = data.get('agent_type', 'claude')
    
    if not file_path:
        return jsonify({'success': False, 'error': 'No file path specified'}), 400
    
    try:
        # Get the agent manager to get the working directory
        agent_manager = get_agent_manager(agent_type)
        if not agent_manager:
            return jsonify({'success': False, 'error': 'Agent not found'}), 400
        
        # Use the agent's working directory as base if path is relative
        if not os.path.isabs(file_path):
            working_dir = agent_manager.get_status().get('working_directory', os.getcwd())
            full_path = os.path.join(working_dir, file_path)
        else:
            full_path = file_path
        
        # Expand user home directory
        full_path = os.path.expanduser(full_path)
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'error': 'File does not exist'}), 404
        
        if not os.path.isfile(full_path):
            return jsonify({'success': False, 'error': 'Path is not a file'}), 400
        
        # Check file size (limit to 1MB)
        file_size = os.path.getsize(full_path)
        if file_size > 1024 * 1024:  # 1MB limit
            return jsonify({'success': False, 'error': 'File too large (max 1MB)'}), 413
        
        # Read file content
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            # Try with different encoding
            try:
                with open(full_path, 'r', encoding='latin-1') as f:
                    content = f.read()
            except Exception:
                return jsonify({'success': False, 'error': 'Cannot read file (unsupported encoding)'}), 400
        
        return jsonify({
            'success': True,
            'path': full_path,
            'content': content,
            'size': file_size
        })
        
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/write', methods=['POST'])
def write_file():
    """Write content to a file"""
    data = request.get_json()
    file_path = data.get('path', '')
    content = data.get('content', '')
    agent_type = data.get('agent_type', 'claude')
    
    if not file_path:
        return jsonify({'success': False, 'error': 'No file path specified'}), 400
    
    try:
        # Get the agent manager to get the working directory
        agent_manager = get_agent_manager(agent_type)
        if not agent_manager:
            return jsonify({'success': False, 'error': 'Agent not found'}), 400
        
        # Use the agent's working directory as base if path is relative
        if not os.path.isabs(file_path):
            working_dir = agent_manager.get_status().get('working_directory', os.getcwd())
            full_path = os.path.join(working_dir, file_path)
        else:
            full_path = file_path
        
        # Expand user home directory
        full_path = os.path.expanduser(full_path)
        
        # Create directory if it doesn't exist
        dir_path = os.path.dirname(full_path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)
        
        # Write file content
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        return jsonify({
            'success': True,
            'path': full_path,
            'size': len(content.encode('utf-8'))
        })
        
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/files/delete', methods=['POST'])
def delete_file():
    """Delete a file or directory"""
    data = request.get_json()
    path = data.get('path', '')
    agent_type = data.get('agent_type', 'claude')
    
    if not path:
        return jsonify({'success': False, 'error': 'No path specified'}), 400
    
    try:
        # Get the agent manager to get the working directory
        agent_manager = get_agent_manager(agent_type)
        if not agent_manager:
            return jsonify({'success': False, 'error': 'Agent not found'}), 400
        
        # Use the agent's working directory as base if path is relative
        if not os.path.isabs(path):
            working_dir = agent_manager.get_status().get('working_directory', os.getcwd())
            full_path = os.path.join(working_dir, path)
        else:
            full_path = path
        
        # Expand user home directory
        full_path = os.path.expanduser(full_path)
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'error': 'Path does not exist'}), 404
        
        # Delete file or directory
        if os.path.isfile(full_path):
            os.remove(full_path)
        elif os.path.isdir(full_path):
            import shutil
            shutil.rmtree(full_path)
        else:
            return jsonify({'success': False, 'error': 'Invalid path type'}), 400
        
        return jsonify({
            'success': True,
            'path': full_path
        })
        
    except PermissionError:
        return jsonify({'success': False, 'error': 'Permission denied'}), 403
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/approve_tools', methods=['POST'])
def handle_approval_request():
    """
    Handle approval requests from the MCP server
    This route receives the approval request, sends it to the frontend,
    and waits for the user's decision
    """
    try:
        data = request.get_json()
        approval_id = data.get('approval_id')
        tool_name = data.get('tool_name')
        tool_input = data.get('input', {})
        reason = data.get('reason', '')
        
        if not approval_id or not tool_name:
            return jsonify({'error': 'Missing approval_id or tool_name'}), 400
        
        logger.info(f"Received approval request {approval_id} for tool {tool_name}")
        
        # Create an event to wait for the response
        response_event = threading.Event()
        
        # Store the approval request
        pending_approvals[approval_id] = {
            'request_data': data,
            'response_event': response_event,
            'result': None,
            'timestamp': datetime.now()
        }
        
        # Send to all connected Claude clients via SocketIO
        approval_notification = {
            'approval_id': approval_id,
            'tool_name': tool_name,
            'input': tool_input,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'message': f"Claude wants to use tool: {tool_name}",
        }
        
        # Create tool approval required message for in-chat display
        tool_approval_message = {
            'content': f"🔒 Tool Approval Required\n\nClaude wants to use the **{tool_name}** tool.\n\n**Reason:** {reason if reason else 'No specific reason provided'}\n\nPlease approve or deny this tool usage.",
            'type': 'tool_approval_required',
            'metadata': {
                'tool_name': tool_name,
                'approval_id': approval_id
            },
            'streaming': True,
            
            'approval_id': approval_id,
            'tool_name': tool_name,
            'input': tool_input,
            'reason': reason,
            'timestamp': datetime.now().isoformat(),
            'message': f"Claude wants to use tool: {tool_name}",
        }
        
        # Send to all clients in active Claude sessions
        claude_manager = get_agent_manager('claude')
        if claude_manager and claude_manager.current_session_id:
            # Send notification for pop-up
            socketio.emit('approval_request', approval_notification, 
                         room=claude_manager.current_session_id)
            # Send tool approval required for in-chat display
            socketio.emit('agent_output', tool_approval_message, 
                         room=claude_manager.current_session_id)
        else:
            # If no active session, send to all connected clients
            socketio.emit('approval_request', approval_notification, 
                         namespace='/')
            socketio.emit('agent_output', tool_approval_message, 
                         namespace='/')
        
        # Wait for user response (5 minute timeout)
        if response_event.wait(timeout=300):  # 5 minutes
            result = pending_approvals[approval_id]['result']
            
            # Clean up
            del pending_approvals[approval_id]
            
            if result:
                return jsonify({
                    'approved': result['approved'],
                    'reason': result.get('reason', ''),
                    'approval_id': approval_id
                })
            else:
                return jsonify({
                    'approved': False,
                    'reason': 'Internal error processing approval',
                    'approval_id': approval_id
                }), 500
        else:
            # Timeout
            del pending_approvals[approval_id]
            return jsonify({
                'approved': False,
                'reason': 'Approval request timed out (5 minutes)',
                'approval_id': approval_id
            }), 408
            
    except Exception as e:
        logger.error(f"Error handling approval request: {e}")
        return jsonify({
            'approved': False,
            'reason': f'Server error: {str(e)}',
            'approval_id': data.get('approval_id', 'unknown')
        }), 500

@app.route('/api/approve_tools/<approval_id>', methods=['POST'])
def submit_approval_decision(approval_id):
    """
    Handle approval decisions from the frontend
    """
    try:
        data = request.get_json()
        approved = data.get('approved', False)
        reason = data.get('reason', '')
        
        if approval_id not in pending_approvals:
            return jsonify({'error': 'Approval request not found or expired'}), 404
        
        # Store the result
        pending_approvals[approval_id]['result'] = {
            'approved': approved,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
        
        # Signal the waiting thread
        pending_approvals[approval_id]['response_event'].set()
        
        logger.info(f"Approval decision for {approval_id}: {approved} - {reason}")
        
        # Broadcast decision to all clients for UI updates
        claude_manager = get_agent_manager('claude')
        if claude_manager and claude_manager.current_session_id:
            socketio.emit('approval_decision', {
                'approval_id': approval_id,
                'approved': approved,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }, room=claude_manager.current_session_id)
        
        return jsonify({'success': True, 'approval_id': approval_id})
        
    except Exception as e:
        logger.error(f"Error processing approval decision: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/pending_approvals')
def get_pending_approvals():
    """Get list of pending approval requests"""
    try:
        # Clean up expired approvals (older than 5 minutes)
        current_time = datetime.now()
        expired_ids = []
        
        for approval_id, approval_data in pending_approvals.items():
            if current_time - approval_data['timestamp'] > timedelta(minutes=5):
                expired_ids.append(approval_id)
        
        for approval_id in expired_ids:
            if approval_id in pending_approvals:
                pending_approvals[approval_id]['response_event'].set()
                del pending_approvals[approval_id]
        
        # Return current pending approvals
        pending_list = []
        for approval_id, approval_data in pending_approvals.items():
            request_data = approval_data['request_data']
            pending_list.append({
                'approval_id': approval_id,
                'tool_name': request_data.get('tool_name'),
                'input': request_data.get('input', {}),
                'reason': request_data.get('reason', ''),
                'timestamp': approval_data['timestamp'].isoformat()
            })
        
        return jsonify({'pending_approvals': pending_list})
        
    except Exception as e:
        logger.error(f"Error getting pending approvals: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/agents/refresh', methods=['POST'])
def refresh_agents():
    """Force refresh the agent availability cache"""
    try:
        print("Manual agent refresh requested")
        agent_status = check_agent_availability(force_refresh=True)
        return jsonify({
            'success': True,
            'message': 'Agent availability refreshed',
            'agent_status': agent_status,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"Error refreshing agents: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/agents/cache/status')
def get_cache_status():
    """Get information about the agent cache"""
    try:
        global _cache_timestamp
        cached_data = get_cached_agent_status()
        
        return jsonify({
            'has_cache': cached_data is not None,
            'cache_timestamp': _cache_timestamp.isoformat() if _cache_timestamp else None,
            'cache_age_days': (datetime.now() - _cache_timestamp).days if _cache_timestamp else None,
            'cache_expires_in_days': CACHE_EXPIRY_DAYS - (datetime.now() - _cache_timestamp).days if _cache_timestamp else None,
            'cache_expired': (datetime.now() - _cache_timestamp).days >= CACHE_EXPIRY_DAYS if _cache_timestamp else True
        })
    except Exception as e:
        logger.error(f"Error getting cache status: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/agents/cache/clear', methods=['POST'])
def clear_cache():
    """Clear the agent availability cache"""
    try:
        clear_agent_cache()
        return jsonify({
            'success': True,
            'message': 'Agent cache cleared'
        })
    except Exception as e:
        logger.error(f"Error clearing cache: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# File diff management API endpoints
@app.route('/api/diffs/<session_id>')
def get_session_diffs(session_id):
    """Get all diffs for a session"""
    try:
        diffs = file_tracker.get_session_diffs(session_id)
        return jsonify({
            'success': True,
            'diffs': diffs,
            'session_id': session_id
        })
    except Exception as e:
        logger.error(f"Error getting session diffs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/diffs/<session_id>/pending')
def get_pending_diffs(session_id):
    """Get pending diffs for a session"""
    try:
        diffs = file_tracker.get_pending_diffs(session_id)
        return jsonify({
            'success': True,
            'diffs': diffs,
            'session_id': session_id,
            'count': len(diffs)
        })
    except Exception as e:
        logger.error(f"Error getting pending diffs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/diffs/<session_id>/<diff_id>/accept', methods=['POST'])
def accept_diff(session_id, diff_id):
    """Accept a specific diff"""
    try:
        success = file_tracker.accept_diff(session_id, diff_id)
        if success:
            return jsonify({
                'success': True,
                'message': 'Diff accepted',
                'diff_id': diff_id
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Diff not found or already processed'
            }), 404
    except Exception as e:
        logger.error(f"Error accepting diff: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/diffs/<session_id>/<diff_id>/deny', methods=['POST'])
def deny_diff(session_id, diff_id):
    """Deny a specific diff and restore old version"""
    try:
        success = file_tracker.deny_diff(session_id, diff_id)
        if success:
            return jsonify({
                'success': True,
                'message': 'Diff denied and file restored',
                'diff_id': diff_id
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Diff not found or already processed'
            }), 404
    except Exception as e:
        logger.error(f"Error denying diff: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/diffs/<session_id>/accept_all', methods=['POST'])
def accept_all_diffs(session_id):
    """Accept all pending diffs for a session"""
    try:
        count = file_tracker.accept_all_diffs(session_id)
        return jsonify({
            'success': True,
            'message': f'Accepted {count} diffs',
            'count': count
        })
    except Exception as e:
        logger.error(f"Error accepting all diffs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/files/<session_id>/content', methods=['POST'])
def get_file_content_with_diffs(session_id):
    """Get file content with diff information"""
    try:
        data = request.get_json()
        file_path = data.get('file_path', '')
        
        if not file_path:
            return jsonify({
                'success': False,
                'error': 'No file path specified'
            }), 400
        
        # Get current content
        current_content = file_tracker.get_file_current_content(session_id, file_path)
        if current_content is None:
            return jsonify({
                'success': False,
                'error': 'File not found or cannot be read'
            }), 404
        
        # Get diffs for this file
        all_diffs = file_tracker.get_session_diffs(session_id)
        file_diffs = [diff for diff in all_diffs if diff['file_path'] == file_path]
        
        return jsonify({
            'success': True,
            'file_path': file_path,
            'current_content': current_content,
            'diffs': file_diffs
        })
        
    except Exception as e:
        logger.error(f"Error getting file content with diffs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/sessions/<agent_type>/<session_id>', methods=['DELETE'])
def delete_agent_session(agent_type, session_id):
    """Delete a specific session for a specific agent type"""
    try:
        agent_manager = get_agent_manager(agent_type)
        if not agent_manager:
            return jsonify({'success': False, 'error': 'Agent not found'}), 400
        
        # Check if session exists
        session_obj = agent_manager.db.get_session(session_id)
        if not session_obj:
            return jsonify({'success': False, 'error': 'Session not found'}), 404
        
        # Delete the session
        success = agent_manager.db.delete_session(session_id)
        if success:
            return jsonify({'success': True, 'message': 'Session deleted successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to delete session'}), 500
            
    except Exception as e:
        logger.error(f"Error deleting session: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500









# SocketIO event handlers
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f"Client connected: {request.sid}")

def ensure_client_in_session_room(agent_manager, client_id, action_description="action"):
    """Helper function to ensure client is in session room and log the action"""
    if not agent_manager:
        return False
    
    status = agent_manager.get_status()
    if status['active'] and status['session_id']:
        # Join session room to ensure client receives agent_output events
        join_room(status['session_id'])
        print(f"Client {client_id} joined session room {status['session_id']} for {action_description}")
        return True
    else:
        print(f"Warning: No active session found for {action_description} from client {client_id}")
        return False

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f"Client disconnected: {request.sid}")
    
    # Disconnect client from all agent managers
    for agent_type, agent_manager in agent_managers.items():
        if agent_manager:
            agent_manager.disconnect_client(request.sid)
            
            # Leave session room if in one
            if agent_manager.current_session_id:
                leave_room(agent_manager.current_session_id)

@socketio.on('start_session')
def handle_start_session(data):
    """Handle session start request"""
    print(f"Received start_session request: {data}")
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_or_create_agent_manager(agent_type)
    
    if agent_manager:
        working_directory = data.get('working_directory', os.getcwd())
        session_name = data.get('session_name', None)
        
        # Expand user home directory
        working_directory = os.path.expanduser(working_directory)
        
        print(f"Starting session for {agent_type} in {working_directory}")
        result = agent_manager.start_session(working_directory, session_name)
        print(f"Session start result: {result}")
        
        if result['success']:
            try:
                # Emit early ack to unblock UI
                emit('session_started', {
                    'success': True,
                    'session_id': result.get('session_id'),
                    'session_name': result.get('session_name'),
                    'working_directory': result.get('working_directory'),
                }, room=request.sid)
                
                # Join session room
                join_room(result['session_id'])
                
                # Start file watching for this session (non-blocking and tolerant)
                try:
                    file_tracker.start_watching(result['session_id'], working_directory)
                except Exception as e:
                    print(f"Warning: file watcher failed to start: {e}")
                
                # Connect client and optionally send connection_result with history
                try:
                    connection_result = agent_manager.connect_client(request.sid, data.get('device_id'))
                    # Send a secondary update with history and timers, but do not block UI
                    emit('connection_result', connection_result, room=request.sid)
                except Exception as e:
                    print(f"Warning: connect_client failed: {e}")
            except Exception as e:
                print(f"Error emitting session_started: {e}")
        else:
            print(f"Session start failed: {result['error']}")
            emit('error', {'message': result['error']}, room=request.sid)
    else:
        print(f"Failed to create {agent_type} agent manager")
        emit('error', {'message': f'Failed to create {agent_type} agent manager'})

@socketio.on('connect_to_session')
def handle_connect_to_session(data):
    """Connect to existing active session"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager:
        device_id = data.get('device_id')
        
        # Check if there's an active session
        status = agent_manager.get_status()
        
        if not status['active']:
            emit('connection_result', {
                'success': False,
                'error': 'No active session'
            })
            return
        
        # Join session room
        join_room(status['session_id'])
        
        # Connect client
        result = agent_manager.connect_client(request.sid, device_id)
        emit('connection_result', result)
    else:
        emit('connection_result', {
            'success': False,
            'error': f'{agent_type} agent manager not found'
        })

@socketio.on('send_command')
def handle_send_command(data):
    """Handle command sending request"""
    print(f"Received send_command from client {request.sid}: {data}")
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    print(f"Agent manager for {agent_type}: {agent_manager is not None}")
    if agent_manager:
        print(f"Agent manager status: {agent_manager.get_status()}")
        command = data.get('command', '')
        device_id = data.get('device_id')
        
        print(f"Command: '{command}', Device ID: {device_id}")
        
        if not command:
            print("Empty command received")
            emit('command_status', {
                'success': False,
                'error': 'Empty command'
            })
            return
        
        # Ensure client is in the session room for receiving agent_output events
        room_joined = ensure_client_in_session_room(agent_manager, request.sid, f"command: {command}")
        print(f"Room join result: {room_joined}")
        
        print(f"Calling agent_manager.send_command with: command='{command}', client_id='{request.sid}', device_id='{device_id}'")
        success = agent_manager.send_command(command, request.sid, device_id)
        print(f"send_command result: {success}")
        
        emit('command_status', {
            'success': success,
            'command': command,
            'timestamp': datetime.now().isoformat()
        })
    else:
        print(f"No agent manager found for {agent_type}")
        emit('error', {'message': f'{agent_type} agent manager not found'})

@socketio.on('send_streaming_input')
def handle_send_streaming_input(data):
    """Handle streaming input request (Claude only)"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager and hasattr(agent_manager, 'send_streaming_input'):
        input_chunk = data.get('input_chunk', '')
        device_id = data.get('device_id')
        
        if not input_chunk:
            emit('streaming_input_status', {
                'success': False,
                'error': 'Empty input chunk'
            })
            return
        
        success = agent_manager.send_streaming_input(input_chunk, request.sid, device_id)
        emit('streaming_input_status', {
            'success': success,
            'chunk_length': len(input_chunk),
            'timestamp': datetime.now().isoformat()
        })
    else:
        emit('error', {'message': f'{agent_type} agent manager not found or streaming not supported'})

@socketio.on('submit_approval')
def handle_submit_approval(data):
    """Handle approval submission via SocketIO"""
    try:
        approval_id = data.get('approval_id')
        approved = data.get('approved', False)
        reason = data.get('reason', '')
        
        if not approval_id:
            emit('approval_error', {'message': 'Missing approval_id'})
            return
        
        if approval_id not in pending_approvals:
            emit('approval_error', {'message': 'Approval request not found or expired'})
            return
        
        # Store the result
        pending_approvals[approval_id]['result'] = {
            'approved': approved,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
        
        # Signal the waiting thread
        pending_approvals[approval_id]['response_event'].set()
        
        logger.info(f"Approval decision via SocketIO for {approval_id}: {approved} - {reason}")
        
        # Confirm to sender
        emit('approval_submitted', {
            'approval_id': approval_id,
            'approved': approved,
            'reason': reason
        })
        
        # Broadcast to all clients in session
        claude_manager = get_agent_manager('claude')
        if claude_manager and claude_manager.current_session_id:
            socketio.emit('approval_decision', {
                'approval_id': approval_id,
                'approved': approved,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }, room=claude_manager.current_session_id, broadcast=True)
        
    except Exception as e:
        logger.error(f"Error handling SocketIO approval submission: {e}")
        emit('approval_error', {'message': str(e)})

@socketio.on('send_enter_key')
def handle_send_enter_key(data):
    """Handle enter key sending request"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager:
        device_id = data.get('device_id')
        
        # Ensure client is in the session room for receiving agent_output events
        ensure_client_in_session_room(agent_manager, request.sid, "enter key")
        
        success = agent_manager.send_enter_key(request.sid, device_id)
        emit('command_status', {
            'success': success,
            'command': '[Enter Key]',
            'timestamp': datetime.now().isoformat()
        })
    else:
        emit('error', {'message': f'{agent_type} agent manager not found'})

@socketio.on('send_backspace_key')
def handle_send_backspace_key(data):
    """Handle backspace key sending request"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager:
        device_id = data.get('device_id')
        count = data.get('count', 1)  # Number of backspaces to send
        
        # Ensure client is in the session room for receiving agent_output events
        ensure_client_in_session_room(agent_manager, request.sid, f"backspace key x{count}")
        
        success = agent_manager.send_backspace_key(request.sid, device_id, count)
        emit('command_status', {
            'success': success,
            'command': f'[Backspace Key x{count}]',
            'timestamp': datetime.now().isoformat()
        })
    else:
        emit('error', {'message': f'{agent_type} agent manager not found'})

@socketio.on('end_session')
def handle_end_session(data):
    """Handle session end request"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager:
        session_id = agent_manager.current_session_id
        success = agent_manager.end_session()
        
        if success:
            # Stop file watching for this session
            if session_id:
                file_tracker.stop_watching(session_id)
            
            # Notify all clients in the session
            if session_id:
                socketio.emit('session_ended', {
                    'message': 'Session has been terminated'
                }, room=session_id)
        
        emit('session_end_result', {'success': success})

        # Always emit a session_closed event after the end-session process completes
        # so that all clients can perform consistent UI cleanup.
        if session_id:
            socketio.emit('session_closed', {
                'message': 'session closed',
                'agent_type': agent_type,
            }, room=session_id)
    else:
        emit('error', {'message': f'{agent_type} agent manager not found'})

@socketio.on('get_status')
def handle_get_status(data):
    """Get current session status for a specific agent"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager:
        emit('status_update', agent_manager.get_status())
    else:
        emit('status_update', {'active': False, 'agent_type': agent_type})

@socketio.on('resume_session')
def handle_resume_session(data):
    """Resume a previous session (load history only) - for multi-device active session resume"""
    agent_type = data.get('agent_type', 'claude')
    session_id = data.get('session_id')
    
    if not session_id:
        emit('resume_result', {
            'success': False,
            'error': 'Session ID required'
        })
        return
    
    agent_manager = get_agent_manager(agent_type)
    if agent_manager:
        session_obj = agent_manager.db.get_session(session_id)
        if not session_obj:
            emit('resume_result', {
                'success': False,
                'error': 'Session not found'
            })
            return
        
        messages = agent_manager.db.get_session_messages(session_id)
        
        emit('resume_result', {
            'success': True,
            'session': asdict(session_obj),
            'messages': [asdict(m) for m in messages]
        })
    else:
        emit('resume_result', {
            'success': False,
            'error': f'{agent_type} agent manager not found'
        })

@socketio.on('resume_agent_session')
def handle_resume_agent_session(data):
    """Resume an agent session using agent_api_session_id"""
    agent_type = data.get('agent_type', 'claude')
    session_id = data.get('session_id')
    
    if not session_id:
        emit('resume_agent_result', {
            'success': False,
            'error': 'Session ID required'
        })
        return
    
    agent_manager = get_or_create_agent_manager(agent_type)
    if agent_manager:
        session_obj = agent_manager.db.get_session(session_id)
        if not session_obj:
            emit('resume_agent_result', {
                'success': False,
                'error': 'Session not found'
            })
            return
        
        # Check if session has agent_api_session_id for resumption
        if not session_obj.agent_api_session_id:
            emit('resume_agent_result', {
                'success': False,
                'error': 'Session does not have an agent API session ID for resumption'
            })
            return
        
        # For Claude, use the resume_session method
        if agent_type == 'claude' and hasattr(agent_manager, 'resume_session'):
            result = agent_manager.resume_session(
                session_id=session_id,
                agent_api_session_id=session_obj.agent_api_session_id,
                working_dir=session_obj.working_directory,
                session_name=session_obj.name
            )
            
            if result['success']:
                try:
                    # Emit early ack to unblock UI
                    emit('session_resumed', {
                        'success': True,
                        'session_id': result.get('session_id'),
                        'session_name': result.get('session_name'),
                        'working_directory': result.get('working_directory'),
                        'agent_api_session_id': result.get('agent_api_session_id'),
                        'message_count': result.get('message_count', 0),
                        'history': result.get('history', [])
                    }, room=request.sid)
                    
                    # Also emit resume_agent_result for session viewer compatibility
                    emit('resume_agent_result', {
                        'success': True,
                        'session_id': result.get('session_id'),
                        'session_name': result.get('session_name'),
                        'working_directory': result.get('working_directory'),
                        'agent_api_session_id': result.get('agent_api_session_id'),
                        'message_count': result.get('message_count', 0)
                    })
                    
                    # Join session room
                    join_room(result['session_id'])
                    
                    # Start file watching for this session (non-blocking and tolerant)
                    try:
                        file_tracker.start_watching(result['session_id'], session_obj.working_directory)
                    except Exception as e:
                        print(f"Warning: file watcher failed to start: {e}")
                    
                    # Connect client and optionally send connection_result with history
                    try:
                        connection_result = agent_manager.connect_client(request.sid, data.get('device_id'))
                        # Send a secondary update with history and timers, but do not block UI
                        emit('connection_result', connection_result, room=request.sid)
                    except Exception as e:
                        print(f"Warning: connect_client failed: {e}")
                except Exception as e:
                    print(f"Error emitting session_resumed: {e}")
            else:
                emit('resume_agent_result', {
                    'success': False,
                    'error': result.get('error', 'Failed to resume agent session')
                })
        else:
            emit('resume_agent_result', {
                'success': False,
                'error': f'Agent session resume not supported for {agent_type} agent'
            })
    else:
        emit('resume_agent_result', {
            'success': False,
            'error': f'{agent_type} agent manager not found'
        })

@socketio.on('send_key')
def handle_send_key(data):
    """Handle sending a single key or escape sequence"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)
    
    if agent_manager:
        key = data.get('key')
        if key:
            success = agent_manager.send_key_sequence(key, request.sid)
            # We don't need to emit a status for every key press,
            # as it would be too chatty. The visual feedback will
            # come from the agent's output.

@socketio.on('resize_terminal')
def handle_resize_terminal(data):
    """Handle terminal resize request from client"""
    agent_type = data.get('agent_type', 'claude')
    agent_manager = get_agent_manager(agent_type)

    if agent_manager:
        rows = data.get('rows')
        cols = data.get('cols')
        if rows and cols:
            agent_manager.resize_pty(rows, cols)

# Add this to your Flask-SocketIO application

@socketio.on('tool_approval')
def handle_tool_approval(data):
    """Handle tool approval from client"""
    try:
        agent_type = data.get('agent_type', 'claude')
        tool_use_id = data.get('tool_use_id')
        approved = data.get('approved', False)
        reason = data.get('reason', '')
        # session_id = data.get('session_id')

        if not tool_use_id:
            emit('error', {'message': 'Missing tool_use_id'})
            return
        
        # Get the appropriate agent manager
        if agent_type == 'claude':
            manager = get_agent_manager(agent_type)  # Your Claude manager instance
        else:
            emit('error', {'message': f'Unknown agent type: {agent_type}'})
            return
        
        session_obj = asdict(manager.db.get_session(manager.current_session_id))
        
        # Handle the approval
        success = manager.handle_tool_approval(
            tool_use_id=tool_use_id,
            approved=approved,
            client_id=session_obj.get('client_id'),
            device_id=session_obj.get('device_id'),
            reason=reason
        )
        
        if success:
            # Broadcast approval decision to all clients in session
            emit('approval_decision', {
                'tool_use_id': tool_use_id,
                'approved': approved,
                'reason': reason,
                'timestamp': datetime.now().isoformat()
            }, room=manager.current_session_id, broadcast=True)
            
            logger.info(f"Tool approval processed: {tool_use_id} -> {approved}")
        else:
            emit('error', {'message': 'Failed to process approval'})
            
    except Exception as e:
        logger.error(f"Error handling tool approval: {e}")
        emit('error', {'message': str(e)})

@socketio.on('send_streaming_command')
def handle_streaming_command(data):
    """Handle streaming command with improved approval integration"""
    try:
        agent_type = data.get('agent_type', 'claude')
        command = data.get('command', '').strip()
        
        if not command:
            return
        
        # Get the appropriate agent manager
        if agent_type == 'claude':
            manager = get_agent_manager(agent_type)
        else:
            emit('error', {'message': f'Unknown agent type: {agent_type}'})
            return
        
        # Ensure client is in the session room for receiving agent_output events
        ensure_client_in_session_room(manager, request.sid, f"streaming command: {command}")
        
        session_obj = asdict(manager.db.get_session(manager.current_session_id))

        # Send streaming command
        success = manager.send_streaming_command(
            command=command,
            client_id=request.sid,  # Use request.sid instead of session_obj.get('client_id')
            device_id=data.get('device_id')  # Use device_id from request data
        )
        
        if not success:
            emit('error', {'message': 'Failed to send command'})
            
    except Exception as e:
        logger.error(f"Error handling streaming command: {e}")
        emit('error', {'message': str(e)})

# Cleanup function
def cleanup():
    """Cleanup resources on shutdown"""
    for agent_type in list(agent_managers.keys()):
        cleanup_agent_manager(agent_type)

# Register cleanup function
atexit.register(cleanup)

# Signal handlers for graceful shutdown
def signal_handler(signum, frame):
    """Handle shutdown signals"""
    print(f"\nReceived signal {signum}, shutting down gracefully...")
    cleanup()
    exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


if __name__ == '__main__':
    print("Starting MobileBuilder...")
    
    # --- Modified section for HTTPS ---

    # IMPORTANT: Replace 'my-computer.local' with your actual computer's hostname
    # that you used with mkcert.
    hostname = os.getenv('LOCAL_HOSTNAME', 'my-computer.local') # <--- CHANGE THIS
    port = os.getenv('PORT', 10000)

    # Generate with `openssl req -x509 -newkey rsa:4096 -nodes -out {hostname}-cert.pem -keyout {hostname}-key.pem -days 365 -subj "/CN={hostname}.local"`
    cert_file = f'{hostname}+4-cert.pem'
    key_file = f'{hostname}+4-key.pem'
    ssl_context = (cert_file, key_file)

    print(f"Server is running with HTTPS. Access it at:")
    print(f"  - On this machine: https://localhost:{port} or https://{hostname}:{port}")
    print(f"  - On your local network: https://{hostname}:{port} (replace hostname with your IP if needed)")
    print("Press Ctrl+C to stop")
    
    # Run the application with the SSL context
    try:
        socketio.run(app, host='0.0.0.0', port=port, debug=True, ssl_context=ssl_context, use_reloader=False)
    except FileNotFoundError:
        print("\n--- SSL ERROR ---")
        print(f"Could not find certificate files: '{cert_file}' and '{key_file}'")
        print("Please make sure you have generated them with mkcert and they are in the correct directory.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")

