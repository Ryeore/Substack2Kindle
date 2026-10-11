import argparse
import hashlib
import html
import os
import re
import smtplib
import sys
import unicodedata
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from ebooklib import epub


USER_AGENT = "Substack2Kindle/1.0 (+https://github.com/)"
TIMEOUT = 30
MAX_IMAGE_BYTES = 20 * 1024 * 1024
# shortcut: only JPEG/PNG/GIF are embedded; add Pillow conversion when WebP coverage is needed.
IMAGE_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
}
CONTENT_SELECTORS = (
    ".available-content",
    ".body.markup",
    '[itemprop="articleBody"]',
    "article",
    "main",
)
ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "del", "div", "em", "figcaption",
    "figure", "h1", "h2", "h3", "h4", "hr", "i", "img", "li", "ol", "p", "pre",
    "s", "section", "span", "strong", "sub", "sup", "table", "tbody", "td",
    "th", "thead", "tr", "ul",
}


def load_env(path=Path(".env")):
    """Load simple KEY=VALUE entries without overriding process environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def validate_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("URL must be an HTTPS article URL.")
    return url


def extract_article(html, url):
    soup = BeautifulSoup(html, "html.parser")
    body = next(
        (
            candidate
            for selector in CONTENT_SELECTORS
            for candidate in soup.select(selector)
            if len(candidate.get_text(" ", strip=True)) >= 40
        ),
        None,
    )
    if body is None:
        raise ValueError("Could not find article content on this page.")

    for embed in body.select('[data-component-name="DigestPostEmbed"]'):
        embed.decompose()

    post_title = soup.select_one(".post-title")
    title = post_title.get_text(" ", strip=True) if post_title else ""
    meta = soup.find("meta", property="og:title")
    if not title and meta:
        title = meta.get("content", "").strip()
    if not title:
        heading = body.find("h1") or soup.select_one("h1")
        title = heading.get_text(" ", strip=True) if heading else ""
    if not title and soup.title:
        title = soup.title.get_text(" ", strip=True)
    if not title:
        title = urlparse(url).path.rstrip("/").split("/")[-1] or "Substack article"

    for heading in body.find_all(("h1", "h2", "h3", "h4")):
        if heading.get_text(" ", strip=True).casefold() == title.casefold():
            heading.decompose()
            break

    for tag in body.select("script, style, noscript, iframe, form, button, svg"):
        tag.decompose()
    article_url = urlparse(url)
    for tag in list(body.find_all(True)):
        if tag.name not in ALLOWED_TAGS:
            tag.unwrap()
            continue
        if tag.name == "a" and tag.get("href"):
            link = urlparse(urljoin(url, tag["href"]))
            if (
                link.scheme.lower(),
                link.netloc.lower(),
                link.path.rstrip("/"),
            ) == (
                article_url.scheme.lower(),
                article_url.netloc.lower(),
                article_url.path.rstrip("/"),
            ):
                tag.unwrap()
                continue
        allowed = {"a": {"href", "title"}, "img": {"src", "data-src", "alt", "title", "width", "height"}}
        keep = allowed.get(tag.name, set())
        for attr in list(tag.attrs):
            if attr not in keep:
                del tag.attrs[attr]
        if tag.name == "a" and tag.get("href"):
            if urlparse(tag["href"]).scheme not in ("", "http", "https", "mailto"):
                del tag["href"]
        if tag.name == "img" and (
            not tag.get("src") or tag["src"].startswith("data:")
        ):
            tag["src"] = tag.get("data-src", "")
        tag.attrs.pop("data-src", None)
        if tag.name == "img":
            for dimension in ("width", "height"):
                if tag.get(dimension) and not tag[dimension].isdigit():
                    del tag[dimension]
    return title, body


def slugify(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:80].rstrip("-") or "substack-article")


def filename_from_title(title):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title).strip().rstrip(". ")
    name = name[:150].rstrip(". ")
    if not name:
        return "Substack article"
    if name.split(".", 1)[0].upper() in {
        "CON", "PRN", "AUX", "NUL",
        *( "COM{}".format(number) for number in range(1, 10) ),
        *( "LPT{}".format(number) for number in range(1, 10) ),
    }:
        name = "_" + name
    return name


def download_images(body, article_url, session, image_prefix):
    images = []
    skipped = 0
    for index, tag in enumerate(body.find_all("img"), start=1):
        source = tag.get("src", "").strip()
        if not source or source.startswith("data:"):
            source = tag.get("data-src", "").strip()
        if not source or source.startswith("data:"):
            tag.decompose()
            skipped += 1
            continue
        image_url = urljoin(article_url, source)
        try:
            if urlparse(image_url).scheme != "https":
                raise ValueError("image URL must use HTTPS")
            response = session.get(image_url, timeout=TIMEOUT, stream=True)
            response.raise_for_status()
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
            extension = IMAGE_TYPES.get(media_type)
            if not extension:
                raise ValueError("unsupported image format")
            data = bytearray()
            for chunk in response.iter_content(64 * 1024):
                data.extend(chunk)
                if len(data) > MAX_IMAGE_BYTES:
                    raise ValueError("image exceeds 20 MB limit")
            if not data:
                raise ValueError("empty image")
            name = "images/image-{}{}".format(index, extension)
            images.append((name, media_type, bytes(data)))
            tag["src"] = image_prefix + name
        except (requests.RequestException, ValueError) as error:
            print("  Image {} skipped: {}".format(image_url, error))
            tag.decompose()
            skipped += 1
        finally:
            if "response" in locals():
                response.close()
                del response
    return images, skipped


def write_clean_html(title, body, images, destination, source_url):
    asset_dir = destination.with_name(destination.stem + "-assets")
    for name, _, data in images:
        image_path = asset_dir.joinpath(*Path(name).parts)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        image_path.write_bytes(data)

    document = BeautifulSoup(
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="source-url" content="{}">'
        '<title>{}</title><style>'
        'body{{font-family:Georgia,serif;line-height:1.6;max-width:48rem;'
        'margin:2rem auto;padding:0 1rem;color:#222}}'
        'img{{max-width:100%;height:auto}}figure{{margin:1.5rem 0;text-align:center}}'
        'figcaption{{font-size:.9em;color:#555}}'
        'table{{border-collapse:collapse;max-width:100%}}'
        'td,th{{border:1px solid #888;padding:.35em}}'
        '</style></head><body></body></html>'.format(
            html.escape(source_url, quote=True), html.escape(title)
        ),
        "html.parser",
    )
    heading = document.new_tag("h1")
    heading.string = title
    document.body.append(heading)
    document.body.append(body)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        document.prettify(formatter="html"),
        encoding="utf-8",
    )


def make_epub(html_path, destination):
    document = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    title = document.title.get_text(" ", strip=True) if document.title else ""
    if not title or document.body is None:
        raise ValueError("Clean HTML must contain a title and article body.")
    body = document.body
    images = {}
    for tag in body.find_all("img"):
        source = urlparse(tag.get("src", ""))
        if source.scheme or source.netloc or not source.path:
            raise ValueError("Clean HTML images must reference local image files.")
        image_path = (html_path.parent / unquote(source.path)).resolve()
        try:
            image_path.relative_to(html_path.parent.resolve())
        except ValueError:
            raise ValueError("Clean HTML image path escapes its output directory.")
        extension = image_path.suffix.lower()
        media_type = next(
            (kind for kind, suffix in IMAGE_TYPES.items() if suffix == extension),
            None,
        )
        if not media_type:
            raise ValueError("Unsupported image format in clean HTML: {}".format(extension))
        name = "images/" + image_path.name
        images.setdefault(name, (media_type, image_path.read_bytes()))
        tag["src"] = "../" + name

    book = epub.EpubBook()
    book.set_identifier("substack-" + slugify(title))
    book.set_title(title)
    book.set_language("en")
    chapter = epub.EpubHtml(title=title, file_name="text/article.xhtml", lang="en")
    escaped_title = html.escape(title)
    chapter.content = (
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="en"><head>'
        '<title>{}</title><link rel="stylesheet" type="text/css" href="../style.css" />'
        '</head><body>{}</body></html>'.format(
            escaped_title,
            body.decode_contents(),
        )
    )
    book.add_item(chapter)
    book.add_item(epub.EpubItem(
        uid="style", file_name="style.css", media_type="text/css",
        content=(
            "body{font-family:serif;line-height:1.5;margin:5%;}"
            "h1,h2,h3{line-height:1.2;}img{max-width:100%;height:auto;}"
            "figure{margin:1em 0;text-align:center;}figcaption{font-size:.9em;}"
            "table{border-collapse:collapse;width:100%;}td,th{padding:.3em;border:1px solid #888;}"
        ),
    ))
    for name, (media_type, data) in images.items():
        book.add_item(epub.EpubItem(
            uid=name, file_name=name, media_type=media_type, content=data
        ))
    book.toc = (chapter,)
    book.spine = [chapter]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    destination.parent.mkdir(parents=True, exist_ok=True)
    epub.write_epub(str(destination), book)


def kindle_sender():
    sender = os.getenv("EMAIL_SENDER", "").strip()
    if sender and "@" not in sender:
        sender += "@gmail.com"
    return sender


def send_to_kindle(path):
    recipient = os.getenv("EMAIL_KINDLE", "").strip()
    password = os.getenv("EMAIL_PASSWORD", "")
    sender = kindle_sender()
    server_name = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    if not recipient or not sender or not password:
        raise ValueError("Set EMAIL_KINDLE, EMAIL_SENDER, and EMAIL_PASSWORD in .env.")

    message = EmailMessage()
    message["Subject"] = "Kindle: {}".format(path.stem)
    message["From"] = sender
    message["To"] = recipient
    message.set_content("Your Substack article is attached.")
    message.add_attachment(
        path.read_bytes(),
        maintype="application",
        subtype="epub+zip",
        filename=path.name,
    )
    with smtplib.SMTP(server_name, port, timeout=TIMEOUT) as smtp:
        smtp.starttls()
        smtp.login(sender, password)
        smtp.send_message(message)


def process_url(url, output_dir, send_email):
    print("\n{}".format(url))
    stage = "Validate URL"
    try:
        validate_url(url)
        stage = "Fetch article"
        with requests.Session() as session:
            session.headers["User-Agent"] = USER_AGENT
            response = session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            validate_url(response.url)
            print("[OK] Fetch article")
            stage = "Extract article"
            title, body = extract_article(response.text, response.url)
            print("[OK] Extract article: {}".format(title))
            stage = "Download images"
            basename = filename_from_title(title)
            html_path = output_dir / (basename + ".html")
            if html_path.exists():
                existing = BeautifulSoup(
                    html_path.read_text(encoding="utf-8"), "html.parser"
                ).find("meta", attrs={"name": "source-url"})
                if not existing or existing.get("content") != response.url:
                    suffix = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
                    basename = "{} ({})".format(basename, suffix)
            html_path = output_dir / (basename + ".html")
            image_prefix = basename + "-assets/"
            images, skipped_images = download_images(
                body, response.url, session, image_prefix
            )
            print("[OK] Download images: {} retained, {} skipped".format(
                len(images), skipped_images
            ))
        stage = "Save clean HTML"
        write_clean_html(title, body, images, html_path, response.url)
        print("[OK] Save clean HTML: {}".format(html_path.resolve()))
        stage = "Convert HTML to EPUB"
        destination = output_dir / (basename + ".epub")
        make_epub(html_path, destination)
        print("[OK] Convert HTML to EPUB: {}".format(destination))
        print("[OK] Save local copy: {}".format(destination.resolve()))
    except (requests.RequestException, ValueError, OSError) as error:
        print("[FAILED] {}: {}".format(stage, error))
        return False

    if send_email:
        try:
            send_to_kindle(destination)
            print("[OK] Email to Kindle")
        except (OSError, ValueError, smtplib.SMTPException) as error:
            print("[FAILED] Email to Kindle: {}".format(error))
            return False
    else:
        print("[SKIP] Email to Kindle (--no-email)")
    return True


def main(argv=None):
    load_env()
    parser = argparse.ArgumentParser(
        description="Convert Substack article URLs to EPUBs and email them to Kindle."
    )
    parser.add_argument("urls", nargs="+", help="HTTPS article URL(s)")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--no-email", action="store_true", help="Only create local EPUB files")
    args = parser.parse_args(argv)
    results = [
        process_url(url, args.output_dir, not args.no_email)
        for url in args.urls
    ]
    print("\nCompleted: {} succeeded, {} failed.".format(results.count(True), results.count(False)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
