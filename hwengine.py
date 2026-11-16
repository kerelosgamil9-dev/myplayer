# -*- coding: utf-8 -*-
"""
hwengine.py - hardware-accelerated playback through Android's own MediaPlayer.

Video and audio are decoded by the phone's hardware codecs (smooth 1080p/4K,
real 2x speed with pitch kept, perfect A/V sync, little battery use).  The
decoder renders into a SurfaceTexture; a small Fbo converts that external
(OES) texture into a normal Kivy texture that the player page draws.

Smoothness rules (this file is on the hot path, 30-60 times a second):
  * every decoded frame is taken from the SurfaceTexture, even when the app
    was busy for a moment (queued frames are drained, the newest one is drawn),
    so the decoder never stalls waiting for us;
  * the GL work is done once per new frame only, nothing else is touched;
  * the player clock is read from the MediaPlayer a few times a second and
    extrapolated in between (each read is an inter-process call).

Everything here is Android-only and wrapped defensively: if anything fails, the
wrapper in engine.py silently falls back to the ffpyplayer engine for that video.
"""
import time
import traceback

from kivy.clock import Clock

import bridge

GL_TEXTURE_EXTERNAL_OES = 0x8D65
MAX_SIDE = 1920            # pictures are converted at most this big (4K is scaled down)
MAX_DRAIN = 6              # frames taken from the decoder in one go when we are behind

# SurfaceTexture default transform of a video frame (flips vertically)
_DEFAULT_MATRIX = [1, 0, 0, 0, 0, -1, 0, 0, 0, 0, 1, 0, 0, 1, 0, 1]

_FS = '''
#extension GL_OES_EGL_image_external : require
#ifdef GL_ES
precision highp float;
#endif
varying vec4 frag_color;
varying vec2 tex_coord0;
uniform samplerExternalOES texture1;
uniform mat4 texmat;
void main() {
    vec2 uv = (texmat * vec4(tex_coord0, 0.0, 1.0)).xy;
    gl_FragColor = texture2D(texture1, uv);
}
'''


def _listener_class():
    from jnius import PythonJavaClass, java_method

    class FrameListener(PythonJavaClass):
        __javainterfaces__ = ['android/graphics/SurfaceTexture$OnFrameAvailableListener']
        __javacontext__ = 'app'

        def __init__(self):
            super(FrameListener, self).__init__()
            self.count = 0

        @java_method('(Landroid/graphics/SurfaceTexture;)V')
        def onFrameAvailable(self, st):
            self.count += 1

    return FrameListener


