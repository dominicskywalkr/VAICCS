"""
Test script that runs the real launcher like the user would
"""
import subprocess
import sys
import time

print("=" * 60)
print("TEST: Running Real Application")
print("=" * 60)

# Run the actual launcher
print("\n[TEST] Starting application...")
proc = subprocess.Popen(
    [sys.executable, "launcher.py"],
    cwd=r"c:\Users\domin\OneDrive\Desktop\python apps\closed captioning",
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1
)

print("[TEST] Waiting 10 seconds for app to start...")
time.sleep(10)

print("\n[TEST] Terminating application...")
proc.terminate()

# Wait for it to close
print("[TEST] Waiting for graceful close...")
try:
    proc.wait(timeout=5)
    print("[TEST] Process exited cleanly!")
except subprocess.TimeoutExpired:
    print("[TEST] Process didn't exit after 5 seconds, forcing kill...")
    proc.kill()
    proc.wait()
    print("[TEST] Process killed")

print("\n[TEST] Collecting output:")
for line in proc.stdout:
    print(f"  {line.rstrip()}")

print("\n[TEST] Done!")
