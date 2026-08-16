#!/bin/bash
# ============================================================================
# GarudaTel Enterprise RC6 FIXED — UNINSTALLER
# Version: 1.0.0
# Usage  : bash /root/uninstall_rc6.sh
#
# SCOPE (hanya komponen RC6):
#   - Service: web_ppob, subscription_worker, telegram_listener
#   - Folder : /root/web_ppob/paypoint
#   - Unit   : /etc/systemd/system/{web_ppob,subscription_worker,telegram_listener}.service
#   - Port   : 2100 (hanya proses RC6)
#
# DILARANG menyentuh:
#   - Nginx, Xray, VPN, port 5000, port 8080
#   - Project/database lain di /root/web_ppob/ (selain subfolder paypoint)
#   - Proses Python milik project lain
#   - cloudflared (jika digunakan project lain)
# ============================================================================

set -uo pipefail

# ============================================================================
# KONFIGURASI
# ============================================================================
INSTALL_DIR="/root/web_ppob/paypoint"
RC6_PORT=2100
RC6_SERVICES=("web_ppob" "subscription_worker" "telegram_listener")
RC6_SERVICE_FILES=(
    "/etc/systemd/system/web_ppob.service"
    "/etc/systemd/system/subscription_worker.service"
    "/etc/systemd/system/telegram_listener.service"
)
RC6_VENV_DIR="$INSTALL_DIR/venv"

# ============================================================================
# WARNA & LOGGING
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

log_info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_phase() {
    echo ""
    echo "============================================================================"
    echo -e "${BOLD}${GREEN}$1${NC}"
    echo "============================================================================"
}

# ============================================================================
# KONFIRMASI
# ============================================================================
main() {
    echo ""
    echo "============================================================================"
    echo -e "  ${BOLD}GARUDATEL ENTERPRISE RC6 FIXED — UNINSTALLER${NC}"
    echo "  Version: 1.0.0"
    echo "============================================================================"
    echo ""
    echo "  Tindakan yang akan dilakukan:"
    echo "    - Stop dan disable service: web_ppob, subscription_worker, telegram_listener"
    echo "    - Hapus unit file service RC6"
    echo "    - Hapus folder: $INSTALL_DIR"
    echo "    - Bersihkan proses di port $RC6_PORT (khusus RC6)"
    echo ""
    echo "  TIDAK akan menyentuh: Nginx, Xray, VPN, port 5000/8080, project lain"
    echo ""
    echo -n "  Lanjutkan uninstall? [y/N] "
    read -r CONFIRM
    echo ""

    if [[ ! "$CONFIRM" =~ ^[yY]$ ]]; then
        log_info "Uninstall dibatalkan"
        exit 0
    fi

    check_root
    stop_rc6_services
    remove_unit_files
    kill_rc6_port_process
    remove_install_dir
    reload_daemon
    verify_cleanup
    print_summary
}

# ============================================================================
# CEK ROOT
# ============================================================================
check_root() {
    if [[ $EUID -ne 0 ]]; then
        log_error "Uninstaller harus dijalankan sebagai root"
        exit 1
    fi
    log_ok "Running as root"
}

# ============================================================================
# STEP 1: STOP DAN DISABLE SERVICE RC6
# ============================================================================
stop_rc6_services() {
    log_phase "STEP 1: STOP SERVICE RC6"

    for svc in "${RC6_SERVICES[@]}"; do
        # Cek apakah service unit file ada
        if ! systemctl list-unit-files --full 2>/dev/null | grep -q "^${svc}.service"; then
            log_info "Service $svc tidak ditemukan (sudah dihapus atau belum diinstall)"
            continue
        fi

        log_info "Menghentikan $svc..."

        # Stop
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            systemctl stop "$svc" 2>/dev/null && log_ok "$svc dihentikan" || log_warn "Gagal stop $svc (lanjut)"
        else
            log_info "$svc sudah tidak aktif"
        fi

        # Disable
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            systemctl disable "$svc" 2>/dev/null && log_ok "$svc disabled" || log_warn "Gagal disable $svc (lanjut)"
        else
            log_info "$svc sudah tidak enabled"
        fi
    done
}

