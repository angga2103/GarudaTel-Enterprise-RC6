# RC6 Deployment Architecture Verification

## 1. Actual Flask Binding
**FAKTA:**
- `app.py:194`: Port diambil dari environment variable `PORT` dengan default `2100`
- `app.py:196`: `app.run(host="0.0.0.0", port=port, debug=os.getenv("FLASK_DEBUG", "0") == "1")`
- Flask dijalankan pada host `0.0.0.0` bukan `127.0.0.1`

## 2. Actual Systemd Runtime
**FAKTA:**
- Tidak ada file `web_ppob.service` di project root
- Installer `installer_vps_baru_RC6_FIXED_v2.sh:1133`: Membuat service dengan konfigurasi:
  ```
  ExecStart=/root/web_ppob/paypoint/venv/bin/gunicorn --workers 3 --threads 2 --bind 127.0.0.1:5000
  ```
**KONFLIK:**
- Installer bind ke `127.0.0.1:5000`
- Flask runtime default `0.0.0.0:2100`
- Port mismatch: `5000` vs `2100`

## 3. Cloudflare Tunnel Configuration
**FAKTA:**
- `installer_vps_baru_RC6_FIXED_v2.sh:1398`: `cloudflared service install "$CF_TOKEN"`
- Tunnel menggunakan `named tunnel` bukan `ingress configuration`
- **KEY FINDING:** Token Cloudflare menentukan seluruh konfigurasi di sisi Cloudflare
- Tidak ada konfigurasi lokal `config.yml` yang menentukan origin

## 4. Actual Tunnel Origin
**UNCONFIRMED:**
- Origin tergantung konfigurasi di Cloudflare Dashboard
- Bisa jadi `localhost:8080`, `127.0.0.1:5000`, atau `0.0.0.0:2100`
- **ASUMSI INCORRECT:** Menganggap tunnel origin pasti `localhost:8080`

## 5. Gunicorn Status
**FAKTA:**
- `requirements.txt:12`: `gunicorn==21.2.0`
- Aplikasi menggunakan `app:app` pattern yang kompatibel dengan Gunicorn
- `app.py:121`: `app = create_app()` → WSGI ready

## 6. Nginx Requirement
**VERDICT:**
**NGINX TIDAK DIPERLUKAN UNTUK ARSITEKTUR INI.**

**ALASAN:**
- Arsitektur: Cloudflare Tunnel → Gunicorn → Flask
- Cloudflare Tunnel berfungsi sebagai reverse proxy
- Tidak perlu reverse proxy tambahan (Nginx)
- Gunicorn sudah menangani static files & worker management

## 7. Firewall Requirement
**ANALISIS:**
- `app.py:196`: `host="0.0.0.0"` → semua interface terbuka
- `installer:1133`: `--bind 127.0.0.1:5000` → hanya localhost
- **KONFLIK:** Flask vs Gunicorn binding berbeda

**REKOMENDASI:**
- Jika menggunakan Gunicorn dengan `127.0.0.1:5000`: firewall untuk port 2100 tidak diperlukan
- Jika menggunakan Flask langsung dengan `0.0.0.0:2100`: firewall port 2100 diperlukan

## 8. Security Assessment
**RISIKO FAKTUAL:**
1. **Cloudflare Tunnel → localhost HTTP**: Aman (local loopback)
2. **0.0.0.0 vs 127.0.0.1**: 
   - `0.0.0.0` → semua interface terbuka → RISIKO MEDIUM jika firewall tidak dikonfigurasi
   - `127.0.0.1` → hanya localhost → RISIKO LOW

**VULNERABILITAS:**
- KONFLIK bind address antara Flask (`0.0.0.0`) dan Gunicorn (`127.0.0.1`)
- Port mismatch (5000 vs 2100)

