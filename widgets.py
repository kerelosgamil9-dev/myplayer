# -*- coding: utf-8 -*-
"""
widgets.py - all custom widgets (pure Python, no .kv files):
  Txt, Icon, Tap, IconButton, Thumb, PillSwitch, SeekBar, FieldInput,
  VList (virtualised list with scrolling, long-press selection and drag reordering),
  Overlay / MenuSheet / Dialog / PromptDialog, Toast.
"""
import math
import os
import time
from collections import OrderedDict

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel, LabelBase
from kivy.graphics import (Color, Ellipse, Line, Mesh, PopMatrix, PushMatrix, Rectangle,
                           RoundedRectangle, Translate, Triangle)
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import core
import textfix

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# theme
# ---------------------------------------------------------------------------
BG = (0.031, 0.033, 0.043, 1)
BG_INT = 0xFF000000 | (int(round(BG[0] * 255)) << 16) | (int(round(BG[1] * 255)) << 8) | int(round(BG[2] * 255))
SURFACE = (0.082, 0.087, 0.108, 1)
SURFACE2 = (0.128, 0.134, 0.160, 1)
ACCENT = (1.0, 0.42, 0.37, 1)
ACCENT_SOFT = (1.0, 0.42, 0.37, 0.16)
ON_ACCENT = (0.10, 0.04, 0.04, 1)          # text / icons drawn on top of the accent colour
TEXT = (0.97, 0.97, 0.98, 1)
SUB = (0.62, 0.64, 0.69, 1)
DIVIDER = (1, 1, 1, 0.07)
DANGER = (1.0, 0.36, 0.36, 1)
SCRIM = (0, 0, 0, 0.66)                    # translucent dark chips drawn over the video

AR_FONT = 'ProArabic'
LATIN_FONT = 'Roboto'


def _find_font(*names):
    """First font file that exists (in assets/fonts, or next to this file when the app is flat)."""
    for n in names:
        for d in (os.path.join(HERE, 'assets', 'fonts'), HERE):
            p = os.path.join(d, n)
            if os.path.exists(p):
                return p
    return None


def register_fonts():
    """IBM Plex Sans Arabic (clean, modern; Arabic + Latin in one family); DejaVu if it is missing."""
    global LATIN_FONT
    reg = _find_font('ProArabic-Regular.ttf', 'DejaVuSans.ttf')
    bold = _find_font('ProArabic-SemiBold.ttf', 'DejaVuSans-Bold.ttf') or reg
    if reg is None:
        return
    LabelBase.register(name=AR_FONT, fn_regular=reg, fn_bold=bold)
    if 'ProArabic' in os.path.basename(reg):
        LATIN_FONT = AR_FONT


def font_for(text):
    return AR_FONT if core.has_arabic(text) else LATIN_FONT


# ---------------------------------------------------------------------------
# text measuring
# ---------------------------------------------------------------------------
_core_labels = {}
_measure_cache = {}


def measure(text, font, size, bold=False):
    key = (text, font, round(size, 1), bold)
    w = _measure_cache.get(key)
    if w is not None:
        return w
    lk = (font, round(size, 1), bold)
    lab = _core_labels.get(lk)
    if lab is None:
        lab = CoreLabel(font_name=font, font_size=size, bold=bold)
        _core_labels[lk] = lab
    try:
        w = lab.get_extents(text)[0]
    except Exception:
        w = len(text) * size * 0.6
    if len(_measure_cache) > 20000:
        _measure_cache.clear()
    _measure_cache[key] = w
    return w


_lh_cache = {}


def line_height(font, size, bold=False):
    """Height in pixels of one line of text in this font (the font's own ascent + descent)."""
    key = (font, round(size, 1), bold)
    h = _lh_cache.get(key)
    if h is None:
        try:
            lab = CoreLabel(text='Ag\u0644', font_name=font, font_size=size, bold=bold)
            lab.refresh()
            h = float(lab.texture.height)
        except Exception:
            h = size * 1.4
        _lh_cache[key] = h
    return h


class Txt(Label):
    """Label that takes *logical* text (Arabic / English) and does shaping, bidi,
    ellipsis and wrapping by itself."""
    ltext = StringProperty('')
    nlines = NumericProperty(1)
    keep_nl = BooleanProperty(False)
    align_mode = StringProperty('right')      # right | left | center | auto

    def __init__(self, text='', **kw):
        kw.pop('text', None)
        ltext = kw.pop('ltext', text)
        if 'align_mode' not in kw and kw.get('halign') in ('left', 'center', 'right'):
            kw['align_mode'] = kw['halign']          # an explicit halign must not be overridden later
        kw.setdefault('halign', 'right')
        kw.setdefault('valign', 'middle')
        kw.setdefault('color', TEXT)
        kw.setdefault('font_size', sp(16))
        kw.setdefault('size_hint', (1, 1))
        super(Txt, self).__init__(**kw)
        self._ltext_init = ltext
        self.bind(ltext=self._refresh, size=self._refresh, font_size=self._refresh,
                  bold=self._refresh, nlines=self._refresh, align_mode=self._refresh)
        self.ltext = ltext
        self._refresh()

    def _refresh(self, *a):
        txt = self.ltext or ''
        w = self.width
        if w < 2 or not txt:
            if self.text:
                self.text = ''
            return
        font = font_for(txt)
        if self.font_name != font:
            self.font_name = font
        size, bold = self.font_size, self.bold

        def m(s):
            return measure(s, font, size, bold)
        if self.keep_nl:
            lines = []
            for part in txt.split('\n'):
                lines.extend(textfix.wrap_text(part, w, m, max(1, self.nlines)) or [''])
        else:
            lines = textfix.wrap_text(txt, w, m, max(1, self.nlines))
        base = None
        vis = '\n'.join(textfix.fix(l, base) for l in lines)
        mode = self.align_mode
        if mode == 'auto':
            self.halign = 'right' if textfix.is_rtl(txt) else 'left'
        elif mode in ('right', 'left', 'center'):
            self.halign = mode
        self.text = vis
        self.text_size = (w, self.height)

    def text_height(self, lines=None):
        """Height that `lines` lines (default: as many as the text really needs) of this label take."""
        n = lines if lines is not None else len(self.logical_lines())
        return max(1, n) * line_height(font_for(self.ltext or 'a'), self.font_size, self.bold)

    def logical_lines(self):
        """The lines the text is wrapped into (logical order), at the current width."""
        txt = self.ltext or ''
        if not txt or self.width < 2:
            return [txt]
        font = font_for(txt)
        size, bold = self.font_size, self.bold
        return textfix.wrap_text(txt, self.width, lambda t: measure(t, font, size, bold),
                                 max(1, self.nlines)) or [txt]

    def text_width(self):
        txt = self.ltext or ''
        if not txt:
            return 0
        font = font_for(txt)
        return measure(textfix.fix(txt), font, self.font_size, self.bold)


# ---------------------------------------------------------------------------
# icons (vector, drawn with canvas instructions on a 24x24 grid, y down)
# ---------------------------------------------------------------------------
def _arc(cx, cy, r, a0, a1, n=18):
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / float(n))
        pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _rrect(x0, y0, x1, y1, r, n=5):
    """Closed outline of a rounded rectangle (24 grid, y down)."""
    pts = []
    for (cx, cy, a0) in ((x1 - r, y0 + r, 270), (x1 - r, y1 - r, 0), (x0 + r, y1 - r, 90), (x0 + r, y0 + r, 180)):
        pts.extend(_arc(cx, cy, r, a0, a0 + 90, n))
    pts.append(pts[0])
    return pts


def _arrow_head(cx, cy, r, a, h=4.0):
    import math
    ar = math.radians(a)
    ex, ey = cx + r * math.cos(ar), cy + r * math.sin(ar)
    tx, ty = -math.sin(ar), math.cos(ar)
    nx, ny = math.cos(ar), math.sin(ar)
    return [(ex - tx * h + nx * h * 0.8, ey - ty * h + ny * h * 0.8), (ex, ey),
            (ex - tx * h - nx * h * 0.8, ey - ty * h - ny * h * 0.8)]


def _arrow_fill(cx, cy, r, a, h=3.6):
    """Solid arrow head at angle `a` of a circle, pointing the way the angle grows."""
    ar = math.radians(a)
    ex, ey = cx + r * math.cos(ar), cy + r * math.sin(ar)
    tx, ty = -math.sin(ar), math.cos(ar)
    nx, ny = math.cos(ar), math.sin(ar)
    return ('fill', [(ex + tx * h, ey + ty * h), (ex + nx * h * 0.85, ey + ny * h * 0.85),
                     (ex - nx * h * 0.85, ey - ny * h * 0.85)])


def _mirror(ops):
    """The same icon flipped left <-> right (24 grid)."""
    out = []
    for op in ops:
        k = op[0]
        if k in ('line', 'fill'):
            out.append((k, [(24 - x, y) for (x, y) in op[1]]))
        elif k == 'rect':
            out.append((k, 24 - op[1] - op[3], op[2], op[3], op[4]))
        else:                                   # circle / dot
            out.append((k, 24 - op[1], op[2], op[3]))
    return out


_STEP_FWD = [('line', _arc(12, 13.2, 8.2, 300, 603, 30)), _arrow_fill(12, 13.2, 8.2, 603, 3.5)]

