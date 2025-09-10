#!/usr/bin/env python3
"""
Cursor Agent Wrapper - Lightweight wrapper for Cursor-specific functionality
This file serves as a minimal wrapper that imports and calls the shared logic
from generic_agent.py, passing in "cursor-agent" as the specific command.
"""

# Import the generic agent functionality
from .generic_agent import GenericAgentManager
from .db_manager import DatabaseManager, Message, Session
from pathlib import Path

# Cursor-specific configuration
CURSOR_COMMAND = "cursor-agent"
CURSOR_DB_PATH = Path("agents/cursor_sessions.db")

def create_cursor_manager(socketio_instance):
    """Create a Cursor-specific agent manager"""
    return GenericAgentManager(CURSOR_COMMAND, CURSOR_DB_PATH, socketio_instance, exit_command="exit")

# For backward compatibility, you can still import these classes directly
__all__ = ['GenericAgentManager', 'DatabaseManager', 'Message', 'Session', 'create_cursor_manager']
