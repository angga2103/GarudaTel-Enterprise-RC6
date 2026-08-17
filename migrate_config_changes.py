"""
Migration: Add config_changes table for configuration audit trail
"""

import sqlite3
import os

def get_db_path():
    """Get database path based on environment."""
    if os.name == 'nt':  # Windows
        return os.path.join(os.path.dirname(__file__), "paypoint.db")
    else:  # Linux
        return "/root/web_ppob/paypoint/paypoint.db"

def migrate():
    """Create config_changes table."""
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        print("Migration will be applied when database is available.")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # Create config_changes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                admin_user TEXT NOT NULL,
                integration TEXT NOT NULL,
                action TEXT NOT NULL
            )
        """)

        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config_changes_integration
            ON config_changes(integration)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_config_changes_timestamp
            ON config_changes(timestamp DESC)
        """)

        conn.commit()
        print("OK Migration successful: config_changes table created")

    except Exception as e:
        conn.rollback()
        print(f"ERROR Migration failed: {e}")
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    migrate()
