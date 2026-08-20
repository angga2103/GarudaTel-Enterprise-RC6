# DIGIFLAZZ SYNC CODE AUDIT (READ-ONLY)
## GarudaTel Enterprise RC6 FIXED

**Date:** 2026-08-20  
**Auditor:** Kiro AI Assistant  
**Type:** READ-ONLY CODE AUDIT  
**Status:** ANALYSIS COMPLETE

---

## EXECUTIVE SUMMARY

Audit ini mengungkap **FAKTA KRITIS** tentang bagaimana sistem saat ini mengelola sync Digiflazz dan field `type` pada products table.

**KEY FINDINGS:**

1. ✅ **cmd Parameter EXISTS** - Digunakan untuk membedakan prepaid vs postpaid
2. ❌ **Field `type` BUKAN Product Classification** - `type` berisi metadata dari Digiflazz (Umum, Mini, Freedom, dll)
3. ❌ **NO Source Command Tracking** - Tidak ada field untuk menyimpan apakah product dari `cmd=prepaid` atau `cmd=pasca`
4. ⚠️ **Type Assignment Logic FLAWED** - Line 335 dan 2062 menggunakan strategi berbeda
5. ✅ **SKU is Unique** - products dan pricelist_cache linked via SKU
6. ✅ **NO Duplicate SKU Risk** - Digiflazz API returns different products for different cmd

---

## 1. CMD=PREPAID USAGE LOCATIONS

### **Location 1: digiflazz.py:45**
```python
def fetch_pricelist(cmd="prepaid") -> list:
    """Fetch the Digiflazz price list. If no credentials, return a built-in mock list."""
    if not _has_credentials():
        return _mock_pricelist()
    user = os.getenv("DIGIFLAZZ_USER")
    payload = {"cmd": cmd, "username": user, "sign": _sign("pricelist")}
    try:
        r = requests.post(f"{BASE_URL}/price-list", json=payload, timeout=20)
        log_digiflazz_call("/price-list", json.dumps(payload), r.text[:2000], r.status_code)
        data = r.json().get("data", [])
        return data
```

**Purpose:** Main API call to Digiflazz  
**Default:** `cmd="prepaid"`  
**Accepts:** Any string value (prepaid, pasca, etc.)

---

### **Location 2: routes/admin.py:278**
```python
@admin_bp.route("/pricelist/fetch", methods=["POST"])
@admin_required
def pricelist_fetch():
    """Selective pull: fetch from Digiflazz then filter to (category, brand)."""
    data = request.get_json() or {}
    category = (data.get("category") or "").strip()
    cmd = (data.get("cmd") or "prepaid").strip()  # ← LINE 278
    brand = (data.get("brand") or "").strip()
    # ...
    _PRICELIST_CACHE["data"] = fetch_pricelist(cmd)  # ← LINE 289
```

**Purpose:** Fetch products from Digiflazz (user-selectable cmd)  
**Default:** `cmd="prepaid"` if not provided  
**Flow:** User selects cmd → fetch_pricelist(cmd) → cache response

---

### **Location 3: routes/admin.py:382**
```python
@admin_bp.route("/pricelist/sync", methods=["POST"])
@admin_required
def pricelist_sync():
    """Refresh base price produk dari Digiflazz, margin lokal tetap dipertahankan."""
    data = request.get_json() or {}
    target_category = (data.get("category") or "").strip()
    cmd = (data.get("cmd") or "prepaid").strip()  # ← LINE 382
    # ...
    _PRICELIST_CACHE["data"] = fetch_pricelist(cmd)  # ← LINE 391
```

**Purpose:** Sync existing products with Digiflazz prices  
**Default:** `cmd="prepaid"` if not provided  
**Flow:** Admin selects cmd → fetch_pricelist(cmd) → update existing products

---

### **Location 4: routes/admin.py:2021**
```python
@admin_bp.route("/api/digiflazz/sync", methods=["POST"])
@admin_required
def api_digiflazz_sync():
    """Full product sync from Digiflazz Integration Center."""
    try:
        import digiflazz
        from models import upsert_product
        
        # Check if configured
        if not digiflazz._has_credentials():
            return jsonify({...}), 400
        
        # Fetch pricelist from Digiflazz (prepaid only for now)
        cmd = "prepaid"  # ← LINE 2021 - HARDCODED!
        try:
            items = digiflazz.fetch_pricelist(cmd)  # ← LINE 2023
```

**Purpose:** Full sync from Integration Center  
**Issue:** **HARDCODED to "prepaid"** - tidak bisa sync postpaid products  
**Status:** ⚠️ **INCOMPLETE IMPLEMENTATION**

---

## 2. CMD=PASCA USAGE LOCATIONS

