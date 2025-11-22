import sys
# ensure current dir on path
sys.path.insert(0, r'.')
from gui import App

# Create the app (no mainloop)
app = App()
try:
    settings = app._save_settings()
    print(repr(settings))
except Exception as e:
    print('ERROR:', e)
finally:
    try:
        app.destroy()
    except Exception:
        pass
