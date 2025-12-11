"""
Test script that mimics launcher.py behavior
"""
import threading
import tkinter as tk
import time
import sys
import os

print("=" * 60)
print("TEST: Mimicking Launcher Behavior")
print("=" * 60)

# Create a simple launcher-like structure
info = {}
loaded_event = threading.Event()

def importer():
    """Mimic the importer thread from launcher.py"""
    try:
        print("[IMPORTER] Starting import...")
        from gui import App
        print("[IMPORTER] Import complete")
        info['module'] = App
    except Exception as e:
        print(f"[IMPORTER] Error: {e}")
        info['error'] = str(e)
    finally:
        loaded_event.set()

# Start the importer thread
print("[MAIN] Starting importer thread...")
t = threading.Thread(target=importer, daemon=True)
t.start()

# Create a small root and wait for import
root = tk.Tk()
root.withdraw()

# Wait for import to complete
print("[MAIN] Waiting for import...")
loaded_event.wait(timeout=30)

if 'error' in info:
    print(f"[MAIN] Import failed: {info['error']}")
    sys.exit(1)

print("[MAIN] Import successful")

# Create the app
App = info['module']
print("[MAIN] Creating app...")
app = App()

print("\n[MAIN] Threads before mainloop:")
for t in threading.enumerate():
    print(f"  - {t.name} (daemon={t.daemon})")

# Schedule quit after 5 seconds
def auto_quit():
    print("\n[TIMER] Auto-quit triggered")
    print(f"[TIMER] Destroying window...")
    app.destroy()
    print(f"[TIMER] Window destroyed, calling quit...")
    app.quit()
    print(f"[TIMER] Quit called")

app.after(5000, auto_quit)

print("\n[MAIN] Starting mainloop...")
app.mainloop()
print("[MAIN] Mainloop exited!")

print("\n[MAIN] Threads after mainloop:")
for t in threading.enumerate():
    print(f"  - {t.name} (daemon={t.daemon})")

print("\n[MAIN] Waiting 2 seconds...")
time.sleep(2)

print("\n[MAIN] Final threads:")
for t in threading.enumerate():
    print(f"  - {t.name} (daemon={t.daemon})")

print("\n[MAIN] Done!")
