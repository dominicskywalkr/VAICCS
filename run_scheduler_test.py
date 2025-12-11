"""Scheduler test: 1-minute show with optional demo engine messages.

This script runs a fast, simulated scheduler loop that advances a test
clock one minute per iteration. Use `--demo-engine` to start the
CaptionEngine in demo mode and observe `[DEMO]` messages in the log.
"""

import argparse
import logging
import threading
import time
from datetime import datetime, timedelta

from automations import AutomationManager, ShowAutomation


LOG_PATH = 'scheduler_test.log'


def setup_logging():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(LOG_PATH, mode='w', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


class TestAutomationManager(AutomationManager):
    def __init__(self):
        super().__init__()
        self._test_now = datetime.now().replace(second=0, microsecond=0)
        self._lock = threading.Lock()

    def _get_current_time_minutes(self) -> int:
        with self._lock:
            return self._test_now.hour * 60 + self._test_now.minute

    def _get_current_day_name(self) -> str:
        with self._lock:
            day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
            return day_names[self._test_now.weekday()]

    def advance_minutes(self, minutes: int = 1):
        with self._lock:
            self._test_now = self._test_now + timedelta(minutes=minutes)

    def start_scheduler(self):
        if self._scheduler_running:
            return
        self._scheduler_running = True
        self._scheduler_thread = threading.Thread(target=self._test_scheduler_loop, daemon=True)
        self._scheduler_thread.start()

    def _test_scheduler_loop(self):
        logging.info("Test scheduler loop starting")
        try:
            while self._scheduler_running:
                try:
                    for automation in list(self.automations):
                        should_trigger, is_start = self._check_automation_trigger(automation)
                        if should_trigger:
                            if is_start and self._active_automation != automation:
                                logging.info(f"Trigger START for automation: {automation.name}")
                                self._active_automation = automation
                                if self._on_start_callback:
                                    try:
                                        self._on_start_callback()
                                    except Exception:
                                        logging.exception("Error in automation start callback")
                        elif not should_trigger and self._active_automation == automation:
                            self._active_automation = None
                            if self._on_stop_callback:
                                try:
                                    self._on_stop_callback()
                                except Exception:
                                    logging.exception("Error in automation stop callback")

                    if self._active_automation:
                        should_trigger, is_start = self._check_automation_trigger(self._active_automation)
                        if not should_trigger and not is_start:
                            logging.info(f"Trigger STOP for automation: {self._active_automation.name}")
                            self._active_automation = None
                            if self._on_stop_callback:
                                try:
                                    self._on_stop_callback()
                                except Exception:
                                    logging.exception("Error in automation stop callback")

                    self.advance_minutes(1)
                    time.sleep(0.5)
                except Exception:
                    logging.exception("Error inside test scheduler loop")
                    self._scheduler_running = False
        finally:
            logging.info("Test scheduler loop exiting")


def fmt_time(dt: datetime) -> str:
    return dt.strftime('%I:%M %p').lstrip('0')


def main(demo_engine: bool = False):
    setup_logging()
    logging.info("Starting scheduler backend test")

    events = []

    def on_start_default():
        logging.info(f"on_start called at {datetime.now().isoformat()}")
        events.append(('start', datetime.now()))

    def on_stop_default():
        logging.info(f"on_stop called at {datetime.now().isoformat()}")
        events.append(('stop', datetime.now()))

    mgr = TestAutomationManager()
    now = mgr._test_now
    start_dt = now + timedelta(minutes=1)
    end_dt = start_dt + timedelta(minutes=1)
    automation = ShowAutomation(
        name='Test Show',
        days=[mgr._get_current_day_name()],
        start_time=fmt_time(start_dt),
        end_time=fmt_time(end_dt)
    )

    mgr.add_automation(automation)
    logging.info(f"Added automation: {automation.name} start={automation.start_time} end={automation.end_time} day={automation.days}")

    engine = None

    if demo_engine:
        try:
            from main import CaptionEngine, q

            engine = CaptionEngine(demo=True)

            def engine_cb(text: str):
                logging.info(f"engine callback: {text}")

            def _producer(timeout_seconds: int):
                end = time.time() + timeout_seconds
                dummy = b"\x00" * 3200
                while time.time() < end and not getattr(engine, '_stop_event', threading.Event()).is_set():
                    try:
                        q.put(dummy)
                    except Exception:
                        pass
                    time.sleep(0.2)

            def on_start():
                on_start_default()
                try:
                    engine.start(engine_cb)
                except Exception:
                    logging.exception("Failed to start demo engine on automation start")

            def on_stop():
                on_stop_default()
                try:
                    engine.stop()
                    # wait briefly for the engine thread to exit
                    try:
                        t0 = time.time()
                        while getattr(engine, '_thread', None) and engine._thread.is_alive() and (time.time() - t0) < 5.0:
                            time.sleep(0.1)
                        if getattr(engine, '_thread', None) and engine._thread.is_alive():
                            logging.warning("Engine thread did not exit within timeout after stop()")
                        else:
                            logging.info("Engine stopped successfully")
                    except Exception:
                        pass
                except Exception:
                    logging.exception("Failed to stop demo engine on automation stop")

            timeout = 20
            prod = threading.Thread(target=_producer, args=(timeout,), daemon=True)
            prod.start()
        except Exception:
            logging.exception("Failed to setup demo engine; falling back to event-only test")
            on_start = on_start_default
            on_stop = on_stop_default
    else:
        on_start = on_start_default
        on_stop = on_stop_default

    mgr.set_callbacks(on_start=on_start, on_stop=on_stop)
    mgr.start_scheduler()

    timeout = 20
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            if any(e[0] == 'start' for e in events) and any(e[0] == 'stop' for e in events):
                break
            time.sleep(0.2)
    finally:
        try:
            mgr.stop_scheduler()
        except Exception:
            pass
        if engine is not None:
            try:
                engine.stop()
                # ensure thread is stopped before exiting
                try:
                    t0 = time.time()
                    while getattr(engine, '_thread', None) and engine._thread.is_alive() and (time.time() - t0) < 5.0:
                        time.sleep(0.1)
                except Exception:
                    pass
            except Exception:
                pass

    logging.info("Test completed — event summary:")
    for ev, ts in events:
        logging.info(f"  {ev} at {ts.isoformat()}")

    if not events:
        logging.error("No events recorded — scheduler did not trigger start/stop as expected")
    elif not any(e[0] == 'start' for e in events):
        logging.error("Start event not recorded")
    elif not any(e[0] == 'stop' for e in events):
        logging.error("Stop event not recorded")
    else:
        logging.info("Both start and stop events observed — scheduler logic appears functional")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Run scheduler tests")
    parser.add_argument('--demo-engine', action='store_true', help='Run demo CaptionEngine during scheduler test')
    args = parser.parse_args()

    main(demo_engine=args.demo_engine)
