from __future__ import annotations

from dataclasses import dataclass
import re
import xml.etree.ElementTree as ET


HANJA_CHARS = (
    "\u3400-\u4dbf"
    "\u4e00-\u9fff"
    "\uf900-\ufaff"
    "\U00020000-\U0002A6DF"
    "\U0002A700-\U0002B73F"
    "\U0002B740-\U0002B81F"
    "\U0002B820-\U0002CEAF"
    "\U0002CEB0-\U0002EBEF"
)
HANGUL_CHARS = "\uac00-\ud7a3"

HANGUL_RE = re.compile(f"[{HANGUL_CHARS}]")
PARALLEL_HANJA_RE = re.compile(
    rf"(?P<base>[{HANGUL_CHARS}]+)\((?P<reading>[{HANJA_CHARS}]+)\)"
)
HANJA_ONLY_RE = re.compile(rf"^[{HANJA_CHARS}]+$")


@dataclass(frozen=True)
class RubyAnnotation:
    start: int
    end: int
    base: str
    reading: str


@dataclass(frozen=True)
class _ConvertedAnnotation:
    start: int
    end: int
    base: str
    reading: str


def has_hangul(text: str) -> bool:
    return bool(HANGUL_RE.search(text))


def has_parallel_hanja(text: str) -> bool:
    return bool(PARALLEL_HANJA_RE.search(text))


def qname(namespace: str | None, local_name: str) -> str:
    if namespace:
        return f"{{{namespace}}}{local_name}"
    return local_name


def local_name(tag: str) -> str:
    if tag.startswith("{"):
        return tag.rsplit("}", 1)[1]
    return tag


