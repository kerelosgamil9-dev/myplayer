# -*- coding: utf-8 -*-
"""
screens.py - every screen of Lingora and the dialogs they use.

  HomeScreen        dashboard, streak fire, daily goal, quick actions
  FoldersScreen     list of word folders
  FolderScreen      items of one folder (separators, highlighter, TTS)
  LevelsScreen      built-in progressive levels and level tests
  ChallengesScreen  games and challenges
  GameScreen        hosts the running game and its result
  SettingsScreen    themes, language, dividers, backup, ...
"""

import os
import time

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.screenmanager import Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget

import data_bank
import games
import rtl
from database import PASS_SCORE
from strings import tr
from theme import C, FOLDER_COLORS, HIGHLIGHTS, alpha
import widgets as widgets_mod                                      # noqa: E402
from widgets import (TintButton, ALabel, ATextInput, BarProgress, Card, ColorDots, Dialog, Divider,
                     FlameWidget, FormField, Icon, IconButton, RButton, Segmented, TapCard,
                     Toast, Toggle, WeekStrip, add_row, auto_card, button, confirm, hbox, label,
                     logo_image, spacer, vbox)


# ======================================================================
# helpers
# ======================================================================
def make_divider(app):
    """Divider drawn between list items according to the Settings."""
    db = app.db
    if not db.get_bool('show_dividers'):
        return spacer(h=dp(8))
    col = C('primary') if db.get('divider_color') == 'accent' else C('divider')
    return Divider(style=db.get('divider_style'), thickness=db.get_int('divider_width', 1),
                   color=col)


class Badge(ALabel):
    """Rounded coloured square with a short text (level number, ...)."""

    def __init__(self, bg, **kw):
        kw.setdefault('align', 'center')
        kw.setdefault('bold', True)
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (dp(46), dp(46)))
        super().__init__(**kw)
        with self.canvas.before:
            Color(*bg)
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(14)])
        self.bind(pos=self._u, size=self._u)

    def _u(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size


def centered(widget, size):
    """Wrap a fixed-size widget so it stays vertically centred in a row."""
    box = BoxLayout(orientation='vertical', size_hint=(None, 1), width=size[0])
    box.add_widget(Widget())
    widget.size_hint = (None, None)
    widget.size = size
    box.add_widget(widget)
    box.add_widget(Widget())
    return box


def switch_row(text, active, on_change, sub=''):
    """Label (+ optional description) with a Toggle on the other side."""
    row = BoxLayout(orientation='horizontal', size_hint_y=None, spacing=dp(12))
    row.bind(minimum_height=row.setter('height'))
    col = vbox(spacing=dp(2))
    col.add_widget(label(text, size=16, bold=True))
    if sub:
        col.add_widget(label(sub, size=13, color='sub'))
    t = Toggle(active=active)
    t.bind(active=lambda inst, v: on_change(v))
    holder = BoxLayout(orientation='vertical', size_hint=(None, None), width=dp(52), height=dp(48))
    holder.add_widget(Widget())
    holder.add_widget(t)
    holder.add_widget(Widget())
    add_row(row, [col, holder])
    return row


def section_title(text):
    return label(text, size=13, color='sub', bold=True, padding=[dp(4), 0])


def chips(options, value, on_change, cols=3, size=14):
    """Grid of exclusive chips (like Segmented but wrapping onto several rows)."""
    rows = (len(options) + cols - 1) // cols
    grid = GridLayout(cols=cols, spacing=dp(6), size_hint_y=None, height=rows * dp(42) + (rows - 1) * dp(6))
    btns = {}

    def paint():
        for v, b in btns.items():
            b.bg = C('primary') if v == state['v'] else C('card2')
            b.color = C('on_primary') if v == state['v'] else C('sub')

    state = {'v': value}

    def pick(v):
        state['v'] = v
        paint()
        on_change(v)

    opts = list(options)
    if rtl.UI_RTL:
        # keep the visual reading order right-to-left inside every row
        padded = opts + [None] * (rows * cols - len(opts))
        opts = []
        for r in range(rows):
            opts += list(reversed(padded[r * cols:(r + 1) * cols]))
    for opt in opts:
        if opt is None:
            grid.add_widget(Widget())
            continue
        v, text = opt
        b = RButton(raw=text, font_size=sp(size), radius=dp(12), size_hint_y=None, height=dp(42))
        b.bind(on_release=lambda inst, v=v: pick(v))
        btns[v] = b
        grid.add_widget(b)
    paint()
    return grid


# ======================================================================
# base screen
# ======================================================================
class BaseScreen(Screen):
    scrolling = True

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.app = app
        with self.canvas.before:
            self._bgc = Color(*C('bg'))
            self._bgr = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd_bg, size=self._upd_bg)
        if self.scrolling:
            self.sv = ScrollView(do_scroll_x=False, bar_width=dp(3),
                                 bar_color=alpha(C('sub'), 0.5))
            self.col = vbox(spacing=dp(12), padding=[dp(14), dp(14), dp(14), dp(30)])
            self.sv.add_widget(self.col)
            self.add_widget(self.sv)

    def _upd_bg(self, *a):
        self._bgr.pos = self.pos
        self._bgr.size = self.size

    def topbar_spec(self):
        return ('', 'menu', [])

    def on_pre_enter(self, *a):
        self.refresh()
        self.app.apply_topbar(self)

    def refresh(self):
        if self.scrolling:
            self.col.clear_widgets()
            self.build(self.col)
            self.sv.scroll_y = 1

    def build(self, col):
        pass


class IconTile(BoxLayout):
    """Rounded, softly tinted square with an icon in the middle."""

    def __init__(self, icon, color=None, size=dp(48), **kw):
        kw.setdefault('size_hint', (None, None))
        kw.setdefault('size', (size, size))
        kw.setdefault('padding', size * 0.23)
        super().__init__(**kw)
        col = list(color or C('primary'))[:3] + [1]
        with self.canvas.before:
            Color(*alpha(col, 0.18))
            self._r = RoundedRectangle(pos=self.pos, size=self.size, radius=[size * 0.3])
        self.bind(pos=self._u, size=self._u)
        self.add_widget(Icon(name=icon, color=col))

    def _u(self, *a):
        self._r.pos = self.pos
        self._r.size = self.size


# ======================================================================
# Home
# ======================================================================
def streak_message(n):
    if n <= 0:
        return tr('streak_msg0')
    if n < 3:
        return tr('streak_msg1')
    if n < 7:
        return tr('streak_msg2')
    if n < 30:
        return tr('streak_msg3')
    return tr('streak_msg4')


