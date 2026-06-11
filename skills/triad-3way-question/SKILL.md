---
name: triad-3way-question
version: 0.2.1
---

# triad-3way-question

3 CLI 에 한 질문을 동시에 던지고 답을 raw + 요약으로 받는 SKILL.
4자/2자 페어 brainstorm 의 round-loop / viewer / 첨언 흐름 없이 단발
1 round 만. fact-check / cross-validation / 다각 시각 비교에 적합.

## When to use

- 사용자가 "이거 진짜야?", "왜 X 가 Y 한대?" 같은 fact-check 던질 때
- 한 주제를 3 CLI 시각으로 cross-check 하고 싶을 때
- 다각 비교 — 각 모델의 학습 / 검색 도구 / framing 차이 보기

**언제 안 쓰는지**:
- 사용자가 "토론하자 / 같이 plan 짜자" — `triad-pair-brainstorm` / `triad-pair-plan`
- 사용자가 round-loop 원함 (첨언 → 다음 round) — 페어 SKILL
- 검증 자체가 필요 X (단순 한 CLI 답이면 됨) — 그냥 `Task()` 또는 직접

## Hard rules

1. **bypass flag 절대 X**. 모든 CLI 정식 boot. (CLAUDE.md safety invariant)
2. **정식 인터페이스만**. SKILL → lib helper. lib 직접 호출로 우회 X.
   (`feedback_no_official_interface_bypass.md`)
3. **자동 dashboard**. spawn 후 묻지 말고 즉시 host OS 새 터미널 윈도우.
   `triad_set_headless 0 + triad_open_observable_dashboard`. (`feedback_pair_coding_attach.md`)
4. **per-CLI trust 자동**. `triad_pre_spawn_workdir_trust` (in
   triad-pair-consult.sh) — claude / codex / gemini 모두.
5. **편향 없는 prompt enrichment**. 다음 § 룰 의무.
6. **leader = orchestrator-reporter — 모든 worker raw 답 보존 + 포인트 요약
   작성 + 사용자에게 리포팅. 누락 시 SKILL 위반.** 4자 페어의 "종합자 X"
   룰을 풀되, raw 원문은 항상 보존 (사용자가 직접 비교 가능).
7. **Pre-clean — 호출 시 기존 `triad-3way-{cli}` 세션 살아있으면 kill 후
   fresh spawn.** Step 2 의 코드 블록 시작에 박혀 있음. ready 미달
   상태에서 dispatch 절대 X — 모두 ready 후 dispatch (Step 3 wait_ready
   PASS 후만).
8. **Per-worker ready 매니저 패턴.** Step 3 의 `triad_wait_pane_ready
   triad-3way-<cli> <cli> 60 &` × 3 — 각 worker 가 독립 백그라운드
   매니저, 한 매니저가 직렬로 기다리지 X. 한 worker 가 늦어도 다른
   worker dispatch 보류 (모두 ready 후 동시 dispatch — 일관성).
9. **사용자 explicit kill only — Default = keep alive 절대.** 사용자가
   명시적 'kill / 종료 / 정리 / cleanup' 신호 보낼 때만 4 session
   (3 worker + dashboard) 한 번에 kill. SKILL 종료 시점에 leader 가
   keep 가정으로 끝내고, 사용자가 잊고 종료 신호 안 줘도 그대로 두면
   됨 — 다음 호출의 pre-clean (룰 7) 이 자동 cleanup.

## Prompt enrichment (편향 X 룰)

사용자가 대충 던지면 leader 가 풀어 markdown 으로 보충한다. 단,
**편향 source 절대 X**:

### 의무
- 사용자 질문의 **검증 대상 entity / 주제** 명확화
- WebSearch 1-2 회로 **공개 사실 context** 확보 (의견 / 추측 X)
- per-CLI 적합 **검색 도구** 안내:
  - claude → `WebSearch` tool
  - gemini → `GoogleSearch` tool
  - codex → web search (default `cached`)

