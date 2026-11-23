# -*- coding: utf-8 -*-
"""
player.py - full screen video player page.

Gestures
    tap                    show / hide the controls
    double tap L / R / C   -step  / +step / play-pause
    long press (hold)      temporary fast playback (default 2x) until the finger is lifted
    swipe horizontal       seek (applied on release)
    swipe vertical left    brightness
    swipe vertical right   volume
"""
import gc
import os
import random
import time

from kivy.clock import Clock
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

import bridge
import core
from engine import Engine
from screens import Page
from widgets import (ACCENT, ON_ACCENT, SCRIM, SUB, SURFACE2, TEXT, Badge, ChipsRow, Dialog, Icon, IconButton, MenuSheet, SeekBar,
                     SheetLabel, SheetRow, SheetTitle, StepButton, Tap, Txt)

END_WAIT = 5.0                           # seconds the end-of-video choice stays before the next video starts
REPEAT_MODES = ['off', 'one', 'all', 'shuffle']
REPEAT_LABELS = {'off': 'بدون تكرار', 'one': 'تكرار الفيديو الحالي', 'all': 'تكرار القائمة',
                 'shuffle': 'عشوائي'}
SLEEP_OPTIONS = [0, 15, 30, 45, 60, 90]


TOPBG = (1, 1, 1, 0.10)             # soft discs behind the top bar buttons
SIDEBG = (1, 1, 1, 0.12)            # ... and behind lock / rotate


class Feedback(Widget):
    """Base of the little animations drawn over the video.  They never take touches, stay for a
    moment and then fade out."""

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Feedback, self).__init__(**kw)
        self.opacity = 0
        self._hold = None
        self._fade = None
        self.bind(pos=self._lay, size=self._lay)

    def _lay(self, *a):
        pass

    def on_touch_down(self, touch):
        return False

    def on_touch_move(self, touch):
        return False

    def on_touch_up(self, touch):
        return False

    def _appear(self):
        self._cancel()
        self.opacity = 1

    def _cancel(self):
        for ev in (self._hold, self._fade):
            if ev is not None:
                ev.cancel()
        self._hold = self._fade = None

    def _later(self, seconds):
        if self._hold is not None:
            self._hold.cancel()
        self._hold = Clock.schedule_once(self._start_fade, seconds)

    def _start_fade(self, dt):
        self._hold = None
        if self._fade is None:
            self._fade = Clock.schedule_interval(self._step, 0)

    def _step(self, dt):
        self.opacity = max(0.0, self.opacity - min(dt, 0.05) / 0.22)
        if self.opacity <= 0.0 and self._fade is not None:
            self._fade.cancel()
            self._fade = None

    def hide(self):
        self._cancel()
        self.opacity = 0


class SideFeedback(Feedback):
    """Double tap on the left / right third: that third of the screen lights up softly, with the
    arrows and the seconds skipped so far (tapping again adds up: 10, 20, 30 ...)."""

    def __init__(self, side, **kw):
        super(SideFeedback, self).__init__(**kw)
        self.side = side                        # 'back' = left third, 'fwd' = right third
        self.icon = Icon(name='fwd' if side == 'fwd' else 'rew', size=(dp(32), dp(32)))
        self.lbl = Txt(halign='center', align_mode='center', bold=True, font_size=sp(15),
                       size_hint=(None, None))
        self.add_widget(self.icon)
        self.add_widget(self.lbl)
        self._total = 0
        self._last = 0.0

    def bump(self, secs, area):
        now = time.time()
        if now - self._last > 1.0 or self.opacity <= 0.01:
            self._total = 0
        self._last = now
        self._total += abs(int(secs))
        self.lbl.ltext = '%d ثانية' % self._total
        self.pos = (area[0], area[1])
        self.size = (area[2], area[3])
        self._lay()
        self._appear()
        self._later(0.65)

    def _lay(self, *a):
        x, y, w, h = self.x, self.y, self.width, self.height
        self.canvas.before.clear()
        if w < 2 or h < 2:
            return
        r = min(w * 0.85, h * 0.5)
        rad = [0, r, r, 0] if self.side == 'back' else [r, 0, 0, r]
        with self.canvas.before:
            Color(1, 1, 1, 0.12)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=rad)
        cx, cy = x + w / 2.0, y + h / 2.0
        self.icon.center = (cx, cy + dp(18))
        self.lbl.pos = (x, cy - dp(36))
        self.lbl.size = (w, dp(28))


class CenterFeedback(Feedback):
    """Play / pause symbol that pops up in the middle after a double tap on the centre."""

    def __init__(self, **kw):
        super(CenterFeedback, self).__init__(**kw)
        self.icon = Icon(name='play', size=(dp(38), dp(38)))
        self.add_widget(self.icon)

    def flash(self, name, center):
        self.icon.name = name
        d = dp(78)
        self.size = (d, d)
        self.pos = (center[0] - d / 2.0, center[1] - d / 2.0)
        self._lay()
        self._appear()
        self._later(0.3)

    def _lay(self, *a):
        self.canvas.before.clear()
        if self.width < 2:
            return
        with self.canvas.before:
            Color(*SCRIM)
            Ellipse(pos=self.pos, size=self.size)
        self.icon.center = (self.x + self.width / 2.0, self.y + self.height / 2.0)


class LevelHud(Feedback):
    """Vertical bar on the screen edge for brightness / volume while the finger slides."""

    def __init__(self, **kw):
        kw.setdefault('size', (dp(58), dp(196)))
        super(LevelHud, self).__init__(**kw)
        self.value = 0.0
        self.icon = Icon(name='brightness', size=(dp(24), dp(24)))
        self.lbl = Txt(halign='center', align_mode='center', bold=True, font_size=sp(13),
                       size_hint=(None, None))
        self.add_widget(self.icon)
        self.add_widget(self.lbl)

    def show(self, kind, value, center):
        self.value = max(0.0, min(1.0, value))
        self.icon.name = 'brightness' if kind == 'brightness' else (
            'volume_mute' if self.value <= 0.001 else 'volume')
        self.lbl.ltext = '%d' % int(round(self.value * 100))
        self.pos = (center[0] - self.width / 2.0, center[1] - self.height / 2.0)
        self._lay()
        self._appear()

    def release(self):
        self._later(0.5)

    def _lay(self, *a):
        x, y, w, h = self.x, self.y, self.width, self.height
        self.canvas.before.clear()
        if w < 2 or h < 2:
            return
        cx = x + w / 2.0
        tw = dp(6)
        ty0 = y + dp(42)
        th = h - dp(42) - dp(54)
        with self.canvas.before:
            Color(*SCRIM)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[w / 2.0])
            Color(1, 1, 1, 0.22)
            RoundedRectangle(pos=(cx - tw / 2.0, ty0), size=(tw, th), radius=[tw / 2.0])
            Color(*ACCENT)
            RoundedRectangle(pos=(cx - tw / 2.0, ty0), size=(tw, max(tw, th * self.value)), radius=[tw / 2.0])
        self.icon.center = (cx, y + h - dp(28))
        self.lbl.pos = (x, y + dp(8))
        self.lbl.size = (w, dp(26))


