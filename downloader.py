from __future__ import annotations

import html
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
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
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 "
    "Chrome/131.0 Mobile Safari/537.36"
)

VIDEO_PAGE_RE = re.compile(r"/(?:videos?|video)/\d+(?:/[^\"'<>\s?#]*)?/?$", re.I)
HREF_RE = re.compile(r"href\s*=\s*([\"'])(.*?)\1", re.I | re.S)


@dataclass
class VideoCandidate:
    url: str
    title: str = ""


@dataclass
class DownloadResult:
    url: str
    ok: bool
    filepath: str = ""
    title: str = ""
    error: str = ""


@dataclass
class WebPage:
    url: str
    title: str = ""
    text: str = ""


def _clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _clean_title(value: str) -> str:
    return _clean_text(value)[:180]


def _is_video_page(url: str) -> bool:
    try:
        path = urlparse(url).path.rstrip("/")
    except Exception:
        return False
    return bool(VIDEO_PAGE_RE.search(path))


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


def read_webpage(page_url: str, timeout: int = 30) -> WebPage:
    if not page_url.startswith(("http://", "https://")):
        raise ValueError("Webpage URL must start with http:// or https://")

    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    response = session.get(page_url, timeout=timeout)
    response.raise_for_status()

    parser = _PageTextParser()
    parser.feed(response.text)
    parser.close()

    text = re.sub(r"[ \t]+", " ", "".join(parser.text_parts))
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    text = text.strip()
    return WebPage(url=response.url, title=_clean_title(" ".join(parser.title_parts)), text=text)


def extract_video_page_links(
    listing_url: str,
    timeout: int = 30,
    progress: Optional[Callable[[str], None]] = None,
) -> list[VideoCandidate]:
    """Return individual video-page URLs, not direct media URLs."""
    if not listing_url.startswith(("http://", "https://")):
        raise ValueError("Listing URL must start with http:// or https://")

    if progress:
        progress("Loading the webpage…")

    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": listing_url,
    })

    response = session.get(listing_url, timeout=timeout)
    response.raise_for_status()
    source = html.unescape(response.text.replace("\\/", "/"))

    found: dict[str, VideoCandidate] = {}

    # Normal links in HTML.
    for _, href in HREF_RE.findall(source):
        href = html.unescape(href).strip()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        absolute = urljoin(response.url, href).split("#", 1)[0]
        if _is_video_page(absolute):
            found.setdefault(absolute, VideoCandidate(url=absolute))

    # Plain-text / JSON embedded URLs.
    if not found:
        for match in re.findall(r"https?://[^\"'<>\s]+", source):
            match = match.rstrip(",.;)]}")
            if _is_video_page(match):
                found.setdefault(match, VideoCandidate(url=match))

    # Let yt-dlp inspect recognized listing pages as a fallback.
    if not found and yt_dlp is not None:
        if progress:
            progress("No ordinary links found; asking yt-dlp…")
        opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "noplaylist": False,
            "http_headers": {"Referer": listing_url, "User-Agent": DEFAULT_USER_AGENT},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(listing_url, download=False) or {}
            for entry in info.get("entries") or []:
                if not entry:
                    continue
                candidate = entry.get("webpage_url") or entry.get("original_url") or entry.get("url")
                if candidate and _is_video_page(candidate):
                    title = _clean_title(str(entry.get("title") or ""))
                    found.setdefault(candidate, VideoCandidate(url=candidate, title=title))
        except Exception as exc:
            if progress:
                progress(f"yt-dlp fallback failed: {exc}")

    # Fill missing titles from each video page without downloading the media.
    candidates = list(found.values())
    for index, candidate in enumerate(candidates, start=1):
        if candidate.title:
            continue
        try:
            page = read_webpage(candidate.url, timeout=15)
            if page.title:
                candidate.title = page.title
        except Exception:
            candidate.title = f"Video {index}"

    if progress:
        progress(f"Found {len(candidates)} individual video page(s).")
    return candidates


