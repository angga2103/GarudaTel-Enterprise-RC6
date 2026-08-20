"""Admin routes — products, users, transactions, selective Digiflazz pull."""

import os
import os as _os
import time
import json
import hashlib
import urllib.request
import logging
from functools import wraps

import requests
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, send_file
from flask_login import login_required, current_user

# Logger for admin routes
logger = logging.getLogger(__name__)

from models import (
    get_admin_stats,
    list_products,
    get_product_by_id,
    upsert_product,
    delete_product,
    list_users,
    set_user_balance,
    update_user_balance,
    update_user_admin,
    list_transactions,
    list_digiflazz_logs,
    list_pricelist_categories,
    list_pricelist_brands,
    upsert_pricelist_item,
    get_conn,
    get_user_by_id,
)
from digiflazz import fetch_pricelist, is_configured as digiflazz_configured, credential_hint
from oauth import is_google_configured
from pakasir import is_configured as pakasir_configured

_PRICELIST_CACHE = {"time": 0, "data": []}

admin_bp = Blueprint("admin", __name__)
def admin_required(fn):
    @wraps(fn)
    @login_required
    def wrapper(*args, **kwargs):
        if current_user.role != "admin":
            return redirect(url_for("user.dashboard"))
        return fn(*args, **kwargs)
    return wrapper

@admin_bp.route('/api/maintenance/toggle', methods=['GET', 'POST'])
@admin_required
def toggle_maintenance():
    flag_file = '/root/web_ppob/paypoint/maintenance.flag'

    if request.method == 'GET':
        return jsonify({
            'status': 'on' if _os.path.exists(flag_file) else 'off'
        })

    if _os.path.exists(flag_file):
        _os.remove(flag_file)
        return jsonify({
            'status': 'off',
            'msg': 'Sistem Dibuka! Kasir bisa masuk kembali.'
        })

    with open(flag_file, 'w') as f:
        f.write('1')

    return jsonify({
        'status': 'on',
        'msg': 'Sistem Dikunci! Mode perbaikan aktif.'
    })






# ───── Dashboard ─────
@admin_bp.route("/")
@admin_required
def dashboard():
    from models import get_conn
    conn = get_conn()
    ts_row = conn.execute("SELECT SUM(balance) as tb FROM users WHERE role='user'").fetchone()
    total_saldo = ts_row["tb"] if ts_row and ts_row["tb"] else 0
    conn.close()
    return render_template(
        "admin/dashboard.html",
        total_saldo=total_saldo,
        stats=get_admin_stats(), recent_tx=list_transactions(limit=10),
        digiflazz_configured=digiflazz_configured(),
        google_configured=is_google_configured(),
        pakasir_configured=pakasir_configured(),
        digiflazz_hint=credential_hint(),
    )


# ───── Products CRUD ─────
@admin_bp.route("/products")
@admin_required
def products():
    cat = request.args.get("category", "")
    return render_template("admin/products.html",
                           products=list_products(category=cat or None),
                           selected_cat=cat)


