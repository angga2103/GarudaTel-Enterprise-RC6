# DIGIFLAZZ IMPLEMENTATION PLAN
## GarudaTel Enterprise RC6 FIXED

**Date:** 2026-08-20  
**Author:** Kiro AI Assistant  
**Status:** PLANNING PHASE - AWAITING REVIEW  
**Baseline:** RC6 FIXED - STABLE RELEASE / PRODUCTION READY

---

## EXECUTIVE SUMMARY

Rencana implementasi ini menyusun strategi lengkap untuk mengimplementasikan arsitektur PREPAID dan POSTPAID Digiflazz yang aman, backward-compatible, dan sesuai dokumentasi resmi Digiflazz.

**Key Principles:**
1. **Source of Truth:** `cmd=prepaid` → `product_class=prepaid`, `cmd=pasca` → `product_class=postpaid`
2. **Never Guess:** Data existing tanpa source command → tandai sebagai `unknown`
3. **Server-Side Security:** POSTPAID payment menggunakan data dari inquiry session, BUKAN dari client
4. **Backward Compatible:** Zero breaking changes untuk flow PREPAID yang sudah production-ready
5. **Evidence-Based:** Semua keputusan berdasarkan audit code dan dokumentasi resmi Digiflazz

---

## 1. CURRENT ARCHITECTURE

### 1.1 Framework & Tech Stack
- **Language:** Python 3.x
- **Framework:** Flask
- **Database:** SQLite3
- **Authentication:** Flask-Login + Google OAuth
- **API Client:** Custom Digiflazz client (`digiflazz.py`)
- **Frontend:** HTML Templates + Tailwind CSS + Vanilla JavaScript

### 1.2 Core Digiflazz Integration Files
| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `digiflazz.py` | 297 | API client (prepaid & postpaid) | ✅ Complete |
| `models.py` | 1223 | Database operations | ✅ Complete |
| `routes/user.py` | 1623 | Transaction endpoints | ✅ Complete |
| `routes/admin.py` | 3000+ | Admin & sync endpoints | ✅ Complete |
| `routes/api.py` | 398 | Webhook endpoints | ✅ Complete |
| `subscription_worker.py` | 150+ | Inquiry session cleanup | ✅ Complete |

### 1.3 Current Database Schema

**products table:**
```sql
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    brand TEXT NOT NULL,
    type TEXT NOT NULL,              -- "prepaid" or "postpaid"
    base_price INTEGER NOT NULL DEFAULT 0,
    price INTEGER NOT NULL DEFAULT 0,
    margin INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_langganan INTEGER DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**transactions table:**
```sql
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
```

**inquiry_sessions table (CRITICAL for POSTPAID):**
```sql
CREATE TABLE IF NOT EXISTS inquiry_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_id TEXT UNIQUE NOT NULL,
    uid INTEGER NOT NULL,
    sku TEXT NOT NULL,
    target TEXT NOT NULL,
    amount INTEGER NOT NULL DEFAULT 0,
    customer_name TEXT DEFAULT '',
    desc TEXT DEFAULT '',              -- JSON string
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TEXT NOT NULL,
    order_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (uid) REFERENCES users(id)
);
```

### 1.4 Current Flow Status

**PREPAID Flow (routes/user.py:429-471):**
```
✅ PRODUCTION READY
User → Product Selection → PIN → Balance Debit → submit_transaction() 
→ Digiflazz API → Response → Database Update → Receipt
```

**POSTPAID Flow (routes/user.py:370-427):**
```
✅ INFRASTRUCTURE COMPLETE
User → Product Selection → inquiry_postpaid() → Display Bill 
→ User Confirms → pay_postpaid() → Balance Debit → Transaction → Receipt
```

**Security Feature (EXCELLENT):**
- `save_inquiry_session()` - Server-side price locking
- `get_and_lock_inquiry()` - Atomic lock prevents race conditions
- `finalize_inquiry()` - Cleanup after success/failure
- Client CANNOT manipulate price after inquiry (routes/user.py:384-387)

---

## 2. PRODUCTION DATA FINDINGS

### 2.1 Local Database Analysis

**Current workspace database:**
- Total products: 19
- All products: `type="prepaid"`
- Zero postpaid products
- No `source` or `provider` field in products table

**Status:** ❌ NOT REPRESENTATIVE of production

### 2.2 Production Data Requirements

**REQUIRES PRODUCTION DATA:**

1. **Product Distribution:**
   - Total products in production database
   - Current `type` field distribution (prepaid vs postpaid vs other)
   - Products by category breakdown
   - Products by brand breakdown

2. **Source Command History:**
   - Which products imported via `cmd=prepaid`?
   - Which products imported via `cmd=pasca`?
   - Which products added manually?
   - Which products have unknown source?

3. **Transaction History:**
   - Total prepaid transactions
   - Total postpaid transactions
   - Transaction success rate by type
   - Most used product categories

4. **Data Quality:**
   - Products with empty/null `type` field
   - Products with invalid `type` values
   - SKU format consistency
   - Price data completeness

**Why Production Data Needed:**
- Cannot classify existing products without knowing their original source
- Cannot determine safe migration strategy without actual data distribution
- Cannot validate classification logic without real-world examples
- Cannot estimate impact without transaction patterns

---

## 3. PRODUCT CLASSIFICATION STRATEGY

### 3.1 Classification Rules (Priority Order)

**Rule 1: Source Command (PRIMARY CLASSIFIER)**
```python
# During Digiflazz sync
if fetch_pricelist(cmd="prepaid"):
    product_class = "prepaid"
elif fetch_pricelist(cmd="pasca"):
    product_class = "postpaid"
```

**Rule 2: Existing Data (NO GUESSING)**
```python
# For existing products without source info
if product.source_command == "prepaid":
    product_class = "prepaid"
elif product.source_command == "pasca":
    product_class = "postpaid"
else:
    product_class = "unknown"  # DO NOT GUESS
