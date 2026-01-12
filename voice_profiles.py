import json
import math
import os
import sys
import resources
from datetime import datetime
from pathlib import Path
import shutil
from typing import List, Optional, Dict, Tuple

import numpy as np
# soundfile is optional; fall back to the builtin wave reader for basic WAV support
try:
    import soundfile as sf
    HAS_SOUNDFILE = True
except Exception:
    sf = None
    HAS_SOUNDFILE = False

# Try to use librosa when available for more robust MFCCs; otherwise fall back
try:
    import librosa  # type: ignore
    HAS_LIBROSA = True
except Exception:
    HAS_LIBROSA = False


def _slugify(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name).lower()


# Project base directory (directory containing this script)
_VP_BASE = os.path.abspath(os.path.dirname(__file__))


def _vp_maybe_rel(p: str) -> str:
    """Return a path relative to the project base if the path is inside it,
    otherwise return the absolute path unchanged. Normalizes to forward slashes."""
    try:
        if not p:
            return ''
        full = os.path.abspath(p)
        base_n = os.path.normcase(_VP_BASE)
        full_n = os.path.normcase(full)
        if full_n == base_n or full_n.startswith(base_n + os.sep):
            return os.path.relpath(full, _VP_BASE).replace('\\', '/')
        return full
    except Exception:
        return p


def _vp_resolve_rel(p: str) -> str:
    """Resolve a possibly-relative path against project base. If already absolute,
    returns as-is."""
    try:
        if not p:
            return ''
        if os.path.isabs(p):
            return os.path.abspath(p)
        return os.path.abspath(os.path.join(_VP_BASE, p))
    except Exception:
        return p