@admin_bp.route("/products/save", methods=["POST"])
@admin_required
def products_save():
    data = request.get_json() or {}
    sku = (data.get("sku") or "").strip()
    name = (data.get("name") or "").strip()
    category = (data.get("category") or "").strip()
    cmd = (data.get("cmd") or "prepaid").strip()
    brand = (data.get("brand") or "").strip()
    type_ = (data.get("type") or "prepaid").strip()
    try:
        base_price = int(data.get("base_price") or 0)
        margin = int(data.get("margin") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Harga dan margin harus angka"}), 400
    if not sku or not name or not category or not brand:
        return jsonify({"ok": False, "error": "SKU, nama, kategori, brand wajib diisi"}), 400
    if base_price < 0 or margin < 0:
        return jsonify({"ok": False, "error": "Harga tidak boleh negatif"}), 400
    upsert_product(sku=sku, name=name, category=category, brand=brand, type_=type_,
                   base_price=base_price, margin=margin,
                   description=data.get("description", ""),
                   is_active=int(data.get("is_active", 1)))

    # --- BYPASS LANGGANAN START ---
    try:
        import sqlite3
        is_lang = int(data.get("is_langganan", 0))
        conn = sqlite3.connect('/root/web_ppob/paypoint/paypoint.db')
        conn.execute("UPDATE products SET is_langganan = ? WHERE sku = ?", (is_lang, sku))
        conn.commit()
        conn.close()
    except Exception as e:
        print("Bypass Langganan Error:", e)
    # --- BYPASS LANGGANAN END ---
    return jsonify({"ok": True})


@admin_bp.route("/products/delete/<int:pid>", methods=["POST"])
@admin_required
def products_delete(pid):
    delete_product(pid)
    return jsonify({"ok": True})


# ───── Users (CRM) — atomic balance adjust ─────
@admin_bp.route("/users")
@admin_required
def users():
    search = request.args.get("q", "")
    return render_template("admin/users.html",
                           users=list_users(search=search), search=search)


@admin_bp.route("/users/<int:uid>/balance", methods=["POST"])
@admin_required
def users_adjust_balance(uid):
    data = request.get_json() or {}
    try:
        delta = int(data.get("delta") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Jumlah harus angka"}), 400
    new_balance = update_user_balance(uid, delta)  # atomic (BEGIN IMMEDIATE)
    if new_balance < 0:
        u = get_user_by_id(uid)
        return jsonify({"ok": False, "error": "Saldo tidak boleh negatif",
                        "balance": u.balance if u else 0}), 400

    # --- LOGIKA AUTO UPGRADE RESELLER (MANUAL DEPOSIT ADMIN) ---
    if delta > 0:
        try:
            from models import get_conn
            conn_promo = get_conn()
            res_set = conn_promo.execute("SELECT value FROM settings WHERE key='min_depo_reseller'").fetchone()
            min_depo = int(res_set['value']) if res_set else 100000

            # Jika nominal yang ditambahkan admin mencapai target
            if delta >= min_depo:
                conn_promo.execute("UPDATE users SET level='reseller' WHERE id=?", (uid,))
                conn_promo.commit() # Simpan perubahan level ke database

            conn_promo.close()
        except Exception as e:
            pass
    # -----------------------------------------------------------

    return jsonify({"ok": True, "balance": new_balance})


@admin_bp.route("/users/<int:uid>/edit", methods=["POST"])
@admin_required
def users_edit(uid):
    data = request.get_json() or {}
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip()
    role = data.get("role") or "user"
    if not username:
        return jsonify({"ok": False, "error": "Username wajib diisi"}), 400
    if role not in ("user", "admin"):
        return jsonify({"ok": False, "error": "Role tidak valid"}), 400
    update_user_admin(uid, username=username, email=email, role=role)
    wa = (data.get("whatsapp") or "").strip()
    from models import get_conn
    conn = get_conn()
    level = data.get("level") or "reguler"
    store_name = (data.get("store_name") or "Garuda Tell").strip()
    theme_color = (data.get("theme_color") or "#115E59").strip()
    conn.execute("UPDATE users SET whatsapp=?, level=?, store_name=?, theme_color=? WHERE id=?", (wa, level, store_name, theme_color, uid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ───── Transactions / Logs ─────
@admin_bp.route("/transactions")
@admin_required
def transactions():
    status = request.args.get("status", "")
    user = request.args.get("user", "").strip()
    return render_template("admin/transactions.html",
                           transactions=list_transactions(status=status or None, limit=200, username=user),
                           status_filter=status,
                           user_filter=user)


@admin_bp.route("/logs")
@admin_required
def logs():
    return render_template("admin/logs.html", logs=list_digiflazz_logs(limit=200))


# ──────────────── Selective Auto-Pull (SAFETY FIRST) ────────────────
# The previous "pull everything" behaviour risked Digiflazz API timeouts
# and produced unreviewed product spam. New flow:
#   1. Page loads cached categories & brands (instant; no API call).
#   2. Admin picks ONE category + ONE brand and clicks "Tarik Pricelist".
#   3. Server fetches Digiflazz, FILTERS in-memory by cat+brand only,
#      caches the matched subset, returns it as JSON.
#   4. Admin reviews + selects rows + sets margin → "Import Pilihan".
@admin_bp.route("/pricelist")
@admin_required
def pricelist():
    return render_template(
        "admin/pricelist.html",
        cached_cats=list_pricelist_categories(),
        digiflazz_configured=digiflazz_configured(),
    )


@admin_bp.route("/pricelist/brands")
@admin_required
def pricelist_brands():
    """Return cached brands for a chosen category (live as the admin types)."""
    cat = request.args.get("category", "").strip()
    if not cat:
        return jsonify({"ok": True, "brands": []})
    return jsonify({"ok": True, "brands": list_pricelist_brands(cat)})


@admin_bp.route("/pricelist/fetch", methods=["POST"])
@admin_required
def pricelist_fetch():
    """Selective pull: fetch from Digiflazz then filter to (category, brand)."""
    data = request.get_json() or {}
    category = (data.get("category") or "").strip()
    cmd = (data.get("cmd") or "prepaid").strip()
    brand = (data.get("brand") or "").strip()
    if not category:
        return jsonify({"ok": False, "error": "Pilih kategori dan brand dahulu"}), 400
    if not digiflazz_configured():
        return jsonify({"ok": False, "error": "Digiflazz belum dikonfigurasi"}), 400

    global _PRICELIST_CACHE
    try:
        # Jika data usianya kurang dari 30 menit, ambil dari memori. Jika lebih, minta ke Digiflazz.
        if time.time() - _PRICELIST_CACHE["time"] > 1800 or _PRICELIST_CACHE.get("cmd") != cmd:
            _PRICELIST_CACHE["data"] = fetch_pricelist(cmd)
            _PRICELIST_CACHE["cmd"] = cmd
            _PRICELIST_CACHE["time"] = time.time()
        items = _PRICELIST_CACHE["data"]
    except Exception as e:
        return jsonify({"ok": False,
                        "error": f"Gagal terhubung ke Digiflazz: {type(e).__name__}"}), 502

    # VAKSIN ANTI-CRASH: Cek apakah Digiflazz membalas dengan pesan Limit/Error
    if isinstance(items, dict) and "message" in items:
        # Hancurkan memori cache agar Bos bisa langsung coba lagi tanpa nunggu 30 menit
        _PRICELIST_CACHE["time"] = 0
        return jsonify({"ok": False, "error": f"Digiflazz: {items.get('message')}"}), 400
    elif not isinstance(items, list):
        _PRICELIST_CACHE["time"] = 0
        return jsonify({"ok": False, "error": "Format data dari Digiflazz tidak dikenali."}), 400

    filtered = []
    cat_l, brand_l = category.lower(), brand.lower()
    for it in items:
        item_cat = it.get("category", "").lower()
        item_brand = it.get("brand", "").lower()

        is_match = False
        if cmd == "pasca":
            # Jika mode Pasca, kategori dari Digiflazz pasti "pascabayar"
            # Kita cocokkan pilihan Bos (PLN/BPJS) ke Brand-nya
            if item_cat == "pascabayar":
                if not category or cat_l in item_brand:
                    is_match = True
        else:
            # Mode Prabayar normal
            if item_cat == cat_l and (not brand or item_brand == brand_l):
                is_match = True

        if is_match:
            filtered.append(it)
            try:
                upsert_pricelist_item(it, source_command=cmd)  # cache the subset for next visit
            except Exception:
                pass

    payload = [{
        "sku": it.get("buyer_sku_code") or it.get("sku"),
        "name": it.get("product_name") or it.get("name"),
        "category": it.get("category"), "brand": it.get("brand"),
        "type": "postpaid" if cmd == "pasca" else it.get("type", "prepaid"),
        "price": int(it.get("price", 0)),
        "stock_status": "Tersedia" if int(it.get("buyer_product_status", 1)) else "Habis",
        "description": (it.get("description") or "")[:200],
    } for it in filtered]
    return jsonify({"ok": True, "count": len(payload), "items": payload})


@admin_bp.route("/pricelist/import", methods=["POST"])
@admin_required
def pricelist_import():
    """Import the SKUs the admin checked, applying their chosen margin."""
    data = request.get_json() or {}
    skus = data.get("skus") or []
    try:
        margin = int(data.get("margin") or 0)
    except (TypeError, ValueError):
        margin = 0
    if not skus:
        return jsonify({"ok": False, "error": "Pilih minimal 1 produk"}), 400
    if margin < 0:
        return jsonify({"ok": False, "error": "Margin tidak boleh negatif"}), 400

    conn = get_conn()
    # Build safe parameterized query with placeholders
    placeholders = ",".join("?" * len(skus))
    query = "SELECT * FROM pricelist_cache WHERE sku IN (" + placeholders + ")"
    rows = conn.execute(query, skus).fetchall()
    conn.close()

    imported = 0
    for r in rows:
        upsert_product(
            sku=r["sku"], name=r["name"], category=r["category"], brand=r["brand"],
            type_=r["type"] or "prepaid", base_price=int(r["price"]),
            margin=margin, description=r["description"] or "", is_active=1,
            source_command=r.get("source_command"),
        )
        imported += 1
    return jsonify({"ok": True, "imported": imported})


@admin_bp.route("/pricelist/sync", methods=["POST"])
@admin_required
def pricelist_sync():
    """Refresh base price produk dari Digiflazz, margin lokal tetap dipertahankan."""
    data = request.get_json() or {}
    target_category = (data.get("category") or "").strip()
    cmd = (data.get("cmd") or "prepaid").strip()

    if not digiflazz_configured():
        return jsonify({"ok": False, "error": "Digiflazz belum dikonfigurasi"}), 400

    global _PRICELIST_CACHE
    try:
        # cache 30 menit per cmd
        if time.time() - _PRICELIST_CACHE["time"] > 1800 or _PRICELIST_CACHE.get("cmd") != cmd:
            _PRICELIST_CACHE["data"] = fetch_pricelist(cmd)
            _PRICELIST_CACHE["cmd"] = cmd
            _PRICELIST_CACHE["time"] = time.time()

        items = _PRICELIST_CACHE["data"]
    except Exception as e:
        return jsonify({
            "ok": False,
            "error": f"Gagal sinkron ke Digiflazz: {type(e).__name__}"
        }), 502

    # Proteksi kalau Digiflazz balas error / format aneh
    if isinstance(items, dict) and "message" in items:
        _PRICELIST_CACHE["time"] = 0
        return jsonify({"ok": False, "error": f"Digiflazz: {items.get('message')}"}), 400
    if not isinstance(items, list):
        _PRICELIST_CACHE["time"] = 0
        return jsonify({"ok": False, "error": "Format data Digiflazz tidak valid"}), 400

    # Bangun peta SKU -> harga & status aktif
    by_sku = {}
    for it in items:
        sku_code = it.get("buyer_sku_code") or it.get("sku")
        if not sku_code:
            continue

        b_status = it.get("buyer_product_status", True)
        s_status = it.get("seller_product_status", True)

        # jika salah satu status false/0 => produk dianggap gangguan/nonaktif
        is_active = 1
        if str(b_status).lower() in ("false", "0") or str(s_status).lower() in ("false", "0"):
            is_active = 0

        by_sku[sku_code] = {
            "price": int(it.get("price", 0) or 0),
            "active": is_active
        }

    conn = get_conn()
    try:
        if target_category:
            rows = conn.execute(
                "SELECT id, sku, margin FROM products WHERE category=?",
                (target_category,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, sku, margin FROM products"
            ).fetchall()

        updated = 0
        for r in rows:
            sku = r["sku"]
            if sku not in by_sku:
                continue

            digi = by_sku[sku]
            new_base = int(digi["price"])
            margin = int(r["margin"] or 0)
            new_price = new_base + margin
            new_status = int(digi["active"])

            conn.execute("""
                UPDATE products
                SET base_price=?,
                    price=?,
                    is_active=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (new_base, new_price, new_status, r["id"]))
            updated += 1

        conn.commit()
        return jsonify({
            "ok": True,
            "updated": updated,
            "fetched": len(by_sku),
            "cmd": cmd,
            "category": target_category or "ALL"
        })
    finally:
        conn.close()


@admin_bp.route("/transactions/force-fail", methods=["POST"])
@admin_required
def force_fail():
    if not current_user.is_authenticated or getattr(current_user, 'role', '') != 'admin':
        return jsonify({"ok": False, "error": "Bukan Admin"}), 403

    data = request.get_json() or {}
    order_id = (data.get("order_id") or "").strip()
    if not order_id:
        return jsonify({"ok": False, "error": "order_id wajib diisi"}), 400

    conn = get_conn()
    try:
        tx = conn.execute("""
            SELECT id, uid, order_id, price, status
            FROM transactions
            WHERE order_id=?
            LIMIT 1
        """, (order_id,)).fetchone()

        if not tx:
            return jsonify({"ok": False, "error": "Transaksi tidak ditemukan"}), 404

        if str(tx["status"]).lower() != "pending":
            return jsonify({
                "ok": False,
                "error": f"Transaksi tidak pending (status: {tx['status']})"
            }), 400

        user = conn.execute(
            "SELECT balance FROM users WHERE id=?",
            (tx["uid"],)
        ).fetchone()

        balance_before = int(user["balance"] or 0) if user else 0
        refund_amount = int(tx["price"] or 0)
        balance_after = balance_before + refund_amount

        # 1) fail-kan transaksi
        conn.execute(
            "UPDATE transactions SET status='failed' WHERE id=?",
            (tx["id"],)
        )

        # 2) kembalikan saldo user
        conn.execute(
            "UPDATE users SET balance=? WHERE id=?",
            (balance_after, tx["uid"])
        )

        # 3) catat mutasi refund
        conn.execute("""
            INSERT INTO mutations
            (uid, type, amount, balance_before, balance_after, description)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            tx["uid"],
            "in",
            refund_amount,
            balance_before,
            balance_after,
            f"Refund force-fail admin untuk order {tx['order_id']}"
        ))

        conn.commit()
        return jsonify({
            "ok": True,
            "msg": "Transaksi berhasil di-force-fail dan saldo dikembalikan",
            "order_id": tx["order_id"],
            "refund": refund_amount,
            "balance_before": balance_before,
            "balance_after": balance_after
        })

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()

@admin_bp.route("/api/monitor-stats")
@admin_required
def monitor_stats():
    from flask_login import current_user
    from flask import jsonify
    if not current_user.is_authenticated or getattr(current_user, 'role', '') != 'admin':
        return jsonify({"ok": False}), 403

    from models import get_conn
    import datetime
    conn = get_conn()
    limit_time = (datetime.datetime.now() - datetime.timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
    alert_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE status='pending' AND created_at < ?", (limit_time,)).fetchone()[0]
    conn.close()

    return jsonify({"ok": True, "alert_pending": alert_count})

@admin_bp.route("/users/approve", methods=["POST"])
@admin_required
def approve_user():
    from flask_login import current_user
    from flask import jsonify, request
    if not current_user.is_authenticated or getattr(current_user, 'role', '') != 'admin':
        return jsonify({"ok": False}), 403
    uid = request.get_json().get("user_id")
    from models import get_conn
    conn = get_conn()
    conn.execute("UPDATE users SET status='active' WHERE id=?", (uid,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@admin_bp.route("/users/reset-password", methods=["POST"])
@admin_required
def reset_password():
    from flask_login import current_user
    from flask import jsonify, request
    if not current_user.is_authenticated or getattr(current_user, 'role', '') != 'admin':
        return jsonify({"ok": False}), 403
    uid = request.get_json().get("user_id")
    from werkzeug.security import generate_password_hash
    new_pass = generate_password_hash("123456")
    from models import get_conn
    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?", (new_pass, uid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "msg": "Password berhasil direset menjadi: 123456"})


@admin_bp.route("/api/backup")
@login_required
def web_backup():
    if current_user.role != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    import zipfile
    from datetime import datetime
    from flask import send_file

    timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M")
    zip_filename = f"Backup_PayPoint_{timestamp}.zip"
    zip_filepath = f"/tmp/{zip_filename}"

    # Proses membungkus folder menjadi ZIP (Mengabaikan file sampah/berat)
    with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk("/root/web_ppob"):
            if "venv" in root or "__pycache__" in root or ".git" in root:
                continue
            for file in files:
                file_path = os.path.join(root, file)
                zipf.write(file_path, os.path.join("web_ppob", os.path.relpath(file_path, "/root/web_ppob")))

    return send_file(zip_filepath, as_attachment=True, download_name=zip_filename)

import hashlib
import requests
import os

# --- SISTEM RIWAYAT DEPOSIT ---
def load_deposit_history():
    import json
    try:
        with open("deposit_history.json", "r") as f:
            return json.load(f)
    except:
        return []

def save_deposit_history(hist):
    import json
    with open("deposit_history.json", "w") as f:
        json.dump(hist, f, indent=4)

@admin_bp.route("/deposit-master")
@admin_required
def deposit_master():
    hist = load_deposit_history()
    return render_template("admin/deposit.html", riwayat=hist)

@admin_bp.route("/api/tiket-deposit", methods=["POST"])
@admin_required
def tiket_deposit():
    from datetime import datetime
    import json
    data = request.json
    nominal = data.get('nominal')
    username = os.getenv("DIGIFLAZZ_USER")
    api_key = os.getenv("DIGIFLAZZ_KEY")

    sign_str = f"{username}{api_key}deposit"
    sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

    payload = {
        "username": username,
        "amount": int(nominal),
        "Bank": "ShopeePay",
        "owner_name": "Admin MarketData",
        "sign": sign
    }

    try:
        url = "https://api.digiflazz.com/v1/deposit"
        response = requests.post(url, json=payload, timeout=15)
        res_data = response.json()

        if response.status_code == 200 and 'data' in res_data:
            d = res_data['data']
            # Simpan ke riwayat
            hist = load_deposit_history()
            hist.insert(0, {
                "tanggal": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "nominal": d['amount'],
                "bank": "ShopeePay (BCA)",
                "status": "PENDING"
            })
            save_deposit_history(hist[:10]) # Simpan 10 riwayat terakhir
            return jsonify({"status": "success", "data": d})
        else:
            return jsonify({"status": "error", "msg": res_data.get('data', {}).get('message', 'Gagal dari Digiflazz')})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})


@admin_bp.route("/settings")
@login_required
def admin_settings():
    if current_user.role != "admin":
        return redirect(url_for("user.dashboard"))
    return render_template("admin/settings.html")


@admin_bp.route("/api/change-password", methods=["POST"])
@login_required
def admin_change_password():
    from flask import request, jsonify
    from flask_login import current_user

    if getattr(current_user, 'role', '') != 'admin':
        return jsonify({"status": "error", "msg": "Akses Ditolak!"})

    data = request.get_json() or {}
    old_pass = data.get("old_password")
    new_pass = data.get("new_password")

    if not current_user.check_password(old_pass):
        return jsonify({"status": "error", "msg": "Password lama yang Anda masukkan salah!"})

    try:
        from werkzeug.security import generate_password_hash
        from models import get_conn

        # INI DIA STRUKTUR ASLI WEB BOS!
        conn = get_conn()
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new_pass), current_user.id))
        conn.commit()
        conn.close()

        return jsonify({"status": "success", "msg": "Password Admin berhasil diperbarui dengan aman! 🔐"})
    except Exception as e:
        return jsonify({"status": "error", "msg": f"System Error: {str(e)}"})

@admin_bp.route("/api/settings", methods=["GET"])
@login_required
def get_settings():
    if current_user.role != 'admin':
        return jsonify({"ok": False}), 403

    conn = get_conn()
    try:
        row_aa = conn.execute("SELECT value FROM settings WHERE key='auto_approve'").fetchone()
        row_pk = conn.execute("SELECT value FROM settings WHERE key='pakasir_enabled'").fetchone()
        row_pykta = conn.execute("SELECT value FROM settings WHERE key='paymentkita_enabled'").fetchone()
        row_be = conn.execute("SELECT value FROM settings WHERE key='backup_enabled'").fetchone()
        row_bi = conn.execute("SELECT value FROM settings WHERE key='backup_interval'").fetchone()

        return jsonify({
            "auto_approve": row_aa[0] == "1" if row_aa else False,
            "pakasir_enabled": row_pk[0] == "1" if row_pk else False,
            "paymentkita_enabled": row_pykta[0] == "1" if row_pykta else False,
            "backup_enabled": row_be[0] == "1" if row_be else False,
            "backup_interval": row_bi[0] if row_bi else "2"
        })
    finally:
        conn.close()

@admin_bp.route("/api/settings/toggle", methods=["POST"])
@login_required
def toggle_settings():
    if current_user.role != 'admin': return jsonify({"ok": False})
    data = request.get_json() or {}
    from models import get_conn
    conn = get_conn()

    # Fungsi Cerdas: Coba ubah dulu, kalau gagal berarti belum ada, baru ditambah
    def safe_save(k, v):
        res = conn.execute("UPDATE settings SET value=? WHERE key=?", (v, k))
        if res.rowcount == 0:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (k, v))
        conn.commit()

    if "auto_approve" in data:
        safe_save("auto_approve", "1" if data["auto_approve"] else "0")
    if "pakasir_enabled" in data:
        safe_save("pakasir_enabled", "1" if data["pakasir_enabled"] else "0")

    if "paymentkita_enabled" in data:
        safe_save("paymentkita_enabled", "1" if data["paymentkita_enabled"] else "0")

    if "backup_enabled" in data:
        val = "1" if data["backup_enabled"] else "0"
        interval = str(data.get("backup_interval", "2"))
        safe_save("backup_enabled", val)
        safe_save("backup_interval", interval)

        import subprocess
        try:
            cron_sekarang = subprocess.check_output("/usr/bin/crontab -l", shell=True, stderr=subprocess.DEVNULL).decode("utf-8")
        except:
            cron_sekarang = ""

        cron_bersih = "\n".join([b for b in cron_sekarang.splitlines() if "telegram_backup.py" not in b])
        if val == "1":
            cron_bersih += f"\n0 */{interval} * * * cd /root/web_ppob/paypoint && /usr/bin/python3 /root/web_ppob/paypoint/telegram_backup.py >> /root/web_ppob/paypoint/backup_cron.log 2>&1\n"
        with open("/tmp/cron_baru", "w") as fc:
            fc.write(cron_bersih + "\n")
        subprocess.run("/usr/bin/crontab /tmp/cron_baru", shell=True)

    # [PENAMBAL PIPA BOCOR] Ditarik keluar agar dieksekusi apapun tombol yang ditekan!
    conn.commit()
    conn.close()
    return jsonify({"ok": True})
@admin_bp.route("/users/delete/<int:uid>", methods=["POST"])
@admin_required
def delete_user_route(uid):
    # Proteksi Anti-Blunder: Jangan sampai Admin bunuh diri
    if uid == 1 or uid == current_user.id:
        return jsonify({"ok": False, "error": "Tidak bisa menghapus akun Admin Utama!"}), 400

    from models import get_conn
    conn = get_conn()
    try:
        # Hapus semua jejak akun ini sampai ke akar-akarnya
        conn.execute("BEGIN TRANSACTION")
        conn.execute("DELETE FROM transactions WHERE uid=?", (uid,))
        conn.execute("DELETE FROM mutations WHERE uid=?", (uid,))
        conn.execute("DELETE FROM topups WHERE uid=?", (uid,))
        conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
        return jsonify({"ok": True})
    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@admin_bp.route("/users/reset-pin", methods=["POST"])
@admin_required
def reset_user_pin():
    import secrets
    import bcrypt
    data = request.get_json() or {}
    uid = data.get("user_id")
    if not uid: return jsonify({"ok": False, "error": "User ID tidak valid"}), 400

    # Generate random 6-digit PIN and hash it
    random_pin = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
    pin_hash = bcrypt.hashpw(random_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    from models import get_conn
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET pin=?, force_pin_change=1 WHERE id=?", (pin_hash, uid))
        conn.commit()
        return jsonify({"ok": True, "msg": f"PIN berhasil direset ke {random_pin}. User wajib mengganti PIN saat transaksi pertama.", "new_pin": random_pin})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@admin_bp.route("/laba")
@admin_required
def laba_report():
    from models import get_conn
    conn = get_conn()

    # Hitung Hari Ini
    t_today = conn.execute('''
        SELECT COUNT(t.id), SUM(t.price), SUM(p.base_price)
        FROM transactions t JOIN products p ON t.sku = p.sku
        WHERE (LOWER(t.status) IN ('sukses', 'success'))
        AND date(t.created_at, '+7 hours') = date('now', '+7 hours')
    ''').fetchone()

    # Hitung Bulan Ini
    t_month = conn.execute('''
        SELECT COUNT(t.id), SUM(t.price), SUM(p.base_price)
        FROM transactions t JOIN products p ON t.sku = p.sku
        WHERE (LOWER(t.status) IN ('sukses', 'success'))
        AND strftime('%Y-%m', t.created_at, '+7 hours') = strftime('%Y-%m', 'now', '+7 hours')
    ''').fetchone()

    # Hitung Keseluruhan
    t_all = conn.execute('''
        SELECT COUNT(t.id), SUM(t.price), SUM(p.base_price)
        FROM transactions t JOIN products p ON t.sku = p.sku
        WHERE (LOWER(t.status) IN ('sukses', 'success'))
    ''').fetchone()

    conn.close()

    stats = {
        'today': {'trx': t_today[0] or 0, 'omzet': t_today[1] or 0, 'modal': t_today[2] or 0, 'laba': (t_today[1] or 0) - (t_today[2] or 0)},
        'month': {'trx': t_month[0] or 0, 'omzet': t_month[1] or 0, 'modal': t_month[2] or 0, 'laba': (t_month[1] or 0) - (t_month[2] or 0)},
        'all':   {'trx': t_all[0] or 0, 'omzet': t_all[1] or 0, 'modal': t_all[2] or 0, 'laba': (t_all[1] or 0) - (t_all[2] or 0)}
    }
    return render_template("admin/laba.html", stats=stats)



@admin_bp.route("/api/broadcast", methods=["POST"])
@login_required
def api_broadcast():
    if current_user.role != "admin":
        return jsonify({"ok": False, "error": "Akses Ditolak!"}), 403

    data = request.get_json() or {}
    title = data.get("title", "Garuda Tell Info")
    body = data.get("body", "")

    try:
        import fcm_helper
        succ, fail = fcm_helper.send_broadcast_notification(title, body)
        return jsonify({"ok": True, "succ": succ, "fail": fail})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500



@admin_bp.route("/api/saldo-digiflazz", methods=["GET"])
@login_required
def api_saldo_digiflazz():
    if current_user.role != "admin":
        return jsonify({"status": "Gagal", "message": "Akses Ditolak!"})
    try:
        import digiflazz
        res = digiflazz.cek_saldo()
        return jsonify(res)
    except Exception as e:
        return jsonify({"status": "Gagal", "message": str(e)})



@admin_bp.route("/api/update-riwayat-depo", methods=["POST"])
@login_required
def update_riwayat_depo():
    if current_user.role != "admin": return jsonify({"ok": False})
    data = request.json
    idx = data.get("index")
    action = data.get("action")

    try:
        hist = load_deposit_history()
        if 0 <= idx < len(hist):
            if action == "sukses":
                hist[idx]["status"] = "SUKSES"
            elif action == "hapus":
                hist.pop(idx)
            save_deposit_history(hist)
            return jsonify({"ok": True})
    except Exception as e:
        print("Error Update Riwayat:", e)

    return jsonify({"ok": False})



@admin_bp.route("/api/promo-reseller", methods=["GET", "POST"])
@login_required
def api_promo_reseller():
    if current_user.role != "admin":
        return jsonify({"ok": False}), 403

    conn = get_conn()
    try:
        if request.method == "POST":
            data = request.get_json() or {}
            val = int(data.get("min_depo") or 100000)

            res = conn.execute(
                "UPDATE settings SET value=? WHERE key='min_depo_reseller'",
                (str(val),)
            )
            if res.rowcount == 0:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    ("min_depo_reseller", str(val))
                )

            conn.commit()
            return jsonify({"ok": True, "val": val})

        # GET
        res = conn.execute(
            "SELECT value FROM settings WHERE key='min_depo_reseller'"
        ).fetchone()

        val = int(res["value"]) if res and res["value"] else 100000
        return jsonify({"ok": True, "val": val})

    except Exception as e:
        conn.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()


@admin_bp.route("/api/backup/test", methods=["POST"])
@admin_required
def test_backup():
    os.system("python3 /root/web_ppob/paypoint/telegram_backup.py &")
    return jsonify({"ok": True})


@admin_bp.app_template_filter('wib')
def wib_filter(date_str):
    try:
        if not date_str: return '-'
        from datetime import datetime, timedelta
        # Ubah string waktu menjadi objek Python, lalu tambah 7 jam
        dt = datetime.strptime(str(date_str)[:19].replace('T', ' '), '%Y-%m-%d %H:%M:%S')
        dt = dt + timedelta(hours=7)
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except Exception as e:
        return date_str


# ───── Integration Center ─────
@admin_bp.route("/integration-center")
@admin_required
def integration_center():
    """Integration Center - Pondasi untuk integrasi sistem eksternal."""
    return render_template("admin/integration_center.html")


# ───── Firebase Integration ─────
@admin_bp.route("/firebase")
@admin_required
def firebase_integration():
    """Firebase Cloud Messaging Integration."""
    return render_template("admin/firebase.html")


@admin_bp.route("/api/firebase/config", methods=["GET"])
@admin_required
def api_firebase_config():
    """Get Firebase configuration status."""
    try:
        import json
        import os

        cred_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "firebase_credentials.json")

        if not os.path.exists(cred_path):
            return jsonify({
                "ok": True,
                "is_configured": False,
                "project_id": None,
                "sender_id": None,
                "client_email": None
            })

        with open(cred_path, 'r') as f:
            cred_data = json.load(f)

        return jsonify({
            "ok": True,
            "is_configured": True,
            "project_id": cred_data.get("project_id"),
            "sender_id": cred_data.get("client_id"),
            "client_email": cred_data.get("client_email")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/firebase/stats", methods=["GET"])
@admin_required
def api_firebase_stats():
    """Get Firebase statistics."""
    try:
        import fcm_helper

        # Get registered tokens
        registered = fcm_helper.get_registered_tokens()

        # Get last broadcast time from database (if exists)
        from models import get_conn
        conn = get_conn()
        try:
            # Check if we have broadcast log table
            last_broadcast = None
            try:
                result = conn.execute(
                    "SELECT MAX(created_at) as last_time FROM broadcast_log"
                ).fetchone()
                if result and result["last_time"]:
                    last_broadcast = result["last_time"]
            except:
                pass  # Table doesn't exist yet
        finally:
            conn.close()

        return jsonify({
            "ok": True,
            "total_devices": len(registered),
            "valid_tokens": len(registered),  # Will be updated after validation
            "invalid_tokens": 0,
            "last_broadcast": last_broadcast or "Never",
            "devices": registered
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/firebase/test", methods=["POST"])
@admin_required
def api_firebase_test():
    """Test Firebase connection dengan mengirim test notification."""
    try:
        import fcm_helper

        success_count, failure_count = fcm_helper.send_broadcast_notification(
            title="🔥 Firebase Test",
            body="Test notification dari Integration Center. Jika kamu melihat ini, Firebase bekerja dengan baik!"
        )

        return jsonify({
            "ok": True,
            "success_count": success_count,
            "failure_count": failure_count
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/firebase/validate", methods=["POST"])
@admin_required
def api_firebase_validate():
    """Validate all FCM tokens dan cleanup invalid tokens."""
    try:
        import fcm_helper
        from models import get_conn

        # Get all registered tokens
        registered = fcm_helper.get_registered_tokens()
        tokens = [r["fcm_token"] for r in registered]

        if not tokens:
            return jsonify({
                "ok": True,
                "valid_count": 0,
                "invalid_count": 0
            })

        # Validate tokens
        validation_result = fcm_helper.validate_tokens(tokens)
        valid_count = validation_result["valid_count"]
        invalid_tokens = validation_result["invalid_tokens"]

        # Clean up invalid tokens
        if invalid_tokens:
            conn = get_conn()
            try:
                placeholders = ','.join(['?'] * len(invalid_tokens))
                conn.execute(
                    f"UPDATE users SET fcm_token = NULL WHERE fcm_token IN ({placeholders})",
                    invalid_tokens
                )
                conn.commit()
            finally:
                conn.close()

        return jsonify({
            "ok": True,
            "valid_count": valid_count,
            "invalid_count": len(invalid_tokens)
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ───── Cloudflare Zero Trust Integration ─────
@admin_bp.route("/cloudflare")
@admin_required
def cloudflare_integration():
    """Cloudflare Zero Trust Tunnel Management."""
    return render_template("admin/cloudflare.html")


@admin_bp.route("/api/cloudflare/config", methods=["GET"])
@admin_required
def api_cloudflare_config():
    """Get Cloudflare configuration."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        provider = cm.get_provider("cloudflare")

        return jsonify({
            "ok": True,
            "is_configured": provider["is_configured"] if provider else False,
            "config": provider["config"] if provider else {}
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/cloudflare/status", methods=["GET"])
@admin_required
def api_cloudflare_status():
    """Get Cloudflare tunnel status with comprehensive checks."""
    try:
        from config_manager import get_config_manager
        from datetime import datetime
        import subprocess
        import shutil
        import base64
        import json

        cm = get_config_manager()
        provider = cm.get_provider("cloudflare")

        if not provider or not provider["is_configured"]:
            return jsonify({
                "ok": True,
                "token_saved": False,
                "token_format": "NOT_SAVED",
                "binary_installed": False,
                "binary_version": "-",
                "service_status": "N/A",
                "tunnel_status": "NOT_CONFIGURED",
                "origin_status": "UNKNOWN",
                "tunnel_name": "-",
                "hostname": "-",
                "service": "http://localhost:2100",
                "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_error": "Cloudflare belum dikonfigurasi"
            })

        config = provider["config"]
        tunnel_token = config.get("CLOUDFLARE_TUNNEL_TOKEN") or ""
        tunnel_name = config.get("CLOUDFLARE_TUNNEL_NAME") or "unnamed-tunnel"

        # Extract hostname from token if possible
        hostname = "konter.mascariss.my.id"  # Production verified hostname
        tunnel_id = None

        # Validate token format
        token_format = "INVALID"
        if tunnel_token:
            try:
                padding = 4 - (len(tunnel_token) % 4)
                padded_token = tunnel_token + ('=' * padding if padding != 4 else '')
                decoded_bytes = base64.urlsafe_b64decode(padded_token)
                token_json = json.loads(decoded_bytes)

                if 'a' in token_json and 't' in token_json and 's' in token_json:
                    token_format = "VALID"
                    tunnel_id = token_json.get('t', '')
            except:
                token_format = "INVALID"

        # Check if cloudflared is installed
        cloudflared_path = shutil.which("cloudflared")
        binary_installed = False
        binary_version = "-"

        if not cloudflared_path:
            # Check common installation paths
            common_paths = [
                "/usr/local/bin/cloudflared",
                "/usr/bin/cloudflared",
                "/bin/cloudflared"
            ]
            for path in common_paths:
                if os.path.exists(path):
                    cloudflared_path = path
                    break

        if cloudflared_path:
            binary_installed = True
            # Get cloudflared version
            try:
                result = subprocess.run(
                    [cloudflared_path, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False
                )
                if result.returncode == 0:
                    binary_version = result.stdout.strip().split('\n')[0] if result.stdout else "Unknown"
            except Exception:
                binary_version = "Unknown"

        # Check if service is running (systemd)
        service_status = "UNKNOWN"
        if binary_installed:
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", "cloudflared"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False
                )
                status_output = result.stdout.strip()
                if result.returncode == 0 and status_output == "active":
                    service_status = "RUNNING"
                elif status_output == "inactive":
                    service_status = "STOPPED"
                elif status_output == "failed":
                    service_status = "FAILED"
                else:
                    service_status = "NOT_CONFIGURED"
            except FileNotFoundError:
                service_status = "SYSTEMD_NOT_AVAILABLE"
            except Exception:
                service_status = "UNKNOWN"

        # Determine tunnel status based on service
        if service_status == "RUNNING":
            tunnel_status = "CONNECTED"
        elif service_status in ("STOPPED", "FAILED"):
            tunnel_status = "DISCONNECTED"
        elif not binary_installed:
            tunnel_status = "NOT_INSTALLED"
        elif token_format == "INVALID":
            tunnel_status = "INVALID_TOKEN"
        else:
            tunnel_status = "UNKNOWN"

        # Check origin health (http://localhost:2100)
        origin_status = "UNKNOWN"
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', 2100))
            sock.close()

            if result == 0:
                # Port is listening, check HTTP response
                try:
                    import urllib.request
                    req = urllib.request.Request('http://127.0.0.1:2100/', method='GET')
                    response = urllib.request.urlopen(req, timeout=3)
                    status_code = response.getcode()

                    # 200, 30x are all healthy for Flask app
                    if status_code in (200, 301, 302, 303, 307, 308):
                        origin_status = "HEALTHY"
                    else:
                        origin_status = f"HTTP_{status_code}"
                except urllib.error.HTTPError as e:
                    # Even HTTP errors mean app is responding
                    if e.code in (200, 301, 302, 303, 307, 308):
                        origin_status = "HEALTHY"
                    else:
                        origin_status = f"HTTP_{e.code}"
                except:
                    origin_status = "UNREACHABLE"
            else:
                origin_status = "PORT_CLOSED"
        except Exception:
            origin_status = "CHECK_FAILED"

        # Build error message
        last_error = None
        if tunnel_status == "NOT_INSTALLED":
            last_error = "cloudflared binary not installed"
        elif tunnel_status == "DISCONNECTED":
            last_error = f"Service status: {service_status}"
        elif tunnel_status == "INVALID_TOKEN":
            last_error = "Token format invalid"
        elif origin_status in ("UNREACHABLE", "PORT_CLOSED", "CHECK_FAILED"):
            last_error = f"Origin unreachable: {origin_status}"

        return jsonify({
            "ok": True,
            "token_saved": bool(tunnel_token),
            "token_format": token_format,
            "binary_installed": binary_installed,
            "binary_version": binary_version,
            "binary_path": cloudflared_path if cloudflared_path else None,
            "service_status": service_status,
            "tunnel_status": tunnel_status,
            "tunnel_id": tunnel_id[:8] + '...' if tunnel_id else None,
            "origin_status": origin_status,
            "tunnel_name": tunnel_name,
            "hostname": hostname,
            "service": "http://localhost:2100",
            "last_check": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "last_error": last_error
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/cloudflare/save", methods=["POST"])
@admin_required
def api_cloudflare_save():
    """Save Cloudflare configuration."""
    try:
        from config_manager import get_config_manager
        import base64
        import json

        data = request.get_json() or {}
        tunnel_token = data.get("tunnel_token", "").strip()
        tunnel_name = data.get("tunnel_name", "").strip()
        account_id = data.get("account_id", "").strip()

        if not tunnel_token:
            return jsonify({"ok": False, "error": "Tunnel token wajib diisi"}), 400

        # Validate token format (Base64-encoded JSON with required fields)
        try:
            # Add padding if needed for base64 decode
            padding = 4 - (len(tunnel_token) % 4)
            padded_token = tunnel_token + ('=' * padding if padding != 4 else '')

            # Decode base64 to get JSON
            decoded_bytes = base64.urlsafe_b64decode(padded_token)
            token_json = json.loads(decoded_bytes)

            # Validate token_json is a dict
            if not isinstance(token_json, dict):
                return jsonify({
                    "ok": False,
                    "error": "Token format tidak valid. Token harus berupa JSON object"
                }), 400

            # Validate Cloudflare tunnel token structure
            # Required fields: a (AccountTag), t (TunnelID), s (TunnelSecret)
            required_fields = ['a', 't', 's']
            missing_fields = [f for f in required_fields if f not in token_json]

            if missing_fields:
                return jsonify({
                    "ok": False,
                    "error": f"Token tidak lengkap. Missing fields: {', '.join(missing_fields)}"
                }), 400

            # Validate field values are non-empty strings
            invalid_fields = [
                f for f in required_fields
                if not isinstance(token_json.get(f), str)
                or not token_json.get(f, "").strip()
            ]

            if invalid_fields:
                return jsonify({
                    "ok": False,
                    "error": f"Token tidak valid. Fields must be non-empty strings: {', '.join(invalid_fields)}"
                }), 400

        except base64.binascii.Error:
            return jsonify({
                "ok": False,
                "error": "Token format base64 tidak valid"
            }), 400
        except json.JSONDecodeError:
            return jsonify({
                "ok": False,
                "error": "Token bukan format JSON yang valid"
            }), 400
        except ValueError as ve:
            return jsonify({
                "ok": False,
                "error": f"Token validation error: {str(ve)}"
            }), 400

        cm = get_config_manager()

        updates = {
            "CLOUDFLARE_TUNNEL_TOKEN": tunnel_token
        }

        if tunnel_name:
            updates["CLOUDFLARE_TUNNEL_NAME"] = tunnel_name

        if account_id:
            updates["CLOUDFLARE_ACCOUNT_ID"] = account_id

        # Save to .env via ConfigManager
        cm.update_config(updates, backup=True)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/cloudflare/test", methods=["POST"])
@admin_required
def api_cloudflare_test():
    """Test Cloudflare tunnel token validation - FORMAT ONLY, not connection test."""
    try:
        data = request.get_json() or {}
        tunnel_token = data.get("tunnel_token", "").strip()

        if not tunnel_token:
            return jsonify({"ok": False, "error": "Tunnel token tidak boleh kosong"}), 400

        # Validate Cloudflare Tunnel Token format
        # Note: Cloudflare tunnel tokens are base64-encoded JSON (single string),
        # NOT standard JWT with 3 parts (header.payload.signature)
        import base64
        import json

        try:
            # Add padding if needed for base64 decode
            padding = 4 - (len(tunnel_token) % 4)
            padded_token = tunnel_token + ('=' * padding if padding != 4 else '')

            # Decode base64 to get JSON
            decoded_bytes = base64.urlsafe_b64decode(padded_token)
            token_json = json.loads(decoded_bytes)

            # Validate token_json is a dict
            if not isinstance(token_json, dict):
                return jsonify({
                    "ok": True,
                    "is_valid": False,
                    "error": "Token format tidak valid. Token harus berupa JSON object"
                })

            # Validate Cloudflare tunnel token structure
            # Required fields: a (AccountTag), t (TunnelID), s (TunnelSecret)
            required_fields = ['a', 't', 's']
            missing_fields = [f for f in required_fields if f not in token_json]

            if missing_fields:
                return jsonify({
                    "ok": True,
                    "is_valid": False,
                    "error": f"Token tidak lengkap. Missing fields: {', '.join(missing_fields)}"
                })

            # Validate field values are non-empty strings
            invalid_fields = [
                f for f in required_fields
                if not isinstance(token_json.get(f), str)
                or not token_json.get(f, "").strip()
            ]

            if invalid_fields:
                return jsonify({
                    "ok": True,
                    "is_valid": False,
                    "error": f"Token tidak valid. Fields must be non-empty strings: {', '.join(invalid_fields)}"
                })

            # Extract tunnel info (partial only, for security)
            account_tag = token_json.get('a', '')
            tunnel_id = token_json.get('t', '')

            # Token format is valid
            return jsonify({
                "ok": True,
                "is_valid": True,
                "status": "TOKEN_FORMAT_VALID",
                "message": "Token format valid. Simpan konfigurasi, lalu periksa Status Panel untuk koneksi aktual.",
                "tunnel_id": tunnel_id[:8] + '...' if tunnel_id else None,
                "account_tag": account_tag[:8] + '...' if account_tag else None
            })

        except base64.binascii.Error:
            return jsonify({
                "ok": True,
                "is_valid": False,
                "error": "Token format base64 tidak valid"
            })
        except json.JSONDecodeError:
            return jsonify({
                "ok": True,
                "is_valid": False,
                "error": "Token bukan format JSON yang valid"
            })
        except ValueError as ve:
            return jsonify({
                "ok": True,
                "is_valid": False,
                "error": f"Token validation error: {str(ve)}"
            })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ───── Notification Center ─────
@admin_bp.route("/notification-center")
@admin_required
def notification_center():
    """Notification Center - Enterprise notification management."""
    return render_template("admin/notification_center.html")


@admin_bp.route("/notification-center/broadcast")
@admin_required
def notification_broadcast():
    """Broadcast notification page."""
    return render_template("admin/notification_broadcast.html")


@admin_bp.route("/notification-center/history")
@admin_required
def notification_history():
    """Notification history page."""
    return render_template("admin/notification_history.html")


@admin_bp.route("/api/notification/statistics", methods=["GET"])
@admin_required
def api_notification_statistics():
    """Get notification statistics."""
    try:
        from notification_engine import get_notification_engine
        engine = get_notification_engine()

        stats = engine.get_statistics()

        return jsonify({
            "ok": True,
            "stats": stats
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/notification/channels", methods=["GET"])
@admin_required
def api_notification_channels():
    """Get notification channels."""
    try:
        from notification_engine import get_notification_engine
        engine = get_notification_engine()

        channels = engine.get_all_channels()

        return jsonify({
            "ok": True,
            "channels": channels
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/notification/history", methods=["GET"])
@admin_required
def api_notification_history():
    """Get notification history."""
    try:
        from notification_engine import get_notification_engine
        engine = get_notification_engine()

        limit = int(request.args.get('limit', 50))
        history = engine.get_broadcast_history(limit=limit)

        return jsonify({
            "ok": True,
            "history": history
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/notification/target-counts", methods=["GET"])
@admin_required
def api_notification_target_counts():
    """Get target user counts."""
    try:
        from models import get_conn
        conn = get_conn()

        counts = {
            'all': conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            'reseller': conn.execute("SELECT COUNT(*) FROM users WHERE role='reseller'").fetchone()[0],
            'member': conn.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0],
            'kasir': conn.execute("SELECT COUNT(*) FROM users WHERE role='kasir'").fetchone()[0],
            'admin': conn.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0],
        }

        conn.close()

        return jsonify({
            "ok": True,
            "counts": counts
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/notification/broadcast", methods=["POST"])
@admin_required
def api_notification_broadcast():
    """Send broadcast notification."""
    try:
        from notification_engine import get_notification_engine

        data = request.get_json() or {}
        title = data.get('title', '').strip()
        message = data.get('message', '').strip()
        image_url = data.get('image_url', '').strip()
        target_type = data.get('target_type', 'all')
        channels = data.get('channels', [])

        if not title or not message:
            return jsonify({"ok": False, "error": "Title and message are required"}), 400

        if not channels:
            return jsonify({"ok": False, "error": "At least one channel is required"}), 400

        engine = get_notification_engine()

        # Create broadcast
        broadcast_id = engine.create_broadcast(
            title=title,
            message=message,
            target_type=target_type,
            channels=channels,
            created_by=current_user.id,
            image_url=image_url if image_url else None
        )

        if not broadcast_id:
            return jsonify({"ok": False, "error": "Failed to create broadcast"}), 500

        # Add to queue
        engine.add_to_queue(broadcast_id, target_type, channels)

        # Send immediately
        result = engine.send_broadcast(broadcast_id)

        return jsonify({
            "ok": True,
            "broadcast_id": broadcast_id,
            "result": result
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ───── WhatsApp Center ─────

# WhatsApp Center APIs - Append to routes/admin.py

@admin_bp.route("/whatsapp-center")
@admin_required
def whatsapp_center():
    """WhatsApp Communication Center."""
    return render_template("admin/whatsapp_center.html")


@admin_bp.route("/api/whatsapp/config", methods=["GET"])
@admin_required
def api_whatsapp_config():
    """Get WhatsApp configuration."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        provider = cm.get_provider("whatsapp")

        return jsonify({
            "ok": True,
            "is_configured": provider["is_configured"] if provider else False,
            "config": provider["config"] if provider else {}
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/status", methods=["GET"])
@admin_required
def api_whatsapp_status():
    """Get WhatsApp connection status."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter
        adapter = get_whatsapp_adapter()

        status = adapter.get_connection_status()

        return jsonify({
            "ok": True,
            "status": status
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/pair", methods=["POST"])
@admin_required
def api_whatsapp_pair():
    """Generate pairing code for WhatsApp."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter

        data = request.get_json() or {}
        phone_number = data.get("phone_number", "").strip()

        if not phone_number:
            return jsonify({"ok": False, "error": "Phone number is required"}), 400

        adapter = get_whatsapp_adapter()
        result = adapter.generate_pairing_code(phone_number)

        if result.get("success"):
            return jsonify({
                "ok": True,
                "code": result.get("code"),
                "expires_in": result.get("expires_in")
            })
        else:
            return jsonify({
                "ok": False,
                "error": result.get("error", "Failed to generate code")
            })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/reconnect", methods=["POST"])
@admin_required
def api_whatsapp_reconnect():
    """Reconnect WhatsApp session."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter
        adapter = get_whatsapp_adapter()

        result = adapter.restart_session()

        return jsonify({
            "ok": result.get("success", False),
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/restart", methods=["POST"])
@admin_required
def api_whatsapp_restart():
    """Restart WhatsApp session."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter
        adapter = get_whatsapp_adapter()

        result = adapter.restart_session()

        return jsonify({
            "ok": result.get("success", False),
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/disconnect", methods=["POST"])
@admin_required
def api_whatsapp_disconnect():
    """Disconnect WhatsApp session."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter
        adapter = get_whatsapp_adapter()

        result = adapter.disconnect()

        return jsonify({
            "ok": result.get("success", False),
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/delete", methods=["POST"])
@admin_required
def api_whatsapp_delete():
    """Delete WhatsApp session."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter
        adapter = get_whatsapp_adapter()

        result = adapter.delete_session()

        return jsonify({
            "ok": result.get("success", False),
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/whatsapp/test", methods=["POST"])
@admin_required
def api_whatsapp_test():
    """Send test message via WhatsApp."""
    try:
        from whatsapp_adapter import get_whatsapp_adapter

        data = request.get_json() or {}
        phone_number = data.get("phone_number", "").strip()

        if not phone_number:
            return jsonify({"ok": False, "error": "Phone number is required"}), 400

        adapter = get_whatsapp_adapter()
        result = adapter.send_message(
            phone_number,
            "ðŸ§ª Test message dari GarudaTel WhatsApp Center\n\nJika Anda menerima pesan ini, WhatsApp integration berfungsi dengan baik!"
        )

        return jsonify({
            "ok": result.get("success", False),
            "error": result.get("error")
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Digiflazz Integration -----
@admin_bp.route("/digiflazz")
@admin_required
def digiflazz_integration():
    """Digiflazz PPOB Integration."""
    return render_template("admin/digiflazz.html")


@admin_bp.route("/api/digiflazz/config", methods=["GET"])
@admin_required
def api_digiflazz_config():
    """Get Digiflazz configuration."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        provider = cm.get_provider("digiflazz")

        return jsonify({
            "ok": True,
            "is_configured": provider["is_configured"] if provider else False,
            "config": provider["config"] if provider else {}
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/digiflazz/save", methods=["POST"])
@admin_required
def api_digiflazz_save():
    """Save Digiflazz configuration."""
    try:
        from config_manager import get_config_manager

        data = request.get_json() or {}
        username = data.get("username", "").strip()
        api_key = data.get("api_key", "").strip()

        if not username or not api_key:
            return jsonify({"ok": False, "error": "Username dan API Key wajib diisi"}), 400

        cm = get_config_manager()

        updates = {
            "DIGIFLAZZ_USER": username,
            "DIGIFLAZZ_KEY": api_key
        }

        # Save to .env via ConfigManager
        cm.update_config(updates, backup=True)

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/digiflazz/test", methods=["POST"])
@admin_required
def api_digiflazz_test():
    """Test Digiflazz connection."""
    try:
        import digiflazz

        # Check if configured
        if not digiflazz._has_credentials():
            return jsonify({
                "ok": False,
                "error": "Digiflazz belum dikonfigurasi. Simpan credentials terlebih dahulu."
            }), 400

        # Test connection by calling cek_saldo
        result = digiflazz.cek_saldo()

        if result and result.get("status") == "Sukses":
            balance = result.get("saldo", 0)
            return jsonify({
                "ok": True,
                "is_valid": True,
                "balance": balance,
                "message": "Koneksi ke Digiflazz berhasil"
            })
        else:
            error_msg = result.get("message", "Gagal terhubung ke Digiflazz") if result else "Gagal terhubung ke Digiflazz"
            return jsonify({
                "ok": True,
                "is_valid": False,
                "error": error_msg
            })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/digiflazz/sync", methods=["POST"])
@admin_required
def api_digiflazz_sync():
    """Sync all products from Digiflazz to local database."""
    try:
        import digiflazz
        from models import upsert_product

        # Check if configured
        if not digiflazz._has_credentials():
            return jsonify({
                "ok": False,
                "error": "Digiflazz belum dikonfigurasi. Simpan credentials terlebih dahulu."
            }), 400

        # Fetch pricelist from Digiflazz (prepaid only for now)
        cmd = "prepaid"
        try:
            items = digiflazz.fetch_pricelist(cmd)
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": f"Gagal mengambil data dari Digiflazz: {type(e).__name__}"
            }), 502

        # Validate response
        if isinstance(items, dict) and "message" in items:
            return jsonify({
                "ok": False,
                "error": f"Digiflazz error: {items.get('message')}"
            }), 400

        if not isinstance(items, list):
            return jsonify({
                "ok": False,
                "error": "Format data dari Digiflazz tidak valid"
            }), 400

        # Build SKU map for tracking
        by_sku = {}
        for it in items:
            sku_code = it.get("buyer_sku_code") or it.get("sku")
            if not sku_code:
                continue

            b_status = it.get("buyer_product_status", True)
            s_status = it.get("seller_product_status", True)

            # Determine if product is active
            is_active = 1
            if str(b_status).lower() in ("false", "0") or str(s_status).lower() in ("false", "0"):
                is_active = 0

            by_sku[sku_code] = {
                "name": it.get("product_name") or it.get("name"),
                "category": it.get("category"),
                "brand": it.get("brand"),
                "type": it.get("type", "prepaid"),
                "price": int(it.get("price", 0) or 0),
                "description": (it.get("desc") or it.get("description") or "")[:200],
                "active": is_active
            }

        # Get existing products from database
        conn = get_conn()
        try:
            existing_products = conn.execute(
                "SELECT sku, margin FROM products"
            ).fetchall()
            existing_skus = {row["sku"]: row["margin"] for row in existing_products}
        finally:
            conn.close()

        # Statistics
        created = 0
        updated = 0
        skipped = 0

        # Process each product
        for sku, product_data in by_sku.items():
            try:
                if sku in existing_skus:
                    # Update existing product (preserve margin)
                    margin = existing_skus[sku]
                    upsert_product(
                        sku=sku,
                        name=product_data["name"],
                        category=product_data["category"],
                        brand=product_data["brand"],
                        type_=product_data["type"],
                        base_price=product_data["price"],
                        margin=margin,
                        description=product_data["description"],
                        is_active=product_data["active"],
                        source_command=cmd
                    )
                    updated += 1
                else:
                    # Create new product (default margin 0)
                    upsert_product(
                        sku=sku,
                        name=product_data["name"],
                        category=product_data["category"],
                        brand=product_data["brand"],
                        type_=product_data["type"],
                        base_price=product_data["price"],
                        margin=0,
                        description=product_data["description"],
                        is_active=product_data["active"],
                        source_command=cmd
                    )
                    created += 1
            except Exception as e:
                logger.error("Failed to sync Digiflazz product SKU %s: %s", sku, str(e), exc_info=True)
                skipped += 1
                continue

        total_processed = created + updated + skipped

        # Save last sync timestamp to settings table (only on successful sync)
        try:
            sync_conn = get_conn()
            try:
                res = sync_conn.execute("UPDATE settings SET value=datetime('now') WHERE key=?", ("last_digiflazz_sync",))
                if res.rowcount == 0:
                    sync_conn.execute("INSERT INTO settings (key, value) VALUES (?, datetime('now'))", ("last_digiflazz_sync",))
                sync_conn.commit()
            finally:
                sync_conn.close()
        except Exception as e:
            logger.warning("Failed to update last_digiflazz_sync timestamp: %s", str(e))

        return jsonify({
            "ok": True,
            "message": "Product sync successful",
            "stats": {
                "total_processed": total_processed,
                "created": created,
                "updated": updated,
                "deactivated": 0,
                "skipped": skipped
            }
        })

    except Exception as e:
        logger.error("Digiflazz sync failed: %s", str(e), exc_info=True)
        return jsonify({"ok": False, "error": "Internal sync error. Check server logs."}), 500


@admin_bp.route("/api/digiflazz/products/stats", methods=["GET"])
@admin_required
def api_digiflazz_products_stats():
    """Get Digiflazz product statistics."""
    try:
        conn = get_conn()
        try:
            # Get total products
            total_row = conn.execute("SELECT COUNT(*) as count FROM products").fetchone()
            total = total_row["count"] if total_row else 0

            # Get active products
            active_row = conn.execute("SELECT COUNT(*) as count FROM products WHERE is_active = 1").fetchone()
            active = active_row["count"] if active_row else 0

            # Get inactive products
            inactive = total - active

            # Get last sync time from settings table (dedicated Digiflazz sync timestamp)
            last_sync_row = conn.execute(
                "SELECT value FROM settings WHERE key = 'last_digiflazz_sync'"
            ).fetchone()
            last_sync = last_sync_row["value"] if last_sync_row else None

        finally:
            conn.close()

        return jsonify({
            "ok": True,
            "stats": {
                "total": total,
                "active": active,
                "inactive": inactive,
                "last_sync": last_sync
            }
        })
    except Exception as e:
        logger.error("Failed to retrieve Digiflazz product statistics: %s", str(e), exc_info=True)
        return jsonify({"ok": False, "error": "Internal error. Check server logs."}), 500


# ----- PaymentKita Integration -----
@admin_bp.route("/paymentkita")
@admin_required
def paymentkita_integration():
    """PaymentKita QRIS Integration."""
    return render_template("admin/paymentkita.html")


@admin_bp.route("/api/paymentkita/config", methods=["GET"])
@admin_required
def api_paymentkita_config():
    """Get PaymentKita configuration."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        provider = cm.get_provider("paymentkita")

        return jsonify({
            "ok": True,
            "is_configured": provider["is_configured"] if provider else False,
            "config": provider["config"] if provider else {},
            "last_test": provider.get("last_test") if provider else None
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/paymentkita/save", methods=["POST"])
@admin_required
def api_paymentkita_save():
    """Save PaymentKita configuration."""
    try:
        from config_manager import get_config_manager

        data = request.get_json() or {}
        merchant = data.get("merchant", "").strip()
        secret = data.get("secret", "").strip()

        if not merchant or not secret:
            return jsonify({"ok": False, "error": "Merchant ID dan Secret Key wajib diisi"}), 400

        cm = get_config_manager()

        updates = {
            "PAYMENTKITA_MERCHANT": merchant,
            "PAYMENTKITA_SECRET": secret
        }

        # Save to .env via ConfigManager
        cm.update_config(updates, backup=True)

        # Log configuration change
        _log_config_change("paymentkita", "UPDATED")

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/paymentkita/test", methods=["POST"])
@admin_required
def api_paymentkita_test():
    """Test PaymentKita connection."""
    try:
        import paymentkita

        # Check if configured
        try:
            merchant, secret = paymentkita.get_credentials()
        except ValueError as ve:
            return jsonify({
                "ok": False,
                "error": "PaymentKita belum dikonfigurasi. Simpan credentials terlebih dahulu."
            }), 400

        # Test by creating a test QRIS (small amount)
        test_ref = f"TEST-{int(time.time())}"
        result = paymentkita.create_qris_paymentkita(test_ref, 1000)

        if result and result.get("success"):
            return jsonify({
                "ok": True,
                "message": "Koneksi ke PaymentKita berhasil - QRIS dapat dibuat"
            })
        else:
            error_msg = result.get("msg", "Gagal terhubung ke PaymentKita") if result else "Gagal terhubung ke PaymentKita"
            return jsonify({
                "ok": False,
                "error": error_msg
            })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Pakasir Integration -----
@admin_bp.route("/pakasir")
@admin_required
def pakasir_integration():
    """Pakasir POS Integration."""
    return render_template("admin/pakasir.html")


@admin_bp.route("/api/pakasir/config", methods=["GET"])
@admin_required
def api_pakasir_config():
    """Get Pakasir configuration."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        provider = cm.get_provider("pakasir")

        return jsonify({
            "ok": True,
            "is_configured": provider["is_configured"] if provider else False,
            "config": provider["config"] if provider else {},
            "last_test": provider.get("last_test") if provider else None
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/pakasir/save", methods=["POST"])
@admin_required
def api_pakasir_save():
    """Save Pakasir configuration."""
    try:
        from config_manager import get_config_manager

        data = request.get_json() or {}
        api_key = data.get("api_key", "").strip()
        project = data.get("project", "").strip()

        if not api_key or not project:
            return jsonify({"ok": False, "error": "API Key dan Project Name wajib diisi"}), 400

        cm = get_config_manager()

        updates = {
            "PAKASIR_KEY": api_key,
            "PAKASIR_PROJECT": project
        }

        # Save to .env via ConfigManager
        cm.update_config(updates, backup=True)

        # Log configuration change
        _log_config_change("pakasir", "UPDATED")

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/pakasir/test", methods=["POST"])
@admin_required
def api_pakasir_test():
    """Test Pakasir configuration."""
    try:
        import pakasir

        # Check if configured
        if not pakasir.is_configured():
            return jsonify({
                "ok": False,
                "error": "Pakasir belum dikonfigurasi. Simpan credentials terlebih dahulu."
            }), 400

        # Validate by creating test payment URL
        test_order = f"TEST-{int(time.time())}"
        result = pakasir.create_qris(1000, test_order)

        if result and result.get("ok") and result.get("payment_url"):
            return jsonify({
                "ok": True,
                "message": "Konfigurasi Pakasir valid - URL pembayaran dapat dibuat"
            })
        else:
            return jsonify({
                "ok": False,
                "error": "Gagal membuat payment URL - periksa konfigurasi"
            })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Telegram Integration -----
@admin_bp.route("/telegram")
@admin_required
def telegram_integration():
    """Telegram Bot Integration."""
    return render_template("admin/telegram.html")


@admin_bp.route("/api/telegram/config", methods=["GET"])
@admin_required
def api_telegram_config():
    """Get Telegram configuration."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        provider = cm.get_provider("telegram")

        return jsonify({
            "ok": True,
            "is_configured": provider["is_configured"] if provider else False,
            "config": provider["config"] if provider else {},
            "last_test": provider.get("last_test") if provider else None
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/telegram/save", methods=["POST"])
@admin_required
def api_telegram_save():
    """Save Telegram configuration."""
    try:
        from config_manager import get_config_manager

        data = request.get_json() or {}
        bot_token = data.get("bot_token", "").strip()
        chat_id = data.get("chat_id", "").strip()

        if not bot_token or not chat_id:
            return jsonify({"ok": False, "error": "Bot Token dan Chat ID wajib diisi"}), 400

        cm = get_config_manager()

        updates = {
            "TELEGRAM_BOT_TOKEN": bot_token,
            "TELEGRAM_CHAT_ID": chat_id
        }

        # Save to .env via ConfigManager
        cm.update_config(updates, backup=True)

        # Log configuration change
        _log_config_change("telegram", "UPDATED")

        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/telegram/test", methods=["POST"])
@admin_required
def api_telegram_test():
    """Test Telegram bot connection."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")

        if not token:
            return jsonify({
                "ok": False,
                "error": "Telegram belum dikonfigurasi. Simpan bot token terlebih dahulu."
            }), 400

        # Test bot using getMe API
        url = f"https://api.telegram.org/bot{token}/getMe"

        response = requests.get(url, timeout=10)
        data = response.json()

        if data.get("ok") and data.get("result"):
            bot_info = data["result"]
            bot_username = bot_info.get("username", "Unknown")
            return jsonify({
                "ok": True,
                "message": f"Bot connected: @{bot_username}"
            })
        else:
            return jsonify({
                "ok": False,
                "error": "Bot token tidak valid atau bot tidak dapat diakses"
            })

    except requests.Timeout:
        return jsonify({"ok": False, "error": "Timeout: Telegram API tidak merespons"}), 500
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Health Monitor -----
@admin_bp.route("/health-monitor")
@admin_required
def health_monitor():
    """System Health Monitor."""
    return render_template("admin/health_monitor.html")


@admin_bp.route("/api/health", methods=["GET"])
@admin_required
def api_health():
    """Get system health status."""
    try:
        health = {}

        # 1. Application
        health["Application"] = {
            "status": "GREEN",
            "message": "Running"
        }

        # 2. Gunicorn (check if process exists)
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-f", "gunicorn"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                health["Gunicorn"] = {"status": "GREEN", "message": "Running"}
            else:
                health["Gunicorn"] = {"status": "RED", "message": "Not running"}
        except:
            health["Gunicorn"] = {"status": "YELLOW", "message": "Cannot check status"}

        # 3. Port 2100
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex(('127.0.0.1', 2100))
            sock.close()
            if result == 0:
                health["Port 2100"] = {"status": "GREEN", "message": "Listening"}
            else:
                health["Port 2100"] = {"status": "RED", "message": "Not listening"}
        except:
            health["Port 2100"] = {"status": "YELLOW", "message": "Cannot check"}

        # 4. Database
        try:
            conn = get_conn()
            conn.execute("SELECT 1").fetchone()
            conn.close()
            health["Database"] = {"status": "GREEN", "message": "Connected"}
        except Exception as e:
            health["Database"] = {"status": "RED", "message": "Connection failed", "details": str(e)[:50]}

        # 5. Digiflazz
        try:
            import digiflazz
            if digiflazz.is_configured():
                health["Digiflazz"] = {"status": "GREEN", "message": "Configured"}
            else:
                health["Digiflazz"] = {"status": "GRAY", "message": "Not configured"}
        except:
            health["Digiflazz"] = {"status": "GRAY", "message": "Not configured"}

        # 6. PaymentKita
        try:
            import paymentkita
            paymentkita.get_credentials()
            health["PaymentKita"] = {"status": "GREEN", "message": "Configured"}
        except:
            health["PaymentKita"] = {"status": "GRAY", "message": "Not configured"}

        # 7. Pakasir
        try:
            import pakasir
            if pakasir.is_configured():
                health["Pakasir"] = {"status": "GREEN", "message": "Configured"}
            else:
                health["Pakasir"] = {"status": "GRAY", "message": "Not configured"}
        except:
            health["Pakasir"] = {"status": "GRAY", "message": "Not configured"}

        # 8. Telegram
        try:
            token = os.getenv("TELEGRAM_BOT_TOKEN")
            if token:
                health["Telegram"] = {"status": "GREEN", "message": "Configured"}
            else:
                health["Telegram"] = {"status": "GRAY", "message": "Not configured"}
        except:
            health["Telegram"] = {"status": "GRAY", "message": "Not configured"}

        # 9. Firebase/FCM
        try:
            fcm_key = os.getenv("FCM_SERVER_KEY")
            if fcm_key:
                health["Firebase"] = {"status": "GREEN", "message": "Configured"}
            else:
                health["Firebase"] = {"status": "GRAY", "message": "Not configured"}
        except:
            health["Firebase"] = {"status": "GRAY", "message": "Not configured"}

        # 10. Cloudflare/cloudflared
        try:
            import subprocess
            result = subprocess.run(
                ["pgrep", "-f", "cloudflared"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                health["Cloudflare"] = {"status": "GREEN", "message": "Tunnel running"}
            else:
                health["Cloudflare"] = {"status": "YELLOW", "message": "Tunnel not running"}
        except:
            health["Cloudflare"] = {"status": "GRAY", "message": "Not installed"}

        return jsonify({
            "ok": True,
            "health": health
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Configuration Backup -----
@admin_bp.route("/config-backup")
@admin_required
def config_backup():
    """Configuration Backup Management."""
    return render_template("admin/config_backup.html")


@admin_bp.route("/api/config/backups", methods=["GET"])
@admin_required
def api_config_backups():
    """List available backups."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        backups = cm.list_backups()

        # Add file size to each backup
        for backup in backups:
            try:
                backup["size"] = os.path.getsize(backup["path"])
            except:
                backup["size"] = 0

        return jsonify({
            "ok": True,
            "backups": backups
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/config/backup", methods=["POST"])
@admin_required
def api_config_backup():
    """Create new backup."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()

        backup_file = cm.backup_env()

        # Log backup creation
        _log_config_change("system", "BACKUP_CREATED")

        return jsonify({
            "ok": True,
            "backup_file": backup_file,
            "message": "Backup created successfully"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/config/restore", methods=["POST"])
@admin_required
def api_config_restore():
    """Restore configuration from backup."""
    try:
        from config_manager import get_config_manager

        data = request.get_json() or {}
        backup_file = data.get("backup_file", "").strip()

        if not backup_file:
            return jsonify({"ok": False, "error": "Backup file required"}), 400

        cm = get_config_manager()

        # Restore from backup (security validation inside restore_backup)
        cm.restore_backup(backup_file)

        # Log restore
        _log_config_change("system", "BACKUP_RESTORED")

        return jsonify({
            "ok": True,
            "message": "Configuration restored successfully. Please restart application."
        })
    except ValueError as ve:
        return jsonify({"ok": False, "error": str(ve)}), 400
    except FileNotFoundError as fe:
        return jsonify({"ok": False, "error": str(fe)}), 404
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Configuration Log -----
@admin_bp.route("/config-log")
@admin_required
def config_log():
    """Configuration Change Log."""
    return render_template("admin/config_log.html")


@admin_bp.route("/api/config/logs", methods=["GET"])
@admin_required
def api_config_logs():
    """Get configuration change logs."""
    try:
        conn = get_conn()

        # Get filter parameters
        integration = request.args.get('integration', '')
        action = request.args.get('action', '')
        limit = int(request.args.get('limit', 100))

        # Build query
        query = "SELECT * FROM config_changes WHERE 1=1"
        params = []

        if integration:
            query += " AND integration = ?"
            params.append(integration)

        if action:
            query += " AND action = ?"
            params.append(action)

        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        logs = []

        for row in cursor.fetchall():
            logs.append({
                "id": row["id"],
                "timestamp": row["timestamp"],
                "admin_user": row["admin_user"],
                "integration": row["integration"],
                "action": row["action"]
            })

        conn.close()

        return jsonify({
            "ok": True,
            "logs": logs
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# ----- Helper function for config logging -----
def _log_config_change(integration, action):
    """Log configuration changes to database."""
    try:
        conn = get_conn()
        conn.execute("""
            INSERT INTO config_changes (timestamp, admin_user, integration, action)
            VALUES (datetime('now'), ?, ?, ?)
        """, (current_user.username, integration, action))
        conn.commit()
        conn.close()
    except:
        pass  # Silent fail - logging is not critical


# ==================== AUTO-TIER MARGIN MANAGEMENT ====================

@admin_bp.route("/auto-tier")
@admin_required
def auto_tier():
    """Auto-Tier Margin configuration page."""
    return render_template("admin/auto_tier.html")


@admin_bp.route("/api/auto-tier/config", methods=["GET"])
@admin_required
def api_auto_tier_config():
    """Get current Auto-Tier configuration."""
    try:
        from models import get_auto_tier_config
        config = get_auto_tier_config()

        # Count AUTO products (margin=0)
        conn = get_conn()
        auto_count = conn.execute("SELECT COUNT(*) as cnt FROM products WHERE margin=0").fetchone()["cnt"]
        manual_count = conn.execute("SELECT COUNT(*) as cnt FROM products WHERE margin>0").fetchone()["cnt"]
        conn.close()

        return jsonify({
            "ok": True,
            "config": config,
            "stats": {
                "auto_products": auto_count,
                "manual_products": manual_count
            }
        })
    except Exception as e:
        logger.error("Failed to get auto-tier config: %s", str(e), exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/auto-tier/save", methods=["POST"])
@admin_required
def api_auto_tier_save():
    """Save Auto-Tier configuration with validation."""
    try:
        data = request.get_json() or {}
        tiers = data.get("tiers", [])

        if not isinstance(tiers, list) or len(tiers) == 0:
            return jsonify({"ok": False, "error": "Minimal 1 tier diperlukan"}), 400

        # Validate each tier
        for i, tier in enumerate(tiers):
            tier_type = tier.get("type", "fixed")
            level = tier.get("level")
            tier_min = tier.get("min")
            tier_max = tier.get("max")

            # Type validation for common fields
            try:
                tier["level"] = int(level)
                tier["min"] = int(tier_min)

                # Max can be None/null for unlimited
                if tier_max is not None and tier_max != '':
                    tier["max"] = int(tier_max)
                else:
                    tier["max"] = None

            except (TypeError, ValueError):
                return jsonify({"ok": False, "error": f"Tier {i+1}: Level dan Min harus berupa angka"}), 400

            # Validate based on tier type
            if tier_type == "fixed":
                margin_member = tier.get("margin_member")
                margin_reseller = tier.get("margin_reseller")

                try:
                    tier["margin_member"] = int(margin_member)
                    tier["margin_reseller"] = int(margin_reseller)
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Margin harus berupa angka"}), 400

                # Value validation
                if tier["margin_member"] < 0:
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Margin Member tidak boleh negatif"}), 400
                if tier["margin_reseller"] < 0:
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Margin Reseller tidak boleh negatif"}), 400

            elif tier_type == "dynamic":
                # Validate dynamic tier parameters
                min_member = tier.get("min_member")
                percent_member = tier.get("percent_member")
                min_reseller = tier.get("min_reseller")
                percent_reseller = tier.get("percent_reseller")

                try:
                    tier["min_member"] = int(min_member)
                    tier["min_reseller"] = int(min_reseller)
                    tier["percent_member"] = float(percent_member)
                    tier["percent_reseller"] = float(percent_reseller)
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Parameter dynamic tier harus berupa angka"}), 400

                # Value validation
                if tier["min_member"] < 0:
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Min Member tidak boleh negatif"}), 400
                if tier["min_reseller"] < 0:
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Min Reseller tidak boleh negatif"}), 400
                if tier["percent_member"] < 0 or tier["percent_member"] > 1:
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Percent Member harus antara 0 dan 1"}), 400
                if tier["percent_reseller"] < 0 or tier["percent_reseller"] > 1:
                    return jsonify({"ok": False, "error": f"Tier {i+1}: Percent Reseller harus antara 0 dan 1"}), 400

            # Common validation
            if tier["min"] < 0:
                return jsonify({"ok": False, "error": f"Tier {i+1}: Min tidak boleh negatif"}), 400
            if tier["max"] is not None and tier["max"] < tier["min"]:
                return jsonify({"ok": False, "error": f"Tier {i+1}: Max harus >= Min"}), 400

        # Sort by min price
        tiers_sorted = sorted(tiers, key=lambda t: t["min"])

        # Check for gaps and overlaps (only for non-unlimited tiers)
        for i in range(len(tiers_sorted) - 1):
            current_max = tiers_sorted[i]["max"]
            next_min = tiers_sorted[i+1]["min"]

            # Skip overlap check if current tier is unlimited
            if current_max is None:
                continue

            if next_min <= current_max:
                return jsonify({
                    "ok": False,
                    "error": f"Tier overlap detected: Tier {i+1} max ({current_max}) >= Tier {i+2} min ({next_min})"
                }), 400

        # Re-number levels sequentially
        for i, tier in enumerate(tiers_sorted):
            tier["level"] = i + 1
        for i in range(len(tiers_sorted) - 1):
            current_max = tiers_sorted[i]["max"]
            next_min = tiers_sorted[i+1]["min"]

            if next_min <= current_max:
                return jsonify({
                    "ok": False,
                    "error": f"Tier overlap detected: Tier {i+1} max ({current_max}) >= Tier {i+2} min ({next_min})"
                }), 400

        # Re-number levels sequentially
        for i, tier in enumerate(tiers_sorted):
            tier["level"] = i + 1

        # Save to settings table
        config = {"tiers": tiers_sorted}
        conn = get_conn()
        try:
            existing = conn.execute("SELECT id FROM settings WHERE key='auto_tier_config'").fetchone()
            if existing:
                conn.execute("UPDATE settings SET value=? WHERE key='auto_tier_config'", (json.dumps(config),))
            else:
                conn.execute("INSERT INTO settings (key, value) VALUES ('auto_tier_config', ?)", (json.dumps(config),))
            conn.commit()
        finally:
            conn.close()

        logger.info("Auto-Tier config saved by %s: %d tiers", current_user.username, len(tiers_sorted))

        return jsonify({"ok": True, "message": f"Rumus {len(tiers_sorted)} tier berhasil disimpan"})

    except Exception as e:
        logger.error("Failed to save auto-tier config: %s", str(e), exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@admin_bp.route("/api/auto-tier/apply", methods=["POST"])
@admin_required
def api_auto_tier_apply():
    """Apply Auto-Tier calculation to all AUTO products (margin=0)."""
    try:
        from models import get_auto_tier_config, hitung_harga_final

        # Get current tier config
        config = get_auto_tier_config()
        tiers = config.get("tiers", [])

        if len(tiers) == 0:
            return jsonify({"ok": False, "error": "Tidak ada konfigurasi tier"}), 400

        conn = get_conn()

        # Get all AUTO products (margin=0)
        auto_products = conn.execute("""
            SELECT id, sku, base_price, margin
            FROM products
            WHERE margin = 0
        """).fetchall()

        total_checked = len(auto_products)
        updated = 0
        skipped = 0
        no_tier = 0
        failed = 0

        for product in auto_products:
            try:
                prod_id = product["id"]
                base_price = int(product["base_price"] or 0)

                # Find matching tier
                found_tier = False
                for tier in tiers:
                    tier_min = int(tier.get("min", 0))
                    tier_max = int(tier.get("max", 0))

                    if tier_min <= base_price <= tier_max:
                        found_tier = True
                        # IMPORTANT: Keep margin=0 to maintain AUTO indicator
                        # Only update the 'price' field (sell price for reguler)
                        margin_member = int(tier.get("margin_member", 0))
                        new_price = base_price + margin_member

                        conn.execute("""
                            UPDATE products
                            SET price = ?,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (new_price, prod_id))

                        updated += 1
                        break

                if not found_tier:
                    no_tier += 1

            except Exception as e:
                logger.warning("Failed to apply tier to product ID %s: %s", prod_id, str(e))
                failed += 1
                continue

        conn.commit()
        conn.close()

        logger.info("Auto-Tier applied by %s: %d updated, %d skipped, %d no tier, %d failed",
                    current_user.username, updated, skipped, no_tier, failed)

        return jsonify({
            "ok": True,
            "stats": {
                "total_checked": total_checked,
                "updated": updated,
                "skipped_manual": skipped,
                "no_tier_match": no_tier,
                "failed": failed
            }
        })

    except Exception as e:
        logger.error("Failed to apply auto-tier: %s", str(e), exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
