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
from kivy.uix.textinput import TextInput

from downloader import (
    VideoCandidate,
    DownloadResult,
    download_batch,
    extract_video_page_links,
    make_batch_dir,
    read_webpage,
)
from ffmpeg_manager import check_ffmpeg, make_jpeg_thumbnail


class VideoRow(BoxLayout):
    def __init__(self, candidate: VideoCandidate, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(58),
            spacing=dp(8),
            padding=(dp(4), dp(4)),
            **kwargs,
        )
        self.candidate = candidate
        self.checkbox = CheckBox(size_hint_x=None, width=dp(44), active=True)
        self.add_widget(self.checkbox)

        title = candidate.title or candidate.url
        text = f"{title}\n{candidate.url}"
        self.add_widget(
            Label(
                text=text,
                halign="left",
                valign="middle",
                text_size=(None, None),
            )
        )

    @property
    def selected(self) -> bool:
        return bool(self.checkbox.active)


class DownloaderRoot(BoxLayout):
    status = StringProperty("Ready. Enter a webpage URL.")

    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=dp(10), spacing=dp(8), **kwargs)
        self.app_ref = app
        self.candidates: list[VideoCandidate] = []
        self.rows: list[VideoRow] = []
        self._build()

    def _button(self, text: str, callback, width: float | None = None):
        button = Button(text=text, size_hint_y=None, height=dp(46))
        if width is not None:
            button.size_hint_x = None
            button.width = dp(width)
        button.bind(on_release=lambda *_: callback())
        return button

    def _build(self):
        self.add_widget(
            Label(
                text="Bulk Video Downloader",
                font_size="22sp",
                size_hint_y=None,
                height=dp(48),
            )
        )

        self.add_widget(Label(text="Webpage URL", size_hint_y=None, height=dp(24), halign="left"))
        self.page_input = TextInput(
            multiline=False,
            size_hint_y=None,
            height=dp(46),
            hint_text="https://example.com/page/",
        )
        self.add_widget(self.page_input)

        actions = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        actions.add_widget(self._button("Read Page", self.read_page))
        actions.add_widget(self._button("Find Videos", self.find_videos))
        actions.add_widget(self._button("Select All", self.select_all))
        actions.add_widget(self._button("Clear", self.clear_results))
        self.add_widget(actions)

        self.page_info = Label(
            text="Page text and video links will appear below.",
            size_hint_y=None,
            height=dp(80),
            halign="left",
            valign="top",
        )
        self.page_info.bind(size=lambda *_: setattr(self.page_info, "text_size", (self.page_info.width, None)))
        self.add_widget(self.page_info)

        self.results_scroll = ScrollView(size_hint=(1, 1))
        self.results_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.results_box.bind(minimum_height=self.results_box.setter("height"))
        self.results_scroll.add_widget(self.results_box)
        self.add_widget(self.results_scroll)

        settings = BoxLayout(size_hint_y=None, height=dp(92), spacing=dp(8))
        self.workers_input = TextInput(text="2", multiline=False, input_filter="int", hint_text="Workers")
        self.quality_input = TextInput(
            text="best[ext=mp4]/best",
            multiline=False,
            hint_text="yt-dlp format",
        )
        settings.add_widget(self.workers_input)
        settings.add_widget(self.quality_input)
        self.add_widget(settings)

        thumb_row = BoxLayout(size_hint_y=None, height=dp(40))
        self.thumbnail_check = CheckBox(active=False, size_hint_x=None, width=dp(44))
        thumb_row.add_widget(self.thumbnail_check)
        thumb_row.add_widget(Label(text="Save FFmpeg JPG thumbnail beside each video", halign="left"))
        self.add_widget(thumb_row)

        self.add_widget(self._button("Download Selected", self.download_selected))

        self.status_label = Label(
            text=self.status,
            size_hint_y=None,
            height=dp(120),
            halign="left",
            valign="top",
        )
        self.status_label.bind(size=lambda *_: setattr(self.status_label, "text_size", (self.status_label.width, None)))
        self.add_widget(self.status_label)

    def log(self, message: str):
        def update(_dt):
            self.status = message
            self.status_label.text = message
        Clock.schedule_once(update)

    def clear_results(self):
        self.candidates.clear()
        self.rows.clear()
        self.results_box.clear_widgets()
        self.page_info.text = "Page text and video links will appear below."
        self.log("Results cleared.")

    def select_all(self):
        for row in self.rows:
            row.checkbox.active = True
        self.log(f"Selected {len(self.rows)} video(s).")

    def read_page(self):
        page_url = self.page_input.text.strip()
        if not page_url:
            self.log("Enter a webpage URL first.")
            return
        self.log("Reading page…")

        def work():
            try:
                page = read_webpage(page_url)
                text = page.text[:7000]
                message = f"{page.title or 'Page'}\n\n{text}"
                Clock.schedule_once(lambda _dt: setattr(self.page_info, "text", message))
                self.log(f"Page read successfully: {page.title or page_url}")
            except Exception as exc:
                self.log(f"Read failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def find_videos(self):
        page_url = self.page_input.text.strip()
        if not page_url:
            self.log("Enter a webpage URL first.")
            return
        self.log("Finding individual video-page links…")

        def work():
            try:
                candidates = extract_video_page_links(page_url, progress=self.log)

                def apply(_dt):
                    self.candidates = candidates
                    self.rows = []
                    self.results_box.clear_widgets()
                    for candidate in candidates:
                        row = VideoRow(candidate)
                        self.rows.append(row)
                        self.results_box.add_widget(row)
                    self.status = f"Found {len(candidates)} individual video page(s)."
                    self.status_label.text = self.status

                Clock.schedule_once(apply)
            except Exception as exc:
                self.log(f"Find failed: {exc}")

        threading.Thread(target=work, daemon=True).start()

    def download_selected(self):
        selected = [row.candidate for row in self.rows if row.selected]
        page_url = self.page_input.text.strip()
        if not selected:
            self.log("Select at least one video.")
            return
        if not page_url:
            self.log("The webpage URL is required as the referer.")
            return
        try:
            workers = max(1, min(4, int(self.workers_input.text or "2")))
        except ValueError:
            workers = 2

        batch_root = Path(self.app_ref.user_data_dir) / "downloads"
        batch_dir = make_batch_dir(batch_root)
        self.app_ref.last_batch = batch_dir
        urls = [c.url for c in selected]
        self.log(f"Batch started: {batch_dir.name}\n{len(urls)} video(s).")

        def work():
            results = download_batch(
                urls,
                batch_dir,
                referer=page_url,
                workers=workers,
                format_selector=self.quality_input.text.strip() or "best[ext=mp4]/best",
                write_thumbnail=self.thumbnail_check.active,
                thumbnail_func=make_jpeg_thumbnail,
                progress=self.log,
            )
            ok = sum(1 for r in results if r.ok)
            failed = len(results) - ok
            self.log(
                f"Batch finished: {ok} downloaded, {failed} failed.\n"
                f"Folder: {batch_dir}"
            )

        threading.Thread(target=work, daemon=True).start()


class BulkVideoDownloaderApp(App):
    title = "Bulk Video Downloader"

    def build(self):
        self.last_batch: Path | None = None
        return DownloaderRoot(self)


if __name__ == "__main__":
    BulkVideoDownloaderApp().run()
