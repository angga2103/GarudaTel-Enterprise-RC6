# ============================================================
# GARUDATEL RC6 - ONE COMMAND DEPLOYMENT
# Windows PowerShell -> VPS
# ============================================================

$ErrorActionPreference = "Stop"

$VPS_USER = "root"
$VPS_HOST = "203.194.112.109"

$REMOTE_DIR = "/root/web_ppob/paypoint"
$PROJECT_DIR = "$REMOTE_DIR/GarudaTel_Enterprise_RC6_FIXED"

$LOCAL_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"

$TEMP_TAR = Join-Path $env:TEMP "garudatel_rc6_$TIMESTAMP.tar"
$REMOTE_TAR = "/tmp/garudatel_rc6_$TIMESTAMP.tar"
$REMOTE_SCRIPT = Join-Path $env:TEMP "garudatel_rc6_remote_$TIMESTAMP.sh"

Write-Host ""
Write-Host "============================================================"
Write-Host "       GARUDATEL RC6 - AUTOMATIC DEPLOYMENT"
Write-Host "============================================================"
Write-Host ""
Write-Host "LOCAL : $LOCAL_DIR"
Write-Host "VPS   : $VPS_USER@$VPS_HOST"
Write-Host "REMOTE: $PROJECT_DIR"
Write-Host ""

# ============================================================
# 1. LOCAL PROJECT CHECK
# ============================================================

Write-Host "[1/8] Memeriksa project lokal..."

foreach ($file in @("app.py", "requirements.txt")) {
    if (-not (Test-Path (Join-Path $LOCAL_DIR $file))) {
        throw "File wajib tidak ditemukan: $file"
    }
}

Write-Host "[OK] Project lokal valid."

# ============================================================
# 2. SSH CHECK
# ============================================================

Write-Host ""
Write-Host "[2/8] Memeriksa koneksi SSH..."

ssh -o ConnectTimeout=10 "$VPS_USER@$VPS_HOST" "echo SSH_OK"

if ($LASTEXITCODE -ne 0) {
    throw "Koneksi SSH gagal."
}

Write-Host "[OK] SSH terhubung."

# ============================================================
# 3. CREATE SOURCE ARCHIVE
# ============================================================

Write-Host ""
Write-Host "[3/8] Membuat archive source code..."

if (Test-Path $TEMP_TAR) {
    Remove-Item $TEMP_TAR -Force
}

tar `
    --exclude=".env" `
    --exclude=".git" `
    --exclude="__pycache__" `
    --exclude="*.pyc" `
    --exclude="venv" `
    --exclude=".venv" `
    --exclude="*.db" `
    -cf $TEMP_TAR `
    -C $LOCAL_DIR .

if ($LASTEXITCODE -ne 0) {
    throw "Gagal membuat archive source."
}

Write-Host "[OK] Archive dibuat."

# ============================================================
# 4. CREATE REMOTE BASH SCRIPT
# ============================================================

Write-Host ""
Write-Host "[4/8] Menyiapkan deployment script VPS..."

$REMOTE_BASH = @'
#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_DIR="__PROJECT_DIR__"
BACKUP_ROOT="/root/web_ppob/rc6_backups"
TIMESTAMP="__TIMESTAMP__"
REMOTE_TAR="__REMOTE_TAR__"

echo ""
echo "============================================================"
echo "          GARUDATEL RC6 VPS DEPLOYMENT"
echo "============================================================"

mkdir -p "$PROJECT_DIR"
mkdir -p "$BACKUP_ROOT"

echo "[1/9] Backup source lama..."

if [ -f "$PROJECT_DIR/app.py" ]; then
    tar \
        --exclude=".env" \
        --exclude="__pycache__" \
        --exclude="venv" \
        --exclude=".venv" \
        --exclude="*.db" \
        -czf "$BACKUP_ROOT/rc6_$TIMESTAMP.tar.gz" \
        -C "$PROJECT_DIR" . || true
    echo "[OK] Backup dibuat."
else
    echo "[INFO] Belum ada source lama."
fi

echo "[2/9] Extract source baru..."

TMP_DIR="/tmp/rc6_deploy_$TIMESTAMP"

rm -rf "$TMP_DIR"
mkdir -p "$TMP_DIR"
tar -xf "$REMOTE_TAR" -C "$TMP_DIR"

test -f "$TMP_DIR/app.py"
test -f "$TMP_DIR/requirements.txt"

echo "[OK] Source valid."

echo "[3/9] Mengamankan .env..."

ENV_BACKUP="/tmp/rc6_env_$TIMESTAMP"

if [ -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env" "$ENV_BACKUP"
    chmod 600 "$ENV_BACKUP"
fi

echo "[4/9] Update source..."

cp -a "$TMP_DIR"/. "$PROJECT_DIR"/

if [ -f "$ENV_BACKUP" ]; then
    cp "$ENV_BACKUP" "$PROJECT_DIR/.env"
    chmod 600 "$PROJECT_DIR/.env"
    rm -f "$ENV_BACKUP"
    echo "[OK] .env lama dipertahankan."
fi

echo "[5/9] Permission..."

chown -R root:root "$PROJECT_DIR"
find "$PROJECT_DIR" -type f -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true

echo "[6/9] Dependency check..."

if [ -x "$PROJECT_DIR/venv/bin/pip" ]; then
    "$PROJECT_DIR/venv/bin/pip" install -r "$PROJECT_DIR/requirements.txt" --disable-pip-version-check -q
    echo "[OK] Python dependencies checked."
else
    echo "[WARNING] venv tidak ditemukan. Dependency tidak diubah."
fi

echo "[7/9] Restart web_ppob..."

systemctl daemon-reload

if systemctl list-unit-files 2>/dev/null | grep -q '^web_ppob.service'; then
    systemctl restart web_ppob
    sleep 3
else
    echo "[ERROR] web_ppob.service tidak ditemukan."
    exit 1
fi

echo "[8/9] Port 2100..."

if ss -lntp | grep -q '127.0.0.1:2100'; then
    echo "[OK] 127.0.0.1:2100 LISTENING"
else
    echo "[ERROR] Port 2100 tidak listening."
    systemctl status web_ppob --no-pager -l || true
    exit 1
fi

echo "[9/9] HTTP health check..."

HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' \
    --max-time 10 \
    http://127.0.0.1:2100/ || true)

echo "HTTP STATUS: $HTTP_CODE"

case "$HTTP_CODE" in
    200|301|302|303|307|308)
        echo "[OK] RC6 merespons."
        ;;
    *)
        echo "[WARNING] HTTP response: $HTTP_CODE"
        ;;
esac

rm -rf "$TMP_DIR"
rm -f "$REMOTE_TAR"

echo ""
echo "============================================================"
echo "       RC6 DEPLOYMENT BERHASIL"
echo "============================================================"
echo "Project : $PROJECT_DIR"
echo "Port    : 127.0.0.1:2100"
echo "Backup  : $BACKUP_ROOT/rc6_$TIMESTAMP.tar.gz"
echo "============================================================"
'@

$REMOTE_BASH = $REMOTE_BASH.Replace("__PROJECT_DIR__", $PROJECT_DIR)
$REMOTE_BASH = $REMOTE_BASH.Replace("__TIMESTAMP__", $TIMESTAMP)
$REMOTE_BASH = $REMOTE_BASH.Replace("__REMOTE_TAR__", $REMOTE_TAR)

# Bash script harus LF dan tanpa BOM.
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$remoteText = $REMOTE_BASH -replace "`r`n", "`n"
[System.IO.File]::WriteAllText($REMOTE_SCRIPT, $remoteText, $utf8NoBom)

