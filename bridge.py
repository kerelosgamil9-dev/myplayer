# -*- coding: utf-8 -*-
"""
bridge.py - the only place that talks to Android (through pyjnius).
Every function degrades gracefully on desktop so the app can be tried on a PC
(set PROPLAYER_DIR to a folder that contains videos).
"""
import hashlib
import os
import threading
import traceback

from kivy.clock import Clock
from kivy.utils import platform

ANDROID = platform == 'android'

if ANDROID:
    try:
        from jnius import autoclass
        from android import activity as android_activity            # noqa
        from android.runnable import run_on_ui_thread               # noqa
    except Exception:                                                # pragma: no cover
        ANDROID = False

if not ANDROID:
    def run_on_ui_thread(f):
        return f

SCREEN_PORTRAIT = 1
SCREEN_LANDSCAPE = 6          # sensor landscape (both directions)
SCREEN_UNSPECIFIED = -1


def log(*a):
    try:
        print('[ProPlayer]', *a)
    except Exception:
        pass


def _activity():
    PythonActivity = autoclass('org.kivy.android.PythonActivity')
    return PythonActivity.mActivity


# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------
def data_dir(app):
    d = getattr(app, 'user_data_dir', None) or os.path.expanduser('~/.proplayer')
    os.makedirs(d, exist_ok=True)
    return d


def cache_dir(app):
    d = os.path.join(data_dir(app), 'thumbs')
    os.makedirs(d, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# permissions
# ---------------------------------------------------------------------------
def sdk_int():
    if not ANDROID:
        return 0
    try:
        return int(autoclass('android.os.Build$VERSION').SDK_INT)
    except Exception:
        return 0


def needed_permissions():
    if not ANDROID:
        return []
    if sdk_int() >= 33:
        return ['android.permission.READ_MEDIA_VIDEO']
    perms = ['android.permission.READ_EXTERNAL_STORAGE']
    if sdk_int() <= 29:
        perms.append('android.permission.WRITE_EXTERNAL_STORAGE')
    return perms


def has_permissions():
    if not ANDROID:
        return True
    try:
        from android.permissions import check_permission
        return all(check_permission(p) for p in needed_permissions())
    except Exception:
        return False


def request_permissions(callback):
    """callback(granted: bool) is called on the Kivy thread."""
    if not ANDROID or has_permissions():
        Clock.schedule_once(lambda dt: callback(True), 0)
        return
    try:
        from android.permissions import request_permissions as _req

        def _cb(perms, grants):
            ok = all(grants) if grants else False
            Clock.schedule_once(lambda dt: callback(ok), 0)
        _req(needed_permissions(), _cb)
    except Exception:
        log(traceback.format_exc())
        Clock.schedule_once(lambda dt: callback(False), 0)


def open_app_settings():
    if not ANDROID:
        return
    try:
        Intent = autoclass('android.content.Intent')
        Settings = autoclass('android.provider.Settings')
        Uri = autoclass('android.net.Uri')
        act = _activity()
        i = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
        i.setData(Uri.parse('package:' + act.getPackageName()))
        act.startActivity(i)
    except Exception:
        log(traceback.format_exc())


# ---------------------------------------------------------------------------
# scanning videos
# ---------------------------------------------------------------------------
_VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.3gp',
               '.m4v', '.ts', '.mpg', '.mpeg', '.mts', '.m2ts', '.ogv', '.vob')


def _scan_android():
    resolver = _activity().getContentResolver()
    MediaStoreVideo = autoclass('android.provider.MediaStore$Video$Media')
    uri = MediaStoreVideo.EXTERNAL_CONTENT_URI
    cols = ['_id', '_data', '_display_name', 'duration', '_size', 'date_added',
            'date_modified', 'bucket_id', 'bucket_display_name', 'width', 'height']
    cur = resolver.query(uri, cols, None, None, 'date_added DESC')
    out = []
    if cur is None:
        return out
    try:
        idx = {c: cur.getColumnIndex(c) for c in cols}

        def s(c):
            i = idx[c]
            if i < 0 or cur.isNull(i):
                return None
            return cur.getString(i)

        def n(c):
            i = idx[c]
            if i < 0 or cur.isNull(i):
                return 0
            return cur.getLong(i)

        while cur.moveToNext():
            path = s('_data')
            if not path or not os.path.isabs(path):
                continue
            if '/.' in path:                 # hidden folders / trash
                continue
            out.append({
                'id': n('_id'),
                'path': path,
                'name': s('_display_name') or os.path.basename(path),
                'duration': n('duration') / 1000.0,
                'size': n('_size'),
                'added': n('date_added'),
                'modified': n('date_modified'),
                'bucket_id': str(n('bucket_id')),
                'bucket': s('bucket_display_name') or os.path.basename(os.path.dirname(path)),
                'w': n('width'),
                'h': n('height'),
            })
    finally:
        cur.close()
    return out