### 금지 (편향 source 가 되는 패턴)
| ❌ 편향 framing | ✅ 중립 framing |
|---|---|
| "왜 X 가 Y 하는지" (Y 가정 박힘) | "X 가 Y 하는지, 그렇다면 왜인지, 아니라면 어떤 오해 / 다른 현상인지" |
| "X 의 문제 분석" (부정 가정) | "X 에 대한 비판 + 옹호 양쪽 시각 모두 검증" |
| "X 가 Z 보다 떨어진다는데 그 이유" | "X 와 Z 의 비교 — 양쪽 강점/약점 모두" |
| leader 의 가설 / 추론 직접 명시 | 검증 대상만 풀어 명확화. leader 의견 X. |

### per-CLI 시각 분배 룰
- **사용자가 명시한 경우만 분배** (e.g. "gemini 자아 비판, claude/codex 팩트체크")
- 명시 X 면 **단일 prompt 3 CLI 동일** — 자연스러운 시각 차이는 모델 학습/도구
  차이로 자동 발생, leader 가 강요 X

### enriched prompt 구조 (per CLI 1 파일)

```markdown
# <검증 대상 한 줄, 중립 framing>

## 검증할 것
1. <factoid 1 — 일어나는지 (yes/no 모두 열어둠)>
2. <factoid 2 — 일어난다면 메커니즘 / 알려진 원인>
3. <factoid 3 — 일어나지 않는다면 어떤 다른 현상 / 오해와 혼동되는지>
4. <factoid 4 — (사용자 시각 분배가 있을 때만) 자아 비판 / 팩트체크 / 비교>

## 도구
- <CLI native 검색 도구 명시>

## 출력
- 한국어 markdown
- 출처 URL 1-3 개 명시 (실 존재 검증된 것만)
- 검증된 사실만; 추측은 명시 표기 ("추측:")
- 분량: 답 본문 ~30-50 lines (너무 길면 사용자 부담)
```

## Flow

### Step 0 — SKILL 호출
사용자가 `/triad-3way-question` + 자유 텍스트 질문 (한 줄 또는
multi-line). 본 SKILL 은 사용자 직접 호출만 — leader 자동 trigger X.

### Step 1 — Leader prompt enrichment

leader 가:

1. 사용자 질문 entity / 주제 / 검증 대상 추출
2. (선택) WebSearch 1-2 회로 공개 사실 context 빠르게 확인
   — 추측 / 의견 박지 X. 이건 enrichment 의 사실 부분 채우는 용도.
3. 위 § 룰 따라 편향 없는 markdown prompt 작성:
   - 사용자가 per-CLI 시각 분배 명시했으면 → 3 prompt 다름
   - 명시 X 면 → 1 prompt × 3 사용
4. **사용자에게 enriched prompt 보여주고 1-step confirm**:
   ```
   원본 질문: <사용자 한 줄>

   Enriched prompt (편향 X 검증):
   ─────────────
   <enriched markdown>
   ─────────────

   3 CLI 에 이대로 보낼게요. 정정 / OK?
   ```
   사용자가 정정 가능 (편향 의심 / 누락 / per-CLI 분배 변경).
   **사용자 OK 후에만** 다음 단계.

### Step 2 — pre-clean / workdir / trust / spawn (병렬)

