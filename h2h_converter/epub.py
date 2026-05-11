from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import posixpath
import shutil
import tempfile
from typing import Protocol
from urllib.parse import unquote
import zipfile
import xml.etree.ElementTree as ET

from .ruby import has_hangul, local_name, namespace_uri, qname, ruby_fragments


XHTML_NS = "http://www.w3.org/1999/xhtml"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"

DEFAULT_RUBY_CSS = """ruby { ruby-position: over; }
rt { font-size: 0.5em; line-height: 1; }"""

SKIP_TEXT_TAGS = {
    "script",
    "style",
    "ruby",
    "rt",
    "rp",
    "title",
    "svg",
    "math",
    "code",
    "pre",
    "textarea",
}


class TextConverter(Protocol):
    def convert(self, text: str) -> str:
        ...


@dataclass
class ConversionStats:
    documents: int = 0
    text_nodes: int = 0
    ruby_nodes: int = 0

    def add(self, other: "ConversionStats") -> None:
        self.documents += other.documents
        self.text_nodes += other.text_nodes
        self.ruby_nodes += other.ruby_nodes


def convert_epub(
    input_epub: Path,
    output_epub: Path,
    converter: TextConverter,
    *,
    add_css: bool = True,
    overwrite: bool = False,
) -> ConversionStats:
    input_epub = Path(input_epub)
    output_epub = Path(output_epub)

    if not input_epub.exists():
        raise FileNotFoundError(input_epub)
    if output_epub.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_epub}")

    with zipfile.ZipFile(input_epub, "r") as source:
        rootfile = _find_rootfile(source)
        spine_docs = _find_spine_documents(source.read(rootfile), rootfile)
        modified: dict[str, bytes] = {}
        stats = ConversionStats()

        for doc_path in spine_docs:
            if doc_path not in source.namelist():
                continue
            converted, doc_stats = transform_xhtml_bytes(
                source.read(doc_path), converter, add_css=add_css
            )
            modified[doc_path] = converted
            stats.add(doc_stats)

        _write_epub(source, output_epub, modified)

    return stats


def transform_xhtml_bytes(
    data: bytes,
    converter: TextConverter,
    *,
    add_css: bool = True,
) -> tuple[bytes, ConversionStats]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(data, parser=parser)
    namespace = namespace_uri(root.tag)

    if namespace == XHTML_NS:
        ET.register_namespace("", XHTML_NS)

    stats = ConversionStats(documents=1)
    _transform_element(root, converter, namespace, stats)

    if add_css:
        _ensure_ruby_style(root, namespace)

    return (
        ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=False),
        stats,
    )


def _transform_element(
    element: ET.Element,
    converter: TextConverter,
    namespace: str | None,
    stats: ConversionStats,
) -> None:
    if not isinstance(element.tag, str):
        return

    if local_name(element.tag) in SKIP_TEXT_TAGS:
        return

    original_children = list(element)

    if element.text:
        fragments = _convert_text_to_fragments(element.text, converter, namespace, stats)
        _replace_element_text(element, fragments)

    for child in original_children:
        _transform_element(child, converter, namespace, stats)
        if child.tail:
            fragments = _convert_text_to_fragments(child.tail, converter, namespace, stats)
            _replace_child_tail(element, child, fragments)


def _convert_text_to_fragments(
    text: str,
    converter: TextConverter,
    namespace: str | None,
    stats: ConversionStats,
) -> list[str | ET.Element]:
    if not has_hangul(text):
        return [text]

    converted = converter.convert(text)
    fragments = ruby_fragments(converted, namespace)
    stats.text_nodes += 1
    stats.ruby_nodes += sum(isinstance(fragment, ET.Element) for fragment in fragments)
    return fragments


def _replace_element_text(element: ET.Element, fragments: list[str | ET.Element]) -> None:
    element.text = None
    insert_at = 0
    previous: ET.Element | None = None

    for fragment in fragments:
        if isinstance(fragment, str):
            if previous is None:
                element.text = (element.text or "") + fragment
            else:
                previous.tail = (previous.tail or "") + fragment
            continue

        element.insert(insert_at, fragment)
        insert_at += 1
        previous = fragment


