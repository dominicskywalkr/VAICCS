"""
Test script to debug the exit issue
"""
import sys
import os
import threading
import time

# Add current dir to path
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("TEST SCRIPT: Debugging Exit Issue")
print("=" * 60)

# Patch threading to log all thread creation and destruction
original_thread_init = threading.Thread.__init__
thread_list = []

def patched_init(self, *args, **kwargs):
    thread_list.append(self)
    print(f"[THREAD] Created: {self.name} (daemon={self.daemon})")
    original_thread_init(self, *args, **kwargs)

threading.Thread.__init__ = patched_init

# Now import and run the app
try:
    print("\n[MAIN] Importing GUI module...")
    from gui import App
    
    print("[MAIN] Creating app instance...")
    app = App()
    
    print("\n[MAIN] Listing all active threads:")
    for t in threading.enumerate():
        print(f"  - {t.name} (daemon={t.daemon}, alive={t.is_alive()})")
    
    print("\n[MAIN] App created. Waiting 3 seconds then closing...")
    time.sleep(3)
    
    print("\n[MAIN] Calling app.quit()...")
    app.quit()
    
    print("\n[MAIN] Quit called. Checking threads...")
    time.sleep(1)
    
    print("\n[MAIN] Active threads after quit:")
    for t in threading.enumerate():
        print(f"  - {t.name} (daemon={t.daemon}, alive={t.is_alive()})")
    
    print("\n[MAIN] Done with test script.")
    
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()

print("\nScript finished. Press Ctrl+C to force exit if still hanging...")
time.sleep(2)
print("Exiting...")
