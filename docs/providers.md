# Existing provider adapters (PR-C)

`providers/` exposes exactly text and speech capabilities, with structural interfaces
in `capabilities.py`. Anthropic handles completion, exact token counting, paginated
model listing and alias retrieval. ElevenLabs handles voice listing/selection and
streaming synthesis to a temporary MP3. No dependency was added.

The application retains prompt rendering, source sampling, budget enforcement,
completion validation, usage and attempt journals, paid-draft preservation and
validation/atomic commit of versioned audio. Model limits come from discovery;
the application still caps input at 60,000 tokens and prompts at 180,000 characters.
Speech limits are characters per model, with the existing MP3 format and voice settings.

Discovery cache identity includes the normalized endpoint and an in-memory digest
of the resolved credential (its revision). Rotation discards cached IDs, errors
and model limits. No voice cache is introduced. Credentials remain resolved lazily
by Configuration and fixed inside operations. Clients disable redirects; text
clients retain zero automatic retries. Startup and page loads perform no discovery.

Only mocked transport/regression tests are authorized for this extraction. They
cannot establish live entitlements or audio quality. PR-F retains first-archived
history dates; explicit delete-with-history with shared-input protection remains
required before release. Additional providers follow the initial release.