class HWEngine(object):
    """Same public interface as engine.VideoEngine."""

    last_error = ''
    black_fail = False

    def __init__(self, on_frame=None, on_eof=None, on_error=None, on_fail=None):
        self.on_frame = on_frame
        self.on_eof = on_eof
        self.on_error = on_error
        self.on_fail = on_fail          # callback(path, position, message) when hardware playback breaks
        self.mp = None
        self.st = None
        self.surface = None
        self.listener = None
        self.texture = None
        self.fbo = None
        self.oes = None
        self.path = None
        self.size = (0, 0)
        self.duration = 0.0
        self.speed = 1.0
        self.paused = False
        self.eof = False
        self.ready = False
        self.stats = {}                 # published once a second (shown by the performance overlay)
        self._volume = 1.0
        self._ev = None
        self._last_count = 0
        self._last_ts = 0
        self._cb_time = 0.0
        self._open_time = 0.0
        self._seek_time = 0.0
        self._seek_target = 0.0
        self._next_slow = 0.0
        self._failed = False
        self._matrix = None
        self._pos = 0.0
        self._pos_time = 0.0
        self._last_ret = 0.0
        self._gl_retry = 0.0
        self._reset_stats(0.0)

    # ---- lifecycle ------------------------------------------------------------
    def open(self, path, start=0.0, speed=1.0, paused=False, duration_hint=0.0):
        self.close(keep_texture=True)
        self.path = path
        self.speed = float(speed)
        self.paused = bool(paused)
        self.eof = False
        self.ready = False
        self._failed = False
        self._pos = float(start)
        self._pos_time = 0.0
        self._last_ret = float(start)
        self._seek_target = float(start)
        self._seek_time = 0.0
        self._cb_time = time.time()
        self._reset_stats(time.time())
        if duration_hint:
            self.duration = float(duration_hint)
        try:
            from jnius import autoclass
            bridge.crumb('hw: open %s' % path)
            self._build_surface()
            MP = autoclass('android.media.MediaPlayer')
            mp = MP()
            mp.setDataSource(path)
            mp.setSurface(self.surface)
            mp.prepare()
            self.mp = mp
            bridge.crumb('hw: prepared')
            d = mp.getDuration()
            if d and d > 0:
                self.duration = d / 1000.0
            w, h = mp.getVideoWidth(), mp.getVideoHeight()
            if w and h:
                self.size = (int(w), int(h))
            else:
                raise RuntimeError('no video track')
            mp.setVolume(self._volume, self._volume)
            if start > 0.3 or self.paused:
                self._seek_ms(int(start * 1000))
            self._apply_speed()
            if not self.paused:
                mp.start()
            self._open_time = time.time()
            self._make_fbo()
            bridge.crumb('hw: started')
        except Exception as ex:
            traceback.print_exc()
            bridge.crumb('hw: failed %s' % ex)
            self._release()
            self.last_error = str(ex)
            return False
        if self._ev is None:
            # interval 0 = once per Kivy frame (exactly when the screen can show something new)
            self._ev = Clock.schedule_interval(self._tick, 0)
        return True

    def close(self, keep_texture=False):
        if self._ev is not None:
            self._ev.cancel()
            self._ev = None
        self._release()
        self.path = None
        self.ready = False
        if not keep_texture:
            self.texture = None

    def _release(self):
        for name in ('mp',):
            o = getattr(self, name)
            setattr(self, name, None)
            if o is not None:
                try:
                    o.release()
                except Exception:
                    pass
        for name in ('surface', 'st'):
            o = getattr(self, name)
            setattr(self, name, None)
            if o is not None:
                try:
                    o.release()
                except Exception:
                    pass
        self.listener = None
        self.fbo = None
        self.oes = None

    # ---- GL ------------------------------------------------------------------------
    def _build_surface(self):
        """OES texture + SurfaceTexture + Surface (what the decoder draws into)."""
        from jnius import autoclass
        from kivy.graphics.texture import Texture
        SurfaceTexture = autoclass('android.graphics.SurfaceTexture')
        Surface = autoclass('android.view.Surface')
        self.oes = Texture(width=16, height=16, target=GL_TEXTURE_EXTERNAL_OES, colorfmt='rgba')
        bridge.crumb('hw: oes texture %s' % self.oes.id)
        self.st = SurfaceTexture(int(self.oes.id))
        self.listener = _listener_class()()
        self.st.setOnFrameAvailableListener(self.listener)
        self.surface = Surface(self.st)
        self._last_count = 0
        self._last_ts = 0                       # 0 = no frame yet
        bridge.crumb('hw: surface ready')

    def _make_fbo(self):
        from kivy.graphics import BindTexture, ClearBuffers, ClearColor, Fbo, Rectangle
        w, h = self.size
        k = min(1.0, float(MAX_SIDE) / max(w, h))
        fw = max(2, int(w * k) // 2 * 2)
        fh = max(2, int(h * k) // 2 * 2)
        fbo = Fbo(size=(fw, fh))
        fbo.shader.fs = _FS
        ok = getattr(fbo.shader, 'success', True)
        bridge.crumb('hw: shader ok=%s fbo=%dx%d video=%dx%d' % (ok, fw, fh, w, h))
        if not ok:
            raise RuntimeError('video shader failed to compile')
        with fbo:
            ClearColor(0, 0, 0, 1)
            ClearBuffers()
            BindTexture(texture=self.oes, index=1)
            Rectangle(size=(fw, fh))
        self.fbo = fbo
        self.texture = fbo.texture
        try:
            self.texture.flip_vertical()        # GL output is bottom-up: show it upright
        except Exception as ex:
            bridge.crumb('hw: flip failed %s' % ex)
        self._matrix = None
        self._set_matrix(_DEFAULT_MATRIX)

    def _set_matrix(self, flat):
        from kivy.graphics.transformation import Matrix
        m = Matrix()
        m.set(flat=[float(x) for x in flat])
        self.fbo['texmat'] = m

    def _render(self, calls):
        """Take `calls` frames from the decoder (the last one is the newest) and convert it."""
        st = self.st
        for _ in range(calls):
            st.updateTexImage()
        if self._matrix is None:                # constant for a video: read it once
            flat = [0.0] * 16
            try:
                st.getTransformMatrix(flat)
            except Exception:
                flat = None
            if not flat or not any(abs(v) > 1e-6 for v in flat):
                flat = _DEFAULT_MATRIX
            self._matrix = list(flat)
            self._set_matrix(self._matrix)
        self.fbo.ask_update()
        self.fbo.draw()

    def _poll_new(self):
        """The frame callback has been silent for a while: ask the SurfaceTexture itself."""
        try:
            self.st.updateTexImage()
            ts = self.st.getTimestamp()
        except Exception:
            return False
        if ts != self._last_ts:
            self._last_ts = ts
            return True
        return False

    def _recover_gl(self, ex):
        """The GL side broke (for instance Android dropped the GL context while the app was in
        the background): build it again once; give up if it breaks again right away."""
        now = time.time()
        bridge.crumb('hw: frame failed %s' % ex)
        if now - self._gl_retry < 3.0 or self.mp is None:
            self._fail(str(ex))
            return False
        self._gl_retry = now
        try:
            old = (self.surface, self.st)
            self._build_surface()
            self.mp.setSurface(self.surface)
            self._make_fbo()
            for o in old:
                try:
                    if o is not None:
                        o.release()
                except Exception:
                    pass
            self._cb_time = time.time()
            bridge.crumb('hw: gl rebuilt')
            return True
        except Exception as ex2:
            traceback.print_exc()
            self._fail('%s / %s' % (ex, ex2))
            return False

    # ---- per-frame ------------------------------------------------------------
    def _reset_stats(self, now):
        self._stat = {'t0': now, 'frames': 0, 'skipped': 0, 'gap': 0.0, 'work': 0.0, 'last': 0.0}

    def _publish_stats(self, now):
        s = self._stat
        dt = max(0.001, now - s['t0'])
        self.stats = {'fps': s['frames'] / dt, 'skipped': s['skipped'], 'gap': s['gap'] * 1000.0,
                      'work': s['work'] * 1000.0}
        last = s['last']
        self._reset_stats(now)
        self._stat['last'] = last

    def _tick(self, dt):
        lst = self.listener
        if self.mp is None or lst is None:
            return
        now = time.time()
        cnt = lst.count
        n = cnt - self._last_count
        got = False
        calls = 0
        if n > 0:
            self._last_count = cnt
            self._cb_time = now
            calls = min(n, MAX_DRAIN)
            got = True
        elif not self.paused and now - self._cb_time > 0.4:
            got = self._poll_new()
            n = 1 if got else 0
        if got:
            t0 = time.time()
            try:
                self._render(calls)
            except Exception as ex:
                if not self._recover_gl(ex):
                    return
                got = False
            if got:
                if not self.ready:
                    self.ready = True
                    bridge.crumb('hw: first frame')
                    bridge.hw_ok(self.path)
                s = self._stat
                s['frames'] += 1
                s['skipped'] += max(0, n - 1)
                if s['last']:
                    s['gap'] = max(s['gap'], now - s['last'])
                s['last'] = now
                s['work'] = max(s['work'], time.time() - t0)
                if self.on_frame:
                    self.on_frame(self.texture)
        elif not self.ready and not self.paused and now - self._open_time > 4.0:
            self._fail('no video frames from the hardware decoder')
            return
        if now - self._stat['t0'] >= 1.0:
            self._publish_stats(now)
        if now >= self._next_slow:
            self._next_slow = now + 0.2
            self._check_end(now)

    def _check_end(self, now):
        if self.paused or self.eof or not self.duration or now - self._seek_time < 0.8:
            return
        if self.position < self.duration - 1.5:      # cheap test first (no inter-process call)
            return
        try:
            playing = self.mp.isPlaying()
            pos = self.mp.getCurrentPosition() / 1000.0
        except Exception:
            return
        if not playing and pos >= self.duration - 0.6:
            self.eof = True
            if self.on_eof:
                self.on_eof()

    def _fail(self, msg, black=False):
        if self._failed:
            return
        self._failed = True
        self.black_fail = black
        pos = self.position
        path = self.path
        self.last_error = msg
        self.close(keep_texture=True)
        if self.on_fail:
            self.on_fail(path, pos, msg)
        elif self.on_error:
            self.on_error(msg)

    # ---- clock -------------------------------------------------------------------
    @property
    def position(self):
        now = time.time()
        if now - self._seek_time < 0.7:
            return self._seek_target
        mp = self.mp
        if mp is None:
            return self._last_ret
        age = now - self._pos_time
        if self._pos_time == 0.0 or (not self.paused and age >= 0.3):
            try:
                p = mp.getCurrentPosition() / 1000.0
            except Exception:
                return self._last_ret
            self._pos, self._pos_time = p, now
        elif self.paused:
            p = self._pos
        else:
            p = self._pos + age * self.speed
        if self.duration:
            p = min(p, self.duration)
        p = max(0.0, p)
        if not self.paused and p < self._last_ret and self._last_ret - p < 0.5:
            p = self._last_ret                  # never run backwards because of rounding
        self._last_ret = p
        return p

    # ---- controls -------------------------------------------------------------------
    def _seek_ms(self, ms):
        try:
            self.mp.seekTo(int(ms), 3)          # SEEK_CLOSEST
        except Exception:
            try:
                self.mp.seekTo(int(ms))
            except Exception:
                pass

    def _apply_speed(self):
        if self.mp is None:
            return
        try:
            from jnius import autoclass
            PP = autoclass('android.media.PlaybackParams')
            pp = PP()
            pp.setSpeed(float(self.speed))
            pp.setPitch(1.0)
            self.mp.setPlaybackParams(pp)
            if self.paused and self.mp.isPlaying():
                self.mp.pause()
        except Exception as ex:
            bridge.crumb('hw: speed failed %s' % ex)

    def set_pause(self, paused):
        self.paused = bool(paused)
        self._pos_time = 0.0                    # take a fresh reading of the clock
        if self.mp is None:
            return
        try:
            if self.paused:
                self.mp.pause()
            else:
                if self.eof:
                    self.eof = False
                self.mp.start()
        except Exception:
            traceback.print_exc()

    def toggle_pause(self):
        self.set_pause(not self.paused)

    def seek(self, t, accurate=False):
        if self.mp is None:
            return
        t = max(0.0, float(t))
        if self.duration:
            t = min(t, max(0.0, self.duration - 0.05))
        self.eof = False
        self._seek_time = time.time()
        self._seek_target = t
        self._last_ret = t
        self._pos_time = 0.0
        self._seek_ms(int(t * 1000))

    def seek_relative(self, delta):
        self.seek(self.position + delta)

    def set_speed(self, speed):
        speed = float(speed)
        if abs(speed - self.speed) < 1e-6:
            return
        pos = self.position
        self.speed = speed
        self._apply_speed()
        self._pos, self._pos_time = pos, time.time()

    def set_volume(self, v):
        self._volume = max(0.0, min(1.0, float(v)))
        if self.mp is not None:
            try:
                self.mp.setVolume(self._volume, self._volume)
            except Exception:
                pass

    def cycle_audio(self):
        if self.mp is None:
            return False
        try:
            infos = self.mp.getTrackInfo()
            audio = [i for i in range(len(infos)) if infos[i].getTrackType() == 2]
            if len(audio) < 2:
                return False
            cur = self.mp.getSelectedTrack(2)
            nxt = audio[(audio.index(cur) + 1) % len(audio)] if cur in audio else audio[0]
            self.mp.selectTrack(nxt)
            return True
        except Exception:
            traceback.print_exc()
            return False