def namespace_uri(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def make_ruby(base: str, reading: str, namespace: str | None = None) -> ET.Element:
    ruby = ET.Element(qname(namespace, "ruby"))
    ruby.text = base

    rp_open = ET.SubElement(ruby, qname(namespace, "rp"))
    rp_open.text = "("

    rt = ET.SubElement(ruby, qname(namespace, "rt"))
    rt.text = reading

    rp_close = ET.SubElement(ruby, qname(namespace, "rp"))
    rp_close.text = ")"

    return ruby


def parallel_hanja_annotations(original: str, converted: str) -> list[RubyAnnotation]:
    """Align UTagger's parallel Hanja notation back to the original text.

    UTagger's 병기 output preserves the Hangul sentence and inserts Hanja in
    parentheses after selected words. Prefer positional alignment against the
    de-annotated converted sentence so repeated words map to the occurrence
    UTagger actually annotated. Fall back to an ordered search if UTagger
    normalizes the surrounding text.
    """

    converted_plain, converted_annotations = _strip_parallel_hanja(converted)
    if not converted_annotations:
        return []

    original_plain, original_to_plain_source = _strip_parallel_hanja_with_mapping(original)
    if converted_plain == original_plain:
        return _annotations_from_plain_mapping(
            original,
            converted_annotations,
            original_to_plain_source,
        )

    return _annotations_by_ordered_search(original, converted_annotations)


def existing_parallel_hanja_annotations(text: str) -> list[RubyAnnotation]:
    """Return safe annotations already present as ``한글(漢字)`` in source text.

    Source EPUBs sometimes contain author-provided Hanja parentheses. Convert
    obvious one-to-one pairs, but leave phrase-level notes alone. For example,
    ``반(反)민주적`` is safe, while ``유치 산업(幼稚産業)`` should keep its
    parentheses because the reading applies to the whole phrase, not just
    ``산업``.
    """

    annotations: list[RubyAnnotation] = []
    for match in PARALLEL_HANJA_RE.finditer(text):
        base = match.group("base")
        reading = match.group("reading")
        if len(base) != len(reading):
            continue

        annotations.append(
            RubyAnnotation(
                start=match.start(),
                end=match.end(),
                base=base,
                reading=reading,
            )
        )

    return annotations


def annotations_to_ruby_fragments(
    text: str,
    annotations: list[RubyAnnotation],
    namespace: str | None = None,
) -> list[str | ET.Element]:
    fragments: list[str | ET.Element] = []
    cursor = 0

    for annotation in annotations:
        if annotation.start < cursor or annotation.start >= annotation.end:
            continue
        if annotation.end > len(text):
            continue
        if annotation.start > cursor:
            fragments.append(text[cursor : annotation.start])

        fragments.append(make_ruby(annotation.base, annotation.reading, namespace))
        cursor = annotation.end

    if cursor < len(text):
        fragments.append(text[cursor:])

    return fragments or [text]


def _strip_parallel_hanja(text: str) -> tuple[str, list[_ConvertedAnnotation]]:
    plain_parts: list[str] = []
    annotations: list[_ConvertedAnnotation] = []
    cursor = 0
    plain_cursor = 0

    for match in PARALLEL_HANJA_RE.finditer(text):
        prefix = text[cursor : match.start()]
        plain_parts.append(prefix)
        plain_cursor += len(prefix)

        base = match.group("base")
        reading = match.group("reading")
        plain_parts.append(base)
        annotations.append(
            _ConvertedAnnotation(
                start=plain_cursor,
                end=plain_cursor + len(base),
                base=base,
                reading=reading,
            )
        )
        plain_cursor += len(base)
        cursor = match.end()

    plain_parts.append(text[cursor:])
    return "".join(plain_parts), annotations


def _strip_parallel_hanja_with_mapping(text: str) -> tuple[str, list[int]]:
    plain_parts: list[str] = []
    source_indexes: list[int] = []
    cursor = 0

    def append_slice(start: int, end: int) -> None:
        plain_parts.append(text[start:end])
        source_indexes.extend(range(start, end))

    for match in PARALLEL_HANJA_RE.finditer(text):
        append_slice(cursor, match.start())
        base_start = match.start("base")
        base_end = match.end("base")
        append_slice(base_start, base_end)
        cursor = match.end()

    append_slice(cursor, len(text))
    return "".join(plain_parts), source_indexes


def _annotations_from_plain_mapping(
    original: str,
    converted_annotations: list[_ConvertedAnnotation],
    original_to_plain_source: list[int],
) -> list[RubyAnnotation]:
    annotations: list[RubyAnnotation] = []

    for annotation in converted_annotations:
        if annotation.end > len(original_to_plain_source):
            continue

        start = original_to_plain_source[annotation.start]
        end = original_to_plain_source[annotation.end - 1] + 1
        if original[start:end] != annotation.base:
            continue
        if _has_existing_parallel_hanja_at(original, start, end):
            continue

        annotations.append(
            RubyAnnotation(
                start=start,
                end=end,
                base=annotation.base,
                reading=annotation.reading,
            )
        )

    return annotations


def _annotations_by_ordered_search(
    original: str,
    converted_annotations: list[_ConvertedAnnotation],
) -> list[RubyAnnotation]:
    annotations: list[RubyAnnotation] = []
    cursor = 0

    for annotation in converted_annotations:
        start = original.find(annotation.base, cursor)
        while start != -1:
            end = start + len(annotation.base)
            if not _has_existing_parallel_hanja_at(original, start, end):
                break
            start = original.find(annotation.base, end)

        if start == -1:
            continue

        end = start + len(annotation.base)
        annotations.append(
            RubyAnnotation(
                start=start,
                end=end,
                base=annotation.base,
                reading=annotation.reading,
            )
        )
        cursor = end

    return annotations


def _has_existing_parallel_hanja_at(original: str, start: int, end: int) -> bool:
    if end >= len(original) or original[end] != "(":
        return False

    close = original.find(")", end + 1)
    if close == -1:
        return False

    return bool(HANJA_ONLY_RE.fullmatch(original[end + 1 : close]))


def ruby_fragments(text: str, namespace: str | None = None) -> list[str | ET.Element]:
    fragments: list[str | ET.Element] = []
    cursor = 0

    for match in PARALLEL_HANJA_RE.finditer(text):
        if match.start() > cursor:
            fragments.append(text[cursor : match.start()])

        fragments.append(make_ruby(match.group("base"), match.group("reading"), namespace))
        cursor = match.end()

    if cursor < len(text):
        fragments.append(text[cursor:])

    return fragments or [text]
