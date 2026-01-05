import sys
import os
import argparse
import time

# ensure project root on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from gui import App


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--port', required=True, help='COM port to connect (e.g. COM3)')
    p.add_argument('--baud', type=int, default=9600)
    p.add_argument('--text', default='Hello world this is a live test')
    args = p.parse_args()

    app = App()

    def do_connect_and_send():
        try:
            # set combobox value if present in list
            try:
                app.serial_port_var.set(args.port)
            except Exception:
                pass
            try:
                app.baud_var.set(args.baud)
            except Exception:
                pass
            # attempt connect
            try:
                app.serial_enabled_var.set(True)
                app._toggle_serial_connect()
            except Exception as e:
                print('Connect error:', e)
            # wait briefly then send caption
            try:
                app._on_caption(args.text)
            except Exception as e:
                print('Send caption error:', e)
        except Exception as e:
            print('Live test error:', e)

    # schedule after startup
    try:
        app.after(1000, do_connect_and_send)
    except Exception:
        try:
            do_connect_and_send()
        except Exception:
            pass

    print('Starting GUI. Watch the transcript and your serial monitor for output.')
    app.mainloop()

if __name__ == '__main__':
    main()