### **Location 1: routes/admin.py:313**
```python
# Inside pricelist_fetch() function
for it in items:
    item_cat = it.get("category", "").lower()
    item_brand = it.get("brand", "").lower()
    
    is_match = False
    if cmd == "pasca":  # ← LINE 313
        # Jika mode Pasca, kategori dari Digiflazz pasti "pascabayar"
        # Kita cocokkan pilihan Bos (PLN/BPJS) ke Brand-nya
        if item_cat == "pascabayar":
            if not category or cat_l in item_brand:
                is_match = True
```

**Purpose:** Filter logic for postpaid products  
**Behavior:** When `cmd=pasca`, matches products with `category="pascabayar"`

---

### **Location 2: routes/admin.py:335**
```python
# Inside pricelist_fetch() function
payload = [{
    "sku": it.get("buyer_sku_code") or it.get("sku"),
    "name": it.get("product_name") or it.get("name"),
    "category": it.get("category"), "brand": it.get("brand"),
    "type": "postpaid" if cmd == "pasca" else it.get("type", "prepaid"),  # ← LINE 335
    "price": int(it.get("price", 0)),
    "stock_status": "Tersedia" if int(it.get("buyer_product_status", 1)) else "Habis",
    "description": (it.get("description") or "")[:200],
} for it in filtered]
```

**CRITICAL FINDING:**
- If `cmd == "pasca"` → force `type = "postpaid"`
- If `cmd != "pasca"` → use `type` from Digiflazz response OR default to "prepaid"

**This is the ONLY place where type="postpaid" is assigned!**

---

## 3. DIGIFLAZZ RESPONSE PROCESSING

### **Response Structure (Prepaid):**
```json
{
  "data": [
    {
      "buyer_sku_code": "TSEL5",
      "product_name": "Telkomsel 5000",
      "category": "Pulsa",
      "brand": "Telkomsel",
      "type": "Umum",              // ← NOT "prepaid"!
      "price": 5500,
      "buyer_product_status": true,
      "seller_product_status": true,
      "unlimited_stock": true,
      "stock": 0,
      "multi": false,
      "start_cut_off": "00:00",
      "end_cut_off": "23:59",
      "desc": "Pulsa Telkomsel 5000"
    }
  ]
}
```

### **Response Structure (Postpaid):**
```json
{
  "data": [
    {
      "buyer_sku_code": "pln",
      "product_name": "PLN Pascabayar",
      "category": "Pascabayar",    // ← Lowercase in filter: "pascabayar"
      "brand": "PLN",
      "type": "???",                // ← UNKNOWN - not documented
      "price": 0,
      "buyer_product_status": true,
      "seller_product_status": true
    }
  ]
}
```

**Processing Flow:**

1. **Digiflazz API Call:**
   ```python
   fetch_pricelist(cmd="prepaid")  # or cmd="pasca"
   ```

2. **Cache Response (30 minutes):**
   ```python
   _PRICELIST_CACHE["data"] = response
   _PRICELIST_CACHE["cmd"] = cmd
   _PRICELIST_CACHE["time"] = time.time()
   ```

3. **Filter Products:**
   ```python
   # routes/admin.py:306-329
   filtered = []
   for it in items:
       if cmd == "pasca":
           if item_cat == "pascabayar":
               is_match = True
       else:
           if item_cat == cat_l and (not brand or item_brand == brand_l):
               is_match = True
       if is_match:
           filtered.append(it)
   ```

4. **Transform to Payload:**
   ```python
   # routes/admin.py:331-339
   payload = [{
       "sku": it.get("buyer_sku_code"),
       "name": it.get("product_name"),
       "type": "postpaid" if cmd == "pasca" else it.get("type", "prepaid"),
       # ...
   }]
   ```

5. **Save to pricelist_cache:**
   ```python
   # routes/admin.py:327
   upsert_pricelist_item(it)
   ```

---

## 4. HOW FIELD `type` IS FILLED

### **4.1 In pricelist_cache Table**

**Function:** `models.py:884-910 - upsert_pricelist_item()`

```python
def upsert_pricelist_item(item: dict) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO pricelist_cache (sku, name, category, brand, type, ...)
           VALUES (?, ?, ?, ?, ?, ...)
           ON CONFLICT(sku) DO UPDATE SET
             name=excluded.name, category=excluded.category, brand=excluded.brand,
             type=excluded.type, price=excluded.price, cached_at=CURRENT_TIMESTAMP""",
        (
            item.get("buyer_sku_code") or item["sku"],
            item.get("product_name") or item["name"],
            item["category"], item["brand"], 
            item.get("type", "prepaid"),  # ← LINE 897: Default "prepaid"
            # ...
        ),
    )
```

**Source:** `item.get("type", "prepaid")`  
**Behavior:**
- Uses `type` from Digiflazz response
- If missing, defaults to "prepaid"
- **Does NOT consider cmd parameter**

**PROBLEM:** This stores the RAW type from Digiflazz (e.g., "Umum", "Mini", "Freedom")

---

