# -*- coding: utf-8 -*-
"""
engine.py - video playback engine built directly on ffpyplayer (FFmpeg).

Why not kivy's Video widget?  We need: playback speed that changes at any
moment (hold to 2x), exact position tracking, frame access for our own aspect
modes, and audio-track switching.

Speed is implemented with FFmpeg filters (atempo for audio - pitch preserved -
and setpts for video).  Filters are fixed when a stream is opened, so a speed
change re-opens the stream at the current position (done in the background of
the same call, normally < 0.3 s).  Positions are always kept in *media* time.
"""
import time
import traceback

from kivy.clock import Clock
from kivy.graphics.texture import Texture

import bridge
import core

try:
    from ffpyplayer.player import MediaPlayer
    HAVE_FFPY = True
except Exception:                       # pragma: no cover - depends on build
    MediaPlayer = None
    HAVE_FFPY = False


class VideoEngine(object):
    """Owns one ffpyplayer MediaPlayer at a time. All methods are main-thread."""

    def __init__(self, on_frame=None, on_eof=None, on_error=None):
        self.on_frame = on_frame        # callback(texture)
        self.on_eof = on_eof
        self.on_error = on_error
        self.player = None
        self.path = None
        self.texture = None
        self.size = (0, 0)
        self.duration = 0.0
        self.speed = 1.0
        self.paused = False
        self.eof = False
        self.ready = False              # first frame shown
        self._anchor_media = 0.0        # media time at the anchor
        self._anchor_pts = None         # player clock at the anchor
        self._last_pts = None
        self._next_poll = 0.0
        self._ev = None
        self._open_time = 0.0
        self._pending_seek = None
        self._volume = 1.0
        self._meta_done = False
        self._closing = False

    # ---- lifecycle -----------------------------------------------------------
    def open(self, path, start=0.0, speed=1.0, paused=False, duration_hint=0.0):
        self.close(keep_texture=True)
        if not HAVE_FFPY:
            if self.on_error:
                self.on_error('ffpyplayer غير متوفرة')
            return False
        self.path = path
        self.speed = float(speed)
        self.paused = bool(paused)
        self.eof = False
        self.ready = False
        self._meta_done = False
        if duration_hint:
            self.duration = float(duration_hint)
        self._start_player(max(0.0, float(start)))
        if self._ev is None:
            self._ev = Clock.schedule_interval(self._tick, 1.0 / 60.0)
        return self.player is not None

    def _start_player(self, start):
        if self.player is not None:
            self._close_player()
        opts = {'paused': self.paused, 'out_fmt': 'rgba', 'volume': self._volume}
        af = core.atempo_chain(self.speed)
        vf = core.setpts_filter(self.speed)
        if af:
            opts['af'] = af
        if vf:
            opts['vf'] = vf
        if start > 0.5:
            opts['ss'] = float(start)
        bridge.crumb('engine: open %s ss=%s speed=%s' % (self.path, start, self.speed))
        try:
            self.player = MediaPlayer(self.path, thread_lib='SDL', loglevel='error', ff_opts=opts)
        except Exception as e:
            traceback.print_exc()
            self.player = None
            if self.on_error:
                self.on_error(str(e))
            return
        bridge.crumb('engine: opened')
        self._anchor_media = float(start)
        self._anchor_pts = None
        self._last_pts = None
        self._open_time = time.time()
        self._next_poll = 0.0
        self.eof = False

    def _close_player(self):
        p, self.player = self.player, None
        if p is not None:
            try:
                p.close_player()
            except Exception:
                pass

    def close(self, keep_texture=False):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        self._close_player()
        self.ready = False
        self.path = None
        if not keep_texture:
            self.texture = None
            self.size = (0, 0)

    # ---- clock ------------------------------------------------------------------
    @property
    def position(self):
        """Current media position in seconds."""
        if self._anchor_pts is None or self._last_pts is None:
            return self._anchor_media if self._pending_seek is None else self._pending_seek
        pos = self._anchor_media + (self._last_pts - self._anchor_pts) * self.speed
        if self.duration:
            pos = min(pos, self.duration)
        return max(0.0, pos)

    # ---- controls -----------------------------------------------------------------
    def set_pause(self, paused):
        self.paused = bool(paused)
        if self.player is not None:
            try:
                self.player.set_pause(self.paused)
            except Exception:
                traceback.print_exc()

    def toggle_pause(self):
        self.set_pause(not self.paused)

    def seek(self, t, accurate=False):
        """Seek to an absolute media time."""
        if not self.path:
            return
        t = max(0.0, float(t))
        if self.duration:
            t = min(t, max(0.0, self.duration - 0.05))
        self.eof = False
        if self.player is None:
            self._start_player(t)
            return
        try:
            self.player.seek(t, relative=False, accurate=accurate)
        except Exception:
            traceback.print_exc()
            self._start_player(t)
            return
        self._anchor_media = t
        self._anchor_pts = None          # re-anchored by the next frame
        self._last_pts = None
        self._next_poll = 0.0

    def seek_relative(self, delta):
        self.seek(self.position + delta)

    def set_speed(self, speed):
        speed = float(speed)
        if abs(speed - self.speed) < 1e-6:
            return
        if not self.path:
            self.speed = speed
            return
        pos = self.position
        self.speed = speed
        self._start_player(pos)

    def set_volume(self, v):
        self._volume = max(0.0, min(1.0, float(v)))
        if self.player is not None:
            try:
                self.player.set_volume(self._volume)
            except Exception:
                pass

    def cycle_audio(self):
        if self.player is None:
            return False
        try:
            self.player.request_channel('audio', action='cycle')
            return True
        except Exception:
            traceback.print_exc()
            return False

    # ---- per-frame work ------------------------------------------------------------
    def _read_meta(self):
        try:
            meta = self.player.get_metadata()
        except Exception:
            return
        if not meta:
            return
        d = meta.get('duration')
        if d and d > 0:
            self.duration = float(d)
            self._meta_done = True
        sz = meta.get('src_vid_size')
        if sz and sz[0] and sz[1]:
            self.size = (int(sz[0]), int(sz[1]))

    def _tick(self, dt):
        p = self.player
        if p is None:
            return
        now = time.time()
        if not self._meta_done and (now - self._open_time) < 15:
            self._read_meta()
        if now < self._next_poll:
            return
        try:
            frame, val = p.get_frame()
        except Exception:
            traceback.print_exc()
            return
        if val == 'eof':
            if not self.eof:
                self.eof = True
                if self.duration:
                    self._anchor_media = self.duration
                    self._anchor_pts = self._last_pts = 0.0
                if self.on_eof:
                    self.on_eof()
            self._next_poll = now + 0.1
            return
        if val == 'paused':
            self._next_poll = now + 0.05
        elif isinstance(val, (int, float)):
            self._next_poll = now + min(max(val, 0.0), 0.05)
        if frame is None:
            return
        img, pts = frame
        if not self.ready:
            bridge.crumb('engine: first frame')
        try:
            w, h = img.get_size()
        except Exception:
            return
        if self.texture is None or self.texture.size != (w, h):
            self.texture = Texture.create(size=(w, h), colorfmt='rgba')
            self.texture.flip_vertical()
            self.size = (w, h)
        try:
            if not self.ready:
                bridge.crumb('engine: blit %dx%d' % (w, h))
            self.texture.blit_buffer(img.to_memoryview()[0], colorfmt='rgba')
        except Exception:
            traceback.print_exc()
            return
        if self._anchor_pts is None:
            self._anchor_pts = pts
        self._last_pts = pts
        if not self.ready:
            self.ready = True
            self._read_meta()
        if self.on_frame:
            self.on_frame(self.texture)
