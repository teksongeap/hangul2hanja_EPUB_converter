from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from h2h_converter import cli, config, doctor, installer
from h2h_converter.utagger import ResolvedInstall, resolve_utagger3_path


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
        with (
            mock.patch.dict("os.environ", {}, clear=False),
            mock.patch.object(config, "get_utagger3_path", return_value=Path(r"C:\from-config")),
        ):
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
        self.assertEqual(args.input_epub, Path("in.epub"))
        self.assertEqual(args.output_epub, Path("out.epub"))
        self.assertTrue(args.overwrite)
        self.assertTrue(legacy)

    def test_explicit_run_subcommand(self) -> None:
        with mock.patch.object(cli, "_run_convert", return_value=0) as run_convert:
            exit_code = cli.main(["run", "in.epub", "out.epub"])

        self.assertEqual(exit_code, 0)
        self.assertFalse(run_convert.call_args.kwargs["legacy"])

    def test_run_reports_missing_input(self) -> None:
        parser_args = cli.build_parser().parse_args(["run", "missing.epub", "out.epub"])
        stderr = io.StringIO()
        with mock.patch("sys.stderr", stderr):
            exit_code = cli._run_convert(parser_args, legacy=False)

        self.assertEqual(exit_code, 3)
        self.assertIn("input EPUB not found", stderr.getvalue())

    def test_no_command_prints_help_and_returns_2(self) -> None:
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main([]), 2)

    def test_version_flag(self) -> None:
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)


class FakeUTaggerConverter:
    """Context manager stand-in for UTaggerHanjaConverter in doctor tests."""

    converted = "대한민국(大韓民國)의 역사(歷史)는 오래되었다."

    def __init__(self, options) -> None:  # noqa: ANN001
        self.options = options

    def __enter__(self) -> "FakeUTaggerConverter":
        return self

    def __exit__(self, *exc_info) -> None:  # noqa: ANN001
        return None

    def convert(self, text: str) -> str:
        return self.converted


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
        with tempfile.TemporaryDirectory() as tmp:
            resolved = ResolvedInstall(self._healthy_install(Path(tmp)), "test")

            stdout = io.StringIO()
            with (
                mock.patch.object(doctor, "resolve_utagger3_path", return_value=resolved),
                mock.patch.object(doctor, "UTaggerHanjaConverter", FakeUTaggerConverter),
                redirect_stdout(stdout),
            ):
                exit_code = doctor.run_doctor(None)

        self.assertEqual(exit_code, 0)
        self.assertIn("all checks passed", stdout.getvalue())

    def test_wrong_conversion_output_fails(self) -> None:
        class BrokenConverter(FakeUTaggerConverter):
            converted = "대한민국의 역사는 오래되었다."

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