ICONS = {
    'play': [('fill', [(7, 4), (20, 12), (7, 20)])],
    'pause': [('rect', 6, 4, 4, 16), ('rect', 14, 4, 4, 16)],
    'next': [('fill', [(6, 5), (16, 12), (6, 19)]), ('rect', 16.5, 5, 2.5, 14)],
    'prev': [('fill', [(18, 5), (8, 12), (18, 19)]), ('rect', 5, 5, 2.5, 14)],
    'rew': [('fill', [(12, 6), (3, 12), (12, 18)]), ('fill', [(21, 6), (12, 12), (21, 18)])],
    'fwd': [('fill', [(3, 6), (12, 12), (3, 18)]), ('fill', [(12, 6), (21, 12), (12, 18)])],
    'back': [('line', [(4, 12), (20, 12)]), ('line', [(13, 5), (20, 12), (13, 19)])],
    'chev_left': [('line', [(15, 5), (8, 12), (15, 19)])],
    'chev_right': [('line', [(9, 5), (16, 12), (9, 19)])],
    'close': [('line', [(6, 6), (18, 18)]), ('line', [(18, 6), (6, 18)])],
    'plus': [('line', [(12, 5), (12, 19)]), ('line', [(5, 12), (19, 12)])],
    'dots': [('dot', 12, 5, 2), ('dot', 12, 12, 2), ('dot', 12, 19, 2)],
    'check': [('line', [(5, 12.5), (10, 17.5), (19, 7)])],
    'folder_play': [('line', [(3, 6), (10, 6), (12, 8.5), (21, 8.5), (21, 19), (3, 19), (3, 6)]),
                    ('fill', [(10, 11.5), (10, 16.5), (15, 14)])],
    'folder': [('line', [(3, 6), (10, 6), (12, 8.5), (21, 8.5), (21, 19), (3, 19), (3, 6)])],
    'download': [('line', [(12, 4), (12, 15)]), ('line', [(7, 10.5), (12, 15.5), (17, 10.5)]),
                 ('line', [(5, 19.5), (19, 19.5)])],
    'person': [('circle', 12, 8, 4), ('line', [(4.5, 20.5), (5.5, 16.5), (9, 14), (15, 14), (18.5, 16.5), (19.5, 20.5)])],
    'search': [('circle', 10.5, 10.5, 6), ('line', [(15, 15), (20, 20)])],
    'sort': [('line', [(4, 7), (20, 7)]), ('line', [(4, 12), (15, 12)]), ('line', [(4, 17), (10, 17)])],
    'trash': [('line', [(6, 7), (7, 20), (17, 20), (18, 7)]), ('line', [(4, 7), (20, 7)]),
              ('line', [(9, 7), (9, 4), (15, 4), (15, 7)])],
    'edit': [('line', [(4, 20), (5, 15), (16, 4), (20, 8), (9, 19), (4, 20)])],
    'playlist_add': [('line', [(4, 7), (14, 7)]), ('line', [(4, 12), (14, 12)]), ('line', [(4, 17), (10, 17)]),
                     ('line', [(18, 12), (18, 20)]), ('line', [(14, 16), (22, 16)])],
    'playlist': [('line', [(8, 7), (20, 7)]), ('line', [(8, 12), (20, 12)]), ('line', [(8, 17), (20, 17)]),
                 ('dot', 4, 7, 1.3), ('dot', 4, 12, 1.3), ('dot', 4, 17, 1.3)],
    'select_all': [('line', [(4, 7), (4, 20), (17, 20)]), ('line', [(8, 4), (20, 4), (20, 16), (8, 16), (8, 4)]),
                   ('line', [(11, 10), (13.5, 12.5), (17, 8)])],
    'rotate': [('line', _arc(12, 12, 7.5, 40, 330)), _arrow_fill(12, 12, 7.5, 330, 4.2)],
    'lock': [('line', _rrect(5, 10.5, 19, 20.5, 2.6)),
             ('line', [(8.2, 10.5), (8.2, 7.8)] + _arc(12, 7.8, 3.8, 180, 360, 12) + [(15.8, 7.8), (15.8, 10.5)]),
             ('dot', 12, 15.0, 1.45), ('line', [(12, 15.4), (12, 17.6)])],
    'unlock': [('line', _rrect(5, 10.5, 19, 20.5, 2.6)),
               ('line', [(8.2, 10.5), (8.2, 6.6)] + _arc(12, 6.6, 3.8, 180, 360, 12) + [(15.8, 6.6), (15.8, 8.0)]),
               ('dot', 12, 15.0, 1.45), ('line', [(12, 15.4), (12, 17.6)])],
    'speed': [('line', _arc(12, 15, 9, 190, 350, 22)), ('line', [(12, 15), (16.5, 10)]), ('dot', 12, 15, 1.6)],
    'subtitle': [('line', _rrect(3, 5, 21, 19, 3.2)),
                 ('line', _arc(9.0, 12, 2.6, 42, 318, 12)), ('line', _arc(15.4, 12, 2.6, 42, 318, 12))],
    'audio': [('dot', 8, 18, 3), ('line', [(11, 18), (11, 5), (19, 7.5)])],
    'brightness': [('circle', 12, 12, 4)] + [('line', [(12 + 7 * math.cos(math.radians(a)), 12 + 7 * math.sin(math.radians(a))),
                                                       (12 + 10 * math.cos(math.radians(a)), 12 + 10 * math.sin(math.radians(a)))])
                                              for a in range(0, 360, 45)],
    'volume': [('fill', [(4, 9), (8, 9), (13, 5), (13, 19), (8, 15), (4, 15)]),
               ('line', _arc(14, 12, 4, -50, 50)), ('line', _arc(14, 12, 8, -50, 50))],
    'repeat': [('line', [(4, 11), (4, 7), (18, 7)]), ('line', [(15, 4), (18, 7), (15, 10)]),
               ('line', [(20, 13), (20, 17), (6, 17)]), ('line', [(9, 14), (6, 17), (9, 20)])],
    'repeat_one': [('line', [(4, 11), (4, 7), (18, 7)]), ('line', [(15, 4), (18, 7), (15, 10)]),
                   ('line', [(20, 13), (20, 17), (6, 17)]), ('line', [(9, 14), (6, 17), (9, 20)]),
                   ('line', [(11, 10.5), (12.5, 9.5), (12.5, 14.5)])],
    'shuffle': [('line', [(3, 7), (8, 7), (15, 17), (20, 17)]), ('line', [(3, 17), (8, 17), (15, 7), (20, 7)]),
                ('line', [(17, 4), (20, 7), (17, 10)]), ('line', [(17, 14), (20, 17), (17, 20)])],
    'drag': [('line', [(5, 7.5), (19, 7.5)]), ('line', [(5, 12), (19, 12)]), ('line', [(5, 16.5), (19, 16.5)])],
    'clock': [('circle', 12, 12, 9), ('line', [(12, 7), (12, 12), (16, 14)])],
    'tune': [('line', [(4, 8), (20, 8)]), ('line', [(4, 16), (20, 16)]), ('dot', 9, 8, 2.6), ('dot', 15, 16, 2.6)],
    'move_top': [('line', [(5, 5), (19, 5)]), ('line', [(12, 20), (12, 9)]), ('line', [(7, 13), (12, 8), (17, 13)])],
    'move_bottom': [('line', [(5, 19), (19, 19)]), ('line', [(12, 4), (12, 15)]), ('line', [(7, 11), (12, 16), (17, 11)])],
    'info': [('circle', 12, 12, 9), ('line', [(12, 11), (12, 17)]), ('dot', 12, 7.5, 1.3)],
    'restore': _mirror([('line', _arc(12, 12, 8, 40, 330)), _arrow_fill(12, 12, 8, 330, 4.2)]) +
               [('line', [(12, 8), (12, 12), (14.8, 13.8)])],
    'up': [('line', [(6, 15), (12, 9), (18, 15)])],
    'arrow_up': [('line', [(12, 19), (12, 5)]), ('line', [(6, 11), (12, 5), (18, 11)])],
    'arrow_down': [('line', [(12, 5), (12, 19)]), ('line', [(6, 13), (12, 19), (18, 13)])],
    'down': [('line', [(6, 9), (12, 15), (18, 9)])],
    'step_fwd': _STEP_FWD,
    'step_back': _mirror(_STEP_FWD),
    'volume_mute': [('fill', [(4, 9), (8, 9), (13, 5), (13, 19), (8, 15), (4, 15)]),
                    ('line', [(16, 9.5), (21, 14.5)]), ('line', [(21, 9.5), (16, 14.5)])],
    'bolt': [('fill', [(13, 3), (6, 13), (11, 13), (10, 21), (18, 10), (13, 10)])],
    'share': [('circle', 18, 5.5, 2.7), ('circle', 6, 12, 2.7), ('circle', 18, 18.5, 2.7),
              ('line', [(8.4, 10.7), (15.6, 6.8)]), ('line', [(8.4, 13.3), (15.6, 17.2)])],
    # a phone with a turning arrow on each side: rotate the screen
    'screen_rotate': [('line', _rrect(4.5, 9.5, 16.5, 19.5, 2.2)),
                      ('line', _arc(11.5, 12.5, 9.5, 232, 330, 10)), ('line', _arrow_head(11.5, 12.5, 9.5, 330, 3.3))],
}


_ATLAS = {'tried': False, 'tex': None, 'mod': None, 'regions': {}}


def _icon_region(name):
    """Texture region of the named icon in ui_icons.png (professionally drawn Phosphor / Material icons),
    or None when the atlas is missing, so that the vector drawings below still work."""
    A = _ATLAS
    if not A['tried']:
        A['tried'] = True
        try:
            import iconatlas
            for d in (os.path.join(HERE, 'assets', 'icons'), HERE):
                p = os.path.join(d, 'ui_icons.png')
                if os.path.exists(p):
                    tex = CoreImage(p, mipmap=True).texture
                    if tex is not None and tex.width == iconatlas.SIZE:
                        try:
                            tex.min_filter = 'linear_mipmap_linear'
                            tex.mag_filter = 'linear'
                        except Exception:
                            pass
                        A['tex'], A['mod'] = tex, iconatlas
                        break
        except Exception:
            A['tex'] = None
    if A['tex'] is None:
        return None
    reg = A['regions'].get(name)
    if reg is None:
        mod = A['mod']
        if name not in mod.ATLAS:
            return None
        col, row = mod.ATLAS[name]
        try:
            reg = A['tex'].get_region(col * mod.CELL, mod.SIZE - (row + 1) * mod.CELL, mod.CELL, mod.CELL)
        except Exception:
            return None
        A['regions'][name] = reg
    return reg


class Icon(Widget):
    name = StringProperty('play')
    color = ListProperty([1, 1, 1, 1])
    stroke = NumericProperty(1.5)       # in 24-grid units

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(24), dp(24)))
        super(Icon, self).__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, name=self._draw, color=self._draw)
        self._draw()

    def _draw(self, *a):
        self.canvas.clear()
        if self.width < 2:
            return
        reg = _icon_region(self.name)
        if reg is not None:
            d = min(self.width, self.height) * 0.9          # the drawings fill their whole square
            with self.canvas:
                Color(*self.color)
                Rectangle(texture=reg, pos=(self.x + (self.width - d) / 2.0, self.y + (self.height - d) / 2.0),
                          size=(d, d))
            return
        ops = ICONS.get(self.name)
        if not ops:
            return
        u = min(self.width, self.height) / 24.0
        ox = (self.x + self.width / 2.0) - 12 * u
        oy = (self.y + self.height / 2.0) - 12 * u

        def P(x, y):
            return ox + x * u, oy + (24 - y) * u
        lw = max(1.2, self.stroke * 0.82 * u)
        with self.canvas:
            Color(*self.color)
            for op in ops:
                k = op[0]
                if k == 'line':
                    pts = []
                    for (x, y) in op[1]:
                        pts.extend(P(x, y))
                    Line(points=pts, width=lw, cap='round', joint='round')
                elif k == 'fill':
                    verts = []
                    for (x, y) in op[1]:
                        px, py = P(x, y)
                        verts.extend([px, py, 0, 0])
                    Mesh(vertices=verts, indices=list(range(len(op[1]))), mode='triangle_fan')
                elif k == 'rect':
                    _, x, y, w, h = op
                    px, py = P(x, y + h)
                    Rectangle(pos=(px, py), size=(w * u, h * u))
                elif k == 'circle':
                    _, cx, cy, r = op
                    px, py = P(cx, cy)
                    Line(circle=(px, py, r * u), width=lw)
                elif k == 'dot':
                    _, cx, cy, r = op
                    px, py = P(cx, cy)
                    Ellipse(pos=(px - r * u, py - r * u), size=(2 * r * u, 2 * r * u))


# ---------------------------------------------------------------------------
# tap targets
# ---------------------------------------------------------------------------
TAP_SLOP = dp(12)           # a finger that travels further than this between down and up did not tap


