# -*- coding: utf-8 -*-
"""
core.py - everything that does not need Kivy or Android (so it can be unit-tested):
  * strings / formatting helpers
  * natural sorting (Arabic + English)
  * subtitle parsing (SRT / VTT)
  * Store    : JSON persistence (atomic write + backup)
  * Library  : collections (device albums + custom playlists), ordering, progress
"""
import bisect
import json
import os
import re
import time
import unicodedata
import uuid

APP_TITLE = 'Pro Player'
VIDEO_EXTS = ('.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.3gp',
              '.m4v', '.ts', '.mpg', '.mpeg', '.mts', '.m2ts', '.ogv', '.vob')

SPEEDS = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
QUICK_SPEEDS = [1.0, 1.5, 2.0, 2.5, 3.0]

SORT_MODES = ['manual', 'name', 'duration', 'last_played', 'date', 'size']
SORT_LABELS = {
    'manual': 'ترتيبي اليدوي',
    'name': 'الاسم',
    'duration': 'المدة',
    'last_played': 'آخر تشغيل',
    'date': 'تاريخ الإضافة',
    'size': 'الحجم',
}

DEFAULT_SETTINGS = {
    'resume': True,            # continue from the last position
    'autoplay_next': True,
    'repeat': 'off',           # off | one | all | shuffle
    'speed': 1.0,              # chosen (pinned) speed
    'hold_speed': 2.0,         # speed while the finger is held down
    'seek_step': 10,
    'gestures': True,
    'aspect': 'fit',           # fit | fill | stretch | 16:9 | 4:3
    'keep_awake': True,
    'auto_rotate': True,
    'show_thumbs': True,
    'vibrate': True,
    'sub_size': 22,
    'sub_on': True,
    'videos_sort': {'mode': 'date', 'asc': False},
}


# ---------------------------------------------------------------------------
# formatting
# ---------------------------------------------------------------------------
def fmt_time(sec):
    try:
        sec = int(max(0, float(sec)))
    except (TypeError, ValueError):
        sec = 0
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return '%d:%02d:%02d' % (h, m, s)
    return '%d:%02d' % (m, s)


def fmt_size(n):
    try:
        n = float(n)
    except (TypeError, ValueError):
        return ''
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    if i == 0:
        return '%d %s' % (n, units[i])
    return ('%.1f %s' % (n, units[i])).replace('.0 ', ' ')


def fmt_speed(s):
    s = float(s)
    txt = ('%.2f' % s).rstrip('0').rstrip('.')
    return txt + '×'


def count_videos_label(n):
    """Arabic plural forms for 'video clips' (like the original app)."""
    n = int(n)
    if n == 0:
        return 'لا توجد مقاطع'
    if n == 1:
        return 'مقطع فيديو'
    if n == 2:
        return 'مقطعا فيديو'
    if 3 <= n <= 10:
        return '%d مقاطع فيديو' % n
    return '%d مقطع فيديو' % n