```

**Rule 3: Category/Brand (METADATA ONLY)**
```python
# Use ONLY for validation, NOT classification
postpaid_categories = ["PLN Pascabayar", "PDAM", "BPJS", "Telkom Pascabayar"]
if product_class == "unknown":
    # Flag for manual review, DO NOT auto-assign
    manual_review_needed = True
```

### 3.2 Classification Implementation

**New Field Required:**
```sql
-- Migration needed
ALTER TABLE products ADD COLUMN source_command TEXT;
-- Values: 'prepaid', 'pasca', NULL (unknown)
```

**Sync Logic (routes/admin.py):**
```python
# Current location: routes/admin.py:313-335
def sync_from_digiflazz(cmd):
    items = fetch_pricelist(cmd=cmd)
    for item in items:
        product_data = {
            "sku": item["buyer_sku_code"],
            "type": "prepaid" if cmd == "prepaid" else "postpaid",
            "source_command": cmd  # NEW FIELD
        }
        upsert_product(**product_data)
```

### 3.3 Handling Unknown Products

**Strategy for existing data:**
```python
# After adding source_command field
SELECT * FROM products WHERE source_command IS NULL;

# Action: Manual review required
# Options:
#   1. Re-sync from Digiflazz (recommended)
#   2. Manual classification by admin
#   3. Mark as inactive until classified
```

---

## 4. DATABASE MIGRATION PLAN

### 4.1 Migration Strategy

**Phase 1: Add New Fields (NON-BREAKING)**
```sql
-- Add source tracking
ALTER TABLE products ADD COLUMN source_command TEXT;
CREATE INDEX idx_products_source ON products(source_command);

-- Add postpaid fields to transactions
ALTER TABLE transactions ADD COLUMN transaction_type TEXT DEFAULT 'prepaid';
ALTER TABLE transactions ADD COLUMN customer_name TEXT;
ALTER TABLE transactions ADD COLUMN admin_fee INTEGER DEFAULT 0;
ALTER TABLE transactions ADD COLUMN periode TEXT;
ALTER TABLE transactions ADD COLUMN desc_json TEXT;
ALTER TABLE transactions ADD COLUMN buyer_last_saldo INTEGER;

CREATE INDEX idx_transactions_type ON transactions(transaction_type);
```

**Phase 2: Backfill Existing Data (SAFE)**
```sql
-- Mark all existing products as unknown source
UPDATE products SET source_command = NULL WHERE source_command IS NULL;

-- Backfill transaction type based on product type at time of transaction
UPDATE transactions SET transaction_type = 'prepaid' WHERE transaction_type IS NULL;
-- Note: Cannot determine postpaid without historical data
```

**Phase 3: Validation**
```sql
-- Verify migration
SELECT 
    source_command, 
    type, 
    COUNT(*) as count 
FROM products 
GROUP BY source_command, type;

-- Check for inconsistencies
SELECT * FROM products 
WHERE (source_command = 'prepaid' AND type = 'postpaid')
   OR (source_command = 'pasca' AND type = 'prepaid');
```

### 4.2 Migration Script

**File:** `migrations/add_source_command.py`

```python
"""
Migration: Add source_command field and postpaid transaction fields
Date: 2026-08-20
"""

def upgrade(conn):
    """Add new fields for prepaid/postpaid classification"""
    
    # Add to products
    conn.execute("ALTER TABLE products ADD COLUMN source_command TEXT")
    conn.execute("CREATE INDEX idx_products_source ON products(source_command)")
    
    # Add to transactions
    conn.execute("ALTER TABLE transactions ADD COLUMN transaction_type TEXT DEFAULT 'prepaid'")
    conn.execute("ALTER TABLE transactions ADD COLUMN customer_name TEXT")
    conn.execute("ALTER TABLE transactions ADD COLUMN admin_fee INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE transactions ADD COLUMN periode TEXT")
    conn.execute("ALTER TABLE transactions ADD COLUMN desc_json TEXT")
    conn.execute("ALTER TABLE transactions ADD COLUMN buyer_last_saldo INTEGER")
    conn.execute("CREATE INDEX idx_transactions_type ON transactions(transaction_type)")
    
    # Backfill existing transactions
    conn.execute("UPDATE transactions SET transaction_type = 'prepaid' WHERE transaction_type IS NULL")
    
    conn.commit()
    print("✅ Migration complete: source_command and postpaid fields added")

def downgrade(conn):
    """Remove added fields (not recommended for production)"""
    # SQLite doesn't support DROP COLUMN easily
    # Requires table recreation
    print("⚠️ Downgrade not implemented - manual table recreation required")
```

### 4.3 Rollback Plan

**If migration fails:**
```bash
# 1. Stop application
systemctl stop garudatel

# 2. Restore database backup
cp database.db.backup database.db

# 3. Restart application
systemctl start garudatel

# 4. Verify data integrity
sqlite3 database.db "SELECT COUNT(*) FROM products;"
```

---

## 5. DIGIFLAZZ SYNC ARCHITECTURE

### 5.1 Current Sync Implementation

**Location:** `routes/admin.py:268-469`

**Fetch Endpoint:** `POST /admin/pricelist/fetch`
- Calls `fetch_pricelist(cmd)` from digiflazz.py
- Filters by category and brand
- Saves to `pricelist_cache` table
- Returns filtered items to frontend

**Import Endpoint:** `POST /admin/pricelist/import`
- Reads from `pricelist_cache`
- Admin selects SKUs and sets margin
- Calls `upsert_product()` for each SKU

**Sync Endpoint:** `POST /admin/pricelist/sync`
- Updates existing products only
- Preserves margin settings
- Updates base_price and is_active

### 5.2 Enhanced Sync Architecture

**New Sync Flow:**
```
Admin → Select Command (prepaid/pasca) → Fetch from Digiflazz 
→ Display Products with Classification → Admin Reviews 
→ Import with source_command → Products Created/Updated
```

**Changes Required:**

**File:** `routes/admin.py:268-336` (pricelist_fetch)
```python
# BEFORE
mapped = {
    "type": item.get("type", "prepaid")
}

