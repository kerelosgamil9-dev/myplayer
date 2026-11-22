# -*- coding: utf-8 -*-
"""
services.py - platform services: sound effects, text-to-speech, storage
locations and system theme detection.

Everything here degrades gracefully: when a service is not available on the
current device (for example Pydroid 3 without pyjnius) the call simply
returns False and the UI shows a friendly message instead of crashing.
"""

import math
import os
import shutil
import struct
import subprocess
import time
import wave
from datetime import datetime

from kivy.utils import platform

ANDROID = platform == 'android'


def is_android():
    return ANDROID


_HERE = os.path.dirname(os.path.abspath(__file__))


def find_asset(name):
    """Image / file next to the code (flat repo) or inside an assets/ folder."""
    for p in (os.path.join(_HERE, name), os.path.join(_HERE, 'assets', name)):
        if os.path.exists(p):
            return p
    return None


# ---------------------------------------------------------------- system bars
def _hex(rgb):
    return '#%02X%02X%02X' % tuple(int(max(0, min(1, c)) * 255) for c in rgb[:3])


def set_system_bars(status_rgb, nav_rgb, light_icons):
    """Colour the Android status bar / navigation bar like the app background.
    light_icons=True gives dark icons (for light themes). Silent no-op elsewhere."""
    if not ANDROID:
        return False
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
        activity = get_activity()
        if activity is None:
            return False
        Color = autoclass('android.graphics.Color')
        LP = autoclass('android.view.WindowManager$LayoutParams')
        st, nv = _hex(status_rgb), _hex(nav_rgb)

        @run_on_ui_thread
        def _apply():
            try:
                window = activity.getWindow()
                window.clearFlags(LP.FLAG_TRANSLUCENT_STATUS)
                window.addFlags(LP.FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
                window.setStatusBarColor(Color.parseColor(st))
                window.setNavigationBarColor(Color.parseColor(nv))
                decor = window.getDecorView()
                flags = decor.getSystemUiVisibility()
                light = 0x2000 | 0x10          # LIGHT_STATUS_BAR | LIGHT_NAVIGATION_BAR
                flags = (flags | light) if light_icons else (flags & ~light)
                decor.setSystemUiVisibility(flags)
            except Exception:                  # noqa: BLE001 - cosmetic only
                pass
        _apply()
        return True
    except Exception:                          # noqa: BLE001
        return False


# ---------------------------------------------------------------- keyboard
def _force_ime():
    """Ask Android directly to show the soft keyboard for the SDL view."""
    try:
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
        activity = get_activity()
        if activity is None:
            return
        Context = autoclass('android.content.Context')
        try:
            view = autoclass('org.libsdl.app.SDLActivity').mSurface
        except Exception:                                   # noqa: BLE001
            view = None

        @run_on_ui_thread
        def _go():
            try:
                imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE)
                v = view or activity.getWindow().getDecorView()
                v.requestFocus()
                imm.showSoftInput(v, 0)
            except Exception:                               # noqa: BLE001
                pass
        _go()
    except Exception:                                       # noqa: BLE001
        pass


def install_keyboard_probe(on_fail):
    """Android only.  Kivy drops the keyboard 0.2 s after asking for it when the phone
    has not drawn it yet.  Here the phone's keyboard gets ~1.2 s; if it still is not
    on screen, on_fail(field) is called (the app then shows its own keyboard).
    Returns nothing; harmless elsewhere."""
    if not ANDROID:
        return
    try:
        from kivy.clock import Clock
        from kivy.core.window import Window
        orig_request = Window.request_keyboard
        state = {'t0': 0.0, 'seen': False}

        def request(callback, target, input_type='text', keyboard_suggestions=True):
            state['t0'] = time.time()
            state['seen'] = False
            kb = orig_request(callback, target, input_type, keyboard_suggestions)
            Clock.schedule_once(lambda dt: _force_ime(), 0.1)
            return kb

        def check(dt):
            kb = getattr(Window, '_sdl_keyboard', None)
            if kb is None:
                return False
            try:
                shown = Window._win.is_keyboard_shown()
            except Exception:                               # noqa: BLE001
                shown = False
            if shown:
                state['seen'] = True
                return None
            if state['seen']:                               # the user closed it
                kb.release()
                return False
            age = time.time() - state['t0']
            if age > 1.2:
                try:
                    if on_fail(kb.target):
                        return False
                except Exception:                           # noqa: BLE001
                    pass
                if age > 4.0:
                    kb.release()
                    return False
            return None

        Window.request_keyboard = request
        Window._check_keyboard_shown = check
    except Exception:                                       # noqa: BLE001
        pass


