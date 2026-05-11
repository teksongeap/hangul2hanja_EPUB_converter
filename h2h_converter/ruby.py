from __future__ import annotations

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
