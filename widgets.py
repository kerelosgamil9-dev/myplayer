# -*- coding: utf-8 -*-
"""
widgets.py - all custom widgets (pure Python, no .kv files):
  Txt, Icon, Tap, IconButton, Thumb, Switch, SeekBar, FieldInput,
  VList (virtualised list with scrolling, long-press selection and drag reordering),
  Overlay / MenuSheet / Dialog / PromptDialog, Toast.
"""
import math
import os
import time
from collections import OrderedDict

from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel, LabelBase
from kivy.graphics import Color, Ellipse, Line, Mesh, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.properties import (BooleanProperty, ListProperty, NumericProperty,
                             StringProperty)
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.stencilview import StencilView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

import core
import textfix

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# theme
# ---------------------------------------------------------------------------
BG = (0, 0, 0, 1)
SURFACE = (0.105, 0.105, 0.11, 1)
SURFACE2 = (0.16, 0.16, 0.17, 1)
ACCENT = (0.973, 0.42, 0.36, 1)
TEXT = (1, 1, 1, 1)
SUB = (0.6, 0.6, 0.62, 1)
DIVIDER = (1, 1, 1, 0.08)
DANGER = (0.95, 0.3, 0.3, 1)

AR_FONT = 'ProArabic'
LATIN_FONT = 'Roboto'


def register_fonts():
    reg = os.path.join(HERE, 'DejaVuSans.ttf')
    bold = os.path.join(HERE, 'DejaVuSans-Bold.ttf')
    LabelBase.register(name=AR_FONT, fn_regular=reg, fn_bold=bold if os.path.exists(bold) else reg)


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
    'rotate': [('line', _arc(12, 12, 8, -40, 250)), ('line', [(16, 3.5), (18.5, 5), (17, 8.5)])],
    'lock': [('rect', 6, 11, 12, 9), ('line', _arc(12, 9, 4, 180, 360))],
    'unlock': [('rect', 6, 11, 12, 9), ('line', _arc(12, 8, 4, 180, 330))],
    'speed': [('line', _arc(12, 14, 9, 180, 360)), ('line', [(12, 14), (17, 9)]), ('line', [(3, 14), (21, 14)])],
    'subtitle': [('line', [(5, 5), (19, 5), (21, 7), (21, 17), (19, 19), (5, 19), (3, 17), (3, 7), (5, 5)]),
                 ('line', [(7, 11), (11, 11)]), ('line', [(13, 11), (17, 11)]), ('line', [(7, 15), (13, 15)])],
    'audio': [('dot', 8, 18, 3), ('line', [(11, 18), (11, 5), (19, 7.5)])],
    'brightness': [('circle', 12, 12, 4)] + [('line', [(12 + 7 * math.cos(math.radians(a)), 12 + 7 * math.sin(math.radians(a))),
                                                       (12 + 10 * math.cos(math.radians(a)), 12 + 10 * math.sin(math.radians(a)))])
                                              for a in range(0, 360, 45)],
    'volume': [('fill', [(4, 9), (8, 9), (13, 5), (13, 19), (8, 15), (4, 15)]),
               ('line', _arc(14, 12, 4, -50, 50)), ('line', _arc(14, 12, 8, -50, 50))],
    'aspect': [('line', [(3, 6), (21, 6), (21, 18), (3, 18), (3, 6)]), ('line', [(7, 10), (7, 14)]),
               ('line', [(17, 10), (17, 14)])],
    'repeat': [('line', [(4, 11), (4, 7), (18, 7)]), ('line', [(15, 4), (18, 7), (15, 10)]),
               ('line', [(20, 13), (20, 17), (6, 17)]), ('line', [(9, 14), (6, 17), (9, 20)])],
    'repeat_one': [('line', [(4, 11), (4, 7), (18, 7)]), ('line', [(15, 4), (18, 7), (15, 10)]),
                   ('line', [(20, 13), (20, 17), (6, 17)]), ('line', [(9, 14), (6, 17), (9, 20)]),
                   ('line', [(11, 10.5), (12.5, 9.5), (12.5, 14.5)])],
    'shuffle': [('line', [(3, 7), (8, 7), (15, 17), (20, 17)]), ('line', [(3, 17), (8, 17), (15, 7), (20, 7)]),
                ('line', [(17, 4), (20, 7), (17, 10)]), ('line', [(17, 14), (20, 17), (17, 20)])],
    'drag': [('line', [(5, 8), (19, 8)]), ('line', [(5, 12), (19, 12)]), ('line', [(5, 16), (19, 16)])],
    'clock': [('circle', 12, 12, 9), ('line', [(12, 7), (12, 12), (16, 14)])],
    'tune': [('line', [(4, 8), (20, 8)]), ('line', [(4, 16), (20, 16)]), ('dot', 9, 8, 2.6), ('dot', 15, 16, 2.6)],
    'move_top': [('line', [(5, 5), (19, 5)]), ('line', [(12, 20), (12, 9)]), ('line', [(7, 13), (12, 8), (17, 13)])],
    'move_bottom': [('line', [(5, 19), (19, 19)]), ('line', [(12, 4), (12, 15)]), ('line', [(7, 11), (12, 16), (17, 11)])],
    'info': [('circle', 12, 12, 9), ('line', [(12, 11), (12, 17)]), ('dot', 12, 7.5, 1.3)],
    'restore': [('line', _arc(12, 12, 8, 30, 320)), ('line', [(4, 3.5), (4, 8.5), (9, 8.5)]),
                ('line', [(12, 8), (12, 12), (15, 14)])],
    'up': [('line', [(6, 15), (12, 9), (18, 15)])],
    'down': [('line', [(6, 9), (12, 15), (18, 9)])],
    'bolt': [('fill', [(13, 3), (6, 13), (11, 13), (10, 21), (18, 10), (13, 10)])],
}


