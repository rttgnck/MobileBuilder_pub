#!/usr/bin/env python3
"""
Gemini Agent Wrapper - Lightweight wrapper for Gemini-specific functionality
This file serves as a minimal wrapper that imports and calls the shared logic
from generic_agent.py, passing in "gemini" as the specific command.
"""

# Import the generic agent functionality
from .generic_agent import GenericAgentManager
from .db_manager import DatabaseManager, Message, Session
from pathlib import Path

# Gemini-specific configuration
GEMINI_COMMAND = "gemini"
GEMINI_DB_PATH = Path("agents/gemini_sessions.db")

def create_gemini_manager(socketio_instance):
    """Create a Gemini-specific agent manager"""
    return GenericAgentManager(GEMINI_COMMAND, GEMINI_DB_PATH, socketio_instance, exit_command="/quit")

# For backward compatibility, you can still import these classes directly
__all__ = ['GenericAgentManager', 'DatabaseManager', 'Message', 'Session', 'create_gemini_manager']
