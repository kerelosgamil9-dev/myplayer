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

import bridge                                                     # noqa: E402
import core                                                       # noqa: E402
import widgets                                                    # noqa: E402
from screens import CollectionPage, HomePage, PickerPage, Root   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)


class ProPlayerApp(App):
    title = core.APP_TITLE

    def build(self):
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
