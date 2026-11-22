# -*- coding: utf-8 -*-
"""
database.py - local SQLite storage for Lingora.

Everything the app remembers lives here:
  * settings              (key / value)
  * folders + items       (the user's own words and sentences)
  * bank_progress         (mastery of the built-in vocabulary)
  * level_progress        (test results of the built-in levels)
  * study_days            (for the daily streak and the daily goal)
  * backup export / import (JSON)

All "learnable things" are exposed to the rest of the app as plain dicts
("unified items") so the games do not care where a word comes from:

    {'uid': 'u:12' | 'b:w:3:5' | 'b:s:3:2',
     'src': 'user' | 'bank',
     'kind': 'word' | 'sentence',
     'en': ..., 'ar': ..., 'ex': ..., 'ex_ar': ...,
     'level': 0 for user items, 1..8 for bank items,
     'mastered': 0/1, ...}
"""

import json
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

import data_bank

APP_NAME = 'Lingora'
BACKUP_VERSION = 1
MASTER_STREAK = 3        # correct answers in a row needed to master an item
PASS_SCORE = 60          # % needed to pass a level test

DEFAULT_SETTINGS = {
    'theme': 'auto',            # auto | dark | light
    'lang': 'ar',               # ar | en
    'sound': '1',
    'show_dividers': '1',
    'divider_style': 'solid',   # solid | dashed | dotted | fade | ornament
    'divider_width': '1',       # 1 | 2 | 3
    'divider_color': 'neutral',  # neutral | accent
    'daily_goal': '20',
    'round_size': '10',
    'unlock_all': '0',
    'auto_speak': '1',
    'kb_mode': 'auto',
}


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _today():
    return date.today().isoformat()


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    color      INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id   INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL DEFAULT 'word',
    en          TEXT NOT NULL,
    ar          TEXT NOT NULL DEFAULT '',
    example     TEXT DEFAULT '',
    example_ar  TEXT DEFAULT '',
    hl_main     INTEGER DEFAULT 0,
    hl_example  INTEGER DEFAULT 0,
    mastered    INTEGER DEFAULT 0,
    streak      INTEGER DEFAULT 0,
    correct     INTEGER DEFAULT 0,
    wrong       INTEGER DEFAULT 0,
    last_seen   TEXT,
    created_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_items_folder ON items(folder_id);

CREATE TABLE IF NOT EXISTS bank_progress (
    key       TEXT PRIMARY KEY,
    kind      TEXT,
    level     INTEGER,
    mastered  INTEGER DEFAULT 0,
    streak    INTEGER DEFAULT 0,
    correct   INTEGER DEFAULT 0,
    wrong     INTEGER DEFAULT 0,
    last_seen TEXT
);

CREATE TABLE IF NOT EXISTS level_progress (
    level       INTEGER PRIMARY KEY,
    best_score  INTEGER DEFAULT 0,
    attempts    INTEGER DEFAULT 0,
    passed      INTEGER DEFAULT 0,
    last_played TEXT
);

