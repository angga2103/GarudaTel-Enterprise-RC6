#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Schema Migration: Add Settings Table
=====================================
Purpose: Create settings table for application configuration storage
Date: 2026-08-09
Safety: Idempotent - uses CREATE TABLE IF NOT EXISTS
"""

import sqlite3
import sys
import os
from datetime import datetime

# Database path - same as models.py
DB_PATH = os.path.join(os.path.dirname(__file__), "paypoint.db")

def log(msg):
    """Print timestamped log message."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        print(f"[{timestamp}] {msg}")
    except UnicodeEncodeError:
        # Fallback for Windows console encoding issues
        print(f"[{timestamp}] {msg}".encode('utf-8', errors='replace').decode('utf-8', errors='replace'))

def main():
    log("=" * 70)
    log("SCHEMA MIGRATION: Add Settings Table")
    log("=" * 70)
    
    # Verify database exists
    if not os.path.exists(DB_PATH):
        log(f"ERROR: Database not found at {DB_PATH}")
        sys.exit(1)
    
    log(f"Database: {DB_PATH}")
    
    # Connect to database
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        # Step 1: Check if settings table already exists
        log("\nStep 1: Checking for existing settings table...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        existing = cursor.fetchone()
        
        if existing:
            log("Settings table already exists - skipping creation")
            table_existed = True
        else:
            log("Settings table does not exist - will create")
            table_existed = False
        
        # Step 2: Create settings table
        log("\nStep 2: Creating settings table...")
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                value TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        if table_existed:
            log("Table creation skipped (already exists)")
        else:
            log("Settings table created successfully")
        
        # Step 3: Commit changes
        log("\nStep 3: Committing changes...")
        conn.commit()
        log("Changes committed successfully")
        
        # Step 4: Verify table exists
        log("\nStep 4: Verifying settings table...")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'")
        verify = cursor.fetchone()
        
        if not verify:
            log("ERROR: Settings table verification failed")
            sys.exit(1)
        
        log("Settings table verified successfully")
        
        # Step 5: Check table schema
        log("\nStep 5: Verifying table schema...")
        cursor.execute("PRAGMA table_info(settings)")
        columns = cursor.fetchall()
        
        expected_columns = {'id', 'key', 'value', 'created_at'}
        actual_columns = {row[1] for row in columns}
        
        if not expected_columns.issubset(actual_columns):
            missing = expected_columns - actual_columns
            log(f"ERROR: Missing columns: {missing}")
            sys.exit(1)
        
        log(f"Schema verified: {len(columns)} columns")
        for col in columns:
            log(f"  - {col[1]} ({col[2]})")
        
        # Summary
        log("\n" + "=" * 70)
        log("MIGRATION SUMMARY")
        log("=" * 70)
        log(f"Table existed: {'Yes (skipped creation)' if table_existed else 'No (created)'}")
        log(f"Schema verified: Yes")
        log(f"Columns: {len(columns)}")
        log("=" * 70)
        
        if table_existed:
            log("\n[SUCCESS] Settings table already exists - no changes needed")
        else:
            log("\n[SUCCESS] Settings table created successfully")
        
        log("=" * 70)
        
        return True
        
    except Exception as e:
        log(f"\n[ERROR] Migration failed: {e}")
        conn.rollback()
        import traceback
        traceback.print_exc()
        return False
        
    finally:
        conn.close()

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
