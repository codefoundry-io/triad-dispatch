# Review rules — the one normative location

These rules govern both hosts; current implementation and migration status are recorded separately. Each rule carries an anchor; `process.md`, `cases/cases.json`, `units.json` and the host
skills reference the anchor. Owner rulings are quoted from `decisions/owner-register.md`.

Host citations in this file: unless a citation names its own commit, an On A citation is at `codefoundry-io/triad`
`goal/spec-main-conformance` @ `4af44cf`, with `lib/` meaning `.claude/skills/triad-cross-family-review/lib/` and
`3rd-Agent/wrappers/` the wrappers; an On B citation is at `triad-codex-dispatch` 0.2.558 @ `7f75863`.
The newer A commits and test results reconciled from PR12 head `d805b50d9824e0e18435d902bc48bf2732480554`
are attributed host evidence, not verification rerun here or blanket conformance to this draft. In particular,
C72 successful native search, C74's broader reflected capacity/subscription limit, C76 live web proof and
the R-TERMINAL/C78 replacement remain subject to their per-case limits.

## Agreement

<a id="R-AGREE"></a>
A round is agreed only when its selected roster is nonempty and EVERY selected enabled leg supplies a valid,
current-basis, explicitly affirmative `SAFE TO MERGE` result, with no blocking finding, unresolved `open_questions`,
missing result or integrity failure. Leg count and family diversity are descriptive, not additional approval thresholds
(owner [2026-10-02 ruling](../decisions/owner-register.md#D-REVIEW-STRATEGY-20261002)). Acceptance labels do not exempt a
selected leg. A Minor-only negative is schema-valid but does NOT count as agreement; preserve its verdict and record the
selection deviation. Neither a leader's refutation nor an owner exception rewrites a leg's negative verdict into approval.
An exception may authorize separate human action, but is recorded as an exception to a non-agreed round, never as machine
agreement. A later agreed round must independently satisfy this rule on its current basis (R-REREVIEW).
Collection itself runs the round integrity check before it reports agreement, on both hosts (DL-52); a skipped or
too-early separate check never yields AGREED. On B: `collect` runs `_load_basis` (seal, digest, `verify_round` at
`bin/review_round.py:1908-1931`) at its start and end (`bin/review_round_v2.py:508`, `:532`). On A (@ triad `ee011968`):
when every entry agrees, `collect` runs `review_scratch.py verify` itself before it writes an AGREED record
(`lib/collect_v2.py:1555-1582`); a failed check refuses (exit 2) and leaves the previous collection record untouched,
with one refusal — the round is INVALID, prepare a new round (triad `bb933c6b`, `lib/collect_v2.py` `collect`), as B. A
check that cannot be launched or does not finish is a host fault (exit 64): nothing about the round is known, repair the
host and collect again. `close` runs a fresh check of the latest captured round and never refuses on its outcome, even
when the check cannot run: it warns and closes (`_report_verification_state`, `lib/review_scratch.py:650-679`,
called at `:760`).
A host fault met anywhere in `collect` or `retry` — this host cannot judge any reply or cannot run its own check (the
admission library or contract cannot be loaded or read, the integrity check cannot be launched or finish) — stops the
step: it is never recorded as one entry's state, a leg outcome or one entry's refusal with its remedy, and `collect`
writes no collection record for it. A file of one entry that cannot be read stays that entry's INVALID, not a host
fault. On A the host fault is exit 64 (`_HostFault`): it propagates out of the per-entry checks and out of `retry`'s
refusal check `_retry_blocked`, which writes nothing (`lib/collect_v2.py` `_retry_blocked`, `main` @ triad `e9960053`; no
orphan attempt is adopted since triad `207dd39f`, DL-130);
a seal `collect` wrote for an entry before the step stopped stays. On B an `OSError`, `ValueError` or `TypeError` raised
out of a v2 step ends as the round-integrity refusal, exit 2 (`bin/review_round.py:2451-2452`, `:2585-2587` @
`7f75863`), so B's exit does not tell a host fault from a refusal (a fact).

Known limit, both hosts (owner, 2026-10-04, [D-LATE-ANSWER-20261004](../decisions/owner-register.md#D-LATE-ANSWER-20261004)):
a leg still running in an attempt that a retry replaced can write its answer into that attempt after collection's last
custody check of it and before the AGREED record is written; no construction stops a running process from writing into a
file it already holds, so this collection reports AGREED and the next collection reports the change (an integrity
failure, never agreement). Operator rule: before using AGREED, finish the direct invocations and TRIAD-owned
custody/result writers, then perform final integrity verification and collection under R-TERMINAL. A vendor descendant
retaining only CLI stream handles is not an additional completion gate. On A, as on B, each attempt's custody is checked
once per collection (triad `bb933c6b`). On B: `collect` checks each attempt's sealed terminal once per run
(`bin/review_round_v2.py:507-535`).

`open_questions` contains unresolved facts necessary to judge approval, not optional curiosities; every remaining entry
blocks, without a collector importance heuristic. A `SAFE TO MERGE` with a blocker or open question is invalid under the
existing wire. Explicit approval may coexist with Minor or HARDENING-SUGGESTION findings. For a plan review, the existing
affirmative token means the plan can proceed to implementation as written; it is not approval of future implementation
bytes. The wire remains `contracts/leg-verdict.schema.json`; this amendment changes collection, not its verdict enum.
Historical Minor-only and three-family release decisions are superseded for this contract; historical results remain
records of the contract under which they ran.

## Correction re-review

<a id="R-REREVIEW"></a>
Any correction to reviewed content or to the review conditions (prompts, criteria, roster, model, effort, route, policy)
creates a new [bound basis](#R-PREPARE), and EVERY selected enabled leg reviews the complete agreed scope again. The
leader chooses the reviewed range that covers that scope; the host supplies every selected leg and the `current-basis`
clause and does not check the range against earlier rounds. Rebuild the current
brief and leader-authored `prior_residual` string: current findings, dispositions, necessary rebuttal evidence, changes
and remaining uncertainties. Treat these as data and claims to check. Do not automatically append previous prompts,
verbatim conversations or successive residuals. There is no new structured residual table, state enum or semantic deduper.
Needed prior excerpts and verification outputs must be materialized in this round's bound inputs (R-CONTEXT); a historical
path alone is not current evidence or permission. Previous approval never carries forward to changed bytes or conditions.
A narrow follow-up investigation can resolve a question but cannot substitute for this full-scope re-review. The shipped
"one focused re-confirm scoped to the wave's hunks" remains withdrawn on both hosts.

<a id="R-RETRY"></a>
When a leg failed to RUN and nothing changed (source, prompts, criteria, roster, model, effort, route, policy), retry only
that leg on the same [bound basis](#R-PREPARE) (owner Q-C). A changed review condition, selection or control of that
basis refuses the retry before an attempt is allocated or dispatched; prepare a new round. Changed reviewed bytes are
caught by the round integrity verification before agreement (R-AGREE); a pre-retry rehash of the reviewed tree is not
required (`decisions/host-b-preimplementation-audit.md`, "Every renderer must immediately rehash"). On A: `retry` runs
`_check_toolkit` and `_bound_metadata` before allocating (`lib/collect_v2.py` `retry` @ triad `80b302e7`). On B: `allocate_attempt`
loads the basis (which also re-verifies the reviewed tree), re-prepares the entry's adapter — writing its capability
receipts into a new numbered preparation directory, kept as setup evidence — and then refuses changed launch controls
before the attempt directory exists (`bin/review_round_v2.py:267`, `:276-284`). Before any dispatch exists, retry the
corrected preparation step.

## Roster

<a id="R-ROSTER"></a>
The default runnable roster remains three legs, one per family, as a convenience, not an agreement requirement.
The owner may select any nonempty roster, including one leg or several entries from the same model or family, according
to subscription and capacity. Every enabled entry counts under R-AGREE, including one labelled `informational`; no leg
has a special approval rule. Only the owner changes this selection. Changing it creates a new basis; do not drop a
failed or dissenting leg to relabel an old round as agreed. Preserve unresolved findings when a later roster changes.
Preparation refuses a roster with no enabled entry before any adapter, dispatch or round record exists; that refusal is a
preparation failure, never a round outcome (On A: `resolve_roster` raises "the selected roster is empty",
`lib/roster_v2.py:782-788`; On B: `create_basis` raises "v2 review requires at least one enabled entry",
`bin/review_round_v2.py:146-148`).
A control a host resolves from a host-native source outside the roster file is a member of the bound basis like a roster
value (R-PREPARE). On A: the claude entry's model and effort come from the agent preset frontmatter
(`.claude/agents/cross-family-review-reviewer.md:5-6` and its siblings), which the round binds as the shipped preset
file's digest (`authoring/shared-dev-log.md` DL-49). `claude.agent` names one preset of the closed list A ships
(`lib/roster_v2.py` `CLAUDE_WEB_TWINS`: three base presets — base, `-high`, `-max` — and their `-web` twins; the older-model pair removed by the owner 2026-10-06, done @ triad `526aa0d`, Task 31) by its bare name; any other
value, a `:`-scoped one included, is refused at resolve on every claude entry, enabled or not (`:543`
`_check_capabilities`, through `:500` `_claude_web_twin`); `claude.model` and `claude.effort` are refused; the preset
frontmatter is the only pin. (PR #13 R-AGENT-ROLES, C73) On A each route keeps its own agent requirement: the codex
leg passes the roster's model and reasoning to its wrapper as options (`--model=<v>`, `--reasoning`), the native claude
leg is one shipped preset, and the agy leg runs its explicit read-only agent (R-CONTAIN). The six shipped reviewer presets
list `Read, Grep, Glob` in `tools` (the `-web` twins add `WebSearch, WebFetch`) and no `Bash`: the tool shape for which
Claude Code gives a sub-agent its dedicated Glob and Grep tools on macOS, Linux and WSL, where they are otherwise absent
(code.claude.com/docs/en/tools-reference § Glob tool behavior, read 2026-10-09; measured 2026-10-09 with an `Explore`
dispatch of the same tool shape — Glob, Grep and Read present and working) (`.claude/agents/cross-family-review-reviewer*.md`,
`tests/unit/skills/t7-reviewer-siblings-mirror.sh` axis 1, `tests/unit/skills/t12-roster-v2.sh` axis 42 @ triad
`e9960053`). Prepare binds, as the entry's `preset` in the round record that `roster_config_digest`
covers, the spawned preset's layout-qualified id, the sha256 of A's own shipped file (`agents/<name>.md` under this
install's layout root, the WHOLE file) and its `model` / `effort` lines (`:516` `_claude_preset`;
`lib/review_scratch.py:5776` `_v2_record_entries`, `:3263` `_qualify_claude_agent_id`). Retry and collection compare
the round's toolkit map, which holds the six shipped preset files beside every file under `lib/` and the vendored `spec/**`
(`lib/collect_v2.py` `_check_toolkit` @ triad `80b302e7`); a changed or absent preset file refuses, naming the file, with
"prepare a new round (R-REREVIEW)"; an attempt is admitted only from the dispatch record the host wrote for it (a
retry refuses an attempt that already exists above the recorded one and never adopts it @ triad `207dd39f`). The `roster_v2.py
resolve` preview prints each startable claude entry's model and effort read from that file (`lib/roster_v2.py:1133`
`main`); the dispatch line does not print them (a fact). A residual fact, nothing built for it: in the dev tree a bare
id spawns the session project's `.claude/agents/<name>.md`, else the user's `~/.claude/agents/<name>.md`, so a
same-named file there with other bytes than A's shipped file would spawn content the round did not bind; projects
linked to the dev tree (`tools/link_sot.py`) point at the same file. On B: every control comes from the resolved roster and its adapters, sealed in
the basis (`bin/review_round_v2.py:146`, `:152-169`), except that a claude entry's `agent` is passed as `--agent`
(`bin/review_adapters_v2.py:107-108`, `bin/review_round_v2.py:222-223`) and the named agent's definition, resolved by the
Claude CLI, is outside the roster and outside `_toolkit` (open, DL-49).

<a id="R-AGENT-ROLES"></a>
**Agent requirements are route-specific (C73).** An AGY primary tool profile,
an optional Claude CLI `--agent` selection, and a host-native reviewer spawn are
different mechanisms. Do not infer a shared requirement to create or resolve
agent definitions for every leg from their similar names.

| Route | Required mechanism and ownership |
|---|---|
| AGY formal leg on either host | The explicit primary profile supplies native discovery tools when absent from the vendor default; follow R-CONTAIN/C72. This does not choose the review model or create a host-native subagent. |
| B's default Claude CLI leg | `claude.agent` is null; model/effort are direct CLI selections. No named Claude agent definition or definition resolver is required for this default path. |
| A's external Codex CLI leg | Model/reasoning controls are passed directly to the CLI; no AGY-style custom agent definition is required. |
| Each host's native leg | Preserve the host's own spawning/preset mechanism. A's native Claude preset binding is not a requirement to introduce presets into B's Claude CLI path or another native host. |

Default read/search capability does not promise identical tool names. Claude
Code can use Read and shell search; its current macOS/Linux/WSL default omits
dedicated Glob/Grep. Codex CLI can inspect files through its native command tools
under the selected sandbox. Neither capability requires an AGY-style profile.
Effective permissions, tool overrides and inherited settings still apply; a null
roster agent means no explicit `--agent`, not that all vendor settings are erased.
Versioned official sources and bounded runtime evidence belong in the linked
decision, not a new per-round tool-inventory or source-read audit.

DL-49's B definition-binding obligation applies only when a non-null optional
Claude CLI agent is selected: bind its resolved definition or refuse an unbound
selection. It does not require enabling that optional feature, scanning agent
files when agent is null, or making its resolver a prerequisite for default-leg
work. The current optional implementation's unresolved conformance remains
recorded; it does not create an active or deferred resolver task. The owner
removed that unsupported planning item under
[D-NO-CLAUDE-AGENT-BACKLOG-20261009](../decisions/owner-register.md#D-NO-CLAUDE-AGENT-BACKLOG-20261009).
This does not certify or silently remove the existing optional interface.
See the [owner's scope clarification](../decisions/2026-10-09-leg-agent-scope.md).

The receipt records entries actually run and family coverage; two legs of one family remain one family, without a veto
on an otherwise agreed round. Selected investigations remain separate under R-INVEST.

Reuse each host's existing JSON roster and shipped data defaults (B: `.agents/triad-review-legs.json` and its existing
shipped default file). Change an entry's model/effort in that configuration location; resolve and pass its requested
model name exactly as configured (an alias or an exact model ID, below) to the CLI/native invocation without separately
editable copies in prompts or orchestration code.

Alias over exact model ID (owner, 2026-10-08,
[D-OWNER-ANSWERS-20261008](../decisions/owner-register.md#D-OWNER-ANSWERS-20261008) item 17, generalising
[D-PRESET-ALIASES-20261006](../decisions/owner-register.md#D-PRESET-ALIASES-20261006) beyond host A's claude presets):
rosters, presets and examples name a CLI's versionless alias wherever that CLI accepts one, and the exact model ID only
where it does not. Which aliases a CLI accepts is a measured fact. Measured: claude accepts `opus` and `sonnet`, on its
`--model` option and in an agent's `model` frontmatter (Claude Code model configuration documentation,
code.claude.com/docs/en/model-config, fetched 2026-10-06, the source cited below). Not measured: codex and agy aliases —
no run or vendor source read for this specification shows that either CLI accepts a versionless alias, so the current
codex and agy roster defaults (exact IDs and slugs, below and R-NOCOST) stay until an alias is measured (DL-114). This creates
no new settings layer; the recommended defaults are the ones stated below. Existing override precedence and explicit `model: null` semantics
remain. `vendor` is a FAMILY value (`claude` | `codex` | `google`); `agy` / `gemini` blocks hold route-specific settings.
Model and effort remain expressible for every vendor and are validated by the host adapter against its supported option
vocabulary before inference, never against a vendor catalog (R-MODEL).
When both Google CLIs are present, an explicit `google.route` pin selects one; otherwise keep R-GOOGLE's existing chain.
Timeouts remain adapter-validated (B legacy formal Gemini requires 600 s and Claude 1200 s; illustrative shared 900 s
Claude entries are not B runnable defaults). No configuration is a shared user-global dependency. Show the resolved
roster before inference, and never start unselected entries. Model lists and probes follow R-MODEL;
exact CLI model selection is not relaxed by the version rule R-CLI-VERSION.

The recommended Claude review default is Opus with `xhigh` effort (owner, 2026-09-25, then Opus 5.5), named by the
`opus` alias (the alias rule above; the owner's 2026-09-25 sentence "Ship the explicit model ID rather than the moving
`opus` alias" is superseded by D-OWNER-ANSWERS-20261008 item 17). Named model/effort overrides and explicit null
selection retain their existing semantics; an older model remains selectable where a host's route takes a full model
name as an override (B's claude CLI route), and on A no older Claude model is selectable (below).
Where a route provides selection evidence without inference, the adapter checks the exposed model and effort before
review inference and refuses a reported contradiction — for a full model ID any other model, for an alias a model
outside the family and tier it names (C34). This CLI-selection check is separate from forbidden model-list or
availability probing and does not attest the eventual runtime model. Identity or effort exposed by the actual review
call is checked before accepting its answer. Absent observations remain absent/null, never inferred and never alone
grounds for refusal; routes without exposed selection evidence acquire no new probe.
B's legacy formal route and v2 default request `opus` / `xhigh` (completed U1b,
`docs/superpowers/plans/2026-10-09-shared-spec-execution.md` § U1b @ B `ab86e86`; DL-114).
Its raw wrapper keeps caller passthrough; explicit v2 IDs and null retain their existing semantics.
On A the Claude leg is native: the agent preset's `model` frontmatter is the selection, and it holds only
when the spawn passes no per-invocation `model` parameter, which outranks the frontmatter (Claude Code sub-agents
documentation, fetched 2026-10-04); A's printed spawn line passes none: `review_scratch.py` prints the native line with no `model` parameter (`lib/review_scratch.py:2903-2915` @ triad `ee011968`; FIXED-A `aebc586`, DL-78). A native spawn
returns no model to A's code and A has no probe, so the refusal of a reported contradicting selection has no input on
A (a fact). B retains its no-inference CLI-selection check (`bin/review_adapters_v2.py:108-177` @ B `ab86e86`;
receipt scope `cli-selection`, `provider_started: false`; U1a evidence in `decisions/2026-10-09-execution-planning.md`).
The historical CLI 2.1.282 receipt establishes that selection format, not every installed version or runtime identity. On A every
shipped preset names its model by the `opus` alias, which Claude Code resolves to the latest Opus (code.claude.com/docs/en/model-config,
fetched 2026-10-06: an alias points to the recommended version and updates over time; only a full model name pins a version), so
an older Claude model is NOT selectable on A and the default is the latest Opus, not a fixed `claude-opus-5-5` (owner
2026-10-06, [D-PRESET-ALIASES-20261006](../decisions/owner-register.md#D-PRESET-ALIASES-20261006); C12 and C34 state
it, DL-100; @ triad `526aa0d`). A fact (same documentation): the alias resolves per route — the latest
Opus on the subscription login route, which R-AUTH makes the only route; an `ANTHROPIC_DEFAULT_OPUS_MODEL` setting remaps it — and
the round records `opus`, not the runtime model (selection evidence is not the runtime model), so an alias re-pointed between
prepare and retry leaves the bound file digest unchanged. A refuses `claude.model` in the roster; any other model or effort needs another
shipped preset, that is, a host release. A's lib names no model. In a plugin install the host
scopes the bare name to its own plugin (`_qualify_claude_agent_id`), so a same-named project agent cannot shadow the
shipped reviewer. The preset FILE is bound as written (the whole file's bytes, so any change of model, effort, tools
or body is a changed control). Each shipped preset's frontmatter is fixed by a build-time check, not a runtime read:
exactly the keys `name`, `description`, `tools`, `model`, `effort`; base `tools: Read, Grep, Glob`, the twin adding
`WebSearch, WebFetch` and nothing that runs or writes (R-CONTAIN); one `model:` and one `effort:` line, equal in base
and twin (`tests/unit/skills/t23-review-web-c32.sh` axis 9 @ triad `3894879`; B reads no preset — DL-49). On Ubuntu
24.04 the pydantic venv is created with `--system-site-packages` so apt's jsonschema stays visible beside the venv's
pydantic 2 (a host install fact; NOT RUN on Ubuntu). Claude Code also ranks managed-settings and `--agents`
definitions above project agents and scans every `.claude/agents/` from its working directory up to the repository
root; a host that reads fewer places records that it does not observe the others (Claude Code sub-agents
documentation, fetched 2026-10-05). The frontmatter
outranks a session-wide subagent model setting only from Claude Code v2.1.251, and a forcing setting (v2.1.257+) makes Claude
Code ignore it (same documentation): on A the pin is the selection only on such a version with no forcing setting — an operator
configuration A does not observe (a fact). Likewise for effort: a sub-agent's frontmatter `effort`
outranks the session level but not the `CLAUDE_CODE_EFFORT_LEVEL` environment variable, and a `maxEffortLevel` setting
or an organization effort cap still limits it (Claude Code model configuration documentation, fetched 2026-10-05). A
binds and records the preset's pins, the selection it requested, not the model and effort the leg ran at; Claude Code's
own sub-agent transcript records what ran, and A observes none of these operator settings (a fact; DL-96). A's guide
for skill users says so (`.claude/skills/triad-cross-family-review/SKILL.md` rule 15 @ triad `ef11f5e`).

The recommended codex review default is `gpt-6-astra` with `high` reasoning on both
hosts (owner, 2026-10-03, [D-REVIEW-LEGS-20261003](../decisions/owner-register.md#D-REVIEW-LEGS-20261003)); it stays an
exact model ID until a codex alias is measured (the alias rule above). A host's SHIPPED default roster
carries an explicit model selection for every leg — the measured alias where its CLI accepts one, else the exact
model ID: a shipped `null` resolves to the operator's personal CLI configuration and makes the
review baseline differ per machine (found on host A, `authoring/shared-dev-log.md`
DL-2). `model: null` remains an operator OVERRIDE meaning the host's default and is
frozen as null. The requested model and effort are frozen in the bound round inputs
and visible in the per-attempt dispatch record; a runtime identity the CLI does not
expose stays null, never inferred from the request, and an exposed identity that
contradicts the request is refused. A comparison or trial model on any family is an
ordinary opt-in entry; its findings count under R-AGREE like any leg's, and the difference
between two entries is a ledger observation, never a vote (C35).

## Models are user-pinned data

<a id="R-MODEL"></a>
A leg's model and effort are data the user pins in the roster entry — on a host whose native leg cannot carry a model,
in the agent definition the entry names — and the user changes them (owner, 2026-09-27: "모델 변경은 사용자가 직접하고
니가 추론하지마 … 니가 프로브로 검사하는 라운드 자체가 비용에 영향을 줌 그 모델이 없어지면 사용자에게 알리는 정도로"). A
host never chooses, infers, substitutes or falls back to another model, and runs no model-list or model-availability
probe on the review or dispatch path: a probe is a paid call, and model names change faster than any packaged list. A
host-packaged model list is data a host may display, never a gate on the user's pin. A capability check that a rule
requires — a CLI version floor that names the capability it guards, the R-REVIEW-WEB route preflight — is not a model
probe. When the vendor CLI refuses a pinned model (withdrawn, renamed, or unsupported by the installed CLI version), the
attempt ends as ONE terminal failed-to-run record that names the leg and the model and tells the user to change the roster
entry; the change is a new basis (R-REREVIEW). An exposed runtime identity that contradicts the request is still refused
(R-ROSTER) — that is an observation of the answer already paid for, not a probe.

A host transports an explicit model pin as one opaque model-option value across
every wrapper and vendor parser boundary. A value resembling another option
does not activate that option. Use an encoding supported by that boundary; no
universal argv spelling or new model-name grammar is imposed. Vendor rejection
still produces the existing single terminal outcome; it is not permission to
substitute a model or retry inference (C18, C34).
If host parsing cannot preserve an explicitly supplied model value as a string,
refuse before dispatch; never treat that malformed value as an omitted model.

(PR #13 R-MODEL opaque-transport paragraph; C18, C34) On A a pin travels as ONE option token across every boundary it
crosses: the roster renders `--model=<v>` and agy's `--effort=<v>` (`lib/roster_v2.py` `pin`, `:841-844`, called at
`:867` codex, `:889` / `:891` agy, `:915` gemini; M-1, triad `9e16880d`), and the wrappers hand it to the vendor as codex
`-c model="<v>"` (`3rd-Agent/wrappers/codex_wrapper.py:334`), gemini `--model=<v>` (`gemini_wrapper.py:585`) and agy
`--model=<v>` (`antigravity_wrapper.py:70`), all @ triad `e9960053`. Every wrapper calls `args.model.strip()` right after
`parse_args()` (codex `:170`, gemini `:377`, agy `:1243`), so a parsed value that is not a string raises before any
vendor I/O and is never treated as an omitted model. A's Python floor is Ubuntu 24.04's 3.12.3, above the Python 3.12.1
argparse defect that parses `--model=--` into a list; a literal `--` pin is a constructed shape
([D-MEASURED-SHAPES-20261005](../decisions/owner-register.md#D-MEASURED-SHAPES-20261005)) — a recorded limit, no code;
so is a `"` or `\` inside a codex pin, which would break the TOML-embedded value (DL-132). Tests:
`tests/unit/skills/t12-roster-v2.sh` axis 42, `tests/unit/wrappers/t57-gemini-preflight-c16.sh` axes 12 / 12b,
`tests/unit/wrappers/t71-agy-model-passthrough-c18.sh` axes P1 / M1 @ triad `e9960053`.

## Selected investigations

<a id="R-INVEST"></a>
A selected investigation is one or more chosen legs with a custom prompt, model / effort / perspective, authorized extra
read roots and web, returning a free-form or custom-schema result — never a review verdict (owner Q-D). Both hosts keep
it as their existing single-shot dispatch path (On A: the `triad-*-dispatch` skills with `--cwd`; On B: raw
dispatch); it is not a review round and enters no roster accounting. Web search is allowed for every investigation and
dispatch leg of every family (the leader's reading (b) of the owner's words, recorded in
[D-REVIEW-LEGS-20261003](../decisions/owner-register.md#D-REVIEW-LEGS-20261003) and confirmed by the owner's answer there:
model research and the review of prompt-engineering techniques); the caller selects it through the
host's existing web option and needs no further authorization. On A the web option is: codex `--search`
(`3rd-Agent/wrappers/codex_wrapper.py:103-116`, `:161`), agy `--web` (the read-only research agent,
`antigravity_wrapper.py:1907`) and gemini `--web` (A's research profile, without `--sandbox`, `gemini_wrapper.py:378-392`,
`:510-515`). Host A has no claude CLI route: the claude family runs natively on A — the leader's own agent, and in a
review a shipped preset (R-ROSTER) — so a claude investigation on A is a native agent with its own web tools, and A ships
no claude CLI wrapper (owner, [D-OWNER-ANSWERS-20261008](../decisions/owner-register.md#D-OWNER-ANSWERS-20261008) item 2;
host A's claude CLI wrapper bundle at triad `e0b15f1` — `3rd-Agent/wrappers/claude_wrapper.py`, the
`triad-claude-dispatch` skill, the `claude-wrapper-repair` agent and their tests — is removed, DL-110). On B: the raw AGY,
Gemini and Claude wrappers' explicit `--web` (`bin/antigravity_wrapper.py:421`, `bin/gemini_wrapper.py:256`,
`bin/claude_wrapper.py:286`; C29, C31) — B's claude `--web` adds the native pre-approval `--allowedTools WebSearch
WebFetch` only (`bin/claude_wrapper.py:417-418`) and restricts no tool list, its formal review running `--permission-mode
plan` (`:419-420`); a native codex investigation runs in the host's own codex session, and no B
code selects its web (open, DL-39). Web evidence in an investigation is a FETCHED page: the
leg cites the URL it fetched and the date or version visible on that page; a search summary is a pointer, never a
citation; an unfetched, placeholder or undated claim is UNSURE. The host appends the shared clause `web-evidence`
(`prompts/investigation.md`) LAST on every web-enabled Google INVESTIGATION. Existing host
audit/redaction/failure-log/retention rules apply; no new permanent exact-text or page store is required (D-B2).
Verify prompt assembly in tests and actual fetched-page interpretation through bounded task-authorized evidence.
Missing or incomplete evidence stays UNSURE; a URL or successful exit alone proves no fetch (case C29;
measured 2026-09-19: `spikes/2026-09-19-google-web-evidence.md`).

## Google leg

<a id="R-GOOGLE"></a>
agy and gemini are different CLIs of one family. Each host keeps its SHIPPED resolution: A — explicit pin, else agy if
installed, else gemini, else skip and log; B — `select-google-route` with its authentication-class gate (owner Q-N: keep
the existing fallback logic). The resolved route, binary and observed CLI version are frozen for the attempt and recorded;
a started leg never switches route silently. The "neither installed" outcome differs by host (A skips and logs, B refuses)
and is recorded as host policy; neither outcome is agreement. Gemini is spec-maintained where only agy runs and tested
where gemini is in service; the owner tests it and briefs the leader, who records the briefing (owner Q-N). CONVENTION
for a change whose runtime effect cannot be exercised where it is written (owner 2026-09-19: apply first, leave the
untested part as a separate config-like record): the change is APPLIED to the contract and to the author's host, and the
same commit adds a verification manifest `contracts/<contract-file>.verify.toml` — one `[[check]]` per untested effect
with `id`, `case`, `what`, the exact `brief` to dispatch, `expect`, `on_fail`, `status = "NOT RUN"`, plus the contract's
`policy_sha256` and the CLI version the reasoning was checked against. Whoever has the capability in service runs the
checks with the approved invocation documented in the manifest (a direct verification-only CLI command may select a
candidate policy or preserve engine events; host preflight/authentication boundaries still apply, and this is not
wrapper conformance), and the result is recorded ONCE, here in `decisions/owner-register.md` (a
briefing row per check) and in the case's test column; an unrun check is never green, and nothing else is written about
it on either host beyond a pointer. Current manifests: `contracts/gemini-readonly.verify.toml` (A: D-9 web-tool denies,
mutation denies, canonical `grep_search` visibility separately from alias matching, and the proposed `*` catch-all),
`contracts/gemini-readonly-b.verify.toml` (B: B1-B3 on the separate D-B1 profile),
`contracts/gemini-readonly-web.verify.toml` (A: WA1-WA2 on the R-REVIEW-WEB web profile),
`contracts/gemini-readonly-web-b.verify.toml` (B: WB1-WB2 on the R-REVIEW-WEB web profile). This convention covers
the manifests that verify a policy file (those carrying `policy_sha256`). The service and conformance manifests —
`contracts/review-web.verify.toml` (R-REVIEW-WEB live host checks WEB-A-1, WEB-A-3, WEB-A-2, WEB-B-1; WEB-A-2 runs
through `contracts/gemini-readonly-web.verify.toml` WA1-WA2, the owner-briefing route above) and
`contracts/review-strategy.verify.toml` (the 2026-10-02 strategy cases, per-host provider-free evidence) — name their
result channel in their own `result_channel` field; every manifest's checks carry id, case, what, brief, expect,
on_fail and status.

## Review purpose and context

<a id="R-PROMPT"></a>
Select one short shared purpose using `review_kind` (`contracts/review-kind.schema.json`): `formal-plan` selects
`plan-purpose`; `pre-merge` and `implementation-review` select `code-purpose`; omission defaults to `pre-merge` at the
host invocation boundary. Unknown or null values are refused before dispatch. The stage input is the value `review_kind`;
the command or request that carries it is host-native calling syntax (`units.json` prompts exceptions), and a stage under
any other name is an unknown input. On A: `review_scratch.py prepare --v2 --review-kind <value>`
(`lib/review_scratch.py:3711-3778`). On B: the `review_kind` member of the `review_round.py v2-create --request-file`
request (`bin/review_round.py:2325-2326`, `bin/review_round_v2.py:130-136`). Every leg prompt carries the shared
`current-date` clause with `<review-date>` filled by the UTC date (`YYYY-MM-DD`) on which the round was prepared, a
bound-basis member, so a retry renders the same date (C67; On A: `lib/prompts_v2.py:288`, `lib/review_scratch.py:3805`
@ `b53409b`; On B: `review_date` is recorded in the digest-covered basis and reused in retries,
`bin/review_round_v2.py:170-177`, `:198-206` @ B `e3a35a3`; DL-46,
`decisions/2026-10-10-b-shared-review-context.md`). The plan purpose REPLACES the code
purpose, not a checklist appended to it. The resolved stage is a member of the bound basis (R-PREPARE); no verdict field
is added.
All selected legs receive the same semantic purpose, requirements, scope and evidence. Identity, output handling and
provider tools remain route-specific. The default first review uses no separate personas or predicted-defect checklist.
A leader's hypotheses never limit findings elsewhere in scope. Targeted perspectives remain available through R-INVEST.
For guarded-worktree review, the leader supplies the objective, diff, worktree and explicit exclusions;
the reviewer discovers relevant unchanged code, tests and behavioral documentation within the agreed
product scope. Changed-file inventories and required packet inputs are navigation, not a per-file
read allowlist: the leader neither enumerates all related files nor approves each additional read
(C70; D-REVIEW-DISCOVERY-20261009). Prepared-copy membership remains a separate transport boundary.
Normal collection does not require the leader to reconstruct or approve source-read paths or inspect
provider logs. Inspect logs for a concrete failure, access/contamination concern or explicit audit
request, limited to that issue (C71). Existing coded required-input-read, tool-effect, hook-load,
binding and integrity checks retain their stated purposes under R-CONTAIN; they are not source-file
approval lists. These rules do not grant access to explicitly excluded data or symlink targets.
Use the existing shared clauses and renderer, not a new prompt engine. A fresh conversation is the default for a new
formal basis, but does not prove isolation from memory or inherited instructions; record actual isolation limits without
changing global memory settings. Continued-context investigations must be identified as such.

<a id="R-CONTEXT"></a>
The leader writes a concise environment summary in the existing TASK/brief: review basis and scope; supported target
runtime/deployment; relevant dependency declarations and locked/resolved versions; actually observed verification
environment and results; material execution assumptions; unknown or conflicting facts. Cite the evidence and its
revision; use `unknown` or `not applicable` with a reason rather than guessing. Support declarations, lockfile resolutions
and installed/tested versions are distinct observations. The review host's version is not automatically the target's.
Keep requirements/owner decisions, observations, claims to verify and unknowns distinguishable. An unsupported assertion
that a scenario cannot occur is not an exclusion. Do not dump credentials or the entire environment.

This is authoring guidance for leader prose, not a new environment schema. Hosts preserve existing input, regular-file,
source/packet and digest checks and transport the supplied values faithfully. A transported value includes its edges:
leading and trailing blank lines and the presence or absence of a final newline reach the bound prompt unchanged, and
any framing the host adds (an encoded string, a fence, a separator added every time) leaves the exact value recoverable
from the bound bytes, so values that differ only at an edge bind different prompts. An empty `prior_residual` is the
absent value. On A: the leader omits `--prior-residual` and no residual block is rendered; a residual file that is
empty or whitespace-only is refused, naming the omission (`lib/review_scratch.py:5535-5538`). On B: an omitted or empty
value renders the data fence holding the JSON string `""` (`bin/review_round_v2.py:197`). A host may refuse prose that
collides with its own data framing as an existing input check, and its refusal names the colliding line or characters.
On A (`lib/review_scratch.py:1681-1694` @ triad 107c5a1b): a residual or excerpt line whose stripped text equals one
of the round's fence lines; a brief is split on the one `=====QUESTIONS=====` marker line and every other brief line, a
fence-like one included, is transported as written. On
B: no such refusal; only `prior_residual` is fenced, as one JSON string inside a fence longer than any backtick run it
contains, and objective, criteria and approved_boundary are one JSON object outside any fence
(`bin/review_prompts_v2.py:53-57`, `:121-125`). Those checks do not parse
Markdown rows, verify truth/completeness, classify issues, or prove that the reviewer stayed within the instructed read
boundary. On B, existing nonempty checks cover objective, criteria and approved_boundary; `prior_residual` may be empty
and TASK.md is checked as a regular file. Decoded-value equality may prove text transport despite JSON escaping, not
semantic quality. Unknown context does not automatically invalidate preparation; a necessary unsettled fact becomes an
open question.

Needed prior findings, refutations and verification results must be present in the current bound `prior_residual` or
existing evidence/brief surface. On B, prefer existing `EVIDENCE.md` for long excerpts; additional source uses existing
source members or EVIDENCE.md, never an invented packet slot. On A, use its existing bound brief/evidence surfaces.
Historical root/export/ledger paths are provenance only, not implicit read grants or current binding. Obtain any missing
authorization before including extra source. Retain the evidence needed to assess current claims, without automatically
copying entire old rounds or delaying old-root cleanup. Leader condensation must preserve unresolved risks and relevant
counterevidence; the host neither summarizes nor semantically deduplicates it.

## Code-smell criterion

<a id="R-SMELL"></a>
The leader assesses simplicity while verifying findings: a smell needs a concrete current correctness or maintenance
cost. Prefer the smallest correction satisfying the agreed requirements; no hypothetical extensibility, new abstraction
or stylistic redesign merely to satisfy a reviewer. The shared `smell-criterion` is leader triage guidance, not a mandatory
long checklist inserted into every initial leg prompt. No dedicated smell reviewer or extra test-strengthening round.
A confirmed correctness or security defect is not downgraded because its fix is large; disclose its size. A change of the
gated design still follows R-STOP.

## Design-change stop and convergence

<a id="R-STOP"></a>
A fix requiring a new contract, public definition or substantive change to the gated design goes to the owner before that
design work starts. Line growth alone is not such a change. Continue authorized in-scope corrections while new material
counterexamples, meaningful verification of fixes, or evidence resolving necessary unknowns improve the current basis.
A passing test copied from the implementation, rewording, another vote or the same assertion without new evidence is not
progress. Verification must exercise the governing requirement; a static contradiction or a checked source can also
resolve a fact without executing code.

The leader stops repeating an item when no new evidence addresses it, while other independently progressing items may
continue. Reopen a closed claim for a new counterexample, relevant source/context change or demonstrated error in its
refutation. Two findings are CONFLICTED only if both survive verification and cannot coexist, not merely because verdicts
differ. Escalate that affected decision to the owner. Stop automatic rounds when no remaining item has a concrete path to
new verification or resolving a necessary fact; retain unresolved dissent, uncertainty and stop reason. There is no fixed
round cap or mandatory duplicate run. An owner-set resource limit is a valid stop reason, never agreement. A stalled or
exception-released process cannot bypass R-AGREE.

For skills and prompts, distinguish structural checks and static contradictions from claims about model behavior. TRIAD
does not run or arrange separate fresh-context behavior experiments for the reviewed skill/prompt; a leader's reenactment
is not such evidence. Independently supplied experiments may be assessed as evidence. Without verifiable new evidence,
record behavioral hypotheses and stop wording-only repetition without converting a remaining negative into approval.

## Owner-authorized review web verification

<a id="R-REVIEW-WEB"></a>
Web verification in REVIEW is allowed for every selected review leg in every round by the owner's standing
authorization ([D-REVIEW-LEGS-20261003](../decisions/owner-register.md#D-REVIEW-LEGS-20261003)). The host
binds that authorization into each review round; only the owner revokes it, and reviewed text, a URL or a leg's output
can neither grant nor revoke it. The operation remains REVIEW, with its normal verdict, read-only
containment, entry accounting and integrity checks. A change of the authorization applies to rounds prepared after
it, whose basis it changes under R-REREVIEW; a round already prepared keeps its bound condition (the current fact,
`authoring/shared-dev-log.md` DL-57; the owner may rule otherwise).

The invocation condition is the strict boolean `review_web_authorized`; under the standing authorization it is true for
every round unless the owner revokes that authorization. It enters the frozen common conditions and every participating
leg's prompt and launch controls. It is a round condition and a member of the bound basis (R-PREPARE), not a roster
field. Every selected route must support that condition before inference; a missing capability is a preflight refusal,
not silent partial authorization. No leader heuristic decides which technology needs web.

On CLI review routes, the route's web switch and the renderer/preflight condition must agree in both directions, with
the same review ID, digest and v2 entry/attempt binding. Under the standing authorization the host binds
`review_web_authorized` true for every review round and records it explicitly in the bound basis; a caller's `false`
is ignored while the standing authorization holds, and a non-boolean value stays an input refusal (On B:
`bin/review_round_v2.py:134-135`); it binds false only after the owner revokes the standing authorization, by an entry in
`decisions/owner-register.md`. How a revocation reaches each host (a fact, no new mechanism): On A, the operator then
edits the one constant `REVIEW_WEB_STANDING_AUTHORIZATION` (`lib/review_scratch.py:3650-3658` @ `b53409b`); On B, released commit `c81c029` uses `REVIEW_WEB_STANDING_AUTHORIZATION` in `bin/review_round_v2.py`; `create_basis` validates
the caller's strict boolean before replacing it with that policy. Only recorded owner revocation changes the constant
([B U5b evidence](../decisions/2026-10-10-b-standing-review-web.md), DL-39). Toolkit/source integrity is still independent:
editing code bytes requires a fresh basis; retaining a round's bound condition does not exempt implementation drift. An absent condition in a bound record means false. Every route of
every host supports web; a route without it is a host defect, refused at preflight until fixed. Gemini selects a
complete web-enabled host profile, never an overlay: only `google_web_search` and `web_fetch` move to allow, with all
other controls preserved; the no-web profile stays the profile for a false condition. Pre-existing owner and admin
denies remain authoritative. The review-web authorization lets no round make a permanent global settings change or
bypass a permission. Each host's agy settings fact, per host: On A, an install-time allow — a user-level agy settings allow of `read_url(*)`, made once by the operator at installation as the operator's own setting and named by the wrapper at `--setup-agents` (`3rd-Agent/wrappers/antigravity_wrapper.py:2320-2327` @ triad `e0b15f1`). Host A never writes or locks the machine-wide agy settings: it writes none of `~/.gemini/antigravity-cli/settings.json`, `.agybak`, `.agy_settings.lock`, `.agy_settings.shared.json` or `.agy_settings.holders/`, takes no lock, and reads only `settings.json`, for the agy web prerequisite check below (owner, [D-AGY-SETTINGS-UNTOUCHED-20261008](../decisions/owner-register.md#D-AGY-SETTINGS-UNTOUCHED-20261008), with the owner's answer "읽기 확인만 남김 (권장)"); its read-only leg, every review leg included, is the allowlisted agent with `--add-dir` (R-CONTAIN). Host A's other settings handling at triad `e0b15f1` — the `_agy_settings` module and its lock-timeout setting, the guard and lock around the permissive call (`antigravity_wrapper.py:2147`), the heal of a stale `.agybak` at `--setup-agents` (`:2309-2317`) and the machine uninstall's removal of the lock file and holders directory — is removed (DL-112). On B, the owner-selected U7 replacement never writes, locks, restores or heals machine-wide AGY settings or its legacy backup/lease files, for formal or raw calls. Read-only calls select the existing explicit native-tool profile with `excludeDefaultComponents: true`, retain native plan/sandbox and definition binding, and do not use headless autoapproval. An explicit project keeps its existing read-only validation. Requested review web reads the existing settings only to reject a known URL-wide deny; it does not add an allow or require a new operator setting. Missing settings mean no locally observed deny, not a runtime permission guarantee; malformed existing settings refuse requested web. Old settings/backup/lease residue is preserved without automatic restoration or deletion. The permissive raw path preserves its existing version-gated CLI behavior without a settings transaction. Implementation/measurement status is recorded in [the owner-selected U7 decision](../decisions/2026-10-11-b-agy-profile-only.md). Live service checks: `contracts/review-web.verify.toml`. Per host, a true condition reaches each
route as follows; a false condition leaves every route in its R-CONTAIN no-web posture.

- On A (cited @ `b53409b`): the carrier is `review_scratch.py prepare --v2`, which binds the strict boolean
  `review_web_authorized` to the one named constant `REVIEW_WEB_STANDING_AUTHORIZATION = True`
  (`lib/review_scratch.py:3650-3658`) and the UTC `review_date` into the digest-covered `Review metadata:` line
  (`:5897-5899`); a caller's `--review-web-authorized false` is ignored with a NOTE and a non-boolean value is refused
  before any file is written (`:3786-3806`). `collect_v2._bound_metadata` checks both against the round record, an
  absent condition meaning false (`lib/collect_v2.py:519-545`). The renderer fills `<review-web-policy>` from the fenced
  `review-web-permission` / `review-no-web` clause and records the selected clause in the prompt manifest, and fills
  `<review-date>` (`lib/prompts_v2.py:40-50`, `:153-155`, `:288`, `:581-582`). `retry` re-renders the round's
  BOUND condition (`lib/collect_v2.py` `retry` @ triad `e9960053`) and does not compare it with the current constant:
  a revocation applies to rounds prepared after it, as above (DL-57). A round prepared before this change binds no
  `review_date` and carries no toolkit map; `retry` and `collect` run `_check_toolkit` first, so it is refused with "this
  round was prepared before the host recorded its toolkit map — prepare a new round" (`lib/collect_v2.py` @
  triad `80b302e7`). Per route
  (`lib/roster_v2.py:929` `render_dispatch`):
  - codex: `--search` (`lib/roster_v2.py:994-1002`); the wrapper's `--search` (top-level `codex --search exec`) replaces
    the pinned `-c web_search="disabled"`; the read-only sandbox, `approval_policy=never` and `--ignore-rules` stay
    (`3rd-Agent/wrappers/codex_wrapper.py:103-116`, `:466`).
  - claude: the native leg is spawned as its preset's web twin by the closed table — `cross-family-review-reviewer` →
    `-web`, `-high` → `-high-web`, `-max` → `-max-web` (`lib/roster_v2.py`
    `CLAUDE_WEB_TWINS`, `:500` `_claude_web_twin`, called from `render_dispatch` at `:980` @ triad `3894879`); a web
    preset maps to itself under a true condition and to its base under a false one; a name outside the table is refused
    at resolve (R-ROSTER). Every listed preset has a twin, and the export ships all six files
    (`3rd-Agent/export_plugin.py` `VERBATIM_AGENT_FILES`). Twin content is fixed by a build-time check
    (`tests/unit/skills/t23-review-web-c32.sh` axis 9), not a runtime read. The shipped twins (`.claude/agents/cross-family-review-reviewer-web.md`, `-high-web.md`, `-max-web.md`) are, for a rebuild:
    the base preset's model and effort; tools `Read`, `Grep`, `Glob`, `WebSearch`, `WebFetch` and nothing that runs or
    writes; and a body whose web rule is the content of the shared `review-web-permission` clause
    (`prompts/common-clauses.md`).
  - agy: `--review-web` (`lib/roster_v2.py:1025`), a wrapper option that selects exactly what `--web` selects — the
    read-only research agent `triad-readonly-research` and the admission of errored steps of its two web tools — but
    never appends the investigation `web-evidence` clause, which `--web` keeps for investigations
    (`3rd-Agent/wrappers/antigravity_wrapper.py:307-314`, `:1758-1767`, `:1915-1920`, `:2043-2047`); the round's hook runs
    in its `--web` mode (`lib/review_scratch.py:4142-4152`, `:5841-5843`; `lib/agy_hook.py:123`, `:196`); the operator's
    user-level agy settings allow `read_url(*)` (the install-time prerequisite above, the operator's own setting). The
    wrapper prints that prerequisite at `--setup-agents` (`3rd-Agent/wrappers/antigravity_wrapper.py:2320-2327` @ triad
    `e0b15f1`). Host A checks it before inference as the route preflight of a missing capability (the R-REVIEW-WEB route
    preflight R-MODEL names): for a true round with an agy leg, `prepare` and the `retry` of an agy entry read the
    operator's agy settings file and refuse — naming the file and the reason — when `permissions.allow` does not list
    `read_url(*)`, when `permissions.deny` lists it, or when the file is missing or is not JSON
    (`_v2_agy_web_refusal`, `lib/review_scratch.py:2613-2648`, called at `:3224`; `lib/collect_v2.py:1658` @ triad
    `e9960053`; DL-58). The check reads and writes nothing else and takes no lock
    (D-AGY-SETTINGS-UNTOUCHED-20261008). It computes the path itself — `AGY_SETTINGS_PATH` when set, else
    `Path.home() / ".gemini" / "antigravity-cli" / "settings.json"` on every platform — and reads the file as plain JSON
    (the wrappers' `_agy_settings` module is removed @ triad `dfa2eb57`, DL-112). The vendor states that path only
    home-relative (`~/.gemini/antigravity-cli/settings.json`, codelab for CLI 1.1.27; no Linux-specific path is stated,
    checked 2026-10-08), so both hosts compute the same home-relative path on every platform — a recorded limit until a
    Linux run shows otherwise (DL-122). Historically, while a codex-host read-only agy call held its per-call deny merge (DL-107), the
    check read the merged `read_url(*)` deny and refused the round, naming that cause and telling the operator to run
    again after that call ends — an inference from both hosts' code, not measured (DL-122). A's permissive agy call
    (`--sandbox` omitted; `--dangerously-skip-permissions` on agy >= 1.1.3) runs with no lock and reads no settings
    file, and an exception inside it ends `unknown` / 1 through `_common._guarded_main`, as on the read-only route
    (`3rd-Agent/wrappers/antigravity_wrapper.py` `_dispatch` @ triad `e9960053`); agy applied a codex-host call's merged
    denies to that raw call too (deny outranks the danger flag, measured on agy 1.1.17; DL-122). B's U7 removal of
    machine-settings transactions supersedes that coexistence scenario; it is not current B work.
  - gemini: `--review-web` (`lib/roster_v2.py:1050`) attaches `3rd-Agent/wrappers/policies/gemini-readonly-web.toml`,
    byte-equal to the imported `contracts/gemini-readonly-web.toml` bytes recorded in
    `import-origin.json`, instead of the no-web profile (`gemini_wrapper.py:125`, `:465`).
    Current canonical provenance comments differ; host re-vendoring remains pending.
  - Every attempt's dispatch record is rendered from the bound condition at prepare and retry and is not re-compared
    later: no host adopts an orphan attempt — `retry` refuses an attempt that already exists above the recorded one
    (R-PREPARE; triad `207dd39f`, DL-130). A wrapper line edited by hand before it runs, and a line with the review log-dir env value removed,
    run and are caught at collection (R-BIND, the executed-command receipt and its
    known limit). A native spawn that names another preset than its record has no receipt (DL-18; a fact).
  - Host A has no legacy review entry point (owner, D-REVIEW-LEGS-20261003 "레거시 경로 차후 폐기" and the 2026-10-08
    discard list item 1; `authoring/shared-dev-log.md` DL-59, DL-128): the v1 round (`prepare` without `--v2`, its
    X-leg arms, `$TRIAD_REVIEW_X_LEGS` and the user file `~/.config/triad/review-legs.json`) is removed @ triad
    `12b1dd6f`, the v1 pydantic verdict schema `3rd-Agent/wrappers/verdict_schema.py` @ `cc5f2f3f`, and the small review
    path (`lib/review_small.py`, `small/`) @ `32124be5`. `prepare` always prepares the named-roster round and accepts
    `--v2` as its stage carrier (R-PROMPT, C60), so every A round binds the standing authorization and renders the shared
    current-date and deployment-context clauses: C67 and C68 hold on every A path. The v1 path's hand rename of an agy
    read-audit file and its move between rounds went with it; each round is prepared in its own packet dir (R-PREPARE,
    DL-115).
- On B: released commit `c81c029` normalizes the v2 request member `review_web_authorized` from
  `REVIEW_WEB_STANDING_AUTHORIZATION` in `bin/review_round_v2.py:create_basis`, after strict caller-type validation.
  Omitted/boolean caller input cannot override the policy. New rounds bind the value explicitly; retry consumes the
  frozen request, subject to existing toolkit integrity (DL-39; [B U5b evidence](../decisions/2026-10-10-b-standing-review-web.md)). For a true
  condition: native Codex receives it through its fresh-child prompt metadata and requires host web availability
  (`bin/review_adapters_v2.py:61-75`, `bin/review_prompts_v2.py:88-90`); Claude preapproves only native `WebSearch` and
  `WebFetch` (`bin/claude_wrapper.py:417-418`); AGY selects the authorized-web profile and checks existing owner URL denies without settings writes (the U7 contract above); Gemini selects
  `bin/policies/gemini-formal-web.toml`, byte-equal to `contracts/gemini-readonly-web-b.toml`
  (`bin/gemini_wrapper.py:175`, `:466`; `bin/policies/web-source-manifest.json`). Non-conformance of B's legacy entry points (a
  fact, as for A's above; keeping or retiring them is host B's own decision, the owner's answer making no ruling on B,
  DL-59): the workspace four-leg gate and
  the fixed legacy formal route render through `render_review_prompt` / `render_worktree_review_prompt`, whose
  `review_web_authorized` is a per-request value, default false (`bin/review_round.py:122`, `:141`, `:165`, `:2006-2043`,
  `:2128-2178` @ `7f75863`), so they do not bind the standing authorization.

Render only the short common `review-web-permission` clause from `prompts/common-clauses.md` when true, and the
`review-no-web` clause otherwise. Existing evidence, uncertainty and untrusted-content rules continue; do not
add technology classification or automatic web triggers. The investigation `web-evidence` clause (R-INVEST) is never
appended in REVIEW. Raw investigations remain separate under R-INVEST;
the raw Claude `--web` permit does not add review accounting or rewrite the caller's prompt.

## Containment and validity — what exists today and must survive

<a id="R-CONTAIN"></a>

AGY review discovery must remain available when the vendor removes search tools
from its default agent. An explicit main-agent profile may supply native reads,
content/name search and directory listing; model/effort stay separately selected.
The selected definition is checked before dispatch and bound into the review's
control evidence; a missing or changed definition refuses the attempt before
inference, without silently falling back or reinstalling. The no-web profile
omits web tools; its authorized-web counterpart includes them. A vendor tool
inventory is not a permission guarantee: existing web authorization and execution
containment still apply. Provisioning paths and execution containment
remain host-owned. A version-only preflight is not proof of native search: verify
capability recovery with an actual successful search and read control (C72).
On B, legacy/v2 formal AGY uses B-owned `triad-codex-readonly-review` and its
`triad-codex-readonly-research` web twin under `~/.gemini/config/agents`, selected
by `--agent`; name/path/definition SHA-256 are bound in preflight. Explicit setup
is separate from dispatch. U7 adds `excludeDefaultComponents: true` while retaining
the explicit native read/search/list/finish tools and optional web twin. Read-only
calls require AGY >=1.2.1, where exclusion was introduced; current live evidence
is on1.3.3 only. Existing plan/sandbox, definition drift checks and result/integrity
admission remain. Read-only raw investigations reuse the research profile; raw
permissive calls remain distinct. Neither host changes its native leg. The owner
accepts the measured profile posture without claiming universal pre-execution
write prevention: actual search/read/web and no write after a direct request were
observed, but there was no attempted write denied by the provider. B profiles and
review prompts prohibit MCP use; the default profile route does not claim a
mechanical deny of every inherited MCP tool. An explicit project retains its
existing `mcp(*)` deny validation. No routine
read audit, new hook or workspace-copy architecture is required by U7. See [owner decision](../decisions/2026-10-09-agy-search-tools.md).
Review legs read; they do not mutate, execute the candidate, or spawn vendors. REVIEW web follows the bound
R-REVIEW-WEB condition, which the owner's standing authorization sets true for every round (D-9's review prohibition
is superseded by D-REVIEW-LEGS-20261003). When that condition is false, REVIEW has no web: codex `web_search="disabled"`;
agy review agents without web tools (both hosts select their no-web profile;
raw investigations remain separately authorized); gemini by the explicit deny rows in its host profile below. Renderers keep the
no-web posture for a false condition and select the authorized web posture only under R-REVIEW-WEB. Gemini host
profiles remain separate under D-B1. On A: `contracts/gemini-readonly.toml` for a false condition
(`3rd-Agent/wrappers/policies/gemini-readonly.toml`) and `contracts/gemini-readonly-web.toml` for a true one (`3rd-Agent/wrappers/policies/gemini-readonly-web.toml`, byte-equal to the imported bytes recorded in `import-origin.json`,
selected under `--review-web`, `gemini_wrapper.py:125`, `:465` @ `b53409b`). On B: `contracts/gemini-readonly-b.toml` for a false condition and
`contracts/gemini-readonly-web-b.toml` for a true one (`bin/policies/gemini-formal-readonly.toml`,
`bin/policies/gemini-formal-web.toml`). Equality means exact bytes of
the selected complete profile, with its adjacent digest; no concatenated overlay is implied. Preserve B's
existing 999/998 allow/deny/catch-all and Plan Mode transition restrictions while moving its two web tools
to explicit denies. That B-profile split preserved A's imported profile and V1–V5 manifest;
the current A provenance-header edits change comments only, with rules and priorities unchanged.
Current adjacent policy digests follow those new bytes; A's host copies remain at the imported
bytes recorded in `import-origin.json` until separate host re-vendoring. B's live checks are separately recorded
in `contracts/gemini-readonly-b.verify.toml`. The web-enabled profiles are selected under R-REVIEW-WEB; the no-web
profile selection does not modify policy bytes, and their header comments (A: "review legs have no web tools"; B: "D-9: web evidence
belongs to a separately authorized investigation, never REVIEW") describe the no-web profile. B's web profile header
(`contracts/gemini-readonly-web-b.toml:1`, `:3`: "explicitly authorized web verification", "selected only for an explicitly
owner-authorized review") predates the standing authorization; under it every review round is owner-authorized, so the
header reads as "selected for a true bound condition"; its bytes stay pinned by B's manifest digest. A's web profile header
(`contracts/gemini-readonly-web.toml:9-10`) points its runtime effect at `contracts/review-web.verify.toml`; that
manifest's WEB-A-2 reaches the profile's policy checks WA1-WA2 through `contracts/gemini-readonly-web.verify.toml`
(the imported A payload bytes are pinned in `import-origin.json`; current comment-only edits
do not establish host re-vendoring or new runtime verification).
Web-enabled investigations (R-INVEST) keep web. No alignment may introduce a dangerous /
yolo permission bypass on any leg (each host discloses its existing permissive-route flags in `units.json` exceptions; none is on a review route). A leg a host runs natively stays native; no leader-model CLI subprocess is
added for symmetry. Containment EVIDENCE is attributed to the leg attempt that produced it (C23): on a host with a LIVE
per-round hook (A) the wrapper records each attempt's vendor conversation id in its read audit and the hook load check
attributes hook rows by that id — a shared, unattributed hook log never certifies a leg, and a count of conversations is
not attribution (found on A over rounds r11–r13, `authoring/shared-dev-log.md` DL-6). Per vendor, the guards that ship today and must survive any alignment (host, symbol):

- codex leg (A `codex_wrapper.py`, command builder): selected read-only sandbox, `approval_policy=never`, `--ignore-rules`
  on every posture, `web_search="disabled"` whenever `--search` is absent (`codex_wrapper.py:440-464`). On A the v2
  path passes `--search` exactly when the round's bound condition is true (`lib/roster_v2.py:994-1002` @ `b53409b`); A
  has no other review path (the small path is removed @ triad `32124be5`, DL-128). These are A's controls,
  not instructions for B's native session.
- gemini leg (A `gemini_wrapper.py`): approval modes pinned to `default` / `auto_edit` (plan and yolo removed), the
  read-only × auto_edit conflict refusal, the read-only policy-file precondition, the hardened-install read-only default,
  write posture requires `--cwd`; for a false R-REVIEW-WEB condition A's selected read-only no-web profile denies
  `google_web_search` / `web_fetch` by EXPLICIT rows (D-9 rows — `--policy` replaces only the user tier, so an unnamed
  tool keeps the default tier's decision; runtime effect per `contracts/gemini-readonly.verify.toml`); for a true
  condition A's `--review-web` selects `contracts/gemini-readonly-web.toml` (`gemini_wrapper.py:125`, `:465` @ `b53409b`;
  runtime effect per `contracts/gemini-readonly-web.verify.toml`, NOT RUN); B: `--help` capability preflight, policy self-check against
  `contracts/gemini-readonly-b.toml` for a false condition and `contracts/gemini-readonly-web-b.toml` for a true one
  (runtime effect per `contracts/gemini-readonly-b.verify.toml` / `contracts/gemini-readonly-web-b.verify.toml`), credential/endpoint
  variables removed from the child on the formal route. Effective posture is computed BEFORE the conflict and policy checks
  (On A: the hardened read-only default is assigned before both checks, `3rd-Agent/wrappers/gemini_wrapper.py:421-437`).
- agy leg (A): per-round PreToolUse allow-list hook + hook load check + read-audit gate (the hook's `--web` mode adds
  `read_url_content` / `search_web` to its allow set, `lib/agy_hook.py:123`, `:196` @ `b53409b`; a v2 round with a true
  bound condition installs the hook in that mode, `lib/review_scratch.py:4142-4152`, `:5841-5843` @ `b53409b`).
  On A, every read-only agy call (every agy review leg) runs a
  setup-once agent named with `--agent`. Without web it runs `triad-readonly-review` (allowlist `view_file`,
  `grep_search`, `list_dir`, `find_by_name`, `finish`). Under `--web` or `--review-web` it runs
  `triad-readonly-research`, which adds `read_url_content` and `search_web`. The call carries `--add-dir <--cwd>`, the
  leg's only repository read grant, with no danger flag and no settings transaction, and needs agy >= 1.1.18
  (`3rd-Agent/wrappers/antigravity_wrapper.py:356-361`, `:2087-2113`, `:2502-2507` @ triad `e0b15f1`). (PR #13 C72,
  the R-CONTAIN AGY-profile paragraph) On A that pair is the explicit profile: both definitions are embedded in the
  wrapper (`AGENT_BODIES`, `3rd-Agent/wrappers/antigravity_wrapper.py:299-317`), the review agent's own `tools:` list
  names the search tools (`grep_search`, `list_dir`, `find_by_name`), `--setup-agents` writes both once (`setup_agents`,
  `:320-343`) and a dispatch never installs one: before each read-only call `check_agent_file` (`:346-357`, called at
  `:1126`) refuses — `config-conflict` / 65, nothing spawned — unless the installed file is byte-identical to the
  embedded body (@ triad `e9960053`). A records no name, path or sha256 receipt of the definition, and the round's
  toolkit map (R-PREPARE) does not hash the wrapper that embeds it (a fact). No committed capture on A shows a native
  search step of the custom agent on agy 1.3.x, so C72's successful-search control is NOT RUN on A (2026-10-09). Measured agy
  facts: in print mode, `--agent` resolves only from `~/.gemini/config/agents` (measured 2026-08-22). A name agy cannot
  resolve does not fail: agy runs its default agent, which can write files (measured on agy 1.2.3, 2026-09-16). The
  `init` event echoes the name that was passed, so the stream cannot prove which agent loaded. agy shows a custom agent
  its full tool registry whatever the agent's `tools:` list says, so the allowlist binds only through the agent body's
  rule and the wrapper's admission census, which quarantines an answer whose stream shows an off-list tool ran
  (`:401-421`, `:695-711`). A read-only call without `--web` and without `--cwd` is
  refused with exit 3 before any vendor work (`:2391-2403`). Historical B baseline before C72: the formal route passed no `--agent`
  (`bin/antigravity_wrapper.py:151` @ `7f75863`); current profile selection follows R-CONTAIN/C72 above. B: the U7 profile-based route and optional non-mutating project validation described above; no path retains the machine-settings transaction. B's hook stays dormant; no new hook is selected. On A the read-only agy route runs an allow-list census over every attempt's tool steps, retries included (`3rd-Agent/wrappers/antigravity_wrapper.py:517-611`, `:1164-1169` @ triad `e0b15f1`): a tool outside the agent's allow-list that EXECUTED withholds the answer as `admission-refused` / 65 with the tool named, and the wrapper never retries it (`:698-711`, `:1678-1704`); this is the measured shape (a model that burned its turns on `manage_task`, 33 lost verdicts). An off-list call that was denied before it ran does not void the answer (`:1705-1714`). This is the wrapper side of the shared leg prompt's sentence that a forbidden call that executes invalidates the review (`prompts/leg-google.md:40`). Shared rule, both hosts (owner, [D-OWNER-ANSWERS-20261008B](../decisions/owner-register.md#D-OWNER-ANSWERS-20261008B) item 7): an agy read-only run whose terminal status is ERROR only because an earlier `finish` submission errored and a LATER `finish` in the same run succeeded (`step_type: finish`, state DONE, no `tool_info.error`) is admitted, the later submission being the answer. Identification and ordering of finish recovery read structured stream fields only (step type, state, `tool_info.error`, stream order), never infer recovery from message text. The separate denied-before-execution check uses the measured head of a structured `tool_info.error.message`: state must be ERROR and the first non-empty line, stripped and case-folded, must start with `tool call denied by pre-tool hook` or `user denied permission`, or start with `permission check failed for ` whose tail after the last `": ` starts with `user denied permission` or `permission denied for`. A DONE step carrying denial-shaped text is not a denial; neither a generic TOOL_ERROR type nor a phrase quoted mid-message establishes denial. An off-list tool that executed, an errored step that is neither an allowed read nor a resubmitted `finish`, or a run that read nothing still refuses recovery. On B this recovery exception applies at vendor exit0; B's nonzero classifier path remains. A's broader nonzero/errored-read admission is a host fact below, not a requirement to broaden B (maintainer clarification, [DL-113 evidence](../decisions/2026-10-10-agy-resubmission-evidence.md)). Measured basis: host A's agy leg of 2026-09-27, one run and one conversation holding the errored and then the successful `finish` (triad `docs/reviews/2026-09-27-simple-review-spike.md`, item 4), and 3 of 25 runs on 2026-08-21. On A: the census marks the last successful and the last errored submission by stream position and moves an errored `finish` that a later success follows out of the errored non-read steps (`3rd-Agent/wrappers/antigravity_wrapper.py:553-566`, `:583`, `:592-593`, `:607-611` @ triad `e0b15f1`), and the status check admits it as "a resubmitted submission" (`:714-726`); the read-blind guard still applies. Historically, B at `7f75863` refused non-SUCCESS terminals except its plan-mode completion denial. Current B at `c81c029` implements structured finish-resubmission recovery in `bin/antigravity_wrapper.py` (`_agy_finish_resubmitted`), with `tests/test_agy_finish_resubmission.py`; its exit0 and profile/read/terminal guards remain as described above and in DL-113. The following B description is the historical `7f75863` baseline, not a current recovery claim: the read-only route relies on `--mode plan --sandbox` and reads executed tool steps only as diagnostics (`bin/antigravity_wrapper.py:150-151`, `:178-211` @ `7f75863`); B emits no `admission-refused` (`bin/_common.py:85`). A fact, not an obligation. The agy hook and the gemini read-only policy are TOOL-NAME controls: neither scopes paths, and the read audit records the argument path as given, not a resolved target — they do not by themselves contain a symlink escape (see the Q4 item in R-PREPARE).
- all wrappers: binary presence; a relative `--prompt-file` or `--cwd` is ACCEPTED and resolved against the wrapper PROCESS cwd at argument processing (never the child `--cwd`); every existing validation stays — configured runtime roots where configured, regular file, UTF-8, non-empty; the resolved absolute prompt-file and child-cwd paths are represented in the existing success summary and audit row, using the host's current redaction mode (D-B2). Refusal names the resolved candidate through that same masking policy. An input with no resolvable candidate (`~<no-such-user>`, a relative path once the wrapper's entry cwd is gone) is refused masked under redaction on both hosts; without redaction A names the text given and B the exception class (a fact: A `_resolve_against_entry_cwd`, `3rd-Agent/wrappers/_common.py:1882-1905` @ triad `bf38f60`; B `input_path_error`, `bin/_common.py:537-548` @ `7f75863`). A configuration refusal (an allowed-roots entry that cannot be resolved, a hardened run without allowed roots) names the argument it stopped on, on both hosts (A `_ensure_within_runtime_roots`, `_common.py:1825-1833`; B `input_path_error`, whose label for the prompt file is `prompt load`). Failure-only run logs remain failure-only. Relative spelling alone is never a reason to refuse (C28). A host's other file options that name an existing input file (on A the schema-file options
`--output-schema-file` / `--json-schema-file`) follow the same rule (on A the resolved schema-file path is recorded in the audit row's `cmd` / the run-log's
`vendor_cmd`, the vendor argv; the summary tail carries `prompt_file=` only). Path text on a wrapper's stderr lines (a
fact; the only rule is C36's for custody lines): On A every path or free-text value on the summary tail (`prompt_file=`,
`model=`, `reasoning=`) and on the custody line (`read-audit-file:`) is percent-escaped over its
filesystem bytes by one formatter (`_summary_field`, safe set `/._-~+=@,:`). Space, `[` / `]` and every non-ASCII or
control byte are escaped, so the value stays on its line and cannot carry a second `[wrapper] <cli> <token> ` sequence
into the summary line a caller parses. An ordinary POSIX path prints byte-identical, and the audit row and run-log keep
the raw value (`3rd-Agent/wrappers/_common.py:2110-2178`, `:5696`; `3rd-Agent/wrappers/antigravity_wrapper.py:2631` @
triad `e0b15f1`). On B the summary line carries no path (`bin/_common.py:1685-1689` @ `7f75863`). The resolved paths
print raw on their own `resolved_prompt_file=… effective_cwd=…` line (`bin/_common.py:574`, through the plain `print` of
`log`, `:322-324`), so a path that holds a line break splits that line (no run has shown one). On A the read-audit gate's printed remedies follow R-RETRY — ABSENT → `retry` (a never-set `TRIAD_READ_AUDIT_FILE` is a dispatch fault: run the line `retry` prints); an audit jq cannot use → `retry` first, a new round only when `retry` refuses because the file cannot be read; a custody mismatch (an audit beside the attempt that no dispatch of its own named) and VOID → `retry`; a broken round hook log or a hooks.json that failed to load → a new round (`lib/read_audit_gate.sh`, `lib/collect_v2.py` `_agy_custody_reason`, `lib/agy_hook.py` @ triad `5534a7df` + `ee011968`). This is A's gate, not a common per-file read list or leader read audit. On A: relative paths are rebased on the process-entry cwd and then validated (`3rd-Agent/wrappers/_common.py:1800-1844`, `:1865-1881`); On B: `bin/_common.py:502-537`; exact input availability and direct-child completion under R-TERMINAL; final output capture without descendant lifecycle management; local schema validation without an automatic whole-CLI repair call (R-TERMINAL); verdict
  binding to review id, family and content digest; round integrity capture/verify.
- cleanup (only host code deletes, from declared roots — R-CLEANUP): refuses without deleting when a tree is not provably its own; ownership is proven by an allocation record or
  marker, never by a name shape (On A: a review packet by its `.active` marker; a leftover `<name>.pruning` folder without one is an unmanaged
  folder — reported and left, or, when EMPTY and past the floor, removed by R-CLEANUP's empty-folder rule like any empty
  folder; the `.pruning` / `.claim` reclaim and the name-shape `rmdir` of DL-54 are removed @ triad `24226e3d`, DL-141;
  On B: allocation provenance, verified export and root identity for stale and explicit cleanup, `bin/review_round.py:1017`, `:1060`, `:1232-1242`).

<a id="R-TERMINAL"></a>
### Vendor invocation and result collection

This contract replaces the former thread-completion/process-group prescription
([owner decision](../decisions/2026-10-11-vendor-invocation-boundary.md)). It applies
to both hosts' external CLI legs; each host's native leg remains host-owned.

The vendor owns its agent loop, tools, descendants and session lifecycle. The
host launches the selected CLI, observes its direct completion, captures its
result, and applies the existing classification, schema and review-binding rules.
For capacity and local schema-validation failures, one wrapper dispatch makes
one inference invocation of the selected CLI. The vendor owns retries inside
that invocation. Do not restart the whole CLI for capacity backoff or append a
schema-correction prompt and purchase another answer. Return the existing
`server-capacity`/64 or `schema-fail`/66 outcome, with its original vendor evidence;
authentication STOP and other higher-priority observed failures remain unchanged.
Binary/version/capability preflight is not an inference invocation. Explicit
diagnosed later dispatches and same-basis failed-entry retry under R-RETRY remain
separate owner/leader actions. Native legs remain host-owned. C78 and the
[owner-approved replacement](../decisions/2026-10-11-single-cli-invocation.md)
supersede older automatic capacity/schema-repair descriptions; historical host
evidence is not a mandate to retain those loops.

Do not infer review success from exit0 alone. Do not sweep or kill descendants
because the direct CLI completed, or reproduce a vendor's internal process manager.

Provide the exact complete input through the CLI's selected input interface.
For stdin, `complete` means all UTF-8 input was prepared and made available to
the launched CLI, not that the vendor consumed or understood it. Preparation or
encoding failure prevents launch (`not-started`). A CLI that closes stdin early
is judged by its result; no BrokenPipe, byte-consumption or file-offset audit is
required. The existing receipt keys and enum values do not change (C9).

Capture stdout and stderr independently. After direct-child completion, collect
the observed final snapshot without waiting for descendant EOF or later writes.
A local capture failure or invalid UTF-8 cannot turn exit0 into success. Preserve
available failure evidence and the real vendor exit; observed authentication STOP
retains R-AUTH precedence. Missing/incomplete or wrong-bound review results are
still refused by the existing parsers and validators.

On timeout or cancellation, stop and reap the direct child with bounded ordinary
termination. Withhold the answer even if the child handles termination by exiting0.
Timeout retains precedence over a concurrent signal, except observed R-AUTH STOP.
Catchable SIGTERM/SIGHUP observed during result collection yields the existing
`unknown`/1 interruption outcome unless a higher-priority failure applies. A bare
nonzero process termination outside that collection window is also a failed
invocation; identical summary/audit records in every signal window are not required.
No host guarantee covers every descendant or remote operation after cancellation.

Live provider-output mirroring is not required. Keep captured stderr for diagnosis;
best-effort display failure must not replace the result or replay a dropped line.
Partial setup/spawn/capture failures release invocation-owned resources and cannot
produce success (C2). Use existing own-artifact cleanup; no new janitor is implied.
Before final integrity/admission/cleanup, finish the direct invocations and
TRIAD-owned custody/result writers. A vendor descendant retaining only CLI stream
handles is not an additional completion gate. Its anonymous output file can remain
alive until those handles close; later bytes are not part of the captured result.

On B, the selected implementation uses invocation-owned anonymous temporary stream files,
ordinary direct-child supervision and offset-independent final reads. These are
host implementation choices, not requirements for A's internal code. Verification
is recorded separately in C1/C2/C9; the rule does not claim completed host adoption. Historical
mechanisms and their former test evidence are preserved in the linked
[superseded record](../decisions/2026-10-11-terminal-contract-superseded.md).
PR12's newer A evidence of that former mechanism is historical too: `t53-terminal-transport-c1c2.sh`
axes 7e/7f/7g @ triad `e9960053`; probe record-only removal at `87c7d0a5` (agy) and `adaeda5f` (gemini),
with `t57-gemini-preflight-c16.sh` axes 15-16 and `t71-agy-model-passthrough-c18.sh` axes 21-22.
Those tests do not certify the direct-child/snapshot/single-invocation replacement; A C1/C2/C9/C78 remain pending.

<a id="R-TOKENS"></a>
Every classification token a host EMITS is a member of `contracts/exit-tokens.json` and maps to the same exit code there;
wrapper-only tokens and compatibility aliases are listed explicitly as exceptions. A membership test, not an `is not None` assert, checks it (On A:
`tests/unit/wrappers/t55-exit-token-membership-c8.sh`; On B: `tests/test_exit_token_contract.py`). Every emitted
summary line carries a (token, exit) pair the contract holds or its listed exceptions name; a line whose pair the
contract does not hold, with an exit a later step corrects, is not allowed. The codex wrapper's `--task` mode and its exits 68 / 69 are removed from the contract (owner 2026-10-05; DL-91). On A
the summary line prints the contract's code for the token, never a provisional 1 a driver corrects later
(`3rd-Agent/wrappers/_common.py:3974-3984` @ `bf38f60`). On B a provisional `token-limit exit=1` summary is printed before
the driver corrects the exit to 65 (`bin/_common.py:1685-1689`, re-emitted at `:1884-1887` @ `7f75863`; DL-72).
A dispatch may print more than one summary line: when a later step changes the verdict (for example a driver promotion
or a capacity-exit promotion), the wrapper prints the summary again in the same format from the final state. The last
summary line of a dispatch is its verdict. The process exit equals that line's exit except in these recorded limits: on
A, an exception raised after the records are written (DL-98); on B, a signal that arrives after the run returned
(R-TERMINAL). On A: `_emit_canonical_summary` (`3rd-Agent/wrappers/_common.py:2182-2212` @ triad `e0b15f1`), called on
every promotion in `run_cli_with_retry` (`:4017`, `:4032`, `:4088`, `:4215`, `:4233`, `:4275`) and by the wrapper guard
(`:2249`). On B: `promote_terminal` (`bin/_common.py:1883-1888`) and the schema-rejected line (`:1889-1896`) @
`7f75863`; B's README tells the caller to use the final `[wrapper]` line (`README.md:646`).

<a id="R-CLASSIFY"></a>
A failed vendor call is classified by the vendor's own error sentence, and a sentence applies to the CLI that emits it.
The known sentences are data in `contracts/vendor-failure-lines.json`: each row names the CLI, the sentence, the part of
it a host matches (lowercase) and the token. Every host classifies a row's sentence as the row's token on the row's CLI.
The rows hold every phrase a host keeps today (On A `CLI_PATTERNS`, `3rd-Agent/wrappers/_common.py:266-302` @ triad
`e0b15f1`); a phrase measured later is a classifier-extension entry or a new row, its evidence cited beside it. A phrase a
host learns through its classifier repair loop (a proposal from a failed run's own record, applied by deterministic code) is
promoted to a row of this contract with that record as its evidence, so every host classifies it
([D-REPAIR-LOOP-KEEP-20261008](../decisions/owner-register.md#D-REPAIR-LOOP-KEEP-20261008); DL-104).
**Repair research, both hosts (C76):** after an actual run ends `unknown` or
`extraction-error`, the read-only repair analyzer may use web search and page
fetching to explain that run's literal error, exit code and CLI/version context.
Both hosts expose that capability; a blanket network prohibition must not disable
this research. Start from the failed run's record and local classifier, then search
when needed, preferring vendor documentation, source and relevant issue reports.
Queries contain only sanitized error identifiers/text and version context, never
credentials, private prompt/source content or the full run log. Cite the URLs used
and distinguish the observed output from the source's explanation in the existing
proposal reason or handoff; no new response schema or evidence store is required.
Search results supplement the run record: they do not prove an unobserved CLI
message, output field/channel or exit combination. A new error does not
automatically require a new class or rule. If the evidence supports one existing
class, propose the existing bounded extension entry; if evidence is insufficient,
web access is unavailable and needed, or a new class/design is required, report
the limitation and escalate. The analyzer remains read-only and does not invoke a
vendor CLI/model to reproduce the failure. The deterministic applier verifies
against the stored run record, not a fresh vendor call, as DL-104 specifies.
Verification requires a usable record and a demonstrated classification change;
returning the record's original classification is not proof of a learned repair.
A host transport/collection failure that determines the runtime result before
vendor classification is unsupported evidence for phrase repair. Preserve
R-TERMINAL's distinction: when the runtime retains a nonzero vendor's diagnosis,
verification follows that same path over the retained streams and raw exit; it
does not impose a new complete-output policy. Missing or empty verification input
is refused without falling through to the mutation path (C76).
Promote a verified learned phrase through the existing shared-spec authoring
process with its run evidence and any research sources; resolve a necessary new
rule before dependent implementation. Preserve existing authentication STOP and
timeout routing. This authorizes failure-driven research, not routine successful-run
log audits or speculative error enumeration. Native spawn mechanisms stay host-owned.
Owner basis: [D-REPAIR-WEB-20261009](../decisions/owner-register.md#D-REPAIR-WEB-20261009).
Under R-AUTH, both hosts refuse every repair proposal whose classification is
`oauth-env`, whether it targets a raw phrase, an AGY banner or a vendor exit code.
Authentication recovery belongs to the user through the vendor's login. This
proposal refusal does not remove existing curated extension entries or change
their loading rules. A already implements this boundary; B's corresponding
correction and verification are tracked in
[U4b applier evidence](../decisions/2026-10-09-u4b-applier.md).
A plain fragment that an answer, a reviewed file or a tool's output can contain is never a match phrase: a host may
search the whole output of a failed run, and such a fragment would hide the real cause behind a retry.
A row's carrier also names where the sentence is matched; agy's print-timeout row is matched only as a whole stderr line
beginning `[agy] `, at any vendor exit, and its answer, partial or empty, is never returned.
agy folds the middle of a long answer at about 4 KB on the CLI side. It puts an own-line `<truncated N bytes>` /
`<truncated N lines>` marker in its place and keeps no full copy (observed 2026-07-22, also under stream-json). An
answer carrying that marker on its own line is `truncated-answer` / 65 and is withheld; a quoted marker inside a sentence
does not count. The marker applies to the answer channel the route emits: the raw route's `response`;
on a schema route, a locally validated `structured_output` remains usable when only the separate `response`
carries the marker. Tool output, including web-search results, is not the emitted answer channel; do not
add a tool-output scan or a vendor-bug workaround under this rule. No recursive JSON-field scan or fixed
answer-size limit is implied. Existing schema, binding and original-JSON checks remain.
On A, the current response-first check withholds both channels; that is an A implementation fact,
not the shared requirement, and the mixed-channel pair is unmeasured (DL-102;
[evidence](../decisions/2026-10-10-u3-remaining-carriers.md)). On A: `3rd-Agent/wrappers/antigravity_wrapper.py:267-279`, `:1747-1755` @ triad `e0b15f1`. Historically B returned the folded raw answer (`bin/antigravity_wrapper.py:390-399` @ `7f75863`); B at released commit `c81c029` implements the selected-channel rule ([evidence](../decisions/2026-10-10-b-agy-answer-truncation.md)). agy's own turn timeout
(the `timeout waiting for response` row) is `vendor-timeout` / 65 on A (`:162-174`, `:2006-2020`). Historically B classified that run as `unknown` / 1 (`bin/antigravity_wrapper.py:286-303`, `bin/_common.py:690-778` @ `7f75863`); B at released commit `c81c029` emits `vendor-timeout` / 65 on the measured carrier ([evidence](../decisions/2026-10-10-b-agy-turn-timeout.md)). A
host fact: a nonzero vendor exit with an answer is `vendor-error` / 65 on A (`:1721-1746`). On A's read-only review
route the answer is instead admitted when every errored step is an allowed read or a `finish` that a later successful
`finish` follows (the shared resubmission rule, R-CONTAIN) and the run read something (`:654-733`, `:1664-1677`). On B a nonzero vendor exit goes through `classify()` before the answer is read
(`:286-303`). Both hosts classify a failed run's
known sentences in one shared order (a fact): agy's auth banner first (agy route only), then cli-subscription-cap,
server-capacity, token-limit and oauth-env — server-capacity before oauth-env because Gemini's capacity stderr always
carries the `OAuth2Client` stack trace (On A `3rd-Agent/wrappers/_common.py:2208-2232` @ `cbc67f6`; On B
`bin/_common.py:743-766` @ `7f75863`). A run the wrapper ended at its timeout is classified `timeout` (exit 2), never
retried, before the vendor exit map and every phrase list, so the partial output of a hung run never classifies as
server-capacity (a fact on both hosts: On A `classify`, `3rd-Agent/wrappers/_common.py:2555-2556` @ triad e0b15f1, where
only R-AUTH's carrier STOP, judged on what the run printed before, precedes it, `:2551-2554`; On B `classify`,
`bin/_common.py:700-701` @ `7f75863`, with no carrier rung before it, DL-75). A new rung must not let a retryable token outrank R-AUTH's STOP: an `oauth-env`
sentence on the same failed agy run outranks agy's print-timeout rung. On A that rung sits after the engine-decided
verdicts and the read-only allowlist census, above every answer, ok and retry branch
(`3rd-Agent/wrappers/antigravity_wrapper.py:179-187`, `:1135-1150` @ `cbc67f6`); on A the auth-carrier rung below now
comes before it. The shared order also lets an API-key-shaped sentence on the same failed run as a server-capacity
sentence classify `server-capacity` and be retried; under the absolute law (R-AUTH (ii)) that is a defect both hosts fix,
not a limit: A fixed (triad `ca82837`, Task 22), B to change (DL-75).
The newer A auth-first/print-timeout evidence is `f13` and `t67-auth-carrier-stop-c37.sh` @ triad `ee011968`
(C43, DL-62); it does not close C37/C43's full live evidence limits or reinstate automatic capacity retries.
On A the auth-carrier rung comes first (R-AUTH (ii)): after the ok return and before every other rung — the timeout
verdict included — an
authentication sentence or structured code in the vendor's OWN error carrier — the codex `error` / `turn.failed`
message, the claude `is_error` envelope (`api_error_status` 401, or its result text; a claude CLI route — host A has none,
DL-110), the gemini error object (code 41
`FatalAuthenticationError` or 401, or its message; gemini CLI 0.60.0), agy's `result.error` and a stderr line beginning
with its auth banner — classifies `oauth-env`, and no answer, reviewed file or tool output is read for it; the shared order above
then applies to the rest of the failed run (`3rd-Agent/wrappers/_common.py` `_auth_carrier_stop`, triad `71173cd`,
merged at triad `ca82837`). A structured code is a carrier fact `contracts/vendor-failure-lines.json` has no column for.
Except for the measured reflections below, a vendor's OWN error carrier is vendor text, so the
whole authentication vocabulary there — an API key (an api-key helper included), unauthorized or 401, not logged in, sign in
or log in (run /login), authentication or credentials, an auth / access / refresh / session / bearer token or its data, an
expired or unrefreshable token or session, an API credit balance — is the R-AUTH (ii) STOP; a vendor row is evidence of a
sentence, not the only trigger; a vendor's own authentication exit code (gemini 41) is a carrier too, and a run that ended
in a timeout is judged on what it printed before. A sentence no carrier rule knows yet ends unknown
and reaches the repair analysis, which grows the classifier; it is never retried. The STOP applies to a call that failed: a
run that completed with an answer is not stopped by a banner line. Outside a carrier the plain-fragment rule above stands.
Facts: inside a JSON message a carrier's lines are split on line feeds only (a bare CR or U+2028 there is part of the line);
on a CLI's own stderr a bare CR also starts a line (progress output rewrites the line, and the host's text-mode pipe turns it
into a line feed) — stderr is the CLI's own channel, never tool output; gemini 0.60.0
puts a fatal TOOL error into its error object as "Error executing tool <name>: …" — that message is tool output, so only the
object's code (41 / 401) is read there; gemini's "Cached credentials are not valid:" log line appears only in debug mode; a
signed-out agy print-mode run (agy 1.3.1, captured 2026-10-08, plain and stream-json) prints its banner as the FIRST stderr
line, at the line start, waits 60 s for a sign-in, ends with `error: authentication failed or timed out` and exits 1 — no
authentication-specific exit code — and in stream-json also puts `authentication failed or timed out` into the terminal
`result.error` (status ERROR, num_turns 0); both are `contracts/vendor-failure-lines.json` rows (host A's wrapper ends that run
`oauth-env` / 65 with no retry, verified the same day).
The existing AGY `permission check failed for command ` result error embeds the model's command,
so that reflected command is not authentication evidence, just as reflected schema-report text is not.
Skip that permission-denial result error entirely for authentication, including a quoted banner
inside the command; no capture establishes a vendor sign-in banner there. The CLI's own stderr
banner and the schema-report exception remain separate carriers. Keep host answer-admission checks;
do not reclassify a denied command because a filename or command contains authentication words. Likewise,
Claude `permission_denials` tool input is not the error result. Retaining original streams for the
authentication predicate must not widen other classification input to those fields. C74 records the
regression controls and [source evidence](../decisions/2026-10-09-reflected-error-text.md); these controls
introduce no new vendor field, channel, permission or native-leg mechanism.
Recorded limits (a fact, owner 2026-10-05,
[D-MEASURED-SHAPES-20261005](../decisions/owner-register.md#D-MEASURED-SHAPES-20261005)). Vendor error text belongs to the vendor and changes with each release, so a
host codes only a MEASURED shape — a capture, a row of `contracts/vendor-failure-lines.json`, or the vendor's own
source — and ordinary operator actions; a shape a reviewer constructs and no run has shown is recorded here, never coded,
and a new vendor message ends `unknown` and reaches the repair analysis. Recorded, not handled: an error object placed
mid-line, inside a tool-error line, or on a channel no capture shows; a finish-schema validation report from any CLI but
agy (agy's own, measured — the report becomes `result.error` — is read there for agy's sign-in banner only); report or
authentication text in a field other than the vendor's message; an authentication or capacity word in a tool's output on
a FAILED run (worst case: an R-AUTH STOP the owner inspects, or the bounded capacity retries (at most two, three calls) — never a lost answer). On A
only gemini's trailing stderr envelope is read (`_gemini_trailing_envelope` @ triad `e40001d`), so two fatal envelopes in
one run — an authentication one, then a capacity one — retry as capacity (constructed shape); gemini 0.60.0 in JSON mode
writes a fatal error to stderr as `[ERROR] {json}` or a pretty-printed object (gemini-cli v0.60.0
`packages/cli/src/utils/errors.ts`, `nonInteractiveCli.ts`). On A no agy step- or tool-level error text reaches the no-answer
classify input: `agy_classify_signals` forwards only the result-level `error`'s first line (`_common.py:724-745`, triad
`3626aab7`).
(PR #13 C74) On A the agy permission-denied `result.error` — its first line begins `permission check failed for `
(`_AGY_PERMISSION_HEAD`, `3rd-Agent/wrappers/_common.py:365`) and embeds the model's command — is skipped by the
auth-carrier rung before the schema-report and vocabulary arms, so a denied command quoting the sign-in banner or naming
a login command is not an R-AUTH STOP; agy's own stderr banner line and the schema-report exception stay carriers
(`_auth_carrier_stop`, `:1727-1730`, triad `893bc085`; `tests/unit/wrappers/t67-auth-carrier-stop-c37.sh` C74 axes
(a)-(d) and the neutral control @ triad `e9960053`). A has no external claude route (DL-110), so C74's
`permission_denials` half does not apply on A. A recorded limit on A: that error's first line still reaches the
no-answer classify input, so a denied command quoting a measured capacity or subscription-cap sentence could classify
`server-capacity` / `cli-subscription-cap` (a constructed shape, not guarded). On A the trailing-envelope scan is
quadratic on a stderr with many braces and no trailing object — reachable on measured gemini 429 dumps, with no hang
recorded over 334 `server-capacity` rows. The plain-English `model overloaded`, `service unavailable` and `too many
requests` are not match phrases (no capture where one is the only signal; a captured gemini 429 carries `Too Many
Requests` beside `resource_exhausted` / `model_capacity_exhausted` / `ratelimitexceeded` — observed loss zero; DL-86). The
plain-fragment rule applies to EVERY raw-text phrase list a host reads over a failed run's output — capacity,
subscription cap, token limit, schema-rejected, configuration and authentication words alike: a phrase stays
only with measured evidence (a real vendor failure, a contract row, the vendor's own source), cited beside it; a review
leg quoting a host's code never reaches a STOP or a retry through a generic phrase. Every phrase is per-CLI (a sentence
applies only to the CLI that emits it); no shared list keeps a phrase unless it is measured on every CLI it applies to —
none today. No raw-text authentication phrase is kept: one matched over a failed run's whole output produced a MEASURED
false STOP (a codex run of 2026-07-16 that failed on "Selected model is at capacity" was recorded oauth-env because a
fetched page in its transcript quoted "401 Unauthorized"); the authentication STOPs come from the structured carriers
only, and an authentication failure printed outside every carrier ends `unknown` (never retried). A classifier extension cannot add a raw-text authentication phrase: such an entry is ignored with one log line, and A's patch applier refuses every proposal whose class is `oauth-env` — an authentication phrase, an agy banner phrase or an exit-code entry alike; entries already in an extension are read as before (A has no raw-text authentication list at all — `OAUTH_ENV_PATTERNS` removed @ triad `c048340`; the refusal @ triad `cfaa45ec`).
On A an applied proposal is verified without calling the vendor again: deterministic code
(`_common.reclassify_run_record`, run by `apply_patch.py --verify-run-log`, which reads and checks the record before
the apply and classifies it again after it) classifies the failed run's stored record a second time from the input the
wrapper built for that run — for a run that failed with a nonzero vendor exit or a wrapper timeout, its stderr, stdout,
wrapper exit and vendor exit; for a non-agy run whose answer extraction failed at vendor exit 0, the extraction error
in place of stderr, an empty stdout and the vendor exit (after the authentication-carrier check on its stored streams);
for an agy run that returned no answer, the no-answer input rebuilt from the stored stream (its stderr, the stream's
typed signals and the terminal status) — and the proposal holds only when that record now classifies as the proposed
token and did not before the apply (`apply_patch.py` exit 4 otherwise, the entry staying applied; the three `verify:` /
`evidence:` / `sentence:` lines are printed after every verified apply). A record the input cannot be rebuilt from — a
class decided outside the classifier, no stored vendor exit, an agy record an earlier rung decided — or a run-log that
is missing, empty, unreadable or of another CLI is refused before the apply, exit 3, nothing applied. The record keeps
every field this input needs, in full; a promoted row's evidence is the applied proposal (the match phrase, the
record's path and time, the vendor version) and the vendor sentence the analyzer quoted from that record, written
before the record's age floor removes it; the wrappers' `--repair-mode` re-run is gone (triad `1e979d60` + `35dc7de8`,
PR #13 C76). On A only a verified pattern-list proposal is promoted to a row (the repair procedure § 5e, triad
`7210ad61`): the contract has no column for a vendor exit code, so an applied `vendor_exit_map` entry stays in the
host's classifier extension (a fact for both hosts). A promoted row's cli is the contract's name (`agy` for A's
`antigravity` wrapper), and a phrase verified on the extraction path carries the carrier "the extraction reason of a
run at vendor exit 0". Tests: `tests/unit/wrappers/t76-reclassify-run-record.sh` @ triad `e9960053`. (PR #13 C76) On A
the three read-only repair analyzers are one body rendered to three names, with the tools `Read, Grep, Glob, WebSearch,
WebFetch` and no write, edit, shell or sub-agent tool; the two web tools serve only the bounded research rule
(D-REPAIR-WEB-20261009, recorded on PR #13) (`.claude/agents/{codex,gemini,agy}-wrapper-repair.md`,
`3rd-Agent/export_assets/distributed-repair-agent.md.tmpl`, triad `7dbba148` + `2118f7ff`;
`tests/unit/wrappers/t33-repair-agent-readonly-lint.sh` @ triad `e9960053`; DL-147).
On A codex's write posture (`--sandbox workspace-write`) requires `--cwd` — exit 3, nothing spawned — as A's gemini wrapper already requires (@ triad `c048340`); the codex `--task` mode and its exits 68 / 69 are gone from A (@ triad `11662b2`). codex's own
`you've hit your usage limit` (codex-rs `UsageLimitReachedError`) is its subscription-cap sentence (On A
`CLI_PATTERNS` @ triad `7e9e1fb`). On A (`3rd-Agent/wrappers/_common.py`
@ triad `3fde8d6`) the kept phrases include codex's own `exceeded retry limit, last status: 429` (vendor source:
`codex-rs/protocol/src/error.rs` RetryLimitReachedError, "exceeded retry limit, last status: {}{}", fetched 2026-10-05)
and codex's `invalid schema for response_format` (two real failures, 2026-09-20); the token-limit and
configuration lists hold no measured sentence and are empty, so those failures end `unknown` and reach the repair
analysis; `aborterror` is gone (its one capture is a user abort). An extension token outside the contract vocabulary — and, for an exit-code entry, outside the classes an exit-code proposal may carry — is
ignored with one log line, never emitted (the emitted pair always matches the contract's code) (R-TOKENS; On A `_load_classifier_extension` @ triad `d966ab0`, the file parsed on each load; B returns any extension string, DL-97).
(PR #13 C77) On A a hand-edited `vendor_exit_map` keeps only a string class of `VENDOR_EXIT_PROPOSAL_CLASSES` and no
key whose integer value is 0 or below — the rest is dropped, an unsupported class or a non-positive code with one log
line (`3rd-Agent/wrappers/_common.py:990-1010`, triad `9a440ebf`; `tests/unit/wrappers/t21-classifier-extension.sh`
axes 10, 12, 14, 17 and `tests/unit/wrappers/t32-apply-classifier-patch.sh` @ triad `e9960053`); a key that is not an
integer spelling is kept and never matches a vendor exit (a recorded fact). A residual: a `401` outside the carrier,
on a failed run that also carries a measured capacity token, classifies `server-capacity` and is retried, since capacity
precedes oauth-env (not observed). Three guarantees replace per-shape code. A usable answer is never discarded because of
text inside it: on A the codex `-o` last-message file is the answer, read before the JSONL events (`_common.py`
@ triad `d966ab0`; B has no codex wrapper; a constructed `agent_message` whose text is null or empty ends `ok` with an
empty answer, and one of another type ends through the wrapper guard — recorded limits); a non-null claude `structured_output` is the answer beside `is_error` on B's claude CLI route, which returns
`structured_output` before reading `is_error` (`bin/_common.py:1256-1260` @ `7f75863`); claude's measured authentication
result lines ("Not logged in · Please run /login", "Invalid API key · Fix external API key") are rows of
`contracts/vendor-failure-lines.json`; host A has no claude CLI route (DL-110). The
auth-carrier rung runs before every other rung. Classification never raises: an exception in a classifier, an extractor or the auth-carrier rung
ends `unknown`, exit 1, with the summary line, the audit row and the run-log written (On A one guard, `_common.py`
`_guarded_main`, around each wrapper's whole `main` — probes, the run, extraction, payload building, classification —
letting SystemExit / KeyboardInterrupt pass, @ triad `c8907314`; DL-90, DL-137; recorded limits: such an exception
raised inside the dispatch, before the wrapper holds the run's result, records a not-started receipt — empty stdout /
stderr and vendor exit `None` — so the repair analyzer an `unknown` routes to has no vendor evidence; an exception after
the run's result is held but before the records ends `extraction-error` after a vendor exit 0, else `unknown`, exit 1,
with the three records — no measured shape raises there — and one after the records is one guard line and exit 1, the
records keeping their verdict, DL-98); no raw-text authentication rung follows, so a measured codex 401 the raising
rung did not read ends `unknown`, exit 1, never retried (On A t74 G5 @ triad `c8907314`).

<a id="R-RECEIPT"></a>
The transport receipt and audit / run-log records carry the common transport object defined by
`contracts/receipt-fields.json`: stdin delivery class, execution route, binary, observed CLI version and attempt.
Existing host envelopes remain. Schema validation alone does not prove host implementation or observed runtime identity.
Historical A driver behavior before the R-TERMINAL/C78 replacement: when a later agy driver turn (a capacity retry or a schema-repair re-run) fails to spawn, the audit `cmd` is the argv of
the last turn that spawned, the receipt describes that same last spawned turn (its binary and its delivery; 6.0 —
earlier the unspawned turn's pre-spawn shape), and the unspawned turn adds no attempt to the read audit
(`3rd-Agent/wrappers/antigravity_wrapper.py:683-713`; `build_transport`, `3rd-Agent/wrappers/_common.py:1347` @ triad
`e9960053`; the soft-deny re-run is removed @ triad `e34edcb4`, DL-140). B has no driver re-run
turn (a fact).

<a id="R-BIND"></a>
Every leg's result binds `review_id`, `family` and `content_digest` today on both hosts; a mismatch is an INVALID leg, never
a pass. v2 ADDS (round r2, all three families; lands with the D-3 wire — `contracts/leg-verdict-mapping.md`): `leg_name` (the
roster entry), `attempt` (integer ≥ 1, per leg), `route` (the resolved Google route `agy` | `gemini`; null for a family with
one route). The common v2 prompt pins use these fields. Each host adopts its validator, all shaped clauses and collectors together;
explicit legacy entry points retain their old contract and cannot admit v2 results. On A no legacy entry point remains:
the small review path and the v1 round are removed (triad `32124be5`, `12b1dd6f`; DL-128).
A recorded attempt is sealed: the result and every evidence file its route records for the attempt (read evidence; a
transport receipt where the route records one there) are written once and bound by digest when recorded, and collection
refuses a later change, removal or replacement of any of them. A native leg seals what it records; DL-18 adds no
transport receipt or receipt check to A's native spawn. On A: the native claude leg records its verbatim raw reply and
its admitted result (`lib/review_scratch.py:5206-5224` @ `90417ce`). On B: the native leg's host receipt is built and sealed like any
route's (`bin/review_round_v2.py:474-486`, `:388-395`). A new answer from the same entry needs a new attempt, which
R-RETRY allows only after a failure to run, or a new round (R-REREVIEW). A saved reply is recorded (admitted and sealed)
before any retry of its entry and before any agreement: a reply the host has not yet recorded blocks both until it is.
On B: `record_attempt` writes result, read
evidence and receipt with exclusive create and seals `terminal.json` with their digests (`bin/review_round_v2.py:378-397`,
`bin/review_round.py:2308-2317`), and `collect` re-checks those digests (`bin/review_round_v2.py:365-375`).

On A (triad `e24a82f2` and `bb933c6b`, cited @ `e9960053`): a seal (`seal.json` beside the attempt) records one
state — `valid` (an admitted answer), `invalid` (an answer that could not be admitted) or `failed-to-run` (no answer)
— and the digests of the files the round's frozen entry derives for it: the result, the receipt (the native leg's raw
reply; a wrapper leg's stderr), the read evidence (agy) and, on a wrapper route, the run-log directory that holds the
executed-command receipt (digested over its `*.json` run-logs; `_sealed_paths`, `lib/collect_v2.py:709-727`,
`_bound_digest`, `:755`). The native admission seals only a reply it admits: once `--admitted-out` is in place it
creates a `valid` seal exclusively, binding the admitted object and the raw reply it judged (`_write_admission_seal`,
`lib/verdict_v2.py:598-633`, called at `:839-841`); a seal that cannot be written after an admitted reply is a host
fault (exit 64, "re-run this same admission"). A reply the admission refuses is not sealed: the admission prints the
reason and exits with its own code (`main`, `:831-835`), collection reports the attempt not admitted with its retry
open, and `retry` seals it `invalid` over the `raw.json` it judged when it replaces the attempt — host B's single valid
seal (DL-135). The admission takes the six expected bindings from the attempt's own `binding.json`; a typed flag that
disagrees is an argument error (exit 64) and seals nothing (`_attempt_binding`, `:740`). A `raw.json` that is not a
readable regular file is never judged: the admission refuses it as a reply, the entry is INVALID and its retry stays
open. A wrapper attempt is sealed by the first collection that judges it, over the digests that collection took once
before judging (`_evaluate_unsealed`, `lib/collect_v2.py:1253`). An unsealed `admitted.json` is judged as found; it is
not re-derived from the `raw.json` beside it. A native reply saved and never admitted blocks agreement and retry until
its printed `admit:` line runs, in ANY attempt of the entry: a regular, readable `raw.json` the admission would admit
against the round's own expected bindings, with no seal and no `admitted.json` (`_raw_admissible`, `:876`;
`_saved_not_admitted`, `:889`; `_history_reason`, `:996`; `_retry_blocked`, `:1156`); no printed remedy asks for a hand
removal (Z2; R-CLEANUP: only host code deletes). `retry` RECORDS the attempt it replaces before it allocates the next:
it takes that attempt's digests once, judges those same bytes, and seals it `invalid` when an answer is there — a
result it judged inadmissible, or, on the native route, a saved `raw.json` (Z4) — and `failed-to-run` when none is; an
attempt whose digests cannot be taken (an unreadable file) refuses the retry with nothing allocated: prepare a new round
(`retry`, `lib/collect_v2.py:1616-1755`; `_seal_replaced`, `:812`). On B an attempt's sealed `allocation.json` that does not match its basis is refused (`bin/review_round_v2.py:256-263` @ `7f75863`) and a retry is allowed only after a diagnosed failed-to-run attempt (`:274`). Each attempt's custody is digested once per
collection or retry: a write that lands after that digest is not seen by that step, and the next collection's seal
check reports it (R-AGREE, D-LATE-ANSWER-20261004). `collect-r<N>.json` keeps each seal's digest, and every collection
re-checks every sealed attempt of the entry — the earlier ones included — so a later change, removal or replacement of
a sealed file or seal is an integrity failure (INCOMPLETE, never AGREED). The printed wrapper line runs a seal guard
under `noclobber`, and the native spawn gets a printed `guard:` line (`lib/review_scratch.py:2906-2936` @ triad
`e9960053`).

Known limits, recorded as facts. Both hosts (owner, 2026-10-03,
[D-PRE-RECORD-REPLY-20261003](../decisions/owner-register.md#D-PRE-RECORD-REPLY-20261003)): a saved reply replaced before
any host write about it has landed — a stop before the host's first record, or that first write itself failing (on A the
admission's seal create, on B the exclusive create of `record_attempt`) — is undetectable by construction, since no host
record of the first bytes exists; the chain also needs the leader to ignore the fault, skip the printed guard and save
over the existing file. On A, each a deliberate tampering with the host's own files (owner decision
[D-C66-LIMITS-20261003](../decisions/owner-register.md#D-C66-LIMITS-20261003), codex's tampering chains, and the
leader's ruling under [R-THREAT](#R-THREAT)): (1) after an unusable attempt directory is collected, removing that
directory and the original seal and replacing a blocking result can reach AGREED in the same round; (4) a native seal's
state field can be edited before the first collection; (5) a hand-edited `binding.json` makes `collect` and `retry`
name the `admit:` line while that line refuses the reply, so the round never reaches AGREED and no message names a new
round. On A, recorded limits of the single valid seal (DL-135; constructed shapes, no code): a second reply saved over
a refused, unsealed one can be admitted into that attempt; an unsealed `admitted.json` is not re-derived from its
`raw.json`; a hand-written `admitted.json` beside a saved reply is judged as found. On A, ordinary failures with a safe
outcome: (3) a seal write that fails at collection records nothing — that entry is INCOMPLETE and the next collection
judges and seals the same bytes; no evidence size cap remains on A, as on B (the 64 MiB cap of four readers is removed @
triad `e24a82f2`, DL-135); a run-log that cannot be written (a full disk) is one stderr line: the answer is still published with its
exit code unchanged, and the attempt carries no receipt, so it is INVALID at collection with its retry open (R-TERMINAL;
`_dispatch_record`, `3rd-Agent/wrappers/_common.py:4441-4457` @ triad e0b15f1;
tests/unit/wrappers/t74-record-seam-a4-c1.sh A4).

Which attempt collection evaluates (a fact): On B the last sealed allocation, refusing a history whose earlier
attempt is not FAILED_TO_RUN (`bin/review_round_v2.py:507-518`); On A the attempt the round record's `attempt` field
names, only behind earlier attempts that `retry` sealed and diagnosed, whose sealed files are unchanged and that are not
sealed valid (`_history_reason`, `lib/collect_v2.py:992-1041` @ triad `ee011968`), and `retry` refuses a valid-sealed attempt,
a saved reply never admitted and a history that can never be collected before allocating (`_retry_blocked`, `lib/collect_v2.py:1152-1246`, called by `retry`, `:1612`).
A retryable attempt differs by host (a fact, DL-55): On A an attempt sealed invalid (an answer that could not be
admitted) is retryable while its sealed files are unchanged, and one whose sealed files changed is an integrity failure
(prepare a new round; `_seal_reason` in `_retry_blocked`, `:1228-1230`); On B a completed invalid answer is INVALID, not failed-to-run, and is
refused for retry (`bin/review_round_v2.py:345-349`, `:274-275`).

The executed command is checked against the recorded dispatch at collection, on both hosts: the wrapper records the
command it actually executed (its argv, `wrapper_cmd`) in a run-log in the attempt's own log namespace, on success too;
an answer with no such receipt, or whose executed command differs from the attempt's recorded dispatch, never counts. An
edited dispatch line is caught there by that executed-command receipt (owner,
[D-OWNER-ANSWERS-20261008](../decisions/owner-register.md#D-OWNER-ANSWERS-20261008) item 6). A host may in addition
refuse a line whose review markers disagree with the bound metadata before the vendor runs (On B, below); host A has no
such pre-spawn check: its pre-spawn review-argv digest (`TRIAD_REVIEW_ARGV_SHA256` in the dispatch env,
`lib/roster_v2.py:1003-1004`, checked by `_review_argv_refusal`, `3rd-Agent/wrappers/_common.py:5148-5174`, called at
`codex_wrapper.py:194`, `antigravity_wrapper.py:2333`, `gemini_wrapper.py:443` @ triad `e0b15f1`) is removed (DL-111).
On A (@ triad `ee011968`): the dispatch env carries `TRIAD_REVIEW_LOG_DIR=<attempt>/logs`; with the log dir set the wrapper
writes its run-log there on success and failure alike (`emit_run_log`, `_common.py:3885-3990`); `collect` makes an unsealed or invalid-sealed
wrapper attempt INVALID when no run-log is there or any run-log's `wrapper_cmd` differs from `dispatch.json`'s argv
(`_receipt_reason`, `lib/collect_v2.py:1277-1316`, called at `:1365`), and the run-log directory is a sealed file
(above). An attempt whose line never ran, or was refused before the spawn, leaves no or an empty result file and is
MISSING (`:1327-1337`). On B (@ `7f75863`): before the vendor runs, `bound_wrapper` refuses a v2 review without the
configured per-attempt log dir or any of the six expected bindings (`bin/verdict_v2.py:67-74`; called at argument
parsing: agy `bin/antigravity_wrapper.py:495-502`, gemini `bin/gemini_wrapper.py:348-352`, claude
`bin/claude_wrapper.py:340-344`), and `validate_review_web` refuses a `--web` that differs from the bound
`review_web_authorized` and a binding mismatch with the bound metadata (`bin/_common.py:577-600`; agy `:554`, gemini
`:411`, claude `:392`; the vendor runs later: agy `:736`, gemini `:501`, claude `:450`); the v2 dispatch runs with
`TRIAD_DISPATCH_LOG_DIR` = the attempt's `logs` (`bin/review_round_v2.py:234-236`), the wrapper writes the run-log on
success too for a review binding (`bin/_common.py:2903-2904`), and `record_cli_attempt` refuses unless the named run-log
lies under the attempt's own `logs/<cli>/runs` and its `wrapper_cmd` equals the allocated argv
(`bin/review_round_v2.py:427-438`), which covers the rest of the argv. Known limit, both hosts (owner, 2026-10-03,
[D-ENV-DROPPED-LINE-20261003](../decisions/owner-register.md#D-ENV-DROPPED-LINE-20261003)): a printed wrapper line with
every review marker removed (on A the log-dir env value) runs as an ordinary call — no construction can refuse before
inference a command that carries no review marker — and is caught at collection, never agreement. The native claude
spawn on A has no receipt (DL-18): the subagent it was spawned as is not checked (a fact).
Duplicate JSON members are rejected at the original-text boundary before extraction or normalization can discard evidence
(On A: the wrapper schema path, `3rd-Agent/wrappers/_common.py:197-234` `_reject_duplicate_pairs`; the v2 admission
of every route's result, `lib/verdict_v2.py:277-311` `_reject_duplicate` / `_parse_strict` @ triad `e9960053`; the
raw-reply admission `lib/validate_verdict.py` is removed @ triad `12b1dd6f`, DL-128. On B: its review
wrapper/result paths including explicit v2, `bin/validate_v2.py:34`; see C14/C30).

## Preparation, verification, cleanup (lifecycle obligations)

<a id="R-PREPARE"></a>
Required bound packet inputs must be readable through the selected leg's permitted
file-read tools in its actual launch context. An absolute path in a prompt does
not establish that availability. Keep related worktree discovery available (C70);
granting packet access does not grant access to sibling receipts, logs or results.
An unreadable necessary input remains a coverage gap/open question, including
when the provider exits successfully; do not bypass denied tools or represent a
valid negative verdict as completed coverage (C79).

On A, the current v2 packet files are co-located with the review worktree. On B,
formal v2 guarded-worktree keeps the prepared `shared` packet outside the product
cwd. B derives Gemini's `--review-packet-dir` from that round's exact canonical
`prepared_dir`, binds it through the existing adapter/preflight receipt and
allocation, and passes only that directory as native `--include-directories`.
The existing preflight digest binds the prompt; the six reviewer-result binding
values are unchanged. An absent, noncanonical, symlinked, comma-containing,
wrong-round or broader directory is refused before provider start. Raw
`--add-dir` remains unavailable to formal review. B prepared-directory mode and
other routes keep their existing launch controls. This is packet availability
guidance under the existing read-only policy, not a new per-file allowlist or
routine read audit.

`prepare` pins the reviewed basis (commit + content digest), writes the brief, the gated patch and the test patch as separate files (separation is PRESENTATION: relevant tests, policy and prompt text inside the agreed scope stay visible, bound and reviewed; host packet file names are mapped in `units.json`), the history, and the per-round containment artefacts the host uses (A: the agy PreToolUse hook); resolves
the roster from the registry with the recommended defaults; prints one COMPLETE dispatch line per enabled leg, run as
printed (its executed command is checked against the recorded dispatch, R-BIND); captures the
round snapshot. It refuses on a malformed registry entry and never launches a provider itself. A change to a rule,
schema, prompt clause or policy file is behavioral review scope even when the file contains only text; the docs-never-gate
rule covers narrative documentation only. Symlinks (owner Q4, RULED 2026-09-19: "링크 자체는 검토하되, 대상을 자동으로 따라가지 않는 방식"): the LINK ITSELF is review material — its path, kind and exact link text are fingerprinted and available to reviewers; its TARGET is never followed automatically. Target content enters a review only as an independently authorized, bound input; a link the review cannot follow is disclosed as a coverage gap, never claimed inspected; cleanup never follows a link to delete its target. Each host implements "never followed" its own way and records the evidence (B: link-text fingerprint — its guarded worktree folds an untracked link by its text, `bin/review_round.py:1594-1597` — and a symlink refusal in the prepared copy, `:1441-1444` @ `7f75863`). On A: the reviewed patch is always committed content — a range without `..` still reviews `<commit>..HEAD` (`lib/review_scratch.py:4060-4066` @ `ce30d82`), and `_require_clean_scope` refuses in-scope modified tracked files (`:4112-4130`) — so the bound v2 `brief.md` DISCLOSES the basis's links rather than adding them to the patch: every committed link (kind `symlink`, path and exact link text from the commit's tree and blob objects) and, on a working-tree range, each untracked nonignored link of the source checkout (kind `untracked link`, text read with `readlink` of the link itself). On A (triad `92b7fee`) the brief lists every link with its path, kind and exact text, and one sentence discloses any target not read in the tree as a coverage gap; no target is opened. An untracked-file listing that warns it could not read a directory (git skips it with exit 0) is refused, never taken as complete (DL-84; on A every untracked listing refuses git's "could not open directory" warning — the brief's links, the round fingerprint and the precheck — `lib/review_scratch.py:2232-2252` `_git_untracked`, called at `:2412`, `:4193`, `:4955` @ triad `99aaebc`). An untracked nonignored source link is listed beside the committed links (`_tree_symlinks` / `_render_links`, `lib/review_scratch.py:2713-2767`; `tests/unit/skills/t24-symlink-c26.sh` @ triad `92b7feeb`; DL-53). The one refusal that stays on A is the round-copy guard: a link found where the round copy is captured or verified is refused (`:2194-2195`, `:3970-3971`), as B refuses links in its prepared copy. Mechanism per host, principle = shared rule.

The **bound basis** of a round is every input its review depends on: the reviewed bytes and packet; the review
conditions (`review_kind`, `review_web_authorized`, the round date `<review-date>`, and the leader's prompt inputs —
objective, criteria, boundary, `prior_residual`); the selected entries and every entry's resolved controls, from
whatever source the host resolves them (R-ROSTER); and the installed prompt clauses, producer schema and admission
contract. The content digest every leg result carries (R-BIND) covers the reviewed bytes, the review conditions, the
selection and the controls. An input a host produces only after that digest, because the rendered prompts embed the
digest, is recorded with the round at prepare (a mutable round record suffices), and before a retry or a
collection the host re-derives it from the installed files and compares it with the recorded value; a host may instead
hash the installed source files into the digest. No host re-enters an attempt that exists on disk but that the round
record does not yet name (left by an interrupted retry): both refuse it, and the leader prepares a new round (On A
`_retry_blocked`, `lib/collect_v2.py:1156` @ triad `e9960053`, since `207dd39f`; On B `bin/review_round_v2.py:291-294`
@ `7f75863`; DL-130). Retry and
collection read the digest-covered members from the bound bytes, never from a mutable copy. A changed member is a
changed basis: R-RETRY refuses a changed condition, selection or control before an attempt is allocated, the round (verify, then
collect) does not agree on any changed member, and the leader prepares a new round (R-REREVIEW). A host change that alters the bound
basis makes rounds prepared before it non-retryable; prepare a new round.

R-PREPARE fixes basis freezing and the round snapshot, not the folder layout. Layout, per host: On B each round is
prepared in a fresh review root: its own managed review workspace `triad-review-<review_id>`, created new
(`prepare_review_workspace`, `bin/review_round.py:1034`, `:1063`; `create_basis` requires it,
`bin/review_round_v2.py:139-141` @ `7f75863`). On A the target is the same (owner,
[D-OWNER-ANSWERS-20261008B](../decisions/owner-register.md#D-OWNER-ANSWERS-20261008B) item 8): each round in a fresh
review root, no packet dir shared by the rounds of a gate and no worktree re-pinned from round to round. On A (triad
`6878cc4a`): `prepare` refuses a packet dir that already holds a round tree or a captured snapshot, before anything is
created (`lib/review_scratch.py` `cmd_prepare`); the leader opens a new packet dir per round.

- On A: `review_scratch.py prepare --v2` writes the `Review metadata:` line of `delivery-r<N>.md`, whose sha256 is the
  content digest (`lib/review_scratch.py:5823-5848`). It carries `review_kind`, `review_web_policy` (the rendered
  web sentence; since `b53409b` the strict boolean `review_web_authorized` and `review_date` instead,
  `lib/review_scratch.py:5896-5899` @ `b53409b`), `selected_entries` and `roster_config_digest`
  (`_v2_config_digest`, `:5263`: every round-record entry field except `attempt`, plus `gate_files`, `hook_log` and
  `results_dir`); the brief and residual are inside the hashed packet. `collect_v2._bound_metadata`
  (`lib/collect_v2.py:442-512`) re-hashes the delivery record and compares the record with the bound line in
  `collect` and `retry`. A later edit of the project roster file does not affect a prepared round. On A (triad `80b302e7`, `c50b1c8b`) `prepare` records a map of the installed toolkit files —
  every file directly under `lib/`, the vendored `spec/` and the six shipped reviewer presets — with each file's sha256 in `.roster-r<N>.json`,
  and `collect` and `retry` compare it with the installed files before anything is judged or allocated, naming every
  changed file (the recorded-and-compared option above: the map lives in the mutable round record, outside the content
  digest). A retry checks the whole round's basis: a changed member of any
  dispatched entry (the claude preset while codex is retried, say) refuses the retry, since that member could never
  agree and a paid retry on it is refused rather than spent (R-RETRY). A round prepared before triad `80b302e7` carries no
  toolkit map and can no longer be retried or collected ("this round was prepared before the host recorded its toolkit
  map — prepare a new round"). The
  round date is bound since `b53409b` (above).
- On B: `bin/review_round_v2.py` `create_basis` seals `basis-v2.json` (the request with `review_kind`,
  `review_web_authorized` and `prior_residual`; the resolved roster; adapters with launch controls and receipt digests;
  the round snapshot; packet files; `_toolkit`, the sha256 of every file under `bin/`, `contracts/`, `prompts/` and the
  skill except `__pycache__` directories, `.pyc` / `.pyo` files and `bin/_logs`, `bin/_debug`) with a `.sha256` sidecar
  and `content_digest` over the rest (`bin/review_round_v2.py:61-71`, `:127-176`). `_load_basis` (`:107-124`), run by
  allocate, record and collect, re-checks the seal and digest, runs `verify_round`, and refuses a changed toolkit, a
  re-resolved roster that differs from the bound one, or changed adapter receipts. The UTC preparation date is recorded
  as `review_date` in the digest-covered basis and reused when rendering retries (`bin/review_round_v2.py:170-177`,
  `:198-206` @ B `e3a35a3`; DL-46; `decisions/2026-10-10-b-shared-review-context.md`).

<a id="R-THREAT"></a>
This rule scopes reviews of a TRIAD dispatch host's own code (the review and dispatch toolkit itself); for any other
reviewed target, the target's deployment context is what the leader states in the brief (R-CONTEXT). Both hosts serve
one operator, and there is no malicious actor (owner,
[D-THREAT-MODEL-20261003](../decisions/owner-register.md#D-THREAT-MODEL-20261003)). Concurrency has two levels (owner
fact, [D-CONCURRENCY-FACT-20261008](../decisions/owner-register.md#D-CONCURRENCY-FACT-20261008)). Inside ONE working
folder no second operation runs while one runs: no second install, update, uninstall or review session works on that
folder's packet directories, worktrees or round records meanwhile; concurrency INSIDE one operation, such as two legs of
one round, is real and stays covered. Operations started from DIFFERENT working folders, and the claude-host and
codex-host toolkits, DO run at the same time on one machine and meet at MACHINE-LEVEL state: the CLIs' own settings and
configuration (for example the agy settings file with its `.agybak`, lock and lease files, the agy agents directory,
`~/.codex/config.toml`), a classifier extension file, the logs inside one installed toolkit that several projects use.
Guards defend against ordinary failures: a full disk, a stop at any point (a crash, or a session that hits its token or
usage limit), a wrong argument or another ordinary operator action, an operation from another folder or the other host
meeting the same machine-level state, a bad vendor answer that a run has shown (a MEASURED shape: a capture, a row of
`contracts/vendor-failure-lines.json`, the vendor's own source — a shape no run has shown is a recorded limit under
R-CLASSIFY "Recorded limits", owner 2026-10-05,
[D-MEASURED-SHAPES-20261005](../decisions/owner-register.md#D-MEASURED-SHAPES-20261005); DL-93), an odd layout of files
the leader creates by hand, a reviewer's or the leader's mistake (owner, 2026-10-03, D-THREAT-MODEL-20261003). A guard on
machine-level shared state is in scope. A finding whose trigger needs deliberate tampering with the host's own files, or
a second operation inside one working folder, is recorded as a fact — no code and no blocking; the C66 limits (1) and (4)
under R-BIND are worked examples. A limit an ordinary failure can reach that no construction closes on either host is
recorded as a fact in the rule it limits, without an owner question
([R-DECISION-ORDER](spec-authoring.md#R-DECISION-ORDER)); where the owner decided one, that rule cites the decision
(R-BIND, R-AGREE). How facts recorded under earlier wording were triaged is in `authoring/shared-dev-log.md` DL-59 and
DL-60; the judgements that rested on "no concurrent operation" for machine-level state were re-checked against
D-CONCURRENCY-FACT-20261008 (DL-107, DL-108, DL-109, DL-112). Every leg receives this context, with this rule,
D-THREAT-MODEL-20261003 and D-CONCURRENCY-FACT-20261008 as its evidence pointer, through the shared
`deployment-context` clause, which applies it only when the reviewed code is a TRIAD host's own and has the leg label
such a finding HARDENING-SUGGESTION (non-blocking under R-AGREE); the leader records it as a SPECULATIVE fact (R-VERIFY).

<a id="R-VERIFY"></a>
The leader checks each claim against the current reviewed bytes, required behavior, concrete trigger and impact before
acting. Preserve the original finding and evidence for each disposition: verified blocking defect → smallest adequate
fix and full re-review (R-REREVIEW); verified non-blocking issue → record, with correction at the maintainer's option;
refuted claim → record the specific counterevidence and its limits; design/scope change → R-STOP; a finding outside the
deployment context → a recorded fact under R-THREAT; speculation → residual, not speculative code. A fix changes the basis. Verify the proposed repair too: a reviewer's label or suggested design is
a claim, not an instruction, and a vote is not evidence. Leader triage cannot rewrite approval under R-AGREE.

For prompt development in the current shared spec-to-code effort, apply
[D-PROMPT-REVIEW-BOUNDED-20261009](../decisions/owner-register.md#D-PROMPT-REVIEW-BOUNDED-20261009):
two to three passes focus on substantial defects and observed behavior; repeated
wording disputes are decided by fresh scenario/control choices. Correct choices
end wording iteration; do not add phrase-pinning tests as a substitute for behavior
evidence. The owner reviews wording later. Actual unresolved functional defects
still require correction or escalation. Preserve original review verdicts and
record an explicit owner disposition separately; this changes no collector enum
or unanimous-approval calculation.

<a id="R-CLEANUP"></a>
Cleanup exports and verifies the round's evidence first, then releases only resources the helper can PROVE it allocated or claimed (its own allocation record or marker — never a name shape; an empty directory or a plausible-looking marker can still be foreign); uncertain residue is preserved and reported; it refuses without deleting, states what it observes, and points at the host's deletion command when a tree is not its own. A second cleanup is a no-op.
Only host code deletes ([D-DELETION-BY-CODE-20261004](../decisions/owner-register.md#D-DELETION-BY-CODE-20261004)).
Every folder a host's code may delete is declared in one JSON configuration file (shape:
`contracts/cleanup-roots.schema.json`; illustration: `contracts/cleanup-roots.example.json`); each entry carries a role,
a root, the ownership proof this rule already requires and the host's age floor for that role. A root is one folder and
covers its whole subtree (no glob, no `..` component): repository-relative (resolved against the git top-level of the working directory),
or beginning with `$TMPDIR`, `~` or `$HOST_DIR` (the directory that holds the host's own deletion command, for folders a
host keeps beside its installed code, such as its wrapper logs). A `marker:<name>` proof is a regular file of that name
directly in the folder to delete; `alloc-record` and `inside-owned-packet` are proved only inside the host's own sweep,
so the deletion command refuses them. On A, for a host-managed log folder, `inside-owned-packet` means a root the host's own
code creates beside its deletion command (`$HOST_DIR/…`) or inside its own packet and that no other program writes;
membership is a regular file (never a link) directly in the folder the sweep names inside that root, older than the
floor; no per-file record exists or is required (On A `cleanup-roots.default.json` role `wrapper-run-logs` →
`$HOST_DIR/_logs`; `_common._swept` `:3118` proves the root — the declared role, its proof label, the swept folder
inside the root, no symbolic link on the way, the floor — and `_prune_dir_by_caps` `:3991` proves membership per entry,
`lstat` never followed, a link refused, an unreadable entry left in place; triad `e9960053`). (PR #13 C4 (iv)) On A
every wrapper sweep acts only under a role root the host's own configuration declares — `wrapper-run-logs`,
`wrapper-audit-archives` and `dispatch-prompts` (proof `inside-owned-packet`) and `wrapper-debug` (proof
`alloc-record`) — through `_common._swept` (`3rd-Agent/wrappers/_common.py:3372`, `:4129`, `:4269`, `:4424`,
`:4441`, `:4627`); the review-scratch sweep (`review_scratch._prune_stale` `:463` → `_scratch_role` `:344`, role
`review-scratch`, `marker:.active`) and the test-runs prune (`tests/lib/prune_runs.sh:68-73`, `cleanup.py remove
test-runs`, role `test-runs`, `marker:.triad-run`, declared in the lab's `.claude/triad-cleanup.json:9`) act under their
own declared roles — and A has no sweep of a shared temporary directory by name prefix and age
(`tests/unit/wrappers/t73-prune-roles-c69.sh` @ triad `e9960053`). The age floor binds the sweep and the deletion command alike, and the age is read
from the proof itself (a marker's own modification time), never from the folder a deletion is emptying. Removing an empty folder that carries no proof marker never completes or removes a git registration below it (On A restored @ triad `3fde8d6`; B requires its allocation and a verified export, `bin/review_round.py:1338-1341` @ `7f75863`). A deletion keeps its
proof until last, so a deletion stopped part-way resumes from the same proof; a linked worktree inside the folder is first
removed through the repository that owns it — a worktree is emptied (its `.git` entry kept) before it is detached, because git
drops a worktree's registration even when removing its tree fails — and a folder holding one that cannot be detached, any
other `.git` entry, or a path the root's repository still registers that no `.git` entry inside the folder names, is
refused — except git's own failed-remove states, which are completed: a folder holding only a `.git` file whose
registration is gone or no longer valid, and a registered path that is missing or empty, whose ONE registration is then
removed (never a repository-wide prune); a git-registered worktree's age is its registration's age. An EMPTY folder left
inside a marker role's root, older than the floor and not inside a folder that carries ANY declared role's marker, is removed with rmdir: it
holds nothing to lose; roles whose proof only the sweep can check, and roots shared with other programs (a root beginning
with `$TMPDIR` or `~`; a repository-relative or `$HOST_DIR` root is the host's own), get no such
removal. On A the empty folder a stopped `cleanup.py remove code-worktrees` leaves (between its `.git` unlink and its
rmdir) stays: the deletion command refuses it and it is harmless, and a later `git worktree add` of the same name
succeeds (measured on git 2.43.0 and 2.50.1); the codex wrapper's sweep of such folders is removed @ triad `39b19821`
(a recorded limit, DL-139). A coded sweep may run in a folder that stands in for its role's
root for test isolation (on A a log- or debug-directory variable, a review attempt's own log directory); a root a caller
hands a review helper is not a stand-in — it must be the declared root; the role must still be declared and its proof and floor apply, and the deletion command never
reads such a stand-in. A sweep checks one proof — a role that declares another is skipped with a note; a day-granular sweep
rounds the declared seconds up to whole days; an operator setting may raise a floor, never lower it, and a host keeps its
own minimum for a role whose files a live call or a paused round still uses (the cap prune's fresh-sibling floor above; a
review packet's activity) — a declared floor below it is raised to it. A file a call writes at a caller-named path and
clears before writing again is removed only when its content shows the host wrote it. A deletion reads only the root's repository's registrations: an EMPTY folder that ANOTHER repository registers is removed
like any empty folder and leaves that repository a prunable registration (a recorded limit; B uses no linked worktrees).
A link in any component of a deletion path below the project base — the declared root's own components included — is
refused. A folder holding a worktree that git has LOCKED (git's documented guard against pruning), at any depth, is refused by
every deletion — a sweep and the deletion command alike; unlocking it is the operator's own act. When the named folder is itself a
registered worktree (on A the code-worktrees role), a tree holding uncommitted or untracked changes is refused, as git's
own `git worktree remove` without force refuses it — a deleted tracked file (no content lost; what a stopped removal
leaves, so running the command again finishes it) and an ignored entry (as in git's own guard) are not counted, and every untracked file counts whatever the repository's
`status.showUntrackedFiles` says: committing the work to the worktree's own branch keeps it and is the
leader's step; discarding it is the operator's act. A worktree
nested inside a marker role's folder (a review packet's round tree, checked by its own close and partly emptied by a
stopped one) is detached as above. A folder holding a
moved or copied round tree, a clone, or a tree whose `.git` file names no registration is refused by the deletion command
and skipped by the sweep, so it stays: no supported step removes it, and removing it is likewise the operator's own act (a
recorded limit, measured on A with git 2.50.1). The floor also binds the deletion command, so a refused folder younger than
its role's floor is left behind: the work goes on in a new folder and the old one goes past the floor. On A the deletion
command resolves its project from the current directory's repository, so a printed remedy names the repository to run it
from; run elsewhere it refuses with nothing deleted. git's own lock left by a stopped `git worktree add` (its reason "initializing") is refused
like any other; every lock refusal prints the lock's reason. On A the reason is read from the registration's `locked` file (its first
512 bytes on one line), printed as `reason: "<text>"` or `no reason given`; a lock file that cannot be read still refuses.
A nested worktree under a folder the repository ignores is invisible to `git status` and to `git worktree remove`'s clean
check (git checks only the outer tree's lock), so a removal that runs its own `git worktree remove` first checks the whole
tree below its own `.git` for any other `.git` entry and refuses on an unreadable folder (none on A since triad
`6878cc4a`: a packet dir holds one round and only the deletion command removes it). `git worktree add` exits
non-zero when a post-checkout hook fails yet leaves the
worktree and its registration in place, so its exit code alone does not say whether it created one: on A a rollback
claims a registration when its add succeeded or left its tree inside the folder the same call created; an add refused
because the path was already registered created nothing to roll back. An add stopped after it wrote the registration and
before it created the tree leaves a registration no rollback claims (a recorded limit; git marks it prunable). A review close (A: the scratch packet; A's
small review path is removed @ triad `32124be5`, DL-128) finishes an EMPTY folder directly under its declared root. A sweep hands an EMPTY folder directly under its role's root, past the
floor, to the empty-folder rule (A: the scratch sweep). A failed step's rollback
that removes a worktree the same call created is the creating call's own removal: a lock set during that call (a
checkout hook) does not stop it. A stopped deletion that resumes re-checks what remains as a SUBSET of what it
checked before it started (nothing new, nothing foreign), never as the whole set (On B `bin/review_round.py:1342-1361` @
`7f75863`); the host records that it started inside the proof it removes last. A new round is never prepared in a folder whose deletion has started; a partly
written start record reads as not started, so the next run checks the whole set again. A resumed close does not repeat the fresh
round check, which ran before its first deletion; an explicit close of an EMPTY folder directly under
its declared root removes it whatever its age (its proof is gone, so an emptied folder cannot be told from another empty one,
and it holds nothing to lose). On A the start is one line appended to the packet's `.active`; a resumed close judges the subset with `git status` and
the round artifacts' hashes (an entry may be missing; anything new or modified is refused). A deletion removes a symbolic link inside the folder as a link —
never following it, never removing it as a folder, a `.gitignore` that links to a folder included. A deletion that empties a folder removes its
ignore files (any name that case-folds to `.gitignore`, at any depth — on a case-insensitive volume git honours
a committed `.GITIGNORE`, measured on A with APFS and git 2.50.1) last, the deepest first, and within one folder the name `.gitignore`
itself after its case variants (on a case-sensitive volume a variant is an ordinary file the real one may ignore), and
a `.git` entry is any name that matches `.git` ignoring case (on a case-insensitive volume git honours a `.GIT` folder as a
repository; measured on A, APFS, git 2.50.1 — on a case-sensitive volume it does not), the named folder's own proof entry is kept
to the end whatever its case (own only when the listing holds no other name that case-folds to `.git` — a hand hard link
`.GIT` → `.git` is one inode under two names, and the second is "other"), and any OTHER entry so named, anywhere below, is refused on both volume kinds — never
skipped and never emptied, so a stop never shows a file they ignore as new and every resume finishes
(on A both a stopped code-worktree removal and a stopped packet close). A rollback finds its own registration by identity (device
and inode), because git records the real path. The age floor binds a SWEEP; an
explicit close of one named round, or the resumption of a deletion the host already decided, is not held back by it — every
other check still applies (On B `bin/review_round.py:1319` has no age check, its sweep `:1024` does @ `7f75863`). Removing the host itself is outside this rule: after an uninstall no host code is left, so what
the uninstall does not remove (entries in a shared `$TMPDIR`, the plugin cache, a configuration folder named by a relative
`XDG_CONFIG_HOME`; on A also an older install record that names no settings file, which no step can tell from another
settings file's) stays and is the operator's; the procedure says so and never prints a removal command. A helper
deleting inside a project reads that project's configuration (the root's project, not the working directory's). A
wipe-style export
empties an existing target only when it is that role's declared root. Every check runs before any action — containment first, also for a path that no longer exists — and a check that
cannot be made (an unreadable registration list, a git step that fails) refuses or reports the failure, never success (On A
`lib/review_scratch.py:960-1035`, `tests/lib/prune_runs.sh:18-22`; On B
`tests/test_review_cleanup_custody.py:201-217` @ `7f75863`). Deletion code refuses a
target outside a declared root, and inside one it still refuses anything it cannot prove it allocated: the declaration
adds to the proof and never replaces it. An AI — the leader, a sub-agent, skill, agent or prompt text, a printed remedy —
at most chooses a declared role and a folder and runs the host's deletion command; no prompt, skill, agent text, printed
remedy or operator procedure carries its own removal command (`rm`, `rmdir`, `git worktree remove`, an rmtree). A call
that removes what it created itself needs no declaration: an atomic write's temporary file, a failed step's rollback, a
test's own fixture. On A: the deletion command is `3rd-Agent/wrappers/cleanup.py remove <role> <path>`: a refusal
exits 64 with one stderr line and nothing deleted; an action that fails exits 1 with its proof kept. The configuration is
the first configuration file present in its lookup order, ending at the shipped
`3rd-Agent/wrappers/cleanup-roots.default.json`; a present file that is invalid, a link or cannot be probed refuses and
never falls through to a later one (`load_roots` / `_present`, `3rd-Agent/wrappers/cleanup.py:200-250` @ triad
e0b15f1). On B: deletion is coded and no prompt text deletes, but its roots and
floors are not yet declared in the configuration file (DL-77). When the configuration file is missing or invalid, nothing
is deleted: the host's deletion command refuses (a host fault) and the automatic prunes skip with a one-line note; each
host ships a default configuration file so a fresh install still prunes (owner, 2026-10-04, D-DELETION-BY-CODE-20261004).
A wrapper run-log is never removed by an AI after a repair analysis: the host's coded sweep (its age floor and caps)
collects it, and no prompt carries a run-log removal step (owner, 2026-10-04, D-DELETION-BY-CODE-20261004). Cap-based pruning of run-log and repair-IPC
files keeps a minimum age floor so a fresh sibling file is never deleted to satisfy a cap (mtime is not only a sort key). A folder may therefore stay above its cap until its files pass the floor. The stale sweep of the wrapper run-log folder removes a run-log once it is older than the floor, so a repair step that starts later than the floor finds no run-log to read; the floor is host data (a fact): A 86400 s, the `wrapper-run-logs` role's `min_age_s` and never below one day (`prune_stale_run_logs`, `3rd-Agent/wrappers/_common.py:5810-5839`; `3rd-Agent/wrappers/cleanup-roots.default.json:6` @ triad `bf38f60`); B 3600 s (`_STALE_IPC_AGE_FLOOR_S`, `bin/_common.py:3111` @ `7f75863`).
A round that is paused, not abandoned, stays alive: each step that works on it refreshes its activity mark. On A (@
triad `e9960053`): `retry` (through the round-record write, `lib/collect_v2.py:488-494`), `collect` (`:1611`) and the
native admission of an admitted reply (`lib/verdict_v2.py:769-778`, called at `:850`; a refused reply refreshes nothing,
triad `e24a82f2`) refresh the packet's `.active` mtime, refresh-only and best-effort; the stale sweep runs at `open` and
after `close` (`lib/review_scratch.py:583`, `:840`); `close` runs a fresh round check and never refuses on its outcome (R-AGREE).
On B: allocation and record refresh the prepared directory's activity (`bin/review_round_v2.py:305`, `:396`).
Generated environment briefs, condensed residuals and copied verification evidence follow these same existing ownership,
writer-completion, export and cleanup rules. Needed prior evidence is materialized in the current packet under R-CONTEXT,
so cleanup of an eligible previous temporary root need not wait for future rounds. Preserve the host-specific retention
and export exceptions in [PRD-RETENTION](../decisions/claude-host-v2-implementation-prd.md#PRD-RETENTION), including A's
committed-ledger export and B's verified durable export. Do not invent a common age threshold, new cleanup service,
automatic expiry for durable exports/investigation records, or authority over provider-owned resources.

## No cost, CLI only

<a id="R-NOCOST"></a>
Both hosts call vendor CLIs only — no vendor HTTP API, SDK or API key. Login is the user's own OAuth login in each CLI;
wrappers check the binary and never enter or store credentials. Billing follows the AUTHENTICATION type, not the model
flag (Gemini CLI v0.60.0 `contentGenerator.ts`: auth is selected before the model is resolved); environment scrubbing and
the absence of `-m` are hygiene, not proof of the billing route. The names a host removes from every vendor child (C11's
agreed set) are the union of both hosts' lists, read from the installed CLIs. Every name B removes is in it. Loader /
interpreter names, identical on both hosts: LD_PRELOAD, LD_LIBRARY_PATH, LD_AUDIT, LD_DEBUG, DYLD_INSERT_LIBRARIES,
DYLD_LIBRARY_PATH, DYLD_FRAMEWORK_PATH, NODE_OPTIONS, NODE_PATH, PYTHONPATH, PYTHONHOME, PYTHONSTARTUP, BASH_ENV, ENV,
PERL5LIB, RUBYOPT, RUBYLIB. Credential / endpoint names: Google — GOOGLE_API_KEY, GEMINI_API_KEY,
GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_GENAI_USE_VERTEXAI, GEMINI_CLI_USE_COMPUTE_ADC, CLOUD_SHELL,
GOOGLE_GEMINI_BASE_URL, GOOGLE_VERTEX_BASE_URL, GEMINI_DEFAULT_AUTH_TYPE, GOOGLE_CLOUD_ACCESS_TOKEN,
AGY_ADC_AUTH, GOOGLE_GENAI_USE_ENTERPRISE; codex — OPENAI_API_KEY, CODEX_API_KEY, CODEX_ACCESS_TOKEN, OPENAI_BASE_URL,
OPENAI_ORGANIZATION, OPENAI_PROJECT; claude — ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL,
CLAUDE_CODE_USE_{BEDROCK, VERTEX, FOUNDRY, ANTHROPIC_AWS,
ANTHROPIC_GOOGLE_CLOUD, GATEWAY, MANTLE}, CLAUDE_CODE_API_BASE_URL, CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR,
CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR, CLAUDE_CODE_OAUTH_REFRESH_TOKEN,
CLAUDE_CODE_GATEWAY_TOKEN, CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR, ANTHROPIC_FOUNDRY_API_KEY,
ANTHROPIC_FOUNDRY_AUTH_TOKEN, ANTHROPIC_AWS_API_KEY, AWS_BEARER_TOKEN_BEDROCK, ANTHROPIC_IDENTITY_TOKEN,
ANTHROPIC_IDENTITY_TOKEN_FILE, ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_SERVICE_ACCOUNT_ID, ANTHROPIC_PROFILE,
ANTHROPIC_ORGANIZATION_ID, ANTHROPIC_WORKSPACE_ID. A name of one family is inert in another family's child. Filtering checks each name before retrieving its value; an omitted variable is not read merely to discard it (C75). The project
family GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_CLOUD_REGION and GOOGLE_CLOUD_QUOTA_PROJECT reaches a gemini
child and is removed on every other route. Not removed: PATH, the CLIs' config-dir pointers, and GOOGLE_GENAI_USE_GCA
(it selects the login route). Model/effort user settings are preserved, including
GEMINI_MODEL, ANTHROPIC_MODEL and ANTHROPIC_SMALL_FAST_MODEL; they are not part
of the removed-name set. No additional environment inspection, warning or
effective-effort attestation is introduced (owner
[D-SELECTOR-PROPOSAL-WITHDRAWN-20261009](../decisions/owner-register.md#D-SELECTOR-PROPOSAL-WITHDRAWN-20261009)).
The following source snapshots predate that withdrawal. On A: one list for every route (`_CHILD_ENV_SCRUB`, `_CHILD_ENV_SCRUB_CREDENTIALS`,
`_GEMINI_ROUTE_KEEP`, `3rd-Agent/wrappers/_common.py:3124-3253` @ triad e0b15f1). On B: the loader names on every route
(`bin/_common.py:1307-1313`), and a per-route subset on the formal routes only (agy `bin/antigravity_wrapper.py:39-50`,
gemini `bin/gemini_wrapper.py:43-53` @ `7f75863`; DL-71, DL-80, DL-81). The project family stays on the gemini route because the gemini CLI documents that a Company, School or Google
Workspace account signing in with Google may need a Google Cloud project set
(https://geminicli.com/docs/get-started/authentication/ § Set your Google Cloud project, "Last updated: Sep 18, 2026",
read 2026-10-04). Default model for the Google review leg on BOTH CLIs: the Pro family with a verifiable HIGH thinking configuration (owner Q-W; owner via the codex session, Q2: "두 CLI 모두 Pro 계열 + 확인 가능한 high로 맞춤; 인증 경계 유지"). agy: today's Pro-high catalog slug, recorded in the roster; gemini CLI: a route-valid Pro model whose default thinking level is HIGH (v0.60.0 `defaultModelConfigs.ts` gives Gemini 3 Pro `ThinkingLevel.HIGH`; the agy slug is NOT a portable gemini CLI argument). Flash was retired as a reviewer (0 unique blocking defects over ten rounds, owner 2026-09-14). Slugs are dispatch-time values in the roster's `agy` / `gemini` block, never constants in code; the configured default is recorded separately from the exposed runtime identity; the model option stays selectable only so a future model can be evaluated. B's explicit legacy development path remains Auto-only. B's opt-in v2 adapter selects route-valid Pro defaults and checks supported controls before inference; preflight settings do not prove runtime identity. On A the v2 gemini route passes the roster's model (`lib/roster_v2.py:971-972`; shipped data `spec/review-legs.default.json:42`). Deterministic
provider-free checks (help, version, policy, argv, env, preflight) stay in each host's automated suite; only authenticated
service checks go through the owner-briefing route (R-GOOGLE); an unrun authenticated check is unverified, never green. Gemini formal review requires CLI
`>= 0.63.0` (owner, D-GEMINI-FLOOR-20261009; includes the earlier headless policy-allow fix) and tests the declared supported range. Gemini `--policy`
REPLACES the user-tier policy directory only; system/admin, workspace and built-in defaults still load (v0.46.0 and
v0.60.0 `packages/core/src/policy/config.ts`), so an admin policy can outrank the wrapper's denies; the CLI help string
"Additional policy files" is misleading and the wrapper's TOML header is right.
A different Google model (C18) is the user's pin and is passed to the CLI as written (R-MODEL): no host checks it against
a model list before review inference — no `agy models` call, and no packaged list as a gate (the gemini CLI exposes no
model listing, `gemini --help`, 0.60.0; a host-packaged gemini list is display data only). A model the CLI refuses ends
as R-MODEL's one terminal failed-to-run record naming the leg and the model and telling the user to change the roster
entry; `contracts/vendor-failure-lines.json` holds no measured agy or gemini model-refusal sentence yet, so a new one
ends `unknown` and reaches the repair analysis (R-CLASSIFY). The Pro-high default above stays, and the resolved model is
recorded (R-ROSTER). Code removed (DL-116): on A the `agy models` gate before a pinned review dispatch
(`_catalog_auth_observed` / `_model_catalog_refusal`) and the gemini review preflight's packaged-list gate
(`3rd-Agent/wrappers/gemini-models.json`) are gone @ triad `86cffe93` (`tests/unit/wrappers/t71-agy-model-passthrough-c18.sh`
axis P0); at triad `e0b15f1` they sat at `antigravity_wrapper.py:775-923`, `:2511-2519` and `gemini_wrapper.py:273-296`,
called at `:329-330`; On B the agy preflight runs `agy models` and refuses an unprobeable listing or a model it does not
advertise (`bin/antigravity_wrapper.py:82-101`, `:635-643` @ `7f75863`) and the gemini route refuses a model its packaged
list does not name (`bin/data/gemini-models.json`, `bin/google_preflight_v2.py:15-24`, called at
`bin/gemini_wrapper.py:192-194`). Every Gemini CLI route, including raw investigation and legacy/v2 review, requires 0.63.0 or later
(owner, [D-GEMINI-FLOOR-20261009](../decisions/owner-register.md#D-GEMINI-FLOOR-20261009)); this is one route floor,
independent of the requested model, not a model catalog gate. A pre-release of a floor
version is below that floor (On B `bin/review_round.py:470`), and the observed version is recorded as the CLI printed
it. On A, the all-route 0.63.0 floor and version probe are implemented at triad `1491387a`
(DL-134; C16/C18/C65; `t57` axes 2/7/8/9/10/11/13/17/18 and `t65` axis 3), including raw/write/web calls;
this attributed source/test evidence is not authenticated runtime or adoption proof. The Google Cloud
access-token variable the gemini CLI reads is an API-key-shaped credential under R-AUTH; host A removes it from every
vendor child (`GOOGLE_CLOUD_ACCESS_TOKEN`, triad `ca82837`), B per DL-81.
On A (triad `31c7be92`; PR #13 C75 and the owner's D-SELECTOR-PROPOSAL-WITHDRAWN-20261009, recorded on PR #13): the
model and effort user settings `GEMINI_MODEL`, `ANTHROPIC_MODEL` and `ANTHROPIC_SMALL_FAST_MODEL` of the list above pass
through to every vendor child — A removes the loader names and the credential / endpoint names only — and
`scrubbed_child_env` checks each name before it reads a value, so an omitted variable is never read; every gemini spawn,
the preflight `--version` / `--help` probes included, keeps the project family (`_CHILD_ENV_SCRUB`,
`3rd-Agent/wrappers/_common.py:2068-2074`; `_CHILD_ENV_SCRUB_CREDENTIALS`, `:2097-2160`; `_GEMINI_ROUTE_KEEP`,
`:2176-2180`; `scrubbed_child_env`, `:2183-2196` @ triad `e9960053`; `tests/unit/wrappers/t37-child-env-scrub.sh` the
kept-through and C75 axes, `tests/unit/wrappers/t68-gemini-route-env-c17.sh` axis 4).

## Authentication — the user's own browser login only

<a id="R-AUTH"></a>
Every vendor CLI is authenticated by the USER'S OWN interactive browser (web) login in that CLI, and by nothing else
(owner, 2026-09-26: "api key 형태의 어떤 것도 시도하지 말아야 … 사용자 직접 웹을 통한 로그인만 허용, 비용 발생 위험" — an
API-key-shaped credential bills a paid API outside the subscription). No host component — wrapper, hook, skill, helper,
test, adapter or dispatch — ever issues, configures, reads, stores, sends, forwards or TRIES an API-key-shaped credential
(a vendor API key, a service-account key, a bearer token, or an environment variable that carries one), and no route has
an API-key form of authentication as a fallback when the login is missing, expired or refused. The R-NOCOST child-environment
scrub removes such variables from the vendor child; the scrub is hygiene and never a licence to read their values. A vendor
CLI OBSERVED presenting an API-key-shaped bearer — a `401 Incorrect API key` class error, an auth banner or preflight that
names an API key, a receipt whose authentication class is not the subscription login — is a STOP for that attempt: the host
records it as a terminal failed-to-run record whose remedy is the owner's browser re-login through the CLI's own flow (A:
classification `oauth-env`, exit 65; B: its auth-class refusal or start-failure record), never retries on that basis by
itself, and never inspects, repairs or "fixes" the credential store. A same-basis retry (R-RETRY) runs only after the owner
reports the re-login. The gemini review preflight's refusal of the api-key / Vertex / ADC classes (C16) is one instance of
this rule; the rule holds for every CLI, every route and every credential shape.

R-AUTH is an ABSOLUTE law (owner, 2026-10-04,
[D-AUTH-ABSOLUTE-20261004](../decisions/owner-register.md#D-AUTH-ABSOLUTE-20261004)): every vendor CLI is used only
through the user's own OAuth (browser) login in that CLI; an API key bills unintended charges and is forbidden. It
outranks every other rule of this specification; no host exception, no case exception and no owner question relaxes it.
Where another rule conflicts — the shared classification order (R-CLASSIFY), R-CLASSIFY's plain-fragment rule, R-RETRY —
R-AUTH decides. Login is the user's own act through the CLI: no host checks or configures the login before a call
([D-AUTH-JUDGE-STOP-20261004](../decisions/owner-register.md#D-AUTH-JUDGE-STOP-20261004)); a valid key stored in a CLI's
own configuration and used silently is the user's responsibility under that decision. Enforcement: (i) the
child-environment scrub of credential and endpoint variables (R-NOCOST; hygiene; exists on both hosts);
(ii) the host judges, from the CLI's own outcome, whether a call failed because the login is missing or expired or a
credential is API-key-shaped, and that observed authentication failure STOPS the attempt before any other
classification of the run — no retry, no other method, no fallback. (ii): A done (triad `ca82837`); B to check (DL-76). The gemini
review preflight (C16) is an earlier rule and stays as it is.

## CLI version evidence

<a id="R-CLI-VERSION"></a>
For Codex, AGY, Claude and other CLI adapters, record the observed version and test the controls the route actually needs.
Preserve capability, authentication, containment, transport and output checks, and minimum-version restrictions justified
by a specific known defect (including R-NOCOST's Gemini policy floor). The agy minimum versions differ by host (a
fact). On A there are three floors, checked in this order after the `agy --version` probe, and each refuses
`config-conflict` 65 before any dispatch. (1) The stream-json transport needs agy >= 1.1.8 (`_STREAM_JSON_FLOOR`). (2) A
call that passes `--model` or `--effort` needs >= 1.1.10, because older agy applied both flags after model configuration
had initialised and ran the default model without an error (agy changelog 1.1.10, `_MODEL_FLAG_FLOOR`); a call without
them still runs below 1.1.10. (3) The read-only route needs >= 1.1.18, the first version measured to auto-allow
`--add-dir` reads (`AGY_V2_FLOOR`). Sources: `3rd-Agent/wrappers/antigravity_wrapper.py:336`, `:347`, `:356`, checked at
`:2483-2510` @ triad `e0b15f1`. On B one floor, agy >= 1.1.20, covers every call. Its basis is B's headless plan-mode
contract with native `--json-schema` (`bin/antigravity_wrapper.py:2`, `:31`). Below it B exits 65 with one log line
(`:630-633` @ `7f75863`). B's floor is above all of A's. An unprobeable version is refused on both hosts (A as below the
1.1.8 floor, B as below 1.1.20). An observed/tested patch version is evidence, not
an exact supported-version lock or an upper bound. A different or newer version alone is neither refusal nor conformance;
missing or changed required controls still fail preflight. Do not demand the globally latest CLI or equate version output
with effective policy enforcement. Native routes have no CLI version. A route that observes no version records null (not
observed), never a version inferred from a request or carried over from a preparation probe (a fact, DL-66). On A the
codex wrapper records null and probes no version (`build_transport`, `3rd-Agent/wrappers/_common.py:1949-2005` @
`cbc67f6`); its claude leg is native; this rule authorizes no new probe. On B the claude adapter probes `claude --version`
at preparation and records it in `claude-capability.json` and the sealed adapter (`bin/review_adapters_v2.py:96-97`,
`:130-135`), kept apart from the run receipt, whose `cli_version` stays null when the run does not expose it
(`bin/review_round_v2.py:326-329`); B's codex leg is native. The agy and gemini routes record the version they probe (On A
the same function; On B `bin/antigravity_wrapper.py:766`, `bin/gemini_wrapper.py:519`). On A the agy argument refusal that returned after the probe before any record — a non-numeric
`AGY_SETTINGS_LOCK_TIMEOUT` (exit 3, the probed version unrecorded; `3rd-Agent/wrappers/antigravity_wrapper.py:2456-2460`
@ triad `e0b15f1`) — goes with that setting (DL-112). This rule does not loosen exact model selection or
authorize a model probe (R-MODEL), fallback, global settings or provider permission changes.

## Parity scope

<a id="R-PARITY"></a>
Parity covers option names, types, defaults, scope, refusal behavior and the declared host exceptions of every shared
surface (`units.json`: `common` name + `exceptions`); a matching filename alone is not parity. Host-native internals, test
trees, install layers and agent registration stay host-specific.

## Platforms

<a id="R-PLATFORM"></a>
Both hosts support macOS and Ubuntu 24.04 across install, preflight, dispatch, collection, validation and cleanup;
results are recorded per platform; an unrun check is unverified, never green. Where each host keeps its per-platform
RUN / NOT RUN record (case C24) is host-owned: On A, the goal plan's Evidence section and the task report
(`docs/superpowers/plans/2026-10-03-spec-main-conformance-goal.md` § Evidence in triad; macOS RUN, Ubuntu 24.04 NOT RUN
until its stage 6.2) (a fact, DL-73).