class HomeScreen(BaseScreen):
    def topbar_spec(self):
        return (tr('welcome'), 'menu', [], {'sub': tr('home_sub'), 'logo': True})

    def build(self, col):
        app, db = self.app, self.app.db
        st = db.stats()
        streak = db.get_streak()

        # --- streak + daily goal ---------------------------------------
        card = auto_card(padding=[dp(16), dp(14)], spacing=dp(12), radius=dp(22))
        row = hbox(dp(96), spacing=dp(14))
        flame = FlameWidget(days=streak, size_hint=(None, 1), width=dp(84))
        info = BoxLayout(orientation='vertical', spacing=dp(2))
        num_row = hbox(dp(48), spacing=dp(8))
        num = label(str(streak), size=40, bold=True, wrap=False, size_hint=(None, 1),
                    width=dp(30 + 22 * len(str(streak))))
        num.color = C('accent') if streak else C('sub')
        cap = label(tr('days_in_row'), size=16, color='sub', bold=True, wrap=False, size_hint=(1, 1))
        add_row(num_row, [num, cap])
        info.add_widget(num_row)
        info.add_widget(label(streak_message(streak), size=14, color='sub'))
        add_row(row, [flame, info])
        card.add_widget(row)
        card.add_widget(WeekStrip(db.week_activity(), tr('weekdays').split(',')))
        done, _ = db.today_answers()
        goal = max(1, db.get_int('daily_goal', 20))
        goal_row = hbox(dp(22))
        add_row(goal_row, [
            label(tr('daily_goal'), size=14, bold=True, wrap=False, size_hint_y=1),
            label('%d / %d' % (min(done, goal), goal), size=14, color='sub', bold=True,
                  wrap=False, size_hint_y=1, align='left' if rtl.UI_RTL else 'right')])
        card.add_widget(goal_row)
        card.add_widget(BarProgress(value=min(1.0, done / float(goal)),
                                    fg=C('success') if done >= goal else C('accent'),
                                    height=dp(10)))
        col.add_widget(card)

        # --- stats ---------------------------------------------------------
        srow = BoxLayout(orientation='horizontal', size_hint_y=None, height=dp(98), spacing=dp(10))
        stat_cards = []
        for val, cap_key, colr in ((st['words'], 'stat_words', 'primary'),
                                   (st['sentences'], 'stat_sentences', 'accent'),
                                   (st['mastered'], 'stat_mastered', 'success')):
            c = Card(padding=[dp(8), dp(10)], spacing=dp(2), radius=dp(18))
            c.add_widget(label(str(val), size=30, bold=True, color=colr, align='center',
                               wrap=False, size_hint_y=1))
            c.add_widget(label(tr(cap_key), size=13, color='sub', bold=True, align='center',
                               wrap=False, size_hint_y=None, height=dp(24)))
            stat_cards.append(c)
        add_row(srow, stat_cards)
        col.add_widget(srow)

        # --- continue learning ---------------------------------------------
        nxt = self._next_level()
        if nxt:
            data = data_bank.get_level(nxt)
            c = auto_card(padding=[dp(16), dp(14)], spacing=dp(8), radius=dp(22))
            c.add_widget(label(tr('continue_learning'), size=13, color='sub', bold=True))
            c.add_widget(label(tr('level_n', n=nxt) + ' — ' + level_title(nxt),
                               size=19, bold=True))
            m, t = db.level_mastery(nxt)
            c.add_widget(BarProgress(value=m / float(t), height=dp(8)))
            c.add_widget(button(tr('start_level'), lambda n=nxt: app.open_level(n), height=dp(46)))
            col.add_widget(c)

        # --- quick actions ---------------------------------------------------
        col.add_widget(section_title(tr('quick_actions')))
        grid = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, height=dp(2 * 62 + 10))
        acts = [
            ('mode_smart', 'replay', lambda: app.start_game({'mode': 'mixed', 'source': 'smart',
                                                             'n': 10, 'title': 'mode_smart'})),
            ('mode_flash', 'book', lambda: app.start_game({'mode': 'flash', 'source': 'bank',
                                                           'n': 10})),
            ('mode_daily', 'bolt', lambda: app.start_game({'mode': 'mixed', 'source': 'bank',
                                                           'n': 10, 'title': 'mode_daily'})),
            ('mode_mcq', 'check', lambda: app.pick_source('mcq')),
        ]
        if rtl.UI_RTL:
            acts = [acts[1], acts[0], acts[3], acts[2]]
        tint = {'mode_smart': FOLDER_COLORS[3], 'mode_flash': FOLDER_COLORS[0],
                'mode_daily': FOLDER_COLORS[4], 'mode_mcq': FOLDER_COLORS[2]}
        for key, icon, cb in acts:
            inner = BoxLayout(orientation='horizontal', padding=[dp(10), 0], spacing=dp(10))
            ic = centered(IconTile(icon, color=tint[key], size=dp(38)), (dp(38), dp(38)))
            tl = label(tr(key), size=14, bold=True, autoheight=False, size_hint_y=1)
            add_row(inner, [ic, tl])
            tile = TapCard(padding=0, spacing=0, radius=dp(18))
            tile.add_widget(inner)
            tile.bind(on_release=lambda inst, cb=cb: cb())
            grid.add_widget(tile)
        col.add_widget(grid)

        # --- word of the day --------------------------------------------------
        w = db.word_of_the_day()
        c = auto_card(padding=[dp(16), dp(14)], spacing=dp(6), radius=dp(22))
        c.add_widget(label(tr('word_of_day'), size=13, color='sub', bold=True))
        top = BoxLayout(orientation='horizontal', size_hint_y=None, spacing=dp(8))
        top.bind(minimum_height=top.setter('height'))
        en = label(w['en'], size=26, bold=True, color='primary')
        sp_btn = IconButton(name='speaker', color=C('primary'), size_hint=(None, None),
                            size=(dp(46), dp(46)))
        sp_btn.bind(on_release=lambda *_: app.speak(w['en']))
        add_row(top, [en, sp_btn])
        c.add_widget(top)
        c.add_widget(label(w['ar'], size=21, bold=True))
        c.add_widget(label(w['ex'], size=15, color='sub'))
        c.add_widget(label(w['ex_ar'], size=14, color='sub'))
        col.add_widget(c)

    def _next_level(self):
        db = self.app.db
        for lv in data_bank.group_ids('main') + data_bank.group_ids('extra'):
            if db.is_level_unlocked(lv) and not db.level_info(lv)['passed']:
                return lv
        return None


