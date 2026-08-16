import sqlite3
import os, time, sqlite3, re, json
import urllib.request, urllib.parse

# 1. BACA KONFIGURASI DENGAN AMAN
env_path = '/root/web_ppob/paypoint/.env'
env_vars = {}
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, val = line.strip().split('=', 1)
                env_vars[key.strip()] = val.strip().strip('"\'')

TOKEN = env_vars.get('TELEGRAM_BOT_TOKEN')
CHAT_ID = str(env_vars.get('TELEGRAM_CHAT_ID'))

def send_msg(chat_id, text, parse_mode=None):
    try:
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode: payload["parse_mode"] = parse_mode
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print("Error kirim pesan:", e)

def show_main_menu(chat_id):
    """Show main navigation menu - GarudaTel Enterprise Bot"""
    import urllib.request, json
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    kb = {
        "inline_keyboard": [
            [{"text": "📢 Broadcast", "callback_data": "menu_broadcast"}],
            [{"text": "🎨 Banner & Promo", "callback_data": "menu_promo"}],
            [{"text": "❌ Tutup", "callback_data": "menu_close"}]
        ]
    }
    menu_text = "━━━━━━━━━━━━━━━━━━\n*GARUDATEL ENTERPRISE*\n━━━━━━━━━━━━━━━━━━\n\nSilakan pilih menu:"
    payload = {"chat_id": chat_id, "text": menu_text, "parse_mode": "Markdown", "reply_markup": kb}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
    urllib.request.urlopen(req, timeout=10)