# AFTER
mapped = {
    "type": "prepaid" if cmd == "prepaid" else "postpaid",
    "source_command": cmd  # ADD THIS
}
```

**File:** `routes/admin.py:339-369` (pricelist_import)
```python
# BEFORE
upsert_product(
    sku=r["sku"],
    type_=r["type"] or "prepaid",
    # ...
)

# AFTER
upsert_product(
    sku=r["sku"],
    type_=r["type"],
    source_command=r.get("source_command"),  # ADD THIS
    # ...
)
```

**File:** `models.py:667-706` (upsert_product)
```python
# BEFORE
def upsert_product(sku, name, category, brand, type_, base_price, margin, description, is_active):
    # ...

# AFTER
def upsert_product(sku, name, category, brand, type_, base_price, margin, 
                   description, is_active, source_command=None):
    # Add source_command to INSERT and UPDATE
    # ...
```

### 5.3 Sync Validation

**Pre-Sync Checks:**
```python
def validate_sync_data(items, cmd):
    """Validate data before sync"""
    errors = []
    
    for item in items:
        # Check required fields
        if not item.get("buyer_sku_code"):
            errors.append(f"Missing SKU: {item}")
        
        # Check price validity
        if item.get("price", 0) <= 0:
            errors.append(f"Invalid price for {item.get('product_name')}")
        
        # Check classification consistency
        expected_type = "prepaid" if cmd == "prepaid" else "postpaid"
        if item.get("type") and item["type"] != expected_type:
            # Log warning but don't block
            logger.warning(f"Type mismatch: {item['buyer_sku_code']}")
    
    return errors
```

---

## 6. PREPAID TRANSACTION ARCHITECTURE

### 6.1 Current Implementation (DO NOT CHANGE)

**Location:** `routes/user.py:429-471`

**Flow:**
```
1. Product selection + target number
2. PIN validation (kasir_name verification)
3. Auto-tier price calculation
4. Balance debit (atomic)
5. Transaction creation (status='pending')
6. submit_transaction() to Digiflazz
7. Response handling (success/pending/failed)
8. Balance refund on failure
```

**Status:** ✅ PRODUCTION READY - DO NOT MODIFY

### 6.2 Digiflazz API (Prepaid)

**Endpoint:** `POST https://api.digiflazz.com/v1/transaction`

**Request Payload:**
```json
{
  "username": "user",
  "buyer_sku_code": "TSEL5",
  "customer_no": "081234567890",
  "ref_id": "ORD-ABCD1234",
  "sign": "md5(username+apikey+ref_id)"
}
```

**Response (Success):**
```json
{
  "data": {
    "ref_id": "ORD-ABCD1234",
    "status": "Sukses",
    "rc": "00",
    "sn": "SN1234567890",
    "message": "Transaksi berhasil"
  }
}
```

**Response Codes:**
- `rc=00` → Success
- `rc=03` → Pending
- Other → Failed (refund balance)

### 6.3 Security Controls (Existing)

**Balance Atomicity:**
```python
# models.py:834-865
def try_debit_balance(uid, amount):
    """Atomic balance debit with race condition protection"""
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")  # Lock database
    # ... debit logic ...
    conn.commit()
```

**PIN Verification:**
```python
# routes/user.py:345-361
kasir_name = validate_transaksi_pin(pin, current_user.id)
if not kasir_name:
    return jsonify({"ok": False, "error": "PIN Transaksi Salah!"}), 403
```

---

## 7. POSTPAID INQUIRY ARCHITECTURE

### 7.1 Current Implementation (COMPLETE)

**Location:** `routes/user.py:126-175`

**Endpoint:** `POST /api/inquiry`

**Flow:**
```
1. User enters customer_no (target)
2. Generate unique ref_id (INQ-XXXXXXXX)
3. Call inquiry_postpaid() to Digiflazz
4. Parse response (customer_name, selling_price, admin, desc)
5. Calculate total = selling_price + admin
6. Save to inquiry_sessions (server-side)
7. Return bill details to client
```

**Status:** ✅ COMPLETE AND SECURE

### 7.2 Digiflazz API (Inquiry)

**Endpoint:** `POST https://api.digiflazz.com/v1/transaction`

**Request Payload:**
```json
{
  "commands": "inq-pasca",
  "username": "user",
  "buyer_sku_code": "pln",
  "customer_no": "530000000001",
  "ref_id": "INQ-ABCD1234",
  "sign": "md5(username+apikey+ref_id)"
}
```

**Response (Success):**
```json
{
  "data": {
    "ref_id": "INQ-ABCD1234",
    "customer_no": "530000000001",
    "customer_name": "JOHN DOE",
    "buyer_sku_code": "pln",
    "admin": 2500,
    "message": "Transaksi Sukses",
    "status": "Sukses",
    "rc": "00",
    "periode": "202401",
    "selling_price": 125000,
    "desc": {
      "tarif": "R1",
      "daya": 1300,
      "lembar_tagihan": 1,
      "detail": [...]
    }
  }
}
```

### 7.3 Inquiry Session Security (EXCELLENT)

**Save Session (models.py):**
```python
def save_inquiry_session(ref_id, uid, sku, target, amount, customer_name, desc):
    """Save inquiry with expiration (15 minutes)"""
    expires_at = (datetime.now() + timedelta(minutes=15)).isoformat()
    conn.execute("""
        INSERT INTO inquiry_sessions 
        (ref_id, uid, sku, target, amount, customer_name, desc, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (ref_id, uid, sku, target, amount, customer_name, desc, expires_at))
```

**Lock Session (models.py):**
```python
def get_and_lock_inquiry(ref_id, uid, order_id):
    """Atomic lock - prevents double payment"""
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute("""
        SELECT * FROM inquiry_sessions 
        WHERE ref_id=? AND uid=? AND status='active' 
        AND datetime(expires_at) > datetime('now')
    """, (ref_id, uid)).fetchone()
    
    if row:
        # Lock inquiry by changing status and linking order
        conn.execute("""
            UPDATE inquiry_sessions 
            SET status='processing', order_id=?
            WHERE ref_id=?
        """, (order_id, ref_id))
        conn.commit()
    return row
```

