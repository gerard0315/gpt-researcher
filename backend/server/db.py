import sqlite3
import json
import os
import uuid
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join("outputs", "researches.db")


def init_db():
    """Initialize the researches database table."""
    os.makedirs("outputs", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS researches (
            id TEXT PRIMARY KEY,
            task TEXT,
            report_type TEXT,
            report_source TEXT,
            tone TEXT,
            report_content TEXT,
            file_paths_json TEXT,
            created_at TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_research(id: str, task: str, report_type: str, report_source: str, tone: str, report_content: str, file_paths: Dict):
    """Save a research record."""
    try:
        # Generate unique ID to prevent collisions
        unique_id = f"{id}_{uuid.uuid4().hex[:8]}"
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        created_at = datetime.now().isoformat()
        cursor.execute('''
            INSERT INTO researches (id, task, report_type, report_source, tone, report_content, file_paths_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (unique_id, task, report_type, report_source, tone, report_content, json.dumps(file_paths), created_at))
        conn.commit()
        conn.close()
        logger.info(f"Research saved to database: {unique_id}")
    except Exception as e:
        logger.error(f"Failed to save research to database: {e}")


def get_all_researches() -> List[Dict]:
    """Get all researches (summary)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT id, task, created_at FROM researches ORDER BY created_at DESC')
    rows = cursor.fetchall()
    researches = []
    for row in rows:
        researches.append({
            "id": row["id"],
            "task": row["task"],
            "created_at": row["created_at"]
        })
    conn.close()
    return researches

def get_research(id: str) -> Optional[Dict]:
    """Get full details of a specific research."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM researches WHERE id = ?', (id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row["id"],
            "task": row["task"],
            "report_type": row["report_type"],
            "report_source": row["report_source"],
            "tone": row["tone"],
            "report_content": row["report_content"],
            "file_paths": json.loads(row["file_paths_json"]) if row["file_paths_json"] else {},
            "created_at": row["created_at"]
        }
    return None

def delete_research(id: str):
    """Delete a research record."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM researches WHERE id = ?', (id,))
    conn.commit()
    conn.close()
