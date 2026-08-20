import secrets
import re
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash

from models import (
    list_categories, list_brands_by_category, list_types_by_brand,
    list_products_by_type, get_product_by_id,
    create_transaction, list_transactions, update_transaction,
    try_debit_balance, force_credit_balance,
    create_topup, get_topup, get_user_by_id, get_conn
)
from digiflazz import submit_transaction
from pakasir import create_qris
from paymentkita import create_qris_paymentkita

user_bp = Blueprint("user", __name__)

import os as _os

@user_bp.before_request
def check_maintenance():
    # Pengecualian agar Admin (lewat bossmode) tetap bisa memantau
    allowed_endpoints = ['user.bossmode', 'static', 'auth.login', 'auth.logout']
    if request.endpoint in allowed_endpoints:
        return None
    
    # Kunci rute kasir jika mode aktif
    if _os.path.exists('/root/web_ppob/paypoint/maintenance.flag'):
        return render_template('maintenance.html'), 503


# ─────────────────────────── API V2 (GOPAY STYLE) ───────────────────────────
@user_bp.route("/api/v2/products")
@login_required
def get_products_v2():
    provider = request.args.get("provider", "").strip().upper()
    category = request.args.get("category", "").strip()
    
    # PENYESUAIAN NAMA KATEGORI (DARI LAYAR KE DATABASE)
    cat_upper = category.upper()
    if cat_upper == "PAKET DATA": category = "Data"
    elif cat_upper == "TOKEN PLN": category = "PLN"
    elif cat_upper in ["E MONEY", "E-MONEY", "SALDO"]: category = "E-Money"
    elif "MASA" in cat_upper and "AKTIF" in cat_upper: category = "Masa Aktif"
    elif "SMS" in cat_upper or "TELPON" in cat_upper: category = "Paket SMS & Telpon"
    
    if not provider or not category: return jsonify({"ok": False, "data": []})
        
    from models import get_conn, hitung_harga_final
    conn = get_conn()
    # KHUSUS GOPAY: Tangkap semua variasi penulisan nama di database
    if provider in ["GOPAY", "GO-PAY"]:
        rows = conn.execute("SELECT * FROM products WHERE category=? AND (brand LIKE '%GOPAY%' OR brand LIKE '%GO-PAY%' OR brand LIKE '%GO PAY%') ORDER BY price ASC", (category,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM products WHERE category=? AND brand LIKE ? COLLATE NOCASE ORDER BY price ASC", (category, f"%{provider}%")).fetchall()
    conn.close()
    
    hasil = []
    lvl = getattr(current_user, 'level', 'reguler')
    for r in rows:
        d = dict(r)
        bp = d.get('base_price') or d.get('price', 0)
        mg = d.get('margin', 0)
        harga_member = hitung_harga_final(bp, mg, 'reguler')
        harga_reseller = hitung_harga_final(bp, mg, 'reseller')
        nama_rapi = d['name'].replace(provider, "").replace("PROMO", "").strip() or d['name']
        
        hasil.append({
            "id": d['id'], "sku": d['sku'], "name": d['name'], "nama_rapi": nama_rapi,
            "harga_member": harga_member, "harga_reseller": harga_reseller,
            "harga_final": harga_reseller if lvl == 'reseller' else harga_member,
            "is_reseller": (lvl == 'reseller'),
            "is_active": d.get("is_active", 1),
            "desc": str(d.get("description", "") or "")
        })
    return jsonify({"ok": True, "data": hasil})

@user_bp.route("/transaksi/<kategori>")
@login_required
def transaksi_pintar(kategori):
    if _admin_blocked(): return _admin_redirect()
    return render_template("user/gopay_transaksi.html", kategori=kategori.replace("-", " ").title())
# ────────────────────────────────────────────────────────────────────────────


def _admin_blocked() -> bool:
    return current_user.role == "admin"

def _admin_redirect():
    return redirect(url_for("admin.dashboard"))

@user_bp.route("/api/search")
@login_required
def search_products():
    import re
    q = request.args.get("q", "").strip().lower()
    if len(q) < 2: return jsonify({"ok": True, "data": []})

    q = re.sub(r'(\d+)(k|rb)', r'\g<1>000', q)
    terms = q.split()

    from models import get_conn
    conn = get_conn()
    where_clauses = ["is_active=1"]
    params = []

    for t in terms:
        if t.isdigit():
            val = int(t)
            target = val * 1000 if val < 1000 else val
            min_p = target - 10000
            max_p = target + 15000
            where_clauses.append("(name LIKE ? OR sku LIKE ? OR brand LIKE ? OR category LIKE ? OR (price >= ? AND price <= ?))")
            params.extend([f"%{t}%", f"%{t}%", f"%{t}%", f"%{t}%", min_p, max_p])
        else:
            where_clauses.append("(name LIKE ? OR sku LIKE ? OR brand LIKE ? OR category LIKE ?)")
            params.extend([f"%{t}%", f"%{t}%", f"%{t}%", f"%{t}%"])

    sql = "SELECT id, sku, name, price, category, brand, type FROM products WHERE " + " AND ".join(where_clauses) + " ORDER BY price ASC LIMIT 30"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return jsonify({"ok": True, "data": [dict(r) for r in rows]})

@user_bp.route("/api/inquiry", methods=["POST"])
@login_required
def inquiry_api():
    # --- BLACK BOX RECORDER START ---
    import json
    from datetime import datetime
    log_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "path": request.path,
        "method": request.method,
        "args": dict(request.args),
        "json": request.get_json(silent=True),
        "form": dict(request.form)
    }
    print(f"\n🚨 [BLACK BOX RECORDER] DATA MASUK: {json.dumps(log_data, indent=2)}")
    # --- BLACK BOX RECORDER END ---
    
    from digiflazz import inquiry_postpaid
    from models import save_inquiry_session
    import uuid
    import json
    
    data = request.json
    sku = data.get("sku")
    target = data.get("target")
    
    if not sku or not target:
        return jsonify({"ok": False, "error": "Data tidak lengkap"})
    
    ref_id = "INQ-" + str(uuid.uuid4())[:8].upper()
    res = inquiry_postpaid(ref_id, sku, target)
    
    if res.get("rc") == "00":
        tagihan = res.get("selling_price", 0)
        admin_df = res.get("admin", 0)
        total_tagihan = tagihan + admin_df
        customer_name = res.get("customer_name", "")
        desc_data = json.dumps(res.get("desc", {}))
        
        # Save inquiry session to prevent price manipulation
        save_inquiry_session(ref_id, current_user.id, sku, target, total_tagihan, customer_name, desc_data)
        
        return jsonify({
            "ok": True, 
            "name": customer_name,
            "amount": total_tagihan,
            "desc": res.get("desc", {}),
            "ref_id": ref_id
        })
    return jsonify({"ok": False, "error": res.get("message", "Gagal cek tagihan")})

@user_bp.route("/change-password", methods=["POST"])
@login_required
def change_password():
    from flask import request, jsonify
    from flask_login import current_user
    from werkzeug.security import generate_password_hash
    from models import get_conn
    
    data = request.get_json() if request.is_json else request.form
    if not data: data = {}
    old_pass = data.get("old_password")
    new_pass = data.get("new_password")
    
    if not current_user.check_password(old_pass):
        return jsonify({"ok": False, "error": "Password lama yang dimasukkan salah!"}), 400
        
    try:
        conn = get_conn()
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pass), current_user.id))
        conn.commit()
        conn.close()
        return jsonify({"ok": True, "msg": "Password berhasil diubah!"})
    except Exception as e:
        return jsonify({"ok": False, "error": f"Database Error: {str(e)}"}), 500

