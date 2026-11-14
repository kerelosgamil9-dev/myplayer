[app]
title = Pro Player
package.name = proplayer
package.domain = org.proplayer
source.dir = .
source.include_exts = py,png,jpg,ttf,json
source.exclude_dirs = tests,tools,.github,bin,.buildozer,__pycache__
version = 1.0.0

# ffpyplayer = FFmpeg based decoding (software), pyjnius/android = system access
requirements = python3,kivy==2.3.0,ffpyplayer,pyjnius,android

orientation = portrait
fullscreen = 0
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
android.presplash_color = #000000

# Permissions: media read (API 33+ uses READ_MEDIA_VIDEO, older uses READ_EXTERNAL_STORAGE)
android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,READ_MEDIA_VIDEO,VIBRATE,WAKE_LOCK

android.api = 33
android.minapi = 24
android.ndk = 25b
android.ndk_api = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.logcat_filters = *:S python:D

[buildozer]
log_level = 2
warn_on_root = 1
