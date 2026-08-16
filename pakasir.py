import hmac
import hashlib
import os
from urllib.parse import urlencode

def is_configured() -> bool:
    return bool(os.getenv("PAKASIR_KEY") and os.getenv("PAKASIR_PROJECT"))

def _key(): return os.getenv("PAKASIR_KEY", "").strip()
def _project(): return os.getenv("PAKASIR_PROJECT", "").strip()

def create_qris(amount: int, order_id: str):
    project = _project() or "Ansor"
    qs = urlencode({"order_id": order_id, "api_key": _key(), "qris_only": "1"})
    payment_url = f"https://app.pakasir.com/pay/{project}/{int(amount)}?{qs}"
    return {
        "ok": True,
        "amount": int(amount),
        "order_id": order_id,
        "payment_url": payment_url,
        "qris_data": payment_url
    }

def verify_callback(payload, query_api_key="", signature=""):
    """
    Verify Pakasir webhook callback with HMAC-SHA256 signature validation.
    
    Args:
        payload: Webhook payload (dict)
        query_api_key: API key from query string
        signature: HMAC signature from header/payload
    
    Returns:
        Tuple (bool, str): (is_valid, reason)
    """
    # 1. Verify API key is present
    if not query_api_key:
        return False, "Missing API key in query string"
    
    # 2. Get configured API key
    expected_key = _key()
    if not expected_key:
        return False, "Pakasir not configured"
    
    # 3. Verify API key matches using constant-time comparison
    if not hmac.compare_digest(query_api_key, expected_key):
        return False, "Invalid API key"
    
    # 4. Verify required fields are present
    required_fields = ["order_id", "amount"]
    for field in required_fields:
        if field not in payload:
            return False, f"Missing required field: {field}"
    
    # 5. Verify order_id format (must be TOP-*)
    order_id = str(payload.get("order_id", "")).strip()
    if not order_id.startswith("TOP-"):
        return False, "Invalid order_id format (must start with TOP-)"
    
    # 6. Verify amount is positive integer
    try:
        amount = int(payload.get("amount", 0))
        if amount <= 0:
            return False, "Amount must be positive"
        if amount > 10000000:  # 10 million max
            return False, "Amount exceeds maximum allowed"
    except (TypeError, ValueError):
        return False, "Invalid amount format"
    
    # 7. Verify HMAC signature if provided (defense in depth)
    if signature:
        raw_string = f"{order_id}:{amount}:{expected_key}"
        calculated_sig = hmac.new(
            expected_key.encode('utf-8'),
            raw_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, calculated_sig):
            return False, "Invalid HMAC signature"
    
    # ✅ All validations passed
    return True, "ok"
