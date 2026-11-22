# -*- coding: utf-8 -*-
"""
screens.py - navigation root, rows, home page (playlists / folders / videos /
history / me), collection page and the video picker.
"""
import time

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle, Triangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

import bridge
import core
import textfix
from widgets import (ACCENT, ACCENT_SOFT, BG, DANGER, DIVIDER, SUB, SURFACE, SURFACE2, TEXT,
                     ChipsRow, Dialog, EmptyState, FieldInput, Group, Icon, IconButton, MenuSheet,
                     PromptDialog, Row, SettingRow, SheetButton, SheetLabel, SheetRow, SheetTitle, PillSwitch, Thumb, Tag, Toast, Txt, VList, make_scroll)


# ---------------------------------------------------------------------------
# root / pages
# ---------------------------------------------------------------------------
class Page(FloatLayout):
    """Full screen page with an opaque background."""
    BGCOLOR = BG

    def __init__(self, app, **kw):
        kw.setdefault('size_hint', (1, 1))
        super(Page, self).__init__(**kw)
        self.app = app
        with self.canvas.before:
            Color(*self.BGCOLOR)
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

    def on_resume(self):
        """Back on top again because the page above it closed."""
        self.refresh()
        self.on_show()


class Root(FloatLayout):
    def __init__(self, app, **kw):
        super(Root, self).__init__(**kw)
        self.app = app
        self.pages = []
        self.overlays = []
        self._covered = []           # (page, [pages taken out of the tree while it is on top])
        self.toast = Toast()
        self.add_widget(self.toast)
        self._guard_until = 0.0
        self._eaten = set()

    def guard_touches(self, touch=None, sec=0.7):
        """A sheet was just closed by a press outside it: the rest of that touch is ignored, and so is
        every new press for a moment, so the tap (or an echo of it) can never open what lies under it."""
        if touch is not None:
            self._eaten.add(touch.uid)
        self._guard_until = time.time() + sec

    def on_touch_down(self, touch):
        if time.time() < self._guard_until:
            self._eaten.add(touch.uid)
            return True
        return FloatLayout.on_touch_down(self, touch)

    def on_touch_move(self, touch):
        if touch.uid in self._eaten:
            return True
        return FloatLayout.on_touch_move(self, touch)

    def on_touch_up(self, touch):
        if touch.uid in self._eaten:
            self._eaten.discard(touch.uid)
            return True
        return FloatLayout.on_touch_up(self, touch)

    def _raise_layers(self):
        for ov in self.overlays:
            self.remove_widget(ov)
            self.add_widget(ov)
        self.remove_widget(self.toast)
        self.add_widget(self.toast)

    def push(self, page):
        self.pages.append(page)
        self.add_widget(page)
        self.suspend_below(page)
        self._raise_layers()
        page.on_show()

    def suspend_below(self, page):
        """Pages are full screen and opaque, so whatever is under the top page is invisible.  Kivy
        draws every widget in the tree on every frame, hidden or not, which doubles the work of
        scrolling a list; the pages below are therefore taken out of the tree while a page is on
        top of them (and put back, in order, when it closes)."""
        if page not in self.pages:
            return
        below = []
        for p in self.pages:
            if p is page:
                break
            if p.parent is self:
                below.append(p)
        if not below:
            return
        for p in below:
            self.remove_widget(p)
        self._covered.append((page, below))

    def _uncover(self, page):
        for k in range(len(self._covered) - 1, -1, -1):
            owner, pages = self._covered[k]
            if owner is not page:
                continue
            del self._covered[k]
            for p in reversed(pages):        # the top-most first; each one goes to the very bottom
                if p.parent is None and p in self.pages:
                    self.add_widget(p, index=len(self.children))

    def pop(self):
        if len(self.pages) <= 1:
            return False
        page = self.pages.pop()
        try:
            page.on_close()
        finally:
            self.remove_widget(page)
            self._uncover(page)
        if self.pages:
            self.pages[-1].on_resume()
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
            return self.x + (dp(100) if self.ctx.reorder else dp(54))
        return self.x + dp(16)

    @staticmethod
    def fit_title(label, w, steps):
        """Give a title the first (font size, lines) step in which the WHOLE name fits; when none does, the
        last (smallest) step is kept.  Lets the user read the full name of a row while ordering by hand."""
        txt = ' '.join((label.ltext or '').split())
        label.width = w
        for fs, n in steps:
            label.font_size = sp(fs)
            label.nlines = n
            lines = label.logical_lines()
            if len(lines) <= n and ' '.join(lines) == txt:
                return

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
        _draw_check(self.canvas.before, self.x + dp(30), (self.y + self.height / 2.0), dp(11), sel)
        if ctx.reorder:
            self.handle.opacity = 1
            self.handle.center = (self.x + dp(72), (self.y + self.height / 2.0))
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
    STEPS = [(15.5, 2)]
    STEPS_SEL = [(15.5, 2), (14, 3), (13, 3), (12, 3), (11.5, 4)]

    def __init__(self, **kw):
        super(VideoRow, self).__init__(**kw)
        self.thumb = Thumb(radius=dp(12), size=(dp(128), dp(72)))
        self.title = Txt(font_size=sp(15.5), nlines=2, valign='top', size_hint=(None, None))
        self.info = Txt(font_size=sp(12.5), color=SUB, valign='top', size_hint=(None, None))
        self.badge = Tag()
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
        self.badge.set_text(core.fmt_time(dur) if dur else '')
        self.set_thumb_for(self.thumb, key)

    def relayout(self):
        if self.item is None or self.ctx is None:
            return
        ctx = self.ctx
        if self.unchanged(ctx.sel_mode, ctx.reorder, self.is_selected(), self.badge.ltext,
                          round(self.frac, 3), self.title.ltext):
            return
        self.draw_selection()
        tw, th = dp(128), dp(72)
        cy = self.y + self.height / 2.0
        self.thumb.size = (tw, th)
        self.thumb.pos = ((self.x + self.width) - dp(16) - tw, cy - th / 2.0)
        left = self.left_bound()
        tx_right = self.thumb.x - dp(14)
        w = max(10, tx_right - left)
        self.fit_title(self.title, w, self.STEPS_SEL if ctx.sel_mode else self.STEPS)
        # the title may need several lines: stack title + info as one block, centred on the thumbnail
        self.title.size = (w, dp(10))
        n = len(self.title.logical_lines())
        ht = self.title.text_height(n) * (1.0 if n < 2 else 1.12)   # a little slack: tall glyphs (brackets) must not drop a line
        hi = self.info.text_height(1)
        gap = dp(1)
        top = cy + (ht + gap + hi) / 2.0
        self.title.pos = (left, top - ht)
        self.title.size = (w, ht)
        self.info.pos = (left, top - ht - gap - hi)
        self.info.size = (w, hi)
        watched = self.frac > 0.02
        self.badge.pos = (self.thumb.x + tw - dp(6) - self.badge.width,
                          self.thumb.y + (dp(11) if watched else dp(6)))
        self.canvas.after.clear()
        with self.canvas.after:
            if watched:
                bx, by, bwid = self.thumb.x + dp(8), self.thumb.y + dp(5), tw - dp(16)
                Color(1, 1, 1, 0.30)
                RoundedRectangle(pos=(bx, by), size=(bwid, dp(3)), radius=[dp(1.5)])
                Color(*ACCENT)
                RoundedRectangle(pos=(bx, by), size=(max(dp(3), bwid * min(1.0, self.frac)), dp(3)),
                                 radius=[dp(1.5)])


