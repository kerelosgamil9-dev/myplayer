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
import os
import random
import time

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget

import bridge
import core
from engine import VideoEngine
from screens import Page
from widgets import (ACCENT, SUB, ChipsRow, Dialog, Icon, IconButton, MenuSheet, SeekBar,
                     SheetLabel, SheetRow, SheetTitle, Tap, Txt)

ASPECTS = ['fit', 'fill', 'stretch', '16:9', '4:3']
ASPECT_LABELS = {'fit': 'ملائم للشاشة', 'fill': 'ملء الشاشة (قص)', 'stretch': 'تمديد',
                 '16:9': '16:9', '4:3': '4:3'}
REPEAT_MODES = ['off', 'one', 'all', 'shuffle']
REPEAT_LABELS = {'off': 'بدون تكرار', 'one': 'تكرار الفيديو الحالي', 'all': 'تكرار القائمة',
                 'shuffle': 'عشوائي'}
SLEEP_OPTIONS = [0, 15, 30, 45, 60, 90]


class Pill(Widget):
    """Small rounded dark label that appears for a moment."""

    def __init__(self, **kw):
        kw.setdefault('size_hint', (None, None))
        super(Pill, self).__init__(**kw)
        self.lbl = Txt(halign='center', font_size=sp(17), bold=True, size_hint=(None, None))
        self.add_widget(self.lbl)
        self.opacity = 0
        self._ev = None
        self.bind(pos=self._lay, size=self._lay)

    def show(self, text, center, w=dp(150), h=dp(44), duration=0.0):
        self.size = (w, h)
        self.center = center
        self.lbl.ltext = text
        self.opacity = 1
        if self._ev:
            self._ev.cancel()
            self._ev = None
        if duration:
            self._ev = Clock.schedule_once(lambda dt: self.hide(), duration)
        self._lay()

    def hide(self):
        self.opacity = 0

    def _lay(self, *a):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(0, 0, 0, 0.72)
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.height / 2.0])
        self.lbl.pos = self.pos
        self.lbl.size = self.size

    def on_touch_down(self, touch):
        return False


