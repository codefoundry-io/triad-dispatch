---
name: triad-cross-family-review
description: Runs the FINAL pre-merge (or review-worthy / security-or-correctness-critical) cross-family review mandated by the lab's cross-family review rule — dispatches INDEPENDENT cross-family reviewers (a claude fresh-eye sub-agent via Agent + codex via triad-codex-dispatch + the Google-family CLI selected at runtime, agy via triad-antigravity-dispatch or gemini via triad-gemini-dispatch), frames the suspect/omitted/simplified decisions as QUESTIONS, consolidates their verdicts (SAFE TO MERGE / MERGE WITH FIXES / DO NOT MERGE), then runs a fix→re-confirm loop until the gating legs are unanimously SAFE (a MERGE WITH FIXES carrying only non-blocking findings satisfies the gate). Trigger when about to merge review-worthy work, ESPECIALLY when the leader chose to OMIT or SIMPLIFY something from a vetted source, or after a subagent-driven implementation before integration.
version: 0.35.4
# changelog:
#  0.35.4 (2026-09-18): S2-9 — the S2 ledger's owner-optional row, ACCEPTED by the owner on resume (2026-09-18): `codex_wrapper.py` passes `--ignore-rules` on EVERY posture, not only read-only — a wrapper dispatch pins `approval_policy=never` and never wants an escalation outside the sandbox on the write posture (`--task code`) either; the operator's execpolicy allow rules (`git add/commit`, `gh …`, `rm -rf _runs` on this host) were the one path around that pin, and inside workspace-write the same commands still run when the sandbox permits them. Skill behaviour is unchanged (the codex leg was already read-only); `references/leg-contracts.md` W16 bullet + call-site note, the plugin `README.md`, root `CLAUDE.md` resynced; `t24` write-posture axis flipped from absence to presence (RED observed, then GREEN). Same day, before this change: the 41 commits `27640ed..929d971` PUSHED and the S3 dist re-export DONE (`~/triad-dispatch` 0.2.821, SKILL 0.31.0→0.35.3 in one export); this change re-exports again.
#  0.35.3 (2026-09-17): S2 gate r3 wave 3 (ledger § Round 3 — focused re-confirm of wave 2, gating legs, CONVERGING: claude SAFE TO MERGE, codex one must-fix = the LAST captured vendor denial tail). R3-1 (codex + claude): `_AGY_PERMISSION_TAILS` — the structural vendor head now accepts every CAPTURED tail (`user denied permission …` and the retired settings deny-rule shape `Permission denied for <verb>(…). Matches user-configured deny rule.`); the leader enumerated every distinct error head in the captured corpus, so the predicate seam closes by construction. R3-2 (codex): the collision scan compares tracked paths as git prints them (raw `-z` names; no whitespace stripping — a leading/trailing blank is a different file). R3-3 (claude): the denial tail is read after the last `": ` (the echoed argument may carry a quote). R3-5/R3-6: the load check's report list is capped at 40 + `(+N more)`; a bool step index prints as None. R3-7: the X-leg dispatch comment states S2-6 (no conversation-id filtering) honestly. R3-8: `casefold()` (one word). OWNER INSTRUCTION mid-round: negative tests for vendor-side / exotic shapes are NOT built to the legs' depth — the vendor is a paid service responsible for its output; an unknown shape fails closed and is disclosed, never waved (the `.agentſ` axis was dropped). Disclosed: S2-12 (integer `step_index` reuse would reopen R2-1 fail-open; unreachable on measured streams), S2-13 (`DENY_TOOLS` denies the research agent's web tools too — no `--web` leg runs at a hooked worktree today). t13 27-28, t9 14-15. Wave size code-only +19/−12 (S2 cumulative +359/−60 vs ~180 — disclosure trigger stays fired; physical +607/−68 vs ~420, ×1.45, backstop clear).
#  0.35.2 (2026-09-17): S2 gate r2 wave 2 (ledger § Round 2 — focused re-confirm of wave 1, gating legs, CONVERGING; claude re-proved the claim on the measured spike stream: the denied `write_to_file` now reaches `Admission.ok` with `blocked == ("write_to_file",)`). R2-1 (codex): an ACTIVE record is suppressed ONLY by a TRUSTWORTHY identity — an INTEGER `step_index` shared with a terminal update of the same name; malformed or missing indices never suppress (two string indices had collapsed to `None`, letting a denied write's terminal key hide a second, ACTIVE-only write). R2-2 (codex + claude): the pre-mutation collision check is CASE-INSENSITIVE over every tracked path at the reviewed commit — a tracked `.AGENTS` / `.Agents/` / `BRIEF.md` on the case-folding macOS filesystem had slipped past the exact-name lookups and wedged the round after the artifacts existed; `.agents` is allowed only spelled exactly and as a tree. R2-3 (claude, must-fix): the vendor's own denial head is matched STRUCTURALLY — `permission check failed for <verb> "<arg>": user denied permission …` (position-0 head, denial tail after the LAST quote; the model's argument sits inside the quotes) — the wave-1 prefix `user denied permission` matched no captured vendor message, so vendor denials had been forbidden (fail-closed) while the docs asserted coverage. R2-4: the first NON-EMPTY line (`_agy_first_line`). R2-5: the shared allowlist sentence is true for both agent bodies (off-list tools, WHEN the caller's worktree carries a hook; the research agent's web tools are never called blocked) — hosts re-run `--setup-agents`. R2-6: the load check's report line caps and ASCII-escapes the vendor-payload tool name. Disclosed: S2-10 any non-ACTIVE state is treated as terminal (a future PENDING re-breaks the claim fail-closed); S2-11 a hook that cannot read stdin logs its denials, so the load check PASSes (correct — it loaded). t38 33 (+31 fixtures with integer indices), t13 26, t9 12-13, t28 pins. Wave size code-only +38/−17 (S2 cumulative +352/−60 vs ~180 — disclosure trigger stays fired; physical +588/−68 vs ~420, backstop clear).
#  0.35.1 (2026-09-17): S2 gate r1 wave 1 (ledger `docs/reviews/2026-09-17-s2-enforcement-residuals.md` § Round 1 — three legs CONVERGING on two seams). S2-1 (codex + claude, REPRODUCED against the spike streams): the census read EVERY `step_update`, and the vendor emits an ACTIVE update before each DONE/ERROR, so a hook-DENIED call was `executed` too and the effect-based split never fired on a real stream — the TERMINAL update now decides each call (`step_index` + name), and an ACTIVE update with no terminal update (a cut stream) still counts as executed (unknown effect, fail-closed). S2-2 (three families, REPRODUCED): `_agy_step_denied` is ANCHORED — state ERROR and the FIRST LINE of the message STARTS with a vendor denial phrase (`tool call denied by pre-tool hook` / `user denied permission`); a diagnostic quoting the phrase mid-message, or a DONE step carrying a denial-shaped error, is an ordinary error and the call stays forbidden. S2-3 (codex + agy, REPRODUCED twice): a reviewed tree that TRACKS `.agents` as a symlink or a file is refused before the worktree exists (`git ls-tree` mode), and cleanup refuses before any unlink when `.agents` is not a real directory — `close` had unlinked `.agents/hooks.json` THROUGH a tracked symlink into a shared directory, or wedged on ENOTDIR with the artifacts gone. S2-4 (codex): the load check counts only hook-shaped rows (`decision` allow|deny + `tool`); any other JSON object → INCONCLUSIVE. S2-5 (agy + claude, REPRODUCED): the handler reads stdin as bytes and decodes UTF-8 with replacement — a legacy stdio encoding crashed it on a non-ASCII path. S2-8 (claude): the READ-GRANT / agent body condition the blocked-call promise — the leg cannot see from inside whether the hook loaded, so it never makes one (hosts re-run `--setup-agents`). Disclosed residuals: S2-6 the load check is per ROUND (one agy leg per round as deployed; fix shape = `conversation_id` in the read audit), S2-7 no codex version floor for `--ignore-rules` (loud fail-closed; pre-deploy check in the S3 note), S2-9 the write posture keeps the operator's rules (pre-existing; owner-optional). t38 31-32, t13 25 (+ axis 7 realigned), t9 9-11, t4 pin; fake-agy `v2_denied_shell_admitted` carries the ACTIVE precursors. Wave size code-only +57/−14 (S2 cumulative +329/−58 vs ~180 — disclosure trigger stays fired; physical +546/−66 vs ~420, backstop clear).
#  0.35.0 (2026-09-17): S2 ENFORCEMENT — the agy leg's containment moves off the prompt and off the agent allowlist onto a MECHANICAL PreToolUse hook in the round worktree (plan `docs/superpowers/plans/2026-09-16-cfr-delivery-and-enforcement-redesign.md` § Enforcement; MEASURED on agy 1.2.5, session spike-s2, two runs: a workspace `.agents/hooks.json` fires in print mode with matcher `*`, a denied call reaches the stream as state ERROR + `tool call denied by pre-tool hook: <reason>`, the run stays SUCCESS / rc 0 and the file is never written; a call the vendor rejects at ARGUMENT VALIDATION never reaches the hook; `--agent <unknown>` fails OPEN silently, measured 2026-09-16). `prepare` writes `<worktree>/.agents/hooks.json` (one named hook, `enabled`, matcher `*`, handler `python3 <skill>/lib/agy_hook.py --log <packet-dir>/agy-hook-r<N>.jsonl`, timeout 10 s) AFTER the four artifacts and BEFORE the untracked walk and capture; the handler (NEW `lib/agy_hook.py`, stdlib, no AI) denies a fixed set of mutating / command / network-browser / subagent / messaging / planner tools — the measured 57-tool registry classified once, pinned by `t9` — and allows everything else: reads are never denied, an unknown tool is allowed (the census still judges it), an unreadable or nameless payload is DENIED (fail-closed), tool ARGS are never logged. ADMISSION IS EFFECT-BASED — Gate A only: an off-list call DENIED before execution (the hook, or the vendor's own permission denial — ONE predicate `_common._agy_step_denied`, shared with the digest's `denied` list) is BLOCKED: logged on stderr (`[wrapper] antigravity blocked-calls n=… tools=[…]`), never voiding; an off-list call that EXECUTED, or errored for a non-denial reason (its effect is unknown), still voids as `admission-refused` — Policy D unchanged. Gate B (a degraded status is admitted only when an errored READ explains it; `t28` v2-7 / v2-9) is UNTOUCHED — a blocked call explains nothing (`t38` axis 29). NEW MECHANICAL CHECK, the hook LOAD CHECK: `python3 <skill>/lib/agy_hook.py check <packet-dir>/agy-read-audit.json <packet-dir>/agy-hook-r<N>.jsonl` prints `HOOK_LOAD_<PASS|VOID|ABSENT|INCONCLUSIVE> tool_steps=<n> invocations=<n> denied=<n>` (exit 0 / 3 / 2 / 4; 64 usage) — ZERO hook invocations while the read audit counts tool steps means the enforcement layer did not load and VOIDs the leg (PASS needs one invocation, never an equality); `prepare` prints the command beside the read-audit gate line, for the standing leg and every agy X leg (one hook log per round, conversation ids tell the legs apart). The hook log is a leg OUTPUT (`agy-hook-r<N>.jsonl`, a BASENAME rule like the X shape); `.agents/hooks.json` is OWNED by cleanup like the four artifacts and censused by the worktree fingerprint — NOT listed in the delivery record (it is enforcement, not delivered material; a reviewed repo that gitignores `.agents/` hides it from the fingerprint's untracked arm — disclosed); a reviewed tree that TRACKS `.agents/hooks.json` is refused before the worktree exists. W16: the codex wrapper passes `--ignore-rules` on every READ-ONLY dispatch (Tier 1: `codex-rs/exec/src/cli.rs` — "Do not load user or project execpolicy `.rules` files"; an execpolicy `decision="allow"` rule runs its command OUTSIDE the sandbox without prompting, and this host's `~/.codex/rules` allow `git add/commit`, `gh …`, `rm -rf _runs`); the write posture keeps the operator's rules. Prompt text (`_agy_read_grant`, mirrored in `references/leg-contracts.md`) and the agent body (`_allowlist_rule` — hosts RE-RUN `--setup-agents`) state the ONE rule the hook and the census enforce together: mutating / network calls are BLOCKED before they run (logged, not fatal) and any off-list call that EXECUTES voids; the three `an errored step voids your review` consequences, false since the v2 admission tolerated errored reads, are gone. Riding in the same gate range but NOT S2 material: S1 OPEN residuals AB1 (the prune blocks on a gitfile-less `wt-r<N>`) and AB2 (only the four repository-SELECTION `GIT_*` variables are stripped) — `t8` 86-87, own commit. Tests: `t9-agy-hook.sh` NEW (8 axes), `t13` 24, `t38` 26-30, `t24` `--ignore-rules`, `t28` / `t4` wording pins. Size at GREEN: code-only +283/−55 against the declared ~180 — the PRIMARY disclosure trigger fired (×1.57, +103; the classified registry and the load check are most of it) — physical +470/−63 against ~420 (backstop clear); no public def outside the gated design; recorded, continuing (owner rule 2026-09-17).
#  0.34.1 (2026-09-17): wave 11 of the S1 gate — the bounded micro-wave the owner ruled after r11 (ledger `docs/reviews/2026-09-16-s1-worktree-delivery-residuals.md` § Owner ruling 2026-09-17 (r11), rows AA1-AA8). The outgoing round tree's acceptance test is a CONJUNCT again: repository identity AND registration AT THIS PATH — wave 10 REPLACED the second with the first where it should have ADDED to it, so a packet dir copied or moved WHOLE (`cp -a`, `mv`, a restore from backup) had its four artifacts unlinked before `git worktree remove` failed, i.e. the helper DELETED in a state the boundary says it may only observe (AA1, BLOCKING, reproduced, two families; this is not the r9 Y1 regression — that was a worktree-PATH compare). Two further reproduced refusals of VALID states: the repository probe no longer requires a `.git` ENTRY inside the path, so a `--separate-git-dir` source — whose metadata dir is what `git worktree list` names as the main worktree — resolves instead of being refused "could not be established" (AA2; the NO-DISCOVERY rule Z5 moves to `_observe_entry`, where a path is OBSERVED rather than compared), and the stale-sibling prune's SKIP now blocks on any `wt`/`wt-*` DIRECTORY it cannot resolve, `.git` or not — a lost gitfile over a LIVE registration had the reap rmtree the sibling around it (AA3; a plain file or symlink at those names still goes with the sibling, Z16 unchanged). Containment: every git probe runs with `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR`/`GIT_INDEX_FILE`/`GIT_OBJECT_DIRECTORY`/`GIT_ALTERNATE_OBJECT_DIRECTORIES` dropped next to the `LC_ALL=C` pin, so an ambient exported repository can no longer make both identity answers equal (AA5); `_digest_note` treats a snapshot whose `files` is not a list as unvalidatable instead of raising out of a refusal (AA4). Docs: rule 8 scopes the no-runnable-exit sentence to entries the helper only OBSERVED and names the one surviving escape, and pins its gate token to `ROUND_INTEGRITY_OK r<N>` (AA6); `references/packet-lifecycle.md` supports a hand-built round ONLY when it writes `delivery-r<N>.md` and captures under the ROUND label (AA7); the module docstring and `read_audit_gate.sh`'s not-found message drop the retired `packet-r<N>.md` name (AA8). t8 axis 80 narrowed + axes 81-85 new.
#  0.34.0 (2026-09-17): THE SUPPORT BOUNDARY — the packet dir is HELPER-OWNED (owner ruling after r10 named the loop's non-termination; ledger `docs/reviews/2026-09-16-s1-worktree-delivery-residuals.md` § Owner ruling 2026-09-17 (r10), plan § Owner decisions). Manual manipulation beyond ONE documented recovery (`references/packet-lifecycle.md` § Removing a stray checkout, NEW) is OUT OF SCOPE: for any state the helper cannot name as its own round tree it REFUSES WITHOUT DELETING, states five OBSERVATIONS (the quoted path; directory/symlink/file; its `.git` entry gitfile/directory/symlink/none; the repository that resolves to, or `unresolvable`; whether the round's SOURCE registers that path, or `unknown`) and closes with ONE identical pointer line. The per-shape exit selector is DELETED — no `rm`, `git worktree remove` or `git worktree prune` is printed for a stray or unremovable entry (14 residual rows across r7–r10 were that selector defeated by one more exotic filesystem state; r10 Z2/Z3/Z6/Z7/Z10/Z15 close as out-of-scope with it). The ONE surviving prescription is the `--force` escape for a round tree whose repository the helper just established LIVE. Two BUGS the same review found are fixed: the re-pin's acceptance test is REPOSITORY IDENTITY (`git rev-parse --path-format=absolute --git-common-dir` on the tree and on the source) instead of "does the source register this path" — a STALE registration plus another repository's checkout at that path unlinked all four artifacts before failing (r10 Z1, reproduced) — and `verify` resolves the delivery record by the SUPPLIED label first, then the canonical number, so a genuine pre-canonical `delivery-r04.md` + `.snapshot-r04.json` verifies WITH its hash check (r10 Z4). Narrowings: no repository is ever reported from git's parent-directory DISCOVERY (Z5); the permissive snapshot read never ranks or mints round 0 (Z11); the stale-sibling prune SKIPS only on the CHECKOUT predicate, so a plain `wt-…` file no longer makes a sibling un-reapable (Z16); `_digest_note` also reads a PADDED snapshot of the same round (Z13) and names `codex-body-r<N>.txt`'s `content_digest` as the third carrier of the record's sha256 (Z8); the no-tree WARNING enumerates rounds permissively (Z9); a NON-round `verify` prints `ROUND_INTEGRITY_OK <label> (artifact hashes NOT checked — no delivery record)` so the gate token is never satisfied silently (Z17). Wave 10 of the S1 gate (r10 Z1–Z17). t8 axes 36/51/58/60b/61/64/70/72/75 rewritten + 76–80 new; t3 follows the token line.
#  0.33.0 (2026-09-17): the round WORKTREE is `<packet-dir>/wt-r<N>` — the round lives in the tree's NAME (owner ruling after the three-family design review; ledger `docs/reviews/2026-09-16-s1-worktree-delivery-residuals.md` § Design review 2026-09-17). Cleanup derives the round from the directory name and reads nothing inside the tree for identity: record present → hash the four artifacts, any missing/different → refuse; no record + no snapshot + bare tree → never delivered → remove; anything else → refuse and preserve. `close`/`prepare` REFUSE on any entry they cannot name as the round tree (a renamed/symlinked/non-directory `wt*` at the top level, or a directory carrying `.git` at ANY depth), with an exit that applies — detach only when git registers THAT path, else `rm -rf` + `git worktree prune`; they also refuse on a legacy `wt` checkout (migration = verify, then the printed exit); with NO tree and records present `close` proceeds with a WARNING naming the anomalous round's record/snapshot/digest (owner-ruled W15). `verify` accepts a padded legacy label whose snapshot exists but resolves the delivery record by round NUMBER and refuses when it is absent (a non-round label gets a NOTE that artifact hashes were not checked); readers of `.snapshot-r*.json` are permissive, minting is canonical; `prepare`/`capture` refuse non-canonical `r0`/`r04`. Every printed recovery command is shlex-quoted and names `-C <owner>` only when resolved. Waves 7–9 of the S1 gate (r7 W1–W14, r8 X1–X13, r9 Y1–Y11).
#  0.32.0 (2026-09-17): the THREE-ROUND CAP is REMOVED (owner directive 2026-09-17, superseding 2026-08-22). Rule 5's stop set is now (a) a finding whose fix requires a PLAN or DESIGN change → owner discussion BEFORE design work; (b) convergence (zero new REAL must-fix → one focused re-confirm); (c) rule 12 contradiction / rule 4 CONFLICTED-OSCILLATING / rule 14 TERMINAL. Non-contradicting bug/completeness findings inside the existing design are fixed and re-confirmed at any round count without asking — the leader verifies, delegates implementation to a subagent (SDD/TDD) where that keeps its context lean. Evidence: the S1 worktree-delivery gate ran five rounds; two of the leader's three owner checkpoints were round-arithmetic asks over in-design bug fixes, and only the third (a write-order restructure = a design change) was a legitimate ask. Rule 5, rule 14, triage.md § Loop exit; `~/.claude/CLAUDE.md` § Slice-size budget drops its "Round budget" line and demotes the numeric size triggers to DISCLOSURE (structural stop stays the sole size ask-trigger). No code change.
#  0.31.0 (2026-09-14): the ADVISORY fourth leg(s) are configured by the skill USER in a JSON FILE, not in the leader's shell profile — `prepare` resolves `--x-leg`/`--no-x-leg` > PROJECT `<worktree>/.claude/triad-review-legs.json` > USER `$XDG_CONFIG_HOME/triad/review-legs.json` (empty/unset -> `~/.config`) > `$TRIAD_REVIEW_X_LEGS` (DEPRECATED fallback, its NOTE says so) > none (a NOTE, no longer a leader-environment defect). File contract `schema: "triad-review-legs.v1"` + `x_legs` list of `{name, vendor, agent|model(+effort), enabled}`; EVERY entry — disabled ones included — runs through the existing `--x-leg` spec parser, so the name regex / vendor set / per-vendor effort / duplicate-name / claude-effort refusals apply unchanged (a disabled entry is dropped from the RENDERED set only after it has passed them, so a leg kept on file cannot rot); a malformed or symlinked config, an unknown key, `agent` on a non-claude vendor, `model`/`effort` on claude, both `agent` and `model` are LOUD refusals naming the file BEFORE prepare's first mutation; no structured field may contain `':'` (the entry round-trips through the colon-joined spec; a claude `agent` may carry the plugin scope but not an effort tail), a RELATIVE `XDG_CONFIG_HOME` is invalid and ignored (XDG spec 0.8), and a config candidate the probe cannot read aborts the round only when it DECIDES the arm (a flag arm is never abortable, its probe failure a stderr NOTE); every ignored source — env var and config file alike — is mirrored to stderr, and stdout carries only the arm that fired. `.x-legs-r<N>.json` gains `x_config_path` (absolute or null) and `x_disabled`; `x_source` ∈ `flag|config|env|suppressed|null`. Recommended default (owner 2026-09-14, ten-round evidence `docs/reviews/2026-09-07-design-campaign-gate.md`): the claude `high` comparison arm (8 must-fix the gating claude arm missed, 2 found by no other leg) as the standing advisory arm; the Google Flash tier is no longer the standing fourth leg (0 unique blocking defects over 10 rounds) and stays on file `enabled: false`. Rule 1(d) + rule 15 + Flow 2/3, leg-contracts § Fourth leg, failure-modes W-7 + a malformed-config row, triage.md (Flash clause now conditional), NEW `references/review-legs.example.json`, docs/setting_vs.md § 6.2b. t4 axes 41-53 (+28/32/33/34/37/38/40 pins).
#  0.30.1 (2026-09-06): doc + agent-definition only — `cross-family-review-reviewer-high` (identical body, `effort: high`) registered as the ADVISORY comparison arm of the 2026-09-06 claude-effort campaign (`docs/reviews/2026-09-06-claude-effort-high-vs-xhigh-campaign.md`): dispatched only as a fourth leg (`prepare --x-leg x-claude-high:claude:cross-family-review-reviewer-high` typed next to `--x-leg "$TRIAD_REVIEW_X_LEGS"`), never the standing leg, never gates; leg-contracts § claude fresh-eye leg + § Fourth leg name it; the exporter ships it verbatim with its two siblings and s1 asserts all three ship with the read-only pin + effort tier; t7 pins the three bodies byte-identical. The registering session dispatched the new id at once on the 2026-09-06 desktop build (smoke: transcript `effort: high`) — the session-start-snapshot rule is refuted for a NEW definition file there; on any other build check the Agent tool's available-types list before the first gate.
#  0.30.0 (2026-09-06): the experimental X leg becomes the STANDING fourth leg (owner directive 2026-09-06). `prepare` reads `$TRIAD_REVIEW_X_LEGS` when no `--x-leg` is typed (`--no-x-leg` suppresses; explicit `--x-leg` wins; exactly one source ARM fires, its NOTE on stdout and the absent arm mirrored to stderr; a malformed env spec fails loud pre-mutation naming the variable). Rule 1(d) + rule 15 retitle + Flow 2; leg-contracts § Fourth leg (default spec snippet, every-round contract, read-audit gate mandatory); triage.md "Pro + Flash = ONE family" for the two-family floor and rule 12; failure-modes row for the absent fourth leg; docs/setting_vs.md § 6.2b `~/.zshenv` line (the leader's Bash tool sources `~/.zshenv` only — spike 2026-09-06). Model/effort: NO tier change (10-round evidence in docs/reviews/2026-09-06-portability-audit.md). Gate r1 fix wave: `.x-legs-r<N>.json` is written on EVERY prepare carrying `x_source` (`env` / `flag` / `suppressed` / `null`) so an audit can tell a suppressed round from a missing profile line; the absent NOTE says "unset or empty" and the "ignored this round" arm keys on the PARSED env specs; the env-provenance hint names the VARIABLE (and disclaims the plugin-manifest refusal) instead of asserting which spec was refused; triage.md's consolidation loop reads the fourth leg from the round record (MISSING line when a recorded leg filed no verdict); the read-audit directive is agy-qualified; docs say one source ARM. t4 axes 32-40.
#  0.29.2 (2026-09-05): P6-gate instruction fixes + the experimental X leg. Prompts: every rendered leg body states that a finding's `file` is a REPO-RELATIVE POSIX path (`verdict_schema` refuses an absolute one — agy r3 attempt 1 schema-fail 66 with 6 errors, and the r2 quarantined answer, both used the absolute packet path), and the claude prompt now OPENS with the OUTPUT-SHAPE NOTICE the leader had hand-added since 2026-09-04 (`--admit` refuses a reply not beginning with `{`). Docs: retry-artifact naming (`<leg>-r<N>-attempt<K>.*`, inside the leg-output allowlist) + never hand-move or chain a file op on `agy-read-audit.json` (a failed `mv &&` meant the codex leg never launched) in packet-lifecycle.md and rule 13; three failure-mode rows (paging-overshoot `admission-refused` on a big packet, the repo-relative `schema-fail`, the never-launched chained dispatch); leg-contracts agy observation (1.1.26 rejects `run_command` at execution while `init.tools` still advertises 57 — the census stays the enforcement, Policy D unchanged); triage.md scope-expansion gate on a plan-gate fold of a NEW semantic contract (fold CONSTRAINTS, delegate the row-level design), pointed at from rule 5. Feature: `prepare --x-leg <name>:<vendor>[:<model>[:<effort>]]` renders an ADVISORY 4th leg from the SAME packet (rule 15), records `.x-legs-r<N>.json`, prints the complete dispatch command; `read_audit_gate.sh --audit-file <abs>` gates an agy X leg's own read audit. Gate r1 fix wave: the raw-reply glob is X-shaped (`x-*-r[0-9]*-raw.json`, never a bare `*-raw.json` that fnmatch would span a subdirectory with); each X leg carries its OWN binding `review_id` (`<review-id>.<x-name>`) so admission mechanically refuses a cross-leg filing, and `prepare` prints an admission command for EVERY leg; `_wrapper_command_path` resolves the two shipped layouts explicitly instead of walking every ancestor; `--audit-file` must live directly in the packet dir and carry the X basename shape (the standing audit is never a legal override); a claude X leg's agent id may carry a plugin scope and its default is layout-derived from the plugin manifest; the agy X dispatch prints its read-audit gate command; `.x-legs-r<N>.json` records the basename. Gate r2 fix wave: X leg-output coverage is an explicit basename SHAPE (no `/`; `x-…-r<N>[-attempt<K>]-{raw,verdict,read-audit}.json` or `.err`) instead of a path-spanning fnmatch glob that let `x-fixtures-r1/notes-raw.json` and `x-c-r1-notes-raw.json` escape the census; a claude X spec whose FINAL field is an effort token is refused (the agent-id rejoin had re-admitted it) and an all-empty agent remainder falls back to the default; a dist-layout plugin manifest that is unreadable / not JSON / name-less now fails LOUD before prepare's first mutation instead of printing a shadowable bare agent id; the wrapper not-found NOTE prints AFTER its own leg line; the X renders carry one sentence resolving the packet's standing `Review metadata:` id against the X binding id. t3/t4/t5 pins.
#  0.29.1 (2026-09-04): agy leg TOOL-ALLOWLIST instruction (audit: 33 complete verdicts quarantined 2026-08-22..09-03 — agy advertises 57 tools to the allowlisted agent; the prompt claimed the command tool was absent): the rendered agy READ-GRANT names the five permitted tools + the forbidden planner/shell/write/subagent/browser/web tools and states any other call voids the review; wrapper 0.2.x emits the DISTINCT `admission-refused` (65) token on the census-refusal path (was `vendor-error`) so the one-retry-then-missing rule keys on it; agent bodies carry the same rule (re-run `--setup-agents`; the deployed plugin is re-exported in the same change — a host with two wrapper builds shares one agents dir). Gate r1 wave: `vendor-timeout` (65) for agy's own turn timeout (was `unknown`), forbidden-tool runs with an empty answer or a framing defect still classify `admission-refused`, the prompt block is agy-scoped with a gemini sentence, t4 links the prompt's tool list to `AGY_REVIEW_TOOLS`. t4/t28/t38 pins.
#  0.29.0 verdict-admission hardening (2026-08-30 adjudication): validate_verdict --admit raw-reply mode (no repair path; exit 2 unparseable→targeted re-ask, exit 3 end-marker absent; --admitted-out canonical claude-rN-verdict.json) + prepare prints canonical leg outputs w/ real review-id + claude prompt output-integrity/<END-VERDICT> contract + triage.md INVALID definitional home + reviewer agent-def severity/output fixes
#   0.28.5 (2026-08-29): doc-only — leg-contracts.md claude-leg
#     transcription caveat gains the RAW-STAGING RULE (+ a
#     packet-lifecycle.md cross-ref in the leg-OUTPUT allowlist bullet):
#     the still-escaped raw reply is staged in the session SCRATCHPAD
#     under a GATE-SLUG-scoped name (`<gate-slug>-claude-r<N>.raw`) with
#     write->unescape->materialize->validate run in one sitting. Two
#     same-day incidents 2026-08-29: P4-D3a r1 (a .raw inside the packet
#     dir failed verify as an uncovered non-output) and P4-D3b r3 (a
#     bare `claude-r3-verdict.raw` name reused across same-session gates
#     materialized the EARLIER gate's stale bytes; the binding validator
#     refused it — review-ID mismatch — slug-scoped naming prevents
#     rather than catches).
#   0.28.4 (2026-08-28): doc-only — packet-lifecycle.md § Round integrity
#     gains two observed-incident rules: (a) consolidation-ledger writes
#     go BEFORE `prepare` or AFTER `verify`, never during the frozen
#     round (P4-A2 merge gate r3: a mid-round ledger edit fingerprint-
#     invalidated a clean focused pass; discarded, re-run as r4); (b) the
#     verdict-name globs are SUFFIX matches — `<leg>-r<N>-verdict.json`,
#     never the inverted `<leg>-verdict-r<N>.json` (P4-A merge gate r1:
#     inverted names matched no glob and failed verify; rename recovered).
#   0.28.3 (2026-08-27): doc-only — packet-lifecycle.md § Round integrity
#     gains the leg-OUTPUT naming rule: outputs must match the shipped
#     _LEG_OUTPUT_GLOBS (*.out, *.err, *-read-audit.json, claude-r*.json,
#     *-verdict.json) AT DISPATCH TIME (P4 entry gate r1: a mis-named
#     stderr redirect tripped verify; rename recovered, naming avoids).
#   0.28.2 (2026-08-26): doc resync — references/leg-contracts.md agy-leg
#     `--cwd` obligation is now ENFORCED by the wrapper (owner ruling: a
#     review dispatch without --cwd = EXIT_ARG_ERROR pre-spawn, agy-dispatch
#     0.16.2); the 0.28.1 "does not yet refuse" clause superseded.
#   0.28.1 (2026-08-26): doc-only — rule 13 gains the session-cwd-pinning
#     project_f40_residual_discharge_merged_2026_08_19): the leader's cwd
#     resets to the primary working directory at context reinitialization
#     (probe-measured 2026-08-26 — tied to reinit, NOT to background
#     dispatch itself), which lands at long-leg wake-up boundaries; at every
#     wake-up/dispatch boundary re-read the real cwd (`pwd`) and build leg
#     args absolute at dispatch time. references/leg-contracts.md: the agy
#     leg's `--cwd` caller obligation stated (symmetric with the codex leg's
#     rule-9 READ-GRANT duty; audit census 211/421 grant-less pre-fix
#     dispatches on 2026-08-22). No flow/contract change.
#   0.28.0 (2026-08-22): GATE STOP RULES + agy leg v2. Rules 5 / 12 / 14 now
#     carry the countable stop rules the three-family consultation proposed
#     after the 9-round v1.2 gate: a 3-full-round cap (a 4th needs an owner
#     re-budget citing a NEW defect observed in real output), the occurrence
#     gate (REACHABLE-UNOBSERVED becomes code only from REAL vendor output; a
#     fixture-only repro is a residual), convergence on a round with zero new
#     REAL must-fix (then ONE hunk-scoped focused re-confirm), docs never gate
#     code (batched post-merge), scope freeze after round 2, two-family floor
#     for single-family REACHABLE items. agy leg: the wrapper's read-only
#     path v2 (setup-once allowlist agents, --add-dir, no danger flag / deny
#     transaction; a status=ERROR run with a valid bound verdict and a clean
#     census is ADMITTED) — leg-contracts resynced, READ-GRANT block
#     regenerated from the template.
#   0.27.4 (2026-08-22): agy leg = tools-allowlisted custom agent + EXISTENCE
#     pin. (a) The wrapper's `--sandbox read-only` now dispatches agy as the
#     `triad-readonly-review` custom primary agent (no shell/write/MCP/browser
#     tool; v1.2: the settings deny transaction and the headless auto-approve
#     flag are RETAINED as belt + read-tool approval, agy --sandbox is
#     dropped) — the 2026-08-22 permission-ladder spike measured
#     every deny/ask shape ending status=ERROR on ONE denied step while the
#     allowlist ends SUCCESS; the rendered READ-GRANT now says "you have NO
#     shell tool" instead of the retired "cat is deny-listed" line, and the
#     agy-leg bullets in leg-contracts.md replace the agy-1.1.8-era "prompt
#     is the only per-call carrier" sentence (3-family cross-check finding).
#     (b) EXISTENCE pin: the READ-GRANT forbids opening paths that do not
#     exist (plan-stage NEW/planned files) — upstream #826 kills the turn at
#     permission-conversion; the ContentOffset clause's rationale is
#     corrected (valid arg; the failure is paging past EOF). Pinned by
#     tests/unit/skills/t4-prepare.sh. Ledger: docs/agy-vendor-workarounds.md.
#   0.27.0 (2026-08-13): agy read-audit gate -> ONE executable lib helper
#     (owner approval; backlog record 2026-08-07 — the leader re-typed the
#     canonical jq block inline once per round, ~6x/gate observed). NEW
#     `lib/read_audit_gate.sh <abs-packet-dir> <abs-packet-file>...`:
#     digest path DERIVED as the shared "$PACKET_DIR/agy-read-audit.json"
#     literal (J1 anti-drift, no env fallback), exit 0 PASS / 2 ABSENT /
#     3 VOID / 4 INCONCLUSIVE / 64 usage (a nonexistent packet-file arg
#     fails LOUD instead of false-VOIDing on a stale name), greppable
#     READ_AUDIT_GATE_<VERDICT> summary line (+' unevaluated=<n>' when
#     some argument was not evaluated), symlinked-digest check-then-open
#     refusal (weaker than validate_verdict.py's O_NOFOLLOW read;
#     compensated by the gate running strictly post-reap on a path only
#     the wrapper writes). Gate-review waves (3-family, ledger
#     docs/reviews/2026-08-13-read-audit-helper-residuals.md): OVER-CAP
#     packet paths (>=200 chars, -ge) refused INCONCLUSIVE — a capped digest
#     stores only a prefix-identity, indistinguishable from any
#     same-prefix file incl. a stale prior-round packet (2-family
#     convergence; -ge boundary — an exactly-cap value could be a longer
#     path's truncation) — and the jq match TOOL+KEY-RESTRICTED to
#     view_file.AbsolutePath (a grep_search whose Query VALUE equals the
#     packet path is reference, not a read — live-corroborated; a
#     non-view_file entry carrying AbsolutePath is refused too); bash-4+
#     POLICY-floor guard (a 3.x death would alias exit 2 = ABSENT).
#     leg-contracts.md § agy read-audit gate keeps the SPEC and points at
#     the helper; the canonical liftable jq block now lives ONLY in the
#     helper (t41/f9 lift from it; t5-read-audit-gate.sh owns the CLI
#     contract; export ships lib/*.sh next to lib/*.py).
#   0.26.0 (2026-08-11): FU10-gate lessons — verdict-inflation fix +
#     deterministic round preparation. (1) BUG-1: the verdict-selection
#     rule ("verdict tracks the BLOCKING axis — zero Critical/must-fix
#     => SAFE TO MERGE even with Minor/HARDENING-SUGGESTION findings")
#     now rides EVERY leg prompt: stated in triage.md § Reviewer-side
#     instruction and baked into the rendered templates. Across the
#     21-verdict FU10 plan gate no leg ever returned SAFE+Minor although
#     the schema permits it (spike-confirmed through binding admission),
#     which alone made a literal unanimous SAFE unreachable. (2) Flow 4
#     and Hard rule 4 restate the non-blocking-MWF carve-out INLINE (the
#     literal-SAFE misread cost an owner call at FU10). (3) triage.md
#     § Loop exit codifies the self-recording-target non-convergence
#     pattern + the mechanical-census remedy. (4) NEW review_scratch.py
#     `prepare` subcommand (owner directive — token discipline): the
#     leader authors ONE brief (context / =====QUESTIONS===== marker /
#     questions) and NAMES the reviewed change
#     (--diff/--diff-path/--tests-path/--excerpt); the tool creates the
#     round WORKTREE and writes its four artifacts FILE-TO-FILE, writes
#     digest-r<N>.txt, renders all three round-suffixed leg bodies
#     (binding lines + per-leg READ-GRANT + severity instruction +
#     verdict-selection rule), auto-preserves round-invariant leg
#     outputs (agy-read-audit.json -> -r<N-1>; capture too), then
#     captures — replacing the manual per-round assembly that burned
#     leader context and produced the FU10 fold-edit slips. codex/agy
#     dispatch via --prompt-file on the rendered bodies. (5) claude-leg
#     reply HTML-escape transcription caveat (de-escape before
#     admission). Tests: tests/unit/skills/t4-prepare.sh (22 axes);
#     verdict_schema.py findings comment made explicitly bidirectional.
#     This version itself passed a THREE-ROUND 3-family gate, every
#     round PREPARED BY the new subcommand (dogfood). r1 (3x MWF, 25
#     findings) landed: severity instruction restored to the full
#     triage.md SoT text (3-family convergence — the condensed template
#     had dropped the untrusted-input scope / anti-over-hardening /
#     may-challenge clauses, the BUG-1 defect class reintroduced inside
#     BUG-1's own fix) + a t4 drift-guard axis pinning template<->doc
#     clauses both directions; a DO-NOT-MERGE clause (a must-not-merge
#     judgment is itself a blocking finding); review_id validated
#     against the LegVerdict contract at prepare time; preserve suffix
#     derived from the latest captured snapshot (true provenance) with
#     os.link no-clobber; fence-set + QUESTIONS-marker refusal over all
#     embedded content; dir_fd O_NOFOLLOW component chain for
#     --file/--excerpt; capture-refusal prechecks +
#     render-all-before-write; post-capture embedded-source recheck
#     (embed-vs-capture TOCTOU). r2 (codex MWF 1C+3m; claude SAFE+5m —
#     the FIRST SAFE-with-Minors composition, the BUG-1 fix observed
#     working live; agy MWF) landed: fence scan moved to
#     str.splitlines() (full boundary set incl. VT/FF/FS/GS/RS); brief
#     refuses alternate line separators outright; path guard also
#     rejects NEL/U+2028/U+2029 + empty paths; readability
#     open/close-probe on untracked + packet-dir files; --diff-path
#     disk-or-HEAD existence gate (git exits 0 on a no-match pathspec —
#     probe-confirmed); untracked-omission stderr NOTE; agy binding line
#     above the READ-GRANT. r3 (codex SAFE+2m, claude SAFE+3m, agy
#     SAFE(0) — gate CLOSED): pathspec gate gained a per-spec range-diff
#     third arm; in-scope untracked WARNING with repr()-escaped names;
#     unborn-HEAD precheck. Slice bundling (verdict policy + prepare
#     subsystem in one gate) = accepted residual per the owner's
#     explicit same-session bundle order; ledger =
#     docs/reviews/2026-08-11-skill-0260-gate-residuals.md.
#   0.25.10 (2026-08-11): codex-host 0.2.533 adoption — CLOSED (owner
#     decision C). ADOPTED and solid: LegVerdict round/leg BINDING
#     (review_id/family/content_digest, REQUIRED) + bidirectional SAFE
#     validator (SAFE must not carry Critical/must-fix; Minor/HS may) +
#     strict/forbid + POSIX finding paths, admitted via
#     validate_verdict.py --expected-review-id/--expected-family/
#     --expected-packet (all-or-nothing; digest recomputed from the
#     packet file); mechanized round integrity (review_scratch.py
#     capture/verify — per-round evidence snapshot + git-config-
#     independent worktree fingerprint incl. index-flag/uncovered-file
#     guards, ROUND_INTEGRITY_OK); codex AND agy READ-GRANT (packet read
#     FIRST, then repo verification reads; mutation denied + capture/
#     verify belt); Review-metadata packet head + per-round excerpt
#     policy + per-round digest-r<N> / agy-read-audit-r<N> naming. The
#     schema-repair-retry "severity laundering" channel was hardened
#     across a fix loop and STOPPED at round 9 (rule 12): a detection
#     probe does not converge over the adversarial JSON-encoding space,
#     and the path fired ZERO times in 18 real dispatches (all valid
#     JSON), so per owner decision C the realistic cooperative-model
#     failure is closed (marker-skip + content probe + a canonical
#     json.dumps regex backstop, terminating for the parseable space)
#     and three residuals are ACCEPTED/disclosed: the trigger token is a
#     non-authoritative hint (authority = the run-log structured
#     payload), unparseable escape-spelled content stays fail-open, and
#     the content-agnostic class-close (run-log on every retried call +
#     leader attempt-1 inspection) is a recorded FUTURE option. Declined
#     from the reference: severity/verdict token collapse, context_known
#     removal, round-scoped invalidation, no-schema-repair sentinel.
#     Full gate ledger + round-by-round history:
#     docs/reviews/2026-08-10-adopt-02533-gate-STATE.md + git log. This
#     version also folds a skill-prompt-review polish (obligation-4
#     discriminator reconciled to one source, provenance dates stripped
#     from rule bodies, changelog pruned to the file's own convention).
#   0.24.0-0.24.2 (2026-08-01): all three legs share ONE pydantic verdict
#     schema (verdict_schema.py LegVerdict/LegFinding); codex/agy via
#     native --output-schema / --json-schema, claude via its prompt's
#     output contract + the deterministic lib/validate_verdict.py; the
#     leader consolidates validated objects (references/triage.md § jq)
#     instead of reshaping three legs' prose. (Binding admission
#     superseded by 0.25.10; interim re-confirm fixes in git log.)
#   0.23.0 (2026-08-01): body split into one-level references/ after an
#     overlap/dead-content audit + a tone/provenance de-scope pass — the
#     body now carries frontmatter, when-to-use, a Contents map, the hard
#     rules stated ONCE, and the Flow; per-leg contracts, packet
#     lifecycle, triage machinery and measurement evidence moved to
#     references/. No contract changed meaning. (Older entries: git log.)
---

