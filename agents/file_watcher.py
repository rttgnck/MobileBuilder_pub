#!/usr/bin/env python3
"""
File Watcher System for MobileBuilder
Tracks file changes in working directories and provides diff functionality
"""

import os
import time
import threading
import hashlib
import json
import difflib
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

logger = logging.getLogger(__name__)

@dataclass
class FileSnapshot:
    """Represents a snapshot of a file at a point in time"""
    path: str
    content: str
    hash: str
    timestamp: datetime
    size: int
    
    def to_dict(self):
        return {
            'path': self.path,
            'content': self.content,
            'hash': self.hash,
            'timestamp': self.timestamp.isoformat(),
            'size': self.size
        }

@dataclass
class FileDiff:
    """Represents a diff between two file versions"""
    file_path: str
    old_snapshot: Optional[FileSnapshot]
    new_snapshot: FileSnapshot
    diff_lines: List[str]
    change_type: str  # 'modified', 'created', 'deleted'
    timestamp: datetime
    status: str  # 'pending', 'accepted', 'denied'
    diff_id: str
    
    def to_dict(self):
        return {
            'file_path': self.file_path,
            'old_snapshot': self.old_snapshot.to_dict() if self.old_snapshot else None,
            'new_snapshot': self.new_snapshot.to_dict(),
            'diff_lines': self.diff_lines,
            'change_type': self.change_type,
            'timestamp': self.timestamp.isoformat(),
            'status': self.status,
            'diff_id': self.diff_id
        }

