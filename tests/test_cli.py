from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

from h2h_converter import cli, config, doctor, installer
from h2h_converter.epub import ConversionStats
from h2h_converter.utagger import ResolvedInstall, resolve_utagger3_path


def _run_cli(argv: list[str]) -> tuple[int, str, str]:
    """Run cli.main with captured stdout/stderr."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
        exit_code = cli.main(argv)
    return exit_code, stdout.getvalue(), stderr.getvalue()


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
  <body><p>대한민국의 역사는 오래되었다.</p></body>
</html>"""
    with zipfile.ZipFile(path, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr("META-INF/container.xml", container_xml)
        epub.writestr("OEBPS/content.opf", opf)
        epub.writestr("OEBPS/chapter.xhtml", chapter)


class FakeLoadedConverter:
    """Stand-in for UTaggerHanjaConverter with no DLL behind it."""

    def __init__(self) -> None:
        self.load_calls = 0

    def load(self) -> None:
        self.load_calls += 1

    def release(self) -> None:
        pass

    def __enter__(self) -> "FakeLoadedConverter":
        return self

    def __exit__(self, *exc_info) -> None:  # noqa: ANN001
        return None

    def convert(self, text: str) -> str:
        return text.replace(
            "대한민국의 역사는 오래되었다.",
            "대한민국(大韓民國)의 역사(歷史)는 오래되었다.",
        )


def _fake_convert_epub(input_epub: Path, output_epub: Path, converter, **kwargs) -> ConversionStats:  # noqa: ANN001
    output_epub.parent.mkdir(parents=True, exist_ok=True)
    output_epub.write_bytes(b"epub")
    return ConversionStats(documents=3, text_nodes=10, ruby_nodes=42)


class ConfigTests(unittest.TestCase):
    def test_utagger3_path_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "config.json"
            with mock.patch.object(config, "config_path", return_value=config_file):
                written = config.save_utagger3_path(Path(r"C:\utagger\v3_2109b"))

                self.assertEqual(written, config_file)
                self.assertEqual(config.get_utagger3_path(), Path(r"C:\utagger\v3_2109b"))

                data = json.loads(config_file.read_text(encoding="utf-8"))
                self.assertEqual(data["utagger3_path"], r"C:\utagger\v3_2109b")

    def test_missing_config_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(config, "config_path", return_value=Path(tmp) / "config.json"):
                self.assertIsNone(config.get_utagger3_path())


class ResolveUtagger3PathTests(unittest.TestCase):
    def test_explicit_path_wins(self) -> None:
        resolved = resolve_utagger3_path(Path("some/dir"))
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.source, "--utagger3-path")

    def test_env_var_beats_config_file(self) -> None:
        with (
            mock.patch.dict("os.environ", {"UTAGGER3_PATH": r"C:\from-env"}),
            mock.patch.object(config, "get_utagger3_path", return_value=Path(r"C:\from-config")),
        ):
            resolved = resolve_utagger3_path(None)
        self.assertEqual(resolved.path, Path(r"C:\from-env"))
        self.assertIn("UTAGGER3_PATH", resolved.source)

    def test_config_file_beats_pyutagger_saved_path(self) -> None:
        with mock.patch.object(config, "get_utagger3_path", return_value=Path(r"C:\from-config")):
            resolved = resolve_utagger3_path(None)
        self.assertEqual(resolved.path, Path(r"C:\from-config"))
        self.assertTrue(resolved.source.startswith("config file"))

    def test_returns_none_when_nothing_is_configured(self) -> None:
        with (
            mock.patch.dict("os.environ", {}, clear=True),
            mock.patch.object(config, "get_utagger3_path", return_value=None),
            mock.patch("h2h_converter.utagger._read_saved_pyutagger_path", return_value=None),
            mock.patch("h2h_converter.utagger._find_local_workspace_install", return_value=None),
        ):
            self.assertIsNone(resolve_utagger3_path(None))