# triad-cross-family-review

The leader's standard **final pre-merge review**: three independent reviewers
from different model families judge a diff/branch, the suspect decisions are
posed as questions, and findings drive a fix→re-confirm loop. Codifies
the lab's standing cross-family review rule.

## When to use

- About to merge review-worthy or security/correctness-critical work.
- The leader OMITTED or SIMPLIFIED something from a vetted external source
  (the canonical author-blind-spot case).
- After a `superpowers:subagent-driven-development` run, before integrating —
  per-task spec+quality reviews are same-family and miss cross-cutting issues.

## Skip when

- A single-shot codex / gemini / agy / claude call → the per-CLI dispatch SKILLs (the `Agent` tool for claude).
- Trivial / mechanical change with no correctness or security surface.

## Contents

The body below is the whole operating contract: the hard rules and the flow.
Five references carry the detail — open one only when its column applies.

| Reference | Open it when |
|---|---|
| `references/leg-contracts.md` | dispatching legs, or weighing an agy verdict — Google-leg selection, per-leg flags/prompts, the agy READ-GRANT block, **the MECHANICAL read-audit gate (executable form = `lib/read_audit_gate.sh`)**, the agy read/network residual |
| `references/packet-lifecycle.md` | opening/closing a packet dir, assembling a LARGE packet, ordering and fencing a packet, or freezing a round |
| `references/triage.md` | consolidating a round — release paths, REAL / REACHABLE-UNOBSERVED / SPECULATIVE, the scope-expansion gate, the residual table, the reviewer-side severity instruction |
| `references/failure-modes.md` | a round misbehaved and you want the rule that already covers it — symptom → cause → rule index |
| `references/evidence.md` | a threshold or policy looks arbitrary — latency measurements, the agy depth study, measured timeouts, origin incidents |