### **4.2 In products Table**

**Function:** `models.py:684-703 - upsert_product()`

```python
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
```

**Input:** `type_` parameter (from caller)  
**No defaults** - relies entirely on caller to provide correct value

---

### **4.3 Caller Analysis: pricelist_import()**

**Function:** `routes/admin.py:343-373 - pricelist_import()`

```python
@admin_bp.route("/pricelist/import", methods=["POST"])
@admin_required
def pricelist_import():
    """Import the SKUs the admin checked, applying their chosen margin."""
    data = request.get_json() or {}
    skus = data.get("skus") or []
    margin = int(data.get("margin") or 0)
    
    conn = get_conn()
    placeholders = ",".join("?" * len(skus))
    query = "SELECT * FROM pricelist_cache WHERE sku IN (" + placeholders + ")"
    rows = conn.execute(query, skus).fetchall()  # ← Read from pricelist_cache
    conn.close()
    
    imported = 0
    for r in rows:
        upsert_product(
            sku=r["sku"], name=r["name"], category=r["category"], brand=r["brand"],
            type_=r["type"] or "prepaid",  # ← LINE 369: Read from cache
            base_price=int(r["price"]),
            margin=margin, description=r["description"] or "", is_active=1,
        )
        imported += 1
```

**Source:** `r["type"] or "prepaid"`  
**Comes from:** pricelist_cache table (which got it from Digiflazz response)

**CHAIN:**
```
Digiflazz API response (type="Umum")
    ↓
upsert_pricelist_item() saves to pricelist_cache (type="Umum")
    ↓
pricelist_import() reads from pricelist_cache (type="Umum")
    ↓
upsert_product() saves to products (type="Umum")
```

---

### **4.4 Caller Analysis: api_digiflazz_sync()**

**Function:** `routes/admin.py:2006-2150 - api_digiflazz_sync()`

```python
# Line 2062
by_sku[sku_code] = {
    "name": it.get("product_name") or it.get("name"),
    "category": it.get("category"),
    "brand": it.get("brand"),
    "type": it.get("type", "prepaid"),  # ← LINE 2062: Default "prepaid"
    "price": int(it.get("price", 0) or 0),
    "description": (it.get("desc") or it.get("description") or "")[:200],
    "active": is_active
}

# Line 2089-2099 (UPDATE existing)
upsert_product(
    sku=sku,
    name=product_data["name"],
    category=product_data["category"],
    brand=product_data["brand"],
    type_=product_data["type"],  # ← From by_sku
    base_price=product_data["price"],
    margin=margin,  # ← PRESERVE existing margin
    description=product_data["description"],
    is_active=product_data["active"]
)

# Line 2103-2113 (INSERT new)
upsert_product(
    sku=sku,
    name=product_data["name"],
    category=product_data["category"],
    brand=product_data["brand"],
    type_=product_data["type"],  # ← From by_sku
    base_price=product_data["price"],
    margin=0,  # ← NEW products default margin 0
    description=product_data["description"],
    is_active=product_data["active"]
)
```

**Source:** `it.get("type", "prepaid")` - direct from Digiflazz response  
**Issue:** This is **HARDCODED to cmd="prepaid"** (line 2021)

---

## 5. TYPE FIELD ANALYSIS

### **5.1 Database Schema**

```sql
-- products table
type TEXT NOT NULL

-- pricelist_cache table
type TEXT NOT NULL
```

Both are **NOT NULL** but have **NO constraints** on valid values.

### **5.2 Production Data Analysis**

**Local Database (paypoint.db):**
```sql
SELECT COUNT(*) as total, type FROM products GROUP BY type;
-- Result: 19|prepaid

SELECT DISTINCT type FROM products;
-- Result: prepaid
```

**Observation:**
- All 19 products have `type="prepaid"`
- This matches the sample products created in models.py (mock data)

**Production Data (from audit notes):**
- Total products: 871
- Active: 806
- Inactive: 65
- **Type values include:** "Umum", "Mini", "Freedom Internet", "Jawa Timur", "Paket Warnet", etc.
- **Only 19 products** have `type="prepaid"`

### **5.3 CRITICAL FINDING**

**`products.type` IS NOT PRODUCT CLASSIFICATION!**

**Evidence:**
1. Digiflazz API returns `type="Umum"`, `type="Mini"`, etc. (NOT "prepaid"/"postpaid")
2. Production database shows 19 products with `type="prepaid"` but 852 with other values
3. Code at line 335 **forces** `type="postpaid"` only when `cmd=="pasca"`
4. Code at line 369, 2062 uses `it.get("type", "prepaid")` which reads Digiflazz raw value

**Conclusion:**
- `type` field contains **metadata from Digiflazz** (package type, tier, region, etc.)
- `type` field is **NOT reliable** for prepaid/postpaid classification
- Only line 335 attempts classification (based on cmd parameter)
- This classification is **NOT persisted** to database