@user_bp.route("/dashboard")
@login_required
def dashboard():
    if _admin_blocked(): return _admin_redirect()
    
    # Ambil data shift untuk Banner Kasir
    from models import get_conn
    shift_info = None
    if getattr(current_user, 'active_shift_id', 0):
        conn = get_conn()
        row = conn.execute("SELECT staff_name, start_time FROM shifts WHERE id=?", (current_user.active_shift_id,)).fetchone()
        conn.close()
        if row:
            shift_info = dict(row)

    recent = list_transactions(uid=current_user.id, limit=5)
    cats = list_categories()
    import json, os
    banners_data = []
    try:
        bp_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'banners.json')
        if os.path.exists(bp_path):
            with open(bp_path, 'r', encoding='utf-8') as file:
                banners_data = json.load(file)
    except:
        pass
    return render_template("user/dashboard.html", recent=recent, categories=cats, active_shift=shift_info, banners=banners_data)

@user_bp.route("/shop")
@login_required
def shop():
    if _admin_blocked(): return _admin_redirect()
    return render_template("user/belanja.html", level="category", categories=list_categories(), crumbs=[])

@user_bp.route("/shop/<category>")
@login_required
def shop_brand(category):
    if _admin_blocked(): return _admin_redirect()
    return render_template("user/belanja.html", level="brand", category=category, brands=list_brands_by_category(category), crumbs=[("Belanja", url_for("user.shop")), (category, None)], back_url=url_for("user.shop"))

@user_bp.route("/shop/<category>/<brand>")
@login_required
def shop_type(category, brand):
    if _admin_blocked(): return _admin_redirect()
    return render_template("user/belanja.html", level="type", category=category, brand=brand, types=list_types_by_brand(category, brand), crumbs=[("Belanja", url_for("user.shop")), (category, url_for("user.shop_brand", category=category)), (brand, None)], back_url=url_for("user.shop_brand", category=category))

@user_bp.route("/shop/<category>/<brand>/<type_>")
@login_required
def shop_products(category, brand, type_):
    if _admin_blocked(): return _admin_redirect()
    return render_template("user/belanja.html", level="product", category=category, brand=brand, type_=type_, products=list_products_by_type(category, brand, type_), crumbs=[("Belanja", url_for("user.shop")), (category, url_for("user.shop_brand", category=category)), (brand, url_for("user.shop_type", category=category, brand=brand)), (type_, None)], back_url=url_for("user.shop_type", category=category, brand=brand))