class Tap(Widget):
    """Plain touch target with press feedback; callback(widget) on release."""

    def __init__(self, callback=None, **kw):
        kw.setdefault('size_hint', (1, None))
        if 'size' not in kw:
            kw.setdefault('height', dp(52))
        super(Tap, self).__init__(**kw)
        self.callback = callback
        self.pressed = False
        self.long_callback = None
        self._long_ev = None
        self._long_fired = False
        self._fb = None
        self.fb_radius = None              # corner radii of the press highlight (cards)
        self.bind(pos=self._fb_upd, size=self._fb_upd)

    def _fb_upd(self, *a):
        if self._fb is not None:
            self._fb.pos = self.pos
            self._fb.size = self.size

    def _set_pressed(self, v):
        self.pressed = v
        self.canvas.after.clear()
        self._fb = None
        if v:
            with self.canvas.after:
                Color(1, 1, 1, 0.09)
                if self.fb_radius:
                    self._fb = RoundedRectangle(pos=self.pos, size=self.size, radius=self.fb_radius)
                else:
                    self._fb = Rectangle(pos=self.pos, size=self.size)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        self._long_fired = False
        self._down = (touch.x, touch.y)
        self._set_pressed(True)
        if self.long_callback:
            self._long_ev = Clock.schedule_once(self._long, 0.45)
        return True

    def tap_now(self):
        """A tap decided by a scroll container (it tracked the finger itself): flash, then call back."""
        if self.disabled:
            return
        self._set_pressed(True)
        Clock.schedule_once(self._unflash, 0.09)
        if self.callback:
            self.callback(self)

    def _unflash(self, dt):
        self._set_pressed(False)

    def _long(self, dt):
        self._long_ev = None
        if self.pressed:
            self._long_fired = True
            self._set_pressed(False)
            self.long_callback(self)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            d = getattr(self, '_down', None)
            slipped = d is not None and (abs(touch.x - d[0]) > TAP_SLOP or abs(touch.y - d[1]) > TAP_SLOP)
            if self.pressed and (slipped or not self.collide_point(*touch.pos)):   # a drag is not a tap
                self._set_pressed(False)
                if self._long_ev:
                    self._long_ev.cancel()
                    self._long_ev = None
            return True
        return False

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self._long_ev:
                self._long_ev.cancel()
                self._long_ev = None
            was = self.pressed
            self._set_pressed(False)
            if was and not self._long_fired and self.callback:
                self.callback(self)
            return True
        return False


class IconButton(Tap):
    def __init__(self, icon='play', callback=None, color=None, icon_size=None, bg=None, bg_d=None, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(48), dp(48)))
        super(IconButton, self).__init__(callback=callback, **kw)
        self.bg = bg
        self.bg_d = bg_d                      # disc diameter (default: the whole button)
        self.bind(pos=self._draw_bg, size=self._draw_bg)
        isz = icon_size or dp(24)
        self.icon = Icon(name=icon, size=(isz, isz), color=list(color or TEXT))
        self.add_widget(self.icon)
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _draw_bg(self, *a):
        self.canvas.before.clear()
        if self.bg:
            d = self.bg_d or min(self.width, self.height)
            with self.canvas.before:
                Color(*self.bg)
                Ellipse(pos=(self.x + (self.width - d) / 2.0, self.y + (self.height - d) / 2.0), size=(d, d))

    def _sync(self, *a):
        self.icon.center = (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def set_icon(self, name):
        self.icon.name = name

    def set_color(self, c):
        self.icon.color = list(c)

    def _set_pressed(self, v):
        self.pressed = v
        self.icon.opacity = 0.55 if v else 1.0

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return False
        return Tap.on_touch_down(self, touch)


class PillSwitch(Tap):
    value = BooleanProperty(False)
    k = NumericProperty(0.0)                     # 0 = off ... 1 = on (animated)

    def __init__(self, value=False, on_change=None, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(46), dp(28)))
        super(PillSwitch, self).__init__(callback=self._toggle, **kw)
        self.on_change = on_change
        self.value = value
        self.k = 1.0 if value else 0.0
        self.bind(pos=self._draw, size=self._draw, k=self._draw)
        self.bind(value=self._slide)
        self._draw()

    def _slide(self, inst, v):
        Animation.cancel_all(self, 'k')
        if self.get_root_window() is None:
            self.k = 1.0 if v else 0.0
            return
        Animation(k=1.0 if v else 0.0, d=0.14, transition='out_quad').start(self)

    def _toggle(self, *a):
        self.value = not self.value
        if self.on_change:
            self.on_change(self.value)

    def _set_pressed(self, v):
        self.pressed = v

    def _draw(self, *a):
        self.canvas.clear()
        h = self.height
        k = max(0.0, min(1.0, self.k))
        with self.canvas:
            off = (0.19, 0.20, 0.235)                                # quiet grey track
            Color(off[0] + (ACCENT[0] - off[0]) * k, off[1] + (ACCENT[1] - off[1]) * k,
                  off[2] + (ACCENT[2] - off[2]) * k, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[h / 2.0])
            r = h * (0.28 + 0.08 * k)
            pad = h / 2.0
            cx = (self.x + pad) + ((self.x + self.width - pad) - (self.x + pad)) * k
            cy = self.y + self.height / 2.0
            if k > 0.05:
                Color(0, 0, 0, 0.18 * k)                              # soft shadow under the knob
                Ellipse(pos=(cx - r, cy - r - dp(1)), size=(2 * r, 2 * r))
            Color(0.72 + 0.28 * k, 0.74 + 0.26 * k, 0.79 + 0.21 * k, 1)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))


class Chip(Tap):
    def __init__(self, label, selected=False, callback=None, **kw):
        kw.setdefault('height', dp(40))
        super(Chip, self).__init__(callback=callback, **kw)
        self.selected = selected
        self.label = Txt(ltext=label, halign='center', font_size=sp(15), bold=selected,
                         color=ON_ACCENT if selected else TEXT, size_hint=(None, None))
        self.add_widget(self.label)
        self.bind(pos=self._draw, size=self._draw)
        self._draw()

    def _draw(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*(ACCENT if self.selected else SURFACE2))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.height / 2.0])
        self.label.pos = self.pos
        self.label.size = self.size


# ---------------------------------------------------------------------------
# thumbnails
# ---------------------------------------------------------------------------
_tex_cache = OrderedDict()
_loader_state = {'broken': False}


def _remember(path, tex):
    _tex_cache[path] = tex
    _tex_cache.move_to_end(path)
    while len(_tex_cache) > 90:
        _tex_cache.popitem(last=False)


def load_texture(path):
    """Decode a picture right now (blocks for a few ms)."""
    tex = _tex_cache.get(path)
    if tex is not None:
        _tex_cache.move_to_end(path)
        return tex
    try:
        tex = CoreImage(path, nocache=True).texture
    except Exception:
        return None
    _remember(path, tex)
    return tex


def _is_error_image(proxy):
    try:
        from kivy.loader import Loader
        return getattr(proxy, 'image', None) is Loader.error_image
    except Exception:
        return False


def load_texture_async(path, done):
    """done(texture or None) is called on the main thread: at once when the picture is already
    cached, otherwise after Kivy's loader decoded it on a worker thread (so scrolling never waits
    for a JPEG).  Falls back to decoding right now if the loader is unusable."""
    tex = _tex_cache.get(path)
    if tex is not None:
        _tex_cache.move_to_end(path)
        done(tex)
        return
    if not _loader_state['broken']:
        try:
            from kivy.loader import Loader
            proxy = Loader.image(path, nocache=True)

            def on_load(p, path=path):
                tex = None
                if not _is_error_image(p):
                    try:
                        tex = p.texture
                    except Exception:
                        tex = None
                if tex is not None:
                    _remember(path, tex)
                done(tex)
            if proxy.loaded:
                on_load(proxy)
            else:
                proxy.bind(on_load=on_load)
            return
        except Exception:
            _loader_state['broken'] = True
    done(load_texture(path))


class Thumb(Widget):
    """Rounded, centre-cropped picture with a dark placeholder."""

    def __init__(self, radius=None, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Thumb, self).__init__(**kw)
        self.radius = radius if radius is not None else dp(12)
        self.source = None
        self._tex = None
        self._req = 0
        self._ev = None
        self.bind(pos=self._draw, size=self._draw)

    def set_source(self, path):
        if path == self.source:
            return
        self.source = path
        self._req += 1
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        if not path:
            self._tex = None
        else:
            tex = _tex_cache.get(path)
            if tex is not None:
                _tex_cache.move_to_end(path)
                self._tex = tex
            else:
                self._tex = None
                # a row that is scrolling past changes its picture every few frames: wait a
                # moment so that only pictures which stay on screen get decoded
                req = self._req
                self._ev = Clock.schedule_once(lambda dt, p=path, r=req: self._start_load(p, r), 0.04)
        self._draw()

    def _start_load(self, path, req):
        self._ev = None
        if req != self._req:
            return

        def done(tex, req=req):
            if req == self._req and tex is not None:
                self._tex = tex
                self._draw()
        load_texture_async(path, done)

    def _draw(self, *a):
        self.canvas.clear()
        if self.width < 2:
            return
        with self.canvas:
            tex = self._tex
            if tex is None:
                # no picture (yet): a calm panel with a play mark instead of a black hole
                Color(0.105, 0.11, 0.14, 1)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
                m = min(self.width, self.height) * 0.15
                cx, cy = self.x + self.width / 2.0, self.y + self.height / 2.0
                Color(1, 1, 1, 0.13)
                Triangle(points=[cx - m * 0.8, cy - m, cx - m * 0.8, cy + m, cx + m * 1.1, cy])
            else:
                Color(0.02, 0.02, 0.025, 1)
                RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
            if tex is not None:
                tw, th = tex.size
                if tw > 0 and th > 0:
                    # "contain": the whole picture, black bars at the sides for tall videos
                    k = min(self.width / float(tw), self.height / float(th))
                    dw, dh = tw * k, th * k
                    Color(1, 1, 1, 1)
                    if dw >= self.width - 1 and dh >= self.height - 1:
                        RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius], texture=tex)
                    else:
                        Rectangle(pos=(self.x + (self.width - dw) / 2.0, self.y + (self.height - dh) / 2.0),
                                  size=(dw, dh), texture=tex)


