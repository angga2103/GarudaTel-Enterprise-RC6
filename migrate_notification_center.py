"""
Database Migration: Notification Center Tables

Creates tables for Enterprise Notification Center:
- notification_broadcasts: Broadcast history
- notification_queue: Queue management
- notification_channels: Channel configuration
"""

import sqlite3
import os
from datetime import datetime

def migrate():
    """Run migration for Notification Center."""
    
    # Fix Windows console encoding
    import sys
    import io
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    # Determine database path
    db_path = os.path.join(os.path.dirname(__file__), 'paypoint.db')
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("=" * 60)
        print("NOTIFICATION CENTER MIGRATION")
        print("=" * 60)
        
        # Table 1: notification_broadcasts
        print("\n[1/3] Creating notification_broadcasts table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_broadcasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                image_url TEXT,
                target_type TEXT NOT NULL,
                channels TEXT NOT NULL,
                total_target INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                failed_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'pending',
                created_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                error_message TEXT,
                FOREIGN KEY (created_by) REFERENCES users(id)
            )
        """)
        print("   ✅ notification_broadcasts created")
        
        # Table 2: notification_queue
        print("\n[2/3] Creating notification_queue table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                broadcast_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                channel TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                retry_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP,
                error_message TEXT,
                FOREIGN KEY (broadcast_id) REFERENCES notification_broadcasts(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        print("   ✅ notification_queue created")
        
        # Table 3: notification_channels
        print("\n[3/3] Creating notification_channels table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_name TEXT UNIQUE NOT NULL,
                channel_type TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                configuration TEXT,
                last_status TEXT,
                last_check TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        print("   ✅ notification_channels created")
        
        # Insert default channels
        print("\n[4/4] Inserting default channels...")
        
        channels = [
            ('firebase', 'push', 1, '{}', 'active', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            ('whatsapp', 'messaging', 0, '{}', 'coming_soon', None),
            ('telegram', 'messaging', 0, '{}', 'coming_soon', None),
        ]
        
        for channel in channels:
            cursor.execute("""
                INSERT OR IGNORE INTO notification_channels 
                (channel_name, channel_type, is_active, configuration, last_status, last_check)
                VALUES (?, ?, ?, ?, ?, ?)
            """, channel)
        
        print("   ✅ Default channels inserted")
        
        # Create indexes for performance
        print("\n[5/5] Creating indexes...")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON notification_broadcasts(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_broadcasts_created_at ON notification_broadcasts(created_at)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_broadcast ON notification_queue(broadcast_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_status ON notification_queue(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queue_user ON notification_queue(user_id)")
        print("   ✅ Indexes created")
        
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ MIGRATION COMPLETED SUCCESSFULLY")
        print("=" * 60)
        
        # Verify tables
        print("\nVerifying tables...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'notification_%'")
        tables = cursor.fetchall()
        print(f"Created tables: {[t[0] for t in tables]}")
        
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        conn.close()


def rollback():
    """Rollback migration (drop tables)."""
    
    # Fix Windows console encoding
    import sys
    import io
    if sys.platform == 'win32':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    
    db_path = os.path.join(os.path.dirname(__file__), 'paypoint.db')
    
    if not os.path.exists(db_path):
        print(f"❌ Database not found: {db_path}")
        return False
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        print("=" * 60)
        print("ROLLING BACK NOTIFICATION CENTER MIGRATION")
        print("=" * 60)
        
        cursor.execute("DROP TABLE IF EXISTS notification_queue")
        print("✅ notification_queue dropped")
        
        cursor.execute("DROP TABLE IF EXISTS notification_broadcasts")
        print("✅ notification_broadcasts dropped")
        
        cursor.execute("DROP TABLE IF EXISTS notification_channels")
        print("✅ notification_channels dropped")
        
        conn.commit()
        
        print("\n" + "=" * 60)
        print("✅ ROLLBACK COMPLETED")
        print("=" * 60)
        
        return True
        
    except Exception as e:
        print(f"\n❌ Rollback failed: {e}")
        conn.rollback()
        return False
        
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "rollback":
        rollback()
    else:
        migrate()