class CollRow(ListRow):
    kind = 'coll'
    STEPS = [(17.5, 1)]
    STEPS_SEL = [(17.5, 1), (15.5, 2), (14, 2), (13, 3), (12, 3), (11.5, 4)]
    INFO_STEPS_SEL = [(13.5, 1), (12.5, 1), (12, 2), (11.5, 2)]

    def __init__(self, **kw):
        super(CollRow, self).__init__(**kw)
        self.thumb = Thumb(radius=dp(14), size=(dp(142), dp(80)))
        self.title = Txt(font_size=sp(17.5), bold=True, valign='top', size_hint=(None, None))
        self.info = Txt(font_size=sp(13.5), color=SUB, valign='top', size_hint=(None, None))
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
        ctx = self.ctx
        if self.unchanged(ctx.sel_mode, ctx.reorder, self.is_selected(), self.title.ltext, self.info.ltext):
            return
        self.draw_selection()
        tw, th = dp(142), dp(80)
        cy = self.y + self.height / 2.0
        self.thumb.size = (tw, th)
        self.thumb.pos = ((self.x + self.width) - dp(16) - tw, cy - th / 2.0 - dp(3))
        left = self.left_bound()
        w = max(10, self.thumb.x - dp(16) - left)
        self.fit_title(self.title, w, self.STEPS_SEL if ctx.sel_mode else self.STEPS)
        self.fit_title(self.info, w, self.INFO_STEPS_SEL if ctx.sel_mode else [(13.5, 1)])
        self.title.size = (w, dp(10))
        self.info.size = (w, dp(10))
        n = len(self.title.logical_lines())
        ht = self.title.text_height(n) * (1.0 if n < 2 else 1.12)
        hi = self.info.text_height(len(self.info.logical_lines()))
        gap = dp(3)
        top = cy + (ht + gap + hi) / 2.0
        self.title.pos = (left, top - ht)
        self.title.size = (w, ht)
        self.info.pos = (left, top - ht - gap - hi)
        self.info.size = (w, hi)
        self.draw_peek(tw)

    def draw_peek(self, tw):
        self.canvas.after.clear()
        top = self.thumb.y + self.thumb.height
        with self.canvas.after:               # two cards peeking out behind the cover: "a stack"
            Color(0.20, 0.21, 0.25, 1)
            RoundedRectangle(pos=(self.thumb.x + dp(22), top - dp(1)), size=(tw - dp(44), dp(9)),
                             radius=[dp(5), dp(5), 0, 0])
            Color(0.29, 0.30, 0.35, 1)
            RoundedRectangle(pos=(self.thumb.x + dp(11), top - dp(1)), size=(tw - dp(22), dp(5)),
                             radius=[dp(5), dp(5), 0, 0])


class GroupRow(CollRow):
    """A folder ("مجلد") of lists: a cover with a folder tab and a folder badge."""
    kind = 'group'

    def __init__(self, **kw):
        super(GroupRow, self).__init__(**kw)
        self.badge = Icon(name='folder', color=[1, 1, 1, 0.95], size=(dp(22), dp(22)), stroke=1.8)
        self.add_widget(self.badge)

    def fill(self, item, idx, ctx):
        c = item['coll']
        self.title.ltext = c.name
        self.info.ltext = core.count_lists_label(len(c.lists)) + '  •  ' + core.count_videos_label(c.count)
        cover = None
        for lst in c.lists:
            cover = ctx.lib.cover_key(lst.keys)
            if cover:
                break
        self.set_thumb_for(self.thumb, cover)

    def draw_peek(self, tw):
        self.canvas.after.clear()
        top = self.thumb.y + self.thumb.height
        with self.canvas.after:               # the tab of a folder, sticking out at the top
            Color(0.29, 0.30, 0.35, 1)
            RoundedRectangle(pos=(self.thumb.x + tw - dp(64), top - dp(1)), size=(dp(54), dp(9)),
                             radius=[dp(6), dp(6), 0, 0])
        self.badge.center = (self.thumb.x + dp(22), self.thumb.y + dp(22))
        self.badge.canvas.before.clear()
        with self.badge.canvas.before:         # dark disc so the badge reads on any cover
            Color(0, 0, 0, 0.62)
            Ellipse(pos=(self.badge.center_x - dp(16), self.badge.center_y - dp(16)), size=(dp(32), dp(32)))


class CreateRow(Row):
    kind = 'create'

    LABEL = 'إنشاء قائمة تشغيل جديدة'

    def __init__(self, **kw):
        super(CreateRow, self).__init__(**kw)
        self.label = Txt(ltext=self.LABEL, font_size=sp(15.5), bold=True, nlines=2, size_hint=(None, None))
        self.plus = Icon(name='plus', color=list(ACCENT), size=(dp(26), dp(26)), stroke=1.8)
        self.add_widget(self.label)
        self.add_widget(self.plus)

    def relayout(self):
        if self.unchanged():
            return
        tw, th = dp(128), dp(72)                      # same footprint as a cover: rows line up
        x = (self.x + self.width) - dp(16) - tw
        y = (self.y + self.height / 2.0) - th / 2.0
        self.canvas.before.clear()
        with self.canvas.before:
            Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.07)
            RoundedRectangle(pos=(x, y), size=(tw, th), radius=[dp(12)])
            Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.30)
            Line(rounded_rectangle=(x + dp(0.5), y + dp(0.5), tw - dp(1.0), th - dp(1.0), dp(12)),
                 width=dp(1.0), dash_length=dp(5), dash_offset=dp(4))
            d = dp(38)                                # the plus sits in a soft disc
            Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.16)
            Ellipse(pos=(x + tw / 2.0 - d / 2.0, y + th / 2.0 - d / 2.0), size=(d, d))
        self.plus.center = (x + tw / 2.0, y + th / 2.0)
        self.label.pos = (self.x + dp(16), (self.y + self.height / 2.0) - dp(30))
        self.label.size = (x - dp(14) - self.x - dp(16), dp(60))


class GCreateRow(CreateRow):
    kind = 'gcreate'
    LABEL = 'إنشاء مجلد جديد'