def keyboard_diagnostics():
    """Human-readable facts about the phone's keyboard state (for troubleshooting)."""
    lines = ['android: %s' % ANDROID]
    if not ANDROID:
        return lines
    try:
        from jnius import autoclass
        activity = get_activity()
        Build = autoclass('android.os.Build$VERSION')
        Context = autoclass('android.content.Context')
        lines.append('sdk: %s' % Build.SDK_INT)
        try:
            lines.append('target sdk: %s' % activity.getApplicationInfo().targetSdkVersion)
        except Exception as e:                              # noqa: BLE001
            lines.append('target sdk: ? %s' % e)
        try:
            lines.append('window focus: %s' % activity.hasWindowFocus())
        except Exception as e:                              # noqa: BLE001
            lines.append('window focus: ? %s' % e)
        try:
            imm = activity.getSystemService(Context.INPUT_METHOD_SERVICE)
            lines.append('imm active: %s' % imm.isActive())
            lines.append('imm accepting text: %s' % imm.isAcceptingText())
            names = [str(i.getPackageName()) for i in imm.getEnabledInputMethodList().toArray()]
            lines.append('keyboards: %s' % ', '.join(names))
        except Exception as e:                              # noqa: BLE001
            lines.append('imm: ? %s' % e)
        try:
            sdl = autoclass('org.libsdl.app.SDLActivity')
            lines.append('SDL text view: %s' % (sdl.mTextEdit is not None))
        except Exception as e:                              # noqa: BLE001
            lines.append('SDL: ? %s' % e)
        try:
            from kivy.core.window import Window
            lines.append('kivy keyboard shown: %s' % Window._win.is_keyboard_shown())
        except Exception as e:                              # noqa: BLE001
            lines.append('kivy: ? %s' % e)
    except Exception as e:                                  # noqa: BLE001
        lines.append('error: %s' % e)
    return lines


# ---------------------------------------------------------------- activity
def get_activity():
    """Return the current Android Activity (or None)."""
    if not ANDROID:
        return None
    try:
        from jnius import autoclass
    except Exception:
        return None
    for cls in ('org.kivy.android.PythonActivity',
                'org.renpy.android.PythonActivity'):
        try:
            return autoclass(cls).mActivity
        except Exception:
            continue
    try:
        from android import mActivity            # newer python-for-android
        return mActivity
    except Exception:
        return None


# ------------------------------------------------------------ system theme
def system_is_dark():
    """True/False from the phone's night mode; falls back to the clock."""
    if ANDROID:
        try:
            from jnius import autoclass
            Configuration = autoclass('android.content.res.Configuration')
            act = get_activity()
            cfg = act.getResources().getConfiguration()
            mode = cfg.uiMode & Configuration.UI_MODE_NIGHT_MASK
            return mode == Configuration.UI_MODE_NIGHT_YES
        except Exception:
            pass
    hour = datetime.now().hour
    return hour >= 19 or hour < 6


