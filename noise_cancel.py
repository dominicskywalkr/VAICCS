"""Noise cancellation helper module.

Provides a HanceProcessor wrapper (best-effort) and functions to install
an audio callback wrapper that filters incoming audio in realtime before
forwarding to the application's queue used by Vosk (`main.q`).

This module ships a lightweight fallback processor when a real Hance
SDK isn't available: a simple RMS-based noise gate that reduces low-level
background noise. If the user has a Hance python package or SDK, the
processor will attempt to use it (try/except guarded).
"""
from typing import Optional, Callable
import threading
import sys
import time
try:
    import numpy as np
except Exception:
    np = None

# Attempt to import Hance SDK at module level so we can expose clearer
# error messages and share a single reference. The actual SDK name and
# API may vary; we support several common patterns below.
try:
    import hance as hance_sdk  # type: ignore
except Exception:
    hance_sdk = None

# keep reference to original callback so we can restore it
_original_callback = None
_installed = False
_lock = threading.Lock()


class HanceProcessor:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path
        self._has_hance = False
        self._model = None
        self._hance_proc = None
        self._last_noise = 1e-6
        # Try to initialize the Hance SDK if available. We attempt several
        # common API shapes so this will work for different SDK versions.
        if hance_sdk is not None:
            try:
                # Preferred: a top-level loader function
                if hasattr(hance_sdk, 'load_model'):
                    try:
                        self._hance_proc = hance_sdk.load_model(model_path) if model_path else hance_sdk.load_model()
                        self._has_hance = True
                    except Exception:
                        self._hance_proc = None
                # Common alternative: a Model class
                if self._hance_proc is None and hasattr(hance_sdk, 'Model'):
                    try:
                        self._model = hance_sdk.Model(model_path) if model_path else hance_sdk.Model()
                        # some SDKs expose a processor from the model
                        self._hance_proc = getattr(self._model, 'processor', None) or self._model
                        self._has_hance = True
                    except Exception:
                        self._model = None
                # Another alternative: Denoiser / Processor class
                if self._hance_proc is None and hasattr(hance_sdk, 'Denoiser'):
                    try:
                        self._hance_proc = hance_sdk.Denoiser(model_path) if model_path else hance_sdk.Denoiser()
                        self._has_hance = True
                    except Exception:
                        self._hance_proc = None
            except Exception:
                # any error -> disable hance usage
                self._hance_proc = None
                self._has_hance = False

    def process_int16_array(self, arr):
        """Process a numpy int16 array and return a new int16 array.

        If a real Hance model is available, call into it. Otherwise apply
        a simple noise-gating algorithm.
        """
        if arr is None:
            return arr
        # If Hance SDK available and processor loaded, attempt to call it
        if self._has_hance and self._hance_proc is not None:
            try:
                # Try several common method names (process, apply, denoise, infer)
                for name in ('process', 'apply', 'denoise', 'infer', 'run'):
                    fn = getattr(self._hance_proc, name, None)
                    if callable(fn):
                        try:
                            out = fn(arr)
                            # If returns bytes, convert to numpy
                            if isinstance(out, (bytes, bytearray)) and np is not None:
                                out_arr = np.frombuffer(bytes(out), dtype=np.int16)
                                return out_arr
                            # If returns numpy-like, convert to int16
                            if np is not None and hasattr(out, 'dtype'):
                                return out.astype(np.int16)
                            # otherwise, if it returned list-like, try to coerce
                            try:
                                return np.asarray(out, dtype=np.int16)
                            except Exception:
                                return arr
                        except Exception:
                            # try next method name
                            continue
            except Exception:
                # fall through to fallback
                pass

        # Fallback: simple RMS-based noise gate
        if np is None:
            # no numpy -> return unchanged
            return arr

        try:
            # compute short-window RMS
            # use waveform as float in -1..1
            f = arr.astype('float32') / 32768.0
            rms = float(np.sqrt(np.mean(f * f) + 1e-12))
            # update noise estimate (slow-moving average)
            alpha = 0.995
            self._last_noise = alpha * self._last_noise + (1.0 - alpha) * rms

            # threshold relative to noise estimate
            if rms < max(1e-4, self._last_noise * 1.5):
                # quiet chunk -> attenuate
                factor = 0.25
            else:
                factor = 1.0

            out = (f * factor)
            # re-scale to int16
            out_i16 = np.clip(out * 32767.0, -32768, 32767).astype(np.int16)
            return out_i16
        except Exception:
            return arr

    def process_bytes(self, data: bytes):
        """Accept raw int16 bytes and return processed bytes."""
        if not data:
            return data
        if np is None:
            # cannot process; return original
            return data
        try:
            arr = np.frombuffer(data, dtype=np.int16)
            out = self.process_int16_array(arr)
            # if result is numpy array
            if np is not None and hasattr(out, 'tobytes'):
                return out.tobytes()
            # if result is bytes already
            if isinstance(out, (bytes, bytearray)):
                return bytes(out)
            # otherwise attempt to coerce
            return np.asarray(out, dtype=np.int16).tobytes()
        except Exception:
            return data


def _make_wrapper(proc: Optional[HanceProcessor], original_cb: Callable):
    """Return a callback wrapper that applies `proc` (if provided) then
    calls `original_cb` with the processed data (matching signature of
    sounddevice callbacks).
    """

    def wrapper(indata, frames, time_info, status):
        # Try to behave like main.callback: accept ndarray or raw bytes
        try:
            if np is not None and isinstance(indata, np.ndarray):
                try:
                    if proc is not None:
                        # downmix multi-channel to mono then process
                        if indata.ndim > 1 and indata.shape[1] > 1:
                            mono = indata.mean(axis=1).astype('int16')
                        else:
                            mono = indata.reshape(-1).astype('int16')
                        processed = proc.process_int16_array(mono)
                        original_cb(processed.tobytes(), frames, time_info, status)
                        return
                    else:
                        original_cb(indata, frames, time_info, status)
                        return
                except Exception:
                    # on error, fallback to original
                    original_cb(indata, frames, time_info, status)
                    return

            # Fallback for raw bytes
            try:
                if proc is not None:
                    processed = proc.process_bytes(bytes(indata))
                    original_cb(processed, frames, time_info, status)
                else:
                    original_cb(indata, frames, time_info, status)
            except Exception:
                original_cb(indata, frames, time_info, status)
        except Exception:
            # be defensive: ignore errors in wrapper
            try:
                original_cb(indata, frames, time_info, status)
            except Exception:
                pass

    return wrapper


def install(model_path: Optional[str] = None):
    """Install the noise-cancelling wrapper by replacing `main.callback`.

    This is done in-place and is reversible via `uninstall()`.
    """
    global _original_callback, _installed
    import main as mainmod

    with _lock:
        if _installed:
            return True
        # record original
        _original_callback = getattr(mainmod, 'callback', None)
        proc = HanceProcessor(model_path)
        if _original_callback is None:
            return False
        mainmod.callback = _make_wrapper(proc, _original_callback)
        _installed = True
        return True


def uninstall():
    """Restore the original `main.callback` if we previously installed a wrapper."""
    global _original_callback, _installed
    import main as mainmod

    with _lock:
        if not _installed:
            return False
        try:
            if _original_callback is not None:
                mainmod.callback = _original_callback
        except Exception:
            pass
        _installed = False
        return True


def is_installed():
    return bool(_installed)
