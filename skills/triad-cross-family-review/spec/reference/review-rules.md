# Review rules — the one normative location

These rules govern both hosts; current implementation and migration status are recorded separately. Each rule carries an anchor; `process.md`, `cases/cases.json`, `units.json` and the host
skills reference the anchor. Owner rulings are quoted from `decisions/owner-register.md`.

Host citations in this file: unless a citation names its own commit, an On A citation is at `codefoundry-io/triad`
`goal/spec-main-conformance` @ `4af44cf`, with `lib/` meaning `.claude/skills/triad-cross-family-review/lib/` and
`3rd-Agent/wrappers/` the wrappers; an On B citation is at `triad-codex-dispatch` 0.2.558 @ `7f75863`.

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
Where the round integrity check runs differs by host (a fact, DL-52). On B: `collect` itself runs `_load_basis` (seal,
digest, `verify_round` at `bin/review_round.py:1908-1931`) at its start and end (`bin/review_round_v2.py:508`,
`:532`). On A: the leader runs `review_scratch.py verify` before `collect`
(`.claude/skills/triad-cross-family-review/SKILL.md:499-502`; `lib/review_scratch.py:2445`), which writes
`.verified-r<N>.json`; `collect_v2.collect` does not read that record (`lib/collect_v2.py:1934-1962`) and `close`
warns when it is absent (`lib/review_scratch.py:18-23`). A skipped `verify` is a leader's mistake within R-THREAT's
scope; host A's guard is its flow (verify before collect) and the `close` warning when the highest captured round has no
verify record (`lib/review_scratch.py:18-23` @ `faeb86b`); the spec does not require a collector refusal. That
DL-52 is a fact rather than a rule is the leader's ruling (host A's leader ledger, unpublished); this reconciliation with
R-THREAT is the controller's ruling in the owner-directed fix round 15 ("Fix the 5 lows, then publish").

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
`_check_contract_basis` and `_bound_metadata` before allocating (`lib/collect_v2.py:2539-2540`). On B: `allocate_attempt`
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
(`.claude/agents/cross-family-review-reviewer.md:5-6` and its siblings), which the round does not yet bind (open,
`authoring/shared-dev-log.md` DL-49). On B: every control comes from the resolved roster and its adapters, sealed in
the basis (`bin/review_round_v2.py:146`, `:152-169`), except that a claude entry's `agent` is passed as `--agent`
(`bin/review_adapters_v2.py:107-108`, `bin/review_round_v2.py:222-223`) and the named agent's definition, resolved by the
Claude CLI, is outside the roster and outside `_toolkit` (open, DL-49).
The receipt records entries actually run and family coverage; two legs of one family remain one family, without a veto
on an otherwise agreed round. Selected investigations remain separate under R-INVEST.

Reuse each host's existing JSON roster and shipped data defaults (B: `.agents/triad-review-legs.json` and its existing
shipped default file). Change an entry's model/effort in that configuration location; resolve and pass its exact requested
model ID to the CLI/native invocation without separately editable copies in prompts or orchestration code. This creates
no new settings layer; the recommended defaults are the ones stated below. Existing override precedence and explicit `model: null` semantics
remain. `vendor` is a FAMILY value (`claude` | `codex` | `google`); `agy` / `gemini` blocks hold route-specific settings.
Model and effort remain expressible for every vendor and adapter-validated against actual capabilities before inference.
When both Google CLIs are present, an explicit `google.route` pin selects one; otherwise keep R-GOOGLE's existing chain.
Timeouts remain adapter-validated (B legacy formal Gemini requires 600 s and Claude 1200 s; illustrative shared 900 s
Claude entries are not B runnable defaults). No configuration is a shared user-global dependency. Show the resolved
roster before inference, and never start unselected entries. Model catalogue/probe policy changes are a separate scope;
exact CLI model selection is not relaxed by the version rule R-CLI-VERSION.

The recommended Claude review default is `claude-opus-5-5` (Opus 5.5) with
`xhigh` effort (owner, 2026-09-25). Ship the explicit model ID rather than the
moving `opus` alias. Named model/effort overrides and explicit null selection
retain their existing semantics; older supported models remain selectable.
The adapter checks the requested model and effort before review inference and
refuses a reported selection that contradicts a catalogued explicit model ID. Selection
evidence is not proof of the eventual runtime model. B's fixed legacy formal
route uses this same model/effort pin; its raw wrapper keeps caller passthrough.

