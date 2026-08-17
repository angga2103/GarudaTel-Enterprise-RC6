"""Configuration Manager - Single engine untuk manajemen konfigurasi sistem.

Digunakan oleh semua provider (Digiflazz, PaymentKita, Pakasir, Telegram, Firebase).

Features:
- Provider abstraction dengan schema
- Configuration load/update dengan backup otomatis
- Dirty state tracking untuk perubahan unsaved
- Backup metadata dengan checksum dan versioning
- Single source of truth untuk semua konfigurasi provider
"""
import os
import shutil
import json
import hashlib
from datetime import datetime
from typing import Dict, Optional, List, Any
from dataclasses import dataclass, asdict


from dataclasses import dataclass, asdict


@dataclass
class ProviderSchema:
    """Schema untuk provider configuration.

    Attributes:
        provider_name: Nama provider (misal: digiflazz, paymentkita)
        description: Deskripsi provider
        required_keys: List key .env yang wajib ada
        optional_keys: List key .env yang optional
    """
    provider_name: str
    description: str
    required_keys: List[str]
    optional_keys: List[str] = None

    def __post_init__(self):
        if self.optional_keys is None:
            self.optional_keys = []


# Provider schema registry - Single source of truth untuk semua provider
PROVIDER_SCHEMAS = {
    "digiflazz": ProviderSchema(
        provider_name="digiflazz",
        description="Provider PPOB Digiflazz untuk pulsa, token, dan produk digital",
        required_keys=["DIGIFLAZZ_USER", "DIGIFLAZZ_KEY"],
        optional_keys=[]
    ),
    "paymentkita": ProviderSchema(
        provider_name="paymentkita",
        description="Payment gateway dan QRIS otomatis PaymentKita",
        required_keys=["PAYMENTKITA_MERCHANT", "PAYMENTKITA_SECRET"],
        optional_keys=[]
    ),
    "pakasir": ProviderSchema(
        provider_name="pakasir",
        description="Sistem kasir dan pembayaran offline Pakasir",
        required_keys=["PAKASIR_KEY", "PAKASIR_PROJECT"],
        optional_keys=[]
    ),
    "telegram": ProviderSchema(
        provider_name="telegram",
        description="Bot Telegram untuk notifikasi dan customer service",
        required_keys=["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"],
        optional_keys=[]
    ),
    "firebase": ProviderSchema(
        provider_name="firebase",
        description="Firebase Cloud Messaging untuk push notification",
        required_keys=["FIREBASE_PROJECT_ID", "FIREBASE_PRIVATE_KEY"],
        optional_keys=["FIREBASE_CLIENT_EMAIL"]
    ),
    "cloudflare": ProviderSchema(
        provider_name="cloudflare",
        description="Cloudflare Zero Trust Tunnel untuk secure access",
        required_keys=["CLOUDFLARE_TUNNEL_TOKEN"],
        optional_keys=["CLOUDFLARE_TUNNEL_NAME", "CLOUDFLARE_ACCOUNT_ID"]
    ),
    "whatsapp": ProviderSchema(
        provider_name="whatsapp",
        description="WhatsApp Communication Center untuk broadcast dan notifikasi",
        required_keys=["WHATSAPP_API_URL", "WHATSAPP_API_KEY"],
        optional_keys=["WHATSAPP_INSTANCE_NAME", "WHATSAPP_PHONE_NUMBER"]
    ),
}


@dataclass
class BackupMetadata:
    """Metadata untuk backup configuration.

    Attributes:
        filename: Nama file backup
        created_at: Timestamp pembuatan backup
        checksum: MD5 checksum dari file backup
        version: Versi backup (auto-increment)
    """
    filename: str
    created_at: str
    checksum: str
    version: int


