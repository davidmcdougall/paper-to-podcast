# Prompt storage and text-generation history (PR-B)

Five shipped UTF-8 Markdown templates live in `prompt_templates/`: `script`,
`voice_edit`, `summary`, `show_notes` and `metadata`. Their rendered requests match
fixtures captured before extraction. Git attributes pin shipped templates to LF
line endings on every OS, while editable/archive bytes are preserved exactly. System instructions and metadata schema
validation remain in Python. No dependency was added.

The first mutating operation seeds editable copies in `<user data>/prompts/`.
The data location comes from Configuration (`platformdirs` or `P2P_DATA_DIR`),
independent of the selected episode library. Later launches/upgrades never
replace edits. A missing or invalid editable file uses the shipped default and
adds a warning to generated episodes; it is not silently repaired. A corrupt
immutable archive refuses reuse instead of overwriting history.

Templates are plain text, limited to 32,000 UTF-8 bytes. Each has these required
literal placeholders (no expressions, conversions, format specifiers or other
braces):

| Template | Required placeholders |
|---|---|
| script | `{length_rule}`, `{notes}`, `{source}` |
| voice_edit | `{script}` |
| summary | `{title}`, `{source}` |
| show_notes | `{title}`, `{authors}`, `{source}` |
| metadata | `{source}` |

`{source}` must appear exactly once, as the last bytes of each source-bearing
template (no trailing newline). Substitution takes one pass: braces inside paper
text, notes or scripts remain literal. Editorial instructions such as avoiding
invented citations cannot guarantee the model's accuracy. Finished responses,
nonempty text and metadata JSON structure are checked before recording success.
HTML escaping remains the responsibility of the existing views.

## Backend API

`PromptStore(data_dir)` provides `snapshot()`, `save(name, text)`, `reset(name)`,
`history(name)`, `historical(name, sha256)` and `preview(name, text=None)`.
Save rejects invalid input before changing files; reset archives the previous
bytes and installs the current shipped default. Writes are atomic and protected
by a cross-process prompt lock. History archives exact bytes, including line
endings, under `prompts/history/<name>/<sha256>.md`. History lists hashes, not an
ordered edit log. Externally invalid bytes are retained when explicitly replaced.

Preview renders the bundled synthetic sample without contacting a provider. It
labels its character-based token estimate as approximate. Browser settings,
editing, history controls and preview UI belong to PR-F; no endpoint was added
in this PR. A developer can use the backend API now.

## Snapshots and attempt records

Configuration takes a prompt snapshot alongside settings at operation start.
An external edit or backend save during generation affects the next operation.
Secrets are still resolved lazily and never passed into prompt/history records.

Each application text-generation attempt has a unique ID and a JSON record in
`<user data>/generation-history/<id>.json`. Intent is written before provider
access. A later update records the actual rendered-request hash, sampled-source
reference/hash, token budget, system-instruction hash and provider usage when
available. Completion records success or failure, timestamps and output hash.
An interrupted process can leave `started`: it is not proof of provider success
or zero spend. The existing SDK has automatic retries disabled. A manual retry
creates new records and uses new snapshots; earlier records remain intact.

Records include template hash, selected model, output limit, source-word cap,
length rule, provider-default temperature, sampling version and original
extracted-source reference/hash. Source, draft and other input text is stored
once by content hash under `generation-history/inputs/`, with relative references
in records instead of large inline values. These are private local files and can
contain full paper text, notes and scripts. They are not uploaded to R2 or
published in RSS. Keep the user-data directory private. No credentials, provider
exception bodies or settings/secret snapshots are included.

Saved episodes gain additive `generation_attempts` and `source_hash` fields.
`episodes.json` remains a list; existing records are not migrated. Before optional
passes, the paid draft and its attempts are saved. Failed optional passes retain
the draft and attempt status. A final journal-write failure cannot discard a paid
response: in-memory records mark the failure, and the episode retains them.
If storage fails before the call, generation stops before spending. Voice-only
retries preserve the episode's text-generation records; speech accounting is
unchanged.

Archives and input blobs survive library moves because they belong to the
installation's user-data directory. No automatic pruning or deletion was added.
Deleting an episode does not erase this history. Exact regeneration is not
promised: provider defaults, model versions and sampling can change.
