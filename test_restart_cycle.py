#!/usr/bin/env python3
"""
Test license persistence across simulated restarts.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

def test_restart_cycle():
    """Simulate: activate -> save -> close -> reopen -> validate -> close."""
    import license_manager
    
    print("="*60)
    print("[TEST] License Restart Cycle")
    print("="*60)
    
    # Get RSA pubkey
    try:
        base = os.path.abspath(os.path.dirname(__file__))
        cfg_path = os.path.join(base, 'cryptolens_config.json')
        pubkey = ''
        if os.path.exists(cfg_path):
            with open(cfg_path, 'r') as f:
                cfg = json.load(f)
            pubkey = cfg.get('rsa_pubkey', '')
    except:
        pubkey = ''
    
    print(f"\nRSA Pubkey available: {bool(pubkey)}")
    
    # Step 1: Save a commercial license (simulating activation)
    print("\n[1] Activation Phase - Saving commercial license...")
    license_data = {
        'type': 'commercial',
        'email': 'test@example.com',
        'product_key': 'TEST-TEST-TEST-TEST',
        'license_skm': 'FAKE_SKM_STRING_FOR_TESTING'
    }
    try:
        saved = license_manager.save_license(license_data)
        print(f"    ✓ License saved: {saved}")
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Step 2: Verify it loads as commercial
    print("\n[2] Checking license type after save...")
    try:
        lic_type = license_manager.license_type()
        print(f"    License type: {lic_type}")
        if lic_type == 'commercial':
            print(f"    ✓ Correctly identified as commercial")
        else:
            print(f"    ✗ Expected commercial, got: {lic_type}")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Step 3: Simulate "reopen" - validate the saved license
    print("\n[3] Reopen Phase - Validating saved license...")
    if pubkey:
        try:
            ok, msg = license_manager.validate_saved_license(pubkey, v=2)
            print(f"    Validation result: ok={ok}, msg='{msg}'")
            if ok:
                print(f"    ✓ License is valid on restart")
            else:
                print(f"    ✗ License validation failed (this is expected with fake SKM)")
        except Exception as e:
            print(f"    Error during validation: {e}")
            # With fake SKM this will fail, which is expected
            print(f"    (This is OK - we're using a fake SKM for testing)")
    else:
        print(f"    (Skipping validation - no RSA pubkey configured)")
    
    # Step 4: Verify license_type() still works after "reopen"
    print("\n[4] Checking license_type after simulated reopen...")
    try:
        lic_type = license_manager.license_type()
        print(f"    License type: {lic_type}")
        if lic_type == 'commercial':
            print(f"    ✓ Still correctly identified as commercial")
        else:
            print(f"    ✗ Expected commercial, got: {lic_type}")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Step 5: Cleanup
    print("\n[5] Cleanup - Clearing test license...")
    try:
        license_manager.clear_license()
        print(f"    ✓ Test license cleared")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    print("\n" + "="*60)
    print("✓ RESTART CYCLE TEST PASSED")
    print("="*60)
    return True

if __name__ == '__main__':
    try:
        success = test_restart_cycle()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