```bash
. .claude/skills/triad-orchestrate/lib/triad-tmux.sh
. .claude/skills/triad-orchestrate/lib/triad-pair-consult.sh

# Pre-clean (Hard rule 7) — 기존 worker 세션 살아있으면 kill 후 fresh.
# 사용자 잊음 처리: 이전 호출이 keep-alive 로 끝났어도 매 호출 첫 단계가
# 자동 cleanup. 즉 사용자가 명시적 kill 안 해도 lab 환경이 누적 X.
for s in triad-3way-claude triad-3way-codex triad-3way-gemini triad-3way-dash; do
  if tmux has-session -t "$s" 2>/dev/null; then
    triad_kill_session "$s" || tmux kill-session -t "$s"
  fi
done

WORKDIR_BASE="$HOME/triad-pair/3way"
mkdir -p "$WORKDIR_BASE/claude" "$WORKDIR_BASE/codex" "$WORKDIR_BASE/gemini"

# enriched prompt 파일 저장 (per CLI)
cat > "$WORKDIR_BASE/claude/_3way-prompt.md"  <<'EOF' ... EOF
cat > "$WORKDIR_BASE/codex/_3way-prompt.md"   <<'EOF' ... EOF
cat > "$WORKDIR_BASE/gemini/_3way-prompt.md"  <<'EOF' ... EOF

. .claude/skills/triad-orchestrate/lib/triad-tmux.sh
. .claude/skills/triad-orchestrate/lib/triad-pair-consult.sh

# Visibility default 0 (사용자 진행 과정 보임) — 사용자 override = SKILL invoke 직전 TRIAD_TMUX_HEADLESS=1 set
: "${TRIAD_TMUX_HEADLESS:=0}"
triad_set_headless "$TRIAD_TMUX_HEADLESS"

# trust 자동 (3 CLI)
triad_pre_spawn_workdir_trust claude "$WORKDIR_BASE/claude"
triad_pre_spawn_workdir_trust codex  "$WORKDIR_BASE/codex"
triad_pre_spawn_workdir_trust gemini "$WORKDIR_BASE/gemini"

# 병렬 spawn
triad_spawn_worker triad-3way-claude claude "$WORKDIR_BASE/claude" &
triad_spawn_worker triad-3way-codex  codex  "$WORKDIR_BASE/codex"  &
triad_spawn_worker triad-3way-gemini gemini "$WORKDIR_BASE/gemini" &
wait

# 자동 dashboard (host OS new terminal, 묻지 X)
triad_open_observable_dashboard triad-3way-dash \
  triad-3way-claude triad-3way-codex triad-3way-gemini
```

### Step 3 — wait_ready 병렬 (per-worker 매니저)

```bash
# Hard rule 8 — 각 worker 별 독립 백그라운드 매니저, 직렬 X.
# 모두 ready 후 동시 dispatch (Step 4) — 한 worker 가 늦어도 다른
# worker dispatch 보류, 일관성 위해.
triad_wait_pane_ready triad-3way-claude claude 60 &
triad_wait_pane_ready triad-3way-codex  codex  60 &
triad_wait_pane_ready triad-3way-gemini gemini 60 &
wait
```

### Step 4 — dispatch 병렬 (file-handoff)

trigger ≤200 char (lib 강제). claude trigger 는 textual answer
강제 표현 명시 (이전 mid-task 발견 — `Read X and answer.` 만으로는
claude 가 Read tool 만 호출하고 답 X):

```bash
CLAUDE_TRIG="Read $WORKDIR_BASE/claude/_3way-prompt.md. Then write your full markdown answer in this chat. Do not just acknowledge."
CODEX_TRIG="Read $WORKDIR_BASE/codex/_3way-prompt.md and answer in chat with web sources cited."
GEMINI_TRIG="Read $WORKDIR_BASE/gemini/_3way-prompt.md and answer in chat with GoogleSearch sources cited."

triad_dispatch_and_capture triad-3way-claude claude "$CLAUDE_TRIG" > /tmp/3way-claude.raw 2> /tmp/3way-claude.err &
triad_dispatch_and_capture triad-3way-codex  codex  "$CODEX_TRIG"  > /tmp/3way-codex.raw  2> /tmp/3way-codex.err  &
triad_dispatch_and_capture triad-3way-gemini gemini "$GEMINI_TRIG" > /tmp/3way-gemini.raw 2> /tmp/3way-gemini.err &
wait
```

### Step 5 — 답 추출 + 요약

```bash
for cli in claude codex gemini; do
  triad_extract_answer_text "$(cat /tmp/3way-$cli.raw)" "$cli" \
    > "/tmp/3way-$cli.answer.md" 2> /dev/null
done
```

leader 가 3 답 읽고 **포인트 요약** 작성:
- 공통점 (3 답이 모두 가리키는 사실)
- 분기점 (답이 갈리는 부분)
- 출처 신뢰도 — URL 인용 개수 / 도메인 / cross-reference 가능성

## 출력 형식 (사용자에게)

