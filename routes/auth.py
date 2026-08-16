"""Authentication routes: login, register, logout, Google OAuth."""
import os
from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user

from models import get_user_by_username, get_user_by_email, get_user_by_google_id, create_user
from oauth import oauth, is_google_configured

import bot_helper
auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    # Apply rate limiting: 5 attempts per minute per IP
    limiter = getattr(current_app, 'limiter', None)
    if limiter:
        limiter.limit("5 per minute")(login)
    
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard" if current_user.role == "user" else "admin.dashboard"))
    if request.method == "POST":
        data = request.get_json() if request.is_json else request.form
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        
        user = get_user_by_username(username)
        if not user or not user.check_password(password):
            return jsonify({"ok": False, "error": "Username atau password salah"}), 401
        
        # LOGIKA KEAGENAN: Cek Status Persetujuan
        # (Gunakan hasattr untuk keamanan jika DB lama belum terupdate sempurna)
        if hasattr(user, 'status') and user.status != 'active':
            return jsonify({"ok": False, "error": "Akun Anda sedang direview oleh Admin."}), 403

        login_user(user, remember=True)
        next_url = url_for("admin.dashboard") if user.role == "admin" else url_for("user.dashboard")
        return jsonify({"ok": True, "redirect": next_url})
    return render_template(
        "auth/login.html",
        google_enabled=is_google_configured(),
        admin_wa=os.getenv("ADMIN_WA_NUMBER", "6281234567890"),
    )


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    # Apply rate limiting: 10 attempts per hour per IP
    limiter = getattr(current_app, 'limiter', None)
    if limiter:
        limiter.limit("10 per hour")(register)
    
    if current_user.is_authenticated:
        return redirect(url_for("user.dashboard"))
    if request.method == "POST":
        data = request.get_json() if request.is_json else request.form
        username = (data.get("username") or "").strip()
        email = f"{username}@garudatel.my.id"
        password = data.get("password") or ""
        whatsapp = (data.get("whatsapp") or "").strip()
        
        if len(username) < 3:
            return jsonify({"ok": False, "error": "Username minimal 3 karakter"}), 400
        if len(password) < 6:
            return jsonify({"ok": False, "error": "Password minimal 6 karakter"}), 400
        if len(whatsapp) < 9:
            return jsonify({"ok": False, "error": "Nomor WhatsApp tidak valid"}), 400
        if get_user_by_username(username):
            return jsonify({"ok": False, "error": "Username sudah terdaftar"}), 400
            
        from models import create_user, get_conn
        # 1. Gunakan mesin bawaan web agar tidak error masalah kolom database
        user = create_user(username=username, password=password, email=email, role="user", balance=0)
        
        # 2. Get the generated PIN for this user
        conn = get_conn()
        user_data = conn.execute("SELECT pin FROM users WHERE id=?", (user.id,)).fetchone()
        generated_pin = user_data["pin"] if user_data else "UNKNOWN"
        
        # 3. Cek status auto-approve dari database settings
        try:
            auto_app = conn.execute("SELECT value FROM settings WHERE key='auto_approve'").fetchone()
            is_auto = True if (auto_app and auto_app[0] == '1') else False
        except:
            is_auto = False
            
        new_status = 'active' if is_auto else 'pending'
        
        conn.execute("UPDATE users SET whatsapp=?, status=? WHERE username=?", (whatsapp, new_status, username))
        conn.commit()
        conn.close()
        
        # 4. Kirim Notifikasi (Hanya Jika Pending/Saklar OFF)
        if not is_auto:
            try:
                import bot_helper
                bot_helper.send_approval_notif(username, email or "Tidak ada", whatsapp, request.host_url)
            except:
                pass
            msg = f"Pendaftaran berhasil! Tunggu persetujuan Admin. PIN transaksi Anda: {generated_pin} (WAJIB DIGANTI saat transaksi pertama)"
        else:
            msg = f"Pendaftaran berhasil! Akun langsung aktif. PIN transaksi Anda: {generated_pin} (WAJIB DIGANTI saat transaksi pertama)"
            
        return jsonify({"ok": True, "redirect": url_for("auth.login"), "msg": msg, "pin": generated_pin})
    return render_template("auth/register.html", google_enabled=is_google_configured())
