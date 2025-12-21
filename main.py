import os
import sounddevice as sd
import queue
import sys
import json
import datetime
import re
import threading
from typing import Callable, Optional, List
import tempfile
import wave
try:
    import numpy as np
except Exception:
    np = None
try:
    from punctuator import Punctuator
except Exception:
    Punctuator = None

# Application version. Update this when creating releases.
__version__ = "1.0b2"

# Configuration
DEFAULT_MODEL_PATH = "model"
SAMPLE_RATE = 16000


def _resource_path(relpath: str) -> str:
    """Resolve a resource file path, preferring files placed next to the exe or
    the current working directory, then the PyInstaller extraction folder, and
    finally the module directory.

    This allows distributing data files (like `bad_words.txt`) next to a
    onefile exe in `dist` and have the running app pick them up.
    """
    # 1) directory of the launched executable (works when user places files next to exe)
    try:
        exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        p = os.path.join(exe_dir, relpath)
        if os.path.exists(p):
            return p
    except Exception:
        pass

    # 2) current working directory
    try:
        p = os.path.join(os.getcwd(), relpath)
        if os.path.exists(p):
            return p
    except Exception:
        pass

    # 3) PyInstaller temp extraction folder
    try:
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            p = os.path.join(meipass, relpath)
            if os.path.exists(p):
                return p
    except Exception:
        pass

    # 4) module directory (fallback)
    try:
        p = os.path.join(os.path.dirname(__file__), relpath)
        return p
    except Exception:
        return relpath

# shared globals
# Start with an empty set and do NOT auto-load a bundled `bad_words.txt`.
# Loading must be explicit (e.g., via the GUI's Load Restricted Words File).
BAD_WORDS = set()
# Bleep/replacement settings. GUI will update this at runtime.
# mode: one of 'fixed', 'keep_first', 'keep_last', 'keep_first_last', 'remove', 'custom'
# mask_char: single-character string used to mask letters when using keep_* modes
# custom_text: used when mode == 'fixed' or mode == 'custom'
BLEEP_SETTINGS = {
    "mode": "fixed",
    "mask_char": "*",
    "custom_text": "****",
}
q = queue.Queue()

# Load bad words and helper to bleep them
def load_bad_words(path="bad_words.txt"):
    """Load bad words from a file, one per line. Ignores blank lines and lines starting with #."""
    try:
        # resolve path (so packaged exe can load a file placed next to the exe,
        # current working directory, PyInstaller _MEIPASS, or module dir)
        p = path if os.path.isabs(path) else _resource_path(path)
        with open(p, encoding="utf-8") as f:
            words = {line.strip().lower() for line in f if line.strip() and not line.strip().startswith("#")}
            return words
    except Exception:
        return set()


def _ensure_bad_words():
    global BAD_WORDS
    # Preserve existing behavior but do not auto-load from disk. If the
    # set was accidentally left as None, ensure it's at least an empty set.
    if BAD_WORDS is None:
        BAD_WORDS = set()
# Do not automatically call `load_bad_words()` at import time. The GUI
# provides an explicit action for users to load a restricted-words file.

_WORD_RE = re.compile(r"\b\w+(?:[-']\w+)*\b", re.UNICODE)