def _replace_child_tail(
    parent: ET.Element, child: ET.Element, fragments: list[str | ET.Element]
) -> None:
    child.tail = None
    insert_at = list(parent).index(child) + 1
    previous = child

    for fragment in fragments:
        if isinstance(fragment, str):
            previous.tail = (previous.tail or "") + fragment
            continue

        parent.insert(insert_at, fragment)
        insert_at += 1
        previous = fragment


def _ensure_ruby_style(root: ET.Element, namespace: str | None) -> None:
    head = _find_child(root, "head")
    if head is None:
        return

    for child in head:
        if local_name(child.tag) == "style" and child.attrib.get("data-h2h-ruby-style"):
            return

    style = ET.Element(
        qname(namespace, "style"),
        {"type": "text/css", "data-h2h-ruby-style": "true"},
    )
    style.text = DEFAULT_RUBY_CSS
    head.append(style)


def _find_child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if local_name(child.tag) == name:
            return child
    return None


def _find_rootfile(epub: zipfile.ZipFile) -> str:
    container = ET.fromstring(epub.read("META-INF/container.xml"))
    rootfile = container.find(f".//{{{CONTAINER_NS}}}rootfile")
    if rootfile is None:
        rootfile = container.find(".//rootfile")
    if rootfile is None or "full-path" not in rootfile.attrib:
        raise ValueError("EPUB container.xml does not name an OPF package file.")
    return rootfile.attrib["full-path"]


def _find_spine_documents(opf_data: bytes, opf_path: str) -> list[str]:
    package = ET.fromstring(opf_data)
    manifest: dict[str, str] = {}

    for item in package.findall(f".//{{{OPF_NS}}}manifest/{{{OPF_NS}}}item"):
        media_type = item.attrib.get("media-type", "")
        href = item.attrib.get("href")
        item_id = item.attrib.get("id")
        if not href or not item_id:
            continue
        if media_type in {"application/xhtml+xml", "text/html"} or href.endswith((".xhtml", ".html")):
            manifest[item_id] = _resolve_epub_href(opf_path, href)

    if not manifest:
        for item in package.findall(".//manifest/item"):
            href = item.attrib.get("href")
            item_id = item.attrib.get("id")
            if href and item_id and href.endswith((".xhtml", ".html")):
                manifest[item_id] = _resolve_epub_href(opf_path, href)

    docs: list[str] = []
    for itemref in package.findall(f".//{{{OPF_NS}}}spine/{{{OPF_NS}}}itemref"):
        doc = manifest.get(itemref.attrib.get("idref", ""))
        if doc:
            docs.append(doc)

    if not docs:
        for itemref in package.findall(".//spine/itemref"):
            doc = manifest.get(itemref.attrib.get("idref", ""))
            if doc:
                docs.append(doc)

    return docs


def _resolve_epub_href(opf_path: str, href: str) -> str:
    href = unquote(href.split("#", 1)[0])
    base = posixpath.dirname(opf_path)
    return PurePosixPath(posixpath.normpath(posixpath.join(base, href))).as_posix()


def _write_epub(
    source: zipfile.ZipFile,
    output_epub: Path,
    modified: dict[str, bytes],
) -> None:
    output_epub.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=".epub") as tmp_file:
        tmp_path = Path(tmp_file.name)

    try:
        with zipfile.ZipFile(tmp_path, "w") as target:
            names = source.namelist()
            if "mimetype" in names:
                target.writestr(
                    _clone_zip_info(source.getinfo("mimetype"), zipfile.ZIP_STORED),
                    source.read("mimetype"),
                )
                names = [name for name in names if name != "mimetype"]

            for name in names:
                info = source.getinfo(name)
                data = modified.get(name, source.read(name))
                target.writestr(_clone_zip_info(info, info.compress_type), data)

        shutil.move(str(tmp_path), output_epub)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _clone_zip_info(info: zipfile.ZipInfo, compress_type: int) -> zipfile.ZipInfo:
    clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
    clone.compress_type = compress_type
    clone.comment = info.comment
    clone.extra = info.extra
    clone.internal_attr = info.internal_attr
    clone.external_attr = info.external_attr
    return clone
