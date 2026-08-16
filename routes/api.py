"""Lightweight JSON helpers + Pakasir webhook (public, signature-verified)."""
import logging
import os
import hashlib

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from paymentkita import verify_callback as verify_pk
from digiflazz import is_configured as digiflazz_configured, credential_hint
from oauth import is_google_configured
from pakasir import is_configured as pakasir_configured, verify_callback
from models import (
    get_admin_stats,
    get_topup,
    mark_topup_paid,
    create_transaction,
    get_user_by_id,
    get_conn,
)

api_bp = Blueprint("api", __name__)
log = logging.getLogger("paypoint.pakasir")


@api_bp.route("/health")
def health():
    return jsonify({"status": "ok"})


@api_bp.route("/me")
@login_required
def me():
    return jsonify({
        "id": current_user.id,
        "username": current_user.username,
        "email": current_user.email,
        "balance": current_user.balance,
        "role": current_user.role,
    })


@api_bp.route("/system-status")
@login_required
def system_status():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403

    stats = get_admin_stats()
    return jsonify({
        "digiflazz": {
            "configured": digiflazz_configured(),
            "hint": credential_hint(),
        },
        "google": {
            "configured": is_google_configured(),
        },
        "pakasir": {
            "configured": pakasir_configured(),
        },
        "stats": stats,
    })


@api_bp.route("/callback/pakasir", methods=["POST"])
def pakasir_callback():
    """Receive Pakasir webhook. Idempotent. Signature-verified."""
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    query_key = request.args.get("api_key", "")

    ok, reason = verify_callback(payload, query_api_key=query_key)
    if not ok:
        log.warning(
            "Pakasir callback rejected: %s | order=%s",
            reason,
            payload.get("order_id"),
        )
        return jsonify({"ok": False, "error": reason}), 400

    order_id = str(payload.get("order_id", "")).strip()
    if not order_id:
        return jsonify({"ok": False, "error": "order_id kosong"}), 400

    try:
        amount_in = int(payload.get("amount") or 0)
    except (TypeError, ValueError):
        amount_in = 0

    topup = get_topup(order_id)
    if not topup:
        log.warning("Pakasir callback unknown order_id=%s", order_id)
        return jsonify({"ok": False, "error": "Order tidak ditemukan"}), 404

    if amount_in and int(topup["amount"]) != amount_in:
        log.error(
            "Pakasir amount mismatch order=%s expected=%s got=%s",
            order_id, topup["amount"], amount_in
        )
        return jsonify({"ok": False, "error": "Amount mismatch"}), 400

    # mark_topup_paid() = sumber kebenaran atomik
    paid_row = mark_topup_paid(order_id)
    if not paid_row:
        # Replay callback / sudah paid sebelumnya
        fresh = get_topup(order_id)
        current_balance = None
        if fresh:
            u = get_user_by_id(fresh["uid"])
            current_balance = u.balance if u else None

        log.info("Pakasir callback duplicate/already-paid order=%s", order_id)
        return jsonify({
            "ok": True,
            "status": "already_paid",
            "order_id": order_id,
            "amount": topup["amount"],
            "new_balance": current_balance,
        })

    # Pastikan transaksi topup hanya tercatat sekali
    conn = get_conn()
    try:
        existing_tx = conn.execute(
            "SELECT id FROM transactions WHERE order_id=? LIMIT 1",
            (order_id,),
        ).fetchone()

        if not existing_tx:
            create_transaction(
                order_id=order_id,
                uid=topup["uid"],
                sku="TOPUP",
                name="Top Up Saldo (QRIS)",
                target=str(topup["uid"]),
                price=topup["amount"],
                kind="topup",
                status="success",
            )
    finally:
        conn.close()

    fresh_user = get_user_by_id(topup["uid"])
    new_balance = fresh_user.balance if fresh_user else None

    log.info(
        "Pakasir top-up settled order=%s uid=%s amount=%s",
        order_id, topup["uid"], topup["amount"]
    )
    return jsonify({
        "ok": True,
        "status": "paid",
        "order_id": order_id,
        "amount": topup["amount"],
        "new_balance": new_balance,
    })


