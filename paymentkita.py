import requests
import hashlib
import hmac
import time

def get_credentials():
    import os
    merchant = os.getenv("PAYMENTKITA_MERCHANT")
    secret = os.getenv("PAYMENTKITA_SECRET")
    
    if not merchant or not secret:
        raise ValueError(
            "PaymentKita credentials tidak ditemukan. "
            "Pastikan PAYMENTKITA_MERCHANT dan PAYMENTKITA_SECRET "
            "sudah di-set di file .env"
        )
    
    return merchant, secret

def create_qris_paymentkita(ref_id, nominal):
    merchant, secret = get_credentials()
    base_url = "https://api.paymentkita.com/v1/order"
    
    payload = {
        "merchant": merchant,
        "secret": secret,
        "ref_id": ref_id,
        "nominal": nominal,
        "metode": "QRISREALTIME"
    }
    
    headers = {"User-Agent": "GarudaTell-Server/2.0", "Accept": "application/json"}
    
    try:
        response = requests.get(base_url, params=payload, headers=headers, timeout=15)
        data = response.json()
        
        if "data" in data and ("qr_link" in data["data"] or "qr_string" in data["data"]):
            total_bayar = data["data"].get("total_bayar") or data["data"].get("nominal") or nominal
            return {
                "success": True,
                "qr_string": data["data"].get("qr_string", ""),
                "qr_url": data["data"].get("qr_link", "") or data["data"].get("pay_url", ""),
                "total_bayar": total_bayar,
                "msg": "QRIS PaymentKita berhasil dibuat"
            }
        else:
            pesan_pusat = data.get("message") or data.get("error_msg") or str(data)[:100]
            return {"success": False, "msg": f"Pesan dari Pusat: {pesan_pusat}"}
            
    except Exception as e:
        return {"success": False, "msg": f"Koneksi jaringan terputus: {str(e)}"}

def check_paymentkita_status(ref_id):
    merchant, secret = get_credentials()
    base_url = "https://api.paymentkita.com/v1/check-order"
    payload = {"merchant": merchant, "secret": secret, "ref_id": ref_id}
    headers = {"User-Agent": "GarudaTell-Server/2.0", "Accept": "application/json"}
    
    try:
        response = requests.get(base_url, params=payload, headers=headers, timeout=15)
        data = response.json()
        status_api = data.get("data", {}).get("status", "").lower()
        if status_api == "success" or data.get("status", "").lower() == "success":
            return True, "Valid dan Lunas"
        return False, f"Status saat ini: {status_api or 'Pending'}"
    except Exception as e:
        return False, f"Error cek radar: {str(e)}"

def verify_callback(payload):
    """Verify callback signature using HMAC-SHA256 with timestamp validation."""
    merchant, secret = get_credentials()
    reff_id = payload.get("reff_id", "")
    received_signature = payload.get("signature", "")
    timestamp = payload.get("timestamp", "")
    
    # Validate timestamp (prevent replay attacks - accept within 5 minutes)
    if timestamp:
        try:
            callback_time = int(timestamp)
            current_time = int(time.time())
            if abs(current_time - callback_time) > 300:  # 5 minutes
                return False, "Callback expired (timestamp too old)"
        except:
            pass  # If timestamp validation fails, continue with signature check
    
    # Verify signature using HMAC-SHA256
    raw_string = f"{merchant}:{reff_id}:{timestamp}" if timestamp else f"{merchant}:{reff_id}"
    calculated_signature = hmac.new(
        secret.encode('utf-8'),
        raw_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    if hmac.compare_digest(calculated_signature, received_signature) and payload.get("status") == "Success":
        return True, "Valid dan Lunas"
    return False, "Signature tidak cocok atau belum lunas!"