# ======================================================================
# Folders
# ======================================================================
class FoldersScreen(BaseScreen):
    def topbar_spec(self):
        return (tr('nav_folders'), 'menu', [('plus', self.add_folder)])

    def build(self, col):
        app = self.app
        folders = app.db.list_folders()
        if not folders:
            c = auto_card(padding=[dp(18), dp(22)], spacing=dp(12), radius=dp(22))
            ic = BoxLayout(size_hint_y=None, height=dp(76))
            ic.add_widget(Widget())
            ic.add_widget(IconTile('folder', color=FOLDER_COLORS[0], size=dp(72)))
            ic.add_widget(Widget())
            c.add_widget(ic)
            c.add_widget(label(tr('no_folders_title'), size=20, bold=True, align='center'))
            c.add_widget(label(tr('no_folders_text'), size=15, color='sub', align='center'))
            c.add_widget(button(tr('create_folder'), self.add_folder))
            c.add_widget(button(tr('add_sample'), self.add_sample, style='soft'))
            col.add_widget(c)
            return
        for f in folders:
            col.add_widget(self._folder_card(f))
        col.add_widget(button(tr('create_folder'), self.add_folder, style='ghost'))

    def _folder_card(self, f):
        app = self.app
        card = TapCard(size_hint_y=None, height=dp(104), padding=[dp(12), dp(10)],
                       spacing=dp(10), orientation='horizontal')
        card.bind(on_release=lambda *_: app.open_folder(f['id']))
        stripe = Widget(size_hint=(None, 1), width=dp(6))
        with stripe.canvas:
            Color(*FOLDER_COLORS[f['color'] % len(FOLDER_COLORS)])
            r = RoundedRectangle(pos=stripe.pos, size=stripe.size, radius=[dp(3)])
        stripe.bind(pos=lambda w, v: setattr(r, 'pos', v), size=lambda w, v: setattr(r, 'size', v))
        info = BoxLayout(orientation='vertical', spacing=dp(4))
        info.add_widget(label(f['name'], size=19, bold=True, wrap=False, size_hint_y=1))
        total = f['words'] + f['sentences']
        info.add_widget(label(tr('folder_counts', w=f['words'], s=f['sentences']), size=13,
                              color='sub', wrap=False, size_hint_y=None, height=dp(22)))
        info.add_widget(BarProgress(value=(f['mastered'] / float(total)) if total else 0,
                                    fg=C('success'), height=dp(7)))
        acts = BoxLayout(orientation='vertical', size_hint=(None, 1), width=dp(40),
                         spacing=dp(8))
        acts.add_widget(Widget())
        e = TintButton('edit', C('primary'), box=dp(38))
        e.bind(on_release=lambda *_: self.edit_folder(f))
        d = TintButton('trash', C('danger'), box=dp(38))
        d.bind(on_release=lambda *_: self.delete_folder(f))
        acts.add_widget(e)
        acts.add_widget(d)
        acts.add_widget(Widget())
        add_row(card, [stripe, info, acts])
        return card

    # -- actions ---------------------------------------------------------
    def add_sample(self):
        fid = self.app.db.create_sample_folder(self.app.lang)
        Toast.show(tr('sample_added'), 'ok')
        self.refresh()
        return fid

    def add_folder(self):
        self._folder_dialog(None)

    def edit_folder(self, f):
        self._folder_dialog(f)

    def _folder_dialog(self, f):
        db = self.app.db
        body = vbox(spacing=dp(12))
        name = FormField(tr('folder_name'), hint=tr('folder_name_hint'),
                         text=f['name'] if f else '')
        body.add_widget(name)
        body.add_widget(label(tr('folder_color'), size=13, color='sub', bold=True))
        dots = ColorDots(FOLDER_COLORS, f['color'] if f else 0, dot=dp(34))
        body.add_widget(dots)

        def save():
            if not name.text:
                Toast.show(tr('err_name'), 'error')
                return False
            if f:
                db.update_folder(f['id'], name.text, dots.selected)
            else:
                db.add_folder(name.text, dots.selected)
            self.refresh()
            self.app.refresh_drawer()
            return True

        Dialog(title=tr('edit_folder') if f else tr('new_folder'), body=body,
               buttons=[(tr('cancel'), None, 'soft'), (tr('save'), save, 'primary')]).open()

    def delete_folder(self, f):
        def do():
            self.app.db.delete_folder(f['id'])
            Toast.show(tr('folder_deleted'), 'ok')
            self.refresh()
        confirm(tr('delete_folder'), tr('delete_folder_q', name=f['name']), do,
                yes_text=tr('delete'), no_text=tr('cancel'), danger=True)


# ======================================================================
# Folder detail
# ======================================================================
class ItemRow(BoxLayout):
    """One word / sentence of a folder."""

    def __init__(self, app, item, on_change, edit_cb, **kw):
        super().__init__(orientation='vertical', size_hint_y=None, spacing=dp(4),
                         padding=[dp(6), dp(6)], **kw)
        self.bind(minimum_height=self.setter('height'))
        self.app, self.item, self.on_change, self.edit_cb = app, item, on_change, edit_cb
        word = item['kind'] == 'word'

        top = BoxLayout(orientation='horizontal', size_hint_y=None, spacing=dp(6))
        top.bind(minimum_height=top.setter('height'))
        en = label(item['en'], size=21 if word else 17, bold=True)
        if item['hl_main']:
            en.hl = list(HIGHLIGHTS[item['hl_main']])
        speak = IconButton(name='speaker', color=C('primary'), size_hint=(None, None),
                           size=(dp(42), dp(42)))
        speak.bind(on_release=lambda *_: app.speak(item['en']))
        add_row(top, [en, speak])
        self.add_widget(top)

        ar = label(item['ar'], size=19 if word else 16, color='primary', bold=word)
        self.add_widget(ar)
        if item['ex']:
            box = auto_card(bg_name='card2', padding=[dp(12), dp(8)], spacing=dp(3),
                            radius=dp(12))
            ex = label(item['ex'], size=15)
            if item['hl_example']:
                ex.hl = list(HIGHLIGHTS[item['hl_example']])
            box.add_widget(ex)
            if item['ex_ar']:
                box.add_widget(label(item['ex_ar'], size=13, color='sub'))
            self.add_widget(box)

        acts = hbox(dp(40), spacing=dp(2))
        star = IconButton(name='star', filled=bool(item['mastered']),
                          color=C('accent') if item['mastered'] else C('sub'),
                          size_hint=(None, 1), width=dp(40))
        star.bind(on_release=lambda *_: self._toggle_master())
        mark = IconButton(name='marker', color=C('sub'), size_hint=(None, 1), width=dp(40))
        mark.bind(on_release=lambda *_: self._highlight())
        edit_b = TintButton('edit', C('primary'), box=dp(34))
        edit_b.bind(on_release=lambda *_: edit_cb(item))
        trash_b = TintButton('trash', C('danger'), box=dp(34))
        trash_b.bind(on_release=lambda *_: self._delete())
        edit = centered(edit_b, (dp(38), dp(34)))
        trash = centered(trash_b, (dp(38), dp(34)))
        edit.width = trash.width = dp(38)
        edit_b.size = trash_b.size = (dp(34), dp(34))
        stats = label(tr('item_stats', c=item['correct'], w=item['wrong']), size=12, color='sub',
                      wrap=False, size_hint_y=1)
        add_row(acts, [stats, star, mark, edit, trash])
        self.add_widget(acts)

    def _toggle_master(self):
        self.app.db.set_mastered(self.item['id'], not self.item['mastered'])
        self.on_change()

    def _delete(self):
        def do():
            self.app.db.delete_item(self.item['id'])
            self.on_change()
        confirm(tr('delete_item'), tr('delete_item_q', name=self.item['en']), do,
                yes_text=tr('delete'), no_text=tr('cancel'), danger=True)

    def _highlight(self):
        item, db = self.item, self.app.db
        body = vbox(spacing=dp(12))
        target = {'v': 'main'}
        if item['ex']:
            seg = Segmented([('main', tr('hl_word') if item['kind'] == 'word' else tr('hl_sentence')),
                             ('example', tr('hl_example'))], 'main',
                            on_change=lambda v: target.update(v=v))
            body.add_widget(seg)
        body.add_widget(label(tr('hl_pick'), size=13, color='sub', bold=True))
        dlg = {}

        def pick(i):
            db.set_highlight(item['id'], target['v'], i)
            dlg['d'].dismiss()
            self.on_change()

        dots = ColorDots(HIGHLIGHTS, 0, on_change=pick, dot=dp(38))
        body.add_widget(dots)
        d = Dialog(title=tr('highlighter'), body=body, buttons=[(tr('close'), None, 'soft')])
        dlg['d'] = d
        d.open()


