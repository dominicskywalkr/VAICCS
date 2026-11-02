#!/usr/bin/env python3
"""
Comprehensive test: simulate full activation and restart cycle.
This mimics what happens when a user:
1. Opens app (personal/eval mode)
2. Activates with email+key
3. Closes and reopens
4. Should see commercial features enabled
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

def test_full_activation_flow():
    """Full lifecycle test."""
    import license_manager
    
    print("="*70)
    print("[FULL TEST] Activation Lifecycle")
    print("="*70)
    
    # Clear any existing license first
    print("\n[0] Cleanup - removing any existing license...")
    try:
        license_manager.clear_license()
        print("    ✓ Cleared")
    except:
        pass
    
    # Phase 1: Initial boot (personal/eval)
    print("\n[Phase 1] Initial Boot (Personal/Eval Mode)")
    print("-" * 70)
    try:
        lic_type = license_manager.license_type()
        print(f"    License type on first boot: '{lic_type}'")
        if lic_type == '':
            print(f"    ✓ Correctly detected as personal/eval (empty string)")
        else:
            print(f"    ⚠ Expected empty string, got: '{lic_type}'")
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Phase 2: User activates
    print("\n[Phase 2] User Activates with Product Key")
    print("-" * 70)
    license_data = {
        'type': 'commercial',
        'email': 'user@example.com',
        'product_key': 'XYZAB-XYZAB-XYZAB-XYZAB',
        'license_skm': 'SIMULATED_SKM_STRING'
    }
    try:
        saved = license_manager.save_license(license_data)
        if saved:
            print(f"    ✓ License saved successfully")
        else:
            print(f"    ✗ License save failed")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Verify immediate state
    try:
        lic_type = license_manager.license_type()
        print(f"    License type after activation: '{lic_type}'")
        if lic_type == 'commercial':
            print(f"    ✓ Correctly identified as commercial")
        else:
            print(f"    ✗ Expected 'commercial', got: '{lic_type}'")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Phase 3: Close and Reopen (simulate restart)
    print("\n[Phase 3] Restart: Close and Reopen")
    print("-" * 70)
    print("    (Simulating program restart...)")
    
    # Reload license from disk
    try:
        loaded = license_manager.load_license()
        if loaded and loaded.get('type') == 'commercial':
            print(f"    ✓ License reloaded from disk")
        else:
            print(f"    ✗ Failed to reload license")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Check license type after restart
    try:
        lic_type = license_manager.license_type()
        print(f"    License type on restart: '{lic_type}'")
        if lic_type == 'commercial':
            print(f"    ✓ License PERSISTED: Still commercial after restart")
        else:
            print(f"    ✗ LICENSE LOST: Expected 'commercial', got: '{lic_type}'")
            return False
    except Exception as e:
        print(f"    ✗ Error: {e}")
        return False
    
    # Phase 4: Cleanup
    print("\n[Phase 4] Cleanup")
    print("-" * 70)
    try:
        license_manager.clear_license()
        print(f"    ✓ Test license cleared")
    except Exception as e:
        print(f"    ✗ Error: {e}")
    
    print("\n" + "="*70)
    print("✓ FULL ACTIVATION LIFECYCLE TEST PASSED")
    print("  License persists correctly across restart")
    print("="*70)
    return True

if __name__ == '__main__':
    try:
        success = test_full_activation_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
