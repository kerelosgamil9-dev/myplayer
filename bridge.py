# -*- coding: utf-8 -*-
"""
bridge.py - the only place that talks to Android (through pyjnius).
Every function degrades gracefully on desktop so the app can be tried on a PC
(set PROPLAYER_DIR to a folder that contains videos).
"""
import hashlib
import os
import threading
import time as _time
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


_CRUMB = {'path': None}


_HW_STARTUP = ('hw: open', 'hw: oes', 'hw: surface', 'hw: prepared', 'hw: shader', 'hw: started')


def _init_crumbs_inner(app):
    """Breadcrumb file: survives native crashes, shown on the next start."""
    try:
        p = os.path.join(data_dir(app), 'last_run.txt')
        prev = ''
        if os.path.exists(p):
            with open(p, encoding='utf8', errors='replace') as f:
                prev = f.read().strip()
        _CRUMB['path'] = p
        crumb_reset()
        crumb('start')
        if prev and not prev.endswith(('clean-exit', 'paused', 'resumed')):
            lines = prev.strip().split('\n')
            last = lines[-1]
            why = exit_info()
            if last.startswith(_HW_STARTUP):
                # the hardware decoder died while starting THIS video: that video (only) will
                # use software playback from now on
                vid = ''
                for ln in reversed(lines):
                    if ln.startswith('hw: open '):
                        vid = ln[len('hw: open '):]
                        break
                hw_mark_bad(vid, 'crash at: ' + last)
                return (prev[-600:] + '\n\n>> hardware playback crashed on this video; it will use software playback'
                        + why)
            if last.startswith('hw:'):
                return ''           # died while a video was already playing fine: not the decoder's fault
            if last.startswith(('engine: open', 'player: load', 'engine: get_frame')):
                return prev[-600:] + '\n\n>> switching playback mode to level %d' % bump_engine_level()
            if last in ('start', 'resumed') or last.startswith('player: '):
                return ''
            return prev[-600:]
    except Exception:
        pass
    return ''


def init_crumbs(app):
    """Breadcrumbs of the previous run, plus the Java stack trace when that run died of an uncaught Java
    exception (written by the handler installed with install_crash_logger)."""
    res = _init_crumbs_inner(app)
    try:
        p = _data_file('java_crash.txt')
        if p and os.path.exists(p):
            with open(p, encoding='utf8', errors='replace') as f:
                jc = f.read().strip()
            os.remove(p)
            if jc:
                lines = [ln[:150] for ln in jc.split('\n') if ln.strip()][:28]
                res = (res or 'PREVIOUS RUN CRASHED') + '\n\n>> java crash:\n' + '\n'.join(lines)
    except Exception:
        pass
    return res


_JCRASH = {'handler': None}


def install_crash_logger():
    """Remember the stack trace of an uncaught Java exception (any thread) in java_crash.txt, then let
    Android handle the crash as usual."""
    if not ANDROID:
        return
    try:
        from jnius import PythonJavaClass, java_method
        Thread = autoclass('java.lang.Thread')
        Log = autoclass('android.util.Log')
        prev = Thread.getDefaultUncaughtExceptionHandler()
        path = _data_file('java_crash.txt')
        if not path:
            return

        class _Handler(PythonJavaClass):
            __javainterfaces__ = ['java/lang/Thread$UncaughtExceptionHandler']
            __javacontext__ = 'app'

            @java_method('(Ljava/lang/Thread;Ljava/lang/Throwable;)V')
            def uncaughtException(self, thread, ex):
                try:
                    txt = 'thread: %s\n%s' % (thread.getName(), Log.getStackTraceString(ex))
                    with open(path, 'w', encoding='utf8') as f:
                        f.write(txt)
                except Exception:
                    pass
                try:
                    if prev is not None:
                        prev.uncaughtException(thread, ex)
                except Exception:
                    pass

        _JCRASH['handler'] = _Handler()          # kept alive: Java only holds a weak handle
        Thread.setDefaultUncaughtExceptionHandler(_JCRASH['handler'])
    except Exception:
        log(traceback.format_exc())