class FolderScreen(BaseScreen):
    PAGE = 40

    def __init__(self, app, **kw):
        super().__init__(app, **kw)
        self.filter = 'all'
        self.query = ''
        self.limit = self.PAGE

    def topbar_spec(self):
        f = self.app.db.get_folder(self.app.current_folder_id)
        return (f['name'] if f else '', 'back', [('plus', self.add_item)])

    def on_pre_enter(self, *a):
        self.filter, self.query, self.limit = 'all', '', self.PAGE
        super().on_pre_enter(*a)

    def build(self, col):
        app, db = self.app, self.app.db
        fid = app.current_folder_id
        f = db.get_folder(fid)
        if not f:
            return
        items_all = db.get_all_user_items(fid)
        words = sum(1 for i in items_all if i['kind'] == 'word')
        sents = len(items_all) - words
        mast = sum(1 for i in items_all if i['mastered'])

        head = auto_card(padding=[dp(16), dp(14)], spacing=dp(8), radius=dp(22))
        head.add_widget(label(tr('folder_counts', w=words, s=sents), size=15, bold=True))
        total = len(items_all)
        head.add_widget(BarProgress(value=(mast / float(total)) if total else 0,
                                    fg=C('success'), height=dp(8)))
        head.add_widget(label(tr('mastered_n', a=mast, b=total), size=13, color='sub'))
        head.add_widget(button(tr('practice'), self.practice, height=dp(46)))
        col.add_widget(head)

        self.seg = Segmented([('all', tr('f_all')), ('word', tr('f_words')),
                              ('sentence', tr('f_sentences')), ('mastered', tr('f_mastered'))],
                             self.filter, on_change=self._set_filter, size=13)
        col.add_widget(self.seg)
        self.search = ATextInput(hint=tr('search'), text=self.query, height=dp(46))
        self.search.bind(text=self._on_search)
        col.add_widget(self.search)

        self.list_card = auto_card(padding=[dp(10), dp(6)], spacing=0, radius=dp(20))
        col.add_widget(self.list_card)
        self._fill_list()

    def _set_filter(self, v):
        self.filter = v
        self.limit = self.PAGE
        self._fill_list()

    def _on_search(self, inst, text):
        self.query = text
        self.limit = self.PAGE
        self._fill_list()

    def _fill_list(self):
        app, db = self.app, self.app.db
        lc = self.list_card
        lc.clear_widgets()
        kind = self.filter if self.filter in ('word', 'sentence') else None
        items = db.get_items(app.current_folder_id, kind=kind, search=self.query or None,
                             mastered_only=(self.filter == 'mastered'))
        if not items:
            lc.add_widget(label(tr('no_items_here'), size=15, color='sub', align='center',
                                padding=[0, dp(16)]))
            return
        shown = items[:self.limit]
        for i, it in enumerate(shown):
            lc.add_widget(ItemRow(app, it, self._changed, self.edit_item))
            if i < len(shown) - 1:
                lc.add_widget(make_divider(app))
        if len(items) > self.limit:
            def more():
                self.limit += self.PAGE
                self._fill_list()
            lc.add_widget(button(tr('show_more', n=len(items) - self.limit), more, style='soft',
                                 height=dp(44)))

    def _changed(self):
        keep = self.sv.scroll_y
        self.refresh()
        self.sv.scroll_y = keep

    # -- add / edit ----------------------------------------------------------
    def add_item(self):
        self._item_dialog(None)

    def edit_item(self, item):
        self._item_dialog(item)

    def _item_dialog(self, item):
        db = self.app.db
        body = vbox(spacing=dp(10))
        kind = {'v': item['kind'] if item else 'word'}
        seg = Segmented([('word', tr('kind_word')), ('sentence', tr('kind_sentence'))], kind['v'],
                        on_change=lambda v: set_kind(v))
        body.add_widget(seg)
        f_en = FormField(tr('word_en'), hint='apple', text=item['en'] if item else '', vk_lang='en')
        f_ar = FormField(tr('word_ar'), hint=tr('word_ar_hint'), text=item['ar'] if item else '', vk_lang='ar')
        ex_box = vbox(spacing=dp(10))
        f_ex = FormField(tr('example_en'), hint='I eat an apple.', text=item['ex'] if item else '', vk_lang='en')
        f_exar = FormField(tr('example_ar'), hint=tr('example_ar_hint'),
                           text=item['ex_ar'] if item else '', vk_lang='ar')
        ex_box.add_widget(f_ex)
        ex_box.add_widget(f_exar)
        body.add_widget(f_en)
        body.add_widget(f_ar)

        def set_kind(v):
            kind['v'] = v
            f_en.caption.raw = tr('word_en') if v == 'word' else tr('sentence_en')
            f_ar.caption.raw = tr('word_ar') if v == 'word' else tr('sentence_ar')
            if v == 'word' and ex_box.parent is None:
                body.add_widget(ex_box)
            elif v == 'sentence' and ex_box.parent is not None:
                body.remove_widget(ex_box)

        if kind['v'] == 'word':
            body.add_widget(ex_box)
        else:
            set_kind('sentence')

        def save():
            if not f_en.text or not f_ar.text:
                Toast.show(tr('err_fields'), 'error')
                return False
            ex, exar = (f_ex.text, f_exar.text) if kind['v'] == 'word' else ('', '')
            if item:
                db.update_item(item['id'], kind['v'], f_en.text, f_ar.text, ex, exar)
            else:
                db.add_item(self.app.current_folder_id, kind['v'], f_en.text, f_ar.text, ex, exar)
            self._changed()
            return True

        Dialog(title=tr('edit_item') if item else tr('new_item'), body=body,
               buttons=[(tr('cancel'), None, 'soft'), (tr('save'), save, 'primary')]).open()

    def practice(self):
        self.app.pick_game_for_folder(self.app.current_folder_id)


