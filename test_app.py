import tempfile
import unittest
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from bs4 import BeautifulSoup

import web_app
from app import (
    download_images,
    extract_article,
    filename_from_title,
    make_epub,
    slugify,
    validate_url,
    write_clean_html,
)
from web_app import open_browser, render_page, resolve_output_file, validate_article_urls


class ConverterTests(unittest.TestCase):
    def test_validate_url_requires_https_and_host(self):
        self.assertEqual(validate_url("https://example.substack.com/p/test"),
                         "https://example.substack.com/p/test")
        for url in ("http://example.com/article", "not-a-url"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_web_form_only_accepts_https_substack_article_urls(self):
        self.assertEqual(
            validate_article_urls(
                "https://example.substack.com/p/one\nhttps://substack.com/p/two"
            ),
            [
                "https://example.substack.com/p/one",
                "https://substack.com/p/two",
            ],
        )
        for url in (
            "http://example.substack.com/p/article",
            "https://example.com/p/article",
            "https://example.substack.com.evil.test/p/article",
            "https://127.0.0.1/p/article",
            "https://user@example.substack.com/p/article",
            "https://example.substack.com:8443/p/article",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_article_urls(url)
        with self.assertRaises(ValueError):
            validate_article_urls("\n".join(
                "https://example.substack.com/p/{}".format(index)
                for index in range(6)
            ))

    def test_web_file_route_stays_inside_output_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "article.epub").write_bytes(b"book")
            self.assertEqual(
                resolve_output_file("article.epub", root),
                (root / "article.epub").resolve(),
            )
            for path in ("../secret.epub", "missing.exe"):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    resolve_output_file(path, root)

    def test_web_results_escape_untrusted_article_text(self):
        page = render_page(
            results=[{
                "url": 'https://example.substack.com/<script>',
                "success": False,
                "log": "<script>alert(1)</script>",
            }]
        )
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    @patch("web_app.threading.Timer")
    def test_web_app_can_schedule_opening_browser(self, timer):
        open_browser(8123)
        timer.assert_called_once_with(
            1,
            web_app.webbrowser.open,
            args=("http://127.0.0.1:8123/",),
        )
        timer.return_value.start.assert_called_once()

    def test_extract_article_preserves_images_and_removes_scripts(self):
        html = """
        <html><head><meta property="og:title" content="Test Article"></head>
        <body><article><h1>Test Article</h1><div class="body markup">
        <p>This article has enough text to be selected as the full article body.</p>
        <figure><img src="/chart.png" alt="Chart"><figcaption>Data</figcaption></figure>
        <script>bad()</script><iframe src="https://example.com"></iframe>
        </div></article></body></html>
        """
        title, body = extract_article(html, "https://example.substack.com/p/test")
        self.assertEqual(title, "Test Article")
        self.assertEqual(body.img["src"], "/chart.png")
        self.assertEqual(body.img["alt"], "Chart")
        self.assertIsNone(body.find("script"))
        self.assertIsNone(body.find("iframe"))

    def test_extract_article_prefers_article_title_over_publication_name(self):
        html = """
        <html><head><meta property="og:title" content="Actual Article"></head>
        <body><h1>Publication Name</h1><div class="available-content">
        <p>This article has enough text to be selected as the full article body.</p>
        <h2>Actual Article</h2><p>More content remains in the article body.</p>
        </div></body></html>
        """
        title, body = extract_article(html, "https://example.substack.com/p/test")
        self.assertEqual(title, "Actual Article")
        self.assertIsNone(body.find("h2", string="Actual Article"))
        self.assertIn("More content remains", body.get_text())

    def test_post_title_wins_and_self_link_is_removed(self):
        html = """
        <html><head><meta property="og:title" content="Publication Name"></head>
        <body><h1 class="post-title">Sztuka bycia zaradnym</h1>
        <div class="available-content"><p>This is enough article text to pass
        the article body length check and be selected by the parser.</p>
        <a href="https://example.substack.com/p/test?utm_source=email">Read this page</a>
        </div></body></html>
        """
        title, body = extract_article(
            html, "https://example.substack.com/p/test"
        )
        self.assertEqual(title, "Sztuka bycia zaradnym")
        self.assertIsNone(body.find("a", href=True))
        self.assertIn("Read this page", body.get_text())

    def test_extract_article_removes_embedded_digest_posts(self):
        html = """
        <html><body><h1 class="post-title">Article</h1>
        <div class="available-content">
        <p>This is the actual article content and is long enough to be selected.</p>
        <div data-component-name="DigestPostEmbed">
          <p>Another article embedded here</p><a href="/p/another">Read it</a>
        </div>
        <div class="subscription-widget-wrap">
          <p>Subscribe to keep reading</p><a href="/subscribe">Subscribe</a>
        </div>
        <p>More actual article content.</p>
        </div></body></html>
        """
        title, body = extract_article(
            html, "https://example.substack.com/p/article"
        )
        self.assertEqual(title, "Article")
        self.assertNotIn("Another article embedded here", body.get_text())
        self.assertNotIn("Read it", body.get_text())
        self.assertNotIn("Subscribe to keep reading", body.get_text())
        self.assertNotIn("Subscribe", body.get_text())
        self.assertIn("More actual article content.", body.get_text())

    def test_slugify_returns_safe_nonempty_filename(self):
        self.assertEqual(slugify("A Good Article!"), "a-good-article")
        self.assertEqual(
            slugify("Sztuka bycia zaradnym, czyli co warto umieć"),
            "sztuka-bycia-zaradnym-czyli-co-warto-umiec",
        )
        self.assertEqual(slugify("..."), "substack-article")

    def test_filename_preserves_polish_title_and_removes_windows_invalid_chars(self):
        self.assertEqual(
            filename_from_title("Dlaczego wybrałem inwestowanie dywidendowe?"),
            "Dlaczego wybrałem inwestowanie dywidendowe",
        )

    def test_clean_html_is_saved_and_epub_converts_that_file(self):
        body = BeautifulSoup(
            '<p>Original content.</p>'
            '<img src="article-assets/images/chart.png" alt="Chart">',
            "html.parser",
        )
        with tempfile.TemporaryDirectory() as directory:
            html_path = Path(directory) / "article.html"
            epub_path = Path(directory) / "article.epub"
            write_clean_html(
                "<Test & Title>",
                body,
                [("images/chart.png", "image/png", b"image bytes")],
                html_path,
                "https://example.substack.com/p/article",
            )
            saved_html = html_path.read_text(encoding="utf-8")
            self.assertEqual(
                BeautifulSoup(saved_html, "html.parser").title.get_text(strip=True),
                "<Test & Title>",
            )
            self.assertEqual(
                BeautifulSoup(saved_html, "html.parser").body.h1.get_text(strip=True),
                "<Test & Title>",
            )
            self.assertIn("article-assets/images/chart.png", saved_html)
            self.assertEqual(
                (Path(directory) / "article-assets/images/chart.png").read_bytes(),
                b"image bytes",
            )
            html_path.write_text(
                saved_html.replace("Original content.", "Reviewed content."),
                encoding="utf-8",
            )

            make_epub(html_path, epub_path)
            with zipfile.ZipFile(epub_path) as archive:
                self.assertEqual(archive.namelist()[0], "mimetype")
                package = ET.fromstring(archive.read("EPUB/content.opf"))
                ns = {"opf": "http://www.idpf.org/2007/opf"}
                manifest = {
                    item.attrib["id"]: item.attrib["href"]
                    for item in package.findall("opf:manifest/opf:item", ns)
                }
                reading_order = [
                    manifest[item.attrib["idref"]]
                    for item in package.findall("opf:spine/opf:itemref", ns)
                ]
                self.assertEqual(reading_order, ["text/article.xhtml"])
                chapter = archive.read("EPUB/text/article.xhtml").decode("utf-8")
                self.assertIn("&lt;Test &amp; Title&gt;", chapter)
                chapter_soup = BeautifulSoup(chapter, "html.parser")
                self.assertEqual(
                    chapter_soup.body.h1.get_text(strip=True), "<Test & Title>"
                )
                self.assertIn("Reviewed content.", chapter)
                self.assertNotIn("Original content.", chapter)
                self.assertIn("EPUB/images/chart.png", archive.namelist())

    def test_make_epub_rejects_external_html_images(self):
        with tempfile.TemporaryDirectory() as directory:
            html_path = Path(directory) / "article.html"
            html_path.write_text(
                '<html><head><title>Article</title></head><body>'
                '<img src="https://example.com/chart.png"></body></html>',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "local image files"):
                make_epub(html_path, Path(directory) / "article.epub")

    def test_download_images_uses_lazy_source_and_skips_http(self):
        body = BeautifulSoup(
            '<div><img src="data:image/gif;base64,placeholder" '
            'data-src="/chart.png"><img src="http://example.com/pixel.png"></div>',
            "html.parser",
        )
        session = Mock()
        response = Mock()
        response.headers = {"Content-Type": "image/png"}
        response.iter_content.return_value = [b"chart"]
        session.get.return_value = response
        images, skipped = download_images(
            body, "https://example.substack.com/p/article", session, "assets/"
        )
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0][2], b"chart")
        self.assertEqual(skipped, 1)
        self.assertEqual(body.img["src"], "assets/images/image-1.png")
        response.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