class ConfigManager:
    """Configuration Manager untuk load, update, backup, dan restore .env

    Features:
    - Provider abstraction dengan schema validation
    - Dirty state tracking untuk unsaved changes
    - Backup dengan metadata (checksum, version)
    - Single source of truth untuk semua provider

    Usage:
        cm = ConfigManager()

        # Get provider config
        provider = cm.get_provider("digiflazz")

        # Update config
        cm.update_config({"DIGIFLAZZ_USER": "newuser"})

        # Check unsaved changes
        if cm.has_unsaved_changes():
            cm.save_config()
    """

    def __init__(self, env_path: Optional[str] = None):
        """
        Initialize ConfigManager.

        Args:
            env_path: Path ke file .env. Default: .env di directory paypoint
        """
        if env_path:
            self.env_path = env_path
        else:
            # Default path: cari .env di directory paypoint
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.env_path = os.path.join(base_dir, ".env")

        self.backup_dir = os.path.join(os.path.dirname(self.env_path), ".env_backups")
        self.metadata_file = os.path.join(self.backup_dir, "backup_metadata.json")
        os.makedirs(self.backup_dir, exist_ok=True)

        # Dirty state tracking
        self._dirty = False
        self._pending_changes = {}

        # Load initial config state
        self._initial_config = self.load_config()

    def get_provider(self, provider_name: str) -> Optional[Dict[str, Any]]:
        """
        Get konfigurasi provider beserta schema dan status validasi.

        Args:
            provider_name: Nama provider (digiflazz, paymentkita, pakasir, telegram, firebase)

        Returns:
            Dictionary berisi:
            - schema: ProviderSchema
            - config: Dict key-value dari .env untuk provider ini
            - validation: Dict status validasi per-key
            - is_configured: Boolean apakah provider sudah dikonfigurasi lengkap

            None jika provider tidak ditemukan
        """
        if provider_name not in PROVIDER_SCHEMAS:
            return None

        schema = PROVIDER_SCHEMAS[provider_name]
        config = self.load_config()

        # Ambil config untuk provider ini saja
        provider_config = {}
        all_keys = schema.required_keys + schema.optional_keys
        for key in all_keys:
            provider_config[key] = config.get(key, "")

        # Validasi required keys
        validation = self.validate_keys(schema.required_keys)
        is_configured = all(validation.values())

        return {
            "schema": schema,
            "config": provider_config,
            "validation": validation,
            "is_configured": is_configured
        }

    def list_providers(self) -> List[str]:
        """
        List semua provider yang tersedia.

        Returns:
            List nama provider
        """
        return list(PROVIDER_SCHEMAS.keys())

    def get_provider_schema(self, provider_name: str) -> Optional[ProviderSchema]:
        """
        Get schema untuk provider tertentu.

        Args:
            provider_name: Nama provider

        Returns:
            ProviderSchema atau None jika tidak ditemukan
        """
        return PROVIDER_SCHEMAS.get(provider_name)

    def has_unsaved_changes(self) -> bool:
        """
        Check apakah ada perubahan yang belum disimpan.

        Returns:
            True jika ada perubahan pending, False jika tidak
        """
        return self._dirty

    def set_dirty(self, updates: Optional[Dict[str, str]] = None):
        """
        Mark configuration sebagai dirty (ada perubahan belum disimpan).

        Args:
            updates: Optional dict perubahan yang akan di-track
        """
        self._dirty = True
        if updates:
            self._pending_changes.update(updates)

    def clear_dirty(self):
        """
        Clear dirty state (setelah save atau cancel).
        """
        self._dirty = False
        self._pending_changes = {}

    def get_pending_changes(self) -> Dict[str, str]:
        """
        Get perubahan yang belum disimpan.

        Returns:
            Dictionary berisi key-value yang pending
        """
        return self._pending_changes.copy()

    def load_config(self) -> Dict[str, str]:
        """
        Load konfigurasi dari file .env.

        Returns:
            Dictionary berisi key-value dari .env
        """
        config = {}

        if not os.path.exists(self.env_path):
            return config

        try:
            with open(self.env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip comment dan empty line
                    if not line or line.startswith('#'):
                        continue

                    # Parse key=value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        config[key] = value
        except Exception as e:
            raise RuntimeError(f"Failed to load config from {self.env_path}: {e}")

        return config

    def get_value(self, key: str, default: str = "") -> str:
        """
        Get value dari konfigurasi.

        Args:
            key: Key yang dicari
            default: Default value jika key tidak ditemukan

        Returns:
            Value dari key atau default
        """
        config = self.load_config()
        return config.get(key, default)

    def update_config(self, updates: Dict[str, str], backup: bool = True) -> bool:
        """
        Update konfigurasi di .env.

        Args:
            updates: Dictionary berisi key-value yang akan diupdate
            backup: Backup .env sebelum update (default: True)

        Returns:
            True jika berhasil, False jika gagal
        """
        if not os.path.exists(self.env_path):
            return False

        # Mark as dirty
        self.set_dirty(updates)

        # Backup dulu jika diminta
        if backup:
            self.backup_config()

        try:
            # Baca seluruh file
            with open(self.env_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            # Update line yang sesuai
            updated_keys = set()
            new_lines = []

            for line in lines:
                stripped = line.strip()

                # Preserve comment dan empty line
                if not stripped or stripped.startswith('#'):
                    new_lines.append(line)
                    continue

                # Parse key
                if '=' in stripped:
                    key = stripped.split('=', 1)[0].strip()

                    if key in updates:
                        # Update value
                        new_value = updates[key]
                        new_lines.append(f"{key}={new_value}\n")
                        updated_keys.add(key)
                    else:
                        # Keep original
                        new_lines.append(line)
                else:
                    new_lines.append(line)

            # Tambah key baru yang belum ada
            for key, value in updates.items():
                if key not in updated_keys:
                    new_lines.append(f"{key}={value}\n")

            # Write back
            with open(self.env_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)

            # Update os.environ juga
            for key, value in updates.items():
                os.environ[key] = value

            # Clear dirty state setelah save berhasil
            self.clear_dirty()

            # Update initial config
            self._initial_config = self.load_config()

            return True

        except Exception as e:
            raise RuntimeError(f"Failed to update config: {e}")

    def validate_keys(self, required_keys: List[str]) -> Dict[str, bool]:
        """
        Validasi apakah key yang diperlukan sudah ada dan terisi.

        Args:
            required_keys: List key yang wajib ada

        Returns:
            Dictionary berisi key dan status validasinya (True/False)
        """
        config = self.load_config()
        result = {}

        for key in required_keys:
            value = config.get(key, "")
            # Valid jika key ada dan value tidak kosong
            result[key] = bool(value)

        return result

    def backup_config(self) -> str:
        """
        Backup file .env dengan timestamp dan metadata.

        Returns:
            Path ke file backup
        """
        if not os.path.exists(self.env_path):
            raise FileNotFoundError(f".env not found at {self.env_path}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f".env.backup_{timestamp}"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        try:
            # Copy file
            shutil.copy2(self.env_path, backup_path)

            # Calculate checksum
            checksum = self._calculate_checksum(backup_path)

            # Get version (auto-increment)
            version = self._get_next_backup_version()

            # Save metadata
            metadata = BackupMetadata(
                filename=backup_filename,
                created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                checksum=checksum,
                version=version
            )
            self._save_backup_metadata(metadata)

            return backup_path
        except Exception as e:
            raise RuntimeError(f"Failed to backup config: {e}")

    def _calculate_checksum(self, filepath: str) -> str:
        """Calculate MD5 checksum dari file."""
        md5 = hashlib.md5()
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b""):
                md5.update(chunk)
        return md5.hexdigest()

    def _get_next_backup_version(self) -> int:
        """Get next backup version number."""
        metadata_list = self._load_all_backup_metadata()
        if not metadata_list:
            return 1
        max_version = max(m["version"] for m in metadata_list)
        return max_version + 1

    def _save_backup_metadata(self, metadata: BackupMetadata):
        """Save backup metadata ke file JSON."""
        # Load existing metadata
        metadata_list = self._load_all_backup_metadata()

        # Add new metadata
        metadata_list.append(asdict(metadata))

        # Save back
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(metadata_list, f, indent=2)

    def _load_all_backup_metadata(self) -> List[Dict[str, Any]]:
        """Load semua backup metadata dari file JSON."""
        if not os.path.exists(self.metadata_file):
            return []

        try:
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return []

    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List semua backup yang tersedia dengan metadata lengkap.

        Returns:
            List dictionary berisi info backup (filename, path, timestamp, checksum, version)
        """
        backups = []

        if not os.path.exists(self.backup_dir):
            return backups

        # Load metadata
        metadata_list = self._load_all_backup_metadata()
        metadata_dict = {m["filename"]: m for m in metadata_list}

        try:
            for filename in os.listdir(self.backup_dir):
                if filename.startswith(".env.backup_"):
                    filepath = os.path.join(self.backup_dir, filename)

                    # Get metadata jika ada
                    if filename in metadata_dict:
                        meta = metadata_dict[filename]
                        backups.append({
                            "filename": filename,
                            "path": filepath,
                            "timestamp": meta.get("created_at", ""),
                            "checksum": meta.get("checksum", ""),
                            "version": meta.get("version", 0)
                        })
                    else:
                        # Fallback ke file metadata jika tidak ada di JSON
                        mtime = os.path.getmtime(filepath)
                        timestamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                        backups.append({
                            "filename": filename,
                            "path": filepath,
                            "timestamp": timestamp,
                            "checksum": "",
                            "version": 0
                        })

            # Sort by version descending (newest first)
            backups.sort(key=lambda x: x.get("version", 0), reverse=True)

        except Exception as e:
            raise RuntimeError(f"Failed to list backups: {e}")

        return backups

    def restore_config(self, backup_path: str) -> bool:
        """
        Restore .env dari backup.

        Args:
            backup_path: Path ke file backup

        Returns:
            True jika berhasil, False jika gagal
        """
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_path}")

        try:
            # Backup current .env dulu sebelum restore
            if os.path.exists(self.env_path):
                self.backup_config()

            # Restore dari backup
            shutil.copy2(backup_path, self.env_path)

            # Reload environment variables
            self._reload_env()

            return True

        except Exception as e:
            raise RuntimeError(f"Failed to restore config: {e}")

    def _reload_env(self):
        """Reload environment variables dari .env yang baru."""
        config = self.load_config()
        for key, value in config.items():
            os.environ[key] = value

    def backup_env(self) -> str:
        """
        Backup .env file. Alias untuk backup_config() untuk backward compatibility.

        Returns:
            Backup filename (not full path)
        """
        backup_path = self.backup_config()
        return os.path.basename(backup_path)

    def restore_backup(self, backup_filename: str) -> bool:
        """
        Restore dari backup file. Security: validate filename untuk prevent path traversal.

        Args:
            backup_filename: Nama file backup (e.g., .env.backup_20260817_123456)

        Returns:
            True jika berhasil
        """
        import re

        # Security: validate filename format (no path traversal)
        if not re.match(r'^\.env\.backup_\d{8}_\d{6}$', backup_filename):
            raise ValueError("Invalid backup filename format")

        # Security: prevent path traversal
        if '..' in backup_filename or '/' in backup_filename or '\\' in backup_filename:
            raise ValueError("Invalid backup filename: path traversal detected")

        # Construct safe path
        backup_path = os.path.join(self.backup_dir, backup_filename)

        # Verify file exists and is within backup directory
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found: {backup_filename}")

        # Verify path is within backup directory (additional security)
        real_backup_path = os.path.realpath(backup_path)
        real_backup_dir = os.path.realpath(self.backup_dir)
        if not real_backup_path.startswith(real_backup_dir):
            raise ValueError("Invalid backup path: outside backup directory")

        # Restore
        return self.restore_config(backup_path)


# Global instance (optional, untuk kemudahan akses)
_default_manager = None

def get_config_manager() -> ConfigManager:
    """Get global ConfigManager instance."""
    global _default_manager
    if _default_manager is None:
        _default_manager = ConfigManager()
    return _default_manager