# ======================================================================
# Levels
# ======================================================================
LEVEL_QUESTIONS = 20


def level_title(n):
    lv = data_bank.get_level(n)
    if not lv:
        return str(n)
    return lv['title_ar'] if rtl.UI_RTL else lv['title_en']


_level_label = level_title


def level_cfg(n):
    """One tap = a random mixed quiz over this level (all question types)."""
    return {'source': 'bank', 'levels': [n], 'mode': 'mixed', 'n': LEVEL_QUESTIONS,
            'level_test': n, 'title': 'mode_test'}


class LevelsScreen(BaseScreen):
    def topbar_spec(self):
        return (tr('nav_levels'), 'menu', [])

    def build(self, col):
        col.add_widget(label(tr('levels_intro', p=PASS_SCORE), size=14, color='sub'))
        for group, title_key, hint_key in (('main', 'track_main', 'track_main_d'),
                                           ('extra', 'track_extra', 'track_extra_d')):
            col.add_widget(section_title(tr(title_key)))
            col.add_widget(label(tr(hint_key), size=13, color='sub'))
            for lv in data_bank.LEVELS:
                if lv['group'] == group:
                    col.add_widget(self._level_card(lv))

    def _level_card(self, lv):
        app, db = self.app, self.app.db
        n = lv['id']
        unlocked = db.is_level_unlocked(n)
        info = db.level_info(n)
        m, t = db.level_mastery(n)
        card = TapCard(size_hint_y=None, height=dp(88), padding=[dp(12), dp(10)],
                       spacing=dp(10), orientation='horizontal')
        card.bind(on_release=lambda *_: self._tapped(n, unlocked))
        badge = Badge(FOLDER_COLORS[(n - 1) % len(FOLDER_COLORS)] if unlocked else C('card2'),
                      raw=str(n), font_size=sp(20), color=(1, 1, 1, 1) if unlocked else C('sub'))
        mid = BoxLayout(orientation='vertical', spacing=dp(4))
        mid.add_widget(label(level_title(n), size=16, bold=True, size_hint_y=1,
                             autoheight=False, color='text' if unlocked else 'sub'))
        mid.add_widget(BarProgress(value=m / float(t), fg=C('success'), height=dp(7)))
        sub = tr('level_progress', a=m, b=t)
        if info['passed']:
            sub += '  •  %d%%' % info['best_score']
        mid.add_widget(label(sub, size=12, color='sub', wrap=False,
                             size_hint_y=None, height=dp(20)))
        right = BoxLayout(orientation='horizontal', size_hint=(None, 1), width=dp(84),
                          spacing=dp(2))
        if not unlocked:
            right.add_widget(Widget())
            right.add_widget(centered(Icon(name='lock', color=C('sub')), (dp(24), dp(24))))
        else:
            words = IconButton(name='book', color=C('sub'), size_hint=(None, 1), width=dp(40))
            words.bind(on_release=lambda *_: self._words(n))
            right.add_widget(words)
            if info['passed']:
                right.add_widget(centered(Icon(name='star', filled=True, color=C('accent')),
                                          (dp(26), dp(26))))
            else:
                right.add_widget(centered(Icon(name='play', color=C('primary')),
                                          (dp(26), dp(26))))
        add_row(card, [badge, mid, right])
        return card

    def _tapped(self, n, unlocked):
        if not unlocked:
            prev = data_bank.prev_in_group(n)
            Toast.show(tr('level_locked', n=level_title(prev), p=PASS_SCORE), 'warn')
            return
        self.app.open_level(n)

    def _words(self, n):
        WordsSheet(self.app, n).open()


class WordsSheet:
    """The words of one level (with speaker) + 'add to my folders'."""

    def __init__(self, app, n):
        self.app, self.n = app, n
        items = app.db.bank_items([n], ('word',))
        body = vbox(spacing=dp(2))
        for it in items:
            row = BoxLayout(orientation='horizontal', size_hint_y=None, spacing=dp(6))
            row.bind(minimum_height=row.setter('height'))
            col = vbox(spacing=dp(1))
            col.add_widget(label(it['en'], size=16, bold=True))
            col.add_widget(label(it['ar'], size=15, color='primary'))
            sp_btn = IconButton(name='speaker', color=C('sub'), size_hint=(None, None),
                                size=(dp(38), dp(38)))
            sp_btn.bind(on_release=lambda inst, t=it['en']: self.app.speak(t))
            add_row(row, [col, sp_btn])
            body.add_widget(row)
            body.add_widget(Divider(style='solid', color=C('divider'), thickness=1, height=dp(8)))
        self.dlg = Dialog(title=tr('level_n', n=n) + ' — ' + level_title(n), body=body,
                          buttons=[(tr('copy_level_short'), self._copy, 'soft'),
                                   (tr('close'), None, 'primary')],
                          body_max=Window.height * 0.62)

    def open(self):
        self.dlg.open()

    def _copy(self):
        name = tr('level_n', n=self.n) + ' - ' + level_title(self.n)
        self.app.db.copy_level_to_folder(self.n, name)
        Toast.show(tr('level_copied'), 'ok')
        self.app.refresh_drawer()
        return True