ROW_FACTORIES = {'video': VideoRow, 'coll': CollRow, 'create': CreateRow, 'group': GroupRow,
                 'gcreate': GCreateRow}


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

    def set(self, title, sub='', right=(), left=(), big=False, extra=None, short=''):
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
        self._full, self._short = title, short
        self.title.ltext = title
        self.title.font_size = sp(29) if big else sp(19.5)
        self.sub.ltext = sub
        self._lay()

    def _lay(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*BG)
            Rectangle(pos=self.pos, size=self.size)
        x_r = (self.x + self.width) - dp(6)
        for b in self.right_btns:
            b.pos = (x_r - b.width, (self.y + self.height / 2.0) - b.height / 2.0)
            x_r -= b.width
        x_l = self.x + dp(6)
        for b in self.left_btns:
            b.pos = (x_l, (self.y + self.height / 2.0) - b.height / 2.0)
            x_l += b.width
        if not self.right_btns:
            x_r = (self.x + self.width) - dp(16)
        if self.extra is not None:
            self.extra.pos = (x_l + dp(4), (self.y + self.height / 2.0) - self.extra.height / 2.0)
            self.extra.width = max(10, x_r - x_l - dp(10))
            self.title.size = (0, 0)
            self.sub.size = (0, 0)
            return
        w = max(10, x_r - x_l - dp(8))
        full, short = getattr(self, '_full', None), getattr(self, '_short', '')
        if short and full is not None:                  # many buttons: a smaller "10 محدد", else just "10"
            self.title.ltext = full
            for fs in (19.5, 18, 16.5, 15.5):
                self.title.font_size = sp(fs)
                if self.title.text_width() <= w:
                    break
            else:
                self.title.font_size = sp(19.5)
                self.title.ltext = short
        if self.sub.ltext:
            self.title.pos = (x_l + dp(4), (self.y + self.height / 2.0) - dp(2))
            self.title.size = (w, dp(28))
            self.sub.pos = (x_l + dp(4), (self.y + self.height / 2.0) - dp(26))
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
    """Sheet: add the given video keys to any list (or to a new one)."""
    lib = app.lib
    keys = list(keys)

    def done(msg):
        app.root.say(msg)
        app.store.save()
        if after:
            after()
        app.root.refresh_pages()

    def build():
        rows = [SheetTitle('إضافة إلى قائمة تشغيل'),
                SheetRow('قائمة تشغيل جديدة', icon='plus', callback=lambda w: new())]
        for c in lib.collections():
            rows.append(SheetRow(c.name, icon='playlist', value=core.count_videos_label(c.count),
                                 callback=lambda w, cid=c.id, nm=c.name: pick(cid, nm)))
        return rows
    sheet = MenuSheet(app.root, build)

    def pick(cid, name):
        sheet.dismiss()
        n = lib.add_to_playlist(cid, keys)
        if n:
            done('تمت إضافة %d فيديو إلى «%s»' % (n, name))
        else:
            done('الفيديوهات موجودة بالفعل في «%s»' % name)

    def new():
        sheet.dismiss()
        if not keys:
            app.root.say('اختر فيديو واحد على الأقل')
            return

        def ok(name):
            cid = lib.create_playlist(name, keys)
            done('تم إنشاء «%s» (%d فيديو)' % (lib.collection(cid).name, len(keys)))
        ask_text(app, 'قائمة تشغيل جديدة', '', 'اسم القائمة', ok, 'إنشاء')
    sheet.show()


def pick_lists(app, title, candidates, ok_label, on_done):
    """Sheet with lists to tick (at least one); on_done(list_of_ids) when confirmed.

    Ticking only touches the one row and the pinned button: rebuilding every row each time was slow."""
    if not candidates:
        app.root.say('لا توجد قوائم تشغيل لإضافتها')
        return
    chosen = []
    ids = [c.id for c in candidates]
    rows_by_id = {}
    all_row = []

    def all_label():
        return 'إلغاء تحديد الكل' if len(chosen) == len(ids) else 'تحديد الكل'

    def build():
        rows_by_id.clear()
        del all_row[:]
        all_row.append(SheetRow(all_label(), icon='select_all', callback=lambda w: toggle_all()))
        rows = [SheetTitle(title), all_row[0]]
        for c in candidates:
            r = SheetRow(c.name, icon='playlist', value=core.count_videos_label(c.count),
                         checked=c.id in chosen, callback=lambda w, cid=c.id: toggle(cid))
            rows_by_id[c.id] = r
            rows.append(r)
        return rows

    def footer():                                # pinned at the bottom: always reachable however long the list
        n = len(chosen)
        return SheetButton('%s (%d)' % (ok_label, n) if n else 'اختر قائمة واحدة على الأقل',
                           callback=lambda w: go(), enabled=bool(n))
    sheet = MenuSheet(app.root, build, footer=footer)

    def sync():
        all_row[0].lbl.ltext = all_label()
        sheet.refresh_footer()

    def toggle(cid):
        if cid in chosen:
            chosen.remove(cid)
        else:
            chosen.append(cid)
        rows_by_id[cid].set_checked(cid in chosen)
        sync()

    def toggle_all():
        if len(chosen) == len(ids):
            del chosen[:]
        else:
            chosen[:] = list(ids)
        for cid, r in rows_by_id.items():
            r.set_checked(cid in chosen)
        sync()

    def go():
        if not chosen:
            return
        sheet.dismiss()
        on_done(list(chosen))
    sheet.show()


def new_group_flow(app, after=None):
    """Ask for a name, then for the lists to put in the new folder."""
    lib = app.lib

    def named(name):
        def picked(cids):
            gid = lib.create_group(name, cids)
            app.store.save()
            app.root.say('تم إنشاء المجلد «%s»' % lib.group(gid).name)
            app.root.refresh_pages()
            if after:
                after(gid)
        # the keyboard is still closing (the window is resizing): open the sheet when it is gone
        Clock.schedule_once(lambda dt: pick_lists(app, 'اختر قوائم المجلد', lib.collections(), 'إنشاء المجلد', picked), 0.35)
    ask_text(app, 'مجلد جديد', '', 'اسم المجلد', named, 'التالي')


def sort_sheet(app, title, modes, get_state, set_state, extra=None):
    """Generic 'sort by' sheet. get_state() -> (mode, asc); set_state(mode, asc).

    The sheet keeps its own copy of the choice and redraws at once; the (slow) re-sorting of the
    page behind it happens a moment later, so the sheet never freezes or jumps.  Its rows are the
    same in every mode, so its height never changes either."""
    cur = list(get_state())

    def build():
        mode, asc = cur
        rows = [SheetTitle(title)]
        for m in modes:
            rows.append(SheetRow(core.SORT_LABELS.get(m, m), checked=(m == mode),
                                 callback=lambda w, m=m: pick(m)))
        rows.append(SheetLabel('الاتجاه'))
        rows.append(SheetRow('تصاعدي', icon='arrow_up', checked=asc, callback=lambda w: setd(True)))
        rows.append(SheetRow('تنازلي', icon='arrow_down', checked=not asc, callback=lambda w: setd(False)))
        return rows
    sheet = MenuSheet(app.root, build)

    def apply(mode, asc):
        set_state(mode, asc)
        cur[0], cur[1] = get_state()          # what the page really stored (manual order resets it)
        sheet.rebuild()

    def pick(m):
        if m == cur[0]:
            return
        cur[0] = m
        if m == 'manual':
            cur[1] = True
        sheet.rebuild()
        Clock.schedule_once(lambda dt: apply(cur[0], cur[1]), 0.05)

    def setd(a):
        if a == cur[1]:
            return
        cur[1] = a
        sheet.rebuild()
        Clock.schedule_once(lambda dt: apply(cur[0], cur[1]), 0.05)
    sheet.show()
    return sheet


