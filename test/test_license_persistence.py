#!/usr/bin/env python3
"""
Test license persistence: save and load a license across restarts.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(__file__))

def test_license_persistence():
    """Test that license saves and loads correctly."""
    import license_manager
    
    print("[TEST] License Persistence Test\n")
    
    # Step 1: Create a test license data structure
    print("[1] Creating test license data...")
    license_data = {
        'type': 'commercial',
        'email': 'test@example.com',
        'product_key': 'TEST01-TEST01-TEST01-TEST01',
        'license_skm': 'FAKE_SKM_STRING_FOR_TESTING'
    }
    print(f"    License data: {json.dumps(license_data, indent=2)}")
    
    # Step 2: Save the license
    print("\n[2] Saving license...")
    try:
        saved = license_manager.save_license(license_data)
        if saved:
            print(f"    ✓ License saved successfully")
        else:
            print(f"    ✗ License save returned False")
            return False
    except Exception as e:
        print(f"    ✗ Error saving license: {e}")
        return False
    
    # Step 3: Load and verify the license
    print("\n[3] Loading license...")
    try:
        loaded = license_manager.load_license()
        if loaded:
            print(f"    ✓ License loaded: {json.dumps(loaded, indent=2)}")
        else:
            print(f"    ✗ No license data found")
            return False
    except Exception as e:
        print(f"    ✗ Error loading license: {e}")
        return False
    
    # Step 4: Verify license type
    print("\n[4] Checking license type...")
    try:
        lic_type = license_manager.license_type()
        print(f"    License type: {lic_type}")
        if lic_type == 'commercial':
            print(f"    ✓ License type is commercial")
        else:
            print(f"    ✗ Expected 'commercial', got '{lic_type}'")
            return False
    except Exception as e:
        print(f"    ✗ Error checking license type: {e}")
        return False
    
    # Step 5: Cleanup
    print("\n[5] Cleaning up test license...")
    try:
        license_manager.clear_license()
        print(f"    ✓ Test license cleared")
    except Exception as e:
        print(f"    ✗ Error clearing license: {e}")
    
    print("\n" + "="*60)
    print("✓ LICENSE PERSISTENCE TEST PASSED")
    print("="*60)
    return True

if __name__ == '__main__':
    try:
        success = test_license_persistence()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n✗ FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
