import os
import sys
import time
import sqlite3
import secrets
import traceback
from datetime import datetime, timedelta

BASE_DIR = "/root/web_ppob/paypoint"
DB_PATH = "/root/web_ppob/paypoint/paypoint.db"
LOG_PATH = "/root/web_ppob/paypoint/subscription_worker.log"
SLEEP_SECONDS = 60
FAILED_DELAY_MINUTES = 30

sys.path.insert(0, BASE_DIR)
from digiflazz import submit_transaction
from models import create_transaction, update_transaction

def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def process_subscription(sub):
    conn = get_conn()
    try:
        fresh = conn.execute("SELECT * FROM auto_subscriptions WHERE id = ? LIMIT 1", (sub["id"],)).fetchone()
        if not fresh or fresh["status"] != "active": return

        prod = conn.execute("SELECT name FROM products WHERE sku = ? LIMIT 1", (fresh["sku"],)).fetchone()
        product_name = prod["name"] if prod else f"Subscription {fresh['sku']}"

        order_id = "SUB-" + secrets.token_hex(8).upper()
        create_transaction(
            order_id=order_id, uid=fresh["uid"], sku=fresh["sku"], name=product_name,
            target=fresh["target"], price=fresh["price_per_cycle"], kind="subscription", status="pending"
        )

        log(f"SUB #{fresh['id']} START | target={fresh['target']} | sku={fresh['sku']}")
        result = submit_transaction(order_id=order_id, sku=fresh["sku"], target=fresh["target"]) or {}

        rc = str(result.get("rc", "")).strip()
        status_text = str(result.get("status", "")).lower().strip()
        message = str(result.get("message", "") or "").strip()
        sn_text = str(result.get("sn", "")).strip()

        log(f"SUB #{fresh['id']} RESULT | rc={rc} | status={status_text} | msg={message}")

        is_simulation = "simulasi" in message.lower() or sn_text.startswith("SN-")
        if is_simulation:
            update_transaction(order_id, "failed", message="Gagal: Mode Simulasi Terdeteksi")
            retry_date = (datetime.now() + timedelta(minutes=FAILED_DELAY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE auto_subscriptions SET next_run_date = ? WHERE id = ?", (retry_date, fresh["id"]))
            conn.commit()
            log(f"🚨 GHOST BLOCKED SUB #{fresh['id']} -> retry at {retry_date}")

        # ===== SUCCESS / PENDING (SIKLUS MAJU) =====
        elif rc in ["00", "03"] or status_text in ["sukses", "success", "pending"]:
            # Tentukan status transaksi untuk dicatat di DB
            db_status = "pending" if rc == "03" or "pending" in status_text else "success"
            update_transaction(order_id, db_status, sn=sn_text, message=message)
            
            # MAJUKAN SIKLUS TERLEPAS DARI STATUS PENDING ATAU SUKSES AWAL
            next_cycle = int(fresh["current_cycle"]) + 1
            total_cycles = int(fresh["total_cycles"])
            cycle_days = int(fresh["cycle_days"])

            if next_cycle >= total_cycles:
                conn.execute("UPDATE auto_subscriptions SET current_cycle = ?, status = 'completed' WHERE id = ?", (total_cycles, fresh["id"]))
                log(f"SUB #{fresh['id']} COMPLETED at cycle={total_cycles}")
            else:
                next_date = (datetime.now() + timedelta(days=cycle_days)).strftime("%Y-%m-%d %H:%M:%S")
                conn.execute("UPDATE auto_subscriptions SET current_cycle = ?, next_run_date = ? WHERE id = ?", (next_cycle, next_date, fresh["id"]))
                log(f"SUB #{fresh['id']} ADVANCED -> next_run_date={next_date}")
            conn.commit()

        # ===== FAILED =====
        else:
            update_transaction(order_id, "failed", message=message)
            retry_date = (datetime.now() + timedelta(minutes=FAILED_DELAY_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE auto_subscriptions SET next_run_date = ? WHERE id = ?", (retry_date, fresh["id"]))
            conn.commit()
            log(f"SUB #{fresh['id']} FAILED -> retry at {retry_date}")

    except Exception as e:
        log(f"ERROR SUB #{sub['id']} : {e}")
    finally:
        conn.close()

def cleanup_expired_inquiries():
    """Cleanup expired inquiry sessions (passive cleanup)"""
    conn = get_conn()
    try:
        deleted = conn.execute("DELETE FROM inquiry_sessions WHERE expires_at < datetime('now', '-1 hour')").rowcount
        conn.commit()
        if deleted > 0:
            log(f"CLEANUP: Deleted {deleted} expired inquiry sessions")
    except Exception as e:
        log(f"CLEANUP ERROR: {e}")
    finally:
        conn.close()

def recover_processing_inquiries():
    """Recover stuck inquiry sessions after crash."""
    conn = get_conn()
    try:
        # Find inquiries stuck in 'processing' state
        stuck = conn.execute("""
            SELECT i.ref_id, i.uid, i.order_id, t.status
            FROM inquiry_sessions i
            LEFT JOIN transactions t ON i.order_id = t.order_id
            WHERE i.status = 'processing' AND i.order_id IS NOT NULL
        """).fetchall()
        
        if not stuck:
            return
        
        log(f"RECOVERY: Found {len(stuck)} stuck inquiry sessions")
        
        for row in stuck:
            ref_id = row['ref_id']
            uid = row['uid']
            order_id = row['order_id']
            tx_status = row['status']
            
            if tx_status == 'success':
                # Transaction succeeded, delete inquiry
                conn.execute("DELETE FROM inquiry_sessions WHERE ref_id=? AND uid=?", (ref_id, uid))
                log(f"RECOVERY: Deleted inquiry {ref_id} (transaction success)")
            
            elif tx_status == 'failed':
                # Transaction failed, restore inquiry to active
                conn.execute("UPDATE inquiry_sessions SET status='active', order_id=NULL WHERE ref_id=? AND uid=?", (ref_id, uid))
                log(f"RECOVERY: Restored inquiry {ref_id} (transaction failed)")
            
            elif tx_status == 'pending':
                # Transaction still pending, do nothing
                log(f"RECOVERY: Skip inquiry {ref_id} (transaction pending)")
            
            else:
                # Transaction not found, inquiry orphaned, restore to active
                conn.execute("UPDATE inquiry_sessions SET status='active', order_id=NULL WHERE ref_id=? AND uid=?", (ref_id, uid))
                log(f"RECOVERY: Restored orphaned inquiry {ref_id} (no transaction)")
        
        conn.commit()
    except Exception as e:
        log(f"RECOVERY ERROR: {e}")
    finally:
        conn.close()

def run_once():
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT * FROM auto_subscriptions
            WHERE status = 'active' AND current_cycle < total_cycles
            AND datetime(next_run_date) <= datetime('now','localtime') ORDER BY id ASC
        """).fetchall()
    finally:
        conn.close()

    if rows: log(f"DUE SUBSCRIPTIONS = {len(rows)}")
    for sub in rows: process_subscription(sub)

# Global counter for scheduled jobs
run_counter = 0

def main():
    global run_counter
    log("BACKGROUND WORKER STARTED - Subscription + Inquiry Cleanup + Crash Recovery")
    while True:
        try: 
            run_once()
            run_counter += 1
            
            # Cleanup expired inquiries every 10 minutes (10 cycles)
            if run_counter % 10 == 0:
                cleanup_expired_inquiries()
            
            # Recover stuck inquiries every 5 minutes (5 cycles)
            if run_counter % 5 == 0:
                recover_processing_inquiries()
                
        except Exception as e: log(f"FATAL LOOP ERROR: {e}")
        time.sleep(SLEEP_SECONDS)

if __name__ == "__main__":
    main()