def share_keys(app, keys):
    """Open the system share sheet for the given video keys."""
    vids = [app.lib.videos[k] for k in keys if k in app.lib.videos]
    if not vids:
        app.root.say('لا توجد فيديوهات للمشاركة')
        return
    if not bridge.share_videos(vids):
        app.root.say('تعذرت المشاركة: ' + (bridge.LAST_SHARE_ERROR[0] or ''))


def selection_keys(ctx, lib):
    return [k for k in ctx.selected if k in lib.videos]


# ---------------------------------------------------------------------------
# tab bar + nav bar
# ---------------------------------------------------------------------------
class TabBar(Widget):
    def __init__(self, tabs, on_pick, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(52))
        super(TabBar, self).__init__(**kw)
        self.tabs = tabs                  # [(id, label)] in display order: first = rightmost
        self.on_pick = on_pick
        self.current = tabs[0][0]
        self.labels = {}
        self._hit = []
        for tid, label in tabs:
            t = Txt(ltext=label, font_size=sp(15.5), size_hint=(None, None), halign='center')
            self.labels[tid] = t
            self.add_widget(t)
        self.bind(pos=self._lay, size=self._lay)

    def set_current(self, tid):
        self.current = tid
        self._lay()

    def _lay(self, *a):
        self.canvas.before.clear()          # never canvas.clear(): it would drop the children
        x = (self.x + self.width) - dp(16)
        self._hit = []
        ch = dp(38)
        cy0 = self.y + (self.height - ch) / 2.0
        gap = dp(8)
        avail = self.width - dp(32)
        for tid, label in self.tabs:
            t = self.labels[tid]
            active = tid == self.current
            t.bold = active
            t.color = ACCENT if active else (0.80, 0.82, 0.87, 1)
        pad = dp(34)
        for fs in (15.5, 14.5, 13.5, 12.5):          # shrink until all the chips fit on the screen
            for tid, label in self.tabs:
                self.labels[tid].font_size = sp(fs)
            texts = [max(dp(30), self.labels[tid].text_width()) for tid, label in self.tabs]
            pad = (avail - gap * (len(texts) - 1) - sum(texts)) / float(len(texts))
            if pad >= dp(26):
                break
        pad = min(dp(34), max(dp(12), pad))
        with self.canvas.before:
            Color(*BG)
            Rectangle(pos=self.pos, size=self.size)
            for tid, label in self.tabs:
                t = self.labels[tid]
                active = tid == self.current
                cw = max(dp(30), t.text_width()) + pad
                cx0 = x - cw
                Color(*(ACCENT_SOFT if active else SURFACE))
                RoundedRectangle(pos=(cx0, cy0), size=(cw, ch), radius=[ch / 2.0])
                if active:
                    Color(ACCENT[0], ACCENT[1], ACCENT[2], 0.55)
                    Line(rounded_rectangle=(cx0 + 0.5, cy0 + 0.5, cw - 1, ch - 1, ch / 2.0), width=1)
                t.size = (cw, ch)
                t.pos = (cx0, cy0)
                self._hit.append((cx0 - dp(4), cx0 + cw + dp(4), tid))
                x = cx0 - gap

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
            cx = (self.x + self.width) - cw * (i + 0.5)
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
        i = int(((self.x + self.width) - touch.x) // (self.width / float(n)))
        i = max(0, min(n - 1, i))
        self.on_pick(self.items[i][0])
        return True


# ---------------------------------------------------------------------------
# settings pane
# ---------------------------------------------------------------------------
_app_grad = {}


def _app_gradient():
    t = _app_grad.get('t')
    if t is None:
        from kivy.graphics.texture import Texture
        t = Texture.create(size=(1, 2), colorfmt='rgba')
        # first row = bottom of the picture: pink below, coral above (the colours of the app icon)
        t.blit_buffer(bytes([240, 52, 110, 255, 255, 122, 96, 255]), colorfmt='rgba', bufferfmt='ubyte')
        t.mag_filter = 'linear'
        _app_grad['t'] = t
    return t


class AppCard(Widget):
    """Name + logo + a one line summary, at the top of the settings."""

    def __init__(self, **kw):
        kw.setdefault('size_hint', (1, None))
        kw.setdefault('height', dp(100))
        super(AppCard, self).__init__(**kw)
        self.title = Txt(ltext='Pro Player', bold=True, font_size=sp(21), size_hint=(None, None))
        self.sub = Txt(ltext='', color=SUB, font_size=sp(14), size_hint=(None, None))
        self.add_widget(self.title)
        self.add_widget(self.sub)
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def set_summary(self, text):
        self.sub.ltext = text

    def _lay(self, *a):
        x, y, w, h = self.x, self.y, self.width, self.height
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*SURFACE)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(20)])
            bs = dp(58)
            bx, by = (x + w) - dp(20) - bs, y + (h - bs) / 2.0
            Color(1, 1, 1, 1)
            RoundedRectangle(pos=(bx, by), size=(bs, bs), radius=[dp(16)], texture=_app_gradient())
            m = bs * 0.2
            cx, cy = bx + bs / 2.0, by + bs / 2.0
            Color(1, 1, 1, 1)
            Triangle(points=[cx - m * 0.75, cy - m * 1.05, cx - m * 0.75, cy + m * 1.05, cx + m * 1.2, cy])
        tx = bx - dp(16)
        self.title.pos = (x + dp(20), y + h / 2.0 - dp(2))
        self.title.size = (tx - x - dp(20), dp(30))
        self.sub.pos = (x + dp(20), y + h / 2.0 - dp(32))
        self.sub.size = (tx - x - dp(20), dp(28))


