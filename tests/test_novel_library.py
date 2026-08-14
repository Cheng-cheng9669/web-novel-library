from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "novel_library.py"
SPEC = importlib.util.spec_from_file_location("novel_library", SCRIPT)
assert SPEC and SPEC.loader
novel_library = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = novel_library
SPEC.loader.exec_module(novel_library)


class NovelLibraryTests(unittest.TestCase):
    def run_cli(self, *args: str) -> int:
        return novel_library.main(list(args))

    def make_book(self, root: Path) -> Path:
        self.assertEqual(self.run_cli("init", str(root)), 0)
        self.assertEqual(
            self.run_cli(
                "add",
                str(root),
                "--slug",
                "sample",
                "--source-title",
                "Original",
                "--target-title",
                "Translation",
                "--platform",
                "local",
                "--source-url",
                "https://example.invalid/work/1",
            ),
            0,
        )
        return root / "novel" / "sample"

    def test_end_to_end_record_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            book = self.make_book(root)
            incoming = Path(temp) / "incoming"
            incoming.mkdir()
            (incoming / "1.txt").write_text("Chapter one\n\nSource", encoding="utf-8")
            (incoming / "2.txt").write_text("Chapter two\n\nSource", encoding="utf-8")
            self.assertEqual(
                self.run_cli("ingest", str(root), "sample", "--input-dir", str(incoming)),
                0,
            )

            manifest = json.loads((book / "source" / "manifest.json").read_text(encoding="utf-8"))
            first_hash = manifest["chapters"][0]["sha256"]
            translation = Path(temp) / "translation.md"
            translation.write_text("Chapter one\n\nTranslated", encoding="utf-8")
            self.assertEqual(
                self.run_cli(
                    "record",
                    str(root),
                    "sample",
                    "--chapter",
                    "1",
                    "--translation",
                    str(translation),
                    "--source-hash",
                    first_hash,
                ),
                0,
            )
            status = novel_library.book_status(book)
            self.assertEqual(status["current_translations"], [1])
            self.assertEqual(status["missing_or_stale"], [2])

    def test_record_rejects_stale_source_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            book = self.make_book(root)
            incoming = Path(temp) / "incoming"
            incoming.mkdir()
            (incoming / "001.txt").write_text("Source", encoding="utf-8")
            self.assertEqual(
                self.run_cli("ingest", str(root), "sample", "--input-dir", str(incoming)),
                0,
            )
            translation = Path(temp) / "translation.md"
            translation.write_text("Translated", encoding="utf-8")
            self.assertEqual(
                self.run_cli(
                    "record",
                    str(root),
                    "sample",
                    "--chapter",
                    "1",
                    "--translation",
                    str(translation),
                    "--source-hash",
                    "0" * 64,
                ),
                2,
            )
            self.assertFalse((book / "translation" / "001.md").exists())

    def test_validate_detects_stale_translation_after_source_edit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            book = self.make_book(root)
            incoming = Path(temp) / "incoming"
            incoming.mkdir()
            (incoming / "001.txt").write_text("Source", encoding="utf-8")
            self.assertEqual(
                self.run_cli("ingest", str(root), "sample", "--input-dir", str(incoming)),
                0,
            )
            manifest = novel_library.manifest_map(book)
            translation = Path(temp) / "translation.md"
            translation.write_text("Translated", encoding="utf-8")
            self.assertEqual(
                self.run_cli(
                    "record",
                    str(root),
                    "sample",
                    "--chapter",
                    "1",
                    "--translation",
                    str(translation),
                    "--source-hash",
                    manifest[1]["sha256"],
                ),
                0,
            )
            (book / "source" / "001.txt").write_text("Changed source", encoding="utf-8")
            novel_library.build_manifest(book)
            issues = novel_library.scan_book(book)
            self.assertIn("stale-translation", {issue.code for issue in issues})

    def test_validate_detects_secret_like_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            book = self.make_book(root)
            (book / "session-cookie.txt").write_text("redacted", encoding="utf-8")
            issues = novel_library.scan_book(book)
            self.assertIn("possible-secret-file", {issue.code for issue in issues})

    def test_unchanged_manifest_preserves_generation_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "library"
            book = self.make_book(root)
            incoming = Path(temp) / "incoming"
            incoming.mkdir()
            (incoming / "001.txt").write_text("Source", encoding="utf-8")
            self.assertEqual(
                self.run_cli("ingest", str(root), "sample", "--input-dir", str(incoming)),
                0,
            )
            manifest_path = book / "source" / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["generated_at"] = "sentinel"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            refreshed = novel_library.build_manifest(book)

            self.assertEqual(refreshed["generated_at"], "sentinel")
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8"))["generated_at"],
                "sentinel",
            )

    def test_slug_cannot_escape_library(self) -> None:
        with self.assertRaises(novel_library.LibraryError):
            novel_library.validate_slug("../escape")

    def test_compact_numbers(self) -> None:
        self.assertEqual(novel_library.compact_numbers([1, 2, 3, 5, 8, 9]), "1-3,5,8-9")


if __name__ == "__main__":
    unittest.main()