# ======================================================================
# Challenges
# ======================================================================
CHALLENGES = [
    # key, icon, needs source dialog, base cfg
    ('mode_daily', 'bolt', True, {'mode': 'mixed', 'n': 10, 'title': 'mode_daily'}),
    ('mode_speed', 'play', True, {'mode': 'speed', 'time': 60, 'title': 'mode_speed'}),
    ('mode_survival', 'star', True, {'mode': 'survival', 'title': 'mode_survival'}),
    ('mode_match', 'levels', True, {'mode': 'match', 'n': 10}),
    ('mode_spell', 'edit', True, {'mode': 'spell', 'n': 8}),
    ('mode_rev', 'replay', True, {'mode': 'rev', 'n': 10}),
    ('mode_mcq', 'check', True, {'mode': 'mcq', 'n': 10}),
    ('mode_flash', 'book', True, {'mode': 'flash', 'n': 10}),
    ('mode_smart', 'star', False, {'mode': 'mixed', 'source': 'smart', 'n': 10,
                                   'title': 'mode_smart'}),
]


CHALLENGE_COLORS = {
    'mode_daily': FOLDER_COLORS[4], 'mode_speed': FOLDER_COLORS[1],
    'mode_survival': FOLDER_COLORS[6], 'mode_match': FOLDER_COLORS[3],
    'mode_spell': FOLDER_COLORS[5], 'mode_rev': FOLDER_COLORS[2],
    'mode_mcq': FOLDER_COLORS[0], 'mode_flash': FOLDER_COLORS[7],
    'mode_smart': FOLDER_COLORS[3],
}


class ChallengesScreen(BaseScreen):
    def topbar_spec(self):
        return (tr('nav_challenges'), 'menu', [])

    def build(self, col):
        app = self.app
        col.add_widget(label(tr('challenges_intro'), size=14, color='sub'))
        best_s = app.db.get_int('best_speed', 0)
        best_v = app.db.get_int('best_survival', 0)
        for key, icon, needs, cfg in CHALLENGES:
            card = TapCard(size_hint_y=None, height=dp(88), padding=[dp(14), dp(10)],
                           spacing=dp(14), orientation='horizontal')
            tile = centered(IconTile(icon, color=CHALLENGE_COLORS.get(key)), (dp(48), dp(48)))
            col_info = BoxLayout(orientation='vertical', spacing=dp(2))
            col_info.add_widget(label(tr(key), size=18, bold=True, wrap=False, size_hint_y=1))
            desc = tr(key + '_d')
            if key == 'mode_speed' and best_s:
                desc += '  •  ' + tr('best_n', n=best_s)
            if key == 'mode_survival' and best_v:
                desc += '  •  ' + tr('best_n', n=best_v)
            col_info.add_widget(label(desc, size=13, color='sub'))
            chev = centered(Icon(name='chevron', color=C('sub'), mirror=rtl.UI_RTL),
                            (dp(22), dp(22)))
            add_row(card, [tile, col_info, chev])
            card.bind(on_release=lambda inst, key=key, needs=needs, cfg=cfg: self._go(key, needs, cfg))
            col.add_widget(card)

    def _go(self, key, needs, cfg):
        app = self.app
        if not needs:
            app.start_game(dict(cfg))
            return
        app.pick_source(cfg['mode'], base=dict(cfg))


# ======================================================================
# Source picker + game picker dialogs
# ======================================================================
def source_dialog(app, mode, base=None, on_start=None):
    """Ask where the questions come from (system words / my words)."""
    db = app.db
    base = dict(base or {'mode': mode, 'n': 10})
    base['mode'] = mode
    state = {'source': 'bank', 'level': 0, 'folder': 0, 'kinds': 'both'}
    if not db.list_folders() and not db.get_all_user_items():
        pass
    body = vbox(spacing=dp(12))
    seg = Segmented([('bank', tr('src_system')), ('user', tr('src_mine'))], 'bank',
                    on_change=lambda v: (state.update(source=v), render()))
    body.add_widget(seg)
    dyn = vbox(spacing=dp(10))
    body.add_widget(dyn)
    kinds_box = vbox(spacing=dp(6))
    body.add_widget(kinds_box)

    def render():
        dyn.clear_widgets()
        if state['source'] == 'bank':
            dyn.add_widget(label(tr('src_system_hint'), size=13, color='sub'))
            opts = [(0, tr('progressive'))] + [(n, tr('level_short', n=n))
                                               for n in data_bank.level_ids()
                                               if db.is_level_unlocked(n)]
            dyn.add_widget(chips(opts, state['level'], lambda v: state.update(level=v), cols=3,
                                 size=13))
        else:
            folders = db.list_folders()
            if not folders:
                dyn.add_widget(label(tr('src_no_folders'), size=14, color='warn', bold=True))
            else:
                opts = [(0, tr('all_my_words'))] + [(f['id'], f['name']) for f in folders]
                dyn.add_widget(label(tr('src_pick_folder'), size=13, color='sub'))
                dyn.add_widget(chips(opts, state['folder'], lambda v: state.update(folder=v),
                                     cols=2, size=13))

    render()
    if mode not in ('spell', 'match'):
        kinds_box.add_widget(label(tr('content'), size=13, color='sub', bold=True))
        kinds_box.add_widget(Segmented([('both', tr('k_both')), ('word', tr('k_words')),
                                        ('sentence', tr('k_sentences'))], 'both',
                                       on_change=lambda v: state.update(kinds=v), size=13))

    def start():
        cfg = dict(base)
        cfg['source'] = state['source']
        if state['source'] == 'bank':
            cfg['levels'] = [state['level']] if state['level'] else None
        else:
            if not db.get_all_user_items(state['folder'] or None):
                Toast.show(tr('no_items'), 'warn')
                return False
            cfg['folder_id'] = state['folder'] or None
        cfg['kinds'] = {'both': ('word', 'sentence'), 'word': ('word',),
                        'sentence': ('sentence',)}[state['kinds']]
        if mode in ('spell', 'match'):
            cfg['kinds'] = ('word',)
        (on_start or app.start_game)(cfg)

    Dialog(title=tr('choose_source'), body=body,
           buttons=[(tr('cancel'), None, 'soft'), (tr('start'), start, 'primary')]).open()


def folder_game_dialog(app, folder_id):
    """Practice menu for one of the user's folders."""
    body = vbox(spacing=dp(8))
    holder = {}

    def go(mode, n):
        holder['d'].dismiss()
        app.start_game({'mode': mode, 'source': 'user', 'folder_id': folder_id, 'n': n,
                        'kinds': ('word',) if mode in ('spell', 'match') else ('word', 'sentence')})

    for key, mode, n in (('mode_flash', 'flash', 10), ('mode_mcq', 'mcq', 10),
                         ('mode_rev', 'rev', 10), ('mode_match', 'match', 10),
                         ('mode_spell', 'spell', 8), ('mode_mixed', 'mixed', 10)):
        body.add_widget(button(tr(key), lambda m=mode, k=n: go(m, k), style='soft', height=dp(48)))
    d = Dialog(title=tr('practice'), body=body, buttons=[(tr('close'), None, 'soft')])
    holder['d'] = d
    d.open()


