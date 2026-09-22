#!/usr/bin/env bash
set -euo pipefail

command -v buildozer >/dev/null 2>&1 || {
  echo "Buildozer is not installed."
  echo "python3 -m pip install buildozer==1.5.0 cython==0.29.36"
  exit 1
}

python3 -m py_compile main.py downloader.py android_storage.py ffmpeg_manager.py
python3 tests_smoke.py
rm -rf .buildozer
buildozer -v android debug
ls -lh bin/*.apk
