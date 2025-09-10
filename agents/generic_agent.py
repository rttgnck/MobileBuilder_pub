#!/usr/bin/env python3
"""
Generic Agent Module - Core functionality for command-line agent interactions
This module provides reusable functionality for managing agent sessions, database operations,
and WebSocket communication that can be used by any agent wrapper.
"""

import subprocess
import threading
import queue
import os
import select
import fcntl
import time
import json
import uuid
import sqlite3
import termios
import struct
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import pty
import signal
import logging
from .db_manager import DatabaseManager, Message, Session


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
DEFAULT_WORKING_DIR = os.getenv("DEFAULT_WORKING_DIR")
SESSION_MAX_DURATION = 5 * 60 * 60  # 5 hours in seconds
WARNING_INTERVALS = [3600, 1800, 900, 600, 300, 60]  # 1hr, 30min, 15min, 10min, 5min, 1min


class GenericAgentManager:
    """Generic manager for command-line agent sessions with multi-device support"""
    
    def __init__(self, agent_command: str, db_path: Path, socketio_instance: SocketIO, exit_command: str = "/exit"):
        self.agent_command = agent_command
        self.exit_command = exit_command  # Agent-specific exit command
        self.active_session = None
        self.process = None
        self.master_fd = None
        self.is_running = False
        self.connected_clients = set()
        self.message_buffer = []
        self.command_queue = queue.Queue()
        self.session_start_time = None
        self.active_time_start = None
        self.total_active_time = 0
        self.warning_timers = {}
        self.db = DatabaseManager(db_path)
        self.current_session_id = None
        self.working_directory = DEFAULT_WORKING_DIR
        self.lock = threading.Lock()
        self.socketio = socketio_instance
    
    def start_session(self, working_dir: str = None, session_name: str = None) -> Dict[str, Any]:
        """Start a new agent session"""
        with self.lock:
            if self.is_running:
                logger.info(f"Session already running for {self.agent_command}")
                return {
                    'success': False,
                    'error': 'Session already running',
                    'session_id': self.current_session_id
                }
            
            try:
                # Set working directory
                self.working_directory = working_dir or DEFAULT_WORKING_DIR
                logger.info(f"Starting {self.agent_command} session in directory: {self.working_directory}")
                
                # Validate directory exists
                if not os.path.exists(self.working_directory):
                    logger.error(f"Directory does not exist: {self.working_directory}")
                    return {
                        'success': False,
                        'error': f'Directory does not exist: {self.working_directory}'
                    }
                
                # Create session record
                self.current_session_id = str(uuid.uuid4())
                session_name = session_name or f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                
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
                
                # Start agent process
                logger.info(f"Starting {self.agent_command} process...")
                self.master_fd, slave_fd = pty.openpty()
                
                # Change to working directory and start agent
                cmd = f'cd "{self.working_directory}" && {self.agent_command}'
                logger.info(f"Executing command: {cmd}")
                
                self.process = subprocess.Popen(
                    ['bash', '-c', cmd],
                    stdin=slave_fd,
                    stdout=slave_fd,
                    stderr=slave_fd,
                    preexec_fn=os.setsid,
                    env={**os.environ, 'TERM': 'xterm-256color'}
                )
                
                os.close(slave_fd)
                
                # Wait a moment for the process to fully start up
                time.sleep(0.5)
                
                # Make non-blocking for reading, but keep blocking for writing
                # This ensures commands are sent immediately without buffering
                flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
                fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                
                # Set PTY to raw mode for better command handling
                import termios
                try:
                    attrs = termios.tcgetattr(self.master_fd)
                    attrs[3] &= ~termios.ECHO  # Disable echo
                    attrs[3] &= ~termios.ICANON  # Disable canonical mode
                    termios.tcsetattr(self.master_fd, termios.TCSANOW, attrs)
                except Exception as e:
                    logger.warning(f"Could not set PTY attributes: {e}")
                
                self.is_running = True
                self.session_start_time = datetime.now()
                self.total_active_time = 0
                
                logger.info(f"Process started with PID: {self.process.pid}")
                
                # Start output reader thread
                logger.info("Starting output reader thread...")
                threading.Thread(target=self._read_output, daemon=True).start()
                
                # Start command processor thread
                logger.info("Starting command processor thread...")
                threading.Thread(target=self._process_commands, daemon=True).start()
                
                # Start session timer
                logger.info("Starting session timer...")
                self._start_session_timer()
                
                # Wait for agent to be fully ready
                logger.info("Waiting for agent to be ready...")
                time.sleep(1)
                # ready_attempts = 0
                # max_ready_attempts = 10
                # while ready_attempts < max_ready_attempts:
                #     if self.test_agent_connection():
                #         logger.info("Agent is ready to receive commands")
                #         break
                #     time.sleep(0.5)
                #     ready_attempts += 1
                
                # if ready_attempts >= max_ready_attempts:
                #     logger.warning("Agent may not be fully ready, but proceeding with session")
                
                logger.info(f"Started {self.agent_command} session: {self.current_session_id}")
                
                return {
                    'success': True,
                    'session_id': self.current_session_id,
                    'session_name': session_name,
                    'working_directory': self.working_directory
                }
                
            except Exception as e:
                logger.error(f"Error starting {self.agent_command} session: {e}")
                return {
                    'success': False,
                    'error': str(e)
                }
    
    def connect_client(self, client_id: str, device_id: str = None) -> Dict[str, Any]:
        """Connect a client to the active session"""
        with self.lock:
            logger.info(f"Client {client_id} attempting to connect to {self.agent_command} session")
            
            if not self.is_running:
                logger.warning(f"Client {client_id} connection failed: No active session")
                return {
                    'success': False,
                    'error': 'No active session'
                }
            
            self.connected_clients.add(client_id)
            logger.info(f"Client {client_id} connected to {self.agent_command} session")
            
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
        """Queue a command to be sent to the agent process"""
        if not self.is_running:
            logger.warning(f"Command '{command}' from client {client_id} failed: Session not running")
            return False
        
        try:
            self.command_queue.put((command, client_id, device_id), timeout=1.0)
            logger.info(f"Command queued successfully: {command.strip()}")
            return True
        except queue.Full:
            logger.error(f"Command queue is full, cannot queue command: {command}")
            return False
        except Exception as e:
            logger.error(f"Error queueing command '{command}' from client {client_id}: {e}")
            return False
    
    def end_session(self, graceful: bool = True) -> bool:
        """End the current agent session"""
        with self.lock:
            if not self.is_running:
                return False
            
            try:
                # Preserve session id for notification after cleanup
                old_session_id = self.current_session_id
                # Send exit command if graceful
                if graceful and self.master_fd:
                    try:
                        exit_cmd = self.exit_command + '\n'
                        logger.info(f"Sending graceful exit command: {self.exit_command}")
                        os.write(self.master_fd, exit_cmd.encode('utf-8'))
                        time.sleep(0.5)
                    except Exception as e:
                        logger.warning(f"Failed to send exit command: {e}")
                
                # Stop warning timers
                for timer in self.warning_timers.values():
                    timer.cancel()
                self.warning_timers.clear()
                
                # Update active time
                if self.active_time_start:
                    self.total_active_time += time.time() - self.active_time_start
                    self.active_time_start = None
                
                # Terminate process
                if self.process:
                    try:
                        self.process.terminate()
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                    except:
                        pass
                
                # Close file descriptor
                if self.master_fd:
                    try:
                        os.close(self.master_fd)
                    except:
                        pass
                
                # Check if session has messages before deciding what to do
                session_has_messages = False
                if self.current_session_id:
                    session_has_messages = self.db.has_session_messages(self.current_session_id)
                    
                    if session_has_messages:
                        # Update session in database if it has messages
                        self.db.update_session(
                            self.current_session_id,
                            end_time=datetime.now().isoformat(),
                            status='completed' if graceful else 'terminated',
                            total_active_time=self.total_active_time
                        )
                        logger.info(f"Session {self.current_session_id} updated with {self.db.get_session_messages(self.current_session_id)} messages")
                    else:
                        # Delete empty session from database
                        if self.db.delete_session(self.current_session_id):
                            logger.info(f"Deleted empty session {self.current_session_id} from database")
                        else:
                            logger.warning(f"Failed to delete empty session {self.current_session_id}")
                
                # Clear command queue
                while not self.command_queue.empty():
                    try:
                        self.command_queue.get_nowait()
                        self.command_queue.task_done()
                    except queue.Empty:
                        break
                
                # Emit appropriate event based on whether session was saved or deleted
                if old_session_id:
                    try:
                        if session_has_messages:
                            # Session was saved, emit normal session_closed
                            self.socketio.emit('session_closed', {
                                'message': 'session closed',
                                'agent_type': self.agent_command,
                            }, room=old_session_id)
                        else:
                            # Session was empty and deleted, emit special message
                            self.socketio.emit('session_closed', {
                                'message': 'session closed (empty session not saved)',
                                'agent_type': self.agent_command,
                                'empty_session': True
                            }, room=old_session_id)
                    except Exception as e:
                        logger.warning(f"Failed to emit session_closed: {e}")

                # Reset state
                self.is_running = False
                self.process = None
                self.master_fd = None
                self.session_start_time = None
                self.current_session_id = None
                
                logger.info(f"{self.agent_command} session ended")
                return True
                
            except Exception as e:
                logger.error(f"Error ending session: {e}")
                return False
    
    def _read_output(self):
        """Read output from agent process with intelligent buffering"""
        buffer = b""
        output_accumulator = ""
        last_output_time = None
        consecutive_errors = 0
        max_consecutive_errors = 10
        
        while self.is_running:
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.01)
                if ready:
                    try:
                        chunk = os.read(self.master_fd, 4096)
                        if chunk:
                            buffer += chunk
                            
                            # Try to decode
                            try:
                                text = buffer.decode('utf-8', errors='ignore')
                                buffer = b""
                                output_accumulator += text
                                last_output_time = time.time()
                                consecutive_errors = 0  # Reset error counter on successful read
                                
                                # Update active time tracking
                                if self.active_time_start is None:
                                    self.active_time_start = time.time()
                                
                            except UnicodeDecodeError:
                                continue
                    except OSError as e:
                        # Don't break immediately on OSError during startup
                        if self.is_running:
                            consecutive_errors += 1
                            if consecutive_errors > max_consecutive_errors:
                                logger.error(f"Too many consecutive OSErrors in output reading: {e}")
                                break
                            time.sleep(0.1)  # Brief pause before retrying
                            continue
                        else:
                            break
                else:
                    # Check if we should flush accumulated output
                    if output_accumulator and last_output_time:
                        time_since_last = time.time() - last_output_time
                        if time_since_last > 0.05:  # Reduced to 50ms for more responsive output
                            self._emit_output(output_accumulator)
                            output_accumulator = ""
                            last_output_time = None
                            
                            # Stop tracking active time
                            if self.active_time_start:
                                self.total_active_time += time.time() - self.active_time_start
                                self.active_time_start = None
                        
            except Exception as e:
                logger.error(f"Error reading output: {e}")
                consecutive_errors += 1
                if consecutive_errors > max_consecutive_errors:
                    logger.error(f"Too many consecutive errors in output reading, breaking")
                    break
                time.sleep(0.1)  # Brief pause before retrying
                continue
        
        # Flush any remaining output
        if output_accumulator:
            self._emit_output(output_accumulator)
        
        logger.info(f"Output reading thread ended for {self.agent_command} session")
    
    def _process_commands(self):
        """Process queued commands to ensure reliable execution"""
        while self.is_running:
            try:
                command_data = self.command_queue.get(timeout=0.1)
                command, client_id, device_id = command_data
                
                # Save the user message to the database here
                message = Message(
                    id=str(uuid.uuid4()),
                    session_id=self.current_session_id,
                    type='user',
                    content=command,
                    timestamp=datetime.now().isoformat(),
                    device_id=device_id
                )
                self.db.save_message(message)

                # Append newline for command execution and send
                command_to_write = command + '\n'
                if not self._write_to_pty(command_to_write):
                    logger.warning(f"Failed to process queued command: {command}")
                
                self.command_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in command processor: {e}")
                time.sleep(0.1)
        
        logger.info(f"Command processor thread ended for {self.agent_command} session")
    
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
                timestamp=datetime.now().isoformat()
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
            'message': f'Warning: {self.agent_command} session will reset in {time_str}'
        }, room=self.current_session_id)
    
    def _get_elapsed_time(self) -> float:
        """Get total elapsed active time"""
        if not self.session_start_time:
            return 0
        
        current_active = 0
        if self.active_time_start:
            current_active = time.time() - self.active_time_start
        
        return self.total_active_time + current_active
    
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
            'agent_ready': self.is_agent_ready()
        }
    
    def is_agent_ready(self) -> bool:
        """Check if the agent is ready to receive commands"""
        if not self.is_running or not self.process or not self.master_fd:
            return False
        
        # Check if process is still running
        if self.process.poll() is not None:
            return False
        
        return True
    
    def test_agent_connection(self) -> bool:
        """Test if the agent is responsive by sending a simple command"""
        if not self.is_agent_ready():
            return False
        
        try:
            # Send a simple command to test responsiveness
            test_cmd = "echo 'test'\n"
            os.write(self.master_fd, test_cmd.encode('utf-8'))
            
            # Wait a bit for response
            time.sleep(0.1)
            
            # Try to read any output
            try:
                ready, _, _ = select.select([self.master_fd], [], [], 0.01)
                if ready:
                    # There's output available, connection is working
                    return True
            except:
                pass
            
            return True  # Assume working if no errors
        except Exception as e:
            logger.debug(f"Agent connection test failed: {e}")
            return False
    
    def send_test_command(self, command: str = "echo 'test'") -> bool:
        """Send a test command to verify agent functionality"""
        if not self.is_agent_ready():
            return False
        
        try:
            # Send test command directly
            if not command.endswith('\n'):
                command += '\n'
            
            os.write(self.master_fd, command.encode('utf-8'))
            logger.info(f"Test command sent: {command.strip()}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send test command: {e}")
            return False
    
    def send_command_with_retry(self, command: str, client_id: str, device_id: str = None, max_retries: int = 3) -> bool:
        """Send command with retry logic for better reliability"""
        for attempt in range(max_retries):
            if self.send_command(command, client_id, device_id):
                return True
            
            if attempt < max_retries - 1:
                logger.warning(f"Command failed, retrying in 0.1s (attempt {attempt + 1}/{max_retries})")
                time.sleep(0.1)
        
        logger.error(f"Command failed after {max_retries} attempts")
        return False
    
    def force_flush_output(self):
        """Force flush any pending output from the agent"""
        if not self.is_running or not self.master_fd:
            return
        
        try:
            # Send a small control sequence to force output flush
            # This can help with buffered output
            os.write(self.master_fd, b'\r')
            time.sleep(0.01)
        except Exception as e:
            logger.debug(f"Force flush failed: {e}")
    
    def flush_command_queue(self):
        """Flush all pending commands in the queue"""
        flushed_count = 0
        while not self.command_queue.empty():
            try:
                self.command_queue.get_nowait()
                self.command_queue.task_done()
                flushed_count += 1
            except queue.Empty:
                break
        
        logger.info(f"Flushed {flushed_count} commands from queue")
        return flushed_count
    
    def _write_to_pty(self, data: str) -> bool:
        """Writes raw string data to the PTY master file descriptor"""
        if not self.is_agent_ready():
            logger.warning(f"Agent not ready for write")
            return False
        
        try:
            
            command = data.strip()
            command = command + '\r\n'
            
            data_bytes = command.encode('utf-8')
            logger.error(f"Data bytes: {data_bytes}")
            bytes_written = 0
            while bytes_written < len(data_bytes):
                written = os.write(self.master_fd, data_bytes[bytes_written:])
                if written == 0:
                    logger.error("Wrote 0 bytes to PTY, connection may be lost.")
                    return False
                bytes_written += written

            # Force immediate processing
            self.force_flush_output()

            # FIX: Change log level from error to debug
            logger.debug(f"Data bytes written: {bytes_written}/{len(data_bytes)}")
            return True
        except Exception as e:
            logger.error(f"Error writing to PTY: {e}")
            return False
    
    def send_enter_key(self, client_id: str, device_id: str = None) -> bool:
        """Send a simple enter key (\\r\\n) to the agent process"""
        if not self.is_agent_ready():
            logger.warning(f"Agent not ready for enter key from client {client_id}")
            return False
        
        try:
            logger.info(f"Client {client_id} sending enter key")
            
            # Track active time
            if not self.active_time_start:
                self.active_time_start = time.time()
            
            # Save user message for enter key
            message = Message(
                id=str(uuid.uuid4()),
                session_id=self.current_session_id,
                type='user',
                content='[Enter Key]',
                timestamp=datetime.now().isoformat(),
                device_id=device_id
            )
            self.db.save_message(message)
            
            # Send simple enter key (carriage return + line feed)
            enter_key = '\r'
            enter_key_bytes = enter_key.encode('utf-8')
            bytes_written = os.write(self.master_fd, enter_key_bytes)
            
            logger.debug(f"Enter key bytes written: {bytes_written}/{len(enter_key_bytes)}")
            
            # Force immediate processing
            self.force_flush_output()
            
            # Brief wait for potential output
            time.sleep(0.05)
            
            logger.info(f"Enter key sent successfully from client {client_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending enter key from client {client_id}: {e}")
            return False
    
    def send_backspace_key(self, client_id: str, device_id: str = None, count: int = 1) -> bool:
        """Send backspace key(s) to the agent process"""
        if not self.is_agent_ready():
            logger.warning(f"Agent not ready for backspace key from client {client_id}")
            return False
        
        try:
            logger.info(f"Client {client_id} sending {count} backspace key(s)")
            
            # Track active time
            if not self.active_time_start:
                self.active_time_start = time.time()
            
            # Save user message for backspace key
            message = Message(
                id=str(uuid.uuid4()),
                session_id=self.current_session_id,
                type='user',
                content=f'[Backspace Key x{count}]',
                timestamp=datetime.now().isoformat(),
                device_id=device_id
            )
            self.db.save_message(message)
            
            # CHANGE: Use the DEL character (\x7f) which is more common for backspace
            backspace_key = '\x7f' * count
            backspace_bytes = backspace_key.encode('utf-8')
            bytes_written = os.write(self.master_fd, backspace_bytes)
            
            logger.debug(f"Backspace key bytes written: {bytes_written}/{len(backspace_bytes)}")
            
            # Force immediate processing
            self.force_flush_output()
            
            # Brief wait for potential output
            time.sleep(0.05)
            
            logger.info(f"Backspace key(s) sent successfully from client {client_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending backspace key from client {client_id}: {e}")
            return False
    
    def send_key_sequence(self, key_sequence: str, client_id: str) -> bool:
        """Send a raw key sequence to the agent process (for special keys like arrows, tabs, etc.)"""
        if not self.is_agent_ready():
            logger.warning(f"Agent not ready for key sequence from client {client_id}")
            return False
        
        try:
            # Note: We don't save every keystroke to the DB to avoid clutter. 
            # Only full commands and explicit actions are saved.
            
            key_bytes = key_sequence.encode('utf-8')
            bytes_written = os.write(self.master_fd, key_bytes)
            
            logger.debug(f"Key sequence '{repr(key_sequence)}' sent, {bytes_written} bytes written.")
            return True
            
        except Exception as e:
            logger.error(f"Error sending key sequence from client {client_id}: {e}")
            return False
    
    def resize_pty(self, rows: int, cols: int):
        """Resize the pseudoterminal window"""
        if not self.master_fd:
            return
        
        try:
            # Pack rows and cols into a bytes struct for the ioctl call
            # The format 'HHHH' corresponds to 4 unsigned short integers
            # (rows, cols, xpixel, ypixel)
            winsize = struct.pack('HHHH', rows, cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            logger.info(f"Resized PTY to {rows} rows, {cols} cols.")
        except Exception as e:
            logger.error(f"Error resizing PTY: {e}")