class SeekCard(Feedback):
    """While swiping sideways: where the video would jump to, and by how much."""

    def __init__(self, **kw):
        kw.setdefault('size', (dp(176), dp(92)))
        super(SeekCard, self).__init__(**kw)
        self.frac = 0.0
        self.time = Txt(halign='center', align_mode='center', bold=True, font_size=sp(27),
                        size_hint=(None, None))
        self.delta = Txt(halign='center', align_mode='center', font_size=sp(14), size_hint=(None, None))
        self.add_widget(self.time)
        self.add_widget(self.delta)

    def show(self, target, base, dur, center):
        d = int(target - base)
        self.time.ltext = core.fmt_time(target)
        self.delta.ltext = '%s%d ثانية' % ('+' if d >= 0 else '−', abs(d))
        self.delta.color = list(ACCENT) if d >= 0 else [0.86, 0.88, 0.93, 1]
        self.frac = max(0.0, min(1.0, target / dur)) if dur and dur < 1e8 else 0.0
        self.pos = (center[0] - self.width / 2.0, center[1] - self.height / 2.0)
        self._lay()
        self._appear()

    def _lay(self, *a):
        x, y, w, h = self.x, self.y, self.width, self.height
        self.canvas.before.clear()
        if w < 2 or h < 2:
            return
        bx, bw = x + dp(20), w - dp(40)
        with self.canvas.before:
            Color(*SCRIM)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(20)])
            Color(1, 1, 1, 0.22)
            RoundedRectangle(pos=(bx, y + dp(14)), size=(bw, dp(4)), radius=[dp(2)])
            Color(*ACCENT)
            RoundedRectangle(pos=(bx, y + dp(14)), size=(max(dp(4), bw * self.frac), dp(4)), radius=[dp(2)])
        self.time.pos = (x, y + h - dp(46))
        self.time.size = (w, dp(40))
        self.delta.pos = (x, y + dp(24))
        self.delta.size = (w, dp(26))


class EndPanel(Widget):
    """Shown when a video ends: "play again" and "play next" (with a 5 s countdown on the latter)."""

    def __init__(self, on_replay=None, on_next=None, **kw):
        kw.setdefault('size_hint', (None, None))
        super(EndPanel, self).__init__(**kw)
        self.on_replay, self.on_next = on_replay, on_next
        self.has_next = False
        self.frac = 1.0
        self.title = Txt(ltext='انتهى الفيديو', bold=True, font_size=sp(18), align_mode='center',
                         halign='center', size_hint=(None, None))
        self.sub = Txt(color=SUB, font_size=sp(13), align_mode='center', halign='center',
                       size_hint=(None, None))
        self.btn_replay = Tap(callback=lambda w: self.on_replay and self.on_replay(),
                              size_hint=(None, None), height=dp(52))
        self.btn_next = Tap(callback=lambda w: self.on_next and self.on_next(),
                            size_hint=(None, None), height=dp(52))
        for b in (self.btn_replay, self.btn_next):
            b.fb_radius = [dp(16)] * 4
        self.lbl_replay = Txt(ltext='إعادة تشغيل', bold=True, font_size=sp(15.5), color=TEXT,
                              halign='center', align_mode='center', size_hint=(None, None))
        self.lbl_next = Txt(ltext='تشغيل التالي', bold=True, font_size=sp(15.5), color=ON_ACCENT,
                            halign='center', align_mode='center', size_hint=(None, None))
        self.count = Txt(ltext='', bold=True, font_size=sp(15), color=ON_ACCENT, halign='center',
                         align_mode='center', size_hint=(None, None))
        self.btn_replay.add_widget(self.lbl_replay)
        self.btn_next.add_widget(self.lbl_next)
        self.btn_next.add_widget(self.count)
        for w in (self.title, self.sub, self.btn_replay, self.btn_next):
            self.add_widget(w)
        self._bar = None
        self.bind(pos=self._lay, size=self._lay)

    def configure(self, next_title, counting):
        """next_title: title of the next video, or None when there is none."""
        self.has_next = next_title is not None
        self.sub.ltext = ('التالي: ' + next_title) if next_title else ''
        self.btn_next.opacity = 1 if self.has_next else 0
        self.btn_next.disabled = not self.has_next
        self.frac = 1.0
        self.count.ltext = '%d' % int(END_WAIT) if (self.has_next and counting) else ''
        self._lay()

    def set_remaining(self, secs):
        """Countdown tick (secs left, or None to show no countdown)."""
        if secs is None:
            self.frac = 1.0
            self.count.ltext = ''
        else:
            self.frac = max(0.0, min(1.0, secs / END_WAIT))
            n = '%d' % max(1, int(secs + 0.999))
            if n != self.count.ltext:
                self.count.ltext = n
        if self._bar is not None:
            self._bar.size = (max(0.0, self._bar_w * self.frac), dp(3))

    def _lay(self, *a):
        x, y, w, h = self.x, self.y, self.width, self.height
        self.canvas.before.clear()
        self._bar = None
        if w < 10 or h < 10:
            return
        pad, gap = dp(18), dp(10)
        with self.canvas.before:
            Color(0.07, 0.075, 0.09, 0.94)
            RoundedRectangle(pos=(x, y), size=(w, h), radius=[dp(24)])
            Color(1, 1, 1, 0.08)
            Line(rounded_rectangle=(x + 0.5, y + 0.5, w - 1, h - 1, dp(24)), width=1)
        self.title.pos = (x + pad, y + h - dp(52))
        self.title.size = (w - 2 * pad, dp(34))
        self.sub.pos = (x + pad, y + h - dp(80))
        self.sub.size = (w - 2 * pad, dp(26))
        bw = (w - 2 * pad - gap) / 2.0 if self.has_next else w - 2 * pad
        by = y + dp(24)
        # RTL: replay on the right, next on the left
        self.btn_replay.size = (bw, dp(52))
        self.btn_replay.pos = ((x + w) - pad - bw, by)
        self.btn_next.size = (bw, dp(52))
        self.btn_next.pos = (x + pad, by)
        for b, lbl, accent in ((self.btn_replay, self.lbl_replay, not self.has_next),
                               (self.btn_next, self.lbl_next, True)):
            lbl.pos = b.pos
            lbl.size = b.size
            b.canvas.before.clear()
            with b.canvas.before:
                Color(*(ACCENT if accent else SURFACE2))
                RoundedRectangle(pos=b.pos, size=b.size, radius=[dp(16)])
        self.lbl_next.pos = (self.btn_next.x + dp(34), by)            # the number sits at the left end
        self.lbl_next.size = (max(10, bw - dp(34)), dp(52))
        self.lbl_replay.color = list(ON_ACCENT if not self.has_next else TEXT)
        self.count.pos = (self.btn_next.x + dp(4), by)
        self.count.size = (dp(32), dp(52))
        self._bar_w = w - 2 * pad
        with self.canvas.before:
            Color(1, 1, 1, 0.12)
            RoundedRectangle(pos=(x + pad, y + dp(12)), size=(self._bar_w, dp(3)), radius=[dp(1.5)])
            Color(*ACCENT)
            self._bar = RoundedRectangle(pos=(x + pad, y + dp(12)), size=(self._bar_w * self.frac, dp(3)),
                                         radius=[dp(1.5)])

    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        Widget.on_touch_down(self, touch)           # the two buttons
        return True


