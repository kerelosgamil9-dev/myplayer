# -*- coding: utf-8 -*-
"""
textfix.py - Arabic shaping + a compact Unicode bidi implementation.

Kivy (SDL2_ttf) draws text left-to-right glyph by glyph: it does NOT join Arabic
letters and does NOT reorder right-to-left text. This module converts a *logical*
string (the way it is typed / stored) into a *visual* string that Kivy can draw
as is.  It has no third-party dependencies (everything is derived from the
`unicodedata` tables that ship with Python), so nothing extra has to be built
for Android.

Public API
    fix(text, base=None)          logical -> visual (single line)
    fix_lines(text)               same but for text containing '\n'
    is_rtl(text)                  True if the first strong character is RTL
    fit_text(text, max_w, measure)            ellipsize a single line
    wrap_text(text, max_w, measure, max_lines) word wrap (logical lines)
"""
import unicodedata
from functools import lru_cache

# --------------------------------------------------------------------------
# Arabic letter forms (built once from the Unicode database)
# --------------------------------------------------------------------------
_FORMS = {}   # base char -> {'isolated':c, 'final':c, 'initial':c, 'medial':c}
_LIGS = {}    # alef-variant -> {'isolated':c, 'final':c}   (lam + alef ligatures)


def _build_tables():
    ranges = list(range(0xFB50, 0xFDFC)) + list(range(0xFE70, 0xFEFD))
    for cp in ranges:
        ch = chr(cp)
        dec = unicodedata.decomposition(ch)
        if not dec or not dec.startswith('<'):
            continue
        parts = dec.split()
        tag = parts[0].strip('<>')
        if tag not in ('isolated', 'final', 'initial', 'medial'):
            continue
        try:
            cps = [int(x, 16) for x in parts[1:]]
        except ValueError:
            continue
        if len(cps) == 1:
            base = chr(cps[0])
            # only letters, never marks / spaces
            if unicodedata.category(base) == 'Lo':
                _FORMS.setdefault(base, {})
                # first definition wins (FE70.. range is the standard one for the core
                # letters, FB50.. adds Persian/Urdu/Egyptian letters)
                _FORMS[base].setdefault(tag, ch)
        elif len(cps) == 2 and cps[0] == 0x0644 and tag in ('isolated', 'final'):
            _LIGS.setdefault(chr(cps[1]), {})[tag] = ch


_build_tables()


def _join_type(c):
    """'D' dual joining, 'R' right joining, 'U' non joining."""
    if c == 'ـ':          # tatweel
        return 'D'
    f = _FORMS.get(c)
    if not f:
        return 'U'
    if 'initial' in f and 'medial' in f:
        return 'D'
    if 'final' in f:
        return 'R'
    return 'U'


def _is_arabic_mark(c):
    o = ord(c)
    return 0x0600 <= o <= 0x06FF and unicodedata.category(c) == 'Mn'


def shape(text):
    """Replace Arabic letters with their contextual presentation forms."""
    chars = [c for c in text if not _is_arabic_mark(c)]   # drop harakat
    n = len(chars)
    if n == 0:
        return ''
    types = [_join_type(c) for c in chars]
    out = []
    i = 0
    while i < n:
        c = chars[i]
        prev_joins = i > 0 and types[i - 1] == 'D'
        # lam + alef ligature
        if c == 'ل' and i + 1 < n and chars[i + 1] in _LIGS:
            lig = _LIGS[chars[i + 1]]
            form = 'final' if prev_joins else 'isolated'
            out.append(lig.get(form) or lig.get('isolated'))
            i += 2
            continue
        t = types[i]
        if t == 'U' or c == 'ـ':
            out.append(c)
            i += 1
            continue
        nxt_joins = i + 1 < n and types[i + 1] in ('D', 'R')
        forms = _FORMS[c]
        if t == 'R':
            form = 'final' if prev_joins else 'isolated'
        else:
            if prev_joins and nxt_joins:
                form = 'medial'
            elif prev_joins:
                form = 'final'
            elif nxt_joins:
                form = 'initial'
            else:
                form = 'isolated'
        out.append(forms.get(form) or forms.get('isolated') or c)
        i += 1
    return ''.join(out)


# --------------------------------------------------------------------------
# Bidi (simplified UAX #9 - one line, no explicit embeddings)
# --------------------------------------------------------------------------
_MIRROR = {
    '(': ')', ')': '(', '[': ']', ']': '[', '{': '}', '}': '{',
    '<': '>', '>': '<', '«': '»', '»': '«',
    '‹': '›', '›': '‹',
}
_CONTROLS = set('‎‏‪‫‬‭‮⁦⁧⁨⁩؜')


def _bidi_class(c):
    if c == '‎':
        return 'L'
    if c == '‏':
        return 'R'
    return unicodedata.bidirectional(c)


def _has_rtl(text):
    for c in text:
        if ord(c) >= 0x0590 and unicodedata.bidirectional(c) in ('R', 'AL', 'AN'):
            return True
    return False


def is_rtl(text):
    """True when the first strong character of text is right-to-left."""
    for c in text:
        b = _bidi_class(c)
        if b == 'L':
            return False
        if b in ('R', 'AL'):
            return True
    return False


