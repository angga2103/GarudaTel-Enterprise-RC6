import os
import json
import urllib.request
import urllib.parse
import hashlib

def send_approval_notif(username, email, whatsapp, host_url):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id: return

    # =========================================
    # 1. KONVERSI NOMOR WA (Otomatis Ubah 0 jadi 62)
    # =========================================
    # Bersihkan spasi, tanda strip, atau plus
    clean_wa = "".join(filter(str.isdigit, str(whatsapp)))
    # Jika depannya 0, ganti jadi 62
    if clean_wa.startswith("0"):
        clean_wa = "62" + clean_wa[1:]

    # =========================================
    # 2. BUAT TEKS WHATSAPP OTOMATIS
    # =========================================
    raw_wa = f"🎉 *Halo {username}! Selamat Datang di Garuda Tell!* 🦅\n\n"
    raw_wa += f"Pendaftaran akun Anda telah kami *SETUJUI*. Berikut detail akun Anda:\n"
    raw_wa += f"👤 *Username:* {username}\n"
    raw_wa += f"📧 *Email:* {email}\n"
    raw_wa += f"📱 *WhatsApp:* {whatsapp}\n"
    raw_wa += f"🔑 *Password:* (Sesuai yang Anda daftarkan)\n\n"
    raw_wa += f"🌐 *Link Login:* {host_url}\n\n"
    raw_wa += f"⚠️ *PENTING:* Demi keamanan saldo, mohon segera login dan lakukan:\n"
    raw_wa += f"1. Ubah kata sandi di menu *Ganti Sandi*\n"
    raw_wa += f"2. Setting PIN Transaksi di menu *Ganti PIN* (PIN bawaan: 123456)\n\n"
    raw_wa += f"*Gaspol transaksinya, Bos! Semoga makin cuan! 🚀💸*"
    
    # URL-Encode teks WA agar aman dijadikan Link, gunakan clean_wa untuk link
    encoded_wa = urllib.parse.quote(raw_wa)
    wa_link = f"https://wa.me/{clean_wa}?text={encoded_wa}"

    # =========================================
    # 3. FORMAT PESAN TELEGRAM (HTML)
    # =========================================
    text = f"""
🔔 <b>AGEN BARU MENUNGGU PERSETUJUAN</b> 🔔

👤 <b>Username:</b> {username}
📧 <b>Email:</b> {email}
📱 <b>WhatsApp:</b> <a href="{wa_link}">{whatsapp}</a>

<i>💡 Klik nomor WA di atas untuk mengirim pesan WA otomatis.</i>

Pilih tindakan di bawah ini:
"""

    # =========================================
    # 4. KODE TOMBOL BAWAAN (JANGAN DIUBAH)
    # =========================================
    sign = hashlib.md5((username + token).encode()).hexdigest()
    safe_u = urllib.parse.quote(username)
    
    url_approve = f"{host_url}api/tg-approve?u={safe_u}&sign={sign}&action=approve"
    url_reject  = f"{host_url}api/tg-approve?u={safe_u}&sign={sign}&action=reject"
    
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅  IZINKAN", "url": url_approve},
                {"text": "❌  TOLAK (Hapus)", "url": url_reject}
            ]
        ]
    }
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "reply_markup": keyboard}
    
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=5)
    except:
        pass
