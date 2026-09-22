# Bulk Video Downloader — Android 1.0

A Kivy + yt-dlp bulk downloader designed for Android. It can accept:

- a listing/page URL and discover video links;
- a direct video URL;
- multiple video URLs pasted one per line.

## Important Android storage fix

Older versions saved downloads under Kivy's private `user_data_dir`, which is why videos could appear to be "missing" from the phone's normal Downloads folder. This version downloads into a temporary app-specific staging directory and then publishes each completed file into:

```text
Download/Bulk Video Downloader/Batch_YYYYMMDD_HHMMSS/
```

On Android 10+ this uses `MediaStore.Downloads`, so the finished file is in shared storage and remains after uninstall. On Android 9 and older it uses the public Downloads directory after requesting the legacy storage permission.

Android's scoped-storage model recommends shared storage/MediaStore for user files that should be visible outside the app. urlAndroid shared storage documentationhttps://developer.android.com/training/data-storage/shared/media

## Reliability changes

The downloader now:

- removes the hard requirement for `/videos/<number>/...` URLs;
- detects common video/watch/clip/reel/media/episode URLs and direct media URLs;
- uses yt-dlp as a second discovery layer;
- supports multiple pasted URLs;
- retries extraction, file access and media fragments;
- uses a browser-like User-Agent plus Referer/Origin when available;
- tries multiple format strategies when the first one fails;
- prefers single-file MP4 when a separate audio/video merge is unavailable;
- resumes partial downloads when possible;
- limits concurrent workers to reduce server throttling;
- writes `video_links.txt` and `results.json` for each batch;
- reports failures individually instead of hiding them in a single status line.

yt-dlp recommends FFmpeg/ffprobe for merging separate video and audio streams. This Android build therefore includes the FFmpeg recipe. urlyt-dlp documentationhttps://github.com/yt-dlp/yt-dlp

## Build with GitHub Actions

1. Push this folder to GitHub.
2. Open **Actions → Build Android APK**.
3. Click **Run workflow**.
4. Download the `bulk-video-downloader-apk` artifact.
5. Install the APK on your phone.

If a build fails, the workflow uploads a `buildozer-build-log` artifact containing the complete log.

## Limits

This app does not bypass DRM, paywalls, private access controls, or site authentication. Some websites intentionally block automated clients; those may still require an authenticated cookies file or another supported access method.
