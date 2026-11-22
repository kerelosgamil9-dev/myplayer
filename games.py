# -*- coding: utf-8 -*-
"""
games.py - all learning / testing activities of Lingora.

  Feeder         chooses the questions (system words that get harder step by
                 step, the user's own words, or the hard words of Smart Review)
  QuizGame       multiple choice, reverse choice, spelling, mixed, speed round,
                 survival and level tests
  FlashcardGame  flip cards
  MatchGame      word matching
  ResultView     score screen shown at the end of every activity
"""

import random
import re

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

import data_bank
import rtl
from strings import tr
from theme import C, HIGHLIGHTS, alpha
from widgets import (ATextInput, BarProgress, FlameWidget, Icon,
                     IconButton, RButton, TapCard, Toast, add_row, auto_card, button,
                     hbox, label, spacer, vbox)


# ======================================================================
# question selection
# ======================================================================
class Feeder:
    """Hands out learning items one by one.

    cfg keys
        source   'bank' (built-in levels) | 'user' (my folders) | 'smart'
        levels   list of bank levels, or None for *progressive* (all unlocked
                 levels, starting with the easiest and getting harder)
        folder_id  restrict 'user' to one folder (None = all)
        kinds    ('word', 'sentence')
    """

    RAMP = 6      # endless modes move up one level every RAMP questions

    def __init__(self, db, cfg, total=None):
        self.db = db
        self.cfg = cfg
        self.kinds = tuple(cfg.get('kinds') or ('word', 'sentence'))
        self.total = total
        self.count = 0
        self.used = set()
        self.cursor = 0
        self.source = cfg.get('source', 'bank')
        self.by_level = {}
        self.levels = []
        self.pool = []
        self.progressive = False
        self._dist_cache = {}
        self.fallback = False
        if self.source == 'user':
            self.pool = db.get_all_user_items(cfg.get('folder_id'), self.kinds)
            random.shuffle(self.pool)
        elif self.source == 'smart':
            self.pool, hard = db.smart_pool(60, self.kinds)
            self.hard_count = hard
            if not self.pool:
                self.source = 'bank'
                self.fallback = True
        if self.source == 'bank':
            lv = cfg.get('levels')
            self.progressive = not lv
            self.levels = list(lv) if lv else db.unlocked_levels()
            self.by_level = {l: db.bank_items([l], self.kinds) for l in self.levels}

    def available(self):
        if self.source == 'bank':
            return sum(len(v) for v in self.by_level.values())
        return len(self.pool)

    def next(self):
        self.count += 1
        if self.source != 'bank':
            if not self.pool:
                return None
            if self.cursor >= len(self.pool):
                self.cursor = 0
                random.shuffle(self.pool)
            it = self.pool[self.cursor]
            self.cursor += 1
            return it
        # bank: ramp the level with the question number
        n = len(self.levels)
        if not self.progressive:
            lvl = random.choice(self.levels)
        elif self.total:
            lvl = self.levels[min(n - 1, (self.count - 1) * n // max(1, self.total))]
        else:
            lvl = self.levels[min(n - 1, (self.count - 1) // self.RAMP)]
        cands = [it for it in self.by_level.get(lvl, []) if it['uid'] not in self.used]
        if not cands:
            cands = [it for l in self.levels for it in self.by_level[l]
                     if it['uid'] not in self.used]
        if not cands:
            self.used.clear()
            cands = list(self.by_level.get(lvl) or self.by_level[self.levels[0]])
        weights = [1 if it['mastered'] else 3 for it in cands]
        it = random.choices(cands, weights=weights)[0]
        self.used.add(it['uid'])
        return it

    def session_items(self, n):
        """n distinct items (used by flashcards / matching)."""
        out, seen = [], set()
        guard = 0
        while len(out) < n and guard < n * 6:
            guard += 1
            it = self.next()
            if it is None:
                break
            if it['uid'] in seen:
                continue
            seen.add(it['uid'])
            out.append(it)
        return out

    # -- wrong options ----------------------------------------------------
    def options(self, item, field, k=3):
        """Shuffled list of (text, is_correct) with k distractors."""
        correct = item[field]
        kind = item['kind']
        near = self._near(kind)
        texts = []
        for it in near:
            t = it[field]
            if t != correct and t not in texts:
                texts.append(t)
        random.shuffle(texts)
        texts = texts[:k]
        if len(texts) < k:
            far = self._far(kind)
            random.shuffle(far)
            for it in far:
                t = it[field]
                if t != correct and t not in texts:
                    texts.append(t)
                    if len(texts) >= k:
                        break
        opts = [(correct, True)] + [(t, False) for t in texts]
        random.shuffle(opts)
        return opts

    def _near(self, kind):
        if self.source == 'bank':
            return [it for l in self.levels for it in self.by_level[l] if it['kind'] == kind]
        return [it for it in self.pool if it['kind'] == kind]

    def _far(self, kind):
        if kind not in self._dist_cache:
            self._dist_cache[kind] = self.db.bank_items(
                data_bank.level_ids(), (kind,))
        return list(self._dist_cache[kind])


# ======================================================================
# helpers
# ======================================================================
def _norm(s):
    s = (s or '').lower().strip()
    s = re.sub(r"[.,!?;:\"“”]", '', s)
    s = s.replace('’', "'")
    return re.sub(r'\s+', ' ', s)


def stars_for(pct):
    if pct >= 90:
        return 3
    if pct >= 70:
        return 2
    if pct >= 40:
        return 1
    return 0


def _app():
    return App.get_running_app()


class GameBase(BoxLayout):
    """Common state: answers, score, finishing."""

    def __init__(self, app, cfg, on_finish, **kw):
        super().__init__(orientation='vertical', padding=[dp(14), dp(10)],
                         spacing=dp(10), **kw)
        self.app = app
        self.cfg = cfg
        self.on_finish = on_finish
        self.correct = 0
        self.wrong = 0
        self.score = 0
        self.finished = False
        self._events = []

    def later(self, fn, delay):
        ev = Clock.schedule_once(lambda dt: fn(), delay)
        self._events.append(ev)
        return ev

    def stop(self):
        for ev in self._events:
            try:
                ev.cancel()
            except Exception:
                pass
        self._events = []

    def start(self):
        raise NotImplementedError

    def finish(self, extra=None):
        if self.finished:
            return
        self.finished = True
        self.stop()
        total = self.correct + self.wrong
        res = {'mode': self.cfg.get('mode'), 'cfg': self.cfg, 'correct': self.correct,
               'wrong': self.wrong, 'total': total, 'score': self.score,
               'pct': int(round(100.0 * self.correct / total)) if total else 0}
        if extra:
            res.update(extra)
        self.on_finish(res)

    def _head(self, left_text, right_text=''):
        """Header row with counter and score + progress bar. Returns (box, widgets)."""
        box = vbox(spacing=dp(6))
        row = hbox(dp(28))
        self.lbl_left = label(left_text, size=15, bold=True, wrap=False, size_hint_y=1)
        self.lbl_right = label(right_text, size=15, color='sub', bold=True, wrap=False,
                               size_hint_y=1, align='right' if not rtl.UI_RTL else 'left')
        add_row(row, [self.lbl_left, self.lbl_right])
        self.bar = BarProgress(value=0, height=dp(8))
        box.add_widget(row)
        box.add_widget(self.bar)
        return box


# ======================================================================
# Quiz game (mcq / reverse / spelling / mixed / speed / survival)
# ======================================================================
class QuizGame(GameBase):

    def __init__(self, app, cfg, on_finish, **kw):
        super().__init__(app, cfg, on_finish, **kw)
        self.mode = cfg.get('mode', 'mcq')
        self.endless = self.mode in ('speed', 'survival')
        if self.mode == 'spell':
            cfg = dict(cfg, kinds=('word',))
            self.cfg = cfg
        self.feeder = Feeder(app.db, cfg, None if self.endless else cfg.get('n', 10))
        avail = self.feeder.available()
        n = cfg.get('n') or app.db.get_int('round_size', 10)
        if self.endless:
            self.total = None
        elif self.feeder.source == 'bank':
            self.total = n
        else:
            self.total = max(1, min(n, avail))
        self.index = 0
        self.combo = 0
        self.best_combo = 0
        self.lives = 3
        self.time_left = float(cfg.get('time', 60))
        self.locked = False
        self.hints = 0
        self.item = None
        self.qtype = 'en_ar'

        if self.mode == 'speed':
            right = '%d' % self.time_left
        elif self.mode == 'survival':
            right = '♥ ' * self.lives
        else:
            right = ''
        self.add_widget(self._head('', right))
        self.sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        self.body = vbox(spacing=dp(12), padding=[0, dp(4), 0, dp(20)])
        self.sv.add_widget(self.body)
        self.add_widget(self.sv)

    # -- flow ---------------------------------------------------------------
    def start(self):
        if self.feeder.available() == 0:
            Toast.show(tr('no_items'), 'warn')
            self.finish()
            return
        if self.mode == 'speed':
            self._events.append(Clock.schedule_interval(self._tick, 0.25))
        self._next()

    def _tick(self, dt):
        if self.finished:
            return False
        self.time_left -= dt
        left = max(0, int(self.time_left + 0.99))
        self.lbl_right.raw = '%d s' % left
        self.bar.value = max(0.0, self.time_left / float(self.cfg.get('time', 60)))
        if self.time_left <= 0:
            self._end()
            return False
        return True

    def _end(self):
        extra = {'score': self.score, 'best_combo': self.best_combo}
        self.finish(extra)

    def _pick_type(self, item):
        m = self.mode
        if m == 'mcq':
            return 'en_ar'
        if m == 'rev':
            return 'ar_en'
        if m == 'spell':
            return 'spell'
        if m in ('speed', 'survival'):
            return random.choice(['en_ar', 'ar_en'])
        choices = ['en_ar', 'ar_en']
        weights = [4, 3]
        if item['kind'] == 'word':
            choices.append('spell')
            weights.append(2)
        return random.choices(choices, weights=weights)[0]

    def _update_header(self):
        if self.mode == 'speed':
            self.lbl_left.raw = tr('score_n', n=self.score)
            return
        if self.mode == 'survival':
            self.lbl_left.raw = tr('score_n', n=self.score)
            self.lbl_right.raw = '♥ ' * self.lives if self.lives else '-'
            self.bar.value = 0
            return
        self.lbl_left.raw = '%d / %d' % (min(self.index + 1, self.total), self.total)
        self.lbl_right.raw = tr('score_n', n=self.score)
        self.bar.value = self.index / float(self.total)

    def _next(self):
        if self.finished:
            return
        if not self.endless and self.index >= self.total:
            self._end()
            return
        if self.mode == 'survival' and self.lives <= 0:
            self._end()
            return
        item = self.feeder.next()
        if item is None:
            self._end()
            return
        self.item = item
        self.qtype = self._pick_type(item)
        self.locked = False
        self.hints = 0
        self._update_header()
        self.body.clear_widgets()
        if self.qtype == 'spell':
            self._build_spell()
        else:
            self._build_choice()
        self.sv.scroll_y = 1

    # -- multiple choice -----------------------------------------------------
    def _build_choice(self):
        it = self.item
        en_to_ar = self.qtype == 'en_ar'
        card = auto_card(padding=[dp(18), dp(24)], spacing=dp(12), radius=dp(24))
        caption = tr('q_pick_ar') if en_to_ar else tr('q_pick_en')
        if it['kind'] == 'sentence':
            caption = tr('q_pick_ar_s') if en_to_ar else tr('q_pick_en_s')
        card.add_widget(label(caption, size=13, color='sub', bold=True, align='center'))
        q_text = it['en'] if en_to_ar else it['ar']
        size = 36 if it['kind'] == 'word' else 22
        card.add_widget(label(q_text, size=size, bold=True, align='center'))
        if en_to_ar:
            row = hbox(dp(46))
            row.add_widget(Widget())
            sp_btn = IconButton(name='speaker', color=C('primary'), size_hint=(None, 1),
                                width=dp(46))
            sp_btn.bind(on_release=lambda *_: self.app.speak(it['en']))
            row.add_widget(sp_btn)
            row.add_widget(Widget())
            card.add_widget(row)
        self.body.add_widget(card)

        field = 'ar' if en_to_ar else 'en'
        self.opt_buttons = []
        col = vbox(spacing=dp(12))
        for text, ok in self.feeder.options(it, field):
            b = RButton(raw=text, bg=C('card'), color=C('text'), wrap=True, autoheight=True,
                        padding=[dp(14), dp(20)], font_size=sp(20 if it['kind'] == 'word' else 17),
                        outline=C('border'), radius=dp(18), size_hint_y=None, height=dp(64))
            b.is_ok = ok
            b.bind(on_release=self._on_choice)
            self.opt_buttons.append(b)
            col.add_widget(b)
        self.body.add_widget(col)
        if en_to_ar and self.app.db.get_bool('auto_speak'):
            self.later(lambda: self.app.speak(it['en'], quiet=True), 0.25)

    def _on_choice(self, btn):
        if self.locked or self.finished:
            return
        self.locked = True
        ok = btn.is_ok
        for b in self.opt_buttons:
            b.disabled = False
            if b.is_ok:
                b.bg = C('success')
                b.color = (1, 1, 1, 1)
                b.outline = []
            elif b is btn:
                b.bg = C('danger')
                b.color = (1, 1, 1, 1)
                b.outline = []
            else:
                b.opacity = 0.55
        self._answered(ok, delay=0.85 if ok else 1.5)

    # -- spelling ---------------------------------------------------------------
    def _build_spell(self):
        it = self.item
        card = auto_card(padding=[dp(14), dp(12)], spacing=dp(4))
        card.add_widget(label(tr('q_spell'), size=13, color='sub', bold=True, align='center'))
        card.add_widget(label(it['ar'], size=28, bold=True, align='center'))
        row = hbox(dp(42))
        row.add_widget(Widget())
        sp_btn = IconButton(name='speaker', color=C('primary'), size_hint=(None, 1), width=dp(42))
        sp_btn.bind(on_release=lambda *_: self.app.speak(it['en']))
        row.add_widget(sp_btn)
        row.add_widget(Widget())
        card.add_widget(row)
        self.pattern = label('', size=24, color='primary', bold=True, align='center')
        self._update_pattern()
        card.add_widget(self.pattern)
        self.body.add_widget(card)

        self.spell_input = ATextInput(hint=tr('type_english'), font_size=sp(20),
                                      halign='center', height=dp(56), vk_lang='en')
        self.spell_input.bind(on_text_validate=lambda *_: self._check_spell())
        self.body.add_widget(self.spell_input)
        self.spell_msg = label('', size=17, bold=True, align='center')
        self.body.add_widget(self.spell_msg)
        row2 = hbox(dp(50), spacing=dp(10))
        self.btn_hint = button(tr('hint'), self._hint, style='soft')
        self.btn_check = button(tr('check'), self._check_spell, style='primary')
        add_row(row2, [self.btn_hint, self.btn_check])
        self.body.add_widget(row2)
        self.later(self._open_input, 0.35)
        if self.app.db.get_bool('auto_speak'):
            self.later(lambda: self.app.speak(it['en'], quiet=True), 0.35)

    def _update_pattern(self):
        word = self.item['en']
        shown = []
        revealed = self.hints
        count = 0
        for ch in word:
            if ch == ' ':
                shown.append('  ')
            elif count < revealed:
                shown.append(ch)
                count += 1
            else:
                shown.append('_')
                count += 1
        self.pattern.raw = ' '.join(shown)

    def _hint(self):
        if self.locked:
            return
        letters = len(self.item['en'].replace(' ', ''))
        if self.hints < letters - 1:
            self.hints += 1
            self._update_pattern()

    def _open_input(self):
        self.spell_input.focus_input()

    def _check_spell(self):
        if self.locked or self.finished:
            return
        answer = _norm(self.spell_input.text)
        if not answer:
            return
        self.locked = True
        self.spell_input.focus = False
        ok = answer == _norm(self.item['en'])
        if ok:
            self.spell_msg.color = C('success')
            self.spell_msg.raw = tr('correct')
            self._answered(True, delay=0.9, hinted=self.hints > 0)
        else:
            self.spell_msg.color = C('danger')
            self.spell_msg.raw = tr('answer_is', a=self.item['en'])
            self.app.speak(self.item['en'], quiet=True)
            self._answered(False, delay=2.2)

    # -- scoring ----------------------------------------------------------------
    def _answered(self, ok, delay, hinted=False):
        app = self.app
        app.db.record_answer(self.item, ok and not hinted)
        if ok:
            self.correct += 1
            self.combo += 1
            self.best_combo = max(self.best_combo, self.combo)
            self.score += (5 if hinted else 10) + min(self.combo - 1, 5) * 2
            app.sfx.play('correct')
        else:
            self.wrong += 1
            self.combo = 0
            if self.mode == 'survival':
                self.lives -= 1
            app.sfx.play('wrong')
        self.index += 1
        self._update_header()
        if self.mode == 'speed' and self.time_left <= 0:
            return
        self.later(self._next, delay)

    def stop(self):
        super().stop()


# ======================================================================
# Flashcards
# ======================================================================
class FlashcardGame(GameBase):

    def __init__(self, app, cfg, on_finish, **kw):
        super().__init__(app, cfg, on_finish, **kw)
        self.feeder = Feeder(app.db, cfg, cfg.get('n', 10))
        n = cfg.get('n') or app.db.get_int('round_size', 10)
        self.items = self.feeder.session_items(n)
        self.index = 0
        self.flipped = False
        self.add_widget(self._head('', ''))
        self.card = TapCard(padding=[dp(18), dp(18)], spacing=dp(10), radius=dp(26))
        self.card.bind(on_release=lambda *_: self.flip())
        self.content = BoxLayout(orientation='vertical', spacing=dp(10))
        self.card.add_widget(self.content)
        self.add_widget(self.card)
        self.btn_row = hbox(dp(54), spacing=dp(10))
        self.add_widget(self.btn_row)

    def start(self):
        if not self.items:
            Toast.show(tr('no_items'), 'warn')
            self.finish()
            return
        self._show()

    def _show(self):
        if self.index >= len(self.items):
            self.finish()
            return
        it = self.items[self.index]
        self.flipped = False
        self.lbl_left.raw = '%d / %d' % (self.index + 1, len(self.items))
        self.lbl_right.raw = tr('score_n', n=self.score)
        self.bar.value = self.index / float(len(self.items))
        self._render()
        self.btn_row.clear_widgets()
        self.btn_row.add_widget(button(tr('flip'), self.flip, style='primary'))
        if self.app.db.get_bool('auto_speak'):
            self.later(lambda: self.app.speak(it['en'], quiet=True), 0.25)

    def _render(self):
        it = self.items[self.index]
        c = self.content
        c.clear_widgets()
        if not self.flipped:
            c.add_widget(label(tr('flash_front'), size=13, color='sub', bold=True, align='center',
                               size_hint_y=None))
            c.add_widget(Widget())
            big = label(it['en'], size=34 if it['kind'] == 'word' else 24, bold=True,
                        align='center')
            if it.get('hl_main'):
                big.hl = list(HIGHLIGHTS[it['hl_main']])
            c.add_widget(big)
            row = hbox(dp(52))
            row.add_widget(Widget())
            b = IconButton(name='speaker', color=C('primary'), size_hint=(None, 1), width=dp(52))
            b.bind(on_release=lambda *_: self.app.speak(it['en']))
            row.add_widget(b)
            row.add_widget(Widget())
            c.add_widget(row)
            c.add_widget(Widget())
            c.add_widget(label(tr('tap_flip'), size=13, color='sub', align='center'))
        else:
            c.add_widget(label(tr('flash_back'), size=13, color='sub', bold=True, align='center',
                               size_hint_y=None))
            c.add_widget(Widget())
            c.add_widget(label(it['ar'], size=32 if it['kind'] == 'word' else 22, bold=True,
                               align='center', color='primary'))
            if it['ex']:
                c.add_widget(spacer(h=dp(8)))
                c.add_widget(label(it['ex'], size=17, align='center'))
                if it['ex_ar']:
                    c.add_widget(label(it['ex_ar'], size=15, color='sub', align='center'))
            c.add_widget(Widget())

    def flip(self):
        if self.finished:
            return
        if not self.flipped:
            self.flipped = True
            self.app.sfx.play('flip')
            self._render()
            self.btn_row.clear_widgets()
            again = button(tr('still_learning'), lambda: self._grade(False), style='soft')
            known = button(tr('got_it'), lambda: self._grade(True), style='success')
            add_row(self.btn_row, [again, known])
        else:
            self.flipped = False
            self._render()
            self.btn_row.clear_widgets()
            self.btn_row.add_widget(button(tr('flip'), self.flip, style='primary'))

    def _grade(self, ok):
        it = self.items[self.index]
        self.app.db.record_answer(it, ok)
        if ok:
            self.correct += 1
            self.score += 10
            self.app.sfx.play('correct')
        else:
            self.wrong += 1
            self.app.sfx.play('click')
        self.index += 1
        self._show()


# ======================================================================
# Word matching
# ======================================================================
class MatchGame(GameBase):
    PAIRS = 5

    def __init__(self, app, cfg, on_finish, **kw):
        cfg = dict(cfg, kinds=('word',))
        super().__init__(app, cfg, on_finish, **kw)
        self.feeder = Feeder(app.db, cfg, cfg.get('n', 10))
        n = cfg.get('n') or app.db.get_int('round_size', 10)
        n = max(self.PAIRS, n)
        self.items = self.feeder.session_items(n)
        self.rounds = [self.items[i:i + self.PAIRS] for i in range(0, len(self.items), self.PAIRS)]
        if len(self.rounds) > 1 and len(self.rounds[-1]) < 3:
            self.rounds[-2] += self.rounds.pop()
        self.round_index = 0
        self.sel_left = None
        self.sel_right = None
        self.matched = 0
        self.errors = set()
        self.locked = False
        self.add_widget(self._head('', ''))
        self.board = BoxLayout(orientation='horizontal', spacing=dp(12))
        self.add_widget(self.board)

    def start(self):
        if not self.items:
            Toast.show(tr('no_items'), 'warn')
            self.finish()
            return
        self._round()

    def _round(self):
        if self.round_index >= len(self.rounds):
            self.finish()
            return
        items = self.rounds[self.round_index]
        self.lbl_left.raw = tr('round_n', a=self.round_index + 1, b=len(self.rounds))
        self.lbl_right.raw = tr('score_n', n=self.score)
        self.bar.value = self.round_index / float(len(self.rounds))
        self.matched = 0
        self.sel_left = self.sel_right = None
        self.locked = False
        self.board.clear_widgets()
        left_col = BoxLayout(orientation='vertical', spacing=dp(10))
        right_col = BoxLayout(orientation='vertical', spacing=dp(10))
        self.left_btns, self.right_btns = [], []
        lefts = list(items)
        rights = list(items)
        random.shuffle(lefts)
        random.shuffle(rights)
        for it in lefts:
            b = self._tile(it['en'], it, 'left')
            self.left_btns.append(b)
            left_col.add_widget(b)
        for it in rights:
            b = self._tile(it['ar'], it, 'right')
            self.right_btns.append(b)
            right_col.add_widget(b)
        self.board.add_widget(left_col)
        self.board.add_widget(right_col)

    def _tile(self, text, item, side):
        b = RButton(raw=text, bg=C('card'), color=C('text'), outline=C('border'),
                    radius=dp(16), font_size=sp(17), wrap=True, padding=[dp(6), dp(4)])
        b.item = item
        b.side = side
        b.done = False
        b.bind(on_release=self._tap)
        return b

    def _paint(self, b, state):
        if state == 'idle':
            b.bg, b.color, b.outline = C('card'), C('text'), C('border')
        elif state == 'sel':
            b.bg, b.color, b.outline = alpha(C('primary'), 0.25), C('text'), C('primary')
        elif state == 'ok':
            b.bg, b.color, b.outline = C('success'), (1, 1, 1, 1), []
        elif state == 'bad':
            b.bg, b.color, b.outline = C('danger'), (1, 1, 1, 1), []

    def _tap(self, b):
        if self.locked or b.done or self.finished:
            return
        if b.side == 'left':
            if self.sel_left is not None:
                self._paint(self.sel_left, 'idle')
            self.sel_left = b
            self._paint(b, 'sel')
            self.app.speak(b.item['en'], quiet=True)
        else:
            if self.sel_right is not None:
                self._paint(self.sel_right, 'idle')
            self.sel_right = b
            self._paint(b, 'sel')
        if self.sel_left is not None and self.sel_right is not None:
            self._resolve()

    def _resolve(self):
        a, b = self.sel_left, self.sel_right
        self.sel_left = self.sel_right = None
        if a.item['uid'] == b.item['uid']:
            for x in (a, b):
                x.done = True
                self._paint(x, 'ok')
            first_try = a.item['uid'] not in self.errors
            self.app.db.record_answer(a.item, first_try)
            if first_try:
                self.correct += 1
                self.score += 10
            self.app.sfx.play('correct')
            self.matched += 1
            self.lbl_right.raw = tr('score_n', n=self.score)
            if self.matched >= len(self.rounds[self.round_index]):
                self.locked = True
                self.round_index += 1
                self.later(self._round, 0.8)
        else:
            self.locked = True
            self._paint(a, 'bad')
            self._paint(b, 'bad')
            self.app.sfx.play('wrong')
            for it in (a.item, b.item):
                if it['uid'] not in self.errors:
                    self.errors.add(it['uid'])
                    self.app.db.record_answer(it, False)
                    self.wrong += 1

            def reset():
                for x in (a, b):
                    if not x.done:
                        self._paint(x, 'idle')
                self.locked = False
            self.later(reset, 0.5)


# ======================================================================
# Results
# ======================================================================
class ResultView(BoxLayout):
    def __init__(self, app, res, on_again, on_back, extra_lines=(), **kw):
        super().__init__(orientation='vertical', padding=[dp(18), dp(14)], spacing=dp(12), **kw)
        sv = ScrollView(do_scroll_x=False, bar_width=dp(3))
        col = vbox(spacing=dp(12), padding=[0, dp(6), 0, dp(10)])
        pct = res['pct']
        stars = stars_for(pct)
        card = auto_card(padding=[dp(18), dp(20)], spacing=dp(10), radius=dp(26))
        srow = hbox(dp(54), spacing=dp(6))
        srow.add_widget(Widget())
        for i in range(3):
            s = Icon(name='star', filled=True,
                     color=C('accent') if i < stars else alpha(C('sub'), 0.4),
                     size_hint=(None, 1), width=dp(52))
            srow.add_widget(s)
        srow.add_widget(Widget())
        card.add_widget(srow)
        title = tr('res_great') if pct >= 70 else (tr('res_good') if pct >= 40 else tr('res_try'))
        card.add_widget(label(title, size=24, bold=True, align='center'))
        card.add_widget(label(tr('res_score', n=res['score']), size=34, bold=True,
                              color='primary', align='center'))
        card.add_widget(label(tr('res_correct', a=res['correct'], b=res['total']),
                              size=17, color='sub', align='center'))
        card.add_widget(BarProgress(value=pct / 100.0, height=dp(10)))
        card.add_widget(label('%d%%' % pct, size=15, bold=True, align='center'))
        col.add_widget(card)
        for text, kind in extra_lines:
            c2 = auto_card(padding=[dp(14), dp(12)])
            c2.add_widget(label(text, size=16, bold=True, align='center',
                                color={'ok': 'success', 'warn': 'warn',
                                       'bad': 'danger'}.get(kind, 'text')))
            col.add_widget(c2)
        streak = app.db.get_streak()
        sc = auto_card(padding=[dp(14), dp(10)])
        srow2 = hbox(dp(54), spacing=dp(12))
        flame = FlameWidget(days=streak, size_hint=(None, 1), width=dp(46))
        srow2.add_widget(flame)
        srow2.add_widget(label(tr('streak_days', n=streak), size=17, bold=True, wrap=False,
                               size_hint_y=1))
        sc.add_widget(srow2)
        col.add_widget(sc)
        sv.add_widget(col)
        self.add_widget(sv)
        row = hbox(dp(54), spacing=dp(10))
        add_row(row, [button(tr('back'), on_back, style='soft'),
                      button(tr('play_again'), on_again, style='primary')])
        self.add_widget(row)