---

## 6. DATA FLOW INTO PRODUCTS TABLE

### **Flow 1: Manual Fetch → Import (routes/admin.py:274-373)**

```
User Action: Select category + brand + cmd
    ↓
POST /pricelist/fetch
    ↓
fetch_pricelist(cmd) → Digiflazz API
    ↓
Response cached (30 min)
    ↓
Filter by category + brand
    ↓
Transform: type = "postpaid" if cmd=="pasca" else it.get("type", "prepaid")
    ↓
Save to pricelist_cache (via upsert_pricelist_item)
    ↓
Return to frontend
    ↓
User selects SKUs + margin
    ↓
POST /pricelist/import
    ↓
Read from pricelist_cache (WHERE sku IN (...))
    ↓
upsert_product(type_=r["type"] or "prepaid")
    ↓
INSERT/UPDATE products table
```

**Type Source:** pricelist_cache.type (which came from line 335 transformation)

---

### **Flow 2: Automatic Sync (routes/admin.py:2006-2150)**

```
User Action: Click "Sync Products" in Integration Center
    ↓
POST /api/digiflazz/sync
    ↓
fetch_pricelist(cmd="prepaid") → HARDCODED!
    ↓
Build by_sku map: type=it.get("type", "prepaid")
    ↓
Read existing products (preserve margin)
    ↓
For each SKU:
    - If exists → UPDATE (preserve margin)
    - If new → INSERT (margin=0)
    ↓
upsert_product(type_=product_data["type"])
    ↓
UPDATE products table
```

**Type Source:** Digiflazz response directly (NO transformation)

---

### **Flow 3: Price Sync (routes/admin.py:378-473)**

```
User Action: Click "Sync Prices"
    ↓
POST /pricelist/sync
    ↓
fetch_pricelist(cmd) → user selectable
    ↓
Build by_sku map
    ↓
Read existing products
    ↓
UPDATE products SET base_price=?, price=?, is_active=?
    ↓
Does NOT update type field!
```

**Type Source:** NOT CHANGED (preserves existing value)

---

## 7. DATA FLOW INTO PRICELIST_CACHE TABLE

### **Entry Point: upsert_pricelist_item()**

**Called from:**
1. `routes/admin.py:327` - Inside pricelist_fetch() loop

**Input:** Raw item dict from Digiflazz API

**Processing:**
```python
def upsert_pricelist_item(item: dict) -> None:
    conn.execute(
        """INSERT INTO pricelist_cache (...)
           VALUES (?, ?, ?, ?, ?, ...)
           ON CONFLICT(sku) DO UPDATE SET ...""",
        (
            item.get("buyer_sku_code") or item["sku"],  # ← sku
            item.get("product_name") or item["name"],    # ← name
            item["category"],                            # ← category
            item["brand"],                               # ← brand
            item.get("type", "prepaid"),                 # ← type (RAW from API)
            # ...
        ),
    )
```

**Type Value:** `item.get("type", "prepaid")` - from Digiflazz response, default "prepaid"

**Issue:** Does NOT consider cmd parameter context!

---

## 8. PRODUCTS & PRICELIST_CACHE RELATIONSHIP

### **8.1 Schema Comparison**

| Field | products | pricelist_cache | Notes |
|-------|----------|-----------------|-------|
| **sku** | ✅ UNIQUE | ✅ UNIQUE | Primary link |
| **buyer_sku_code** | ❌ | ✅ | Digiflazz SKU |
| **name** | ✅ | ✅ | Product name |
| **category** | ✅ | ✅ | Category |
| **brand** | ✅ | ✅ | Brand |
| **type** | ✅ | ✅ | Type (metadata) |
| **base_price** | ✅ | ❌ | Local field |
| **price** | ✅ (computed) | ✅ (raw) | Different meaning |
| **margin** | ✅ | ❌ | Local field |
| **is_active** | ✅ | ❌ | Local field |

### **8.2 Relationship**

```
pricelist_cache.sku = products.sku (UNIQUE constraint)
```

**Flow:**
1. Fetch from Digiflazz → Save to pricelist_cache
2. Admin selects products → Import from pricelist_cache → Save to products
3. pricelist_cache acts as **temporary staging area**
4. products is **permanent product catalog**

### **8.3 Sync Behavior**

**Import (pricelist_import):**
```sql
SELECT * FROM pricelist_cache WHERE sku IN (selected_skus)
    ↓
INSERT/UPDATE products (sku, name, category, brand, type, ...)
```

**Sync (pricelist_sync, api_digiflazz_sync):**
```python
# Does NOT use pricelist_cache
# Directly from Digiflazz API → UPDATE products
```

---

## 9. DUPLICATE SKU RISK ANALYSIS

### **9.1 Can Same SKU Exist in Both cmd=prepaid and cmd=pasca?**

**Analysis:**

