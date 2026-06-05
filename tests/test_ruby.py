from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from h2h_converter.ruby import (
    annotations_to_ruby_fragments,
    existing_parallel_hanja_annotations,
    parallel_hanja_annotations,
    ruby_fragments,
)


class RubyFragmentTests(unittest.TestCase):
    def test_ruby_fragments_convert_parallel_hanja_notation(self) -> None:
        fragments = ruby_fragments("대한민국(大韓民國)의 역사(歷史)는 오래되었다.")

        self.assertEqual(fragments[1], "의 ")
        ruby_nodes = [fragment for fragment in fragments if isinstance(fragment, ET.Element)]
        self.assertEqual(len(ruby_nodes), 2)
        self.assertEqual(ruby_nodes[0].text, "대한민국")
        self.assertEqual(ruby_nodes[0].find("rt").text, "大韓民國")
        self.assertEqual(ruby_nodes[1].text, "역사")
        self.assertEqual(ruby_nodes[1].find("rt").text, "歷史")

    def test_parallel_hanja_annotations_align_to_original_text(self) -> None:
        annotations = parallel_hanja_annotations(
            "대한민국의 역사는 오래되었다.",
            "대한민국(大韓民國)의 역사(歷史)는 오래되었다.",
        )

        self.assertEqual(len(annotations), 2)
        self.assertEqual((annotations[0].start, annotations[0].end), (0, 4))
        self.assertEqual(annotations[0].reading, "大韓民國")
        self.assertEqual((annotations[1].start, annotations[1].end), (6, 8))
        self.assertEqual(annotations[1].reading, "歷史")

    def test_parallel_hanja_annotations_use_converted_position_for_repeated_base(self) -> None:
        annotations = parallel_hanja_annotations(
            "역사는 역사다.",
            "역사는 역사(歷史)다.",
        )

        self.assertEqual(len(annotations), 1)
        self.assertEqual((annotations[0].start, annotations[0].end), (4, 6))
        self.assertEqual(annotations[0].reading, "歷史")

    def test_parallel_hanja_annotations_skip_existing_parallel_hanja(self) -> None:
        original = "역사(歷史)는 역사다."
        annotations = parallel_hanja_annotations(
            original,
            "역사(歷史)는 역사(歷史)다.",
        )

        second_history = original.rfind("역사")
        self.assertEqual(len(annotations), 1)
        self.assertEqual(
            (annotations[0].start, annotations[0].end),
            (second_history, second_history + 2),
        )

    def test_existing_parallel_hanja_annotations_convert_safe_source_pairs(self) -> None:
        original = "반(反)민주적 역사(歷史)"
        annotations = existing_parallel_hanja_annotations(original)

        self.assertEqual(len(annotations), 2)
        fragments = annotations_to_ruby_fragments(original, annotations)
        ruby_nodes = [fragment for fragment in fragments if isinstance(fragment, ET.Element)]

        self.assertEqual("".join(fragment for fragment in fragments if isinstance(fragment, str)), "민주적 ")
        self.assertEqual(ruby_nodes[0].text, "반")
        self.assertEqual(ruby_nodes[0].find("rt").text, "反")
        self.assertEqual(ruby_nodes[1].text, "역사")
        self.assertEqual(ruby_nodes[1].find("rt").text, "歷史")

    def test_existing_parallel_hanja_annotations_skip_phrase_level_readings(self) -> None:
        annotations = existing_parallel_hanja_annotations("유치 산업(幼稚産業)")

        self.assertEqual(annotations, [])

    def test_annotations_to_ruby_fragments_preserve_original_text(self) -> None:
        original = "대한민국의 역사는 오래되었다."
        annotations = parallel_hanja_annotations(
            original,
            "대한민국(大韓民國)의 역사(歷史)는 오래됐습니다.",
        )

        fragments = annotations_to_ruby_fragments(original, annotations)

        self.assertEqual(fragments[-1], "는 오래되었다.")
        ruby_nodes = [fragment for fragment in fragments if isinstance(fragment, ET.Element)]
        self.assertEqual(len(ruby_nodes), 2)


if __name__ == "__main__":
    unittest.main()
