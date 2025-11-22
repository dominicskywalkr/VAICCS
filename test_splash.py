# test_splash.py
from tkinter import Tk
from gui_splash import Splash

root = Tk()
try:
    s = Splash(root, title_text="Test Splash", creator="You")
    root.withdraw()
    root.after(1500, lambda: s.update_status("Initializing..."))
    root.after(3500, lambda: s.close())
    root.after(3600, lambda: root.destroy())
    root.mainloop()
finally:
    try:
        root.destroy()
    except Exception:
        pass