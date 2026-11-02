import time
import traceback

try:
    from gui import App
    print('Imported App')
    app = App()
    print('Created App')
    print('Calling start_capture()')
    app.start_capture()
    time.sleep(2)
    print('Calling stop_capture()')
    app.stop_capture()
    print('Destroying app')
    app.destroy()
    print('Done')
except Exception as e:
    print('Exception during headless GUI test:')
    traceback.print_exc()
