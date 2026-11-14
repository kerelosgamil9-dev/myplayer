# -*- coding: utf-8 -*-
"""
screens.py - navigation root, rows, home page (playlists / folders / videos /
history / me), collection page and the video picker.
"""
from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

import bridge
import core
import textfix
from widgets import (ACCENT, BG, DANGER, DIVIDER, SUB, SURFACE, SURFACE2, TEXT, ChipsRow, Dialog,
                     FieldInput, Icon, IconButton, MenuSheet, PromptDialog, Row, SheetLabel,
                     SheetRow, SheetTitle, Switch, Tap, Thumb, Toast, Txt, VList)


# ---------------------------------------------------------------------------
# root / pages
# ---------------------------------------------------------------------------
class Page(FloatLayout):
    """Full screen page with an opaque black background."""

    def __init__(self, app, **kw):
        kw.setdefault('size_hint', (1, 1))
        super(Page, self).__init__(**kw)
        self.app = app
        with self.canvas.before:
            Color(*BG)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._bg_geo, size=self._bg_geo)

    def _bg_geo(self, *a):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def on_touch_down(self, touch):
        FloatLayout.on_touch_down(self, touch)
        return True          # pages are opaque: nothing below may react

    def on_touch_move(self, touch):
        FloatLayout.on_touch_move(self, touch)
        return True

    def on_touch_up(self, touch):
        FloatLayout.on_touch_up(self, touch)
        return True

    def on_back(self):
        return False

    def on_show(self):
        pass

    def on_close(self):
        pass

    def refresh(self):
        pass


class Root(FloatLayout):
    def __init__(self, app, **kw):
        super(Root, self).__init__(**kw)
        self.app = app
        self.pages = []
        self.overlays = []
        self.toast = Toast()
        self.add_widget(self.toast)

    def _raise_layers(self):
        for ov in self.overlays:
            self.remove_widget(ov)
            self.add_widget(ov)
        self.remove_widget(self.toast)
        self.add_widget(self.toast)

    def push(self, page):
        self.pages.append(page)
        self.add_widget(page)
        self._raise_layers()
        page.on_show()

    def pop(self):
        if len(self.pages) <= 1:
            return False
        page = self.pages.pop()
        try:
            page.on_close()
        finally:
            self.remove_widget(page)
        if self.pages:
            self.pages[-1].refresh()
            self.pages[-1].on_show()
        return True

    def show_overlay(self, ov):
        if ov in self.overlays:
            return
        self.overlays.append(ov)
        self.add_widget(ov)
        self._raise_layers()

    def dismiss_overlay(self, ov):
        if ov in self.overlays:
            self.overlays.remove(ov)
            self.remove_widget(ov)

    def back(self):
        """Android back button. Returns True when handled."""
        if self.overlays:
            self.overlays[-1].on_back()
            return True
        if self.pages and self.pages[-1].on_back():
            return True
        if len(self.pages) > 1:
            self.pop()
            return True
        return False

    def say(self, text):
        self.toast.show(text, self.size)

    def refresh_pages(self):
        for p in self.pages:
            p.refresh()


# ---------------------------------------------------------------------------
# shared context for rows
# ---------------------------------------------------------------------------
class Ctx(object):
    def __init__(self, app):
        self.app = app
        self.sel_mode = False
        self.selected = set()
        self.reorder = False
        self.show_path = False

    @property
    def lib(self):
        return self.app.lib


def _draw_check(canvas, cx, cy, r, selected):
    with canvas:
        if selected:
            Color(*ACCENT)
            Ellipse(pos=(cx - r, cy - r), size=(2 * r, 2 * r))
            Color(0, 0, 0, 1)
            Line(points=[cx - r * 0.45, cy, cx - r * 0.1, cy - r * 0.38, cx + r * 0.5, cy + r * 0.42],
                 width=dp(1.8), cap='round', joint='round')
        else:
            Color(1, 1, 1, 0.5)
            Line(circle=(cx, cy, r), width=dp(1.4))


class ListRow(Row):
    """Common behaviour: selection background + check circle + drag handle."""

    def __init__(self, **kw):
        super(ListRow, self).__init__(**kw)
        self.handle = Icon(name='drag', color=[1, 1, 1, 0.55], size=(dp(24), dp(24)))
        self.add_widget(self.handle)
        self._thumb_key = None

    def is_selected(self):
        return bool(self.ctx and self.item and self.ctx.sel_mode and self._sel_id() in self.ctx.selected)

    def _sel_id(self):
        return None

    def hit_handle(self, x):
        return bool(self.ctx and self.ctx.sel_mode and self.ctx.reorder and x < self.x + dp(100))

    def left_bound(self):
        if self.ctx and self.ctx.sel_mode:
            return self.x + (dp(100) if self.ctx.reorder else dp(60))
        return self.x + dp(16)

    def draw_selection(self):
        self.canvas.before.clear()
        ctx = self.ctx
        if not ctx or not ctx.sel_mode:
            self.handle.opacity = 0
            return
        sel = self.is_selected()
        with self.canvas.before:
            if sel:
                Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.13)
                Rectangle(pos=self.pos, size=self.size)
        _draw_check(self.canvas.before, self.x + dp(30), self.center_y, dp(11), sel)
        if ctx.reorder:
            self.handle.opacity = 1
            self.handle.center = (self.x + dp(72), self.center_y)
        else:
            self.handle.opacity = 0

    def set_thumb_for(self, thumb, key):
        self._thumb_key = key
        app = self.ctx.app
        if key is None:
            thumb.set_source(None)
            return

        def got(path, k=key):
            if self._thumb_key == k and self.item is not None:
                thumb.set_source(path)
        thumb.set_source(app.thumb(key, got))


