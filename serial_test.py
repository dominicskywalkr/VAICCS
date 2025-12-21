"""Simple serial test utility for VAICCS project.

Usage:
  python serial_test.py           # interactive port selection
  python serial_test.py --port COM3 --baud 9600 --text "Hello"
  python serial_test.py --port COM3 --baud 9600 --text "Hello" --pulse-dtr

This script uses the local `serial_helper.SerialManager` if available, falling
back to pyserial directly if needed.
"""
import sys
import argparse
import time

try:
    from serial_helper import list_serial_ports, SerialManager
except Exception:
    SerialManager = None
    def list_serial_ports():
        try:
            import serial.tools.list_ports as lp
            return [getattr(p, 'device', str(p)) for p in lp.comports()]
        except Exception:
            return []


def choose_port_interactive(ports):
    if not ports:
        print("No serial ports detected.")
        return None
    print("Available ports:")
    for i, p in enumerate(ports):
        if isinstance(p, dict):
            print(f"  {i}: {p.get('device')} - {p.get('description')}")
        else:
            print(f"  {i}: {p}")
    try:
        sel = input("Select index: ")
        idx = int(sel)
        chosen = ports[idx]
        if isinstance(chosen, dict):
            return chosen.get('device')
        return chosen
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', help='COM port (e.g. COM3)')
    ap.add_argument('--baud', type=int, default=9600)
    ap.add_argument('--text', default='TEST: Hello from serial_test.py')
    ap.add_argument('--pulse-dtr', action='store_true', help='Pulse DTR for 200ms before sending')
    args = ap.parse_args()

    ports = list_serial_ports()
    port = args.port
    if not port:
        port = choose_port_interactive(ports)
    if not port:
        print('No port selected; exiting.')
        sys.exit(1)

    baud = args.baud

    # Try to use SerialManager if available
    if SerialManager is not None:
        mgr = SerialManager(port, baud)
        ok = False
        try:
            ok = mgr.open()
        except Exception as e:
            print('SerialManager.open() raised:', e)
            ok = False

        if ok:
            try:
                if args.pulse_dtr:
                    try:
                        ser = getattr(mgr, '_ser', None)
                        if ser is not None:
                            ser.setDTR(True)
                            time.sleep(0.2)
                            ser.setDTR(False)
                    except Exception as e:
                        print('DTR pulse failed:', e)
                res = mgr.send_line(args.text)
                print('send_line returned', res)
            finally:
                mgr.close()
            sys.exit(0 if res else 3)

        # If SerialManager failed to open, attempt to use pyserial directly
        print('SerialManager failed to open port; attempting direct pyserial fallback...')
        try:
            import serial
        except Exception:
            print('pyserial not installed. Please install with: python -m pip install pyserial')
            sys.exit(2)
        try:
            ser = serial.Serial(port, baud, timeout=1)
        except Exception as e:
            print('Failed to open port via pyserial fallback:', e)
            sys.exit(5)
        try:
            if args.pulse_dtr:
                try:
                    ser.setDTR(True)
                    time.sleep(0.2)
                    ser.setDTR(False)
                except Exception as e:
                    print('DTR pulse failed:', e)
            payload = (args.text + '\r\n').encode('utf-8')
            n = ser.write(payload)
            print(f'wrote {n} bytes (fallback)')
            sys.exit(0 if n else 6)
        finally:
            try:
                ser.close()
            except Exception:
                pass

    # Fallback to pyserial
    try:
        import serial
    except Exception:
        print('pyserial is not installed and SerialManager not available')
        sys.exit(4)

    try:
        ser = serial.Serial(port, baud, timeout=1)
    except Exception as e:
        print('Failed to open port via pyserial:', e)
        sys.exit(5)

    try:
        if args.pulse_dtr:
            try:
                ser.setDTR(True)
                time.sleep(0.2)
                ser.setDTR(False)
            except Exception as e:
                print('DTR pulse failed:', e)
        payload = (args.text + '\r\n').encode('utf-8')
        n = ser.write(payload)
        print(f'wrote {n} bytes')
    except Exception as e:
        print('write failed:', e)
        sys.exit(6)
    finally:
        try:
            ser.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
