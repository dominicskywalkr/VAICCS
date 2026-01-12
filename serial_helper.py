"""Serial helper for sending captions to an external encoder.

Provides a small `SerialManager` class to open/close a serial port and send
lines. Also exposes `list_serial_ports()` to enumerate available serial ports
on the host (e.g. COMx on Windows or /dev/tty.* on macOS/Linux).

This module avoids opening a port at import time so importing it is safe
when pyserial is not available; callers should handle missing dependency.
"""
import sys
import time
from typing import List, Optional

try:
    import serial
    import serial.tools.list_ports as list_ports
except Exception:
    serial = None
    list_ports = None

# On Windows we can also query the registry for SerialCOMM mappings which
# sometimes list USB<->COM mappings that help detect USB-to-RS232 adapters
_have_winreg = False
try:
    import winreg
    _have_winreg = True
except Exception:
    _have_winreg = False


def list_serial_ports() -> List[str]:
    """Return a list of available serial ports as dictionaries.

    Each item is a dict with keys: 'device', 'description', 'hwid', 'vid', 'pid', 'manufacturer'.
    This provides extra context for USB-to-RS232 adapters (shows VID/PID and description).

    If pyserial is not installed, returns an empty list.
    """
    results = []

    # first try pyserial if available
    if list_ports is not None:
        try:
            for p in list_ports.comports():
                info = {
                    "device": getattr(p, "device", ""),
                    "description": getattr(p, "description", ""),
                    "hwid": getattr(p, "hwid", ""),
                    "vid": getattr(p, "vid", None),
                    "pid": getattr(p, "pid", None),
                    "manufacturer": getattr(p, "manufacturer", ""),
                }
                results.append(info)
        except Exception:
            # ignore pyserial enumeration errors
            pass

    # On Windows, augment with registry entries from HARDWARE\DEVICEMAP\SERIALCOMM
    if _have_winreg:
        try:
            key_path = r"HARDWARE\DEVICEMAP\SERIALCOMM"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(k, i)
                        # value is the COM port name (e.g., 'COM5' on Windows)
                        dev = str(value)
                        # create an entry only if device not already present
                        if not any(r.get("device") == dev for r in results):
                            results.append({
                                "device": dev,
                                "description": f"Registry:{name}",
                                "hwid": name,
                                "vid": None,
                                "pid": None,
                                "manufacturer": "",
                            })
                        i += 1
                    except OSError:
                        break
        except Exception:
            # ignore registry read errors
            pass

    return results


class SerialManager:
    """Manage a serial connection for caption output.

    Usage:
      mgr = SerialManager(port='COM3', baud=9600)
      mgr.open()
      mgr.send_line('hello')
      mgr.close()
    """

    def __init__(self, port: Optional[str] = None, baud: int = 9600, timeout: float = 1.0):
        self.port = port
        self.baud = int(baud)
        self.timeout = float(timeout)
        self._ser = None
        # human-readable error from last operation
        self.last_error: Optional[str] = None

    def open(self) -> bool:
        """Open the configured serial port. Returns True on success."""
        if serial is None:
            self.last_error = "pyserial is not installed"
            raise RuntimeError("pyserial is not installed")
        if not self.port:
            self.last_error = "No port specified"
            raise ValueError("No port specified")
        try:
            self._ser = serial.Serial(self.port, self.baud, bytesize=serial.EIGHTBITS,
                                      parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                      timeout=self.timeout)
            # ensure port is actually open
            if getattr(self._ser, 'is_open', False):
                self.last_error = None
                return True
            else:
                self.last_error = 'failed to open port'
                try:
                    self._ser.close()
                except Exception:
                    pass
                self._ser = None
                return False
        except Exception as e:
            # capture message for callers
            self.last_error = str(e)
            self._ser = None
            return False

    def close(self):
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        finally:
            self._ser = None
            self.last_error = None

    def send_line(self, text: str) -> bool:
        """Send a single line (adds CRLF). Returns True on success."""
        if self._ser is None or not getattr(self._ser, 'is_open', False):
            self.last_error = 'port not open'
            return False
        try:
            payload = (text + "\r\n").encode("utf-8")
            self._ser.write(payload)
            # attempt to flush if supported
            try:
                if hasattr(self._ser, 'flush'):
                    self._ser.flush()
            except Exception:
                pass
            self.last_error = None
            return True
        except Exception:
            self.last_error = str(sys.exc_info()[1]) if 'sys' in globals() else 'write error'
            return False

    def pulse_dtr(self, duration: float = 0.2) -> bool:
        """Pulse DTR line high for `duration` seconds if supported."""
        if self._ser is None or not getattr(self._ser, 'is_open', False):
            self.last_error = 'port not open'
            return False
        try:
            self._ser.setDTR(True)
            time.sleep(duration)
            self._ser.setDTR(False)
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = str(e)
            return False

    def pulse_rts(self, duration: float = 0.2) -> bool:
        """Pulse RTS line high for `duration` seconds if supported."""
        if self._ser is None or not getattr(self._ser, 'is_open', False):
            self.last_error = 'port not open'
            return False
        try:
            self._ser.setRTS(True)
            time.sleep(duration)
            self._ser.setRTS(False)
            self.last_error = None
            return True
        except Exception as e:
            self.last_error = str(e)
            return False


if __name__ == '__main__':
    # quick demo when run directly
    print('Available ports:', list_serial_ports())