**Critical Security Feature:**
- Client sends `ref_id` only
- Server retrieves `amount`, `sku`, `target` from inquiry_sessions
- Client CANNOT manipulate price (routes/user.py:384-387)

---

## 8. POSTPAID PAYMENT ARCHITECTURE

### 8.1 Current Implementation (COMPLETE)

**Location:** `routes/user.py:370-427`

**Flow:**
```
1. User confirms payment (sends ref_id + PIN)
2. PIN validation
3. get_and_lock_inquiry() - atomic lock
4. Extract data from SERVER (amount, sku, target)
5. Balance debit (atomic)
6. Transaction creation (status='pending')
7. pay_postpaid() to Digiflazz
8. Response handling (success/pending/failed)
9. finalize_inquiry() - cleanup
10. Balance refund on failure
```

**Status:** ✅ COMPLETE AND SECURE

### 8.2 Digiflazz API (Payment)

**Endpoint:** `POST https://api.digiflazz.com/v1/transaction`

**Request Payload:**
```json
{
  "commands": "pay-pasca",
  "username": "user",
  "buyer_sku_code": "pln",
  "customer_no": "530000000001",
  "ref_id": "ORD-ABCD1234",
  "sign": "md5(username+apikey+ref_id)"
}
```

**Response (Success):**
```json
{
  "data": {
    "ref_id": "ORD-ABCD1234",
    "customer_no": "530000000001",
    "customer_name": "JOHN DOE",
    "buyer_sku_code": "pln",
    "buyer_last_saldo": 9500000,
    "admin": 2500,
    "price": 125000,
    "selling_price": 125000,
    "sn": "SN1234567890",
    "status": "Sukses",
    "rc": "00",
    "message": "Transaksi berhasil"
  }
}
```

### 8.3 Payment Security Controls (EXCELLENT)

**Server-Side Price Validation:**
```python
# routes/user.py:384-387
# NEVER trust client - get all data from inquiry session
final_price = inquiry["amount"]  # From SERVER
target = inquiry["target"]        # From SERVER
sku = inquiry["sku"]              # From SERVER
```

**Atomic Balance & Session:**
```python
# routes/user.py:390-392
if not try_debit_balance(current_user.id, final_price):
    finalize_inquiry(ref_id, current_user.id, False)  # Restore
    return error
```

**Response Handling:**
```python
# Success: rc=00
update_transaction(order_id, "success", sn=result.get("sn"))
finalize_inquiry(ref_id, current_user.id, True)  # Delete

# Pending: rc=03
update_transaction(order_id, "pending")
# Keep inquiry for recovery

# Failed: other
update_transaction(order_id, "failed")
force_credit_balance(current_user.id, final_price)  # Refund
finalize_inquiry(ref_id, current_user.id, False)    # Restore
```

---

## 9. STATUS & WEBHOOK ARCHITECTURE

### 9.1 Current Webhook Implementation

**Location:** `routes/api.py` (webhook endpoint)

**Endpoint:** `POST /callback/digiflazz`

**Digiflazz Callback Payload:**
```json
{
  "data": {
    "ref_id": "ORD-ABCD1234",
    "status": "Sukses",
    "rc": "00",
    "sn": "SN1234567890",
    "message": "Transaksi berhasil",
    "buyer_last_saldo": 9500000
  }
}
```

**Webhook Flow:**
```
Digiflazz → POST /callback/digiflazz → Verify Signature 
→ Find Transaction → Update Status → Refund if Failed
```

### 9.2 Status Mapping

**Digiflazz Status → Database Status:**
```python
if rc == "00" or "sukses" in status.lower():
    db_status = "success"
elif rc == "03" or "pending" in status.lower():
    db_status = "pending"
else:
    db_status = "failed"
    # Refund balance
```

### 9.3 Webhook Security

**Required Enhancements:**
```python
def verify_digiflazz_webhook(payload):
    """Verify webhook authenticity"""
    # Check signature
    expected_sign = md5(username + apikey + ref_id)
    if payload.get("sign") != expected_sign:
        return False
    
    # Check IP whitelist (if Digiflazz provides)
    # allowed_ips = ["ip1", "ip2"]
    
    return True
```

---

## 10. SECURITY CONTROLS

### 10.1 Existing Security (DO NOT CHANGE)

**Authentication:**
- Flask-Login session management
- Google OAuth integration
- `@login_required` decorators
- `@admin_required` for admin routes

**Authorization:**
- User level checks (member/reseller)
- PIN verification for transactions
- Balance ownership validation

**Data Protection:**
- Parameterized SQL queries
- Password hashing (werkzeug)
- CSRF protection (Flask-WTF)

**Transaction Security:**
- Atomic balance operations
- Race condition protection
- Server-side price validation (postpaid)

### 10.2 Additional Security Controls

**API Rate Limiting:**
```python
from flask_limiter import Limiter

# Add to inquiry endpoint
@limiter.limit("10 per minute")
@user_bp.route("/api/inquiry", methods=["POST"])
def inquiry_api():
    # ...
```

**Input Validation:**
```python
def validate_customer_no(customer_no, product_type):
    """Validate customer number format"""
    if product_type == "PLN":
        # PLN: 12 digits
        if not re.match(r'^\d{12}$', customer_no):
            return False
    elif product_type == "PDAM":
        # PDAM: varies by region
        if not re.match(r'^\d{6,15}$', customer_no):
            return False
    return True
```

**Logging Enhancement:**
```python
# Log all inquiry attempts
logger.info(f"Inquiry attempt: uid={uid}, sku={sku}, target={target[:4]}****")

# Log payment attempts
logger.info(f"Payment attempt: uid={uid}, ref_id={ref_id}, amount={amount}")

# NEVER log sensitive data (full customer_no, full names)
```

### 10.3 Security Checklist

- ✅ Atomic balance operations
- ✅ Server-side price validation
- ✅ Inquiry session locking
- ✅ PIN verification
- ✅ Parameterized queries
- ✅ CSRF protection
- ⚠️ Rate limiting (recommended)
- ⚠️ Input validation (recommended)
- ⚠️ Webhook signature verification (recommended)
- ⚠️ Audit logging (recommended)

