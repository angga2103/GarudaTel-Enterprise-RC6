"""SQLite database layer for PayPoint."""
import os
import sqlite3
import bcrypt
from datetime import datetime
from typing import Optional
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

DB_PATH = os.path.join(os.path.dirname(__file__), "paypoint.db")


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class User(UserMixin):
    def __init__(self, row):
        self.id = row["id"]
        self.google_id = row["google_id"]
        self.username = row["username"]
        self.password_hash = row["password_hash"]
        self.email = row["email"]
        self.balance = row["balance"]
        self.role = row["role"]
        self.created_at = row["created_at"]
        self.pin = row["pin"] if "pin" in row.keys() else "123456"
        self.status = row["status"] if "status" in row.keys() else "active"
        self.whatsapp = row["whatsapp"] if "whatsapp" in row.keys() else ""
        self.level = row["level"] if "level" in row.keys() else "reguler"
        self.shop_name = row["shop_name"] if "shop_name" in row.keys() else ""
        self.shop_address = row["shop_address"] if "shop_address" in row.keys() else ""
        self.store_name = row["store_name"] if "store_name" in row.keys() else "Garuda Tell"
        self.theme_color = row["theme_color"] if "theme_color" in row.keys() else "#115E59"
        self.markup_profit = row["markup_profit"] if "markup_profit" in row.keys() else 0
        self.pin_staff1 = row["pin_staff1"] if "pin_staff1" in row.keys() else ""
        self.pin_staff2 = row["pin_staff2"] if "pin_staff2" in row.keys() else ""
        self.nama_staff1 = row["nama_staff1"] if "nama_staff1" in row.keys() else "Staff 1"
        self.nama_staff2 = row["nama_staff2"] if "nama_staff2" in row.keys() else "Staff 2"
        self.active_shift_id = row["active_shift_id"] if "active_shift_id" in row.keys() else 0
        self.force_pin_change = row["force_pin_change"] if "force_pin_change" in row.keys() else 0 

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)
    
    def check_pin(self, pin_input: str, auto_migrate: bool = True) -> bool:
        """
        Verify PIN with backward compatibility for plaintext PINs.
        
        Args:
            pin_input: PIN to verify
            auto_migrate: Auto-upgrade plaintext to bcrypt on success
        
        Returns:
            True if PIN matches, False otherwise
        """
        if not self.pin:
            return False
        
        pin_input_clean = str(pin_input).strip()
        pin_stored = str(self.pin).strip()
        
        # Check if stored PIN is bcrypt hash (starts with $2a$, $2b$, or $2y$)
        is_bcrypt = pin_stored.startswith('$2')
        
        if is_bcrypt:
            # Verify bcrypt hash
            try:
                return bcrypt.checkpw(pin_input_clean.encode('utf-8'), pin_stored.encode('utf-8'))
            except:
                return False
        else:
            # Legacy plaintext PIN - direct comparison
            if pin_input_clean == pin_stored:
                # Auto-migrate to bcrypt on successful verification
                if auto_migrate:
                    try:
                        pin_hash = bcrypt.hashpw(pin_input_clean.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                        conn = get_conn()
                        conn.execute("UPDATE users SET pin=? WHERE id=?", (pin_hash, self.id))
                        conn.commit()
                        conn.close()
                        # Update in-memory object
                        self.pin = pin_hash
                    except:
                        pass  # Migration failed, but authentication succeeded
                return True
            return False

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def init_db() -> None:
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            email TEXT,
            balance INTEGER NOT NULL DEFAULT 0,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            pin TEXT DEFAULT '123456',
            pin_staff1 TEXT DEFAULT '',
            pin_staff2 TEXT DEFAULT '',
            force_pin_change INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            whatsapp TEXT DEFAULT '',
            level TEXT DEFAULT 'reguler',
            shop_name TEXT DEFAULT '',
            shop_address TEXT DEFAULT '',
            store_name TEXT DEFAULT 'Garuda Tell',
            theme_color TEXT DEFAULT '#115E59',
            markup_profit INTEGER DEFAULT 0,
            nama_staff1 TEXT DEFAULT 'Staff 1',
            nama_staff2 TEXT DEFAULT 'Staff 2',
            active_shift_id INTEGER DEFAULT 0,
            fcm_token TEXT,
            pin_admin TEXT
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            type TEXT NOT NULL,
            base_price INTEGER NOT NULL DEFAULT 0,
            price INTEGER NOT NULL DEFAULT 0,
            margin INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            is_langganan INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            uid INTEGER NOT NULL,
            sku TEXT NOT NULL,
            name TEXT NOT NULL,
            target TEXT NOT NULL,
            price INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            sn TEXT,
            kind TEXT NOT NULL DEFAULT 'purchase',
            message TEXT,
            kasir_name TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS digiflazz_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT,
            endpoint TEXT NOT NULL,
            request_body TEXT,
            response_body TEXT,
            status_code INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            order_id TEXT UNIQUE NOT NULL,
            amount INTEGER NOT NULL,
            qris_data TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            paid_at TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS pricelist_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            brand TEXT NOT NULL,
            type TEXT NOT NULL,
            seller_name TEXT,
            price INTEGER NOT NULL,
            buyer_sku_code TEXT,
            buyer_product_status INTEGER DEFAULT 1,
            seller_product_status INTEGER DEFAULT 1,
            unlimited_stock INTEGER DEFAULT 1,
            stock INTEGER DEFAULT 0,
            multi INTEGER DEFAULT 0,
            start_cut_off TEXT,
            end_cut_off TEXT,
            description TEXT,
            cached_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS mutations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            balance_before INTEGER NOT NULL DEFAULT 0,
            balance_after INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS inquiry_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_id TEXT UNIQUE NOT NULL,
            uid INTEGER NOT NULL,
            sku TEXT NOT NULL,
            target TEXT NOT NULL,
            amount INTEGER NOT NULL DEFAULT 0,
            customer_name TEXT DEFAULT '',
            desc TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            expires_at TEXT NOT NULL,
            order_id TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS auto_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            sku TEXT NOT NULL,
            target TEXT NOT NULL,
            total_cycles INTEGER NOT NULL DEFAULT 1,
            current_cycle INTEGER NOT NULL DEFAULT 1,
            price_per_cycle INTEGER NOT NULL DEFAULT 0,
            next_run_date TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            cycle_days INTEGER NOT NULL DEFAULT 30,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid INTEGER NOT NULL,
            staff_name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            modal_awal INTEGER NOT NULL DEFAULT 0,
            setoran_akhir INTEGER,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (uid) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            ticket_type TEXT NOT NULL DEFAULT 'transaksi',
            order_id TEXT,
            message TEXT,
            status TEXT NOT NULL DEFAULT 'open',
            reply TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS admin_replies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT UNIQUE NOT NULL,
            question TEXT,
            reply TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS broadcast_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        -- Notification Center Tables
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS notification_broadcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            image_url TEXT,
            target_type TEXT NOT NULL,
            channels TEXT NOT NULL,
            total_target INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            failed_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            error_message TEXT,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS notification_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            broadcast_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP,
            error_message TEXT,
            FOREIGN KEY (broadcast_id) REFERENCES notification_broadcasts(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS notification_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_name TEXT UNIQUE NOT NULL,
            channel_type TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            configuration TEXT,
            last_status TEXT,
            last_check TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_tx_uid ON transactions(uid);
        CREATE INDEX IF NOT EXISTS idx_tx_created ON transactions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category);
        CREATE INDEX IF NOT EXISTS idx_pricelist_cat ON pricelist_cache(category);
        CREATE INDEX IF NOT EXISTS idx_mutations_uid ON mutations(uid);
        CREATE INDEX IF NOT EXISTS idx_mutations_created ON mutations(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_inquiry_uid ON inquiry_sessions(uid);
        CREATE INDEX IF NOT EXISTS idx_inquiry_ref ON inquiry_sessions(ref_id);
        CREATE INDEX IF NOT EXISTS idx_autosub_uid ON auto_subscriptions(uid);
        CREATE INDEX IF NOT EXISTS idx_autosub_status ON auto_subscriptions(status);
        CREATE INDEX IF NOT EXISTS idx_shifts_uid ON shifts(uid);
        CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);

        -- Notification Center Indexes
        CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_broadcasts_status ON notification_broadcasts(status);
        CREATE INDEX IF NOT EXISTS idx_broadcasts_created_at ON notification_broadcasts(created_at);
        CREATE INDEX IF NOT EXISTS idx_queue_broadcast ON notification_queue(broadcast_id);
        CREATE INDEX IF NOT EXISTS idx_queue_status ON notification_queue(status);
        CREATE INDEX IF NOT EXISTS idx_queue_user ON notification_queue(user_id);
    """)
    conn.commit()

    # Seed admin user
    admin_pw = os.getenv("ADMIN_PASSWORD", "admin123")
    existing = c.execute("SELECT id FROM users WHERE username = ?", ("admin",)).fetchone()
    if not existing:
        c.execute(
            "INSERT INTO users (username, password_hash, email, balance, role) VALUES (?, ?, ?, ?, ?)",
            ("admin", generate_password_hash(admin_pw), "admin@paypoint.id", 0, "admin"),
        )
        conn.commit()

    # Seed sample regular user
    existing_user = c.execute("SELECT id FROM users WHERE username = ?", ("testuser",)).fetchone()
    if not existing_user:
        c.execute(
            "INSERT INTO users (username, password_hash, email, balance, role) VALUES (?, ?, ?, ?, ?)",
            ("testuser", generate_password_hash("user123"), "user@paypoint.id", 500000, "user"),
        )
        conn.commit()

    # Seed sample products if empty
    count = c.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count == 0:
        sample = [
            ("TSEL5", "Telkomsel Pulsa 5.000", "Pulsa", "Telkomsel", "prepaid", 5500, 6500, 1000),
            ("TSEL10", "Telkomsel Pulsa 10.000", "Pulsa", "Telkomsel", "prepaid", 10500, 11500, 1000),
            ("TSEL25", "Telkomsel Pulsa 25.000", "Pulsa", "Telkomsel", "prepaid", 25500, 26500, 1000),
            ("XL5", "XL Pulsa 5.000", "Pulsa", "XL", "prepaid", 5400, 6400, 1000),
            ("XL10", "XL Pulsa 10.000", "Pulsa", "XL", "prepaid", 10400, 11400, 1000),
            ("ISAT5", "Indosat Pulsa 5.000", "Pulsa", "Indosat", "prepaid", 5400, 6400, 1000),
            ("DATA-TSEL-1GB", "Telkomsel Data 1GB / 7 Hari", "Data", "Telkomsel", "prepaid", 13500, 15000, 1500),
            ("DATA-TSEL-3GB", "Telkomsel Data 3GB / 30 Hari", "Data", "Telkomsel", "prepaid", 30000, 32000, 2000),
            ("DATA-XL-2GB", "XL Data 2GB / 30 Hari", "Data", "XL", "prepaid", 25000, 27000, 2000),
            ("OVO50", "OVO Saldo 50.000", "E-Money", "OVO", "prepaid", 50500, 52000, 1500),
            ("DANA50", "DANA Saldo 50.000", "E-Money", "DANA", "prepaid", 50500, 52000, 1500),
            ("GOPAY50", "GoPay Saldo 50.000", "E-Money", "GoPay", "prepaid", 50500, 52000, 1500),
            ("PLN20", "PLN Token 20.000", "PLN", "PLN", "prepaid", 21500, 23000, 1500),
            ("PLN50", "PLN Token 50.000", "PLN", "PLN", "prepaid", 51500, 53000, 1500),
            ("PLN100", "PLN Token 100.000", "PLN", "PLN", "prepaid", 101500, 103000, 1500),
            ("ML86", "Mobile Legends 86 Diamonds", "Game", "Mobile Legends", "prepaid", 22000, 24000, 2000),
            ("ML172", "Mobile Legends 172 Diamonds", "Game", "Mobile Legends", "prepaid", 43000, 45500, 2500),
            ("FF70", "Free Fire 70 Diamonds", "Game", "Free Fire", "prepaid", 9500, 11000, 1500),
            ("FF140", "Free Fire 140 Diamonds", "Game", "Free Fire", "prepaid", 19000, 21000, 2000),
        ]
        for sku, name, cat, brand, typ, base, price, margin in sample:
            c.execute(
                """INSERT INTO products (sku, name, category, brand, type, base_price, price, margin)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sku, name, cat, brand, typ, base, price, margin),
            )
        conn.commit()

    conn.close()