class PlayerPage(Page):
    BGCOLOR = (0, 0, 0, 1)                   # the bars around the picture are pure black

    def __init__(self, app, keys, index, cid=None, **kw):
        super(PlayerPage, self).__init__(app, **kw)
        self.lib = app.lib
        self.store = app.store
        self.queue = list(keys)
        self.cid = cid
        self.order = list(range(len(self.queue)))
        self.cursor = max(0, min(index, len(self.queue) - 1))
        self.shuffled = False
        self.key = None
        self.locked = False
        self.ctl_visible = True
        self.seeking = False
        self.speed = float(self.store.setting('speed') or 1.0)
        self.hold_active = False
        self.repeat = self.store.setting('repeat')
        self.sub_files = []
        self.sub_track = None
        self.sub_delay = 0.0
        self.sub_text = ''
        self.sleep_at = 0
        self.g = None
        self._last_tap = None
        self._single_ev = None
        self._hide_ev = None
        self._closed = False
        self._oriented = False
        self._last_save = 0
        self._brightness = None
        self._ended = False
        self._last_up = 0.0
        self._place_key = None
        self._cur_txt = None
        self._dur_txt = None
        self.perf_on = False                    # performance overlay (player menu)
        self.perf = None
        self._perf_next = 0.0
        self.engine = Engine(on_frame=self._on_frame, on_eof=self._on_eof, on_error=self._on_error)

        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._vrect = Rectangle(pos=self.pos, size=(0, 0))

        self.ctl = FloatLayout(size_hint=(1, 1))
        self.add_widget(self.ctl)
        self.btn_back = IconButton('back', callback=lambda w: self.app.root.back(), bg=TOPBG, bg_d=dp(40))
        self.title = Txt(font_size=sp(16.5), align_mode='auto', size_hint=(None, None), bold=True)
        self.qinfo = Txt(font_size=sp(12), color=(1, 1, 1, 0.66), align_mode='left', size_hint=(None, None))
        self.btn_cc = IconButton('subtitle', callback=lambda w: self.subtitle_menu(), bg=TOPBG, bg_d=dp(40),
                                 icon_size=dp(22))
        self.btn_more = IconButton('dots', callback=lambda w: self.main_menu(), bg=TOPBG, bg_d=dp(40))
        self.cur = Txt(font_size=sp(13), halign='left', bold=True, size_hint=(None, None))
        self.dur = Txt(font_size=sp(13), halign='right', color=(1, 1, 1, 0.72), size_hint=(None, None))
        self.seek = SeekBar(on_start=self._seek_start, on_move=self._seek_move, on_end=self._seek_end,
                            size_hint=(None, None), size=(dp(100), dp(36)))
        self.btn_lock = IconButton('unlock', callback=lambda w: self.set_lock(True), bg=SIDEBG, bg_d=dp(40), icon_size=dp(24))
        self.btn_prev = IconButton('prev', callback=lambda w: self.prev())
        self.btn_rew = StepButton('back', callback=lambda w: self.skip(-self._step()), value=self._step())
        self.btn_play = IconButton('pause', callback=lambda w: self.toggle_play(), icon_size=dp(30),
                                   size=(dp(64), dp(64)), bg=(1, 1, 1, 0.95), color=(0.06, 0.06, 0.08, 1))
        self.btn_fwd = StepButton('fwd', callback=lambda w: self.skip(self._step()), value=self._step())
        self.btn_next = IconButton('next', callback=lambda w: self.next())
        for b in (self.btn_prev, self.btn_next):
            b.size = (dp(48), dp(48))
            b.icon.size = (dp(28), dp(28))
        self.btn_rot = IconButton('screen_rotate', callback=lambda w: self.rotate(), bg=SIDEBG, bg_d=dp(40), icon_size=dp(23))
        self.btn_unlock = IconButton('lock', color=ACCENT, callback=lambda w: self.set_lock(False),
                                     size=(dp(56), dp(56)), bg=(0.17, 0.17, 0.2, 0.92), bg_d=dp(48))
        for w in (self.btn_back, self.title, self.qinfo, self.btn_cc, self.btn_more, self.cur, self.dur,
                  self.seek, self.btn_lock, self.btn_prev, self.btn_rew, self.btn_play, self.btn_fwd,
                  self.btn_next, self.btn_rot):
            self.ctl.add_widget(w)
        self.sub_lbl = Txt(font_size=sp(self.store.setting('sub_size')), halign='center', valign='bottom',
                           nlines=2, keep_nl=True, size_hint=(None, None), outline_width=dp(2),
                           outline_color=(0, 0, 0, 1), bold=True)
        self.add_widget(self.sub_lbl)
        self.fb = Badge()                                   # short messages (+10 s from a button)
        self.speed_tag = Badge(font=sp(14))                 # shown for two seconds when the speed changes
        self.hold_pill = Badge(pulse=True)                  # the 2x while the finger is held down
        self.bubble = Badge(font=sp(14))                    # time above the seek bar knob
        self.step_fb = {'back': SideFeedback('back'), 'fwd': SideFeedback('fwd')}
        self.center_fb = CenterFeedback()
        self.level = LevelHud()
        self.seek_card = SeekCard()
        for w in (self.step_fb['back'], self.step_fb['fwd'], self.center_fb, self.seek_card, self.level,
                  self.fb, self.speed_tag, self.hold_pill, self.bubble, self.btn_unlock):
            self.add_widget(w)
        self.btn_unlock.opacity = 0
        self.end_panel = EndPanel(on_replay=self._end_replay, on_next=self._end_next)
        self._end_ev = None
        self._end_until = None
        self.bind(pos=self._lay, size=self._lay)
        self._lay()
        self._ui_ev = Clock.schedule_interval(self._ui_tick, 0.1)
        self._wd_ev = Clock.schedule_interval(self._hold_watchdog, 0.25)

    # ------------------------------------------------------------------ lifecycle
    def on_show(self):
        if self._closed:
            return
        bridge.set_immersive(True)
        if self.store.setting('keep_awake'):
            bridge.keep_awake(True)
        if self.key is None:
            self._quiet_start()
            self._start_current()
        self.show_controls(True)

    def _quiet_start(self):
        """Playback must not hitch: (1) the pages under the player are not drawn at all while it
        is on top, (2) everything the app allocated so far is moved out of the garbage collector's
        reach so it never scans it in the middle of a video."""
        try:
            self.app.root.suspend_below(self)
        except Exception:
            pass
        try:
            gc.collect()
            gc.freeze()
        except Exception:
            pass

    def on_close(self):
        if self._closed:
            return
        self._closed = True
        self._hide_end()
        self.save_progress(force=True)
        try:
            self._ui_ev.cancel()
            self._wd_ev.cancel()
        except Exception:
            pass
        self.engine.close()
        try:
            gc.unfreeze()
        except Exception:
            pass
        bridge.set_immersive(False)
        bridge.keep_awake(False)
        if self._brightness is not None:
            bridge.set_brightness(None)
        bridge.set_orientation(bridge.SCREEN_PORTRAIT)
        self.store.save()

    def on_app_pause(self):
        if not self._closed:
            if self._end_until is not None:          # do not start the next video behind the user's back
                self._cancel_end_timer()
                self.end_panel.set_remaining(None)
            self.save_progress(force=True)
            if not self.engine.paused:
                self.engine.set_pause(True)
                self._sync_play_icon()
            self.store.save()

    def on_app_resume(self):
        if not self._closed:
            bridge.set_immersive(True)

    def on_back(self):
        if self.locked:
            self.app.root.say('الشاشة مقفلة، اضغط على القفل لفتحها')
            self._flash_unlock()
            return True
        return False

    # ------------------------------------------------------------------ queue
    def _current_index(self):
        return self.order[self.cursor]

    def _start_current(self, start=None):
        if not self.queue:
            return
        self.save_progress(force=True)
        idx = self._current_index()
        key = self.queue[idx]
        v = self.lib.videos.get(key)
        if v is None or not os.path.exists(v['path']):
            self.app.root.say('الملف غير موجود')
            return
        self.key = key
        self._clear_ended()
        self._oriented = False
        self.title.ltext = self.lib.title(key)
        self.qinfo.ltext = ('%d / %d' % (self.cursor + 1, len(self.queue))) if len(self.queue) > 1 else ''
        self.qinfo.align_mode = 'right' if core.has_arabic(self.title.ltext) else 'left'
        if start is None:
            start = self.lib.resume_pos(key) if self.store.setting('resume') else 0.0
        self.lib.mark_started(key)
        bridge.crumb('player: load %s' % v['path'])
        self.engine.open(v['path'], start=start, speed=self.speed, paused=False,
                         duration_hint=v.get('duration', 0))
        self._sync_play_icon()
        self.seek.value = 0
        self._load_subs(v['path'])
        self.show_controls(True)

    def next(self, auto=False):
        n = len(self.queue)
        if n <= 1:
            if auto:
                return False
            self.engine.seek(0)
            return True
        if self.cursor + 1 < n:
            self.cursor += 1
        elif self.repeat in ('all', 'shuffle') or not auto:
            self.cursor = 0
        else:
            return False
        self._start_current()                    # carries on where that video was left (if 'resume' is on)
        return True

    def prev(self):
        """Always the previous video, however far into this one we are (it carries on where it was left).
        Only on the first video does it restart the current one."""
        if self.cursor == 0:
            self.engine.seek(0)
            return
        self.cursor -= 1
        self._start_current()

    def _apply_repeat_order(self):
        cur_idx = self._current_index()
        if self.repeat == 'shuffle':
            rest = [i for i in range(len(self.queue)) if i != cur_idx]
            random.shuffle(rest)
            self.order = [cur_idx] + rest
            self.cursor = 0
            self.shuffled = True
        elif self.shuffled:
            self.order = list(range(len(self.queue)))
            self.cursor = cur_idx
            self.shuffled = False

    # ------------------------------------------------------------------ engine callbacks
    def _on_frame(self, tex):
        """A new picture is ready.  The engine drew it into `tex` behind Kivy's back, so the
        screen must be told to redraw (without this the picture only refreshes when some other
        widget happens to change, which looks like heavy stutter)."""
        vr = self._vrect
        if vr.texture is not tex:
            vr.texture = tex
            self._place_key = None
        w, h = self.engine.size
        key = (w, h, self.width, self.height)
        if key != self._place_key:
            self._place_key = key
            self._place_video()
        self.canvas.ask_update()

    def _on_eof(self):
        if self._closed:
            return
        self._ended = True
        if self.key:
            self.lib.set_progress(self.key, 0, self.engine.duration)
        if self.repeat == 'one':
            self.engine.open(self.lib.videos[self.key]['path'], 0, self.speed, False,
                             self.engine.duration)
            self._ended = False
            return
        # the video is over: let the person choose (replay / next) instead of jumping on at once
        self.engine.set_pause(True)
        self._sync_play_icon()
        nxt = self._next_title()
        self.show_controls(False)
        self._show_end(nxt, counting=bool(self.store.setting('autoplay_next')) and nxt is not None)

    # ------------------------------------------------------------------ end of video
    def _has_next(self):
        n = len(self.queue)
        if n <= 1:
            return False
        return self.cursor + 1 < n or self.repeat in ('all', 'shuffle')

    def _next_title(self):
        if not self._has_next():
            return None
        c = self.cursor + 1 if self.cursor + 1 < len(self.queue) else 0
        return self.lib.title(self.queue[self.order[c]])

    def _show_end(self, next_title, counting):
        self._cancel_end_timer()
        self.end_panel.configure(next_title, counting)
        if self.end_panel.parent is None:
            self.add_widget(self.end_panel)
        self._lay_end()
        if counting:
            self._end_until = time.time() + END_WAIT
            self._end_ev = Clock.schedule_interval(self._end_tick, 0.1)

    def _cancel_end_timer(self):
        if self._end_ev is not None:
            self._end_ev.cancel()
            self._end_ev = None
        self._end_until = None

    def _hide_end(self):
        self._cancel_end_timer()
        if self.end_panel.parent is self:
            self.remove_widget(self.end_panel)

    def _clear_ended(self):
        """The video is playing / seeking again: the end-of-video choice is obsolete."""
        self._ended = False
        self._hide_end()

    def _end_tick(self, dt):
        if self._closed or self._end_until is None:
            self._cancel_end_timer()
            return
        left = self._end_until - time.time()
        if left <= 0:
            self._end_next()
        else:
            self.end_panel.set_remaining(left)

    def _end_replay(self):
        self._hide_end()
        self._start_current(start=0.0)

    def _end_next(self):
        self._hide_end()
        if not self.next(auto=True):
            self._start_current(start=0.0)

    def _on_error(self, msg):
        self.app.root.say('تعذر تشغيل الفيديو')
        try:
            self.app.show_error('PLAYBACK ERROR:\n\n' + str(msg))
        except Exception:
            pass

    # ------------------------------------------------------------------ playback actions
    def _step(self):
        return float(self.store.setting('seek_step') or 10)

    def toggle_play(self):
        if self._ended:
            self._start_current(start=0.0)
            return
        self.engine.toggle_pause()
        self._sync_play_icon()
        if self.engine.paused:
            self.save_progress(force=True)
        self.show_controls(True)

    def _sync_play_icon(self):
        self.btn_play.set_icon('play' if self.engine.paused else 'pause')

    def skip(self, delta, show=True, side=None):
        pos = self.engine.position
        dur = self.engine.duration or 1e9
        target = max(0.0, min(dur - 0.5, pos + delta))
        self.engine.seek(target)
        self._clear_ended()
        if show:
            if side in self.step_fb:
                W, H = self.size
                x = self.x if side == 'back' else self.x + W * 2.0 / 3.0
                fh = min(H, max(dp(260), W / 3.0 * 1.6))      # not a full-height column in portrait
                self.step_fb[side].bump(delta, (x, self.y + (H - fh) / 2.0, W / 3.0, fh))
            else:
                self.fb.show('%s%d ث' % ('+' if delta > 0 else '−', abs(int(delta))), self._center(),
                             icon='step_fwd' if delta > 0 else 'step_back', duration=0.7)
        if side not in self.step_fb:            # a double tap on the screen leaves the controls alone
            self.show_controls(True)

    def set_speed(self, s, say=True):
        self.speed = float(s)
        self.store.set_setting('speed', self.speed)
        self.engine.set_speed(self.speed)
        self._sync_speed_tag()
        if say:
            self.app.root.say('السرعة ' + core.fmt_speed(self.speed))

    def _sync_speed_tag(self):
        """Tell the speed for two seconds after it was changed, then let the picture be."""
        if abs(self.speed - 1.0) > 1e-6 and not self.hold_active:
            self.speed_tag.show(core.fmt_speed(self.speed),
                                ((self.x + self.width / 2.0), (self.y + self.height) - dp(86)),
                                icon='speed', h=dp(34), duration=2.0)
        else:
            self.speed_tag.hide()

    def rotate(self):
        """Turn the screen: portrait -> landscape and back."""
        land = self.width > self.height
        bridge.set_orientation(bridge.SCREEN_PORTRAIT if land else bridge.SCREEN_LANDSCAPE)
        self.show_controls(True)

    def set_lock(self, on):
        self.locked = bool(on)
        if on:
            self.show_controls(False)
            self._flash_unlock()
        else:
            self.btn_unlock.opacity = 0
            self.show_controls(True)

    def _flash_unlock(self):
        self.btn_unlock.opacity = 1
        Clock.unschedule(self._hide_unlock)
        Clock.schedule_once(self._hide_unlock, 2.5)

    def _hide_unlock(self, dt):
        self.btn_unlock.opacity = 0

    # ------------------------------------------------------------------ controls visibility
    def show_controls(self, show):
        if self._hide_ev:
            self._hide_ev.cancel()
            self._hide_ev = None
        if self.locked:
            show = False
        self.ctl_visible = show
        self._attach_ctl(show)
        self._lay()
        if show:
            self._update_time_ui(self.engine.position, force=True)
            self.btn_rew.set_value(self._step())
            self.btn_fwd.set_value(self._step())
        if show and not self.engine.paused and not self.seeking:
            self._hide_ev = Clock.schedule_once(lambda dt: self.show_controls(False), 3.8)

    def _attach_ctl(self, on):
        """Hidden controls are taken out of the widget tree: an invisible widget is still drawn
        (and still costs time) on every frame, a removed one costs nothing."""
        ctl = self.ctl
        if on and ctl.parent is None:
            self.add_widget(ctl, index=len(self.children))      # under pills / subtitles
        elif not on and ctl.parent is self:
            self.remove_widget(ctl)

    # ------------------------------------------------------------------ seekbar
    def _seek_start(self, v):
        self.seeking = True
        if self._hide_ev:
            self._hide_ev.cancel()
        self._seek_move(v)

    def _seek_move(self, v):
        d = self.engine.duration
        if d:
            self.cur.ltext = core.fmt_time(v * d)
            self.bubble.show(core.fmt_time(v * d), (self.seek.thumb_x(), self.seek.y + dp(54)), h=dp(32))

    def _seek_end(self, v):
        self.seeking = False
        self.bubble.hide()
        d = self.engine.duration
        if d:
            self.engine.seek(v * d, accurate=True)
            self._clear_ended()
        self.show_controls(True)

    # ------------------------------------------------------------------ periodic work
    def _update_time_ui(self, pos, force=False):
        e = self.engine
        if not self.seeking:
            if e.duration:
                v = max(0.0, min(1.0, pos / e.duration))
                if force or abs(v - self.seek.value) > 1.0 / max(300.0, self.seek.width):
                    self.seek.value = v
            t = core.fmt_time(pos)
            if t != self._cur_txt:
                self._cur_txt = t
                self.cur.ltext = t
        d = core.fmt_time(e.duration) if e.duration else '--:--'
        if d != self._dur_txt:
            self._dur_txt = d
            self.dur.ltext = d

    def _ui_tick(self, dt):
        if self._closed:
            return
        e = self.engine
        pos = e.position
        if self.ctl_visible:                    # nobody sees the time bar otherwise
            self._update_time_ui(pos)
        if self.perf_on:
            self._update_perf()
        # subtitles
        txt = ''
        if self.sub_track is not None and self.store.setting('sub_on'):
            txt = self.sub_track.at(pos - self.sub_delay)
        if txt != self.sub_text:
            self.sub_text = txt
            self.sub_lbl.ltext = txt
        # progress + sleep timer
        now = time.time()
        if now - self._last_save > 5 and not e.paused:
            self.save_progress()
        if self.sleep_at and now >= self.sleep_at:
            self.sleep_at = 0
            e.set_pause(True)
            self._sync_play_icon()
            self.save_progress(force=True)
            self.app.root.say('انتهى مؤقت النوم')
            self.show_controls(True)

    # ------------------------------------------------------------------ performance overlay
    def _set_perf(self, on):
        self.perf_on = bool(on)
        if on:
            if self.perf is None:
                from kivy.uix.label import Label
                self.perf = Label(text='', font_size=sp(11), size_hint=(None, None), halign='left',
                                  valign='top', color=(0.55, 1, 0.55, 1))
                self.perf.bind(size=lambda w, v: setattr(w, 'text_size', v))
            if self.perf.parent is None:
                self.add_widget(self.perf)
            self._lay_perf()
            self._perf_next = 0.0
        elif self.perf is not None and self.perf.parent is self:
            self.remove_widget(self.perf)

    def _lay_perf(self):
        if self.perf is not None:
            self.perf.size = (dp(340), dp(96))
            self.perf.pos = (self.x + dp(10), (self.y + self.height) - dp(170))

    def _update_perf(self):
        now = time.time()
        if now < self._perf_next or self.perf is None:
            return
        self._perf_next = now + 0.5
        e = self.engine
        impl = getattr(e, 'impl', e)
        kind = 'HW' if impl.__class__.__name__ == 'HWEngine' else 'SW'
        st = getattr(impl, 'stats', None) or {}
        try:
            loop = Clock.get_rfps()
        except Exception:
            loop = 0
        w, h = e.size
        self.perf.text = '\n'.join([
            '%s  %dx%d  speed %.2f' % (kind, w, h, e.speed),
            'screen %d fps   video %.0f fps' % (loop, st.get('fps', 0)),
            'longest gap %.0f ms   busiest frame %.1f ms' % (st.get('gap', 0), st.get('work', 0)),
            'frames skipped %d   held %d   pacing %s (%.2f)' % (
                st.get('skipped', 0), st.get('held', 0), 'on' if st.get('paced') else 'off', st.get('lock', 0))])

    def save_progress(self, force=False):
        if not self.key:
            return
        e = self.engine
        if not e.duration and not force:
            return
        pos = e.position
        if self._ended:
            pos = 0
        self.lib.set_progress(self.key, pos, e.duration)
        self._last_save = time.time()
        if force:
            self.store.save()

    # ------------------------------------------------------------------ geometry
    def _center(self):
        return ((self.x + self.width / 2.0), (self.y + self.height / 2.0) + dp(50))

    def _place_video(self):
        w, h = self.engine.size
        W, H = self.size
        if not w or not h or W <= 1:
            self._vrect.size = (0, 0)
            return
        ar = w / float(h)
        k = min(W / ar, H)                           # the whole picture, black bars where it does not fill
        rw, rh = k * ar, k
        self._vrect.size = (rw, rh)
        self._vrect.pos = (self.x + (W - rw) / 2.0, self.y + (H - rh) / 2.0)

    def _lay(self, *a):
        if not hasattr(self, 'btn_unlock'):
            return
        W, H = self.size
        x0, y0 = self.pos
        land = W > H
        pad = dp(28) if land else dp(10)
        top_h = dp(66)
        bot_h = dp(138)
        self.ctl.canvas.before.clear()
        if not hasattr(self, '_grad'):
            from kivy.graphics.texture import Texture
            t = Texture.create(size=(1, 2), colorfmt='rgba')
            t.blit_buffer(bytes([0, 0, 0, 0, 0, 0, 0, 205]), colorfmt='rgba', bufferfmt='ubyte')
            t.mag_filter = 'linear'
            self._grad = t
        with self.ctl.canvas.before:
            Color(1, 1, 1, 1)
            Rectangle(pos=(x0, y0), size=(W, bot_h + dp(30)), texture=self._grad,
                      tex_coords=(0, 1, 1, 1, 1, 0, 0, 0))
            Rectangle(pos=(x0, y0 + H - top_h - dp(20)), size=(W, top_h + dp(20)), texture=self._grad)
        # top bar: back on the right, title (+ position in the queue), then cc / menu on the left
        top = y0 + H - top_h
        self.btn_back.pos = (x0 + W - pad - dp(48), top + dp(9))
        self.btn_more.pos = (x0 + pad, top + dp(9))
        self.btn_cc.pos = (self.btn_more.x + dp(46), top + dp(9))
        tl = self.btn_cc.x + dp(50)
        tw = max(10, self.btn_back.x - tl - dp(6))
        if self.qinfo.ltext:
            self.title.pos = (tl, top + dp(30))
            self.title.size = (tw, dp(28))
            self.qinfo.pos = (tl, top + dp(10))
            self.qinfo.size = (tw, dp(20))
        else:
            self.title.pos = (tl, top + dp(4))
            self.title.size = (tw, top_h - dp(8))
            self.qinfo.size = (0, 0)
        # seek row
        sy = y0 + dp(78)
        self.cur.pos = (x0 + pad + dp(4), sy)
        self.cur.size = (dp(54), dp(36))
        self.dur.pos = (x0 + W - pad - dp(58), sy)
        self.dur.size = (dp(54), dp(36))
        self.seek.pos = (x0 + pad + dp(54), sy)
        self.seek.size = (max(10, W - 2 * pad - dp(108)), dp(36))
        # transport row: lock | prev  -10  PLAY  +10  next | rotate screen
        ry = y0 + dp(8)
        cx = x0 + W / 2.0
        narrow = W < dp(420)
        play, st, mid, sd = (dp(60), dp(48), dp(44), dp(44)) if narrow else (dp(64), dp(52), dp(48), dp(48))
        for b, d in ((self.btn_play, play), (self.btn_rew, st), (self.btn_fwd, st), (self.btn_prev, mid),
                     (self.btn_next, mid), (self.btn_lock, sd), (self.btn_rot, sd)):
            b.size = (d, d)
        gap = max(dp(2), min(dp(14), (W - 2 * pad - 2 * sd - play - 2 * st - 2 * mid) / 8.0))
        cyr = ry + play / 2.0
        self.btn_play.pos = (cx - play / 2.0, ry)
        self.btn_rew.pos = (self.btn_play.x - gap - st, cyr - st / 2.0)
        self.btn_prev.pos = (self.btn_rew.x - gap - mid, cyr - mid / 2.0)
        self.btn_fwd.pos = (self.btn_play.x + play + gap, cyr - st / 2.0)
        self.btn_next.pos = (self.btn_fwd.x + st + gap, cyr - mid / 2.0)
        self.btn_lock.pos = (x0 + pad, cyr - sd / 2.0)
        self.btn_rot.pos = (x0 + W - pad - sd, cyr - sd / 2.0)
        self.btn_unlock.center = (x0 + pad + dp(34), y0 + H / 2.0)
        # subtitles
        base = dp(154) if self.ctl_visible else dp(28)
        self.sub_lbl.size = (W * 0.9, dp(110))
        self.sub_lbl.pos = (x0 + W * 0.05, y0 + base)
        self._place_video()
        self._lay_perf()
        self._lay_end()

    def _lay_end(self):
        cx, cy = self.x + self.width / 2.0, self.y + self.height / 2.0
        w = min(self.width - dp(32), dp(400))
        h = dp(172)
        self.end_panel.size = (w, h)
        self.end_panel.pos = (cx - w / 2.0, cy - h / 2.0)

    # ------------------------------------------------------------------ gestures
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if self.end_panel.parent is self and self.end_panel.on_touch_down(touch):
            return True
        if self.locked:
            if self.btn_unlock.opacity and self.btn_unlock.on_touch_down(touch):
                return True
        elif self.ctl_visible:
            if self.ctl.on_touch_down(touch):
                return True
        touch.grab(self)
        now = time.time()
        self._release_hold()                       # never leave a previous hold running
        self.g = {'uid': touch.uid, 'sx': touch.x, 'sy': touch.y, 'mode': None, 'time': now,
                  'moved': False}
        # no hold-to-speed while the user is tapping quickly (double-tap skips)
        if not self.locked and now - self._last_up > 0.45:
            self.g['ev'] = Clock.schedule_once(self._hold_start, 0.4)
        return True

    def _release_hold(self):
        if self.hold_active:
            self.hold_active = False
            self.hold_pill.hide()
            self.engine.set_speed(self.speed)

    def _hold_watchdog(self, dt):
        """If the finger is gone but the 2x is still running (lost touch-up), stop it."""
        if not self.hold_active:
            return
        try:
            from kivy.base import EventLoop
            alive = [t.uid for t in EventLoop.touches]
        except Exception:
            return
        g = self.g
        if not g or g['uid'] not in alive:
            self.g = None
            self._release_hold()

    def _hold_start(self, dt):
        g = self.g
        if not g or g['mode'] is not None or self.locked:
            return
        g['mode'] = 'hold'
        if self.engine.paused:
            return                      # nothing to speed up: the picture and sound stay where they are
        self.hold_active = True
        hs = float(self.store.setting('hold_speed') or 2.0)
        self.speed_tag.hide()
        self.hold_pill.show(core.fmt_speed(hs),
                            ((self.x + self.width / 2.0), (self.y + self.height) - dp(86)), icon='ff',
                            h=dp(40))
        if self.store.setting('vibrate'):
            bridge.vibrate(15)
        if abs(hs - self.speed) > 1e-6:
            self.engine.set_speed(hs)

    def on_touch_move(self, touch):
        g = self.g
        if touch.grab_current is self and g and g['uid'] == touch.uid:
            dx, dy = touch.x - g['sx'], touch.y - g['sy']
            if g['mode'] is None and not self.locked and self.store.setting('gestures'):
                if max(abs(dx), abs(dy)) > dp(16):
                    g['moved'] = True
                    ev = g.get('ev')
                    if ev:
                        ev.cancel()
                    if abs(dx) > abs(dy):
                        g['mode'] = 'seek'
                        g['base'] = self.engine.position
                    elif g['sx'] < (self.x + self.width / 2.0):
                        g['mode'] = 'bright'
                        g['base'] = bridge.get_brightness()
                    else:
                        g['mode'] = 'vol'
                        g['base'] = bridge.get_volume()
            elif g['mode'] is None and max(abs(dx), abs(dy)) > dp(16):
                g['moved'] = True
                ev = g.get('ev')
                if ev:
                    ev.cancel()
            mode = g['mode']
            if mode == 'seek':
                dur = self.engine.duration or 1e9
                delta = dx / dp(1) * 0.35
                target = max(0.0, min(dur - 0.5, g['base'] + delta))
                g['target'] = target
                self.seek_card.show(target, g['base'], dur, self._center())
            elif mode == 'bright':
                v = max(0.02, min(1.0, g['base'] + dy / (self.height * 0.7)))
                bridge.set_brightness(v)
                self._brightness = v
                self.level.show('brightness', v, (self.x + dp(64), self.y + self.height / 2.0))
            elif mode == 'vol':
                v = max(0.0, min(1.0, g['base'] + dy / (self.height * 0.7)))
                bridge.set_volume(v)
                self.level.show('volume', v, ((self.x + self.width) - dp(64), self.y + self.height / 2.0))
            return True
        return Page.on_touch_move(self, touch)

    def on_touch_up(self, touch):
        g = self.g
        if g and g['uid'] == touch.uid and touch.grab_current is not self:
            self._last_up = time.time()
        if touch.grab_current is self and g and g['uid'] == touch.uid:
            self._last_up = time.time()
            touch.ungrab(self)
            self.g = None
            ev = g.get('ev')
            if ev:
                ev.cancel()
            mode = g['mode']
            if mode == 'hold':
                self.hold_active = False
                self.hold_pill.hide()
                if abs(float(self.store.setting('hold_speed') or 2.0) - self.speed) > 1e-6:
                    self.engine.set_speed(self.speed)
            elif mode == 'seek':
                if 'target' in g:
                    self.engine.seek(g['target'])
                    self._clear_ended()
                self.seek_card.hide()
            elif mode in ('bright', 'vol'):
                self.level.release()
            elif not g['moved']:
                self._tap(touch)
            return True
        return Page.on_touch_up(self, touch)

    def _tap(self, touch):
        if self.locked:
            self._flash_unlock()
            return
        now = time.time()
        lt = self._last_tap
        if lt and now - lt[0] < 0.3 and abs(touch.x - lt[1]) < dp(90):
            if self._single_ev:
                self._single_ev.cancel()
                self._single_ev = None
            self._last_tap = None
            self._double(touch.x)
            return
        self._last_tap = (now, touch.x)
        self._single_ev = Clock.schedule_once(self._single_tap, 0.3)

    def _single_tap(self, dt):
        self._single_ev = None
        self._last_tap = None
        if self.end_panel.parent is self:           # the choice on screen must not be covered by the bars
            return
        self.show_controls(not self.ctl_visible)

    def _double(self, x):
        third = self.width / 3.0
        if x < self.x + third:
            self.skip(-self._step(), side='back')
        elif x > self.x + 2 * third:
            self.skip(self._step(), side='fwd')
        else:
            self.toggle_play()
            self.center_fb.flash('pause' if self.engine.paused else 'play',
                                 (self.x + self.width / 2.0, self.y + self.height / 2.0))

    # ------------------------------------------------------------------ subtitles
    def _load_subs(self, path):
        self.sub_files = core.find_subtitle_files(path)
        self.sub_track = None
        self.sub_text = ''
        self.sub_lbl.ltext = ''
        self.sub_delay = 0.0
        if self.sub_files and self.store.setting('sub_on'):
            self._select_sub(self.sub_files[0], say=False)
        self.btn_cc.icon.color = list(ACCENT if self.sub_track else (1, 1, 1, 1))

    def _select_sub(self, path, say=True):
        try:
            self.sub_track = core.load_subtitle(path)
        except Exception:
            self.sub_track = None
            self.app.root.say('تعذر قراءة ملف الترجمة')
            return
        if say:
            self.app.root.say('الترجمة: ' + self.sub_track.name)
        self.btn_cc.icon.color = list(ACCENT)

    def subtitle_menu(self):
        def build():
            rows = [SheetTitle('الترجمة')]
            rows.append(SheetRow('بدون ترجمة', icon='close', checked=self.sub_track is None,
                                 callback=lambda w: pick(None)))
            for p in self.sub_files:
                cur = self.sub_track is not None and self.sub_track.name == os.path.basename(p)
                rows.append(SheetRow(os.path.basename(p), icon='subtitle', checked=cur,
                                     callback=lambda w, p=p: pick(p)))
            if not self.sub_files:
                rows.append(SheetLabel('لا توجد ملفات ترجمة (.srt / .vtt) بجوار الفيديو بنفس الاسم', muted=True))
            else:
                rows.append(SheetLabel('تأخير الترجمة: %+.1f ث' % self.sub_delay))
                rows.append(SheetRow('تأخير +0.5 ث', icon='plus', callback=lambda w: delay(0.5)))
                rows.append(SheetRow('تقديم −0.5 ث', icon='close', callback=lambda w: delay(-0.5)))
            return rows
        sheet = MenuSheet(self.app.root, build)

        def pick(p):
            sheet.dismiss()
            if p is None:
                self.sub_track = None
                self.sub_lbl.ltext = ''
                self.btn_cc.icon.color = [1, 1, 1, 1]
            else:
                self._select_sub(p)

        def delay(d):
            self.sub_delay += d
            sheet.rebuild()
        self._sheet(sheet)

    # ------------------------------------------------------------------ menus
    def _sheet(self, sheet):
        sheet.show()
        if self._hide_ev:
            self._hide_ev.cancel()

    def main_menu(self):
        def build():
            rows = [SheetTitle('خيارات التشغيل'), SheetLabel('السرعة'),
                    ChipsRow([(s, core.fmt_speed(s)) for s in core.SPEEDS], self.speed, pick_speed)]
            rows.append(SheetRow('الترجمة', icon='subtitle',
                                 value=(self.sub_track.name[:14] if self.sub_track else 'لا يوجد'),
                                 callback=lambda w: (sheet.dismiss(), self.subtitle_menu())))
            rows.append(SheetRow('التكرار', icon='repeat', value=REPEAT_LABELS[self.repeat],
                                 callback=lambda w: cycle_repeat()))
            rows.append(SheetRow('المسار الصوتي', icon='audio', value='تبديل',
                                 callback=lambda w: audio()))
            rows.append(SheetRow('مؤقت النوم', icon='clock', value=sleep_label(),
                                 callback=lambda w: cycle_sleep()))
            rows.append(SheetRow('سرعة الضغط المطول', icon='speed',
                                 value=core.fmt_speed(self.store.setting('hold_speed')),
                                 callback=lambda w: cycle_hold()))
            rows.append(SheetRow('مشاركة الفيديو', icon='share',
                                 callback=lambda w: (sheet.dismiss(), self.share())))
            rows.append(SheetRow('معلومات الفيديو', icon='info',
                                 callback=lambda w: (sheet.dismiss(), self.info())))
            rows.append(SheetRow('عداد الأداء (للفحص)', icon='tune', value='شغال' if self.perf_on else 'متوقف',
                                 callback=lambda w: (self._set_perf(not self.perf_on), sheet.rebuild())))
            return rows
        def pick_speed(v):
            self.set_speed(v)
            sheet.rebuild()

        def cycle_repeat():
            i = (REPEAT_MODES.index(self.repeat) + 1) % len(REPEAT_MODES)
            self.repeat = REPEAT_MODES[i]
            self.store.set_setting('repeat', self.repeat)
            self._apply_repeat_order()
            sheet.rebuild()

        def audio():
            ok = self.engine.cycle_audio()
            self.app.root.say('تم تبديل المسار الصوتي' if ok else 'لا يوجد مسار صوتي آخر')

        def sleep_label():
            if not self.sleep_at:
                return 'متوقف'
            return '%d د' % max(1, int((self.sleep_at - time.time()) / 60 + 0.5))

        def cycle_sleep():
            cur = 0
            if self.sleep_at:
                cur = max(1, int((self.sleep_at - time.time()) / 60 + 0.5))
            nxt = SLEEP_OPTIONS[0]
            for i, m in enumerate(SLEEP_OPTIONS):
                if m > cur:
                    nxt = m
                    break
            else:
                nxt = 0
            self.sleep_at = (time.time() + nxt * 60) if nxt else 0
            sheet.rebuild()

        def cycle_hold():
            opts = [1.5, 2.0, 2.5, 3.0]
            cur = float(self.store.setting('hold_speed') or 2.0)
            i = (opts.index(cur) + 1) % len(opts) if cur in opts else 1
            self.store.set_setting('hold_speed', opts[i])
            sheet.rebuild()
        sheet = MenuSheet(self.app.root, build)
        self._sheet(sheet)

    def share(self):
        v = self.lib.videos.get(self.key)
        if not v or not bridge.share_videos([v]):
            self.app.root.say('تعذرت المشاركة: ' + (bridge.LAST_SHARE_ERROR[0] or ''))

    def info(self):
        v = self.lib.videos.get(self.key, {})
        w, h = self.engine.size
        lines = [self.lib.title(self.key) if self.key else '',
                 'المسار: %s' % v.get('path', ''),
                 'الحجم: %s' % core.fmt_size(v.get('size', 0)),
                 'المدة: %s' % core.fmt_time(self.engine.duration),
                 'الدقة: %dx%d' % (w, h)]
        Dialog(self.app.root, 'معلومات الفيديو', '\n'.join(lines)).show()
        self.show_controls(True)


_ = (SUB, Icon, Tap)