---

## 11. UI ARCHITECTURE

### 11.1 Current UI Implementation

**Templates with Postpaid Support:**
1. `templates/user/belanja.html` - Detects `type === 'postpaid'` (line 123)
2. `templates/user/gopay_transaksi.html` - Dedicated "Cek Tagihan" area (line 37-38)
3. `templates/user/transaksi.html` - "Cek Tagihan" button area (line 49-50)
4. `templates/user/dashboard.html` - Postpaid category links (line 160, 178, 185)

**Admin Templates:**
1. `templates/admin/pricelist.html` - "PASCABAYAR" sync option (line 28)
2. `templates/admin/products.html` - Product listing
3. `templates/admin/digiflazz.html` - Integration center

### 11.2 UI Enhancement Plan

**Phase 1: Product Selection**
```javascript
// belanja.html enhancement
function renderProduct(product) {
    const isPostpaid = product.type === 'postpaid';
    const badge = isPostpaid 
        ? '<span class="badge-postpaid">Pascabayar</span>'
        : '<span class="badge-prepaid">Prepaid</span>';
    
    return `
        <div class="product-card ${isPostpaid ? 'postpaid' : 'prepaid'}">
            ${badge}
            <h3>${product.name}</h3>
            <p>${formatPrice(product.price)}</p>
        </div>
    `;
}
```

**Phase 2: Inquiry Display**
```html
<!-- Structured bill display -->
<div id="inquiry-result" class="hidden">
    <div class="bill-header">
        <h3>Detail Tagihan</h3>
        <p class="customer-name" id="customer-name"></p>
    </div>
    <div class="bill-details">
        <div class="bill-row">
            <span>ID Pelanggan:</span>
            <span id="customer-no"></span>
        </div>
        <div class="bill-row">
            <span>Tagihan:</span>
            <span id="bill-amount"></span>
        </div>
        <div class="bill-row">
            <span>Admin:</span>
            <span id="admin-fee"></span>
        </div>
        <div class="bill-row total">
            <span>Total:</span>
            <span id="total-amount"></span>
        </div>
    </div>
    <div id="bill-desc"></div>
    <button id="btn-pay-postpaid">Bayar Sekarang</button>
</div>
```

**Phase 3: Payment Confirmation**
```javascript
function confirmPostpaidPayment(ref_id, amount) {
    const pin = prompt("Masukkan PIN Transaksi:");
    if (!pin) return;
    
    fetch('/buy', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            ref_id: ref_id,
            pin: pin,
            is_postpaid: true,
            pid: currentProductId
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.ok) {
            showReceipt(data);
        } else {
            alert(data.error);
        }
    });
}
```

### 11.3 Responsive Design Considerations

**Mobile (< 768px):**
- Vertical bill layout
- Full-width buttons
- Collapsible bill details
- Touch-optimized inputs

**Tablet (768px - 1024px):**
- Two-column layout
- Side-by-side inquiry and payment
- Larger touch targets

**Desktop (> 1024px):**
- Three-column layout
- Fixed sidebar for bill summary
- Keyboard shortcuts
- Hover effects

---

## 12. BACKUP & ROLLBACK PLAN

### 12.1 Pre-Implementation Backup

**Full System Backup:**
```bash
# 1. Stop application
systemctl stop garudatel

# 2. Backup database
cp database.db database.db.backup.$(date +%Y%m%d_%H%M%S)

# 3. Backup code
cd /root/web_ppob/paypoint
tar -czf ../backup_rc6_$(date +%Y%m%d_%H%M%S).tar.gz .

# 4. Backup .env
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)

# 5. Restart application
systemctl start garudatel
```

### 12.2 Database Rollback Strategy

**If migration fails:**
```bash
# 1. Stop application
systemctl stop garudatel

# 2. Restore database
cp database.db.backup.YYYYMMDD_HHMMSS database.db

# 3. Verify integrity
sqlite3 database.db ".schema products" | grep source_command
# Should return nothing if rollback successful

# 4. Restart application
systemctl start garudatel
```

### 12.3 Code Rollback Strategy

**If implementation breaks:**
```bash
# Option 1: Git revert (if committed)
git log --oneline
git revert <commit-hash>
git push

# Option 2: Restore from backup
cd /root/web_ppob
tar -xzf backup_rc6_YYYYMMDD_HHMMSS.tar.gz -C paypoint/

# Option 3: Git reset (if not pushed)
git reset --hard <previous-commit>

# Restart
systemctl restart garudatel
```

### 12.4 Rollback Testing

**Pre-rollback verification:**
```bash
# 1. Verify backup exists
ls -lh database.db.backup.*
ls -lh ../backup_rc6_*

# 2. Test backup integrity
sqlite3 database.db.backup.YYYYMMDD_HHMMSS "SELECT COUNT(*) FROM products;"

# 3. Check disk space
df -h

# 4. Document current state
sqlite3 database.db ".tables" > schema_before_rollback.txt
```

---

## 13. TEST PLAN

### 13.1 Unit Tests

**Test File:** `test_digiflazz_classification.py`

```python
import pytest
from models import classify_product

def test_prepaid_classification():
    """Test prepaid product classification"""
    product = {"source_command": "prepaid"}
    assert classify_product(product) == "prepaid"

def test_postpaid_classification():
    """Test postpaid product classification"""
    product = {"source_command": "pasca"}
    assert classify_product(product) == "postpaid"

def test_unknown_classification():
    """Test unknown product classification"""
    product = {"source_command": None}
    assert classify_product(product) == "unknown"

def test_no_guessing():
    """Ensure we never guess classification"""
    product = {"category": "PLN Pascabayar", "source_command": None}
    # Should NOT classify as postpaid based on category alone
    assert classify_product(product) == "unknown"
```

### 13.2 Integration Tests

