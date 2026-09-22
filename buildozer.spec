[app]
title = Bulk Video Downloader
package.name = bulkvideodownloader
package.domain = org.kamal
source.dir = .
source.include_exts = py,png,jpg,jpeg,atlas,txt,json
source.exclude_dirs = .git,bin,.buildozer,tests,__pycache__,.venv
version = 1.0.0
requirements = python3,kivy,requests,certifi,yt-dlp,pyjnius
orientation = portrait
fullscreen = 0
android.archs = arm64-v8a
android.minapi = 23
android.api = 34
android.ndk = 25b
android.accept_sdk_license = True
android.permissions = INTERNET,WAKE_LOCK,WRITE_EXTERNAL_STORAGE
p4a.branch = v2024.01.21

[buildozer]
log_level = 2
warn_on_root = 1
