import time
import os
from main import CaptionEngine

print('Before start: OMP_NUM_THREADS=', os.environ.get('OMP_NUM_THREADS'))

cb_calls = []

def cb(t):
    cb_calls.append(t)

eng = CaptionEngine(demo=True, cpu_threads=4)
print('Starting engine with cpu_threads=4')
eng.start(cb)
# give it a moment
time.sleep(0.5)
print('After start: OMP_NUM_THREADS=', os.environ.get('OMP_NUM_THREADS'))
print('MKL_NUM_THREADS=', os.environ.get('MKL_NUM_THREADS'))
print('OPENBLAS_NUM_THREADS=', os.environ.get('OPENBLAS_NUM_THREADS'))
eng.stop()
print('Engine stopped')
print('Callback samples:', len(cb_calls))