# ---------------------------------------------------------------------------
# seek bar
# ---------------------------------------------------------------------------
class SeekBar(Widget):
    value = NumericProperty(0.0)       # 0..1

    def __init__(self, on_start=None, on_move=None, on_end=None, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(36))
        super(SeekBar, self).__init__(**kw)
        self.on_start, self.on_move, self.on_end = on_start, on_move, on_end
        self.dragging = False
        self.bind(pos=self._draw, size=self._draw, value=self._draw)
        self._draw()

    def thumb_x(self):
        pad = dp(10)
        return self.x + pad + max(1.0, self.width - 2 * pad) * max(0.0, min(1.0, self.value))

    def _frac(self, x):
        pad = dp(10)
        w = max(1.0, self.width - 2 * pad)
        return max(0.0, min(1.0, (x - self.x - pad) / w))

    def _draw(self, *a):
        self.canvas.clear()
        pad = dp(10)
        w = max(1.0, self.width - 2 * pad)
        th = dp(4) if not self.dragging else dp(6)
        cy = self.y + self.height / 2.0
        y = cy - th / 2.0
        v = max(0.0, min(1.0, self.value))
        with self.canvas:
            Color(1, 1, 1, 0.24)
            RoundedRectangle(pos=(self.x + pad, y), size=(w, th), radius=[th / 2.0])
            Color(*ACCENT)
            RoundedRectangle(pos=(self.x + pad, y), size=(max(th, w * v), th), radius=[th / 2.0])
            kx = self.x + pad + w * v
            if self.dragging:
                Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.28)           # halo while the finger is down
                Ellipse(pos=(kx - dp(15), cy - dp(15)), size=(dp(30), dp(30)))
            r = dp(7.5) if not self.dragging else dp(10)
            Color(0, 0, 0, 0.25)
            Ellipse(pos=(kx - r, cy - r - dp(1)), size=(2 * r, 2 * r))
            Color(1, 1, 1, 1)
            Ellipse(pos=(kx - r, cy - r), size=(2 * r, 2 * r))

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        self.dragging = True
        self.value = self._frac(touch.x)
        if self.on_start:
            self.on_start(self.value)
        self._draw()
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            self.value = self._frac(touch.x)
            if self.on_move:
                self.on_move(self.value)
            return True
        return False

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            self.dragging = False
            self.value = self._frac(touch.x)
            self._draw()
            if self.on_end:
                self.on_end(self.value)
            return True
        return False


# ---------------------------------------------------------------------------
# text field that shows correctly shaped Arabic
# ---------------------------------------------------------------------------
class FieldInput(FloatLayout):
    """A TextInput (invisible, only used to get keyboard input) plus our own
    renderer, because Kivy's TextInput cannot shape / reorder Arabic."""

    def __init__(self, text='', hint='', on_submit=None, max_len=80, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(52))
        super(FieldInput, self).__init__(**kw)
        self.hint = hint
        self.on_submit = on_submit
        self.max_len = max_len
        self._caret_on = True
        with self.canvas.before:
            Color(*SURFACE2)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.ti = TextInput(text=text, multiline=False, write_tab=False,
                            background_normal='', background_active='', background_color=(0, 0, 0, 0),
                            foreground_color=(0, 0, 0, 0), cursor_color=(0, 0, 0, 0),
                            selection_color=(0, 0, 0, 0), hint_text='', size_hint=(1, 1))
        for attr, val in (('use_bubble', False), ('use_handles', False), ('keyboard_suggestions', False)):
            try:
                setattr(self.ti, attr, val)
            except Exception:
                pass
        self.on_resize = None                         # called when the field grows (long text wraps)
        self.shown = Txt(ltext=text or hint, color=TEXT if text else SUB, font_size=sp(17),
                         align_mode='auto', nlines=4, size_hint=(None, None))
        self.add_widget(self.shown)
        self.add_widget(self.ti)
        self.ti.bind(text=self._on_text, on_text_validate=self._validate, focus=self._on_focus)
        self.bind(pos=self._layout, size=self._layout)
        self._blink = Clock.schedule_interval(self._blink_tick, 0.5)
        self._layout()
        self._draw_caret()

    @property
    def text(self):
        return self.ti.text

    def focus(self):
        self.ti.focus = True

    def release(self):
        try:
            self._blink.cancel()
        except Exception:
            pass
        self.ti.focus = False

    def _on_focus(self, inst, val):
        self._draw_caret()

    def _validate(self, *a):
        if self.on_submit:
            self.on_submit(self.ti.text)

    def _on_text(self, inst, value):
        if len(value) > self.max_len:
            inst.text = value[:self.max_len]
            return
        self.shown.ltext = value or self.hint
        self.shown.color = TEXT if value else SUB
        self._fit()
        self._draw_caret()

    LINE_H = sp(17) * 1.3

    def _fit(self):
        """A long text wraps onto up to 4 lines and the field grows, so what is typed is always seen."""
        n = 1
        if self.ti.text and self.shown.width > 2:
            n = max(1, len(self.shown.logical_lines()))
        h = max(dp(52), n * self.LINE_H + dp(22))
        if abs(h - self.height) > 0.5:
            self.height = h
            if self.on_resize:
                self.on_resize()

    def _layout(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size
        pad = dp(16)
        self.shown.pos = (self.x + pad, self.y)
        self.shown.size = (self.width - 2 * pad, self.height)
        self.ti.pos = self.pos
        self.ti.size = self.size
        self._fit()
        self._draw_caret()

    def _blink_tick(self, dt):
        self._caret_on = not self._caret_on
        self._draw_caret()

    def _draw_caret(self):
        self.canvas.after.clear()
        if not self.ti.focus:
            return
        with self.canvas.after:                       # accent outline while typing
            Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.85)
            Line(rounded_rectangle=(self.x + dp(0.8), self.y + dp(0.8), self.width - dp(1.6),
                                    self.height - dp(1.6), dp(14)), width=dp(1.3))
        if not self._caret_on:
            return
        txt = self.ti.text
        pad = dp(16)
        lines = self.shown.logical_lines() if txt else ['']
        last = lines[-1] if lines else ''
        w = measure(textfix.fix(last), font_for(last), self.shown.font_size, False) if last else 0
        rtl = textfix.is_rtl(txt) if txt else True
        if rtl:
            x = (self.x + self.width) - pad - w - dp(2)
        else:
            x = self.x + pad + w + dp(1)
        # the text block is centred vertically; the caret sits on its last line
        cy = self.y + self.height / 2.0 - (len(lines) - 1) * self.LINE_H / 2.0
        with self.canvas.after:
            Color(*ACCENT)
            Rectangle(pos=(x, cy - dp(11)), size=(dp(2), dp(22)))


# ---------------------------------------------------------------------------
# virtualised list with selection + drag reordering
# ---------------------------------------------------------------------------
class Row(Widget):
    """Base class for list rows. Subclasses implement fill() and relayout().

    A row is laid out at y = 0 (inside its Carrier); the list moves it with a Translate, so a
    row never has to re-layout its children just because it moved."""
    kind = 'row'

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Row, self).__init__(**kw)
        self.idx = -1
        self.item = None
        self.ctx = None
        self._quiet = False
        self._sig = None
        self.bind(pos=self._on_geom, size=self._on_geom)

    def _on_geom(self, *a):
        if not self._quiet:
            self.relayout()

    def place(self, x, y, w, h):
        """Set position and size with one layout at most (the caller lays the row out when this
        returns True)."""
        if (self.x, self.y, self.width, self.height) == (x, y, w, h):
            return False
        self._quiet = True
        try:
            self.size = (w, h)
            self.pos = (x, y)
        finally:
            self._quiet = False
        return True

    def unchanged(self, *parts):
        """True when everything the layout depends on equals what the previous layout used - the
        drawing would come out the same, so the caller can skip it."""
        sig = (self.x, self.y, self.width, self.height) + parts
        if sig == self._sig:
            return True
        self._sig = sig
        return False

    def bind_item(self, item, idx, ctx):
        self.item, self.idx, self.ctx = item, idx, ctx
        self.fill(item, idx, ctx)
        self.relayout()

    def fill(self, item, idx, ctx):
        pass

    def relayout(self):
        pass

    def hit_handle(self, x):
        return False


class Carrier(Widget):
    """Holds one row.  Its Translate puts the row at its place in the list, so moving a row
    (scrolling, drag and drop) is a single property write."""

    def __init__(self, row, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (0, 0))
        super(Carrier, self).__init__(**kw)
        with self.canvas.before:
            PushMatrix()
            self._tr = Translate(0, 0)
        with self.canvas.after:
            PopMatrix()
        self.row = row
        row._car = self
        self.add_widget(row)
        self.vy = 0.0              # where the row belongs: the target of the drag animation

    def at(self):
        return self._tr.y

    def put(self, y):
        if self._tr.y != y:
            self._tr.y = y


