import requests
from bs4 import BeautifulSoup
import re
import os
from urllib.parse import urljoin
import json


def parse_vosk_models():
    url = 'https://alphacephei.com/vosk/models'
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    text = r.text

    soup = BeautifulSoup(text, 'html.parser')
    archive_exts = ('.zip', '.tar.gz', '.tgz', '.tar', '.tar.bz2', '.tar.xz')
    size_re = re.compile(r'(\d+(?:\.\d+)?\s*(?:GB|GiB|MB|MiB|KB|KiB|M|G))', re.IGNORECASE)

    def find_size_near(tag):
        try:
            txt = tag.get_text(' ', strip=True) if hasattr(tag, 'get_text') else str(tag)
            m = size_re.search(txt)
            if m:
                return m.group(1)
        except Exception:
            pass
        try:
            if getattr(tag, 'name', None) == 'tr':
                for cell in tag.find_all(['td', 'th']):
                    try:
                        ct = cell.get_text(' ', strip=True)
                        m = size_re.search(ct)
                        if m:
                            return m.group(1)
                    except Exception:
                        continue
        except Exception:
            pass
        try:
            for sib in list(getattr(tag, 'next_siblings', []))[:6]:
                try:
                    st = sib.get_text(' ', strip=True) if hasattr(sib, 'get_text') else str(sib)
                    m = size_re.search(st)
                    if m:
                        return m.group(1)
                except Exception:
                    continue
            for sib in list(getattr(tag, 'previous_siblings', []))[:6]:
                try:
                    st = sib.get_text(' ', strip=True) if hasattr(sib, 'get_text') else str(sib)
                    m = size_re.search(st)
                    if m:
                        return m.group(1)
                except Exception:
                    continue
        except Exception:
            pass
        try:
            parent = getattr(tag, 'parent', None)
            if parent is not None:
                pt = parent.get_text(' ', strip=True) if hasattr(parent, 'get_text') else str(parent)
                m = size_re.search(pt)
                if m:
                    return m.group(1)
                for sib in list(getattr(parent, 'previous_siblings', []))[:4]:
                    try:
                        st = sib.get_text(' ', strip=True) if hasattr(sib, 'get_text') else str(sib)
                        m = size_re.search(st)
                        if m:
                            return m.group(1)
                    except Exception:
                        continue
                for sib in list(getattr(parent, 'next_siblings', []))[:4]:
                    try:
                        st = sib.get_text(' ', strip=True) if hasattr(sib, 'get_text') else str(sib)
                        m = size_re.search(st)
                        if m:
                            return m.group(1)
                    except Exception:
                        continue
        except Exception:
            pass
        return ''

    def get_size_from_row(tr, anchor):
        try:
            tds = tr.find_all(['td', 'th'])
            if not tds:
                return ''
            ahref = anchor.get('href', '')
            idx = None
            for i, td in enumerate(tds):
                for a_tag in td.find_all('a', href=True):
                    try:
                        if a_tag.get('href','').split('?')[0] == ahref.split('?')[0] or a_tag.get_text(strip=True) == anchor.get_text(strip=True):
                            idx = i
                            break
                    except Exception:
                        continue
                if idx is not None:
                    break
            if idx is None:
                for i, td in enumerate(tds):
                    if td.find('a', href=True):
                        idx = i
                        break
            if idx is None:
                return ''
            for td in tds[idx+1: idx+4]:
                try:
                    txt = td.get_text(' ', strip=True)
                except Exception:
                    txt = ''
                m = size_re.search(txt)
                if m:
                    return m.group(1)
        except Exception:
            pass
        return find_size_near(tr)

    def infer_language_from_name(name: str):
        if not name:
            return None
        lower = name.lower()
        padded = '-' + lower + '-'
        code_map = {
            'en-us': 'English', 'en-in': 'English (India)', 'en': 'English',
            'cn': 'Chinese', 'zh-cn': 'Chinese', 'zh': 'Chinese',
            'ru': 'Russian', 'fr': 'French', 'de': 'German', 'es': 'Spanish',
            'pt': 'Portuguese', 'gr': 'Greek', 'tr': 'Turkish', 'vn': 'Vietnamese',
            'it': 'Italian', 'nl': 'Dutch', 'ca': 'Catalan', 'ar-tn': 'Arabic (Tunisian)', 'ar': 'Arabic',
            'fa': 'Farsi', 'ph': 'Filipino', 'uk': 'Ukrainian', 'kz': 'Kazakh', 'sv': 'Swedish',
            'eo': 'Esperanto', 'hi': 'Hindi', 'cs': 'Czech', 'pl': 'Polish', 'uz': 'Uzbek',
            'br': 'Breton', 'gu': 'Gujarati', 'tg': 'Tajik', 'te': 'Telugu', 'ky': 'Kyrgyz'
        }
        for code in sorted(code_map.keys(), key=lambda x: -len(x)):
            if f'-{code}-' in padded or f'-{code}_' in padded or padded.startswith(f'-{code}-') or padded.endswith(f'-{code}-'):
                return code_map[code]
        return None

    found_map = {}

    heading_tags = soup.find_all(['b', 'h2', 'h3', 'h4'])
    for h in heading_tags:
        lang = h.get_text(strip=True)
        if not lang:
            continue
        ll = lang.lower()
        blacklist = ('model', 'models', 'list', 'punctuation', 'available', 'download')
        if any(b in ll for b in blacklist):
            continue
        node = h.next_sibling
        steps = 0
        while node is not None and steps < 200:
            steps += 1
            if getattr(node, 'name', None) in ('b', 'h2', 'h3', 'h4'):
                break
            if getattr(node, 'name', None) == 'table':
                for tr in node.find_all('tr'):
                    a = tr.find('a', href=True)
                    if not a:
                        continue
                    href = a['href']
                    if not any(ext in href.lower() for ext in archive_exts):
                        continue
                    url = urljoin(r.url, href)
                    name = a.get_text(strip=True) or os.path.basename(href).split('?')[0]
                    size = get_size_from_row(tr, a) or ''
                    disp = name.replace('.zip', '').replace('.tar.gz', '').replace('.tgz', '').replace('.tar', '')
                    name_lang = infer_language_from_name(disp)
                    target_lang = name_lang or lang
                    found_map.setdefault(target_lang, []).append({'name': disp, 'url': url, 'size': size})
            else:
                if hasattr(node, 'find_all'):
                    for a in node.find_all('a', href=True):
                        href = a['href']
                        if not any(ext in href.lower() for ext in archive_exts):
                            continue
                        url = urljoin(r.url, href)
                        name = a.get_text(strip=True) or os.path.basename(href).split('?')[0]
                        size = find_size_near(a) or ''
                        disp = name.replace('.zip', '').replace('.tar.gz', '').replace('.tgz', '').replace('.tar', '')
                        name_lang = infer_language_from_name(disp)
                        target_lang = name_lang or lang
                        found_map.setdefault(target_lang, []).append({'name': disp, 'url': url, 'size': size})
            node = node.next_sibling

    if not found_map:
        grouped = {}
        for a in soup.find_all('a', href=True):
            href = a['href']
            if not any(ext in href.lower() for ext in archive_exts):
                continue
            url = urljoin(r.url, href)
            name = a.get_text(strip=True) or os.path.basename(href).split('?')[0]
            size = find_size_near(a) or ''
            disp = name.replace('.zip', '').replace('.tar.gz', '').replace('.tgz', '').replace('.tar', '')
            name_lang = infer_language_from_name(disp)
            lang = name_lang or 'Other'
            grouped.setdefault(lang, []).append({'name': disp, 'url': url, 'size': size})
        if grouped:
            found_map = grouped

    return found_map


if __name__ == '__main__':
    try:
        res = parse_vosk_models()
        print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print('Error:', e)
