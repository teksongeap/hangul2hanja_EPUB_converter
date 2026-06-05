from __future__ import annotations

from dataclasses import dataclass, field
from html.entities import name2codepoint
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import tempfile
from typing import Protocol
from urllib.parse import unquote
import zipfile
import xml.etree.ElementTree as ET

from .ruby import (
    RubyAnnotation,
    annotations_to_ruby_fragments,
    existing_parallel_hanja_annotations,
    has_hangul,
    local_name,
    make_ruby,
    namespace_uri,
    parallel_hanja_annotations,
    qname,
)


XHTML_NS = "http://www.w3.org/1999/xhtml"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"
OPF_NS = "http://www.idpf.org/2007/opf"

DEFAULT_RUBY_CSS = """ruby { ruby-position: over; }
rt { font-size: 0.5em; line-height: 1; }"""

HTML_ENTITY_RE = re.compile(br"&([A-Za-z][A-Za-z0-9]+);")
XML_ENTITY_NAMES = {b"amp", b"apos", b"gt", b"lt", b"quot"}

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

TEXT_SCOPE_TAGS = {
    "p",
    "dt",
    "dd",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "caption",
    "figcaption",
}

FALLBACK_TEXT_SCOPE_TAGS = {
    "article",
    "aside",
    "blockquote",
    "body",
    "div",
    "footer",
    "header",
    "li",
    "main",
    "nav",
    "section",
    "td",
    "th",
}


class TextConverter(Protocol):
    def convert(self, text: str) -> str:
        ...


@dataclass(frozen=True)
class TextRun:
    owner: ET.Element
    kind: str
    parent: ET.Element | None
    text: str
    start: int
    end: int


@dataclass
class ConversionTask:
    kind: str
    text: str
    element: ET.Element | None = None
    child: ET.Element | None = None
    runs: list[TextRun] = field(default_factory=list)