def exit_info():
    """Why the previous process died, as Android recorded it (API 30+): the exit reason and, for a native
    crash, the readable strings of the tombstone (library and function names of the backtrace)."""
    if not ANDROID or sdk_int() < 30:
        return ''
    try:
        import re
        Ctx = autoclass('android.content.Context')
        am = _activity().getSystemService(Ctx.ACTIVITY_SERVICE)
        lst = am.getHistoricalProcessExitReasons(None, 0, 1)
        if lst is None or int(lst.size()) == 0:
            return ''
        info = lst.get(0)
        out = ['', '>> android exit record: reason=%s status=%s' % (info.getReason(), info.getStatus()),
               'desc: %s' % info.getDescription()]
        stream = info.getTraceInputStream()
        if stream is not None:
            Scanner = autoclass('java.util.Scanner')
            sc = Scanner(stream, 'ISO-8859-1')
            sc.useDelimiter('\\A')
            txt = str(sc.next()) if sc.hasNext() else ''
            seen = []
            for m in re.findall(r'[\x20-\x7e]{6,}', txt):
                if m not in seen and re.search(r'/|::|\.so|SIG|abort|Abort|Fatal|fault|signal', m):
                    seen.append(m)
            out.append('trace (%d bytes):' % len(txt))
            out.extend(x[:110] for x in seen[:45])
        return '\n'.join(out)
    except Exception:
        return '\n>> exit record unavailable: %s' % traceback.format_exc().strip().split('\n')[-1]


def _level_path():
    p = _CRUMB.get('path')
    return os.path.join(os.path.dirname(p), 'engine_mode.txt') if p else None


def engine_level():
    """Android: 2 = video by ffpyplayer + audio by Android MediaPlayer, 3 = same with
    python threads. (ffpyplayer's own audio crashes on some devices.) PC: 0."""
    if not ANDROID:
        return 0
    p = _level_path()
    try:
        with open(p) as f:
            return 3 if int(f.read().strip() or 2) == 3 else 2
    except Exception:
        return 2


def bump_engine_level():
    """Previous run died while opening a video: try the other mode."""
    p = _level_path()
    if not p or not ANDROID:
        return engine_level()
    n = 2 if engine_level() == 3 else 3
    try:
        with open(p, 'w') as f:
            f.write(str(n))
    except Exception:
        pass
    return n


def _data_file(name):
    p = _CRUMB.get('path')
    return os.path.join(os.path.dirname(p), name) if p else None


def _hw_flag():
    return _data_file('hw_disabled.txt')


def hw_enabled():
    """Hardware playback on (Android only) unless it was switched off for the whole device."""
    if not ANDROID:
        return False
    p = _hw_flag()
    return not (p and os.path.exists(p))


def disable_hw(reason=''):
    p = _hw_flag()
    if p:
        try:
            with open(p, 'w') as f:
                f.write(reason or 'disabled')
        except Exception:
            pass


def _bad_list():
    p = _data_file('hw_bad.txt')
    try:
        with open(p, encoding='utf8') as f:
            return [ln.rstrip('\n') for ln in f if ln.strip()]
    except Exception:
        return []


def _save_bad(lst):
    p = _data_file('hw_bad.txt')
    if not p:
        return
    try:
        if lst:
            with open(p, 'w', encoding='utf8') as f:
                f.write('\n'.join(lst) + '\n')
        elif os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def hw_is_bad(path):
    """True when hardware playback failed on this particular video before."""
    return bool(path) and path in _bad_list()


def hw_bad_count():
    return len(_bad_list())


def hw_mark_bad(path, reason=''):
    """Remember a video the hardware decoder cannot play; switch hardware off for the whole
    device only after three different videos failed."""
    lst = _bad_list()
    if path and path not in lst:
        lst.append(path)
        _save_bad(lst)
    if len(lst) >= 3:
        disable_hw(reason)


def hw_ok(path):
    """A video played fine with hardware decoding: forget an earlier failure."""
    p = _data_file('hw_bad.txt')
    if not p or not os.path.exists(p):
        return
    lst = _bad_list()
    if path in lst:
        lst.remove(path)
        _save_bad(lst)


