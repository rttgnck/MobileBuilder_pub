import sqlite3
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Message:
    """Message data structure"""
    id: str
    session_id: str
    type: str  # 'user', 'agent', 'system'
    content: str
    timestamp: str
    device_id: Optional[str] = None
    metadata: Optional[str] = None  # JSON string for additional metadata

@dataclass
class Session:
    """Session data structure"""
    id: str
    name: str
    start_time: str
    end_time: Optional[str]
    working_directory: str
    message_count: int
    status: str  # 'active', 'completed', 'terminated'
    total_active_time: float = 0.0
    last_activity: Optional[str] = None
    agent_api_session_id: Optional[str] = None  # Agent's internal session ID for resumption



class DatabaseManager:
    """Manages database operations for sessions and messages"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """Initialize database with required tables"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Sessions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    working_directory TEXT NOT NULL,
                    message_count INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    total_active_time REAL DEFAULT 0.0,
                    last_activity TEXT,
                    metadata TEXT,
                    agent_api_session_id TEXT
                )
            ''')
            
            # Messages table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    device_id TEXT,
                    metadata TEXT,
                    FOREIGN KEY (session_id) REFERENCES sessions (id)
                )
            ''')
            
            # Session tags table for searching
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS session_tags (
                    session_id TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions (id),
                    PRIMARY KEY (session_id, tag)
                )
            ''')
            
            # Add metadata column to messages table if it doesn't exist (migration)
            try:
                cursor.execute('ALTER TABLE messages ADD COLUMN metadata TEXT')
                logger.info("Added metadata column to messages table")
            except sqlite3.OperationalError:
                # Column already exists, ignore
                pass
            
            # Add agent_api_session_id column to sessions table if it doesn't exist (migration)
            try:
                cursor.execute('ALTER TABLE sessions ADD COLUMN agent_api_session_id TEXT')
                logger.info("Added agent_api_session_id column to sessions table")
            except sqlite3.OperationalError:
                # Column already exists, ignore
                pass
            
            # ADD INDEXES for performance
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages (session_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions (status)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_start_time ON sessions (start_time)')
            
            conn.commit()
    
    def create_session(self, session: Session) -> bool:
        """Create a new session"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO sessions (id, name, start_time, end_time, 
                                         working_directory, message_count, status,
                                         total_active_time, last_activity, agent_api_session_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (session.id, session.name, session.start_time, session.end_time,
                      session.working_directory, session.message_count, session.status,
                      session.total_active_time, session.last_activity, session.agent_api_session_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error creating session: {e}")
            return False
    
    def update_session(self, session_id: str, **kwargs) -> bool:
        """Update session attributes"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                updates = []
                values = []
                for key, value in kwargs.items():
                    updates.append(f"{key} = ?")
                    values.append(value)
                values.append(session_id)
                
                query = f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?"
                cursor.execute(query, values)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error updating session: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, name, start_time, end_time, working_directory,
                           message_count, status, total_active_time, last_activity, agent_api_session_id
                    FROM sessions WHERE id = ?
                ''', (session_id,))
                row = cursor.fetchone()
                if row:
                    return Session(*row)
        except Exception as e:
            logger.error(f"Error getting session: {e}")
        return None
    
    def get_active_session(self) -> Optional[Session]:
        """Get currently active session"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, name, start_time, end_time, working_directory,
                           message_count, status, total_active_time, last_activity, agent_api_session_id
                    FROM sessions WHERE status = 'active'
                    ORDER BY start_time DESC LIMIT 1
                ''')
                row = cursor.fetchone()
                if row:
                    return Session(*row)
        except Exception as e:
            logger.error(f"Error getting active session: {e}")
        return None
    
    def list_sessions(self, limit: int = 50, offset: int = 0) -> List[Session]:
        """List sessions with pagination"""
        sessions = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, name, start_time, end_time, working_directory,
                           message_count, status, total_active_time, last_activity, agent_api_session_id
                    FROM sessions 
                    ORDER BY start_time DESC
                    LIMIT ? OFFSET ?
                ''', (limit, offset))
                for row in cursor.fetchall():
                    sessions.append(Session(*row))
        except Exception as e:
            logger.error(f"Error listing sessions: {e}")
        return sessions
    
    def save_message(self, message: Message) -> bool:
        """Save a message to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO messages (id, session_id, type, content, timestamp, device_id, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (message.id, message.session_id, message.type, message.content,
                      message.timestamp, message.device_id, message.metadata))
                
                # Update message count
                cursor.execute('''
                    UPDATE sessions 
                    SET message_count = message_count + 1,
                        last_activity = ?
                    WHERE id = ?
                ''', (message.timestamp, message.session_id))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return False
    
    def get_session_messages(self, session_id: str, limit: int = 1000) -> List[Message]:
        """Get messages for a session"""
        messages = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, session_id, type, content, timestamp, device_id, metadata
                    FROM messages 
                    WHERE session_id = ?
                    ORDER BY timestamp ASC
                    LIMIT ?
                ''', (session_id, limit))
                for row in cursor.fetchall():
                    messages.append(Message(*row))
        except Exception as e:
            logger.error(f"Error getting messages: {e}")
        return messages
    
    def has_session_messages(self, session_id: str) -> bool:
        """Check if a session has any messages"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM messages WHERE session_id = ?
                ''', (session_id,))
                count = cursor.fetchone()[0]
                return count > 0
        except Exception as e:
            logger.error(f"Error checking session messages: {e}")
            return False
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session and all its messages"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Delete messages first (foreign key constraint)
                cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
                
                # Delete session tags
                cursor.execute('DELETE FROM session_tags WHERE session_id = ?', (session_id,))
                
                # Delete session
                cursor.execute('DELETE FROM sessions WHERE id = ?', (session_id,))
                
                conn.commit()
                logger.info(f"Deleted session {session_id} and all associated data")
                return True
        except Exception as e:
            logger.error(f"Error deleting session: {e}")
            return False