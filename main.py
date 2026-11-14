# -*- coding: utf-8 -*-
"""
Pro Player - a video player with Arabic UI, device-album playlists, manual
ordering by drag, hold-to-speed-up and many player features.

Run on PC for a quick look:   PROPLAYER_DIR=/path/with/videos python main.py
"""
import os
import sys
import traceback

os.environ.setdefault('KIVY_NO_ARGS', '1')

from kivy.config import Config                                   # noqa: E402

Config.set('kivy', 'exit_on_escape', '0')
Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

from kivy.app import App                                          # noqa: E402
from kivy.clock import Clock                                      # noqa: E402
from kivy.core.window import Window                               # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

IMPORT_ERROR = None
try:
    import bridge                                                 # noqa: E402
    import core                                                   # noqa: E402
    import widgets                                                # noqa: E402
    from screens import CollectionPage, HomePage, PickerPage, Root   # noqa: E402
except Exception:
    IMPORT_ERROR = traceback.format_exc()
    core = None


def error_view(text):
    """Plain Kivy widgets only: shows a traceback on screen so it can be photographed."""
    from kivy.uix.boxlayout import BoxLayout
    from kivy.uix.button import Button
    from kivy.uix.label import Label
    from kivy.uix.scrollview import ScrollView
    box = BoxLayout(orientation='vertical', padding=10, spacing=10)
    sv = ScrollView(size_hint=(1, 1))
    lab = Label(text=text, size_hint_y=None, halign='left', valign='top', font_size='12sp',
                text_size=(Window.width - 30, None), color=(1, 0.8, 0.8, 1))
    lab.bind(texture_size=lambda inst, val: setattr(inst, 'height', val[1] + 20))
    sv.add_widget(lab)
    box.add_widget(sv)
    btn = Button(text='Close', size_hint=(1, None), height=90)
    box.add_widget(btn)
    return box, btn


class ProPlayerApp(App):
    title = 'Pro Player'

    def build(self):
        try:
            if IMPORT_ERROR:
                raise RuntimeError(IMPORT_ERROR)
            return self._build()
        except Exception:
            tb = traceback.format_exc()
            Window.clearcolor = (0.1, 0, 0, 1)
            view, btn = error_view('STARTUP ERROR\n\n' + tb)
            btn.bind(on_release=lambda *a: self.stop())
            return view

    def _install_error_overlay(self):
        from kivy.base import ExceptionHandler, ExceptionManager
        app = self

        class Handler(ExceptionHandler):
            def handle_exception(self, inst):
                try:
                    app.show_error(traceback.format_exc())
                except Exception:
                    pass
                return ExceptionManager.PASS
        ExceptionManager.add_handler(Handler())

    def show_error(self, tb):
        if getattr(self, '_err_view', None) is not None:
            return
        view, btn = error_view('ERROR (the app is still running)\n\n' + tb)
        self._err_view = view
        Window.add_widget(view)

        def close(*a):
            Window.remove_widget(view)
            self._err_view = None
        btn.bind(on_release=close)

    def _build(self):
        self._err_view = None
        self._install_error_overlay()
        widgets.register_fonts()
        Window.clearcolor = (0, 0, 0, 1)
        self.store = core.Store(os.path.join(bridge.data_dir(self), 'library.json'))
        self.lib = core.Library(self.store)
        self.thumbs = bridge.ThumbService(self)
        self.loaded = False
        self.permitted = False
        self.root = Root(self)
        self.home = HomePage(self)
        self.root.push(self.home)
        Window.bind(on_keyboard=self._on_keyboard)
        Clock.schedule_once(lambda dt: self.start_up(), 0.2)
        Clock.schedule_interval(lambda dt: self.store.save(), 20)
        return self.root

    # ---- startup / scanning ------------------------------------------------------
    def start_up(self):
        bridge.request_permissions(self._perm_result)

    def _perm_result(self, ok):
        self.permitted = ok
        if not ok:
            self.loaded = True
            self.home.rebuild()
            self.root.say('يلزم السماح بالوصول إلى الفيديوهات')
            return
        self.rescan()

    def rescan(self, manual=False):
        if not bridge.has_permissions():
            bridge.request_permissions(self._perm_result)
            return

        def done(videos):
            self.lib.set_catalog(videos)
            self.loaded = True
            self.permitted = True
            self.root.refresh_pages()
            if manual:
                self.root.say('تم العثور على %d فيديو' % len(videos))
        bridge.scan_videos_async(done)

    # ---- helpers used by pages -------------------------------------------------------
    def thumb(self, key, callback):
        if not self.store.setting('show_thumbs'):
            return None
        v = self.lib.videos.get(key)
        if v is None:
            return None
        return self.thumbs.get(v, callback)

    def open_collection(self, cid):
        self.root.push(CollectionPage(self, cid))

    def open_picker(self, cid):
        self.root.push(PickerPage(self, cid))

    def play(self, keys, index, cid=None):
        from player import PlayerPage          # imported lazily: needs ffpyplayer
        if not keys:
            return
        self.root.push(PlayerPage(self, keys, index, cid))

    # ---- android keys / lifecycle -----------------------------------------------------
    def _on_keyboard(self, window, key, scancode=None, codepoint=None, modifier=None, **kw):
        if key == 27:
            return self.root.back()
        return False

    def _player(self):
        page = self.root.pages[-1] if self.root.pages else None
        return page if hasattr(page, 'on_app_pause') else None

    def on_pause(self):
        p = self._player()
        if p:
            p.on_app_pause()
        self.store.save(force=True)
        return True

    def on_resume(self):
        p = self._player()
        if p:
            p.on_app_resume()
        else:
            self.rescan()

    def on_stop(self):
        try:
            p = self._player()
            if p:
                p.on_close()
            self.store.save(force=True)
        except Exception:
            traceback.print_exc()


if __name__ == '__main__':
    ProPlayerApp().run()