## Hard rules

1. **Three INDEPENDENT cross-family reviewers.** (a) a **claude fresh-eye
   sub-agent** via the `Agent` tool with `subagent_type: triad-dispatch:cross-family-review-reviewer`
   — the dedicated read-only reviewer agent
   (`agents/cross-family-review-reviewer.md`) whose frontmatter pins
   `tools: Read, Grep, Glob`, making rule 7's no-execute contract mechanical
   rather than advisory. Never the leader reasoning in-line: the leader holds the
   originating framing and shares its blind spot. (b) **codex** via
   `triad-codex-dispatch`. (c) the **Google-family CLI**, resolved at runtime —
   agy and gemini share the Gemini backend, so exactly one of them is the Google
   leg. Same-family-only reviewers inherit the leader's framing; cross-family
   plus fresh-eye is what breaks the monoculture.
   - **agy verdict = ADVISORY for the unanimous gate** (standing policy). Its
     findings consolidate like any leg's, but its SAFE does not satisfy the merge
     gate — gate on codex + claude. The same applies to a Google leg that fell
     back to the shallow default tier.
   - **(d) Standing FOURTH leg(s) — ADVISORY, configured by the skill USER.**
     A fourth leg runs on the SAME packet and is consolidated like any leg,
     tagged `x:<name>` (rule 15). It never gates, never counts toward the three
     families. The legs of a round come from
     `<worktree>/.claude/triad-review-legs.json` (project) or
     `~/.config/triad/review-legs.json` (user, `$XDG_CONFIG_HOME`-aware — an
     unset, empty or RELATIVE value falls back to `~/.config`) —
     schema + example in `references/leg-contracts.md` § Fourth leg and
     `references/review-legs.example.json`; an explicit `--x-leg` (repeatable)
     replaces the file's legs for the round, `--no-x-leg` drops them, the two
     flags together are refused (exit 2); `$TRIAD_REVIEW_X_LEGS` is a
     DEPRECATED fallback honored only when no config file exists (its NOTE says
     so). Exactly one source ARM fires (its NOTE on stdout; every ignored
     source is mirrored to stderr); a gemini fourth leg WITH an effort field
     additionally prints its effort NOTE. `prepare` records the source, the
     config path and the disabled entries in `.x-legs-r<N>.json` on EVERY
     round. **No config = three standing legs** — the `NOTE — no fourth leg
     configured this round` line is information, NOT a defect.
     **Recommended default (owner 2026-09-14, ten-round evidence
     `docs/reviews/2026-09-07-design-campaign-gate.md`):** the claude `high`
     comparison arm `cross-family-review-reviewer-high` as a yield-justified
     SECOND claude arm (it raised 8 must-fix the gating claude arm missed, 2 of
     them found by no other leg). The Google Flash tier is no longer the
     standing fourth leg (0 unique blocking defects over 10 rounds); keep it on
     file with `enabled: false` if a deployment wants to re-enable it. Whenever
     a Flash leg IS configured, Pro + Flash agreement is ONE family for every
     two-family rule (`references/triage.md` § Countable stop rules).
   - **Degraded mode = fewer than three families RETURN a consolidated verdict
     this round** — neither Google CLI installed, or a leg logged terminally
     missing (rule 13). A leg that RAN and was consolidated is not degraded mode,
     whatever its verdict weighs. Degraded mode does not block merge by itself; it
     requires an explicit owner decision before merging on fewer than three
     families.
   - **Depth: xhigh-class by default; max-class only on a round the leader
     designates very-important AND algorithmically complex**, both deep legs
     escalating together. The tier is necessary but not sufficient — every leg
     also needs rule 11's adversarial framing, and rule 10's max-thinking prompt
     directive on the claude leg stays unconditional at every tier.
   - **The agy leg's read/network egress is open by design** — a deployment that
     cannot accept that runs the leg inside an external fs-scoped,
     network-denied OS sandbox.
   Everything per-leg — the deterministic selection snippet, each leg's flags and
   prompt requirements, the agy READ-GRANT block, the MECHANICAL read-audit gate
   (run `lib/read_audit_gate.sh` AND the hook LOAD CHECK `lib/agy_hook.py
   check` — `HOOK_LOAD_PASS`, 0.35.0 — before weighing that leg's verdict and before
   any agy finding enters the residual table), the folded-verdict re-dispatch,
   and the egress residual's evidence — is in `references/leg-contracts.md`.
