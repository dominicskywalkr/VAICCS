"""Lightweight punctuation and casing post-processor.

This module provides a small rule-based fallback punctuator and an
optional Hugging Face-backed loader when a checkpoint/model id is provided
and `transformers` is available. The goal is to provide a safe, dependency-
aware post-processor that can be used in-process or replaced with a more
capable implementation later.
"""
import re
from typing import Optional


class Punctuator:
    def __init__(self, mode: str = "rule", hf_pipeline: Optional[object] = None):
        """Create a punctuator.

        mode: 'rule' or 'hf'
        hf_pipeline: optional transformers pipeline object used when mode == 'hf'
        """
        self.mode = mode
        self.hf_pipeline = hf_pipeline

    @staticmethod
    def from_path(path: Optional[str]):
        """Factory that returns a Punctuator.

        If `path` is None or empty, returns a rule-based punctuator.
        If `path` starts with 'hf:' the remainder is treated as a Hugging
        Face model id / local dir and an attempt is made to build a
        `transformers` pipeline. If `transformers` is not available or the
        load fails, falls back to the rule-based implementation and does
        not raise.
        """
        if not path:
            return Punctuator(mode="rule")
        # Accept forms like 'hf:facebook/your-model' or a plain path/model id
        model_id = path
        if path.startswith('hf:'):
            model_id = path[3:]

        try:
            from transformers import pipeline
            # Use a text2text generation pipeline; many punctuation models are
            # available as seq2seq transformers. This is optional and best-effort.
            hf_pipe = pipeline('text2text-generation', model=model_id, device=-1)
            return Punctuator(mode="hf", hf_pipeline=hf_pipe)
        except Exception:
            # Could not load HF pipeline; fall back to rule-based.
            return Punctuator(mode="rule")

    def punctuate(self, text: str) -> str:
        """Return punctuated and cased text.

        This method is intentionally conservative: it preserves the original
        words, applies sentence capitalization, ensures a sentence terminator,
        and normalizes lone 'i' to 'I'. Use an HF-backed pipeline for better
        quality when available.
        """
        if not text:
            return text
        try:
            if self.mode == 'hf' and self.hf_pipeline is not None:
                # transformers pipeline expects reasonable-length input; trim
                # whitespace and run the model, returning the generated text.
                out = self.hf_pipeline(text, truncation=True)
                if isinstance(out, list) and len(out) > 0:
                    # many pipelines return dicts with 'generated_text' or 'summary_text'
                    v = out[0]
                    if isinstance(v, dict):
                        return v.get('generated_text') or v.get('summary_text') or str(v)
                    return str(v)
                return text

            # Rule-based fallback
            s = text.strip()
            # Normalize whitespace
            s = re.sub(r"\s+", " ", s)

            # Capitalize 'i' as a standalone word
            s = re.sub(r"\bi\b", "I", s)

            # Capitalize first letter of the string
            if s:
                s = s[0].upper() + s[1:]

            # Capitalize after sentence-ending punctuation
            def _cap_after(m):
                return m.group(1) + m.group(2).upper()

            s = re.sub(r"([\.\?\!][\"']?\s+)([a-z])", _cap_after, s)

            # Ensure sentence terminator at end
            if not re.search(r'[\.\?\!]\s*$', s):
                s = s + '.'

            return s
        except Exception:
            return text


def simple_punctuate(text: str) -> str:
    return Punctuator().punctuate(text)


if __name__ == '__main__':
    # tiny CLI for quick local testing
    import sys
    p = None
    if len(sys.argv) > 1:
        p = Punctuator.from_path(sys.argv[1])
    else:
        p = Punctuator()
    for ln in sys.stdin:
        print(p.punctuate(ln.strip()))
