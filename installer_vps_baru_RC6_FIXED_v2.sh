#!/bin/bash
# ============================================================================
# GarudaTel Enterprise Installer V2
# Version: 2.0.0
# Purpose: Production-grade installer with validation & verification
# ============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# ============================================================================
# CONFIGURATION
# ============================================================================
INSTALL_DIR="/root/web_ppob/paypoint"
PYTHON_MIN_VERSION="3.8"
REQUIRED_DISK_MB=1024
REQUIRED_RAM_MB=512
SERVICE_NAME="web_ppob"

# ============================================================================
# COLOR OUTPUT
# ============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# LOGGING FUNCTIONS
# ============================================================================
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_phase() {
    echo ""
    echo "============================================================================"
    echo -e "${GREEN}$1${NC}"
    echo "============================================================================"
}

# ============================================================================
# PREFLIGHT VALIDATION
# ============================================================================
preflight_check() {
    log_phase "PHASE 1: PREFLIGHT VALIDATION"
    
    local errors=0
    
    # Check if running as root
    log_info "Checking user privileges..."
    if [[ $EUID -ne 0 ]]; then
        log_error "Installer must be run as root"
        errors=$((errors + 1))
    else
        log_success "Running as root"
    fi
    
    # Check OS
    log_info "Checking operating system..."
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        if [[ "$ID" == "ubuntu" ]] || [[ "$ID" == "debian" ]]; then
            log_success "OS: $PRETTY_NAME"
        else
            log_warning "OS: $PRETTY_NAME (not tested, but will continue)"
        fi
    else
        log_warning "Cannot detect OS version"
    fi
    
    # Check Python version
    log_info "Checking Python version..."
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 --version | awk '{print $2}')
        log_success "Python version: $PYTHON_VERSION"
        
        # Compare version
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
        MIN_MAJOR=$(echo $PYTHON_MIN_VERSION | cut -d. -f1)
        MIN_MINOR=$(echo $PYTHON_MIN_VERSION | cut -d. -f2)
        
        if [[ $PYTHON_MAJOR -lt $MIN_MAJOR ]] || [[ $PYTHON_MAJOR -eq $MIN_MAJOR && $PYTHON_MINOR -lt $MIN_MINOR ]]; then
            log_error "Python $PYTHON_MIN_VERSION or higher required"
            errors=$((errors + 1))
        fi
    else
        log_error "Python3 not found"
        errors=$((errors + 1))
    fi
    
    # Check disk space
    log_info "Checking disk space..."
    AVAILABLE_DISK=$(df /root | tail -1 | awk '{print $4}')
    if [[ $AVAILABLE_DISK -gt $REQUIRED_DISK_MB ]]; then
        log_success "Disk space: $(($AVAILABLE_DISK / 1024)) MB available"
    else
        log_error "Insufficient disk space. Required: ${REQUIRED_DISK_MB}MB, Available: $(($AVAILABLE_DISK / 1024))MB"
        errors=$((errors + 1))
    fi
    
    # Check RAM
    log_info "Checking memory..."
    AVAILABLE_RAM=$(free -m | awk 'NR==2{print $7}')
    if [[ $AVAILABLE_RAM -gt $REQUIRED_RAM_MB ]]; then
        log_success "Memory: ${AVAILABLE_RAM}MB available"
    else
        log_warning "Low memory. Required: ${REQUIRED_RAM_MB}MB, Available: ${AVAILABLE_RAM}MB"
    fi
    
    # Check internet connectivity
    log_info "Checking internet connectivity..."
    local internet_ok=false
    
    # Try primary endpoint: pypi.org (needed for pip install)
    if curl -s --max-time 10 --connect-timeout 5 -o /dev/null -w "%{http_code}" https://pypi.org | grep -qE "^(200|301|302|307|308)$"; then
        internet_ok=true
    else
        # Try secondary endpoint: google.com
        if curl -s --max-time 10 --connect-timeout 5 -o /dev/null -w "%{http_code}" https://www.google.com | grep -qE "^(200|301|302|307|308)$"; then
            internet_ok=true
        fi
    fi
    
    if [[ "$internet_ok" == true ]]; then
        log_success "Internet connection OK"
    else
        log_error "No internet connection"
        errors=$((errors + 1))
    fi
    
    if [[ $errors -gt 0 ]]; then
        log_error "Preflight check failed with $errors error(s)"
        exit 1
    fi
    
    log_success "Preflight validation passed"
}

# ============================================================================
# PROJECT STRUCTURE VALIDATION
# ============================================================================
validate_project_structure() {
    log_phase "PHASE 2: PROJECT STRUCTURE VALIDATION"
    
    local errors=0
    
    log_info "Validating project directory..."
    if [[ ! -d "$INSTALL_DIR" ]]; then
        log_error "Project directory not found: $INSTALL_DIR"
        errors=$((errors + 1))
    else
        log_success "Project directory exists"
    fi
    
    cd "$INSTALL_DIR" || exit 1
    
    # Check critical files
    log_info "Checking critical files..."
    
    local critical_files=(
        "app.py"
        "requirements.txt"
    )
    
    for file in "${critical_files[@]}"; do
        if [[ -f "$file" ]]; then
            log_success "Found: $file"
        else
            log_error "Missing: $file"
            errors=$((errors + 1))
        fi
    done
    
    # Check .env (optional)
    if [[ -f ".env" ]]; then
        log_success "Found: .env"
    else
        log_warning ".env not found — will be created automatically"
    fi
    
    # Check critical directories
    log_info "Checking critical directories..."
    
    local critical_dirs=(
        "templates"
        "static"
    )
    
    for dir in "${critical_dirs[@]}"; do
        if [[ -d "$dir" ]]; then
            log_success "Found: $dir/"
        else
            log_warning "Missing: $dir/ (optional)"
        fi
    done
    
    if [[ $errors -gt 0 ]]; then
        log_error "Project structure validation failed with $errors error(s)"
        exit 1
    fi
    
    log_success "Project structure validated"
}

