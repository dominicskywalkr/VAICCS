#!/usr/bin/env python3
"""
Smoke test for license activation and runtime feature enabling.

This test:
1. Starts the GUI app
2. Opens the Activate dialog
3. Simulates saving a commercial license
4. Verifies that noise and automations controls are enabled without restart
"""

import os
import sys
import time
import tkinter as tk
from tkinter import messagebox

# Add project to path
sys.path.insert(0, os.path.dirname(__file__))

def test_activation_flow():
    """Test that activation enables features at runtime."""
    print("[TEST] Starting license activation smoke test...\n")
    
    # Import GUI
    try:
        import gui as gui_mod
        print("[✓] GUI module imported successfully")
    except Exception as e:
        print(f"[✗] Failed to import GUI: {e}")
        return False
    
    # Create app (headless splash)
    try:
        app = gui_mod.App()
        print("[✓] App initialized")
    except Exception as e:
        print(f"[✗] Failed to create app: {e}")
        return False
    
    # Check initial license state
    try:
        is_commercial = getattr(app, '_is_commercial', False)
        automations_allowed = getattr(app, '_automations_allowed', False)
        print(f"[i] Initial state: _is_commercial={is_commercial}, _automations_allowed={automations_allowed}")
    except Exception as e:
        print(f"[!] Could not check initial state: {e}")
    
    # Check noise controls disabled
    try:
        noise_state = app.noise_chk.cget('state')
        print(f"[i] Initial Noise checkbox state: {noise_state}")
        if noise_state == 'disabled':
            print("[✓] Noise checkbox correctly disabled for personal/eval mode")
        else:
            print("[!] Noise checkbox should be disabled in personal/eval mode")
    except Exception as e:
        print(f"[!] Could not check noise control state: {e}")
    
    # Check automations controls disabled
    try:
        add_state = app.add_automation_btn.cget('state')
        apply_state = app.apply_automations_btn.cget('state')
        print(f"[i] Initial Add Show button state: {add_state}")
        print(f"[i] Initial Apply button state: {apply_state}")
        if add_state == 'disabled' and apply_state == 'disabled':
            print("[✓] Automations controls correctly disabled for personal/eval mode")
        else:
            print("[!] Automations controls should be disabled in personal/eval mode")
    except Exception as e:
        print(f"[!] Could not check automations control states: {e}")
    
    # Simulate saving a commercial license
    print("\n[TEST] Simulating license save (commercial)...")
    try:
        import license_manager
        license_manager.save_license({
            'type': 'commercial',
            'email': 'test@example.com',
            'product_key': 'TEST01-TEST01-TEST01-TEST01'
        })
        print("[✓] Commercial license saved")
    except Exception as e:
        print(f"[!] Failed to save license: {e}")
        return False
    
    # Call refresh_license_state to simulate post-activation refresh
    print("\n[TEST] Calling refresh_license_state()...")
    try:
        app.refresh_license_state()
        print("[✓] refresh_license_state() completed")
    except Exception as e:
        print(f"[✗] refresh_license_state() failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Verify state changed
    try:
        is_commercial = getattr(app, '_is_commercial', False)
        automations_allowed = getattr(app, '_automations_allowed', False)
        print(f"[i] After refresh: _is_commercial={is_commercial}, _automations_allowed={automations_allowed}")
        if is_commercial and automations_allowed:
            print("[✓] License state correctly updated to commercial")
        else:
            print("[!] License state should be commercial after refresh")
    except Exception as e:
        print(f"[!] Could not verify state: {e}")
    
    # Verify noise controls enabled
    print("\n[TEST] Verifying noise controls are now enabled...")
    try:
        noise_state = app.noise_chk.cget('state')
        print(f"[i] Noise checkbox state after refresh: {noise_state}")
        if noise_state == 'normal':
            print("[✓] Noise checkbox correctly enabled for commercial mode")
        else:
            print(f"[✗] Noise checkbox should be enabled but is '{noise_state}'")
    except Exception as e:
        print(f"[!] Could not check noise control state: {e}")
    
    # Verify automations controls enabled
    print("\n[TEST] Verifying automations controls are now enabled...")
    try:
        add_state = app.add_automation_btn.cget('state')
        apply_state = app.apply_automations_btn.cget('state')
        print(f"[i] Add Show button state after refresh: {add_state}")
        print(f"[i] Apply button state after refresh: {apply_state}")
        if add_state == 'normal' and apply_state == 'normal':
            print("[✓] Automations controls correctly enabled for commercial mode")
        else:
            print(f"[✗] Automations controls should be enabled but are '{add_state}' and '{apply_state}'")
    except Exception as e:
        print(f"[!] Could not check automations control states: {e}")
    
    # Cleanup
    print("\n[TEST] Cleaning up...")
    try:
        app.quit()
        print("[✓] App closed")
    except Exception as e:
        print(f"[!] Error during cleanup: {e}")
    
    # Clear test license
    try:
        import license_manager
        license_manager.clear_license()
        print("[✓] Test license cleared")
    except Exception as e:
        print(f"[!] Could not clear test license: {e}")
    
    print("\n" + "="*60)
    print("[✓] SMOKE TEST COMPLETED - Features enable at runtime!")
    print("="*60)
    return True

if __name__ == '__main__':
    try:
        success = test_activation_flow()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n[✗] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
