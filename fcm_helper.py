"""Firebase Cloud Messaging Helper - Broadcast notification dan token management.

Refactored untuk menggunakan ConfigManager sebagai single source of truth.
"""
import os
import firebase_admin
from firebase_admin import credentials, messaging
from models import get_conn


def _get_firebase_config():
    """Get Firebase configuration dari ConfigManager atau fallback ke file."""
    try:
        from config_manager import get_config_manager
        cm = get_config_manager()
        
        # Check apakah Firebase dikonfigurasi via .env
        firebase_config = cm.get_provider("firebase")
        if firebase_config and firebase_config.get("is_configured"):
            # Firebase configured via .env (future enhancement)
            # For now, fallback to credentials file
            pass
    except Exception:
        pass
    
    # Default: gunakan firebase_credentials.json
    cred_path = os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
    if os.path.exists(cred_path):
        return cred_path
    
    return None


def is_configured():
    """Check apakah Firebase sudah dikonfigurasi."""
    cred_path = _get_firebase_config()
    return cred_path is not None and os.path.exists(cred_path)


def initialize_firebase():
    """Initialize Firebase Admin SDK."""
    if firebase_admin._apps:
        return True  # Already initialized
    
    cred_path = _get_firebase_config()
    if not cred_path:
        print("⚠️ Firebase credentials tidak ditemukan")
        return False
    
    try:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
        print("✅ Mesin Firebase Siap!")
        return True
    except Exception as e:
        print(f"⚠️ Gagal menyalakan Firebase: {e}")
        return False


def get_registered_tokens():
    """Get semua FCM token yang terdaftar dari database.
    
    Returns:
        List of dict dengan info: user_id, username, fcm_token
    """
    conn = get_conn()
    try:
        users = conn.execute(
            "SELECT id, username, fcm_token FROM users WHERE fcm_token IS NOT NULL AND fcm_token != ''"
        ).fetchall()
        
        return [
            {
                "user_id": user["id"],
                "username": user["username"],
                "fcm_token": user["fcm_token"]
            }
            for user in users
        ]
    except Exception as e:
        print(f"Error getting registered tokens: {e}")
        return []
    finally:
        conn.close()


def validate_tokens(tokens):
    """Validate FCM tokens dengan dry run.
    
    Args:
        tokens: List of FCM tokens
        
    Returns:
        Dict with valid_count and invalid_tokens list
    """
    if not tokens:
        return {"valid_count": 0, "invalid_tokens": []}
    
    if not initialize_firebase():
        return {"valid_count": 0, "invalid_tokens": tokens}
    
    # Test dengan dry run message
    try:
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title="Test",
                body="Validation test"
            ),
            tokens=tokens[:100] if len(tokens) > 100 else tokens  # Max 100 per batch
        )
        
        # Send dengan dry_run=True (tidak benar-benar kirim)
        response = messaging.send_multicast(message, dry_run=True)
        
        invalid_tokens = []
        for idx, resp in enumerate(response.responses):
            if not resp.success:
                invalid_tokens.append(tokens[idx])
        
        return {
            "valid_count": response.success_count,
            "invalid_tokens": invalid_tokens
        }
    except Exception as e:
        print(f"Token validation error: {e}")
        return {"valid_count": 0, "invalid_tokens": []}


def send_broadcast_notification(title, body):
    """Fungsi untuk meledakkan notifikasi ke semua agen.
    
    Args:
        title: Judul notifikasi
        body: Isi notifikasi
        
    Returns:
        Tuple (success_count, failure_count)
    """
    if not initialize_firebase():
        return 0, 0
    
    conn = get_conn()
    try:
        # Cari semua agen yang punya FCM token
        users = conn.execute(
            "SELECT fcm_token FROM users WHERE fcm_token IS NOT NULL AND fcm_token != ''"
        ).fetchall()
        tokens = [user['fcm_token'] for user in users]
        
        if not tokens:
            print("⚠️ Tidak ada device terdaftar untuk broadcast")
            return 0, 0
        
        print(f"📢 Broadcasting ke {len(tokens)} device...")
        
        # Siapkan Peluru Notifikasi untuk Web/Android
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            webpush=messaging.WebpushConfig(
                notification=messaging.WebpushNotification(
                    title=title,
                    body=body,
                    icon='/static/img/logo.png',
                    require_interaction=True,
                    vibrate=[200, 100, 200]
                ),
                fcm_options=messaging.WebpushFCMOptions(
                    link='/'
                )
            ),
            tokens=tokens,
        )
        
        # TEMBAK!
        response = messaging.send_multicast(message)
        
        print(f"✅ Broadcast selesai: {response.success_count} sukses, {response.failure_count} gagal")
        
        # Clean up invalid tokens
        if response.failure_count > 0:
            _cleanup_invalid_tokens(tokens, response)
        
        return response.success_count, response.failure_count
        
    except Exception as e:
        print(f"❌ FCM Broadcast Error: {e}")
        import traceback
        traceback.print_exc()
        return 0, 0
    finally:
        conn.close()


def _cleanup_invalid_tokens(tokens, response):
    """Remove invalid FCM tokens dari database."""
    try:
        conn = get_conn()
        invalid_tokens = []
        
        for idx, resp in enumerate(response.responses):
            if not resp.success:
                error_code = resp.exception.code if resp.exception else None
                # Remove token jika invalid/unregistered
                if error_code in ['invalid-argument', 'registration-token-not-registered']:
                    invalid_tokens.append(tokens[idx])
        
        if invalid_tokens:
            placeholders = ','.join(['?'] * len(invalid_tokens))
            conn.execute(
                f"UPDATE users SET fcm_token = NULL WHERE fcm_token IN ({placeholders})",
                invalid_tokens
            )
            conn.commit()
            print(f"🧹 Cleaned up {len(invalid_tokens)} invalid tokens")
        
        conn.close()
    except Exception as e:
        print(f"Error cleaning up tokens: {e}")


# Initialize on module load
initialize_firebase()