class VoiceProfileManager:
    """Manage voice profiles by extracting simple MFCC-based embeddings from WAV files.

    Features:
    - create_profile(name, wav_paths): create a new profile from one or more WAV files
    - update_profile(name, add_wav_paths, replace): update or replace an existing profile
    - list_profiles(), load_profile(name), delete_profile(name)
    - match_profile(wav_path, top_k): find the most similar profiles by cosine similarity

    Notes:
    - This uses averaged MFCC statistics (mean+std) as a lightweight speaker embedding.
    - For production speaker recognition, prefer a model-based approach (i-vector/xvector).
    """

    INDEX_NAME = "index.json"

    def __init__(self, profiles_dir: str = None, sample_rate: int = 16000, n_mfcc: int = 20):
        # Default to Documents/VAICCS/Voice profiles on macOS, otherwise local folder
        if profiles_dir:
            pd = profiles_dir
        else:
            try:
                if sys.platform == 'darwin':
                    pd = resources.get_voice_profiles_dir()
                else:
                    pd = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'voice_profiles')
            except Exception:
                pd = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'voice_profiles')

        self.profiles_dir = Path(pd)
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        self.n_mfcc = n_mfcc
        self.index_path = self.profiles_dir / self.INDEX_NAME
        self._index: Dict[str, Dict] = {}
        self._load_index()

    def _read_wav(self, wav_path: str) -> Tuple[np.ndarray, int]:
        """Read a WAV file into a numpy array and return (y, sr).

        Uses `soundfile` when available; otherwise falls back to the builtin
        `wave` module and basic conversions for common sample widths.
        """
        if HAS_SOUNDFILE and sf is not None:
            y, sr = sf.read(wav_path)
            return y, sr

        # fallback using wave for PCM WAV files
        import wave

        with wave.open(wav_path, 'rb') as wf:
            sr = wf.getframerate()
            nchan = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            nframes = wf.getnframes()
            frames = wf.readframes(nframes)

        # interpret bytes
        if sampwidth == 1:
            dtype = np.uint8
        elif sampwidth == 2:
            dtype = np.int16
        elif sampwidth == 4:
            dtype = np.int32
        else:
            # 24-bit or other; convert via uint8 then reshape
            a = np.frombuffer(frames, dtype=np.uint8)
            if sampwidth == 3:
                # 24-bit little-endian to int32
                a = a.reshape(-1, 3)
                samples = (a[:, 0].astype(np.int32) | (a[:, 1].astype(np.int32) << 8) | (a[:, 2].astype(np.int32) << 16))
                samples = samples.astype(np.int32)
                samples[samples >= 2 ** 23] -= 2 ** 24
                y = samples.astype(np.float32) / float(2 ** 23)
                if nchan > 1:
                    y = y.reshape(-1, nchan)
                return y, sr
            else:
                # unknown width; try int16 fallback
                dtype = np.int16

        y = np.frombuffer(frames, dtype=dtype)
        if nchan > 1:
            y = y.reshape(-1, nchan)

        # normalize to float32
        if dtype == np.uint8:
            y = (y.astype(np.float32) - 128.0) / 128.0
        elif dtype == np.int16:
            y = y.astype(np.float32) / 32768.0
        elif dtype == np.int32:
            y = y.astype(np.float32) / 2147483648.0

        return y, sr

    def _load_index(self):
        if self.index_path.exists():
            try:
                with open(self.index_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                # Resolve any relative-looking paths in index entries
                resolved = {}
                for k, v in (raw or {}).items():
                    if isinstance(v, dict):
                        entry = {}
                        for ik, iv in v.items():
                            if isinstance(iv, str):
                                # if value looks like a path (contains separator or dot), resolve it
                                if ('/' in iv) or ('\\' in iv) or iv.startswith('.'):
                                    entry[ik] = _vp_resolve_rel(iv)
                                else:
                                    entry[ik] = iv
                            else:
                                entry[ik] = iv
                        resolved[k] = entry
                    else:
                        resolved[k] = v
                self._index = resolved
            except Exception:
                self._index = {}
        else:
            self._index = {}

    def _save_index(self):
        # Convert any absolute paths inside index entries to relative when under project base
        try:
            serial = {}
            for k, v in self._index.items():
                if isinstance(v, dict):
                    entry = {}
                    for ik, iv in v.items():
                        if isinstance(iv, str):
                            # try to convert values that look like paths
                            if ('/' in iv) or ('\\' in iv) or iv.startswith('.') or os.path.isabs(iv):
                                entry[ik] = _vp_maybe_rel(iv)
                            else:
                                entry[ik] = iv
                        else:
                            entry[ik] = iv
                    serial[k] = entry
                else:
                    serial[k] = v
        except Exception:
            serial = self._index
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(serial, f, indent=2)

    def _extract_embedding(self, wav_path: str) -> np.ndarray:
        # Prefer librosa if available (better resampling and MFCC), otherwise use fallback
        if HAS_LIBROSA:
            y, sr = librosa.load(wav_path, sr=self.sample_rate, mono=True)
            mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=self.n_mfcc)
        else:
            # lightweight fallback: read with soundfile if available, otherwise use builtin reader
            y, sr = self._read_wav(wav_path)
            # promote to mono
            if y.ndim > 1:
                y = np.mean(y, axis=1)
            # resample if needed (simple linear interpolation)
            if sr != self.sample_rate:
                # naive resample
                import math

                ratio = float(self.sample_rate) / float(sr)
                n = int(math.ceil(len(y) * ratio))
                x_old = np.arange(len(y))
                x_new = np.linspace(0, len(y) - 1, n)
                y = np.interp(x_new, x_old, y).astype(np.float32)
                sr = self.sample_rate

            mfcc = self._mfcc_fallback(y, sr, n_mfcc=self.n_mfcc)

        # stats
        mean = np.mean(mfcc, axis=1)
        std = np.std(mfcc, axis=1)
        emb = np.concatenate([mean, std]).astype(np.float32)
        # normalize
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb

    def _mfcc_fallback(self, signal: np.ndarray, sr: int, n_mfcc: int = 20) -> np.ndarray:
        """Compute a simple MFCC-like matrix (n_mfcc x frames) using numpy.

        This is a compact implementation intended as a fallback when librosa
        is not available. It computes log-mel filterbank energies and applies
        a DCT to get cepstral coefficients.
        """
        # framing
        frame_len = int(0.025 * sr)
        frame_step = int(0.010 * sr)
        signal_length = len(signal)
        num_frames = int(np.ceil(float(np.abs(signal_length - frame_len)) / frame_step)) + 1
        pad_length = int((num_frames - 1) * frame_step + frame_len)
        pad_signal = np.append(signal, np.zeros((pad_length - signal_length,)))

        indices = np.tile(np.arange(0, frame_len), (num_frames, 1)) + np.tile(np.arange(0, num_frames * frame_step, frame_step), (frame_len, 1)).T
        frames = pad_signal[indices.astype(np.int32, copy=False)]
        # window
        frames *= np.hamming(frame_len)
        NFFT = 1
        while NFFT < frame_len:
            NFFT *= 2
        mag_frames = np.absolute(np.fft.rfft(frames, NFFT))
        pow_frames = (1.0 / NFFT) * (mag_frames ** 2)

        # mel filterbanks
        nfilt = 40
        low_freq_mel = 0
        high_freq_mel = 2595 * np.log10(1 + (sr / 2) / 700.0)
        mel_points = np.linspace(low_freq_mel, high_freq_mel, nfilt + 2)
        hz_points = 700 * (10 ** (mel_points / 2595.0) - 1)
        bin = np.floor((NFFT + 1) * hz_points / sr).astype(int)

        fbank = np.zeros((nfilt, int(NFFT / 2 + 1)))
        for m in range(1, nfilt + 1):
            f_m_minus = bin[m - 1]
            f_m = bin[m]
            f_m_plus = bin[m + 1]
            if f_m_minus == f_m:
                continue
            for k in range(f_m_minus, f_m):
                if k < fbank.shape[1]:
                    fbank[m - 1, k] = (k - bin[m - 1]) / (bin[m] - bin[m - 1])
            if f_m == f_m_plus:
                continue
            for k in range(f_m, f_m_plus):
                if k < fbank.shape[1]:
                    fbank[m - 1, k] = (bin[m + 1] - k) / (bin[m + 1] - bin[m])

        filter_banks = np.dot(pow_frames, fbank.T)
        # avoid log of zero
        filter_banks = np.where(filter_banks == 0, np.finfo(float).eps, filter_banks)
        log_fbanks = np.log(filter_banks)

        # DCT (type II) to get MFCCs
        nframes = log_fbanks.shape[0]
        ncoeff = n_mfcc
        dct_basis = np.empty((ncoeff, nfilt))
        for i in range(ncoeff):
            dct_basis[i, :] = np.cos(np.pi * i * (2 * np.arange(nfilt) + 1) / (2.0 * nfilt))
        mfcc = np.dot(log_fbanks, dct_basis.T)
        # transpose to (n_mfcc, frames)
        return mfcc.T

    def create_profile(self, name: str, wav_paths: List[str]) -> Dict:
        """Create a profile from one or more WAV files. Returns metadata dict."""
        if isinstance(wav_paths, (str, Path)):
            wav_paths = [str(wav_paths)]
        if name in self._index:
            raise ValueError(f"Profile '{name}' already exists. Use update_profile to add samples.")

        slug = _slugify(name)
        profile_dir = self.profiles_dir / slug
        if profile_dir.exists():
            raise FileExistsError(f"Profile folder already exists: {profile_dir}")
        profile_dir.mkdir(parents=True, exist_ok=False)

        # copy wav files into profile folder and compute embeddings from the copies
        copied_files = []
        embeddings = []
        for p in wav_paths:
            src = Path(p)
            if not src.exists():
                # skip missing
                continue
            dest = profile_dir / src.name
            try:
                shutil.copy2(str(src), str(dest))
            except Exception:
                # if copy fails, try to still use the original path
                dest = src
            copied_files.append(str(dest))
            emb = self._extract_embedding(str(dest))
            embeddings.append(emb)

        if not embeddings:
            # cleanup empty folder
            try:
                shutil.rmtree(profile_dir)
            except Exception:
                pass
            raise ValueError("No valid wav paths provided or files could not be read")

        profile_emb = np.mean(np.stack(embeddings, axis=0), axis=0)

        emb_path = profile_dir / "embedding.npy"
        np.save(str(emb_path), profile_emb)

        # write a profile metadata file inside the folder
        meta = {
            "name": name,
            "slug": slug,
            "folder": str(slug),
            "created_at": datetime.utcnow().isoformat() + "Z",
            "source_files": [os.path.basename(p) for p in copied_files],
            "embedding_file": os.path.basename(str(emb_path)),
            "profile_file": "profile.json",
        }
        with open(profile_dir / "profile.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        # update global index with minimal info
        self._index[name] = {"name": name, "slug": slug, "folder": str(slug), "profile_file": "profile.json"}
        self._save_index()
        return meta

    def update_profile(self, name: str, add_wav_paths: Optional[List[str]] = None, replace: bool = False) -> Dict:
        """Update an existing profile. If replace=True, the added wavs replace previous profile."""
        if name not in self._index:
            raise KeyError(f"Profile '{name}' does not exist")
        meta = self._index[name]
        # determine profile folder
        folder = meta.get("folder") or meta.get("slug")
        if not folder:
            raise KeyError("Profile folder information missing in index")
        profile_dir = self.profiles_dir / folder
        if not profile_dir.exists():
            raise FileNotFoundError(f"Profile folder missing: {profile_dir}")

        emb_path = profile_dir / "embedding.npy"

        if replace:
            embeddings = []
        else:
            if emb_path.exists():
                existing = np.load(emb_path)
                embeddings = [existing]
            else:
                embeddings = []

        copied = []
        if add_wav_paths:
            for p in add_wav_paths:
                src = Path(p)
                if not src.exists():
                    continue
                dest = profile_dir / src.name
                try:
                    shutil.copy2(str(src), str(dest))
                except Exception:
                    dest = src
                copied.append(str(dest))
                embeddings.append(self._extract_embedding(str(dest)))

        if not embeddings:
            raise ValueError("No embeddings available after update")

        new_emb = np.mean(np.stack(embeddings, axis=0), axis=0)
        np.save(str(emb_path), new_emb)

        # update profile.json
        profile_meta_path = profile_dir / "profile.json"
        try:
            with open(profile_meta_path, "r", encoding="utf-8") as f:
                profile_meta = json.load(f)
        except Exception:
            profile_meta = {"name": name, "slug": folder}

        if copied:
            profile_meta.setdefault("source_files", []).extend([os.path.basename(p) for p in copied])
        profile_meta["updated_at"] = datetime.utcnow().isoformat() + "Z"
        with open(profile_meta_path, "w", encoding="utf-8") as f:
            json.dump(profile_meta, f, indent=2)

        # update global index minimal info
        self._index[name] = {"name": name, "slug": folder, "folder": folder, "profile_file": "profile.json"}
        self._save_index()
        return profile_meta

    def edit_profile(self, name: str, new_name: Optional[str] = None,
                     add_wav_paths: Optional[List[str]] = None,
                     remove_wav_filenames: Optional[List[str]] = None,
                     replace_wav_paths: Optional[List[str]] = None) -> Dict:
        """Edit a profile's metadata and source WAV files.

        - new_name: change the profile display name (and slug/folder will be renamed)
        - add_wav_paths: list of wav file paths to add to the profile
        - remove_wav_filenames: list of filenames (basenames) to remove from the profile folder
        - replace_wav_paths: if provided, replace the set of source files with these

        Returns the updated profile metadata dictionary.
        """
        if name not in self._index:
            raise KeyError(f"Profile '{name}' does not exist")

        meta = self._index[name]
        folder = meta.get("folder") or meta.get("slug")
        if not folder:
            raise KeyError("Profile folder information missing in index")
        profile_dir = self.profiles_dir / folder
        if not profile_dir.exists():
            raise FileNotFoundError(f"Profile folder missing: {profile_dir}")

        # load existing profile meta
        profile_meta_path = profile_dir / "profile.json"
        try:
            with open(profile_meta_path, "r", encoding="utf-8") as f:
                profile_meta = json.load(f)
        except Exception:
            profile_meta = {"name": name, "slug": folder}

        # Handle rename
        if new_name and new_name != name:
            if new_name in self._index:
                raise ValueError(f"Profile name '{new_name}' already exists")
            new_slug = _slugify(new_name)
            new_folder = self.profiles_dir / new_slug
            if new_folder.exists():
                raise FileExistsError(f"Target profile folder already exists: {new_folder}")
            # move directory
            shutil.move(str(profile_dir), str(new_folder))
            # update references
            profile_dir = new_folder
            folder = str(new_slug)
            profile_meta["name"] = new_name
            profile_meta["slug"] = new_slug
            profile_meta["folder"] = folder

            # update global index key: remove old key and create new
            self._index.pop(name, None)
            name = new_name

        # If replace_wav_paths provided, remove all existing source files (except metadata/embedding)
        if replace_wav_paths is not None:
            # remove all files listed in source_files
            for fn in list(profile_meta.get("source_files", [])):
                p = profile_dir / fn
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
            profile_meta["source_files"] = []

        # Remove specified wav files by basename
        if remove_wav_filenames:
            for fn in remove_wav_filenames:
                p = profile_dir / fn
                try:
                    if p.exists():
                        p.unlink()
                except Exception:
                    pass
                # remove from source_files list if present
                if "source_files" in profile_meta and fn in profile_meta["source_files"]:
                    profile_meta["source_files"].remove(fn)

        # Add new wavs (either via add_wav_paths or replace_wav_paths)
        to_add = []
        if replace_wav_paths is not None:
            to_add = list(replace_wav_paths)
        elif add_wav_paths:
            to_add = list(add_wav_paths)

        copied_files = []
        new_embeddings = []
        # If there are existing embedding(s), load them to combine unless we are replacing entirely
        emb_path = profile_dir / "embedding.npy"
        if replace_wav_paths is None and emb_path.exists():
            try:
                existing = np.load(str(emb_path))
                new_embeddings.append(existing)
            except Exception:
                pass

        if to_add:
            for p in to_add:
                src = Path(p)
                if not src.exists():
                    continue
                dest = profile_dir / src.name
                try:
                    shutil.copy2(str(src), str(dest))
                except Exception:
                    dest = src
                copied_files.append(str(dest))
                emb = self._extract_embedding(str(dest))
                new_embeddings.append(emb)
                profile_meta.setdefault("source_files", []).append(os.path.basename(str(dest)))

        # If no embeddings available (after operations), try to compute from remaining source_files
        if not new_embeddings:
            # attempt to compute from existing files in profile_meta.source_files
            sfiles = profile_meta.get("source_files", [])
            for fn in sfiles:
                p = profile_dir / fn
                if p.exists():
                    try:
                        new_embeddings.append(self._extract_embedding(str(p)))
                    except Exception:
                        pass

        if not new_embeddings:
            raise ValueError("No embeddings available after edit; profile must contain at least one valid WAV")

        new_emb = np.mean(np.stack(new_embeddings, axis=0), axis=0)
        np.save(str(profile_dir / "embedding.npy"), new_emb)

        profile_meta["updated_at"] = datetime.utcnow().isoformat() + "Z"
        with open(profile_dir / "profile.json", "w", encoding="utf-8") as f:
            json.dump(profile_meta, f, indent=2)

        # update global index entry
        self._index[name] = {"name": name, "slug": folder, "folder": folder, "profile_file": "profile.json"}
        self._save_index()
        return profile_meta

    def delete_profile(self, name: str) -> bool:
        # Remove index entry first
        if name not in self._index:
            return False
        meta = self._index.pop(name)

        # Try to determine the folder to remove: prefer explicit folder/slug, fall back to slugified name
        folder = meta.get("folder") or meta.get("slug") or _slugify(name)
        profile_path = self.profiles_dir / folder

        try:
            if profile_path.exists():
                shutil.rmtree(profile_path)
        except Exception:
            # ignore removal errors but continue to attempt other cleanups
            pass

        # As a safety: scan all profile folders and remove any whose profile.json 'name' matches
        try:
            for p in self.profiles_dir.iterdir():
                try:
                    if not p.is_dir():
                        continue
                    pf = p / "profile.json"
                    if not pf.exists():
                        continue
                    with open(pf, 'r', encoding='utf-8') as f:
                        pdata = json.load(f)
                    if pdata.get('name') == name:
                        try:
                            shutil.rmtree(p)
                        except Exception:
                            pass
                except Exception:
                    # ignore errors for individual folders
                    pass
        except Exception:
            pass

        self._save_index()
        return True

    def list_profiles(self) -> List[str]:
        return list(self._index.keys())

    def load_profile_embedding(self, name: str) -> np.ndarray:
        if name not in self._index:
            raise KeyError(f"Profile '{name}' not found")
        meta = self._index[name]
        folder = meta.get("folder") or meta.get("slug")
        if not folder:
            raise KeyError("Profile folder missing in index")
        emb_file = self.profiles_dir / folder / "embedding.npy"
        if not emb_file.exists():
            raise FileNotFoundError(f"Embedding file missing: {emb_file}")
        return np.load(emb_file)

    def match_profile(self, wav_path: str, top_k: int = 1) -> List[Tuple[str, float]]:
        """Return top_k matching profiles as list of (name, score) where score is cosine similarity [0..1]."""
        emb = self._extract_embedding(wav_path)
        scores = []
        for name, meta in self._index.items():
            # profile can be stored in its folder with embedding.npy
            folder = meta.get("folder") or meta.get("slug")
            if folder:
                emb_path = self.profiles_dir / folder / "embedding.npy"
            else:
                # fallback to old index format
                emb_path = self.profiles_dir / meta.get("embedding_file", "")
            try:
                p_emb = np.load(emb_path)
            except Exception:
                continue
            # cosine similarity
            denom = (np.linalg.norm(emb) * np.linalg.norm(p_emb))
            if denom <= 0:
                sim = 0.0
            else:
                sim = float(np.dot(emb, p_emb) / denom)
            scores.append((name, sim))
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage simple voice profiles (MFCC-stat embeddings)")
    sub = parser.add_subparsers(dest="cmd")

    p_create = sub.add_parser("create")
    p_create.add_argument("name")
    p_create.add_argument("wav", nargs="+", help="One or more WAV files to build the profile from")

    p_list = sub.add_parser("list")

    p_match = sub.add_parser("match")
    p_match.add_argument("wav")
    p_match.add_argument("-k", type=int, default=1)

    p_delete = sub.add_parser("delete")
    p_delete.add_argument("name")

    p_edit = sub.add_parser("edit")
    p_edit.add_argument("name")
    p_edit.add_argument("--new-name", dest="new_name", help="New profile name")
    p_edit.add_argument("--add", dest="add_wavs", nargs="+", help="WAV files to add to the profile")
    p_edit.add_argument("--remove", dest="remove_files", nargs="+", help="Filenames (basenames) to remove from the profile folder")
    p_edit.add_argument("--replace", dest="replace_wavs", nargs="+", help="Replace source files with these WAVs")

    args = parser.parse_args()
    mgr = VoiceProfileManager()

    if args.cmd == "create":
        meta = mgr.create_profile(args.name, args.wav)
        print("Created:", meta)
    elif args.cmd == "list":
        for n in mgr.list_profiles():
            print(n)
    elif args.cmd == "match":
        res = mgr.match_profile(args.wav, top_k=args.k)
        for name, score in res:
            print(f"{name}: {score:.4f}")
    elif args.cmd == "delete":
        ok = mgr.delete_profile(args.name)
        print("Deleted" if ok else "Not found")
    elif args.cmd == "edit":
        try:
            meta = mgr.edit_profile(args.name, new_name=args.new_name, add_wav_paths=args.add_wavs,
                                    remove_wav_filenames=args.remove_files, replace_wav_paths=args.replace_wavs)
            print("Updated:", meta)
        except Exception as e:
            print("Error:", e)
    else:
        parser.print_help()