class VList(StencilView):
    """Fixed-row-height virtualised list.

    Scrolling moves ONE Translate (``_shift``) that carries every row; each row sits in a Carrier
    whose own Translate holds its place in the list.  Nothing inside a row is laid out again while
    the list scrolls, which is what keeps it smooth.  All translations are whole pixels so text
    stays sharp.

    owner callbacks (all optional)
        on_tap(idx, item, x)         short tap
        on_long(idx, item)           long press (selection starts here)
        on_reorder(src, dst)         drag finished
        can_drag(idx, item) -> bool
    """

    def __init__(self, row_factories, row_h=None, **kw):
        super(VList, self).__init__(**kw)
        self.factories = row_factories
        self.row_h = float(max(1, int(round(row_h or dp(96)))))      # whole pixels
        self.bottom_pad = 0.0            # free space after the last row (under a floating button)
        self.items = []
        self.ctx = None
        self.scroll = 0.0
        self.rows = {}
        self.pools = {}
        self.on_tap = None
        self.on_long = None
        self.on_reorder = None
        self.can_drag = None
        self.reorderable = False
        self._t = None
        self._fling = None
        self._fling_v = 0.0
        self._long_ev = None
        self._drag = None          # dict while dragging
        self._drag_ev = None
        self._geo = None
        self._holder = Widget(size_hint=(None, None), size=(0, 0))
        with self._holder.canvas.before:
            PushMatrix()
            self._shift = Translate(0, 0)
        with self._holder.canvas.after:
            PopMatrix()
        self.add_widget(self._holder)
        self.bind(pos=self.relayout, size=self.relayout)

    # ---- data ----------------------------------------------------------
    def set_items(self, items, keep_scroll=True):
        self.items = list(items)
        if not keep_scroll:
            self.scroll = 0.0
        self._release_all()
        self.relayout()

    def refresh(self):
        for i, row in self.rows.items():
            if 0 <= i < len(self.items):
                row.bind_item(self.items[i], i, self.ctx)
        self.relayout()

    def _recycle(self, i):
        row = self.rows.pop(i)
        self._holder.remove_widget(row._car)
        self.pools.setdefault(row.kind, []).append(row)

    def _release_all(self):
        for i in list(self.rows):
            self._recycle(i)

    def max_scroll(self):
        return max(0.0, len(self.items) * self.row_h + self.bottom_pad - self.height)

    def scroll_to(self, idx):
        self.scroll = max(0.0, min(self.max_scroll(), idx * self.row_h))
        self.relayout()

    def screen_y(self, i):
        """Bottom edge of row ``i`` in window coordinates (None when it is not on screen)."""
        row = self.rows.get(i)
        if row is None:
            return None
        return row._car.at() + self._shift.y

    # ---- layout ----------------------------------------------------------
    def _slot_of(self, i):
        d = self._drag
        if not d or i == d['from']:
            return i
        f, t = d['from'], d['to']
        if f < t and f < i <= t:
            return i - 1
        if f > t and t <= i < f:
            return i + 1
        return i

    def _acquire(self, i, vy):
        item = self.items[i]
        kind = item.get('kind', 'row') if isinstance(item, dict) else 'row'
        pool = self.pools.setdefault(kind, [])
        if pool:
            row = pool.pop()
        else:
            row = self.factories[kind]()
            Carrier(row)
        row.kind = kind
        row.place(self.x, 0.0, self.width, self.row_h)
        car = row._car
        car.vy = vy
        car.put(vy)
        row.bind_item(item, i, self.ctx)          # one layout, at the final geometry
        self._holder.add_widget(car)
        self.rows[i] = row
        return row

    def relayout(self, *a):
        if self.height <= 1:
            return
        n = len(self.items)
        rh = self.row_h
        self.scroll = max(0.0, min(self.scroll, self.max_scroll()))
        shift = float(round(self.scroll))
        base = float(round(self.y + self.height))
        geo = (self.x, self.width, rh, base)
        moved = geo != self._geo
        self._geo = geo
        first = max(0, int(self.scroll // rh) - 1)
        last = min(n - 1, int((self.scroll + self.height) // rh) + 1)
        wanted = set(range(first, last + 1))
        d = self._drag
        if d:
            wanted.add(d['from'])
        for i in list(self.rows):
            if i not in wanted:
                self._recycle(i)
        if self._shift.y != shift:
            self._shift.y = shift
        for i in wanted:
            vy = base - (self._slot_of(i) + 1) * rh
            row = self.rows.get(i)
            if row is None:
                self._acquire(i, vy)
                continue
            car = row._car
            car.vy = vy
            if moved and row.place(self.x, 0.0, self.width, rh):
                row.relayout()
            if d and i == d['from']:
                car.put(round(d['y']) - shift)
            elif d:
                # smooth movement is handled by _drag_tick; only far jumps are instant
                if abs(car.at() - vy) > rh * 3:
                    car.put(vy)
            else:
                car.put(vy)

    # ---- touch -------------------------------------------------------------
    def index_at(self, y):
        i = int((self.scroll + ((self.y + self.height) - y)) // self.row_h)
        return i if 0 <= i < len(self.items) else None

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        btn = getattr(touch, 'button', None)
        if btn in ('scrollup', 'scrolldown'):
            self.scroll += (-1 if btn == 'scrollup' else 1) * self.row_h * 1.2
            self.relayout()
            return True
        if self._t is not None:          # stale state from a lost touch
            self._cancel_long()
            if self._drag:
                self._end_drag()
            self._t = None
        self._stop_fling()
        touch.grab(self)
        idx = self.index_at(touch.y)
        state = 'pending'
        if idx is not None and self.reorderable and self.ctx is not None and getattr(self.ctx, 'sel_mode', False):
            row = self.rows.get(idx)
            if row is not None and row.hit_handle(touch.x) and self._can_drag(idx):
                state = 'handle'
        self._t = {'uid': touch.uid, 'idx': idx, 'state': state, 'sx': touch.x, 'sy': touch.y,
                   'last_y': touch.y, 'samples': [(time.time(), touch.y)]}
        if idx is not None and state == 'pending':
            self._long_ev = Clock.schedule_once(self._long_fire, 0.42)
        return True

    def _can_drag(self, idx):
        if not self.reorderable:
            return False
        if self.can_drag:
            return bool(self.can_drag(idx, self.items[idx]))
        return True

    def _long_fire(self, dt):
        self._long_ev = None
        t = self._t
        if not t or t['state'] != 'pending' or t['idx'] is None:
            return
        t['state'] = 'armed'
        if self.on_long:
            self.on_long(t['idx'], self.items[t['idx']])

    def on_touch_move(self, touch):
        t = self._t
        if touch.grab_current is not self or not t or t['uid'] != touch.uid:
            return False
        thr = dp(9)
        moved = abs(touch.y - t['sy']) > thr or abs(touch.x - t['sx']) > thr
        st = t['state']
        if st == 'pending':
            if moved:
                self._cancel_long()
                t['state'] = 'scroll'
                st = 'scroll'
        elif st == 'armed':
            if moved and t['idx'] is not None and self._can_drag(t['idx']) and \
                    getattr(self.ctx, 'sel_mode', False):
                self._begin_drag(t['idx'], touch)
                st = 'drag'
                t['state'] = 'drag'
        elif st == 'handle':
            if moved:
                self._begin_drag(t['idx'], touch)
                st = 'drag'
                t['state'] = 'drag'
        if st == 'scroll':
            dy = touch.y - t['last_y']
            self.scroll += dy
            self.relayout()
            t['samples'].append((time.time(), touch.y))
            if len(t['samples']) > 6:
                t['samples'].pop(0)
        elif st == 'drag':
            self._drag_move(touch.y)
        t['last_y'] = touch.y
        return True

    def on_touch_up(self, touch):
        t = self._t
        if touch.grab_current is not self or not t or t['uid'] != touch.uid:
            return False
        touch.ungrab(self)
        self._cancel_long()
        st = t['state']
        self._t = None
        if st in ('pending', 'handle'):
            if t['idx'] is not None and self.on_tap:
                self.on_tap(t['idx'], self.items[t['idx']], touch.x)
        elif st == 'scroll':
            s = t['samples']
            if len(s) >= 2:
                dt = s[-1][0] - s[0][0]
                if dt > 0.001:
                    v = (s[-1][1] - s[0][1]) / dt
                    if abs(v) > dp(120):
                        self._start_fling(v)
        elif st == 'drag':
            self._end_drag()
        return True

    def _cancel_long(self):
        if self._long_ev:
            self._long_ev.cancel()
            self._long_ev = None

    # ---- kinetic scrolling ------------------------------------------------------
    def _start_fling(self, v):
        self._fling_v = max(-dp(6000), min(dp(6000), v))
        if self._fling is None:
            self._fling = Clock.schedule_interval(self._fling_tick, 0)      # every frame

    def _stop_fling(self):
        if self._fling is not None:
            self._fling.cancel()
            self._fling = None
        self._fling_v = 0.0

    def _fling_tick(self, dt):
        dt = min(dt, 0.05)              # a long frame must not make the list jump
        self.scroll += self._fling_v * dt
        self._fling_v *= 0.94 ** (dt * 60.0)
        before = self.scroll
        self.relayout()
        if abs(self._fling_v) < dp(25) or self.scroll != before:
            self._stop_fling()

    # ---- drag reorder -------------------------------------------------------------
    def _begin_drag(self, idx, touch):
        row = self.rows.get(idx)
        if row is None:
            return
        car = row._car
        y = car.at() + self._shift.y
        self._drag = {'from': idx, 'to': idx, 'y': y, 'touch_y': touch.y, 'off': touch.y - y}
        self._holder.remove_widget(car)          # re-add so it is drawn above the others
        self._holder.add_widget(car)
        row.opacity = 0.95
        if self._drag_ev is None:
            self._drag_ev = Clock.schedule_interval(self._drag_tick, 0)

    def _drag_move(self, y):
        d = self._drag
        if not d:
            return
        d['touch_y'] = y
        self._update_drag_target()

    def _update_drag_target(self):
        d = self._drag
        rh = self.row_h
        y = d['touch_y']
        d['y'] = max(self.y - rh * 0.5, min((self.y + self.height) - rh * 0.5, y - d['off']))
        center = d['y'] + rh / 2.0
        to = int((self.scroll + ((self.y + self.height) - center)) // rh)
        d['to'] = max(0, min(len(self.items) - 1, to))

    def _drag_tick(self, dt):
        d = self._drag
        if not d:
            return
        dt = min(dt, 0.05)
        # auto scroll near the edges
        edge = dp(70)
        ty = d['touch_y']
        top = self.y + self.height
        speed = dp(9) * dt * 60.0
        if ty > top - edge:
            self.scroll -= speed * (1 + (ty - (top - edge)) / edge)
        elif ty < self.y + edge:
            self.scroll += speed * (1 + ((self.y + edge) - ty) / edge)
        self.scroll = max(0.0, min(self.scroll, self.max_scroll()))
        self._update_drag_target()
        self.relayout()
        k = min(1.0, dt * 18.0)
        shift = self._shift.y
        for i, row in self.rows.items():
            car = row._car
            if i == d['from']:
                car.put(round(d['y']) - shift)
                continue
            diff = car.vy - car.at()
            if abs(diff) <= 1.0:
                car.put(car.vy)
            else:
                step = diff * k
                if abs(step) < 1.0:
                    step = 1.0 if diff > 0 else -1.0
                car.put(round(car.at() + step))

    def _end_drag(self):
        d = self._drag
        if self._drag_ev is not None:
            self._drag_ev.cancel()
            self._drag_ev = None
        self._drag = None
        for row in self.rows.values():
            row.opacity = 1.0
        src, dst = d['from'], d['to']
        if src != dst and self.on_reorder:
            self.on_reorder(src, dst)
        else:
            self._release_all()
            self.relayout()


# ---------------------------------------------------------------------------
# overlays: sheet / dialogs / toast
# ---------------------------------------------------------------------------
def make_scroll(**kw):
    """The scrolling container used by sheets and the settings (see PlainScroll)."""
    return PlainScroll(**kw)


class PlainScroll(StencilView):
    """Vertical scroller that owns its touches, exactly like VList does.

    Kivy's ScrollView hands a touch to the rows as a *press* in several situations (the finger
    rested a moment, an earlier touch was lost, ...), after which the list can no longer scroll.
    Here no row ever sees a touch: the container tracks the finger itself.  Moving more than a few
    dp scrolls (with a fling on release); lifting the finger without moving is a tap, which is
    delivered to the Tap widget under the finger.  The content (``box``) keeps its normal layout
    position; scrolling only moves one Translate.
    """

    THRESH = dp(9)

    def __init__(self, **kw):
        kw.setdefault('size_hint', (1, 1))
        super(PlainScroll, self).__init__(**kw)
        self.box = None
        self.offset = 0.0
        self._t = None
        self._fling = None
        self._fling_v = 0.0
        self._hl_ev = None
        self._long_ev = None
        self._bar_ev = None
        self._holder = Widget(size_hint=(None, None), size=(0, 0))
        with self._holder.canvas.before:
            PushMatrix()
            self._shift = Translate(0, 0)
        with self._holder.canvas.after:
            PopMatrix()
        super(PlainScroll, self).add_widget(self._holder)
        self._bar = Widget(size_hint=(None, None), size=(0, 0))
        with self._bar.canvas:
            self._bar_col = Color(1, 1, 1, 0)
            self._bar_rect = RoundedRectangle(pos=(0, 0), size=(0, 0), radius=[dp(2)])
        super(PlainScroll, self).add_widget(self._bar)
        self.bind(pos=self._sync, size=self._sync)

    # ---- content ---------------------------------------------------------------
    def add_widget(self, widget, *a, **k):
        if self.box is not None:
            self._holder.remove_widget(self.box)
            self.box.unbind(height=self._sync)
        self.box = widget
        widget.size_hint_x = None
        self._holder.add_widget(widget)
        widget.bind(height=self._sync)
        self._sync()

    def max_offset(self):
        b = self.box
        return max(0.0, (b.height if b is not None else 0.0) - self.height)

    def _get_scroll_y(self):
        m = self.max_offset()
        return 1.0 if m <= 0 else 1.0 - self.offset / m

    def _set_scroll_y(self, v):
        self.offset = (1.0 - max(0.0, min(1.0, v))) * self.max_offset()
        self._apply()

    scroll_y = property(_get_scroll_y, _set_scroll_y)

    def _sync(self, *a):
        b = self.box
        if b is None:
            return
        if b.width != self.width:
            b.width = self.width
        b.pos = (self.x, self.top - b.height)
        self._apply()

    def _apply(self):
        self.offset = max(0.0, min(self.max_offset(), self.offset))
        y = float(round(self.offset))
        if self._shift.y != y:
            self._shift.y = y
        self._draw_bar()

    def scroll_to_top(self):
        self.offset = 0.0
        self._apply()

    # ---- scroll bar ----------------------------------------------------------------
    def _draw_bar(self):
        m = self.max_offset()
        if m <= 0 or self._bar_ev is None:
            self._bar_col.a = 0
            return
        h = self.height
        total = self.box.height
        bh = max(dp(28), h * h / total)
        by = self.top - bh - (h - bh) * (self.offset / m)
        self._bar_rect.pos = (self.right - dp(5), by)
        self._bar_rect.size = (dp(3), bh)
        self._bar_col.a = 0.32

    def _show_bar(self):
        if self._bar_ev is not None:
            self._bar_ev.cancel()
        self._bar_ev = Clock.schedule_once(self._hide_bar, 0.8)
        self._draw_bar()

    def _hide_bar(self, dt):
        self._bar_ev = None
        self._bar_col.a = 0

    # ---- touch -----------------------------------------------------------------------
    def _find(self, w, x, y):
        """Deepest Tap widget under (x, y) in the content's own coordinates."""
        for c in w.children:                    # topmost first
            if c.disabled or c.opacity == 0 or not c.collide_point(x, y):
                continue
            r = self._find(c, x, y)
            if r is not None:
                return r
        if isinstance(w, Tap) and not w.disabled and (w.callback or w.long_callback) and w.collide_point(x, y):
            return w
        return None

    def _clear_target(self):
        for ev in (self._hl_ev, self._long_ev):
            if ev is not None:
                ev.cancel()
        self._hl_ev = None
        self._long_ev = None
        t = self._t
        if t and t.get('tgt') is not None and t['tgt'].pressed:
            t['tgt']._set_pressed(False)

    def _highlight(self, dt):
        self._hl_ev = None
        t = self._t
        if t and t['state'] == 'pending' and t['tgt'] is not None:
            t['tgt']._set_pressed(True)

    def _long_fire(self, dt):
        self._long_ev = None
        t = self._t
        if t and t['state'] == 'pending' and t['tgt'] is not None and t['tgt'].long_callback:
            t['state'] = 'done'
            tgt = t['tgt']
            tgt._set_pressed(False)
            tgt.long_callback(tgt)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        btn = getattr(touch, 'button', None)
        if btn in ('scrollup', 'scrolldown'):
            self.offset += (-1 if btn == 'scrollup' else 1) * dp(90)
            self._apply()
            return True
        if self._t is not None:                 # stale state from a lost touch
            self._clear_target()
            self._t = None
        was_moving = self._fling is not None
        self._stop_fling()
        touch.grab(self)
        tgt = None
        if not was_moving and self.box is not None:         # a touch that stops a fling is not a tap
            tgt = self._find(self.box, touch.x, touch.y - self._shift.y)
        self._t = {'uid': touch.uid, 'state': 'pending' if not was_moving else 'stopper',
                   'sx': touch.x, 'sy': touch.y, 'last_y': touch.y, 'tgt': tgt,
                   'samples': [(time.time(), touch.y)]}
        if tgt is not None:
            self._hl_ev = Clock.schedule_once(self._highlight, 0.08)
            if tgt.long_callback:
                self._long_ev = Clock.schedule_once(self._long_fire, 0.45)
        return True

    def on_touch_move(self, touch):
        t = self._t
        if touch.grab_current is not self or not t or t['uid'] != touch.uid:
            return False
        if t['state'] in ('pending', 'stopper'):
            if abs(touch.y - t['sy']) > self.THRESH or abs(touch.x - t['sx']) > self.THRESH:
                self._clear_target()
                t['state'] = 'scroll'
        if t['state'] == 'scroll':
            self.offset += touch.y - t['last_y']
            self._apply()
            self._show_bar()
            t['samples'].append((time.time(), touch.y))
            if len(t['samples']) > 6:
                t['samples'].pop(0)
        t['last_y'] = touch.y
        return True

    def on_touch_up(self, touch):
        t = self._t
        if touch.grab_current is not self or not t or t['uid'] != touch.uid:
            return False
        touch.ungrab(self)
        self._t = None
        st = t['state']
        tgt = t['tgt']
        for ev in (self._hl_ev, self._long_ev):
            if ev is not None:
                ev.cancel()
        self._hl_ev = None
        self._long_ev = None
        if st == 'pending':
            if tgt is not None:
                tgt._set_pressed(False)
                tgt.tap_now()
        elif st == 'scroll':
            s = t['samples']
            if len(s) >= 2:
                dt = s[-1][0] - s[0][0]
                if dt > 0.001:
                    v = (s[-1][1] - s[0][1]) / dt
                    if abs(v) > dp(120):
                        self._start_fling(v)
        elif tgt is not None and tgt.pressed:
            tgt._set_pressed(False)
        return True

    # ---- fling -------------------------------------------------------------------------
    def _start_fling(self, v):
        self._fling_v = max(-dp(6000), min(dp(6000), v))
        if self._fling is None:
            self._fling = Clock.schedule_interval(self._fling_tick, 0)

    def _stop_fling(self):
        if self._fling is not None:
            self._fling.cancel()
            self._fling = None
        self._fling_v = 0.0

    def _fling_tick(self, dt):
        dt = min(dt, 0.05)
        want = self.offset + self._fling_v * dt
        self._fling_v *= 0.94 ** (dt * 60.0)
        self.offset = want
        self._apply()
        self._show_bar()
        if abs(self._fling_v) < dp(25) or self.offset != want:
            self._stop_fling()


class Overlay(FloatLayout):
    cancelable = True

    def __init__(self, root, **kw):
        kw.setdefault('size_hint', (1, 1))
        super(Overlay, self).__init__(**kw)
        self.root = root
        self.panel = None
        with self.canvas.before:
            Color(0, 0, 0, 0.62)
            self._dim = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._geo, size=self._geo)

    def _geo(self, *a):
        self._dim.pos = self.pos
        self._dim.size = self.size
        self.place()

    def place(self):
        pass

    def show(self):
        self.root.show_overlay(self)

    def dismiss(self):
        self.root.dismiss_overlay(self)

    def on_back(self):
        if self.cancelable:
            self.dismiss()
        return True

    def on_touch_down(self, touch):
        if FloatLayout.on_touch_down(self, touch):
            return True
        if self.panel is not None and self.panel.collide_point(*touch.pos):
            return True
        # A press outside the panel only closes the overlay.  The rest of that touch, and any press
        # right after it, is swallowed by the root so it can never press what lies under the finger.
        if self.cancelable:
            guard = getattr(self.root, 'guard_touches', None)
            if guard:
                guard(touch)
            self.dismiss()
        return True

    def on_touch_move(self, touch):
        FloatLayout.on_touch_move(self, touch)
        return True

    def on_touch_up(self, touch):
        FloatLayout.on_touch_up(self, touch)
        return True


class Panel(FloatLayout):
    """Rounded background container used by sheets and dialogs."""

    def __init__(self, radius=None, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Panel, self).__init__(**kw)
        self.radius = radius or [dp(24)] * 4
        with self.canvas.before:
            Color(*SURFACE)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
        self.bind(pos=self._geo, size=self._geo)

    def _geo(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size


def icon_chip(canvas, cx, cy, d=None, danger=False):
    """The soft round tile behind a row icon."""
    d = d or dp(38)
    with canvas:
        if danger:
            Color(DANGER[0], DANGER[1], DANGER[2], 0.14)
        else:
            Color(1, 1, 1, 0.07)
        Ellipse(pos=(cx - d / 2.0, cy - d / 2.0), size=(d, d))


class SheetRow(Tap):
    def __init__(self, label, icon=None, value=None, checked=False, danger=False, callback=None, **kw):
        kw.setdefault('height', dp(58))
        super(SheetRow, self).__init__(callback=callback, **kw)
        self.danger = danger
        col = DANGER if danger else (ACCENT if checked else TEXT)
        self.icon = Icon(name=icon, color=list(DANGER if danger else TEXT), size=(dp(22), dp(22))) if icon else None
        self.lbl = Txt(ltext=label, color=col, bold=bool(checked), font_size=sp(16), size_hint=(None, None))
        self.val = Txt(ltext=value or '', color=SUB, font_size=sp(14), halign='left', size_hint=(None, None))
        self.chk = Icon(name='check', color=list(ACCENT), size=(dp(24), dp(24)), stroke=2.0) if checked else None
        for w in (self.icon, self.lbl, self.val, self.chk):
            if w is not None:
                self.add_widget(w)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def set_checked(self, flag):
        """Tick / untick in place (no rebuild of the whole sheet: that is what made long lists lag)."""
        flag = bool(flag)
        if flag == (self.chk is not None):
            return
        if flag:
            self.chk = Icon(name='check', color=list(ACCENT), size=(dp(24), dp(24)), stroke=2.0)
            self.add_widget(self.chk)
        else:
            self.remove_widget(self.chk)
            self.chk = None
        self.lbl.color = DANGER if self.danger else (ACCENT if flag else TEXT)
        self.lbl.bold = flag
        self._lay()

    def _lay(self, *a):
        pad = dp(18)
        cy = self.y + self.height / 2.0
        right = (self.x + self.width) - pad
        self.canvas.before.clear()
        if self.icon is not None:
            self.icon.center = (right - dp(19), cy)
            icon_chip(self.canvas.before, right - dp(19), cy, dp(38), self.danger)
            right -= dp(52)
        left = self.x + pad
        if self.chk is not None:
            self.chk.center = (left + dp(12), cy)
            left += dp(40)
        vw = min(dp(150), self.val.text_width() + dp(10)) if self.val.ltext else 0
        self.val.pos = (left, self.y)
        self.val.size = (vw, self.height)
        self.lbl.pos = (left + vw + dp(6), self.y)
        self.lbl.size = (max(10, right - left - vw - dp(6)), self.height)


class SettingRow(Tap):
    """One line of the settings card: tinted icon tile, title (+ small description) and, on the far
    side, either a switch or the current value with a chevron."""
    TILE = dp(38)
    PAD = dp(16)

    def __init__(self, title, sub='', icon=None, value=None, switch=None, callback=None, **kw):
        kw.setdefault('height', dp(66) if sub else dp(58))
        super(SettingRow, self).__init__(callback=callback, **kw)
        self.icon = Icon(name=icon, color=list(ACCENT), size=(dp(20), dp(20)), stroke=1.7) if icon else None
        self.lbl = Txt(ltext=title, font_size=sp(15.5), size_hint=(None, None))
        self.sub = Txt(ltext=sub, color=SUB, font_size=sp(12.5), size_hint=(None, None)) if sub else None
        self.sw = switch
        self.val = Txt(ltext=value, color=ACCENT, bold=True, font_size=sp(14), halign='left',
                       size_hint=(None, None)) if value is not None else None
        self.chev = Icon(name='chev_left', color=[0.5, 0.52, 0.58, 1], size=(dp(18), dp(18)),
                         stroke=1.8) if (value is not None) else None
        for w in (self.icon, self.lbl, self.sub, self.sw, self.val, self.chev):
            if w is not None:
                self.add_widget(w)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        pad = self.PAD
        cy = self.y + self.height / 2.0
        right = (self.x + self.width) - pad
        self.canvas.before.clear()
        if self.icon is not None:
            d = self.TILE
            with self.canvas.before:
                Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.13)
                RoundedRectangle(pos=(right - d, cy - d / 2.0), size=(d, d), radius=[dp(11)])
            self.icon.center = (right - d / 2.0, cy)
            right -= d + dp(13)
        left = self.x + pad
        if self.sw is not None:
            self.sw.pos = (left, cy - self.sw.height / 2.0)
            left += self.sw.width + dp(14)
        elif self.val is not None:
            self.chev.center = (left + dp(7), cy)
            left += dp(22)
            vw = min(dp(120), self.val.text_width() + dp(8))
            self.val.pos = (left, self.y)
            self.val.size = (vw, self.height)
            left += vw + dp(10)
        w = max(10, right - left)
        if self.sub is not None:
            self.lbl.pos = (left, cy + dp(1))
            self.lbl.size = (w, dp(24))
            self.sub.pos = (left, cy - dp(23))
            self.sub.size = (w, dp(22))
        else:
            self.lbl.pos = (left, self.y)
            self.lbl.size = (w, self.height)

    def set_value(self, text):
        if self.val is not None:
            self.val.ltext = text
            self._lay()


class SheetButton(Widget):
    """A wide rounded button inside a sheet (accent when enabled, quiet when not)."""

    def __init__(self, label, callback=None, enabled=True, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(74))
        super(SheetButton, self).__init__(**kw)
        self.enabled = bool(enabled)
        self.btn = Tap(callback=(callback if enabled else None), size_hint=(None, None), height=dp(52))
        self.btn.fb_radius = [dp(16)] * 4
        self.lbl = Txt(ltext=label, halign='center', bold=True, font_size=sp(16.5),
                       color=ON_ACCENT if enabled else SUB, size_hint=(None, None))
        self.btn.add_widget(self.lbl)
        self.add_widget(self.btn)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        b = self.btn
        b.pos = (self.x + dp(18), self.y + dp(11))
        b.size = (max(10, self.width - dp(36)), dp(52))
        self.lbl.pos = b.pos
        self.lbl.size = b.size
        b.canvas.before.clear()
        with b.canvas.before:
            Color(*(ACCENT if self.enabled else SURFACE2))
            RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(16)])


class SheetTitle(Widget):
    def __init__(self, text, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(60))
        super(SheetTitle, self).__init__(**kw)
        self.lbl = Txt(ltext=text, bold=True, font_size=sp(20), size_hint=(None, None))
        self.add_widget(self.lbl)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        self.lbl.pos = (self.x + dp(20), self.y + dp(2))
        self.lbl.size = (self.width - dp(40), self.height - dp(4))
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*DIVIDER)
            Rectangle(pos=(self.x + dp(20), self.y), size=(max(0, self.width - dp(40)), 1))


class SheetLabel(Widget):
    """Small section heading (accent) - or, with muted=True, a quiet explanatory line."""

    def __init__(self, text, muted=False, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(40) if not muted else dp(36))
        super(SheetLabel, self).__init__(**kw)
        self.lbl = Txt(ltext=text, color=SUB if muted else ACCENT, bold=not muted,
                       font_size=sp(13) if not muted else sp(13), nlines=2 if muted else 1,
                       valign='bottom' if not muted else 'middle', size_hint=(None, None))
        self.add_widget(self.lbl)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        self.lbl.pos = (self.x + dp(20), self.y + (dp(4) if self.lbl.valign == 'bottom' else 0))
        self.lbl.size = (self.width - dp(40), self.height - dp(4))


class ChipsRow(Widget):
    """Wrapping grid of chips (used for the speed picker)."""

    def __init__(self, options, current, on_pick, cols=4, **kw):
        kw.setdefault('size_hint', (1, None))
        super(ChipsRow, self).__init__(**kw)
        self.cols = cols
        n = len(options)
        self.nrows = (n + cols - 1) // cols
        self.height = self.nrows * dp(52) + dp(10)
        self.chips = []
        for val, label in options:
            c = Chip(label, selected=(abs(float(val) - float(current)) < 1e-6),
                     callback=(lambda w, v=val: on_pick(v)), size_hint=(None, None))
            self.chips.append(c)
            self.add_widget(c)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        pad = dp(18)
        gap = dp(8)
        cw = (self.width - 2 * pad - gap * (self.cols - 1)) / float(self.cols)
        for i, c in enumerate(self.chips):
            r, col = divmod(i, self.cols)
            # RTL: first chip on the right
            x = (self.x + self.width) - pad - (col + 1) * cw - col * gap
            y = (self.y + self.height) - dp(4) - (r + 1) * dp(44) - r * dp(8)
            c.pos = (x, y)
            c.size = (cw, dp(44))


class MenuSheet(Overlay):
    """Bottom sheet (portrait) or side panel (landscape) with a scrolling list.

    build() is a function returning a list of widgets; call rebuild() to refresh."""

    PAD_TOP = dp(18)
    PAD_BOTTOM = dp(14)

    def __init__(self, root, build, footer=None, **kw):
        super(MenuSheet, self).__init__(root, **kw)
        self.build = build
        self.footer_fn = footer           # optional: returns a widget pinned to the bottom (never scrolls)
        self.footer_w = None
        self.footer_h = 0
        self.panel = Panel()
        self.add_widget(self.panel)
        self.sv = make_scroll(size_hint=(None, None))
        self.box = BoxLayout(orientation='vertical', size_hint_y=None,
                             padding=[0, self.PAD_TOP, 0, self.PAD_BOTTOM])
        self.box.bind(minimum_height=self.box.setter('height'))
        self.sv.add_widget(self.box)
        self.panel.add_widget(self.sv)
        self.content_h = self.PAD_TOP + self.PAD_BOTTOM
        self.rebuild()

    def rebuild(self):
        self.box.clear_widgets()
        widgets = self.build()
        total = self.PAD_TOP + self.PAD_BOTTOM
        for w in widgets:
            w.size_hint = (1, None)
            total += w.height
            self.box.add_widget(w)
        self.content_h = total
        self._make_footer()
        self.box.height = total                 # at once: do not wait for the next layout pass
        if total <= self.sv.height:
            self.sv.scroll_y = 1                # content that fits is never left scrolled
        self._ready = True
        self.place()

    def _make_footer(self):
        if self.footer_w is not None:
            self.panel.remove_widget(self.footer_w)
            self.footer_w = None
        self.footer_h = 0
        if self.footer_fn is not None:
            fw = self.footer_fn()
            fw.size_hint = (None, None)
            self.panel.add_widget(fw)
            self.footer_w = fw
            self.footer_h = fw.height + dp(6)

    def refresh_footer(self):
        """Replace only the pinned button (cheap): used after ticking a row."""
        self._make_footer()
        self.place()

    def place(self):
        W, H = self.width, self.height
        if W <= 1 or H <= 1 or not getattr(self, '_ready', False):
            return
        self.panel.canvas.after.clear()
        if W > H:
            pw = min(dp(420), W * 0.55)
            ph = H
            self.panel.radius = [dp(24), 0, 0, dp(24)]
            self.panel.pos = ((self.x + self.width) - pw, self.y)
        else:
            pw = min(W, dp(520))
            ph = min(self.content_h + self.footer_h + dp(6), H * 0.82)
            self.panel.radius = [dp(26), dp(26), 0, 0]
            self.panel.pos = ((self.x + self.width / 2.0) - pw / 2.0, self.y)
        self.panel._bg.radius = self.panel.radius
        self.panel.size = (pw, ph)
        fh = self.footer_h
        self.sv.pos = (self.panel.x, self.panel.y + fh)
        self.sv.size = (pw, ph - fh)
        if self.footer_w is not None:
            self.footer_w.pos = self.panel.pos
            self.footer_w.size = (pw, fh)
            with self.panel.canvas.after:               # a thin line above the pinned button
                Color(1, 1, 1, 0.08)
                Rectangle(pos=(self.panel.x, self.panel.y + fh), size=(pw, 1))
        if W <= H:
            with self.panel.canvas.after:               # the little grab handle of a bottom sheet
                Color(1, 1, 1, 0.22)
                RoundedRectangle(pos=(self.panel.x + pw / 2.0 - dp(20), (self.panel.y + ph) - dp(12)),
                                 size=(dp(40), dp(4)), radius=[dp(2)])


class Dialog(Overlay):
    def __init__(self, root, title, message='', buttons=None, **kw):
        super(Dialog, self).__init__(root, **kw)
        self.extra = None
        self.panel = Panel(radius=[dp(26)] * 4)
        self.add_widget(self.panel)
        self.title = Txt(ltext=title, bold=True, font_size=sp(20), size_hint=(None, None))
        self.msg = Txt(ltext=message, color=(0.78, 0.80, 0.85, 1), font_size=sp(15), nlines=6, keep_nl=True,
                       valign='top', size_hint=(None, None))
        self.panel.add_widget(self.title)
        self.panel.add_widget(self.msg)
        self.btns = []
        for label, cb, kind in (buttons or [('حسناً', None, 'primary')]):
            b = Tap(callback=(lambda w, cb=cb: self._press(cb)), size_hint=(None, None), height=dp(48))
            b.kind = kind
            b.fb_radius = [dp(14)] * 4
            b.lbl = Txt(ltext=label, halign='center', bold=True, font_size=sp(16),
                        color=(ON_ACCENT if kind == 'primary' else (1, 1, 1, 1) if kind == 'danger' else TEXT),
                        size_hint=(None, None))
            b.add_widget(b.lbl)
            self.panel.add_widget(b)
            self.btns.append(b)
        self.place()

    auto_dismiss = True

    def _press(self, cb):
        if self.auto_dismiss or cb is None:
            self.dismiss()
        if cb:
            cb()

    def set_extra(self, widget):
        self.extra = widget
        widget.size_hint = (None, None)            # we set its width ourselves (a hint would stretch it)
        self.panel.add_widget(widget)
        self.place()

    def place(self):
        W = self.width
        if W <= 1 or not hasattr(self, 'btns'):
            return
        pw = min(W - dp(36), dp(420))
        pad = dp(22)
        msg_lines = 0
        if self.msg.ltext:
            tw = pw - 2 * pad
            font = font_for(self.msg.ltext)
            for part in self.msg.ltext.split('\n'):
                msg_lines += len(textfix.wrap_text(part, tw, lambda t: measure(t, font, sp(15), False), 6) or [''])
            msg_lines = min(6, max(1, msg_lines))
        mh = msg_lines * sp(15) * 1.62 if self.msg.ltext else 0
        eh = (self.extra.height + dp(10)) if self.extra is not None else 0
        ph = pad + dp(32) + dp(10) + mh + eh + dp(20) + dp(48) + dp(18)
        px = (self.x + self.width / 2.0) - pw / 2.0
        if self.extra is not None:
            py = (self.y + self.height) - dp(120) - ph       # keep clear of the keyboard
            py = max(self.y + dp(8), py)
        else:
            py = (self.y + self.height / 2.0) - ph / 2.0
        self.panel.pos = (px, py)
        self.panel.size = (pw, ph)
        y = py + ph - pad - dp(32)
        self.title.pos = (px + pad, y)
        self.title.size = (pw - 2 * pad, dp(32))
        y -= dp(10) + mh
        self.msg.pos = (px + pad, y)
        self.msg.size = (pw - 2 * pad, mh)
        if self.extra is not None:
            y -= eh
            self.extra.pos = (px + pad, y + dp(5))
            self.extra.width = pw - 2 * pad
        n = len(self.btns)
        gap = dp(10)
        bw = (pw - 2 * pad - gap * (n - 1)) / float(n)
        for i, b in enumerate(self.btns):
            # first button on the right
            b.pos = (px + pw - pad - (i + 1) * bw - i * gap, py + dp(18))
            b.size = (bw, dp(48))
            b.lbl.pos = b.pos
            b.lbl.size = b.size
            b.canvas.before.clear()
            with b.canvas.before:
                if b.kind == 'primary':
                    Color(*ACCENT)
                elif b.kind == 'danger':
                    Color(*DANGER)
                else:
                    Color(*SURFACE2)
                RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(14)])