def bleep_text(text, bad_set=None):
    """Replace whole-word occurrences (case-insensitive) of bad words with 'bleep'.

    The `bad_set` parameter, if provided, is used. If omitted or None,
    the function will use the current global `BAD_WORDS` set. This avoids
    binding the bad-words set at function-definition time so callers can
    change `BAD_WORDS` at runtime (e.g., via the GUI's load/unload).

    Preserves surrounding punctuation and spacing. Hyphenated sequences like
    "mother-in-law" are treated as a single token and will be matched
    against entries in `bad_words.txt` (so include the hyphenated form if
    you want to block the whole phrase).
    """
    # Resolve the effective bad-words set at call time
    if bad_set is None:
        bad_set = BAD_WORDS

    if not bad_set or not text:
        return text

    # Helper to build replacement based on settings
    def _mask_token(token: str, mode: str, mask_char: str, custom_text: str) -> str:
        if mode in ("fixed", "custom"):
            return custom_text
        if mode == "remove":
            return ""

        # For keep_first / keep_last / keep_first_last: preserve non-alnum chars
        chars = list(token)
        # indices of maskable characters (alphanumeric)
        maskable = [i for i, c in enumerate(chars) if c.isalnum()]
        if not maskable:
            return token

        def mask_indices(show_indices):
            out = []
            for i, c in enumerate(chars):
                if not c.isalnum():
                    out.append(c)
                elif i in show_indices:
                    out.append(c)
                else:
                    out.append(mask_char)
            return ''.join(out)

        if mode == "keep_first":
            show = {maskable[0]}
            return mask_indices(show)
        if mode == "keep_last":
            show = {maskable[-1]}
            return mask_indices(show)
        if mode == "keep_first_last":
            if len(maskable) == 1:
                show = {maskable[0]}
            else:
                show = {maskable[0], maskable[-1]}
            return mask_indices(show)

        # fallback: fixed
        return custom_text

    def _repl(m):
        w = m.group(0)
        if w.lower() not in bad_set:
            return w
        settings = globals().get('BLEEP_SETTINGS', None) or {}
        mode = settings.get('mode', 'fixed')
        mask_char = settings.get('mask_char', '*') or '*'
        custom_text = settings.get('custom_text', '****') or '****'
        try:
            # ensure mask_char is single char
            if not isinstance(mask_char, str) or mask_char == '':
                mask_char = '*'
            else:
                mask_char = mask_char[0]
        except Exception:
            mask_char = '*'

        try:
            return _mask_token(w, mode, mask_char, custom_text)
        except Exception:
            # on any failure, fall back to simple fixed replacement
            return custom_text

    return _WORD_RE.sub(_repl, text)

def callback(indata, frames, time, status):
    """Stream callback handles both numpy array input (InputStream) and raw bytes (RawInputStream).
    Downmix to mono when numpy is available; otherwise pass raw bytes through.
    """
    if status:
        print(status, file=sys.stderr)

    # If numpy is available and indata is an ndarray, downmix to mono and queue bytes
    if np is not None and isinstance(indata, np.ndarray):
        try:
            if indata.ndim > 1 and indata.shape[1] > 1:
                mono = indata.mean(axis=1).astype('int16')
            else:
                mono = indata.reshape(-1).astype('int16')
            q.put(mono.tobytes())
            return
        except Exception:
            pass

    # Fallback for RawInputStream or unexpected types: push raw bytes
    try:
        q.put(bytes(indata))
    except Exception:
        # Last-resort: ignore this chunk
        return


# Recase subprocess integration removed. Previous session added a long-lived
# subprocess wrapper here to run a third-party recase/punctuator. That code
# has been intentionally removed to avoid relying on vendor scripts. If you
# want to attach an external punctuation/casing service, implement a separate
# adapter module and attach it to the engine at runtime.

def format_timestamp(seconds):
    # Format seconds (float) into SRT timestamp: HH:MM:SS,mmm
    total_seconds = int(seconds)
    ms = int((seconds - total_seconds) * 1000)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

def format_confidence(words):
    if not words:
        return 0.0
    avg_conf = sum(w.get("conf", 0.0) for w in words) / len(words)
    return round(avg_conf * 100, 1)