def hw_reset():
    """Settings > turn hardware playback on again."""
    for name in ('hw_disabled.txt', 'hw_bad.txt'):
        p = _data_file(name)
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def crumb(msg):
    p = _CRUMB.get('path')
    if not p:
        return
    try:
        with open(p, 'a', encoding='utf8') as f:
            f.write(msg + '\n')
            f.flush()
            os.fsync(f.fileno())
    except Exception:
        pass


def crumb_reset():
    p = _CRUMB.get('path')
    if p:
        try:
            open(p, 'w').close()
        except Exception:
            pass


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
    """Folder of the thumbnails.  The path is remembered: the list asks for it for every row that
    scrolls into view, and it must not cost two system calls each time."""
    d = getattr(app, '_thumb_dir', None)
    if d:
        return d
    d = os.path.join(data_dir(app), 'thumbs')
    os.makedirs(d, exist_ok=True)
    try:
        app._thumb_dir = d
    except Exception:
        pass
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
    sig = '%s|%s|%s|v2' % (video['path'], video.get('size', 0), video.get('modified', 0))   # v2: no black frames
    h = hashlib.md5(sig.encode('utf-8', 'replace')).hexdigest()
    return os.path.join(cache_dir(app), h + '.jpg')


LAST_THUMB_ERROR = ['']


def _save_bitmap(bmp, out):
    Bitmap = autoclass('android.graphics.Bitmap')
    CF = autoclass('android.graphics.Bitmap$CompressFormat')
    FOS = autoclass('java.io.FileOutputStream')
    w, h = bmp.getWidth(), bmp.getHeight()
    if w <= 0 or h <= 0:
        return False
    tw = 480
    if w > tw:
        bmp = Bitmap.createScaledBitmap(bmp, tw, max(1, int(h * tw / float(w))), True)
    fos = FOS(out + '.part')
    try:
        ok = bmp.compress(CF.JPEG, 82, fos)
        fos.flush()
    finally:
        fos.close()
    if ok:
        os.replace(out + '.part', out)
    return bool(ok)