# --------------------------------------------------------------- sound fx
class SoundFX:
    """Tiny synthesised sound effects (no audio assets needed)."""

    RATE = 22050

    def __init__(self, folder):
        self.folder = folder
        self.enabled = True
        self._sounds = {}
        self._ready = False

    # -- synthesis ------------------------------------------------------
    def _tone(self, freq, dur, vol=0.35, slide=None, shape='sine'):
        n = int(self.RATE * dur)
        out = []
        phase = 0.0
        for i in range(n):
            f = freq if slide is None else freq + (slide - freq) * (i / float(n))
            phase += 2 * math.pi * f / self.RATE
            if shape == 'square':
                v = 1.0 if math.sin(phase) >= 0 else -1.0
                v *= 0.6
            else:
                v = math.sin(phase)
            attack = min(1.0, i / (self.RATE * 0.004))
            release = min(1.0, (n - i) / (n * 0.35))
            out.append(int(32767 * vol * v * attack * release))
        return out

    def _write(self, name, samples):
        path = os.path.join(self.folder, name + '.wav')
        with wave.open(path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.RATE)
            wf.writeframes(b''.join(struct.pack('<h', max(-32768, min(32767, s)))
                                    for s in samples))
        return path

    def _build(self):
        os.makedirs(self.folder, exist_ok=True)
        t = self._tone
        specs = {
            'click': t(1100, 0.035, 0.22),
            'flip': t(520, 0.07, 0.25, slide=860),
            'correct': t(660, 0.09, 0.32) + t(880, 0.16, 0.32),
            'wrong': t(230, 0.22, 0.22, slide=150, shape='square'),
            'win': (t(523, 0.1) + t(659, 0.1) + t(784, 0.1) + t(1047, 0.3)),
            'lose': t(392, 0.14) + t(330, 0.14) + t(262, 0.3),
        }
        for name, samples in specs.items():
            path = os.path.join(self.folder, name + '.wav')
            if not os.path.exists(path):
                self._write(name, samples)

    def load(self):
        if self._ready:
            return
        self._ready = True
        try:
            from kivy.core.audio import SoundLoader
            self._build()
            for name in ('click', 'flip', 'correct', 'wrong', 'win', 'lose'):
                snd = SoundLoader.load(os.path.join(self.folder, name + '.wav'))
                if snd:
                    self._sounds[name] = snd
        except Exception:
            self._sounds = {}

    def play(self, name):
        if not self.enabled:
            return
        if not self._ready:
            self.load()
        snd = self._sounds.get(name)
        if snd:
            try:
                snd.stop()
                snd.play()
            except Exception:
                pass


