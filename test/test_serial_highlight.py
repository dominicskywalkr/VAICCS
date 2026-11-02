import time
import sys
import threading
import traceback

# Ensure we can import the app
import os
import sys
# ensure project root is on sys.path so `gui` can be imported when running test directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from gui import App


class DummySerial:
    def __init__(self):
        self.sent = []

    def send_line(self, text: str) -> bool:
        # simulate a small write delay
        self.sent.append(text)
        return True


def run_test(sample_text: str, timeout: float = 5.0) -> int:
    app = None
    try:
        app = App(simulate_automation=False)
        # ensure window is not destroyed
        app.update_idletasks()

        # inject dummy serial manager and enable serial
        d = DummySerial()
        app.serial_manager = d
        app.serial_enabled_var.set(True)
        # force direct highlights (test mode)
        app._force_direct_highlight = True
        # set short delay
        try:
            app.serial_word_delay_ms.set(50)
        except Exception:
            app.serial_word_delay_ms = app.serial_word_delay_ms if hasattr(app, 'serial_word_delay_ms') else None
            try:
                if app.serial_word_delay_ms is not None:
                    app.serial_word_delay_ms.set(50)
            except Exception:
                pass

        # call caption handler
        app._on_caption(sample_text)

        start = time.time()
        highlight_seen = False

        # loop until thread finishes or timeout
        while time.time() - start < timeout:
            try:
                app.update()
            except Exception:
                # sometimes update raises if window closed; ignore
                pass

                # check tag ranges or recorded highlight log
                try:
                    ranges = app.transcript.tag_ranges('serial_send')
                    if ranges and len(ranges) > 0:
                        highlight_seen = True
                except Exception:
                    pass
                try:
                    if getattr(app, '_highlight_log', None) and len(app._highlight_log) > 0:
                        highlight_seen = True
                except Exception:
                    pass

            th = getattr(app, '_serial_send_thread', None)
            if th is None or not th.is_alive():
                break
            time.sleep(0.01)

        # final check: ensure words were sent and highlight seen
        printed = False
        if not d.sent:
            print('ERROR: No words were sent over serial.\n')
            printed = True
        if not highlight_seen:
            # as a fallback, check recorded highlight intents from worker
            try:
                if getattr(app, '_highlight_log', None) and len(app._highlight_log) > 0:
                    highlight_seen = True
            except Exception:
                pass
        if not highlight_seen:
            print('ERROR: No highlights were observed in the transcript.\n')
            printed = True

        if printed:
            print('Sent words:', d.sent)
            # dump transcript contents and tag ranges
            try:
                content = app.transcript.get('1.0', 'end')
                print('Transcript content:\n', content)
                print('Final tag ranges:', app.transcript.tag_ranges('serial_send'))
                print('Highlight log (worker intents):', getattr(app, '_highlight_log', None))
            except Exception:
                pass
            return 2

        print('OK: Highlight observed and words sent. Sent words:', d.sent)
        return 0

    except Exception:
        traceback.print_exc()
        return 3
    finally:
        try:
            if app:
                app.destroy()
        except Exception:
            pass


if __name__ == '__main__':
    sample = 'Hello world this is a test of highlighting'
    code = run_test(sample)
    sys.exit(code)
