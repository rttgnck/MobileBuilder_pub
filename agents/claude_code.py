#!/usr/bin/env python3
"""
Claude Agent Wrapper - Python SDK implementation for Claude Code
This file provides a specialized wrapper for Claude that uses the official Python SDK
with proper streaming, multi-turn conversations, session management, and simplified approval handling.
"""

import asyncio
import threading
import queue
import os
import time
import json
import uuid
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from flask_socketio import SocketIO
import logging

# Import the Claude Code Python SDK
from claude_code_sdk import ClaudeSDKClient, ClaudeCodeOptions, CLINotFoundError, ProcessError

# Import the generic agent functionality for database and message handling
from .db_manager import DatabaseManager, Message, Session


logger = logging.getLogger(__name__)

# Configuration
DEFAULT_WORKING_DIR = os.getenv("DEFAULT_WORKING_DIR")
SESSION_MAX_DURATION = 5 * 60 * 60  # 5 hours in seconds
WARNING_INTERVALS = [3600, 1800, 900, 600, 300, 60]  # 1hr, 30min, 15min, 10min, 5min, 1min

class ClaudeSDKManager:
    """Simplified manager for Claude using the official Python SDK with new approval system"""
    
    def __init__(self, db_path: Path, socketio_instance: SocketIO):
        self.agent_command = "claude"
        self.db_path = db_path
        self.socketio = socketio_instance
        self.active_session = None
        self.is_running = False
        self.connected_clients = set()
        self.command_queue = queue.Queue()
        self.session_start_time = None
        self.total_active_time = 0
        self.warning_timers = {}
        self.db = DatabaseManager(db_path)
        self.current_session_id = None
        self.working_directory = DEFAULT_WORKING_DIR
        self.lock = threading.Lock()
        self.current_claude_session_id = None  # Claude's internal session ID
        self.output_buffer = ""
        self.is_processing = False
        self.sdk_client = None  # ClaudeSDKClient instance
        self.sdk_options = None  # ClaudeCodeOptions instance
        self.event_loop = None  # Async event loop for SDK operations
        self.loop_thread = None  # Thread running the event loop
        self.has_emitted_init = False  # Track if we've emitted initialization message
    
    def start_session(self, working_dir: str = None, session_name: str = None) -> Dict[str, Any]:
        """Start a new Claude SDK session"""
        with self.lock:
            if self.is_running:
                logger.info("Claude session already running")
                return {
                    'success': False,
                    'error': 'Session already running',
                    'session_id': self.current_session_id
                }
            
            try:
                # Set working directory
                self.working_directory = working_dir or DEFAULT_WORKING_DIR
                logger.info(f"Starting Claude SDK session in directory: {self.working_directory}")
                
                # Validate directory exists
                if not os.path.exists(self.working_directory):
                    logger.error(f"Directory does not exist: {self.working_directory}")
                    return {
                        'success': False,
                        'error': f'Directory does not exist: {self.working_directory}'
                    }
                
                # Create session record
                self.current_session_id = str(uuid.uuid4())
                session_name = session_name or f"Claude Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                
                session = Session(
                    id=self.current_session_id,
                    name=session_name,
                    start_time=datetime.now().isoformat(),
                    end_time=None,
                    working_directory=self.working_directory,
                    message_count=0,
                    status='active'
                )
                
                logger.info(f"Creating session record: {self.current_session_id}")
                self.db.create_session(session)
                
                # Initialize Claude SDK session
                logger.info("Initializing Claude SDK session...")
                
                self.is_running = True
                self.session_start_time = datetime.now()
                self.total_active_time = 0
                
                # Start async event loop in a separate thread
                self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
                self.loop_thread.start()
                
                # Wait for event loop to be ready
                max_wait = 10  # Maximum wait time in seconds
                wait_time = 0
                while self.event_loop is None and wait_time < max_wait:
                    time.sleep(0.1)
                    wait_time += 0.1
                
                if self.event_loop is None:
                    logger.error("Failed to create event loop within timeout")
                    return {
                        'success': False,
                        'error': 'Failed to initialize event loop'
                    }
                
                logger.info("Event loop initialized successfully")
                
                # Start command processor thread
                logger.info("Starting command processor thread...")
                threading.Thread(target=self._process_commands, daemon=True).start()
                
                # Start session timer
                logger.info("Starting session timer...")
                self._start_session_timer()
                
                logger.info(f"Started Claude SDK session: {self.current_session_id}")
                
                return {
                    'success': True,
                    'session_id': self.current_session_id,
                    'session_name': session_name,
                    'working_directory': self.working_directory
                }
                
            except Exception as e:
                logger.error(f"Error starting Claude SDK session: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
    
    def resume_session(self, session_id: str, agent_api_session_id: str, working_dir: str = None, session_name: str = None) -> Dict[str, Any]:
        """Resume an existing Claude SDK session using the agent API session ID"""
        with self.lock:
            if self.is_running:
                logger.info("Claude session already running")
                return {
                    'success': False,
                    'error': 'Session already running',
                    'session_id': self.current_session_id
                }
            
            try:
                # Get the existing session from database
                existing_session = self.db.get_session(session_id)
                if not existing_session:
                    return {
                        'success': False,
                        'error': 'Session not found'
                    }
                
                # Set working directory from existing session or provided parameter
                self.working_directory = working_dir or existing_session.working_directory
                logger.info(f"Resuming Claude SDK session in directory: {self.working_directory}")
                
                # Validate directory exists
                if not os.path.exists(self.working_directory):
                    logger.error(f"Directory does not exist: {self.working_directory}")
                    return {
                        'success': False,
                        'error': f'Directory does not exist: {self.working_directory}'
                    }
                
                # Set current session ID to the existing session
                self.current_session_id = session_id
                self.current_claude_session_id = agent_api_session_id
                
                # Update session status to active
                self.db.update_session(session_id, status='active', end_time=None)
                
                # Initialize Claude SDK session with resume_id
                logger.info(f"Initializing Claude SDK session with resume_id: {agent_api_session_id}")
                
                self.is_running = True
                self.session_start_time = datetime.now()
                self.has_emitted_init = False
                
                # Create SDK options with resume_id
                self.sdk_options = ClaudeCodeOptions(
                    system_prompt="You are a helpful AI assistant specialized in coding, debugging, and problem-solving. When you need to use tools that may require approval, the system will handle approval requests automatically.",
                    max_turns=10,
                    cwd=self.working_directory,
                    resume=agent_api_session_id,  # This is the key parameter for resuming
                    # Allow all tools - approval is handled by our separate MCP server
                    allowed_tools=[],  # Empty means allow all
                    disallowed_tools=[],  # No disabled tools
                    permission_mode="default",  # Use MCP permission handling
                    permission_prompt_tool_name="mcp__approve-tools__permissions__approve",  # Points to our approve_tools.py
                    continue_conversation=True,  # Enable multi-turn conversations
                    mcp_servers=os.getenv("MCP_SERVERS")  # Use our MCP servers configuration
                )
                
                # Start the event loop thread
                self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
                self.loop_thread.start()
                
                # Wait for event loop to be ready
                max_wait = 10  # Maximum wait time in seconds
                wait_time = 0
                while self.event_loop is None and wait_time < max_wait:
                    time.sleep(0.1)
                    wait_time += 0.1
                
                if self.event_loop is None:
                    logger.error("Failed to create event loop within timeout")
                    return {
                        'success': False,
                        'error': 'Failed to initialize event loop'
                    }
                
                logger.info("Event loop initialized successfully for resume")
                
                # Start command processor thread
                logger.info("Starting command processor thread for resume...")
                threading.Thread(target=self._process_commands, daemon=True).start()
                
                # Start session timer
                logger.info("Starting session timer for resume...")
                self._start_session_timer()
                
                # Add system message indicating session resumption
                resume_message = Message(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    type='system',
                    content=f"🔄 Resuming Claude session with agent API session ID: {agent_api_session_id}",
                    timestamp=datetime.now().isoformat()
                )
                self.db.save_message(resume_message)
                
                # # Load messages
                messages = self.db.get_session_messages(session_id)
                
                logger.info(f"Successfully resumed Claude SDK session: {session_id}")
                
                return {
                    'success': True,
                    'session_id': self.current_session_id,
                    'session_name': existing_session.name,
                    'working_directory': self.working_directory,
                    'agent_api_session_id': agent_api_session_id,
                    'message_count': len(messages),
                    'history': [asdict(msg) for msg in messages]
                }
                
            except Exception as e:
                logger.error(f"Error resuming Claude SDK session: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
    
    def _run_event_loop(self):
        """Run the async event loop for SDK operations"""
        try:
            # Create new event loop for this thread
            self.event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.event_loop)
            
            logger.info("Event loop created successfully")
            
            # Initialize SDK client and options with MCP approval server
            # Only create new options if they don't already exist (for resume scenarios)
            if not self.sdk_options:
                self.sdk_options = ClaudeCodeOptions(
                    system_prompt="You are a helpful AI assistant specialized in coding, debugging, and problem-solving. When you need to use tools that may require approval, the system will handle approval requests automatically.",
                    max_turns=10,
                    cwd=self.working_directory,
                    # Allow all tools - approval is handled by our separate MCP server
                    allowed_tools=[],  # Empty means allow all
                    disallowed_tools=[],  # No disabled tools
                    permission_mode="default",  # Use MCP permission handling
                    permission_prompt_tool_name="mcp__approve-tools__permissions__approve",  # Points to our approve_tools.py
                    continue_conversation=True,  # Enable multi-turn conversations
                    mcp_servers=os.getenv("MCP_SERVERS") # Use our MCP servers configuration
                )
                logger.info("Event loop started for Claude SDK with new session")
            else:
                logger.info("Event loop started for Claude SDK with existing options (resume scenario)")
            
            # Keep the event loop running
            self.event_loop.run_forever()
            
        except Exception as e:
            logger.error(f"Error in event loop: {e}")
            import traceback
            traceback.print_exc()
        finally:
            if self.event_loop and not self.event_loop.is_closed():
                self.event_loop.close()
    
    def connect_client(self, client_id: str, device_id: str = None) -> Dict[str, Any]:
        """Connect a client to the active session"""
        with self.lock:
            logger.info(f"Client {client_id} attempting to connect to Claude SDK session")
            
            if not self.is_running:
                logger.warning(f"Client {client_id} connection failed: No active session")
                return {
                    'success': False,
                    'error': 'No active session'
                }
            
            self.connected_clients.add(client_id)
            logger.info(f"Client {client_id} connected to Claude SDK session")
            
            # Get session history for this client
            messages = self.db.get_session_messages(self.current_session_id)
            logger.info(f"Loaded {len(messages)} messages for client {client_id}")
            
            return {
                'success': True,
                'session_id': self.current_session_id,
                'history': [asdict(msg) for msg in messages],
                'working_directory': self.working_directory,
                'session_time_remaining': self._get_remaining_time()
            }
    
    def disconnect_client(self, client_id: str):
        """Disconnect a client"""
        with self.lock:
            self.connected_clients.discard(client_id)
            logger.info(f"Client disconnected: {client_id}")
    
    def send_command(self, command: str, client_id: str, device_id: str = None) -> bool:
        """Queue a command to be sent to Claude"""
        logger.info(f"ClaudeSDKManager.send_command called: command='{command}', client_id='{client_id}', device_id='{device_id}'")
        logger.info(f"Session running: {self.is_running}")
        logger.info(f"Event loop ready: {self.event_loop is not None and not self.event_loop.is_closed()}")
        logger.info(f"Command queue size: {self.command_queue.qsize()}")
        
        if not self.is_running:
            logger.warning(f"Command '{command}' from client {client_id} failed: Session not running")
            return False
        
        try:
            self.command_queue.put((command, client_id, device_id), timeout=1.0)
            logger.info(f"Command queued successfully: {command.strip()}")
            logger.info(f"Command queue size after adding: {self.command_queue.qsize()}")
            return True
        except queue.Full:
            logger.error(f"Command queue is full, cannot queue command: {command}")
            return False
        except Exception as e:
            logger.error(f"Error queueing command '{command}' from client {client_id}: {e}")
            return False
    
    def send_streaming_command(self, command: str, client_id: str, device_id: str = None) -> bool:
        """Send a streaming command directly to Claude SDK (bypasses queue for immediate processing)"""
        if not self.is_running:
            logger.warning(f"Streaming command '{command}' from client {client_id} failed: Session not running")
            return False
        
        try:
            # Save the user message to the database
            message = Message(
                id=str(uuid.uuid4()),
                session_id=self.current_session_id,
                type='user',
                content=command,
                timestamp=datetime.now().isoformat(),
                device_id=device_id,
                metadata=None
            )
            self.db.save_message(message)
            
            # Send command directly to Claude SDK with streaming
            if self._send_to_claude_sdk_streaming(command):
                logger.info(f"Streaming command sent to Claude SDK: {command}")
                return True
            else:
                logger.warning(f"Failed to send streaming command to Claude SDK: {command}")
                return False
                
        except Exception as e:
            logger.error(f"Error sending streaming command '{command}' from client {client_id}: {e}")
            return False
    
    def send_streaming_input(self, input_chunk: str, client_id: str, device_id: str = None) -> bool:
        """Send streaming input chunk to Claude (for real-time input)"""
        if not self.is_running:
            logger.warning(f"Streaming input from client {client_id} failed: Session not running")
            return False
        
        try:
            # For streaming input, we can accumulate chunks and send them
            # This is useful for real-time typing or voice input
            logger.debug(f"Received streaming input chunk from client {client_id}: {len(input_chunk)} characters")
            
            # Emit acknowledgment to client
            self.socketio.emit('streaming_input_ack', {
                'chunk_length': len(input_chunk),
                'timestamp': datetime.now().isoformat(),
                'client_id': client_id
            }, room=self.current_session_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling streaming input from client {client_id}: {e}")
            return False
    
    def handle_tool_approval(self, tool_use_id: str, approved: bool, client_id: str, device_id: str = None, reason: str = None) -> bool:
        """Handle tool approval or dismissal (legacy method for compatibility)"""
        # This method is kept for backward compatibility
        # Actual approval is handled by the approve_tools.py MCP server and main app routes
        logger.info(f"Legacy tool approval received: {approved} for tool_use_id: {tool_use_id}")
        
        # Emit approval decision to all clients for UI updates
        self.socketio.emit('approval_decision', {
            'tool_use_id': tool_use_id,
            'approved': approved,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }, room=self.current_session_id)
        
        return True
    
    def _process_commands(self):
        """Process queued commands and send them to Claude SDK"""
        logger.info("Claude command processor thread started")
        while self.is_running:
            try:
                logger.debug(f"Command processor waiting for commands, queue size: {self.command_queue.qsize()}")
                command_data = self.command_queue.get(timeout=0.1)
                command, client_id, device_id = command_data
                
                logger.info(f"Processing command from queue: '{command}' from client {client_id}")
                
                # Save the user message to the database
                message = Message(
                    id=str(uuid.uuid4()),
                    session_id=self.current_session_id,
                    type='user',
                    content=command,
                    timestamp=datetime.now().isoformat(),
                    device_id=device_id,
                    metadata=None
                )
                self.db.save_message(message)
                logger.info(f"User message saved to database")
                
                # Send command to Claude SDK
                logger.info(f"Attempting to send command to Claude SDK: '{command}'")
                if self._send_to_claude_sdk(command):
                    logger.info(f"Command sent to Claude SDK successfully: {command}")
                else:
                    logger.warning(f"Failed to send command to Claude SDK: {command}")
                
                self.command_queue.task_done()
                logger.info(f"Command processing completed for: '{command}'")
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in command processor: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.1)
        
        logger.info("Command processor thread ended for Claude SDK session")
    
    def _send_to_claude_sdk(self, command: str) -> bool:
        """Send a command to Claude SDK (non-streaming)"""
        logger.info(f"_send_to_claude_sdk called with command: '{command}'")
        
        if not self.is_running:
            logger.error("Session is not running")
            return False
            
        if not self.event_loop:
            logger.error("Event loop is not initialized")
            return False
            
        if self.event_loop.is_closed():
            logger.error("Event loop is closed")
            return False
        
        logger.info(f"Event loop is ready, scheduling async command")
        
        try:
            # Schedule the async operation in the event loop
            future = asyncio.run_coroutine_threadsafe(
                self._async_send_command(command, streaming=False),
                self.event_loop
            )
            
            logger.info(f"Async command scheduled, waiting for result...")
            # Wait for completion with timeout
            result = future.result(timeout=300)  # 5 minute timeout
            logger.info(f"Async command completed with result: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Error sending command to Claude SDK: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _send_to_claude_sdk_streaming(self, command: str) -> bool:
        """Send a command to Claude SDK with streaming support"""
        if not self.is_running:
            logger.error("Session is not running")
            return False
            
        if not self.event_loop:
            logger.error("Event loop is not initialized")
            return False
            
        if self.event_loop.is_closed():
            logger.error("Event loop is closed")
            return False
        
        try:
            # Schedule the async operation in the event loop
            future = asyncio.run_coroutine_threadsafe(
                self._async_send_command(command, streaming=True),
                self.event_loop
            )
            
            # Don't wait for completion - let it stream in background
            # The streaming will happen asynchronously
            return True
            
        except Exception as e:
            logger.error(f"Error sending streaming command to Claude SDK: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    async def _async_send_command(self, command: str, streaming: bool = True) -> bool:
        """Async method to send command to Claude SDK"""
        try:
            # Create or reuse SDK client
            if not self.sdk_client:
                self.sdk_client = ClaudeSDKClient(options=self.sdk_options)
                await self.sdk_client.__aenter__()
                logger.info("Claude SDK client initialized")
            
            # Send the query
            await self.sdk_client.query(command)
            
            if streaming:
                # Stream the response
                await self._stream_sdk_response()
            else:
                # Collect full response
                await self._collect_sdk_response()
            
            return True
            
        except CLINotFoundError:
            logger.error("Claude CLI not found. Please install: npm install -g @anthropic-ai/claude-code")
            self._emit_error("Claude CLI not found. Please install the CLI first.")
            return False
        except ProcessError as e:
            logger.error(f"Claude process error: {e}")
            self._emit_error(f"Claude process error: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error in async send command: {e}")
            self._emit_error(f"Error: {str(e)}")
            return False
    
    async def _stream_sdk_response(self):
        """Stream Claude SDK response in real-time"""
        try:
            full_response = ""
            tool_use_count = 0
            
            async for message in self.sdk_client.receive_response():
                message_type = type(message).__name__
                logger.info(f"Received message type: {message_type}")
                
                # Handle SystemMessage
                if message_type == "SystemMessage":
                    if hasattr(message, 'subtype'):
                        if message.subtype == 'init':
                            # Session initialization
                            if hasattr(message, 'data') and isinstance(message.data, dict):
                                session_id = message.data.get('session_id')
                                if session_id:
                                    self.current_claude_session_id = session_id
                                    logger.info(f"Claude session initialized with ID: {session_id}")
                                    
                                    # Update the database with the agent API session ID
                                    if self.current_session_id:
                                        self.db.update_session(self.current_session_id, agent_api_session_id=session_id)
                                        logger.info(f"Updated session {self.current_session_id} with agent API session ID: {session_id}")
                                
                                # Show initialization details
                                init_info = "Claude Session Initialized\n"
                                if hasattr(message, 'data'):
                                    data = message.data
                                    if 'cwd' in data:
                                        init_info += f"Working Directory: {data['cwd']}\n"
                                    if 'model' in data:
                                        init_info += f"Model: {data['model']}\n"
                                    if 'tools' in data:
                                        tools = data['tools']
                                        init_info += f"Available Tools: {', '.join(tools[:5])}"
                                        if len(tools) > 5:
                                            init_info += f" (and {len(tools) - 5} more)"
                                        init_info += "\n"
                                    if 'permissionMode' in data:
                                        init_info += f"Permission Mode: {data['permissionMode']}\n"
                                
                                self._emit_streaming_output(init_info, "init")
                                self.has_emitted_init = True
                            else:
                                # Other system messages
                                system_content = f"System Message ({message.subtype})\n"
                                if hasattr(message, 'data'):
                                    system_content += f"{json.dumps(message.data, indent=2)}"
                                else:
                                    system_content += str(message)
                                self._emit_streaming_output(system_content, "system_message")
                        else:
                            # Generic system message
                            system_content = f"System Message\n{str(message)}"
                            self._emit_streaming_output(system_content, "system_message")
                    else:
                        # System message without subtype
                        system_content = f"System Message\n{str(message)}"
                        self._emit_streaming_output(system_content, "system_message")
                
                # Handle AssistantMessage
                elif message_type == "AssistantMessage":
                    if hasattr(message, 'content'):
                        assistant_content = ""
                        for block in message.content:
                            block_type = type(block).__name__
                            logger.info(f"Processing assistant message block type: {block_type}")
                            if block_type == 'TextBlock':
                                if hasattr(block, 'text'):
                                    # Text content - stream it as simple assistant message
                                    text_content = block.text
                                    full_response += text_content
                                    assistant_content += text_content
                            elif block_type == 'ToolUseBlock':
                                # Tool use - show tool information
                                tool_name = block.name
                                tool_input = getattr(block, 'input', {})
                                tool_use_id = getattr(block, 'id', '')
                                tool_use_count += 1
                                
                                # Format tool use display
                                if isinstance(tool_input, dict):
                                    command = tool_input.get('command', '')
                                    description = tool_input.get('description', '')
                                    if command:
                                        tool_display = f"Using {tool_name}:\n{command}"
                                        if description:
                                            tool_display += f"\n{description}"
                                    else:
                                        tool_display = f"Using {tool_name}"
                                else:
                                    tool_display = f"Using {tool_name}"
                                
                                # Emit tool use (approval is handled by separate system)
                                self._emit_streaming_output(tool_display, "tool_use", metadata={'tool_use_id': tool_use_id, 'tool_name': tool_name})
                        
                        # Emit assistant text content if any
                        if assistant_content.strip():
                            self._emit_streaming_output(assistant_content, "assistant_message")
                    else:
                        # Assistant message without content
                        self._emit_streaming_output(f"Assistant Message\n{str(message)}", "assistant_message")
                
                # Handle UserMessage (tool results)
                elif message_type == "UserMessage":
                    if hasattr(message, 'content'):
                        for block in message.content:
                            block_type = type(block).__name__
                            if block_type == 'ToolResultBlock':
                                tool_result = getattr(block, 'content', '')
                                is_error = getattr(block, 'is_error')
                                tool_use_id = getattr(block, 'tool_use_id', '')
                                
                                # Format tool result
                                if is_error:
                                    formatted_content = f"Tool Error\n{tool_result}"
                                    result_type = "tool_error"
                                else:
                                    # Format tool result nicely
                                    if len(tool_result) > 500:
                                        # Truncate long results
                                        preview = tool_result[:500] + "..."
                                        formatted_content = f"Tool Result\n{preview}\nResult truncated - {len(tool_result)} characters total"
                                    else:
                                        formatted_content = f"Tool Result\n{tool_result}"
                                    result_type = "tool_result"
                                
                                self._emit_streaming_output(formatted_content, result_type, metadata={'tool_use_id': tool_use_id})
                            else:
                                # Other user message content
                                user_content = f"User Message\n{str(block)}"
                                self._emit_streaming_output(user_content, "user_message")
                    else:
                        # User message without content
                        self._emit_streaming_output(f"User Message\n{str(message)}", "user_message")
                
                # Handle ResultMessage
                elif message_type == "ResultMessage":
                    # Final result message
                    result = getattr(message, 'result', '')
                    session_id = getattr(message, 'session_id', None)
                    
                    if session_id:
                        self.current_claude_session_id = session_id
                    
                    # Save the complete response to database
                    if full_response.strip():
                        message_obj = Message(
                            id=str(uuid.uuid4()),
                            session_id=self.current_session_id,
                            type='agent',
                            content=full_response,
                            timestamp=datetime.now().isoformat(),
                            device_id=None,
                            metadata=None
                        )
                        self.db.save_message(message_obj)
                    
                    # Format final result
                    if result.strip():
                        formatted_result = f"Final Result\n{result}"
                    else:
                        formatted_result = "Task Completed Successfully"
                    
                    self._emit_streaming_output(formatted_result, "final_result")
                    
                    # Create usage metadata block
                    usage_info = "Session Usage\n"
                    if hasattr(message, 'total_cost_usd'):
                        usage_info += f"Cost: ${message.total_cost_usd:.6f}\n"
                    if hasattr(message, 'duration_ms'):
                        duration_sec = message.duration_ms / 1000
                        usage_info += f"Duration: {duration_sec:.2f}s\n"
                    if hasattr(message, 'num_turns'):
                        usage_info += f"Turns: {message.num_turns}\n"
                    if hasattr(message, 'usage') and message.usage:
                        usage = message.usage
                        if 'input_tokens' in usage:
                            usage_info += f"Input Tokens: {usage['input_tokens']}\n"
                        if 'output_tokens' in usage:
                            usage_info += f"Output Tokens: {usage['output_tokens']}\n"
                        if 'cache_read_input_tokens' in usage:
                            usage_info += f"Cache Read: {usage['cache_read_input_tokens']} tokens\n"
                        if 'cache_creation_input_tokens' in usage:
                            usage_info += f"Cache Created: {usage['cache_creation_input_tokens']} tokens\n"
                    
                    # Emit usage metadata in separate block
                    if usage_info != "Session Usage\n":
                        self._emit_streaming_output(usage_info, "usage_metadata")
                    
                    break
                
                # Handle ErrorMessage
                elif message_type == "ErrorMessage":
                    error_msg = getattr(message, 'error', 'Unknown error occurred')
                    formatted_error = f"Error\n{error_msg}"
                    self._emit_streaming_output(formatted_error, "error")
                
                # Handle any other message types
                else:
                    # Unknown or other message type
                    logger.info(f"Displaying message type: {message_type}")
                    other_content = f"{message_type}\n{str(message)}"
                    self._emit_streaming_output(other_content, "other_message")
            
        except Exception as e:
            logger.error(f"Error streaming SDK response: {e}")
            self._emit_streaming_output(f"Error processing response\n{str(e)}", "error")
    
    async def _collect_sdk_response(self):
        """Collect full Claude SDK response (non-streaming)"""
        try:
            full_response = ""
            
            async for message in self.sdk_client.receive_response():
                message_type = type(message).__name__
                
                if message_type == "ResultMessage":
                    result = getattr(message, 'result', '')
                    session_id = getattr(message, 'session_id', None)
                    
                    if session_id:
                        self.current_claude_session_id = session_id
                    
                    # Save agent message
                    message_obj = Message(
                        id=str(uuid.uuid4()),
                        session_id=self.current_session_id,
                        type='agent',
                        content=result,
                        timestamp=datetime.now().isoformat(),
                        device_id=None,
                        metadata=None
                    )
                    self.db.save_message(message_obj)
                    
                    # Emit to clients
                    self.socketio.emit('agent_output', {
                        'content': result,
                        'timestamp': message_obj.timestamp,
                        'session_id': self.current_session_id
                    }, room=self.current_session_id)
                    break
                
                elif message_type == "ErrorMessage":
                    error_msg = getattr(message, 'error', 'Unknown error occurred')
                    self._emit_error(f"Error: {error_msg}")
                    break
            
        except Exception as e:
            logger.error(f"Error collecting SDK response: {e}")
            self._emit_error(f"Error: {str(e)}")
    
    def _emit_streaming_output(self, output: str, output_type: str = "streaming", metadata: Dict = None):
        """Emit streaming output to all connected clients and save to database"""
        if not output or not output.strip():
            return
        
        try:
            logger.debug(f"Emitting streaming output ({output_type}): {len(output)} characters")
            
            # Save the streaming message to the database
            message = Message(
                id=str(uuid.uuid4()),
                session_id=self.current_session_id,
                type='agent',
                content=output,
                timestamp=datetime.now().isoformat(),
                device_id=None,
                metadata=json.dumps({
                    'streaming': True,
                    'output_type': output_type,
                    'metadata': metadata
                }) if metadata else json.dumps({
                    'streaming': True,
                    'output_type': output_type
                })
            )
            self.db.save_message(message)
            
            # Broadcast to all connected clients in the session room
            emit_data = {
                'content': output,
                'timestamp': message.timestamp,
                'session_id': self.current_session_id,
                'streaming': True,
                'type': output_type
            }
            
            if metadata:
                emit_data['metadata'] = metadata
            
            self.socketio.emit('agent_output', emit_data, room=self.current_session_id)
            
            logger.info(f"Streaming output emitted to session room {self.current_session_id} for {len(self.connected_clients)} connected clients and saved to database")
            
        except Exception as e:
            logger.error(f"Error emitting streaming output: {e}")
    
    def _emit_output(self, output: str):
        """Emit output to all connected clients"""
        if not output or not output.strip():
            return
        
        try:
            logger.debug(f"Emitting output: {len(output)} characters")
            
            # Save agent message
            message = Message(
                id=str(uuid.uuid4()),
                session_id=self.current_session_id,
                type='agent',
                content=output,
                timestamp=datetime.now().isoformat(),
                device_id=None,
                metadata=None
            )
            self.db.save_message(message)
            
            # Broadcast to all connected clients in the session room
            self.socketio.emit('agent_output', {
                'content': output,
                'timestamp': message.timestamp,
                'session_id': self.current_session_id
            }, room=self.current_session_id)
            
            logger.info(f"Output emitted to session room {self.current_session_id} for {len(self.connected_clients)} connected clients")
            
        except Exception as e:
            logger.error(f"Error emitting output: {e}")
    
    def _emit_error(self, error_message: str):
        """Emit error message to all connected clients"""
        try:
            self.socketio.emit('agent_output', {
                'content': error_message,
                'timestamp': datetime.now().isoformat(),
                'session_id': self.current_session_id,
                'streaming': False,
                'type': 'error'
            }, room=self.current_session_id)
        except Exception as e:
            logger.error(f"Error emitting error message: {e}")
    
    def end_session(self, graceful: bool = True) -> bool:
        """End the current Claude SDK session"""
        with self.lock:
            if not self.is_running:
                return False
            
            try:
                # Capture session_id for post-cleanup notifications
                old_session_id = self.current_session_id
                # Stop warning timers
                for timer in self.warning_timers.values():
                    timer.cancel()
                self.warning_timers.clear()
                
                # Close SDK client if it exists
                if self.sdk_client and self.event_loop and not self.event_loop.is_closed():
                    try:
                        future = asyncio.run_coroutine_threadsafe(
                            self.sdk_client.__aexit__(None, None, None),
                            self.event_loop
                        )
                        future.result(timeout=5)  # 5 second timeout
                    except Exception as e:
                        logger.warning(f"Error closing SDK client: {e}")
                
                # Stop event loop
                if self.event_loop and not self.event_loop.is_closed():
                    self.event_loop.call_soon_threadsafe(self.event_loop.stop)
                
                # Wait for loop thread to finish
                if self.loop_thread and self.loop_thread.is_alive():
                    self.loop_thread.join(timeout=5)
                
                # Update session in database
                if self.current_session_id:
                    self.db.update_session(
                        self.current_session_id,
                        end_time=datetime.now().isoformat(),
                        status='completed' if graceful else 'terminated',
                        total_active_time=self.total_active_time
                    )
                
                # Clear command queue
                while not self.command_queue.empty():
                    try:
                        self.command_queue.get_nowait()
                        self.command_queue.task_done()
                    except queue.Empty:
                        break
                
                # Emit session_closed to notify all clients in the session room
                if old_session_id:
                    try:
                        self.socketio.emit('session_closed', {
                            'message': 'session closed',
                            'agent_type': 'claude',
                        }, room=old_session_id)
                    except Exception as e:
                        logger.warning(f"Failed to emit session_closed: {e}")

                # Reset state
                self.is_running = False
                self.session_start_time = None
                self.current_session_id = None
                self.current_claude_session_id = None
                self.sdk_client = None
                self.sdk_options = None
                self.event_loop = None
                self.loop_thread = None
                self.has_emitted_init = False
                
                logger.info("Claude SDK session ended")
                return True
                
            except Exception as e:
                logger.error(f"Error ending session: {e}")
                return False
    
    def _start_session_timer(self):
        """Start session duration timer with warnings"""
        def check_session_time():
            while self.is_running:
                elapsed = self._get_elapsed_time()
                remaining = SESSION_MAX_DURATION - elapsed
                
                # Check for warning intervals
                for interval in WARNING_INTERVALS:
                    if remaining <= interval and interval not in self.warning_timers:
                        self._send_time_warning(remaining)
                        self.warning_timers[interval] = True
                
                # Auto-terminate if exceeded
                if remaining <= 0:
                    logger.warning("Session time limit reached, terminating")
                    self.socketio.emit('session_timeout', {
                        'message': 'Session time limit reached. Session will now terminate.'
                    }, room=self.current_session_id)
                    self.end_session(graceful=True)
                    break
                
                time.sleep(10)  # Check every 10 seconds
        
        threading.Thread(target=check_session_time, daemon=True).start()
    
    def _send_time_warning(self, remaining_seconds: float):
        """Send time warning to all connected clients"""
        hours = int(remaining_seconds // 3600)
        minutes = int((remaining_seconds % 3600) // 60)
        
        if hours > 0:
            time_str = f"{hours} hour{'s' if hours > 1 else ''} {minutes} minute{'s' if minutes != 1 else ''}"
        else:
            time_str = f"{minutes} minute{'s' if minutes != 1 else ''}"
        
        self.socketio.emit('session_warning', {
            'remaining_seconds': remaining_seconds,
            'time_string': time_str,
            'message': f'Warning: Claude session will reset in {time_str}'
        }, room=self.current_session_id)
    
    def _get_elapsed_time(self) -> float:
        """Get total elapsed active time"""
        if not self.session_start_time:
            return 0
        return time.time() - self.session_start_time.timestamp()
    
    def _get_remaining_time(self) -> float:
        """Get remaining session time"""
        return max(0, SESSION_MAX_DURATION - self._get_elapsed_time())
    
    def get_status(self) -> Dict[str, Any]:
        """Get current session status"""
        if not self.is_running:
            return {
                'active': False,
                'session_id': None
            }
        
        return {
            'active': True,
            'session_id': self.current_session_id,
            'connected_clients': len(self.connected_clients),
            'elapsed_time': self._get_elapsed_time(),
            'remaining_time': self._get_remaining_time(),
            'working_directory': self.working_directory,
            'command_queue_size': self.command_queue.qsize(),
            'agent_ready': self.is_agent_ready(),
            'sdk_connected': self.sdk_client is not None
        }
    
    def is_agent_ready(self) -> bool:
        """Check if Claude SDK is ready to receive commands"""
        return (self.is_running and 
                self.event_loop is not None and 
                not self.event_loop.is_closed() and
                self.sdk_client is not None)
    
    def is_event_loop_ready(self) -> bool:
        """Check if the event loop is ready"""
        return (self.event_loop is not None and 
                not self.event_loop.is_closed())
    
    def send_enter_key(self, client_id: str, device_id: str = None) -> bool:
        """Send a simple enter key to Claude (not applicable in SDK mode)"""
        logger.info(f"Enter key requested from client {client_id} - not applicable in SDK mode")
        return True
    
    def send_backspace_key(self, client_id: str, device_id: str = None, count: int = 1) -> bool:
        """Send backspace key(s) to Claude (not applicable in SDK mode)"""
        logger.info(f"Backspace key requested from client {client_id} - not applicable in SDK mode")
        return True
    
    def send_key_sequence(self, key_sequence: str, client_id: str) -> bool:
        """Send a raw key sequence to Claude (not applicable in SDK mode)"""
        logger.info(f"Key sequence requested from client {client_id} - not applicable in SDK mode")
        return True
    
    def resize_pty(self, rows: int, cols: int):
        """Resize the pseudoterminal window (not applicable in SDK mode)"""
        logger.info(f"PTY resize requested - not applicable in SDK mode")
        pass

# Claude-specific configuration
CLAUDE_DB_PATH = Path("agents/claude_sessions.db")

def create_claude_manager(socketio_instance):
    """Create a Claude-specific SDK manager"""
    return ClaudeSDKManager(CLAUDE_DB_PATH, socketio_instance)

# For backward compatibility, you can still import these classes directly
__all__ = ['ClaudeSDKManager', 'DatabaseManager', 'Message', 'Session', 'create_claude_manager']