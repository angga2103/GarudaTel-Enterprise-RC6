"""
Migration script: Hash existing plaintext PINs with bcrypt
Run this ONCE before deploying security fixes
"""
import sqlite3
import bcrypt
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "paypoint.db")

def migrate_pins():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    print("[INFO] Starting PIN migration to bcrypt...")
    
    # Get all users with PINs
    users = cursor.execute("SELECT id, pin, pin_staff1, pin_staff2 FROM users").fetchall()
    
    migrated_count = 0
    skipped_count = 0
    
    for user in users:
        uid = user['id']
        needs_update = False
        
        # Check if PIN needs migration (plaintext = 6 digits, bcrypt hash starts with $2)
        pin = user['pin']
        pin_staff1 = user['pin_staff1']
        pin_staff2 = user['pin_staff2']
        
        new_pin = pin
        new_staff1 = pin_staff1
        new_staff2 = pin_staff2
        
        # Migrate main PIN if plaintext (6 digits)
        if pin and len(str(pin).strip()) == 6 and str(pin).strip().isdigit():
            new_pin = bcrypt.hashpw(str(pin).strip().encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            needs_update = True
            print(f"[MIGRATE] User {uid}: main PIN {pin} -> hashed")
        
        # Migrate staff1 PIN if plaintext
        if pin_staff1 and len(str(pin_staff1).strip()) == 6 and str(pin_staff1).strip().isdigit():
            new_staff1 = bcrypt.hashpw(str(pin_staff1).strip().encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            needs_update = True
            print(f"[MIGRATE] User {uid}: staff1 PIN -> hashed")
        
        # Migrate staff2 PIN if plaintext
        if pin_staff2 and len(str(pin_staff2).strip()) == 6 and str(pin_staff2).strip().isdigit():
            new_staff2 = bcrypt.hashpw(str(pin_staff2).strip().encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            needs_update = True
            print(f"[MIGRATE] User {uid}: staff2 PIN -> hashed")
        
        if needs_update:
            cursor.execute(
                "UPDATE users SET pin=?, pin_staff1=?, pin_staff2=? WHERE id=?",
                (new_pin, new_staff1, new_staff2, uid)
            )
            migrated_count += 1
        else:
            skipped_count += 1
    
    conn.commit()
    conn.close()
    
    print(f"\n[SUCCESS] Migration complete!")
    print(f"  - Migrated: {migrated_count} users")
    print(f"  - Skipped: {skipped_count} users (already hashed)")
    print(f"\n[IMPORTANT] Backup your database before deploying!")

if __name__ == "__main__":
    migrate_pins()