class VideoRow(ListRow):
    kind = 'video'

    def __init__(self, **kw):
        super(VideoRow, self).__init__(**kw)
        self.thumb = Thumb(radius=dp(10), size=(dp(128), dp(72)))
        self.title = Txt(font_size=sp(16), nlines=2, valign='bottom', size_hint=(None, None))
        self.info = Txt(font_size=sp(13), color=SUB, valign='top', size_hint=(None, None))
        self.badge = Txt(font_size=sp(11), halign='center', size_hint=(None, None))
        for w in (self.thumb, self.title, self.info, self.badge):
            self.add_widget(w)
        self.frac = 0.0

    def _sel_id(self):
        return self.item.get('key')

    def fill(self, item, idx, ctx):
        lib = ctx.lib
        key = item['key']
        v = lib.videos.get(key, {})
        self.title.ltext = lib.title(key)
        dur = v.get('duration', 0) or lib.progress(key).get('dur', 0)
        parts = []
        if v.get('size'):
            parts.append(core.fmt_size(v['size']))
        if v.get('w') and v.get('h'):
            parts.append('%dp' % min(v['w'], v['h']))
        self.frac = lib.watched_fraction(key)
        if self.frac > 0.02:
            parts.append('%d%%' % int(self.frac * 100))
        self.info.ltext = '  •  '.join(parts)
        self.badge.ltext = core.fmt_time(dur) if dur else ''
        self.set_thumb_for(self.thumb, key)

    def relayout(self):
        if self.item is None or self.ctx is None:
            return
        self.draw_selection()
        tw, th = dp(128), dp(72)
        self.thumb.size = (tw, th)
        self.thumb.pos = (self.right - dp(16) - tw, self.center_y - th / 2.0)
        left = self.left_bound()
        tx_right = self.thumb.x - dp(12)
        w = max(10, tx_right - left)
        self.title.pos = (left, self.center_y)
        self.title.size = (w, th / 2.0 + dp(6))
        self.info.pos = (left, self.center_y - th / 2.0 + dp(2))
        self.info.size = (w, th / 2.0 - dp(8))
        bw = dp(46) if self.badge.ltext else 0
        self.badge.size = (bw, dp(18))
        self.badge.pos = (self.thumb.x + dp(6), self.thumb.y + dp(5))
        self.canvas.after.clear()
        with self.canvas.after:
            if self.badge.ltext:
                Color(0, 0, 0, 0.72)
                RoundedRectangle(pos=self.badge.pos, size=self.badge.size, radius=[dp(5)])
            if self.frac > 0.02:
                Color(1, 1, 1, 0.3)
                Rectangle(pos=(self.thumb.x, self.thumb.y), size=(tw, dp(3)))
                Color(*ACCENT)
                Rectangle(pos=(self.thumb.x, self.thumb.y), size=(tw * min(1.0, self.frac), dp(3)))


class CollRow(ListRow):
    kind = 'coll'

    def __init__(self, **kw):
        super(CollRow, self).__init__(**kw)
        self.thumb = Thumb(radius=dp(14), size=(dp(142), dp(80)))
        self.title = Txt(font_size=sp(18), valign='bottom', size_hint=(None, None))
        self.info = Txt(font_size=sp(14), color=SUB, valign='top', size_hint=(None, None))
        for w in (self.thumb, self.title, self.info):
            self.add_widget(w)

    def _sel_id(self):
        return self.item['coll'].id

    def fill(self, item, idx, ctx):
        c = item['coll']
        self.title.ltext = c.name
        sub = core.count_videos_label(c.count)
        if ctx.show_path and c.path:
            sub = sub + '  •  ' + c.path
        self.info.ltext = sub
        self.set_thumb_for(self.thumb, ctx.lib.cover_key(c.keys))

    def relayout(self):
        if self.item is None or self.ctx is None:
            return
        self.draw_selection()
        tw, th = dp(142), dp(80)
        self.thumb.size = (tw, th)
        self.thumb.pos = (self.right - dp(16) - tw, self.center_y - th / 2.0 - dp(3))
        left = self.left_bound()
        w = max(10, self.thumb.x - dp(14) - left)
        self.title.pos = (left, self.center_y)
        self.title.size = (w, dp(30))
        self.info.pos = (left, self.center_y - dp(30))
        self.info.size = (w, dp(30))
        self.canvas.after.clear()
        with self.canvas.after:               # the "stack" strip above the cover
            Color(0.32, 0.32, 0.33, 1)
            RoundedRectangle(pos=(self.thumb.x + dp(12), self.thumb.top - dp(1)),
                             size=(tw - dp(24), dp(8)), radius=[dp(5), dp(5), 0, 0])


class CreateRow(Row):
    kind = 'create'

    def __init__(self, **kw):
        super(CreateRow, self).__init__(**kw)
        self.label = Txt(ltext='إنشاء قائمة التشغيل الخاصة بك', font_size=sp(17), size_hint=(None, None))
        self.plus = Icon(name='plus', color=[0.35, 0.35, 0.37, 1], size=(dp(40), dp(40)), stroke=1.4)
        self.add_widget(self.label)
        self.add_widget(self.plus)

    def relayout(self):
        tw, th = dp(142), dp(80)
        x = self.right - dp(16) - tw
        y = self.center_y - th / 2.0 - dp(3)
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.32, 0.32, 0.33, 1)
            RoundedRectangle(pos=(x + dp(12), y + th - dp(1)), size=(tw - dp(24), dp(8)),
                             radius=[dp(5), dp(5), 0, 0])
            Color(0.87, 0.87, 0.88, 1)
            RoundedRectangle(pos=(x, y), size=(tw, th), radius=[dp(14)])
        self.plus.center = (x + tw / 2.0, y + th / 2.0)
        self.label.pos = (self.x + dp(16), self.center_y - dp(20))
        self.label.size = (x - dp(14) - self.x - dp(16), dp(40))


ROW_FACTORIES = {'video': VideoRow, 'coll': CollRow, 'create': CreateRow}


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
class Header(Widget):
    def __init__(self, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(60))
        super(Header, self).__init__(**kw)
        self.title = Txt(bold=True, font_size=sp(20), size_hint=(None, None))
        self.sub = Txt(color=SUB, font_size=sp(12.5), size_hint=(None, None))
        self.add_widget(self.title)
        self.add_widget(self.sub)
        self.right_btns = []
        self.left_btns = []
        self.extra = None
        self.big = False
        self.bind(pos=self._lay, size=self._lay)

    def set(self, title, sub='', right=(), left=(), big=False, extra=None):
        for b in self.right_btns + self.left_btns:
            if b.parent is self:
                self.remove_widget(b)
        if self.extra is not None and self.extra.parent is self:
            self.remove_widget(self.extra)
        self.right_btns, self.left_btns = list(right), list(left)
        self.extra = extra
        for b in self.right_btns + self.left_btns:
            self.add_widget(b)
        if extra is not None:
            self.add_widget(extra)
        self.big = big
        self.title.ltext = title
        self.title.font_size = sp(30) if big else sp(19)
        self.sub.ltext = sub
        self._lay()

    def _lay(self, *a):
        x_r = self.right - dp(6)
        for b in self.right_btns:
            b.pos = (x_r - b.width, self.center_y - b.height / 2.0)
            x_r -= b.width
        x_l = self.x + dp(6)
        for b in self.left_btns:
            b.pos = (x_l, self.center_y - b.height / 2.0)
            x_l += b.width
        if not self.right_btns:
            x_r = self.right - dp(16)
        if self.extra is not None:
            self.extra.pos = (x_l + dp(4), self.center_y - self.extra.height / 2.0)
            self.extra.width = max(10, x_r - x_l - dp(10))
            self.title.size = (0, 0)
            self.sub.size = (0, 0)
            return
        w = max(10, x_r - x_l - dp(8))
        if self.sub.ltext:
            self.title.pos = (x_l + dp(4), self.center_y - dp(2))
            self.title.size = (w, dp(28))
            self.sub.pos = (x_l + dp(4), self.center_y - dp(26))
            self.sub.size = (w, dp(24))
        else:
            self.title.pos = (x_l + dp(4), self.y + (dp(4) if self.big else 0))
            self.title.size = (w, self.height - (dp(4) if self.big else 0))
            self.sub.size = (0, 0)


