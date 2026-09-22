from pathlib import Path
from tempfile import TemporaryDirectory

from android_storage import public_location
from downloader import (
    _LinkParser,
    _is_probable_video_page,
    is_direct_media_url,
    make_batch_dir,
    extract_candidates,
)

assert _is_probable_video_page("https://example.com/videos/296082/example-slug/")
assert _is_probable_video_page("https://example.com/video/123/foo")
assert _is_probable_video_page("https://example.com/watch/hello")
assert is_direct_media_url("https://cdn.example.com/media/file.mp4")
assert is_direct_media_url("https://cdn.example.com/media/file.m3u8")
assert not _is_probable_video_page("https://example.com/categories/movies")

parser = _LinkParser()
parser.feed("<a href=\"/videos/1/one\">First Video</a><a href=\"/watch/2\">Second</a>")
parser.close()
assert parser.links[0][0] == "/videos/1/one"
assert parser.links[0][1] == "First Video"

with TemporaryDirectory() as tmp:
    root = Path(tmp) / "downloads"
    one = make_batch_dir(root)
    two = make_batch_dir(root)
    assert one != two
    assert one.name.startswith("Batch_")
    assert two.name.startswith("Batch_")

assert public_location("Batch_20260922_010203").startswith("Download/Bulk Video Downloader/")

try:
    extract_candidates("not a url")
except ValueError:
    pass
else:
    raise AssertionError("Invalid URL input should raise ValueError")

print("Android downloader smoke tests passed.")