The recommended codex review default is `gpt-6-astra` with `high` reasoning on both
hosts (owner, 2026-10-03, [D-REVIEW-LEGS-20261003](../decisions/owner-register.md#D-REVIEW-LEGS-20261003)). A host's SHIPPED default roster
carries an explicit model ID for every leg whose CLI exposes a catalogued ID: a
shipped `null` resolves to the operator's personal CLI configuration and makes the
review baseline differ per machine (found on host A, `authoring/shared-dev-log.md`
DL-2). `model: null` remains an operator OVERRIDE meaning the host's default and is
frozen as null. The requested model and effort are frozen in the bound round inputs
and visible in the per-attempt dispatch record; a runtime identity the CLI does not
expose stays null, never inferred from the request, and an exposed identity that
contradicts the request is refused. A comparison or trial model on any family is an
ordinary opt-in entry; its findings count under R-AGREE like any leg's, and the difference
between two entries is a ledger observation, never a vote (C35).

## Selected investigations

<a id="R-INVEST"></a>
A selected investigation is one or more chosen legs with a custom prompt, model / effort / perspective, authorized extra
read roots and web, returning a free-form or custom-schema result — never a review verdict (owner Q-D). Both hosts keep
it as their existing single-shot dispatch path (On A: the `triad-*-dispatch` skills with `--cwd`; On B: raw
dispatch); it is not a review round and enters no roster accounting. Web search is allowed for every investigation and
dispatch leg of every family (the leader's reading (b) of the owner's words, recorded in
[D-REVIEW-LEGS-20261003](../decisions/owner-register.md#D-REVIEW-LEGS-20261003) and confirmed by the owner's answer there:
model research and the review of prompt-engineering techniques); the caller selects it through the
host's existing web option and needs no further authorization. On A the web option today is: codex `--search`
(`3rd-Agent/wrappers/codex_wrapper.py:103-116`, `:161`), agy `--web` (the read-only research agent,
`antigravity_wrapper.py:1907`) and gemini `--web` (A's research profile, without `--sandbox`, `gemini_wrapper.py:378-392`,
`:510-515`), and claude `--web` (`3rd-Agent/wrappers/claude_wrapper.py:145-152`, `:258-276` @ `38a036d`): it adds the native
pre-approval `--allowedTools WebSearch WebFetch`, and under `--sandbox read-only` it widens the restricted `--tools` list
to `Read,Glob,Grep,WebSearch,WebFetch`, because a pre-approval cannot add a tool `--tools` removed (an A-only mechanism;
Claude Code CLI reference, https://code.claude.com/docs/en/cli-reference); `--strict-mcp-config`, `--setting-sources user`
and `dontAsk` stay, and the audit row gains `web` only when true (`3rd-Agent/wrappers/_common.py:3988-3991` @ `38a036d`). On B: the raw AGY,
Gemini and Claude wrappers' explicit `--web` (`bin/antigravity_wrapper.py:421`, `bin/gemini_wrapper.py:256`,
`bin/claude_wrapper.py:286`; C29, C31) — B's claude `--web` adds the same pre-approval only
(`bin/claude_wrapper.py:417-418`) and restricts no tool list, its formal review running `--permission-mode plan`
(`:419-420`); a native codex investigation runs in the host's own codex session, and no B
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
@ `b53409b`; On B: open, DL-46). The plan purpose REPLACES the code
purpose, not a checklist appended to it. The resolved stage is a member of the bound basis (R-PREPARE); no verdict field
is added.
All selected legs receive the same semantic purpose, requirements, scope and evidence. Identity, output handling and
provider tools remain route-specific. The default first review uses no separate personas or predicted-defect checklist.
A leader's hypotheses never limit findings elsewhere in scope. Targeted perspectives remain available through R-INVEST.
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
On A (`lib/review_scratch.py:2783-2796`, `:2809-2847`): a brief carrying an alternate line-separator character; a brief
line whose stripped text begins and ends with `=====` and is neither exactly `=====` nor the one
`=====QUESTIONS=====` marker; a residual or excerpt line whose stripped text equals one of the round's fence lines. On
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
edits the one constant `REVIEW_WEB_STANDING_AUTHORIZATION` (`lib/review_scratch.py:3650-3658` @ `b53409b`); On B, the
request's `review_web_authorized` is the caller's value, default false (`bin/review_round_v2.py:133`), so B has no
standing switch yet (its standing binding is open, DL-39). An absent condition in a bound record means false. Every route of
every host supports web; a route without it is a host defect, refused at preflight until fixed. Gemini selects a
complete web-enabled host profile, never an overlay: only `google_web_search` and `web_fetch` move to allow, with all
other controls preserved; the no-web profile stays the profile for a false condition. Pre-existing owner and admin
denies remain authoritative. The review-web authorization lets no round make a permanent global settings change or
bypass a permission. Each host's agy settings fact, per host: On A, an install-time allow — a user-level agy settings
allow of `read_url(*)`, made once by the operator at installation and named by the wrapper
(`3rd-Agent/wrappers/antigravity_wrapper.py:1975`); On B, a per-call temporary settings transaction — the v2 agy adapter
passes no `--project` (`bin/review_adapters_v2.py:167`), so the wrapper merges its deny rules into the agy settings for
the call and restores them afterwards (`bin/antigravity_wrapper.py:655-664`, `bin/_agy_settings.py:571-591`). Live service checks: `contracts/review-web.verify.toml`. Per host, a true condition reaches each
route as follows; a false condition leaves every route in its R-CONTAIN no-web posture.

- On A (cited @ `b53409b`): the carrier is `review_scratch.py prepare --v2`, which binds the strict boolean
  `review_web_authorized` to the one named constant `REVIEW_WEB_STANDING_AUTHORIZATION = True`
  (`lib/review_scratch.py:3650-3658`) and the UTC `review_date` into the digest-covered `Review metadata:` line
  (`:5897-5899`); a caller's `--review-web-authorized false` is ignored with a NOTE and a non-boolean value is refused
  before any file is written (`:3786-3806`). `collect_v2._bound_metadata` checks both against the round record, an
  absent condition meaning false (`lib/collect_v2.py:519-545`). The renderer fills `<review-web-policy>` from the fenced
  `review-web-permission` / `review-no-web` clause and records the selected clause in the prompt manifest, and fills
  `<review-date>` (`lib/prompts_v2.py:40-50`, `:153-155`, `:288`, `:581-582`). `retry` and adoption re-render the
  round's BOUND condition (`lib/collect_v2.py:551`, `:2430`, `:2789`) and do not compare it with the current constant:
  a revocation applies to rounds prepared after it, as above (DL-57). A round prepared before this change binds no
  `review_date`: retry and adoption refuse it (`:581-585`) and collection reads it with web false (`:523`). Per route
  (`lib/roster_v2.py:929` `render_dispatch`):
  - codex: `--search` (`lib/roster_v2.py:994-1002`); the wrapper's `--search` (top-level `codex --search exec`) replaces
    the pinned `-c web_search="disabled"`; the read-only sandbox, `approval_policy=never` and `--ignore-rules` stay
    (`3rd-Agent/wrappers/codex_wrapper.py:103-116`, `:466`).
  - claude: the native leg is spawned as its preset's web twin — `cross-family-review-reviewer` → `-web`, `-high` →
    `-high-web`, `-max` → `-max-web` (`lib/roster_v2.py:170-173`, `:956-968`); a web preset maps to itself under a true
    condition and to its base under a false one; a selected claude preset without a twin is refused at prepare
    (`:548-557`). The twins (`.claude/agents/cross-family-review-reviewer-web.md`, `-high-web.md`, `-max-web.md`) are, for a rebuild:
    the base preset's model and effort; tools `Read`, `Grep`, `Glob`, `WebSearch`, `WebFetch` and nothing that runs or
    writes; and a body whose web rule is the content of the shared `review-web-permission` clause
    (`prompts/common-clauses.md`).
  - agy: `--review-web` (`lib/roster_v2.py:1025`), a wrapper option that selects exactly what `--web` selects — the
    read-only research agent `triad-readonly-research` and the admission of errored steps of its two web tools — but
    never appends the investigation `web-evidence` clause, which `--web` keeps for investigations
    (`3rd-Agent/wrappers/antigravity_wrapper.py:307-314`, `:1758-1767`, `:1915-1920`, `:2043-2047`); the round's hook runs
    in its `--web` mode (`lib/review_scratch.py:4142-4152`, `:5841-5843`; `lib/agy_hook.py:123`, `:196`); the operator's
    user-level agy settings allow `read_url(*)` (the install-time prerequisite above). The wrapper prints that prerequisite
    at `--setup-agents` (`3rd-Agent/wrappers/antigravity_wrapper.py:1984-1991`), but no round checks it before inference,
    and errored web-tool steps are admitted — a host without the allow runs its agy legs without web and without a
    refusal; a per-round preflight check is open (DL-58).
  - gemini: `--review-web` (`lib/roster_v2.py:1050`) attaches `3rd-Agent/wrappers/policies/gemini-readonly-web.toml`,
    byte-equal to `contracts/gemini-readonly-web.toml`, instead of the no-web profile (`gemini_wrapper.py:125`, `:465`).
  - Every attempt's dispatch record is rendered from the bound condition at prepare and retry. Only the adoption of an
    orphan attempt (R-PREPARE) re-compares the record's launch switch with the bound condition in both directions — a
    wrapper argv carries its route's switch exactly when true and never the investigation `--web`; a native record names
    a web twin exactly when true (`lib/collect_v2.py:154`, `:2084-2105`, `:2182-2205`, called at `:2431` inside
    `_adopt_orphan_attempt`, reached from `retry` at `:2751-2754` @ `faeb86b`). An ordinary attempt's record and a command
    line edited by hand before it runs are not re-compared (a fact under R-THREAT).
  - Non-conformance of host A's legacy entry points (a fact, not an exception, until they are retired: the owner's
    answer of 2026-10-03 is to retire them later, D-REVIEW-LEGS-20261003, `authoring/shared-dev-log.md` DL-59). They do not implement the standing authorization (cited @
    `faeb86b`). The small review path (`lib/review_small.py`) gives web only under its own `--web`: codex `--search` and
    agy the investigation flag `--web` (`:328-332`), which also appends the investigation `web-evidence` clause
    (`3rd-Agent/wrappers/antigravity_wrapper.py:2043-2047`), and claude spawned as `<agent>-web` (`:367-371`); under its
    `--web` it refuses gemini and a claude agent other than the base and high presets (`:101-102`, `:265-271`,
    `:450-455`); without `--web`, a directly named `-web` preset is spawned unchanged and runs with its web tools. The v1
    path (`prepare` without `--v2`) passes no web switch — its X-leg codex line is printed without `--search`
    (`lib/review_scratch.py:3624-3625`); for its standing codex and agy legs `prepare` prints only the output
    redirections (`:6081-6085`) and the dispatch is the v1 hand-built line of `references/leg-contracts.md:1397-1415`
    (codex: `--sandbox read-only`, `--pydantic`, no `--search`) and the agy read-only review agent, which has no web tool
    (`:435-439`), all @ `faeb86b` — and refuses the review-web condition (`lib/review_scratch.py:3817-3820`).
- On B: the v2 request member `review_web_authorized` (`bin/review_round_v2.py:130-133`) is the carrier; it defaults to
  false per request, so binding it true for every round under the standing authorization is open (DL-39). For a true
  condition: native Codex receives it through its fresh-child prompt metadata and requires host web availability
  (`bin/review_adapters_v2.py:61-75`, `bin/review_prompts_v2.py:88-90`); Claude preapproves only native `WebSearch` and
  `WebFetch` (`bin/claude_wrapper.py:417-418`); AGY keeps its read-only controls while omitting the review-only
  `read_url(*)` deny (`bin/antigravity_wrapper.py:647-663`, `bin/_agy_settings.py:43-49`, `:90-100`); Gemini selects
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
Review legs read; they do not mutate, execute the candidate, or spawn vendors. REVIEW web follows the bound
R-REVIEW-WEB condition, which the owner's standing authorization sets true for every round (D-9's review prohibition
is superseded by D-REVIEW-LEGS-20261003). When that condition is false, REVIEW has no web: codex `web_search="disabled"`;
agy review agents without web tools (A ships this posture; B's formal builder explicitly denies `read_url(*)`;
raw investigations retain web); gemini by the explicit deny rows in its host profile below. Renderers keep the
no-web posture for a false condition and select the authorized web posture only under R-REVIEW-WEB. Gemini host
profiles remain separate under D-B1. On A: `contracts/gemini-readonly.toml` for a false condition
(`3rd-Agent/wrappers/policies/gemini-readonly.toml`) and `contracts/gemini-readonly-web.toml` for a true one (`3rd-Agent/wrappers/policies/gemini-readonly-web.toml`, byte-equal,
selected under `--review-web`, `gemini_wrapper.py:125`, `:465` @ `b53409b`). On B: `contracts/gemini-readonly-b.toml` for a false condition and
`contracts/gemini-readonly-web-b.toml` for a true one (`bin/policies/gemini-formal-readonly.toml`,
`bin/policies/gemini-formal-web.toml`). Equality means exact bytes of
the selected complete profile, with its adjacent digest; no concatenated overlay is implied. Preserve B's
existing 999/998 allow/deny/catch-all and Plan Mode transition restrictions while moving its two web tools
to explicit denies. A's profile and V1–V5 manifest stay unchanged; B's live checks are separately recorded
in `contracts/gemini-readonly-b.verify.toml`. The web-enabled profiles are selected under R-REVIEW-WEB; the no-web
profile bytes stay unchanged, and their header comments (A: "review legs have no web tools"; B: "D-9: web evidence
belongs to a separately authorized investigation, never REVIEW") describe the no-web profile. B's web profile header
(`contracts/gemini-readonly-web-b.toml:1`, `:3`: "explicitly authorized web verification", "selected only for an explicitly
owner-authorized review") predates the standing authorization; under it every review round is owner-authorized, so the
header reads as "selected for a true bound condition"; its bytes stay pinned by B's manifest digest. A's web profile header
(`contracts/gemini-readonly-web.toml:8-9`) points its runtime effect at `contracts/review-web.verify.toml`; that
manifest's WEB-A-2 reaches the profile's policy checks WA1-WA2 through `contracts/gemini-readonly-web.verify.toml`
(bytes pinned, unchanged).
Web-enabled investigations (R-INVEST) keep web. No alignment may introduce a dangerous /
yolo permission bypass on any leg (each host discloses its existing permissive-route flags in `units.json` exceptions; none is on a review route). A leg a host runs natively stays native; no leader-model CLI subprocess is
added for symmetry. Containment EVIDENCE is attributed to the leg attempt that produced it (C23): on a host with a LIVE
per-round hook (A) the wrapper records each attempt's vendor conversation id in its read audit and the hook load check
attributes hook rows by that id — a shared, unattributed hook log never certifies a leg, and a count of conversations is
not attribution (found on A over rounds r11–r13, `authoring/shared-dev-log.md` DL-6). Per vendor, the guards that ship today and must survive any alignment (host, symbol):

- codex leg (A `codex_wrapper.py`, command builder): selected read-only sandbox, `approval_policy=never`, `--ignore-rules`
  on every posture, `web_search="disabled"` whenever `--search` is absent (`codex_wrapper.py:440-464`). On A the v2
  path passes `--search` exactly when the round's bound condition is true (`lib/roster_v2.py:994-1002` @ `b53409b`); the
  legacy small path passes it for a round prepared with its own `--web` (`lib/review_small.py:331`). These are A's controls,
  not instructions for B's native session.
- gemini leg (A `gemini_wrapper.py`): approval modes pinned to `default` / `auto_edit` (plan and yolo removed), the
  read-only × auto_edit conflict refusal, the read-only policy-file precondition, the hardened-install read-only default,
  write posture requires `--cwd`; for a false R-REVIEW-WEB condition A's selected read-only no-web profile denies
  `google_web_search` / `web_fetch` by EXPLICIT rows (D-9 rows — `--policy` replaces only the user tier, so an unnamed
  tool keeps the default tier's decision; runtime effect per `contracts/gemini-readonly.verify.toml`); for a true
  condition A's `--review-web` selects `contracts/gemini-readonly-web.toml` (`gemini_wrapper.py:125`, `:465` @ `b53409b`;
  runtime effect per `contracts/gemini-readonly-web.verify.toml`, NOT RUN); B: `--help` capability preflight, policy self-check against
  `contracts/gemini-readonly-b.toml` for a false condition and `contracts/gemini-readonly-web-b.toml` for a true one
  (runtime effect per `contracts/gemini-readonly-b.verify.toml` / `contracts/gemini-readonly-web-b.verify.toml`), credential/endpoint/model-selector
  variables removed from the child on the formal route. Effective posture is computed BEFORE the conflict and policy checks
  (On A: the hardened read-only default is assigned before both checks, `3rd-Agent/wrappers/gemini_wrapper.py:421-437`).
- agy leg (A): per-round PreToolUse allow-list hook + hook load check + read-audit gate (the hook's `--web` mode adds
  `read_url_content` / `search_web` to its allow set, `lib/agy_hook.py:123`, `:196` @ `b53409b`; a v2 round with a true
  bound condition installs the hook in that mode, `lib/review_scratch.py:4142-4152`, `:5841-5843` @ `b53409b`, and the
  legacy small path uses it under its own `--web`); B: non-mutating project route (`--mode plan --sandbox read-only`) with `--project`, and on the v2 path (no `--project`) the temporary settings transaction named under R-REVIEW-WEB; B's hook stays dormant until separately agreed. The agy hook and the gemini read-only policy are TOOL-NAME controls: neither scopes paths, and the read audit records the argument path as given, not a resolved target — they do not by themselves contain a symlink escape (see the Q4 item in R-PREPARE).
- all wrappers: binary presence; a relative `--prompt-file` or `--cwd` is ACCEPTED and resolved against the wrapper PROCESS cwd at argument processing (never the child `--cwd`); every existing validation stays — configured runtime roots where configured, regular file, UTF-8, non-empty; the resolved absolute prompt-file and child-cwd paths are represented in the existing success summary and audit row, using the host's current redaction mode (D-B2). Refusal names the resolved candidate through that same masking policy; failure-only run logs remain failure-only. Relative spelling alone is never a reason to refuse (C28). On A: relative paths are rebased on the process-entry cwd and then validated (`3rd-Agent/wrappers/_common.py:1800-1844`, `:1865-1881`); On B: `bin/_common.py:502-537`; stdin delivery confirmed or refused (fail closed); process group captured at spawn and
  reaped on timeout / abnormal unwind and normal exit under R-TERMINAL (On A: `_common.py:3198-3205`, `:3333-3381`; On B: `bin/_common.py:1357-1386`); reader and writer completion before success (On A: incomplete readers fail closed, `_common.py:3433-3437`; On B: incomplete/error collection is rejected); schema validation with one clean repair retry where a leg relies on it; verdict
  binding to review id, family and content digest; round integrity capture/verify.
- cleanup: refuses without deleting when a tree is not provably its own; ownership is proven by an allocation record or
  marker, never by a name shape (On A: a `<name>.pruning` dir is reclaimed with the `.claim` record written before its rename, `lib/review_scratch.py:705-722`; On B: allocation provenance, verified export and root identity for stale and explicit cleanup, `bin/review_round.py:1017`, `:1060`, `:1232-1242`). Open exception on A, pending DL-54: an EMPTY unclaimed `.pruning`
  residue older than the floor is removed by `rmdir` (`lib/review_scratch.py:865-876`), a name-shape removal that main's
  R-CLEANUP does not allow; it follows the owner ruling of 2026-09-27 carried by the unpublished R-CLEANUP amendment on
  branch `claude/r-model` (PR #6).

<a id="R-TERMINAL"></a>
Transport success requires: process exit collected, all reader threads joined without error, the owned process group
reaped, stdin delivery confirmed. A settings-guard release failure after a completed transcript is still a failure; the
transcript is preserved. A display-mirror failure is distinct from a failure to capture the result.

<a id="R-TOKENS"></a>
Every classification token a host EMITS is a member of `contracts/exit-tokens.json` and maps to the same exit code there;
wrapper-only tokens and compatibility aliases are listed explicitly as exceptions. A membership test, not an `is not None` assert, checks it (On A:
`tests/unit/wrappers/t55-exit-token-membership-c8.sh`; On B: `tests/test_exit_token_contract.py`).

<a id="R-CLASSIFY"></a>
A failed vendor call is classified by the vendor's own error sentence, and a sentence applies to the CLI that emits it.
The known sentences are data in `contracts/vendor-failure-lines.json`: each row names the CLI, the sentence, the part of
it a host matches (lowercase) and the token. Every host classifies a row's sentence as the row's token on the row's CLI.
A plain fragment that an answer, a reviewed file or a tool's output can contain is never a match phrase: a host may
search the whole output of a failed run, and such a fragment would hide the real cause behind a retry.

<a id="R-RECEIPT"></a>
The transport receipt and audit / run-log records carry the common transport object defined by
`contracts/receipt-fields.json`: stdin delivery class, execution route, binary, observed CLI version and attempt.
Existing host envelopes remain. Schema validation alone does not prove host implementation or observed runtime identity.

<a id="R-BIND"></a>
Every leg's result binds `review_id`, `family` and `content_digest` today on both hosts; a mismatch is an INVALID leg, never
a pass. v2 ADDS (round r2, all three families; lands with the D-3 wire — `contracts/leg-verdict-mapping.md`): `leg_name` (the
roster entry), `attempt` (integer ≥ 1, per leg), `route` (the resolved Google route `agy` | `gemini`; null for a family with
one route). The common v2 prompt pins use these fields. Each host adopts its validator, all shaped clauses and collectors together;
explicit legacy entry points retain their old contract and cannot admit v2 results. On A: the legacy small path
(`lib/review_small.py`) never collects a v2 round's results; it reads its own round's answers and treats v2-shaped extra
fields (binding or schema members) as shape notes, keeping the answer (`:631`, `:654`, `:745`).
A recorded attempt is sealed: the result and every evidence file its route records for the attempt (read evidence; a
transport receipt where the route records one there) are written once and bound by digest when recorded, and collection
refuses a later change, removal or replacement of any of them. A native leg seals what it records; DL-18 adds no
transport receipt or receipt check to A's native spawn. On A: the native claude leg records its verbatim raw reply and
its admitted result (`lib/review_scratch.py:5077-5093`). On B: the native leg's host receipt is built and sealed like any
route's (`bin/review_round_v2.py:474-486`, `:388-395`). A new answer from the same entry needs a new attempt, which
R-RETRY allows only after a failure to run, or a new round (R-REREVIEW). On B: `record_attempt` writes result, read
evidence and receipt with exclusive create and seals `terminal.json` with their digests (`bin/review_round_v2.py:378-397`,
`bin/review_round.py:2308-2317`), and `collect` re-checks those digests (`bin/review_round_v2.py:365-375`). On A: the native admission writes `seal.json` at admission
(`lib/verdict_v2.py:772`, `_write_admission_seal`); a wrapper attempt is sealed by the first collection that evaluates
it; every attempt that recorded an answer, valid or invalid, is sealed with a state field (`lib/collect_v2.py:1322-1475`);
`collect-r<N>.json` keeps each seal's digest and later collections re-check the result, receipt, read evidence and seal;
the printed wrapper line runs a seal guard under `noclobber` and the native spawn gets a printed `guard:` line
(native `guard:` line `lib/review_scratch.py:5078-5088`; wrapper line under `noclobber` `:5107-5111`); an integrity failure makes that entry INCOMPLETE, never AGREED. Known limits on A,
recorded as facts under [R-THREAT](#R-THREAT) — (1)-(3), codex's tampering chains, by owner decision
[D-C66-LIMITS-20261003](../decisions/owner-register.md#D-C66-LIMITS-20261003); (4) and (5) by the leader's ruling under
R-THREAT: (1) after an unusable attempt directory
is collected, removing that directory and the original seal and replacing a blocking result can reach AGREED in the same
round; (2) an earlier attempt sealed invalid is not re-checked for its contents, so changing it after a retry is not
refused; (3) a seal-write failure leaves an evaluated answer without a seal digest, later treated as unrecorded; (4) a
native seal's state field can be edited before the first collection; (5) a native reply that fails admission is not
sealed. Which attempt collection evaluates (a fact): On B the last sealed allocation, refusing a history whose earlier
attempt is not FAILED_TO_RUN (`bin/review_round_v2.py:507-518`); On A the attempt the round record's `attempt` field
names, only behind earlier attempts that `retry` diagnosed and that are not sealed valid (`lib/collect_v2.py:1515-1545`),
and `retry` refuses a valid-sealed attempt and a history that can never be collected before allocating
(`lib/collect_v2.py:2526ff`). A retryable attempt differs by host (a fact, DL-55): On A an attempt sealed invalid (an
answer that could not be admitted) is retryable; On B a completed invalid answer is INVALID, not failed-to-run, and is
refused for retry (`bin/review_round_v2.py:345-349`, `:274-275`).
Duplicate JSON members are rejected at the original-text boundary before extraction or normalization can discard evidence
(On A: the wrapper schema path, `3rd-Agent/wrappers/_common.py:2474-2486`; the raw-reply admission,
`lib/validate_verdict.py:409-436`; the v2 admission of every route's result, `lib/verdict_v2.py:356-419`. On B: its review
wrapper/result paths including explicit v2, `bin/validate_v2.py:34`; see C14/C30).

## Preparation, verification, cleanup (lifecycle obligations)

<a id="R-PREPARE"></a>
`prepare` pins the reviewed basis (commit + content digest), writes the brief, the gated patch and the test patch as separate files (separation is PRESENTATION: relevant tests, policy and prompt text inside the agreed scope stay visible, bound and reviewed; host packet file names are mapped in `units.json`), the history, and the per-round containment artefacts the host uses (A: the agy PreToolUse hook); resolves
the roster from the registry with the recommended defaults; prints one COMPLETE dispatch line per enabled leg; captures the
round snapshot. It refuses on a malformed registry entry and never launches a provider itself. A change to a rule,
schema, prompt clause or policy file is behavioral review scope even when the file contains only text; the docs-never-gate
rule covers narrative documentation only. Symlinks (owner Q4, RULED 2026-09-19: "링크 자체는 검토하되, 대상을 자동으로 따라가지 않는 방식"): the LINK ITSELF is review material — its path, kind and exact link text are fingerprinted and available to reviewers; its TARGET is never followed automatically. Target content enters a review only as an independently authorized, bound input; a link the review cannot follow is disclosed as a coverage gap, never claimed inspected; cleanup never follows a link to delete its target. Each host implements "never followed" its own way and records the evidence (B: link-text fingerprint + symlink refusal in the prepared copy; A: replace its untracked-link refusal with link-text admission and either materialize the text in the round copy or prove no-follow through its read audit — open, DL-53: A still refuses an untracked symlink, `lib/review_scratch.py:2167-2169`) — mechanism = host migration item, principle = shared rule.

The **bound basis** of a round is every input its review depends on: the reviewed bytes and packet; the review
conditions (`review_kind`, `review_web_authorized`, the round date `<review-date>`, and the leader's prompt inputs —
objective, criteria, boundary, `prior_residual`); the selected entries and every entry's resolved controls, from
whatever source the host resolves them (R-ROSTER); and the installed prompt clauses, producer schema and admission
contract. The content digest every leg result carries (R-BIND) covers the reviewed bytes, the review conditions, the
selection and the controls. An input a host produces only after that digest, because the rendered prompts embed the
digest, is recorded with the round at prepare (a mutable round record suffices), and before a retry, an adoption (the re-entry
into an attempt that exists on disk but that the round record does not yet name, left by an interrupted retry; On A:
`_adopt_orphan_attempt`, `lib/collect_v2.py:2354` @ `faeb86b`; B refuses an attempt that already exists,
`bin/review_round_v2.py:291-294`, and has no adoption) or a
collection the host re-derives it from the installed files and compares it with the recorded value; a host may instead
hash the installed source files into the digest. Retry, adoption and
collection read the digest-covered members from the bound bytes, never from a mutable copy. A changed member is a
changed basis: R-RETRY refuses a changed condition, selection or control before an attempt is allocated, the round (verify, then
collect) does not agree on any changed member, and the leader prepares a new round (R-REREVIEW). A host change that alters the bound
basis makes rounds prepared before it non-retryable; prepare a new round.

- On A: `review_scratch.py prepare --v2` writes the `Review metadata:` line of `delivery-r<N>.md`, whose sha256 is the
  content digest (`lib/review_scratch.py:5823-5848`). It carries `review_kind`, `review_web_policy` (the rendered
  web sentence; since `b53409b` the strict boolean `review_web_authorized` and `review_date` instead,
  `lib/review_scratch.py:5896-5899` @ `b53409b`), `selected_entries` and `roster_config_digest`
  (`_v2_config_digest`, `:5263`: every round-record entry field except `attempt`, plus `gate_files`, `hook_log` and
  `results_dir`); the brief and residual are inside the hashed packet. `collect_v2._bound_metadata`
  (`lib/collect_v2.py:442-512`) re-hashes the delivery record and compares the record with the bound line in
  `collect`, `retry` and adoption. A later edit of the project roster file does not affect a prepared round. The
  clause manifests (`prompt_manifests`, `prompt_spec_dir`), the producer projection digest and the contract digest are
  recorded in `.roster-r<N>.json` and compared there with re-derived values (`lib/collect_v2.py:1910`, `:2718-2720`,
  `:2759`): `collect` re-derives the contract digest (`:1944`), adoption and retry the manifests and projection
  (`:2194`, `:2260`, `:2718`, `:2759`); re-deriving the manifests and projection at collection is open (DL-41). The
  round date is bound since `b53409b` (above).
- On B: `bin/review_round_v2.py` `create_basis` seals `basis-v2.json` (the request with `review_kind`,
  `review_web_authorized` and `prior_residual`; the resolved roster; adapters with launch controls and receipt digests;
  the round snapshot; packet files; `_toolkit`, the sha256 of every file under `bin/`, `contracts/`, `prompts/` and the
  skill except `__pycache__` directories, `.pyc` / `.pyo` files and `bin/_logs`, `bin/_debug`) with a `.sha256` sidecar
  and `content_digest` over the rest (`bin/review_round_v2.py:61-71`, `:127-176`). `_load_basis` (`:107-124`), run by
  allocate, record and collect, re-checks the seal and digest, runs `verify_round`, and refuses a changed toolkit, a
  re-resolved roster that differs from the bound one, or changed adapter receipts. The round date is not yet bound (open,
  DL-46).

<a id="R-THREAT"></a>
This rule scopes reviews of a TRIAD dispatch host's own code (the review and dispatch toolkit itself); for any other
reviewed target, the target's deployment context is what the leader states in the brief (R-CONTEXT). Both hosts serve
one operator on a stable machine. There is no concurrent operation: no second install, update,
uninstall or review session runs while an operation runs; concurrency INSIDE one operation, such as two legs of one
round, is real and stays covered. There is no malicious actor (owner,
[D-THREAT-MODEL-20261003](../decisions/owner-register.md#D-THREAT-MODEL-20261003)). Guards defend against ordinary
failures: a full disk, a stop at any point (a crash, or a session that hits its token or usage limit), a wrong argument,
a bad vendor answer, an odd layout of files the leader creates by hand, a reviewer's or the leader's mistake (owner,
2026-10-03, D-THREAT-MODEL-20261003). A finding whose trigger needs deliberate tampering with the host's own files or a
concurrent operation is recorded as a fact — no code and no blocking; the C66 limits (1), (2) and (4) under R-BIND are
worked examples (limits (3) and (5) and other facts recorded under the earlier wording are to be re-triaged,
`authoring/shared-dev-log.md` DL-59). Every leg receives this context, with this rule and
D-THREAT-MODEL-20261003 as its evidence pointer, through the shared `deployment-context` clause, which applies it only
when the reviewed code is a TRIAD host's own and has the leg label such a finding HARDENING-SUGGESTION (non-blocking under R-AGREE); the leader records it as a
SPECULATIVE fact (R-VERIFY).

<a id="R-VERIFY"></a>
The leader checks each claim against the current reviewed bytes, required behavior, concrete trigger and impact before
acting. Preserve the original finding and evidence for each disposition: verified blocking defect → smallest adequate
fix and full re-review (R-REREVIEW); verified non-blocking issue → record, with correction at the maintainer's option;
refuted claim → record the specific counterevidence and its limits; design/scope change → R-STOP; a finding outside the
deployment context → a recorded fact under R-THREAT; speculation → residual, not speculative code. A fix changes the basis. Verify the proposed repair too: a reviewer's label or suggested design is
a claim, not an instruction, and a vote is not evidence. Leader triage cannot rewrite approval under R-AGREE.

<a id="R-CLEANUP"></a>
Cleanup exports and verifies the round's evidence first, then releases only resources the helper can PROVE it allocated or claimed (its own allocation record or marker — never a name shape; an empty directory or a plausible-looking marker can still be foreign); uncertain residue is preserved and reported; it refuses without deleting, states what it observes, and points at the one documented recovery when a tree is not its own. A second cleanup is a no-op. Cap-based pruning of run-log and repair-IPC
files keeps a minimum age floor so a fresh sibling file is never deleted to satisfy a cap (mtime is not only a sort key).
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
the absence of `-m` are hygiene, not proof of the billing route. Default model for the Google review leg on BOTH CLIs: the Pro family with a verifiable HIGH thinking configuration (owner Q-W; owner via the codex session, Q2: "두 CLI 모두 Pro 계열 + 확인 가능한 high로 맞춤; 인증 경계 유지"). agy: today's Pro-high catalog slug, recorded in the roster; gemini CLI: a route-valid Pro model whose default thinking level is HIGH (v0.60.0 `defaultModelConfigs.ts` gives Gemini 3 Pro `ThinkingLevel.HIGH`; the agy slug is NOT a portable gemini CLI argument). Flash was retired as a reviewer (0 unique blocking defects over ten rounds, owner 2026-09-14). Slugs are dispatch-time values in the roster's `agy` / `gemini` block, never constants in code; the configured default is recorded separately from the exposed runtime identity; the model option stays selectable only so a future model can be evaluated. B's explicit legacy development path remains Auto-only. B's opt-in v2 adapter selects route-valid Pro defaults and checks supported controls before inference; preflight settings do not prove runtime identity. On A the v2 gemini route passes the roster's model (`lib/roster_v2.py:971-972`; shipped data `spec/review-legs.default.json:42`). Deterministic
provider-free checks (help, version, policy, argv, env, preflight) stay in each host's automated suite; only authenticated
service checks go through the owner-briefing route (R-GOOGLE); an unrun authenticated check is unverified, never green. Gemini formal review requires CLI
`>= 0.34.0` (PR #20639 lands the headless policy-allow fix) and tests the declared supported range. Gemini `--policy`
REPLACES the user-tier policy directory only; system/admin, workspace and built-in defaults still load (v0.46.0 and
v0.60.0 `packages/core/src/policy/config.ts`), so an admin policy can outrank the wrapper's denies; the CLI help string
"Additional policy files" is misleading and the wrapper's TOML header is right.

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

## CLI version evidence

<a id="R-CLI-VERSION"></a>
For Codex, AGY, Claude and other CLI adapters, record the observed version and test the controls the route actually needs.
Preserve capability, authentication, containment, transport and output checks, and minimum-version restrictions justified
by a specific known defect (including R-NOCOST's Gemini policy floor). An observed/tested patch version is evidence, not
an exact supported-version lock or an upper bound. A different or newer version alone is neither refusal nor conformance;
missing or changed required controls still fail preflight. Do not demand the globally latest CLI or equate version output
with effective policy enforcement. Native routes have no CLI version. This rule does not loosen exact model selection or
authorize new catalogue/probe policy, fallback, global settings or provider permission changes.

## Parity scope

<a id="R-PARITY"></a>
Parity covers option names, types, defaults, scope, refusal behavior and the declared host exceptions of every shared
surface (`units.json`: `common` name + `exceptions`); a matching filename alone is not parity. Host-native internals, test
trees, install layers and agent registration stay host-specific.

## Platforms

<a id="R-PLATFORM"></a>
Both hosts support macOS and Ubuntu 24.04 across install, preflight, dispatch, collection, validation and cleanup;
results are recorded per platform; an unrun check is unverified, never green.
