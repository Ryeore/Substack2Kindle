import argparse
import contextlib
import io
import os
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse

from app import load_env, process_url


def app_directory():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def parse_article_urls(text):
    urls = [line.strip() for line in text.splitlines() if line.strip()]
    if not urls:
        raise ValueError("Paste at least one Substack article URL.")
    if len(urls) > 5:
        raise ValueError("Paste no more than five article URLs at a time.")
    for url in urls:
        parsed = urlparse(url)
        try:
            host = parsed.hostname or ""
            port = parsed.port
        except ValueError:
            raise ValueError("Enter valid HTTPS Substack article URLs.")
        if (
            parsed.scheme != "https"
            or not (host == "substack.com" or host.endswith(".substack.com"))
            or parsed.username
            or parsed.password
            or port not in (None, 443)
        ):
            raise ValueError(
                "Only HTTPS articles hosted on a substack.com domain are accepted."
            )
    return urls


class Substack2KindleApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Substack2Kindle")
        self.geometry("760x620")
        self.minsize(560, 440)
        self.directory = app_directory()
        load_env(self.directory / ".env")
        self.events = queue.Queue()
        self.create_widgets()
        self.after(100, self.read_events)

    def create_widgets(self):
        frame = ttk.Frame(self, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)
        ttk.Label(
            frame,
            text="Paste Substack article URLs, one per line (up to five):",
        ).grid(row=0, column=0, sticky="w")
        self.urls = tk.Text(frame, height=7, wrap="word")
        self.urls.grid(row=1, column=0, sticky="nsew", pady=(8, 10))
        self.urls.focus_set()

        self.send_email = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frame,
            text="Email EPUBs to my configured Kindle address",
            variable=self.send_email,
        ).grid(row=2, column=0, sticky="nw")
        self.convert_button = ttk.Button(
            frame, text="Convert articles", command=self.start_conversion
        )
        self.convert_button.grid(row=3, column=0, sticky="w", pady=(10, 14))
        ttk.Label(frame, text="Progress").grid(row=4, column=0, sticky="w")
        self.log = tk.Text(frame, height=14, wrap="word", state="disabled")
        self.log.grid(row=5, column=0, sticky="nsew", pady=(8, 10))
        frame.rowconfigure(5, weight=2)
        ttk.Button(
            frame, text="Open output folder", command=self.open_output_folder
        ).grid(row=6, column=0, sticky="w")
        ttk.Button(
            frame, text="Open email settings", command=self.open_email_settings
        ).grid(row=7, column=0, sticky="w", pady=(8, 0))

    def append_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def start_conversion(self):
        try:
            urls = parse_article_urls(self.urls.get("1.0", "end"))
        except ValueError as error:
            messagebox.showerror("Invalid article URL", str(error), parent=self)
            return
        if self.send_email.get() and not all(
            os.getenv(key) for key in ("EMAIL_KINDLE", "EMAIL_SENDER", "EMAIL_PASSWORD")
        ):
            messagebox.showerror(
                "Email settings missing",
                "Set EMAIL_KINDLE, EMAIL_SENDER, and EMAIL_PASSWORD in the .env file, "
                "then restart the app.",
                parent=self,
            )
            return
        self.convert_button.configure(state="disabled")
        self.append_log("Starting {} article(s)...\n\n".format(len(urls)))
        threading.Thread(
            target=self.convert_articles,
            args=(urls, self.send_email.get()),
            daemon=True,
        ).start()

    def convert_articles(self, urls, send_email):
        output_dir = self.directory / "output"
        for url in urls:
            captured = io.StringIO()
            try:
                with contextlib.redirect_stdout(captured):
                    success = process_url(url, output_dir, send_email)
                log = captured.getvalue()
            except Exception as error:
                success = False
                log = captured.getvalue() + "[FAILED] Unexpected error: {}\n".format(error)
            self.events.put(log + "\n")
        self.events.put(None)

    def read_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event is None:
                    self.convert_button.configure(state="normal")
                    self.append_log("Finished.\n")
                else:
                    self.append_log(event)
        except queue.Empty:
            pass
        self.after(100, self.read_events)

    def open_output_folder(self):
        output_dir = self.directory / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(output_dir))
        else:
            messagebox.showinfo(
                "Output folder",
                str(output_dir),
                parent=self,
            )

    def open_email_settings(self):
        settings = self.directory / ".env"
        if hasattr(os, "startfile"):
            os.startfile(str(settings))
        else:
            messagebox.showinfo("Email settings", str(settings), parent=self)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Substack2Kindle desktop app.")
    parser.parse_args(argv)
    directory = app_directory()
    settings = directory / ".env"
    needs_setup = not settings.exists()
    if needs_setup:
        template = Path(getattr(sys, "_MEIPASS", directory)) / ".env.example"
        if template.is_file():
            settings.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    load_env(settings)
    application = Substack2KindleApp()
    if needs_setup:
        application.after(250, application.open_email_settings)
    application.mainloop()


if __name__ == "__main__":
    main()
