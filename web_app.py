import argparse
import contextlib
import html
import io
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from app import load_env, process_url


OUTPUT_DIR = Path("output")
MAX_REQUEST_BYTES = 8192
MAX_URLS = 5
ALLOWED_FILE_TYPES = {".html", ".epub", ".jpg", ".jpeg", ".png", ".gif"}


def validate_article_urls(text):
    urls = [line.strip() for line in text.splitlines() if line.strip()]
    if not urls:
        raise ValueError("Enter at least one Substack article URL.")
    if len(urls) > MAX_URLS:
        raise ValueError("Submit no more than {} URLs at a time.".format(MAX_URLS))
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


def resolve_output_file(request_path, output_dir=OUTPUT_DIR):
    relative = Path(unquote(request_path).lstrip("/"))
    if not relative.parts or any(part in ("", ".", "..") for part in relative.parts):
        raise ValueError("Invalid output file path.")
    path = (output_dir.resolve() / relative).resolve()
    try:
        path.relative_to(output_dir.resolve())
    except ValueError:
        raise ValueError("Output file path is outside the output directory.")
    if path.suffix.lower() not in ALLOWED_FILE_TYPES or not path.is_file():
        raise ValueError("Output file not found.")
    return path


def render_page(results=(), error="", urls=""):
    cards = []
    for result in results:
        links = []
        for label, name in (("Review HTML", result.get("html")), ("Download EPUB", result.get("epub"))):
            if name:
                links.append(
                    '<a href="/files/{}">{}</a>'.format(
                        quote(name, safe=""), html.escape(label)
                    )
                )
        cards.append(
            '<section class="result"><h2>{}: {}</h2>{}<details><summary>Processing log</summary>'
            '<pre>{}</pre></details></section>'.format(
                "Success" if result["success"] else "Failed",
                html.escape(result["url"]),
                " · ".join(links),
                html.escape(result["log"]),
            )
        )
    notice = '<p class="error">{}</p>'.format(html.escape(error)) if error else ""
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Substack2Kindle</title><style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:52rem;margin:2rem auto;padding:0 1rem;color:#202124}}
h1{{line-height:1.2}}textarea{{box-sizing:border-box;width:100%;min-height:9rem;padding:.75rem;font:inherit}}
button{{margin-top:.75rem;padding:.65rem 1rem;font:inherit;cursor:pointer}}
.result{{border-top:1px solid #bbb;padding:1rem 0}}.error{{color:#a00}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}
label{{display:block;margin-top:.75rem}}
</style></head><body><h1>Substack2Kindle</h1>
<p>Paste up to {max_urls} Substack article URLs, one per line. The app saves clean HTML and an EPUB locally.</p>
{notice}<form method="post" action="/convert">
<label for="urls">Article URLs</label><textarea id="urls" name="urls" required>{urls}</textarea>
<label><input type="checkbox" name="send_email" value="yes"> Email EPUBs to my configured Kindle</label>
<button type="submit">Convert articles</button></form>{results}</body></html>""".format(
        max_urls=MAX_URLS,
        notice=notice,
        urls=html.escape(urls),
        results="".join(cards),
    )


class ConverterHandler(BaseHTTPRequestHandler):
    server_version = "Substack2Kindle"

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def send_html(self, content, status=200):
        data = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self.send_html(render_page())
            return
        if self.path.startswith("/files/"):
            try:
                path = resolve_output_file(self.path[len("/files/"):])
            except ValueError as error:
                self.send_error(404, str(error))
                return
            data = path.read_bytes()
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(data)))
            if path.suffix.lower() == ".html":
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self'; style-src 'unsafe-inline'; "
                    "script-src 'none'; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'",
                )
            else:
                fallback_name = re.sub(r"[^A-Za-z0-9._-]", "_", path.name)
                self.send_header(
                    "Content-Disposition",
                    'attachment; filename="{}"; filename*=UTF-8\'\'{}'.format(
                        fallback_name, quote(path.name, safe="")
                    ),
                )
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def do_POST(self):
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        if host not in ("localhost", "127.0.0.1"):
            self.send_error(403, "This app only accepts requests addressed to localhost.")
            return
        origin = self.headers.get("Origin")
        allowed_origins = (
            "http://localhost:{}".format(self.server.server_port),
            "http://127.0.0.1:{}".format(self.server.server_port),
        )
        if origin and origin not in allowed_origins:
            self.send_error(403, "Cross-origin form submissions are not allowed.")
            return
        if self.path != "/convert":
            self.send_error(404)
            return
        if self.headers.get_content_type() != "application/x-www-form-urlencoded":
            self.send_error(415, "Expected a form submission.")
            return
        urls_text = ""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError("Request must be between 1 and {} bytes.".format(MAX_REQUEST_BYTES))
            form = parse_qs(self.rfile.read(length).decode("utf-8"), max_num_fields=4)
            urls_text = form.get("urls", [""])[0]
            urls = validate_article_urls(urls_text)
        except (ValueError, UnicodeDecodeError) as error:
            self.send_html(render_page(error=str(error), urls=urls_text), 400)
            return

        send_email = form.get("send_email", [""])[0] == "yes"
        results = []
        for url in urls:
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                success = process_url(url, OUTPUT_DIR, send_email)
            log = output.getvalue()
            files = {}
            for line in log.splitlines():
                if line.startswith("[OK] Save clean HTML: "):
                    files["html"] = Path(line.split(": ", 1)[1]).name
                elif line.startswith("[OK] Convert HTML to EPUB: "):
                    files["epub"] = Path(line.split(": ", 1)[1]).name
            results.append({"url": url, "success": success, "log": log, **files})
        self.send_html(render_page(results=results, urls=urls_text))

    def log_message(self, format, *args):
        print("{} - {}".format(self.address_string(), format % args))


def main(argv=None):
    load_env()
    parser = argparse.ArgumentParser(description="Run the local Substack2Kindle web app.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = HTTPServer(("127.0.0.1", args.port), ConverterHandler)
    print("Open http://127.0.0.1:{}/ in your browser. Press Ctrl+C to stop.".format(args.port))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping web app.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
