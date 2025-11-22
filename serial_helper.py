"""Serial helper for sending captions to an external encoder.

Provides a small `SerialManager` class to open/close a COM port and send
lines. Also exposes `list_serial_ports()` to enumerate available COM ports.

This module avoids opening a port at import time so importing it is safe
when pyserial is not available; callers should handle missing dependency.
"""
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
                        # value is the COM port name (e.g., 'COM5')
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

    def open(self) -> bool:
        """Open the configured serial port. Returns True on success."""
        if serial is None:
            raise RuntimeError("pyserial is not installed")
        if not self.port:
            raise ValueError("No port specified")
        try:
            self._ser = serial.Serial(self.port, self.baud, bytesize=serial.EIGHTBITS,
                                      parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                                      timeout=self.timeout)
            return True
        except Exception:
            self._ser = None
            return False

    def close(self):
        try:
            if self._ser and self._ser.is_open:
                self._ser.close()
        finally:
            self._ser = None

    def send_line(self, text: str) -> bool:
        """Send a single line (adds CRLF). Returns True on success."""
        if self._ser is None or not getattr(self._ser, 'is_open', False):
            return False
        try:
            payload = (text + "\r\n").encode("utf-8")
            self._ser.write(payload)
            return True
        except Exception:
            return False


if __name__ == '__main__':
    # quick demo when run directly
    print('Available ports:', list_serial_ports())