class FileChangeHandler(FileSystemEventHandler):
    """Handles file system events and tracks changes"""
    
    def __init__(self, file_tracker):
        self.file_tracker = file_tracker
        self.ignored_extensions = {'.pyc', '.pyo', '.pyd', '__pycache__', '.git', 
                                 '.DS_Store', '.tmp', '.swp', '.swo', '~'}
        self.ignored_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', 
                           '.vscode', '.idea', '.venv', 'venv'}
    
    def should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored"""
        # Check file extension
        if any(file_path.endswith(ext) for ext in self.ignored_extensions):
            return True
        
        # Check directory names
        path_parts = file_path.split(os.sep)
        if any(part in self.ignored_dirs for part in path_parts):
            return True
        
        # Check if it's a hidden file
        filename = os.path.basename(file_path)
        if filename.startswith('.') and filename not in {'.env', '.gitignore', '.gitkeep'}:
            return True
        
        return False
    
    def on_modified(self, event):
        if not event.is_directory and not self.should_ignore_file(event.src_path):
            self.file_tracker.handle_file_change(event.src_path, 'modified')
    
    def on_created(self, event):
        if not event.is_directory and not self.should_ignore_file(event.src_path):
            self.file_tracker.handle_file_change(event.src_path, 'created')
    
    def on_deleted(self, event):
        if not event.is_directory and not self.should_ignore_file(event.src_path):
            self.file_tracker.handle_file_change(event.src_path, 'deleted')
    
    def on_moved(self, event):
        if not event.is_directory:
            if not self.should_ignore_file(event.dest_path):
                self.file_tracker.handle_file_change(event.dest_path, 'created')
            if not self.should_ignore_file(event.src_path):
                self.file_tracker.handle_file_change(event.src_path, 'deleted')

class FileTracker:
    """Main file tracking system"""
    
    def __init__(self, socketio=None):
        self.socketio = socketio
        self.observers: Dict[str, Observer] = {}  # session_id -> Observer
        self.file_snapshots: Dict[str, Dict[str, FileSnapshot]] = {}  # session_id -> {file_path: snapshot}
        self.file_diffs: Dict[str, List[FileDiff]] = {}  # session_id -> [diffs]
        self.watching_directories: Dict[str, str] = {}  # session_id -> directory_path
        self.lock = threading.Lock()
        
        # Create diffs directory for storage
        self.diffs_dir = os.path.join(os.getcwd(), 'file_diffs')
        os.makedirs(self.diffs_dir, exist_ok=True)
    
    def start_watching(self, session_id: str, directory_path: str) -> bool:
        """Start watching a directory for file changes"""
        try:
            with self.lock:
                # Stop existing watcher if any
                self.stop_watching(session_id)
                
                # Expand user directory
                directory_path = os.path.expanduser(directory_path)
                
                if not os.path.exists(directory_path):
                    logger.error(f"Directory does not exist: {directory_path}")
                    return False
                
                # Create initial snapshots
                self.file_snapshots[session_id] = {}
                self.file_diffs[session_id] = []
                self.watching_directories[session_id] = directory_path
                
                # Create initial snapshots of existing files
                self._create_initial_snapshots(session_id, directory_path)
                
                # Set up file watcher
                event_handler = FileChangeHandler(self)
                event_handler.session_id = session_id  # Add session context
                
                observer = Observer()
                observer.schedule(event_handler, directory_path, recursive=True)
                observer.start()
                
                self.observers[session_id] = observer
                
                logger.info(f"Started watching directory: {directory_path} for session: {session_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error starting file watcher: {e}")
            return False
    
    def stop_watching(self, session_id: str):
        """Stop watching files for a session"""
        try:
            with self.lock:
                if session_id in self.observers:
                    self.observers[session_id].stop()
                    self.observers[session_id].join()
                    del self.observers[session_id]
                
                # Keep snapshots and diffs for potential future use
                # but remove from watching directories
                if session_id in self.watching_directories:
                    del self.watching_directories[session_id]
                
                logger.info(f"Stopped watching files for session: {session_id}")
                
        except Exception as e:
            logger.error(f"Error stopping file watcher: {e}")
    
    def _create_initial_snapshots(self, session_id: str, directory_path: str):
        """Create initial snapshots of all files in directory"""
        try:
            for root, dirs, files in os.walk(directory_path):
                # Filter out ignored directories
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', '.pytest_cache', 
                                                      'node_modules', '.vscode', '.idea', '.venv', 'venv'}]
                
                for file in files:
                    file_path = os.path.join(root, file)
                    
                    # Skip ignored files
                    if self._should_ignore_file(file_path):
                        continue
                    
                    try:
                        snapshot = self._create_file_snapshot(file_path)
                        if snapshot:
                            self.file_snapshots[session_id][file_path] = snapshot
                    except Exception as e:
                        logger.warning(f"Could not create snapshot for {file_path}: {e}")
                        
        except Exception as e:
            logger.error(f"Error creating initial snapshots: {e}")
    
    def _should_ignore_file(self, file_path: str) -> bool:
        """Check if file should be ignored (same logic as handler)"""
        ignored_extensions = {'.pyc', '.pyo', '.pyd', '__pycache__', '.git', 
                            '.DS_Store', '.tmp', '.swp', '.swo', '~'}
        ignored_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', 
                       '.vscode', '.idea', '.venv', 'venv'}
        
        # Check file extension
        if any(file_path.endswith(ext) for ext in ignored_extensions):
            return True
        
        # Check directory names
        path_parts = file_path.split(os.sep)
        if any(part in ignored_dirs for part in path_parts):
            return True
        
        # Check if it's a hidden file (except specific ones)
        filename = os.path.basename(file_path)
        if filename.startswith('.') and filename not in {'.env', '.gitignore', '.gitkeep'}:
            return True
        
        return False
    
    def _create_file_snapshot(self, file_path: str) -> Optional[FileSnapshot]:
        """Create a snapshot of a file"""
        try:
            if not os.path.exists(file_path) or not os.path.isfile(file_path):
                return None
            
            # Check file size (limit to 1MB)
            file_size = os.path.getsize(file_path)
            if file_size > 1024 * 1024:  # 1MB limit
                logger.warning(f"File too large to track: {file_path} ({file_size} bytes)")
                return None
            
            # Read file content
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except UnicodeDecodeError:
                # Try with different encoding
                try:
                    with open(file_path, 'r', encoding='latin-1') as f:
                        content = f.read()
                except Exception:
                    logger.warning(f"Cannot read file (unsupported encoding): {file_path}")
                    return None
            
            # Create hash
            content_hash = hashlib.sha256(content.encode('utf-8')).hexdigest()
            
            return FileSnapshot(
                path=file_path,
                content=content,
                hash=content_hash,
                timestamp=datetime.now(),
                size=file_size
            )
            
        except Exception as e:
            logger.error(f"Error creating file snapshot for {file_path}: {e}")
            return None
    
    def handle_file_change(self, file_path: str, change_type: str):
        """Handle a file change event"""
        try:
            # Find which session this file belongs to
            session_id = None
            for sid, watch_dir in self.watching_directories.items():
                if file_path.startswith(watch_dir):
                    session_id = sid
                    break
            
            if not session_id:
                return
            
            # Small delay to ensure file write is complete
            time.sleep(0.1)
            
            with self.lock:
                old_snapshot = self.file_snapshots[session_id].get(file_path)
                new_snapshot = None
                
                if change_type in ['modified', 'created']:
                    new_snapshot = self._create_file_snapshot(file_path)
                    if not new_snapshot:
                        return
                
                # Check if content actually changed
                if change_type == 'modified' and old_snapshot and new_snapshot:
                    if old_snapshot.hash == new_snapshot.hash:
                        return  # No actual content change
                
                # Create diff
                diff = self._create_diff(file_path, old_snapshot, new_snapshot, change_type, session_id)
                if diff:
                    self.file_diffs[session_id].append(diff)
                    
                    # Update snapshot
                    if new_snapshot:
                        self.file_snapshots[session_id][file_path] = new_snapshot
                    elif change_type == 'deleted' and file_path in self.file_snapshots[session_id]:
                        del self.file_snapshots[session_id][file_path]
                    
                    # Save diff to disk
                    self._save_diff_to_disk(session_id, diff)
                    
                    # Notify via SocketIO
                    if self.socketio:
                        self.socketio.emit('file_change', {
                            'type': 'diff_created',
                            'diff': diff.to_dict(),
                            'session_id': session_id
                        }, room=session_id)
                    
                    logger.info(f"File change detected: {file_path} ({change_type}) in session {session_id}")
                
        except Exception as e:
            logger.error(f"Error handling file change: {e}")
    
    def _create_diff(self, file_path: str, old_snapshot: Optional[FileSnapshot], 
                    new_snapshot: Optional[FileSnapshot], change_type: str, session_id: str) -> Optional[FileDiff]:
        """Create a diff object"""
        try:
            diff_lines = []
            
            if change_type == 'created':
                if new_snapshot:
                    diff_lines = [f"+ {line}" for line in new_snapshot.content.splitlines()]
            elif change_type == 'deleted':
                if old_snapshot:
                    diff_lines = [f"- {line}" for line in old_snapshot.content.splitlines()]
            elif change_type == 'modified':
                if old_snapshot and new_snapshot:
                    old_lines = old_snapshot.content.splitlines(keepends=True)
                    new_lines = new_snapshot.content.splitlines(keepends=True)
                    diff_lines = list(difflib.unified_diff(
                        old_lines, new_lines,
                        fromfile=f"a/{os.path.basename(file_path)}",
                        tofile=f"b/{os.path.basename(file_path)}",
                        lineterm=''
                    ))
            
            if not diff_lines and change_type != 'deleted':
                return None
            
            # Generate unique diff ID
            diff_id = hashlib.md5(f"{session_id}_{file_path}_{datetime.now().isoformat()}".encode()).hexdigest()
            
            return FileDiff(
                file_path=file_path,
                old_snapshot=old_snapshot,
                new_snapshot=new_snapshot or old_snapshot,  # For deleted files, use old snapshot
                diff_lines=diff_lines,
                change_type=change_type,
                timestamp=datetime.now(),
                status='pending',
                diff_id=diff_id
            )
            
        except Exception as e:
            logger.error(f"Error creating diff: {e}")
            return None
    
    def _save_diff_to_disk(self, session_id: str, diff: FileDiff):
        """Save diff to disk for persistence"""
        try:
            session_diff_dir = os.path.join(self.diffs_dir, session_id)
            os.makedirs(session_diff_dir, exist_ok=True)
            
            diff_file = os.path.join(session_diff_dir, f"{diff.diff_id}.json")
            with open(diff_file, 'w', encoding='utf-8') as f:
                json.dump(diff.to_dict(), f, indent=2)
                
        except Exception as e:
            logger.error(f"Error saving diff to disk: {e}")
    
    def get_session_diffs(self, session_id: str) -> List[Dict]:
        """Get all diffs for a session"""
        with self.lock:
            if session_id in self.file_diffs:
                return [diff.to_dict() for diff in self.file_diffs[session_id]]
            return []
    
    def get_pending_diffs(self, session_id: str) -> List[Dict]:
        """Get pending diffs for a session"""
        with self.lock:
            if session_id in self.file_diffs:
                return [diff.to_dict() for diff in self.file_diffs[session_id] 
                       if diff.status == 'pending']
            return []
    
    def accept_diff(self, session_id: str, diff_id: str) -> bool:
        """Accept a diff (mark as accepted)"""
        try:
            with self.lock:
                if session_id not in self.file_diffs:
                    return False
                
                for diff in self.file_diffs[session_id]:
                    if diff.diff_id == diff_id:
                        diff.status = 'accepted'
                        self._save_diff_to_disk(session_id, diff)
                        
                        # Notify via SocketIO
                        if self.socketio:
                            self.socketio.emit('file_change', {
                                'type': 'diff_accepted',
                                'diff_id': diff_id,
                                'session_id': session_id
                            }, room=session_id)
                        
                        return True
                return False
                
        except Exception as e:
            logger.error(f"Error accepting diff: {e}")
            return False
    
    def deny_diff(self, session_id: str, diff_id: str) -> bool:
        """Deny a diff and restore old version"""
        try:
            with self.lock:
                if session_id not in self.file_diffs:
                    return False
                
                for diff in self.file_diffs[session_id]:
                    if diff.diff_id == diff_id:
                        diff.status = 'denied'
                        
                        # Restore old version if it exists
                        if diff.old_snapshot and os.path.exists(diff.file_path):
                            try:
                                with open(diff.file_path, 'w', encoding='utf-8') as f:
                                    f.write(diff.old_snapshot.content)
                                
                                # Update snapshot to old version
                                self.file_snapshots[session_id][diff.file_path] = diff.old_snapshot
                                
                            except Exception as e:
                                logger.error(f"Error restoring file {diff.file_path}: {e}")
                                return False
                        
                        self._save_diff_to_disk(session_id, diff)
                        
                        # Notify via SocketIO
                        if self.socketio:
                            self.socketio.emit('file_change', {
                                'type': 'diff_denied',
                                'diff_id': diff_id,
                                'file_path': diff.file_path,
                                'session_id': session_id
                            }, room=session_id)
                        
                        return True
                return False
                
        except Exception as e:
            logger.error(f"Error denying diff: {e}")
            return False
    
    def accept_all_diffs(self, session_id: str) -> int:
        """Accept all pending diffs for a session"""
        try:
            count = 0
            with self.lock:
                if session_id not in self.file_diffs:
                    return 0
                
                for diff in self.file_diffs[session_id]:
                    if diff.status == 'pending':
                        diff.status = 'accepted'
                        self._save_diff_to_disk(session_id, diff)
                        count += 1
                
                # Notify via SocketIO
                if self.socketio and count > 0:
                    self.socketio.emit('file_change', {
                        'type': 'all_diffs_accepted',
                        'count': count,
                        'session_id': session_id
                    }, room=session_id)
                
                return count
                
        except Exception as e:
            logger.error(f"Error accepting all diffs: {e}")
            return 0
    
    def get_file_current_content(self, session_id: str, file_path: str) -> Optional[str]:
        """Get current content of a file"""
        try:
            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
        return None
    
    def cleanup_session(self, session_id: str):
        """Clean up all data for a session"""
        try:
            self.stop_watching(session_id)
            
            with self.lock:
                # Remove from memory
                if session_id in self.file_snapshots:
                    del self.file_snapshots[session_id]
                if session_id in self.file_diffs:
                    del self.file_diffs[session_id]
                
                # Optionally remove diff files from disk
                # (commented out to preserve history)
                # session_diff_dir = os.path.join(self.diffs_dir, session_id)
                # if os.path.exists(session_diff_dir):
                #     import shutil
                #     shutil.rmtree(session_diff_dir)
                
            logger.info(f"Cleaned up file tracker for session: {session_id}")
            
        except Exception as e:
            logger.error(f"Error cleaning up session: {e}")

# Global file tracker instance
file_tracker = None

def get_file_tracker(socketio=None):
    """Get or create the global file tracker instance"""
    global file_tracker
    if file_tracker is None:
        file_tracker = FileTracker(socketio)
    elif socketio and not file_tracker.socketio:
        file_tracker.socketio = socketio
    return file_tracker