class SettingsPane(FloatLayout):
    def __init__(self, app, **kw):
        super(SettingsPane, self).__init__(**kw)
        self.app = app
        self.sv = make_scroll(size_hint=(1, 1))
        self.box = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(4),
                             padding=[dp(14), dp(8), dp(14), dp(30)])
        self.box.bind(minimum_height=self.box.setter('height'))
        self.sv.add_widget(self.box)
        self.add_widget(self.sv)
        self.build()

    def S(self, key):
        return self.app.store.setting(key)

    def put(self, key, value):
        self.app.store.set_setting(key, value)

    def card(self, title, rows):
        """A heading and a rounded card with the given rows."""
        self.box.add_widget(SheetLabel(title))
        g = Group(inset=(dp(16), dp(16) + SettingRow.TILE + dp(13)))
        for r in rows:
            g.add_row(r)
        self.box.add_widget(g)

    def switch(self, key, title, sub, icon):
        sw = PillSwitch(value=bool(self.S(key)), on_change=lambda v, k=key: self.put(k, v))
        return SettingRow(title, sub, icon=icon, switch=sw, callback=lambda w: sw._toggle())

    def choice(self, key, title, sub, icon, options, fmt):
        return SettingRow(title, sub, icon=icon, value=fmt(self.S(key)),
                          callback=lambda w: self.pick_number(key, title, options, fmt))

    def build(self):
        lib = self.app.lib
        box = self.box
        box.clear_widgets()
        n_vid = len(lib.videos)
        n_pl = len([c for c in lib.collections()])
        head = AppCard()
        head.set_summary('%d فيديو  •  %d قائمة تشغيل' % (n_vid, n_pl))
        box.add_widget(head)
        play = [self.switch('resume', 'استكمال التشغيل', 'من آخر مكان توقفت عنده', 'clock'),
                self.switch('autoplay_next', 'الفيديو التالي تلقائياً', 'عند انتهاء الفيديو الحالي', 'next'),
                self.switch('keep_awake', 'إبقاء الشاشة مضاءة', 'أثناء تشغيل الفيديو', 'brightness')]
        if bridge.ANDROID and (not bridge.hw_enabled() or bridge.hw_bad_count()):
            # hardware decoding was switched off after a failure: let the user try it again
            play.append(SettingRow('إعادة تفعيل الهاردوير', 'تم إيقافه بعد مشكلة في التشغيل', icon='restore',
                                   callback=lambda w: self.reset_hw()))
        self.card('التشغيل', play)
        self.card('التحكم', [
            self.switch('gestures', 'إيماءات السحب', 'تقديم وترجيع، سطوع، صوت', 'tune'),
            self.choice('hold_speed', 'السرعة عند الضغط المطول', '', 'speed', [1.5, 2.0, 2.5, 3.0],
                        core.fmt_speed),
            self.choice('seek_step', 'مدة التقديم والترجيع', '', 'step_fwd', [5, 10, 15, 30],
                        lambda x: '%d ث' % x)])
        self.card('الترجمة', [
            self.switch('sub_on', 'تشغيل الترجمة تلقائياً', 'إن وُجد ملف ترجمة', 'subtitle'),
            self.choice('sub_size', 'حجم الترجمة', '', 'edit', [16, 20, 22, 26, 30, 36],
                        lambda x: str(int(x)))])
        n_back = len(lib.restorable())
        self.card('عام', [
            self.switch('vibrate', 'الاهتزاز', 'عند تحديد العناصر', 'bolt'),
            SettingRow('استعادة القوائم المحذوفة', '', icon='restore',
                       value=('%d' % n_back) if n_back else '—', callback=lambda w: self.restore())])
        tsdk = bridge.target_sdk()
        box.add_widget(SheetLabel('Pro Player  •  بناء %s%s' % (core.BUILD, ('  •  API %d' % tsdk) if tsdk else ''),
                                  muted=True))

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

    def reset_hw(self):
        bridge.hw_reset()
        self.app.root.say('تم تفعيل التشغيل بالهاردوير')
        self.build()

    def restore(self):
        """Sheet with the deleted lists: tick the ones to bring back (or all of them)."""
        app, lib = self.app, self.app.lib
        rows_data = lib.restorable()
        if not rows_data:
            app.root.say('لا توجد قوائم محذوفة')
            return
        chosen = set()
        rows_by_id = {}
        all_row = []

        def all_label():
            return 'إلغاء تحديد الكل' if len(chosen) == len(rows_data) else 'تحديد الكل'

        def build():
            rows_by_id.clear()
            del all_row[:]
            all_row.append(SheetRow(all_label(), icon='select_all', callback=lambda w: toggle_all()))
            rows = [SheetTitle('استعادة القوائم المحذوفة'), all_row[0]]
            for cid, name, cnt in rows_data:
                r = SheetRow(name, icon='playlist', value=core.count_videos_label(cnt),
                             checked=cid in chosen, callback=lambda w, cid=cid: toggle(cid))
                rows_by_id[cid] = r
                rows.append(r)
            return rows

        def footer():
            n = len(chosen)
            return SheetButton('استعادة المحدد (%d)' % n if n else 'اختر قوائم للاستعادة',
                               callback=lambda w: go(), enabled=bool(n))
        sheet = MenuSheet(app.root, build, footer=footer)

        def sync():
            all_row[0].lbl.ltext = all_label()
            sheet.refresh_footer()

        def toggle(cid):
            if cid in chosen:
                chosen.discard(cid)
            else:
                chosen.add(cid)
            rows_by_id[cid].set_checked(cid in chosen)
            sync()

        def toggle_all():
            if len(chosen) == len(rows_data):
                chosen.clear()
            else:
                chosen.update(r[0] for r in rows_data)
            for cid, r in rows_by_id.items():
                r.set_checked(cid in chosen)
            sync()

        def go():
            sheet.dismiss()
            n = lib.restore_collections(list(chosen))
            app.store.save()
            app.root.say('تمت استعادة %d قائمة' % n)
            app.root.refresh_pages()
        sheet.show()