@auth_bp.route("/logout", methods=["POST", "GET"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/login/google")
def login_google():
    if not is_google_configured():
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@auth_bp.route("/login/callback")
def google_callback():
    if not is_google_configured():
        return redirect(url_for("auth.login"))
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        return redirect(url_for("auth.login"))
    userinfo = token.get("userinfo") or {}
    google_id = userinfo.get("sub")
    email = userinfo.get("email")
    name = userinfo.get("name") or (email.split("@")[0] if email else None)
    if not google_id:
        return redirect(url_for("auth.login"))

    user = get_user_by_google_id(google_id)
    if not user and email:
        user = get_user_by_email(email)
    if not user:
        # Generate unique username
        base = (name or "user").replace(" ", "").lower()[:20] or "user"
        candidate = base
        i = 1
        while get_user_by_username(candidate):
            candidate = f"{base}{i}"
            i += 1
        user = create_user(
            username=candidate, password=None, email=email,
            google_id=google_id, role="user", balance=0,
        )
    login_user(user, remember=True)
    target = url_for("admin.dashboard") if user.role == "admin" else url_for("user.dashboard")
    return redirect(target)

@auth_bp.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.get_json() or {}
    username_req = (data.get("username") or "").strip()
    wa = (data.get("whatsapp") or "").strip()
    
    from models import get_conn
    conn = get_conn()
    user = conn.execute("SELECT username FROM users WHERE username=? AND whatsapp=?", (username_req, wa)).fetchone()
    conn.close()
    
    if user:
        admin_wa = os.getenv("ADMIN_WA_NUMBER", "6281234567890")
        from urllib.parse import quote
        text = f"Halo Bos, saya lupa password akun PayPoint saya.\n\n👤 Username: *{user['username']}*\n📱 WA: *{wa}*\n\nMohon bantu reset password saya."
        link = f"whatsapp://send?phone={admin_wa}&text={quote(text)}"
        return jsonify({"ok": True, "link": link})
        
    return jsonify({"ok": False, "error": "Verifikasi Gagal: Username atau No WA salah!"}), 400

@auth_bp.route('/manifest.json')
def serve_manifest():
    from flask import send_from_directory
    return send_from_directory('static', 'manifest.json', mimetype='application/manifest+json')

@auth_bp.route('/sw.js')
def serve_sw():
    from flask import send_from_directory
    return send_from_directory('static', 'sw.js', mimetype='application/javascript')

@auth_bp.route("/privacy")
def privacy_policy():
    return render_template("privacy.html")


@auth_bp.route("/update-fcm-token", methods=["POST"])
@login_required
def update_fcm_token():
    data = request.get_json() or {}
    token = data.get("token")
    if not token:
        return jsonify({"ok": False, "error": "Token tidak ditemukan"}), 400
    
    from models import get_conn
    conn = get_conn()
    try:
        # Cerdas: Sistem otomatis membuat kolom fcm_token jika database versi lama belum punya
        try:
            conn.execute("ALTER TABLE users ADD COLUMN fcm_token TEXT")
        except Exception:
            pass # Lanjut jika kolom sudah ada
        
        # Simpan token ke profil agen yang sedang login
        conn.execute("UPDATE users SET fcm_token=? WHERE id=?", (token, current_user.id))
        conn.commit()
        return jsonify({"ok": True, "msg": "Alamat HP Agen Berhasil Disimpan!"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        conn.close()



@auth_bp.route('/firebase-messaging-sw.js')
def serve_firebase_sw():
    from flask import send_from_directory
    return send_from_directory('static', 'firebase-messaging-sw.js', mimetype='application/javascript')

