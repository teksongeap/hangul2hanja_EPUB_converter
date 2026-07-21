from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from h2h_converter.epub import collect_epub_texts, convert_epub, transform_xhtml_bytes


class FakeConverter:
    def convert(self, text: str) -> str:
        return text.replace(
            "대한민국의 역사는 오래되었다.",
            "대한민국(大韓民國)의 역사(歷史)는 오래되었다.",
        )


class RepeatedBaseConverter:
    def convert(self, text: str) -> str:
        return text.replace("역사는 역사다.", "역사는 역사(歷史)다.")


class ExistingParallelConverter:
    def convert(self, text: str) -> str:
        return text.replace(
            "역사(歷史)는 역사다.",
            "역사(歷史)는 역사(歷史)다.",
        )


class NormalizingConverter:
    def convert(self, text: str) -> str:
        return text.replace(
            "대한민국의 역사는 오래되었다.",
            "대한민국(大韓民國)의 역사(歷史)는 오래됐습니다.",
        )


class IdentityConverter:
    def convert(self, text: str) -> str:
        return text


class BatchConverter:
    def __init__(self) -> None:
        self.batch_calls = 0
        self.convert_calls = 0

    def convert(self, text: str) -> str:
        self.convert_calls += 1
        return text

    def convert_many(self, texts: list[str]) -> list[str]:
        self.batch_calls += 1
        return [
            text.replace("대한민국", "대한민국(大韓民國)").replace("역사", "역사(歷史)")
            for text in texts
        ]


