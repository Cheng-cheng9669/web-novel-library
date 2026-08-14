#!/usr/bin/env python3
"""Deterministic filesystem tools for the web-novel-library agent skill."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
CHAPTER_RE = re.compile(r"^(\d{1,9})\.(txt|md)$", re.IGNORECASE)
SAFE_SLUG_RE = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+$")
REQUIRED_BOOK_FILES = (
    "meta.json",
    "state.json",
    "glossary.json",
    "glossary.proposals.json",
    "style.md",
    "summary.md",
    "bookinfo.md",
    "index.md",
)
SECRET_NAME_RE = re.compile(r"(cookie|token|secret|credential|session)", re.IGNORECASE)


class LibraryError(RuntimeError):
    """A user-actionable library error."""


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    path: str
    message: str


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        if default is not None:
            return default
        raise LibraryError(f"missing JSON file: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LibraryError(f"invalid JSON file {path}: {exc}") from exc


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_library(root: Path) -> Path:
    root = root.resolve()
    if not (root / "novel").is_dir():
        raise LibraryError(f"not a web novel library: {root} (missing novel directory)")
    return root


def validate_slug(slug: str) -> str:
    slug = slug.strip()
    if not slug or slug in {".", ".."} or not SAFE_SLUG_RE.fullmatch(slug):
        raise LibraryError("slug must be a non-empty filename-safe name without path separators")
    if slug.endswith((".", " ")):
        raise LibraryError("slug must not end with a dot or space")
    return slug


def book_dir(root: Path, slug: str) -> Path:
    slug = validate_slug(slug)
    base = (require_library(root) / "novel").resolve()
    candidate = (base / slug).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise LibraryError("book path escaped the library root") from exc
    if not candidate.is_dir():
        raise LibraryError(f"unknown book: {slug}")
    return candidate


def numbered_files(directory: Path) -> dict[int, Path]:
    result: dict[int, Path] = {}
    if not directory.is_dir():
        return result
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        match = CHAPTER_RE.fullmatch(path.name)
        if not match:
            continue
        chapter = int(match.group(1))
        if chapter <= 0:
            continue
        if chapter in result:
            raise LibraryError(f"duplicate chapter number {chapter} in {directory}")
        result[chapter] = path
    return result


def build_manifest(book: Path) -> dict[str, Any]:
    chapters = []
    for chapter, path in sorted(numbered_files(book / "source").items()):
        chapters.append(
            {
                "chapter": chapter,
                "file": path.name,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
            }
        )
    manifest_path = book / "source" / "manifest.json"
    existing = read_json(manifest_path, {})
    if existing.get("schema_version") == SCHEMA_VERSION and existing.get("chapters") == chapters:
        return existing
    manifest = {"schema_version": SCHEMA_VERSION, "generated_at": utc_now(), "chapters": chapters}
    atomic_write_json(manifest_path, manifest)
    return manifest


def manifest_map(book: Path, refresh: bool = False) -> dict[int, dict[str, Any]]:
    path = book / "source" / "manifest.json"
    manifest = build_manifest(book) if refresh or not path.exists() else read_json(path)
    result: dict[int, dict[str, Any]] = {}
    for entry in manifest.get("chapters", []):
        try:
            result[int(entry["chapter"])] = entry
        except (KeyError, TypeError, ValueError) as exc:
            raise LibraryError(f"invalid source manifest entry in {path}") from exc
    return result


def empty_glossary() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "terms": []}


def empty_state() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "translations": {}}


def cmd_init(args: argparse.Namespace) -> int:
    root = Path(args.library).resolve()
    if root.exists() and any(root.iterdir()) and not args.force:
        raise LibraryError(f"refusing to initialize non-empty directory without --force: {root}")
    (root / "novel").mkdir(parents=True, exist_ok=True)
    build_progress(root)
    print(root)
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    root = require_library(Path(args.library))
    slug = validate_slug(args.slug)
    book = root / "novel" / slug
    if book.exists():
        raise LibraryError(f"book already exists: {slug}")
    (book / "source").mkdir(parents=True)
    (book / "translation").mkdir()
    meta = {
        "schema_version": SCHEMA_VERSION,
        "slug": slug,
        "source_title": args.source_title.strip(),
        "target_title": args.target_title.strip(),
        "author": (args.author or "").strip(),
        "platform": args.platform.strip().lower(),
        "source_url": args.source_url.strip(),
        "status": "planned",
        "started": date.today().isoformat(),
    }
    if not meta["source_title"] or not meta["target_title"]:
        raise LibraryError("source and target titles must not be empty")
    atomic_write_json(book / "meta.json", meta)
    atomic_write_json(book / "state.json", empty_state())
    atomic_write_json(book / "glossary.json", empty_glossary())
    atomic_write_json(book / "glossary.proposals.json", empty_glossary())
    atomic_write_text(
        book / "style.md",
        "# Style\n\n## Stable fingerprint\n\n## Character voice cards\n\n## Evolution log\n",
    )
    atomic_write_text(book / "summary.md", "# Story summary\n\n## Current state\n")
    atomic_write_text(book / "bookinfo.md", f"# {meta['source_title']}\n\nSource: {meta['source_url']}\n")
    build_manifest(book)
    build_book_index(book)
    build_progress(root)
    print(book)
    return 0


def choose_chapter_number(path: Path, fallback: int) -> int:
    match = re.match(r"^(\d{1,9})", path.stem)
    return int(match.group(1)) if match and int(match.group(1)) > 0 else fallback


def atomic_copy(source: Path, target: Path) -> None:
    data = source.read_bytes()
    if not data.strip():
        raise LibraryError(f"source chapter is empty: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)


def cmd_ingest(args: argparse.Namespace) -> int:
    root = Path(args.library)
    book = book_dir(root, args.slug)
    incoming = Path(args.input_dir).resolve()
    if not incoming.is_dir():
        raise LibraryError(f"input directory does not exist: {incoming}")
    candidates = [
        path for path in sorted(incoming.iterdir())
        if path.is_file() and path.suffix.lower() in {".txt", ".md"}
    ]
    if not candidates:
        raise LibraryError("no .txt or .md source chapters found")
    used: set[int] = set()
    planned: list[tuple[Path, Path]] = []
    next_fallback = 1
    for source in candidates:
        chapter = choose_chapter_number(source, next_fallback)
        while chapter in used:
            chapter += 1
        used.add(chapter)
        next_fallback = max(next_fallback, chapter + 1)
        target = book / "source" / f"{chapter:03d}{source.suffix.lower()}"
        if target.exists() and not args.force:
            if sha256_file(target) == sha256_file(source):
                continue
            raise LibraryError(f"refusing to overwrite changed chapter without --force: {target.name}")
        planned.append((source, target))
    for source, target in planned:
        atomic_copy(source, target)
    build_manifest(book)
    meta = read_json(book / "meta.json")
    if meta.get("status") == "planned":
        meta["status"] = "importing"
        atomic_write_json(book / "meta.json", meta)
    build_book_index(book)
    build_progress(require_library(root))
    print(json.dumps({"imported": len(planned), "book": args.slug}, ensure_ascii=False))
    return 0


def excerpt(path: Path, *, head: bool, limit: int = 400) -> str:
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text[:limit] if head else text[-limit:]


def book_status(book: Path) -> dict[str, Any]:
    meta = read_json(book / "meta.json", {})
    source = numbered_files(book / "source")
    target = numbered_files(book / "translation")
    manifest = manifest_map(book)
    state = read_json(book / "state.json", empty_state()).get("translations", {})
    stale: list[int] = []
    untracked: list[int] = []
    current: list[int] = []
    for chapter, path in target.items():
        record = state.get(str(chapter))
        source_entry = manifest.get(chapter)
        if not record:
            untracked.append(chapter)
        elif not source_entry or record.get("source_sha256") != source_entry.get("sha256"):
            stale.append(chapter)
        elif record.get("translation_sha256") != sha256_file(path):
            untracked.append(chapter)
        else:
            current.append(chapter)
    missing = sorted(set(source) - set(current))
    return {
        "slug": meta.get("slug", book.name),
        "source_title": meta.get("source_title", ""),
        "target_title": meta.get("target_title", ""),
        "status": meta.get("status", ""),
        "source_chapters": sorted(source),
        "current_translations": current,
        "missing_or_stale": missing,
        "stale_translations": stale,
        "untracked_translations": untracked,
    }


def all_books(root: Path, slug: str | None = None) -> list[Path]:
    root = require_library(root)
    if slug:
        return [book_dir(root, slug)]
    return sorted(path for path in (root / "novel").iterdir() if path.is_dir())


def cmd_status(args: argparse.Namespace) -> int:
    results = [book_status(book) for book in all_books(Path(args.library), args.slug)]
    if args.json:
        print(json.dumps(results[0] if args.slug else results, ensure_ascii=False, indent=2))
    else:
        for result in results:
            print(
                f"{result['slug']}: source={len(result['source_chapters'])} "
                f"current={len(result['current_translations'])} "
                f"pending={len(result['missing_or_stale'])}"
            )
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    book = book_dir(Path(args.library), args.slug)
    source = numbered_files(book / "source")
    manifest = manifest_map(book, refresh=True)
    status = book_status(book)
    pending = status["missing_or_stale"]
    if args.start is not None:
        pending = [number for number in pending if number >= args.start]
    if args.end is not None:
        pending = [number for number in pending if number <= args.end]
    pending = pending[: args.limit]
    chapters = []
    ordered = sorted(source)
    for chapter in pending:
        position = ordered.index(chapter)
        previous_path = source.get(ordered[position - 1]) if position > 0 else None
        next_path = source.get(ordered[position + 1]) if position + 1 < len(ordered) else None
        chapters.append(
            {
                "chapter": chapter,
                "source_path": str(source[chapter].resolve()),
                "source_sha256": manifest[chapter]["sha256"],
                "target_path": str((book / "translation" / f"{chapter:03d}.md").resolve()),
                "previous_excerpt": excerpt(previous_path, head=False) if previous_path else "",
                "next_excerpt": excerpt(next_path, head=True) if next_path else "",
            }
        )
    plan = {
        "book": args.slug,
        "chapters": chapters,
        "context": {
            "glossary": str((book / "glossary.json").resolve()),
            "style": str((book / "style.md").resolve()),
            "summary": str((book / "summary.md").resolve()),
        },
    }
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    else:
        print(" ".join(str(item["chapter"]) for item in chapters))
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    book = book_dir(Path(args.library), args.slug)
    manifest = manifest_map(book, refresh=True)
    entry = manifest.get(args.chapter)
    if not entry:
        raise LibraryError(f"source chapter does not exist: {args.chapter}")
    if entry["sha256"] != args.source_hash:
        raise LibraryError("source changed after planning; prepare the chapter again")
    incoming = Path(args.translation).resolve()
    if not incoming.is_file() or incoming.stat().st_size == 0:
        raise LibraryError(f"translation file is missing or empty: {incoming}")
    try:
        text = incoming.read_text(encoding="utf-8")
    except UnicodeError as exc:
        raise LibraryError("translation must be valid UTF-8") from exc
    if not text.strip():
        raise LibraryError("translation is blank")
    target = book / "translation" / f"{args.chapter:03d}.md"
    if target.exists() and not args.force:
        raise LibraryError(f"translation already exists; use --force only after review: {target}")
    atomic_write_text(target, text.replace("\r\n", "\n"))
    state = read_json(book / "state.json", empty_state())
    state.setdefault("translations", {})[str(args.chapter)] = {
        "file": target.name,
        "source_sha256": entry["sha256"],
        "translation_sha256": sha256_file(target),
        "recorded_at": utc_now(),
    }
    atomic_write_json(book / "state.json", state)
    meta = read_json(book / "meta.json")
    if meta.get("status") in {"planned", "importing"}:
        meta["status"] = "translating"
        atomic_write_json(book / "meta.json", meta)
    build_book_index(book)
    build_progress(require_library(Path(args.library)))
    print(target)
    return 0


def scan_book(book: Path) -> list[Issue]:
    issues: list[Issue] = []
    for name in REQUIRED_BOOK_FILES:
        path = book / name
        if not path.is_file():
            issues.append(Issue("error", "missing-file", str(path), f"required file is missing: {name}"))
    for directory in (book / "source", book / "translation"):
        if not directory.is_dir():
            issues.append(Issue("error", "missing-directory", str(directory), "required directory is missing"))
    if issues:
        return issues
    try:
        meta = read_json(book / "meta.json")
        if meta.get("schema_version") != SCHEMA_VERSION:
            issues.append(Issue("error", "schema-version", str(book / "meta.json"), "unsupported metadata schema"))
        if meta.get("slug") != book.name:
            issues.append(Issue("error", "slug-mismatch", str(book / "meta.json"), "metadata slug does not match directory name"))
    except LibraryError as exc:
        issues.append(Issue("error", "invalid-json", str(book / "meta.json"), str(exc)))
        return issues
    try:
        source = numbered_files(book / "source")
        target = numbered_files(book / "translation")
    except LibraryError as exc:
        issues.append(Issue("error", "duplicate-chapter", str(book), str(exc)))
        return issues
    if not source:
        issues.append(Issue("warning", "no-source", str(book / "source"), "book has no source chapters"))
    for chapter, path in list(source.items()) + list(target.items()):
        if path.stat().st_size == 0 or not path.read_bytes().strip():
            issues.append(Issue("error", "empty-chapter", str(path), f"chapter {chapter} is empty"))
    try:
        manifest = manifest_map(book)
        for chapter, path in source.items():
            entry = manifest.get(chapter)
            if not entry:
                issues.append(Issue("error", "manifest-missing", str(path), "source chapter is absent from manifest"))
            elif entry.get("sha256") != sha256_file(path):
                issues.append(Issue("error", "manifest-stale", str(path), "source hash differs from manifest; run prepare or ingest"))
        for chapter in sorted(set(manifest) - set(source)):
            issues.append(Issue("error", "manifest-orphan", str(book / "source" / "manifest.json"), f"manifest references missing chapter {chapter}"))
    except LibraryError as exc:
        issues.append(Issue("error", "invalid-manifest", str(book / "source" / "manifest.json"), str(exc)))
        manifest = {}
    try:
        state = read_json(book / "state.json", empty_state()).get("translations", {})
    except LibraryError as exc:
        issues.append(Issue("error", "invalid-state", str(book / "state.json"), str(exc)))
        state = {}
    for chapter, path in target.items():
        record = state.get(str(chapter))
        if chapter not in source:
            issues.append(Issue("error", "orphan-translation", str(path), "translation has no source chapter"))
        elif not record:
            issues.append(Issue("warning", "untracked-translation", str(path), "translation was not recorded by the CLI"))
        elif manifest.get(chapter, {}).get("sha256") != record.get("source_sha256"):
            issues.append(Issue("error", "stale-translation", str(path), "translation refers to an older source hash"))
        elif sha256_file(path) != record.get("translation_sha256"):
            issues.append(Issue("warning", "modified-translation", str(path), "translation changed after it was recorded"))
    for chapter in sorted(set(source) - set(target)):
        issues.append(Issue("warning", "missing-translation", str(book / "translation"), f"chapter {chapter} is not translated"))
    for path in book.rglob("*"):
        if path.is_file() and SECRET_NAME_RE.search(path.name):
            issues.append(Issue("error", "possible-secret-file", str(path), "credential-like filename must not be stored in the library"))
    try:
        glossary = read_json(book / "glossary.json")
        seen: dict[str, str] = {}
        for term in glossary.get("terms", []):
            term_id = str(term.get("id", ""))
            aliases = term.get("aliases", [])
            if not isinstance(aliases, list):
                raise TypeError("aliases must be a list")
            for form in [term.get("source", ""), *aliases]:
                key = str(form).strip().casefold()
                if not key:
                    continue
                if key in seen and seen[key] != term_id:
                    issues.append(Issue("error", "glossary-collision", str(book / "glossary.json"), f"surface form belongs to both {seen[key]} and {term_id}"))
                seen[key] = term_id
    except (LibraryError, TypeError) as exc:
        issues.append(Issue("error", "invalid-glossary", str(book / "glossary.json"), str(exc)))
    return issues


def cmd_validate(args: argparse.Namespace) -> int:
    issues: list[Issue] = []
    for book in all_books(Path(args.library), args.slug):
        issues.extend(scan_book(book))
    payload = [asdict(issue) for issue in issues]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for issue in issues:
            print(f"[{issue.severity.upper()}] {issue.code}: {issue.message} ({issue.path})")
        errors = sum(issue.severity == "error" for issue in issues)
        warnings = sum(issue.severity == "warning" for issue in issues)
        print(f"errors={errors} warnings={warnings}")
    return 1 if any(issue.severity == "error" for issue in issues) else 0


def compact_numbers(numbers: Iterable[int]) -> str:
    values = sorted(set(numbers))
    if not values:
        return ""
    ranges: list[str] = []
    start = previous = values[0]
    for value in values[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(ranges)


def build_book_index(book: Path) -> None:
    meta = read_json(book / "meta.json", {})
    source = numbered_files(book / "source")
    target = numbered_files(book / "translation")
    lines = [f"# {meta.get('target_title') or meta.get('source_title') or book.name}", ""]
    for chapter in sorted(source):
        source_link = f"source/{source[chapter].name}"
        target_link = f"translation/{target[chapter].name}" if chapter in target else ""
        suffix = f" · [translation]({target_link})" if target_link else " · pending"
        lines.append(f"- {chapter:03d}: [source]({source_link}){suffix}")
    atomic_write_text(book / "index.md", "\n".join(lines) + "\n")


def build_progress(root: Path) -> None:
    root = root.resolve()
    novel = root / "novel"
    novel.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Web Novel Library",
        "",
        "| Work | Source | Current | Pending | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for book in sorted(path for path in novel.iterdir() if path.is_dir()):
        try:
            status = book_status(book)
        except LibraryError:
            lines.append(f"| {book.name} | ? | ? | ? | invalid |")
            continue
        lines.append(
            f"| [{status['slug']}](novel/{status['slug']}/index.md) | "
            f"{len(status['source_chapters'])} | {len(status['current_translations'])} | "
            f"{len(status['missing_or_stale'])} | {status['status']} |"
        )
    atomic_write_text(root / "progress.md", "\n".join(lines) + "\n")


def cmd_index(args: argparse.Namespace) -> int:
    root = require_library(Path(args.library))
    for book in all_books(root):
        build_book_index(book)
    build_progress(root)
    print(root / "progress.md")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize a library")
    init.add_argument("library")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=cmd_init)

    add = sub.add_parser("add", help="add a book")
    add.add_argument("library")
    add.add_argument("--slug", required=True)
    add.add_argument("--source-title", required=True)
    add.add_argument("--target-title", required=True)
    add.add_argument("--platform", required=True)
    add.add_argument("--source-url", required=True)
    add.add_argument("--author", default="")
    add.set_defaults(func=cmd_add)

    ingest = sub.add_parser("ingest", help="copy numbered source chapters into a book")
    ingest.add_argument("library")
    ingest.add_argument("slug")
    ingest.add_argument("--input-dir", required=True)
    ingest.add_argument("--force", action="store_true")
    ingest.set_defaults(func=cmd_ingest)

    status = sub.add_parser("status", help="show translation status")
    status.add_argument("library")
    status.add_argument("slug", nargs="?")
    status.add_argument("--json", action="store_true")
    status.set_defaults(func=cmd_status)

    prepare = sub.add_parser("prepare", help="prepare a bounded translation batch")
    prepare.add_argument("library")
    prepare.add_argument("slug")
    prepare.add_argument("--start", type=int)
    prepare.add_argument("--end", type=int)
    prepare.add_argument("--limit", type=int, default=5)
    prepare.add_argument("--json", action="store_true")
    prepare.set_defaults(func=cmd_prepare)

    record = sub.add_parser("record", help="atomically record one translation")
    record.add_argument("library")
    record.add_argument("slug")
    record.add_argument("--chapter", type=int, required=True)
    record.add_argument("--translation", required=True)
    record.add_argument("--source-hash", required=True)
    record.add_argument("--force", action="store_true")
    record.set_defaults(func=cmd_record)

    validate = sub.add_parser("validate", help="audit library integrity")
    validate.add_argument("library")
    validate.add_argument("slug", nargs="?")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(func=cmd_validate)

    index = sub.add_parser("index", help="rebuild generated indexes")
    index.add_argument("library")
    index.set_defaults(func=cmd_index)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "limit", 1) <= 0:
        parser.error("--limit must be positive")
    if getattr(args, "chapter", 1) <= 0:
        parser.error("--chapter must be positive")
    if getattr(args, "start", None) is not None and args.start <= 0:
        parser.error("--start must be positive")
    if getattr(args, "end", None) is not None and args.end <= 0:
        parser.error("--end must be positive")
    try:
        return args.func(args)
    except LibraryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