class Icon(Widget):
    name = StringProperty('play')
    color = ListProperty([1, 1, 1, 1])
    stroke = NumericProperty(2.0)       # in 24-grid units

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(24), dp(24)))
        super(Icon, self).__init__(**kw)
        self.bind(pos=self._draw, size=self._draw, name=self._draw, color=self._draw)
        self._draw()

    def _draw(self, *a):
        self.canvas.clear()
        ops = ICONS.get(self.name)
        if not ops or self.width < 2:
            return
        u = min(self.width, self.height) / 24.0
        ox = self.center_x - 12 * u
        oy = self.center_y - 12 * u

        def P(x, y):
            return ox + x * u, oy + (24 - y) * u
        lw = max(1.0, self.stroke * u)
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
                Color(1, 1, 1, 0.10)
                self._fb = Rectangle(pos=self.pos, size=self.size)

    def on_touch_down(self, touch):
        if self.disabled or not self.collide_point(*touch.pos):
            return False
        touch.grab(self)
        self._long_fired = False
        self._set_pressed(True)
        if self.long_callback:
            self._long_ev = Clock.schedule_once(self._long, 0.45)
        return True

    def _long(self, dt):
        self._long_ev = None
        if self.pressed:
            self._long_fired = True
            self._set_pressed(False)
            self.long_callback(self)

    def on_touch_move(self, touch):
        if touch.grab_current is self:
            if self.pressed and not self.collide_point(*touch.pos):
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
    def __init__(self, icon='play', callback=None, color=None, icon_size=None, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(48), dp(48)))
        super(IconButton, self).__init__(callback=callback, **kw)
        isz = icon_size or dp(24)
        self.icon = Icon(name=icon, size=(isz, isz), color=list(color or TEXT))
        self.add_widget(self.icon)
        self.bind(pos=self._sync, size=self._sync)
        self._sync()

    def _sync(self, *a):
        self.icon.center = self.center

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