2. **Frame suspect decisions as QUESTIONS, not settled facts.** "Is X actually
   safe to omit?" — never "X is a no-op." A biased framing propagates into the
   reviewers and defeats the purpose.
3. **Each reviewer gets the diff scope; the transport differs per leg — state it
   once here.** Give the branch ref / SHA range plus the list of suspect
   decisions. The READING legs (claude `Agent`, agy, gemini) open the packet with
   their OWN READ tools rather than by executing `git diff` or any other
   subprocess (rule 7), which keeps leader context lean; the **codex leg is
   always inlined** into `--prompt` (its guaranteed view; it ALSO gets
   `--cwd` + a READ-GRANT for verification reads — rule 9). For a LARGE packet
   the leader pre-assembles ONE focused file: the reading legs open only that
   file, and codex receives the same focused content inlined (rule 8).
4. **Consolidate, don't average — the LEADER verifies, classifies, then acts.**
   Any reviewer's Critical / must-fix, or a DO-NOT-MERGE verdict, blocks merge —
   and ONLY those do: a MERGE WITH FIXES whose findings are all non-blocking
   (Minor / HARDENING-SUGGESTION) imposes no block (`references/triage.md`
   § Verdict release), and every leg prompt carries the verdict-selection rule
   so a leg with nothing blocking says SAFE outright instead of a
   Minor-only MERGE WITH FIXES.
   A block is released only by a probe that refutes the finding, a fix the
   re-confirm pass clears, or a recorded owner decision — the three paths are
   exhaustive and a leader-side triage never clears a block on its own. The
   leader's three consolidation duties (fact-check → classify the round
   CONVERGING / CONFLICTED / OSCILLATING → call the owner immediately on a
   CONFLICTED item or an OSCILLATING round), the two severity/triage axes, and
   the release paths in full are in `references/triage.md`. A leg wired to the
   shared `LegVerdict` schema (rule 1's per-leg `--pydantic`/output-contract
   wiring) returns a validated JSON object, so mapping its `findings[]` into
   the residual table is mechanical (`jq`, `references/triage.md` §
   Consolidating validated LegVerdict objects) — a leg dispatched without the
   schema still consolidates from prose, the fallback stated there. The
   schema BINDS each verdict to its round and leg
   (`review_id`/`family`/`content_digest`, required): admission runs
   `lib/validate_verdict.py --expected-review-id/--expected-family/
   --expected-packet` for EVERY leg's JSON — the binding flags are
   all-or-nothing (a flagless run is loudly shape-only, never an
   admission), `--expected-packet` recomputes the digest from the packet
   file itself — and a binding mismatch is
   the INVALID-leg handling, never a pass
   (`references/leg-contracts.md` § Verdict binding). The claude leg's
   RAW reply file admits via `--admit` (+ `--end-marker <END-VERDICT>`,
   which the rendered prompt instructs, + `--admitted-out
   claude-r<N>-verdict.json` — the ONLY producer of the canonical file
   the consolidation jq loop reads) — no repair path; an unparseable
   reply takes the ONE-targeted-re-ask-then-INVALID chain whose
   definitional home is `references/triage.md` § Verdict release; a
   leader-completed reply is never admissible (2026-08-30 hardening).