def process_message(msg):
    sender_id = str(msg.get("chat", {}).get("id", ""))
    text = msg.get("text", "")
    
    # 🛡️ VALIDASI LAPIS BAJA UNTUK TEKS
    if sender_id != CHAT_ID:
        send_msg(sender_id, "⛔ AKSES DITOLAK! Anda bukan Admin Garuda Tell.")
        return

    # --- MAIN MENU NAVIGATION ---
    if text == "/menu" or text == "/start":
        show_main_menu(CHAT_ID)
        return

    # --- FITUR CMS BANNER (PROMO) ---
    caption = msg.get("caption", "")
    
    if text == "/promo":
        import urllib.request, json
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        kb = {
            "inline_keyboard": [
                [{"text": "📋 Daftar Banner Aktif", "callback_data": "promo_list"}],
                [{"text": "➕ Cara Tambah", "callback_data": "promo_help"}, {"text": "❌ Tutup Menu", "callback_data": "promo_close"}]
            ]
        }
        payload = {"chat_id": CHAT_ID, "text": "🎛️ **PANEL KONTROL BANNER GARUDA TEL**\nSilakan pilih operasi di bawah ini:", "parse_mode": "Markdown", "reply_markup": kb}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return

    if "photo" in msg and caption.startswith("/promo_tambah"):
        try:
            import urllib.request, json, time
            send_msg(CHAT_ID, "⏳ Sedang mengunduh poster dari Telegram ke Server Web...")
            payload = caption.replace("/promo_tambah", "").strip()
            if payload.startswith("|"): payload = payload[1:]
            parts = [p.strip() for p in payload.split("|")]
            
            if len(parts) < 7:
                send_msg(CHAT_ID, "⚠️ Format salah! Gunakan: /promo_tambah | ID | Judul | Ket_Singkat | Ket_Panjang | Periode | Pengumuman | Hadiah")
                return
            
            b_id, b_title, b_short, b_long, b_periode, b_pengumuman, b_hadiah = parts[:7]; b_disclaimer = parts[7] if len(parts) >= 8 else ''
            
            file_id = msg["photo"][-1]["file_id"]
            get_file_url = f"https://api.telegram.org/bot{TOKEN}/getFile?file_id={file_id}"
            file_res = json.loads(urllib.request.urlopen(get_file_url).read().decode("utf-8"))
            file_path_tg = file_res["result"]["file_path"]
            
            dl_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path_tg}"
            upload_dir = "/root/web_ppob/paypoint/static/banners"
            os.makedirs(upload_dir, exist_ok=True)
            final_filename = f"{b_id}.jpg"
            save_path = os.path.join(upload_dir, final_filename)
            
            urllib.request.urlretrieve(dl_url, save_path)
            
            banner_json = "/root/web_ppob/paypoint/banners.json"
            banners = []
            if os.path.exists(banner_json):
                with open(banner_json, "r") as f:
                    banners = json.load(f)
            
            banners = [b for b in banners if b["id"] != b_id]
            banners.append({
                "id": b_id, "title": b_title, "image": f"/static/banners/{final_filename}",
                "desc_short": b_short, "desc_long": b_long, "periode": b_periode,
                "pengumuman": b_pengumuman, "hadiah": b_hadiah, "disclaimer": b_disclaimer, "author": "Administrator",
                "date": time.strftime("%d/%m/%Y %H:%M:%S")
            })
            
            with open(banner_json, "w") as f:
                json.dump(banners, f, indent=2)
                
            send_msg(CHAT_ID, f"✅ BERHASIL! Banner '{b_title}' langsung tayang di Dashboard Web Garuda Tel!")
            return
        except Exception as e:
            send_msg(CHAT_ID, f"❌ Error Upload: {str(e)}")
            return

    # --- FITUR BROADCAST, EDIT, & HAPUS (LAPIS BAJA) ---
    if text and isinstance(text, str):
        if text.startswith("/delbc"):
            bc_id = text.replace("/delbc", "").strip()
            if not bc_id.isdigit():
                send_msg(CHAT_ID, "❌ Format salah! Gunakan: /delbc <ID>")
                return
            try:
                conn_bc = sqlite3.connect("/root/web_ppob/paypoint/paypoint.db")
                c = conn_bc.cursor()
                c.execute("DELETE FROM notifications WHERE id=?", (int(bc_id),))
                if c.rowcount > 0:
                    send_msg(CHAT_ID, f"✅ Broadcast ID {bc_id} berhasil dihapus dari Web!")
                else:
                    send_msg(CHAT_ID, f"⚠️ Broadcast ID {bc_id} tidak ditemukan.")
                conn_bc.commit()
                conn_bc.close()
            except Exception as e:
                send_msg(CHAT_ID, f"❌ Error: {e}")
            return

        if text.startswith("/editbc"):
            parts = text.replace("/editbc", "").strip().split("|", 2)
            if len(parts) < 3:
                send_msg(CHAT_ID, "❌ Format: /editbc <ID> | <Judul Baru> | <Isi Baru>")
                return
            bc_id = parts[0].strip()
            new_title = parts[1].strip()
            new_msg = parts[2].strip()
            if not bc_id.isdigit():
                send_msg(CHAT_ID, "❌ ID harus angka!")
                return
            try:
                conn_bc = sqlite3.connect("/root/web_ppob/paypoint/paypoint.db")
                c = conn_bc.cursor()
                c.execute("UPDATE notifications SET title=?, message=? WHERE id=?", (new_title, new_msg, int(bc_id)))
                if c.rowcount > 0:
                    send_msg(CHAT_ID, f"✅ Broadcast ID {bc_id} berhasil diperbarui di Web!")
                else:
                    send_msg(CHAT_ID, f"⚠️ Broadcast ID {bc_id} tidak ditemukan.")
                conn_bc.commit()
                conn_bc.close()
            except Exception as e:
                send_msg(CHAT_ID, f"❌ Error: {e}")
            return

        if text.startswith("/bc"):
            if "|" not in text:
                send_msg(CHAT_ID, "❌ Format salah! Gunakan: /bc Judul | Isi")
                return
            pts = text.split("|", 1)
            judul = pts[0].replace("/bc", "").strip()
            isi = pts[1].strip()
            try:
                conn_bc = sqlite3.connect("/root/web_ppob/paypoint/paypoint.db")
                cursor_bc = conn_bc.cursor()
                cursor_bc.execute("CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, message TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
                cursor_bc.execute("SELECT id FROM notifications WHERE title=? AND message=? AND created_at >= datetime('now', '-1 minute')", (judul, isi))
                if not cursor_bc.fetchone():
                    cursor_bc.execute("INSERT INTO notifications (title, message) VALUES (?, ?)", (judul, isi))
                    bc_id = cursor_bc.lastrowid
                    conn_bc.commit()
                    pesan = f"✅ *BROADCAST BERHASIL!*\n🆔 *ID Pesan:* `{bc_id}`\n📌 *Judul:* {judul}\n\n_Hapus: /delbc {bc_id}_\n_Edit: /editbc {bc_id} | Judul Baru | Isi Baru_"
                    send_msg(CHAT_ID, pesan, parse_mode="Markdown")
                conn_bc.close()
            except Exception as e:
                send_msg(CHAT_ID, f"❌ Error BC: {e}")
            return

    # --- FITUR BALAS TIKET AGEN ---
    if "reply_to_message" in msg and text:
        reply_text = text
        original_text = msg["reply_to_message"].get("text", "")
        match = re.search(r"Order ID:\s*(?:`|)(ORD-[A-Z0-9]+)", original_text)
        
        if match:
            order_id = match.group(1)
            q_text = "Kendala Transaksi"
            m_kendala = re.search(r"Kendala:\s*(.+)", original_text)
            m_pesan = re.search(r"Pesan Agen:\s*(.+)", original_text)
            
            if m_pesan and m_pesan.group(1).strip():
                q_text = m_pesan.group(1).strip()
            elif m_kendala:
                q_text = m_kendala.group(1).strip()
                
            try:
                # Menggunakan Absolute Path agar tidak nyasar
                conn = sqlite3.connect("/root/web_ppob/paypoint/database.db")
                cursor = conn.cursor()
                cursor.execute("INSERT OR REPLACE INTO admin_replies (order_id, question, reply) VALUES (?, ?, ?)", (order_id, q_text, reply_text))
                conn.commit()
                conn.close()
                send_msg(CHAT_ID, f"✅ Mantap Bos! Balasan tiket {order_id} sudah tayang.")
            except Exception as e:
                send_msg(CHAT_ID, f"❌ Error Reply: {e}")
        return

def process_callback(callback):
    sender_id = str(callback.get("from", {}).get("id", ""))
    
    # 🛡️ VALIDASI LAPIS BAJA UNTUK TOMBOL
    if sender_id != CHAT_ID:
        # Kita acuhkan saja jika orang asing pencet tombol
        return

    data = callback.get("data", "")

    msg_id = callback.get("message", {}).get("message_id")
    
    # --- MAIN MENU NAVIGATION ---
    if data == "menu_close":
        import urllib.request, json
        url = f"https://api.telegram.org/bot{TOKEN}/deleteMessage"
        payload = {"chat_id": CHAT_ID, "message_id": msg_id}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
        try: urllib.request.urlopen(req, timeout=10)
        except: pass
        return
    
    if data == "menu_broadcast":
        import urllib.request, json
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        kb = {
            "inline_keyboard": [
                [{"text": "📝 Buat Broadcast", "callback_data": "bc_help"}],
                [{"text": "📋 Lihat Semua Broadcast", "callback_data": "bc_list"}],
                [{"text": "⬅️ Kembali", "callback_data": "menu_main"}]
            ]
        }
        bc_text = "📢 *BROADCAST MANAGEMENT*\n\nPilih aksi atau gunakan command:\n• `/bc Judul | Isi` - Buat\n• `/editbc ID | Judul | Isi` - Edit\n• `/delbc ID` - Hapus"
        payload = {"chat_id": CHAT_ID, "text": bc_text, "parse_mode": "Markdown", "reply_markup": kb}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return
    
    if data == "menu_promo":
        # Forward to existing promo menu
        import urllib.request, json
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        kb = {
            "inline_keyboard": [
                [{"text": "📋 Daftar Banner Aktif", "callback_data": "promo_list"}],
                [{"text": "➕ Cara Tambah", "callback_data": "promo_help"}, {"text": "⬅️ Kembali", "callback_data": "menu_main"}]
            ]
        }
        payload = {"chat_id": CHAT_ID, "text": "🎛️ **PANEL KONTROL BANNER GARUDA TEL**\nSilakan pilih operasi di bawah ini:", "parse_mode": "Markdown", "reply_markup": kb}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return
    
    if data == "menu_main":
        show_main_menu(CHAT_ID)
        return
    
    if data == "bc_help":
        help_text = "📝 *CARA BUAT BROADCAST*\n\nFormat:\n`/bc Judul | Isi Pesan`\n\nContoh:\n`/bc Maintenance | Server akan maintenance jam 22:00`\n\n_Edit: /editbc ID | Judul | Isi_\n_Hapus: /delbc ID_"
        send_msg(CHAT_ID, help_text, parse_mode="Markdown")
        return
    
    if data == "bc_list":
        import sqlite3, urllib.request, json
        try:
            conn = sqlite3.connect("/root/web_ppob/paypoint/paypoint.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, title, message, created_at FROM notifications ORDER BY id DESC LIMIT 10")
            broadcasts = cursor.fetchall()
            conn.close()
            
            if not broadcasts:
                send_msg(CHAT_ID, "📭 Belum ada broadcast.")
                return
            
            text = "📋 *DAFTAR BROADCAST (10 Terbaru)*\n\n"
            for bc in broadcasts:
                text += f"🆔 `{bc['id']}` - {bc['title'][:30]}\n"
                text += f"📅 {bc['created_at']}\n\n"
            
            text += "\n_Gunakan /editbc atau /delbc untuk kelola_"
            send_msg(CHAT_ID, text, parse_mode="Markdown")
        except Exception as e:
            send_msg(CHAT_ID, f"❌ Error: {e}")
        return
    
    # --- PROMO/BANNER CALLBACKS (EXISTING) ---
    if data == "promo_close":
        import urllib.request, json
        url = f"https://api.telegram.org/bot{TOKEN}/deleteMessage"
        payload = {"chat_id": CHAT_ID, "message_id": msg_id}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
        try: urllib.request.urlopen(req, timeout=10)
        except: pass
        return
        
    if data == "promo_help":
        help_text = "💡 CARA TAMBAH BANNER BARU\nKirim gambar poster ke bot ini, lalu tulis caption dengan format:\n\n`/promo_tambah | id-promo | Judul Event | Deskripsi Singkat | Deskripsi Panjang | 1-10 Juli | 12 Juli | Rp 1.000.000`"
        send_msg(CHAT_ID, help_text, parse_mode="Markdown")
        return
        
    if data == "promo_list":
        import os, json, urllib.request
        banner_json = "/root/web_ppob/paypoint/banners.json"
        banners = []
        if os.path.exists(banner_json):
            with open(banner_json, "r") as f:
                banners = json.load(f)
        
        if not banners:
            send_msg(CHAT_ID, "📭 Saat ini tidak ada banner promosi yang tayang di web.")
            return
            
        kb = {"inline_keyboard": []}
        for b in banners:
            kb["inline_keyboard"].append([{"text": f"🗑️ Hapus: {b['title']}", "callback_data": f"prmdel_{b['id']}"}])
        kb["inline_keyboard"].append([{"text": "❌ Tutup", "callback_data": "promo_close"}])
        
        url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
        payload = {"chat_id": CHAT_ID, "text": "📋 **DAFTAR BANNER AKTIF**\nKlik tombol di bawah ini untuk menurunkan banner dari website:", "parse_mode": "Markdown", "reply_markup": kb}
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
        urllib.request.urlopen(req, timeout=10)
        return
        
    if data.startswith("prmdel_"):
        import os, json, urllib.request
        b_id = data.split("prmdel_")[1]
        banner_json = "/root/web_ppob/paypoint/banners.json"
        if os.path.exists(banner_json):
            with open(banner_json, "r") as f:
                banners = json.load(f)
            new_banners = [b for b in banners if b["id"] != b_id]
            with open(banner_json, "w") as f:
                json.dump(new_banners, f, indent=2)
            
            img_path = f"/root/web_ppob/paypoint/static/banners/{b_id}.jpg"
            if os.path.exists(img_path): os.remove(img_path)
            
            url = f"https://api.telegram.org/bot{TOKEN}/deleteMessage"
            payload = {"chat_id": CHAT_ID, "message_id": msg_id}
            req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={'Content-Type': 'application/json'})
            try: urllib.request.urlopen(req, timeout=10)
            except: pass
            
            send_msg(CHAT_ID, f"✅ Banner ID '{b_id}' berhasil dihapus dan diturunkan dari web!")
        return

    if data.startswith("restore_"):
        filename = data.split("restore_")[1]
        
        # 🛡️ SECURITY: Sanitize filename to prevent command injection
        # Only allow alphanumeric, dash, underscore, and dot
        import re
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', filename):
            send_msg(CHAT_ID, "❌ GAGAL RESTORE!\nNama file tidak valid (hanya boleh huruf, angka, dash, underscore, dan titik).")
            return
        
        # Prevent path traversal
        if '..' in filename or '/' in filename or '\\' in filename:
            send_msg(CHAT_ID, "❌ GAGAL RESTORE!\nNama file mengandung karakter berbahaya.")
            return
        
        zip_path = f"/root/web_ppob/backups/{filename}"
        
        # Verify file exists and is actually a zip file
        if os.path.exists(zip_path):
            send_msg(CHAT_ID, f"⚙️ MEMULAI RESTORE...\nSistem sedang membongkar file: {filename}\nWeb akan offline selama ~5 detik.")
            
            # 🔒 FIXED: Use subprocess instead of os.system to prevent command injection
            import subprocess
            try:
                # Use list format (NOT string) to prevent shell injection
                subprocess.run(
                    ["/usr/bin/unzip", "-o", zip_path, "-d", "/"],
                    check=True,
                    timeout=30,
                    capture_output=True
                )
                subprocess.run(
                    ["/usr/bin/systemctl", "restart", "web_ppob"],
                    check=True,
                    timeout=10,
                    capture_output=True
                )
                send_msg(CHAT_ID, "✅ RESTORE BERHASIL!\nSistem Garuda Tell telah kembali ke masa lalu dengan sempurna.")
            except subprocess.TimeoutExpired:
                send_msg(CHAT_ID, "⏱️ TIMEOUT!\nProses restore memakan waktu terlalu lama.")
            except subprocess.CalledProcessError as e:
                send_msg(CHAT_ID, f"❌ GAGAL RESTORE!\nError: {e.returncode}")
            except Exception as e:
                send_msg(CHAT_ID, f"❌ GAGAL RESTORE!\nError sistem: {str(e)}")
        else:
            send_msg(CHAT_ID, "❌ GAGAL RESTORE!\nFile ZIP tersebut sudah tidak ada di dalam VPS.")

def listen_telegram():
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    offset = None
    print("🤖 SUPER BOT Garuda Tell Standby (Lapis Baja)...")
    
    while True:
        try:
            params = {"timeout": 30}
            if offset: params["offset"] = offset
            query = urllib.parse.urlencode(params)
            
            req = urllib.request.Request(url + "?" + query)
            response = urllib.request.urlopen(req, timeout=35)
            res = json.loads(response.read().decode("utf-8"))
            
            if res.get("ok"):
                for update in res["result"]:
                    offset = update["update_id"] + 1
                    
                    if "message" in update:
                        process_message(update["message"])
                        
                    elif "callback_query" in update:
                        process_callback(update["callback_query"])
                        
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    listen_telegram()
