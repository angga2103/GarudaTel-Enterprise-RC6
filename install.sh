#!/bin/bash
# ============================================================================
# GarudaTel Enterprise - INTERNAL INSTALLER
# Version: 1.0.0
# Purpose: Copy package to target and launch installer_vps_baru.sh
# Note: This script runs from temporary extraction directory
# ============================================================================

set -e  # Exit on error
set -u  # Exit on undefined variable

# ============================================================================
# CONFIGURATION
# ============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_DIR="/root/web_ppob/paypoint"

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

log_step() {
    echo -e "${GREEN}$1${NC}"
}

# ============================================================================
# MAIN INSTALLATION FLOW
# ============================================================================
main() {
    echo ""
    echo "============================================================================"
    echo "  🔥 GARUDA TELL ENTERPRISE - INTERNAL INSTALLER"
    echo "  Version: 1.0.0"
    echo "============================================================================"
    echo ""
    
    log_info "Script running from: $SCRIPT_DIR"
    
    # Step 1: Validate we have all required files in current directory
    log_step "[1/3] Validating package files..."
    
    local critical_files=(
        "installer_vps_baru.sh"
        "app.py"
        "requirements.txt"
    )
    
    local missing=0
    
    for file in "${critical_files[@]}"; do
        if [[ ! -f "$SCRIPT_DIR/$file" ]]; then
            log_error "Missing critical file: $file"
            ((missing++))
        fi
    done
    
    if [[ $missing -gt 0 ]]; then
        log_error "Package validation failed"
        exit 1
    fi
    
    log_success "All critical files found"
    
    # Step 2: Check target directory
    log_step "[2/3] Checking target directory..."
    
    if [[ -d "$TARGET_DIR" ]]; then
        # Check if existing installation
        if [[ -f "$TARGET_DIR/paypoint.db" ]] || [[ -f "$TARGET_DIR/app.py" ]]; then
            log_error "Target directory already contains an existing installation"
            log_error "Location: $TARGET_DIR"
            echo ""
            log_info "To protect your data, this installer will NOT overwrite existing files."
            echo ""
            log_info "Options:"
            log_info "  1. Backup and remove existing installation:"
            log_info "     mv $TARGET_DIR $TARGET_DIR.backup_$(date +%Y%m%d_%H%M%S)"
            log_info "  2. Use a different target directory"
            echo ""
            exit 1
        else
            log_info "Target directory exists but is empty"
        fi
    else
        log_info "Creating target directory: $TARGET_DIR"
        mkdir -p "$TARGET_DIR"
        log_success "Target directory created"
    fi
    
    # Step 3: Copy package to target directory
    log_step "[3/3] Copying package to target directory..."
    
    cp -r "$SCRIPT_DIR"/* "$TARGET_DIR/"
    
    # Copy hidden files if any
    if ls "$SCRIPT_DIR"/.[!.]* 1> /dev/null 2>&1; then
        cp -r "$SCRIPT_DIR"/.[!.]* "$TARGET_DIR/" 2>/dev/null || true
    fi
    
    log_success "Package copied to $TARGET_DIR"
    
    # Make installer executable
    chmod +x "$TARGET_DIR/installer_vps_baru.sh"
    
    # Launch installer_vps_baru.sh
    echo ""
    echo "============================================================================"
    log_success "Package deployment complete!"
    log_info "Launching installer_vps_baru.sh..."
    echo "============================================================================"
    echo ""
    
    # Change to target directory and run installer
    cd "$TARGET_DIR"
    exec bash "$TARGET_DIR/installer_vps_baru.sh"
}

# ============================================================================
# EXECUTE
# ============================================================================
# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This installer must be run as root"
    log_info "Usage: sudo bash install.sh"
    exit 1
fi

main