@api_bp.route("/tg-approve")
def tg_approve():
    username = request.args.get("u")
    sign = request.args.get("sign")
    action = request.args.get("action")

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    valid_sign = hashlib.md5((str(username) + token).encode()).hexdigest()

    if not sign or sign != valid_sign:
        return "Tautan Tidak Valid atau Kadaluarsa", 403

    conn = get_conn()
    try:
        if action == "approve":
            conn.execute(
                "UPDATE users SET status='active' WHERE username=?",
                (username,)
            )
            msg = f"✅ AGEN {username.upper()} BERHASIL DIIZINKAN!"
            desc = "Agen sekarang sudah bisa login dan Top Up."
            color = "#10b981"

        elif action == "reject":
            conn.execute(
                "DELETE FROM users WHERE username=? AND status='pending'",
                (username,)
            )
            msg = f"❌ AGEN {username.upper()} DITOLAK!"
            desc = "Data pendaftaran telah dihapus dari sistem."
            color = "#f43f5e"

        else:
            msg = "Aksi tidak dikenal"
            desc = ""
            color = "#64748b"

        conn.commit()
    finally:
        conn.close()

    return f"""
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
          body {{
            font-family: system-ui, sans-serif;
            text-align: center;
            padding: 20px;
            background: #f8fafc;
          }}
          .card {{
            background: white;
            padding: 30px 20px;
            border-radius: 16px;
            box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
            margin-top: 15vh;
            border-top: 5px solid {color};
          }}
        </style>
      </head>
      <body>
        <div class="card">
          <h2 style="color: {color}; margin-top: 0;">{msg}</h2>
          <p style="color: #64748b; font-weight: 500;">{desc}</p>
          <p style="margin-top: 40px; font-size: 12px; color: #94a3b8;">
            Halaman ini aman. Silakan tutup dan kembali ke Telegram.
          </p>
        </div>
      </body>
    </html>
    """


@api_bp.route("/callback/paymentkita", methods=["POST"])
def paymentkita_callback():
    """Pintu masuk khusus untuk sinyal lunas dari PaymentKita."""
    payload = request.get_json(silent=True) or request.form.to_dict() or {}

    # Verifikasi signature callback
    is_valid, msg = verify_pk(payload)
    if not is_valid:
        log.warning("PaymentKita callback ditolak: %s", msg)
        return jsonify({"ok": False, "error": msg}), 400

    order_id = str(payload.get("reff_id") or payload.get("ref_id") or "").strip()
    if not order_id:
        return jsonify({"ok": False, "error": "reff_id kosong"}), 400

    topup = get_topup(order_id)
    if not topup:
        return jsonify({"ok": False, "error": "Order tidak ditemukan"}), 404

    # Ambil nominal callback jika ada, lalu cocokkan dengan nominal order lokal
    amount_in = 0
    for key in ("nominal", "amount", "total", "gross_amount"):
        raw = payload.get(key)
        if raw not in (None, ""):
            try:
                amount_in = int(float(str(raw).replace(",", "").strip()))
                break
            except Exception:
                pass

    if amount_in and int(topup["amount"]) != amount_in:
        log.error(
            "PaymentKita amount mismatch order=%s expected=%s got=%s",
            order_id, topup["amount"], amount_in
        )
        return jsonify({"ok": False, "error": "Amount mismatch"}), 400

    # Kalau status lokal sudah paid, cukup jawab sukses
    if topup["status"] == "paid":
        return jsonify({"status": True})

    paid_row = mark_topup_paid(order_id)
    if not paid_row:
        # Sudah diproses thread/request lain
        return jsonify({"status": True})

    # Pastikan transaksi topup tercatat sekali saja
    conn = get_conn()
    try:
        existing_tx = conn.execute(
            "SELECT id FROM transactions WHERE order_id=? LIMIT 1",
            (order_id,),
        ).fetchone()

        if not existing_tx:
            create_transaction(
                order_id=order_id,
                uid=topup["uid"],
                sku="TOPUP",
                name="Top Up Saldo (QRIS)",
                target=str(topup["uid"]),
                price=topup["amount"],
                kind="topup",
                status="success",
            )
    finally:
        conn.close()

    fresh_user = get_user_by_id(topup["uid"])
    new_balance = fresh_user.balance if fresh_user else None

    log.info(
        "PaymentKita topup settled order=%s uid=%s amount=%s balance=%s",
        order_id, topup["uid"], topup["amount"], new_balance
    )
    return jsonify({"status": True})