class PromptDialog(Dialog):
    auto_dismiss = False

    def __init__(self, root, title, text='', hint='', ok_label='حفظ', on_ok=None, message='', **kw):
        self._on_ok = on_ok
        super(PromptDialog, self).__init__(
            root, title, message,
            buttons=[(ok_label, self._submit_btn, 'primary'), ('إلغاء', None, 'plain')], **kw)
        self.field = FieldInput(text=text, hint=hint, on_submit=self._submit_text)
        self.field.on_resize = self.place
        self.set_extra(self.field)
        Clock.schedule_once(self._focus, 0.25)

    def _focus(self, dt):
        if self in self.root.overlays:
            self.field.focus()

    def _submit_btn(self):
        self._submit_text(self.field.text)

    def _submit_text(self, text):
        text = (text or '').strip()
        if not text:
            return
        self.field.release()
        if self in self.root.overlays:
            self.dismiss()
        if self._on_ok:
            self._on_ok(text)

    def dismiss(self):
        try:
            self.field.release()
        except Exception:
            pass
        super(PromptDialog, self).dismiss()


class Toast(Widget):
    """One-line message near the bottom, fades after ~2 s."""

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Toast, self).__init__(**kw)
        self.lbl = Txt(ltext='', halign='center', font_size=sp(15), size_hint=(None, None),
                       nlines=2)
        self.add_widget(self.lbl)
        self.opacity = 0
        self._ev = None
        self.size = (0, 0)

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False

    def show(self, text, parent_size, bottom=dp(96)):
        W = parent_size[0]
        w = min(W - dp(40), dp(380))
        self.size = (w, dp(58) if len(text) > 32 else dp(46))
        self.pos = ((W - w) / 2.0, bottom)
        self.lbl.ltext = text
        self.lbl.pos = (self.x + dp(16), self.y)
        self.lbl.size = (self.width - dp(32), self.height)
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0, 0, 0, 0.35)                                    # shadow
            RoundedRectangle(pos=(self.x, self.y - dp(2)), size=(self.width, self.height), radius=[dp(23)])
            Color(0.15, 0.155, 0.185, 0.98)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(23)])
            Color(1, 1, 1, 0.08)
            Line(rounded_rectangle=(self.x + 0.5, self.y + 0.5, self.width - 1, self.height - 1, dp(23)),
                 width=1)
        self.opacity = 1
        if self._ev:
            self._ev.cancel()
        self._ev = Clock.schedule_once(self._hide, 2.2)

    def _hide(self, dt):
        self.opacity = 0


