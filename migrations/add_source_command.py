"""
Migration: Add source_command field to products and pricelist_cache tables
Date: 2026-08-20
Phase: 1 - Source Command Tracking

Purpose:
    Add source_command field to track which Digiflazz API call (cmd parameter)
    was used to import each product.

Values:
    - "prepaid": Product fetched with cmd=prepaid
    - "pasca": Product fetched with cmd=pasca
    - NULL: Unknown source (existing products, manual entry)

Rules:
    - DO NOT guess source_command for existing products
    - DO NOT backfill based on type/category/brand
    - Existing products remain with source_command=NULL
    - Migration is additive only (no data changes)
    - Migration is idempotent (can run multiple times)

Safety:
    - No existing data modified
    - No existing columns modified
    - No columns dropped
    - Backward compatible
"""

import sqlite3
import sys
import os
from datetime import datetime


def get_db_path():
    """Get database path"""
    # Try paypoint.db first (production)
    if os.path.exists("paypoint.db"):
        return "paypoint.db"
    # Fall back to database.db
    elif os.path.exists("database.db"):
        return "database.db"
    else:
        raise FileNotFoundError("No database file found (paypoint.db or database.db)")


def check_column_exists(conn, table, column):
    """Check if column exists in table"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns


def get_table_count(conn, table):
    """Get row count from table"""
    try:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]
    except sqlite3.Error:
        return 0


def upgrade(conn):
    """Add source_command fields to products and pricelist_cache tables"""
    
    print("=" * 70)
    print("MIGRATION: Add source_command field")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Get pre-migration counts
    products_count = get_table_count(conn, "products")
    cache_count = get_table_count(conn, "pricelist_cache")
    
    print("PRE-MIGRATION STATE:")
    print(f"  - products: {products_count} rows")
    print(f"  - pricelist_cache: {cache_count} rows")
    print()
    
    changes_made = []
    
    # 1. Add source_command to products table
    print("Step 1: Add source_command to products table...")
    if check_column_exists(conn, "products", "source_command"):
        print("  [OK] Column already exists - SKIP")
    else:
        conn.execute("ALTER TABLE products ADD COLUMN source_command TEXT")
        print("  [OK] Column added")
        changes_made.append("products.source_command")
    
    # 2. Add source_command to pricelist_cache table
    print()
    print("Step 2: Add source_command to pricelist_cache table...")
    if check_column_exists(conn, "pricelist_cache", "source_command"):
        print("  [OK] Column already exists - SKIP")
    else:
        conn.execute("ALTER TABLE pricelist_cache ADD COLUMN source_command TEXT")
        print("  [OK] Column added")
        changes_made.append("pricelist_cache.source_command")
    
    # 3. Create index on products.source_command
    print()
    print("Step 3: Create index on products.source_command...")
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_products_source_command ON products(source_command)")
        print("  [OK] Index created")
        changes_made.append("idx_products_source_command")
    except sqlite3.Error as e:
        print(f"  [WARN] Index creation warning: {e}")
    
    # Commit changes
    conn.commit()
    
    # Verify changes
    print()
    print("VERIFICATION:")
    
    products_has_source = check_column_exists(conn, "products", "source_command")
    cache_has_source = check_column_exists(conn, "pricelist_cache", "source_command")
    
    print(f"  - products.source_command exists: {'[YES]' if products_has_source else '[NO]'}")
    print(f"  - pricelist_cache.source_command exists: {'[YES]' if cache_has_source else '[NO]'}")
    
    # Check data integrity
    products_count_after = get_table_count(conn, "products")
    cache_count_after = get_table_count(conn, "pricelist_cache")
    
    print()
    print("POST-MIGRATION STATE:")
    print(f"  - products: {products_count_after} rows (was {products_count})")
    print(f"  - pricelist_cache: {cache_count_after} rows (was {cache_count})")
    
    # Check existing products have NULL source_command
    cursor = conn.execute("SELECT COUNT(*) FROM products WHERE source_command IS NULL")
    null_count = cursor.fetchone()[0]
    
    cursor = conn.execute("SELECT COUNT(*) FROM products WHERE source_command IS NOT NULL")
    not_null_count = cursor.fetchone()[0]
    
    print()
    print("SOURCE_COMMAND DISTRIBUTION:")
    print(f"  - NULL (unknown): {null_count}")
    print(f"  - Known: {not_null_count}")
    
    print()
    print("=" * 70)
    
    if products_count != products_count_after:
        raise Exception(f"ERROR: Data loss detected! products count changed from {products_count} to {products_count_after}")
    
    if cache_count != cache_count_after:
        raise Exception(f"ERROR: Data loss detected! pricelist_cache count changed from {cache_count} to {cache_count_after}")
    
    if not products_has_source or not cache_has_source:
        raise Exception("ERROR: Column creation failed!")
    
    if changes_made:
        print("[SUCCESS] MIGRATION SUCCESSFUL")
        print(f"  Changes: {', '.join(changes_made)}")
    else:
        print("[SUCCESS] MIGRATION ALREADY APPLIED")
        print("  No changes needed (idempotent)")
    
    print("=" * 70)
    print()
    
    return True


def downgrade(conn):
    """
    Downgrade not implemented for SQLite.
    
    SQLite does not support DROP COLUMN directly.
    To remove columns, you would need to:
    1. Create new table without source_command
    2. Copy data from old table
    3. Drop old table
    4. Rename new table
    
    This is dangerous in production and not recommended.
    """
    print("=" * 70)
    print("DOWNGRADE NOT IMPLEMENTED")
    print("=" * 70)
    print()
    print("SQLite does not support DROP COLUMN easily.")
    print("Removing source_command would require full table recreation.")
    print()
    print("To manually downgrade:")
    print("  1. Restore from backup: paypoint.db.backup_phase1_before")
    print("  2. Or leave column as-is (harmless)")
    print()
    print("=" * 70)
    return False


def main():
    """Main migration execution"""
    try:
        # Get database path
        db_path = get_db_path()
        print(f"Using database: {db_path}")
        print()
        
        # Connect to database
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Check if we should downgrade
        if len(sys.argv) > 1 and sys.argv[1] == "--downgrade":
            success = downgrade(conn)
        else:
            success = upgrade(conn)
        
        conn.close()
        
        if success:
            sys.exit(0)
        else:
            sys.exit(1)
            
    except Exception as e:
        print()
        print("=" * 70)
        print("❌ MIGRATION FAILED")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        print("ROLLBACK INSTRUCTIONS:")
        print("  1. Stop application if running")
        print("  2. Restore backup:")
        print("     cp paypoint.db.backup_phase1_before paypoint.db")
        print("  3. Restart application")
        print()
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