class CaptionEngine:
    """Caption engine that can be started/stopped and calls a callback with new caption text.

    callback signature: fn(text: str)
    """

    def __init__(self, model_path: str = DEFAULT_MODEL_PATH, demo: bool = False, source: str = "mic", cpu_threads: Optional[int] = None, voice_profiles_dir: Optional[str] = "voice_profiles", profile_match_threshold: float = 0.7, enable_profile_matching: bool = True, punctuator: Optional[str] = None):
        self.model_path = model_path
        self.demo = demo
        self.source = source
        self.cpu_threads = cpu_threads
        # voice profile matching
        self.enable_profile_matching = bool(enable_profile_matching)
        self.profile_match_threshold = float(profile_match_threshold)
        self._vpm = None
        if self.enable_profile_matching:
            try:
                from voice_profiles import VoiceProfileManager
                self._vpm = VoiceProfileManager(profiles_dir=voice_profiles_dir)
            except Exception:
                # profile manager not available or failed to load; disable matching
                self._vpm = None
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._callback: Optional[Callable[[str], None]] = None
        self._recognizer = None
        self._model = None
        self._using_gpu = False
        # lock to protect recognizer replacement at runtime
        self._rec_lock = threading.Lock()
        # optional runtime vocabulary (list of words) used to bias decoding
        self._current_vocab = None
        # buffer for raw audio bytes corresponding to the current utterance
        self._chunk_buffer = bytearray()
        # punctuator: optional path or model spec (e.g., 'hf:your-model-id')
        try:
            if Punctuator is not None:
                self._punctuator = Punctuator.from_path(punctuator)
            else:
                self._punctuator = None
        except Exception:
            self._punctuator = None

    def _init_recognizer(self):
        # Determine whether to use recognizer
        # If cpu_threads specified, set environment variables before importing Vosk/Kaldi
        if self.cpu_threads:
            try:
                n = int(self.cpu_threads)
                if n > 0:
                    os.environ.setdefault("OMP_NUM_THREADS", str(n))
                    os.environ.setdefault("MKL_NUM_THREADS", str(n))
                    os.environ.setdefault("OPENBLAS_NUM_THREADS", str(n))
            except Exception:
                pass

        if self.demo:
            self._model = None
            self._recognizer = None
            return
        # Delay import of vosk until after we set thread env vars
        try:
            from vosk import Model, KaldiRecognizer
        except Exception as e:
            # Attempt to record the full traceback so frozen executables can surface
            # the underlying import error (missing DLLs, incompatible wheels, etc.).
            try:
                import traceback
                tb = traceback.format_exc()
            except Exception:
                tb = str(e)
            # Try writing the traceback to several accessible locations so
            # users running a frozen exe can find the cause more easily.
            tried_paths = []
            try:
                # 1) directory of the launched executable (works for exe builds)
                exe_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
                p1 = os.path.join(exe_dir, "vosk_import_error.log")
                with open(p1, "w", encoding="utf-8") as lf:
                    lf.write(tb)
                tried_paths.append(p1)
            except Exception:
                pass
            try:
                # 2) current working directory
                p2 = os.path.join(os.getcwd(), "vosk_import_error.log")
                if p2 not in tried_paths:
                    with open(p2, "w", encoding="utf-8") as lf:
                        lf.write(tb)
                    tried_paths.append(p2)
            except Exception:
                pass
            try:
                # 3) fallback: next to this module (may be inside bundle; best-effort)
                here = os.path.dirname(__file__)
                p3 = os.path.join(here, "vosk_import_error.log")
                if p3 not in tried_paths:
                    with open(p3, "w", encoding="utf-8") as lf:
                        lf.write(tb)
                    tried_paths.append(p3)
            except Exception:
                pass
            # Also emit to stderr so console users see it
            try:
                sys.stderr.write("VOSK import failed; traceback written to: " + ",".join(tried_paths) + "\n")
                sys.stderr.write(tb + "\n")
            except Exception:
                pass
            Model = None
            KaldiRecognizer = None

        if Model is None or KaldiRecognizer is None:
            # Vosk not available; fall back to demo
            self._recognizer = None
            self._model = None
            self.demo = True
            return

        if not os.path.exists(self.model_path):
            self._recognizer = None
            self._model = None
            self.demo = True
            return

        try:
            # Support passing either a model directory or an archive file (zip/tar).
            model_dir = self.model_path
            # If the path is a file and looks like an archive, extract to a temp dir.
            if os.path.isfile(model_dir):
                lower = model_dir.lower()
                archive_exts = ('.zip', '.tar.gz', '.tgz', '.tar', '.tar.bz2', '.tar.xz')
                if any(lower.endswith(ext) for ext in archive_exts):
                    try:
                        import tempfile, zipfile, tarfile
                        tmpd = tempfile.mkdtemp(prefix='vosk_model_')
                        if lower.endswith('.zip'):
                            with zipfile.ZipFile(model_dir, 'r') as zf:
                                zf.extractall(tmpd)
                        else:
                            with tarfile.open(model_dir, 'r:*') as tfh:
                                tfh.extractall(tmpd)
                        # try to pick a sensible subfolder as the model dir
                        for nm in os.listdir(tmpd):
                            p = os.path.join(tmpd, nm)
                            if os.path.isdir(p):
                                model_dir = p
                                break
                        # remember to clean up when engine stops
                        self._extracted_model_tmpdir = tmpd
                    except Exception:
                        # extraction failed; fall back to original path and continue
                        model_dir = self.model_path

            self._model = Model(model_dir)
            # If a runtime vocabulary was configured, pass it as grammar to KaldiRecognizer
            try:
                if self._current_vocab:
                    import json as _json
                    grammar = _json.dumps(self._current_vocab)
                    self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE, grammar)
                else:
                    self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE)
            except Exception:
                # fallback to simple recognizer creation
                self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE)
            try:
                self._recognizer.SetWords(True)
            except Exception:
                pass
        except Exception:
            self._recognizer = None
            self._model = None
            self.demo = True

    def update_vocab(self, words: List[str]):
        """Update runtime vocabulary (list of words) used to bias recognition.

        This recreates the KaldiRecognizer with the supplied grammar in a
        thread-safe manner. If called before recognizer/model is initialized,
        the vocabulary will be used when the recognizer is later created.
        """
        try:
            import json as _json
        except Exception:
            _json = None
        # normalize words to simple strings
        if not words:
            self._current_vocab = None
        else:
            self._current_vocab = [str(w) for w in words]

        # If recognizer is active, recreate it with the grammar under lock.
        with self._rec_lock:
            try:
                if getattr(self, '_model', None) is None:
                    return
                # import KaldiRecognizer locally to avoid top-level dependency
                try:
                    from vosk import KaldiRecognizer
                except Exception:
                    KaldiRecognizer = None

                if self._current_vocab and _json is not None and KaldiRecognizer is not None:
                    grammar = _json.dumps(self._current_vocab)
                    try:
                        self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE, grammar)
                    except Exception:
                        # fallback
                        self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE)
                elif KaldiRecognizer is not None:
                    self._recognizer = KaldiRecognizer(self._model, SAMPLE_RATE)
                try:
                    if self._recognizer is not None:
                        self._recognizer.SetWords(True)
                except Exception:
                    pass
            except Exception:
                # leave recognizer as-is on failure
                pass

    def get_current_vocab(self) -> List[str]:
        return list(self._current_vocab) if self._current_vocab else []

    def start(self, callback: Callable[[str], None]):
        if self._thread and self._thread.is_alive():
            return
        _ensure_bad_words()
        self._callback = callback
        self._stop_event.clear()
        self._init_recognizer()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        # Clean up any temporary extracted model directory created when a
        # model archive was supplied.
        try:
            tmp = getattr(self, '_extracted_model_tmpdir', None)
            if tmp and os.path.isdir(tmp):
                try:
                    import shutil
                    shutil.rmtree(tmp)
                except Exception:
                    pass
        except Exception:
            pass

    def _run_loop(self):
        # Safely drain any pending items from the queue without touching internals
        try:
            while True:
                q.get_nowait()
        except Exception:
            # queue.Empty or other minor issues; safe to continue
            pass
        # build stream kwargs
        stream_kwargs = dict(samplerate=SAMPLE_RATE, blocksize=8000, dtype='int16', channels=1, callback=callback)
        use_raw = False
        if np is None:
            use_raw = True
        if self.source == 'system' and hasattr(sd, 'WasapiSettings'):
            try:
                wasapi = sd.WasapiSettings(loopback=True)
                stream_kwargs['extra_settings'] = wasapi
                stream_kwargs['channels'] = 2
            except Exception:
                pass

        try:
            if use_raw:
                stream = sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=8000, dtype='int16', channels=stream_kwargs.get('channels', 1), callback=callback, **({'extra_settings': stream_kwargs['extra_settings']} if 'extra_settings' in stream_kwargs else {}))
            else:
                stream = sd.InputStream(**stream_kwargs)

            with stream:
                start_time = datetime.datetime.now()
                caption_index = 1
                while not self._stop_event.is_set():
                    try:
                        data = q.get(timeout=0.5)
                    except Exception:
                        continue
                    # snapshot recognizer under lock to avoid races while it's replaced
                    with self._rec_lock:
                        local_rec = self._recognizer

                    if local_rec is not None:
                        try:
                            # append chunk to the current utterance buffer (int16 bytes)
                            try:
                                self._chunk_buffer.extend(data)
                            except Exception:
                                # if buffer extend fails, reset buffer
                                self._chunk_buffer = bytearray(data)

                            # keep buffer bounded (e.g., max 30s)
                            try:
                                max_bytes = SAMPLE_RATE * 2 * 30
                                if len(self._chunk_buffer) > max_bytes:
                                    self._chunk_buffer = self._chunk_buffer[-max_bytes:]
                            except Exception:
                                pass

                            if local_rec.AcceptWaveform(data):
                                result = json.loads(local_rec.Result())
                                words = result.get("result", [])
                                text = result.get("text", "")
                                if words and text.strip():
                                    bleeped = bleep_text(text)

                                    speaker = None
                                    # try to match speaker using buffered audio if profile manager is available
                                    if self._vpm is not None:
                                        tmpf = None
                                        try:
                                            tmpf = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                                            tmpf.close()
                                            with wave.open(tmpf.name, 'wb') as wf:
                                                wf.setnchannels(1)
                                                wf.setsampwidth(2)
                                                wf.setframerate(SAMPLE_RATE)
                                                wf.writeframes(bytes(self._chunk_buffer))
                                            try:
                                                res = self._vpm.match_profile(tmpf.name, top_k=1)
                                                if res:
                                                    name, score = res[0]
                                                    try:
                                                        score = float(score)
                                                    except Exception:
                                                        score = 0.0
                                                    if score >= float(self.profile_match_threshold):
                                                        speaker = name
                                            except Exception:
                                                # ignore matching errors
                                                speaker = None
                                        except Exception:
                                            speaker = None
                                        finally:
                                            try:
                                                if tmpf is not None:
                                                    os.unlink(tmpf.name)
                                            except Exception:
                                                pass

                                    # Post-process ASR text with our punctuator (if available).
                                    try:
                                        if getattr(self, '_punctuator', None) is not None:
                                            final_text = self._punctuator.punctuate(bleeped)
                                        else:
                                            final_text = bleeped
                                    except Exception:
                                        final_text = bleeped

                                    if speaker:
                                        out = f"[{speaker}] {final_text}"
                                    else:
                                        out = final_text

                                    # reset buffer for next utterance
                                    self._chunk_buffer = bytearray()

                                    if self._callback:
                                        self._callback(out)
                                    caption_index += 1
                        except Exception:
                            continue
                    else:
                        now = datetime.datetime.now()
                        elapsed = (now - start_time).total_seconds()
                        out = f"[DEMO] audio captured @ {format_timestamp(elapsed)}"
                        if self._callback:
                            self._callback(out)
                        caption_index += 1
        except Exception as e:
            # stream could not be opened; call callback with an error message
            if self._callback:
                self._callback(f"[ERROR] Could not open audio device: {e}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Live captions using Vosk (or demo mode)")
    parser.add_argument("--model", "-m", default=DEFAULT_MODEL_PATH, help="Path to the Vosk model directory")
    parser.add_argument("--demo", action="store_true", help="Run in demo mode without a Vosk model")
    parser.add_argument("--source", "-s", choices=("mic", "system"), default="mic",
                        help="Audio source: 'mic' for default microphone, 'system' for internal computer sound (loopback, Windows WASAPI)")
    args = parser.parse_args()

    engine = CaptionEngine(model_path=args.model, demo=args.demo, source=args.source)

    try:
        print("🎙️ Streaming captions... Press Ctrl+C to stop.")

        def print_cb(text: str):
            print(text)

        engine.start(print_cb)
        # wait until interrupted
        while True:
            try:
                engine._stop_event.wait(1.0)
            except KeyboardInterrupt:
                break
    except KeyboardInterrupt:
        pass
    finally:
        engine.stop()
