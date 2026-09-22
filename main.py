from __future__ import annotations

import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.label import Label
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput

from ffmpeg_manager import make_jpeg_thumbnail
from android_storage import (
    public_location,
    publish_file,
    request_legacy_storage_permission,
    staging_root,
)
from downloader import (
    VideoCandidate,
    download_batch,
    extract_candidates,
    read_webpage,
    make_batch_dir,
    is_direct_media_url,
)


class VideoRow(BoxLayout):
    status_text = StringProperty("Queued")

    def __init__(self, candidate: VideoCandidate, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(74),
            spacing=dp(8),
            padding=(dp(5), dp(5)),
            **kwargs,
        )
        self.candidate = candidate
        self.checkbox = CheckBox(size_hint_x=None, width=dp(40), active=True)
        self.add_widget(self.checkbox)

        middle = BoxLayout(orientation="vertical", spacing=dp(1))
        title = candidate.title or candidate.url
        self.title_label = Label(
            text=title[:140],
            halign="left",
            valign="middle",
            font_size="12sp",
        )
        self.title_label.bind(size=lambda *_: setattr(self.title_label, "text_size", (self.title_label.width, None)))
        self.url_label = Label(
            text=candidate.url,
            halign="left",
            valign="middle",
            font_size="9sp",
        )
        self.url_label.bind(size=lambda *_: setattr(self.url_label, "text_size", (self.url_label.width, None)))
        self.status_label = Label(
            text=self.status_text,
            halign="left",
            valign="middle",
            font_size="10sp",
        )
        self.status_label.bind(size=lambda *_: setattr(self.status_label, "text_size", (self.status_label.width, None)))
        middle.add_widget(self.title_label)
        middle.add_widget(self.url_label)
        middle.add_widget(self.status_label)
        self.add_widget(middle)

    @property
    def selected(self) -> bool:
        return bool(self.checkbox.active)

    def set_status(self, message: str):
        self.status_text = message
        self.status_label.text = message