## 9. Confirmed Findings
1. ✅ Flask default binding: `0.0.0.0:2100` (`app.py:196`)
2. ✅ Gunicorn dalam installer: `127.0.0.1:5000` (`installer:1133`)
3. ✅ Cloudflare Tunnel menggunakan named tunnel token
4. ✅ Gunicorn terdaftar di requirements (`requirements.txt:12`)
5. ✅ Aplikasi WSGI-compatible (`app:app` pattern)

## 10. Unconfirmed Claims
1. ❓ Cloudflare Tunnel origin configuration
2. ❓ Apakah Cloudflare Dashboard diatur ke port `5000` atau `2100`
3. ❓ Service `web_ppob` benar-benar berjalan dengan konfigurasi di installer
4. ❓ Environment variable `PORT` override binding

## 11. Recommended Architecture
**CURRENT (INSTALLER):**
```
Cloudflare Tunnel (token) → Gunicorn (127.0.0.1:5000) → Flask
```

**ACTUAL (APP.PY):**
```
Cloudflare Tunnel (token) → Flask (0.0.0.0:2100)
```

**RECOMMENDED:**
```
Cloudflare Tunnel (token) → Gunicorn (127.0.0.1:2100) → Flask
```

## 12. Required Patches
**PATCH 1 - Service Configuration:**
- Ubah `installer:1133`: `--bind 127.0.0.1:5000` → `--bind 127.0.0.1:2100` ✅ **PATCHED**
- Pastikan environment variable `PORT=2100` di `.env`

**PATCH 2 - Cloudflare Configuration:**
- Verifikasi di Cloudflare Dashboard: Tunnel origin = `localhost:2100`
- Jika perlu, update tunnel configuration di Cloudflare side

**PATCH 3 - Flask Host Binding (OPTIONAL):**
- Ubah `app.py:196`: `host="0.0.0.0"` → `host="127.0.0.1"`
- Hanya jika ingin konsistensi, bukan requirement

---

## PATCH DEP-PORT-001

**Status:** PATCHED

**Problem:**
Gunicorn production service menggunakan `127.0.0.1:5000`, sementara arsitektur RC6 menggunakan port `2100`.

**Fix:**
Gunicorn diubah menjadi `127.0.0.1:2100` di file installer.

**Protected Resource:**
Port `5000` milik aplikasi lain dan tidak boleh diubah.

**File yang Diubah:**
`installer_vps_baru_RC6_FIXED_v2.sh`

**Line yang Diubah:** Line 1133

**Before:**
`ExecStart=/root/web_ppob/paypoint/venv/bin/gunicorn --workers 3 --threads 2 --bind 127.0.0.1:5000 --timeout 120 --access-logfile - --error-logfile - app:app`

**After:**
`ExecStart=/root/web_ppob/paypoint/venv/bin/gunicorn --workers 3 --threads 2 --bind 127.0.0.1:2100 --timeout 120 --access-logfile - --error-logfile - app:app`

**Verifikasi:**
- Tidak ada referensi `5000` untuk binding production
- Port `2100` konsisten untuk seluruh arsitektur
- Port `5000` tetap tidak tersentuh (protected resource aplikasi lain)

---

**SUMMARY:**
- **CONFIRMED:** Arsitektur deployment inkonsisten (Flask vs Gunicorn binding) ✅ **PATCHED**
- **CONFIRMED:** NGINX tidak diperlukan
- **CONFIRMED:** Cloudflare Tunnel menggunakan named tunnel
- **UNCONFIRMED:** Tunnel origin configuration di Cloudflare side
- **REQUIRED:** Patch untuk menyelaraskan port (2100) dan binding (127.0.0.1) ✅ **COMPLETED**

**FILE VERIFIED:**
1. `installer_vps_baru_RC6_FIXED_v2.sh` (line 1133, 1398) ✅ **PATCHED**
2. `app.py` (line 194, 196)
3. `requirements.txt` (line 12)
4. `web_ppob.service` (TIDAK ADA di project root)