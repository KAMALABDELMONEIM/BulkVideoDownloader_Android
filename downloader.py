from __future__ import annotations

import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

import requests

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Mobile Safari/537.36"
)

VIDEO_EXTENSIONS = {".mp4", ".m4v", ".webm", ".mkv", ".mov", ".avi", ".flv", ".ts", ".m3u8", ".mpd"}
VIDEO_PATH_WORDS = ("/video/", "/videos/", "/watch/", "/clip/", "/clips/", "/reel/", "/reels/", "/media/", "/episode/", "/episodes/")
HREF_RE = re.compile(r"href\s*=\s*([\"'])(.*?)\1", re.I | re.S)
URL_RE = re.compile(r"https?://[^\"'< >\s]+", re.I)


@dataclass
class VideoCandidate:
    url: str
    title: str = ""
    source: str = "page"


@dataclass
class DownloadResult:
    url: str
    ok: bool
    filepath: str = ""
    title: str = ""
    error: str = ""
    location: str = ""


@dataclass
class WebPage:
    url: str
    title: str = ""
    text: str = ""


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    return re.sub(r"\s+", " ", value).strip()


def _clean_title(value: str) -> str:
    return _clean_text(value)[:180]


def _is_http_url(value: str) -> bool:
    return value.lower().startswith(("http://", "https://"))


def is_direct_media_url(url: str) -> bool:
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)


def _is_probable_video_page(url: str) -> bool:
    try:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/").lower()
    except Exception:
        return False
    if is_direct_media_url(url):
        return True
    if any(word in path for word in VIDEO_PATH_WORDS):
        return True
    if re.search(r"/(?:videos?|clips?|reels?)/\d+(?:/|$)", path):
        return True
    return False


def _dedupe_key(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")


class _PageTextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_skip = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP:
            self.in_skip += 1
        elif tag == "title":
            self.in_title = True
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "br"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP and self.in_skip:
            self.in_skip -= 1
        elif tag == "title":
            self.in_title = False
        elif tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "br"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self.in_skip:
            return
        if self.in_title:
            self.title_parts.append(data)
        self.text_parts.append(data)


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "a":
            return
        attrs_dict = {str(k).lower(): str(v) for k, v in attrs if v is not None}
        self._href = attrs_dict.get("href")
        self._text = []
        self._depth = 1

    def handle_startendtag(self, tag, attrs):
        if tag.lower() == "a":
            attrs_dict = {str(k).lower(): str(v) for k, v in attrs if v is not None}
            href = attrs_dict.get("href")
            if href:
                self.links.append((href, ""))

    def handle_data(self, data):
        if self._depth:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() != "a" or not self._depth:
            return
        if self._href:
            self.links.append((self._href, _clean_text(" ".join(self._text))))
        self._href = None
        self._text = []
        self._depth = 0


def _new_session(referer: str = "") -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
    )
    if referer:
        session.headers["Referer"] = referer
    return session


