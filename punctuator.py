"""Lightweight punctuation and casing post-processor.

Cleaned implementation that supports:
- rule-based fallback
- Hugging Face pipelines (optional)
- Vosk recasepunc predictor (if present)
- subprocess adapter via 'subproc:' prefix
"""
import os
import re
import subprocess
import tempfile
import traceback
import importlib.util
from typing import Optional


class Punctuator:
    def __init__(self, mode: str = "rule", hf_pipeline: Optional[object] = None):
        self.mode = mode
        self.hf_pipeline = hf_pipeline
        # If initialization encountered a non-fatal error (e.g., HF backend missing),
        # a human-readable diagnostic will be stored here so callers can surface it.
        self.init_error: Optional[str] = None

    @staticmethod
    def from_path(path: Optional[str]):
        if not path:
            return Punctuator(mode="rule")

        model_id = path
        if path.startswith('hf:'):
            model_id = path[3:]

        # subprocess adapter
        if isinstance(path, str) and path.startswith('subproc:'):
            cmd_template = path[len('subproc:'):]
            return SubprocessPunctuator(cmd_template)

        # try Vosk recasepunc model folder
        recase_err = None
        try:
            if os.path.isdir(path):
                ck = os.path.join(path, 'checkpoint')
                model_dir = ck if os.path.exists(ck) else path
                try:
                    import sys as _sys
                    added_path = None
                    # If the model folder contains a 'recasepunc' package folder,
                    # import will resolve when the parent directory is on sys.path.
                    candidate_pkg = os.path.join(model_dir, 'recasepunc')
                    if os.path.isdir(candidate_pkg):
                        pkg_base = os.path.dirname(model_dir)
                        if pkg_base not in _sys.path:
                            _sys.path.insert(0, pkg_base)
                            added_path = pkg_base
                    else:
                        # Otherwise add the model_dir itself (legacy layout where
                        # recasepunc module files live at top-level of model_dir)
                        if model_dir not in _sys.path:
                            _sys.path.insert(0, model_dir)
                            added_path = model_dir
                    try:
                        from recasepunc import CasePuncPredictor
                        predictor = CasePuncPredictor(model_dir, lang="en")
                        return Punctuator(mode="recasepunc", hf_pipeline=predictor)
                    finally:
                        if added_path:
                            try:
                                _sys.path.remove(added_path)
                            except Exception:
                                pass
                except Exception as e:
                    # capture the recasepunc import/initialization error for diagnostics
                    try:
                        recase_err = traceback.format_exc()
                    except Exception:
                        recase_err = str(e)
                    # If the module wasn't found, attempt to locate a recasepunc python
                    # source file inside the model folder and import it directly.
                    try:
                        if isinstance(e, ModuleNotFoundError) or 'No module named' in str(e):
                            # look for likely filenames
                            candidates = []
                            p1 = os.path.join(model_dir, 'recasepunc.py')
                            if os.path.isfile(p1):
                                candidates.append(p1)
                            p2 = os.path.join(model_dir, 'recasepunc', '__init__.py')
                            if os.path.isfile(p2):
                                candidates.append(p2)
                            # any other .py inside recasepunc subfolder
                            pdir = os.path.join(model_dir, 'recasepunc')
                            if os.path.isdir(pdir):
                                for fn in os.listdir(pdir):
                                    if fn.endswith('.py'):
                                        candidates.append(os.path.join(pdir, fn))

                            # try loading candidates until one works
                            for idx, fn in enumerate(candidates):
                                try:
                                    import importlib.util as _il
                                    mod_name = f"recasepunc_fallback_{idx}"
                                    spec = _il.spec_from_file_location(mod_name, fn)
                                    if spec and spec.loader:
                                        mod = _il.module_from_spec(spec)
                                        spec.loader.exec_module(mod)
                                        if hasattr(mod, 'CasePuncPredictor'):
                                            CasePuncPredictor = getattr(mod, 'CasePuncPredictor')
                                            predictor = CasePuncPredictor(model_dir, lang="en")
                                            return Punctuator(mode="recasepunc", hf_pipeline=predictor)
                                except Exception:
                                    # try next candidate
                                    continue
                    except Exception:
                        # ignore fallback import errors; recase_err already contains traceback
                        pass
        except Exception:
            try:
                recase_err = traceback.format_exc()
            except Exception:
                recase_err = "Unknown error while checking recasepunc path"

        # try HF pipeline
        try:
            from transformers import pipeline
            hf_pipe = pipeline('text2text-generation', model=model_id, device=-1)
            return Punctuator(mode="hf", hf_pipeline=hf_pipe)
        except Exception as e:
            # Build a detailed diagnostic to help users fix missing backend issues.
            tb = traceback.format_exc()
            torch_ok = importlib.util.find_spec('torch') is not None
            tf_ok = importlib.util.find_spec('tensorflow') is not None
            flax_ok = importlib.util.find_spec('flax') is not None
            msg = (
                f"Failed to create HuggingFace pipeline for model '{model_id}': {e}\n"
                f"Traceback:\n{tb}\n"
                f"Detected backends - torch: {torch_ok}, tensorflow: {tf_ok}, flax: {flax_ok}\n"
            )
            if recase_err:
                msg += f"\nAdditionally, attempted to load as Vosk recasepunc and encountered:\n{recase_err}\n"
            msg += (
                "Recommendation: either point the punctuator to a supported HuggingFace model, "
                "or ensure the selected folder contains a recasepunc predictor module. "
                "To use HF models install 'transformers' and a backend: e.g. 'pip install transformers torch' for CPU."
            )
            p = Punctuator(mode="rule")
            p.init_error = msg
            try:
                with open('punctuator_init_error.log', 'w', encoding='utf-8') as lf:
                    lf.write(msg)
            except Exception:
                pass
            try:
                import sys
                sys.stderr.write(msg + '\n')
            except Exception:
                pass
            return p

    def punctuate(self, text: str) -> str:
        if not text:
            return text

        try:
            if self.mode == 'hf' and self.hf_pipeline is not None:
                out = self.hf_pipeline(text, truncation=True)
                if isinstance(out, list) and len(out) > 0:
                    v = out[0]
                    if isinstance(v, dict):
                        return v.get('generated_text') or v.get('summary_text') or str(v)
                    return str(v)
                return text

            if self.mode == 'recasepunc' and self.hf_pipeline is not None:
                try:
                    predictor = self.hf_pipeline
                    tokens = list(enumerate(predictor.tokenize(text)))
                    results = ""
                    for token, case_label, punc_label in predictor.predict(tokens, lambda x: x[1]):
                        prediction = predictor.map_punc_label(predictor.map_case_label(token[1], case_label), punc_label)

                        if token[1][0] == '\'' or (len(results) > 0 and results[-1] == '\''):
                            results = results + prediction
                        elif token[1][0] != '#':
                            results = results + ' ' + prediction
                        else:
                            results = results + prediction

                    return results.strip()
                except Exception:
                    return text

        except Exception:
            return text

        # rule fallback
        s = text.strip()
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"\bi\b", "I", s)
        if s:
            s = s[0].upper() + s[1:]

        def _cap_after(m):
            return m.group(1) + m.group(2).upper()

        s = re.sub(r"([\.\?\!][\"']?\s+)([a-z])", _cap_after, s)
        if not re.search(r'[\.\?\!]\s*$', s):
            s = s + '.'
        return s


class SubprocessPunctuator:
    def __init__(self, cmd_template: str, timeout: float = 10.0):
        self.cmd_template = cmd_template
        self.timeout = float(timeout)

    def punctuate(self, text: str) -> str:
        if not text:
            return text
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', suffix='.txt') as f:
                f.write(text)
                tmp = f.name

            cmd = self.cmd_template.format(input=tmp, file=tmp)
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=self.timeout, shell=True)
            out = proc.stdout.decode('utf-8', errors='replace').strip()
            if out:
                return out
            return text
        except subprocess.TimeoutExpired:
            return text
        except Exception:
            return text
        finally:
            if tmp:
                try:
                    os.remove(tmp)
                except Exception:
                    pass


def simple_punctuate(text: str) -> str:
    return Punctuator().punctuate(text)


if __name__ == '__main__':
    import sys
    p = None
    if len(sys.argv) > 1:
        p = Punctuator.from_path(sys.argv[1])
    else:
        p = Punctuator()
    for ln in sys.stdin:
        print(p.punctuate(ln.strip()))