# ============================================================================
# CONFIGURATION FOUNDATION
# ============================================================================
configuration_foundation() {
    log_phase "PHASE 3: CONFIGURATION FOUNDATION"
    
    cd "$INSTALL_DIR"
    
    local errors=0
    
    # Step 1: Verify required configuration files
    log_info "Verifying configuration files..."
    
    # Required files
    if [[ -f "requirements.txt" ]]; then
        log_success "  ✓ requirements.txt"
    else
        log_error "  ✗ requirements.txt (REQUIRED)"
        errors=$((errors + 1))
    fi
    
    if [[ -f "app.py" ]]; then
        log_success "  ✓ app.py"
    else
        log_error "  ✗ app.py (REQUIRED)"
        errors=$((errors + 1))
    fi
    
    # Optional files
    if [[ -f ".env" ]]; then
        log_success "  ✓ .env"
    else
        log_warning "  ! .env (will be created)"
    fi
    
    if [[ -f "firebase_credentials.json" ]]; then
        log_success "  ✓ firebase_credentials.json (optional)"
    else
        log_warning "  ! firebase_credentials.json (optional, not found)"
    fi
    
    if [[ $errors -gt 0 ]]; then
        log_error "Configuration file verification failed"
        exit 1
    fi
    
    # Step 2: Create .env if missing
    log_info "Checking .env configuration..."
    
    if [[ ! -f ".env" ]]; then
        log_warning ".env not found, creating from template..."
        
        if [[ -f ".env.example" ]]; then
            # Copy from example
            cp ".env.example" ".env"
            log_success ".env created from .env.example"
        else
            # Create minimal template
            log_info "Creating minimal .env template..."
            cat > .env << 'ENVEOF'
# --- Flask ---
SECRET_KEY=GENERATED_WILL_BE_REPLACED
FLASK_DEBUG=0
PORT=2100

# --- Admin defaults ---
ADMIN_PASSWORD=admin123
ADMIN_WA_NUMBER=6281234567890

# --- Google OAuth ---
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# --- Digiflazz (PPOB) ---
DIGIFLAZZ_USER=
DIGIFLAZZ_KEY=

# --- PaymentKita (QRIS) ---
PAYMENTKITA_MERCHANT=
PAYMENTKITA_SECRET=

# --- Pakasir (Offline Payment) ---
PAKASIR_KEY=
PAKASIR_PROJECT=paypoint

# --- Telegram Bot ---
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# --- Firebase (Push Notification) ---
FIREBASE_PROJECT_ID=
FIREBASE_PRIVATE_KEY=
FIREBASE_CLIENT_EMAIL=

# --- Cloudflare Tunnel ---
CLOUDFLARE_TUNNEL_TOKEN=

# --- WhatsApp Center ---
WHATSAPP_API_URL=
WHATSAPP_API_KEY=
ENVEOF
            log_success "Minimal .env template created"
        fi
    else
        log_success ".env already exists"
    fi
    
    # Step 3: Generate SECRET_KEY if missing or placeholder
    log_info "Checking SECRET_KEY..."
    
    if grep -q "^SECRET_KEY=" .env; then
        SECRET_VALUE=$(grep "^SECRET_KEY=" .env | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)
        
        # Check if it's a placeholder
        if [[ -z "$SECRET_VALUE" ]] || \
           [[ "$SECRET_VALUE" == "GENERATED_WILL_BE_REPLACED" ]] || \
           [[ "$SECRET_VALUE" == "ganti-saya-jadi-string-panjang-acak" ]] || \
           [[ "$SECRET_VALUE" =~ ^your.*key || "$SECRET_VALUE" =~ ^change.*me ]]; then
            log_warning "SECRET_KEY is placeholder, generating secure key..."
            NEW_SECRET=$(openssl rand -hex 32)
            sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$NEW_SECRET|" .env
            log_success "SECRET_KEY generated and saved"
        else
            log_success "SECRET_KEY already configured"
        fi
    else
        log_warning "SECRET_KEY missing, generating..."
        NEW_SECRET=$(openssl rand -hex 32)
        echo "SECRET_KEY=$NEW_SECRET" >> .env
        log_success "SECRET_KEY generated and added"
    fi
    
    # Step 4: Validate provider configuration (no API calls, no errors for missing providers)
    log_info "Checking provider configuration status..."
    
    # We need minimal Python to check config
    if [[ ! -d "venv" ]]; then
        python3 -m venv venv
    fi
    source venv/bin/activate
    
    # Install minimal deps
    pip install --quiet python-dotenv 2>/dev/null || true
    
    # Check providers (informational only, no failures)
    python3 << 'PYEOF'
import os
import sys

def load_env(path=".env"):
    config = {}
    if not os.path.exists(path):
        return config
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                config[key.strip()] = val.strip().strip('"').strip("'")
    return config

def check_provider(name, required_keys, config):
    """Check if provider is configured"""
    missing = []
    for key in required_keys:
        val = config.get(key, "")
        if not val or val in ["", "your_key_here", "change_me"]:
            missing.append(key)
    
    if not missing:
        return "CONFIGURED"
    elif len(missing) == len(required_keys):
        return "NOT_CONFIGURED"
    else:
        return "PARTIAL"

try:
    config = load_env(".env")
    
    providers = {
        "digiflazz": ["DIGIFLAZZ_USER", "DIGIFLAZZ_KEY"],
        "paymentkita": ["PAYMENTKITA_MERCHANT", "PAYMENTKITA_SECRET"],
        "telegram": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        "firebase": ["FIREBASE_PROJECT_ID", "FIREBASE_PRIVATE_KEY"],
        "cloudflare": ["CLOUDFLARE_TUNNEL_TOKEN"],
    }
    
    print("PROVIDER_STATUS_START")
    for provider, keys in providers.items():
        status = check_provider(provider, keys, config)
        print(f"{provider}:{status}")
    print("PROVIDER_STATUS_END")
    
except Exception as e:
    print(f"ERROR:{e}", file=sys.stderr)
PYEOF
    
    log_success "Provider status checked (configuration via Admin Panel → Integration Center)"
    
    # Step 5: Verify ConfigManager can load (if exists) - non-critical
    log_info "Verifying ConfigManager..."
    
    if [[ -f "config_manager.py" ]]; then
        if python3 -c "from config_manager import ConfigManager; cm = ConfigManager(); cm.load_config()" 2>/dev/null; then
            log_success "ConfigManager verified successfully"
        else
            log_warning "ConfigManager exists but had issues loading (non-critical)"
        fi
    else
        log_warning "config_manager.py not found (optional)"
    fi
    
    # Step 6: Configuration Summary Report
    echo ""
    log_info "Configuration Summary:"
    echo "============================================================================"
    printf "%-20s | %-15s\n" "COMPONENT" "STATUS"
    echo "----------------------------------------------------------------------------"
    printf "%-20s | %-15s\n" "SECRET_KEY" "$(grep -q '^SECRET_KEY=.\{32,\}' .env && echo 'CONFIGURED' || echo 'CHECK')"
    
    # Parse provider status from Python output
    python3 << 'PYEOF2'
import os

def load_env(path=".env"):
    config = {}
    if not os.path.exists(path):
        return config
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, val = line.split('=', 1)
                config[key.strip()] = val.strip().strip('"').strip("'")
    return config

def check_provider(name, required_keys, config):
    missing = []
    for key in required_keys:
        val = config.get(key, "")
        if not val or val in ["", "your_key_here", "change_me"]:
            missing.append(key)
    
    if not missing:
        return "CONFIGURED"
    elif len(missing) == len(required_keys):
        return "NOT_CONFIGURED"
    else:
        return "PARTIAL"

config = load_env(".env")

providers = {
    "DIGIFLAZZ": ["DIGIFLAZZ_USER", "DIGIFLAZZ_KEY"],
    "PAYMENTKITA": ["PAYMENTKITA_MERCHANT", "PAYMENTKITA_SECRET"],
    "TELEGRAM": ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
    "FIREBASE": ["FIREBASE_PROJECT_ID", "FIREBASE_PRIVATE_KEY"],
    "CLOUDFLARE": ["CLOUDFLARE_TUNNEL_TOKEN"],
}

for name, keys in providers.items():
    status = check_provider(name, keys, config)
    print(f"{name:20} | {status:15}")
PYEOF2
    
    echo "============================================================================"
    echo ""
    log_info "Note: Providers marked NOT_CONFIGURED can be configured later via:"
    log_info "      Admin Panel → Integration Center"
    echo ""
    
    log_success "Configuration foundation ready"
}

