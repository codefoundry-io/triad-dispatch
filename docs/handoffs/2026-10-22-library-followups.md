# Claude host: preserve roster diagnostic cases before the next library adoption

Proposal date: 2026-10-22. Target: `codefoundry-io/triad-dispatch`.
Review basis: [distribution commit c02cd976](https://github.com/codefoundry-io/triad-dispatch/tree/c02cd9769880dc14b98f54f4bbe70a669b9b8611), plugin `0.2.1976`.

## Confirmed state

The leg recommendation wording is already corrected: every enabled roster entry is an ordinary leg, and agreement requires every selected enabled leg. Repeating that wording repair is not the next task.

The [adoption record](https://github.com/codefoundry-io/triad-dispatch/blob/c02cd9769880dc14b98f54f4bbe70a669b9b8611/skills/triad-cross-family-review/lib/lib-adoption.json) pins library `0.1.0.dev4`, source `087af94a7078de0ae9701fb057840b5492f51f66`, wheel SHA-256 `c5bfdf10c4ce81f431ec7f77106e4d77b1556ac9c7b6b01bdb6616f988e8b2cc`. Adoption slices 1a, 1b and 2 are existing work, not a new implementation request.

The [host adapter](https://github.com/codefoundry-io/triad-dispatch/blob/c02cd9769880dc14b98f54f4bbe70a669b9b8611/skills/triad-cross-family-review/lib/roster_v2.py#L280) translates library refusals into one stderr line. The [pinned library](https://github.com/codefoundry-io/triad-dispatch/blob/c02cd9769880dc14b98f54f4bbe70a669b9b8611/skills/triad-cross-family-review/lib/triad_dispatch_lib/roster.py#L14) supplies `.path` as the schema path, plus `.missing` and `.document`; it does not expose an instance path. The [requester evidence for library #9](https://github.com/codefoundry-io/triad-dispatch-lib/issues/9#issuecomment-6235946998) identifies the practical loss: operators cannot locate the offending entry in a multi-entry roster from a schema path alone.

## One proposed next task

Ask the Claude host maintainer to retain or add focused regression fixtures in the owning source repository, `codefoundry-io/triad`, for the two recorded cases: a string `timeout_s` in a later override entry, and a resolved Google entry pinned to `agy` that carries only a `gemini` block. First locate the existing adoption coverage and reuse its fixtures where present. Record the actual refusal, document attribution, schema path, missing member when available, and lack of an entry index. These are characterization checks of the current limit, not assertions that the requested API exists.

Keep this proposal in the exported distribution as a maintainer handoff. Its adoption record names the owning source and its verification record; the exported tree contains only three wrapper/setup test files, with no roster test suite. Confirm the source's current instructions, test ownership and exporter before implementation. Do not patch generated adapter copies or vendored package bytes in this distribution.

Only after #9 has an approved API and an exact released package should a separate, bounded adoption change render the newly supplied structural location beside the existing schema path. Use the actual released field and documented behavior; this proposal does not prescribe or claim an implemented `instance_path`. Avoid a second validator, local schema walk, or host-side reconstruction of information the library discarded. Preserve the existing one-line diagnostic contract and exclude offending values from new diagnostics.

## Focused acceptance checks for that later work

- Exercise the adapter's `_library_refusal`, `merge_roster` override path and final `validate_resolved` path with the retained multi-entry fixtures.
- Verify defaults, override and resolved-document attribution separately; cover required-member and type failures without depending on unstable full validator wording.
- Keep roster refusals at exit `2`; dependency, integrity and unusable-contract host faults remain exit `64`. No dispatch starts on either failure.
- Preserve duplicate-member scanning, case-fold duplicate refusal, native Claude preset selection, Google routing, packet custody and the recorded host deviations. Keep one vendored library copy and verify the complete manifest, bundle pairs and hashes through the normal source/export process.

## Deferred decisions and limits

[Library PR #20](https://github.com/codefoundry-io/triad-dispatch-lib/pull/20) is open at `13bee1422032984be42c7bb24ef74ac5001b5a7c`; its wording-only changes leave package assets unchanged. They require no package update by themselves. After merge, any relevant spec refresh must use an explicit merged pin and the normal owner/export path.

[Issue #21](https://github.com/codefoundry-io/triad-dispatch-lib/issues/21) leaves `acceptance` required metadata without an agreement exemption; optionality or removal awaits an owner decision and would affect Claude display, records and currency checks. Keep legacy schema identifiers pinned pending [#17](https://github.com/codefoundry-io/triad-dispatch-lib/issues/17). Boundary extractions in [#5](https://github.com/codefoundry-io/triad-dispatch-lib/issues/5) remain deferred.

This document proposes follow-up work only. Inspection used pinned remote source and current issue/PR metadata; no runtime tests, library implementation, release, installation or provider validation is claimed.
