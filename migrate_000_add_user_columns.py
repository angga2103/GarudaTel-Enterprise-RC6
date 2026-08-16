#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Schema Migration: Add Missing User Columns
===========================================
Purpose: Add required columns to users table for fresh installations
Date: 2026-08-08
Safety: Idempotent - checks column existence before adding
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
    log("SCHEMA MIGRATION: Add Missing User Columns")
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
        # Step 1: Get existing columns
        log("\nStep 1: Checking existing users table schema...")
        cursor.execute("PRAGMA table_info(users)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        log(f"Found {len(existing_columns)} existing columns: {', '.join(existing_columns)}")
        
        # Step 2: Define required columns with their schema
        log("\nStep 2: Preparing column additions...")
        
        columns_to_add = [
            ("pin", "TEXT DEFAULT '123456'"),
            ("pin_staff1", "TEXT DEFAULT ''"),
            ("pin_staff2", "TEXT DEFAULT ''"),
            ("force_pin_change", "INTEGER DEFAULT 0"),
            ("status", "TEXT DEFAULT 'active'"),
            ("whatsapp", "TEXT DEFAULT ''"),
            ("level", "TEXT DEFAULT 'reguler'"),
            ("shop_name", "TEXT DEFAULT ''"),
            ("shop_address", "TEXT DEFAULT ''"),
            ("store_name", "TEXT DEFAULT 'Garuda Tell'"),
            ("theme_color", "TEXT DEFAULT '#115E59'"),
            ("markup_profit", "INTEGER DEFAULT 0"),
            ("nama_staff1", "TEXT DEFAULT 'Staff 1'"),
            ("nama_staff2", "TEXT DEFAULT 'Staff 2'"),
            ("active_shift_id", "INTEGER DEFAULT 0"),
        ]
        
        log(f"Total columns to process: {len(columns_to_add)}")
        
        # Step 3: Add missing columns
        log("\nStep 3: Adding missing columns...")
        
        added_count = 0
        skipped_count = 0
        failed_columns = []
        
        for col_name, col_def in columns_to_add:
            if col_name in existing_columns:
                log(f"  [SKIP] {col_name:20s} - already exists")
                skipped_count += 1
            else:
                try:
                    sql = f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"
                    cursor.execute(sql)
                    log(f"  [ADD]  {col_name:20s} - {col_def}")
                    added_count += 1
                except Exception as e:
                    log(f"  [FAIL] {col_name:20s} - {str(e)}")
                    failed_columns.append((col_name, str(e)))
        
        # Step 4: Check for failures
        if failed_columns:
            log("\nERROR: Some columns failed to add:")
            for col_name, error in failed_columns:
                log(f"  - {col_name}: {error}")
            conn.rollback()
            conn.close()
            sys.exit(1)
        
        # Step 5: Commit changes
        log("\nStep 4: Committing changes...")
        conn.commit()
        log("Changes committed successfully")
        
        # Step 6: Verify final schema
        log("\nStep 5: Verifying final schema...")
        cursor.execute("PRAGMA table_info(users)")
        final_columns = [row[1] for row in cursor.fetchall()]
        
        # Check all required columns exist
        missing_required = []
        for col_name, _ in columns_to_add:
            if col_name not in final_columns:
                missing_required.append(col_name)
        
        if missing_required:
            log(f"\nERROR: Verification failed - missing columns: {', '.join(missing_required)}")
            conn.close()
            sys.exit(1)
        
        log(f"Verified: All {len(columns_to_add)} required columns exist")
        log(f"Total columns in users table: {len(final_columns)}")
        
        # Step 7: Summary
        log("\n" + "=" * 70)
        log("MIGRATION SUMMARY")
        log("=" * 70)
        log(f"Columns added:   {added_count}")
        log(f"Columns skipped: {skipped_count}")
        log(f"Columns failed:  {len(failed_columns)}")
        log(f"Total processed: {len(columns_to_add)}")
        log("=" * 70)
        
        if added_count > 0:
            log(f"\n[SUCCESS] Added {added_count} new column(s) to users table")
        else:
            log("\n[SUCCESS] All columns already exist - no changes needed")
        
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