# ---------------------------------------------------------------------------
# list-page mixin: selection mode handling shared by Home / Collection / Picker
# ---------------------------------------------------------------------------
class ListPageMixin(object):
    def init_list(self):
        self.ctx = Ctx(self.app)
        self.vlist = VList(ROW_FACTORIES, row_h=dp(100), size_hint=(None, None))
        self.vlist.ctx = self.ctx
        self.vlist.on_tap = self._tap
        self.vlist.on_long = self._long
        self.vlist.on_reorder = self._reorder
        self.vlist.can_drag = self._can_drag
        self.vlist.prefetch = self._prefetch_rows

    def _prefetch_rows(self, first, last):
        items = self.vlist.items
        for i in range(first, last + 1):
            it = items[i]
            if isinstance(it, dict) and it.get('kind') == 'video' and it.get('key'):
                self.app.prefetch_thumb(it['key'])

    # overridables
    def open_item(self, idx, item):
        pass

    def item_id(self, item):
        k = item.get('kind')
        if k == 'video':
            return item['key']
        if k in ('coll', 'group'):
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
    TABS = [('videos', 'مقاطع فيديو'), ('playlists', 'قوائم التشغيل'), ('groups', 'المجلدات')]
    NAVS = [('library', 'folder_play', 'على الجهاز'), ('history', 'clock', 'السجل'), ('me', 'person', 'الإعدادات')]

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
        self.navbar = NavBar(self.NAVS, self.set_nav)     # kept for code paths, never shown
        self.me = SettingsPane(app, size_hint=(None, None))
        self.empty = EmptyState('folder_play')
        for w in (self.vlist, self.header, self.tabs, self.empty):
            self.add_widget(w)
        self.btn_search = IconButton('search', callback=lambda w: self.toggle_search(True))
        self.btn_sort = IconButton('sort', callback=lambda w: self.open_sort())
        self.btn_close = IconButton('close', callback=lambda w: self.exit_selection())
        self.btn_menu = IconButton('dots', callback=lambda w: self.app.root.push(SettingsPage(self.app)))
        self.bind(pos=self._lay, size=self._lay)
        self._lay()
        self.update_header()

    # ---- layout ------------------------------------------------------------
    def _lay(self, *a):
        W, H = self.size
        nb = 0
        hh = dp(72) if (self.nav == 'library' and not self.ctx.sel_mode) else dp(60)
        self.header.size = (W, hh)
        self.header.pos = (self.x, (self.y + self.height) - hh)
        top = self.header.y
        if self.nav == 'library':
            self.tabs.size = (W, dp(52))
            self.tabs.pos = (self.x, top - dp(52))
            top -= dp(56)
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
        self.vlist.scroll = 0
        self.rebuild()

    def on_resume(self):
        self.refresh()                      # the list stays where the user left it

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
        elif self.mode == 'groups':
            if not self.query:
                items.append({'kind': 'gcreate'})
            for c in lib.groups():
                if self._match(c.name):
                    items.append({'kind': 'group', 'coll': c})
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
        self.ctx.reorder = bool(self.ctx.sel_mode and self.nav == 'library' and self.mode in ('playlists', 'groups'))
        self.vlist.reorderable = self.ctx.reorder
        items = self.build_items()
        self.vlist.set_items(items)
        if not items or (len(items) == 1 and items[0]['kind'] in ('create', 'gcreate')):
            if not self.app.loaded:
                self.empty.icon.name = 'clock'
                self.empty.ltext = 'جارٍ تحميل الفيديوهات…'
            elif not self.app.permitted:
                self.empty.icon.name = 'lock'
                self.empty.ltext = 'يلزم السماح بالوصول إلى الفيديوهات.\nاسمح بالوصول من إعدادات الهاتف ثم ارجع للتطبيق.'
            elif self.nav == 'history':
                self.empty.icon.name = 'clock'
                self.empty.ltext = 'لا يوجد سجل مشاهدة بعد'
            elif self.query:
                self.empty.icon.name = 'search'
                self.empty.ltext = 'لا توجد نتائج'
            elif self.mode == 'groups':
                self.empty.icon.name = 'folder'
                self.empty.ltext = 'لا توجد مجلدات بعد.\nاضغط «إنشاء مجلد جديد» لتجميع عدة قوائم تحت اسم واحد.'
            else:
                self.empty.icon.name = 'folder_play'
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
            self.header.set('%d محدد' % n, '', right, left, short=str(n))
            return
        if self.search_on:
            self.header.set('', '', [IconButton('close', callback=lambda w: self.toggle_search(False))], [],
                            extra=self.field)
            return
        if self.nav == 'history':
            self.header.set('السجل', '', [], [self.btn_search])
        elif self.nav == 'me':
            self.header.set('الإعدادات', '', [], [])
        else:
            left = [self.btn_menu, self.btn_search]
            if self.mode not in ('folders', 'groups'):
                left.append(self.btn_sort)
            self.header.set('على الجهاز', '', [], left, big=True)

    def _action_buttons(self):
        n = len(self.ctx.selected)
        btns = [IconButton('select_all', callback=lambda w: self.select_all())]
        videos = self.nav == 'history' or self.mode == 'videos'
        btns.append(IconButton('share', callback=lambda w: self.act_share()))
        if self.mode == 'groups' and self.nav == 'library':
            if n == 1:
                btns.append(IconButton('edit', callback=lambda w: self.act_rename()))
            btns.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
            return btns
        if videos:
            btns.append(IconButton('playlist_add', callback=lambda w: self.act_add()))
            if n == 1:
                btns.append(IconButton('edit', callback=lambda w: self.act_rename()))
            btns.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
        elif self.mode == 'playlists':
            btns.append(IconButton('folder_add', callback=lambda w: self.act_make_folder()))
            if n == 1:
                btns.append(IconButton('edit', callback=lambda w: self.act_rename()))
            btns.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
        else:
            btns.append(IconButton('playlist_add', callback=lambda w: self.act_add()))
        return btns

    def on_selection_changed(self):
        self.ctx.reorder = bool(self.ctx.sel_mode and self.nav == 'library' and self.mode in ('playlists', 'groups'))
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
                        SheetLabel('أو اضغط مطولاً على أي قائمة ثم اسحبها لمكانك', muted=True)]
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
                # a playlist only exists once it has videos: pick them first
                self.app.open_picker(None, new_name=name)
            ask_text(self.app, 'قائمة تشغيل جديدة', '', 'اسم القائمة', ok, 'التالي')
        elif k == 'gcreate':
            new_group_flow(self.app, after=lambda gid: self.app.open_group(gid))
        elif k == 'group':
            self.app.open_group(item['coll'].id)
        elif k == 'coll':
            self.app.open_collection(item['coll'].id)
        elif k == 'video':
            keys = [i['key'] for i in self.vlist.items if i.get('kind') == 'video']
            self.app.play(keys, keys.index(item['key']))

    def _reorder(self, src, dst):
        items = list(self.vlist.items)
        if not (self.nav == 'library' and self.mode in ('playlists', 'groups')):
            self.vlist.set_items(items)
            return
        dst = max(dst, 1 if items and items[0]['kind'] in ('create', 'gcreate') else 0)
        it = items.pop(src)
        items.insert(dst, it)
        if self.mode == 'groups':
            self.app.lib.set_groups_order([i['coll'].id for i in items if i['kind'] == 'group'])
        else:
            self.app.lib.set_collections_order([i['coll'].id for i in items if i['kind'] == 'coll'])
        self.vlist.set_items(items)

    def _selected_videos(self):
        lib = self.app.lib
        if self.nav == 'history' or self.mode == 'videos':
            return [k for k in self.ctx.selected if k in lib.videos]
        keys, seen = [], set()
        for cid in self.ctx.selected:                    # whole lists: every video once
            c = lib.collection(cid)
            if c:
                for k in c.keys:
                    if k not in seen:
                        seen.add(k)
                        keys.append(k)
        return keys

    def act_share(self):
        share_keys(self.app, self._selected_videos())

    def act_add(self):
        keys = self._selected_videos()
        if keys:
            choose_playlist(self.app, keys, after=self.exit_selection)

    def act_make_folder(self):
        """The selected playlists (in the order they have on screen) go into a NEW folder or into one
        of the folders that already exist."""
        app = self.app
        lib = app.lib
        ids = [c.id for c in lib.collections() if c.id in self.ctx.selected]
        if not ids:
            return

        def finish(msg):
            app.store.save()
            app.root.say(msg)
            self.exit_selection()
            app.root.refresh_pages()

        def new_folder():
            def ok(name):
                gid = lib.create_group(name, ids)
                finish('تم إنشاء المجلد «%s» وفيه %d قائمة' % (lib.group(gid).name, len(ids)))
            ask_text(app, 'مجلد جديد', '', 'اسم المجلد', ok, 'إنشاء')

        groups = lib.groups()
        if not groups:
            new_folder()
            return

        def build():
            rows = [SheetTitle('وضع القوائم في مجلد'),
                    SheetRow('مجلد جديد', icon='folder_add', callback=lambda w: choose(None))]
            for g in groups:
                rows.append(SheetRow(g.name, icon='folder', value=core.count_lists_label(len(g.lists)),
                                     callback=lambda w, gid=g.id: choose(gid)))
            return rows
        sheet = MenuSheet(app.root, build)

        def choose(gid):
            sheet.dismiss()
            if gid is None:
                new_folder()
                return
            n = lib.add_to_group(gid, ids)
            nm = lib.group(gid).name
            if n:
                finish('تمت إضافة %d قائمة إلى المجلد «%s»' % (n, nm))
            else:
                finish('القوائم موجودة بالفعل في المجلد «%s»' % nm)
        sheet.show()

    def act_rename(self):
        sid = next(iter(self.ctx.selected))
        lib = self.app.lib

        def after():
            self.app.store.save()
            self.exit_selection()
            self.rebuild()
        if self.mode == 'groups' and self.nav == 'library':
            g = lib.group(sid)
            if g is None:
                return

            def ok_g(name):
                lib.rename_group(sid, name)
                after()
            ask_text(self.app, 'تعديل اسم المجلد', g.name, 'اسم المجلد', ok_g)
        elif self.mode == 'playlists' and self.nav == 'library':
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
        if self.mode == 'groups':
            def ok_g():
                for gid in ids:
                    lib.delete_group(gid)
                app.root.say('تم حذف %d مجلد (القوائم والفيديوهات لم تُحذف)' % len(ids))
                after()
            confirm(app, 'حذف مجلدات',
                    'سيتم حذف %d مجلد فقط. القوائم التي بداخلها والفيديوهات تبقى كما هي.' % len(ids),
                    'حذف', ok_g)
            return

        def ok():
            for cid in ids:
                lib.delete_collection(cid)
            app.root.say('تم حذف %d قائمة (الفيديوهات لم تُحذف من الجهاز)' % len(ids))
            after()
        confirm(app, 'حذف قوائم التشغيل',
                'سيتم حذف %d قائمة من التطبيق فقط. الفيديوهات تبقى في الجهاز، '
                'ويمكنك استعادة القوائم من الإعدادات.' % len(ids), 'حذف', ok)