@user_bp.route("/buy", methods=["POST"])
@login_required
def buy():
    # --- BLACK BOX RECORDER START ---
    import json
    from datetime import datetime
    log_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "path": request.path,
        "method": request.method,
        "args": dict(request.args),
        "json": request.get_json(silent=True),
        "form": dict(request.form)
    }
    print(f"\n🚨 [BLACK BOX RECORDER] DATA MASUK: {json.dumps(log_data, indent=2)}")
    # --- BLACK BOX RECORDER END ---
    
    # 🛡️ SECURITY: Check if user must change PIN before transaction
    if hasattr(current_user, 'force_pin_change') and current_user.force_pin_change == 1:
        return jsonify({
            "ok": False, 
            "error": "Anda wajib mengganti PIN transaksi terlebih dahulu untuk keamanan akun Anda.",
            "force_pin_change": True
        }), 403
    
    if _admin_blocked():
        return jsonify({"ok": False, "error": "Admin tidak dapat melakukan transaksi"}), 403
    data = request.get_json() if request.is_json else request.form
    if not data: data = {}
    pid = int(data.get("product_id") or 0)
    target = (data.get("target") or "").strip()
    pin = (data.get("pin") or "").strip()
    
    if not target:
        return jsonify({"ok": False, "error": "Nomor tujuan wajib diisi"}), 400
        
    from models import get_conn
    conn_buy = get_conn()
    row_buy = conn_buy.execute("SELECT pin, pin_staff1, pin_staff2, nama_staff1, nama_staff2 FROM users WHERE id=?", (current_user.id,)).fetchone()
    
    # Intip siapa kasir yang sedang aktif di shift ini
    active_staff = None
    if getattr(current_user, 'active_shift_id', 0):
        s_row = conn_buy.execute("SELECT staff_name FROM shifts WHERE id=?", (current_user.active_shift_id,)).fetchone()
        if s_row:
            active_staff = s_row["staff_name"]
            
    conn_buy.close()
    
    input_pin = str(pin).strip()
    kasir_name = None
    
    if row_buy:
        staff1_name = str(row_buy["nama_staff1"]).strip() if row_buy["nama_staff1"] else "Staff 1"
        staff2_name = str(row_buy["nama_staff2"]).strip() if row_buy["nama_staff2"] else "Staff 2"
        
        # Helper function for backward-compatible PIN verification
        def verify_pin_compat(input_pin, stored_pin, user_id=None, pin_field="pin"):
            """Verify PIN with auto-migration from plaintext to bcrypt."""
            if not stored_pin:
                return False
            
            import bcrypt
            stored_pin_clean = str(stored_pin).strip()
            is_bcrypt = stored_pin_clean.startswith('$2')
            
            if is_bcrypt:
                try:
                    return bcrypt.checkpw(input_pin.encode('utf-8'), stored_pin_clean.encode('utf-8'))
                except:
                    return False
            else:
                # Plaintext - compare and auto-migrate
                if input_pin == stored_pin_clean:
                    if user_id:
                        try:
                            from models import get_conn
                            pin_hash = bcrypt.hashpw(input_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                            conn_migrate = get_conn()
                            conn_migrate.execute(f"UPDATE users SET {pin_field}=? WHERE id=?", (pin_hash, user_id))
                            conn_migrate.commit()
                            conn_migrate.close()
                        except:
                            pass
                    return True
                return False
        
        if input_pin != "":
            # Check master PIN
            if verify_pin_compat(input_pin, row_buy["pin"], current_user.id, "pin"):
                kasir_name = "BOS/ADMIN"
            # Check staff1 PIN
            elif verify_pin_compat(input_pin, row_buy["pin_staff1"], current_user.id, "pin_staff1"):
                if active_staff == staff1_name:
                    kasir_name = staff1_name
                else:
                    return jsonify({"ok": False, "error": f"Ditolak: {staff1_name} sedang tidak Buka Shift!"}), 403
            # Check staff2 PIN
            elif verify_pin_compat(input_pin, row_buy["pin_staff2"], current_user.id, "pin_staff2"):
                if active_staff == staff2_name:
                    kasir_name = staff2_name
                else:
                    return jsonify({"ok": False, "error": f"Ditolak: {staff2_name} sedang tidak Buka Shift!"}), 403
                
    if not kasir_name:
        return jsonify({"ok": False, "error": "PIN Transaksi Salah!"}), 403
    
    product = get_product_by_id(pid)
    if not product or not product["is_active"]:
        return jsonify({"ok": False, "error": "Produk tidak tersedia"}), 404

    # Server-side classification - DO NOT trust client-provided is_postpaid
    # Using source_command as primary source of truth
    from models import get_product_classification
    is_postpaid = get_product_classification(product) == "postpaid"
    
    # === POSTPAID: SERVER-SIDE VALIDATION ===
    if is_postpaid:
        ref_id = data.get("ref_id")
        if not ref_id:
            return jsonify({"ok": False, "error": "ref_id wajib untuk transaksi postpaid"}), 400
        
        order_id = "ORD-" + secrets.token_hex(8).upper()
        
        # Get and lock inquiry atomically
        from models import get_and_lock_inquiry, finalize_inquiry, get_conn
        inquiry = get_and_lock_inquiry(ref_id, current_user.id, order_id)
        
        if not inquiry:
            return jsonify({"ok": False, "error": "Inquiry tidak ditemukan, sudah digunakan, atau expired. Silakan inquiry ulang."}), 400
        
        # Extract all data from SERVER (NEVER trust client)
        final_price = inquiry["amount"]
        target = inquiry["target"]
        sku = inquiry["sku"]
        
        # Debit balance
        if not try_debit_balance(current_user.id, final_price):
            finalize_inquiry(ref_id, current_user.id, False)  # Restore inquiry for retry
            return jsonify({"ok": False, "error": "Saldo tidak mencukupi. Silakan top up."}), 400
        
        # Create transaction
        create_transaction(order_id=order_id, uid=current_user.id, sku=sku, name=product["name"], target=target, price=final_price, kind="purchase", status="pending")
        
        # Stamp kasir
        try:
            conn_upd = get_conn()
            conn_upd.execute("UPDATE transactions SET kasir_name=? WHERE order_id=?", (kasir_name, order_id))
            conn_upd.commit()
            conn_upd.close()
        except:
            pass
        
        # Call Digiflazz
        from digiflazz import pay_postpaid
        result = pay_postpaid(order_id=order_id, sku=sku, target=target)
        rc = (result.get("rc") or "").strip()
        status_text = (result.get("status") or "").lower()
        fresh = get_user_by_id(current_user.id)
        
        if rc == "00" or "sukses" in status_text:
            update_transaction(order_id, "success", sn=result.get("sn"), message=result.get("message"))
            finalize_inquiry(ref_id, current_user.id, True)  # Delete inquiry (success)
            return jsonify({"ok": True, "order_id": order_id, "status": "success", "sn": result.get("sn"), "balance": fresh.balance if fresh else 0, "message": result.get("message", "Transaksi berhasil")})
        
        if "pending" in status_text or rc == "03":
            update_transaction(order_id, "pending", message=result.get("message"))
            # Keep inquiry status='processing' for recovery
            return jsonify({"ok": True, "order_id": order_id, "status": "pending", "balance": fresh.balance if fresh else 0, "message": "Transaksi sedang diproses"})
        
        # Failed
        update_transaction(order_id, "failed", message=result.get("message", "Gagal"))
        force_credit_balance(current_user.id, final_price)
        finalize_inquiry(ref_id, current_user.id, False)  # Restore inquiry for retry
        return jsonify({"ok": False, "error": result.get("message") or "Transaksi gagal, saldo dikembalikan"}), 400
    
    # === PREPAID: ORIGINAL FLOW (UNCHANGED) ===
    # 🛡️ PAKSA HITUNG HARGA AUTO-TIER SEBELUM CHECKOUT
    from models import hitung_harga_final
    try:
        lvl = getattr(current_user, 'level', 'reguler')
        bp = product.get('base_price', 0)
        mg = product.get('margin', 0)
        harga_terhitung = hitung_harga_final(bp, mg, lvl)
    except:
        harga_terhitung = product["price"]

    final_price = harga_terhitung

    if not try_debit_balance(current_user.id, final_price):
        return jsonify({"ok": False, "error": "Saldo tidak mencukupi. Silakan top up."}), 400

    order_id = "ORD-" + secrets.token_hex(8).upper()
    create_transaction(order_id=order_id, uid=current_user.id, sku=product["sku"], name=product["name"], target=target, price=final_price, kind="purchase", status="pending")
    
    # STEMPEL NAMA KASIR KE SETRUK TRANSAKSI
    try:
        from models import get_conn
        conn_upd = get_conn()
        conn_upd.execute("UPDATE transactions SET kasir_name=? WHERE order_id=?", (kasir_name, order_id))
        conn_upd.commit()
        conn_upd.close()
    except Exception as e:
        pass
    
    from digiflazz import submit_transaction
    result = submit_transaction(order_id=order_id, sku=product["sku"], target=target)
    rc = (result.get("rc") or "").strip()
    status_text = (result.get("status") or "").lower()
    fresh = get_user_by_id(current_user.id)
    if rc == "00" or "sukses" in status_text:
        update_transaction(order_id, "success", sn=result.get("sn"), message=result.get("message"))
        return jsonify({"ok": True, "order_id": order_id, "status": "success", "sn": result.get("sn"), "balance": fresh.balance if fresh else 0, "message": result.get("message", "Transaksi berhasil")})
    if "pending" in status_text or rc == "03":
        update_transaction(order_id, "pending", message=result.get("message"))
        return jsonify({"ok": True, "order_id": order_id, "status": "pending", "balance": fresh.balance if fresh else 0, "message": "Transaksi sedang diproses"})
    update_transaction(order_id, "failed", message=result.get("message", "Gagal"))
    force_credit_balance(current_user.id, final_price)
    return jsonify({"ok": False, "error": result.get("message") or "Transaksi gagal, saldo dikembalikan"}), 400

@user_bp.route("/history")
@login_required
def history():
    if _admin_blocked(): return _admin_redirect()
    from models import get_conn
    conn = get_conn()
    pendings = conn.execute("SELECT order_id, sku, target, price FROM transactions WHERE uid=? AND status='pending' AND kind='purchase'", (current_user.id,)).fetchall()
    pending_list = [dict(p) for p in pendings]
    conn.close() 
    
    if pending_list:
        from digiflazz import submit_transaction
        updates = []
        for p in pending_list:
            try:
                res = submit_transaction(p["order_id"], p["sku"], p["target"])
                updates.append((p, res))
            except: pass
            
        if updates:
            conn2 = get_conn()
            for p, res in updates:
                status = str(res.get("status")).lower()
                if status in ["sukses", "success"]:
                    conn2.execute("UPDATE transactions SET status='success', sn=?, message=? WHERE order_id=?", (res.get("sn"), res.get("message"), p["order_id"]))
                elif status in ["gagal", "failed"]:
                    conn2.execute("UPDATE transactions SET status='failed', sn=?, message=? WHERE order_id=?", (res.get("sn"), res.get("message"), p["order_id"]))
                    # Refund menggunakan helper atomic
                    force_credit_balance(current_user.id, p["price"])
            conn2.commit()
            conn2.close()
    
    from models import list_transactions
    txs = list_transactions(uid=current_user.id, limit=100)
    
    # --- CEK KOMPLAIN AKTIF / BALASAN ---
    conn3 = get_conn()
    active_tickets = conn3.execute("SELECT order_id, status, reply, message FROM tickets WHERE user_id=? ORDER BY id DESC LIMIT 10", (current_user.id,)).fetchall()
    conn3.close()
    
    tiket_data = {}
    tiket_badge = None
    
    if active_tickets:
        for t in active_tickets:
            tiket_data[t['order_id']] = {'status': t['status'], 'reply': t['reply'], 'msg': t['message']}
            
            # Prioritas: Jika ada balasan belum dibaca (asumsi belum diklik/ditutup user)
            if t['status'] != 'closed' and t['reply'] and not tiket_badge:
                tiket_badge = {'type': 'balasan', 'order_id': t['order_id'], 'reply': t['reply']}
            # Jika ada yang pending
            elif t['status'] == 'open' and not tiket_badge:
                tiket_badge = {'type': 'pending', 'order_id': t['order_id']}

    conn_tkt = get_conn()
    tkt_rows = conn_tkt.execute("SELECT order_id, status, message FROM tickets WHERE user_id=?", (current_user.id,)).fetchall()
    conn_tkt.close()
    user_tickets = {r['order_id']: dict(r) for r in tkt_rows}
    return render_template("user/history.html", transactions=txs, user_tickets=user_tickets)

@user_bp.route("/topup")
@login_required
def topup():
    if _admin_blocked(): return _admin_redirect()
    from models import get_conn
    conn = get_conn()
    s1 = conn.execute("SELECT value FROM settings WHERE key='pakasir_enabled'").fetchone()
    pakasir_on = (s1[0] == '1') if s1 else False
    s2 = conn.execute("SELECT value FROM settings WHERE key='paymentkita_enabled'").fetchone()
    pk_on = (s2[0] == '1') if s2 else False
    
    # Tombol otomatis muncul jika salah satu gateway aktif
    auto_qris_on = pakasir_on or pk_on
    
    t = conn.execute("SELECT * FROM topups WHERE uid=? AND status='pending' ORDER BY created_at DESC LIMIT 1", (current_user.id,)).fetchone()
    conn.close()
    pending_topup = dict(t) if t else None
    return render_template("user/topup.html", pending=pending_topup, auto_qris_on=auto_qris_on)

@user_bp.route("/api/qris-dinamis", methods=["POST"])
@login_required
def api_qris_dinamis():
    data = request.get_json() or {}
    nominal = data.get("amount", 0)
    import sys
    sys.path.insert(0, '/root/web_ppob/paypoint')
    from qris_dinamis import buat_qris_dinamis
    qris_string = buat_qris_dinamis(nominal)
    return jsonify({"ok": True, "qris_string": qris_string})

@user_bp.route("/topup/cancel", methods=["POST"])
@login_required
def topup_cancel():
    data = request.get_json() if request.is_json else request.form
    if not data: data = {}
    order_id = data.get("order_id")
    from models import get_conn
    conn = get_conn()
    conn.execute("UPDATE topups SET status='cancelled' WHERE order_id=? AND uid=?", (order_id, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@user_bp.route("/topup/create", methods=["POST"])
@login_required
def topup_create():
    if _admin_blocked():
        return jsonify({"ok": False, "error": "Admin tidak dapat top up"}), 403
    data = request.get_json() if request.is_json else request.form
    if not data: data = {}
    try: amount = int(data.get("amount") or 0)
    except (TypeError, ValueError): amount = 0
    if amount < 1000: return jsonify({"ok": False, "error": "Minimum top up Rp 1.000"}), 400
    if amount > 250000: return jsonify({"ok": False, "error": "Maksimum top up Rp 250.000"}), 400
    
    from models import get_conn
    conn = get_conn()
    p_row = conn.execute("SELECT value FROM settings WHERE key='pakasir_enabled'").fetchone()
    pakasir_active = (p_row and p_row["value"] == "1")
    pk_row = conn.execute("SELECT value FROM settings WHERE key='paymentkita_enabled'").fetchone()
    paymentkita_active = (pk_row and pk_row["value"] == "1")
    conn.close()

    if not pakasir_active and not paymentkita_active:
        return jsonify({"ok": False, "error": "Sistem Top Up Otomatis sedang dimatikan Admin."}), 400

    import secrets
    order_id = "TOP-" + secrets.token_hex(8).upper()

    if pakasir_active:
        from pakasir import create_qris
        qris = create_qris(amount=amount, order_id=order_id)
        if "error" in qris:
            return jsonify({"ok": False, "error": f"Pakasir Error: {qris['error']}"})
        qris_data = qris["qris_data"]
        payment_url = qris.get("payment_url", "")
    else:
        from paymentkita import create_qris_paymentkita
        qris = create_qris_paymentkita(ref_id=order_id, nominal=amount)
        if not qris.get("success"):
            return jsonify({"ok": False, "error": f"PaymentKita Error: {qris.get('msg')}"})
        qris_data = qris["qr_string"]
        payment_url = qris["qr_url"]

    create_topup(uid=current_user.id, order_id=order_id, amount=amount, qris_data=qris_data)
    return jsonify({"ok": True, "order_id": order_id, "amount": amount, "qris_data": qris_data, "payment_url": payment_url})

@user_bp.route("/topup/status/<order_id>")
@login_required
def topup_status(order_id):
    t = get_topup(order_id)
    if not t or t["uid"] != current_user.id: return jsonify({"ok": False, "error": "Top up tidak ditemukan"}), 404
    fresh = get_user_by_id(current_user.id)
    return jsonify({"ok": True, "status": t["status"], "amount": t["amount"], "paid_at": t["paid_at"], "balance": fresh.balance if fresh else current_user.balance})

@user_bp.route("/change_pin", methods=["POST"])
@login_required
def change_pin():
    data = request.get_json() if request.is_json else request.form
    if not data: data = {}
    old_pin = str(data.get("old_pin") or "").strip()
    new_pin = str(data.get("new_pin") or "").strip()
    if not old_pin or not new_pin:
        return jsonify({"ok": False, "error": "PIN lama dan baru wajib diisi!"})
    if len(new_pin) != 6 or not new_pin.isdigit():
        return jsonify({"ok": False, "error": "PIN Baru wajib 6 Angka!"}), 400
    
    # Verify old PIN using bcrypt
    if not current_user.check_pin(old_pin):
        return jsonify({"ok": False, "error": "PIN Lama Anda salah!"}), 400
    
    # Hash new PIN with bcrypt
    import bcrypt
    from models import get_conn
    pin_hash = bcrypt.hashpw(new_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    conn = get_conn()
    conn.execute("UPDATE users SET pin=?, force_pin_change=0 WHERE id=?", (pin_hash, current_user.id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@user_bp.route("/mutations")
@login_required
def user_mutations():
    if _admin_blocked(): return _admin_redirect()
    from models import get_conn
    conn = get_conn()
    rows = conn.execute("SELECT id, uid, type, amount, balance_before, balance_after, description, datetime(created_at, 'localtime') as created_at FROM mutations WHERE uid=? ORDER BY id DESC LIMIT 100", (current_user.id,)).fetchall()
    conn.close()
    return render_template("user/mutations.html", mutations=rows)

@user_bp.context_processor
def inject_tiket_reply():
    def get_admin_reply_v2(order_id):
        import sqlite3

        try:
            db_path="/root/web_ppob/paypoint/database.db"

            conn=sqlite3.connect(db_path)
            conn.row_factory=sqlite3.Row

            row=conn.execute(
                "SELECT question, reply FROM admin_replies WHERE order_id=?",
                (order_id,)
            ).fetchone()

            conn.close()

            if row:
                print(f"[ADMIN_REPLY] FOUND {order_id}")
                return {
                    "q": row["question"],
                    "a": row["reply"]
                }

            print(f"[ADMIN_REPLY] NOT FOUND {order_id}")

        except Exception as e:
            print(f"[ADMIN_REPLY ERROR] {e}")

        return None
    return dict(get_admin_reply_v2=get_admin_reply_v2)

@user_bp.context_processor
def inject_notif_count():
    def get_unread_count():
        import sqlite3, os
        try:
            db_path = os.path.join(os.path.dirname(__file__), '..', 'paypoint.db')
            conn = sqlite3.connect(db_path)
            count = conn.execute("SELECT COUNT(*) FROM notifications WHERE created_at >= date('now', '-3 days')").fetchone()[0]
            conn.close()
            return count
        except: return 0
    return dict(unread_notif=get_unread_count())

@user_bp.route("/notifications")
@login_required
def notifications():
    import sqlite3, os
    try:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'paypoint.db')
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        notifs = conn.execute("SELECT * FROM notifications ORDER BY id DESC").fetchall()
        conn.close()
    except:
        notifs = []
    from flask import render_template
    return render_template("user/notifications.html", notifs=notifs)

@user_bp.route("/receipt/<order_id>")
@login_required
def receipt(order_id):
    from models import get_conn
    conn = get_conn()
    conn.row_factory = sqlite3.Row if 'sqlite3' in globals() else dict
    try:
        import sqlite3
        conn.row_factory = sqlite3.Row
    except: pass
    
    t = conn.execute("SELECT * FROM transactions WHERE order_id=? AND uid=?", (order_id, current_user.id)).fetchone()
    conn.close()
    
    if not t or t['status'] != 'success':
        return "Transaksi tidak ditemukan atau belum sukses.", 404
        
    return render_template("user/receipt.html", t=t)


@user_bp.route('/bossmode', methods=['GET', 'POST'])
@login_required
def bossmode():
    from flask import request, render_template, redirect, url_for, flash, session
    from models import get_conn
    from datetime import datetime
    
    # --- LOGIKA SIMPAN DATA ---
    if request.method == 'POST':
        shop_name = request.form.get('shop_name')
        try:
            markup = int(request.form.get('markup_profit') or 0)
        except:
            markup = 0
        p1 = request.form.get('pin_staff1')
        p2 = request.form.get('pin_staff2')
        p_admin = request.form.get('pin_admin')

        conn = get_conn()
        
        # --- SIMPAN PIN ADMIN JIKA ADA INPUT ---
        if p_admin:
            conn.execute("UPDATE users SET pin_admin=? WHERE id=?", (p_admin, current_user.id))
            conn.commit()

        # --- FIREWALL LOGIKA OTORITAS PIN ---
        try:
            db_user = conn.execute("SELECT * FROM users WHERE id=?", (current_user.id,)).fetchone()
            if db_user:
                asli_p1 = db_user['pin_staff1']
                asli_p2 = db_user['pin_staff2']
                
                active_shift_id = getattr(current_user, 'active_shift_id', 0)
                staff_aktif = "BOS/ADMIN"
                if active_shift_id:
                    shift_row = conn.execute("SELECT staff_name FROM shifts WHERE id=?", (active_shift_id,)).fetchone()
                    if shift_row: staff_aktif = shift_row['staff_name']
                    
                nama_s1 = getattr(current_user, 'nama_staff1', 'Staff 1')
                nama_s2 = getattr(current_user, 'nama_staff2', 'Staff 2')

                # --- VERIFIKASI PIN SAAT TOKO TUTUP ---
                if not active_shift_id:
                    auth_pin = request.form.get('auth_pin', '')
                    
                    # Konversi row DB ke dictionary agar aman dari error
                    user_dict = dict(db_user) if db_user else {}
                    boss_pass = user_dict.get('password', '')
                    # SINKRONISASI KE PIN ADMIN UTAMA (DARI MENU PROFIL)
                    admin_pin_utama = str(user_dict.get('pin') or '123456')

                    is_boss = False
                    # Cek apakah input cocok dengan Password Web ATAU PIN Admin Utama
                    if auth_pin != '' and (auth_pin == boss_pass or auth_pin == admin_pin_utama):
                        is_boss = True
                    else:
                        try:
                            from werkzeug.security import check_password_hash
                            if check_password_hash(boss_pass, auth_pin):
                                is_boss = True
                        except:
                            pass

                    if is_boss:
                        staff_aktif = "BOS/ADMIN"
                    elif auth_pin == asli_p1:
                        staff_aktif = nama_s1
                    elif auth_pin == asli_p2:
                        staff_aktif = nama_s2
                    else:
                        from flask import flash, redirect, url_for
                        flash('⛔ OTORITAS DITOLAK: PIN yang Anda masukkan salah!', 'error')
                        return redirect(url_for('user.bossmode'))
                
                if staff_aktif == nama_s1 and p2 != asli_p2:
                    from flask import flash
                    flash('⛔ KEAMANAN: Anda (Staff 1) tidak berhak mengubah PIN Staff 2! Perubahan dibatalkan.', 'warning')
                    p2 = asli_p2
                elif staff_aktif == nama_s2 and p1 != asli_p1:
                    from flask import flash
                    flash('⛔ KEAMANAN: Anda (Staff 2) tidak berhak mengubah PIN Staff 1! Perubahan dibatalkan.', 'warning')
                    p1 = asli_p1
        except Exception as e:
            pass
        # ------------------------------------
        conn.execute("UPDATE users SET shop_name=?, markup_profit=?, pin_staff1=?, pin_staff2=? WHERE id=?", 
                     (shop_name, markup, p1, p2, current_user.id))
        conn.commit()
        conn.close()
        flash('Pengaturan Toko berhasil disimpan!', 'success')
        return redirect(url_for('user.bossmode'))

    # --- LOGIKA HITUNG PROFIT (KHUSUS DI SINI) ---
    today_str = datetime.now().strftime('%Y-%m-%d')
    conn = get_conn()
    res = conn.execute("SELECT COUNT(*) as total FROM transactions WHERE uid=? AND status='success' AND created_at LIKE ?", 
                       (current_user.id, f"{today_str}%")).fetchone()
    count = res['total'] if res else 0
    profit = count * (getattr(current_user, 'markup_profit', 0) or 0)
    conn.close()
    
    from models import get_conn
    conn_tabel = get_conn()
    res_shifts = conn_tabel.execute("SELECT * FROM shifts WHERE uid=? ORDER BY id DESC LIMIT 15", (current_user.id,)).fetchall()
    shifts_data = [dict(r) for r in res_shifts]
    conn_tabel.close()
    return render_template('user/bossmode.html', today_profit=profit, today_trx_count=count, shifts=shifts_data)

@user_bp.route('/api/shift/toggle', methods=['POST'])
@login_required
def toggle_shift():
    from flask import request, jsonify
    from models import get_conn
    
    # 🛡️ SECURITY: Check if user must change PIN before shift operations
    if hasattr(current_user, 'force_pin_change') and current_user.force_pin_change == 1:
        return jsonify({
            'ok': False, 
            'msg': 'Anda wajib mengganti PIN transaksi terlebih dahulu untuk keamanan akun Anda.',
            'force_pin_change': True
        })
    
    data = request.get_json()
    pin_input = str(data.get('pin', '')).strip()
    amount = int(data.get('amount', 0))

    if amount < 0:
        return jsonify({'ok': False, 'msg': 'Nominal tidak boleh minus!'})

    # Verify PIN with backward compatibility
    staff_name = None
    if current_user.check_pin(pin_input):
        staff_name = "BOS/ADMIN"
    else:
        # Check staff PINs with backward compatibility helper
        def verify_staff_pin(stored_pin, user_id, pin_field):
            if not stored_pin:
                return False
            import bcrypt
            stored_clean = str(stored_pin).strip()
            is_bcrypt = stored_clean.startswith('$2')
            
            if is_bcrypt:
                try:
                    return bcrypt.checkpw(pin_input.encode('utf-8'), stored_clean.encode('utf-8'))
                except:
                    return False
            else:
                if pin_input == stored_clean:
                    try:
                        from models import get_conn
                        pin_hash = bcrypt.hashpw(pin_input.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        conn_m = get_conn()
                        conn_m.execute(f"UPDATE users SET {pin_field}=? WHERE id=?", (pin_hash, user_id))
                        conn_m.commit()
                        conn_m.close()
                    except:
                        pass
                    return True
                return False
        
        if verify_staff_pin(getattr(current_user, 'pin_staff1', None), current_user.id, 'pin_staff1'):
            staff_name = getattr(current_user, 'nama_staff1', 'Staff 1')
        elif verify_staff_pin(getattr(current_user, 'pin_staff2', None), current_user.id, 'pin_staff2'):
            staff_name = getattr(current_user, 'nama_staff2', 'Staff 2')
    
    if not staff_name:
        return jsonify({'ok': False, 'msg': 'PIN Salah / Tidak Dikenali!'})

    conn = get_conn()
    try:
        active_shift = getattr(current_user, 'active_shift_id', 0)

        if not active_shift:
            # EKSEKUSI BUKA SHIFT
            cur = conn.cursor()
            cur.execute("INSERT INTO shifts (uid, staff_name, start_time, modal_awal, status) VALUES (?, ?, datetime('now', '+7 hours'), ?, 'open')", (current_user.id, staff_name, amount))
            shift_id = cur.lastrowid
            conn.execute("UPDATE users SET active_shift_id=? WHERE id=?", (shift_id, current_user.id))
            conn.commit()
            return jsonify({'ok': True, 'msg': f'Shift Berhasil Dibuka oleh {staff_name}'})
        else:
            # EKSEKUSI TUTUP SHIFT

            shift_row = conn.execute(
                "SELECT staff_name FROM shifts WHERE id=? AND status='open'",
                (active_shift,)
            ).fetchone()

            if not shift_row:
                return jsonify({
                    'ok': False,
                    'msg': 'Shift aktif tidak ditemukan'
                })

            pembuka_shift = shift_row['staff_name']

            # ADMIN BOLEH OVERRIDE SIAPA SAJA
            if staff_name != "BOS/ADMIN" and pembuka_shift != staff_name:
                return jsonify({
                    'ok': False,
                    'msg': f'Shift ini dibuka oleh {pembuka_shift}. Hanya kasir yang membuka shift yang boleh menutupnya.'
                })

            conn.execute(
                "UPDATE shifts SET end_time=datetime('now', '+7 hours'), setoran_akhir=?, status='closed' WHERE id=?",
                (amount, active_shift)
            )

            conn.execute(
                "UPDATE users SET active_shift_id=0 WHERE id=?",
                (current_user.id,)
            )

            conn.commit()

            if staff_name == "BOS/ADMIN" and pembuka_shift != "BOS/ADMIN":
                msg = f'Admin menutup shift milik {pembuka_shift}'
            else:
                msg = 'Shift Ditutup. Laporan tersimpan!'

            return jsonify({
                'ok': True,
                'msg': msg
            })
    finally:
        conn.close()


from flask import jsonify

@user_bp.route('/shift/tutup', methods=['POST'])
@login_required
def tutup_shift():
    from models import get_conn
    from datetime import datetime

    active_shift_id = getattr(current_user, 'active_shift_id', 0)
    if not active_shift_id:
        return jsonify({'ok': False, 'msg': 'Tidak ada shift aktif!'})

    conn = get_conn()
    try:
        shift = conn.execute("SELECT * FROM shifts WHERE id=? AND uid=? AND status='open'", (active_shift_id, current_user.id)).fetchone()
        if not shift:
            return jsonify({'ok': False, 'msg': 'Data shift tidak ditemukan!'})

        # Hitung total penjualan sejak shift dibuka
        res_sales = conn.execute(
            "SELECT SUM(price) as total FROM transactions WHERE uid=? AND status='success' AND created_at >= ?",
            (current_user.id, shift['start_time'])
        ).fetchone()

        total_penjualan = res_sales['total'] if res_sales['total'] else 0
        modal_awal = shift['modal_awal'] if shift['modal_awal'] else 0
        setoran_akhir = modal_awal + total_penjualan

        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            "UPDATE shifts SET end_time=?, setoran_akhir=?, status='closed' WHERE id=? AND uid=?",
            (now_str, setoran_akhir, active_shift_id, current_user.id)
        )

        # Lepas status aktif user
        conn.execute("UPDATE users SET active_shift_id=0 WHERE id=?", (current_user.id,))
        conn.commit()
        return jsonify({
            'ok': True,
            'msg': f'Shift ditutup! Total Setoran: Rp {setoran_akhir:,.0f}'.replace(',', '.')
        })
    finally:
        conn.close()

@user_bp.route('/api/verify_admin', methods=['POST'])
@login_required
def verify_admin():
    from flask import request, jsonify
    try:
        data = request.get_json(silent=True) or {}
        pin_input = str(data.get('pin', '')).strip()
        master_pin = str(getattr(current_user, 'pin', '')).strip()
        
        if pin_input == master_pin and master_pin != "":
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'msg': 'Otorisasi Gagal: PIN Master Salah!'})
    except Exception as e:
        return jsonify({'ok': False, 'msg': 'Server Error: ' + str(e)})

@user_bp.route("/berlangganan")
@login_required
def berlangganan():
    import sqlite3
    from models import hitung_harga_final
    conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
    conn.row_factory = sqlite3.Row
    
    try:
        raw_prods = conn.execute("SELECT * FROM products WHERE is_langganan = 1 AND is_active = 1").fetchall()
        prods = []
        for p in raw_prods:
            p_dict = dict(p)
            # Menghitung harga akurat berdasarkan level user (Reguler/Reseller)
            p_dict['final_price'] = hitung_harga_final(p_dict['base_price'], p_dict['margin'], getattr(current_user, 'level', 'reguler'))
            prods.append(p_dict)
    except:
        prods = []
        
    try:
        subs = conn.execute("SELECT * FROM auto_subscriptions WHERE uid = ? AND status = 'active'", (current_user.id,)).fetchall()
    except:
        subs = []
        
    conn.close()
    return render_template("user/berlangganan.html", products=prods, subs=subs)

# --- ENDPOINTS LANGGANAN ---
@user_bp.route("/api/check_langganan")
@login_required
def check_langganan():
    import sqlite3
    pid = request.args.get("id")
    conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
    res = conn.execute("SELECT is_langganan FROM products WHERE id = ?", (pid,)).fetchone()
    conn.close()
    return jsonify({"is_langganan": res[0] if res else 0})

@user_bp.route("/api/setup_langganan_precheck", methods=["POST"])
@login_required
def setup_langganan_precheck():
    import sqlite3
    from datetime import datetime, timezone, timedelta

    data = request.get_json(silent=True) or {}

    # --- Ambil & validasi input dasar ---
    try:
        price = int(data.get("price") or 0)
        cycles = int(data.get("cycles") or 0)
        interval = int(data.get("interval") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Format harga / siklus / interval tidak valid"})

    pid = data.get("product_id")
    target = (data.get("target") or "").strip()

    if not pid:
        return jsonify({"ok": False, "error": "Produk langganan tidak valid"})
    if not target:
        return jsonify({"ok": False, "error": "Nomor tujuan wajib diisi"})
    if price <= 0:
        return jsonify({"ok": False, "error": "Harga langganan tidak valid"})
    if cycles < 1:
        return jsonify({"ok": False, "error": "Jumlah siklus minimal 1"})
    if interval < 1:
        return jsonify({"ok": False, "error": "Interval langganan minimal 1 hari"})

    total_needed = price * cycles

    conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
    conn.row_factory = sqlite3.Row

    try:
        # --- Validasi produk langganan ---
        prod = conn.execute("""
            SELECT id, sku, is_langganan, is_active
            FROM products
            WHERE id = ?
            LIMIT 1
        """, (pid,)).fetchone()

        if not prod:
            return jsonify({"ok": False, "error": "Produk tidak ditemukan"})
        if int(prod["is_active"] or 0) != 1:
            return jsonify({"ok": False, "error": "Produk sedang tidak aktif"})
        if int(prod["is_langganan"] or 0) != 1:
            return jsonify({"ok": False, "error": "Produk ini bukan produk langganan"})

        sku = prod["sku"]

        # --- GEMBOK CERDAS: cegah daftar langganan aktif yang sama di hari yang sama ---
        last_sub = conn.execute("""
            SELECT created_at
            FROM auto_subscriptions
            WHERE uid = ?
              AND sku = ?
              AND target = ?
              AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
        """, (current_user.id, sku, target)).fetchone()

        if last_sub and last_sub["created_at"]:
            last_created = str(last_sub["created_at"])
            last_date = last_created.split(" ")[0]

            wib_tz = timezone(timedelta(hours=7))
            today_date = datetime.now(wib_tz).strftime('%Y-%m-%d')

            if last_date == today_date:
                return jsonify({
                    "ok": False,
                    "error": "Paket ini sudah diaktifkan hari ini untuk nomor tersebut. Coba lagi besok atau tunggu sesi aktif selesai."
                })

        # --- Cek saldo user ---
        user = conn.execute("""
            SELECT balance
            FROM users
            WHERE id = ?
            LIMIT 1
        """, (current_user.id,)).fetchone()

        user_balance = int(user["balance"] or 0) if user else 0
        if user_balance < total_needed:
            return jsonify({
                "ok": False,
                "error": f"Saldo tidak cukup. Total butuh Rp {total_needed:,}"
            })

        return jsonify({
            "ok": True,
            "price": price,
            "cycles": cycles,
            "interval": interval,
            "total_needed": total_needed
        })

    except Exception as e:
        return jsonify({"ok": False, "error": f"Precheck gagal: {str(e)}"})
    finally:
        conn.close()

        
@user_bp.route("/api/frontend_langganan_log", methods=["POST"])
@login_required
def frontend_langganan_log():
    from datetime import datetime
    import json

    data = request.get_json(silent=True) or {}
    step = data.get("step", "UNKNOWN")
    payload = data.get("payload", {})

    try:
        with open("/root/web_ppob/paypoint/frontend_langganan_debug.log", "a", encoding="utf-8") as f:
            f.write(
                f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
                f"uid={getattr(current_user, 'id', None)} "
                f"step={step} "
                f"payload={json.dumps(payload, ensure_ascii=False)}\n"
            )
    except Exception as e:
        return jsonify({"ok": False, "error": f"Gagal tulis log frontend: {str(e)}"}), 500

    return jsonify({"ok": True})

@user_bp.route("/api/setup_langganan_commit", methods=["POST"])
@login_required
def setup_langganan_commit():
    import sqlite3
    from datetime import datetime, timedelta

    data = request.get_json(silent=True) or {}

    print("\n================ DEBUG LANGGANAN COMMIT START ================")
    print("RAW JSON:", data)

    try:
        pid = int(data.get("product_id") or 0)
    except (TypeError, ValueError):
        pid = 0

    target = (data.get("target") or "").strip()

    try:
        cycles = int(data.get("cycles") or 0)
        interval = int(data.get("interval") or 0)
        price = int(data.get("price") or 0)
    except (TypeError, ValueError):
        print("DEBUG COMMIT ERROR: cycles/interval/price gagal di-parse")
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": "Format data langganan tidak valid"})

    print("PARSED => pid:", pid, "| target:", target, "| cycles:", cycles, "| interval:", interval, "| price:", price)

    # --- Validasi input awal ---
    if pid <= 0:
        print("DEBUG COMMIT STOP: pid <= 0")
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": "Produk langganan tidak valid"})

    if not target:
        print("DEBUG COMMIT STOP: target kosong")
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": "Nomor tujuan wajib diisi"})

    if cycles < 1:
        print("DEBUG COMMIT STOP: cycles < 1")
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": "Jumlah siklus minimal 1"})

    if interval < 1:
        print("DEBUG COMMIT STOP: interval < 1")
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": "Interval langganan minimal 1 hari"})

    if price <= 0:
        print("DEBUG COMMIT STOP: price <= 0")
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": "Harga langganan tidak valid"})

    # Siklus pertama SUDAH dipotong di /buy
    deduct = price * max(cycles - 1, 0)
    next_date = (datetime.now() + timedelta(days=interval)).strftime("%Y-%m-%d %H:%M:%S")

    print("HITUNGAN => deduct:", deduct, "| next_date:", next_date)

    conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("BEGIN")

        # --- Ambil produk ---
        prod = conn.execute("""
            SELECT id, sku, name, price, is_langganan, is_active
            FROM products
            WHERE id = ?
            LIMIT 1
        """, (pid,)).fetchone()

        if prod:
            print("PRODUCT ROW =>", dict(prod))
        else:
            print("PRODUCT ROW => None")

        if not prod:
            conn.rollback()
            print("DEBUG COMMIT STOP: produk tidak ditemukan untuk pid =", pid)
            print("================ DEBUG LANGGANAN COMMIT END ================\n")
            return jsonify({"ok": False, "error": "Produk tidak ditemukan"})

        if int(prod["is_active"] or 0) != 1:
            conn.rollback()
            print("DEBUG COMMIT STOP: produk tidak aktif | is_active =", prod["is_active"])
            print("================ DEBUG LANGGANAN COMMIT END ================\n")
            return jsonify({"ok": False, "error": "Produk sedang tidak aktif"})

        if int(prod["is_langganan"] or 0) != 1:
            conn.rollback()
            print("DEBUG COMMIT STOP: produk bukan langganan | is_langganan =", prod["is_langganan"])
            print("================ DEBUG LANGGANAN COMMIT END ================\n")
            return jsonify({"ok": False, "error": "Produk ini bukan produk langganan"})
        
        sku = prod["sku"]
        print("SKU VALID =>", sku)

        # --- Cegah langganan aktif ganda ---
        existing = conn.execute("""
            SELECT id, created_at
            FROM auto_subscriptions
            WHERE uid = ?
              AND sku = ?
              AND target = ?
              AND status = 'active'
            ORDER BY id DESC
            LIMIT 1
        """, (current_user.id, sku, target)).fetchone()

        print("EXISTING SUB =>", dict(existing) if existing else None)

        if existing:
            conn.rollback()
            print("DEBUG COMMIT STOP: sudah ada langganan aktif ganda")
            print("================ DEBUG LANGGANAN COMMIT END ================\n")
            return jsonify({
                "ok": False,
                "error": "Masih ada langganan aktif untuk produk dan nomor tujuan ini. Batalkan dulu atau tunggu sesi aktif selesai."
            })

        # --- Cek saldo user ---
        user = conn.execute("""
            SELECT balance
            FROM users
            WHERE id = ?
            LIMIT 1
        """, (current_user.id,)).fetchone()

        print("USER BALANCE ROW =>", dict(user) if user else None)

        if not user:
            conn.rollback()
            print("DEBUG COMMIT STOP: user tidak ditemukan")
            print("================ DEBUG LANGGANAN COMMIT END ================\n")
            return jsonify({"ok": False, "error": "User tidak ditemukan"})

        current_balance = int(user["balance"] or 0)
        print("CURRENT BALANCE =>", current_balance, "| NEED DEDUCT =>", deduct)

        if current_balance < deduct:
            conn.rollback()
            print("DEBUG COMMIT STOP: saldo kurang")
            print("================ DEBUG LANGGANAN COMMIT END ================\n")
            return jsonify({
                "ok": False,
                "error": f"Saldo tidak cukup untuk mengunci sisa siklus langganan. Butuh Rp {deduct:,}"
            })

        # --- Potong saldo sisa siklus ---
        if deduct > 0:
            # Get balance before deduction for mutation log
            balance_before = current_balance
            balance_after = balance_before - deduct
            
            conn.execute("""
                UPDATE users
                SET balance = balance - ?
                WHERE id = ?
            """, (deduct, current_user.id))
            print("SALDO DIPOTONG:", deduct)
            
            # Log mutation for subscription lock
            conn.execute("""
                INSERT INTO mutations
                (uid, type, amount, balance_before, balance_after, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                current_user.id,
                "out",
                deduct,
                balance_before,
                balance_after,
                f"Kunci Saldo Langganan {sku} ({cycles-1} siklus)"
            ))
            print("MUTATION LOGGED: deduct={}, before={}, after={}".format(deduct, balance_before, balance_after))

        # --- Simpan langganan ---
        conn.execute("""
            INSERT INTO auto_subscriptions
            (uid, sku, target, total_cycles, current_cycle, price_per_cycle, next_run_date, status, cycle_days)
            VALUES (?, ?, ?, ?, 1, ?, ?, 'active', ?)
        """, (
            current_user.id,
            sku,
            target,
            cycles,
            price,
            next_date,
            interval
        ))

        sub_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        print("LANGGANAN BERHASIL DISIMPAN => sub_id:", sub_id)
        print("================ DEBUG LANGGANAN COMMIT END ================\n")

        return jsonify({
            "ok": True,
            "deduct": deduct,
            "next_run_date": next_date,
            "cycle_days": interval,
            "subscription_id": sub_id
        })

    except Exception as e:
        conn.rollback()
        print("DEBUG COMMIT EXCEPTION:", str(e))
        print("================ DEBUG LANGGANAN COMMIT END ================\n")
        return jsonify({"ok": False, "error": f"Commit langganan gagal: {str(e)}"})
    finally:
        conn.close()


@user_bp.route("/api/cancel_langganan", methods=["POST"])
@login_required
def cancel_langganan():
    import sqlite3
    from datetime import datetime

    def _log_cancel(msg):
        try:
            with open("/root/web_ppob/paypoint/cancel_langganan_debug.log", "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    data = request.get_json(silent=True) or {}
    sub_id = data.get("id")

    _log_cancel(f"START cancel_langganan | uid={getattr(current_user, 'id', None)} | sub_id={sub_id} | payload={data}")

    if not sub_id:
        _log_cancel("ERROR: sub_id kosong / tidak valid")
        return jsonify({"ok": False, "error": "ID langganan tidak valid"})

    conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("BEGIN IMMEDIATE")
        _log_cancel("DB transaction BEGIN IMMEDIATE")

        sub = conn.execute("""
            SELECT *
            FROM auto_subscriptions
            WHERE id = ?
              AND uid = ?
              AND status = 'active'
            LIMIT 1
        """, (sub_id, current_user.id)).fetchone()

        if not sub:
            _log_cancel(f"ERROR: subscription tidak ditemukan / bukan milik user / tidak active | sub_id={sub_id}")
            conn.rollback()
            return jsonify({"ok": False, "error": "Langganan tidak ditemukan atau sudah berhenti."})

        total_cycles = int(sub["total_cycles"] or 0)
        current_cycle = int(sub["current_cycle"] or 0)
        price_per_cycle = int(sub["price_per_cycle"] or 0)
        sisa_siklus = max(total_cycles - current_cycle, 0)
        refund = sisa_siklus * price_per_cycle

        _log_cancel(
            f"SUB FOUND | sub_id={sub_id} | sku={sub['sku']} | target={sub['target']} | "
            f"total={total_cycles} | current={current_cycle} | price={price_per_cycle} | "
            f"sisa={sisa_siklus} | refund={refund}"
        )

        user = conn.execute("""
            SELECT id, balance
            FROM users
            WHERE id = ?
            LIMIT 1
        """, (current_user.id,)).fetchone()

        if not user:
            _log_cancel(f"ERROR: user tidak ditemukan | uid={current_user.id}")
            conn.rollback()
            return jsonify({"ok": False, "error": "User tidak ditemukan"})

        balance_before = int(user["balance"] or 0)
        balance_after = balance_before + refund

        _log_cancel(
            f"BALANCE BEFORE | uid={current_user.id} | before={balance_before} | after={balance_after}"
        )

        # 1) nonaktifkan langganan dulu
        conn.execute("""
            UPDATE auto_subscriptions
            SET status = 'cancelled'
            WHERE id = ?
        """, (sub_id,))
        _log_cancel(f"SUB STATUS UPDATED -> cancelled | sub_id={sub_id}")

        # 2) refund saldo + catat mutasi kalau memang ada sisa siklus
        if refund > 0:
            conn.execute("""
                UPDATE users
                SET balance = ?
                WHERE id = ?
            """, (balance_after, current_user.id))
            _log_cancel(f"USER BALANCE UPDATED | uid={current_user.id} | new_balance={balance_after}")

            desc = f"Refund pembatalan langganan #{sub_id} ({sub['sku']} - {sub['target']})"

            conn.execute("""
                INSERT INTO mutations
                (uid, type, amount, balance_before, balance_after, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                current_user.id,
                "in",
                refund,
                balance_before,
                balance_after,
                desc
            ))
            _log_cancel(
                f"MUTATION INSERTED | uid={current_user.id} | amount={refund} | desc={desc}"
            )
        else:
            _log_cancel(f"NO REFUND NEEDED | sub_id={sub_id} | refund=0")

        conn.commit()
        _log_cancel(
            f"COMMIT OK | sub_id={sub_id} | refund={refund} | before={balance_before} | after={balance_after}"
        )

        return jsonify({
            "ok": True,
            "refund": refund,
            "sisa_siklus": sisa_siklus,
            "balance_before": balance_before,
            "balance_after": balance_after
        })

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        _log_cancel(f"EXCEPTION | sub_id={sub_id} | error={repr(e)}")
        return jsonify({"ok": False, "error": f"Gagal membatalkan langganan: {str(e)}"})
    finally:
        conn.close()
        _log_cancel(f"END cancel_langganan | sub_id={sub_id}")
        

@user_bp.route("/bandar_langganan")
@login_required
def bandar_langganan():
    if getattr(current_user, 'role', 'user') != 'admin':
        return "🛑 AKSES DITOLAK: Halaman ini dikhususkan untuk Komandan / Admin.", 403
        
    import sqlite3
    conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
    conn.row_factory = sqlite3.Row
    
    # Ambil SEMUA data langganan, gabungkan dengan nama member
    query = '''
        SELECT a.*, u.username as user_name, u.whatsapp as user_phone 
        FROM auto_subscriptions a
        LEFT JOIN users u ON a.uid = u.id
        ORDER BY 
            CASE WHEN a.status = 'active' THEN 1 ELSE 2 END,
            a.created_at DESC
    '''
    try:
        subs = conn.execute(query).fetchall()
    except:
        subs = []
    conn.close()
    
    return render_template("user/radar_bandar.html", subs=subs)


# ==========================================
# RUTE DINAMIS BANNER PROMO (CMS)
# ==========================================
@user_bp.route("/promo/<promo_id>")
@login_required
def promo_detail(promo_id):
    import json, os
    from flask import flash, redirect, url_for
    promo_data = None
    try:
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "banners.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as file:
                banners = json.load(file)
                for banner in banners:
                    if banner["id"] == promo_id:
                        promo_data = banner
                        break
    except Exception as e:
        pass
        
    if not promo_data:
        flash("Maaf, promo tidak ditemukan atau sudah berakhir.", "error")
        return redirect(url_for("user.dashboard"))
        
    return render_template("user/promo_detail.html", promo=promo_data)

# === [INJEKSI KATEGORI DINAMIS KE DASHBOARD] ===
@user_bp.context_processor
def inject_active_categories():
    try:
        from models import get_conn
        conn = get_conn()
        # Mengambil kategori yang aktif dan mengurutkannya dari yang terbanyak
        cats = conn.execute("SELECT category FROM products WHERE is_active=1 GROUP BY category ORDER BY COUNT(*) DESC").fetchall()
        conn.close()
        return dict(active_categories=[dict(c) for c in cats])
    except Exception as e:
        return dict(active_categories=[])
# ===============================================
