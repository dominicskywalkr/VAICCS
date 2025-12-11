"""
Test script to debug exit with mainloop
"""
import sys
import os
import threading
import time

# Add current dir to path
sys.path.insert(0, os.path.dirname(__file__))

print("=" * 60)
print("TEST SCRIPT: Exit with Mainloop")
print("=" * 60)

# Monitor threads
def monitor_threads():
    """Background thread to monitor active threads"""
    while True:
        time.sleep(5)
        print("\n[MONITOR] Active threads:")
        for t in threading.enumerate():
            print(f"  - {t.name} (daemon={t.daemon}, alive={t.is_alive()})")

monitor_thread = threading.Thread(target=monitor_threads, daemon=True)
monitor_thread.start()

try:
    print("\n[MAIN] Importing GUI module...")
    from gui import App
    
    print("[MAIN] Creating app instance...")
    app = App()
    
    print("\n[MAIN] Listing all active threads before mainloop:")
    for t in threading.enumerate():
        print(f"  - {t.name} (daemon={t.daemon}, alive={t.is_alive()})")
    
    print("\n[MAIN] Starting mainloop in 2 seconds, will auto-close in 5 seconds...")
    time.sleep(2)
    
    # Schedule an auto-quit after 5 seconds
    def auto_quit():
        print("\n[TIMER] Auto-quit triggered")
        try:
            app.quit()
        except Exception as e:
            print(f"[ERROR] Failed to quit: {e}")
    
    app.after(5000, auto_quit)
    
    print("[MAIN] Entering mainloop...")
    app.mainloop()
    print("[MAIN] Mainloop exited!")
    
    print("\n[MAIN] Active threads after mainloop:")
    for t in threading.enumerate():
        print(f"  - {t.name} (daemon={t.daemon}, alive={t.is_alive()})")
    
    print("\n[MAIN] Waiting 3 seconds for background threads to finish...")
    time.sleep(3)
    
    print("\n[MAIN] Final active threads:")
    for t in threading.enumerate():
        print(f"  - {t.name} (daemon={t.daemon}, alive={t.is_alive()})")
    
except Exception as e:
    print(f"[ERROR] {e}")
    import traceback
    traceback.print_exc()

print("\nScript finished. Exiting...")
time.sleep(1)