@dataclass
class ConversionStats:
    documents: int = 0
    text_nodes: int = 0
    ruby_nodes: int = 0
    skipped_documents: int = 0
    warnings: list[str] = field(default_factory=list)

    def add(self, other: "ConversionStats") -> None:
        self.documents += other.documents
        self.text_nodes += other.text_nodes
        self.ruby_nodes += other.ruby_nodes
        self.skipped_documents += other.skipped_documents
        self.warnings.extend(other.warnings)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def convert_epub(
    input_epub: Path,
    output_epub: Path,
    converter: TextConverter,
    *,
    add_css: bool = True,
    best_effort: bool = True,
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
        rootfile_member = _find_zip_member(source, rootfile) or rootfile
        spine_docs = _find_spine_documents(source.read(rootfile_member), rootfile_member)
        source_names = set(source.namelist())
        modified: dict[str, bytes] = {}
        stats = ConversionStats()

        for doc_path in spine_docs:
            doc_member = doc_path if doc_path in source_names else _find_zip_member(source, doc_path)
            if doc_member is None:
                stats.skipped_documents += 1
                stats.warn(f"{doc_path}: spine document was listed in the OPF but missing.")
                continue

            try:
                converted, doc_stats = transform_xhtml_bytes(
                    source.read(doc_member), converter, add_css=add_css
                )
            except ET.ParseError as exc:
                if not best_effort:
                    raise
                stats.skipped_documents += 1
                stats.warn(f"{doc_path}: could not parse XHTML/XML cleanly ({exc}).")
                continue

            modified[doc_member] = converted
            stats.add(doc_stats)

        _write_epub(source, output_epub, modified)

    return stats


def transform_xhtml_bytes(
    data: bytes,
    converter: TextConverter,
    *,
    add_css: bool = True,
) -> tuple[bytes, ConversionStats]:
    root = _parse_xhtml_bytes(data)
    namespace = namespace_uri(root.tag)

    if namespace == XHTML_NS:
        ET.register_namespace("", XHTML_NS)

    stats = ConversionStats(documents=1)
    tasks: list[ConversionTask] = []
    _collect_conversion_tasks(root, tasks)
    converted_texts = _convert_task_texts(tasks, converter)
    for task, converted in zip(tasks, converted_texts):
        _apply_conversion_task(task, converted, namespace, stats)

    if add_css:
        _ensure_ruby_style(root, namespace)

    return (
        ET.tostring(root, encoding="utf-8", xml_declaration=True, short_empty_elements=False),
        stats,
    )


def _collect_conversion_tasks(
    element: ET.Element,
    tasks: list[ConversionTask],
) -> None:
    if not isinstance(element.tag, str):
        return

    if local_name(element.tag) in SKIP_TEXT_TAGS:
        return

    if _should_transform_as_text_scope(element):
        runs = _collect_text_runs(element)
        text = "".join(run.text for run in runs)
        if text and has_hangul(text):
            tasks.append(ConversionTask("scope", text, element=element, runs=runs))
        return

    original_children = list(element)

    if element.text and has_hangul(element.text):
        tasks.append(ConversionTask("text", element.text, element=element))

    for child in original_children:
        _collect_conversion_tasks(child, tasks)
        if child.tail and has_hangul(child.tail):
            tasks.append(ConversionTask("tail", child.tail, element=element, child=child))


def _convert_task_texts(
    tasks: list[ConversionTask],
    converter: TextConverter,
) -> list[str]:
    texts = [task.text for task in tasks]
    convert_many = getattr(converter, "convert_many", None)
    if callable(convert_many) and len(texts) > 1:
        converted = list(convert_many(texts))
        if len(converted) != len(texts):
            raise RuntimeError("Batch converter returned the wrong number of text segments.")
        return converted

    return [converter.convert(text) for text in texts]


def _apply_conversion_task(
    task: ConversionTask,
    converted: str,
    namespace: str | None,
    stats: ConversionStats,
) -> None:
    annotations = _annotations_for_conversion(task.text, converted)
    stats.text_nodes += 1
    stats.ruby_nodes += len(annotations)

    if not annotations:
        return

    if task.kind == "scope":
        _rewrite_text_runs_with_annotations(task.runs, annotations, namespace)
        return

    fragments = annotations_to_ruby_fragments(task.text, annotations, namespace)
    if task.kind == "text" and task.element is not None:
        _replace_element_text(task.element, fragments)
        return

    if task.kind == "tail" and task.element is not None and task.child is not None:
        _replace_child_tail(task.element, task.child, fragments)


def _should_transform_as_text_scope(element: ET.Element) -> bool:
    name = local_name(element.tag)
    if name in TEXT_SCOPE_TAGS:
        return True
    if name in FALLBACK_TEXT_SCOPE_TAGS and not _has_descendant_text_scope(element):
        return True
    return False


def _has_descendant_text_scope(element: ET.Element) -> bool:
    for child in element:
        if not isinstance(child.tag, str):
            continue
        name = local_name(child.tag)
        if name in SKIP_TEXT_TAGS:
            continue
        if name in TEXT_SCOPE_TAGS:
            return True
        if _has_descendant_text_scope(child):
            return True
    return False


def _collect_text_runs(element: ET.Element) -> list[TextRun]:
    runs: list[TextRun] = []
    cursor = 0

    def add(owner: ET.Element, kind: str, parent: ET.Element | None, text: str) -> None:
        nonlocal cursor
        runs.append(TextRun(owner, kind, parent, text, cursor, cursor + len(text)))
        cursor += len(text)

    def visit(node: ET.Element) -> None:
        if node.text:
            add(node, "text", None, node.text)

        for child in list(node):
            if isinstance(child.tag, str) and local_name(child.tag) not in SKIP_TEXT_TAGS:
                visit(child)
            if child.tail:
                add(child, "tail", node, child.tail)

    visit(element)
    return runs


def _non_overlapping_annotations(
    annotations: list[RubyAnnotation],
) -> list[RubyAnnotation]:
    filtered: list[RubyAnnotation] = []
    cursor = 0

    for annotation in annotations:
        if annotation.start < cursor or annotation.start >= annotation.end:
            continue
        filtered.append(annotation)
        cursor = annotation.end

    return filtered


def _annotations_for_conversion(original: str, converted: str) -> list[RubyAnnotation]:
    annotations = [
        *existing_parallel_hanja_annotations(original),
        *parallel_hanja_annotations(original, converted),
    ]
    return _non_overlapping_annotations(
        sorted(annotations, key=lambda annotation: (annotation.start, annotation.end))
    )


def _rewrite_text_runs_with_annotations(
    runs: list[TextRun],
    annotations: list[RubyAnnotation],
    namespace: str | None,
) -> None:
    for run in runs:
        fragments = _fragments_for_text_run(run, annotations, namespace)
        if fragments is not None:
            _replace_text_run(run, fragments)


def _fragments_for_text_run(
    run: TextRun,
    annotations: list[RubyAnnotation],
    namespace: str | None,
) -> list[str | ET.Element] | None:
    fragments: list[str | ET.Element] = []
    cursor = run.start
    touched = False

    for annotation in annotations:
        if annotation.end <= run.start:
            continue
        if annotation.start >= run.end:
            break

        text_end = max(annotation.start, run.start)
        if cursor < text_end:
            fragments.append(run.text[cursor - run.start : text_end - run.start])

        if run.start <= annotation.start < run.end:
            fragments.append(make_ruby(annotation.base, annotation.reading, namespace))

        cursor = max(cursor, min(annotation.end, run.end))
        touched = True

    if not touched:
        return None

    if cursor < run.end:
        fragments.append(run.text[cursor - run.start :])

    return fragments


def _replace_text_run(run: TextRun, fragments: list[str | ET.Element]) -> None:
    if run.kind == "text":
        _replace_element_text(run.owner, fragments)
        return

    if run.parent is not None:
        _replace_child_tail(run.parent, run.owner, fragments)


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


def _parse_xhtml_bytes(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data, parser=_xml_parser())
    except ET.ParseError:
        repaired = _replace_html_named_entities(data)
        if repaired == data:
            raise
        return ET.fromstring(repaired, parser=_xml_parser())


def _xml_parser() -> ET.XMLParser:
    return ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))


