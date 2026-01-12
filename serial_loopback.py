"""Loopback/test utility to verify serial TX and optional read-back.

Usage:
    python serial_loopback.py --port <PORT> --baud 9600 --payload "Hello" --pulse-dtr --read

Examples:
    macOS/Linux: /dev/tty.usbserial or /dev/cu.usbserial
    Windows: COM3

Options:
    --pulse-dtr   Pulse DTR for 200ms before sending (some devices need it)
    --pulse-rts   Pulse RTS for 200ms before sending
    --read        Attempt to read response after writing (useful for loopback)
"""
import argparse
import time

try:
    import serial
except Exception as e:
    print('pyserial not available:', e)
    raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', required=True)
    ap.add_argument('--baud', type=int, default=9600)
    ap.add_argument('--payload', default='TEST')
    ap.add_argument('--pulse-dtr', action='store_true')
    ap.add_argument('--pulse-rts', action='store_true')
    ap.add_argument('--read', action='store_true')
    args = ap.parse_args()

    print(f"Opening {args.port}@{args.baud}...")
    try:
        ser = serial.Serial(args.port, args.baud, timeout=1)
    except Exception as e:
        print('Failed to open port:', e)
        return

    try:
        print('Port open:', ser.is_open)
        if args.pulse_dtr:
            try:
                ser.setDTR(True)
                time.sleep(0.2)
                ser.setDTR(False)
                print('Pulsed DTR')
            except Exception as e:
                print('DTR pulse failed:', e)
        if args.pulse_rts:
            try:
                ser.setRTS(True)
                time.sleep(0.2)
                ser.setRTS(False)
                print('Pulsed RTS')
            except Exception as e:
                print('RTS pulse failed:', e)

        payload = (args.payload + "\r\n").encode('utf-8')
        print('Writing:', payload)
        try:
            n = ser.write(payload)
            print(f'Wrote {n} bytes')
        except Exception as e:
            print('Write failed:', e)

        # Give device time to transmit/loopback
        time.sleep(0.2)

        if args.read:
            try:
                data = ser.read(1024)
                print('Read:', data, 'len=', len(data))
                if data:
                    print('Read repr:', repr(data))
                else:
                    print('No data read (loopback may not be connected)')
            except Exception as e:
                print('Read failed:', e)

    finally:
        try:
            ser.close()
        except Exception:
            pass

if __name__ == '__main__':
    main()