**Test Scenario 1: Prepaid Flow (DO NOT BREAK)**
```bash
# Prerequisites: Digiflazz credentials configured
# Expected: All existing prepaid transactions work

curl -X POST http://localhost:5000/buy \
  -H "Content-Type: application/json" \
  -d '{
    "pid": 1,
    "target": "081234567890",
    "pin": "1234"
  }'

# Expected: Transaction success, balance debited, SN returned
```

**Test Scenario 2: Postpaid Inquiry**
```bash
# Prerequisites: Postpaid product exists
# Expected: Bill details returned, session saved

curl -X POST http://localhost:5000/api/inquiry \
  -H "Content-Type: application/json" \
  -d '{
    "sku": "pln",
    "target": "530000000001"
  }'

# Expected: customer_name, amount, ref_id returned
```

**Test Scenario 3: Postpaid Payment**
```bash
# Prerequisites: Valid inquiry ref_id
# Expected: Payment success, inquiry locked

curl -X POST http://localhost:5000/buy \
  -H "Content-Type: application/json" \
  -d '{
    "ref_id": "INQ-ABCD1234",
    "pin": "1234",
    "is_postpaid": true,
    "pid": 2
  }'

# Expected: Transaction success, inquiry finalized
```

**Test Scenario 4: Price Manipulation Prevention**
```bash
# Test: Client tries to send fake amount
curl -X POST http://localhost:5000/buy \
  -H "Content-Type: application/json" \
  -d '{
    "ref_id": "INQ-ABCD1234",
    "pin": "1234",
    "is_postpaid": true,
    "pid": 2,
    "amount": 1000
  }'

# Expected: Server ignores client amount, uses inquiry session amount
```

### 13.3 Production Validation

**Checklist:**
- [ ] All existing prepaid products work
- [ ] Balance calculations correct
- [ ] Auto-tier margin preserved
- [ ] Transaction history intact
- [ ] Admin panel accessible
- [ ] Sync functionality works
- [ ] No database errors in logs
- [ ] No breaking changes detected

**Validation Queries:**
```sql
-- Check product classification
SELECT source_command, type, COUNT(*) 
FROM products 
GROUP BY source_command, type;

-- Check transaction integrity
SELECT transaction_type, status, COUNT(*) 
FROM transactions 
GROUP BY transaction_type, status;

-- Check inquiry sessions
SELECT status, COUNT(*) 
FROM inquiry_sessions 
GROUP BY status;

-- Check for data loss
SELECT COUNT(*) as total_products FROM products;
SELECT COUNT(*) as total_transactions FROM transactions;
```

---

## 14. EXACT FILES TO MODIFY

### 14.1 Database Migration

**File:** `migrations/add_source_command.py` (NEW)
- Add `source_command` field to products
- Add postpaid fields to transactions
- Create indexes
- Backfill existing data

**Estimated Lines:** ~80 lines

### 14.2 Models

**File:** `models.py`

**Function: `upsert_product()` (Line 667-706)**
- Add `source_command` parameter
- Update INSERT statement
- Update UPDATE statement

**Estimated Changes:** +5 lines

**Function: `classify_product()` (NEW)**
- Implement classification logic
- Return "prepaid", "postpaid", or "unknown"

**Estimated Lines:** +20 lines

### 14.3 Admin Routes

**File:** `routes/admin.py`

**Function: `pricelist_fetch()` (Line 268-336)**
- Add `source_command=cmd` to mapped data

**Estimated Changes:** +1 line

**Function: `pricelist_import()` (Line 339-369)**
- Pass `source_command` to `upsert_product()`

**Estimated Changes:** +1 line

**Function: `pricelist_sync()` (Line 372-469)**
- Preserve `source_command` during sync
- Add validation for type consistency

**Estimated Changes:** +5 lines

### 14.4 Digiflazz Client

**File:** `digiflazz.py`

**No changes required** - already implements inquiry_postpaid() and pay_postpaid()

### 14.5 User Routes

**File:** `routes/user.py`

**No changes required** - already implements full postpaid flow with security

### 14.6 Templates (UI Enhancement)

**File:** `templates/user/belanja.html`
- Enhance postpaid product display
- Add classification badges

**Estimated Changes:** +20 lines

**File:** `templates/admin/products.html`
- Add source_command column
- Add classification filter

**Estimated Changes:** +15 lines

**Total Estimated Changes:** ~150 lines across 7 files

---

## 15. EXACT FUNCTIONS TO MODIFY

### 15.1 models.py

**Function 1: `upsert_product()`**
```python
# BEFORE (Line 667)
def upsert_product(sku, name, category, brand, type_, base_price, margin, description, is_active):

# AFTER
def upsert_product(sku, name, category, brand, type_, base_price, margin, 
                   description, is_active, source_command=None):
    # ... existing code ...
    
    # UPDATE statement needs source_command
    conn.execute("""
        UPDATE products 
        SET name=?, category=?, brand=?, type=?, base_price=?, 
            margin=?, price=?, description=?, is_active=?, 
            source_command=?, updated_at=CURRENT_TIMESTAMP 
        WHERE sku=?
    """, (name, category, brand, type_, base_price, margin, price, 
          description, is_active, source_command, sku))
    
    # INSERT statement needs source_command
    conn.execute("""
        INSERT INTO products 
        (sku, name, category, brand, type, base_price, margin, price, 
         description, is_active, source_command)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sku, name, category, brand, type_, base_price, margin, price, 
          description, is_active, source_command))
```

**Function 2: `classify_product()` (NEW)**
```python
def classify_product(product_data):
    """
    Classify product as prepaid, postpaid, or unknown.
    NEVER guess based on category/brand.
    """
    source_cmd = product_data.get("source_command")
    
    if source_cmd == "prepaid":
        return "prepaid"
    elif source_cmd == "pasca":
        return "postpaid"
    else:
        return "unknown"
```

### 15.2 routes/admin.py

**Function 1: `pricelist_fetch()` (Line 268-336)**
```python
# BEFORE (Line 313-335)
if cmd == "pasca":
    if item_cat == "pascabayar":
        mapped["type"] = "postpaid"
else:
    mapped["type"] = item.get("type", "prepaid")

# AFTER
mapped["type"] = "postpaid" if cmd == "pasca" else "prepaid"
mapped["source_command"] = cmd  # ADD THIS LINE
```

