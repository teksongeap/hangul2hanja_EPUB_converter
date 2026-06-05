from __future__ import annotations

import unittest

from h2h_converter.utagger import UTaggerHanjaConverter


class RecordingUTaggerConverter(UTaggerHanjaConverter):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []

    def convert(self, text: str) -> str:
        self.calls.append(text)
        return f"{text}!"


class UTaggerConverterTests(unittest.TestCase):
    def test_convert_many_uses_original_segments_without_synthetic_batching(self) -> None:
        converter = RecordingUTaggerConverter()

        converted = converter.convert_many(["대한민국", "역사"])

        self.assertEqual(converted, ["대한민국!", "역사!"])
        self.assertEqual(converter.calls, ["대한민국", "역사"])


if __name__ == "__main__":
    unittest.main()