# ======================================================================
# Game host
# ======================================================================
class GameScreen(BaseScreen):
    scrolling = False

    def __init__(self, app, **kw):
        super().__init__(app, **kw)
        self.game = None
        self.holder = BoxLayout()
        self.add_widget(self.holder)

    def topbar_spec(self):
        cfg = self.app.game_cfg or {}
        if cfg.get('level_test'):
            n = cfg['level_test']
            return (tr('level_n', n=n) + ' · ' + level_title(n), 'back', [])
        key = cfg.get('title') or 'mode_' + str(cfg.get('mode', 'mcq'))
        return (tr(key), 'back', [])

    def on_pre_enter(self, *a):
        self.app.apply_topbar(self)
        self.launch()

    def on_leave(self, *a):
        self.stop_game()

    def stop_game(self):
        if self.game is not None:
            try:
                self.game.stop()
            except Exception:
                pass
            self.game = None
        self.app.tts.stop()

    def launch(self):
        self.stop_game()
        self.holder.clear_widgets()
        self.app.apply_topbar(self)             # title follows the mode that is starting
        cfg = dict(self.app.game_cfg)
        mode = cfg.get('mode')
        if mode == 'flash':
            g = games.FlashcardGame(self.app, cfg, self.on_finish)
        elif mode == 'match':
            g = games.MatchGame(self.app, cfg, self.on_finish)
        else:
            g = games.QuizGame(self.app, cfg, self.on_finish)
        self.game = g
        self.holder.add_widget(g)
        if getattr(g.feeder, 'fallback', False):
            Toast.show(tr('smart_fallback'), 'info')
        Clock.schedule_once(lambda dt: g.start(), 0.05)

    def on_finish(self, res):
        app, db = self.app, self.app.db
        cfg = res['cfg']
        lines = []
        mode = cfg.get('mode')
        if mode in ('speed', 'survival'):
            key = 'best_' + mode
            best = db.get_int(key, 0)
            if res['score'] > best:
                db.set(key, res['score'])
                if res['score'] > 0:
                    lines.append((tr('new_record'), 'ok'))
            else:
                lines.append((tr('best_n', n=best), 'info'))
            lines.append((tr('best_combo', n=res.get('best_combo', 0)), 'info'))
        if cfg.get('level_test'):
            lvl = cfg['level_test']
            unlocked = db.save_level_result(lvl, res['pct'])
            if res['pct'] >= PASS_SCORE:
                lines.append((tr('test_passed', n=lvl), 'ok'))
                if unlocked:
                    lines.append((tr('level_unlocked', n=_level_label(unlocked)), 'ok'))
            else:
                lines.append((tr('test_failed', p=PASS_SCORE), 'bad'))
        good = res['pct'] >= 60
        app.sfx.play('win' if good else 'lose')
        self.holder.clear_widgets()
        self.game = None
        view = games.ResultView(app, res, on_again=self.launch, on_back=app.go_back,
                                extra_lines=lines)
        self.holder.add_widget(view)
        app.refresh_drawer()


