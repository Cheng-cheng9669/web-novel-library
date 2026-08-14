# Translation protocol

Use this reference for translation, proofreading, terminology updates, style approval, and summary maintenance.

## Context assembly

For each chapter, provide only the context needed for the decision:

1. Current source chapter.
2. Canonical `glossary.json` entries that occur in the chapter, plus high-impact recurring characters.
3. `style.md` stable rules and relevant evolution notes.
4. `summary.md` factual state.
5. Short previous/next excerpts from `prepare` for pronouns, speaker continuity, and entity resolution.
6. The user's current translation instruction.

Neighbor excerpts are read-only context. Never translate or copy text outside the current chapter into its output.

## Translation requirements

- Preserve headings, paragraph boundaries, emphasis markers, and meaningful scene breaks.
- Write natural target-language prose rather than mechanically copying source syntax.
- Preserve narrative viewpoint, formality, character voice, jokes, and deliberate ambiguity.
- Follow canonical terminology exactly.
- Do not invent explanations, relationships, genders, motives, or missing events.
- Preserve placeholders and markup verbatim unless the format contract says otherwise.
- Output only the chapter content to the temporary translation file.

For Japanese-to-Simplified-Chinese light fiction:

- Resolve omitted subjects from context only when confidence is sufficient.
- Split long attributive constructions into natural Chinese sentences.
- Preserve distinctions among first-person pronouns, honorific levels, nicknames, and verbal tics through natural Chinese voice.
- Translate sound symbolism by function and scene rather than fixed dictionary substitution.
- Keep Japanese kanji names, phonetic names, Chinese-style names, titles, and abilities consistent with the reviewed glossary strategy.

## First-chapter gate

For a new work:

1. Read 3-5 representative source chapters or a bounded sample.
2. Draft the stable style fingerprint and initial character voice cards.
3. Build a seed glossary from observed evidence.
4. Translate one representative chapter.
5. Show a concise excerpt and consequential terminology/style choices to the user.
6. Continue automated batches only after approval.

## Parallel work

Parallel workers may read shared context but must write only unique temporary files. They must not edit canonical glossary, state, summary, style, index, or Git state. Each worker should optionally emit a sidecar proposal containing:

```json
{
  "chapter": 12,
  "new_terms": [],
  "alias_hypotheses": [],
  "attribute_hypotheses": [],
  "conflicts": [],
  "uncertainties": []
}
```

Require short evidence excerpts or chapter references. Empty proposals are valid. Merge reviewed decisions between batches, then re-plan chapters affected by terminology changes.

## Proofreading pass

Compare source and target, checking:

- omissions and duplicated passages;
- wrong speaker, subject, pronoun, tense, or polarity;
- terminology and name drift;
- punctuation and quotation pairing;
- source-language residue;
- suspiciously short or long output;
- hallucinated names or facts;
- repeated neighboring context;
- `[TODO]`, `[待校]`, model commentary, and fenced output artifacts.

Automated checks are evidence, not proof of correctness. A clean scan cannot establish literary accuracy.

## Summary and style evolution

Update the summary with facts, unresolved threads, relationship state, and location/time changes. Avoid evaluative prose and predictions. Keep it compact enough to inject repeatedly.

Append new voice or style discoveries with chapter evidence. Promote them into the stable style section only after recurrence or explicit review. Never let a single anomalous chapter silently redefine the whole work's style.