class CliTests(unittest.TestCase):
    def test_legacy_invocation_maps_to_run(self) -> None:
        with mock.patch.object(cli, "_run_convert", return_value=0) as run_convert:
            exit_code = cli.main(["in.epub", "out.epub", "--overwrite"])

        self.assertEqual(exit_code, 0)
        args, legacy = run_convert.call_args.args[0], run_convert.call_args.kwargs["legacy"]
        self.assertEqual(args.command, "run")
        self.assertEqual(args.inputs, [Path("in.epub"), Path("out.epub")])
        self.assertTrue(args.overwrite)
        self.assertTrue(legacy)

    def test_explicit_run_subcommand(self) -> None:
        with mock.patch.object(cli, "_run_convert", return_value=0) as run_convert:
            exit_code = cli.main(["run", "in.epub", "out.epub"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(run_convert.call_args.kwargs["legacy"])

    def test_no_command_prints_help_and_returns_2(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 2)

    def test_version_flag(self) -> None:
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)


class RunDisambiguationTests(unittest.TestCase):
    def test_missing_input_returns_3(self) -> None:
        exit_code, _, stderr = _run_cli(["run", "missing.epub"])
        self.assertEqual(exit_code, 3)
        self.assertIn("input EPUB not found", stderr)

    def test_three_positionals_without_output_dir_is_usage_error(self) -> None:
        exit_code, _, stderr = _run_cli(["run", "a.epub", "b.epub", "c.epub"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--output-dir", stderr)

    def test_preview_rejects_second_positional(self) -> None:
        exit_code, _, stderr = _run_cli(["run", "a.epub", "out.epub", "--preview"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--preview", stderr)

    def test_preview_rejects_output_dir(self) -> None:
        exit_code, _, stderr = _run_cli(["run", "a.epub", "--preview", "-d", "out"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--preview", stderr)


class ExpandInputsTests(unittest.TestCase):
    def test_directory_expands_to_epubs_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "b.epub").write_bytes(b"")
            (root / "a.epub").write_bytes(b"")
            (root / "notes.txt").write_text("x")

            expanded = cli._expand_inputs([root])

        self.assertEqual([p.name for p in expanded], ["a.epub", "b.epub"])

    def test_directory_expansion_skips_default_suffixed_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.epub").write_bytes(b"")
            (root / "a.hanja-ruby.epub").write_bytes(b"")

            expanded = cli._expand_inputs([root])

        self.assertEqual([p.name for p in expanded], ["a.epub"])

    def test_glob_expands_and_filters_to_epubs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "one.epub").write_bytes(b"")
            (root / "two.epub").write_bytes(b"")
            (root / "skip.txt").write_text("x")

            expanded = cli._expand_inputs([Path(str(root / "*.epub"))])

        self.assertEqual([p.name for p in expanded], ["one.epub", "two.epub"])

    def test_glob_without_matches_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                cli._expand_inputs([Path(str(Path(tmp) / "*.epub"))])

    def test_empty_folder_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                cli._expand_inputs([Path(tmp)])

    def test_duplicates_are_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub = Path(tmp) / "book.epub"
            epub.write_bytes(b"")
            expanded = cli._expand_inputs([epub, epub])
        self.assertEqual(len(expanded), 1)


class RunModeTests(unittest.TestCase):
    def test_single_run_uses_default_output_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book.epub"
            book.write_bytes(b"")

            with (
                mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()),
                mock.patch.object(cli, "convert_epub", side_effect=_fake_convert_epub) as convert,
            ):
                exit_code, stdout, _ = _run_cli(["run", str(book)])

            self.assertEqual(exit_code, 0)
            output = convert.call_args.args[1]
            self.assertEqual(output, Path(tmp) / "book.hanja-ruby.epub")
            self.assertIn("42 ruby annotation(s)", stdout)

    def test_single_run_exit_5_when_documents_preserved(self) -> None:
        def preserved_stats(input_epub, output_epub, converter, **kwargs):  # noqa: ANN001
            output_epub.write_bytes(b"epub")
            return ConversionStats(documents=2, text_nodes=5, ruby_nodes=3, skipped_documents=1)

        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book.epub"
            book.write_bytes(b"")
            with (
                mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()),
                mock.patch.object(cli, "convert_epub", side_effect=preserved_stats),
            ):
                exit_code, _, _ = _run_cli(["run", str(book)])

        self.assertEqual(exit_code, 5)

    def test_batch_converts_each_input_with_shared_converter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.epub", "b.epub"):
                (root / name).write_bytes(b"")
            out_dir = root / "out"
            converter = FakeLoadedConverter()

            with (
                mock.patch.object(cli, "_load_converter", return_value=converter),
                mock.patch.object(cli, "convert_epub", side_effect=_fake_convert_epub) as convert,
            ):
                exit_code, stdout, _ = _run_cli(
                    ["run", str(root / "*.epub"), "--output-dir", str(out_dir)]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(converter.load_calls, 1)
            outputs = [call.args[1] for call in convert.call_args_list]
            self.assertEqual(
                [path.name for path in outputs],
                ["a.hanja-ruby.epub", "b.hanja-ruby.epub"],
            )
            self.assertIn("2 converted", stdout)

    def test_batch_skips_existing_outputs(self) -> None:
        def exists_for_b(input_epub, output_epub, converter, **kwargs):  # noqa: ANN001
            if input_epub.name == "b.epub":
                raise FileExistsError(f"Output already exists: {output_epub}")
            return _fake_convert_epub(input_epub, output_epub, converter, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("a.epub", "b.epub"):
                (root / name).write_bytes(b"")

            with (
                mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()),
                mock.patch.object(cli, "convert_epub", side_effect=exists_for_b),
            ):
                exit_code, stdout, _ = _run_cli(
                    ["run", str(root), "--output-dir", str(root / "out")]
                )

            self.assertEqual(exit_code, 5)
            self.assertIn("1 converted", stdout)
            self.assertIn("1 skipped", stdout)

    def test_batch_returns_3_when_nothing_converts(self) -> None:
        def always_fails(input_epub, output_epub, converter, **kwargs):  # noqa: ANN001
            raise ValueError("not an EPUB")

        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "a.epub"
            book.write_bytes(b"")
            with (
                mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()),
                mock.patch.object(cli, "convert_epub", side_effect=always_fails),
            ):
                exit_code, stdout, _ = _run_cli(
                    ["run", str(book), "--output-dir", str(Path(tmp) / "out")]
                )

            self.assertEqual(exit_code, 3)
            self.assertIn("1 failed", stdout)

    def test_batch_returns_5_when_everything_was_already_done(self) -> None:
        def already_done(input_epub, output_epub, converter, **kwargs):  # noqa: ANN001
            raise FileExistsError(f"Output already exists: {output_epub}")

        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "a.epub"
            book.write_bytes(b"")
            with (
                mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()),
                mock.patch.object(cli, "convert_epub", side_effect=already_done),
            ):
                exit_code, stdout, _ = _run_cli(
                    ["run", str(book), "--output-dir", str(Path(tmp) / "out")]
                )

            self.assertEqual(exit_code, 5)
            self.assertIn("1 skipped", stdout)

    def test_utagger_load_failure_returns_4(self) -> None:
        class BrokenConverter(FakeLoadedConverter):
            def load(self) -> None:
                raise RuntimeError("UTagger 3 is not configured.")

        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book.epub"
            book.write_bytes(b"")
            with mock.patch.object(cli, "_load_converter", return_value=BrokenConverter()):
                exit_code, _, stderr = _run_cli(["run", str(book)])

        self.assertEqual(exit_code, 4)
        self.assertIn("not configured", stderr)

    def test_duplicate_output_stems_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in ("one", "two"):
                (root / folder).mkdir()
                (root / folder / "book.epub").write_bytes(b"")

            exit_code, _, stderr = _run_cli(
                [
                    "run",
                    str(root / "one" / "book.epub"),
                    str(root / "two" / "book.epub"),
                    "--output-dir",
                    str(root / "out"),
                ]
            )

        self.assertEqual(exit_code, 2)
        self.assertIn("same output name", stderr)


class PreviewTests(unittest.TestCase):
    def test_preview_prints_pairs_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book.epub"
            _write_minimal_epub(book)

            with mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()):
                exit_code, stdout, _ = _run_cli(["run", str(book), "--preview", "3"])

            self.assertEqual(exit_code, 0)
            self.assertIn("before: 대한민국의 역사는 오래되었다.", stdout)
            self.assertIn("after:  대한민국(大韓民國)의 역사(歷史)는 오래되었다.", stdout)
            self.assertIn("no output file was written", stdout)
            self.assertEqual([p.name for p in Path(tmp).iterdir()], ["book.epub"])


class ReportTests(unittest.TestCase):
    def test_report_file_contains_all_warnings(self) -> None:
        warnings = [f"doc{i}: could not parse" for i in range(8)]

        def warning_stats(input_epub, output_epub, converter, **kwargs):  # noqa: ANN001
            output_epub.write_bytes(b"epub")
            stats = ConversionStats(documents=8, skipped_documents=8)
            stats.warnings.extend(warnings)
            return stats

        with tempfile.TemporaryDirectory() as tmp:
            book = Path(tmp) / "book.epub"
            book.write_bytes(b"")
            report = Path(tmp) / "report.txt"

            with (
                mock.patch.object(cli, "_load_converter", return_value=FakeLoadedConverter()),
                mock.patch.object(cli, "convert_epub", side_effect=warning_stats),
            ):
                exit_code, stdout, stderr = _run_cli(["run", str(book), "--report", str(report)])

            self.assertEqual(exit_code, 5)
            content = report.read_text(encoding="utf-8")
            for warning in warnings:
                self.assertIn(f"book.epub: {warning}", content)
            self.assertIn("8 warning(s) total", content)
            # On screen the list is still truncated by default.
            self.assertIn("more warning(s) omitted", stderr)


class DoctorTests(unittest.TestCase):
    def _healthy_install(self, root: Path) -> Path:
        install = root / "v3_test"
        (install / "bin").mkdir(parents=True)
        (install / "bin" / "UTaggerR64.dll").write_bytes(b"")
        (install / "Hlxcfg.txt").write_text("hangul_to_hanja 2\n", encoding="utf-8")
        return install

    def test_missing_utagger_returns_4_and_points_to_setup(self) -> None:
        stdout = io.StringIO()
        with (
            mock.patch.object(doctor, "resolve_utagger3_path", return_value=None),
            redirect_stdout(stdout),
        ):
            exit_code = doctor.run_doctor(None)

        self.assertEqual(exit_code, 4)
        self.assertIn("h2h-convert setup", stdout.getvalue())

    def test_missing_dll_returns_4(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            install = self._healthy_install(Path(tmp))
            (install / "bin" / "UTaggerR64.dll").unlink()
            resolved = ResolvedInstall(install, "test")

            stdout = io.StringIO()
            with (
                mock.patch.object(doctor, "resolve_utagger3_path", return_value=resolved),
                redirect_stdout(stdout),
            ):
                exit_code = doctor.run_doctor(None)

        self.assertEqual(exit_code, 4)
        self.assertIn("Missing file", stdout.getvalue())

    def test_healthy_install_passes(self) -> None:
        class FakeConverter:
            def __init__(self, options) -> None:  # noqa: ANN001
                pass

            def __enter__(self) -> "FakeConverter":
                return self

            def __exit__(self, *exc_info) -> None:  # noqa: ANN001
                return None

            def convert(self, text: str) -> str:
                return "대한민국(大韓民國)의 역사(歷史)는 오래되었다."

        with tempfile.TemporaryDirectory() as tmp:
            resolved = ResolvedInstall(self._healthy_install(Path(tmp)), "test")

            stdout = io.StringIO()
            with (
                mock.patch.object(doctor, "resolve_utagger3_path", return_value=resolved),
                mock.patch.object(doctor, "UTaggerHanjaConverter", FakeConverter),
                redirect_stdout(stdout),
            ):
                exit_code = doctor.run_doctor(None)

        self.assertEqual(exit_code, 0)
        self.assertIn("all checks passed", stdout.getvalue())

    def test_wrong_conversion_output_fails(self) -> None:
        class BrokenConverter:
            def __init__(self, options) -> None:  # noqa: ANN001
                pass

            def __enter__(self) -> "BrokenConverter":
                return self

            def __exit__(self, *exc_info) -> None:  # noqa: ANN001
                return None

            def convert(self, text: str) -> str:
                return "대한민국의 역사는 오래되었다."

        with tempfile.TemporaryDirectory() as tmp:
            resolved = ResolvedInstall(self._healthy_install(Path(tmp)), "test")

            stdout = io.StringIO()
            with (
                mock.patch.object(doctor, "resolve_utagger3_path", return_value=resolved),
                mock.patch.object(doctor, "UTaggerHanjaConverter", BrokenConverter),
                redirect_stdout(stdout),
            ):
                exit_code = doctor.run_doctor(None)

        self.assertEqual(exit_code, 4)
        self.assertIn("looks wrong", stdout.getvalue())


class InstallerTests(unittest.TestCase):
    def test_reuses_existing_install_without_downloading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "utagger"
            install = base / "v3_existing"
            (install / "bin").mkdir(parents=True)
            (install / "bin" / "UTaggerR64.dll").write_bytes(b"")

            stdout = io.StringIO()
            with (
                mock.patch.object(config, "default_utagger_install_dir", return_value=base),
                mock.patch.object(config, "config_path", return_value=Path(tmp) / "config.json"),
                mock.patch.object(
                    installer, "_load_downloader", side_effect=AssertionError("should not download")
                ),
                redirect_stdout(stdout),
            ):
                exit_code = installer.run_setup(None)

            self.assertEqual(exit_code, 0)
            self.assertIn("reusing", stdout.getvalue())
            with mock.patch.object(config, "config_path", return_value=Path(tmp) / "config.json"):
                self.assertEqual(config.get_utagger3_path(), install)

    def test_missing_pyutagger_returns_2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout = io.StringIO()
            with (
                mock.patch.object(config, "default_utagger_install_dir", return_value=Path(tmp) / "u"),
                mock.patch.object(installer, "_load_downloader", side_effect=ImportError),
                redirect_stdout(stdout),
            ):
                exit_code = installer.run_setup(None)

        self.assertEqual(exit_code, 2)
        self.assertIn('pip install -e ".[setup]"', stdout.getvalue())

    def test_successful_download_saves_config(self) -> None:
        class FakeDownloader:
            @staticmethod
            def install_utagger(ver: str, base: str) -> bool:
                install = Path(base) / "v3_downloaded"
                (install / "bin").mkdir(parents=True)
                (install / "bin" / "UTaggerR64.dll").write_bytes(b"")
                return True

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "utagger"
            stdout = io.StringIO()
            with (
                mock.patch.object(config, "default_utagger_install_dir", return_value=base),
                mock.patch.object(config, "config_path", return_value=Path(tmp) / "config.json"),
                mock.patch.object(installer, "_load_downloader", return_value=FakeDownloader),
                redirect_stdout(stdout),
            ):
                exit_code = installer.run_setup(None)

            self.assertEqual(exit_code, 0)
            self.assertIn("h2h-convert doctor", stdout.getvalue())
            with mock.patch.object(config, "config_path", return_value=Path(tmp) / "config.json"):
                self.assertEqual(config.get_utagger3_path(), base / "v3_downloaded")


if __name__ == "__main__":
    unittest.main()
