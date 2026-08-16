#!/bin/bash
# ============================================================================
# GarudaTel Enterprise RC6 FIXED
# ONE-COMMAND INSTALLER
# Version: 3.0.0
# Usage: bash /root/install_rc6.sh
# ============================================================================
#
# Alur:
#   1. Cek root + OS
#   2. Deteksi ZIP di /root/
#   3. Ekstrak ZIP ke temp dir
#   4. Deteksi struktur nested (GarudaTel_Enterprise_RC6_FIXED/ atau flat)
#   5. Pindahkan ke /root/web_ppob/paypoint/
#   6. Jalankan installer utama
#
# ============================================================================

set -euo pipefail

# ============================================================================
# KONFIGURASI
# ============================================================================
INSTALL_DIR="/root/web_ppob/paypoint"
ZIP_SEARCH_DIR="/root"
TEMP_EXTRACT="/tmp/garudatel_rc6_extract_$$"
MAIN_INSTALLER="installer_vps_baru_RC6_FIXED_v2.sh"

# ============================================================================
# WARNA & LOGGING
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()      { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()    { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_phase()   {
    echo ""
    echo "============================================================================"
    echo -e "${BOLD}${GREEN}$1${NC}"
    echo "============================================================================"
}

cleanup_temp() {
    if [[ -d "$TEMP_EXTRACT" ]]; then
        rm -rf "$TEMP_EXTRACT"
    fi
}
trap cleanup_temp EXIT

# ============================================================================
# MAIN
# ============================================================================
main() {
    echo ""
    echo "============================================================================"
    echo "  GARUDATEL ENTERPRISE RC6 FIXED — ONE-COMMAND INSTALLER"
    echo "  Version: 3.0.0"
    echo "============================================================================"
    echo ""

    # =========================================================================
    # STEP 1: CEK ROOT
    # =========================================================================
    log_phase "STEP 1: VALIDASI AKSES"

    if [[ $EUID -ne 0 ]]; then
        log_error "Installer harus dijalankan sebagai root"
        log_info "Gunakan: sudo bash /root/install_rc6.sh"
        exit 1
    fi
    log_ok "Running as root"

    # Cek OS
    if [[ -f /etc/os-release ]]; then
        source /etc/os-release
        log_ok "OS: $PRETTY_NAME"
        if [[ "$ID" != "ubuntu" && "$ID" != "debian" ]]; then
            log_warn "OS tidak diuji ($ID), melanjutkan..."
        fi
    else
        log_warn "Tidak dapat mendeteksi OS"
    fi

    # =========================================================================
    # STEP 2: CARI FILE ZIP
    # =========================================================================
    log_phase "STEP 2: DETEKSI FILE ZIP"

    # Cari ZIP GarudaTel di /root/
    ZIP_FILE=""
    for candidate in \
        "$ZIP_SEARCH_DIR/GarudaTel_Enterprise_RC6_FIXED.zip" \
        "$ZIP_SEARCH_DIR/GarudaTel_Enterprise_RC6.zip" \
        "$ZIP_SEARCH_DIR/GarudaTel_Enterprise.zip"; do
        if [[ -f "$candidate" ]]; then
            ZIP_FILE="$candidate"
            break
        fi
    done

    # Jika tidak ditemukan dengan nama spesifik, cari pattern
    if [[ -z "$ZIP_FILE" ]]; then
        FOUND=$(find "$ZIP_SEARCH_DIR" -maxdepth 1 -name "GarudaTel*.zip" 2>/dev/null | head -1)
        if [[ -n "$FOUND" ]]; then
            ZIP_FILE="$FOUND"
        fi
    fi

    if [[ -z "$ZIP_FILE" ]]; then
        log_error "File ZIP GarudaTel tidak ditemukan di $ZIP_SEARCH_DIR"
        log_info "Pastikan file ZIP sudah diupload ke /root/"
        log_info "Contoh nama yang dikenali:"
        log_info "  /root/GarudaTel_Enterprise_RC6_FIXED.zip"
        log_info "  /root/GarudaTel_Enterprise_RC6.zip"
        log_info "  /root/GarudaTel_Enterprise.zip"
        exit 1
    fi

    log_ok "Ditemukan: $ZIP_FILE"
    ZIP_SIZE=$(du -h "$ZIP_FILE" | cut -f1)
    log_info "Ukuran: $ZIP_SIZE"

    # =========================================================================
    # STEP 3: BACKUP INSTALASI LAMA (JIKA ADA)
    # =========================================================================
    log_phase "STEP 3: BACKUP INSTALASI LAMA"

    if [[ -d "$INSTALL_DIR" ]]; then
        if [[ -f "$INSTALL_DIR/app.py" ]] || [[ -f "$INSTALL_DIR/paypoint.db" ]]; then
            BACKUP_TS=$(date +"%Y%m%d_%H%M%S")
            BACKUP_PATH="/root/web_ppob/paypoint_backup_$BACKUP_TS"

            log_info "Instalasi lama ditemukan, membuat backup..."

            # Stop service RC6 lama dulu
            log_info "Menghentikan service RC6 lama..."
            for svc in web_ppob subscription_worker telegram_listener; do
                if systemctl is-active --quiet "$svc" 2>/dev/null; then
                    systemctl stop "$svc" 2>/dev/null || true
                    log_ok "Service $svc dihentikan"
                fi
            done

            # Backup
            cp -a "$INSTALL_DIR" "$BACKUP_PATH"
            log_ok "Backup dibuat: $BACKUP_PATH"

            # Hapus instalasi lama
            log_info "Menghapus instalasi lama..."
            rm -rf "$INSTALL_DIR"
            log_ok "Instalasi lama dihapus"
        else
            log_info "Direktori ada tapi kosong, melanjutkan..."
            rm -rf "$INSTALL_DIR"
        fi
    else
        log_info "Tidak ada instalasi lama, fresh install"
    fi

    # =========================================================================
    # STEP 4: EKSTRAK ZIP
    # =========================================================================
    log_phase "STEP 4: EKSTRAK ZIP"

    log_info "Membuat direktori temp..."
    mkdir -p "$TEMP_EXTRACT"

    # Pastikan unzip tersedia
    if ! command -v unzip &>/dev/null; then
        log_info "Menginstall unzip..."
        apt-get install -y unzip -qq
    fi

    log_info "Mengekstrak $ZIP_FILE..."
    unzip -q "$ZIP_FILE" -d "$TEMP_EXTRACT"
    log_ok "ZIP berhasil diekstrak"

    # =========================================================================
    # STEP 5: DETEKSI STRUKTUR ZIP (NESTED vs FLAT)
    # =========================================================================
    log_phase "STEP 5: DETEKSI STRUKTUR PROJECT"

    # Cek apakah app.py langsung ada di temp dir (flat)
    SOURCE_DIR=""

    if [[ -f "$TEMP_EXTRACT/app.py" ]]; then
        # Struktur flat: langsung di root ZIP
        SOURCE_DIR="$TEMP_EXTRACT"
        log_ok "Struktur flat terdeteksi (app.py di root ZIP)"
    else
        # Cari subfolder yang berisi app.py (nested/satu folder wrapper)
        FOUND_APPPY=$(find "$TEMP_EXTRACT" -maxdepth 2 -name "app.py" 2>/dev/null | head -1)
        if [[ -n "$FOUND_APPPY" ]]; then
            SOURCE_DIR=$(dirname "$FOUND_APPPY")
            log_ok "Struktur nested terdeteksi"
            log_info "Folder sumber: $SOURCE_DIR"
        else
            log_error "app.py tidak ditemukan di dalam ZIP"
            log_info "Isi ZIP:"
            find "$TEMP_EXTRACT" -maxdepth 3 | head -30
            exit 1
        fi
    fi

    # Validasi file kritis
    log_info "Memvalidasi file kritis..."
    MISSING=0
    for f in app.py requirements.txt; do
        if [[ -f "$SOURCE_DIR/$f" ]]; then
            log_ok "  ✓ $f"
        else
            log_error "  ✗ $f TIDAK ADA di ZIP"
            MISSING=$((MISSING+1))
        fi
    done
    if [[ $MISSING -gt 0 ]]; then
        log_error "ZIP tidak lengkap, $MISSING file kritis tidak ditemukan"
        exit 1
    fi

    # =========================================================================
    # STEP 6: PINDAHKAN KE INSTALL_DIR
    # =========================================================================
    log_phase "STEP 6: DEPLOY KE $INSTALL_DIR"

    log_info "Membuat direktori target..."
    mkdir -p "$INSTALL_DIR"

    log_info "Menyalin file project..."
    # Copy semua file termasuk hidden files
    cp -a "$SOURCE_DIR"/. "$INSTALL_DIR/"
    log_ok "Project disalin ke $INSTALL_DIR"

    # Verifikasi
    if [[ ! -f "$INSTALL_DIR/app.py" ]]; then
        log_error "Verifikasi gagal: app.py tidak ada di $INSTALL_DIR"
        exit 1
    fi
    log_ok "Verifikasi: app.py ada di $INSTALL_DIR"

    # =========================================================================
    # STEP 7: JALANKAN INSTALLER UTAMA
    # =========================================================================
    log_phase "STEP 7: MENJALANKAN INSTALLER UTAMA"

    if [[ ! -f "$INSTALL_DIR/$MAIN_INSTALLER" ]]; then
        log_error "Installer utama tidak ditemukan: $INSTALL_DIR/$MAIN_INSTALLER"
        log_info "File di $INSTALL_DIR:"
        ls -la "$INSTALL_DIR/"
        exit 1
    fi

    chmod +x "$INSTALL_DIR/$MAIN_INSTALLER"
    log_ok "Installer utama ditemukan: $MAIN_INSTALLER"

    echo ""
    log_info "Menjalankan installer utama..."
    echo "============================================================================"
    echo ""

    # Jalankan installer utama dari dalam INSTALL_DIR
    cd "$INSTALL_DIR"
    exec bash "$INSTALL_DIR/$MAIN_INSTALLER"
}

main "$@"