class Switch(Tap):
    value = BooleanProperty(False)

    def __init__(self, value=False, on_change=None, **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(46), dp(28)))
        super(Switch, self).__init__(callback=self._toggle, **kw)
        self.on_change = on_change
        self.value = value
        self.bind(pos=self._draw, size=self._draw, value=self._draw)
        self._draw()

    def _toggle(self, *a):
        self.value = not self.value
        if self.on_change:
            self.on_change(self.value)

    def _set_pressed(self, v):
        self.pressed = v

    def _draw(self, *a):
        self.canvas.clear()
        h = self.height
        with self.canvas:
            Color(*(ACCENT if self.value else (0.35, 0.35, 0.37, 1)))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[h / 2.0])
            Color(1, 1, 1, 1)
            r = h * 0.38
            cx = self.right - h / 2.0 if self.value else self.x + h / 2.0
            Ellipse(pos=(cx - r, self.center_y - r), size=(2 * r, 2 * r))


class Chip(Tap):
    def __init__(self, label, selected=False, callback=None, **kw):
        kw.setdefault('height', dp(40))
        super(Chip, self).__init__(callback=callback, **kw)
        self.selected = selected
        self.label = Txt(ltext=label, halign='center', font_size=sp(15), bold=selected,
                         color=(0, 0, 0, 1) if selected else TEXT, size_hint=(None, None))
        self.add_widget(self.label)
        self.bind(pos=self._draw, size=self._draw)
        self._draw()

    def _draw(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*(ACCENT if self.selected else SURFACE2))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(10)])
        self.label.pos = self.pos
        self.label.size = self.size


# ---------------------------------------------------------------------------
# thumbnails
# ---------------------------------------------------------------------------
_tex_cache = OrderedDict()


def load_texture(path):
    tex = _tex_cache.get(path)
    if tex is not None:
        _tex_cache.move_to_end(path)
        return tex
    try:
        tex = CoreImage(path, nocache=True).texture
    except Exception:
        return None
    _tex_cache[path] = tex
    while len(_tex_cache) > 90:
        _tex_cache.popitem(last=False)
    return tex


class Thumb(Widget):
    """Rounded, centre-cropped picture with a dark placeholder."""

    def __init__(self, radius=None, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Thumb, self).__init__(**kw)
        self.radius = radius if radius is not None else dp(12)
        self.source = None
        self._tex = None
        self.bind(pos=self._draw, size=self._draw)

    def set_source(self, path):
        if path == self.source:
            return
        self.source = path
        self._tex = load_texture(path) if path else None
        self._draw()

    def _draw(self, *a):
        self.canvas.clear()
        if self.width < 2:
            return
        with self.canvas:
            Color(0.13, 0.13, 0.14, 1)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
            tex = self._tex
            if tex is not None:
                tw, th = tex.size
                if tw > 0 and th > 0:
                    target = self.width / float(self.height)
                    src = tw / float(th)
                    if src > target:
                        nw = th * target
                        reg = tex.get_region((tw - nw) / 2.0, 0, nw, th)
                    else:
                        nh = tw / target
                        reg = tex.get_region(0, (th - nh) / 2.0, tw, nh)
                    Color(1, 1, 1, 1)
                    RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius], texture=reg)


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

    def _frac(self, x):
        pad = dp(10)
        w = max(1.0, self.width - 2 * pad)
        return max(0.0, min(1.0, (x - self.x - pad) / w))

    def _draw(self, *a):
        self.canvas.clear()
        pad = dp(10)
        w = max(1.0, self.width - 2 * pad)
        th = dp(3.5) if not self.dragging else dp(5)
        y = self.center_y - th / 2.0
        v = max(0.0, min(1.0, self.value))
        with self.canvas:
            Color(1, 1, 1, 0.28)
            RoundedRectangle(pos=(self.x + pad, y), size=(w, th), radius=[th / 2.0])
            Color(*ACCENT)
            RoundedRectangle(pos=(self.x + pad, y), size=(max(th, w * v), th), radius=[th / 2.0])
            r = dp(8) if not self.dragging else dp(11)
            Color(*ACCENT)
            Ellipse(pos=(self.x + pad + w * v - r, self.center_y - r), size=(2 * r, 2 * r))

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
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(12)])
        self.ti = TextInput(text=text, multiline=False, write_tab=False,
                            background_normal='', background_active='', background_color=(0, 0, 0, 0),
                            foreground_color=(0, 0, 0, 0), cursor_color=(0, 0, 0, 0),
                            selection_color=(0, 0, 0, 0), hint_text='', size_hint=(1, 1))
        for attr, val in (('use_bubble', False), ('use_handles', False), ('keyboard_suggestions', False)):
            try:
                setattr(self.ti, attr, val)
            except Exception:
                pass
        self.shown = Txt(ltext=text or hint, color=TEXT if text else SUB, font_size=sp(17),
                         align_mode='auto', size_hint=(None, None))
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
        self._draw_caret()

    def _layout(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size
        pad = dp(16)
        self.shown.pos = (self.x + pad, self.y)
        self.shown.size = (self.width - 2 * pad, self.height)
        self.ti.pos = self.pos
        self.ti.size = self.size
        self._draw_caret()

    def _blink_tick(self, dt):
        self._caret_on = not self._caret_on
        self._draw_caret()

    def _draw_caret(self):
        self.canvas.after.clear()
        if not self.ti.focus or not self._caret_on:
            return
        txt = self.ti.text
        pad = dp(16)
        w = self.shown.text_width() if txt else 0
        rtl = textfix.is_rtl(txt) if txt else True
        if rtl:
            x = self.right - pad - w - dp(2)
        else:
            x = self.x + pad + w + dp(1)
        with self.canvas.after:
            Color(*ACCENT)
            Rectangle(pos=(x, self.center_y - dp(11)), size=(dp(2), dp(22)))


# ---------------------------------------------------------------------------
# virtualised list with selection + drag reordering
# ---------------------------------------------------------------------------
class Row(Widget):
    """Base class for list rows. Subclasses implement fill() and relayout()."""
    kind = 'row'

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Row, self).__init__(**kw)
        self.idx = -1
        self.item = None
        self.ctx = None
        self.ty = 0.0
        self.bind(pos=self._on_geom, size=self._on_geom)

    def _on_geom(self, *a):
        self.relayout()

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