```markdown
## Summary

**원본 질문**: <사용자 한 줄>

**3 CLI 답 포인트**:
- 공통점: <2-4 lines>
- 분기점: <2-4 lines>
- 출처 신뢰도: <1-2 lines, 인용 URL 카운트 + 도메인>

**leader 의견**: <1-2 lines, 종합 / 신뢰도 평가. 사용자 directive 로 풀어준 부분 — 4자 페어와 다른 점>

## Raw 답변 (원문 보존)

### claude (<N> lines)
<details><summary>전체 보기</summary>

\`\`\`markdown
<raw 답>
\`\`\`

</details>

### codex (<N> lines)
<details><summary>전체 보기</summary>

\`\`\`markdown
<raw 답>
\`\`\`

</details>

### gemini (<N> lines)
<details><summary>전체 보기</summary>

\`\`\`markdown
<raw 답>
\`\`\`

</details>
```

raw 는 `<details>` 로 접어 사용자가 펼쳐 비교. 요약은 펼친 상태로.

## Cleanup (Step 6)

**Default = keep alive 절대 (Hard rule 9).** 사용자가 명시적 'kill /
종료 / 정리 / cleanup' 신호 보낼 때만 cleanup. SKILL 종료 시점에
leader 가 keep 가정으로 끝내며, "다음 cross-question 받을 준비
완료" 정도의 한 줄 안내 (cleanup 옵션 ask X — 사용자가 요청 안
했는데 묻는 게 friction).

사용자가 잊고 종료 신호 안 줘도 그대로 두면 됨 — 다음 호출의 Step 2
pre-clean 이 자동 cleanup (룰 7). 즉 lab 환경 누적 X.

사용자 명시 종료 신호 받았을 때:

```bash
triad_kill_session triad-3way-claude
triad_kill_session triad-3way-codex
triad_kill_session triad-3way-gemini
triad_kill_session triad-3way-dash
```

## Failure modes

- `triad_dispatch_and_capture` rc≠0:
  - rc=1: max timeout / dialog loop 소진 → leader 가 capture 보고 사용자 escalation
  - rc=3: unknown stuck → Layer 3 사용자 escalation (`triad-orchestrate § Self-recovery` 의 3 Layer framing — 2026-05-04 `triad-pair-self-recovery` SKILL 흡수)
- claude 답 너무 짧음 (<3 lines):
  - 알려진 issue (mid-task A) — claude 의 `Read X and answer.` autonomous mode quirk
  - 위 trigger 의 "Then write your full markdown answer in this chat. Do not just acknowledge." 표현으로 mitigate
  - 그래도 짧으면 leader 가 사용자한테 짚고 재 dispatch 옵션 제시
- gemini URL hallucination 의심:
  - 본 SKILL 의 자체 검증 대상이 될 수도 (`/triad-3way-question 왜 gemini 가 url 틀려?`)
  - leader 요약에 URL 신뢰도 평가 명시

## Why this SKILL exists

이전 turn (2026-04-30 evening): 사용자가 "3 CLI 동시에 fact-check"
요청. leader 가 정식 SKILL 없이 lib helper 직접 호출로 자의 운영 → 사용자
지적: "스킬화하지 않고 자체 운영하면 무슨 의미지". 이 SKILL = 그
incident 의 구조적 fix. 정식 인터페이스 박아 lib 우회 root cause 해결.

본 SKILL 의 의의:
- **단발 fact-check 의 정식 인터페이스** — 4자 페어 SKILL 의 round-loop
  부담 없이 빠르게 cross-check
- **편향 없는 enrichment** — 사용자가 대충 던져도 leader 가 풀되 답을 유도 X
- **요약 + raw 둘 다** — 사용자 시간 (요약) + 사실 보존 (raw)
- **자동 dashboard** — 페어 코딩 default 정합

## Reference

- `lib/triad-tmux.sh` — spawn / wait / dispatch / capture
- `lib/triad-pair-consult.sh` — `triad_pre_spawn_workdir_trust` dispatcher
- `lib/cli/<cli>/{profile,detect,ensure}.sh` — per-CLI primitives (옵션 C)
- `feedback_no_official_interface_bypass.md` — SKILL = 정식 인터페이스
- `feedback_pair_coding_attach.md` — 자동 dashboard
- `feedback_4way_pair.md` — 4자 페어 룰 (이 SKILL 은 다른 흐름)
- `project_orchestrate_audit_2026_04_30.md` — 옵션 C 6단계
