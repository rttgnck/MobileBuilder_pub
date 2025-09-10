#!/usr/bin/env python3
"""
Codex Agent Wrapper - Lightweight wrapper for Codex-specific functionality
This file serves as a minimal wrapper that imports and calls the shared logic
from generic_agent.py, passing in "codex" as the specific command.
"""

# Import the generic agent functionality
from .generic_agent import GenericAgentManager
from .db_manager import DatabaseManager, Message, Session
from pathlib import Path

# Codex-specific configuration
CODEX_COMMAND = "codex"
CODEX_DB_PATH = Path("agents/codex_sessions.db")

def create_codex_manager(socketio_instance):
    """Create a Codex-specific agent manager"""
    return GenericAgentManager(CODEX_COMMAND, CODEX_DB_PATH, socketio_instance, exit_command="exit")

# For backward compatibility, you can still import these classes directly
__all__ = ['GenericAgentManager', 'DatabaseManager', 'Message', 'Session', 'create_codex_manager']
