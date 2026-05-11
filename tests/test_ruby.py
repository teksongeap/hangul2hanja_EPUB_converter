from __future__ import annotations

import unittest
import xml.etree.ElementTree as ET

from h2h_converter.ruby import ruby_fragments


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


if __name__ == "__main__":
    unittest.main()
