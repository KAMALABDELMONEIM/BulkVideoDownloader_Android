#!/usr/bin/env bash
set -euo pipefail

# Build a debug APK from Linux/WSL Ubuntu.
cd "$(dirname "$0")"

if ! command -v buildozer >/dev/null 2>&1; then
  echo "Buildozer is not installed."
  echo "Install with: python3 -m pip install --upgrade buildozer setuptools cython"
  exit 1
fi

python3 -m py_compile main.py downloader.py ffmpeg_manager.py
autopep8 --version >/dev/null 2>&1 || true
python3 tests_smoke.py

buildozer -v android debug

echo
echo "APK files:"
ls -lh bin/*.apk