# ============================================================================
# SYSTEM DEPENDENCIES INSTALLATION
# ============================================================================
install_system_dependencies() {
    log_phase "PHASE 4: SYSTEM DEPENDENCIES INSTALLATION"
    
    log_info "Setting timezone to Asia/Jakarta..."
    timedatectl set-timezone Asia/Jakarta
    log_success "Timezone set to Asia/Jakarta"
    
    # Detect OS version
    log_info "Detecting OS version..."
    local os_id=""
    local os_version=""
    local os_codename=""
    
    if [[ -f /etc/os-release ]]; then
        . /etc/os-release
        os_id="$ID"
        os_version="$VERSION_ID"
        os_codename="$VERSION_CODENAME"
        log_success "Detected: $PRETTY_NAME (codename: $os_codename)"
    else
        log_warning "Cannot detect OS version, assuming Ubuntu"
        os_id="ubuntu"
        os_codename="focal"
    fi
    
    # Try apt update
    log_info "Updating package list..."
    
    local apt_update_success=false
    
    # Run apt-get update and capture both exit code and output
    set +e  # Temporarily disable exit on error
    apt-get update 2>&1 | tee /tmp/apt_update.log
    local apt_exit_code=${PIPESTATUS[0]}
    set -e  # Re-enable exit on error
    
    # Check for errors in output (even if exit code is 0)
    if grep -qE "(404|Failed to fetch|Unable to fetch|Some index files failed)" /tmp/apt_update.log; then
        log_warning "apt-get update encountered repository errors"
        
        # Show which repositories failed
        log_info "Failed repositories:"
        grep -E "(404|Failed to fetch)" /tmp/apt_update.log | head -5 || true
        
        log_info "Attempting fallback to official Ubuntu repositories..."
        
        # Backup current sources.list
        cp /etc/apt/sources.list /etc/apt/sources.list.backup_$(date +%Y%m%d_%H%M%S)
        
        # Create fallback sources.list based on detected version
        if [[ "$os_codename" == "focal" ]]; then
            log_info "Creating Ubuntu 20.04 (Focal) official repository configuration..."
            cat > /etc/apt/sources.list << 'EOF'
# Ubuntu 20.04 LTS (Focal Fossa) - Official Repositories
deb http://archive.ubuntu.com/ubuntu/ focal main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ focal-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ focal-backports main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ focal-security main restricted universe multiverse
EOF
            log_success "Fallback repository configuration created"
        elif [[ "$os_codename" == "jammy" ]]; then
            log_info "Creating Ubuntu 22.04 (Jammy) official repository configuration..."
            cat > /etc/apt/sources.list << 'EOF'
# Ubuntu 22.04 LTS (Jammy Jellyfish) - Official Repositories
deb http://archive.ubuntu.com/ubuntu/ jammy main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ jammy-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu/ jammy-backports main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu/ jammy-security main restricted universe multiverse
EOF
            log_success "Fallback repository configuration created"
        elif [[ "$os_id" == "debian" ]]; then
            log_info "Debian detected, using official Debian repositories..."
            cat > /etc/apt/sources.list << 'EOF'
# Debian - Official Repositories
deb http://deb.debian.org/debian/ stable main contrib non-free
deb http://deb.debian.org/debian/ stable-updates main contrib non-free
deb http://security.debian.org/debian-security stable-security main contrib non-free
EOF
            log_success "Fallback repository configuration created"
        else
            log_error "Unsupported OS version: $os_codename"
            log_info "Cannot create fallback repository configuration"
            exit 1
        fi
        
        # Retry apt update with fallback repositories
        log_info "Retrying apt-get update with fallback repositories..."
        
        set +e
        apt-get update 2>&1 | tee /tmp/apt_update_fallback.log
        local apt_fallback_exit_code=${PIPESTATUS[0]}
        set -e
        
        # Check fallback result
        if [[ $apt_fallback_exit_code -eq 0 ]] && ! grep -qE "(404|Failed to fetch|Unable to fetch|Some index files failed)" /tmp/apt_update_fallback.log; then
            apt_update_success=true
            log_success "Package list updated successfully with fallback repositories"
        else
            log_error "apt-get update failed even with fallback repositories"
            log_info ""
            log_info "Diagnostic information:"
            log_info "  - Exit code: $apt_fallback_exit_code"
            log_info "  - Check repository configuration: cat /etc/apt/sources.list"
            log_info "  - Check network connectivity: curl -I https://archive.ubuntu.com"
            log_info "  - Check apt update log: cat /tmp/apt_update_fallback.log"
            log_info "  - Original sources backup: /etc/apt/sources.list.backup_*"
            log_info ""
            exit 1
        fi
    elif [[ $apt_exit_code -ne 0 ]]; then
        log_error "apt-get update failed with exit code $apt_exit_code"
        log_info "Check log: cat /tmp/apt_update.log"
        exit 1
    else
        apt_update_success=true
        log_success "Package list updated successfully"
    fi
    
    # Install system packages
    log_info "Installing system packages..."
    
    local python_version=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2)
    log_info "Detected Python version: $python_version"
    
    # For Python 3.8, we need python3.8-venv explicitly
    if [[ "$python_version" == "3.8" ]]; then
        log_info "Installing packages for Python 3.8..."
        set +e
        apt-get install -y python3.8-venv python3-pip python3-venv curl unzip sqlite3 cron
        local apt_install_exit_code=$?
        set -e
        
        if [[ $apt_install_exit_code -ne 0 ]]; then
            log_error "Failed to install system packages"
            log_info "Try: apt-get update && apt-get install -y python3.8-venv python3-pip python3-venv curl unzip sqlite3 cron"
            exit 1
        fi
    else
        log_info "Installing packages for Python $python_version..."
        set +e
        apt-get install -y python3-pip python3-venv curl unzip sqlite3 cron
        local apt_install_exit_code=$?
        set -e
        
        if [[ $apt_install_exit_code -ne 0 ]]; then
            log_error "Failed to install system packages"
            log_info "Try: apt-get update && apt-get install -y python3-pip python3-venv curl unzip sqlite3 cron"
            exit 1
        fi
    fi
    
    log_success "System packages installed"
    
    # Verify critical packages
    log_info "Verifying installed packages..."
    local missing_packages=0
    
    if ! command -v python3 &> /dev/null; then
        log_error "python3 not found"
        missing_packages=$((missing_packages + 1))
    fi
    
    if ! command -v pip3 &> /dev/null; then
        log_error "pip3 not found"
        missing_packages=$((missing_packages + 1))
    fi
    
    if ! python3 -m venv --help &> /dev/null; then
        log_error "python3-venv not working"
        missing_packages=$((missing_packages + 1))
    fi
    
    if ! command -v sqlite3 &> /dev/null; then
        log_error "sqlite3 not found"
        missing_packages=$((missing_packages + 1))
    fi
    
    if [[ $missing_packages -gt 0 ]]; then
        log_error "Package verification failed: $missing_packages package(s) missing"
        exit 1
    fi
    
    log_success "All critical packages verified"
}