5. **Fix→re-confirm loop — NO round cap (owner directive 2026-09-17,
   superseding the 2026-08-22 three-round cap).** Findings → fix each (own
   implementer + per-fix review, SDD/TDD — the leader VERIFIES the findings,
   delegating the verification to a subagent when that helps, and delegates
   the IMPLEMENTATION to a subagent whenever that keeps the leader's context
   lean at a worthwhile effort/model-cost trade) → re-confirm on the fixed
   branch. A first-pass DO-NOT-MERGE addressed by a FIX closes only through a
   re-confirm pass, never by the leader asserting it is fixed; a finding
   refuted by a probe closes through that path instead, with the probe
   recorded. **Non-contradicting findings that catch bugs or completeness
   gaps INSIDE the existing design are welcome at ANY round count** — fix them
   and re-confirm without asking; round arithmetic was never the problem.
   Stops: (a) **design or plan change** — a finding whose fix requires
   changing the gated plan or design (a new contract, a restructured order of
   operations, a new public def/class not in the gated design) goes to the
   OWNER before any design work starts. Accepting a review and sliding into
   over-design without that discussion is the failure this rule exists to
   prevent; (b) **convergence** — a round with zero NEW REAL must-fix findings
   ends the gate: if that round produced a fix wave, apply it and run ONE
   focused re-confirm scoped to the wave's hunks — the two GATING legs
   (codex + claude) at minimum, agy optional; a clean round with no wave
   skips the focused pass; then merge, PROVIDED every prior blocking row
   already carries a rule-4 release disposition (re-confirmed fix, recorded
   probe, or owner decision); (c) rule 12's contradiction stop and rule 4's
   CONFLICTED/OSCILLATING owner call, rule 14's TERMINAL exit. **Docs never gate code**: text-only
   findings are batched into one post-merge doc-resync commit and never
   trigger a round. A plan-gate fold that introduces a NEW semantic contract
   draws a fresh layer of REAL findings every round — fold the CONSTRAINTS
   and delegate the row-level design to the owning unit's own gate
   (`references/triage.md` § Scope-expansion gate). Name the non-termination to the owner rather than looping
   on autopilot. Rule 14 BOUNDS the loop's autonomy: only REAL-triaged
   findings with minimal diffs are fixed autonomously.