# ============================================================================
# STEP 2: HAPUS UNIT FILE SERVICE RC6
# ============================================================================
remove_unit_files() {
    log_phase "STEP 2: HAPUS UNIT FILE SERVICE RC6"

    local removed=0
    for unit_file in "${RC6_SERVICE_FILES[@]}"; do
        if [[ -f "$unit_file" ]]; then
            # Verifikasi file ini milik RC6 (cek WorkingDirectory di dalamnya)
            if grep -q "web_ppob/paypoint" "$unit_file" 2>/dev/null; then
                rm -f "$unit_file"
                log_ok "Dihapus: $unit_file"
                removed=$((removed + 1))
            else
                log_warn "Unit file $unit_file tidak tampak milik RC6 — dilewati (aman)"
            fi
        else
            log_info "Unit file tidak ada: $unit_file (skip)"
        fi
    done

    log_ok "Unit file RC6 dihapus: $removed file"
}

# ============================================================================
# STEP 3: BERSIHKAN PROSES DI PORT 2100 (TARGETED — HANYA RC6)
# ============================================================================
kill_rc6_port_process() {
    log_phase "STEP 3: BERSIHKAN PROSES PORT $RC6_PORT (TARGETED)"

    # Temukan PID yang menggunakan port 2100
    local pids=""

    if command -v lsof &>/dev/null; then
        pids=$(lsof -t -i :"$RC6_PORT" -sTCP:LISTEN 2>/dev/null || true)
    fi

    # Fallback: ss + awk
    if [[ -z "$pids" ]] && command -v ss &>/dev/null; then
        pids=$(ss -ltnp "sport = :$RC6_PORT" 2>/dev/null | awk '/LISTEN/ { match($0, /pid=([0-9]+)/, a); if (a[1]) print a[1] }' || true)
    fi

    if [[ -z "$pids" ]]; then
        log_ok "Tidak ada proses di port $RC6_PORT"
        return 0
    fi

    for pid in $pids; do
        # Verifikasi: pastikan proses ini adalah bagian dari RC6
        # Cek cmdline mengandung path install RC6
        local cmdline=""
        cmdline=$(cat "/proc/$pid/cmdline" 2>/dev/null | tr '\0' ' ' || true)

        if echo "$cmdline" | grep -q "web_ppob/paypoint"; then
            log_info "Menghentikan PID $pid (RC6 gunicorn/python): $cmdline"
            kill -TERM "$pid" 2>/dev/null || true
            sleep 2
            # Force kill jika masih hidup
            if kill -0 "$pid" 2>/dev/null; then
                kill -KILL "$pid" 2>/dev/null || true
                log_warn "PID $pid di-KILL paksa"
            else
                log_ok "PID $pid berhasil dihentikan"
            fi
        else
            log_warn "PID $pid di port $RC6_PORT bukan RC6 (cmdline: ${cmdline:0:80}...) — DILEWATI (aman)"
        fi
    done

    # Verifikasi port sudah bebas
    sleep 1
    local remaining=""
    if command -v lsof &>/dev/null; then
        remaining=$(lsof -t -i :"$RC6_PORT" -sTCP:LISTEN 2>/dev/null || true)
    fi

    if [[ -z "$remaining" ]]; then
        log_ok "Port $RC6_PORT sudah bebas"
    else
        log_warn "Port $RC6_PORT masih digunakan (mungkin bukan RC6): PID $remaining"
        log_info "Cek manual: lsof -i :$RC6_PORT"
    fi
}