class PlayerPage(Page):
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
        self.aspect = self.store.setting('aspect')
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
        self.engine = VideoEngine(on_frame=self._on_frame, on_eof=self._on_eof, on_error=self._on_error)

        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._vrect = Rectangle(pos=self.pos, size=(0, 0))

        self.ctl = FloatLayout(size_hint=(1, 1))
        self.add_widget(self.ctl)
        self.btn_back = IconButton('back', callback=lambda w: self.app.root.back())
        self.title = Txt(font_size=sp(16), align_mode='auto', size_hint=(None, None), bold=True)
        self.btn_cc = IconButton('subtitle', callback=lambda w: self.subtitle_menu())
        self.btn_rot = IconButton('rotate', callback=lambda w: self.rotate())
        self.btn_more = IconButton('dots', callback=lambda w: self.main_menu())
        self.cur = Txt(font_size=sp(13), halign='left', size_hint=(None, None))
        self.dur = Txt(font_size=sp(13), halign='right', size_hint=(None, None))
        self.seek = SeekBar(on_start=self._seek_start, on_move=self._seek_move, on_end=self._seek_end)
        self.btn_lock = IconButton('unlock', callback=lambda w: self.set_lock(True))
        self.btn_prev = IconButton('prev', callback=lambda w: self.prev())
        self.btn_rew = IconButton('rew', callback=lambda w: self.skip(-self._step()))
        self.btn_play = IconButton('pause', callback=lambda w: self.toggle_play(), icon_size=dp(34),
                                   size=(dp(60), dp(60)))
        self.btn_fwd = IconButton('fwd', callback=lambda w: self.skip(self._step()))
        self.btn_next = IconButton('next', callback=lambda w: self.next())
        self.btn_aspect = IconButton('aspect', callback=lambda w: self.cycle_aspect())
        self.btn_unlock = IconButton('lock', color=ACCENT, callback=lambda w: self.set_lock(False),
                                     size=(dp(56), dp(56)))
        for w in (self.btn_back, self.title, self.btn_cc, self.btn_rot, self.btn_more, self.cur, self.dur,
                  self.seek, self.btn_lock, self.btn_prev, self.btn_rew, self.btn_play, self.btn_fwd,
                  self.btn_next, self.btn_aspect):
            self.ctl.add_widget(w)
        self.sub_lbl = Txt(font_size=sp(self.store.setting('sub_size')), halign='center', valign='bottom',
                           nlines=2, keep_nl=True, size_hint=(None, None), outline_width=dp(2),
                           outline_color=(0, 0, 0, 1), bold=True)
        self.add_widget(self.sub_lbl)
        self.fb = Pill()
        self.hud = Pill()
        self.speed_tag = Pill()
        self.hold_pill = Pill()
        for w in (self.fb, self.hud, self.speed_tag, self.hold_pill, self.btn_unlock):
            self.add_widget(w)
        self.btn_unlock.opacity = 0
        self.bind(pos=self._lay, size=self._lay)
        self._lay()
        self._ui_ev = Clock.schedule_interval(self._ui_tick, 0.1)

    # ------------------------------------------------------------------ lifecycle
    def on_show(self):
        if self._closed:
            return
        bridge.set_immersive(True)
        if self.store.setting('keep_awake'):
            bridge.keep_awake(True)
        if self.key is None:
            self._start_current()
        self.show_controls(True)

    def on_close(self):
        if self._closed:
            return
        self._closed = True
        self.save_progress(force=True)
        try:
            self._ui_ev.cancel()
        except Exception:
            pass
        self.engine.close()
        bridge.set_immersive(False)
        bridge.keep_awake(False)
        if self._brightness is not None:
            bridge.set_brightness(None)
        bridge.set_orientation(bridge.SCREEN_PORTRAIT)
        self.store.save()

    def on_app_pause(self):
        if not self._closed:
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
        self._ended = False
        self._oriented = False
        self.title.ltext = self.lib.title(key)
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
        self._start_current(start=0.0)
        return True

    def prev(self):
        if self.engine.position > 3 or self.cursor == 0:
            self.engine.seek(0)
            return
        self.cursor -= 1
        self._start_current(start=0.0)

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
        if self._vrect.texture is not tex:
            self._vrect.texture = tex
        self._place_video()
        if not self._oriented and self.engine.size[0]:
            self._oriented = True
            if self.store.setting('auto_rotate'):
                w, h = self.engine.size
                mode = bridge.SCREEN_LANDSCAPE if w >= h else bridge.SCREEN_PORTRAIT

                def rot(dt, mode=mode):
                    if not self._closed:
                        bridge.crumb('player: orientation %s' % mode)
                        bridge.set_orientation(mode)
                Clock.schedule_once(rot, 0.4)

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
        if self.store.setting('autoplay_next') and self.next(auto=True):
            return
        self.engine.set_pause(True)
        self._sync_play_icon()
        self.show_controls(True)

    def _on_error(self, msg):
        self.app.root.say('تعذر تشغيل الفيديو')

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

    def skip(self, delta, show=True):
        pos = self.engine.position
        dur = self.engine.duration or 1e9
        target = max(0.0, min(dur - 0.5, pos + delta))
        self.engine.seek(target)
        self._ended = False
        if show:
            self.fb.show('%s%d ث' % ('+' if delta > 0 else '−', abs(int(delta))), self._center(), duration=0.7)
        self.show_controls(True)

    def set_speed(self, s, say=True):
        self.speed = float(s)
        self.store.set_setting('speed', self.speed)
        self.engine.set_speed(self.speed)
        self._sync_speed_tag()
        if say:
            self.app.root.say('السرعة ' + core.fmt_speed(self.speed))

    def _sync_speed_tag(self):
        if abs(self.speed - 1.0) > 1e-6 and not self.hold_active:
            self.speed_tag.show(core.fmt_speed(self.speed),
                                (self.center_x, self.top - dp(86)), w=dp(70), h=dp(30))
            self.speed_tag.lbl.font_size = sp(14)
        else:
            self.speed_tag.hide()

    def rotate(self):
        land = self.width > self.height
        bridge.set_orientation(bridge.SCREEN_PORTRAIT if land else bridge.SCREEN_LANDSCAPE)

    def cycle_aspect(self):
        i = (ASPECTS.index(self.aspect) + 1) % len(ASPECTS) if self.aspect in ASPECTS else 0
        self.aspect = ASPECTS[i]
        self.store.set_setting('aspect', self.aspect)
        self._place_video()
        self.fb.show(ASPECT_LABELS[self.aspect], self._center(), w=dp(190), duration=0.9)

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
        self.ctl.opacity = 1 if show else 0
        self._lay()
        if show and not self.engine.paused and not self.seeking:
            self._hide_ev = Clock.schedule_once(lambda dt: self.show_controls(False), 3.8)

    # ------------------------------------------------------------------ seekbar
    def _seek_start(self, v):
        self.seeking = True
        if self._hide_ev:
            self._hide_ev.cancel()

    def _seek_move(self, v):
        d = self.engine.duration
        if d:
            self.cur.ltext = core.fmt_time(v * d)

    def _seek_end(self, v):
        self.seeking = False
        d = self.engine.duration
        if d:
            self.engine.seek(v * d, accurate=True)
            self._ended = False
        self.show_controls(True)

    # ------------------------------------------------------------------ periodic work
    def _ui_tick(self, dt):
        if self._closed:
            return
        e = self.engine
        pos = e.position
        if not self.seeking:
            if e.duration:
                self.seek.value = max(0.0, min(1.0, pos / e.duration))
            self.cur.ltext = core.fmt_time(pos)
        self.dur.ltext = core.fmt_time(e.duration) if e.duration else '--:--'
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
        return (self.center_x, self.center_y + dp(50))

    def _place_video(self):
        w, h = self.engine.size
        W, H = self.size
        if not w or not h or W <= 1:
            self._vrect.size = (0, 0)
            return
        a = self.aspect
        if a == 'stretch':
            rw, rh = W, H
        else:
            ar = w / float(h)
            if a == '16:9':
                ar = 16 / 9.0
            elif a == '4:3':
                ar = 4 / 3.0
            if a == 'fill':
                s = max(W / ar, H)
            else:
                s = min(W / ar, H)
            rw, rh = s * ar, s
        self._vrect.size = (rw, rh)
        self._vrect.pos = (self.x + (W - rw) / 2.0, self.y + (H - rh) / 2.0)

    def _lay(self, *a):
        if not hasattr(self, 'btn_unlock'):
            return
        W, H = self.size
        x0, y0 = self.pos
        land = W > H
        pad = dp(28) if land else dp(6)
        top_h = dp(60)
        bot_h = dp(128)
        # translucent bars
        self.ctl.canvas.before.clear()
        with self.ctl.canvas.before:
            Color(0, 0, 0, 0.5)
            Rectangle(pos=(x0, y0 + H - top_h), size=(W, top_h))
            Color(0, 0, 0, 0.55)
            Rectangle(pos=(x0, y0), size=(W, bot_h))
        top = y0 + H - top_h
        self.btn_back.pos = (x0 + W - pad - dp(48), top + dp(6))
        left = x0 + pad
        for b in (self.btn_more, self.btn_rot, self.btn_cc):
            b.pos = (left, top + dp(6))
            left += dp(48)
        self.title.pos = (left + dp(4), top)
        self.title.size = (max(10, self.btn_back.x - left - dp(12)), top_h)
        # seek row
        sy = y0 + dp(68)
        self.cur.pos = (x0 + pad + dp(6), sy)
        self.cur.size = (dp(54), dp(36))
        self.dur.pos = (x0 + W - pad - dp(60), sy)
        self.dur.size = (dp(54), dp(36))
        self.seek.pos = (x0 + pad + dp(60), sy)
        self.seek.size = (max(10, W - 2 * pad - dp(120)), dp(36))
        # transport row
        ry = y0 + dp(10)
        cx = x0 + W / 2.0
        self.btn_play.pos = (cx - dp(30), ry)
        self.btn_rew.pos = (cx - dp(30) - dp(52), ry + dp(6))
        self.btn_prev.pos = (cx - dp(30) - dp(104), ry + dp(6))
        self.btn_fwd.pos = (cx + dp(30) + dp(4), ry + dp(6))
        self.btn_next.pos = (cx + dp(30) + dp(56), ry + dp(6))
        self.btn_lock.pos = (x0 + pad, ry + dp(6))
        self.btn_aspect.pos = (x0 + W - pad - dp(48), ry + dp(6))
        self.btn_unlock.center = (x0 + pad + dp(34), y0 + H / 2.0)
        # subtitles
        base = dp(138) if self.ctl_visible else dp(28)
        self.sub_lbl.size = (W * 0.9, dp(110))
        self.sub_lbl.pos = (x0 + W * 0.05, y0 + base)
        self._place_video()

    # ------------------------------------------------------------------ gestures
    def on_touch_down(self, touch):
        if not self.collide_point(*touch.pos):
            return False
        if self.locked:
            if self.btn_unlock.opacity and self.btn_unlock.on_touch_down(touch):
                return True
        elif self.ctl_visible:
            if self.ctl.on_touch_down(touch):
                return True
        touch.grab(self)
        self.g = {'uid': touch.uid, 'sx': touch.x, 'sy': touch.y, 'mode': None, 'time': time.time(),
                  'moved': False}
        if not self.locked:
            self.g['ev'] = Clock.schedule_once(self._hold_start, 0.4)
        return True

    def _hold_start(self, dt):
        g = self.g
        if not g or g['mode'] is not None or self.locked:
            return
        g['mode'] = 'hold'
        self.hold_active = True
        hs = float(self.store.setting('hold_speed') or 2.0)
        self.speed_tag.hide()
        self.hold_pill.show(core.fmt_speed(hs),
                            (self.center_x, self.top - dp(86)), w=dp(90), h=dp(36))
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
                    elif g['sx'] < self.center_x:
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
                self.fb.show('%s%d ث\n%s' % ('+' if target >= g['base'] else '−',
                                             abs(int(target - g['base'])), core.fmt_time(target)),
                             self._center(), w=dp(130), h=dp(64))
            elif mode == 'bright':
                v = max(0.02, min(1.0, g['base'] + dy / (self.height * 0.7)))
                bridge.set_brightness(v)
                self._brightness = v
                self.hud.show('%d%%  سطوع' % int(v * 100),
                              (self.x + dp(90), self.center_y), w=dp(130), h=dp(40))
            elif mode == 'vol':
                v = max(0.0, min(1.0, g['base'] + dy / (self.height * 0.7)))
                bridge.set_volume(v)
                self.hud.show('%d%%  صوت' % int(v * 100), (self.right - dp(90), self.center_y),
                              w=dp(130), h=dp(40))
            return True
        return Page.on_touch_move(self, touch)

    def on_touch_up(self, touch):
        g = self.g
        if touch.grab_current is self and g and g['uid'] == touch.uid:
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
                self._sync_speed_tag()
            elif mode == 'seek':
                if 'target' in g:
                    self.engine.seek(g['target'])
                    self._ended = False
                self.fb.hide()
            elif mode in ('bright', 'vol'):
                Clock.schedule_once(lambda dt: self.hud.hide(), 0.6)
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
        self.show_controls(not self.ctl_visible)

    def _double(self, x):
        third = self.width / 3.0
        if x < self.x + third:
            self.skip(-self._step())
        elif x > self.x + 2 * third:
            self.skip(self._step())
        else:
            self.toggle_play()

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
                rows.append(SheetLabel('لا توجد ملفات ترجمة (.srt / .vtt) بجوار الفيديو بنفس الاسم'))
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
            rows.append(SheetRow('نسبة العرض', icon='aspect', value=ASPECT_LABELS[self.aspect],
                                 callback=lambda w: (self.cycle_aspect(), sheet.rebuild())))
            rows.append(SheetRow('التكرار', icon='repeat', value=REPEAT_LABELS[self.repeat],
                                 callback=lambda w: cycle_repeat()))
            rows.append(SheetRow('المسار الصوتي', icon='audio', value='تبديل',
                                 callback=lambda w: audio()))
            rows.append(SheetRow('مؤقت النوم', icon='clock', value=sleep_label(),
                                 callback=lambda w: cycle_sleep()))
            rows.append(SheetRow('سرعة الضغط المطول', icon='speed',
                                 value=core.fmt_speed(self.store.setting('hold_speed')),
                                 callback=lambda w: cycle_hold()))
            rows.append(SheetRow('معلومات الفيديو', icon='info',
                                 callback=lambda w: (sheet.dismiss(), self.info())))
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