6. **Codex-path caveat (cross-family-rule nuance).** When the work being reviewed IS
   the codex dispatch path itself, codex reviews the *artifact diff* (e.g.
   Python), not its own reasoning — cross-family + fresh-eye still holds, so the
   full 3-way is valid. Use judgment; when in doubt, keep all three.
7. **Vendor review legs: READ-only, no-mutation/no-execution, generous
   timeout.** Every leg prompt — codex / agy / gemini, and the claude `Agent`
   leg, which also enforces no-exec mechanically through its tool allowlist
   (rule 1a) — instructs the reviewer to review by READING (`git diff`, file
   reads): forbidden are file MUTATION, external-state change, and CANDIDATE
   EXECUTION (running tests/scripts/builds or the code under review, spawning
   vendor CLIs). TWO legs' directives are SCOPED to a READ-GRANT: the CODEX
   leg (read-only shell commands explicitly PERMITTED; the old blanket
   wording banned the very commands codex reads files with; trailer in
   `references/leg-contracts.md` § codex leg) and the AGY leg (the worktree
   BRIEF read FIRST, still the mechanical read-audit gate's required entry,
   then verification reads across the pinned tree with file:line cites;
   `references/leg-contracts.md` § agy leg). For both, the round's
   capture/verify integrity gate (`references/packet-lifecycle.md` § Round
   integrity) is the compensating control — mutation detection, not a
   sandbox claim alone, decides admission. For the AGY leg the containment
   is MECHANICAL since 0.35.0 (S2): the round worktree carries a PreToolUse
   hook (`lib/agy_hook.py`, written by `prepare` into
   `<worktree>/.agents/hooks.json`) that DENIES mutating / command / network /
   subagent / planner tools before they run — whatever agent resolved, since
   `--agent` fails OPEN silently; admission is EFFECT-based (a BLOCKED call is
   logged, an EXECUTED off-list call voids); and the hook LOAD CHECK
   (`agy_hook.py check …` → `HOOK_LOAD_PASS`) must pass beside the read-audit
   gate before that leg's verdict is weighed (`references/leg-contracts.md`
   § agy leg). An agentic sandboxed
   reviewer otherwise live-runs the code under review, hangs on a real vendor API
   call, and under its read-only sandbox cannot reap the hung child — burning the
   whole timeout with no verdict. Pair the no-exec directive with a **timeout
   scaled to DIFF size × reasoning tier** — both, not either: budget
   `--timeout 1500` for a large diff at the max tier, and prefer SHRINKING the
   reviewed surface (`--diff-path`, `--tests-path`, `--excerpt`; rules 8-9)
   over raising the timeout. Also avoid concurrent same-family
   API pressure: keep the gemini leg off the wire while another leg may also call
   gemini (429). A live-run finding can still be valid — capture the gap, then
   re-dispatch read-only. Measurements and the originating incident:
   `references/evidence.md`.
8. **Delivery is the round's WORKTREE, at a repo-relative gitignored path,
   never `/tmp`.** `prepare` creates a DETACHED `git worktree` at
   `<packet-dir>/wt-r<N>` — THE ROUND LIVES IN THE NAME, and `close` derives
   the round from that name, never from anything inside the tree — under the
   gitignored `_runs/review/`, pinned at the
   right-hand side of `--diff`, and writes FOUR files into it: `brief.md`
   (deployment context, a size MANIFEST naming every changed file and the
   surface deliberately excluded, and the suspect questions LAST),
   `diff.prod.patch` (the gated material), `diff.tests.patch` (test changes,
   labelled as a statement of intended behaviour) and `history.txt`
   (`git log --stat`, so a leg sees commit boundaries without executing
   anything). Every leg is dispatched `--cwd <worktree>` and reads for itself;
   gemini is workspace-sandboxed to the repo and cannot read `/tmp` at all.
   **The LEADER builds the diffs** — every leg must judge the SAME bytes,
   because the binding's `content_digest` ties each verdict to that content and
   cross-family corroboration means nothing if three legs each computed their
   own diff. Retired with this design: packet assembly and `--file` whole-file
   embedding (the pinned tree already carries the whole file); `--excerpt`
   survives to pin a hot function INTO the brief, which is the mitigation when
   a diff is near the context ceiling. Before dispatching, run the round's
   `capture` (per-round evidence snapshot + canonical worktree fingerprint —
   `lib/review_scratch.py capture`, over the ROUND WORKTREE) and FREEZE the
   tree; after every required leg terminates, `verify` must print
   `ROUND_INTEGRITY_OK r<N>` before consolidation (the round-suffixed token, as
   the Flow's step 3 requires — a NON-round label's qualified line says the
   artifact hashes were not checked and never satisfies this gate). **The packet
   dir is HELPER-OWNED** (owner ruling 2026-09-17): manual manipulation beyond
   the ONE documented recovery — `references/packet-lifecycle.md` § Removing a
   stray checkout — is out of scope, and for any state it cannot name as its own
   round tree the helper REFUSES WITHOUT DELETING, states what it OBSERVES, and
   points at that section. For an entry it only OBSERVED — a stray or
   unremovable one — it prescribes no per-shape recovery command: do not expect
   a runnable exit in that refusal, and do not add one. The ONE runnable escape
   is the ROUND TREE's own `git worktree remove --force`, printed only after the
   helper has established LIVE — on that same call, before any unlink — that the
   source repository owns the tree and registers it at that path; it offers the
   operator the exit of accepting that the round's material is unverifiable.
   Lifecycle commands, the ownership fences, the fencing text, the
   `Review metadata:` block, and the capture/verify procedure:
   `references/packet-lifecycle.md`.
