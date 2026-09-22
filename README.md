# Bulk Video Downloader — Android 1.0.0

A Kivy + yt-dlp Android app for reading a webpage, finding individual video pages, selecting them, and downloading them in parallel.

## What this version does

1. Paste a webpage URL.
2. Read the page.
3. Find individual video-page links.
4. Select the videos you want.
5. Download them in parallel.
6. Keep each batch in its own folder.
7. Save the source links in `video_links.txt`.

The Android version deliberately does **not** include Telegram code or desktop-only dependencies.

## Important

This project is source code, not an APK. Build it once to create the APK, then install that APK on your phone.

## Build an APK with GitHub Actions

The easiest way to get a ready-to-install APK is to push this project to GitHub and let the workflow build it for you.

1. Create a GitHub repository for this project.
2. Push the files.
3. Open the **Actions** tab.
4. Run **Build Android APK**.
5. Download the `bulk-video-downloader-apk` artifact when the job finishes.

The workflow lives in `.github/workflows/android-apk.yml` and uploads the APK automatically.

## Optional local build with WSL Ubuntu

> Note: the desktop/Kivy environment is best installed with Python 3.12 or 3.13.
> This workspace currently has Python 3.14, which may not have a compatible Kivy wheel yet.
> For APK builds, GitHub Actions is the recommended path.

Install WSL2 + Ubuntu, then inside the project directory:

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv build-essential libffi-dev libssl-dev
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade buildozer cython
./build_android.sh
```

If you prefer to launch the local build from Windows PowerShell, use:

```powershell
Set-Location C:\Users\m6322\PyCharmMiscProject\BulkVideoDownloader_Android
.\build_android.ps1
```

The APK will be in `bin/` locally or in the GitHub Actions artifact.

For a clean local rebuild, run:

```powershell
.\build_android.ps1 -Clean
```

## Install on Android

Copy the generated APK to your phone, open it, allow Android to install it if prompted, and launch **Bulk Video Downloader**.

## Storage

Downloads are stored inside the app's private storage under:

```text
Android app storage/files/downloads/
```

This is intentional for Android compatibility. A later version can add a user-selectable public Downloads folder.

## Supported page discovery

The built-in page scanner recognizes links shaped like:

```text
/videos/123/example/
/video/123/example/
```

If a site generates links only after JavaScript runs, the simple page scanner may not see them. yt-dlp is used as a fallback where supported.

## Android-safe download behavior

The default format is:

```text
best[ext=mp4]/best
```

This avoids making FFmpeg a mandatory Android dependency. The optional thumbnail feature uses FFmpeg only when an FFmpeg binary is available.

## Legal / site restrictions

Only download media that you have permission to download and that the source site permits you to download. Respect copyright, authentication, robots/terms, and access controls.
