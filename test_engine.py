from main import CaptionEngine
import time

def cb(t):
    print('CB:', t)

eng = CaptionEngine(demo=True)
print('starting engine (demo=True)')
eng.start(cb)
try:
    time.sleep(2)
finally:
    eng.stop()
    print('engine stopped')
