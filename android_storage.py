from __future__ import annotations

import mimetypes
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PublishedFile:
    uri: str = ""
    path: str = ""
    display_path: str = ""


def _android_objects():
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Build = autoclass("android.os.Build")
        return PythonActivity, Build
    except Exception:
        return None, None


def is_android() -> bool:
    activity, _ = _android_objects()
    return activity is not None


def sdk_int() -> int:
    _, Build = _android_objects()
    if Build is None:
        return 0
    return int(Build.VERSION.SDK_INT)


def _context():
    activity, _ = _android_objects()
    if activity is None:
        return None
    return activity.mActivity


def request_legacy_storage_permission() -> bool:
    """Request write permission on Android 9 and older. Modern Android uses MediaStore."""
    if not is_android() or sdk_int() >= 29:
        return True
    try:
        from android.permissions import Permission, check_permission, request_permissions

        if check_permission(Permission.WRITE_EXTERNAL_STORAGE):
            return True
        request_permissions([Permission.WRITE_EXTERNAL_STORAGE])
        # Android presents the permission dialog asynchronously. Assume the request
        # was launched successfully; a second check can be made when the user starts
        # the next download.
        return True
    except Exception:
        return False


def staging_root() -> Path:
    """Use app-private external storage on Android, not the app's internal data directory."""
    if is_android():
        ctx = _context()
        if ctx is not None:
            try:
                base = ctx.getExternalFilesDir("Download")
                if base is not None:
                    path = Path(str(base.getAbsolutePath())) / "staging"
                    path.mkdir(parents=True, exist_ok=True)
                    return path
            except Exception:
                pass
    path = Path.home() / "Downloads" / "Bulk Video Downloader" / ".staging"
    path.mkdir(parents=True, exist_ok=True)
    return path


def public_location(batch_name: str) -> str:
    return f"Download/Bulk Video Downloader/{batch_name}/"


def _copy_stream(source: Path, output, chunk_size: int = 1024 * 1024) -> None:
    with source.open("rb") as src:
        while True:
            chunk = src.read(chunk_size)
            if not chunk:
                break
            output.write(chunk)


def _publish_mediastore(source: Path, batch_name: str, mime_type: Optional[str] = None) -> PublishedFile:
    from jnius import autoclass

    ctx = _context()
    if ctx is None:
        raise RuntimeError("Android application context is unavailable")

    MediaStore = autoclass("android.provider.MediaStore")
    ContentValues = autoclass("android.content.ContentValues")
    Build = autoclass("android.os.Build")

    resolver = ctx.getContentResolver()
    downloads = MediaStore.Downloads.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY)

    name = source.name
    mime = mime_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
    relative_path = f"Download/Bulk Video Downloader/{batch_name}/"

    values = ContentValues()
    values.put(MediaStore.Downloads.DISPLAY_NAME, name)
    values.put(MediaStore.Downloads.MIME_TYPE, mime)
    values.put(MediaStore.Downloads.RELATIVE_PATH, relative_path)
    if int(Build.VERSION.SDK_INT) >= 29:
        values.put(MediaStore.Downloads.IS_PENDING, 1)

    uri = resolver.insert(downloads, values)
    if uri is None:
        raise RuntimeError("Android MediaStore refused the file")

    output = None
    try:
        output = resolver.openOutputStream(uri, "w")
        if output is None:
            raise RuntimeError("Could not open the Android Downloads output stream")
        _copy_stream(source, output)
        try:
            output.flush()
        except Exception:
            pass
    except Exception:
        try:
            resolver.delete(uri, None, None)
        except Exception:
            pass
        raise
    finally:
        try:
            if output is not None:
                output.close()
        except Exception:
            pass

    if int(Build.VERSION.SDK_INT) >= 29:
        published = ContentValues()
        published.put(MediaStore.Downloads.IS_PENDING, 0)
        updated = resolver.update(uri, published, None, None)
        if updated <= 0:
            try:
                resolver.delete(uri, None, None)
            except Exception:
                pass
            raise RuntimeError("Android could not publish the downloaded file")

    try:
        source.unlink()
    except OSError:
        pass

    return PublishedFile(
        uri=str(uri.toString()),
        display_path=f"{relative_path}{name}",
    )


def _publish_legacy(source: Path, batch_name: str) -> PublishedFile:
    if not request_legacy_storage_permission():
        raise PermissionError("Storage permission was not granted")

    from jnius import autoclass

    Environment = autoclass("android.os.Environment")
    downloads = Path(str(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS).getAbsolutePath()))
    target_dir = downloads / "Bulk Video Downloader" / batch_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    source.unlink(missing_ok=True)
    return PublishedFile(path=str(target), display_path=str(target))


def publish_file(source: Path, batch_name: str, mime_type: Optional[str] = None) -> PublishedFile:
    source = Path(source)
    if not source.exists() or source.stat().st_size <= 0:
        raise FileNotFoundError(f"Downloaded file is missing or empty: {source}")
    if is_android() and sdk_int() >= 29:
        return _publish_mediastore(source, batch_name, mime_type=mime_type)
    if is_android():
        return _publish_legacy(source, batch_name)

    # Desktop fallback: use a normal public Downloads folder.
    target_dir = Path.home() / "Downloads" / "Bulk Video Downloader" / batch_name
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    shutil.copy2(source, target)
    return PublishedFile(path=str(target), display_path=str(target))


def open_uri(uri: str, mime_type: str = "video/*") -> bool:
    if not uri or not is_android():
        return False
    try:
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        Uri = autoclass("android.net.Uri")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(Uri.parse(uri), mime_type)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        PythonActivity.mActivity.startActivity(intent)
        return True
    except Exception:
        return False