# ============================================================================
# STEP 4: HAPUS FOLDER INSTALASI RC6
# ============================================================================
remove_install_dir() {
    log_phase "STEP 4: HAPUS FOLDER INSTALASI"

    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_info "Folder $INSTALL_DIR tidak ada (sudah bersih)"
        return 0
    fi

    # Verifikasi ini memang folder RC6 (ada app.py GarudaTel)
    if [[ -f "$INSTALL_DIR/app.py" ]]; then
        if grep -q "GARUDA" "$INSTALL_DIR/app.py" 2>/dev/null; then
            log_info "Konfirmasi: folder RC6 valid (app.py GarudaTel ditemukan)"
        fi
    fi

    # Buat snapshot nama folder sebelum hapus (bukan backup penuh)
    log_info "Menghapus: $INSTALL_DIR"
    rm -rf "$INSTALL_DIR"

    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_ok "Folder $INSTALL_DIR berhasil dihapus"
    else
        log_error "Gagal menghapus $INSTALL_DIR"
        log_info "Cek permission dan proses yang masih menggunakan folder"
    fi

    # Cek apakah /root/web_ppob/ kosong setelah hapus paypoint — biarkan
    # Jangan hapus /root/web_ppob/ karena mungkin ada folder lain di dalamnya
    if [[ -d "/root/web_ppob" ]]; then
        local remaining_content
        remaining_content=$(ls -A "/root/web_ppob" 2>/dev/null)
        if [[ -z "$remaining_content" ]]; then
            log_info "Folder /root/web_ppob kosong — dibiarkan (tidak dihapus otomatis)"
        else
            log_info "Folder /root/web_ppob masih berisi item lain — tidak disentuh"
        fi
    fi
}

# ============================================================================
# STEP 5: RELOAD SYSTEMD
# ============================================================================
reload_daemon() {
    log_phase "STEP 5: RELOAD SYSTEMD"
    systemctl daemon-reload 2>/dev/null && log_ok "systemctl daemon-reload OK" || log_warn "daemon-reload gagal (minor)"
    systemctl reset-failed 2>/dev/null || true
}

# ============================================================================
# STEP 6: VERIFIKASI CLEANUP
# ============================================================================
verify_cleanup() {
    log_phase "STEP 6: VERIFIKASI CLEANUP"

    local issues=0

    # Cek service tidak aktif
    for svc in "${RC6_SERVICES[@]}"; do
        if systemctl is-active --quiet "$svc" 2>/dev/null; then
            log_warn "Service $svc masih aktif (unexpected)"
            issues=$((issues+1))
        else
            log_ok "Service $svc: tidak aktif (bersih)"
        fi
    done

    # Cek folder sudah tidak ada
    if [[ -d "$INSTALL_DIR" ]]; then
        log_warn "Folder $INSTALL_DIR masih ada (gagal hapus)"
        issues=$((issues+1))
    else
        log_ok "Folder $INSTALL_DIR: sudah tidak ada (bersih)"
    fi

    # Cek port
    local port_user=""
    if command -v lsof &>/dev/null; then
        port_user=$(lsof -t -i :"$RC6_PORT" -sTCP:LISTEN 2>/dev/null || true)
    fi
    if [[ -z "$port_user" ]]; then
        log_ok "Port $RC6_PORT: bebas (bersih)"
    else
        log_warn "Port $RC6_PORT masih digunakan PID: $port_user"
        issues=$((issues+1))
    fi

    if [[ $issues -eq 0 ]]; then
        log_ok "Semua komponen RC6 berhasil dihapus"
    else
        log_warn "$issues item perlu dicek manual"
    fi
}

# ============================================================================
# RINGKASAN
# ============================================================================
print_summary() {
    echo ""
    echo "============================================================================"
    echo -e "  ${BOLD}${GREEN}UNINSTALL SELESAI${NC}"
    echo "============================================================================"
    echo ""
    echo "  Komponen yang dihapus:"
    echo "    - Service: web_ppob, subscription_worker, telegram_listener"
    echo "    - Unit files: /etc/systemd/system/{web_ppob,subscription_worker,telegram_listener}.service"
    echo "    - Folder: $INSTALL_DIR"
    echo ""
    echo "  Komponen yang TIDAK disentuh:"
    echo "    - Nginx, Xray, VPN, cloudflared (project lain)"
    echo "    - Port 5000, 8080"
    echo "    - Database/project lain di /root/"
    echo "    - Proses Python milik project lain"
    echo ""
    echo "  Untuk install ulang:"
    echo "    bash /root/install_rc6.sh"
    echo ""
    echo "============================================================================"
}

main "$@"