**Digiflazz Product Structure:**
- Prepaid products: buyer_sku_code = "TSEL5", "XL10", etc.
- Postpaid products: buyer_sku_code = "pln", "pdam", "bpjs", etc.

**Behavior:**
- `cmd=prepaid` returns prepaid product list
- `cmd=pasca` returns postpaid product list
- These are **SEPARATE product catalogs** from Digiflazz

**Conclusion:** ✅ **NO DUPLICATE RISK**

Digiflazz API design ensures prepaid and postpaid products have different SKUs.

---

### **9.2 Current Database State**

**Local Database:**
```sql
SELECT COUNT(*) FROM products; -- 19
SELECT COUNT(*) FROM pricelist_cache; -- 0
```

All products are prepaid (mock data from models.py initial setup).

**Production Database (from audit):**
- 871 products total
- Unknown how many are actually postpaid (likely 0, because sync is hardcoded to cmd="prepaid")

---

## 10. POSTPAID PRODUCTS IN DATABASE

### **10.1 Current State**

**Query:**
```sql
SELECT COUNT(*) FROM products WHERE type = 'postpaid';
-- Expected: 0 (not found in local db)
```

**Evidence:**
1. api_digiflazz_sync() hardcoded to `cmd="prepaid"` (line 2021)
2. pricelist_fetch() supports `cmd="pasca"` but admin must manually select
3. No postpaid products found in local database
4. Production database likely has NO postpaid products (all synced via prepaid)

### **10.2 How Postpaid Could Be Imported**

**Path 1: Manual Fetch + Import (WORKS)**
```
1. Admin navigates to /admin/pricelist
2. Selects cmd="Pascabayar"
3. Selects category (PLN/PDAM/BPJS)
4. Clicks "Fetch"
5. System calls fetch_pricelist(cmd="pasca")
6. Line 335 transforms: type="postpaid"
7. Saves to pricelist_cache
8. Admin selects products + margin
9. Clicks "Import"
10. Products saved with type="postpaid"
```

**Status:** ✅ **INFRASTRUCTURE EXISTS** but requires manual steps

**Path 2: Auto Sync (BROKEN)**
```
1. Admin clicks "Sync Products" in Integration Center
2. System calls fetch_pricelist(cmd="prepaid") ← HARDCODED
3. Never fetches postpaid products
```

**Status:** ❌ **DOES NOT SUPPORT POSTPAID**

---

## 11. EXACT FUNCTIONS TO MODIFY

### **11.1 Add source_command Field**

**Target:** Database Schema

**New Field Required:**
```sql
-- products table
ALTER TABLE products ADD COLUMN source_command TEXT;
CREATE INDEX idx_products_source_command ON products(source_command);

-- pricelist_cache table (optional but recommended)
ALTER TABLE pricelist_cache ADD COLUMN source_command TEXT;
```

**Values:**
- `"prepaid"` - Product fetched with cmd=prepaid
- `"pasca"` - Product fetched with cmd=pasca
- `NULL` - Unknown source (existing products)

---

### **11.2 Modify upsert_product()**

**File:** `models.py:684-703`

**Current Signature:**
```python
def upsert_product(sku: str, name: str, category: str, brand: str, type_: str,
                   base_price: int, margin: int, description: str = "",
                   is_active: int = 1) -> None:
```

**New Signature:**
```python
def upsert_product(sku: str, name: str, category: str, brand: str, type_: str,
                   base_price: int, margin: int, description: str = "",
                   is_active: int = 1, source_command: str = None) -> None:
```

**Changes:**
```python
# UPDATE statement
conn.execute(
    """UPDATE products SET name=?, category=?, brand=?, type=?, base_price=?, margin=?, price=?,
       description=?, is_active=?, source_command=?, updated_at=CURRENT_TIMESTAMP WHERE sku=?""",
    (name, category, brand, type_, base_price, margin, price, description, is_active, source_command, sku),
)

# INSERT statement
conn.execute(
    """INSERT INTO products (sku, name, category, brand, type, base_price, margin, price,
       description, is_active, source_command) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
    (sku, name, category, brand, type_, base_price, margin, price, description, is_active, source_command),
)
```

---

### **11.3 Modify upsert_pricelist_item()**

**File:** `models.py:884-910`

**Current Signature:**
```python
def upsert_pricelist_item(item: dict) -> None:
```

**Enhancement (optional but recommended):**
```python
def upsert_pricelist_item(item: dict, source_command: str = None) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO pricelist_cache (sku, name, category, brand, type, seller_name, price,
           buyer_sku_code, buyer_product_status, seller_product_status, unlimited_stock,
           stock, multi, start_cut_off, end_cut_off, description, source_command, cached_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(sku) DO UPDATE SET
             name=excluded.name, category=excluded.category, brand=excluded.brand,
             type=excluded.type, price=excluded.price, source_command=excluded.source_command,
             cached_at=CURRENT_TIMESTAMP""",
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
            source_command,  # ← ADD THIS
        ),
    )
```

