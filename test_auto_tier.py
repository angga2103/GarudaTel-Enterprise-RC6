#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script untuk Auto-Tier Margin implementation.
Verifikasi boundary conditions dan backward compatibility.
"""

import sys
import os
import io

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from models import hitung_harga_final, get_auto_tier_config


def old_formula(bp, mg, role):
    """
    OLD HARDCODED FORMULA - for backward compatibility testing.
    This is the EXACT logic from the original implementation.
    """
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


def test_manual_margin():
    """Test manual margin (margin > 0) - harus tetap sama dengan behavior lama."""
    print("\n=== TEST MANUAL MARGIN ===")

    test_cases = [
        # (base_price, margin, role, expected_price)
        (5000, 1000, 'reguler', 6000),
        (5000, 1000, 'reseller', 5700),
        (10000, 2000, 'reguler', 12000),
        (10000, 2000, 'reseller', 11400),
        (50000, 5000, 'reguler', 55000),
        (50000, 5000, 'reseller', 53500),
    ]

    passed = 0
    failed = 0

    for bp, mg, role, expected in test_cases:
        result = hitung_harga_final(bp, mg, role)
        status = "✓ PASS" if result == expected else "✗ FAIL"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} | BP:{bp:>6} MG:{mg:>4} Role:{role:<8} | Expected:{expected:>6} Got:{result:>6}")

    print(f"\nManual Margin: {passed} passed, {failed} failed")
    return failed == 0


def test_auto_tier_boundaries():
    """Test Auto-Tier boundaries - critical untuk memastikan tidak ada off-by-one error."""
    print("\n=== TEST AUTO-TIER BOUNDARIES ===")

    test_cases = [
        # Tier 1 boundaries
        (0, 0, 'reguler', 1500),
        (0, 0, 'reseller', 500),
        (1, 0, 'reguler', 1501),
        (1, 0, 'reseller', 501),
        (9999, 0, 'reguler', 11499),
        (9999, 0, 'reseller', 10499),
        (10000, 0, 'reguler', 11500),
        (10000, 0, 'reseller', 10500),

        # Tier 1-2 boundary
        (10001, 0, 'reguler', 12001),
        (10001, 0, 'reseller', 10801),

        # Tier 2 boundaries
        (15000, 0, 'reguler', 17000),
        (15000, 0, 'reseller', 15800),
        (25000, 0, 'reguler', 27000),
        (25000, 0, 'reseller', 25800),

        # Tier 2-3 boundary
        (25001, 0, 'reguler', 27501),
        (25001, 0, 'reseller', 26201),

        # Tier 3 boundaries
        (40000, 0, 'reguler', 42500),
        (40000, 0, 'reseller', 41200),
        (50000, 0, 'reguler', 52500),
        (50000, 0, 'reseller', 51200),

        # Tier 3-4 boundary
        (50001, 0, 'reguler', 53001),
        (50001, 0, 'reseller', 51501),

        # Tier 4 boundaries
        (75000, 0, 'reguler', 78000),
        (75000, 0, 'reseller', 76500),
        (100000, 0, 'reguler', 103000),
        (100000, 0, 'reseller', 101500),
    ]

    passed = 0
    failed = 0

    for bp, mg, role, expected in test_cases:
        result = hitung_harga_final(bp, mg, role)
        status = "✓ PASS" if result == expected else "✗ FAIL"

        if result == expected:
            passed += 1
        else:
            failed += 1

        print(f"{status} | BP:{bp:>8} MG:{mg} Role:{role:<8} | Expected:{expected:>8} Got:{result:>8}")

    print(f"\nAuto-Tier Boundaries: {passed} passed, {failed} failed")
    return failed == 0


def test_old_vs_new_compatibility():
    """
    CRITICAL TEST: Compare OLD hardcoded formula with NEW database-driven formula.
    Every result MUST be identical.
    """
    print("\n=== TEST OLD vs NEW BACKWARD COMPATIBILITY ===")
    print("Verifying new implementation produces IDENTICAL results to old hardcoded logic.\n")

    # Comprehensive test cases covering all ranges
    test_base_prices = [
        # Tier 1 (0-10000)
        0, 1, 5000, 9999, 10000,

        # Tier 2 (10001-25000)
        10001, 15000, 20000, 25000,

        # Tier 3 (25001-50000)
        25001, 30000, 40000, 50000,

        # Tier 4 (50001-100000)
        50001, 75000, 90000, 100000,

        # Tier 5 (>100000) - CRITICAL: Dynamic formula
        100001, 150000, 250000, 500000,
        500001, 600000, 750000, 900000,
        1000000, 1250000, 2000000, 5000000,
    ]

    roles = ['reguler', 'reseller']
    margins = [0]  # Only test AUTO tier (margin=0)

    passed = 0
    failed = 0
    failures = []

    for bp in test_base_prices:
        for mg in margins:
            for role in roles:
                old_result = old_formula(bp, mg, role)
                new_result = hitung_harga_final(bp, mg, role)

                if old_result == new_result:
                    passed += 1
                    status = "✓"
                else:
                    failed += 1
                    status = "✗ FAIL"
                    failures.append({
                        'bp': bp,
                        'mg': mg,
                        'role': role,
                        'old': old_result,
                        'new': new_result,
                        'diff': new_result - old_result
                    })

                print(f"{status} | BP:{bp:>8} MG:{mg} Role:{role:<8} | OLD:{old_result:>8} NEW:{new_result:>8}")

    print(f"\nOLD vs NEW Compatibility: {passed} passed, {failed} failed")

    if failed > 0:
        print("\n⚠️  BACKWARD COMPATIBILITY BROKEN! Failures:")
        for f in failures:
            print(f"  BP:{f['bp']:>8} Role:{f['role']:<8} | OLD:{f['old']:>8} NEW:{f['new']:>8} | Diff:{f['diff']:>+5}")

    return failed == 0


def test_dynamic_formula_tier5():
    """
    Specific test for Tier 5 dynamic formula.
    Verify max(min_value, base_price * percent) logic.
    """
    print("\n=== TEST TIER 5 DYNAMIC FORMULA ===")

    # Test cases specifically for >100000 range
    # OLD formula:
    #   Member: max(4000, bp * 0.008)
    #   Reseller: max(2000, bp * 0.005)

    test_cases = [
        # (base_price, role, min_applies, expected)
        # When min_value applies (bp * percent < min)
        (100001, 'reguler', True, 100001 + 4000),   # 100001*0.008=800 < 4000 → use 4000
        (100001, 'reseller', True, 100001 + 2000),  # 100001*0.005=500 < 2000 → use 2000
        (400000, 'reguler', True, 400000 + 4000),   # 400000*0.008=3200 < 4000 → use 4000
        (400000, 'reseller', True, 400000 + 2000),  # 400000*0.005=2000 = 2000 → use 2000

        # When percentage applies (bp * percent > min)
        (600000, 'reguler', False, 600000 + 4800),  # 600000*0.008=4800 > 4000 → use 4800
        (600000, 'reseller', False, 600000 + 3000), # 600000*0.005=3000 > 2000 → use 3000
        (900000, 'reguler', False, 900000 + 7200),  # 900000*0.008=7200
        (900000, 'reseller', False, 900000 + 4500), # 900000*0.005=4500
        (1000000, 'reguler', False, 1000000 + 8000),  # 1000000*0.008=8000
        (1000000, 'reseller', False, 1000000 + 5000), # 1000000*0.005=5000
        (2000000, 'reguler', False, 2000000 + 16000), # 2000000*0.008=16000
        (2000000, 'reseller', False, 2000000 + 10000),# 2000000*0.005=10000
    ]

    passed = 0
    failed = 0

    for bp, role, min_applies, expected in test_cases:
        result = hitung_harga_final(bp, 0, role)
        old = old_formula(bp, 0, role)

        status = "✓ PASS" if result == expected == old else "✗ FAIL"

        if result == expected == old:
            passed += 1
        else:
            failed += 1

        mode = "MIN" if min_applies else "PCT"
        print(f"{status} [{mode}] | BP:{bp:>8} Role:{role:<8} | Expected:{expected:>8} Got:{result:>8} OLD:{old:>8}")

    print(f"\nTier 5 Dynamic Formula: {passed} passed, {failed} failed")
    return failed == 0


def test_config_load():
    """Test configuration loading."""
    print("\n=== TEST CONFIG LOADING ===")

    config = get_auto_tier_config()

    if 'tiers' not in config:
        print("✗ FAIL: Config missing 'tiers' key")
        return False

    tiers = config['tiers']

    if len(tiers) < 1:
        print("✗ FAIL: Config has no tiers")
        return False

    print(f"✓ PASS: Config loaded with {len(tiers)} tiers")

    # Display tier configuration
    print("\nCurrent Tier Configuration:")
    for tier in tiers:
        level = tier.get('level')
        tier_min = tier.get('min')
        tier_max = tier.get('max')
        tier_type = tier.get('type', 'fixed')

        if tier_type == 'fixed':
            m_mem = tier.get('margin_member')
            m_res = tier.get('margin_reseller')
            max_str = str(tier_max) if tier_max is not None else "∞"
            print(f"  Tier {level} [FIXED]: {tier_min:>8} - {max_str:>8} | Member:+{m_mem:>5} Reseller:+{m_res:>5}")
        elif tier_type == 'dynamic':
            min_mem = tier.get('min_member')
            pct_mem = tier.get('percent_member')
            min_res = tier.get('min_reseller')
            pct_res = tier.get('percent_reseller')
            max_str = str(tier_max) if tier_max is not None else "∞"
            print(f"  Tier {level} [DYNAMIC]: {tier_min:>8} - {max_str:>8}")
            print(f"    Member: max({min_mem}, bp×{pct_mem}) | Reseller: max({min_res}, bp×{pct_res})")

    return True


def main():
    """Run all tests."""
    print("=" * 70)
    print("AUTO-TIER MARGIN TEST SUITE (WITH BACKWARD COMPATIBILITY)")
    print("=" * 70)

    results = []

    # Test 1: Configuration loading
    results.append(("Config Loading", test_config_load()))

    # Test 2: Manual margin (backward compatibility)
    results.append(("Manual Margin", test_manual_margin()))

    # Test 3: Auto-Tier boundaries (tier 1-4)
    results.append(("Auto-Tier Boundaries", test_auto_tier_boundaries()))

    # Test 4: Tier 5 dynamic formula
    results.append(("Tier 5 Dynamic Formula", test_dynamic_formula_tier5()))

    # Test 5: CRITICAL - OLD vs NEW full compatibility
    results.append(("OLD vs NEW Compatibility", test_old_vs_new_compatibility()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    all_passed = True
    for test_name, passed in results:
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{status} | {test_name}")
        if not passed:
            all_passed = False

    print("=" * 70)

    if all_passed:
        print("✓ ALL TESTS PASSED - BACKWARD COMPATIBILITY VERIFIED")
        return 0
    else:
        print("✗ SOME TESTS FAILED - REVIEW REQUIRED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