9. **codex leg: DE-INLINED — it reads the round worktree like every other leg
   (`--cwd` + READ-GRANT trailer).** Until this design the packet was inlined
   into `--prompt` as codex's guaranteed view; a tree checked out at the
   reviewed commit removes that premise, and the 2026-09-16 spike measured
   codex holding a 128 KB diff straight from the worktree (307.8 s `ok`, 13 of
   13 cited lines verified real against the tree). The read grant is what lets
   it VERIFY claims (the historical cannot-open-a-file failure was the old
   blanket no-exec directive, not the sandbox — reads were never
   sandbox-blocked, writes still are). Its trailer text, the rescoped fast-SAFE
   heuristic, the call-site shape and the single-quoted-heredoc pitfall it must
   avoid are in `references/leg-contracts.md` § codex leg.
10. **claude fresh-eye leg = a TRUE fresh-eye Agent, MAX thinking, adversarial.**
    The claude leg is a separate `Agent` with isolated context — never the leader
    reasoning inline. Because it is the same family as a claude leader, its
    marginal value is CONTEXT-freshness rather than family diversity (codex/agy
    carry that), so it must reason maximally to earn its place. Its prompt must
    (a) tell it to think as hard as possible before answering (ultrathink);
    (b) frame it adversarially — "a subtle defect is PRESENT; find what the
    same-family leader AND the per-task review missed", not "check if this looks
    fine"; (c) forbid severity-deflation — rate by impact rather than
    downgrading a real correctness/robustness issue to Minor to dodge a fix loop.
    It is spawned mechanically read-only via the dedicated reviewer agent (rule
    1a). Cross-check: if claude returns SAFE while a vendor leg returns must-fix,
    read that as a signal the claude prompt under-reasoned, and sharpen it next
    round.
11. **Adversarial anti-rubber-stamp framing on EVERY leg, not just claude.** The
    rule-1 review tier is necessary but not sufficient: a leg at its deepest tier
    still rubber-stamps when the prompt only asks it to check that things look
    fine. Apply rule 10's framing (assume a defect is present; no
    severity-deflation) to the codex and agy legs too, and additionally require
    every leg to (a) ENUMERATE which criteria/rules it checked before concluding
    and (b) treat a bare "SAFE / none / faithful" verdict as a failed review
    rather than a pass. A fast, terse SAFE from any leg is a rubber-stamp signal
    → re-dispatch that leg with the adversarial framing; the measured threshold
    is under 60s on a packet of 100KB or more. For the agy leg that latency check
    is SECONDARY, behind rule 1's mechanical read-audit gate (a leg the gate rules
    VOID never reaches it); for codex, which has no read-audit instrumentation,
    latency stays the primary heuristic. Criteria enumeration is required but is
    not evidence of depth (`references/evidence.md`).
12. **Non-convergence is a STOP, not another round.** The fix→re-confirm loop
    exists to CONVERGE. Stop dispatching when a new round — without adding
    material new evidence — merely flips a prior round's settled decision,
    contradicts another live leg head-on, or re-litigates an already-adjudicated
    point: consolidate the conflicting claims into a table (claim / leg / round /
    evidence) and hand the conflict to the owner. When a flip or contradiction
    DOES carry new evidence, adjudicate it with a deterministic probe first and
    let the probe decide whether the loop has genuinely stopped converging.
    Owner-call threshold (owner directive): the FIRST head-on same-decision
    contradiction where both sides survive the probe is already an owner call
    (rule 4; Pro + Flash = one voice) — no waiting for oscillation, no
    compromise crafted first. A
    probe-refuted side is not a conflict; close it by recording the probe. One
    healthy signal is not a conflict either: independent legs finding the SAME
    defect is a CONVERGENCE floor (Pro + Flash = one leg —
    `references/triage.md`) — fix it and run one final confirm.
    **Scope freeze (2026-08-22):** from round 3 on, a finding must cite a hunk
    of the gated diff; anything else (a pre-existing line, a neighbouring
    design, a hypothetical input shape) opens a NEW slice rather than another
    round of this one. **Two-family floor:** a single-family
    REACHABLE-UNOBSERVED item without a measured probe is a residual, not a
    fix.
13. **Leg orchestration: background dispatch, ONE generous wait, no unrelated
    interleaving.** Dispatch every leg in the background and wait event-driven:
    one generous wait per leg, never short repeated polls. A wait that expires is
    a wake-up boundary rather than evidence the leg failed — inspect that leg's
    state ONCE, keep a healthy running leg alive through its completion
    notification, and move a leg to rule 1's degraded/missing handling only on a
    documented terminal failure or an explicit owner decision to end the wait.
    Never interrupt or respawn a healthy leg because a wait elapsed, and never
    re-wait a leg whose result already arrived. While legs run, keep the leader's
    own context review-adjacent (fact-check planning, packet hygiene, staging
    fixes for already-returned findings): unrelated work interleaved here
    pollutes later consolidation and leg prompts. Delegate only concrete, bounded
    work, and tell each leg what to inspect and exactly what to return — a
    distilled verdict plus findings with evidence paths, never a raw dump.
    Consolidate once every dispatched leg has either returned a result or been
    logged terminally missing through that terminal path, never by silently
    dropping one. claude-host mechanics: the `Agent` tool runs in the background
    by default (`run_in_background` overrides per call) and fires a completion
    task-notification; a completed agent is resumed by id/name via `SendMessage`;
    wrapper legs are background Bash plus their completion notification.
    **Session-cwd pinning (probe-measured 2026-08-26):** the leader's
    foreground cwd is NOT durable across the wait — it resets to the primary
    working directory at context reinitialization, which lands exactly at
    long-leg wake-up boundaries (both recorded 2026-08-15 F40 occurrences).
    At every wake-up or dispatch boundary, RE-READ the real cwd (`pwd`)
    before the first repo-dependent command, and build every leg argument
    (`--cwd`, `--prompt-file`, packet paths) absolute at dispatch time —
    never from the memory of an earlier `cd`.
    **Retry artifacts + no hand-moves (2026-09-05):** a re-dispatched leg's
    earlier attempt is renamed `<leg>-r<N>-attempt<K>.err` /
    `<leg>-r<N>-attempt<K>-read-audit.json` /
    `<leg>-r<N>-attempt<K>-verdict.json` — all inside the leg-output
    allowlist. NEVER hand-move `agy-read-audit.json` (`prepare`/`capture`
    auto-rename it to the round suffix), never hand-remove an X leg's rendered
    input or `.x-legs-r<N>.json` (round evidence — an abandoned X leg is
    recorded MISSING in the round log and its artifacts stay), and never chain
    a file operation on a helper-managed file before a dispatch: a failed
    `mv &&` meant the codex leg never launched.
14. **Finding triage and over-design containment (owner directive).** The loop
    structurally rewards ADDING code, so every finding is classified during
    rule-4 consolidation BEFORE it may enter the fix queue: **REAL** (demonstrated
    — repro, logged occurrence, or cited passages read side by side) →
    minimal-diff fix; **REACHABLE-UNOBSERVED** (mechanism exists, no occurrence
    evidence) → reproduce FIRST — **from REAL vendor output** (a capture, a
    run-log, an audit row): a repro that exists only in a fixture records a
    DISCLOSED residual, it does not earn code (occurrence gate, 2026-08-22 —
    the v1.2 agy gate spent five rounds on parser shapes that never occurred
    in 22 real captures); a failed repro likewise becomes a DISCLOSED residual
    rather than a reclassification; **SPECULATIVE** (cannot occur in this
    deployment) → **no code**, record a DISCLOSED residual. Any fix that expands
    design scope — a new guard/fallback/retry/lock/validation layer, a new
    file/dependency/config surface, a spill beyond the finding's file, or more
    than 30 changed lines — STOPS for an explicit owner OK, even mid-round. A
    round whose remaining findings are all SPECULATIVE or repro-failed is
    TERMINAL: record the residuals and route to the owner any repro-failed
    REACHABLE item whose residual row would be BLOCKING (a SPECULATIVE item
    cannot block by definition). Every
    finding that is not fixed carries a row in the residual table; rows are
    updated, never deleted. The class definitions, the countable scope-gate
    thresholds, the residual-table schema and dispositions, and the reviewer-side
    severity instruction every leg prompt carries are in `references/triage.md`.