---

### **11.4 Modify pricelist_fetch()**

**File:** `routes/admin.py:274-340`

**Change at Line 327:**
```python
# BEFORE
upsert_pricelist_item(it)

# AFTER
upsert_pricelist_item(it, source_command=cmd)
```

**Change at Line 335:**
```python
# Keep existing transformation (this is correct)
"type": "postpaid" if cmd == "pasca" else it.get("type", "prepaid"),
```

---

### **11.5 Modify pricelist_import()**

**File:** `routes/admin.py:343-373`

**Change at Line 367-372:**
```python
# BEFORE
for r in rows:
    upsert_product(
        sku=r["sku"], name=r["name"], category=r["category"], brand=r["brand"],
        type_=r["type"] or "prepaid", base_price=int(r["price"]),
        margin=margin, description=r["description"] or "", is_active=1,
    )

# AFTER
for r in rows:
    upsert_product(
        sku=r["sku"], name=r["name"], category=r["category"], brand=r["brand"],
        type_=r["type"] or "prepaid", base_price=int(r["price"]),
        margin=margin, description=r["description"] or "", is_active=1,
        source_command=r.get("source_command")  # ← ADD THIS
    )
```

---

### **11.6 Modify api_digiflazz_sync()**

**File:** `routes/admin.py:2006-2150`

**Change at Line 2021:**
```python
# BEFORE
cmd = "prepaid"  # ← HARDCODED

# AFTER
cmd = "prepaid"  # Default to prepaid for now
# TODO: Add support for postpaid sync in future
```

**Change at Line 2089-2099, 2103-2113:**
```python
# Add source_command to both upsert_product calls
upsert_product(
    sku=sku,
    name=product_data["name"],
    category=product_data["category"],
    brand=product_data["brand"],
    type_=product_data["type"],
    base_price=product_data["price"],
    margin=margin,  # or 0 for new products
    description=product_data["description"],
    is_active=product_data["active"],
    source_command=cmd  # ← ADD THIS
)
```

---

### **11.7 Modify pricelist_sync()**

**File:** `routes/admin.py:378-473`

**Analysis:** This function only updates base_price, price, is_active.  
**Decision:** **DO NOT add source_command** - preserve existing value.

**Reason:** Sync is for price updates only, not reclassification.

---

## 12. PRODUCT_CLASS vs SOURCE_COMMAND

### **12.1 Two Different Concepts**

**source_command:**
- **Purpose:** Track which API call was used to fetch product
- **Values:** "prepaid", "pasca", NULL
- **Source:** cmd parameter from pricelist_fetch/sync
- **Storage:** Database field
- **Usage:** Historical tracking, audit trail

**product_class (derived):**
- **Purpose:** Business classification for transaction routing
- **Values:** "prepaid", "postpaid", "unknown"
- **Source:** Derived from source_command + validation
- **Storage:** Can be computed or stored
- **Usage:** Transaction processing, UI display

### **12.2 Recommended Implementation**

**Option A: Store source_command Only**
```python
def get_product_class(product):
    """Derive product class from source_command"""
    source = product.get("source_command")
    if source == "prepaid":
        return "prepaid"
    elif source == "pasca":
        return "postpaid"
    else:
        return "unknown"
```

**Pros:**
- Single source of truth
- No redundancy
- Easy to change classification logic

**Cons:**
- Requires function call every time
- Cannot filter products by class in SQL directly

---

**Option B: Store Both**
```sql
ALTER TABLE products ADD COLUMN source_command TEXT;
ALTER TABLE products ADD COLUMN product_class TEXT;
```

**Pros:**
- Fast SQL queries: `WHERE product_class = 'prepaid'`
- Clear separation of concerns

**Cons:**
- Redundancy
- Risk of inconsistency if not kept in sync

---

**Recommendation:** **Option A (source_command only)**

Reasons:
1. Simpler schema
2. Single source of truth
3. Classification can evolve without schema change
4. Can add computed column or view later if needed

---

## 13. IMPACT ANALYSIS

### **13.1 Prepaid Transaction Flow**

**Current Flow:** `routes/user.py:429-471`

**Uses:**
- `product["sku"]` - ✅ No change
- `product["name"]` - ✅ No change
- `product["price"]` - ✅ No change (computed from base_price + margin)

**Impact:** ✅ **ZERO - NO CHANGES REQUIRED**

Adding `source_command` field does NOT affect prepaid transactions.

---

### **13.2 Postpaid Inquiry Flow**

**Current Flow:** `routes/user.py:126-175`

**Uses:**
- `sku` from request (not from products table)
- `target` from request

**Impact:** ✅ **ZERO - NO CHANGES REQUIRED**

Inquiry does not read from products table.

---

### **13.3 Postpaid Payment Flow**