class EpubConversionTests(unittest.TestCase):
    def test_convert_epub_writes_ruby_markup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            input_epub = tmp_path / "input.epub"
            output_epub = tmp_path / "output.epub"
            _write_minimal_epub(input_epub)

            stats = convert_epub(input_epub, output_epub, FakeConverter())

            self.assertEqual(stats.documents, 1)
            self.assertEqual(stats.ruby_nodes, 2)

            with zipfile.ZipFile(output_epub) as epub:
                chapter = epub.read("OEBPS/chapter.xhtml").decode("utf-8")
                self.assertIn(
                    "<ruby>대한민국<rp>(</rp><rt>大韓民國</rt><rp>)</rp></ruby>",
                    chapter,
                )
                self.assertIn(
                    "<ruby>역사<rp>(</rp><rt>歷史</rt><rp>)</rp></ruby>는",
                    chapter,
                )
                self.assertIn("data-h2h-ruby-style", chapter)

    def test_convert_epub_reports_progress_per_document(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            input_epub = tmp_path / "input.epub"
            output_epub = tmp_path / "output.epub"
            _write_minimal_epub(input_epub)

            calls: list[tuple[int, int, str]] = []
            stats = convert_epub(
                input_epub,
                output_epub,
                FakeConverter(),
                progress=lambda current, total, name: calls.append((current, total, name)),
            )

            self.assertEqual(stats.documents, 1)
            self.assertEqual(calls, [(1, 1, "OEBPS/chapter.xhtml")])

    def test_collect_epub_texts_returns_segments_in_reading_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_epub = Path(temp_dir) / "input.epub"
            _write_minimal_epub(input_epub)

            texts = collect_epub_texts(input_epub, 5)

            self.assertEqual(
                texts,
                [("OEBPS/chapter.xhtml", "대한민국의 역사는 오래되었다.")],
            )

    def test_collect_epub_texts_respects_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            input_epub = Path(temp_dir) / "input.epub"
            _write_minimal_epub(input_epub)

            self.assertEqual(len(collect_epub_texts(input_epub, 1)), 1)
            self.assertEqual(collect_epub_texts(input_epub, 0), [])

    def test_transform_xhtml_maps_annotations_across_inline_tags(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body>
    <p><span>대한</span><span>민국의 역</span><span>사는 오래되었다.</span></p>
  </body>
</html>"""

        converted, stats = transform_xhtml_bytes(xhtml.encode("utf-8"), FakeConverter())
        output = converted.decode("utf-8")

        self.assertEqual(stats.text_nodes, 1)
        self.assertEqual(stats.ruby_nodes, 2)
        self.assertIn(
            "<ruby>대한민국<rp>(</rp><rt>大韓民國</rt><rp>)</rp></ruby>",
            output,
        )
        self.assertIn(
            "<ruby>역사<rp>(</rp><rt>歷史</rt><rp>)</rp></ruby>",
            output,
        )
        self.assertIn("<span>의 <ruby>역사", output)
        self.assertIn("<span>는 오래되었다.</span>", output)

    def test_transform_xhtml_repairs_common_html_entities(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><p>대한민국&nbsp;역사</p></body>
</html>"""

        converted, stats = transform_xhtml_bytes(xhtml.encode("utf-8"), FakeConverter())

        self.assertEqual(stats.documents, 1)
        self.assertIn("대한민국\u00a0역사", converted.decode("utf-8"))

    def test_transform_xhtml_uses_annotation_position_for_repeated_text(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><p>역사는 역사다.</p></body>
</html>"""

        converted, stats = transform_xhtml_bytes(
            xhtml.encode("utf-8"), RepeatedBaseConverter()
        )
        output = converted.decode("utf-8")

        self.assertEqual(stats.ruby_nodes, 1)
        self.assertIn("<p>역사는 <ruby>역사", output)

    def test_transform_xhtml_preserves_existing_parallel_hanja(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><p>역사(歷史)는 역사다.</p></body>
</html>"""

        converted, stats = transform_xhtml_bytes(
            xhtml.encode("utf-8"), ExistingParallelConverter()
        )
        output = converted.decode("utf-8")

        self.assertEqual(stats.ruby_nodes, 2)
        self.assertIn(
            "<ruby>역사<rp>(</rp><rt>歷史</rt><rp>)</rp></ruby>는 "
            "<ruby>역사",
            output,
        )
        self.assertNotIn("역사(歷史)", output)
        self.assertEqual(output.count("<ruby>"), 2)

    def test_transform_xhtml_leaves_phrase_level_existing_hanja(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><p>반(反)민주적 유치 산업(幼稚産業)</p></body>
</html>"""

        converted, stats = transform_xhtml_bytes(xhtml.encode("utf-8"), IdentityConverter())
        output = converted.decode("utf-8")

        self.assertEqual(stats.ruby_nodes, 1)
        self.assertIn("<ruby>반<rp>(</rp><rt>反</rt><rp>)</rp></ruby>민주적", output)
        self.assertIn("유치 산업(幼稚産業)", output)

    def test_transform_xhtml_fallback_preserves_original_text(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body>
    <p>Anchor</p>
    <span>대한민국의 역사는 오래되었다.</span>
  </body>
</html>"""

        converted, stats = transform_xhtml_bytes(
            xhtml.encode("utf-8"), NormalizingConverter()
        )
        output = converted.decode("utf-8")

        self.assertEqual(stats.ruby_nodes, 2)
        self.assertIn("는 오래되었다.</span>", output)
        self.assertNotIn("오래됐습니다", output)

    def test_transform_xhtml_uses_batch_converter_when_available(self) -> None:
        xhtml = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body>
    <p>대한민국</p>
    <p>역사</p>
  </body>
</html>"""
        converter = BatchConverter()

        converted, stats = transform_xhtml_bytes(xhtml.encode("utf-8"), converter)
        output = converted.decode("utf-8")

        self.assertEqual(converter.batch_calls, 1)
        self.assertEqual(converter.convert_calls, 0)
        self.assertEqual(stats.ruby_nodes, 2)
        self.assertIn("<ruby>대한민국", output)
        self.assertIn("<ruby>역사", output)

    def test_convert_epub_preserves_missing_spine_documents_with_warning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            input_epub = tmp_path / "input.epub"
            output_epub = tmp_path / "output.epub"
            _write_minimal_epub(input_epub, include_chapter=False)

            stats = convert_epub(input_epub, output_epub, FakeConverter())

            self.assertEqual(stats.documents, 0)
            self.assertEqual(stats.skipped_documents, 1)
            self.assertEqual(len(stats.warnings), 1)
            self.assertTrue(output_epub.exists())

    def test_convert_epub_accepts_html_href_variants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            input_epub = tmp_path / "input.epub"
            output_epub = tmp_path / "output.epub"
            _write_minimal_epub(
                input_epub,
                chapter_href="Chapter.HTM?cache=1",
                chapter_media_type="application/octet-stream",
            )

            stats = convert_epub(input_epub, output_epub, FakeConverter())

            self.assertEqual(stats.documents, 1)
            self.assertEqual(stats.skipped_documents, 0)
            with zipfile.ZipFile(output_epub) as epub:
                chapter = epub.read("OEBPS/Chapter.HTM").decode("utf-8")
                self.assertIn("<ruby>대한민국", chapter)


def _write_minimal_epub(
    path: Path,
    *,
    include_chapter: bool = True,
    chapter_href: str = "chapter.xhtml",
    chapter_media_type: str = "application/xhtml+xml",
) -> None:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="book-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">test-book</dc:identifier>
    <dc:title>Test Book</dc:title>
    <dc:language>ko</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="{chapter_href}" media-type="{chapter_media_type}"/>
  </manifest>
  <spine>
    <itemref idref="chapter"/>
  </spine>
</package>"""
    chapter = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <head><title>Test</title></head>
  <body><!-- comment --><p>대한민국의 역사는 오래되었다.</p></body>
</html>"""

    with zipfile.ZipFile(path, "w") as epub:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        epub.writestr(info, "application/epub+zip")
        epub.writestr("META-INF/container.xml", container_xml)
        epub.writestr("OEBPS/content.opf", opf)
        if include_chapter:
            chapter_member = chapter_href.split("#", 1)[0].split("?", 1)[0]
            epub.writestr(f"OEBPS/{chapter_member}", chapter)


if __name__ == "__main__":
    unittest.main()
