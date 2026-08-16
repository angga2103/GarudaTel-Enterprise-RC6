"""GARUDA TELL PPOB Auto-Pilot — Flask Application Entry."""
import os
from flask import Flask, redirect, url_for
from flask_login import LoginManager, current_user
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv

from models import init_db, get_user_by_id
from routes.auth import auth_bp
from routes.user import user_bp
from routes.admin import admin_bp
from routes.api import api_bp
from oauth import init_oauth

load_dotenv()


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    secret = os.getenv("SECRET_KEY")
    if not secret:
        # Generate a per-process random secret if none provided. This invalidates
        # sessions on restart — set SECRET_KEY in .env for stable sessions.
        import secrets as _secrets
        secret = _secrets.token_hex(32)
        if os.getenv("FLASK_DEBUG", "0") != "1":
            print("WARNING: SECRET_KEY not set — using a random per-process value. "
                  "Sessions will not survive restarts. Set SECRET_KEY in .env for production.")
    app.config["SECRET_KEY"] = secret
    # SESSION_COOKIE_SECURE: enable in production (HTTPS required)
    # Default "0" agar login via http://IP:2100 berhasil (cookie tidak di-block).
    # Set SESSION_COOKIE_SECURE=1 di .env hanya jika deploy sudah pakai HTTPS/Cloudflare.
    app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Session lifetime (7 days) + max content size (1 MB) — DoS guard
    from datetime import timedelta as _td
    app.config["PERMANENT_SESSION_LIFETIME"] = _td(days=7)
    app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
    app.config["SESSION_COOKIE_NAME"] = "paypoint_sess"
    # Refuse to start in production with the dev-fallback random key
    if os.getenv("FLASK_ENV") == "production" and not os.getenv("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set in production .env")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    
    # Enable CSRF protection
    csrf = CSRFProtect(app)
    
    # Exempt webhook endpoints from CSRF (external callbacks)
    csrf.exempt("routes.api.pakasir_callback")
    csrf.exempt("routes.api.paymentkita_callback")
    csrf.exempt("routes.api.digiflazz_callback")
    
    # Enable rate limiting
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    limiter = Limiter(
        get_remote_address,
        app=app,
        default_limits=[],  # No default limits, apply per-route
        storage_uri="memory://"
    )
    # Make limiter accessible to blueprints
    app.limiter = limiter

    init_db()

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Silakan masuk untuk melanjutkan."
    login_manager.login_message_category = "warning"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(int(user_id))

    init_oauth(app)

    


    @app.context_processor
    def inject_promo_settings():
        min_depo = 100000
        try:
            from models import get_conn
            conn = get_conn()
            res = conn.execute("SELECT value FROM settings WHERE key='min_depo_reseller'").fetchone()
            if res: min_depo = int(res['value'])
            conn.close()
        except: pass
        return dict(min_depo_reseller=min_depo)

    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api")

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            if current_user.role == "admin":
                return redirect(url_for("admin.dashboard"))
            return redirect(url_for("user.dashboard"))
        return redirect(url_for("auth.login"))

    @app.context_processor
    def inject_globals():
        from flask_login import current_user
        app_name = "GARUDA TELL"
        if current_user.is_authenticated and hasattr(current_user, 'store_name') and current_user.store_name:
            app_name = current_user.store_name.upper()
            
        return {
            "ADMIN_WA_NUMBER": os.getenv("ADMIN_WA_NUMBER", "6281234567890"),
            "APP_NAME": app_name,
        }

    return app


app = create_app()



# --- JALUR HELPDESK GARUDA TELL ---
@app.route('/user/tiket/buat', methods=['POST'])
def buat_tiket():
    from flask import request, jsonify, session
    import requests
    from models import get_conn
    import os
    
    try:
        data = request.json
        order_id = data.get('order_id', '-')
        kendala = data.get('jenis_kendala', '-')
        pesan = data.get('pesan', '-')
        
        # Mengambil info agen menggunakan flask_login
        from flask_login import current_user
        if current_user.is_authenticated:
            user_id = str(getattr(current_user, 'id', 'Unknown'))
            user_name = getattr(current_user, 'username', f"Agen-{user_id}")
            user_phone = getattr(current_user, 'email', '-') # Biasanya kontak disimpan di email/phone
        else:
            user_id = 'Unknown'
            user_name = 'Agen-Unknown'
            user_phone = '-'

        # 1. Simpan ke Database
        conn = get_conn()
        conn.execute('''
            INSERT INTO tickets (user_id, ticket_type, order_id, message)
            VALUES (?, 'transaksi', ?, ?)
        ''', (str(user_id), order_id, f"KENDALA: {kendala}\nPESAN: {pesan}"))
        conn.commit()

        # 2. Kirim ke Telegram Bos Mas Ansor
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not bot_token or not chat_id:
            print("WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
            return jsonify({"ok": True})  # Still succeed ticket creation
        
        msg = f"🦅 *[ SISTEM WEB GARUDA TELL ]* 🦅\n"
        msg += f"🚨 *KOMPLAIN TRANSAKSI BARU*\n\n"
        msg += f"👤 *Agen:* {user_name} ({user_phone})\n"
        msg += f"🆔 *Order ID:* `{order_id}`\n"
        msg += f"⚠️ *Kendala:* {kendala}\n"
        msg += f"💬 *Pesan Agen:* {pesan}\n\n"
        msg += f"💡 _Aksi: Silakan cek Database/Panel Admin untuk membalas._"

        requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json={
            "chat_id": chat_id,
            "text": msg,
            "parse_mode": "Markdown"
        }, timeout=5)

        return jsonify({"ok": True})
    except Exception as e:
        print("Error Helpdesk:", e)
        return jsonify({"ok": False, "error": str(e)}), 500



# --- COLOKAN FLASHDISK HELPDESK ---
try:
    from helpdesk import helpdesk_bp
    app.register_blueprint(helpdesk_bp)
except Exception as e: pass
# ----------------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", "2100"))
    # Default to non-debug (production-safe). Set FLASK_DEBUG=1 only locally.
    app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")
