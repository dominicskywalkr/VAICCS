"""Demo: record a short WAV and show Vosk recognition with and without runtime vocab.

Usage:
  python test_vocab_demo.py --check        # check model and vosk availability
  python test_vocab_demo.py --record file.wav  # record from mic to file.wav (prompt)
  python test_vocab_demo.py --run file.wav     # run recognition on file.wav (no recording)

The script expects the model directory 'vosk-model-small-en-us-0.15' to be
present next to this script (project root). It will run recognition twice on
the same WAV: once plain, once with a runtime grammar ["AcmeCorp"].
"""

import argparse
import os
import sys
import wave
import json

SAMPLE_RATE = 16000
MODEL_DIR = os.path.join(os.path.dirname(__file__), 'vosk-model-small-en-us-0.15')


def check_env():
    ok = True
    print('Checking environment...')
    if not os.path.isdir(MODEL_DIR):
        print(f"Model directory not found: {MODEL_DIR}")
        ok = False
    try:
        from vosk import Model
        print('vosk import: OK')
    except Exception as e:
        print('vosk import: FAILED:', e)
        ok = False
    return ok


def record_wav(path, secs=4, samplerate=SAMPLE_RATE):
    try:
        import sounddevice as sd
        import numpy as np
    except Exception as e:
        print('Recording requires sounddevice and numpy:', e)
        return False

    print(f'Recording {secs}s from default microphone. Please speak now (include the word "AcmeCorp").')
    try:
        rec = sd.rec(int(secs * samplerate), samplerate=samplerate, channels=1, dtype='int16')
        sd.wait()
        data = rec.reshape(-1)
        # write WAV
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(samplerate)
            wf.writeframes(data.tobytes())
        print('Saved to', path)
        return True
    except Exception as e:
        print('Recording failed:', e)
        return False


def run_recognition(wav_path):
    try:
        from vosk import Model, KaldiRecognizer
    except Exception as e:
        print('vosk not available:', e)
        return

    if not os.path.exists(wav_path):
        print('WAV not found:', wav_path)
        return

    print('Loading model...')
    model = Model(MODEL_DIR)

    # helper to run recognizer over wav bytes
    def _run_with_grammar(grammar=None):
        if grammar:
            rec = KaldiRecognizer(model, SAMPLE_RATE, json.dumps(grammar))
        else:
            rec = KaldiRecognizer(model, SAMPLE_RATE)
        rec.SetWords(True)

        with wave.open(wav_path, 'rb') as wf:
            # ensure params
            if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
                print('Warning: WAV should be 16kHz mono 16-bit. Results may vary.')
            while True:
                data = wf.readframes(4000)
                if not data:
                    break
                rec.AcceptWaveform(data)
        res = json.loads(rec.FinalResult())
        return res

    print('\nRunning recognition WITHOUT runtime vocab...')
    r1 = _run_with_grammar(None)
    print('Result JSON:', json.dumps(r1, indent=2))
    print('\nRunning recognition WITH runtime vocab ["AcmeCorp"]...')
    r2 = _run_with_grammar(["AcmeCorp"])
    print('Result JSON:', json.dumps(r2, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--record', nargs='?', const='test_acmecorp.wav')
    ap.add_argument('--run', nargs='?')
    args = ap.parse_args()

    if args.check:
        ok = check_env()
        if ok:
            print('Environment looks OK. To run demo:')
            print('  python test_vocab_demo.py --record test_acmecorp.wav')
            print('  python test_vocab_demo.py --run test_acmecorp.wav')
            sys.exit(0)
        else:
            sys.exit(2)

    if args.record:
        path = args.record
        if record_wav(path):
            print('You can now run: python test_vocab_demo.py --run', path)
        else:
            sys.exit(3)
        return

    if args.run:
        run_recognition(args.run)
        return

    ap.print_help()


if __name__ == '__main__':
    main()
