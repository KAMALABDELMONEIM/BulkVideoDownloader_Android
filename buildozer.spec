[app]
title = Bulk Video Downloader
package.name = bulkvideodownloader
package.domain = org.kamal
source.dir = .
source.include_exts = py,png,jpg,jpeg,atlas,txt,json
source.exclude_dirs = .git,bin,.buildozer,tests,__pycache__,.venv
version = 1.0.0
requirements = python3,kivy,requests,certifi,yt-dlp,pyjnius,ffmpeg
orientation = portrait
fullscreen = 0
android.archs = arm64-v8a
android.minapi = 24
android.api = 36
android.ndk = 28c
android.permissions = INTERNET,WAKE_LOCK,WRITE_EXTERNAL_STORAGE
p4a.branch = develop

[buildozer]
log_level = 2
warn_on_root = 1
