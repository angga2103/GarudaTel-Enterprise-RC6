# AI RULES — GarudaTel Enterprise RC6 FIXED

**Project**: GarudaTel Enterprise RC6 FIXED  
**AI Agent**: Kiro  
**Context**: Project analysis dan perbaikan untuk RC6 FIXED release

---

## WORKSPACE RULES

### ✅ WORKSPACE AKTIF

**HANYA**: `C:\GarudaTel-Enterprise\02_WORKSPACE\GarudaTel_Enterprise_RC6_FIXED`

Ini adalah satu-satunya workspace yang boleh dibaca, dianalisa, dan diubah untuk project RC6 FIXED.

### ❌ WORKSPACE NON-AKTIF

**JANGAN** baca, audit, atau gunakan sebagai source:
- `GarudaTel_Enterprise_RC5` (previous version)
- `GarudaTel_Enterprise_RC1` (arsip historis)
- `root/web_ppob/paypoint` (production server)
- Folder lain di luar RC6_FIXED

**Pengecualian**: Hanya jika user secara eksplisit meminta perbandingan dengan versi lain.

---

## PHASE EXECUTION RULES

### 1. Sequential Execution
- Kerjakan satu fase pada satu waktu
- Jangan loncat ke fase berikutnya sebelum fase sekarang selesai
- Jangan paralel multi-fase kecuali diminta eksplisit

### 2. Stop & Report
- Setelah setiap fase selesai: **BERHENTI**
- Buat laporan hasil fase
- Tunggu konfirmasi user sebelum lanjut fase berikutnya
- Jangan auto-continue tanpa instruksi

### 3. No Redundant Audit
- Jangan audit ulang yang sudah selesai
- Jangan analisa ulang yang sudah dilaporkan
- Gunakan hasil fase sebelumnya sebagai input fase berikutnya
- **Contoh**: Jika audit database schema sudah selesai di Fase 1, jangan audit lagi di Fase 3

### 4. Evidence-Based Only
- Setiap perubahan harus berdasarkan analisa source code nyata
- Setiap claim harus ada bukti
- Jangan menebak
- Jangan berasumsi

### 5. Verification Required
- Jangan claim "PASS" tanpa test nyata
- Jangan claim "DONE" tanpa verifikasi
- Syntax check saja tidak cukup — harus ada runtime test atau logic verification
- Database test harus pakai DB kosong temporary, bukan DB production

---

## CODE CHANGE RULES

### ✅ ALLOWED CHANGES

1. **Database Schema Fix**
   - Tambahkan CREATE TABLE yang hilang
   - Tambahkan kolom yang hilang
   - Tambahkan index untuk performa
   - Perbaiki FK constraint

2. **Bug Fix dengan Bukti**
   - Hanya jika ada evidence bug nyata
   - Harus ada test case yang gagal
   - Perbaikan minimal, jangan over-engineer

3. **Compatibility Fix**
   - Perbaiki incompatibility antar modul
   - Perbaiki import error
   - Perbaiki dependency version conflict

### ❌ PROHIBITED CHANGES

1. **Business Logic Refactor**
   - Jangan ubah logic bisnis tanpa bukti bug
   - Jangan "improve" algoritma tanpa diminta
   - Jangan ubah flow transaksi
   - Jangan ubah perhitungan saldo/harga/margin

2. **Large Refactor**
   - Jangan rename massal variabel
   - Jangan restructure folder
   - Jangan ubah arsitektur besar-besaran
   - Jangan migrate framework/library

3. **Feature Changes**
   - Jangan hapus fitur
   - Jangan tambah fitur baru
   - Jangan ubah requirement
   - Jangan ubah UI/UX

4. **Code Style Changes**
   - Jangan reformatting kode yang sudah jalan
   - Jangan ubah naming convention
   - Jangan ubah indentation style (kecuali error syntax)

---

## TESTING RULES

### 1. Fresh Database Priority
- **Instalasi dari nol harus berjalan tanpa error**
- Setiap test database harus mulai dari kosong
- Jangan test pakai DB yang sudah ada data
- Jangan test pakai DB production

### 2. Test Hierarchy
Urutan priority test:
1. Database schema test (init_db() dari nol)
2. Import test (semua module bisa di-import)
3. Syntax test (Python syntax valid)
4. Logic test (business logic tidak rusak)
5. Integration test (flow end-to-end)

### 3. Test Coverage
Minimal test coverage untuk RC6:
- ✅ Database init dari nol
- ✅ Create user
- ✅ Create product
- ✅ Create transaction
- ✅ Topup flow
- ✅ Migration script idempotent