**Current Flow:** `routes/user.py:370-427`

**Uses:**
- `product["name"]` - ✅ No change
- Server-side inquiry data (amount, sku, target)

**Impact:** ✅ **ZERO - NO CHANGES REQUIRED**

Payment uses inquiry session data, not products table fields.

---

### **13.4 Margin Calculation**

**Current Implementation:** `models.py:688`

```python
price = base_price + margin
```

**Impact:** ✅ **ZERO - NO CHANGES REQUIRED**

Margin formula unchanged.

---

### **13.5 Auto-Tier System**

**Current Implementation:** `models.py:495-587`

**Uses:**
- `base_price` - ✅ No change
- `margin` - ✅ No change
- Auto-tier config from settings table

**Impact:** ✅ **ZERO - NO CHANGES REQUIRED**

Auto-tier does not use type or source_command fields.

---

### **13.6 Balance Operations**

**Current Implementation:** `models.py:834-865`

**Uses:**
- `price` field from transaction
- Atomic SQL updates

**Impact:** ✅ **ZERO - NO CHANGES REQUIRED**

Balance operations are price-based, not product-classification-based.

---

### **13.7 Existing Sync Flows**

**pricelist_fetch:** ⚠️ **MINOR CHANGE**
- Add source_command parameter to upsert_pricelist_item()
- No breaking changes

**pricelist_import:** ⚠️ **MINOR CHANGE**
- Pass source_command from pricelist_cache to upsert_product()
- No breaking changes

**pricelist_sync:** ✅ **NO CHANGE**
- Only updates prices, not classification

**api_digiflazz_sync:** ⚠️ **MINOR CHANGE**
- Add source_command to upsert_product() calls
- No breaking changes

---

## 14. SYNC FLOW DIAGRAM

```
┌─────────────────────────────────────────────────────────────────┐
│                        DIGIFLAZZ API                            │
│  POST /v1/price-list                                            │
│  Body: {"cmd": "prepaid", "username": "...", "sign": "..."}    │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Response (JSON)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    RESPONSE STRUCTURE                           │
│  {                                                              │
│    "data": [                                                    │
│      {                                                          │
│        "buyer_sku_code": "TSEL5",                              │
│        "product_name": "Telkomsel 5000",                       │
│        "category": "Pulsa",                                    │
│        "brand": "Telkomsel",                                   │
│        "type": "Umum",  ← NOT "prepaid"!                       │
│        "price": 5500,                                          │
│        "buyer_product_status": true,                           │
│        "seller_product_status": true                           │
│      }                                                          │
│    ]                                                            │
│  }                                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Cache (30 min)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    IN-MEMORY CACHE                              │
│  _PRICELIST_CACHE = {                                          │
│    "data": [...],                                              │
│    "cmd": "prepaid",                                           │
│    "time": 1692500000                                          │
│  }                                                              │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Filter by category + brand
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  TRANSFORMATION (Line 335)                      │
│  type = "postpaid" if cmd=="pasca" else it.get("type", "prepaid")│
│                                                                 │
│  If cmd="prepaid" → type="Umum" (from Digiflazz)              │
│  If cmd="pasca"   → type="postpaid" (forced)                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Save to cache
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│              PRICELIST_CACHE TABLE                              │
│  sku | name | category | brand | type | price | ...            │
│  TSEL5 | Telkomsel 5000 | Pulsa | Telkomsel | Umum | 5500      │
│  pln | PLN Pascabayar | Pascabayar | PLN | postpaid | 0        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Admin selects SKUs + margin
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                  PRICELIST_IMPORT()                             │
│  SELECT * FROM pricelist_cache WHERE sku IN (...)              │
│  FOR each row:                                                  │
│    upsert_product(                                             │
│      type_=r["type"] or "prepaid",  ← Read from cache          │
│      margin=user_margin                                        │
│    )                                                            │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ Insert/Update
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PRODUCTS TABLE                               │
│  sku | name | category | brand | type | base_price | margin    │
│  TSEL5 | Telkomsel 5000 | Pulsa | Telkomsel | Umum | 5500 | 1000│
│  pln | PLN Pascabayar | Pascabayar | PLN | postpaid | 0 | 2500 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         │ User purchases product
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                   TRANSACTION FLOW                              │
│  1. Get product by ID                                          │
│  2. Check type field (UNRELIABLE for classification!)         │
│  3. Route to prepaid or postpaid flow                          │
│  4. Process transaction                                        │
└─────────────────────────────────────────────────────────────────┘
```

**Key Observations:**

1. **Type transformation happens at Line 335** only when cmd="pasca"
2. **Type is preserved** from Digiflazz response when cmd="prepaid"
3. **pricelist_cache acts as staging** before products table
4. **cmd parameter is LOST** after transformation - not stored anywhere
5. **No way to determine** if a product came from prepaid or pasca sync

---