def _replace_html_named_entities(data: bytes) -> bytes:
    def replace(match: re.Match[bytes]) -> bytes:
        name = match.group(1)
        if name in XML_ENTITY_NAMES:
            return match.group(0)
        codepoint = name2codepoint.get(name.decode("ascii"))
        if codepoint is None:
            return match.group(0)
        return f"&#{codepoint};".encode("ascii")

    return HTML_ENTITY_RE.sub(replace, data)


def _find_rootfile(epub: zipfile.ZipFile) -> str:
    container_name = _find_zip_member(epub, "META-INF/container.xml")
    if container_name is None:
        raise ValueError("EPUB does not contain META-INF/container.xml.")

    container = ET.fromstring(epub.read(container_name))
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
        media_type = item.attrib.get("media-type", "").lower()
        href = item.attrib.get("href")
        item_id = item.attrib.get("id")
        if not href or not item_id:
            continue
        if media_type in {"application/xhtml+xml", "text/html"} or _looks_like_html_href(href):
            manifest[item_id] = _resolve_epub_href(opf_path, href)

    if not manifest:
        for item in package.findall(".//manifest/item"):
            href = item.attrib.get("href")
            item_id = item.attrib.get("id")
            if href and item_id and _looks_like_html_href(href):
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


def _looks_like_html_href(href: str) -> bool:
    clean_href = href.split("#", 1)[0].split("?", 1)[0].lower()
    return clean_href.endswith((".xhtml", ".html", ".htm"))


def _resolve_epub_href(opf_path: str, href: str) -> str:
    href = unquote(href.split("#", 1)[0].split("?", 1)[0])
    base = posixpath.dirname(opf_path)
    return PurePosixPath(posixpath.normpath(posixpath.join(base, href))).as_posix()


def _find_zip_member(epub: zipfile.ZipFile, expected_name: str) -> str | None:
    expected = expected_name.lower()
    for name in epub.namelist():
        if name.lower() == expected:
            return name
    return None


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