# ---------------------------------------------------------------------------
# helpers shared by pages: dialogs for common actions
# ---------------------------------------------------------------------------
def confirm(app, title, message, ok_label, on_ok, danger=True):
    Dialog(app.root, title, message,
           [(ok_label, on_ok, 'danger' if danger else 'primary'), ('إلغاء', None, 'plain')]).show()


def ask_text(app, title, text, hint, on_ok, ok_label='حفظ'):
    PromptDialog(app.root, title, text=text, hint=hint, ok_label=ok_label, on_ok=on_ok).show()


def choose_playlist(app, keys, after=None):
    """Sheet: add the given video keys to a playlist (or a new one)."""
    lib = app.lib

    def done(msg):
        app.root.say(msg)
        if after:
            after()
        app.root.refresh_pages()

    def build():
        rows = [SheetTitle('إضافة إلى قائمة تشغيل'),
                SheetRow('قائمة تشغيل جديدة', icon='plus', callback=lambda w: new())]
        for c in lib.collections():
            if c.kind == 'custom':
                rows.append(SheetRow(c.name, icon='playlist',
                                     value=core.count_videos_label(c.count),
                                     callback=lambda w, cid=c.id, nm=c.name: pick(cid, nm)))
        return rows
    sheet = MenuSheet(app.root, build)

    def pick(cid, name):
        sheet.dismiss()
        n = lib.add_to_playlist(cid, keys)
        done('تمت إضافة %d فيديو إلى «%s»' % (n, name))

    def new():
        sheet.dismiss()

        def ok(name):
            cid = lib.create_playlist(name, keys)
            done('تم إنشاء «%s» (%d فيديو)' % (lib.collection(cid).name, len(keys)))
        ask_text(app, 'قائمة تشغيل جديدة', '', 'اسم القائمة', ok, 'إنشاء')
    sheet.show()


def sort_sheet(app, title, modes, get_state, set_state, extra=None):
    """Generic 'sort by' sheet. get_state() -> (mode, asc); set_state(mode, asc)."""
    def build():
        mode, asc = get_state()
        rows = [SheetTitle(title)]
        for m in modes:
            rows.append(SheetRow(core.SORT_LABELS.get(m, m), checked=(m == mode),
                                 callback=lambda w, m=m: pick(m)))
        if mode != 'manual':
            rows.append(SheetLabel('الاتجاه'))
            rows.append(SheetRow('تصاعدي', icon='up', checked=asc, callback=lambda w: setd(True)))
            rows.append(SheetRow('تنازلي', icon='down', checked=not asc, callback=lambda w: setd(False)))
        return rows
    sheet = MenuSheet(app.root, build)

    def pick(m):
        _, asc = get_state()
        set_state(m, asc if m != 'manual' else True)
        sheet.rebuild()

    def setd(a):
        m, _ = get_state()
        set_state(m, a)
        sheet.rebuild()
    sheet.show()
    return sheet


def selection_keys(ctx, lib):
    return [k for k in ctx.selected if k in lib.videos]


# ---------------------------------------------------------------------------
# tab bar + nav bar
# ---------------------------------------------------------------------------
class TabBar(Widget):
    def __init__(self, tabs, on_pick, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(48))
        super(TabBar, self).__init__(**kw)
        self.tabs = tabs                  # [(id, label)] in display order: first = rightmost
        self.on_pick = on_pick
        self.current = tabs[0][0]
        self.labels = {}
        for tid, label in tabs:
            t = Txt(ltext=label, font_size=sp(17), size_hint=(None, None), halign='center')
            self.labels[tid] = t
            self.add_widget(t)
        self.bind(pos=self._lay, size=self._lay)

    def set_current(self, tid):
        self.current = tid
        self._lay()

    def _lay(self, *a):
        self.canvas.clear()
        x = self.right - dp(24)
        self._hit = []
        with self.canvas:
            for tid, label in self.tabs:
                t = self.labels[tid]
                tw = max(dp(30), t.text_width())
                t.size = (tw + dp(4), self.height - dp(6))
                t.pos = (x - t.width, self.y + dp(6))
                active = tid == self.current
                t.color = ACCENT if active else (0.7, 0.7, 0.72, 1)
                if active:
                    Color(*ACCENT)
                    RoundedRectangle(pos=(t.x, self.y), size=(t.width, dp(3)), radius=[dp(1.5)])
                self._hit.append((t.x - dp(10), t.right + dp(10), tid))
                x = t.x - dp(26)

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        for x0, x1, tid in self._hit:
            if x0 <= touch.x <= x1:
                if tid != self.current:
                    self.on_pick(tid)
                return True
        return True


