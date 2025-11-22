import traceback
try:
    import gui
    app = gui.App()
    print("App created")
    app.destroy()
except Exception:
    traceback.print_exc()