**Function 2: `pricelist_import()` (Line 339-369)**
```python
# BEFORE (Line 363-367)
upsert_product(
    sku=r["sku"],
    name=r["name"],
    category=r["category"],
    brand=r["brand"],
    type_=r["type"] or "prepaid",
    base_price=int(r["price"]),
    margin=margin,
    description=r["description"] or "",
    is_active=1
)

# AFTER
upsert_product(
    sku=r["sku"],
    name=r["name"],
    category=r["category"],
    brand=r["brand"],
    type_=r["type"] or "prepaid",
    base_price=int(r["price"]),
    margin=margin,
    description=r["description"] or "",
    is_active=1,
    source_command=r.get("source_command")  # ADD THIS LINE
)
```

**Function 3: `pricelist_sync()` (Line 372-469)**
```python
# Add validation after line 450
existing = get_product_by_id(r["id"])
if existing and existing.get("source_command"):
    # Preserve source_command
    source_cmd = existing["source_command"]
else:
    source_cmd = None

# Include in update (Line 450-457)
conn.execute("""
    UPDATE products
    SET base_price=?,
        price=?,
        is_active=?,
        source_command=?,
        updated_at=CURRENT_TIMESTAMP
    WHERE id=?
""", (new_base, new_price, is_active, source_cmd, r["id"]))
```

### 15.3 No Changes Required

**digiflazz.py:**
- `inquiry_postpaid()` - Already complete
- `pay_postpaid()` - Already complete
- `submit_transaction()` - Already complete

**routes/user.py:**
- `inquiry_api()` - Already complete
- `buy()` - Already complete (handles both prepaid and postpaid)

**routes/api.py:**
- Webhook endpoint - Already functional

---

## 16. MIGRATION ORDER

### Phase 1: Database Preparation (1-2 hours)

**Step 1.1: Create Migration Script**
- Create `migrations/add_source_command.py`
- Write upgrade() function
- Write downgrade() function
- Add validation checks

**Step 1.2: Test Migration on Copy**
```bash
# Copy production database
cp database.db database_test.db

# Test migration
python migrations/add_source_command.py --test

# Verify schema
sqlite3 database_test.db ".schema products"
```

**Step 1.3: Backup Production**
```bash
# Full backup
./backup_production.sh

# Verify backup integrity
sqlite3 database.db.backup "SELECT COUNT(*) FROM products;"
```

**Step 1.4: Execute Migration**
```bash
# Stop app
systemctl stop garudatel

# Run migration
python migrations/add_source_command.py --production

# Verify
sqlite3 database.db "SELECT source_command, COUNT(*) FROM products GROUP BY source_command;"

# Start app
systemctl start garudatel
```

---

### Phase 2: Backend Implementation (2-3 hours)

**Step 2.1: Modify models.py**
- Update `upsert_product()` function
- Add `classify_product()` function
- Test with existing data

**Step 2.2: Modify routes/admin.py**
- Update `pricelist_fetch()`
- Update `pricelist_import()`
- Update `pricelist_sync()`
- Test sync functionality

**Step 2.3: Verify Backend**
```bash
# Test prepaid sync
curl -X POST http://localhost:5000/admin/pricelist/fetch \
  -d '{"cmd": "prepaid"}'

# Test postpaid sync
curl -X POST http://localhost:5000/admin/pricelist/fetch \
  -d '{"cmd": "pasca"}'

# Verify source_command populated
sqlite3 database.db "SELECT sku, type, source_command FROM products LIMIT 10;"
```

---

### Phase 3: UI Enhancement (2-3 hours)

**Step 3.1: Enhance Product Display**
- Update `templates/user/belanja.html`
- Add prepaid/postpaid badges
- Test product selection

**Step 3.2: Enhance Admin Display**
- Update `templates/admin/products.html`
- Add source_command column
- Add classification filter

**Step 3.3: Verify UI**
```bash
# Check user product display
# Navigate to /shop
# Verify badges appear

# Check admin product display
# Navigate to /admin/products
# Verify source_command column visible
```

---

### Phase 4: Integration Testing (2-4 hours)

**Step 4.1: Test Prepaid Flow (MUST NOT BREAK)**
```bash
# Test existing prepaid products
# Select product → Enter target → Enter PIN → Verify success

# Verify:
# - Transaction created
# - Balance debited
# - SN returned
# - Receipt displayed
```

**Step 4.2: Test Postpaid Flow**
```bash
# Test inquiry
# Select postpaid product → Enter customer_no → Verify bill display

# Test payment
# Confirm payment → Enter PIN → Verify success

# Verify:
# - Inquiry session created
# - Payment locked to inquiry amount
# - Balance debited correctly
# - Transaction created
```

**Step 4.3: Test Edge Cases**
```bash
# Test double payment prevention
# Test expired inquiry
# Test price manipulation attempt
# Test insufficient balance
# Test invalid PIN
```

---

### Phase 5: Production Validation (1-2 hours)

**Step 5.1: Data Integrity**
```sql
-- Check products
SELECT source_command, type, COUNT(*) FROM products GROUP BY source_command, type;

-- Check transactions
SELECT COUNT(*) FROM transactions WHERE created_at > datetime('now', '-1 hour');

-- Check inquiry sessions
SELECT status, COUNT(*) FROM inquiry_sessions GROUP BY status;
```

**Step 5.2: Functional Validation**
- Admin sync works
- Product display correct
- Transactions processing
- Balance calculations correct
- No errors in logs

**Step 5.3: Performance Check**
```bash
# Check response times
curl -w "@curl-format.txt" -o /dev/null -s http://localhost:5000/shop

# Check database size
du -h database.db

# Check application logs
tail -f logs/application.log | grep ERROR
```

---

### Phase 6: Monitoring & Rollback Readiness (Ongoing)

**Step 6.1: Monitor First 24 Hours**
- Watch error logs
- Check transaction success rate
- Monitor user reports
- Track system performance

