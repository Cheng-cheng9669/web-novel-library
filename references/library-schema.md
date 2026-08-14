# Library schema

Use this reference when creating or editing library metadata, manifests, glossary data, or translation state.

## Directory layout

```text
<library-root>/
├── novel/
│   └── <slug>/
│       ├── source/
│       │   ├── 001.txt
│       │   └── manifest.json
│       ├── translation/
│       │   └── 001.md
│       ├── meta.json
│       ├── state.json
│       ├── glossary.json
│       ├── glossary.proposals.json
│       ├── style.md
│       ├── summary.md
│       ├── bookinfo.md
│       └── index.md
└── progress.md
```

The CLI owns generated `manifest.json`, `state.json`, per-book `index.md`, and root `progress.md`. Do not hand-edit generated fields while a batch is running.

## `meta.json`

```json
{
  "schema_version": 1,
  "slug": "example-work",
  "source_title": "Original title",
  "target_title": "Translated title",
  "author": "Author or empty string",
  "platform": "kakuyomu",
  "source_url": "https://example.invalid/work/123",
  "status": "translating",
  "started": "2026-01-01"
}
```

Allowed status values are `planned`, `importing`, `translating`, `paused`, and `complete`. Use an empty author when unknown; do not use placeholder personal data.

## `source/manifest.json`

```json
{
  "schema_version": 1,
  "generated_at": "2026-01-01T00:00:00Z",
  "chapters": [
    {
      "chapter": 1,
      "file": "001.txt",
      "sha256": "...",
      "bytes": 1234
    }
  ]
}
```

The hash covers the exact file bytes. A changed source hash makes a previously recorded translation stale; it does not delete that translation.

## `state.json`

```json
{
  "schema_version": 1,
  "translations": {
    "1": {
      "file": "001.md",
      "source_sha256": "...",
      "translation_sha256": "...",
      "recorded_at": "2026-01-01T00:00:00Z"
    }
  }
}
```

Only `record` should update translation state. A target file without a state record is `untracked`; a state record whose source hash differs from the current manifest is `stale`.

## `glossary.json`

```json
{
  "schema_version": 1,
  "terms": [
    {
      "id": "stable-id",
      "source": "source form",
      "target": "canonical translation",
      "category": "person",
      "aliases": [],
      "attributes": {"gender": "unknown"},
      "confidence": "medium",
      "evidence_chapters": [1],
      "notes": ""
    }
  ]
}
```

Categories are free-form but prefer `person`, `place`, `organization`, `title`, `ability`, `item`, and `other`. Confidence should be `low`, `medium`, or `high`. Evidence chapters must point to observed source context. Prevent the same source form or alias from belonging to multiple canonical terms unless explicitly disambiguated by context.

## `glossary.proposals.json`

Use the same term shape plus `reason` and `proposed_in_chapter`. This file is a review queue, not a second canonical glossary. Merge only reviewed decisions into `glossary.json`.

## Compatibility

For an existing repository with title-named source and translation directories, do not rename thousands of files automatically. Either create a new canonical library and ingest the numbered source chapters, or build a narrowly scoped adapter after inspecting the repository and preserving a reversible mapping.

Never infer which title-named directory is source solely from language detection when explicit metadata is available.