---

## BACKUP RULES

### Before Any Change
- Sebelum ubah file: catat file yang akan diubah
- Sebelum ubah banyak file: sarankan backup ZIP
- Jangan ubah tanpa trace

### Change Log
Setiap perubahan harus dicatat:
- File yang diubah
- Alasan perubahan
- Fase perubahan
- Evidence yang mendukung perubahan

---

## REPORTING RULES

### Status Report Format
Setiap laporan harus punya:
1. **Fase**: Fase berapa yang baru selesai
2. **Status**: PASS / FAIL / PARTIAL
3. **Summary**: Ringkasan hasil (3-5 kalimat)
4. **Details**: Detail temuan (jika ada)
5. **Files Changed**: Daftar file yang diubah (jika ada)
6. **Next Action**: Fase berikutnya atau rekomendasi

### Mismatch Report Format
Jika menemukan mismatch:
- **FILE**: path file lengkap
- **LINE**: nomor baris
- **SQL**: query yang bermasalah
- **PROBLEM**: jenis error (no such table, no such column, etc)
- **FIX REQUIRED**: perbaikan yang diperlukan

### No False Positive
- Jangan lapor mismatch yang tidak nyata
- Jangan lapor warning sebagai error
- Jangan lapor style issue sebagai bug

---

## COMMUNICATION RULES

### Clarity
- Gunakan Bahasa Indonesia untuk komunikasi user
- Gunakan bahasa teknis untuk dokumentasi kode
- Jangan bertele-tele
- Langsung ke poin

### Honesty
- Jika tidak tahu, katakan tidak tahu
- Jika belum test, katakan belum test
- Jangan claim tanpa bukti
- Jangan oversell hasil

### Precision
- Gunakan angka eksak (bukan "beberapa", tapi "7 tabel")
- Gunakan path lengkap (bukan "file models", tapi "models.py line 123")
- Gunakan istilah konsisten

---

## FINAL GOAL

**RC6 Release Package yang dapat**:
1. Install fresh tanpa error "no such table"
2. Berjalan tanpa perbaikan manual
3. Semua fitur bekerja dari instalasi kosong
4. Database schema lengkap dari `init_db()`
5. Migration script berjalan idempotent
6. Installer VPS berjalan tanpa crash

**Jangan claim RC6 ready sebelum semua goal tercapai dan terverifikasi.**

---

## ANTI-PATTERN

### ❌ JANGAN LAKUKAN INI

1. **Premature Optimization**
   - ❌ "Kode ini bisa lebih efisien, saya refactor ya"
   - ✅ "Kode ini berjalan tanpa bug, tidak perlu diubah"

2. **Over-Engineering**
   - ❌ "Saya tambahkan abstraction layer untuk future scalability"
   - ✅ "Perbaikan minimal untuk fix bug yang ada"

3. **Scope Creep**
   - ❌ "Sekalian saya tambahkan fitur X"
   - ✅ "Fokus pada database schema fix dulu"

4. **Assumption-Based Work**
   - ❌ "Harusnya kode ini jalan, jadi saya skip test"
   - ✅ "Test dulu baru claim PASS"

5. **Auto-Continue**
   - ❌ "Fase 3 selesai, langsung lanjut Fase 4"
   - ✅ "Fase 3 selesai, berhenti dan lapor"

---

## DECISION MATRIX

| Situasi | Action |
|---|---|
| Menemukan bug dengan bukti | Fix dengan minimal change |
| Menemukan kode tidak rapi tapi jalan | Jangan ubah |
| Menemukan fitur tidak efisien tapi benar | Jangan ubah |
| Menemukan tabel tidak dibuat | Tambahkan CREATE TABLE |
| Menemukan kolom tidak ada | Tambahkan kolom |
| Menemukan SQL error nyata | Fix error |
| Menemukan style tidak konsisten | Jangan ubah |
| User minta refactor besar | Tanya dulu konfirmasi |
| User minta hapus fitur | Tanya dulu alasan |
| Stuck di satu fase | Lapor dan minta guidance |

---

## QUALITY GATE

Sebelum lanjut ke fase berikutnya, pastikan:
- ✅ Fase sekarang selesai 100%
- ✅ Sudah ada laporan tertulis
- ✅ Sudah ada verifikasi (jika perlu)
- ✅ User sudah membaca laporan
- ✅ User sudah memberi instruksi lanjut

**Jangan auto-gate, tunggu approval.**

---

_Last Updated: 2026-08-10_  
_Owner: GarudaTel Enterprise_  
_AI Agent: Kiro_