def read_webpage(page_url: str, timeout: int = 30) -> WebPage:
    if not _is_http_url(page_url):
        raise ValueError("Webpage URL must start with http:// or https://")
    response = _new_session().get(page_url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()

    parser = _PageTextParser()
    parser.feed(response.text)
    parser.close()
    text = re.sub(r"[ \t]+", " ", "".join(parser.text_parts))
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()
    return WebPage(response.url, _clean_title(" ".join(parser.title_parts)), text)


def _yt_dlp_candidates(listing_url: str, progress=None) -> list[VideoCandidate]:
    if yt_dlp is None:
        return []
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "noplaylist": False,
        "http_headers": {"Referer": listing_url, "User-Agent": DEFAULT_USER_AGENT},
        "socket_timeout": 30,
        "extractor_retries": 2,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(listing_url, download=False) or {}

    candidates: list[VideoCandidate] = []
    entries = info.get("entries")
    if entries:
        for entry in entries:
            if not entry:
                continue
            candidate = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
            if candidate and _is_http_url(str(candidate)):
                candidates.append(VideoCandidate(str(candidate), _clean_title(str(entry.get("title") or "")), "yt-dlp"))
    else:
        webpage = info.get("webpage_url") or info.get("original_url")
        if webpage and _is_http_url(str(webpage)):
            candidates.append(VideoCandidate(str(webpage), _clean_title(str(info.get("title") or "")), "yt-dlp"))
    return candidates


def extract_video_page_links(
    listing_url: str,
    timeout: int = 30,
    progress: Optional[Callable[[str], None]] = None,
) -> list[VideoCandidate]:
    if not _is_http_url(listing_url):
        raise ValueError("Listing URL must start with http:// or https://")
    if progress:
        progress("Loading webpage and scanning links…")

    response = _new_session(listing_url).get(listing_url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    source = html.unescape(response.text.replace("\\/", "/"))

    found: dict[str, VideoCandidate] = {}

    parser = _LinkParser()
    try:
        parser.feed(source)
        parser.close()
    except Exception:
        parser.links = []

    # Prefer explicit video-looking links. Also use link text as a title.
    for href, label in parser.links:
        href = html.unescape(href).strip()
        if not href or href.lower().startswith(("javascript:", "#", "mailto:", "tel:")):
            continue
        absolute = urljoin(response.url, href).split("#", 1)[0]
        if not _is_http_url(absolute):
            continue
        if _is_probable_video_page(absolute) or any(word in label.lower() for word in ("video", "watch", "play", "clip", "reel")):
            key = _dedupe_key(absolute)
            if key not in found:
                found[key] = VideoCandidate(absolute, _clean_title(label), "link")

    # JSON/plain URLs are useful for lazy-loaded video cards.
    for match in URL_RE.findall(source):
        match = html.unescape(match).rstrip(",.;)]}\"")
        if _is_http_url(match) and _is_probable_video_page(match):
            key = _dedupe_key(match)
            found.setdefault(key, VideoCandidate(match, "", "embedded"))

    # If the page itself is a direct video URL or has a recognizable extractor,
    # try yt-dlp as a second discovery layer even when ordinary anchors were found.
    if yt_dlp is not None and (not found or len(found) < 2):
        if progress:
            progress("Running yt-dlp discovery for additional videos…")
        try:
            for candidate in _yt_dlp_candidates(response.url, progress=progress):
                key = _dedupe_key(candidate.url)
                found.setdefault(key, candidate)
        except Exception as exc:
            if progress:
                progress(f"yt-dlp discovery skipped: {exc}")

    candidates = list(found.values())
    for index, candidate in enumerate(candidates, start=1):
        if not candidate.title:
            # Do not fetch dozens of pages serially; use a lightweight title request.
            try:
                page = read_webpage(candidate.url, timeout=12)
                candidate.title = page.title or f"Video {index}"
            except Exception:
                candidate.title = f"Video {index}"

    if progress:
        progress(f"Found {len(candidates)} video candidate(s).")
    return candidates


def extract_candidates(text: str, progress=None) -> list[VideoCandidate]:
    """Accept one listing URL, a direct video URL, or multiple URLs separated by lines."""
    raw = [line.strip() for line in text.splitlines() if line.strip()]
    if not raw:
        raw = [text.strip()]
    urls = []
    for item in raw:
        if _is_http_url(item):
            urls.append(item)
    if not urls:
        raise ValueError("Enter one or more http:// or https:// URLs")

    if len(urls) > 1:
        return [VideoCandidate(url, f"Video {i}", "input") for i, url in enumerate(urls, 1)]

    url = urls[0]
    if is_direct_media_url(url):
        return [VideoCandidate(url, Path(urlparse(url).path).name or "Video", "direct")]
    return extract_video_page_links(url, progress=progress)


def _find_downloaded_file(info: dict, ydl) -> Optional[Path]:
    paths: list[Path] = []
    for item in info.get("requested_downloads") or []:
        value = item.get("filepath") or item.get("_filename")
        if value:
            paths.append(Path(str(value)))
    try:
        paths.append(Path(ydl.prepare_filename(info)))
    except Exception:
        pass
    for candidate in paths:
        if candidate.exists() and candidate.stat().st_size > 0:
            return candidate
        if candidate.with_suffix(".mp4").exists() and candidate.with_suffix(".mp4").stat().st_size > 0:
            return candidate.with_suffix(".mp4")
        if candidate.with_suffix(".mkv").exists() and candidate.with_suffix(".mkv").stat().st_size > 0:
            return candidate.with_suffix(".mkv")
        if candidate.with_suffix(".webm").exists() and candidate.with_suffix(".webm").stat().st_size > 0:
            return candidate.with_suffix(".webm")
    return None


def _short_error(exc: Exception) -> str:
    value = _clean_text(str(exc))
    value = re.sub(r"^ERROR:\s*", "", value, flags=re.I)
    return value[:700] or exc.__class__.__name__


def _format_attempts(requested: str, has_ffmpeg: bool) -> list[str]:
    requested = requested.strip()
    if requested and requested.lower() not in {"auto", "best"}:
        return [requested, "best[ext=mp4]/best"]
    attempts = []
    if has_ffmpeg:
        attempts.append("bv*+ba/b")
    attempts.extend(["best[ext=mp4]/best", "best/bestvideo"])
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(attempts))


def download_one(
    video_url: str,
    batch_dir: Path,
    referer: str = "",
    format_selector: str = "auto",
    retries: int = 5,
    cookie_file: str = "",
    write_thumbnail: bool = False,
    thumbnail_func: Optional[Callable[[Path], Optional[Path]]] = None,
    progress: Optional[Callable[[str, str], None]] = None,
) -> DownloadResult:
    if yt_dlp is None:
        return DownloadResult(video_url, False, error="yt-dlp is not installed.")

    batch_dir.mkdir(parents=True, exist_ok=True)
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept-Language": "en-US,en;q=0.9",
    }
    if referer and _is_http_url(referer):
        headers["Referer"] = referer
        try:
            headers["Origin"] = f"{urlparse(referer).scheme}://{urlparse(referer).netloc}"
        except Exception:
            pass

    has_ffmpeg = False
    try:
        from ffmpeg_manager import ffmpeg_path
        has_ffmpeg = bool(ffmpeg_path())
    except Exception:
        pass

    attempts = _format_attempts(format_selector, has_ffmpeg)
    last_error = "Unknown error"

    for attempt_number, selected_format in enumerate(attempts, start=1):
        _emit(progress, video_url, f"Attempt {attempt_number}/{len(attempts)} — preparing…")
        opts: dict = {
            "outtmpl": str(batch_dir / "%(title).120s [%(id)s].%(ext)s"),
            "noplaylist": True,
            "continuedl": True,
            "overwrites": False,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "format": selected_format,
            "merge_output_format": "mp4/mkv",
            "retries": max(1, retries),
            "fragment_retries": max(1, retries),
            "extractor_retries": 3,
            "file_access_retries": 3,
            "socket_timeout": 60,
            "concurrent_fragment_downloads": 2,
            "http_headers": headers,
            "check_formats": True,
        }
        if cookie_file:
            cookie_path = Path(cookie_file).expanduser()
            if cookie_path.exists() and cookie_path.is_file():
                opts["cookiefile"] = str(cookie_path)

        def hook(data: dict) -> None:
            if not progress:
                return
            status = data.get("status")
            if status == "downloading":
                done = float(data.get("downloaded_bytes") or 0)
                total = float(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
                speed = float(data.get("speed") or 0)
                eta = data.get("eta")
                suffix = f"  ETA {int(eta)}s" if eta else ""
                if total > 0:
                    _emit(progress, video_url, f"{done / total * 100:.1f}%  {speed / 1024 / 1024:.2f} MB/s{suffix}")
                else:
                    _emit(progress, video_url, f"{done / 1024 / 1024:.1f} MB downloaded  {speed / 1024 / 1024:.2f} MB/s")
            elif status == "finished":
                _emit(progress, video_url, "Download data received — finalizing…")

        opts["progress_hooks"] = [hook]

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(video_url, download=True) or {}
                path = _find_downloaded_file(info, ydl)

            if path is None:
                raise RuntimeError("yt-dlp finished without producing a readable file")

            title = _clean_title(str(info.get("title") or path.stem))
            thumb_path = None
            if write_thumbnail and thumbnail_func:
                try:
                    thumb_path = thumbnail_func(path)
                except Exception as exc:
                    _emit(progress, video_url, f"Thumbnail skipped: {_short_error(exc)}")

            _emit(progress, video_url, f"Completed — {path.name}")
            if thumb_path:
                _emit(progress, video_url, f"Thumbnail saved — {thumb_path.name}")
            return DownloadResult(video_url, True, str(path), title=title)
        except Exception as exc:
            last_error = _short_error(exc)
            _emit(progress, video_url, f"Attempt failed: {last_error}")
            if attempt_number < len(attempts):
                time.sleep(min(8, 2 ** (attempt_number - 1)))

    return DownloadResult(video_url, False, error=last_error)


def _emit(progress, url: str, message: str) -> None:
    if progress is None:
        return
    try:
        progress(url, message)
    except TypeError:
        # Backwards compatibility with the old one-argument callback.
        progress(f"{url}\n{message}")


def download_batch(
    urls: list[str],
    batch_dir: Path,
    referer: str = "",
    workers: int = 2,
    format_selector: str = "auto",
    retries: int = 5,
    cookie_file: str = "",
    write_thumbnail: bool = False,
    thumbnail_func: Optional[Callable[[Path], Optional[Path]]] = None,
    progress: Optional[Callable[[str, str], None]] = None,
) -> list[DownloadResult]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "video_links.txt").write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

    results_by_url: dict[str, DownloadResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(3, workers))) as pool:
        futures = {
            pool.submit(
                download_one,
                url,
                batch_dir,
                referer,
                format_selector,
                retries,
                cookie_file,
                write_thumbnail,
                thumbnail_func,
                progress,
            ): url
            for url in urls
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = DownloadResult(url, False, error=_short_error(exc))
            results_by_url[url] = result

    results = [results_by_url[url] for url in urls if url in results_by_url]
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "total": len(results),
        "success": sum(r.ok for r in results),
        "failed": sum(not r.ok for r in results),
        "results": [asdict(r) for r in results],
    }
    (batch_dir / "results.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return results


def make_batch_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("Batch_%Y%m%d_%H%M%S")
    candidate = root / stamp
    n = 2
    while candidate.exists():
        candidate = root / f"{stamp}_{n}"
        n += 1
    candidate.mkdir(parents=True)
    return candidate