CREATE TABLE IF NOT EXISTS study_days (
    day     TEXT PRIMARY KEY,
    answers INTEGER DEFAULT 0,
    correct INTEGER DEFAULT 0
);
"""


class Database:
    """Thin wrapper around sqlite3 with all the app queries."""

    def __init__(self, path):
        self.path = path
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self._settings_cache = {}
        self._load_settings()

    # ------------------------------------------------------------------ misc
    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except sqlite3.Error:
            pass

    def _q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def _one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def _x(self, sql, args=()):
        cur = self.conn.execute(sql, args)
        self.conn.commit()
        return cur

    # -------------------------------------------------------------- settings
    def _load_settings(self):
        self._settings_cache = dict(DEFAULT_SETTINGS)
        for r in self._q('SELECT key, value FROM settings'):
            self._settings_cache[r['key']] = r['value']

    def get(self, key, default=None):
        if key in self._settings_cache:
            return self._settings_cache[key]
        return DEFAULT_SETTINGS.get(key, default)

    def get_int(self, key, default=0):
        try:
            return int(self.get(key, default))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key):
        return str(self.get(key, '0')) in ('1', 'true', 'True')

    def set(self, key, value):
        value = str(value)
        self._settings_cache[key] = value
        self._x('INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)',
                (key, value))

    # --------------------------------------------------------------- folders
    def add_folder(self, name, color=0):
        name = (name or '').strip()
        if not name:
            raise ValueError('empty name')
        order = self._one('SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM folders')['n']
        cur = self._x('INSERT INTO folders(name, color, sort_order, created_at) '
                      'VALUES (?, ?, ?, ?)', (name, int(color), order, _now()))
        return cur.lastrowid

    def update_folder(self, folder_id, name, color):
        name = (name or '').strip()
        if not name:
            raise ValueError('empty name')
        self._x('UPDATE folders SET name = ?, color = ? WHERE id = ?',
                (name, int(color), folder_id))

    def delete_folder(self, folder_id):
        self._x('PRAGMA foreign_keys = ON')
        self._x('DELETE FROM items WHERE folder_id = ?', (folder_id,))
        self._x('DELETE FROM folders WHERE id = ?', (folder_id,))

    def get_folder(self, folder_id):
        r = self._one('SELECT * FROM folders WHERE id = ?', (folder_id,))
        return dict(r) if r else None

    def list_folders(self):
        """All folders with counters: words, sentences, mastered."""
        rows = self._q(
            "SELECT f.id, f.name, f.color, f.sort_order, "
            "  COALESCE(SUM(CASE WHEN i.kind = 'word' THEN 1 ELSE 0 END), 0) AS words, "
            "  COALESCE(SUM(CASE WHEN i.kind = 'sentence' THEN 1 ELSE 0 END), 0) AS sentences, "
            "  COALESCE(SUM(i.mastered), 0) AS mastered "
            "FROM folders f LEFT JOIN items i ON i.folder_id = f.id "
            "GROUP BY f.id ORDER BY f.sort_order, f.id")
        return [dict(r) for r in rows]

    # ----------------------------------------------------------------- items
    def add_item(self, folder_id, kind, en, ar, example='', example_ar=''):
        en = (en or '').strip()
        ar = (ar or '').strip()
        if not en or not ar:
            raise ValueError('empty text')
        if kind not in ('word', 'sentence'):
            kind = 'word'
        cur = self._x(
            'INSERT INTO items(folder_id, kind, en, ar, example, example_ar, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            (folder_id, kind, en, ar, (example or '').strip(),
             (example_ar or '').strip(), _now()))
        return cur.lastrowid

    def update_item(self, item_id, kind, en, ar, example='', example_ar=''):
        en = (en or '').strip()
        ar = (ar or '').strip()
        if not en or not ar:
            raise ValueError('empty text')
        self._x('UPDATE items SET kind = ?, en = ?, ar = ?, example = ?, example_ar = ? '
                'WHERE id = ?', (kind, en, ar, (example or '').strip(),
                                 (example_ar or '').strip(), item_id))

    def delete_item(self, item_id):
        self._x('DELETE FROM items WHERE id = ?', (item_id,))

    def get_item(self, item_id):
        r = self._one('SELECT * FROM items WHERE id = ?', (item_id,))
        return self._user_item(r) if r else None

    def get_items(self, folder_id, kind=None, search=None, mastered_only=False):
        sql = 'SELECT * FROM items WHERE folder_id = ?'
        args = [folder_id]
        if kind in ('word', 'sentence'):
            sql += ' AND kind = ?'
            args.append(kind)
        if mastered_only:
            sql += ' AND mastered = 1'
        if search:
            sql += ' AND (LOWER(en) LIKE ? OR ar LIKE ? OR LOWER(example) LIKE ?)'
            like = '%' + search.strip().lower() + '%'
            args += [like, '%' + search.strip() + '%', like]
        sql += ' ORDER BY id DESC'
        return [self._user_item(r) for r in self._q(sql, args)]

    def get_all_user_items(self, folder_id=None, kinds=('word', 'sentence')):
        sql = 'SELECT * FROM items WHERE kind IN (%s)' % ','.join('?' * len(kinds))
        args = list(kinds)
        if folder_id:
            sql += ' AND folder_id = ?'
            args.append(folder_id)
        return [self._user_item(r) for r in self._q(sql, args)]

    def set_highlight(self, item_id, field, color_index):
        col = 'hl_main' if field == 'main' else 'hl_example'
        self._x('UPDATE items SET %s = ? WHERE id = ?' % col, (int(color_index), item_id))

    def set_mastered(self, item_id, value):
        streak = MASTER_STREAK if value else 0
        self._x('UPDATE items SET mastered = ?, streak = ? WHERE id = ?',
                (1 if value else 0, streak, item_id))

    def reset_folder_progress(self, folder_id):
        self._x('UPDATE items SET mastered = 0, streak = 0, correct = 0, wrong = 0 '
                'WHERE folder_id = ?', (folder_id,))

    @staticmethod
    def _user_item(r):
        return {
            'uid': 'u:%d' % r['id'], 'src': 'user', 'id': r['id'],
            'folder_id': r['folder_id'], 'kind': r['kind'],
            'en': r['en'], 'ar': r['ar'],
            'ex': r['example'] or '', 'ex_ar': r['example_ar'] or '',
            'level': 0, 'hl_main': r['hl_main'] or 0,
            'hl_example': r['hl_example'] or 0,
            'mastered': r['mastered'] or 0, 'streak': r['streak'] or 0,
            'correct': r['correct'] or 0, 'wrong': r['wrong'] or 0,
        }

    # ------------------------------------------------------------ bank items
    @staticmethod
    def bank_uid(kind, level, index):
        return 'b:%s:%d:%d' % ('w' if kind == 'word' else 's', level, index)

    def _bank_progress_map(self, level=None):
        if level is None:
            rows = self._q('SELECT * FROM bank_progress')
        else:
            rows = self._q('SELECT * FROM bank_progress WHERE level = ?', (level,))
        return {r['key']: r for r in rows}

    def bank_items(self, levels, kinds=('word', 'sentence')):
        """Unified items of the built-in vocabulary for the given levels."""
        out = []
        for lv in levels:
            data = data_bank.get_level(lv)
            if not data:
                continue
            prog = self._bank_progress_map(lv)
            if 'word' in kinds:
                for i, w in enumerate(data['words']):
                    out.append(self._bank_item('word', lv, i, w, prog))
            if 'sentence' in kinds:
                for i, s in enumerate(data['sentences']):
                    out.append(self._bank_item('sentence', lv, i, s, prog))
        return out

    def _bank_item(self, kind, lv, idx, raw, prog):
        uid = self.bank_uid(kind, lv, idx)
        p = prog.get(uid)
        if kind == 'word':
            en, ar, ex, ex_ar = raw
        else:
            en, ar = raw
            ex = ex_ar = ''
        return {
            'uid': uid, 'src': 'bank', 'id': 0, 'folder_id': 0, 'kind': kind,
            'en': en, 'ar': ar, 'ex': ex, 'ex_ar': ex_ar, 'level': lv,
            'hl_main': 0, 'hl_example': 0,
            'mastered': p['mastered'] if p else 0,
            'streak': p['streak'] if p else 0,
            'correct': p['correct'] if p else 0,
            'wrong': p['wrong'] if p else 0,
        }

    def bank_item_by_uid(self, uid):
        try:
            _, k, lv, idx = uid.split(':')
            lv, idx = int(lv), int(idx)
            data = data_bank.get_level(lv)
            kind = 'word' if k == 'w' else 'sentence'
            raw = data['words'][idx] if kind == 'word' else data['sentences'][idx]
        except (ValueError, IndexError, TypeError, AttributeError):
            return None
        return self._bank_item(kind, lv, idx, raw, self._bank_progress_map(lv))

    def level_mastery(self, level):
        """(mastered, total) for the words + sentences of one level."""
        data = data_bank.get_level(level)
        total = len(data['words']) + len(data['sentences'])
        r = self._one('SELECT COALESCE(SUM(mastered), 0) AS m FROM bank_progress '
                      'WHERE level = ?', (level,))
        return int(r['m']), total

    def word_of_the_day(self):
        words = []
        for lv in data_bank.LEVELS:
            for i, w in enumerate(lv['words']):
                words.append((lv['id'], i, w))
        rnd = random.Random(date.today().toordinal())
        lv, idx, w = rnd.choice(words)
        return self._bank_item('word', lv, idx, w, {})

    # ------------------------------------------------------- answers & stats
    def record_answer(self, item, correct):
        """Store the result of one answered question for any unified item."""
        now = _now()
        if item['src'] == 'user':
            r = self._one('SELECT streak, correct, wrong FROM items WHERE id = ?',
                          (item['id'],))
            if r:
                streak = r['streak'] + 1 if correct else 0
                mastered = 1 if streak >= MASTER_STREAK else 0
                self.conn.execute(
                    'UPDATE items SET streak = ?, mastered = ?, correct = ?, wrong = ?, '
                    'last_seen = ? WHERE id = ?',
                    (streak, mastered, r['correct'] + (1 if correct else 0),
                     r['wrong'] + (0 if correct else 1), now, item['id']))
        else:
            uid = item['uid']
            r = self._one('SELECT streak, correct, wrong FROM bank_progress WHERE key = ?',
                          (uid,))
            old_streak = r['streak'] if r else 0
            old_c = r['correct'] if r else 0
            old_w = r['wrong'] if r else 0
            streak = old_streak + 1 if correct else 0
            mastered = 1 if streak >= MASTER_STREAK else 0
            self.conn.execute(
                'INSERT OR REPLACE INTO bank_progress'
                '(key, kind, level, mastered, streak, correct, wrong, last_seen) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                (uid, item['kind'], item['level'], mastered, streak,
                 old_c + (1 if correct else 0), old_w + (0 if correct else 1), now))
        today = _today()
        self.conn.execute('INSERT OR IGNORE INTO study_days(day, answers, correct) '
                          'VALUES (?, 0, 0)', (today,))
        self.conn.execute('UPDATE study_days SET answers = answers + 1, '
                          'correct = correct + ? WHERE day = ?',
                          (1 if correct else 0, today))
        self.conn.commit()

    def stats(self):
        """Numbers for the dashboard."""
        uw = self._one("SELECT COUNT(*) AS n FROM items WHERE kind = 'word'")['n']
        us = self._one("SELECT COUNT(*) AS n FROM items WHERE kind = 'sentence'")['n']
        um = self._one('SELECT COUNT(*) AS n FROM items WHERE mastered = 1')['n']
        bw = self._one("SELECT COUNT(*) AS n FROM bank_progress WHERE kind = 'word'")['n']
        bs = self._one("SELECT COUNT(*) AS n FROM bank_progress WHERE kind = 'sentence'")['n']
        bm = self._one('SELECT COUNT(*) AS n FROM bank_progress WHERE mastered = 1')['n']
        return {
            'words': uw + bw, 'sentences': us + bs, 'mastered': um + bm,
            'my_words': uw, 'my_sentences': us,
        }

    # -------------------------------------------------------- streak & goal
    def study_day_set(self):
        return {r['day'] for r in self._q('SELECT day FROM study_days WHERE answers > 0')}

    def get_streak(self):
        days = self.study_day_set()
        d = date.today()
        if d.isoformat() not in days:
            d -= timedelta(days=1)
        count = 0
        while d.isoformat() in days:
            count += 1
            d -= timedelta(days=1)
        return count

    def week_activity(self):
        """Last 7 days, oldest first: [(date, studied, is_today), ...]."""
        days = self.study_day_set()
        today = date.today()
        out = []
        for i in range(6, -1, -1):
            dd = today - timedelta(days=i)
            out.append((dd, dd.isoformat() in days, i == 0))
        return out

    def best_streak(self):
        days = sorted(self.study_day_set())
        best = cur = 0
        prev = None
        for s in days:
            d = date.fromisoformat(s)
            if prev is not None and (d - prev).days == 1:
                cur += 1
            else:
                cur = 1
            best = max(best, cur)
            prev = d
        return best

    def studied_today(self):
        return _today() in self.study_day_set()

    def today_answers(self):
        r = self._one('SELECT answers, correct FROM study_days WHERE day = ?', (_today(),))
        return (r['answers'], r['correct']) if r else (0, 0)

    # --------------------------------------------------------------- levels
    def level_info(self, level):
        r = self._one('SELECT * FROM level_progress WHERE level = ?', (level,))
        if r:
            return dict(r)
        return {'level': level, 'best_score': 0, 'attempts': 0, 'passed': 0,
                'last_played': None}

    def is_level_unlocked(self, level):
        prev = data_bank.prev_in_group(level)
        if prev is None or self.get_bool('unlock_all'):
            return True
        return bool(self.level_info(prev)['passed'])

    def unlocked_levels(self):
        return [lv for lv in data_bank.level_ids() if self.is_level_unlocked(lv)]

    def max_unlocked_level(self):
        ids = self.unlocked_levels()
        return ids[-1] if ids else 1

    def save_level_result(self, level, score_pct):
        """Returns the id of the level this result unlocked for the first time
        (0 when nothing new was unlocked)."""
        info = self.level_info(level)
        nxt = data_bank.next_in_group(level)
        was_next_open = bool(nxt) and self.is_level_unlocked(nxt)
        best = max(info['best_score'], int(score_pct))
        passed = 1 if (info['passed'] or score_pct >= PASS_SCORE) else 0
        self._x('INSERT OR REPLACE INTO level_progress'
                '(level, best_score, attempts, passed, last_played) VALUES (?, ?, ?, ?, ?)',
                (level, best, info['attempts'] + 1, passed, _now()))
        if nxt and (not was_next_open) and self.is_level_unlocked(nxt):
            return nxt
        return 0

    # ----------------------------------------------------------- smart pool
    def smart_pool(self, limit=20, kinds=('word', 'sentence')):
        """Hard items first: wrong answers, low streak, then never-seen items."""
        hard, weak, fresh = [], [], []
        for it in self.get_all_user_items(kinds=kinds):
            self._classify(it, hard, weak, fresh)
        for key, r in self._bank_progress_map().items():
            it = self.bank_item_by_uid(key)
            if it and it['kind'] in kinds:
                self._classify(it, hard, weak, fresh)
        hard.sort(key=lambda t: -t[0])
        weak.sort(key=lambda t: -t[0])
        random.shuffle(fresh)
        pool = [t[1] for t in hard] + [t[1] for t in weak] + fresh
        return pool[:limit], len(hard)

    @staticmethod
    def _classify(it, hard, weak, fresh):
        if it['mastered']:
            return
        seen = it['correct'] + it['wrong']
        score = it['wrong'] * 2.0 - it['streak'] - it['correct'] * 0.3
        if it['wrong'] > 0:
            hard.append((score + 3, it))
        elif seen > 0:
            weak.append((-it['streak'] - it['correct'] * 0.3, it))
        else:
            fresh.append(it)

    # ------------------------------------------------- copy bank -> folder
    def copy_level_to_folder(self, level, folder_name):
        data = data_bank.get_level(level)
        fid = self.add_folder(folder_name, color=(level - 1) % 8)
        for en, ar, ex, ex_ar in data['words']:
            self.conn.execute(
                'INSERT INTO items(folder_id, kind, en, ar, example, example_ar, created_at) '
                "VALUES (?, 'word', ?, ?, ?, ?, ?)", (fid, en, ar, ex, ex_ar, _now()))
        for en, ar in data['sentences']:
            self.conn.execute(
                'INSERT INTO items(folder_id, kind, en, ar, created_at) '
                "VALUES (?, 'sentence', ?, ?, ?)", (fid, en, ar, _now()))
        self.conn.commit()
        return fid

    def create_sample_folder(self, lang):
        s = data_bank.SAMPLE_FOLDER
        fid = self.add_folder(s['name_ar'] if lang == 'ar' else s['name_en'], s['color'])
        for en, ar, ex, ex_ar in s['items']:
            self.add_item(fid, 'word', en, ar, ex, ex_ar)
        return fid

    # -------------------------------------------------------------- backup
    def export_all(self):
        folders = []
        for f in self._q('SELECT * FROM folders ORDER BY sort_order, id'):
            items = [dict(i) for i in self._q('SELECT * FROM items WHERE folder_id = ? '
                                              'ORDER BY id', (f['id'],))]
            for i in items:
                i.pop('folder_id', None)
                i.pop('id', None)
            folders.append({'name': f['name'], 'color': f['color'],
                            'sort_order': f['sort_order'],
                            'created_at': f['created_at'], 'items': items})
        return {
            'app': APP_NAME,
            'version': BACKUP_VERSION,
            'exported_at': _now(),
            'settings': {k: v for k, v in self._settings_cache.items()},
            'folders': folders,
            'bank_progress': [dict(r) for r in self._q('SELECT * FROM bank_progress')],
            'level_progress': [dict(r) for r in self._q('SELECT * FROM level_progress')],
            'study_days': [dict(r) for r in self._q('SELECT * FROM study_days')],
        }

    @staticmethod
    def validate_backup(data):
        if not isinstance(data, dict) or data.get('app') != APP_NAME:
            raise ValueError('not a Lingora backup')
        if not isinstance(data.get('folders', []), list):
            raise ValueError('corrupted backup')
        return True

    def import_all(self, data, mode='merge'):
        """Import a backup dict. mode = 'merge' (keep current data) or 'replace'."""
        self.validate_backup(data)
        stats = {'folders': 0, 'items': 0}
        try:
            self.conn.execute('BEGIN')
            if mode == 'replace':
                self.conn.execute('DELETE FROM items')
                self.conn.execute('DELETE FROM folders')
                self.conn.execute('DELETE FROM bank_progress')
                self.conn.execute('DELETE FROM level_progress')
                self.conn.execute('DELETE FROM study_days')
            for f in data.get('folders', []):
                name = str(f.get('name', '')).strip()
                if not name:
                    continue
                row = self._one('SELECT id FROM folders WHERE name = ?', (name,))
                if row:
                    fid = row['id']
                else:
                    order = self._one('SELECT COALESCE(MAX(sort_order), 0) + 1 AS n '
                                      'FROM folders')['n']
                    cur = self.conn.execute(
                        'INSERT INTO folders(name, color, sort_order, created_at) '
                        'VALUES (?, ?, ?, ?)',
                        (name, int(f.get('color', 0) or 0), order,
                         f.get('created_at') or _now()))
                    fid = cur.lastrowid
                    stats['folders'] += 1
                for it in f.get('items', []):
                    en = str(it.get('en', '')).strip()
                    ar = str(it.get('ar', '')).strip()
                    if not en or not ar:
                        continue
                    kind = it.get('kind') if it.get('kind') in ('word', 'sentence') else 'word'
                    dup = self._one('SELECT id FROM items WHERE folder_id = ? AND kind = ? '
                                    'AND LOWER(en) = ?', (fid, kind, en.lower()))
                    if dup:
                        continue
                    self.conn.execute(
                        'INSERT INTO items(folder_id, kind, en, ar, example, example_ar, '
                        'hl_main, hl_example, mastered, streak, correct, wrong, last_seen, '
                        'created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (fid, kind, en, ar, it.get('example') or '',
                         it.get('example_ar') or '', int(it.get('hl_main') or 0),
                         int(it.get('hl_example') or 0), int(it.get('mastered') or 0),
                         int(it.get('streak') or 0), int(it.get('correct') or 0),
                         int(it.get('wrong') or 0), it.get('last_seen'),
                         it.get('created_at') or _now()))
                    stats['items'] += 1
            for p in data.get('bank_progress', []):
                old = self._one('SELECT * FROM bank_progress WHERE key = ?', (p.get('key'),))
                if old and mode == 'merge':
                    if (old['correct'] + old['wrong']) >= (p.get('correct', 0) + p.get('wrong', 0)):
                        continue
                self.conn.execute(
                    'INSERT OR REPLACE INTO bank_progress'
                    '(key, kind, level, mastered, streak, correct, wrong, last_seen) '
                    'VALUES (?,?,?,?,?,?,?,?)',
                    (p.get('key'), p.get('kind'), int(p.get('level') or 0),
                     int(p.get('mastered') or 0), int(p.get('streak') or 0),
                     int(p.get('correct') or 0), int(p.get('wrong') or 0),
                     p.get('last_seen')))
            for p in data.get('level_progress', []):
                old = self._one('SELECT * FROM level_progress WHERE level = ?',
                                (p.get('level'),))
                best = int(p.get('best_score') or 0)
                attempts = int(p.get('attempts') or 0)
                passed = int(p.get('passed') or 0)
                if old:
                    best = max(best, old['best_score'])
                    attempts = max(attempts, old['attempts'])
                    passed = max(passed, old['passed'])
                self.conn.execute(
                    'INSERT OR REPLACE INTO level_progress'
                    '(level, best_score, attempts, passed, last_played) VALUES (?,?,?,?,?)',
                    (int(p.get('level')), best, attempts, passed, p.get('last_played')))
            for d in data.get('study_days', []):
                old = self._one('SELECT * FROM study_days WHERE day = ?', (d.get('day'),))
                ans = int(d.get('answers') or 0)
                cor = int(d.get('correct') or 0)
                if old:
                    ans = max(ans, old['answers'])
                    cor = max(cor, old['correct'])
                self.conn.execute('INSERT OR REPLACE INTO study_days(day, answers, correct) '
                                  'VALUES (?,?,?)', (d.get('day'), ans, cor))
            if mode == 'replace' and isinstance(data.get('settings'), dict):
                for k, v in data['settings'].items():
                    if k in DEFAULT_SETTINGS:
                        self.conn.execute('INSERT OR REPLACE INTO settings(key, value) '
                                          'VALUES (?, ?)', (k, str(v)))
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self._load_settings()
        return stats

    def write_backup_file(self, path):
        data = self.export_all()
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return path

    def read_backup_file(self, path):
        with open(path, 'r', encoding='utf-8') as fh:
            return json.load(fh)

    def reset_progress(self):
        """Forget all learning progress but keep folders and items."""
        self._x('UPDATE items SET mastered = 0, streak = 0, correct = 0, wrong = 0')
        self._x('DELETE FROM bank_progress')
        self._x('DELETE FROM level_progress')
        self._x('DELETE FROM study_days')

    def reset_everything(self):
        self._x('DELETE FROM items')
        self._x('DELETE FROM folders')
        self.reset_progress()