def _brightness(bmp):
    """Average brightness (0-255) of a handful of pixels of a bitmap; -1 when it cannot be read."""
    try:
        w, h = bmp.getWidth(), bmp.getHeight()
        if w < 2 or h < 2:
            return -1.0
        tot, n = 0.0, 0
        for iy in range(1, 6):
            for ix in range(1, 8):
                p = int(bmp.getPixel(w * ix // 8, h * iy // 6))
                tot += 0.299 * ((p >> 16) & 255) + 0.587 * ((p >> 8) & 255) + 0.114 * (p & 255)
                n += 1
        return tot / n
    except Exception:
        return -1.0


DARK_LIMIT = 14.0            # a frame darker than this is a black screen, not a picture


def _thumb_size(mmr):
    """(w, h) of a 480-wide thumbnail with the video's own proportions (turned videos included), or None."""
    try:
        w = int(mmr.extractMetadata(18))
        h = int(mmr.extractMetadata(19))
        rot = mmr.extractMetadata(24)
        if rot is not None and int(rot) in (90, 270):
            w, h = h, w
        if w > 0 and h > 0:
            tw = min(480, w)
            return tw, max(1, int(h * tw / float(w)))
    except Exception:
        pass
    return None


def _frame(mmr, us, size):
    """A frame already scaled to thumbnail size (Android 8.1+): much less memory and time than a
    full-size picture that is scaled afterwards."""
    if size and sdk_int() >= 27:
        try:
            return mmr.getScaledFrameAtTime(us, 2, size[0], size[1])
        except Exception:
            pass
    return mmr.getFrameAtTime(us, 2)


def _make_thumb_android(video, out):
    """Try several ways to get a frame; returns True when a JPEG was written.  A black frame (the
    first seconds of many episodes) is never accepted while a brighter one can be found."""
    path = video['path']
    duration = video.get('duration', 0)
    errors = []
    best = [None, -2.0]                      # [bitmap, brightness] of the best frame seen so far

    def consider(bmp):
        """True when the frame is good enough to stop looking."""
        if bmp is None:
            return False
        b = _brightness(bmp)
        if b >= DARK_LIMIT or b < 0:
            return _save_bitmap(bmp, out)
        if b > best[1]:
            best[0], best[1] = bmp, b
        return False
    # 1) system thumbnail through the content uri (Android 10+)
    try:
        if video.get('id') and sdk_int() >= 29:
            ContentUris = autoclass('android.content.ContentUris')
            MS = autoclass('android.provider.MediaStore$Video$Media')
            Size = autoclass('android.util.Size')
            uri = ContentUris.withAppendedId(MS.EXTERNAL_CONTENT_URI, int(video['id']))
            if consider(_activity().getContentResolver().loadThumbnail(uri, Size(480, 270), None)):
                return True
    except Exception as e:
        errors.append('loadThumbnail: %s' % e)
    # 2) frame grabber: several moments, the first bright one wins
    MMR = autoclass('android.media.MediaMetadataRetriever')
    mmr = MMR()
    try:
        mmr.setDataSource(path)
        size = _thumb_size(mmr)
        if duration:
            times = [min(max(duration * f, 1.0), duration * 0.95) for f in (0.1, 0.25, 0.4, 0.55)]
        else:
            times = [1.0, 5.0, 15.0, 40.0]
        for t in times:
            try:
                if consider(_frame(mmr, int(t * 1000000), size)):
                    return True
            except Exception as e:
                errors.append('frame %.0f: %s' % (t, e))
        if best[0] is None:
            if consider(mmr.getFrameAtTime(-1)):
                return True
        if best[0] is not None and _save_bitmap(best[0], out):      # every frame was dark: keep the best
            return True
        errors.append('no frame')
    except Exception as e:
        errors.append('mmr: %s' % e)
    finally:
        try:
            mmr.release()
        except Exception:
            pass
    if best[0] is not None and not os.path.exists(out):
        try:
            if _save_bitmap(best[0], out):
                return True
        except Exception:
            pass
    LAST_THUMB_ERROR[0] = '; '.join(errors)[:300]
    return False


def _thread_priority(p):
    """Android nice value of the CALLING thread (0 = normal, 9 = a lot less CPU than the screen, 19 =
    background).  Making thumbnails is heavy video decoding; it must never steal the CPU from drawing."""
    if not ANDROID:
        return
    try:
        autoclass('android.os.Process').setThreadPriority(int(p))
    except Exception:
        pass


class ThumbService(object):
    """Generates JPEG thumbnails in background threads.

    What the person is looking at comes first: a row that has just appeared goes to the FRONT of the
    queue (newest first), and rows that were scrolled past long ago are dropped from it - they ask
    again if they come back.  Everything else (``warm``) is made in the background, only when nothing
    on screen is waiting."""
    WORKERS = 2
    MAX_URGENT = 24

    def __init__(self, app):
        self.app = app
        self.lock = threading.Lock()
        self.queue = []                  # urgent: the last entry is made first
        self.bg = []                     # background: made in order, when `queue` is empty
        self.pending = set()
        self.failed = set()
        self.callbacks = {}
        self.workers = 0
        self.bg_busy = False

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
            if key in self.pending:
                self._bump(key)
            else:
                self.pending.add(key)
                self.queue.append((video, out))
            while len(self.queue) > self.MAX_URGENT:          # scrolled past: they will ask again
                v, o = self.queue.pop(0)
                self.pending.discard(v['path'])
                self.callbacks.pop(v['path'], None)
            self._spawn()
        return None

    def _bump(self, key):
        """Already waiting: make it the next one (it is on screen again)."""
        for lst in (self.queue, self.bg):
            for i, (v, o) in enumerate(lst):
                if v['path'] == key:
                    item = lst.pop(i)
                    self.queue.append(item)
                    return

    def warm(self, videos):
        """Queue every missing thumbnail for the background (call once the library is known)."""
        if not ANDROID:
            return
        with self.lock:
            for v in videos:
                key = v['path']
                if key in self.pending or key in self.failed:
                    continue
                self.pending.add(key)
                self.bg.append((v, thumb_path(self.app, v)))
            self._spawn()

    def _spawn(self):
        """(lock held) start workers while there is work."""
        n = len(self.queue) + len(self.bg)
        while self.workers < min(self.WORKERS, max(1, n)) and n:
            self.workers += 1
            threading.Thread(target=self._work, daemon=True).start()
            n -= 1

    def prioritise(self, key):
        with self.lock:
            self._bump(key)

    def _next(self):
        """(item, is_background) - or (None, False) when this worker has nothing to do.  Only ONE worker
        at a time makes background thumbnails, so warming up never takes the whole phone."""
        with self.lock:
            if self.queue:
                return self.queue.pop(), False
            if self.bg and not self.bg_busy:
                self.bg_busy = True
                return self.bg.pop(0), True
            self.workers -= 1
            return None, False

    def _work(self):
        prio = None
        while True:
            item, is_bg = self._next()
            if item is None:
                return
            want = 19 if is_bg else 9
            if want != prio:
                prio = want
                _thread_priority(want)
            video, out = item
            key = video['path']
            ok = os.path.exists(out)
            if not ok:
                try:
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    ok = _make_thumb_android(video, out)
                except Exception:
                    LAST_THUMB_ERROR[0] = traceback.format_exc()[-300:]
                    log('thumb failed', key)
            with self.lock:
                if is_bg:
                    self.bg_busy = False
                self.pending.discard(key)
                cbs = self.callbacks.pop(key, [])
                if not ok:
                    self.failed.add(key)
            if ok:
                for cb in cbs:
                    Clock.schedule_once(lambda dt, cb=cb, out=out: cb(out), 0)
            if is_bg:
                _time.sleep(0.03)             # breathe: the picture on screen matters more

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
# sharing
# ---------------------------------------------------------------------------
LAST_SHARE_ERROR = ['']


def share_videos(videos):
    """Open the system share sheet with the given videos.  Returns how many were handed over
    (0 when sharing is not possible); LAST_SHARE_ERROR[0] then holds the reason."""
    LAST_SHARE_ERROR[0] = ''
    vids = [v for v in videos if v.get('id')]
    if not ANDROID:
        LAST_SHARE_ERROR[0] = 'غير متاح خارج الأندرويد'
        return 0
    if not vids:
        LAST_SHARE_ERROR[0] = 'الفيديو بلا رابط نظام'
        return 0
    errors = []
    for variant in ('cast', 'plain', 'direct'):         # several ways: pyjnius is picky about overloads
        try:
            _share_now(vids, variant)
            return len(vids)
        except Exception as e:
            errors.append('%s: %s' % (variant, str(e)[:90]))
            log(traceback.format_exc())
    LAST_SHARE_ERROR[0] = ' | '.join(errors)[:260]
    return 0


def _share_now(vids, variant):
    from jnius import cast
    Intent = autoclass('android.content.Intent')
    ContentUris = autoclass('android.content.ContentUris')
    MS = autoclass('android.provider.MediaStore$Video$Media')
    uris = [ContentUris.withAppendedId(MS.EXTERNAL_CONTENT_URI, int(v['id'])) for v in vids]

    def parcel(u):
        return cast('android.os.Parcelable', u) if variant != 'plain' else u
    if len(uris) == 1:
        it = Intent(Intent.ACTION_SEND)
        it.setType('video/*')
        it.putExtra(Intent.EXTRA_STREAM, parcel(uris[0]))
    else:
        ArrayList = autoclass('java.util.ArrayList')
        lst = ArrayList()
        for u in uris:
            lst.add(parcel(u))
        it = Intent(Intent.ACTION_SEND_MULTIPLE)
        it.setType('video/*')
        it.putParcelableArrayListExtra(Intent.EXTRA_STREAM, lst)
    it.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    if variant == 'direct':
        _activity().startActivity(it)
        return
    String = autoclass('java.lang.String')
    title = cast('java.lang.CharSequence', String('مشاركة'))
    _activity().startActivity(Intent.createChooser(it, title))


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


_INSETS = {'on': False, 'immersive': False, 'pad': None, 'view': None, 'decor': None,
           'mask': 0, 'ime': 0, 'ev': None}


@run_on_ui_thread
def _setup_insets_ui(bg_color):
    """One-off: dark window background behind the bars and light icons on them."""
    try:
        win = _activity().getWindow()
        try:
            win.getDecorView().setBackgroundColor(int(bg_color))
        except Exception:
            log(traceback.format_exc())
        try:
            ctl = win.getInsetsController()
            WIC = autoclass('android.view.WindowInsetsController')
            ctl.setSystemBarsAppearance(0, WIC.APPEARANCE_LIGHT_STATUS_BARS |
                                        WIC.APPEARANCE_LIGHT_NAVIGATION_BARS)
        except Exception:
            log(traceback.format_exc())
    except Exception:
        log(traceback.format_exc())


@run_on_ui_thread
def _set_padding_ui(left, top, right, bottom):
    try:
        _INSETS['view'].setPadding(int(left), int(top), int(right), int(bottom))
    except Exception:
        log(traceback.format_exc())


def refresh_insets():
    """Pad the activity's content view by the system bars (not the keyboard).  Android 15+ draws apps that
    target API 35 edge to edge, under the bars.  The insets are READ here, on the Python thread, and only
    the padding itself is set on the UI thread.  (An OnApplyWindowInsetsListener written in Python ran on
    the UI thread, and when it returned null the system crashed the whole app with a NullPointerException.)"""
    if not _INSETS['on']:
        return
    try:
        if _INSETS['immersive']:                     # full-screen video: no padding at all
            pad = (0, 0, 0, 0)
        else:
            wi = _INSETS['decor'].getRootWindowInsets()
            if wi is None:
                return
            bars = wi.getInsets(_INSETS['mask'])
            # The keyboard is NOT added to the padding: it used to shrink the whole window while it was
            # open and, when it closed, the window grew back a moment AFTER the layout did (header and
            # tabs cut off, black strip at the bottom).  Dialogs sit at the top, clear of the keyboard.
            pad = (int(bars.left), int(bars.top), int(bars.right), int(bars.bottom))
        if pad != _INSETS['pad']:
            _INSETS['pad'] = pad
            _set_padding_ui(*pad)
    except Exception:
        log(traceback.format_exc())


def target_sdk():
    """The targetSdkVersion this installed app was built for (0 when it is not running on Android)."""
    if not ANDROID:
        return 0
    try:
        return int(_activity().getApplicationInfo().targetSdkVersion)
    except Exception:
        return 0


def setup_window_insets(bg_color=0xFF000000):
    """Call once at start-up.  Android only forces edge-to-edge drawing for apps that TARGET API 35+ and run
    on Android 15+; for an app built for an older target the system already keeps content inside the
    bars, so padding it again would draw black frames around everything."""
    if not (ANDROID and sdk_int() >= 35 and target_sdk() >= 35):
        return
    c = int(bg_color) & 0xFFFFFFFF
    if c > 0x7FFFFFFF:                               # Java ints are signed
        c -= 0x100000000
    try:
        T = autoclass('android.view.WindowInsets$Type')      # every class is resolved on this thread
        act = _activity()
        _INSETS['mask'] = int(T.systemBars() | T.displayCutout())
        _INSETS['ime'] = int(T.ime())
        _INSETS['view'] = act.findViewById(16908290)         # android.R.id.content
        _INSETS['decor'] = act.getWindow().getDecorView()
        _INSETS['on'] = True
    except Exception:
        log(traceback.format_exc())
        return
    _setup_insets_ui(c)
    if _INSETS['ev'] is None:
        _INSETS['ev'] = Clock.schedule_interval(lambda dt: refresh_insets(), 0.25)
    refresh_insets()


@run_on_ui_thread
def _immersive_ui(on):
    try:
        act = _activity()
        win = act.getWindow()
        if sdk_int() >= 30:
            try:
                T = autoclass('android.view.WindowInsets$Type')
                WIC = autoclass('android.view.WindowInsetsController')
                ctl = win.getInsetsController()
                if on:
                    ctl.setSystemBarsBehavior(WIC.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE)
                    ctl.hide(T.systemBars())
                else:
                    ctl.show(T.systemBars())
                return
            except Exception:
                log(traceback.format_exc())
        View = autoclass('android.view.View')
        decor = win.getDecorView()
        if on:
            flags = (View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION |
                     View.SYSTEM_UI_FLAG_FULLSCREEN | View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY |
                     View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN)
        else:
            flags = View.SYSTEM_UI_FLAG_VISIBLE
        decor.setSystemUiVisibility(flags)
    except Exception:
        log(traceback.format_exc())


_CUT = {'t': 0.0, 'v': (0, 0, 0, 0)}


def cutout_insets():
    """(left, top, right, bottom) in pixels taken by the camera hole / notch.  The full-screen player draws
    right under it, so its bars and buttons have to stay clear of this area.  Cached for half a second."""
    if not ANDROID:
        return (0, 0, 0, 0)
    now = _time.time()
    if now - _CUT['t'] < 0.5:
        return _CUT['v']
    _CUT['t'] = now
    try:
        if sdk_int() >= 28:
            decor = _INSETS['decor'] or _activity().getWindow().getDecorView()
            wi = decor.getRootWindowInsets()
            if wi is not None:
                dc = wi.getDisplayCutout()
                _CUT['v'] = (0, 0, 0, 0) if dc is None else (
                    int(dc.getSafeInsetLeft()), int(dc.getSafeInsetTop()),
                    int(dc.getSafeInsetRight()), int(dc.getSafeInsetBottom()))
    except Exception:
        log(traceback.format_exc())
    return _CUT['v']


def set_immersive(on):
    if ANDROID:
        _INSETS['immersive'] = bool(on)
        refresh_insets()
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



# ---------------------------------------------------------------------------
# audio through Android's own MediaPlayer (hardware decoder, speed with pitch kept)
# ---------------------------------------------------------------------------
class NativeAudio(object):
    def __init__(self):
        self.mp = None
        self.paused = False
        self.speed = 1.0
        self.error = ''

    @property
    def ok(self):
        return self.mp is not None

    def open(self, path, start=0.0, speed=1.0, volume=1.0, paused=False):
        self.release()
        self.paused = bool(paused)
        self.speed = float(speed)
        try:
            MP = autoclass('android.media.MediaPlayer')
            mp = MP()
            mp.setDataSource(path)
            mp.prepare()
            self.mp = mp
            if start > 0.3:
                self._seek_ms(int(start * 1000))
            mp.setVolume(float(volume), float(volume))
            self._apply_speed()
            if not self.paused:
                mp.start()
            crumb('audio: started')
            return True
        except Exception as e:
            self.error = str(e)
            crumb('audio: failed %s' % e)
            self.release()
            return False

    def _apply_speed(self):
        if self.mp is None:
            return
        if self.paused:
            return                      # setPlaybackParams() would START a paused player: apply on resume
        try:
            PP = autoclass('android.media.PlaybackParams')
            pp = PP()
            pp.setSpeed(float(self.speed))
            pp.setPitch(1.0)
            self.mp.setPlaybackParams(pp)
            if self.paused and self.mp.isPlaying():
                self.mp.pause()
        except Exception as e:
            crumb('audio: speed failed %s' % e)

    def _seek_ms(self, ms):
        try:
            self.mp.seekTo(int(ms), 3)          # SEEK_CLOSEST (API 26+)
        except Exception:
            try:
                self.mp.seekTo(int(ms))
            except Exception:
                pass

    def set_speed(self, s):
        self.speed = float(s)
        self._apply_speed()

    def set_pause(self, paused):
        self.paused = bool(paused)
        if self.mp is None:
            return
        try:
            if self.paused:
                self.mp.pause()
            else:
                self._apply_speed()
                self.mp.start()
        except Exception:
            pass

    def seek(self, t):
        if self.mp is not None:
            self._seek_ms(int(max(0.0, t) * 1000))

    def position(self):
        if self.mp is None:
            return None
        try:
            return self.mp.getCurrentPosition() / 1000.0
        except Exception:
            return None

    def set_volume(self, v):
        if self.mp is not None:
            try:
                self.mp.setVolume(float(v), float(v))
            except Exception:
                pass

    def cycle_track(self):
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
        except Exception as e:
            crumb('audio: track failed %s' % e)
            return False

    def pause_now(self):
        self.set_pause(True)

    def release(self):
        mp, self.mp = self.mp, None
        if mp is not None:
            try:
                mp.release()
            except Exception:
                pass
