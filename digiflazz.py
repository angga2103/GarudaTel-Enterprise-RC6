"""Digiflazz API client. Falls back to mock pricelist when credentials are absent."""
import os
import json

# --- PATCH BACA ENV OTOMATIS (DIGIFLAZZ) ---
import os
def load_env_if_needed():
    if not os.getenv("DIGIFLAZZ_USER"):
        env_paths = ['/root/web_ppob/.env', '/root/web_ppob/paypoint/.env']
        for env_path in env_paths:
            try:
                with open(env_path, 'r') as f:
                    for line in f:
                        if '=' in line and not line.strip().startswith('#'):
                            k, v = line.strip().split('=', 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
                if os.getenv("DIGIFLAZZ_USER"):
                    break # Berhenti mencari jika sudah ketemu
            except Exception:
                pass

load_env_if_needed()
# ---------------------------------------------

import hashlib
import random
import string
import requests
from datetime import datetime
from models import log_digiflazz_call

BASE_URL = "https://api.digiflazz.com/v1"


def _has_credentials() -> bool:
    return bool(os.getenv("DIGIFLAZZ_USER")) and bool(os.getenv("DIGIFLAZZ_KEY"))


def _sign(payload: str) -> str:
    user = os.getenv("DIGIFLAZZ_USER", "")
    key = os.getenv("DIGIFLAZZ_KEY", "")
    return hashlib.md5(f"{user}{key}{payload}".encode()).hexdigest()


def fetch_pricelist(cmd="prepaid") -> list:
    """Fetch the Digiflazz price list. If no credentials, return a built-in mock list."""
    if not _has_credentials():
        return _mock_pricelist()
    user = os.getenv("DIGIFLAZZ_USER")
    payload = {"cmd": cmd, "username": user, "sign": _sign("pricelist")}
    try:
        r = requests.post(f"{BASE_URL}/price-list", json=payload, timeout=20)
        log_digiflazz_call("/price-list", json.dumps(payload), r.text[:2000], r.status_code)
        data = r.json().get("data", [])
        return data
    except Exception as e:
        log_digiflazz_call("/price-list", json.dumps(payload), str(e), 0)
        return _mock_pricelist()


def submit_transaction(order_id: str, sku: str, target: str) -> dict:
    """Submit a transaction to Digiflazz. Falls back to mock success when not configured."""
    if not _has_credentials():
        # Mock auto-fulfillment
        sn = "SN-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=12))
        result = {"status": "Sukses", "rc": "00", "sn": sn, "message": "Transaksi berhasil (simulasi)"}
        log_digiflazz_call("/transaction", json.dumps({"sku": sku, "target": target, "order_id": order_id}),
                           json.dumps(result), 200, order_id=order_id)
        return result
    user = os.getenv("DIGIFLAZZ_USER")
    payload = {
        "username": user,
        "buyer_sku_code": sku,
        "customer_no": target,
        "ref_id": order_id,
        "sign": _sign(order_id),
    }
    try:
        r = requests.post(f"{BASE_URL}/transaction", json=payload, timeout=30)
        
        log_digiflazz_call("/transaction (inq-pasca)", json.dumps(payload), r.text, r.status_code, order_id=order_id)
        log_digiflazz_call("/transaction", json.dumps(payload), r.text[:2000], r.status_code, order_id=order_id)
        resp = r.json().get("data", {})
        return {
            "status": resp.get("status", "Pending"),
            "rc": resp.get("rc", "99"),
            "sn": resp.get("sn", ""),
            "message": resp.get("message", ""),
        }
    except requests.exceptions.Timeout:
        log_digiflazz_call("/transaction", json.dumps(payload), "TIMEOUT", 504, order_id=order_id)
        # JANGAN DI-REFUND! Paksa status jadi Pending agar saldo agen tertahan
        return {
            "status": "Pending",
            "rc": "99",
            "sn": "",
            "message": "Koneksi lambat dari Pusat. Transaksi sedang diproses (Pending)."
        }
    except Exception as e:
        log_digiflazz_call("/transaction", json.dumps(payload), str(e), 0, order_id=order_id)
        return {
            "status": "Pending",
            "rc": "99",
            "sn": "",
            "message": f"Sistem Error / Koneksi Terputus. (Status diamankan menjadi Pending)"
        }
        return {"status": "Gagal", "rc": "99", "sn": "", "message": str(e)}


def _mock_pricelist() -> list:
    """A simulated Digiflazz pricelist for demo when credentials aren't set."""
    items = []
    # Pulsa
    for brand in ["Telkomsel", "XL", "Indosat", "Tri", "Smartfren"]:
        for nominal in [5, 10, 25, 50, 100]:
            items.append({
                "buyer_sku_code": f"{brand[:4].upper()}{nominal}",
                "product_name": f"{brand} Pulsa {nominal:,}".replace(",", "."),
                "category": "Pulsa",
                "brand": brand,
                "type": "Umum",
                "seller_name": "Digiflazz Demo",
                "price": nominal * 1000 + random.randint(300, 600),
                "buyer_product_status": True,
                "seller_product_status": True,
                "unlimited_stock": True,
                "stock": 0,
                "multi": False,
                "start_cut_off": "23:30",
                "end_cut_off": "00:30",
                "desc": f"Pulsa {brand} {nominal}rb auto-process",
            })
    # Data
    for brand in ["Telkomsel", "XL", "Indosat", "Tri"]:
        for size, price in [("1GB/7H", 13500), ("2GB/30H", 27000), ("5GB/30H", 55000), ("10GB/30H", 100000)]:
            items.append({
                "buyer_sku_code": f"DATA-{brand[:4].upper()}-{size.replace('/', '')}",
                "product_name": f"{brand} Data {size}",
                "category": "Data",
                "brand": brand,
                "type": "Umum",
                "seller_name": "Digiflazz Demo",
                "price": price,
                "buyer_product_status": True,
                "seller_product_status": True,
                "unlimited_stock": True, "stock": 0, "multi": False,
                "start_cut_off": "00:00", "end_cut_off": "23:59",
                "desc": f"Paket data {brand} {size}",
            })
    # E-Money
    for brand in ["OVO", "DANA", "GoPay", "ShopeePay", "LinkAja"]:
        for nominal in [25, 50, 100, 200]:
            items.append({
                "buyer_sku_code": f"{brand[:4].upper()}{nominal}",
                "product_name": f"{brand} Saldo {nominal:,}".replace(",", "."),
                "category": "E-Money",
                "brand": brand,
                "type": "Umum",
                "seller_name": "Digiflazz Demo",
                "price": nominal * 1000 + 1500,
                "buyer_product_status": True, "seller_product_status": True,
                "unlimited_stock": True, "stock": 0, "multi": False,
                "start_cut_off": "00:00", "end_cut_off": "23:59",
                "desc": f"Top up {brand} {nominal}rb",
            })
    # PLN
    for nominal in [20, 50, 100, 200, 500]:
        items.append({
            "buyer_sku_code": f"PLN{nominal}",
            "product_name": f"PLN Token {nominal:,}".replace(",", "."),
            "category": "PLN",
            "brand": "PLN",
            "type": "Umum",
            "seller_name": "Digiflazz Demo",
            "price": nominal * 1000 + 1500,
            "buyer_product_status": True, "seller_product_status": True,
            "unlimited_stock": True, "stock": 0, "multi": False,
            "start_cut_off": "00:00", "end_cut_off": "23:59",
            "desc": f"Token listrik PLN {nominal}rb",
        })
    # Game
    for brand, items_list in [
        ("Mobile Legends", [(86, 22000), (172, 43000), (257, 64000), (706, 173000)]),
        ("Free Fire", [(70, 9500), (140, 19000), (355, 49000), (720, 95000)]),
        ("PUBG Mobile", [(60, 14500), (325, 73000), (660, 145000)]),
        ("Genshin Impact", [(60, 16000), (330, 79000)]),
    ]:
        for diamonds, price in items_list:
            items.append({
                "buyer_sku_code": f"{''.join(brand.split())[:4].upper()}{diamonds}",
                "product_name": f"{brand} {diamonds} Diamonds",
                "category": "Game",
                "brand": brand,
                "type": "Umum",
                "seller_name": "Digiflazz Demo",
                "price": price,
                "buyer_product_status": True, "seller_product_status": True,
                "unlimited_stock": True, "stock": 0, "multi": False,
                "start_cut_off": "00:00", "end_cut_off": "23:59",
                "desc": f"Top up {brand} {diamonds} diamonds",
            })
    log_digiflazz_call("/price-list", "{simulated}", f"{len(items)} items returned (mock)", 200)
    return items


def is_configured() -> bool:
    return _has_credentials()


def credential_hint() -> str:
    user = os.getenv("DIGIFLAZZ_USER", "")
    if not user:
        return "Belum dikonfigurasi (mode simulasi)"
    return f"User: {user[:4]}**** (terkonfigurasi)"

def inquiry_postpaid(order_id: str, sku: str, target: str) -> dict:
    """Cek Tagihan Pascabayar (PLN, PDAM, BPJS, dll)"""
    if not _has_credentials():
        return {"status": "Sukses", "rc": "00", "customer_name": "SAMPEL PELANGGAN", "admin": 0, "selling_price": 150000, "desc": {"tagihan": 150000}}
    
    user = os.getenv("DIGIFLAZZ_USER")
    key = os.getenv("DIGIFLAZZ_KEY")
    import hashlib
    sign = hashlib.md5((user + key + order_id).encode()).hexdigest()
    
    payload = {
        "username": user,
        "commands": "inq-pasca",
        "ref_id": order_id,
        "customer_no": target,
        "buyer_sku_code": sku,
        "sign": sign
    }
    
    import requests, json
    try:
        r = requests.post(f"{BASE_URL}/transaction", json=payload, timeout=30)
        
        log_digiflazz_call("/transaction (inq-pasca)", json.dumps(payload), r.text, r.status_code, order_id=order_id)
        res = r.json().get("data", {})
        return res
    except Exception as e:
        return {"status": "Gagal", "message": str(e)}

def pay_postpaid(order_id: str, sku: str, target: str) -> dict:
    """Bayar Tagihan Pascabayar yang sudah di-Inquiry"""
    if not _has_credentials():
        return {"status": "Sukses", "rc": "00", "sn": "PAY-POST-12345"}
        
    user = os.getenv("DIGIFLAZZ_USER")
    key = os.getenv("DIGIFLAZZ_KEY")
    import hashlib
    sign = hashlib.md5((user + key + order_id).encode()).hexdigest()
    
    payload = {
        "username": user,
        "commands": "pay-pasca",
        "ref_id": order_id,
        "customer_no": target,
        "buyer_sku_code": sku,
        "sign": sign
    }
    
    import requests, json
    try:
        r = requests.post(f"{BASE_URL}/transaction", json=payload, timeout=30)
        
        log_digiflazz_call("/transaction (inq-pasca)", json.dumps(payload), r.text, r.status_code, order_id=order_id)
        res = r.json().get("data", {})
        return res
    except Exception as e:
        return {"status": "Gagal", "message": str(e)}

def cek_saldo() -> dict:
    import os, hashlib, requests
    user = os.getenv("DIGIFLAZZ_USER", "")
    key = os.getenv("DIGIFLAZZ_KEY", "")
    
    if not user or not key:
        return {"status": "Gagal", "message": "Kredensial Digiflazz Belum Diisi"}
    
    # Meracik kunci gembok khusus untuk buka saldo (depo)
    sign = hashlib.md5((user + key + "depo").encode('utf-8')).hexdigest()
    payload = {
        "cmd": "deposit",
        "username": user,
        "sign": sign
    }
    
    try:
        r = requests.post("https://api.digiflazz.com/v1/cek-saldo", json=payload, timeout=15)
        res = r.json()
        if "data" in res and "deposit" in res["data"]:
            return {"status": "Sukses", "saldo": res["data"]["deposit"]}
        return {"status": "Gagal", "message": res.get("data", {}).get("message", "Gagal baca saldo")}
    except Exception as e:
        return {"status": "Gagal", "message": "Koneksi ke Digiflazz terputus"}
