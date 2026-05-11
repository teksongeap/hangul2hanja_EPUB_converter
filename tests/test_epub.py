from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
import zipfile

from h2h_converter.epub import convert_epub


class FakeConverter:
    def convert(self, text: str) -> str:
        return text.replace(
            "대한민국의 역사는 오래되었다.",
            "대한민국(大韓民國)의 역사(歷史)는 오래되었다.",
        )


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


def _write_minimal_epub(path: Path) -> None:
    container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
    opf = """<?xml version="1.0" encoding="UTF-8"?>
<package version="3.0" unique-identifier="book-id" xmlns="http://www.idpf.org/2007/opf">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="book-id">test-book</dc:identifier>
    <dc:title>Test Book</dc:title>
    <dc:language>ko</dc:language>
  </metadata>
  <manifest>
    <item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/>
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
        epub.writestr("OEBPS/chapter.xhtml", chapter)


if __name__ == "__main__":
    unittest.main()