def _scan_desktop():
    root = os.environ.get('PROPLAYER_DIR') or os.path.expanduser('~/Videos')
    out = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fn in files:
            if fn.lower().endswith(_VIDEO_EXTS):
                p = os.path.join(base, fn)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                out.append({'id': 0, 'path': p, 'name': fn, 'duration': 0,
                            'size': st.st_size, 'added': int(st.st_ctime),
                            'modified': int(st.st_mtime),
                            'bucket_id': base, 'bucket': os.path.basename(base) or base,
                            'w': 0, 'h': 0})
    return out


def scan_videos_async(callback):
    """Scan in a worker thread; callback(list_of_videos) runs on the Kivy thread."""
    def work():
        try:
            res = _scan_android() if ANDROID else _scan_desktop()
        except Exception:
            log(traceback.format_exc())
            res = []
        Clock.schedule_once(lambda dt: callback(res), 0)
    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------------------
# thumbnails
# ---------------------------------------------------------------------------
def thumb_path(app, video):
    sig = '%s|%s|%s' % (video['path'], video.get('size', 0), video.get('modified', 0))
    h = hashlib.md5(sig.encode('utf-8', 'replace')).hexdigest()
    return os.path.join(cache_dir(app), h + '.jpg')


def _make_thumb_android(path, out, duration):
    MMR = autoclass('android.media.MediaMetadataRetriever')
    Bitmap = autoclass('android.graphics.Bitmap')
    CF = autoclass('android.graphics.Bitmap$CompressFormat')
    FOS = autoclass('java.io.FileOutputStream')
    mmr = MMR()
    fos = None
    try:
        mmr.setDataSource(path)
        t = int(min(max(duration * 0.1, 1.0), 10.0) * 1000000) if duration else 1000000
        bmp = mmr.getFrameAtTime(t, 2)       # OPTION_CLOSEST_SYNC
        if bmp is None:
            bmp = mmr.getFrameAtTime(-1)
        if bmp is None:
            return False
        w, h = bmp.getWidth(), bmp.getHeight()
        if w <= 0 or h <= 0:
            return False
        tw = 480
        th = max(1, int(h * tw / float(w)))
        if w > tw:
            bmp = Bitmap.createScaledBitmap(bmp, tw, th, True)
        fos = FOS(out + '.part')
        ok = bmp.compress(CF.JPEG, 82, fos)
        fos.flush()
        fos.close()
        fos = None
        if ok:
            os.replace(out + '.part', out)
        return bool(ok)
    finally:
        try:
            if fos is not None:
                fos.close()
        except Exception:
            pass
        try:
            mmr.release()
        except Exception:
            pass