class VList(StencilView):
    """Fixed-row-height virtualised list.

    owner callbacks (all optional)
        on_tap(idx, item, x)         short tap
        on_long(idx, item)           long press (selection starts here)
        on_reorder(src, dst)         drag finished
        can_drag(idx, item) -> bool
    """

    def __init__(self, row_factories, row_h=None, **kw):
        super(VList, self).__init__(**kw)
        self.factories = row_factories
        self.row_h = row_h or dp(96)
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

    def _release_all(self):
        for i, row in list(self.rows.items()):
            self.remove_widget(row)
            self.pools.setdefault(row.kind, []).append(row)
        self.rows = {}

    def max_scroll(self):
        return max(0.0, len(self.items) * self.row_h - self.height)

    def scroll_to(self, idx):
        self.scroll = max(0.0, min(self.max_scroll(), idx * self.row_h))
        self.relayout()

    # ---- layout ----------------------------------------------------------
    def _slot(self, i):
        d = self._drag
        if not d or i == d['from']:
            return i
        f, t = d['from'], d['to']
        if f < t and f < i <= t:
            return i - 1
        if f > t and t <= i < f:
            return i + 1
        return i

    def _acquire(self, i):
        item = self.items[i]
        kind = item.get('kind', 'row') if isinstance(item, dict) else 'row'
        pool = self.pools.setdefault(kind, [])
        row = pool.pop() if pool else self.factories[kind]()
        row.kind = kind
        row.size = (self.width, self.row_h)
        row.bind_item(item, i, self.ctx)
        self.add_widget(row)
        self.rows[i] = row
        return row

    def relayout(self, *a):
        n = len(self.items)
        rh = self.row_h
        if self.height <= 1:
            return
        self.scroll = max(0.0, min(self.scroll, self.max_scroll()))
        first = max(0, int(self.scroll // rh) - 1)
        last = min(n - 1, int((self.scroll + self.height) // rh) + 1)
        wanted = set(range(first, last + 1))
        if self._drag:
            wanted.add(self._drag['from'])
        for i in list(self.rows):
            if i not in wanted:
                row = self.rows.pop(i)
                self.remove_widget(row)
                self.pools.setdefault(row.kind, []).append(row)
        for i in wanted:
            row = self.rows.get(i)
            if row is None:
                row = self._acquire(i)
            if row.width != self.width or row.height != rh:
                row.size = (self.width, rh)
            slot = self._slot(i)
            row.ty = self.top - (slot + 1) * rh + self.scroll
            if self._drag and i == self._drag['from']:
                row.pos = (self.x, self._drag['y'])
            elif self._drag:
                if row.x != self.x:
                    row.x = self.x
                # smooth movement is handled by _drag_tick
                if abs(row.y - row.ty) > rh * 3:
                    row.y = row.ty
            else:
                row.pos = (self.x, row.ty)

    # ---- touch -------------------------------------------------------------
    def index_at(self, y):
        i = int((self.scroll + (self.top - y)) // self.row_h)
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
            self._fling = Clock.schedule_interval(self._fling_tick, 1 / 60.0)

    def _stop_fling(self):
        if self._fling is not None:
            self._fling.cancel()
            self._fling = None
        self._fling_v = 0.0

    def _fling_tick(self, dt):
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
        self._drag = {'from': idx, 'to': idx, 'y': row.y, 'touch_y': touch.y,
                      'off': touch.y - row.y}
        self.remove_widget(row)          # re-add so it is drawn above the others
        self.add_widget(row)
        row.opacity = 0.95
        if self._drag_ev is None:
            self._drag_ev = Clock.schedule_interval(self._drag_tick, 1 / 60.0)

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
        d['y'] = max(self.y - rh * 0.5, min(self.top - rh * 0.5, y - d['off']))
        center = d['y'] + rh / 2.0
        to = int((self.scroll + (self.top - center)) // rh)
        d['to'] = max(0, min(len(self.items) - 1, to))

    def _drag_tick(self, dt):
        d = self._drag
        if not d:
            return
        # auto scroll near the edges
        edge = dp(70)
        ty = d['touch_y']
        if ty > self.top - edge:
            self.scroll -= dp(9) * (1 + (ty - (self.top - edge)) / edge)
        elif ty < self.y + edge:
            self.scroll += dp(9) * (1 + ((self.y + edge) - ty) / edge)
        self.scroll = max(0.0, min(self.scroll, self.max_scroll()))
        self._update_drag_target()
        self.relayout()
        k = min(1.0, dt * 18.0)
        for i, row in self.rows.items():
            if i == d['from']:
                row.y = d['y']
            else:
                row.y += (row.ty - row.y) * k

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
        if self.cancelable:
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
        self.radius = radius or [dp(20)] * 4
        with self.canvas.before:
            Color(*SURFACE)
            self._bg = RoundedRectangle(pos=self.pos, size=self.size, radius=self.radius)
        self.bind(pos=self._geo, size=self._geo)

    def _geo(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size


class SheetRow(Tap):
    def __init__(self, label, icon=None, value=None, checked=False, danger=False, callback=None, **kw):
        kw.setdefault('height', dp(54))
        super(SheetRow, self).__init__(callback=callback, **kw)
        col = DANGER if danger else TEXT
        self.icon = Icon(name=icon, color=list(col), size=(dp(22), dp(22))) if icon else None
        self.lbl = Txt(ltext=label, color=col, font_size=sp(16), size_hint=(None, None))
        self.val = Txt(ltext=value or '', color=SUB, font_size=sp(14), halign='left', size_hint=(None, None))
        self.chk = Icon(name='check', color=list(ACCENT), size=(dp(22), dp(22))) if checked else None
        for w in (self.icon, self.lbl, self.val, self.chk):
            if w is not None:
                self.add_widget(w)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        pad = dp(18)
        right = self.right - pad
        if self.icon is not None:
            self.icon.center = (right - dp(11), self.center_y)
            right -= dp(40)
        left = self.x + pad
        if self.chk is not None:
            self.chk.center = (left + dp(11), self.center_y)
            left += dp(36)
        vw = dp(120) if self.val.ltext else 0
        self.val.pos = (left, self.y)
        self.val.size = (vw, self.height)
        self.lbl.pos = (left + vw + dp(6), self.y)
        self.lbl.size = (max(10, right - left - vw - dp(6)), self.height)


class SheetTitle(Widget):
    def __init__(self, text, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(56))
        super(SheetTitle, self).__init__(**kw)
        self.lbl = Txt(ltext=text, bold=True, font_size=sp(19), size_hint=(None, None))
        self.add_widget(self.lbl)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        self.lbl.pos = (self.x + dp(18), self.y)
        self.lbl.size = (self.width - dp(36), self.height)


class SheetLabel(Widget):
    def __init__(self, text, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(34))
        super(SheetLabel, self).__init__(**kw)
        self.lbl = Txt(ltext=text, color=SUB, font_size=sp(13), size_hint=(None, None))
        self.add_widget(self.lbl)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        self.lbl.pos = (self.x + dp(18), self.y)
        self.lbl.size = (self.width - dp(36), self.height)


class ChipsRow(Widget):
    """Wrapping grid of chips (used for the speed picker)."""

    def __init__(self, options, current, on_pick, cols=4, **kw):
        kw.setdefault('size_hint', (1, None))
        super(ChipsRow, self).__init__(**kw)
        self.cols = cols
        n = len(options)
        self.nrows = (n + cols - 1) // cols
        self.height = self.nrows * dp(48) + dp(8)
        self.chips = []
        for val, label in options:
            c = Chip(label, selected=(abs(float(val) - float(current)) < 1e-6),
                     callback=(lambda w, v=val: on_pick(v)), size_hint=(None, None))
            self.chips.append(c)
            self.add_widget(c)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        pad = dp(14)
        gap = dp(8)
        cw = (self.width - 2 * pad - gap * (self.cols - 1)) / float(self.cols)
        for i, c in enumerate(self.chips):
            r, col = divmod(i, self.cols)
            # RTL: first chip on the right
            x = self.right - pad - (col + 1) * cw - col * gap
            y = self.top - dp(4) - (r + 1) * dp(40) - r * dp(8)
            c.pos = (x, y)
            c.size = (cw, dp(40))


class MenuSheet(Overlay):
    """Bottom sheet (portrait) or side panel (landscape) with a scrolling list.

    build() is a function returning a list of widgets; call rebuild() to refresh."""

    def __init__(self, root, build, **kw):
        super(MenuSheet, self).__init__(root, **kw)
        self.build = build
        self.panel = Panel()
        self.add_widget(self.panel)
        self.sv = ScrollView(size_hint=(None, None), do_scroll_x=False, bar_width=dp(3))
        self.box = BoxLayout(orientation='vertical', size_hint_y=None, padding=[0, dp(4), 0, dp(10)])
        self.box.bind(minimum_height=self.box.setter('height'))
        self.sv.add_widget(self.box)
        self.panel.add_widget(self.sv)
        self.content_h = dp(14)
        self.rebuild()

    def rebuild(self):
        self.box.clear_widgets()
        widgets = self.build()
        total = dp(14)
        for w in widgets:
            w.size_hint = (1, None)
            total += w.height
            self.box.add_widget(w)
        self.content_h = total
        self._ready = True
        self.place()

    def place(self):
        W, H = self.width, self.height
        if W <= 1 or H <= 1 or not getattr(self, '_ready', False):
            return
        if W > H:
            pw = min(dp(420), W * 0.55)
            ph = H
            self.panel.radius = [dp(20), 0, 0, dp(20)]
            self.panel.pos = (self.right - pw, self.y)
        else:
            pw = min(W, dp(520))
            ph = min(self.content_h + dp(8), H * 0.82)
            self.panel.radius = [dp(22), dp(22), 0, 0]
            self.panel.pos = (self.center_x - pw / 2.0, self.y)
        self.panel._bg.radius = self.panel.radius
        self.panel.size = (pw, ph)
        self.sv.pos = self.panel.pos
        self.sv.size = self.panel.size


class Dialog(Overlay):
    def __init__(self, root, title, message='', buttons=None, **kw):
        super(Dialog, self).__init__(root, **kw)
        self.extra = None
        self.panel = Panel(radius=[dp(20)] * 4)
        self.add_widget(self.panel)
        self.title = Txt(ltext=title, bold=True, font_size=sp(19), size_hint=(None, None))
        self.msg = Txt(ltext=message, color=SUB, font_size=sp(15), nlines=6, keep_nl=True,
                       valign='top', size_hint=(None, None))
        self.panel.add_widget(self.title)
        self.panel.add_widget(self.msg)
        self.btns = []
        for label, cb, kind in (buttons or [('حسناً', None, 'primary')]):
            b = Tap(callback=(lambda w, cb=cb: self._press(cb)), size_hint=(None, None), height=dp(46))
            b.kind = kind
            b.lbl = Txt(ltext=label, halign='center', bold=(kind != 'plain'), font_size=sp(16),
                        color=(DANGER if kind == 'danger' else ACCENT if kind == 'primary' else TEXT),
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
        self.panel.add_widget(widget)
        self.place()

    def place(self):
        W = self.width
        if W <= 1 or not hasattr(self, 'btns'):
            return
        pw = min(W - dp(32), dp(420))
        pad = dp(20)
        msg_lines = 0
        if self.msg.ltext:
            msg_lines = min(6, max(1, int(self.msg.ltext.count('\n') + 1 + len(self.msg.ltext) / 34.0)))
        mh = msg_lines * sp(15) * 1.5 if self.msg.ltext else 0
        eh = (self.extra.height + dp(10)) if self.extra is not None else 0
        ph = pad + dp(32) + dp(8) + mh + eh + dp(14) + dp(46) + dp(10)
        px = self.center_x - pw / 2.0
        if self.extra is not None:
            py = self.top - dp(120) - ph       # keep clear of the keyboard
            py = max(self.y + dp(8), py)
        else:
            py = self.center_y - ph / 2.0
        self.panel.pos = (px, py)
        self.panel.size = (pw, ph)
        y = py + ph - pad - dp(32)
        self.title.pos = (px + pad, y)
        self.title.size = (pw - 2 * pad, dp(32))
        y -= dp(8) + mh
        self.msg.pos = (px + pad, y)
        self.msg.size = (pw - 2 * pad, mh)
        if self.extra is not None:
            y -= eh
            self.extra.pos = (px + pad, y + dp(5))
            self.extra.width = pw - 2 * pad
        n = len(self.btns)
        bw = (pw - 2 * pad - dp(8) * (n - 1)) / float(n)
        for i, b in enumerate(self.btns):
            # first button on the right
            b.pos = (px + pw - pad - (i + 1) * bw - i * dp(8), py + dp(10))
            b.size = (bw, dp(46))
            b.lbl.pos = b.pos
            b.lbl.size = b.size


class PromptDialog(Dialog):
    auto_dismiss = False

    def __init__(self, root, title, text='', hint='', ok_label='حفظ', on_ok=None, message='', **kw):
        self._on_ok = on_ok
        super(PromptDialog, self).__init__(
            root, title, message,
            buttons=[(ok_label, self._submit_btn, 'primary'), ('إلغاء', None, 'plain')], **kw)
        self.field = FieldInput(text=text, hint=hint, on_submit=self._submit_text)
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
        self.size = (w, dp(54) if len(text) > 32 else dp(42))
        self.pos = ((W - w) / 2.0, bottom)
        self.lbl.ltext = text
        self.lbl.pos = (self.x + dp(12), self.y)
        self.lbl.size = (self.width - dp(24), self.height)
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.2, 0.2, 0.22, 0.97)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(21)])
        self.opacity = 1
        if self._ev:
            self._ev.cancel()
        self._ev = Clock.schedule_once(self._hide, 2.2)

    def _hide(self, dt):
        self.opacity = 0
