from __future__ import annotations

import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.graphics import Color, RoundedRectangle
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


class Surface(BoxLayout):
    def __init__(self, fill=(0.08, 0.11, 0.16, 1), radius=12, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*fill)
            self.panel = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(radius)])
        self.bind(pos=self._sync_panel, size=self._sync_panel)

    def _sync_panel(self, *_):
        self.panel.pos = self.pos
        self.panel.size = self.size


class SectionLabel(Label):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_size", "12sp")
        kwargs.setdefault("color", (0.48, 0.72, 0.76, 1))
        kwargs.setdefault("bold", True)
        kwargs.setdefault("halign", "left")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)


class VideoRow(BoxLayout):
    def __init__(self, candidate: VideoCandidate, **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(68),
            spacing=dp(10),
            padding=(dp(10), dp(7)),
            **kwargs,
        )
        with self.canvas.before:
            Color(0.10, 0.14, 0.20, 1)
            self.panel = RoundedRectangle(pos=self.pos, size=self.size, radius=[dp(9)])
        self.bind(pos=self._sync_panel, size=self._sync_panel)
        self.candidate = candidate
        self.checkbox = CheckBox(size_hint_x=None, width=dp(34), active=True)
        self.add_widget(self.checkbox)

        title = candidate.title or candidate.url
        text = f"{title}\n{candidate.url}"
        self.add_widget(
            Label(
                text=text,
                color=(0.88, 0.92, 0.95, 1),
                font_size="12sp",
                halign="left",
                valign="middle",
                text_size=(None, None),
            )
        )

    def _sync_panel(self, *_):
        self.panel.pos = self.pos
        self.panel.size = self.size

    @property
    def selected(self) -> bool:
        return bool(self.checkbox.active)


class DownloaderRoot(BoxLayout):
    status = StringProperty("Ready. Enter a webpage URL.")

    def __init__(self, app, **kwargs):
        super().__init__(orientation="vertical", padding=dp(16), spacing=dp(10), **kwargs)
        self.app_ref = app
        self.candidates: list[VideoCandidate] = []
        self.rows: list[VideoRow] = []
        self._build()

    def _button(self, text: str, callback, width: float | None = None):
        button = Button(
            text=text,
            size_hint_y=None,
            height=dp(42),
            background_normal="",
            background_color=(0.10, 0.25, 0.29, 1),
            color=(0.90, 0.98, 0.98, 1),
            font_size="12sp",
        )
        if width is not None:
            button.size_hint_x = None
            button.width = dp(width)
        button.bind(on_release=lambda *_: callback())
        return button

    def _build(self):
        header = BoxLayout(orientation="vertical", size_hint_y=None, height=dp(74), spacing=dp(2))
        header.add_widget(Label(
            text="Bulk Video Downloader",
            color=(0.93, 0.97, 0.98, 1),
            font_size="24sp",
            bold=True,
            halign="left",
            text_size=(None, None),
        ))
        header.add_widget(Label(
            text="Collect, review, and save videos from a webpage",
            color=(0.55, 0.64, 0.69, 1),
            font_size="12sp",
            halign="left",
            text_size=(None, None),
        ))
        self.add_widget(header)

        source = Surface(orientation="vertical", padding=(dp(12), dp(9)), spacing=dp(6), size_hint_y=None, height=dp(86))
        source.add_widget(SectionLabel(text="SOURCE PAGE", size_hint_y=None, height=dp(18)))
        self.page_input = TextInput(
            multiline=False,
            size_hint_y=None,
            height=dp(42),
            hint_text="Paste a webpage URL",
            hint_text_color=(0.40, 0.48, 0.53, 1),
            foreground_color=(0.92, 0.96, 0.97, 1),
            background_normal="",
            background_color=(0.05, 0.08, 0.12, 1),
            padding=(dp(10), dp(10)),
        )
        source.add_widget(self.page_input)
        self.add_widget(source)

        actions = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(8))
        actions.add_widget(self._button("Read Page", self.read_page))
        actions.add_widget(self._button("Find Videos", self.find_videos))
        actions.add_widget(self._button("Select All", self.select_all))
        actions.add_widget(self._button("Clear", self.clear_results))
        self.add_widget(actions)

        self.page_info = Label(
            text="Page text will appear here after reading.",
            color=(0.65, 0.72, 0.76, 1),
            font_size="12sp",
            size_hint_y=None,
            height=dp(58),
            halign="left",
            valign="top",
        )
        self.page_info.bind(size=lambda *_: setattr(self.page_info, "text_size", (self.page_info.width, None)))
        self.add_widget(self.page_info)

        results_header = BoxLayout(size_hint_y=None, height=dp(26))
        results_header.add_widget(SectionLabel(text="VIDEO RESULTS"))
        self.results_count = Label(text="0 found", color=(0.55, 0.64, 0.69, 1), font_size="11sp", halign="right")
        results_header.add_widget(self.results_count)
        self.add_widget(results_header)

        self.results_scroll = ScrollView(size_hint=(1, 1), bar_width=dp(4), scroll_type=["bars", "content"])
        self.results_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(4))
        self.results_box.bind(minimum_height=self.results_box.setter("height"))
        self.results_scroll.add_widget(self.results_box)
        self.add_widget(self.results_scroll)

        settings = Surface(size_hint_y=None, height=dp(76), spacing=dp(8), padding=(dp(10), dp(9)))
        self.workers_input = TextInput(
            text="2", multiline=False, input_filter="int", hint_text="Workers",
            hint_text_color=(0.40, 0.48, 0.53, 1), foreground_color=(0.92, 0.96, 0.97, 1),
            background_normal="", background_color=(0.05, 0.08, 0.12, 1), padding=(dp(9), dp(9)),
        )
        self.quality_input = TextInput(
            text="best[ext=mp4]/best",
            multiline=False,
            hint_text="yt-dlp format",
            hint_text_color=(0.40, 0.48, 0.53, 1), foreground_color=(0.92, 0.96, 0.97, 1),
            background_normal="", background_color=(0.05, 0.08, 0.12, 1), padding=(dp(9), dp(9)),
        )
        settings.add_widget(self.workers_input)
        settings.add_widget(self.quality_input)
        self.add_widget(settings)

        thumb_row = BoxLayout(size_hint_y=None, height=dp(30), spacing=dp(4))
        self.thumbnail_check = CheckBox(active=False, size_hint_x=None, width=dp(44))
        thumb_row.add_widget(self.thumbnail_check)
        thumb_row.add_widget(Label(text="Save a JPG thumbnail beside each video", color=(0.65, 0.72, 0.76, 1), font_size="11sp", halign="left"))
        self.add_widget(thumb_row)

        download_button = self._button("DOWNLOAD SELECTED", self.download_selected)
        download_button.background_color = (0.08, 0.48, 0.43, 1)
        download_button.height = dp(48)
        self.add_widget(download_button)

        self.status_label = Label(
            text=self.status,
            size_hint_y=None,
            color=(0.54, 0.68, 0.70, 1),
            font_size="11sp",
            height=dp(86),
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
        self.results_count.text = "0 found"
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
                    self.results_count.text = f"{len(candidates)} found"
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
