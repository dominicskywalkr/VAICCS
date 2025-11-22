import json
import os
import shutil
from typing import Dict, List
from pathlib import Path


class CustomVocabManager:
    """Manage a small list of custom words and optional pronunciation strings.

    This does not modify the Vosk model graph. It is only used to provide
    a runtime vocabulary (word list) that can be passed to KaldiRecognizer as
    a grammar to bias recognition. Pronunciations are stored for user
    convenience (and potential future graph rebuilds) but are not applied at
    runtime.
    """

    def __init__(self, path: str = "custom_vocab.json"):
        # Resolve path against project base (directory containing this script)
        _CV_BASE = os.path.abspath(os.path.dirname(__file__))
        try:
            if path and not os.path.isabs(path):
                candidate = os.path.join(_CV_BASE, path)
            else:
                candidate = path
        except Exception:
            candidate = path
        self.path = os.path.abspath(candidate) if candidate else os.path.abspath(os.path.join(_CV_BASE, 'custom_vocab.json'))
        # words -> pronunciation (may be empty string)
        self._entries: Dict[str, str] = {}
        # directory next to the JSON file to store audio samples
        try:
            base = Path(self.path).resolve().parent
        except Exception:
            base = Path('.')
        self.data_dir = str(base / 'custom_vocab_data')
        os.makedirs(self.data_dir, exist_ok=True)
        self._load()

    def serializable_path(self) -> str:
        """Return the path suitable for serializing in settings: relative to project base
        when inside the project, otherwise an absolute path."""
        try:
            base = os.path.abspath(os.path.dirname(__file__))
            full = os.path.abspath(self.path)
            base_n = os.path.normcase(base)
            full_n = os.path.normcase(full)
            if full_n == base_n or full_n.startswith(base_n + os.sep):
                return os.path.relpath(full, base).replace('\\', '/')
            return full
        except Exception:
            return self.path

    def _load(self):
        try:
            if os.path.exists(self.path):
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._entries = {str(k): str(v) for k, v in data.items()}
        except Exception:
            # on any failure, start with empty
            self._entries = {}

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._entries, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def list_words(self) -> List[str]:
        return list(self._entries.keys())

    def get_pron(self, word: str) -> str:
        return self._entries.get(word, "")

    def set_word(self, word: str, pron: str = ""):
        if not word:
            return
        self._entries[word] = pron or ""
        self.save()

    def remove_word(self, word: str):
        try:
            if word in self._entries:
                del self._entries[word]
                self.save()
        except Exception:
            pass

    def clear(self):
        self._entries = {}
        self.save()

    def as_word_list(self) -> List[str]:
        # return words as a plain list (for grammar)
        return list(self._entries.keys())

    def export_lexicon_lines(self) -> List[str]:
        # produce simple lexicon lines: WORD PRON
        lines = []
        for w, p in self._entries.items():
            if p:
                lines.append(f"{w} {p}")
            else:
                lines.append(f"{w}")
        return lines

    # --- audio sample management ---
    def _word_dir(self, word: str) -> str:
        safe = ''.join(c for c in word if c.isalnum() or c in ('-', '_')).strip() or 'word'
        d = os.path.join(self.data_dir, safe)
        os.makedirs(d, exist_ok=True)
        return d

    def list_samples(self, word: str) -> List[str]:
        d = self._word_dir(word)
        try:
            files = [f for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]
            files.sort()
            return files
        except Exception:
            return []

    def add_sample_from_path(self, word: str, src_path: str) -> str:
        """Copy an existing WAV into the word's samples folder. Returns dest filename."""
        d = self._word_dir(word)
        try:
            base = os.path.basename(src_path)
            dest = os.path.join(d, base)
            # avoid overwrite by adding numeric suffix
            if os.path.exists(dest):
                name, ext = os.path.splitext(base)
                i = 1
                while True:
                    dest = os.path.join(d, f"{name}_{i}{ext}")
                    if not os.path.exists(dest):
                        break
                    i += 1
            shutil.copy2(src_path, dest)
            return os.path.basename(dest)
        except Exception:
            return ""

    def remove_sample(self, word: str, filename: str) -> bool:
        try:
            d = self._word_dir(word)
            p = os.path.join(d, filename)
            if os.path.exists(p):
                os.remove(p)
                return True
        except Exception:
            pass
        return False

    def sample_path(self, word: str, filename: str) -> str:
        return os.path.join(self._word_dir(word), filename)