class DownloaderRoot(BoxLayout):
    status = StringProperty("Ready. Downloads go to Downloads/Bulk Video Downloader.")

    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=dp(10), spacing=dp(7), **kwargs)
        self.app_ref = app
        self.rows: list[VideoRow] = []
        self._build()

    def _button(self, text: str, callback):
        button = Button(text=text, size_hint_y=None, height=dp(42))
        button.bind(on_release=lambda *_: callback())
        return button

    def _build(self):
        self.add_widget(Label(text="Bulk Video Downloader", font_size="22sp", size_hint_y=None, height=dp(42)))
        self.add_widget(Label(
            text="Bulk download video pages or paste multiple URLs. Files are published to your phone's Downloads folder.",
            font_size="10sp", size_hint_y=None, height=dp(34), halign="left"
        ))

        self.page_input = TextInput(
            multiline=True,
            size_hint_y=None,
            height=dp(90),
            hint_text="Paste a listing page URL, a direct video URL, or one URL per line",
        )
        self.add_widget(self.page_input)

        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
        actions.add_widget(self._button("Find", self.find_videos))
        actions.add_widget(self._button("All", self.select_all))
        actions.add_widget(self._button("None", self.select_none))
        actions.add_widget(self._button("Clear", self.clear_results))
        self.add_widget(actions)

        self.page_info = Label(
            text="",
            size_hint_y=None,
            height=dp(46),
            halign="left",
            valign="top",
            font_size="10sp",
        )
        self.page_info.bind(size=lambda *_: setattr(self.page_info, "text_size", (self.page_info.width, None)))
        self.add_widget(self.page_info)

        header = BoxLayout(size_hint_y=None, height=dp(25))
        header.add_widget(Label(text="VIDEO QUEUE", font_size="11sp", halign="left"))
        self.results_count = Label(text="0", font_size="11sp", halign="right")
        header.add_widget(self.results_count)
        self.add_widget(header)

        self.results_scroll = ScrollView(size_hint=(1, 1), bar_width=dp(4))
        self.results_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(3))
        self.results_box.bind(minimum_height=self.results_box.setter("height"))
        self.results_scroll.add_widget(self.results_box)
        self.add_widget(self.results_scroll)

        settings = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
        settings.add_widget(Label(text="Workers", size_hint_x=None, width=dp(55), font_size="10sp"))
        self.workers_input = TextInput(text="2", multiline=False, input_filter="int", size_hint_x=None, width=dp(52))
        settings.add_widget(self.workers_input)
        settings.add_widget(Label(text="Quality", size_hint_x=None, width=dp(48), font_size="10sp"))
        self.quality_spinner = Spinner(
            text="Auto / best",
            values=("Auto / best", "MP4 compatible", "Up to 720p"),
            size_hint_x=None,
            width=dp(145),
        )
        settings.add_widget(self.quality_spinner)
        self.retry_spinner = Spinner(text="5 retries", values=("3 retries", "5 retries", "8 retries"), size_hint_x=None, width=dp(88))
        settings.add_widget(self.retry_spinner)
        self.add_widget(settings)

        thumb = BoxLayout(size_hint_y=None, height=dp(32))
        self.thumbnail_check = CheckBox(active=False, size_hint_x=None, width=dp(40))
        thumb.add_widget(self.thumbnail_check)
        thumb.add_widget(Label(text="Create thumbnails (requires FFmpeg)", font_size="10sp", halign="left"))
        self.add_widget(thumb)

        self.download_button = self._button("DOWNLOAD SELECTED", self.download_selected)
        self.add_widget(self.download_button)

        self.status_label = Label(
            text=self.status,
            size_hint_y=None,
            height=dp(70),
            halign="left",
            valign="top",
            font_size="10sp",
        )
        self.status_label.bind(size=lambda *_: setattr(self.status_label, "text_size", (self.status_label.width, None)))
        self.add_widget(self.status_label)

    def log(self, message: str):
        Clock.schedule_once(lambda _dt: self._set_status(message))

    def _set_status(self, message: str):
        self.status = message
        self.status_label.text = message

    def clear_results(self):
        self.rows.clear()
        self.results_box.clear_widgets()
        self.results_count.text = "0"
        self._set_status("Queue cleared.")

    def select_all(self):
        for row in self.rows:
            row.checkbox.active = True
        self._set_status(f"Selected {len(self.rows)} video(s).")

    def select_none(self):
        for row in self.rows:
            row.checkbox.active = False
        self._set_status("Selection cleared.")

    def find_videos(self):
        source = self.page_input.text.strip()
        if not source:
            self._set_status("Paste a URL first.")
            return
        self._set_status("Scanning page…")

        def work():
            try:
                candidates = extract_candidates(source, progress=self.log)

                def apply(_dt):
                    self.rows = [VideoRow(candidate) for candidate in candidates]
                    self.results_box.clear_widgets()
                    for row in self.rows:
                        self.results_box.add_widget(row)
                    self.results_count.text = str(len(self.rows))
                    self._set_status(f"Found {len(self.rows)} video candidate(s). Select what you want to download.")

                Clock.schedule_once(apply)
            except Exception as exc:
                self.log(f"Find failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def read_page(self):
        source = self.page_input.text.strip().splitlines()[0] if self.page_input.text.strip() else ""
        if not source:
            self._set_status("Paste a webpage URL first.")
            return
        self._set_status("Reading page…")

        def work():
            try:
                page = read_webpage(source)
                self.log(f"{page.title or page.url}\n{page.text[:1500]}")
            except Exception as exc:
                self.log(f"Read failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def _quality(self) -> str:
        value = self.quality_spinner.text
        if value == "MP4 compatible":
            return "best[ext=mp4]/best"
        if value == "Up to 720p":
            return "bv*[height<=720]+ba/b[height<=720]/best[height<=720]/best"
        return "auto"

    def _retries(self) -> int:
        return {"3 retries": 3, "5 retries": 5, "8 retries": 8}.get(self.retry_spinner.text, 5)

    def download_selected(self):
        selected = [row for row in self.rows if row.selected]
        if not selected:
            self._set_status("Select at least one video.")
            return

        if not request_legacy_storage_permission() and self.app_ref.is_android_legacy:
            self._set_status("Android storage permission is required. Allow it, then start the download again.")
            return

        try:
            workers = max(1, min(3, int(self.workers_input.text or "2")))
        except ValueError:
            workers = 2

        batch_dir = make_batch_dir(staging_root())
        batch_name = batch_dir.name
        public_path = public_location(batch_name)
        self._set_status(f"Downloading {len(selected)} video(s)…\nFinal location: {public_path}")
        self.download_button.disabled = True

        row_by_url = {row.candidate.url: row for row in selected}
        urls = [row.candidate.url for row in selected]
        first_input = source.splitlines()[0].strip() if source.splitlines() else ""
        referer = first_input if len(source.splitlines()) == 1 and not is_direct_media_url(first_input) else ""

        def progress(url: str, message: str):
            row = row_by_url.get(url)
            if row:
                Clock.schedule_once(lambda _dt, r=row, m=message: r.set_status(m))

        def work():
            try:
                results = download_batch(
                    urls,
                    batch_dir,
                    referer=referer,
                    workers=workers,
                    format_selector=self._quality(),
                    retries=self._retries(),
                    write_thumbnail=self.thumbnail_check.active,
                    thumbnail_func=make_jpeg_thumbnail,
                    progress=progress,
                )

                success = 0
                failed = 0
                published = 0
                for result in results:
                    row = row_by_url.get(result.url)
                    if not result.ok:
                        failed += 1
                        if row:
                            Clock.schedule_once(lambda _dt, r=row, e=result.error: r.set_status(f"FAILED: {e}"))
                        continue
                    success += 1
                    try:
                        published_file = publish_file(Path(result.filepath), batch_name)
                        # Publish the optional thumbnail into the same batch folder.
                        thumb = Path(result.filepath).with_name(Path(result.filepath).stem + ".preview.jpg")
                        if thumb.exists():
                            publish_file(thumb, batch_name, "image/jpeg")
                        published += 1
                        if row:
                            Clock.schedule_once(lambda _dt, r=row, p=published_file.display_path: r.set_status(f"SAVED: {p}"))
                    except Exception as exc:
                        failed += 1
                        if row:
                            Clock.schedule_once(lambda _dt, r=row, e=str(exc): r.set_status(f"SAVE FAILED: {e}"))

                # Publish the link list and JSON results for transparency and recovery.
                for filename, mime in (("video_links.txt", "text/plain"), ("results.json", "application/json")):
                    src = batch_dir / filename
                    if src.exists():
                        try:
                            publish_file(src, batch_name, mime)
                        except Exception:
                            pass

                self.log(f"Finished. {success} downloaded, {failed} failed, {published} saved to:\n{public_path}")
            except Exception as exc:
                self.log(f"Batch failed: {exc}")
            finally:
                Clock.schedule_once(lambda _dt: setattr(self.download_button, "disabled", False))

        threading.Thread(target=work, daemon=True).start()


class BulkVideoDownloaderApp(App):
    title = "Bulk Video Downloader"

    @property
    def is_android_legacy(self) -> bool:
        try:
            from android_storage import is_android, sdk_int
            return is_android() and sdk_int() < 29
        except Exception:
            return False

    def build(self):
        self.last_batch: Path | None = None
        return DownloaderRoot(self)


if __name__ == "__main__":
    BulkVideoDownloaderApp().run()
