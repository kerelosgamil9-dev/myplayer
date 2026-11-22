[app]

# ---- identity ---------------------------------------------------------------
title = Lingora
package.name = lingora
package.domain = org.lingora
version = 1.0.0

# ---- icon / splash ------------------------------------------------------------
icon.filename = %(source.dir)s/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/icon_bg.png
presplash.filename = %(source.dir)s/presplash.png
presplash.color = #151515
android.presplash_color = #151515

# ---- sources ----------------------------------------------------------------
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,json,txt
source.include_patterns = fonts/*
source.exclude_dirs = .github, bin, .buildozer, __pycache__, tests
source.exclude_patterns = *.pyc, *.db, *.md

# ---- requirements -------------------------------------------------------------
# pure Kivy (no KivyMD).  pyjnius + android: Text-to-Speech, permissions, night mode
# plyer: optional fallback for Text-to-Speech
requirements = python3==3.11.5,hostpython3==3.11.5,kivy==2.3.0,pyjnius,android,plyer

# ---- display ------------------------------------------------------------------------
orientation = portrait
fullscreen = 0
android.window_softinput_mode = adjustNothing

# ---- android -------------------------------------------------------------------------
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 34
android.minapi = 21
android.ndk = 25b
android.ndk_api = 21
android.archs = arm64-v8a, armeabi-v7a
android.accept_sdk_license = True

# pin python-for-android to a release that matches Kivy 2.3.0 / Python 3.11
p4a.branch = v2024.01.21
android.allow_backup = True
android.logcat_filters = *:S python:D

[buildozer]
log_level = 2
warn_on_root = 1