# ============================================================================
# DATABASE FOUNDATION
# ============================================================================
database_foundation() {
    log_phase "PHASE 6: DATABASE FOUNDATION"
    
    cd "$INSTALL_DIR"
    
    local DB_FILE="paypoint.db"
    local INSTALL_MODE="fresh"
    local table_count=0  # Initialize for fresh install scenario
    
    # Step 1: Detect installation mode
    log_info "Detecting installation mode..."
    if [[ -f "$DB_FILE" ]]; then
        # Check if database has tables
        table_count=$(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0")
        
        if [[ $table_count -gt 0 ]]; then
            INSTALL_MODE="restore"
            log_warning "Existing database detected with $table_count tables"
            log_info "Installation mode: RESTORE EXISTING SERVER"
        else
            INSTALL_MODE="fresh"
            log_info "Empty database file found"
            log_info "Installation mode: FRESH INSTALL"
        fi
    else
        INSTALL_MODE="fresh"
        log_info "No database found"
        log_info "Installation mode: FRESH INSTALL"
    fi
    
    # Step 2: Backup existing database if in restore mode
    if [[ "$INSTALL_MODE" == "restore" ]]; then
        log_info "Creating automatic backup before installation..."
        
        local TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
        local BACKUP_FILE="${DB_FILE}.before_install_${TIMESTAMP}"
        
        cp "$DB_FILE" "$BACKUP_FILE"
        
        if [[ -f "$BACKUP_FILE" ]]; then
            local BACKUP_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
            log_success "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"
        else
            log_error "Failed to create database backup"
            exit 1
        fi
    fi
    
    # Step 3: Initialize database structure
    log_info "Initializing database structure..."
    
    # Ensure venv is activated (already done in PHASE 5)
    source venv/bin/activate
    
    # Initialize database using models.py
    set +e
    python3 -c "from models import init_db; init_db(); print('Database initialized')" 2>&1 | tee /tmp/init_db.log
    local init_db_exit_code=${PIPESTATUS[0]}
    set -e
    
    if [[ $init_db_exit_code -eq 0 ]]; then
        log_success "Database structure initialized"
    else
        log_error "Failed to initialize database structure"
        log_info "Error details:"
        cat /tmp/init_db.log
        log_info ""
        log_info "Check log: cat /tmp/init_db.log"
        exit 1
    fi
    
    # Step 4: Determine if we need to run migrations
    # Check if this is a fresh install or upgrade
    log_info "Checking if database migrations are required..."
    
    # Initialize table_count_before for fresh install scenario
    local table_count_before=$table_count
    
    # Count tables after init_db() to determine if this is fresh install
    local table_count_after=0
    if [[ -f "$INSTALL_DIR/paypoint.db" ]]; then
        table_count_after=$(sqlite3 "$INSTALL_DIR/paypoint.db" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'" 2>/dev/null || echo "0")
    fi
    
    # For fresh install: init_db() already creates complete schema
    # Only run data migrations, skip redundant schema migrations
    if [[ "$table_count_before" -eq 0 ]] && [[ "$table_count_after" -ge 14 ]]; then
        log_success "Fresh database detected ($table_count_after tables created by init_db())"
        log_info "Skipping redundant schema migrations for fresh install"
        log_info "Only running essential data migrations..."
        
        # Only run essential data migrations (not schema migrations)
        local essential_migrations=("migrate_pins_to_bcrypt.py" "migrate_sec005_pin.py")
        local migration_files=()
        
        for mig in "${essential_migrations[@]}"; do
            if [[ -f "$INSTALL_DIR/$mig" ]]; then
                migration_files+=("$mig")
            fi
        done
        
        if [[ ${#migration_files[@]} -eq 0 ]]; then
            log_warning "No essential migrations found, skipping"
            return 0
        fi
    else
        # For upgrade: run all migrations
        log_info "Existing/upgrade database detected, running all migrations..."
        
        # Create migration log directory
        local migration_log_dir="/tmp/garudatel_migrations"
        mkdir -p "$migration_log_dir"
        
        # Discover ALL migration files using nullglob
        shopt -s nullglob
        local migration_files=(migrate_*.py)
        shopt -u nullglob
        
        # Sort migrations alphabetically
        IFS=$'\n' migration_files=($(sort <<<"${migration_files[*]}"))
        unset IFS
    fi
    
    local migration_count=${#migration_files[@]}
    
    if [[ $migration_count -eq 0 ]]; then
        log_warning "No migration scripts found, skipping migrations"
        return 0
    else
        log_info "Found $migration_count migration script(s) to execute"
        
        # Create migration log directory if not already created
        if [[ -z "${migration_log_dir:-}" ]]; then
            migration_log_dir="/tmp/garudatel_migrations"
            mkdir -p "$migration_log_dir"
        fi
        
        local executed=0
        local failed=0
        local migration_num=0
        
        local venv_python="$INSTALL_DIR/venv/bin/python"
        
        for migration in "${migration_files[@]}"; do
            migration_num=$((migration_num + 1))
            
            log_info "Running migration $migration_num/$migration_count: $migration"
            
            # Create log file for this migration
            local timestamp=$(date +"%Y%m%d_%H%M%S")
            local migration_log="$migration_log_dir/${migration}_${timestamp}.log"
            
            # Determine if migration needs special arguments
            local migration_args=""
            if [[ "$migration" == "migrate_sec005_pin.py" ]]; then
                # This migration requires --execute flag for actual execution
                migration_args="--execute"
            fi
            
            # Execute migration once and capture output + exit code
            local exit_code=0
            local output=""
            
            if [[ -n "$migration_args" ]]; then
                output=$("$venv_python" "$migration" $migration_args 2>&1) || exit_code=$?
            else
                output=$("$venv_python" "$migration" 2>&1) || exit_code=$?
            fi
            
            # Save full output to log file
            echo "$output" > "$migration_log"
            
            # Evaluate result based on exit code
            if [[ $exit_code -eq 0 ]]; then
                log_success "[OK] Migration $migration_num/$migration_count completed"
                executed=$((executed + 1))
            else
                log_error "[ERROR] Migration $migration_num/$migration_count FAILED"
                log_error "[ERROR] Migration: $migration"
                log_error "[ERROR] Exit code: $exit_code"
                log_error "[ERROR] Log saved to: $migration_log"
                echo ""
                log_error "--- Migration output (last 30 lines) ---"
                echo "$output" | tail -30
                log_error "--- End of migration output ---"
                echo ""
                failed=$((failed + 1))
                break
            fi
        done
        
        # Migration summary
        echo ""
        log_info "============================================================"
        log_info "MIGRATION SUMMARY"
        log_info "============================================================"
        log_info "Total:    $migration_count"
        log_info "Executed: $executed"
        log_info "Failed:   $failed"
        log_info "============================================================"
        echo ""
        
        if [[ $failed -gt 0 ]]; then
            log_error "Database migration failed with $failed error(s)"
            log_error "Installation stopped"
            exit 1
        fi
        
        log_success "All migrations completed successfully"
    fi
    
    # Step 5: Verify database integrity
    log_info "Verifying database integrity..."
    
    local verification_errors=0
    
    # Check 1: Database file exists
    if [[ ! -f "$DB_FILE" ]]; then
        log_error "Database file not found after initialization"
        verification_errors=$((verification_errors + 1))
    else
        log_success "Database file exists"
    fi
    
    # Check 2: Database can be opened
    if sqlite3 "$DB_FILE" "SELECT 1;" &>/dev/null; then
        log_success "Database can be opened"
    else
        log_error "Database is corrupted or cannot be opened"
        verification_errors=$((verification_errors + 1))
    fi
    
    # Check 3: Required tables exist
    log_info "Checking required tables..."
    
    local required_tables=(
        "users"
        "products"
        "transactions"
        "topups"
        "settings"
    )
    
    for table in "${required_tables[@]}"; do
        if sqlite3 "$DB_FILE" "SELECT name FROM sqlite_master WHERE type='table' AND name='$table';" | grep -q "$table"; then
            log_success "  ✓ Table: $table"
        else
            log_error "  ✗ Missing table: $table"
            verification_errors=$((verification_errors + 1))
        fi
    done
    
    if [[ $verification_errors -gt 0 ]]; then
        log_error "Database verification failed with $verification_errors error(s)"
        exit 1
    fi
    
    log_success "Database verification passed"
    
    # Summary
    echo ""
    log_info "Database Foundation Summary:"
    log_info "  Mode: $INSTALL_MODE"
    log_info "  Database: $DB_FILE"
    if [[ "$INSTALL_MODE" == "restore" ]]; then
        log_info "  Backup: $BACKUP_FILE"
    fi
    log_info "  Tables: $(sqlite3 "$DB_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';")"
    log_success "Database foundation ready"
}

# ============================================================================
# PYTHON ENVIRONMENT SETUP
# ============================================================================
setup_python_environment() {
    log_phase "PHASE 5: PYTHON ENVIRONMENT SETUP"
    
    cd "$INSTALL_DIR"
    
    log_info "Checking virtual environment..."
    if [[ ! -d "venv" ]]; then
        log_info "Creating virtual environment..."
        python3 -m venv venv
        log_success "Virtual environment created"
    else
        log_success "Virtual environment already exists"
    fi
    
    log_info "Activating virtual environment..."
    source venv/bin/activate
    log_success "Virtual environment activated"
    
    log_info "Upgrading pip..."
    pip install --upgrade pip --quiet
    log_success "Pip upgraded"
    
    log_info "Installing Python dependencies from requirements.txt..."
    if [[ -f "requirements.txt" ]]; then
        set +e
        pip install -r requirements.txt 2>&1 | tee /tmp/pip_install.log
        local pip_exit_code=${PIPESTATUS[0]}
        set -e
        
        if [[ $pip_exit_code -eq 0 ]]; then
            log_success "Python dependencies installed"
        else
            log_error "Failed to install Python dependencies"
            log_info "Check log: cat /tmp/pip_install.log"
            exit 1
        fi
    else
        log_error "requirements.txt not found"
        exit 1
    fi
}

# ============================================================================
# DEPENDENCY VERIFICATION
# ============================================================================
verify_dependencies() {
    log_phase "PHASE 7: DEPENDENCY VERIFICATION"
    
    cd "$INSTALL_DIR"
    source venv/bin/activate
    
    log_info "Verifying installed packages..."
    
    local errors=0
    
    # Read requirements.txt and verify each package
    while IFS= read -r line; do
        # Skip empty lines and comments
        [[ -z "$line" || "$line" =~ ^# ]] && continue
        
        # Extract package name (before >= or ==)
        package_name=$(echo "$line" | sed 's/[>=<].*//' | xargs)
        
        if pip show "$package_name" &> /dev/null; then
            package_version=$(pip show "$package_name" | grep "^Version:" | awk '{print $2}')
            log_success "$package_name ($package_version)"
        else
            log_error "$package_name not installed"
            errors=$((errors + 1))
        fi
    done < requirements.txt
    
    if [[ $errors -gt 0 ]]; then
        log_error "Dependency verification failed with $errors missing package(s)"
        exit 1
    fi
    
    log_success "All dependencies verified"
}

# ============================================================================
# CRONJOB SETUP
# ============================================================================
setup_cronjob() {
    log_phase "PHASE 8: CRONJOB SETUP"
    
    log_info "Setting up auto-backup cronjob..."
    
    # Check if telegram_backup.py exists
    if [[ -f "$INSTALL_DIR/telegram_backup.py" ]]; then
        (crontab -l 2>/dev/null; echo "0 */2 * * * cd $INSTALL_DIR && $INSTALL_DIR/venv/bin/python $INSTALL_DIR/telegram_backup.py >> $INSTALL_DIR/backup_cron.log 2>&1") | crontab -
        log_success "Auto-backup cronjob configured (runs every 2 hours)"
    else
        log_warning "telegram_backup.py not found, skipping cronjob setup"
    fi
}

# ============================================================================
# SERVICE FOUNDATION
# ============================================================================

# Helper function: Verify service health
verify_service() {
    local service_name=$1
    local is_critical=$2  # "critical" or "optional"
    
    log_info "Verifying $service_name..."
    
    local errors=0
    
    # Check 1: Service file exists
    if [[ -f "/etc/systemd/system/${service_name}.service" ]]; then
        log_success "  ✓ Service file exists"
    else
        log_error "  ✗ Service file not found"
        errors=$((errors + 1))
    fi
    
    # Check 2: Service is enabled
    if systemctl is-enabled --quiet $service_name 2>/dev/null; then
        log_success "  ✓ Service is enabled"
    else
        log_warning "  ! Service is not enabled"
    fi
    
    # Check 3: Service is active
    if systemctl is-active --quiet $service_name; then
        log_success "  ✓ Service is running"
    else
        log_error "  ✗ Service is not running"
        errors=$((errors + 1))
    fi
    
    # Check 4: Working directory exists
    if [[ -d "$INSTALL_DIR" ]]; then
        log_success "  ✓ Working directory exists"
    else
        log_error "  ✗ Working directory not found"
        errors=$((errors + 1))
    fi
    
    if [[ $errors -gt 0 ]]; then
        if [[ "$is_critical" == "critical" ]]; then
            log_error "$service_name verification failed with $errors error(s)"
            log_info "Check logs: journalctl -u $service_name -n 50"
            exit 1
        else
            log_warning "$service_name verification failed but continuing (optional service)"
            return 1
        fi
    fi
    
    log_success "$service_name verified successfully"
    return 0
}

# Service 1: web_ppob (critical)
install_web_ppob_service() {
    log_info "Installing web_ppob.service (CRITICAL)..."
    
    # Check executable exists
    if [[ ! -f "$INSTALL_DIR/app.py" ]]; then
        log_error "app.py not found at $INSTALL_DIR"
        exit 1
    fi
    
    cat > /etc/systemd/system/web_ppob.service << 'EOF'
[Unit]
Description=Web PPOB Garuda Tell
After=network.target

[Service]
User=root
WorkingDirectory=/root/web_ppob/paypoint
ExecStart=/root/web_ppob/paypoint/venv/bin/gunicorn --workers 3 --threads 2 --bind 0.0.0.0:2100 --timeout 120 --access-logfile - --error-logfile - app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
    
    log_success "web_ppob.service file created"
    
    systemctl daemon-reload
    log_success "Daemon reloaded"
    
    systemctl enable web_ppob
    log_success "Service enabled"
    
    set +e
    systemctl start web_ppob
    local start_exit_code=$?
    set -e
    
    if [[ $start_exit_code -eq 0 ]]; then
        log_success "Service started"
    else
        log_error "Failed to start web_ppob service"
        log_info "Check: systemctl status web_ppob"
        exit 1
    fi
    
    sleep 3
    
    verify_service "web_ppob" "critical"
}

# Service 2: subscription_worker (critical)
install_subscription_worker_service() {
    log_info "Installing subscription_worker.service (CRITICAL)..."
    
    # Check executable exists
    if [[ ! -f "$INSTALL_DIR/subscription_worker.py" ]]; then
        log_error "subscription_worker.py not found at $INSTALL_DIR"
        exit 1
    fi
    
    cat > /etc/systemd/system/subscription_worker.service << 'EOF'
[Unit]
Description=GarudaTel Subscription Worker
After=network.target web_ppob.service

[Service]
User=root
WorkingDirectory=/root/web_ppob/paypoint
ExecStart=/root/web_ppob/paypoint/venv/bin/python subscription_worker.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
    
    log_success "subscription_worker.service file created"
    
    systemctl daemon-reload
    log_success "Daemon reloaded"
    
    systemctl enable subscription_worker
    log_success "Service enabled"
    
    set +e
    systemctl start subscription_worker
    local start_exit_code=$?
    set -e
    
    if [[ $start_exit_code -eq 0 ]]; then
        log_success "Service started"
    else
        log_error "Failed to start subscription_worker service"
        log_info "Check: systemctl status subscription_worker"
        exit 1
    fi
    
    sleep 3
    
    verify_service "subscription_worker" "critical"
}

# Service 3: telegram_listener (optional - conditional)
install_telegram_listener_service() {
    log_info "Checking telegram_listener requirements..."
    
    # Check 1: telegram_listener.py exists
    if [[ ! -f "$INSTALL_DIR/telegram_listener.py" ]]; then
        log_warning "telegram_listener.py not found, skipping telegram service"
        return 0
    fi
    
    # Check 2: TELEGRAM_BOT_TOKEN exists in .env
    local has_token=false
    if [[ -f "$INSTALL_DIR/.env" ]]; then
        if grep -q "^TELEGRAM_BOT_TOKEN=" "$INSTALL_DIR/.env"; then
            local token_value=$(grep "^TELEGRAM_BOT_TOKEN=" "$INSTALL_DIR/.env" | cut -d'=' -f2- | tr -d '"' | tr -d "'" | xargs)
            if [[ -n "$token_value" && "$token_value" != "your_bot_token_here" ]]; then
                has_token=true
                log_success "TELEGRAM_BOT_TOKEN found in .env"
            fi
        fi
    fi
    
    if [[ "$has_token" != true ]]; then
        log_warning "TELEGRAM_BOT_TOKEN not configured in .env, skipping telegram service"
        return 0
    fi
    
    log_info "Installing telegram_listener.service (OPTIONAL)..."
    
    cat > /etc/systemd/system/telegram_listener.service << 'EOF'
[Unit]
Description=GarudaTel Telegram Bot Listener
After=network.target web_ppob.service

[Service]
User=root
WorkingDirectory=/root/web_ppob/paypoint
ExecStart=/root/web_ppob/paypoint/venv/bin/python telegram_listener.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
    
    log_success "telegram_listener.service file created"
    
    systemctl daemon-reload
    log_success "Daemon reloaded"
    
    systemctl enable telegram_listener
    log_success "Service enabled"
    
    set +e
    systemctl start telegram_listener
    local start_exit_code=$?
    set -e
    
    if [[ $start_exit_code -eq 0 ]]; then
        log_success "Service started"
    else
        log_warning "Failed to start telegram_listener service (optional, continuing)"
        log_info "Check: systemctl status telegram_listener"
    fi
    
    sleep 3
    
    # Non-critical verification
    if verify_service "telegram_listener" "optional"; then
        log_success "Telegram listener service is running"
    else
        log_warning "Telegram listener failed but installation will continue"
    fi
}

# Main service foundation function
setup_service_foundation() {
    log_phase "PHASE 9: SERVICE FOUNDATION"
    
    cd "$INSTALL_DIR"
    
    log_info "Installing GarudaTel Enterprise Services..."
    echo ""
    
    # Install critical services
    install_web_ppob_service
    echo ""
    
    install_subscription_worker_service
    echo ""
    
    # Install optional service
    install_telegram_listener_service
    echo ""
    
    # Summary
    log_info "Service Foundation Summary:"
    log_info "  web_ppob: $(systemctl is-active web_ppob)"
    log_info "  subscription_worker: $(systemctl is-active subscription_worker)"
    
    if systemctl list-unit-files | grep -q "telegram_listener.service"; then
        log_info "  telegram_listener: $(systemctl is-active telegram_listener)"
    else
        log_info "  telegram_listener: not installed"
    fi
    
    log_success "Service foundation ready"
}

# ============================================================================
# CLOUDFLARE TUNNEL SETUP
# ============================================================================
# CATATAN: Cloudflare Tunnel adalah OPTIONAL layer.
# Token dimasukkan melalui Admin Panel SETELAH aplikasi berjalan.
# Installer TIDAK meminta token dan TIDAK memblokir jika token kosong.
# Alur: Fresh Install → Web aktif → http://IP:2100 → Login Admin →
#        Admin Panel → Cloudflare → Masukkan Token → Aktifkan Tunnel
# ============================================================================
setup_cloudflare_tunnel() {
    log_phase "PHASE 10: CLOUDFLARE TUNNEL SETUP (OPTIONAL)"

    # Jika service cloudflared sudah ada dan aktif, jangan sentuh.
    if systemctl cat cloudflared.service > /dev/null 2>&1; then
        if systemctl is-active --quiet cloudflared; then
            log_success "Cloudflare Tunnel sudah aktif (existing) — tidak disentuh"
            return 0
        fi
        log_warning "Cloudflare service ada tapi tidak aktif — tidak disentuh"
        log_info "Konfigurasi via Admin Panel → Cloudflare setelah login"
        return 0
    fi

    # Tidak ada cloudflared — install binary saja tanpa token, tanpa service aktif.
    # Token akan dikonfigurasi dari Admin Panel.
    log_info "Menginstall cloudflared binary (tanpa token, tanpa service aktif)..."

    set +e
    curl -fL --output /tmp/cloudflared_rc6.deb \
        "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb" \
        --max-time 60 2>/dev/null
    local curl_exit=$?
    set -e

    if [[ $curl_exit -ne 0 ]] || [[ ! -s "/tmp/cloudflared_rc6.deb" ]]; then
        rm -f /tmp/cloudflared_rc6.deb
        log_warning "Download cloudflared gagal (jaringan/GitHub timeout)"
        log_warning "cloudflared tidak diinstall — OK, bisa install manual nanti"
        log_info "Konfigurasi Cloudflare via Admin Panel → Cloudflare setelah login"
        return 0
    fi

    set +e
    dpkg -i /tmp/cloudflared_rc6.deb > /dev/null 2>&1
    local dpkg_exit=$?
    set -e
    rm -f /tmp/cloudflared_rc6.deb

    if [[ $dpkg_exit -ne 0 ]]; then
        log_warning "Install cloudflared package gagal — OK, bisa install manual nanti"
        return 0
    fi

    log_success "cloudflared binary terinstall (service BELUM aktif — menunggu token)"
    log_info ""
    log_info "  Untuk mengaktifkan Cloudflare Tunnel:"
    log_info "    1. Buka http://IP-VPS:2100"
    log_info "    2. Login Admin"
    log_info "    3. Admin Panel → Cloudflare"
    log_info "    4. Masukkan Tunnel Token"
    log_info "    5. Klik Aktifkan"
}

# ============================================================================
# INSTALLATION CERTIFICATION
# ============================================================================
installation_certification() {
    log_phase "PHASE 11: INSTALLATION CERTIFICATION"
    
    cd "$INSTALL_DIR"
    
    local total_checks=0
    local passed_checks=0
    local failed_checks=0
    local skipped_checks=0
    local critical_failed=0
    
    declare -a report_lines
    
    echo ""
    log_info "Running certification checks..."
    echo ""
    
    # Check 1: Flask Service Health
    log_info "Check 1/9: Flask service health..."
    total_checks=$((total_checks + 1))
    
    # Get port from .env
    local flask_port=2100
    if [[ -f ".env" ]] && grep -q "^PORT=" .env; then
        flask_port=$(grep "^PORT=" .env | cut -d'=' -f2 | tr -d '"' | tr -d "'" | xargs)
    fi
    
    if curl -s --max-time 10 "http://localhost:${flask_port}" &>/dev/null; then
        log_success "Flask service responds on port $flask_port"
        report_lines+=("[✓] Flask Service           PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_error "Flask service not responding on port $flask_port"
        report_lines+=("[✗] Flask Service           FAILED")
        failed_checks=$((failed_checks + 1))
        critical_failed=$((critical_failed + 1))
    fi
    
    # Check 2: Database Integrity
    log_info "Check 2/9: Database integrity..."
    total_checks=$((total_checks + 1))
    
    if [[ -f "paypoint.db" ]]; then
        if sqlite3 paypoint.db "SELECT 1;" &>/dev/null; then
            log_success "Database opens and responds correctly"
            report_lines+=("[✓] Database Integrity      PASS")
            passed_checks=$((passed_checks + 1))
        else
            log_error "Database is corrupted or cannot execute queries"
            report_lines+=("[✗] Database Integrity      FAILED")
            failed_checks=$((failed_checks + 1))
            critical_failed=$((critical_failed + 1))
        fi
    else
        log_error "Database file not found"
        report_lines+=("[✗] Database Integrity      FAILED")
        failed_checks=$((failed_checks + 1))
        critical_failed=$((critical_failed + 1))
    fi
    
    # Check 3: ConfigManager Import
    log_info "Check 3/9: ConfigManager import..."
    total_checks=$((total_checks + 1))
    
    source venv/bin/activate
    
    if python3 -c "from config_manager import ConfigManager; cm = ConfigManager(); cm.load_config()" 2>/dev/null; then
        log_success "ConfigManager imports and loads correctly"
        report_lines+=("[✓] ConfigManager           PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_warning "ConfigManager import failed (non-critical)"
        report_lines+=("[!] ConfigManager           WARNING")
        skipped_checks=$((skipped_checks + 1))
    fi
    
    # Check 4: Python Dependencies
    log_info "Check 4/9: Python dependencies..."
    total_checks=$((total_checks + 1))
    
    if pip_check_output=$(pip check 2>&1); then
        log_success "All Python dependencies are consistent"
        report_lines+=("[✓] Python Dependencies     PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_warning "Dependency conflicts detected but continuing"
        report_lines+=("[!] Python Dependencies     WARNING")
        skipped_checks=$((skipped_checks + 1))
    fi
    
    # Check 5: web_ppob Service
    log_info "Check 5/9: web_ppob service..."
    total_checks=$((total_checks + 1))
    
    if systemctl is-active --quiet web_ppob; then
        log_success "web_ppob service is active"
        report_lines+=("[✓] web_ppob Service        PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_error "web_ppob service is not active"
        report_lines+=("[✗] web_ppob Service        FAILED")
        failed_checks=$((failed_checks + 1))
        critical_failed=$((critical_failed + 1))
    fi
    
    # Check 6: subscription_worker Service
    log_info "Check 6/9: subscription_worker service..."
    total_checks=$((total_checks + 1))
    
    if systemctl is-active --quiet subscription_worker; then
        log_success "subscription_worker service is active"
        report_lines+=("[✓] subscription_worker     PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_error "subscription_worker service is not active"
        report_lines+=("[✗] subscription_worker     FAILED")
        failed_checks=$((failed_checks + 1))
        critical_failed=$((critical_failed + 1))
    fi
    
    # Check 7: telegram_listener Service (optional)
    log_info "Check 7/9: telegram_listener service..."
    total_checks=$((total_checks + 1))
    
    if systemctl list-unit-files | grep -q "telegram_listener.service"; then
        if systemctl is-active --quiet telegram_listener; then
            log_success "telegram_listener service is active"
            report_lines+=("[✓] telegram_listener       PASS")
            passed_checks=$((passed_checks + 1))
        else
            log_warning "telegram_listener service is not active (optional)"
            report_lines+=("[!] telegram_listener       WARNING")
            skipped_checks=$((skipped_checks + 1))
        fi
    else
        log_info "telegram_listener not configured (skipped)"
        report_lines+=("[○] telegram_listener       SKIPPED")
        skipped_checks=$((skipped_checks + 1))
    fi
    
    # Check 8: Working Directory
    log_info "Check 8/9: Working directory..."
    total_checks=$((total_checks + 1))
    
    if [[ -d "$INSTALL_DIR" ]]; then
        log_success "Working directory exists: $INSTALL_DIR"
        report_lines+=("[✓] Working Directory       PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_error "Working directory not found"
        report_lines+=("[✗] Working Directory       FAILED")
        failed_checks=$((failed_checks + 1))
        critical_failed=$((critical_failed + 1))
    fi
    
    # Check 9: Database File
    log_info "Check 9/9: Database file..."
    total_checks=$((total_checks + 1))
    
    if [[ -f "$INSTALL_DIR/paypoint.db" ]]; then
        db_size=$(du -h "$INSTALL_DIR/paypoint.db" | cut -f1)
        log_success "Database file exists: $db_size"
        report_lines+=("[✓] Database File           PASS")
        passed_checks=$((passed_checks + 1))
    else
        log_error "Database file not found"
        report_lines+=("[✗] Database File           FAILED")
        failed_checks=$((failed_checks + 1))
        critical_failed=$((critical_failed + 1))
    fi
    
    # Generate Certification Report
    echo ""
    echo "============================================================================"
    echo "  INSTALLATION CERTIFICATION REPORT"
    echo "  Generated: $(date '+%Y-%m-%d %H:%M:%S')"
    echo "============================================================================"
    
    for line in "${report_lines[@]}"; do
        echo "$line"
    done
    
    echo "----------------------------------------------------------------------------"
    
    # Calculate health score
    local scorable_checks=$((total_checks - skipped_checks))
    local health_score=0
    if [[ $scorable_checks -gt 0 ]]; then
        health_score=$((passed_checks * 100 / scorable_checks))
    fi
    
    echo "Total Checks: $total_checks"
    echo "Passed: $passed_checks"
    echo "Failed: $failed_checks"
    echo "Warnings: $skipped_checks"
    echo "Health Score: $health_score%"
    echo ""
    
    # Final Status
    if [[ $critical_failed -gt 0 ]]; then
        echo -e "${RED}Status: INSTALLATION FAILED${NC}"
        echo "============================================================================"
        echo ""
        log_error "Installation certification FAILED with $critical_failed critical error(s)"
        log_info "Troubleshooting:"
        log_info "  - Check service logs: journalctl -u web_ppob -n 50"
        log_info "  - Check service status: systemctl status web_ppob"
        log_info "  - Check database: sqlite3 $INSTALL_DIR/paypoint.db '.tables'"
        exit 1
    elif [[ $failed_checks -gt 0 ]]; then
        echo -e "${YELLOW}Status: SERVER READY (with warnings)${NC}"
        echo "============================================================================"
        echo ""
        log_warning "Installation completed with $failed_checks non-critical warning(s)"
    else
        echo -e "${GREEN}Status: SERVER READY ✓${NC}"
        echo "============================================================================"
        echo ""
        log_success "Installation certified successfully!"
    fi
}

# ============================================================================
# MAIN INSTALLATION FLOW
# ============================================================================
main() {
    echo ""
    echo "============================================================================"
    echo "  🔥 GARUDA TELL ENTERPRISE INSTALLER V2"
    echo "  Version: 2.0.0"
    echo "  Production-Grade Installation System"
    echo "============================================================================"
    echo ""
    
    preflight_check
    validate_project_structure
    configuration_foundation
    install_system_dependencies
    setup_python_environment
    database_foundation
    verify_dependencies
    setup_cronjob
    setup_service_foundation
    setup_cloudflare_tunnel
    installation_certification
    
    log_phase "INSTALLATION COMPLETE"
    log_success "GarudaTel Enterprise RC6 FIXED sekarang berjalan!"

    # Deteksi public IP untuk URL testing
    local PUBLIC_IP=""
    PUBLIC_IP=$(curl -s --max-time 5 https://api.ipify.org 2>/dev/null || true)
    if [[ -z "$PUBLIC_IP" ]]; then
        PUBLIC_IP=$(curl -s --max-time 5 https://ifconfig.me 2>/dev/null || true)
    fi
    if [[ -z "$PUBLIC_IP" ]]; then
        PUBLIC_IP="<IP-VPS-ANDA>"
    fi

    echo ""
    echo "============================================================================"
    echo "  TESTING URL"
    echo "============================================================================"
    echo ""
    echo "  Local (dari VPS)  : http://127.0.0.1:2100"
    echo "  Public (browser)  : http://${PUBLIC_IP}:2100"
    echo ""
    echo "  Credential default:"
    echo "    Username : admin"
    echo "    Password : admin123"
    echo ""
    echo "  PENTING: Ganti password setelah login pertama!"
    echo ""
    echo "  Cloudflare Tunnel (optional):"
    echo "    1. Login Admin Panel"
    echo "    2. Admin Panel → Cloudflare"
    echo "    3. Masukkan Tunnel Token → Aktifkan"
    echo "============================================================================"
    echo ""
    log_info "Services:"
    log_info "  - systemctl status web_ppob"
    log_info "  - systemctl status subscription_worker"
    if systemctl list-unit-files | grep -q "telegram_listener.service"; then
        log_info "  - systemctl status telegram_listener"
    fi
    log_info "Logs:"
    log_info "  - journalctl -u web_ppob -f"
    log_info "  - journalctl -u subscription_worker -f"
    log_info "Uninstall:"
    log_info "  - bash /root/uninstall_rc6.sh"
    echo ""
}

# ============================================================================
# EXECUTE
# ============================================================================
main
