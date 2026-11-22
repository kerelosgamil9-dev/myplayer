# -*- coding: utf-8 -*-
"""
Lingora - English learning app (pure Kivy + SQLite).

Entry point: creates the window, the navigation drawer and the screens.
Run it with:  python main.py   (or open it in Pydroid 3 and press play)
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from kivy.config import Config                                    # noqa: E402
from kivy.utils import platform                                    # noqa: E402

Config.set('kivy', 'exit_on_escape', '0')
if platform in ('linux', 'win', 'macosx'):
    # phone-shaped window when testing on a computer
    Config.set('graphics', 'width', os.environ.get('LINGORA_W', '400'))
    Config.set('graphics', 'height', os.environ.get('LINGORA_H', '780'))
    Config.set('graphics', 'resizable', '1')

from kivy.app import App                                           # noqa: E402
from kivy.clock import Clock                                       # noqa: E402
from kivy.core.text import LabelBase                               # noqa: E402
from kivy.core.window import Window                                # noqa: E402
from kivy.metrics import dp, sp                                    # noqa: E402
from kivy.uix.boxlayout import BoxLayout                           # noqa: E402
from kivy.uix.floatlayout import FloatLayout                       # noqa: E402
from kivy.uix.modalview import ModalView                           # noqa: E402
from kivy.uix.screenmanager import FadeTransition, ScreenManager   # noqa: E402
from kivy.uix.widget import Widget                                 # noqa: E402
from kivy.graphics import Color, RoundedRectangle                  # noqa: E402


# ----------------------------------------------------------------------
# fonts: Roboto (Kivy default) has no Arabic glyphs, so the default font is
# replaced by a font that has Latin + Arabic (bundled DejaVu Sans, or one of
# the Android system Arabic fonts as a fallback).
# ----------------------------------------------------------------------
def setup_fonts():
    fonts = os.path.join(BASE_DIR, 'fonts')
    regular = [os.path.join(fonts, 'DejaVuSans.ttf'),
               os.path.join(BASE_DIR, 'DejaVuSans.ttf'),      # font next to main.py
               '/system/fonts/NotoNaskhArabic-Regular.ttf',
               '/system/fonts/NotoSansArabic-Regular.ttf',
               '/system/fonts/DroidSansArabic.ttf',
               '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    bold = [os.path.join(fonts, 'DejaVuSans-Bold.ttf'),
            os.path.join(BASE_DIR, 'DejaVuSans-Bold.ttf'),
            '/system/fonts/NotoNaskhArabic-Bold.ttf',
            '/system/fonts/NotoSansArabic-Bold.ttf',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf']
    reg = next((p for p in regular if os.path.exists(p)), None)
    bld = next((p for p in bold if os.path.exists(p)), None) or reg
    if reg:
        LabelBase.register(name='Roboto', fn_regular=reg, fn_bold=bld)
    else:
        print('[Lingora] WARNING: no Arabic-capable font found. '
              'Put DejaVuSans.ttf (and -Bold) next to main.py or in a "fonts" folder.')


setup_fonts()

import rtl                                                         # noqa: E402
import strings                                                     # noqa: E402
from database import Database                                      # noqa: E402
from screens import (ChallengesScreen, FolderScreen,   # noqa: E402
                     FoldersScreen, GameScreen, HomeScreen, level_cfg,
                     LevelsScreen, SettingsScreen, folder_game_dialog,
                     source_dialog)
from services import (SoundFX, Storage, TTS, request_storage_permissions,  # noqa: E402
                      find_asset, install_keyboard_probe, set_system_bars, system_is_dark)
from strings import tr                                             # noqa: E402
from theme import C, THEME, alpha                                  # noqa: E402
import widgets as widgets_mod                                      # noqa: E402
from widgets import (ALabel, DrawerItem, FlameWidget, NavDrawer, Toast,  # noqa: E402
                     TopBar, add_row, hbox, logo_image, spacer)

_LOGO = find_asset('logo.png')
if _LOGO:
    try:
        Window.set_icon(_LOGO)              # desktop window icon (Android uses the APK icon)
    except Exception:                       # noqa: BLE001
        pass

ROOTS = ('home', 'folders', 'levels', 'challenges', 'settings')
NAV = [('home', 'home', 'nav_home'),
       ('folders', 'folder', 'nav_folders'),
       ('levels', 'levels', 'nav_levels'),
       ('challenges', 'bolt', 'nav_challenges'),
       ('settings', 'gear', 'nav_settings')]


class LingoraApp(App):
    title = 'Lingora'

    # ------------------------------------------------------------------
    # life cycle
    # ------------------------------------------------------------------
    def build(self):
        try:
            self.user_dir = self.user_data_dir
            os.makedirs(self.user_dir, exist_ok=True)
        except Exception:                                           # noqa: BLE001
            self.user_dir = os.path.join(BASE_DIR, 'data')
            os.makedirs(self.user_dir, exist_ok=True)
        self.db = Database(os.path.join(self.user_dir, 'lingora.db'))
        self.sfx = SoundFX(os.path.join(self.user_dir, 'sfx'))
        self.tts = TTS()
        self.storage = Storage(self.user_dir)
        self.game_cfg = None
        self.current_folder_id = None
        self.history = []
        self.current = 'home'
        self.section = 'home'
        self._last_back = 0
        self._tts_warned = False
        self._theme_mode_at_build = None

        widgets_mod.VK['mode'] = self.db.get('kb_mode') or 'auto'
        install_keyboard_probe(widgets_mod.vk_fallback)
        Window.bind(on_keyboard=self.on_key)

        self.root_widget = FloatLayout()
        self.apply_settings()
        self.build_ui('home')
        return self.root_widget

    def on_start(self):
        request_storage_permissions()
        Clock.schedule_once(lambda dt: self.sfx.load(), 1.0)

    def on_pause(self):
        return True

    def on_resume(self):
        # follow the phone's night mode when the theme is "auto"
        if self.db.get('theme') == 'auto':
            mode = 'dark' if system_is_dark() else 'light'
            if mode != self._theme_mode_at_build:
                self.rebuild(self.current if self.current in ROOTS else 'home')

    def on_stop(self):
        try:
            self.tts.stop()
            self.db.close()
        except Exception:                                           # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # settings -> runtime state
    # ------------------------------------------------------------------
    def apply_settings(self):
        db = self.db
        self.lang = db.get('lang') if db.get('lang') in ('ar', 'en') else 'ar'
        strings.set_lang(self.lang)
        rtl.UI_RTL = self.lang == 'ar'
        rtl.ENABLED = True                  # Arabic shaping / bidi is always on
        pref = db.get('theme')
        if pref == 'auto':
            mode = 'dark' if system_is_dark() else 'light'
        else:
            mode = pref if pref in ('dark', 'light') else 'dark'
        THEME.set_mode(mode)
        self._theme_mode_at_build = mode
        Window.clearcolor = C('bg')
        self.sfx.enabled = db.get_bool('sound')
        Clock.schedule_once(lambda dt: set_system_bars(C('topbar'), C('bg'), mode == 'light'), 0.2)

    def rebuild(self, goto='home'):
        """Re-create the whole UI (theme / language changed)."""
        for w in list(Window.children):
            if isinstance(w, ModalView):
                try:
                    w.dismiss(animation=False)
                except Exception:                                   # noqa: BLE001
                    pass
        self.apply_settings()
        self.build_ui(goto)

    # ------------------------------------------------------------------
    # UI skeleton
    # ------------------------------------------------------------------
    def build_ui(self, start):
        self.root_widget.clear_widgets()
        main = BoxLayout(orientation='vertical')
        self.topbar = TopBar(on_menu=lambda: self.drawer.toggle(), on_back=self.go_back)
        self.sm = ScreenManager(transition=FadeTransition(duration=0.12))
        self.screens = {
            'home': HomeScreen(self, name='home'),
            'folders': FoldersScreen(self, name='folders'),
            'folder': FolderScreen(self, name='folder'),
            'levels': LevelsScreen(self, name='levels'),
            'challenges': ChallengesScreen(self, name='challenges'),
            'game': GameScreen(self, name='game'),
            'settings': SettingsScreen(self, name='settings'),
        }
        for s in self.screens.values():
            self.sm.add_widget(s)
        main.add_widget(self.topbar)
        main.add_widget(self.sm)
        self.drawer = NavDrawer()
        self.root_widget.add_widget(main)
        self.root_widget.add_widget(self.drawer)
        self.history = []
        self.section = start if start in ROOTS else 'home'
        self.current = start
        self.sm.current = start
        self.screens[start].on_pre_enter()
        self.refresh_drawer()

    def apply_topbar(self, screen):
        spec = screen.topbar_spec()
        title, mode, actions = spec[:3]
        extra = spec[3] if len(spec) > 3 else {}
        self.topbar.set(title, mode, actions, **extra)

    def refresh_drawer(self):
        p = self.drawer.panel
        p.clear_widgets()
        db = self.db
        streak = db.get_streak()
        head = hbox(dp(64), spacing=dp(12))
        col = BoxLayout(orientation='vertical', spacing=dp(2))
        col.add_widget(ALabel(raw='Lingora', font_size=sp(24), bold=True, color=C('text'),
                              align='left' if not rtl.UI_RTL else 'right'))
        col.add_widget(ALabel(raw=tr('tagline'), font_size=sp(12), color=C('sub'),
                              align='left' if not rtl.UI_RTL else 'right'))
        add_row(head, [logo_image(dp(56)), col])
        p.add_widget(head)
        pill = hbox(dp(54), spacing=dp(10), padding=[dp(12), dp(4)])
        with pill.canvas.before:
            Color(*alpha(C('accent'), 0.13))
            pr = RoundedRectangle(pos=pill.pos, size=pill.size, radius=[dp(16)])
        pill.bind(pos=lambda w, v: setattr(pr, 'pos', v), size=lambda w, v: setattr(pr, 'size', v))
        flame = FlameWidget(days=streak, size_hint=(None, 1), width=dp(34))
        add_row(pill, [flame, ALabel(raw=tr('streak_days', n=streak), font_size=sp(15), bold=True,
                                     color=C('text'))])
        p.add_widget(pill)
        p.add_widget(spacer(h=dp(10)))
        for name, icon, key in NAV:
            item = DrawerItem(icon, tr(key), active=(name == self.section))
            item.bind(on_release=lambda inst, n=name: self._nav(n))
            p.add_widget(item)
        p.add_widget(Widget())
        p.add_widget(ALabel(raw=tr('drawer_footer'), font_size=sp(12), color=C('sub'),
                            size_hint_y=None, height=dp(24), align='center'))

    # ------------------------------------------------------------------
    # navigation
    # ------------------------------------------------------------------
    def _nav(self, name):
        self.drawer.close()
        self.go(name)

    def go(self, name, push=False):
        if name in ROOTS:
            self.history = []
            self.section = name
        elif push:
            self.history.append(self.current)
        self._show(name)

    def _show(self, name):
        self.current = name
        screen = self.screens[name]
        if self.sm.current == name:
            screen.on_pre_enter()
        else:
            self.sm.current = name
        self.refresh_drawer()

    def go_back(self):
        if self.history:
            self._show(self.history.pop())
        elif self.current != 'home':
            self.go('home')

    def on_key(self, window, key, *args):
        if key != 27:                       # Android back button / Esc
            return False
        if widgets_mod.vk_hide():           # close the typing keyboard first
            return True
        if self.drawer.is_open:
            self.drawer.close()
            return True
        if self.history or self.current != 'home':
            self.go_back()
            return True
        import time
        now = time.time()
        if now - self._last_back < 2.0:
            self.stop()
            return True
        self._last_back = now
        Toast.show(tr('press_again_exit'), 'info', 1.6)
        return True

    # ------------------------------------------------------------------
    # actions used by the screens
    # ------------------------------------------------------------------
    def open_folder(self, folder_id):
        self.current_folder_id = folder_id
        self.go('folder', push=True)

    def open_level(self, n):
        self.start_game(level_cfg(n))

    def start_game(self, cfg):
        self.game_cfg = dict(cfg)
        if self.current == 'game':
            self.screens['game'].launch()
        else:
            self.go('game', push=True)

    def pick_source(self, mode, base=None):
        source_dialog(self, mode, base)

    def pick_game_for_folder(self, folder_id):
        folder_game_dialog(self, folder_id)

    def speak(self, text, quiet=False):
        ok = self.tts.speak(text)
        if not ok and not (quiet and self._tts_warned):
            self._tts_warned = True
            Toast.show(tr('tts_unavailable'), 'warn', 3)
        return ok


if __name__ == '__main__':
    LingoraApp().run()