def _find_downloaded_file(info: dict, ydl) -> Optional[Path]:
    for item in info.get("requested_downloads") or []:
        value = item.get("filepath") or item.get("_filename")
        if value:
            p = Path(str(value))
            if p.exists():
                return p
            if p.with_suffix(".mp4").exists():
                return p.with_suffix(".mp4")

    prepared = ydl.prepare_filename(info)
    p = Path(prepared)
    if p.exists():
        return p
    if p.with_suffix(".mp4").exists():
        return p.with_suffix(".mp4")

    title = _clean_title(str(info.get("title") or "video"))
    video_id = str(info.get("id") or "")
    if video_id:
        matches = sorted(p.parent.glob(f"*[{video_id}]*"))
        if matches:
            return matches[0]
    return None


def download_one(
    video_url: str,
    batch_dir: Path,
    referer: str = "",
    format_selector: str = "best[ext=mp4]/best",
    retries: int = 3,
    cookies_browser: str = "",
    write_thumbnail: bool = False,
    thumbnail_func: Optional[Callable[[Path], Optional[Path]]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> DownloadResult:
    if yt_dlp is None:
        return DownloadResult(video_url, False, error="yt-dlp is not installed.")

    batch_dir.mkdir(parents=True, exist_ok=True)
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    if referer:
        headers["Referer"] = referer

    if progress:
        progress(f"Starting: {video_url}")

    opts: dict = {
        "outtmpl": str(batch_dir / "%(title).180s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "continuedl": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": format_selector or "best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "retries": max(1, retries),
        "fragment_retries": max(1, retries),
        "concurrent_fragment_downloads": 4,
        "socket_timeout": 45,
        "http_headers": headers,
    }
    if cookies_browser and cookies_browser.lower() != "none":
        opts["cookiesfrombrowser"] = (cookies_browser.lower(),)

    def hook(data: dict) -> None:
        if progress and data.get("status") == "downloading":
            done = int(data.get("downloaded_bytes") or 0)
            total = int(data.get("total_bytes") or data.get("total_bytes_estimate") or 0)
            speed = float(data.get("speed") or 0)
            if total:
                progress(f"{video_url}\n  {done / total * 100:.1f}%  {speed / 1024:.0f} KB/s")
            else:
                progress(f"{video_url}\n  {done / 1024 / 1024:.1f} MB downloaded")

    opts["progress_hooks"] = [hook]

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video_url, download=True) or {}
            path = _find_downloaded_file(info, ydl)

        if path is None:
            return DownloadResult(
                video_url,
                False,
                title=str(info.get("title") or ""),
                error="Downloaded file could not be located.",
            )

        title = _clean_title(str(info.get("title") or path.stem))
        thumb_path = None
        if write_thumbnail and thumbnail_func:
            try:
                thumb_path = thumbnail_func(path)
            except Exception as exc:
                if progress:
                    progress(f"Thumbnail failed: {exc}")

        if progress:
            progress(f"Completed: {title}\n  {path.name}")
            if thumb_path:
                progress(f"  Thumbnail: {thumb_path.name}")

        return DownloadResult(video_url, True, str(path), title=title)
    except Exception as exc:
        return DownloadResult(video_url, False, error=str(exc))


def download_batch(
    urls: list[str],
    batch_dir: Path,
    referer: str = "",
    workers: int = 2,
    format_selector: str = "best[ext=mp4]/best",
    retries: int = 3,
    cookies_browser: str = "",
    write_thumbnail: bool = True,
    thumbnail_func: Optional[Callable[[Path], Optional[Path]]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> list[DownloadResult]:
    batch_dir.mkdir(parents=True, exist_ok=True)
    (batch_dir / "video_links.txt").write_text(
        "\n".join(urls) + ("\n" if urls else ""),
        encoding="utf-8",
    )

    results: list[DownloadResult] = []
    lock = threading.Lock()

    def one(url: str) -> DownloadResult:
        return download_one(
            url,
            batch_dir,
            referer=referer,
            format_selector=format_selector,
            retries=retries,
            cookies_browser=cookies_browser,
            write_thumbnail=write_thumbnail,
            thumbnail_func=thumbnail_func,
            progress=progress,
        )

    with ThreadPoolExecutor(max_workers=max(1, min(4, workers))) as pool:
        futures = [pool.submit(one, url) for url in urls]
        for future in as_completed(futures):
            result = future.result()
            with lock:
                results.append(result)

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