class NavBar(Widget):
    def __init__(self, items, on_pick, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(60))
        super(NavBar, self).__init__(**kw)
        self.items = items               # [(id, icon, label)] first = rightmost
        self.on_pick = on_pick
        self.current = items[0][0]
        self.icons, self.labels = {}, {}
        for nid, icon, label in items:
            ic = Icon(name=icon, size=(dp(26), dp(26)))
            lb = Txt(ltext=label, font_size=sp(12), halign='center', size_hint=(None, None))
            self.icons[nid], self.labels[nid] = ic, lb
            self.add_widget(ic)
            self.add_widget(lb)
        self.bind(pos=self._lay, size=self._lay)

    def set_current(self, nid):
        self.current = nid
        self._lay()

    def _lay(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0.12, 0.12, 0.125, 1)
            Rectangle(pos=self.pos, size=self.size)
        n = len(self.items)
        cw = self.width / float(n)
        for i, (nid, icon, label) in enumerate(self.items):
            cx = self.right - cw * (i + 0.5)
            ic, lb = self.icons[nid], self.labels[nid]
            col = ACCENT if nid == self.current else (0.62, 0.62, 0.64, 1)
            ic.color = list(col)
            lb.color = col
            ic.center = (cx, self.y + self.height - dp(18))
            lb.size = (cw, dp(18))
            lb.pos = (cx - cw / 2.0, self.y + dp(5))

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        n = len(self.items)
        i = int((self.right - touch.x) // (self.width / float(n)))
        i = max(0, min(n - 1, i))
        self.on_pick(self.items[i][0])
        return True


# ---------------------------------------------------------------------------
# settings pane
# ---------------------------------------------------------------------------
class SwitchRow(Widget):
    def __init__(self, label, value, on_change, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(56))
        super(SwitchRow, self).__init__(**kw)
        self.lbl = Txt(ltext=label, font_size=sp(16), size_hint=(None, None))
        self.sw = Switch(value=value, on_change=on_change)
        self.add_widget(self.lbl)
        self.add_widget(self.sw)
        self.bind(pos=self._lay, size=self._lay)

    def _lay(self, *a):
        self.sw.pos = (self.x + dp(18), self.center_y - self.sw.height / 2.0)
        self.lbl.pos = (self.x + dp(18) + self.sw.width + dp(10), self.y)
        self.lbl.size = (self.width - dp(36) - self.sw.width - dp(10), self.height)

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if self.sw.on_touch_down(touch):
                return True
            self.sw._toggle()
            return True
        return False


class SettingsPane(FloatLayout):
    def __init__(self, app, **kw):
        super(SettingsPane, self).__init__(**kw)
        self.app = app
        self.sv = ScrollView(size_hint=(1, 1), do_scroll_x=False, bar_width=dp(3))
        self.box = BoxLayout(orientation='vertical', size_hint_y=None)
        self.box.bind(minimum_height=self.box.setter('height'))
        self.sv.add_widget(self.box)
        self.add_widget(self.sv)
        self.build()

    def S(self, key):
        return self.app.store.setting(key)

    def put(self, key, value):
        self.app.store.set_setting(key, value)

    def build(self):
        a, lib = self.app, self.app.lib
        box = self.box
        box.clear_widgets()
        n_vid = len(lib.videos)
        n_pl = len([c for c in lib.collections()])
        box.add_widget(SheetLabel('%d فيديو  •  %d قائمة تشغيل' % (n_vid, n_pl)))
        box.add_widget(SheetLabel('التشغيل'))
        for key, label in (('resume', 'استكمال من آخر مكان توقفت عنده'),
                           ('autoplay_next', 'تشغيل الفيديو التالي تلقائياً'),
                           ('gestures', 'إيماءات السحب (تقديم / سطوع / صوت)'),
                           ('keep_awake', 'إبقاء الشاشة مضاءة أثناء التشغيل'),
                           ('auto_rotate', 'تدوير الشاشة تلقائياً حسب الفيديو'),
                           ('sub_on', 'تشغيل الترجمة تلقائياً إن وجدت'),
                           ('vibrate', 'اهتزاز عند التحديد')):
            box.add_widget(SwitchRow(label, bool(self.S(key)), lambda v, k=key: self.put(k, v)))
        box.add_widget(SheetLabel('المظهر'))
        box.add_widget(SwitchRow('إظهار الصور المصغرة', bool(self.S('show_thumbs')),
                                 lambda v: (self.put('show_thumbs', v), a.root.refresh_pages())))
        box.add_widget(SheetLabel('خيارات'))
        box.add_widget(SheetRow('السرعة عند الضغط المطول', icon='speed',
                                value=core.fmt_speed(self.S('hold_speed')),
                                callback=lambda w: self.pick_number('hold_speed', 'السرعة عند الضغط المطول',
                                                                    [1.5, 2.0, 2.5, 3.0], core.fmt_speed)))
        box.add_widget(SheetRow('مدة التقديم / الترجيع', icon='fwd', value='%d ث' % self.S('seek_step'),
                                callback=lambda w: self.pick_number('seek_step', 'مدة التقديم / الترجيع',
                                                                    [5, 10, 15, 30], lambda x: '%d ث' % x)))
        box.add_widget(SheetRow('حجم الترجمة', icon='subtitle', value=str(self.S('sub_size')),
                                callback=lambda w: self.pick_number('sub_size', 'حجم الترجمة',
                                                                    [16, 20, 22, 26, 30, 36], str)))
        box.add_widget(SheetLabel('البيانات'))
        box.add_widget(SheetRow('إظهار القوائم المخفية', icon='restore', callback=lambda w: self.restore()))
        box.add_widget(SheetRow('مسح الصور المصغرة', icon='trash', callback=lambda w: self.clear_thumbs()))
        box.add_widget(SheetRow('مسح سجل المشاهدة', icon='clock', callback=lambda w: self.clear_hist()))
        box.add_widget(SheetRow('إعادة فحص الفيديوهات', icon='rotate', callback=lambda w: a.rescan(True)))
        box.add_widget(SheetLabel('Pro Player  •  تشغيل الفيديو بالسرعات والترتيب الذي تريده'))

    def pick_number(self, key, title, options, fmt):
        cur = self.S(key)

        def build():
            rows = [SheetTitle(title)]
            for o in options:
                rows.append(SheetRow(fmt(o), checked=abs(float(o) - float(cur)) < 1e-6,
                                     callback=lambda w, o=o: pick(o)))
            return rows
        sheet = MenuSheet(self.app.root, build)

        def pick(o):
            sheet.dismiss()
            self.put(key, o)
            self.build()
        sheet.show()

    def restore(self):
        self.app.lib.restore_hidden()
        self.app.root.say('تمت إعادة القوائم المخفية')
        self.app.root.refresh_pages()

    def clear_thumbs(self):
        n = self.app.thumbs.clear_cache()
        self.app.root.say('تم مسح %d صورة مصغرة' % n)
        self.app.root.refresh_pages()

    def clear_hist(self):
        def ok():
            for k in list(self.app.store.data['progress']):
                self.app.lib.clear_progress(k)
            self.app.root.say('تم مسح السجل')
            self.app.root.refresh_pages()
        confirm(self.app, 'مسح السجل', 'سيتم مسح سجل المشاهدة وأماكن الاستكمال.', 'مسح', ok)


# ---------------------------------------------------------------------------
# list-page mixin: selection mode handling shared by Home / Collection / Picker
# ---------------------------------------------------------------------------
class ListPageMixin(object):
    def init_list(self):
        self.ctx = Ctx(self.app)
        self.vlist = VList(ROW_FACTORIES, row_h=dp(100))
        self.vlist.ctx = self.ctx
        self.vlist.on_tap = self._tap
        self.vlist.on_long = self._long
        self.vlist.on_reorder = self._reorder
        self.vlist.can_drag = self._can_drag

    # overridables
    def open_item(self, idx, item):
        pass

    def item_id(self, item):
        k = item.get('kind')
        if k == 'video':
            return item['key']
        if k == 'coll':
            return item['coll'].id
        return None

    def selectable(self, item):
        return self.item_id(item) is not None

    def on_selection_changed(self):
        pass

    def _can_drag(self, idx, item):
        return self.selectable(item) and self.ctx.reorder

    def _reorder(self, src, dst):
        pass

    def _tap(self, idx, item, x):
        if self.ctx.sel_mode:
            sid = self.item_id(item)
            if sid is None:
                return
            if sid in self.ctx.selected:
                self.ctx.selected.discard(sid)
            else:
                self.ctx.selected.add(sid)
            if not self.ctx.selected:
                self.exit_selection()
            else:
                self.vlist.refresh()
                self.on_selection_changed()
        else:
            self.open_item(idx, item)

    def _long(self, idx, item):
        if not self.selectable(item):
            return
        bridge.vibrate(30) if self.app.store.setting('vibrate') else None
        self.ctx.sel_mode = True
        self.ctx.selected.add(self.item_id(item))
        self.vlist.refresh()
        self.on_selection_changed()

    def exit_selection(self):
        self.ctx.sel_mode = False
        self.ctx.selected.clear()
        self.vlist.refresh()
        self.on_selection_changed()

    def select_all(self):
        ids = [self.item_id(i) for i in self.vlist.items if self.selectable(i)]
        if len(self.ctx.selected) >= len(ids):
            self.ctx.selected.clear()
            self.exit_selection()
            return
        self.ctx.selected = set(ids)
        self.vlist.refresh()
        self.on_selection_changed()


# ---------------------------------------------------------------------------
# shared actions on videos
# ---------------------------------------------------------------------------
def rename_video_dialog(app, key, after):
    lib = app.lib

    def ok(name):
        lib.rename_video(key, name)
        after()
    ask_text(app, 'تعديل الاسم', lib.title(key), 'اسم الفيديو', ok)


def delete_videos_dialog(app, keys, after):
    lib = app.lib
    vids = [lib.videos[k] for k in keys if k in lib.videos]
    if not vids:
        return

    def run():
        def done(paths):
            if paths:
                lib.forget_videos(paths)
                app.root.say('تم حذف %d فيديو من الجهاز' % len(paths))
            else:
                app.root.say('لم يتم حذف أي ملف')
            app.store.save()
            after()
        bridge.delete_videos(vids, done)
    confirm(app, 'حذف من الجهاز',
            'سيتم حذف %d فيديو نهائياً من الجهاز ولا يمكن التراجع.' % len(vids), 'حذف', run)


# ---------------------------------------------------------------------------
# Home page
# ---------------------------------------------------------------------------
class HomePage(Page, ListPageMixin):
    TABS = [('videos', 'مقاطع فيديو'), ('folders', 'المجلدات'), ('playlists', 'قوائم التشغيل')]
    NAVS = [('library', 'folder_play', 'على الجهاز'), ('history', 'clock', 'السجل'), ('me', 'person', 'أنا')]

    def __init__(self, app, **kw):
        super(HomePage, self).__init__(app, **kw)
        self.init_list()
        self.mode = 'playlists'
        self.nav = 'library'
        self.query = ''
        self.search_on = False
        self.field = None
        self.header = Header()
        self.tabs = TabBar(self.TABS, self.set_tab)
        self.tabs.set_current(self.mode)
        self.navbar = NavBar(self.NAVS, self.set_nav)
        self.me = SettingsPane(app)
        self.empty = Txt(ltext='', halign='center', color=SUB, font_size=sp(16), nlines=3,
                         size_hint=(None, None))
        for w in (self.vlist, self.header, self.tabs, self.navbar, self.empty):
            self.add_widget(w)
        self.btn_search = IconButton('search', callback=lambda w: self.toggle_search(True))
        self.btn_sort = IconButton('sort', callback=lambda w: self.open_sort())
        self.btn_close = IconButton('close', callback=lambda w: self.exit_selection())
        self.bind(pos=self._lay, size=self._lay)
        self._lay()
        self.update_header()

    # ---- layout ------------------------------------------------------------
    def _lay(self, *a):
        W, H = self.size
        nb = dp(60)
        self.navbar.size = (W, nb)
        self.navbar.pos = (self.x, self.y)
        hh = dp(72) if (self.nav == 'library' and not self.ctx.sel_mode) else dp(60)
        self.header.size = (W, hh)
        self.header.pos = (self.x, self.top - hh)
        top = self.header.y
        if self.nav == 'library':
            self.tabs.size = (W, dp(48))
            self.tabs.pos = (self.x, top - dp(48))
            top -= dp(52)
            self.tabs.opacity = 1
        else:
            self.tabs.opacity = 0
            self.tabs.size = (W, 0)
        self.vlist.pos = (self.x, self.y + nb)
        self.vlist.size = (W, max(0, top - (self.y + nb)))
        self.me.pos = (self.x, self.y + nb)
        self.me.size = (W, max(0, self.header.y - (self.y + nb)))
        self.empty.pos = (self.x + dp(30), self.vlist.y + self.vlist.height * 0.35)
        self.empty.size = (W - dp(60), dp(80))

    # ---- navigation ------------------------------------------------------------
    def set_tab(self, tid):
        self.exit_selection_silent()
        self.mode = tid
        self.tabs.set_current(tid)
        self.vlist.scroll = 0
        self.rebuild()

    def set_nav(self, nid):
        self.exit_selection_silent()
        self.nav = nid
        self.navbar.set_current(nid)
        if self.search_on:
            self.toggle_search(False)
        if self.me.parent is self:
            self.remove_widget(self.me)
        if nid == 'me':
            self.me.build()
            self.vlist.opacity = 0
            self.vlist.disabled = True
            self.add_widget(self.me)
            self.remove_widget(self.navbar)
            self.add_widget(self.navbar)
        else:
            self.vlist.opacity = 1
            self.vlist.disabled = False
            self.vlist.scroll = 0
        self._lay()
        self.rebuild()

    def exit_selection_silent(self):
        self.ctx.sel_mode = False
        self.ctx.selected.clear()
        self.ctx.reorder = False

    def on_back(self):
        if self.ctx.sel_mode:
            self.exit_selection()
            return True
        if self.search_on:
            self.toggle_search(False)
            return True
        if self.nav != 'library':
            self.set_nav('library')
            return True
        return False

    def on_show(self):
        self.rebuild()

    def refresh(self):
        if self.nav == 'me':
            self.me.build()
        self.rebuild()

    # ---- data -> items -------------------------------------------------------------
    def _match(self, text):
        q = self.query.strip()
        if not q:
            return True
        return core.natural_key(q) == core.natural_key(text) or \
            q.casefold() in (text or '').casefold()

    def build_items(self):
        lib = self.app.lib
        items = []
        if self.nav == 'history':
            for k in lib.history():
                if self._match(lib.title(k)):
                    items.append({'kind': 'video', 'key': k})
            return items
        if self.mode == 'playlists':
            if not self.query:
                items.append({'kind': 'create'})
            for c in lib.collections():
                if self._match(c.name):
                    items.append({'kind': 'coll', 'coll': c})
        elif self.mode == 'folders':
            for c in lib.folders():
                if self._match(c.name):
                    items.append({'kind': 'coll', 'coll': c})
        else:
            for k in lib.all_videos_sorted():
                if self._match(lib.title(k)):
                    items.append({'kind': 'video', 'key': k})
        return items

    def rebuild(self):
        if self.nav == 'me':
            self.update_header()
            return
        self.ctx.show_path = (self.nav == 'library' and self.mode == 'folders')
        self.ctx.reorder = bool(self.ctx.sel_mode and self.nav == 'library' and self.mode == 'playlists')
        self.vlist.reorderable = self.ctx.reorder
        items = self.build_items()
        self.vlist.set_items(items)
        if not items or (len(items) == 1 and items[0]['kind'] == 'create'):
            if not self.app.loaded:
                self.empty.ltext = 'جارٍ تحميل الفيديوهات…'
            elif not self.app.permitted:
                self.empty.ltext = 'يلزم السماح بالوصول إلى الفيديوهات.\nاضغط على «أنا» ثم «إعادة فحص الفيديوهات».'
            elif self.nav == 'history':
                self.empty.ltext = 'لا يوجد سجل مشاهدة بعد'
            elif self.query:
                self.empty.ltext = 'لا توجد نتائج'
            else:
                self.empty.ltext = 'لا توجد فيديوهات'
        else:
            self.empty.ltext = ''
        self.update_header()

    # ---- header --------------------------------------------------------------------
    def update_header(self):
        ctx = self.ctx
        self._lay()
        if ctx.sel_mode:
            n = len(ctx.selected)
            right = [self.btn_close]
            left = self._action_buttons()
            self.header.set('%d محدد' % n, '', right, left)
            return
        if self.search_on:
            self.header.set('', '', [IconButton('close', callback=lambda w: self.toggle_search(False))], [],
                            extra=self.field)
            return
        if self.nav == 'history':
            self.header.set('السجل', '', [], [self.btn_search])
        elif self.nav == 'me':
            self.header.set('أنا', '', [], [])
        else:
            left = [self.btn_search]
            if self.mode != 'folders':
                left.append(self.btn_sort)
            self.header.set('على الجهاز', '', [], left, big=True)

    def _action_buttons(self):
        n = len(self.ctx.selected)
        btns = [IconButton('select_all', callback=lambda w: self.select_all())]
        videos = self.nav == 'history' or self.mode == 'videos'
        if videos:
            btns.append(IconButton('playlist_add', callback=lambda w: self.act_add()))
            if n == 1:
                btns.append(IconButton('edit', callback=lambda w: self.act_rename()))
            btns.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
        elif self.mode == 'playlists':
            if n == 1:
                btns.append(IconButton('edit', callback=lambda w: self.act_rename()))
            btns.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
        else:
            btns.append(IconButton('playlist_add', callback=lambda w: self.act_add()))
        return btns

    def on_selection_changed(self):
        self.ctx.reorder = bool(self.ctx.sel_mode and self.nav == 'library' and self.mode == 'playlists')
        self.vlist.reorderable = self.ctx.reorder
        self.update_header()
        self.vlist.refresh()

    # ---- search ----------------------------------------------------------------------
    def toggle_search(self, on):
        if on:
            self.field = FieldInput(text='', hint='بحث…')
            self.field.size_hint = (None, None)
            self.field.height = dp(44)
            self.field.ti.bind(text=self._on_query)
            self.search_on = True
            self.update_header()
            Clock.schedule_once(self._focus_field, 0.15)
        else:
            if self.field is not None:
                self.field.release()
            self.search_on = False
            self.field = None
            self.query = ''
            self.update_header()
            self.rebuild()

    def _focus_field(self, dt):
        if self.field is not None and self.search_on:
            self.field.focus()

    def _on_query(self, inst, value):
        self.query = value
        self.rebuild()

    # ---- sorting -----------------------------------------------------------------------
    def open_sort(self):
        lib, app = self.app.lib, self.app
        if self.nav == 'library' and self.mode == 'playlists':
            def build():
                return [SheetTitle('ترتيب القوائم'),
                        SheetRow('حسب الاسم', icon='sort', callback=lambda w: apply('name')),
                        SheetRow('حسب عدد المقاطع', icon='sort', callback=lambda w: apply('count')),
                        SheetLabel('أو اضغط مطولاً على أي قائمة ثم اسحبها لمكانك')]
            sheet = MenuSheet(app.root, build)

            def apply(how):
                sheet.dismiss()
                cs = lib.collections()
                if how == 'name':
                    cs.sort(key=lambda c: core.natural_key(c.name))
                else:
                    cs.sort(key=lambda c: -c.count)
                lib.set_collections_order([c.id for c in cs])
                self.rebuild()
            sheet.show()
            return

        def get():
            s = app.store.setting('videos_sort')
            return s.get('mode', 'date'), s.get('asc', False)

        def put(mode, asc):
            app.store.set_setting('videos_sort', {'mode': mode, 'asc': asc})
            self.rebuild()
        sort_sheet(app, 'ترتيب الفيديوهات', ['name', 'duration', 'last_played', 'date', 'size'], get, put)

    # ---- item actions --------------------------------------------------------------------
    def open_item(self, idx, item):
        k = item.get('kind')
        if k == 'create':
            def ok(name):
                cid = self.app.lib.create_playlist(name)
                self.app.store.save()
                self.rebuild()
                self.app.open_collection(cid)
            ask_text(self.app, 'قائمة تشغيل جديدة', '', 'اسم القائمة', ok, 'إنشاء')
        elif k == 'coll':
            self.app.open_collection(item['coll'].id)
        elif k == 'video':
            keys = [i['key'] for i in self.vlist.items if i.get('kind') == 'video']
            self.app.play(keys, keys.index(item['key']))

    def _reorder(self, src, dst):
        items = list(self.vlist.items)
        if not (self.nav == 'library' and self.mode == 'playlists'):
            self.vlist.set_items(items)
            return
        dst = max(dst, 1 if items and items[0]['kind'] == 'create' else 0)
        it = items.pop(src)
        items.insert(dst, it)
        ids = [i['coll'].id for i in items if i['kind'] == 'coll']
        self.app.lib.set_collections_order(ids)
        self.vlist.set_items(items)

    def _selected_videos(self):
        lib = self.app.lib
        if self.nav == 'history' or self.mode == 'videos':
            return [k for k in self.ctx.selected if k in lib.videos]
        keys = []
        for cid in self.ctx.selected:
            c = lib.collection(cid)
            if c:
                keys.extend(c.keys)
        return keys

    def act_add(self):
        keys = self._selected_videos()
        if keys:
            choose_playlist(self.app, keys, after=self.exit_selection)

    def act_rename(self):
        sid = next(iter(self.ctx.selected))
        lib = self.app.lib

        def after():
            self.app.store.save()
            self.exit_selection()
            self.rebuild()
        if self.mode == 'playlists' and self.nav == 'library':
            c = lib.collection(sid)
            if c is None:
                return

            def ok(name):
                lib.rename_collection(sid, name)
                after()
            ask_text(self.app, 'تعديل اسم القائمة', c.name, 'اسم القائمة', ok)
        else:
            rename_video_dialog(self.app, sid, after)

    def act_delete(self):
        lib, app = self.app.lib, self.app
        ids = list(self.ctx.selected)

        def after():
            app.store.save()
            self.exit_selection()
            self.rebuild()
            app.root.refresh_pages()
        if self.nav == 'history' or self.mode == 'videos':
            delete_videos_dialog(app, ids, after)
            return

        def ok():
            for cid in ids:
                lib.delete_collection(cid)
            app.root.say('تم حذف %d قائمة (الفيديوهات لم تُحذف من الجهاز)' % len(ids))
            after()
        confirm(app, 'حذف قوائم التشغيل',
                'سيتم حذف %d قائمة من التطبيق فقط. الفيديوهات تبقى في الجهاز، '
                'ويمكنك إعادة القوائم الأصلية من «أنا».' % len(ids), 'حذف', ok)


# ---------------------------------------------------------------------------
# Collection page (one playlist / folder)
# ---------------------------------------------------------------------------
class CollectionPage(Page, ListPageMixin):
    def __init__(self, app, cid, **kw):
        super(CollectionPage, self).__init__(app, **kw)
        self.cid = cid
        self.init_list()
        self.ctx.reorder = True          # long press + move = reorder (always possible)
        self.vlist.reorderable = True
        self.header = Header()
        self.query = ''
        self.search_on = False
        self.field = None
        self.fab = Tap(callback=lambda w: self.play_all(), size_hint=(None, None), size=(dp(58), dp(58)))
        self.fab_icon = Icon(name='play', color=[0, 0, 0, 1], size=(dp(26), dp(26)))
        self.fab.add_widget(self.fab_icon)
        self.empty = Txt(ltext='', halign='center', color=SUB, font_size=sp(16), nlines=3,
                         size_hint=(None, None))
        for w in (self.vlist, self.header, self.empty, self.fab):
            self.add_widget(w)
        self.btn_back = IconButton('back', callback=lambda w: self.app.root.back())
        self.btn_close = IconButton('close', callback=lambda w: self.exit_selection())
        self.btn_sort = IconButton('sort', callback=lambda w: self.open_sort())
        self.btn_search = IconButton('search', callback=lambda w: self.toggle_search(True))
        self.btn_add = IconButton('plus', callback=lambda w: self.add_videos())
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    @property
    def coll(self):
        return self.app.lib.collection(self.cid)

    def _lay(self, *a):
        hh = dp(64)
        self.header.size = (self.width, hh)
        self.header.pos = (self.x, self.top - hh)
        self.vlist.pos = self.pos
        self.vlist.size = (self.width, max(0, self.top - hh - self.y))
        self.fab.pos = (self.x + dp(18), self.y + dp(20))
        if hasattr(self, 'fab_icon'):
            self.fab_icon.center = self.fab.center
        self.fab.canvas.before.clear()
        with self.fab.canvas.before:
            Color(*ACCENT)
            Ellipse(pos=self.fab.pos, size=self.fab.size)
        self.empty.pos = (self.x + dp(30), self.vlist.y + self.vlist.height * 0.4)
        self.empty.size = (self.width - dp(60), dp(80))

    def on_show(self):
        self.refresh()

    def on_back(self):
        if self.ctx.sel_mode:
            self.exit_selection()
            return True
        if self.search_on:
            self.toggle_search(False)
            return True
        return False

    def refresh(self):
        c = self.coll
        if c is None:
            Clock.schedule_once(lambda dt: self.app.root.pop(), 0)
            return
        keys = c.keys
        if self.query:
            keys = [k for k in keys if self.query.casefold() in self.app.lib.title(k).casefold()]
        self.vlist.reorderable = bool(self.ctx.sel_mode and not self.query)
        self.vlist.set_items([{'kind': 'video', 'key': k} for k in keys])
        if not keys:
            self.empty.ltext = 'القائمة فارغة.\nاضغط + لإضافة فيديوهات.' if c.kind == 'custom' and not self.query \
                else 'لا توجد فيديوهات'
        else:
            self.empty.ltext = ''
        self.fab.opacity = 1 if keys else 0
        self.fab.disabled = not keys
        self.update_header()

    def update_header(self):
        c = self.coll
        if c is None:
            return
        if self.ctx.sel_mode:
            n = len(self.ctx.selected)
            left = [IconButton('select_all', callback=lambda w: self.select_all()),
                    IconButton('playlist_add', callback=lambda w: self.act_add())]
            if n == 1:
                left.append(IconButton('edit', callback=lambda w: self.act_rename()))
            left.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
            left.append(IconButton('dots', callback=lambda w: self.more_menu()))
            self.header.set('%d محدد' % n, '', [self.btn_close], left)
            return
        if self.search_on:
            self.header.set('', '', [IconButton('close', callback=lambda w: self.toggle_search(False))], [],
                            extra=self.field)
            return
        sub = core.count_videos_label(c.count)
        total = self.app.lib.total_duration(c.keys)
        if total:
            sub += '  •  ' + core.fmt_time(total)
        left = [self.btn_search, self.btn_sort]
        if c.kind == 'custom':
            left.insert(0, self.btn_add)
        self.header.set(c.name, sub, [self.btn_back], left)

    def on_selection_changed(self):
        self.vlist.reorderable = bool(self.ctx.sel_mode and not self.query)
        self.update_header()
        self.vlist.refresh()

    # ---- search / sort ----------------------------------------------------------------------
    def toggle_search(self, on):
        if on:
            self.field = FieldInput(text='', hint='بحث…')
            self.field.size_hint = (None, None)
            self.field.height = dp(44)
            self.field.ti.bind(text=self._on_query)
            self.search_on = True
            self.update_header()
            Clock.schedule_once(self._focus_field, 0.15)
        else:
            if self.field is not None:
                self.field.release()
            self.search_on = False
            self.field = None
            self.query = ''
            self.refresh()

    def _focus_field(self, dt):
        if self.field is not None and self.search_on:
            self.field.focus()

    def _on_query(self, inst, value):
        self.query = value
        self.refresh()

    def open_sort(self):
        lib = self.app.lib

        def get():
            return lib.collection_sort(self.cid)

        def put(mode, asc):
            if mode == 'manual':
                # keep the current visual order as the manual order
                lib.set_manual_order(self.cid, lib.items(self.cid))
            else:
                lib.set_collection_sort(self.cid, mode, asc)
            self.app.store.save()
            self.refresh()
        sort_sheet(self.app, 'ترتيب القائمة', core.SORT_MODES, get, put)

    # ---- items --------------------------------------------------------------------------------
    def open_item(self, idx, item):
        keys = [i['key'] for i in self.vlist.items]
        self.app.play(keys, keys.index(item['key']), cid=self.cid)

    def play_all(self):
        keys = [i['key'] for i in self.vlist.items]
        if keys:
            self.app.play(keys, 0, cid=self.cid)

    def _reorder(self, src, dst):
        items = list(self.vlist.items)
        it = items.pop(src)
        items.insert(dst, it)
        keys = [i['key'] for i in items]
        was_manual = self.app.lib.collection_sort(self.cid)[0] == 'manual'
        self.app.lib.set_manual_order(self.cid, keys)
        self.app.store.save()
        self.vlist.set_items(items)
        if not was_manual:
            self.app.root.say('تم التحويل إلى الترتيب اليدوي')
            self.update_header()

    def add_videos(self):
        self.app.open_picker(self.cid)

    def act_add(self):
        keys = selection_keys(self.ctx, self.app.lib)
        choose_playlist(self.app, keys, after=self.exit_selection)

    def act_rename(self):
        sid = next(iter(self.ctx.selected))

        def after():
            self.app.store.save()
            self.exit_selection()
            self.refresh()
        rename_video_dialog(self.app, sid, after)

    def act_delete(self):
        keys = selection_keys(self.ctx, self.app.lib)

        def after():
            self.exit_selection()
            self.app.root.refresh_pages()
        delete_videos_dialog(self.app, keys, after)

    def more_menu(self):
        lib, app = self.app.lib, self.app

        def build():
            return [SheetTitle('المزيد'),
                    SheetRow('تشغيل المحدد', icon='play', callback=lambda w: do('play')),
                    SheetRow('نقل إلى أول القائمة', icon='move_top', callback=lambda w: do('top')),
                    SheetRow('نقل إلى آخر القائمة', icon='move_bottom', callback=lambda w: do('bottom')),
                    SheetRow('إزالة من القائمة فقط', icon='close', callback=lambda w: do('remove'))]
        sheet = MenuSheet(app.root, build)

        def do(what):
            sheet.dismiss()
            keys = [i['key'] for i in self.vlist.items if i['key'] in self.ctx.selected]
            if what == 'play':
                self.exit_selection()
                app.play(keys, 0, cid=self.cid)
                return
            if what in ('top', 'bottom'):
                lib.move_to_edge(self.cid, keys, top=(what == 'top'))
            else:
                lib.remove_from_collection(self.cid, keys)
                app.root.say('تمت الإزالة من القائمة (الملفات باقية في الجهاز)')
            app.store.save()
            self.exit_selection()
            app.root.refresh_pages()
        sheet.show()


# ---------------------------------------------------------------------------
# Picker: choose videos to add into a custom playlist
# ---------------------------------------------------------------------------
class PickerPage(Page, ListPageMixin):
    def __init__(self, app, cid, **kw):
        super(PickerPage, self).__init__(app, **kw)
        self.cid = cid
        self.init_list()
        self.ctx.sel_mode = True
        self.ctx.reorder = False
        self.header = Header()
        for w in (self.vlist, self.header):
            self.add_widget(w)
        self.btn_close = IconButton('close', callback=lambda w: self.app.root.back())
        self.btn_ok = IconButton('check', color=ACCENT, callback=lambda w: self.confirm())
        self.btn_all = IconButton('select_all', callback=lambda w: self.select_all())
        self.bind(pos=self._lay, size=self._lay)
        self._lay()
        self.refresh()

    def _lay(self, *a):
        hh = dp(60)
        self.header.size = (self.width, hh)
        self.header.pos = (self.x, self.top - hh)
        self.vlist.pos = self.pos
        self.vlist.size = (self.width, max(0, self.top - hh - self.y))

    def refresh(self):
        lib = self.app.lib
        existing = set(lib.items(self.cid))
        keys = [k for k in lib.all_videos_sorted() if k not in existing]
        self.vlist.set_items([{'kind': 'video', 'key': k} for k in keys])
        self.update_header()

    def update_header(self):
        self.header.set('اختر الفيديوهات (%d)' % len(self.ctx.selected), '', [self.btn_close],
                        [self.btn_ok, self.btn_all])

    def on_selection_changed(self):
        self.update_header()

    def _tap(self, idx, item, x):
        sid = item.get('key')
        if sid in self.ctx.selected:
            self.ctx.selected.discard(sid)
        else:
            self.ctx.selected.add(sid)
        self.vlist.refresh()
        self.update_header()

    def _long(self, idx, item):
        self._tap(idx, item, 0)

    def exit_selection(self):
        self.ctx.selected.clear()
        self.vlist.refresh()
        self.update_header()

    def confirm(self):
        keys = [i['key'] for i in self.vlist.items if i['key'] in self.ctx.selected]
        if keys:
            n = self.app.lib.add_to_playlist(self.cid, keys)
            self.app.store.save()
            self.app.root.say('تمت إضافة %d فيديو' % n)
        self.app.root.pop()


_ = (textfix, SURFACE, SURFACE2, TEXT, DIVIDER, ChipsRow)   # imported for convenience