15. **Fourth leg (standing, advisory; 0.30.0 — was the experimental X leg of
    0.29.2).** An X leg is a FOURTH,
    purely ADVISORY reviewer pointed at another vendor / model / effort so its
    output can be compared with the standing leg of the same family. It NEVER
    gates, never counts toward rule 1's three families, and never substitutes
    for one — a failed or missing X leg cannot delay a round. Source order per
    round: `--x-leg` and `--no-x-leg` together are refused (exit 2); otherwise
    explicit `--x-leg` (repeatable) > `--no-x-leg` > the PROJECT config
    `<worktree>/.claude/triad-review-legs.json` > the USER config
    `$XDG_CONFIG_HOME/triad/review-legs.json` (`~/.config` when that variable
    is unset, empty or RELATIVE — a relative value is invalid and ignored per
    the XDG spec) > the DEPRECATED `$TRIAD_REVIEW_X_LEGS` (rule 1(d)) >
    none; exactly one source ARM fires (its NOTE on stdout; every ignored
    source is mirrored to stderr), and a gemini fourth leg WITH
    an effort field additionally prints its effort NOTE.
    Vendor ∈ agy|gemini|codex|claude, and model/effort
    are DISPATCH-TIME values the leader types, never pinned in code
    (`~/.claude/CLAUDE.md` § Web search rules). Per-vendor fields: agy and
    gemini take `[:<model>[:low|medium|high]]`, codex
    `[:<model>[:low|medium|high|xhigh|max]]`, and claude takes an AGENT TYPE
    only — which may itself be scoped `<plugin>:<agent>` — with NO effort
    field (a different tier is a different agent type, so a trailing effort
    token is refused). Names match `x-<lowercase-alnum>[-part]…`;
    `prepare` prints the leg's complete dispatch command and records
    `.x-legs-r<N>.json`. Each X leg is BOUND to its own
    `review_id` = `<review-id>.<name>`, so admission mechanically refuses an X
    verdict filed under the standing leg's id (and vice versa). An agy X leg's
    read audit is gated with `lib/read_audit_gate.sh --audit-file <its own
    x-…-r<N>-read-audit.json>` — that override must sit directly in the packet
    dir and carry the X basename shape; the standing audit is never legal. X
    findings enter the residual table tagged `x:<name>` and take the same
    triage; each round's comparison fields are `references/triage.md`
    § Fourth-leg comparison record, and a comparison CAMPAIGN (when the leader
    declares one) gets a leader-written ledger at
    `docs/reviews/<date>-x-leg-<name>-campaign.md`.

## Flow

1. Scope the review: branch ref + base SHA + the list of suspect/omitted/
   simplified decisions (phrased as questions). Open the packet dir with the
   rule-8 helper (`python3 <skill>/lib/review_scratch.py open <abs>/_runs/review
   <slug>`, which also prunes stale packets from crashed past reviews). Author
   the round's BRIEF — deployment context above one `=====QUESTIONS=====`
   marker line, the suspect questions below it — as a standalone file; that
   brief is the ONLY per-round text the leader writes. Keep the GATED SURFACE
   focused: for a LARGE diff name only the high-risk subset (a narrowed
   `--diff` range, `--diff-path` scoping, `--tests-path` to split test churn
   out of the gated patch, `--excerpt` hot functions into the brief) —
   `references/packet-lifecycle.md` § Large packet. At review end,
   `… close <packet-dir>` — which removes the round worktree FIRST, and
   refuses rather than forcing if a leg wrote into the reviewed tree.
2. Prepare the round with ONE deterministic command:
   `python3 <skill>/lib/review_scratch.py prepare <packet-dir>
   <source-repo> r<N> --brief <abs-brief.md>
   --diff <range> [--diff-path <rel>]... [--tests-path <pathspec>]...
   [--excerpt <rel>:<start>-<end>]...` — `--diff-path` pathspecs scope the
   reviewed surface, and `--tests-path` splits test churn out of the GATED
   patch (the review-is-CODE-only rule). It
   preserve-and-clears round-invariant leg outputs (`agy-read-audit.json`
   → its PRODUCING round's suffixed name, derived from the latest
   captured snapshot), creates the round WORKTREE at `<packet-dir>/wt-r<N>`
   (re-pinning REMOVES the round tree present, identified by its OWN name —
   never by the incoming label — after checking it against that round's record)
   pinned at the right-hand side of `--diff` and writes its four artifacts
   (`brief.md`, `diff.prod.patch`, `diff.tests.patch`, `history.txt`) with
   every byte moved FILE-TO-FILE (never streamed through leader context),
   writes `digest-r<N>.txt`, renders the three round-suffixed leg bodies
   (all three POINT AT the worktree — codex is no longer inlined)
   carrying the binding values, the per-leg READ-GRANT, and
   the verdict-selection rule, renders the CONFIGURED fourth leg's input from
   `.claude/triad-review-legs.json` (project) or
   `~/.config/triad/review-legs.json` (user) — rule 1(d); `--x-leg` /
   `--no-x-leg` override, `$TRIAD_REVIEW_X_LEGS` a deprecated fallback — and
   prints its dispatch command plus the source `NOTE`, and runs the round's
   `capture` (evidence
   snapshot + worktree fingerprint) — so every byte a leg reviews sits
   inside the census by construction (adopt-gate r1 lesson;
   `references/packet-lifecycle.md` § Round integrity + § Deterministic
   round preparation). Then resolve the
   Google-family leg and dispatch the reviewers in parallel, each
   at its family's default review tier (rule 1; max-class only on a designated
   escalation round) — `Agent` with
   `subagent_type: triad-dispatch:cross-family-review-reviewer` (escalation round →
   `subagent_type: triad-dispatch:cross-family-review-reviewer-max`; max-thinking + adversarial
   prompt per rule 10) + `triad-codex-dispatch` (codex `--reasoning xhigh
   --search`) + the resolved Google leg (`triad-antigravity-dispatch` with
   `--sandbox read-only` and `TRIAD_READ_AUDIT_FILE` bound, or
   `triad-gemini-dispatch`; skip and log if neither is installed) + the fourth
   leg by the command `prepare` printed (rule 1(d)). Each leg gets
   the same suspect-question list and diff scope. The agy leg stays read-only for
   the WHOLE round, including its folded-verdict re-dispatch
   (`references/leg-contracts.md` § agy leg).
   **Dispatch precondition — codex `--search`:** this skill passes `--search` by
   default, so the packet content becomes live web-search query context sent to
   the vendor's search backend. Confirm the packet may reach a vendor search
   backend before dispatching; if it may not, drop `--search` for that round and
   record the choice. The default stays ON, and the egress itself is a disclosed
   residual (`references/leg-contracts.md` § codex leg).
   Per-leg flags and prompts: `references/leg-contracts.md`.
3. Once every required leg has terminated, run `verify` for the round — it
   must print `ROUND_INTEGRITY_OK r<N>` (a mismatch INVALIDATES the round:
   mutation detected, never released) — validate every leg (claude: via the `--admit` route, rule 4)'s JSON with
   `lib/validate_verdict.py --expected-*` (rule 4's binding admission), then
   collect every returned leg's verdict and findings (the fourth leg included —
   for an agy fourth leg (a gemini override writes no audit —
   `references/leg-contracts.md` § gemini leg) gate its read audit with
   `lib/read_audit_gate.sh --audit-file <its own
   x-…-r<N>-read-audit.json>` first) and run rule 4's consolidation:
   fact-check each finding against the source with a deterministic probe, TRIAGE
   each finding REAL / REACHABLE-UNOBSERVED / SPECULATIVE (rule 14 — SPECULATIVE
   → DISCLOSED residual, no code), and classify the round CONVERGING /
   CONFLICTED / OSCILLATING.
4. Merge when the round is CONVERGING — a CONFLICTED item or an OSCILLATING round
   routes to the owner FIRST, and merge never passes one — AND the GATING legs
   (codex + claude) are unanimously SAFE TO MERGE with no must-fix — where a
   gating leg's MERGE WITH FIXES whose findings are ALL non-blocking
   (Minor / HARDENING-SUGGESTION) SATISFIES this clause (`references/triage.md`
   § Verdict release: it does not block merge; its findings still triage and
   carry residual rows) — AND no
   BLOCKING residual row is still `open` or `fix-ordered`, AND every rule-14
   obligation is discharged (owed repros run; SPECULATIVE / UNKNOWN-CONTEXT
   residuals recorded — a non-blocking row needs recording, not an owner
   decision; every REAL finding either fixed or carrying a row, so a REAL Minor
   never silently disappears). The Google-family leg's SAFE weighs findings but
   does not itself satisfy the gate (rule 1). A standing non-SAFE verdict from a
   gating leg can still be released this round, and an unusable one is handled as
   a missing leg — both cases in `references/triage.md` § Verdict release at the
   merge gate.
5. Run any owed REACHABLE-UNOBSERVED repros FIRST — a successful repro
   reclassifies the item REAL and it joins the fix path. Then, if no finding
   triages REAL — decidable only once every dispatched leg has returned a verdict
   or been logged terminally missing (rule 13; a wrapper failure is never counted
   as SAFE or as no-findings), and after any CONFLICTED item has been routed to
   the owner WITH the rule-12 conflict table — the loop is TERMINAL: record the
   DISCLOSED residuals, hand the merge decision to the owner when any residual row
   is BLOCKING, otherwise return to Flow 4. Do not GOTO 2. Otherwise, if the round
   is CONVERGING: fix each REAL finding with a minimal diff (implementer +
   per-fix review; a design-expanding fix stops for an owner OK), then GOTO 2 to
   re-confirm — there is no round cap (a zero-new-REAL-must-fix round
   ends the gate with one focused re-confirm). If any item is CONFLICTED or the round
   is OSCILLATING, call the owner instead of re-dispatching and hand over the
   conflict table; non-conflicted findings may continue their fix loop meanwhile.

## Failure modes

Symptom → cause → the rule that owns the fix: `references/failure-modes.md`.
It is an index, not a second statement of the rules.

## Why this exists

A same-family review chain shares the leader's blind spot, and a strict per-task
same-family review still misses cross-cutting issues. The originating incident
and the re-validation are in `references/evidence.md`.

## Related

- `triad-codex-dispatch` (codex leg) / `triad-antigravity-dispatch` + `triad-gemini-dispatch` (the runtime-selected Google-family leg).
- `superpowers:subagent-driven-development` — the per-task (same-family) review this final pass backstops.
- `superpowers:requesting-code-review` / `superpowers:receiving-code-review` — single-reviewer code-review conventions.