# -------------------------------------------------------- text to speech
class TTS:
    """Text-to-speech with several fallbacks.

    1. Android TextToSpeech through pyjnius (APK build and many Pydroid builds)
    2. plyer.tts
    3. desktop command line speakers (espeak / spd-say / say / SAPI)
    """

    def __init__(self):
        self.backend = None
        self._tts = None
        self._ready = False
        self._pending = None
        self._listener = None
        self._started = False

    def start(self):
        """Initialise lazily (first use) so start-up stays fast."""
        if self._started:
            return
        self._started = True
        if ANDROID and self._init_android():
            self.backend = 'android'
            return
        try:
            from plyer import tts as plyer_tts          # noqa: F401
            self.backend = 'plyer'
            return
        except Exception:
            pass
        for cmd in ('espeak-ng', 'espeak', 'spd-say', 'say'):
            if shutil.which(cmd):
                self.backend = cmd
                return
        if os.name == 'nt':
            self.backend = 'sapi'

    def _init_android(self):
        try:
            from jnius import autoclass, PythonJavaClass, java_method
            activity = get_activity()
            if activity is None:
                return False
            TextToSpeech = autoclass('android.speech.tts.TextToSpeech')
            outer = self

            class _InitListener(PythonJavaClass):
                __javainterfaces__ = ['android/speech/tts/TextToSpeech$OnInitListener']

                @java_method('(I)V')
                def onInit(self, status):
                    outer._on_android_ready(status)

            self._listener = _InitListener()
            self._tts = TextToSpeech(activity, self._listener)
            return True
        except Exception:
            self._tts = None
            return False

    def _on_android_ready(self, status):
        try:
            if status == 0:                      # TextToSpeech.SUCCESS
                from jnius import autoclass
                Locale = autoclass('java.util.Locale')
                self._tts.setLanguage(Locale.US)
                self._ready = True
                if self._pending:
                    text, self._pending = self._pending, None
                    self._speak_android(text)
            else:
                self.backend = None
        except Exception:
            self.backend = None

    def _speak_android(self, text):
        try:
            self._tts.speak(text, 0, None, 'lingora')      # QUEUE_FLUSH
            return True
        except Exception:
            try:
                self._tts.speak(text, 0, None)
                return True
            except Exception:
                return False

    @property
    def available(self):
        self.start()
        return self.backend is not None

    def speak(self, text):
        """Speak an English text. Returns False when no engine is available."""
        text = (text or '').strip()
        if not text:
            return False
        self.start()
        b = self.backend
        try:
            if b == 'android':
                if not self._ready:
                    self._pending = text
                    return True
                return self._speak_android(text)
            if b == 'plyer':
                from plyer import tts as plyer_tts
                plyer_tts.speak(text)
                return True
            if b in ('espeak-ng', 'espeak'):
                subprocess.Popen([b, '-v', 'en-us', text],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            if b == 'spd-say':
                subprocess.Popen(['spd-say', '-l', 'en', text])
                return True
            if b == 'say':
                subprocess.Popen(['say', text])
                return True
            if b == 'sapi':
                safe = text.replace("'", "''")
                subprocess.Popen(['powershell', '-Command',
                                  "Add-Type -AssemblyName System.Speech; "
                                  "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                                  ".Speak('%s')" % safe])
                return True
        except Exception:
            return False
        return False

    def stop(self):
        try:
            if self.backend == 'android' and self._tts is not None:
                self._tts.stop()
        except Exception:
            pass


# ---------------------------------------------------------------- storage
def request_storage_permissions():
    """Ask Android for storage access (ignored elsewhere / on Pydroid)."""
    if not ANDROID:
        return
    try:
        from android.permissions import request_permissions, Permission
        request_permissions([Permission.WRITE_EXTERNAL_STORAGE,
                             Permission.READ_EXTERNAL_STORAGE])
    except Exception:
        pass


class Storage:
    """Locations used for JSON backups."""

    def __init__(self, user_dir):
        self.user_dir = user_dir

    def candidate_dirs(self):
        dirs = []
        if ANDROID:
            dirs += ['/storage/emulated/0/Download/Lingora',
                     '/storage/emulated/0/Documents/Lingora',
                     '/sdcard/Download/Lingora']
            try:
                act = get_activity()
                ext = act.getExternalFilesDir(None)
                if ext is not None:
                    dirs.append(os.path.join(ext.getAbsolutePath(), 'backups'))
            except Exception:
                pass
        else:
            home = os.path.expanduser('~')
            dirs += [os.path.join(home, 'Downloads', 'Lingora'),
                     os.path.join(home, 'Lingora_backups')]
        dirs.append(os.path.join(self.user_dir, 'backups'))
        seen, out = set(), []
        for d in dirs:
            if d not in seen:
                seen.add(d)
                out.append(d)
        return out

    def writable_dir(self):
        """First backup directory we can actually write to."""
        for d in self.candidate_dirs():
            try:
                os.makedirs(d, exist_ok=True)
                probe = os.path.join(d, '.write_test')
                with open(probe, 'w') as fh:
                    fh.write('ok')
                os.remove(probe)
                return d
            except Exception:
                continue
        return None

    def new_backup_path(self):
        d = self.writable_dir()
        if d is None:
            return None
        name = 'lingora_backup_%s.json' % time.strftime('%Y%m%d_%H%M%S')
        return os.path.join(d, name)

    def list_backups(self):
        """[(path, mtime, size)] newest first, from every candidate directory."""
        found = []
        for d in self.candidate_dirs():
            try:
                for fn in os.listdir(d):
                    if fn.lower().endswith('.json') and fn.lower().startswith('lingora'):
                        p = os.path.join(d, fn)
                        st = os.stat(p)
                        found.append((p, st.st_mtime, st.st_size))
            except Exception:
                continue
        found.sort(key=lambda t: -t[1])
        return found