# === DIGIFLAZZ WEBHOOK ===
@api_bp.route("/callback/digiflazz", methods=["POST"])
def digiflazz_callback():
    """Receive Digiflazz webhook for async transaction status updates."""
    # Get payload from Digiflazz
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    
    # Log incoming webhook for debugging
    log.info("Digiflazz webhook received: %s", json.dumps(payload)[:500])
    
    # Extract transaction data
    data = payload.get("data", {})
    ref_id = str(data.get("ref_id", "")).strip()
    status = str(data.get("status", "")).strip().lower()
    sn = data.get("sn", "")
    message = data.get("message", "")
    
    if not ref_id:
        log.warning("Digiflazz webhook missing ref_id")
        return jsonify({"ok": False, "error": "ref_id required"}), 400
    
    # Find transaction
    from models import get_conn, force_credit_balance
    conn = get_conn()
    try:
        tx = conn.execute(
            "SELECT id, uid, price, status FROM transactions WHERE order_id = ?",
            (ref_id,)
        ).fetchone()
        
        if not tx:
            log.warning("Digiflazz webhook unknown ref_id: %s", ref_id)
            return jsonify({"ok": False, "error": "Transaction not found"}), 404
        
        current_status = tx["status"]
        uid = tx["uid"]
        price = tx["price"]
        
        # Check if already processed
        if current_status in ["success", "failed"]:
            log.info("Digiflazz webhook duplicate for ref_id=%s status=%s", ref_id, current_status)
            return jsonify({"ok": True, "status": current_status})
        
        # Update transaction based on Digiflazz status
        if status in ["sukses", "success"]:
            # Transaction succeeded
            conn.execute(
                "UPDATE transactions SET status = 'success', sn = ?, message = ? WHERE order_id = ?",
                (sn, message, ref_id)
            )
            log.info("Digiflazz webhook success: ref_id=%s sn=%s", ref_id, sn)
            
        elif status in ["gagal", "failed"]:
            # Transaction failed - refund balance
            conn.execute(
                "UPDATE transactions SET status = 'failed', message = ? WHERE order_id = ?",
                (message, ref_id)
            )
            conn.commit()  # Commit before refund to avoid deadlock
            
            # Refund user balance
            refunded = force_credit_balance(uid, price)
            log.info("Digiflazz webhook failed: ref_id=%s refunded=%s", ref_id, refunded)
            
        elif status == "pending":
            # Keep as pending
            conn.execute(
                "UPDATE transactions SET message = ? WHERE order_id = ?",
                (message, ref_id)
            )
            log.info("Digiflazz webhook pending: ref_id=%s", ref_id)
            
        else:
            # Unknown status
            conn.execute(
                "UPDATE transactions SET message = ? WHERE order_id = ?",
                (f"Unknown status from Digiflazz: {status}", ref_id)
            )
            log.warning("Digiflazz webhook unknown status: ref_id=%s status=%s", ref_id, status)
        
        conn.commit()
        return jsonify({"ok": True, "status": status})
        
    except Exception as e:
        log.error("Digiflazz webhook error: %s", str(e))
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()