def get_user_by_id(uid: int) -> Optional[User]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    conn.close()
    return User(row) if row else None


def get_user_by_username(username: str) -> Optional[User]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
    conn.close()
    return User(row) if row else None


def get_user_by_google_id(gid: str) -> Optional[User]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE google_id = ?", (gid,)).fetchone()
    conn.close()
    return User(row) if row else None


def get_user_by_email(email: str) -> Optional[User]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE LOWER(email) = LOWER(?)", (email,)).fetchone()
    conn.close()
    return User(row) if row else None


def create_user(username: str, password: Optional[str], email: Optional[str] = None,
                google_id: Optional[str] = None, role: str = "user", balance: int = 0) -> User:
    import secrets
    conn = get_conn()
    pw_hash = generate_password_hash(password) if password else None
    
    # Generate random 6-digit PIN and hash it with bcrypt
    random_pin = ''.join([str(secrets.randbelow(10)) for _ in range(6)])
    pin_hash = bcrypt.hashpw(random_pin.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    cur = conn.execute(
        "INSERT INTO users (username, password_hash, email, google_id, role, balance, pin, force_pin_change) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
        (username, pw_hash, email, google_id, role, balance, pin_hash),
    )
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return get_user_by_id(uid)


def update_user_balance(uid: int, delta: int) -> int:
    """Atomically add `delta` (may be negative) to a user's balance WITH MUTATION LOG.
    Returns the new balance, or -1 if the change would leave balance negative."""
    conn = get_conn()
    conn.isolation_level = None  # autocommit-control via BEGIN
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Get current balance first
        user = conn.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            conn.execute("ROLLBACK")
            return -1
        
        balance_before = user["balance"]
        balance_after = balance_before + delta
        
        # Check if result would be negative
        if balance_after < 0:
            conn.execute("ROLLBACK")
            return -1
        
        # Update balance
        conn.execute("UPDATE users SET balance = ? WHERE id = ?", (balance_after, uid))
        
        # Log mutation
        mutation_type = "in" if delta > 0 else "out"
        mutation_amount = abs(delta)
        description = "Penyesuaian Saldo oleh Admin" if delta > 0 else "Pengurangan Saldo oleh Admin"
        
        conn.execute(
            "INSERT INTO mutations (uid, type, amount, balance_before, balance_after, description) VALUES (?,?,?,?,?,?)",
            (uid, mutation_type, mutation_amount, balance_before, balance_after, description)
        )
        
        conn.execute("COMMIT")
        return balance_after
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def force_credit_balance(uid: int, delta: int) -> int:
    if delta <= 0: return -1
    conn = get_conn()
    conn.isolation_level = None # Kontrol manual
    try:
        conn.execute("BEGIN IMMEDIATE") # Kunci tabel
        user = conn.execute('SELECT balance FROM users WHERE id = ?', (uid,)).fetchone()
        if not user:
            conn.execute("ROLLBACK")
            return -1
        before = user['balance']
        after = before + delta
        conn.execute('UPDATE users SET balance = ? WHERE id = ?', (after, uid))
        conn.execute('INSERT INTO mutations (uid, type, amount, balance_before, balance_after, description) VALUES (?,?,?,?,?,?)', (uid, 'in', delta, before, after, 'Penambahan Saldo/Refund'))
        conn.execute("COMMIT")
        return after
    except:
        conn.execute("ROLLBACK")
        return -1
    finally:
        conn.close()

def try_debit_balance(uid: int, amount: int) -> bool:
    if amount <= 0: return False # BLOKIR HARGA MINUS
    conn = get_conn()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        user = conn.execute('SELECT balance FROM users WHERE id = ?', (uid,)).fetchone()
        if not user or user['balance'] < amount:
            conn.execute("ROLLBACK")
            return False
        before = user['balance']
        after = before - amount
        conn.execute('UPDATE users SET balance = ? WHERE id = ?', (after, uid))
        conn.execute('INSERT INTO mutations (uid, type, amount, balance_before, balance_after, description) VALUES (?,?,?,?,?,?)', (uid, 'out', amount, before, after, 'Pembelian Produk'))
        conn.execute("COMMIT")
        return True
    except:
        conn.execute("ROLLBACK")
        return False
    finally:
        conn.close()

def set_user_balance(uid: int, balance: int) -> None:
    """DEPRECATED: Use update_user_balance() or force_credit_balance() instead.
    This function is kept for backward compatibility but now logs mutation."""
    conn = get_conn()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Get current balance
        user = conn.execute("SELECT balance FROM users WHERE id = ?", (uid,)).fetchone()
        if not user:
            conn.execute("ROLLBACK")
            return
        
        balance_before = user["balance"]
        balance_after = balance
        delta = balance_after - balance_before
        
        # Update balance
        conn.execute("UPDATE users SET balance = ? WHERE id = ?", (balance, uid))
        
        # Log mutation if there's a change
        if delta != 0:
            mutation_type = "in" if delta > 0 else "out"
            mutation_amount = abs(delta)
            description = "Set Balance Manual (DEPRECATED)"
            
            conn.execute(
                "INSERT INTO mutations (uid, type, amount, balance_before, balance_after, description) VALUES (?,?,?,?,?,?)",
                (uid, mutation_type, mutation_amount, balance_before, balance_after, description)
            )
        
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def list_users(search: str = "") -> list:
    conn = get_conn()
    if search:
        rows = conn.execute(
            "SELECT * FROM users WHERE username LIKE ? OR email LIKE ? ORDER BY id DESC",
            (f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM users ORDER BY id DESC").fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def update_user_admin(uid: int, username: str, email: str, role: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE users SET username = ?, email = ?, role = ? WHERE id = ?",
        (username, email, role, uid),
    )
    conn.commit()
    conn.close()


# ----- Products -----
def list_products(category: str = None, brand: str = None, active_only: bool = False) -> list:
    conn = get_conn()
    q = "SELECT * FROM products WHERE 1=1"
    params = []
    if active_only:
        q += " AND is_active = 1"
    if category:
        q += " AND category = ?"
        params.append(category)
    if brand:
        q += " AND brand = ?"
        params.append(brand)
    q += " ORDER BY category, brand, price"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def get_product_by_sku(sku: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM products WHERE sku = ?", (sku,)).fetchone()
    conn.close()
    if not row: return None
    d = dict(row)

    return d


def get_product_by_id(pid: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (pid,)).fetchone()
    conn.close()
    if not row: return None
    d = dict(row)

    return d


def upsert_product(sku: str, name: str, category: str, brand: str, type_: str,
                   base_price: int, margin: int, description: str = "",
                   is_active: int = 1) -> None:
    conn = get_conn()
    price = base_price + margin
    existing = conn.execute("SELECT id FROM products WHERE sku = ?", (sku,)).fetchone()
    if existing:
        conn.execute(
            """UPDATE products SET name=?, category=?, brand=?, type=?, base_price=?, margin=?, price=?,
               description=?, is_active=?, updated_at=CURRENT_TIMESTAMP WHERE sku=?""",
            (name, category, brand, type_, base_price, margin, price, description, is_active, sku),
        )
    else:
        conn.execute(
            """INSERT INTO products (sku, name, category, brand, type, base_price, margin, price,
               description, is_active) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sku, name, category, brand, type_, base_price, margin, price, description, is_active),
        )
    conn.commit()
    conn.close()


def delete_product(pid: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()


def list_categories() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT category, COUNT(*) AS count FROM products WHERE is_active = 1 GROUP BY category ORDER BY category"
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def list_brands_by_category(category: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT brand, COUNT(*) AS count FROM products WHERE is_active = 1 AND category = ? GROUP BY brand ORDER BY brand",
        (category,),
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


# ----- Transactions -----
def create_transaction(order_id: str, uid: int, sku: str, name: str, target: str,
                       price: int, kind: str = "purchase", status: str = "pending") -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO transactions (order_id, uid, sku, name, target, price, status, kind) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (order_id, uid, sku, name, target, price, status, kind),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_transaction(order_id: str, status: str, sn: str = None, message: str = None) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE transactions SET status = ?, sn = COALESCE(?, sn), message = COALESCE(?, message) WHERE order_id = ?",
        (status, sn, message, order_id),
    )
    conn.commit()
    conn.close()


def list_transactions(uid: int = None, status: str = None, limit: int = 50, username: str = None) -> list:
    conn = get_conn()
    q = "SELECT t.*, datetime(t.created_at, '+7 hours') as wib_time, u.username FROM transactions t LEFT JOIN users u ON t.uid = u.id WHERE 1=1"
    params = []
    if uid:
        q += " AND t.uid = ?"
        params.append(uid)
    if status:
        q += " AND t.status = ?"
        params.append(status)
    if username:
        q += " AND u.username LIKE ?"
        params.append(f"%{username}%")
    q += " ORDER BY t.created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(q, params).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def get_transaction(order_id: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT *, datetime(created_at, 'localtime') as created_at FROM transactions WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    if not row: return None
    d = dict(row)

    return d


# ----- Digiflazz Logs -----
def log_digiflazz_call(endpoint: str, req: str, resp: str, status_code: int, order_id: str = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO digiflazz_logs (endpoint, request_body, response_body, status_code, order_id) VALUES (?, ?, ?, ?, ?)",
        (endpoint, req, resp, status_code, order_id),
    )
    conn.commit()
    conn.close()


def list_digiflazz_logs(limit: int = 100) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM digiflazz_logs ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


# ----- Topups -----
def create_topup(uid: int, order_id: str, amount: int, qris_data: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO topups (uid, order_id, amount, qris_data, status) VALUES (?, ?, ?, ?, ?)",
            (uid, order_id, amount, qris_data, "pending"),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_topup(order_id: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM topups WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    if not row: return None
    d = dict(row)

    return d


def mark_topup_paid(order_id: str) -> Optional[dict]:
    # Atomic transition status + tambah saldo
    conn = get_conn()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM topups WHERE order_id = ? AND status = 'pending'", (order_id,)).fetchone()
        if not row:
            conn.execute("ROLLBACK")
            return None
        
        d = dict(row)
        uid = d["uid"]
        amount = d["amount"]
        
        # 1. Update Topup Status
        conn.execute("UPDATE topups SET status = 'paid', paid_at = CURRENT_TIMESTAMP WHERE id = ?", (d["id"],))
        
        # 2. Update Saldo User
        user = conn.execute('SELECT balance FROM users WHERE id = ?', (uid,)).fetchone()
        before = user['balance'] if user else 0
        after = before + amount
        conn.execute('UPDATE users SET balance = ? WHERE id = ?', (after, uid))
        
        # 3. Catat Mutasi
        conn.execute('INSERT INTO mutations (uid, type, amount, balance_before, balance_after, description) VALUES (?,?,?,?,?,?)', (uid, 'in', amount, before, after, f'Topup {order_id}'))
        
        conn.execute("COMMIT")
        return d
    except Exception as e:
        conn.execute("ROLLBACK")
        return None
    finally:
        conn.close()


# ----- Pricelist Cache -----
def upsert_pricelist_item(item: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO pricelist_cache (sku, name, category, brand, type, seller_name, price,
           buyer_sku_code, buyer_product_status, seller_product_status, unlimited_stock,
           stock, multi, start_cut_off, end_cut_off, description, cached_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(sku) DO UPDATE SET
             name=excluded.name, category=excluded.category, brand=excluded.brand,
             type=excluded.type, price=excluded.price, cached_at=CURRENT_TIMESTAMP""",
        (
            item.get("buyer_sku_code") or item["sku"],
            item.get("product_name") or item["name"],
            item["category"], item["brand"], item.get("type", "prepaid"),
            item.get("seller_name", ""), int(item.get("price", 0)),
            item.get("buyer_sku_code", item.get("sku")),
            int(item.get("buyer_product_status", 1)),
            int(item.get("seller_product_status", 1)),
            int(item.get("unlimited_stock", 1)),
            int(item.get("stock", 0)),
            int(item.get("multi", 0)),
            item.get("start_cut_off", ""), item.get("end_cut_off", ""),
            item.get("desc", ""),
        ),
    )
    conn.commit()
    conn.close()


def list_pricelist(category: str = None, brand: str = None) -> list:
    conn = get_conn()
    q = "SELECT * FROM pricelist_cache WHERE 1=1"
    params = []
    if category:
        q += " AND category = ?"
        params.append(category)
    if brand:
        q += " AND brand = ?"
        params.append(brand)
    q += " ORDER BY category, brand, price"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def list_pricelist_categories() -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT category, COUNT(*) AS count FROM pricelist_cache GROUP BY category ORDER BY category"
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def list_pricelist_brands(category: str) -> list:
    conn = get_conn()
    rows = conn.execute(
        "SELECT brand, COUNT(*) AS count FROM pricelist_cache WHERE category = ? GROUP BY brand ORDER BY brand",
        (category,),
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


# ----- Stats -----
def get_admin_stats() -> dict:
    conn = get_conn()
    user_count = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role = 'user'").fetchone()["c"]
    product_count = conn.execute("SELECT COUNT(*) AS c FROM products WHERE is_active = 1").fetchone()["c"]
    tx_count = conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM transactions WHERE status = 'pending'"
    ).fetchone()["c"]
    today = datetime.utcnow().strftime("%Y-%m-%d")
    today_omset = conn.execute(
        "SELECT COALESCE(SUM(price), 0) AS s FROM transactions WHERE LOWER(status) IN ('sukses', 'success') AND DATE(created_at, '+7 hours') = DATE('now', '+7 hours')"
    ).fetchone()["s"]
    total_omset = conn.execute(
        "SELECT COALESCE(SUM(price), 0) AS s FROM transactions WHERE LOWER(status) IN ('sukses', 'success')"
    ).fetchone()["s"]
    conn.close()
    return {
        "user_count": user_count,
        "product_count": product_count,
        "tx_count": tx_count,
        "pending_count": pending,
        "today_omset": today_omset,
        "total_omset": total_omset,
    }


# ----- NestedNav helpers (auto-appended) -----
def list_types_by_brand(category: str, brand: str) -> list:
    """Return distinct product types (e.g. prepaid, postpaid) for a brand."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT type, COUNT(*) AS count FROM products "
        "WHERE is_active = 1 AND category = ? AND brand = ? "
        "GROUP BY type ORDER BY type",
        (category, brand),
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def list_products_by_type(category: str, brand: str, type_: str) -> list:
    """Return active products for a specific category/brand/type triple."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM products "
        "WHERE is_active = 1 AND category = ? AND brand = ? AND type = ? "
        "ORDER BY price",
        (category, brand, type_),
    ).fetchall()
    conn.close()
    res = []
    # TAMPILKAN HARGA MURNI DARI DATABASE (TIDAK ADA REKALKULASI)
    for r in rows:
        res.append(dict(r))
    return res


def cancel_topup(order_id: str, uid: int) -> bool:
    conn = get_conn()
    try:
        row = conn.execute("SELECT status FROM topups WHERE order_id=? AND uid=?", (order_id, uid)).fetchone()
        if row and row["status"] == "pending":
            conn.execute("UPDATE topups SET status='cancelled' WHERE order_id=?", (order_id,))
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def record_mutation(uid, type_, amount, before, after, desc):
    conn = get_conn()
    conn.execute("INSERT INTO mutations (uid, type, amount, balance_before, balance_after, description) VALUES (?,?,?,?,?,?)",
                 (uid, type_, amount, before, after, desc))
    conn.commit()
    conn.close()


def hitung_harga_final(bp, mg, role):
    # bp = base_price, mg = margin, role = reseller/reguler
    bp = int(bp or 0)
    mg = int(mg or 0)
    role_str = str(role).lower()
    
    # 1. JIKA ADMIN ISI MARGIN MANUAL (TIDAK 0)
    if mg > 0:
        # Reseller dapat diskon 30% dari margin manual Bos
        return int(bp + (mg * 0.7)) if role_str == 'reseller' else int(bp + mg)
        
    # 2. JIKA MARGIN MANUAL 0 (LOGIKA AUTO TIERING BERJENJANG)
    if bp <= 10000:
        m_mem, m_res = 1500, 500
    elif bp <= 25000:
        m_mem, m_res = 2000, 800
    elif bp <= 50000:
        m_mem, m_res = 2500, 1200
    elif bp <= 100000:
        m_mem, m_res = 3000, 1500
    else:
        # Harga tinggi menggunakan batas minimum persentase (Anti-Rugi)
        m_mem = max(4000, int(bp * 0.008))
        m_res = max(2000, int(bp * 0.005))
        
    return int(bp + (m_res if role_str == 'reseller' else m_mem))


# ----- Inquiry Sessions (Postpaid Protection) -----
def save_inquiry_session(ref_id: str, uid: int, sku: str, target: str, amount: int, customer_name: str = "", desc: str = ""):
    """Save inquiry session to prevent price manipulation."""
    from datetime import datetime, timedelta
    conn = get_conn()
    try:
        # Cleanup expired inquiries for this user before insert
        conn.execute("DELETE FROM inquiry_sessions WHERE uid=? AND expires_at < datetime('now')", (uid,))
        
        # Set expiry 5 minutes from now
        expires_at = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        
        conn.execute("""
            INSERT INTO inquiry_sessions (ref_id, uid, sku, target, amount, customer_name, desc, status, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)
        """, (ref_id, uid, sku, target, amount, customer_name, desc, expires_at))
        conn.commit()
    finally:
        conn.close()


def get_and_lock_inquiry(ref_id: str, uid: int, order_id: str) -> Optional[dict]:
    """Get inquiry and lock it atomically. Returns None if not found/expired/already used."""
    conn = get_conn()
    conn.isolation_level = None
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Get inquiry
        inquiry = conn.execute("""
            SELECT * FROM inquiry_sessions 
            WHERE ref_id=? AND uid=? AND status='active' AND expires_at > datetime('now')
        """, (ref_id, uid)).fetchone()
        
        if not inquiry:
            conn.execute("ROLLBACK")
            return None
        
        # Lock inquiry (mark as processing)
        conn.execute("""
            UPDATE inquiry_sessions 
            SET status='processing', order_id=?
            WHERE ref_id=?
        """, (order_id, ref_id))
        
        conn.execute("COMMIT")
        return dict(inquiry)
    except Exception:
        conn.execute("ROLLBACK")
        return None
    finally:
        conn.close()


def finalize_inquiry(ref_id: str, uid: int, success: bool):
    """Mark inquiry as finished (delete) or restore to active on failure."""
    conn = get_conn()
    try:
        if success:
            # Delete inquiry (consumed successfully) - with uid check
            conn.execute("DELETE FROM inquiry_sessions WHERE ref_id=? AND uid=?", (ref_id, uid))
        else:
            # Restore inquiry to active (allow retry) - with uid check
            conn.execute("UPDATE inquiry_sessions SET status='active', order_id=NULL WHERE ref_id=? AND uid=?", (ref_id, uid))
        conn.commit()
    finally:
        conn.close()
