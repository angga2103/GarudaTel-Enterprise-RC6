# INSTALASI GARUDA TELL ENTERPRISE RC6

## PRASYARAT
- VPS dengan Ubuntu/Debian
- Root access
- Internet connectivity

## STEP 1: UPLOAD FILE KE VPS

```bash
# Upload file yang sudah di-zip ke VPS
scp garudatel_rc6_fixed.zip root@<vps-ip>:/root/
```

## STEP 2: UNZIP DAN INSTALL

```bash
# Login ke VPS
ssh root@<vps-ip>

# Unzip file
cd /root
unzip garudatel_rc6_fixed.zip -d web_ppob/

# Berikan permission executable
chmod +x web_ppob/paypoint/installer_vps_baru_RC6_FIXED_v2.sh

# Jalankan installer
cd web_ppob/paypoint
./installer_vps_baru_RC6_FIXED_v2.sh
```

## STEP 3: INSTALLER FLOW

Installer akan menjalankan 11 fase:

1. ✅ Preflight validation
2. ✅ Project structure validation  
3. ✅ Configuration foundation
4. ✅ System dependencies installation
5. ✅ Python environment setup
6. ✅ Database foundation
7. ✅ Dependency verification
8. ✅ Cronjob setup
9. ✅ Service foundation (Gunicorn pada port 2100)
10. ⏳ Cloudflare Tunnel setup (akan minta token)
11. ✅ Installation certification

## STEP 4: CLOUDFLARE TUNNEL CONFIGURATION

**IMPORTANT:** Token Cloudflare diperlukan selama instalasi.

### Persiapan token:
1. Login ke https://one.dash.cloudflare.com/
2. Pilih "Networks" → "Tunnels" → "Create a tunnel"
3. Copy token yang dimulai dengan `eyJh...`
4. **PASTIKAN** konfigurasi di Cloudflare Dashboard:
   - Origin URL: `http://localhost:2100`
   - Public hostname: sesuaikan dengan domain yang diinginkan

### Selama instalasi:
Installer akan meminta:
```
🔑 Masukkan Token Cloudflare Tunnel (eyJh...): 
```
Paste token yang sudah disiapkan.

## STEP 5: VERIFIKASI INSTALASI

Setelah instalasi selesai, verifikasi:

```bash
# Check services status
systemctl status web_ppob
systemctl status subscription_worker
systemctl status cloudflared

# Check application health
curl http://localhost:2100

# Check logs
journalctl -u web_ppob -n 20
```

## STEP 6: ACCESS APPLICATION

### Melalui Cloudflare Tunnel:
- Akses melalui hostname yang dikonfigurasi di Cloudflare Dashboard

### Lokal testing:
```bash
# Jika ingin test lokal
curl http://localhost:2100
```

## TROUBLESHOOTING

### Issue 1: Port 2100 tidak merespon
```bash
# Check jika service running
systemctl status web_ppob

# Restart service jika perlu
systemctl restart web_ppob

# Check logs
journalctl -u web_ppob -f
```

### Issue 2: Cloudflare Tunnel tidak terkoneksi
```bash
# Check tunnel status
systemctl status cloudflared

# Restart tunnel
systemctl restart cloudflared

# Check tunnel logs
journalctl -u cloudflared -f
```

### Issue 3: Database error
```bash
# Check database file
ls -la /root/web_ppob/paypoint/paypoint.db

# Check database integrity
sqlite3 /root/web_ppob/paypoint/paypoint.db ".tables"
```

## ARCHITECTURE NOTES

✅ **Gunicorn**: Bind ke `127.0.0.1:2100`  
✅ **Flask**: Port `2100` (dari environment variable)  
✅ **Cloudflare**: Named tunnel dengan token  
❌ **Nginx**: Tidak diperlukan untuk arsitektur ini  
✅ **Firewall**: Aplikasi hanya binding ke localhost (127.0.0.1)

## IMPORTANT CONFIGURATIONS

1. **Port**: `2100` (default, bisa diubah di `.env`)
2. **Binding**: `127.0.0.1` (localhost only)
3. **Cloudflare**: Origin harus di-set ke `localhost:2100` di dashboard
4. **Firewall**: Pastikan port 2100 tidak terbuka ke public (sudah aman karena binding ke localhost)

---

**INSTALASI SELESAI:** Aplikasi akan berjalan di `127.0.0.1:2100` dan dapat diakses melalui Cloudflare Tunnel.