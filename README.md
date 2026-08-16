# PayPoint — PPOB Auto-Pilot (Flask)

Aplikasi PPOB modern berbasis Python Flask + SQLite + Tailwind CDN + Google OAuth + Digiflazz Auto-Pilot.

## Menjalankan

```bash
pip install -r requirements.txt
cp .env.example .env       # isi credentials
python app.py              # default PORT=2100
```

Buka `http://localhost:2100`.

## Akun Demo

- **Admin:** `admin` / `admin123`
- **User:** `testuser` / `user123`

## Konfigurasi

Semua secret di `.env`:

| Var | Keterangan |
| --- | --- |
| `SECRET_KEY` | Flask session secret |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth Google. Redirect URI: `https://<YOUR-DOMAIN>/login/callback` |
| `DIGIFLAZZ_USER` / `DIGIFLAZZ_KEY` | Kredensial Digiflazz. Bila kosong, otomatis mode simulasi (mock pricelist & sukses random SN). |
| `PAKASIR_KEY` / `PAKASIR_PROJECT` | Kredensial Pakasir untuk QRIS. Bila kosong, mode simulasi (tombol "Simulasikan Bayar"). |
| `ADMIN_PASSWORD` | Password admin awal (di-seed saat DB pertama dibuat). |
| `ADMIN_WA_NUMBER` | Nomor WhatsApp admin untuk link "Lupa Password". |

## Fitur

- Login Username/Password + Google OAuth
- Dashboard user: Saldo, kategori, transaksi terakhir
- Belanja: Pulsa, Data, E-Money, PLN, Game (auto-fulfillment via Digiflazz)
- Top Up via QRIS (Pakasir, dengan tombol simulasi)
- Lupa Password via WhatsApp Admin
- Admin Panel: Dashboard, Manajemen Produk (CRUD), Auto-Pull Digiflazz Price-List, Sync Harga, User CRM (edit + adjust saldo), Log Transaksi, Log Hit Digiflazz
- Mobile-first responsif, SweetAlert2, Tailwind CDN