def bidi(text, base=None):
    """Return the visual (left-to-right drawing order) version of text."""
    if not text:
        return text
    if not _has_rtl(text):
        return ''.join(c for c in text if c not in _CONTROLS)
    n = len(text)
    cls = [_bidi_class(c) for c in text]
    if base is None:
        base = 1 if is_rtl(text) else 0
    e = 1 if base else 0          # embedding level

    t = list(cls)
    # W1 non-spacing marks take the class of the previous character
    for i in range(n):
        if t[i] == 'NSM':
            t[i] = t[i - 1] if i > 0 else ('R' if e else 'L')
    # W2 EN after AL becomes AN ; W3 AL becomes R
    last_strong = None
    for i in range(n):
        if t[i] in ('L', 'R', 'AL'):
            last_strong = t[i]
        elif t[i] == 'EN' and last_strong == 'AL':
            t[i] = 'AN'
    for i in range(n):
        if t[i] == 'AL':
            t[i] = 'R'
    # W4 single separators between numbers
    for i in range(1, n - 1):
        if t[i] == 'ES' and t[i - 1] == 'EN' and t[i + 1] == 'EN':
            t[i] = 'EN'
        elif t[i] == 'CS' and t[i - 1] == t[i + 1] and t[i - 1] in ('EN', 'AN'):
            t[i] = t[i - 1]
    # W5 terminators adjacent to EN become EN
    i = 0
    while i < n:
        if t[i] == 'ET':
            j = i
            while j < n and t[j] == 'ET':
                j += 1
            if (i > 0 and t[i - 1] == 'EN') or (j < n and t[j] == 'EN'):
                for k in range(i, j):
                    t[k] = 'EN'
            i = j
        else:
            i += 1
    # W6 leftovers become neutral
    for i in range(n):
        if t[i] in ('ES', 'ET', 'CS'):
            t[i] = 'ON'
    # W7 EN after strong L becomes L
    last_strong = 'R' if e else 'L'
    for i in range(n):
        if t[i] in ('L', 'R'):
            last_strong = t[i]
        elif t[i] == 'EN' and last_strong == 'L':
            t[i] = 'L'

    # N1/N2 neutrals
    def strong_dir(x):
        if x == 'L':
            return 'L'
        if x in ('R', 'EN', 'AN'):
            return 'R'
        return None

    edir = 'R' if e else 'L'
    i = 0
    while i < n:
        if strong_dir(t[i]) is None:
            j = i
            while j < n and strong_dir(t[j]) is None:
                j += 1
            before = strong_dir(t[i - 1]) if i > 0 else edir
            after = strong_dir(t[j]) if j < n else edir
            res = before if before == after else edir
            for k in range(i, j):
                t[k] = res
            i = j
        else:
            i += 1

    # I1 / I2 levels
    levels = []
    for x in t:
        if e == 0:
            levels.append(0 if x == 'L' else (1 if x == 'R' else 2))
        else:
            levels.append(1 if x == 'R' else 2)

    # L2 reorder
    order = list(range(n))
    maxl = max(levels)
    odd = [l for l in levels if l % 2 == 1]
    if odd:
        minodd = min(odd)
        for lvl in range(maxl, minodd - 1, -1):
            i = 0
            while i < n:
                if levels[order[i]] >= lvl:
                    j = i
                    while j < n and levels[order[j]] >= lvl:
                        j += 1
                    order[i:j] = reversed(order[i:j])
                    i = j
                else:
                    i += 1
    out = []
    for idx in order:
        c = text[idx]
        if c in _CONTROLS:
            continue
        if levels[idx] % 2 == 1 and c in _MIRROR:
            c = _MIRROR[c]
        out.append(c)
    return ''.join(out)


@lru_cache(maxsize=4096)
def _fix_cached(text, base):
    if not text:
        return ''
    # fast path for plain latin text
    if all(ord(c) < 0x0590 for c in text):
        return text
    return bidi(shape(text), base)


def fix(text, base=None):
    """Logical text -> visual text ready for a Kivy label (single line)."""
    if text is None:
        return ''
    return _fix_cached(str(text), base)


def fix_lines(text, base=None):
    return '\n'.join(fix(line, base) for line in str(text).split('\n'))


# --------------------------------------------------------------------------
# Fitting / wrapping (needs a measuring callback: measure(visual_text) -> px)
# --------------------------------------------------------------------------
ELLIPSIS = '…'


def fit_text(text, max_w, measure):
    """Shorten the logical string (adding an ellipsis) so its visual width <= max_w."""
    text = str(text).replace('\n', ' ').strip()
    if not text:
        return ''
    if measure(fix(text)) <= max_w:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        cand = text[:mid].rstrip() + ELLIPSIS
        if measure(fix(cand)) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    if lo <= 0:
        return ELLIPSIS
    return text[:lo].rstrip() + ELLIPSIS


def _longest_prefix(word, max_w, measure):
    lo, hi = 1, len(word)
    best = 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if measure(fix(word[:mid])) <= max_w:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def wrap_text(text, max_w, measure, max_lines=2):
    """Greedy word wrap on the logical string. Returns a list of logical lines;
    the last one is ellipsized when the text does not fit in max_lines."""
    text = ' '.join(str(text).replace('\n', ' ').split())
    if not text:
        return []
    if max_lines <= 1:
        return [fit_text(text, max_w, measure)]
    words = text.split(' ')
    lines = []
    cur = ''
    i = 0
    while i < len(words):
        w = words[i]
        trial = (cur + ' ' + w) if cur else w
        if measure(fix(trial)) <= max_w:
            cur = trial
            i += 1
            continue
        if cur:
            lines.append(cur)
            cur = ''
            if len(lines) == max_lines - 1:
                rest = ' '.join(words[i:])
                lines.append(fit_text(rest, max_w, measure))
                return lines
            continue
        # a single word wider than the line: split it by characters
        k = _longest_prefix(w, max_w, measure)
        if len(lines) == max_lines - 1:
            rest = ' '.join([w] + words[i + 1:])
            lines.append(fit_text(rest, max_w, measure))
            return lines
        lines.append(w[:k])
        words[i] = w[k:]
        if not words[i]:
            i += 1
        if len(lines) == max_lines:
            return lines
    if cur:
        lines.append(cur)
    return lines[:max_lines]