**Step 6.2: Rollback Criteria**
- Transaction failure rate > 5%
- Database errors
- Balance calculation errors
- User-reported critical bugs

**Step 6.3: Rollback Execution (If Needed)**
```bash
# Stop app
systemctl stop garudatel

# Restore database
cp database.db.backup.YYYYMMDD_HHMMSS database.db

# Restore code
git reset --hard <previous-commit>

# Start app
systemctl start garudatel

# Verify rollback
# Test prepaid transaction
# Verify no errors
```

---

## IMPLEMENTATION CHECKLIST

### Pre-Implementation
- [ ] Read all audit documentation
- [ ] Understand current architecture
- [ ] Review Digiflazz documentation
- [ ] Create full system backup
- [ ] Prepare rollback plan
- [ ] Set up test environment

### Phase 1: Database
- [ ] Create migration script
- [ ] Test migration on copy
- [ ] Backup production database
- [ ] Execute migration
- [ ] Verify schema changes
- [ ] Test database queries

### Phase 2: Backend
- [ ] Modify models.py
- [ ] Modify routes/admin.py
- [ ] Add classification function
- [ ] Test backend functions
- [ ] Verify sync functionality
- [ ] Check error handling

### Phase 3: UI
- [ ] Update user templates
- [ ] Update admin templates
- [ ] Add classification badges
- [ ] Test responsive design
- [ ] Verify accessibility

### Phase 4: Testing
- [ ] Unit tests
- [ ] Integration tests
- [ ] Edge case tests
- [ ] Performance tests
- [ ] Security tests
- [ ] User acceptance tests

### Phase 5: Deployment
- [ ] Code review
- [ ] Final backup
- [ ] Deploy to production
- [ ] Verify deployment
- [ ] Monitor logs
- [ ] Check metrics

### Phase 6: Post-Deployment
- [ ] Monitor for 24 hours
- [ ] Fix any issues
- [ ] Update documentation
- [ ] Train admin users
- [ ] Close implementation ticket

---

## PRODUCTION DATA REQUIREMENTS SUMMARY

**CRITICAL: The following production data is REQUIRED before implementation:**

1. **Current Product Distribution:**
   ```sql
   SELECT type, COUNT(*) FROM products GROUP BY type;
   ```

2. **Transaction Pattern:**
   ```sql
   SELECT 
     p.type,
     COUNT(t.id) as tx_count,
     SUM(t.price) as total_value
   FROM transactions t
   JOIN products p ON t.sku = p.sku
   GROUP BY p.type;
   ```

3. **Product Source Analysis:**
   - Which products were synced via `cmd=prepaid`?
   - Which products were synced via `cmd=pasca`?
   - Which products were added manually?

4. **Data Quality Check:**
   ```sql
   SELECT COUNT(*) FROM products WHERE type IS NULL OR type = '';
   SELECT COUNT(*) FROM products WHERE type NOT IN ('prepaid', 'postpaid');
   ```

**Without this data, we risk:**
- Incorrect classification of existing products
- Breaking existing transactions
- Data loss during migration
- Incorrect business logic

---

## RISK ASSESSMENT

### Low Risk (Safe to Proceed)
- ✅ Adding new database fields (non-breaking)
- ✅ Enhancing UI templates (additive)
- ✅ Adding classification function (new code)
- ✅ Improving logging (non-functional)

### Medium Risk (Test Thoroughly)
- ⚠️ Modifying upsert_product() (critical function)
- ⚠️ Changing sync logic (affects data integrity)
- ⚠️ Database migration (requires backup)

### High Risk (Review Required)
- 🔴 Modifying transaction flow (DO NOT DO)
- 🔴 Changing balance logic (DO NOT DO)
- 🔴 Modifying inquiry security (DO NOT DO)

### Zero Tolerance (DO NOT MODIFY)
- ❌ Prepaid transaction flow (production-stable)
- ❌ Balance calculation (mission-critical)
- ❌ Inquiry session locking (security-critical)
- ❌ Auto-tier margin system (recently verified)

---

## SUCCESS CRITERIA

### Functional Requirements
- ✅ All existing prepaid products work without changes
- ✅ New products synced with correct classification
- ✅ Postpaid inquiry returns correct bill details
- ✅ Postpaid payment uses server-side price validation
- ✅ Balance calculations remain accurate
- ✅ Transaction history preserved
- ✅ Admin sync functionality works
- ✅ UI displays product classification clearly

### Non-Functional Requirements
- ✅ Zero breaking changes to prepaid flow
- ✅ Database migration reversible
- ✅ Performance not degraded
- ✅ Security controls maintained
- ✅ Error handling improved
- ✅ Logging enhanced
- ✅ Documentation updated
- ✅ Test coverage adequate

### Business Requirements
- ✅ Admin can distinguish prepaid vs postpaid
- ✅ Users see clear product classification
- ✅ Transactions processed correctly
- ✅ Revenue calculations accurate
- ✅ Reporting remains functional
- ✅ No user training required for existing features

---

## CONCLUSION

This implementation plan provides a comprehensive, evidence-based strategy for implementing PREPAID and POSTPAID Digiflazz architecture with:

1. **Clear Classification:** `cmd` parameter as source of truth
2. **No Guessing:** Unknown products remain unknown
3. **Security First:** Server-side validation for postpaid
4. **Backward Compatible:** Zero breaking changes for prepaid
5. **Data-Driven:** Requires production data for safe implementation

**Key Strengths:**
- Infrastructure already 90% complete
- Postpaid flow already implemented and secure
- Prepaid flow production-stable
- Clear migration path
- Comprehensive rollback plan

**Key Dependencies:**
- Production database analysis
- Product source history
- Transaction pattern data
- Admin approval for migration

**Estimated Total Effort:** 12-20 hours across 6 phases

**Ready for Review:** YES - Awaiting approval and production data

---

**Document Version:** 1.0  
**Status:** DRAFT - AWAITING REVIEW  
**Next Action:** Review plan → Gather production data → Begin Phase 1

---

END OF IMPLEMENTATION PLAN