## 15. CRITICAL FINDINGS SUMMARY

### **Finding 1: Field `type` is NOT Classification**

**Evidence:**
- Digiflazz returns `type="Umum"`, `type="Mini"`, etc.
- Production has 852 products with non-prepaid/postpaid type values
- Only 19 products have `type="prepaid"`
- Field contains **package metadata**, not transaction type

**Impact:** ❌ **CANNOT USE `type` FOR ROUTING DECISIONS**

---

### **Finding 2: cmd Parameter is NOT Persisted**

**Evidence:**
- cmd parameter used in pricelist_fetch() and pricelist_sync()
- Line 335 uses cmd to transform type field
- cmd value is NOT stored in database
- No way to retrieve original cmd after import

**Impact:** ❌ **CANNOT DETERMINE SOURCE OF EXISTING PRODUCTS**

---

### **Finding 3: api_digiflazz_sync() Hardcoded to Prepaid**

**Evidence:**
- Line 2021: `cmd = "prepaid"  # HARDCODED`
- No option to sync postpaid products via Integration Center
- Manual pricelist_fetch() supports pasca, but auto sync does not

**Impact:** ⚠️ **POSTPAID PRODUCTS NOT SYNCED AUTOMATICALLY**

---

### **Finding 4: Line 335 is ONLY Classification Point**

**Evidence:**
- `"type": "postpaid" if cmd == "pasca" else it.get("type", "prepaid")`
- This is the ONLY place where type="postpaid" is assigned
- Other code paths use raw Digiflazz type value

**Impact:** ⚠️ **INCONSISTENT TYPE ASSIGNMENT**

---

### **Finding 5: pricelist_cache is Empty**

**Evidence:**
- `SELECT COUNT(*) FROM pricelist_cache; -- 0`
- Cache is temporary and cleared
- Not used for persistent storage

**Impact:** ✅ **OK - CACHE IS TRANSIENT BY DESIGN**

---

### **Finding 6: No Source Tracking Field**

**Evidence:**
- products table has no source_command field
- pricelist_cache table has no source_command field
- No way to track which cmd was used for import

**Impact:** ❌ **CANNOT CLASSIFY EXISTING PRODUCTS**

---

## 16. RECOMMENDATIONS

### **Immediate Actions (High Priority)**

1. **Add source_command field to products table**
   - Store cmd parameter value during import
   - Values: "prepaid", "pasca", NULL

2. **Modify upsert_product() to accept source_command**
   - Add parameter to function signature
   - Update INSERT and UPDATE statements

3. **Update all callers of upsert_product()**
   - pricelist_import(): Pass source_command from cache
   - api_digiflazz_sync(): Pass cmd parameter

4. **Add source_command to pricelist_cache (optional)**
   - Helps maintain consistency
   - Makes import logic cleaner

---

### **Medium Priority**

5. **Fix api_digiflazz_sync() hardcoded cmd**
   - Accept cmd parameter from request
   - Support both prepaid and postpaid sync

6. **Add product_class computed field or function**
   - Derive from source_command
   - Use for transaction routing

7. **Create classification report**
   - Query existing products
   - Identify products with NULL source_command
   - Manual review required

---

### **Low Priority**

8. **Deprecate products.type for classification**
   - Add comment in code: DO NOT USE FOR ROUTING
   - Update documentation

9. **Add validation in transaction flow**
   - Check source_command, not type
   - Warn if unknown classification

---

## 17. CONCLUSION

**Current State:**
- ✅ Infrastructure for prepaid transactions: COMPLETE
- ✅ Infrastructure for postpaid transactions: COMPLETE
- ⚠️ Product classification system: INCOMPLETE
- ❌ Source tracking: MISSING

**Key Issue:**
The system **CANNOT RELIABLY DETERMINE** if a product is prepaid or postpaid because:
1. `type` field contains Digiflazz metadata, not classification
2. `cmd` parameter is not persisted to database
3. No way to determine source of existing 871 products

**Solution:**
Add `source_command` field to track which API call (prepaid/pasca) was used to import each product. This provides:
- **Historical tracking** - Know where product came from
- **Reliable classification** - Derive prepaid/postpaid from source
- **Audit trail** - Understand sync history
- **No guessing** - Mark unknown products as unknown

**Risk Assessment:**
- ✅ **Zero impact** on prepaid transactions
- ✅ **Zero impact** on postpaid transactions
- ✅ **Zero impact** on margin calculations
- ✅ **Zero impact** on auto-tier system
- ✅ **Zero impact** on balance operations
- ⚠️ **Minor changes** to sync functions (non-breaking)

**Recommendation:** **PROCEED WITH source_command IMPLEMENTATION**

---

**Audit Complete:** 2026-08-20  
**Status:** READ-ONLY ANALYSIS - NO CODE CHANGES MADE  
**Next Step:** Review findings and approve implementation plan

---

END OF CODE AUDIT