# ---------------------------------------------------------------------------
# small building blocks used by the player and the settings
# ---------------------------------------------------------------------------
class Badge(Widget):
    """Dark rounded chip with an optional icon and a short text; sizes itself to the text."""

    def __init__(self, font=None, pulse=False, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Badge, self).__init__(**kw)
        self.pulse = pulse
        self.icon = Icon(name='play', size=(0, 0))
        self.lbl = Txt(halign='center', align_mode='center', font_size=font or sp(15), bold=True,
                       size_hint=(None, None))
        self.add_widget(self.icon)
        self.add_widget(self.lbl)
        self.opacity = 0
        self._isz = 0
        self._tw = 0
        self._ev = None
        self._pulse_ev = None
        self.bind(pos=self._lay, size=self._lay)

    def show(self, text, center, icon=None, duration=0.0, h=None):
        self.lbl.ltext = text
        tw = self.lbl.text_width() + dp(6)
        on = icon is not None
        if on:
            self.icon.name = icon
        isz = dp(20) if on else 0
        self.icon.size = (isz, isz)
        pad = dp(16)
        h = h or dp(40)
        w = pad * 2 + tw + ((isz + dp(8)) if on else 0)
        self._isz, self._tw = isz, tw
        self.size = (max(w, h), h)
        self.center = center
        self.opacity = 1
        self.icon.opacity = 1
        if self._ev:
            self._ev.cancel()
            self._ev = None
        if duration:
            self._ev = Clock.schedule_once(lambda dt: self.hide(), duration)
        if self.pulse and on and self._pulse_ev is None:
            self._pulse_ev = Clock.schedule_interval(self._beat, 0.4)
        self._lay()

    def _beat(self, dt):
        self.icon.opacity = 0.4 if self.icon.opacity > 0.7 else 1.0

    def hide(self):
        self.opacity = 0
        if self._ev:
            self._ev.cancel()
            self._ev = None
        if self._pulse_ev:
            self._pulse_ev.cancel()
            self._pulse_ev = None

    def _lay(self, *a):
        self.canvas.before.clear()
        h = self.height
        with self.canvas.before:
            Color(*SCRIM)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[h / 2.0])
            Color(1, 1, 1, 0.10)
            Line(rounded_rectangle=(self.x + 0.5, self.y + 0.5, self.width - 1, h - 1, h / 2.0), width=1)
        pad = dp(16)
        cy = self.y + h / 2.0
        if self._isz:
            self.icon.center = (self.x + pad + self._isz / 2.0, cy)
            self.lbl.pos = (self.x + pad + self._isz + dp(8), self.y)
            self.lbl.size = (self._tw, h)
        else:
            self.lbl.pos = (self.x + pad, self.y)
            self.lbl.size = (max(2, self.width - 2 * pad), h)

    def on_touch_down(self, touch):
        return False