# ======================================================================
# Settings
# ======================================================================
class SettingsScreen(BaseScreen):
    def topbar_spec(self):
        return (tr('nav_settings'), 'menu', [])

    def build(self, col):
        app, db = self.app, self.app.db

        # --- appearance -----------------------------------------------------
        col.add_widget(section_title(tr('s_appearance')))
        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(12))
        c.add_widget(label(tr('s_theme'), size=16, bold=True))
        c.add_widget(Segmented([('auto', tr('theme_auto')), ('dark', tr('theme_dark')),
                                ('light', tr('theme_light'))], db.get('theme'),
                               on_change=lambda v: self._set_rebuild('theme', v)))
        c.add_widget(label(tr('s_theme_hint'), size=13, color='sub'))
        c.add_widget(label(tr('s_language'), size=16, bold=True))
        c.add_widget(Segmented([('ar', 'العربية'), ('en', 'English')], db.get('lang'),
                               on_change=lambda v: self._set_rebuild('lang', v)))
        col.add_widget(c)

        # --- sound ---------------------------------------------------------------
        col.add_widget(section_title(tr('s_sound')))
        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(12))
        c.add_widget(switch_row(tr('s_sfx'), db.get_bool('sound'), self._set_sound,
                                sub=tr('s_sfx_d')))
        c.add_widget(switch_row(tr('s_autospeak'), db.get_bool('auto_speak'),
                                lambda v: db.set('auto_speak', '1' if v else '0'),
                                sub=tr('s_autospeak_d')))
        c.add_widget(button(tr('s_test_voice'), lambda: app.speak('Hello! Welcome to Lingora.'),
                            style='soft', height=dp(46)))
        col.add_widget(c)

        # --- dividers ---------------------------------------------------------------
        col.add_widget(section_title(tr('s_dividers')))
        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(12))
        c.add_widget(switch_row(tr('s_show_div'), db.get_bool('show_dividers'),
                                lambda v: self._set_div('show_dividers', '1' if v else '0'),
                                sub=tr('s_show_div_d')))
        c.add_widget(label(tr('s_div_style'), size=15, bold=True))
        c.add_widget(chips([('solid', tr('div_solid')), ('dashed', tr('div_dashed')),
                            ('dotted', tr('div_dotted')), ('fade', tr('div_fade')),
                            ('ornament', tr('div_ornament'))], db.get('divider_style'),
                           lambda v: self._set_div('divider_style', v), cols=3, size=13))
        c.add_widget(label(tr('s_div_width'), size=15, bold=True))
        c.add_widget(Segmented([('1', tr('thin')), ('2', tr('medium')), ('3', tr('thick'))],
                               db.get('divider_width'),
                               on_change=lambda v: self._set_div('divider_width', v)))
        c.add_widget(label(tr('s_div_color'), size=15, bold=True))
        c.add_widget(Segmented([('neutral', tr('neutral')), ('accent', tr('accent'))],
                               db.get('divider_color'),
                               on_change=lambda v: self._set_div('divider_color', v)))
        self.preview = vbox(spacing=0, padding=[dp(8), dp(4)])
        self._fill_preview()
        c.add_widget(self.preview)
        col.add_widget(c)

        # --- learning -------------------------------------------------------------------
        col.add_widget(section_title(tr('s_learning')))
        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(12))
        c.add_widget(label(tr('s_goal'), size=15, bold=True))
        c.add_widget(Segmented([(str(n), str(n)) for n in (10, 20, 30, 50)],
                               str(db.get_int('daily_goal', 20)),
                               on_change=lambda v: db.set('daily_goal', v)))
        c.add_widget(label(tr('s_round'), size=15, bold=True))
        c.add_widget(Segmented([(str(n), str(n)) for n in (5, 10, 15, 20)],
                               str(db.get_int('round_size', 10)),
                               on_change=lambda v: db.set('round_size', v)))
        c.add_widget(label(tr('s_kb_mode'), size=15, bold=True))
        c.add_widget(Segmented([('auto', tr('kb_auto')), ('inapp', tr('kb_inapp')),
                                ('phone', tr('kb_phone'))],
                               db.get('kb_mode') or 'auto', on_change=self._set_kb_mode))
        c.add_widget(label(tr('s_kb_mode_d'), size=13, color='sub'))
        c.add_widget(button(tr('kb_diag'), self._kb_diag, style='soft', height=dp(44)))
        c.add_widget(switch_row(tr('s_unlock_all'), db.get_bool('unlock_all'),
                                lambda v: db.set('unlock_all', '1' if v else '0'),
                                sub=tr('s_unlock_all_d')))
        col.add_widget(c)

        # --- backup ---------------------------------------------------------------------------
        col.add_widget(section_title(tr('s_backup')))
        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(10))
        c.add_widget(label(tr('s_backup_d'), size=13, color='sub'))
        c.add_widget(button(tr('s_export'), self.export_backup, height=dp(48)))
        c.add_widget(button(tr('s_import'), self.import_dialog, style='soft', height=dp(48)))
        col.add_widget(c)

        # --- data -----------------------------------------------------------------------------------
        col.add_widget(section_title(tr('s_data')))
        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(10))
        c.add_widget(button(tr('s_reset_progress'), lambda: confirm(
            tr('s_reset_progress'), tr('s_reset_progress_q'), self._reset_progress,
            yes_text=tr('confirm'), no_text=tr('cancel'), danger=True), style='ghost',
            height=dp(46)))
        c.add_widget(button(tr('s_reset_all'), lambda: confirm(
            tr('s_reset_all'), tr('s_reset_all_q'), self._reset_all,
            yes_text=tr('delete'), no_text=tr('cancel'), danger=True), style='danger',
            height=dp(46)))
        col.add_widget(c)

        c = auto_card(padding=[dp(14), dp(14)], spacing=dp(4))
        c.add_widget(label('Lingora  •  v1.0', size=15, bold=True, align='center'))
        c.add_widget(label(tr('about'), size=13, color='sub', align='center'))
        col.add_widget(c)

    # -- setting handlers -------------------------------------------------------
    def _set_rebuild(self, key, value):
        self.app.db.set(key, value)
        Clock.schedule_once(lambda dt: self.app.rebuild('settings'), 0.05)

    def _set_sound(self, v):
        self.app.db.set('sound', '1' if v else '0')
        self.app.sfx.enabled = bool(v)
        if v:
            self.app.sfx.play('correct')

    def _set_kb_mode(self, v):
        self.app.db.set('kb_mode', v)
        widgets_mod.VK['mode'] = v

    def _kb_diag(self):
        from services import keyboard_diagnostics
        body = vbox(spacing=dp(2))
        for ln in keyboard_diagnostics():
            body.add_widget(label(ln, size=12, color='sub'))
        Dialog(title=tr('kb_diag'), body=body, buttons=[(tr('close'), None, 'primary')]).open()

    def _set_div(self, key, value):
        self.app.db.set(key, value)
        self._fill_preview()

    def _fill_preview(self):
        self.preview.clear_widgets()
        self.preview.add_widget(label(tr('s_preview_a'), size=15, padding=[0, dp(8)]))
        self.preview.add_widget(make_divider(self.app))
        self.preview.add_widget(label(tr('s_preview_b'), size=15, padding=[0, dp(8)]))

    # -- backup ---------------------------------------------------------------------------
    def export_backup(self):
        app = self.app
        path = app.storage.new_backup_path()
        if not path:
            Toast.show(tr('err_storage'), 'error')
            return
        try:
            app.db.write_backup_file(path)
        except Exception as e:                       # noqa: BLE001
            Toast.show(tr('err_export', e=str(e)), 'error')
            return
        body = vbox(spacing=dp(8))
        body.add_widget(label(tr('export_ok'), size=15))
        body.add_widget(label(path, size=13, color='primary', align='left'))
        Dialog(title=tr('s_export'), body=body, buttons=[(tr('close'), None, 'primary')]).open()

    def import_dialog(self):
        app = self.app
        body = vbox(spacing=dp(10))
        path_field = FormField(tr('import_path'), hint='/storage/emulated/0/Download/...json', vk_lang='en')
        path_field.input.halign = 'left'
        body.add_widget(label(tr('import_found'), size=13, color='sub', bold=True))
        found = app.storage.list_backups()
        if not found:
            body.add_widget(label(tr('import_none'), size=14, color='sub'))
        for p, mtime, size in found[:8]:
            when = time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))
            b = button(os.path.basename(p) + '\n' + when, None, style='soft', size=13,
                       height=dp(54))
            b.bind(on_release=lambda inst, p=p: setattr(path_field.input, 'text', p))
            body.add_widget(b)
        body.add_widget(path_field)
        body.add_widget(label(tr('import_modes'), size=12, color='sub'))

        def run(mode):
            path = path_field.text
            if not path:
                Toast.show(tr('err_path'), 'error')
                return False
            try:
                data = app.db.read_backup_file(path)
                stats = app.db.import_all(data, mode)
            except Exception as e:                   # noqa: BLE001
                Toast.show(tr('err_import', e=str(e)[:80]), 'error', 3.5)
                return False
            Toast.show(tr('import_ok', f=stats['folders'], i=stats['items']), 'ok', 3)
            Clock.schedule_once(lambda dt: app.rebuild('settings'), 0.1)
            return True

        def replace():
            if not path_field.text:
                Toast.show(tr('err_path'), 'error')
                return False
            confirm(tr('import_replace'), tr('import_replace_q'), lambda: run('replace'),
                    yes_text=tr('confirm'), no_text=tr('cancel'), danger=True)
            return True

        Dialog(title=tr('s_import'), body=body,
               buttons=[(tr('import_merge'), lambda: run('merge'), 'primary'),
                        (tr('import_replace'), replace, 'danger')]).open()

    def _reset_progress(self):
        self.app.db.reset_progress()
        Toast.show(tr('done'), 'ok')
        self.app.rebuild('settings')

    def _reset_all(self):
        self.app.db.reset_everything()
        Toast.show(tr('done'), 'ok')
        self.app.rebuild('settings')