class ThumbService(object):
    """Generates JPEG thumbnails one by one in a background thread."""

    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.queue = []
        self.pending = set()
        self.failed = set()
        self.callbacks = {}
        self.running = False

    def get(self, video, callback=None):
        """Return the cached thumbnail path or None (and generate it)."""
        out = thumb_path(self.app, video)
        if os.path.exists(out):
            return out
        key = video['path']
        if key in self.failed or not ANDROID:
            return None
        with self.lock:
            if callback:
                self.callbacks.setdefault(key, []).append(callback)
            if key not in self.pending:
                self.pending.add(key)
                self.queue.append((video, out))
            if not self.running:
                self.running = True
                threading.Thread(target=self._work, daemon=True).start()
        return None

    def prioritise(self, key):
        with self.lock:
            for i, (v, o) in enumerate(self.queue):
                if v['path'] == key:
                    self.queue.insert(0, self.queue.pop(i))
                    break

    def _work(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.running = False
                    return
                video, out = self.queue.pop(0)
            ok = False
            try:
                ok = _make_thumb_android(video['path'], out, video.get('duration', 0))
            except Exception:
                log('thumb failed', video['path'])
            key = video['path']
            with self.lock:
                self.pending.discard(key)
                cbs = self.callbacks.pop(key, [])
                if not ok:
                    self.failed.add(key)
            if ok:
                for cb in cbs:
                    Clock.schedule_once(lambda dt, cb=cb, out=out: cb(out), 0)

    def clear_cache(self):
        d = cache_dir(self.app)
        n = 0
        for fn in os.listdir(d):
            try:
                os.remove(os.path.join(d, fn))
                n += 1
            except OSError:
                pass
        self.failed.clear()
        return n


# ---------------------------------------------------------------------------
# deleting files from the device
# ---------------------------------------------------------------------------
_DELETE_REQ = 7731
_delete_state = {'cb': None, 'bound': False, 'paths': []}


def _on_activity_result(request, result, intent):
    if request != _DELETE_REQ:
        return
    cb = _delete_state.get('cb')
    paths = _delete_state.get('paths', [])
    _delete_state['cb'] = None
    ok = (result == -1)          # RESULT_OK
    if cb:
        Clock.schedule_once(lambda dt: cb(list(paths) if ok else []), 0)


def delete_videos(videos, callback):
    """Delete files. callback(list_of_deleted_paths) on the Kivy thread.
    Android 11+ shows the system confirmation dialog."""
    paths = [v['path'] for v in videos]
    if not ANDROID:
        done = []
        for p in paths:
            try:
                os.remove(p)
                done.append(p)
            except OSError:
                pass
        Clock.schedule_once(lambda dt: callback(done), 0)
        return
    try:
        act = _activity()
        resolver = act.getContentResolver()
        ContentUris = autoclass('android.content.ContentUris')
        MS = autoclass('android.provider.MediaStore$Video$Media')
        uris = []
        for v in videos:
            if v.get('id'):
                uris.append(ContentUris.withAppendedId(MS.EXTERNAL_CONTENT_URI, int(v['id'])))
        if sdk_int() >= 30 and uris:
            ArrayList = autoclass('java.util.ArrayList')
            MediaStore = autoclass('android.provider.MediaStore')
            lst = ArrayList()
            for u in uris:
                lst.add(u)
            pi = MediaStore.createDeleteRequest(resolver, lst)
            _delete_state['cb'] = callback
            _delete_state['paths'] = paths
            if not _delete_state['bound']:
                android_activity.bind(on_activity_result=_on_activity_result)
                _delete_state['bound'] = True
            act.startIntentSenderForResult(pi.getIntentSender(), _DELETE_REQ, None, 0, 0, 0)
            return
        done = []
        for v in videos:
            ok = False
            try:
                if v.get('id'):
                    u = ContentUris.withAppendedId(MS.EXTERNAL_CONTENT_URI, int(v['id']))
                    ok = resolver.delete(u, None, None) > 0
            except Exception:
                ok = False
            if not ok:
                try:
                    os.remove(v['path'])
                    ok = True
                except OSError:
                    ok = False
            if ok:
                done.append(v['path'])
        Clock.schedule_once(lambda dt: callback(done), 0)
    except Exception:
        log(traceback.format_exc())
        Clock.schedule_once(lambda dt: callback([]), 0)


# ---------------------------------------------------------------------------
# window / system helpers
# ---------------------------------------------------------------------------
@run_on_ui_thread
def _set_orientation_ui(mode):
    try:
        _activity().setRequestedOrientation(int(mode))
    except Exception:
        log(traceback.format_exc())


def set_orientation(mode):
    if ANDROID:
        _set_orientation_ui(mode)


@run_on_ui_thread
def _immersive_ui(on):
    try:
        act = _activity()
        View = autoclass('android.view.View')
        decor = act.getWindow().getDecorView()
        if on:
            flags = (View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                     View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                     View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN)
        else:
            flags = View.SYSTEM_UI_FLAG_VISIBLE
        decor.setSystemUiVisibility(flags)
    except Exception:
        log(traceback.format_exc())


def set_immersive(on):
    if ANDROID:
        _immersive_ui(bool(on))


@run_on_ui_thread
def _keep_awake_ui(on):
    try:
        WM = autoclass('android.view.WindowManager$LayoutParams')
        w = _activity().getWindow()
        if on:
            w.addFlags(WM.FLAG_KEEP_SCREEN_ON)
        else:
            w.clearFlags(WM.FLAG_KEEP_SCREEN_ON)
    except Exception:
        log(traceback.format_exc())


def keep_awake(on):
    if ANDROID:
        _keep_awake_ui(bool(on))


@run_on_ui_thread
def _brightness_ui(v):
    try:
        w = _activity().getWindow()
        lp = w.getAttributes()
        lp.screenBrightness = float(v)       # 0..1, or -1 = system default
        w.setAttributes(lp)
    except Exception:
        log(traceback.format_exc())


def set_brightness(v):
    if ANDROID:
        _brightness_ui(-1.0 if v is None else max(0.01, min(1.0, v)))


def get_brightness():
    """Current window brightness 0..1 (falls back to the system value)."""
    if not ANDROID:
        return 0.5
    try:
        lp = _activity().getWindow().getAttributes()
        b = float(lp.screenBrightness)
        if b >= 0:
            return b
        Settings = autoclass('android.provider.Settings$System')
        v = Settings.getInt(_activity().getContentResolver(), 'screen_brightness', 128)
        return max(0.05, min(1.0, v / 255.0))
    except Exception:
        return 0.5


def _audio():
    Context = autoclass('android.content.Context')
    return _activity().getSystemService(Context.AUDIO_SERVICE)


def get_volume():
    if not ANDROID:
        return 0.5
    try:
        am = _audio()
        mx = am.getStreamMaxVolume(3)
        return am.getStreamVolume(3) / float(mx or 1)
    except Exception:
        return 0.5


def set_volume(v):
    if not ANDROID:
        return
    try:
        am = _audio()
        mx = am.getStreamMaxVolume(3)
        am.setStreamVolume(3, int(round(max(0.0, min(1.0, v)) * mx)), 0)
    except Exception:
        log(traceback.format_exc())


def vibrate(ms=25):
    if not ANDROID:
        return
    try:
        Context = autoclass('android.content.Context')
        vib = _activity().getSystemService(Context.VIBRATOR_SERVICE)
        if vib is not None:
            vib.vibrate(int(ms))
    except Exception:
        pass


def screen_density_scale():
    """Not used for layout (kivy.metrics.dp does that) - handy for debugging."""
    return 1.0
