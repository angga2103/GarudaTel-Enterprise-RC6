#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SEC-005 Migration Script
=========================
Purpose: Flag existing users with default PIN '123456' to force PIN change.
Date: 2026-08-06
Safety: Does NOT change user PINs, only sets force_pin_change flag.
"""

import sqlite3
import sys
import os
from datetime import datetime

# Auto-detect database path
if os.name == 'nt':  # Windows
    DB_PATH = os.path.join(os.path.dirname(__file__), "paypoint.db")
else:  # Linux
    DB_PATH = "/root/web_ppob/paypoint/paypoint.db"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        print(f"[{timestamp}] {msg}")
    except UnicodeEncodeError:
        # Fallback for Windows console encoding issues
        print(f"[{timestamp}] {msg}".encode('utf-8', errors='replace').decode('utf-8', errors='replace'))

def main():
    log("=" * 60)
    log("SEC-005 MIGRATION: Default PIN Remediation")
    log("=" * 60)
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # 1. Check if force_pin_change column exists
        log("Step 1: Checking database schema...")
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'force_pin_change' not in columns:
            log("ERROR: Column 'force_pin_change' does not exist. Please run: ALTER TABLE users ADD COLUMN force_pin_change INTEGER DEFAULT 0;")
            sys.exit(1)
        
        log("[OK] Schema OK: force_pin_change column exists")
        
        # 2. Count users with default PIN
        log("\nStep 2: Analyzing users with default PIN '123456'...")
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE pin = '123456'")
        default_pin_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) as total FROM users")
        total_users = cursor.fetchone()[0]
        
        log(f"Found {default_pin_count} users with default PIN '123456' out of {total_users} total users")
        
        if default_pin_count == 0:
            log("[OK] No users with default PIN. Migration not needed.")
            return
        
        # 3. Get list of affected users
        cursor.execute("""
            SELECT id, username, role, created_at 
            FROM users 
            WHERE pin = '123456'
            ORDER BY id
        """)
        affected_users = cursor.fetchall()
        
        log(f"\nAffected users:")
        for user in affected_users:
            log(f"  - ID={user['id']}, username={user['username']}, role={user['role']}, created={user['created_at']}")
        
        # 4. Confirm migration
        log(f"\n[WARNING] This will set force_pin_change=1 for {default_pin_count} users.")
        log("These users will be required to change their PIN before their next transaction.")
        log("This does NOT change their current PIN.")
        
        if len(sys.argv) > 1 and sys.argv[1] == '--execute':
            log("\n--execute flag detected. Proceeding with migration...")
        else:
            log("\n[DRY RUN] DRY RUN MODE. To execute migration, run: python migrate_sec005_pin.py --execute")
            return
        
        # 5. Execute migration
        log("\nStep 3: Executing migration...")
        cursor.execute("""
            UPDATE users 
            SET force_pin_change = 1 
            WHERE pin = '123456'
        """)
        
        affected_rows = cursor.rowcount
        conn.commit()
        
        log(f"[SUCCESS] Migration completed: {affected_rows} users flagged for PIN change")
        
        # 6. Verification
        log("\nStep 4: Verifying migration...")
        cursor.execute("SELECT COUNT(*) as total FROM users WHERE force_pin_change = 1")
        flagged_count = cursor.fetchone()[0]
        
        log(f"[OK] Verification: {flagged_count} users now have force_pin_change=1")
        
        # 7. Summary
        log("\n" + "=" * 60)
        log("MIGRATION SUMMARY")
        log("=" * 60)
        log(f"Total users: {total_users}")
        log(f"Users with default PIN: {default_pin_count}")
        log(f"Users flagged for PIN change: {flagged_count}")
        log(f"Success rate: {(flagged_count/default_pin_count*100) if default_pin_count > 0 else 0:.1f}%")
        log("\n[SUCCESS] SEC-005 Migration completed successfully!")
        log("=" * 60)
        
    except Exception as e:
        log(f"\n[ERROR] ERROR during migration: {e}")
        conn.rollback()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