Write-Host "[OK] Remote script siap."

# ============================================================
# 5. UPLOAD
# ============================================================

Write-Host ""
Write-Host "[5/8] Mengirim source ke VPS..."

scp $TEMP_TAR "$VPS_USER@$VPS_HOST`:$REMOTE_TAR"

if ($LASTEXITCODE -ne 0) {
    throw "Upload source gagal."
}

scp $REMOTE_SCRIPT "$VPS_USER@$VPS_HOST`:/tmp/rc6_deploy_$TIMESTAMP.sh"

if ($LASTEXITCODE -ne 0) {
    throw "Upload deployment script gagal."
}

Write-Host "[OK] Source berhasil dikirim."

# ============================================================
# 6. RUN REMOTE DEPLOYMENT
# ============================================================

Write-Host ""
Write-Host "[6/8] Menjalankan deployment di VPS..."

$remoteCommand = "chmod +x /tmp/rc6_deploy_$TIMESTAMP.sh && /bin/bash /tmp/rc6_deploy_$TIMESTAMP.sh"

ssh "$VPS_USER@$VPS_HOST" $remoteCommand

if ($LASTEXITCODE -ne 0) {
    throw "Deployment di VPS gagal."
}

# ============================================================
# 7. FINAL CHECK
# ============================================================

Write-Host ""
Write-Host "[7/8] Pemeriksaan akhir..."

ssh "$VPS_USER@$VPS_HOST" "systemctl is-active web_ppob; ss -lntp | grep ':2100 ' ; curl -I --max-time 5 http://127.0.0.1:2100/"

# ============================================================
# 8. CLEANUP
# ============================================================

Write-Host ""
Write-Host "[8/8] Membersihkan temporary file..."

if (Test-Path $TEMP_TAR) {
    Remove-Item $TEMP_TAR -Force
}

if (Test-Path $REMOTE_SCRIPT) {
    Remove-Item $REMOTE_SCRIPT -Force
}

Write-Host "[OK] Cleanup selesai."

Write-Host ""
Write-Host "============================================================"
Write-Host "        RC6 DEPLOYMENT SUCCESS"
Write-Host "============================================================"
Write-Host ""
Write-Host "Source lokal sudah dikirim ke VPS."
Write-Host ""
Write-Host "Dilindungi:"
Write-Host "  .env"
Write-Host "  Database"
Write-Host "  Cloudflare Tunnel"
Write-Host "  Nginx"
Write-Host "  Xray"
Write-Host ""
Write-Host "============================================================"
