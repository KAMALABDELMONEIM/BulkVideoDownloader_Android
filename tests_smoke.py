from pathlib import Path
from tempfile import TemporaryDirectory

from downloader import _is_video_page, make_batch_dir

assert _is_video_page("https://example.com/videos/296082/example-slug/")
assert _is_video_page("https://example.com/video/123/foo")
assert not _is_video_page("https://example.com/videos/abc/foo")

with TemporaryDirectory() as tmp:
    root = Path(tmp) / "downloads"
    one = make_batch_dir(root)
    two = make_batch_dir(root)
    assert one != two
    assert one.name.startswith("Batch_")
    assert two.name.startswith("Batch_")

print("Android downloader smoke tests passed.")
