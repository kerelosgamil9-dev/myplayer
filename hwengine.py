# -*- coding: utf-8 -*-
"""
hwengine.py - hardware-accelerated playback through Android's own MediaPlayer.

Video and audio are decoded by the phone's hardware codecs (smooth 1080p/4K,
real 2x speed with pitch kept, perfect A/V sync, little battery use).  The
decoder renders into a SurfaceTexture; a small Fbo converts that external
(OES) texture into a normal Kivy texture that the player page draws.

Everything here is Android-only and wrapped defensively: if anything fails, the
wrapper in engine.py silently falls back to the ffpyplayer engine.
"""
import time
import traceback

from kivy.clock import Clock

import bridge

GL_TEXTURE_EXTERNAL_OES = 0x8D65

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

    def __init__(self, on_frame=None, on_eof=None, on_error=None, on_fail=None):
        self.on_frame = on_frame
        self.on_eof = on_eof
        self.on_error = on_error
        self.on_fail = on_fail          # callback(position) when hardware playback does not work
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
        self._volume = 1.0
        self._ev = None
        self._last_count = 0
        self._open_time = 0.0
        self._seek_time = 0.0
        self._seek_target = 0.0
        self._next_slow = 0.0
        self._failed = False
        self._fbo_size = None

    # ---- lifecycle ------------------------------------------------------------
    def open(self, path, start=0.0, speed=1.0, paused=False, duration_hint=0.0):
        self.close(keep_texture=True)
        self.path = path
        self.speed = float(speed)
        self.paused = bool(paused)
        self.eof = False
        self.ready = False
        self._failed = False
        self._last_count = 0
        if duration_hint:
            self.duration = float(duration_hint)
        try:
            from jnius import autoclass
            from kivy.graphics.texture import Texture
            bridge.crumb('hw: open %s' % path)
            self.oes = Texture(width=16, height=16, target=GL_TEXTURE_EXTERNAL_OES, colorfmt='rgba')
            bridge.crumb('hw: oes texture %s' % self.oes.id)
            SurfaceTexture = autoclass('android.graphics.SurfaceTexture')
            Surface = autoclass('android.view.Surface')
            MP = autoclass('android.media.MediaPlayer')
            self.st = SurfaceTexture(int(self.oes.id))
            self.listener = _listener_class()()
            self.st.setOnFrameAvailableListener(self.listener)
            self.surface = Surface(self.st)
            bridge.crumb('hw: surface ready')
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
            self._ev = Clock.schedule_interval(self._tick, 1.0 / 60.0)
        return True

    last_error = ''
    black_fail = False

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
        self._fbo_size = None

    # ---- GL ------------------------------------------------------------------------
    def _make_fbo(self):
        from kivy.graphics import BindTexture, ClearBuffers, ClearColor, Fbo, Rectangle
        w, h = self.size
        fbo = Fbo(size=(w, h))
        fbo.shader.fs = _FS
        ok = getattr(fbo.shader, 'success', True)
        bridge.crumb('hw: shader ok=%s size=%dx%d' % (ok, w, h))
        if not ok:
            raise RuntimeError('video shader failed to compile')
        with fbo:
            ClearColor(0, 0, 0, 1)
            ClearBuffers()
            BindTexture(texture=self.oes, index=1)
            Rectangle(size=(w, h))
        self.fbo = fbo
        self._fbo_size = (w, h)
        self.texture = fbo.texture
        self._set_matrix(_DEFAULT_MATRIX)
        self._first_frame_time = 0.0
        self._pix_checks = [0.4, 1.2, 2.5]
        self._pix_ok = False

    def _set_matrix(self, flat):
        from kivy.graphics.transformation import Matrix
        m = Matrix()
        m.set(flat=[float(x) for x in flat])
        self.fbo['texmat'] = m

    def _update_frame(self):
        st = self.st
        st.updateTexImage()
        flat = [0.0] * 16
        try:
            st.getTransformMatrix(flat)
        except Exception:
            flat = None
        if not flat or not any(abs(v) > 1e-6 for v in flat):
            flat = _DEFAULT_MATRIX
        self._set_matrix(flat)
        self.fbo.ask_update()
        self.fbo.draw()

    # ---- per-frame ------------------------------------------------------------
    def _tick(self, dt):
        if self.mp is None or self.listener is None:
            return
        now = time.time()
        cnt = self.listener.count
        if cnt != self._last_count:
            self._last_count = cnt
            try:
                self._update_frame()
            except Exception as ex:
                traceback.print_exc()
                bridge.crumb('hw: frame failed %s' % ex)
                self._fail(str(ex))
                return
            if not self.ready:
                self.ready = True
                self._first_frame_time = now
                bridge.crumb('hw: first frame')
            if self.on_frame:
                self.on_frame(self.texture)
        elif not self.ready and not self.paused and now - self._open_time > 4.0:
            self._fail('no video frames from the hardware decoder')
            return
        if self.ready and not self._pix_ok and self._pix_checks \
                and now - self._first_frame_time >= self._pix_checks[0]:
            self._pix_checks.pop(0)
            if self._picture_visible():
                self._pix_ok = True
                bridge.crumb('hw: picture ok')
            elif not self._pix_checks:
                bridge.crumb('hw: picture black')
                self._fail('picture stayed black (GL path)', black=True)
                return
        if now >= self._next_slow:
            self._next_slow = now + 0.15
            self._check_end(now)

    def _check_end(self, now):
        if self.paused or self.eof or now - self._seek_time < 0.8:
            return
        try:
            playing = self.mp.isPlaying()
            pos = self.mp.getCurrentPosition() / 1000.0
        except Exception:
            return
        if not playing and self.duration and pos >= self.duration - 0.6:
            self.eof = True
            if self.on_eof:
                self.on_eof()

    def _picture_visible(self):
        try:
            px = self.texture.pixels
            return any(px[i] > 12 for i in range(0, len(px), 97))
        except Exception as ex:
            bridge.crumb('hw: pixel check failed %s' % ex)
            return True                     # cannot tell: assume fine

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
        if time.time() - self._seek_time < 0.7:
            return self._seek_target
        if self.mp is None:
            return self._seek_target
        try:
            p = self.mp.getCurrentPosition() / 1000.0
        except Exception:
            return self._seek_target
        if self.duration:
            p = min(p, self.duration)
        return max(0.0, p)

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
        self._seek_ms(int(t * 1000))

    def seek_relative(self, delta):
        self.seek(self.position + delta)

    def set_speed(self, speed):
        speed = float(speed)
        if abs(speed - self.speed) < 1e-6:
            return
        self.speed = speed
        self._apply_speed()

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