def fmt_ago(ts, now=None):
    if not ts:
        return 'لم يُشغّل بعد'
    now = now or time.time()
    d = max(0, now - ts)
    if d < 60:
        return 'الآن'
    if d < 3600:
        return 'منذ %d دقيقة' % (d // 60)
    if d < 86400:
        return 'منذ %d ساعة' % (d // 3600)
    days = int(d // 86400)
    if days == 1:
        return 'أمس'
    if days < 30:
        return 'منذ %d يوم' % days
    if days < 365:
        return 'منذ %d شهر' % (days // 30)
    return 'منذ %d سنة' % (days // 365)


def atempo_chain(speed):
    """ffmpeg audio filter for a tempo change (each atempo stage is 0.5 .. 2.0)."""
    speed = float(speed)
    if abs(speed - 1.0) < 1e-6:
        return ''
    stages = []
    s = speed
    while s > 2.0:
        stages.append(2.0)
        s /= 2.0
    while s < 0.5:
        stages.append(0.5)
        s /= 0.5
    stages.append(s)
    return ','.join('atempo=%.4f' % x for x in stages)


def setpts_filter(speed):
    speed = float(speed)
    if abs(speed - 1.0) < 1e-6:
        return ''
    return 'setpts=%.6f*PTS' % (1.0 / speed)


# ---------------------------------------------------------------------------
# sorting helpers
# ---------------------------------------------------------------------------
_num_re = re.compile(r'(\d+)')


def _norm_char(c):
    # Arabic normalisation so that  أ إ آ ا  sort together, ى = ي, ة = ه
    m = {'أ': 'ا', 'إ': 'ا', 'آ': 'ا', 'ى': 'ي', 'ة': 'ه', 'ؤ': 'و', 'ئ': 'ي'}
    return m.get(c, c)


def natural_key(text):
    text = unicodedata.normalize('NFKC', str(text or '')).casefold()
    text = ''.join(_norm_char(c) for c in text if not (0x064B <= ord(c) <= 0x065F))
    parts = []
    for p in _num_re.split(text):
        if not p:
            continue
        if p.isdigit():
            try:
                parts.append((0, int(p), ''))
            except ValueError:
                parts.append((1, 0, p))
        else:
            parts.append((1, 0, p))
    return parts


def has_arabic(text):
    for c in str(text):
        o = ord(c)
        if 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0xFB50 <= o <= 0xFEFF:
            return True
    return False


# ---------------------------------------------------------------------------
# subtitles
# ---------------------------------------------------------------------------
_tag_re = re.compile(r'<[^>]+>|\{\\[^}]*\}')
_time_re = re.compile(
    r'(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})\s*-->\s*(?:(\d+):)?(\d{1,2}):(\d{2})[,.](\d{1,3})')


def _ts(h, m, s, ms):
    ms = (ms + '000')[:3]
    return int(h or 0) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def decode_text(data):
    if data.startswith(b'\xef\xbb\xbf'):
        return data[3:].decode('utf-8', 'replace')
    if data.startswith(b'\xff\xfe') or data.startswith(b'\xfe\xff'):
        return data.decode('utf-16', 'replace')
    for enc in ('utf-8', 'cp1256', 'cp1252'):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode('latin-1', 'replace')


def parse_subtitles(text):
    """SRT / WebVTT text -> sorted list of (start, end, text)."""
    cues = []
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    blocks = re.split(r'\n\s*\n', text)
    for b in blocks:
        lines = [l for l in b.split('\n')]
        for i, line in enumerate(lines):
            m = _time_re.search(line)
            if m:
                g = m.groups()
                start = _ts(g[0], g[1], g[2], g[3])
                end = _ts(g[4], g[5], g[6], g[7])
                body = '\n'.join(lines[i + 1:])
                body = _tag_re.sub('', body)
                body = body.replace('&nbsp;', ' ').replace('&amp;', '&') \
                    .replace('&lt;', '<').replace('&gt;', '>')
                body = '\n'.join(x.strip() for x in body.split('\n') if x.strip())
                if body and end >= start:
                    cues.append((start, end, body))
                break
    cues.sort(key=lambda c: c[0])
    return cues


class SubtitleTrack(object):
    def __init__(self, cues, name=''):
        self.cues = cues
        self.name = name
        self.starts = [c[0] for c in cues]
        self.max_len = max([c[1] - c[0] for c in cues] or [0])

    def at(self, t):
        if not self.cues:
            return ''
        i = bisect.bisect_right(self.starts, t) - 1
        lo = bisect.bisect_left(self.starts, t - self.max_len - 0.01)
        out = []
        for k in range(max(lo, 0), i + 1):
            s, e, txt = self.cues[k]
            if s <= t <= e:
                out.append(txt)
        return '\n'.join(out)


def find_subtitle_files(video_path):
    """Sibling .srt/.vtt files whose name starts with the video's name."""
    folder = os.path.dirname(video_path)
    stem = os.path.splitext(os.path.basename(video_path))[0].lower()
    found = []
    try:
        for fn in sorted(os.listdir(folder)):
            low = fn.lower()
            if low.endswith(('.srt', '.vtt')) and low.startswith(stem):
                found.append(os.path.join(folder, fn))
    except OSError:
        pass
    return found


def load_subtitle(path):
    with open(path, 'rb') as f:
        data = f.read(5 * 1024 * 1024)
    cues = parse_subtitles(decode_text(data))
    return SubtitleTrack(cues, os.path.basename(path))


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------
class Store(object):
    def __init__(self, path):
        self.path = path
        self.data = {}
        self._dirty = False
        self.load()

    def _defaults(self):
        return {
            'version': 1,
            'titles': {},
            'progress': {},
            'playlists': {},
            'auto': {},
            'coll_order': [],
            'hidden_colls': [],
            'settings': {},
        }

    def load(self):
        d = None
        for p in (self.path, self.path + '.bak'):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    d = json.load(f)
                if isinstance(d, dict):
                    break
                d = None
            except (OSError, ValueError):
                d = None
        base = self._defaults()
        if d:
            for k, v in d.items():
                base[k] = v
        self.data = base
        for k, v in self._defaults().items():
            if not isinstance(self.data.get(k), type(v)):
                self.data[k] = v

    def mark(self):
        self._dirty = True

    def save(self, force=False):
        if not (self._dirty or force):
            return True
        tmp = self.path + '.tmp'
        try:
            os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
            if os.path.exists(self.path):
                try:
                    os.replace(self.path, self.path + '.bak')
                except OSError:
                    pass
            os.replace(tmp, self.path)
            self._dirty = False
            return True
        except OSError:
            return False

    # settings -------------------------------------------------------------
    def setting(self, key):
        s = self.data['settings']
        if key in s:
            return s[key]
        v = DEFAULT_SETTINGS.get(key)
        if isinstance(v, dict):
            return dict(v)
        return v

    def set_setting(self, key, value):
        self.data['settings'][key] = value
        self.mark()


# ---------------------------------------------------------------------------
# library
# ---------------------------------------------------------------------------
class Collection(object):
    """A playlist-like list: either a device album ('a:<bucket>') or custom ('p:<id>')."""

    def __init__(self, cid, name, kind, keys, path=''):
        self.id = cid
        self.name = name
        self.kind = kind          # 'auto' | 'custom'
        self.keys = keys          # ordered video keys (already filtered)
        self.path = path

    @property
    def count(self):
        return len(self.keys)


class Library(object):
    def __init__(self, store):
        self.store = store
        self.videos = {}      # key -> video dict
        self.buckets = {}     # bucket id -> {'id','name','path','keys':[...]}

    # ---- catalog --------------------------------------------------------
    def set_catalog(self, videos):
        self.videos = {}
        self.buckets = {}
        for v in videos:
            key = v['path']
            v['key'] = key
            v.setdefault('title', os.path.splitext(v.get('name') or os.path.basename(key))[0])
            self.videos[key] = v
            bid = str(v.get('bucket_id') or os.path.dirname(key))
            b = self.buckets.get(bid)
            if b is None:
                b = {'id': bid, 'name': v.get('bucket') or os.path.basename(os.path.dirname(key)) or '?',
                     'path': os.path.dirname(key), 'keys': []}
                self.buckets[bid] = b
            b['keys'].append(key)

    def exists(self, key):
        return key in self.videos

    # ---- titles ---------------------------------------------------------
    def title(self, key):
        t = self.store.data['titles'].get(key)
        if t:
            return t
        v = self.videos.get(key)
        return v['title'] if v else os.path.splitext(os.path.basename(key))[0]

    def rename_video(self, key, title):
        title = (title or '').strip()
        if title and title != self.videos.get(key, {}).get('title'):
            self.store.data['titles'][key] = title
        else:
            self.store.data['titles'].pop(key, None)
        self.store.mark()

    # ---- progress -------------------------------------------------------
    def progress(self, key):
        return self.store.data['progress'].get(key) or {}

    def set_progress(self, key, pos, dur):
        p = self.store.data['progress'].setdefault(key, {})
        p['pos'] = float(pos)
        p['dur'] = float(dur) if dur else p.get('dur', 0)
        p['last'] = time.time()
        self.store.mark()

    def mark_started(self, key):
        p = self.store.data['progress'].setdefault(key, {})
        p['last'] = time.time()
        p['count'] = int(p.get('count', 0)) + 1
        self.store.mark()

    def clear_progress(self, key):
        self.store.data['progress'].pop(key, None)
        self.store.mark()

    def resume_pos(self, key):
        p = self.progress(key)
        pos, dur = p.get('pos', 0), p.get('dur', 0) or self.videos.get(key, {}).get('duration', 0)
        if pos < 5:
            return 0.0
        if dur and pos > dur - 8:
            return 0.0
        return float(pos)

    def watched_fraction(self, key):
        p = self.progress(key)
        dur = p.get('dur') or self.videos.get(key, {}).get('duration') or 0
        if not dur:
            return 0.0
        return max(0.0, min(1.0, p.get('pos', 0) / float(dur)))

    def history(self, limit=100):
        items = [(p.get('last', 0), k) for k, p in self.store.data['progress'].items()
                 if p.get('last') and k in self.videos]
        items.sort(reverse=True)
        return [k for _, k in items[:limit]]

    # ---- sorting --------------------------------------------------------
    def sort_keys(self, keys, mode, asc=True):
        vids = self.videos

        def kf(k):
            v = vids.get(k, {})
            if mode == 'name':
                return natural_key(self.title(k))
            if mode == 'duration':
                return v.get('duration', 0)
            if mode == 'last_played':
                return self.progress(k).get('last', 0)
            if mode == 'date':
                return v.get('added', 0)
            if mode == 'size':
                return v.get('size', 0)
            return 0
        out = sorted(keys, key=kf)
        if not asc:
            out.reverse()
        return out

    def all_videos_sorted(self):
        s = self.store.setting('videos_sort')
        mode = s.get('mode', 'date')
        if mode == 'manual':
            mode = 'date'
        return self.sort_keys(list(self.videos.keys()), mode, s.get('asc', False))

    # ---- collections ----------------------------------------------------
    def _auto_state(self, bid):
        return self.store.data['auto'].setdefault(bid, {})

    def collection_sort(self, cid):
        st = self._state(cid)
        s = st.get('sort') or {}
        return s.get('mode', 'manual'), s.get('asc', True)

    def _state(self, cid):
        if cid.startswith('a:'):
            return self._auto_state(cid[2:])
        return self.store.data['playlists'].get(cid[2:], {})

    def set_collection_sort(self, cid, mode, asc):
        st = self._state(cid)
        st['sort'] = {'mode': mode, 'asc': bool(asc)}
        self.store.mark()

    def _ordered_keys(self, cid):
        """Keys of a collection in its display order (hidden / missing removed)."""
        st = self._state(cid)
        hidden = set(st.get('hidden', []))
        if cid.startswith('a:'):
            b = self.buckets.get(cid[2:])
            base = list(b['keys']) if b else []
            base = [k for k in base if k not in hidden]
            order = st.get('order', [])
        else:
            base = [k for k in st.get('items', []) if k in self.videos]
            order = st.get('order') or st.get('items', [])
        mode, asc = self.collection_sort(cid)
        if mode == 'manual':
            pos = {k: i for i, k in enumerate(order)}
            known = [k for k in base if k in pos]
            known.sort(key=lambda k: pos[k])
            new = [k for k in base if k not in pos]
            new = self.sort_keys(new, 'date', True)   # new ones go to the end
            res = known + new
            return res if asc else list(reversed(res))
        return self.sort_keys(base, mode, asc)

    def items(self, cid):
        return self._ordered_keys(cid)

    def set_manual_order(self, cid, keys):
        st = self._state(cid)
        st['order'] = list(keys)
        st['sort'] = {'mode': 'manual', 'asc': True}
        if cid.startswith('p:'):
            st['items'] = list(keys)
        self.store.mark()

    def move_to_edge(self, cid, sel_keys, top=True):
        cur = self._ordered_keys(cid)
        sel = [k for k in cur if k in set(sel_keys)]
        rest = [k for k in cur if k not in set(sel_keys)]
        self.set_manual_order(cid, (sel + rest) if top else (rest + sel))

    def collections(self):
        res = []
        hidden = set(self.store.data['hidden_colls'])
        for bid, b in self.buckets.items():
            cid = 'a:' + bid
            if cid in hidden:
                continue
            keys = self._ordered_keys(cid)
            if not keys:
                continue
            name = self._auto_state(bid).get('name') or b['name']
            res.append(Collection(cid, name, 'auto', keys, b['path']))
        for pid, p in self.store.data['playlists'].items():
            cid = 'p:' + pid
            res.append(Collection(cid, p.get('name', '?'), 'custom', self._ordered_keys(cid)))
        order = self.store.data['coll_order']
        pos = {c: i for i, c in enumerate(order)}
        known = sorted([c for c in res if c.id in pos], key=lambda c: pos[c.id])
        new = [c for c in res if c.id not in pos]
        new.sort(key=lambda c: natural_key(c.name))
        return known + new

    def folders(self):
        """Real device folders (always auto collections, regardless of hiding)."""
        res = []
        for bid, b in self.buckets.items():
            keys = [k for k in b['keys']]
            if keys:
                res.append(Collection('a:' + bid, b['name'], 'auto', keys, b['path']))
        res.sort(key=lambda c: natural_key(c.name))
        return res

    def collection(self, cid):
        for c in self.collections():
            if c.id == cid:
                return c
        for c in self.folders():
            if c.id == cid:
                return c
        return None

    def set_collections_order(self, ids):
        self.store.data['coll_order'] = list(ids)
        self.store.mark()

    def create_playlist(self, name, keys=()):
        pid = uuid.uuid4().hex[:10]
        seen, items = set(), []
        for k in keys:
            if k not in seen:
                seen.add(k)
                items.append(k)
        self.store.data['playlists'][pid] = {
            'id': pid, 'name': (name or '').strip() or 'قائمة جديدة', 'items': items,
            'order': list(items), 'sort': {'mode': 'manual', 'asc': True}, 'created': time.time()}
        self.store.mark()
        return 'p:' + pid

    def add_to_playlist(self, cid, keys):
        p = self.store.data['playlists'].get(cid[2:])
        if p is None:
            return 0
        n = 0
        for k in keys:
            if k not in p['items']:
                p['items'].append(k)
                p.setdefault('order', []).append(k)
                n += 1
        self.store.mark()
        return n

    def rename_collection(self, cid, name):
        name = (name or '').strip()
        if not name:
            return
        if cid.startswith('p:'):
            self.store.data['playlists'][cid[2:]]['name'] = name
        else:
            self._auto_state(cid[2:])['name'] = name
        self.store.mark()

    def delete_collection(self, cid):
        if cid.startswith('p:'):
            self.store.data['playlists'].pop(cid[2:], None)
        else:
            if cid not in self.store.data['hidden_colls']:
                self.store.data['hidden_colls'].append(cid)
        self.store.mark()

    def restore_hidden(self):
        self.store.data['hidden_colls'] = []
        for st in self.store.data['auto'].values():
            st.pop('hidden', None)
        self.store.mark()

    def remove_from_collection(self, cid, keys):
        """Remove videos from the list only (the files stay on the device)."""
        ks = set(keys)
        if cid.startswith('p:'):
            p = self.store.data['playlists'].get(cid[2:])
            if p:
                p['items'] = [k for k in p['items'] if k not in ks]
                p['order'] = [k for k in p.get('order', []) if k not in ks]
        else:
            st = self._auto_state(cid[2:])
            h = set(st.get('hidden', [])) | ks
            st['hidden'] = sorted(h)
        self.store.mark()

    def forget_videos(self, keys):
        """Called after files were really deleted from the device."""
        for k in keys:
            self.videos.pop(k, None)
            self.store.data['progress'].pop(k, None)
            self.store.data['titles'].pop(k, None)
        for b in self.buckets.values():
            b['keys'] = [k for k in b['keys'] if k not in set(keys)]
        self.store.mark()

    def is_empty_playlist_name_taken(self, name):
        n = (name or '').strip().casefold()
        return any(p.get('name', '').strip().casefold() == n
                   for p in self.store.data['playlists'].values())

    def cover_key(self, keys):
        return keys[0] if keys else None

    def total_duration(self, keys):
        return sum(self.videos.get(k, {}).get('duration', 0) for k in keys)
