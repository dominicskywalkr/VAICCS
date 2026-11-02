import os
from tkinter import Tk
from gui_splash import Splash
import license_manager


def _collect_texts(widget, out):
    try:
        # try to read text if available
        txt = None
        try:
            txt = widget.cget('text')
        except Exception:
            try:
                # ttk.Label may use textvariable; attempt to read that
                txt = widget.cget('text')
            except Exception:
                txt = None
        if txt:
            out.append(str(txt))
    except Exception:
        pass
    try:
        for c in widget.winfo_children():
            _collect_texts(c, out)
    except Exception:
        pass


def _make_splash_and_get_texts(title_text):
    root = Tk()
    try:
        root.withdraw()
        s = Splash(root, title_text=title_text, creator="Test")
        # ensure widgets are created
        root.update_idletasks()
        texts = []
        _collect_texts(s, texts)
        try:
            s.close()
        except Exception:
            try:
                s.destroy()
            except Exception:
                pass
        return texts
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_splash_annotations():
    # Backup existing license
    orig = license_manager.load_license()
    try:
        # Personal license
        license_manager.save_license({'type': 'personal', 'email': 'you@example.com'})
        lt = license_manager.license_type()
        title = 'VAICCS'
        if lt == 'commercial':
            title = 'VAICCS (commercial)'
        elif lt == 'personal':
            title = 'VAICCS (personal/evaluation)'
        texts = _make_splash_and_get_texts(title)
        assert any(('personal' in (t or '').lower() or 'evaluation' in (t or '').lower()) for t in texts), f"Personal annotation not found in texts: {texts}"

        # Commercial license
        license_manager.save_license({'type': 'commercial', 'email': 'owner@example.com', 'product_key': 'ABCD-1234-EFGH-5678'})
        lt = license_manager.license_type()
        title = 'VAICCS'
        if lt == 'commercial':
            title = 'VAICCS (commercial)'
        elif lt == 'personal':
            title = 'VAICCS (personal/evaluation)'
        texts = _make_splash_and_get_texts(title)
        assert any(('commercial' in (t or '').lower()) for t in texts), f"Commercial annotation not found in texts: {texts}"

        # No license
        license_manager.clear_license()
        lt = license_manager.license_type()
        title = 'VAICCS'
        if lt == 'commercial':
            title = 'VAICCS (commercial)'
        elif lt == 'personal':
            title = 'VAICCS (personal/evaluation)'
        texts = _make_splash_and_get_texts(title)
        # Should include plain VAICCS and not include personal/commercial
        assert any(('vaiccs' in (t or '').lower()) for t in texts), f"Base title not found in texts: {texts}"
        assert not any(('commercial' in (t or '').lower() or 'personal' in (t or '').lower() or 'evaluation' in (t or '').lower()) for t in texts), f"Unexpected annotation present in texts: {texts}"

    finally:
        # restore original license
        try:
            if orig:
                license_manager.save_license(orig)
            else:
                license_manager.clear_license()
        except Exception:
            pass


if __name__ == '__main__':
    test_splash_annotations()
    print('Splash license tests passed')