# ---------------------------------------------------------------------------
# Collection page (one playlist / folder)
# ---------------------------------------------------------------------------
class SettingsPage(Page):
    """The options (what used to be the 'Me' tab), opened from the 3-dots button."""

    def __init__(self, app, **kw):
        super(SettingsPage, self).__init__(app, **kw)
        self.header = Header()
        self.pane = SettingsPane(app, size_hint=(None, None))     # sized by _lay: below the header
        self.add_widget(self.pane)
        self.add_widget(self.header)
        self.header.set('الإعدادات', '', [IconButton('back', callback=lambda w: self.app.root.back())], [])
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    def _lay(self, *a):
        hh = dp(60)
        self.header.size = (self.width, hh)
        self.header.pos = (self.x, (self.y + self.height) - hh)
        self.pane.pos = self.pos
        self.pane.size = (self.width, max(0, (self.y + self.height) - hh - self.y))

    def refresh(self):
        self.pane.build()


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
        self.empty = EmptyState('playlist')
        for w in (self.vlist, self.header, self.empty):
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
        self.header.pos = (self.x, (self.y + self.height) - hh)
        self.vlist.pos = self.pos
        self.vlist.size = (self.width, max(0, (self.y + self.height) - hh - self.y))
        self.empty.pos = (self.x + dp(30), self.vlist.y + self.vlist.height * 0.4)
        self.empty.size = (self.width - dp(60), dp(80))

    def on_show(self):
        self.refresh()

    def on_resume(self):
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
            self.empty.ltext = 'القائمة فارغة.\nاضغط + لإضافة فيديوهات.' if not self.query \
                else 'لا توجد فيديوهات'
        else:
            self.empty.ltext = ''
        self.update_header()

    def update_header(self):
        c = self.coll
        if c is None:
            return
        if self.ctx.sel_mode:
            n = len(self.ctx.selected)
            left = [IconButton('select_all', callback=lambda w: self.select_all()),
                    IconButton('share', callback=lambda w: self.act_share()),
                    IconButton('playlist_add', callback=lambda w: self.act_add())]
            left.append(IconButton('trash', color=DANGER, callback=lambda w: self.act_delete()))
            left.append(IconButton('dots', callback=lambda w: self.more_menu()))
            self.header.set('%d محدد' % n, '', [self.btn_close], left, short=str(n))
            return
        if self.search_on:
            self.header.set('', '', [IconButton('close', callback=lambda w: self.toggle_search(False))], [],
                            extra=self.field)
            return
        sub = core.count_videos_label(c.count)
        total = self.app.lib.total_duration(c.keys)
        if total:
            sub += '  •  ' + core.fmt_time(total)
        left = [self.btn_add, self.btn_search, self.btn_sort]
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
            if mode == 'manual' and lib.collection_sort(self.cid)[0] != 'manual':
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

    def act_share(self):
        share_keys(self.app, selection_keys(self.ctx, self.app.lib))

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
            rows = [SheetTitle('المزيد'),
                    SheetRow('تشغيل المحدد', icon='play', callback=lambda w: do('play'))]
            if len(self.ctx.selected) == 1:
                rows.append(SheetRow('تعديل الاسم', icon='edit', callback=lambda w: (sheet.dismiss(), self.act_rename())))
            return rows + [
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


class GroupPage(Page, ListPageMixin):
    """One folder ("مجلد"): the lists that were put together under a name chosen by the user."""

    def __init__(self, app, cid, **kw):
        super(GroupPage, self).__init__(app, **kw)
        self.cid = cid
        self.init_list()
        self.ctx.reorder = True          # long press + move = reorder the lists
        self.vlist.reorderable = True
        self.header = Header()
        self.empty = EmptyState('folder')
        for w in (self.vlist, self.header, self.empty):
            self.add_widget(w)
        self.btn_back = IconButton('back', callback=lambda w: self.app.root.back())
        self.btn_close = IconButton('close', callback=lambda w: self.exit_selection())
        self.btn_add = IconButton('plus', callback=lambda w: self.add_lists())
        self.btn_menu = IconButton('dots', callback=lambda w: self.more_menu())
        self.bind(pos=self._lay, size=self._lay)
        self._lay()

    @property
    def group(self):
        return self.app.lib.group(self.cid)

    def _lay(self, *a):
        hh = dp(64)
        self.header.size = (self.width, hh)
        self.header.pos = (self.x, (self.y + self.height) - hh)
        self.vlist.pos = self.pos
        self.vlist.size = (self.width, max(0, (self.y + self.height) - hh - self.y))
        self.empty.pos = (self.x + dp(30), self.vlist.y + self.vlist.height * 0.4)
        self.empty.size = (self.width - dp(60), dp(80))

    def on_show(self):
        self.refresh()

    def on_resume(self):
        self.refresh()

    def on_back(self):
        if self.ctx.sel_mode:
            self.exit_selection()
            return True
        return False

    def refresh(self):
        g = self.group
        if g is None:
            Clock.schedule_once(lambda dt: self.app.root.pop(), 0)
            return
        self.vlist.reorderable = bool(self.ctx.sel_mode)
        self.vlist.set_items([{'kind': 'coll', 'coll': c} for c in g.lists])
        self.empty.ltext = '' if g.lists else 'المجلد فارغ.\nاضغط + لإضافة قوائم تشغيل.'
        self.update_header()

    def update_header(self):
        g = self.group
        if g is None:
            return
        if self.ctx.sel_mode:
            n = len(self.ctx.selected)
            left = [IconButton('select_all', callback=lambda w: self.select_all()),
                    IconButton('share', callback=lambda w: self.act_share()),
                    IconButton('trash', color=DANGER, callback=lambda w: self.act_remove())]
            self.header.set('%d محدد' % n, '', [self.btn_close], left, short=str(n))
            return
        sub = core.count_lists_label(len(g.lists)) + '  •  ' + core.count_videos_label(g.count)
        self.header.set(g.name, sub, [self.btn_back], [self.btn_menu, self.btn_add])

    def on_selection_changed(self):
        self.vlist.reorderable = bool(self.ctx.sel_mode)
        self.update_header()
        self.vlist.refresh()

    def open_item(self, idx, item):
        self.app.open_collection(item['coll'].id)

    def _reorder(self, src, dst):
        items = list(self.vlist.items)
        it = items.pop(src)
        items.insert(dst, it)
        self.app.lib.set_group_order(self.cid, [i['coll'].id for i in items])
        self.app.store.save()
        self.vlist.set_items(items)

    def add_lists(self):
        lib, app = self.app.lib, self.app
        g = self.group
        have = set(c.id for c in g.lists) if g else set()
        cands = [c for c in lib.collections() if c.id not in have]
        if not cands:
            app.root.say('كل القوائم موجودة بالفعل في هذا المجلد')
            return

        def done(cids):
            n = lib.add_to_group(self.cid, cids)
            app.store.save()
            app.root.say('تمت إضافة %d قائمة' % n)
            self.refresh()
            app.root.refresh_pages()
        pick_lists(app, 'إضافة قوائم إلى المجلد', cands, 'إضافة', done)

    def act_share(self):
        lib = self.app.lib
        keys, seen = [], set()
        for cid in self.ctx.selected:
            c = lib.collection(cid)
            for k in (c.keys if c else []):
                if k not in seen:
                    seen.add(k)
                    keys.append(k)
        share_keys(self.app, keys)

    def act_remove(self):
        ids = list(self.ctx.selected)
        lib, app = self.app.lib, self.app

        def ok():
            lib.remove_from_group(self.cid, ids)
            app.store.save()
            app.root.say('تمت الإزالة من المجلد (القوائم لم تُحذف)')
            self.exit_selection()
            self.refresh()
            app.root.refresh_pages()
        confirm(app, 'إزالة من المجلد',
                'سيتم إخراج %d قائمة من هذا المجلد فقط. القوائم والفيديوهات تبقى كما هي.' % len(ids),
                'إزالة', ok)

    def more_menu(self):
        lib, app = self.app.lib, self.app

        def build():
            return [SheetTitle('المجلد'),
                    SheetRow('إضافة قوائم', icon='plus', callback=lambda w: (sheet.dismiss(), self.add_lists())),
                    SheetRow('تعديل الاسم', icon='edit', callback=lambda w: (sheet.dismiss(), rename())),
                    SheetRow('حذف المجلد', icon='trash', danger=True,
                             callback=lambda w: (sheet.dismiss(), delete()))]
        sheet = MenuSheet(app.root, build)

        def rename():
            g = self.group
            if g is None:
                return

            def ok(name):
                lib.rename_group(self.cid, name)
                app.store.save()
                self.refresh()
                app.root.refresh_pages()
            ask_text(app, 'تعديل اسم المجلد', g.name, 'اسم المجلد', ok)

        def delete():
            def ok():
                lib.delete_group(self.cid)
                app.store.save()
                app.root.say('تم حذف المجلد (القوائم لم تُحذف)')
                app.root.pop()
                app.root.refresh_pages()
            confirm(app, 'حذف المجلد',
                    'سيتم حذف المجلد فقط. القوائم التي بداخله والفيديوهات تبقى كما هي.', 'حذف', ok)
        sheet.show()


# ---------------------------------------------------------------------------
# Picker: choose videos to add into a custom playlist
# ---------------------------------------------------------------------------
class PickerPage(Page, ListPageMixin):
    """Tick videos.  With a cid they are added to that list; with new_name (and no cid) they
    become a NEW playlist - which is only created when at least one video is ticked."""

    def __init__(self, app, cid, new_name=None, **kw):
        super(PickerPage, self).__init__(app, **kw)
        self.cid = cid
        self.new_name = new_name
        self.query = ''
        self.search_on = False
        self.field = None
        self.all_keys = []
        self.init_list()
        self.ctx.sel_mode = True
        self.ctx.reorder = False
        self.header = Header()
        for w in (self.vlist, self.header):
            self.add_widget(w)
        self.btn_close = IconButton('close', callback=lambda w: self.app.root.back())
        self.btn_ok = IconButton('check', color=ACCENT, callback=lambda w: self.confirm())
        self.btn_all = IconButton('select_all', callback=lambda w: self.select_all())
        self.btn_search = IconButton('search', callback=lambda w: self.toggle_search(True))
        self.bind(pos=self._lay, size=self._lay)
        self._lay()
        self.refresh()

    def _lay(self, *a):
        hh = dp(60)
        self.header.size = (self.width, hh)
        self.header.pos = (self.x, (self.y + self.height) - hh)
        self.vlist.pos = self.pos
        self.vlist.size = (self.width, max(0, (self.y + self.height) - hh - self.y))

    def _match(self, text):
        q = self.query.strip()
        if not q:
            return True
        return core.natural_key(q) == core.natural_key(text) or \
            q.casefold() in (text or '').casefold()

    def refresh(self):
        lib = self.app.lib
        existing = set(lib.items(self.cid)) if self.cid else set()
        self.all_keys = [k for k in lib.all_videos_sorted() if k not in existing]
        keys = [k for k in self.all_keys if self._match(lib.title(k))]
        self.vlist.set_items([{'kind': 'video', 'key': k} for k in keys])
        self.update_header()

    def update_header(self):
        if self.search_on:
            self.header.set('', '', [IconButton('close', callback=lambda w: self.toggle_search(False))], [],
                            extra=self.field)
            return
        n = len(self.ctx.selected)
        title = ('«%s»  •  %d' % (self.new_name, n)) if self.new_name else 'اختر الفيديوهات (%d)' % n
        self.header.set(title, 'اختر فيديو واحد على الأقل' if self.new_name else '', [self.btn_close],
                        [self.btn_ok, self.btn_all, self.btn_search], short=str(n))

    # ---- search ----------------------------------------------------------------------
    def toggle_search(self, on):
        if on:
            self.field = FieldInput(text='', hint='ابحث عن فيديو…')
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

    def on_back(self):
        if self.search_on:
            self.toggle_search(False)
            return True
        return False

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
        # every ticked video counts, also the ones a search is hiding right now
        keys = [k for k in self.all_keys if k in self.ctx.selected]
        if self.cid is None:
            if not keys:
                self.app.root.say('اختر فيديو واحد على الأقل لإنشاء القائمة')
                return
            cid = self.app.lib.create_playlist(self.new_name, keys)
            self.app.store.save()
            self.app.root.pop()
            self.app.root.refresh_pages()
            self.app.open_collection(cid)
            return
        if keys:
            n = self.app.lib.add_to_playlist(self.cid, keys)
            self.app.store.save()
            self.app.root.say('تمت إضافة %d فيديو' % n)
        self.app.root.pop()


_ = (textfix, SURFACE, SURFACE2, TEXT, DIVIDER, ChipsRow)   # imported for convenience