class Tag(Widget):
    """Small dark label that hugs its text (duration on a thumbnail, ...)."""

    def __init__(self, font=None, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Tag, self).__init__(**kw)
        self.lbl = Txt(halign='center', bold=True, font_size=font or sp(11), size_hint=(None, None))
        self.add_widget(self.lbl)
        self.bind(pos=self._lay, size=self._lay)

    @property
    def ltext(self):
        return self.lbl.ltext

    def set_text(self, text):
        self.lbl.ltext = text
        self.width = (self.lbl.text_width() + dp(12)) if text else 0
        self.height = dp(18) if text else 0
        self._lay()

    def _lay(self, *a):
        self.canvas.before.clear()
        self.lbl.pos = self.pos
        self.lbl.size = self.size
        if self.width < 2:
            return
        with self.canvas.before:
            Color(0, 0, 0, 0.78)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(5)])


class StepButton(Tap):
    """Round arrow with the number of seconds inside it (the usual -10 / +10 buttons)."""

    def __init__(self, direction, callback=None, value=10, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(52), dp(52)))
        super(StepButton, self).__init__(callback=callback, **kw)
        self.icon = Icon(name='step_fwd' if direction == 'fwd' else 'step_back', size=(dp(46), dp(46)),
                         stroke=1.7)
        self.num = Txt(ltext=str(int(value)), halign='center', align_mode='center', bold=True,
                       font_size=sp(10), size_hint=(None, None))
        self.add_widget(self.icon)
        self.add_widget(self.num)
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def set_value(self, n):
        self.num.ltext = str(int(n))

    def _sync(self, *a):
        cx, cy = self.x + self.width / 2.0, self.y + self.height / 2.0
        self.icon.center = (cx, cy)
        self.num.size = (dp(24), dp(14))
        self.num.center = (cx, cy + dp(0.2))         # the ring of the arrow is centred on the icon box

    def _set_pressed(self, v):
        self.pressed = v
        self.icon.opacity = 0.55 if v else 1.0
        self.num.opacity = 0.55 if v else 1.0


class EmptyState(Widget):
    """A muted icon over a short message, shown when a list has nothing to show."""
    ltext = StringProperty('')

    def __init__(self, icon='folder_play', **kw):
        kw.setdefault('size_hint', (None, None))
        super(EmptyState, self).__init__(**kw)
        self.icon = Icon(name=icon, size=(dp(60), dp(60)), color=[1, 1, 1, 0.2], stroke=1.2)
        self.lbl = Txt(halign='center', align_mode='center', color=SUB, font_size=sp(16), nlines=3,
                       size_hint=(None, None))
        self.add_widget(self.icon)
        self.add_widget(self.lbl)
        self.bind(pos=self._lay, size=self._lay, ltext=self._text)
        self._text()

    def _text(self, *a):
        self.lbl.ltext = self.ltext
        self.opacity = 1 if self.ltext else 0
        self._lay()

    def _lay(self, *a):
        self.lbl.pos = self.pos
        self.lbl.size = self.size
        self.icon.center = (self.x + self.width / 2.0, (self.y + self.height) + dp(38))

    def on_touch_down(self, touch):
        return False


class Group(BoxLayout):
    """A rounded card holding rows that are separated by hairlines (settings)."""

    def __init__(self, inset=(dp(20), dp(20)), **kw):
        kw.setdefault('orientation', 'vertical')
        kw.setdefault('size_hint', (1, None))
        super(Group, self).__init__(**kw)
        self.inset = inset                      # (left, right) gap of the hairlines
        self.bind(minimum_height=self.setter('height'))
        self._rows = []
        with self.canvas.before:
            Color(*SURFACE)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(20)])
        self.bind(pos=self._geo, size=self._geo)

    def add_row(self, w):
        w.size_hint = (1, None)
        self._rows.append(w)
        self.add_widget(w)
        n, r = len(self._rows), dp(20)
        for i, row in enumerate(self._rows):
            if isinstance(row, Tap):
                top, bot = (r if i == 0 else 0), (r if i == n - 1 else 0)
                row.fb_radius = [top, top, bot, bot]
        self._geo()

    def _geo(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self.canvas.after.clear()
        with self.canvas.after:
            Color(1, 1, 1, 0.055)                                   # hairline edge of the card
            Line(rounded_rectangle=(self.x, self.y, self.width, self.height, dp(20)), width=1)
            Color(*DIVIDER)
            y = self.y + self.height
            for row in self._rows[:-1]:
                y -= row.height
                Rectangle(pos=(self.x + self.inset[0], y - 0.5),
                          size=(max(0, self.width - self.inset[0] - self.inset[1]), 1))
