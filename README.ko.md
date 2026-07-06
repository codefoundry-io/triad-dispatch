> 🌐 **English: [README.md](./README.md)**

# triad-dispatch

**AI 코딩 어시스턴트는 자기 리뷰어와 blind spot 을 공유합니다.** Claude 에게
Claude 의 결과물을 검토시키면 같은 framing 을 물려받습니다 — 버그를 만든 추론이
곧 그 버그를 리뷰하는 추론입니다. triad-dispatch 는 **다른 모델 패밀리** 로부터
두 번째, 세 번째 의견을 받아줍니다: Claude Code 세션에서 **codex**(OpenAI)와
**antigravity / `agy`**(Google)를 단발(single-shot) 워커로 디스패치하고, 위험한
변경을 머지하기 전에는 각 패밀리가 그 결정을 **독립적으로** 반박하는 리뷰를
돌립니다 — 그래서 내 주 모델이 스스로 합리화해 넘긴 버그를, 그 blind spot 이 애초에
없던 모델이 잡아냅니다.

Claude Code 에 플러그인으로 추가합니다. 계속 Claude Code 안에서 작업하되, 외부
의견이 필요하거나 변경이 머지를 막을 만큼 위험할 때 어시스턴트가 대신 다른
패밀리에 물어봅니다.

> **자매 제품:** 팀이 Claude Code 대신 **codex** CLI 를 리더로 쓴다면
> **[triad-codex-dispatch](https://github.com/codefoundry-io/triad-codex-dispatch)**
> 를 보세요 — codex 가 드라이버인 동일한 3-패밀리 모델입니다. 이 제품은 Claude Code
> 드라이버용입니다.

## 첫 디스패치 (2분)

[필수 설정 (~2분)](#필수-설정-2분) 을 마친 뒤, 평소처럼 Claude Code
에게 이렇게 요청합니다:

> triad-codex-dispatch 로 codex 에게 물어봐: `git rebase --onto` 는 무슨 일을 해? 한 문단으로.

Claude 가 `triad-codex-dispatch` skill 을 실행하고, codex wrapper 를 호출해 codex 의
답을 돌려줍니다. stderr 에는 아래 같은 한 줄 성공 요약이 보입니다:

```
[wrapper] codex ok exit=0 vendor=0 elapsed=6.4s
```

- `[wrapper] codex` — 어떤 워커가 실행됐는지.
- `ok` — 분류(깨끗한 답변; `oauth-env` 나 `server-capacity` 같은 다른 값은 특정
  실패를 뜻합니다 — [문제 해결](#문제-해결-troubleshooting) 참고).
- `exit=0` — 성공. 이어서 codex 의 답이 응답으로 옵니다.

이 `[wrapper] <cli> ok …` 줄이 디스패치가 동작했다는 신호입니다. 이 줄과 답이
보이면 플러그인이 살아 있는 것입니다. `triad-codex-dispatch` 를
`triad-antigravity-dispatch` 로 바꾸면 Google-family(`agy`) leg 을 같은 방식으로
시험할 수 있습니다.

## 필수 설정 (~2분)

네 단계면 동작하는 설치가 됩니다. 이 섹션 아래는 모두 선택입니다.

1. **worker CLI 하나 설치 + 로그인.** 디스패치할 non-Claude 패밀리가 최소
   하나는 필요합니다. 나머지는 나중에 추가하세요([선택](#선택--고급) 참고).
   보유한 것 하나를 골라 vendor 의 native login 으로 로그인합니다 — wrapper 는
   인증을 직접 관리하지 않습니다:
   - `codex` (OpenAI) — 설치 후 `codex login`.
   - **Google 패밀리** — `agy` (Antigravity) 설치 + OAuth 로그인(개인 Google
     액세스용); 또는 `gemini` (Gemini CLI) + 조직 로그인(엔터프라이즈 / 조직
     Gemini 액세스용). Gemini CLI *개인* tier 는 폐지(Antigravity 스위트로 이전)
     되었으므로 그 경우 `agy` 를 사용하세요. **엔터프라이즈** Gemini tier 는 계속
     사용됩니다.

   또한 PATH 에 **`python3 >= 3.12`** (wrapper 는 `#!/usr/bin/env python3` 로
   실행)와, 플러그인 마켓플레이스 + 네임스페이스 플러그인 skill 을 지원할 만큼
   **최신 Claude Code** 가 필요합니다. claude 리뷰 leg 는 세션 내 `Agent` 이므로
   별도 로그인이 필요 없습니다.

2. **플러그인 추가.**

   ```
   /plugin marketplace add codefoundry-io/triad-dispatch
   /plugin install triad-dispatch@triad-dispatch
   ```

   저장소가 공개(public)이므로 설치에 별도 인증이 필요 없습니다.

3. **wrapper Bash 권한 부여(명령 한 줄).** 플러그인은 Bash 권한을 부여할 수
   없으므로 wrapper 명령을 `.claude/settings.json` 에 allow-list 해야 합니다.
   이 스크립트가 대신 해줍니다 — 결정적(deterministic), 멱등(idempotent), 재실행
   안전:

   ```bash
   python3 <plugin-dir>/scripts/setup_permissions.py
   ```

   프로젝트 루트에서 실행하세요(`./.claude/settings.json` 을 쓰며, 없으면 만들고,
   엔트리를 중복 없이 병합합니다). `<plugin-dir>` 는 Claude Code 에게 Bash tool
   호출로 물어보면 됩니다: `command -v codex_wrapper.py` 가 설치된 플러그인의
   `bin/` 아래로 해소되고, 그 상위가 플러그인 루트입니다. `--target <경로-또는-디렉터리>`
   로 다른 곳을 지정하거나 `--dry-run` 으로 미리 볼 수도 있습니다. 파일을 직접
   편집하고 싶으면 아래 [수동 allowlist](#수동-allowlist--스크립트가-하는-일) 를 보세요.

4. **세션 재시작 후 스모크 테스트.** 플러그인 skill 과 설정 allowlist 는 세션
   시작 시 로드되므로 Claude Code 를 한 번 reload / 재시작하세요. 그다음 평소
   턴에서 leader 에게 요청합니다:

   > triad-codex-dispatch 로 codex 에게 물어봐: `git rebase --onto` 는 무슨 일을 해? 한 문단으로.

   답 + stderr 의 `[wrapper] <cli> ok …` 줄이 보이면 설치가 살아 있는 것입니다.
   (`triad-antigravity-dispatch` 로 바꾸면 `agy` leg 입니다.)

이게 필수 경로의 전부입니다. repair 는 자동이라 설정이 필요 없습니다: 인식 안 된
실패 시 leader 가 분류기를 대신 자기개선합니다(자세히는
[동작 원리](#동작-원리-how-it-works) 와 [보안](#보안-security)).

## 선택 / 고급

이 섹션의 어떤 것도 일반 설치에는 필요 없습니다. 각 하위 섹션의 "다음 경우에만
하세요…" 조건이 해당될 때만 보세요.

### 2번째 / 3번째 worker CLI 추가

*크로스-패밀리 리뷰를 원할 때만*(worker 하나 + claude leg 대신 세 독립 패밀리).
step 1 과 같은 방식으로 다른 CLI 를 설치 + 로그인합니다: `codex login`; `agy`
OAuth 로그인; 또는 `gemini` 조직 로그인(엔터프라이즈 / 조직 계정 전용).
`triad-cross-family-review` 가 Google-family leg 를 런타임 해소
(`TRIAD_GOOGLE_REVIEW_CLI`, 없으면 agy, 없으면 gemini)하고 claude(`Agent`) +
codex + 그 leg 를 실행합니다.

### Bash 샌드박스를 켤 경우

샌드박스는 **기본 OFF** 이므로 대부분의 설치는 step 3 의 권한 allowlist 만으로
충분합니다. 켠다면(`/sandbox`), 설정 스크립트가 이미 wrapper 를
`sandbox.excludedCommands` 로 면제해 둡니다 — 네트워크와 vendor 인증이 필요하기
때문입니다. vendor API 를 미리 승인하고 fallback 을 두려면
`sandbox.network.allowedDomains` 와 `allowUnsandboxedCommands` 를 직접
추가하세요; [Claude Code 샌드박스 문서](https://code.claude.com/docs/en/sandboxing) 참고.

### 선택: daily drift check

`bin/agy-daily-check.sh` 와 `bin/gemini-daily-check.sh` 는 선택적 drift
detector 입니다 — CLI / 모델 목록 / skill 세트 drift(예: agy 용 Superpowers
출시나 gemini extension/skill 변경)를 확인합니다. 가끔 실행하거나 daily
cron/launchd job 으로 연결하세요; 각각 exit code 를 0(변화 없음),
1(조치 필요), 2(정보성)로 나눕니다. 일반 사용에는 필요 없습니다 — 정확한
동작은 스크립트 자체의 헤더 주석을 참고하세요.

### 권장 동반 도구 — Superpowers

*implementer / TDD / 리뷰 워크플로 skill 을 원할 때만.* Superpowers 는 이 툴킷과
잘 맞는 동반 skill 세트입니다. 자체 마켓플레이스로 설치
(`/plugin marketplace add https://github.com/obra/superpowers` 후
`/plugin install superpowers`)하거나 해당 README 를 따르세요:
https://github.com/obra/superpowers .

- **codex**: 권장 — codex `--task code` 모드는 Superpowers 의 implementer
  서브에이전트를 본떴고, `triad-cross-family-review` 는
  `superpowers:subagent-driven-development` 의 마무리(capstone)입니다.
- **gemini**: 지원 — gemini 는 네이티브 skills (`gemini skills`)를 갖추어
  Superpowers 를 동반 설치합니다. 동봉된 `gemini-daily-check.sh` 가 설치된 skill
  세트를 추적합니다.
- **antigravity (agy)**: Superpowers 는 Antigravity CLI 를 아직 지원하지
  않습니다 — 향후 업데이트가 예정되어 있습니다. `agy-daily-check.sh` 가 매일
  탐지합니다.

### 추가 검증 단계

*step 4 의 스모크 테스트로 부족해 각 계층을 확인하고 싶을 때만.*

- **bin PATH** — `command -v codex_wrapper.py` 가 설치된 플러그인의 `bin/` 아래로
  해소됩니다(자동 PATH 추가; 사용자 조치 불필요).
- **자기개선 분류기** — 인식 안 된 실패 시 해당 wrapper-repair 에이전트의 proposal
  이 `~/.config/triad-dispatch/classifier-patches.json` (홈 디렉터리, 플러그인
  디렉터리 아님)에 적용되고, 그 파일에 엔트리가 생겨 플러그인 업데이트를 가로질러
  보존됩니다.
- **크로스-패밀리 리뷰** — `triad-cross-family-review` 를 실행하면 Google-family
  leg 를 런타임 해소하고 claude(`Agent`) + codex + 그 leg 를 실행합니다.
- **동봉 테스트** — `python3 <plugin-dir>/tests/test_*.py` (stdlib-only).

### 수동 allowlist — 스크립트가 하는 일

*`scripts/setup_permissions.py` 대신 파일을 직접 편집하고 싶을 때만.* 아래
엔트리를 `.claude/settings.json`(또는 `.claude/settings.local.json`)에
추가하세요 — 스크립트가 병합하는 것이 바로 이것입니다:

```json
{ "permissions": { "allow": [
  "Bash(codex_wrapper.py:*)",
  "Bash(gemini_wrapper.py:*)",
  "Bash(antigravity_wrapper.py:*)",
  "Bash(agy-daily-check.sh:*)",
  "Bash(gemini-daily-check.sh:*)"
] } }
```

allowlist 가 없으면 디스패치마다 승인 프롬프트가 뜨고 headless 환경에서는 거부
됩니다. allowlist 등록과 샌드박스는 **직교(orthogonal)** 합니다 — allowlist 에
있다고 해서 Bash 샌드박스에서 면제되지 않습니다.

Bash 샌드박스는 **기본 OFF** 입니다 (`/sandbox` 로 opt-in). 켜면 네트워크가
제한되며, wrapper 는 사용자 인증으로 API 를 호출하는 vendor CLI 를 띄우므로
샌드박스 **밖에서** 실행되어야 합니다. `scripts/setup_permissions.py` 가 이미
이 명령들을 `sandbox.excludedCommands` 에 추가합니다; 수동 형태는:

```json
{ "sandbox": { "excludedCommands": [
  "codex_wrapper.py *",
  "gemini_wrapper.py *",
  "antigravity_wrapper.py *"
] } }
```

### 로컬 설치 (빌드한 폴더에서 직접)

*publish 전에 로컬 빌드본을 테스트할 때만.* `marketplace add` 에 플러그인 디렉터리
자체를 지정하세요 — **git repo 불필요** (디렉터리의
`.claude-plugin/marketplace.json` 이 읽히고, 그 상대경로 `source` 는 로컬-디렉터리
add 시 정상 해소). 경로는 절대경로이거나 `./` 로 시작해야 합니다:

```
/plugin marketplace add /absolute/path/to/triad-dispatch
/plugin install triad-dispatch@triad-dispatch
```

반드시 깨끗한 작업 디렉터리에서 테스트 — 자체 `.claude/skills/` 나
`agents/` 가 이미 있는 체크아웃 말고. 플러그인 skill/agent 는
네임스페이스됩니다(예: `triad-dispatch:triad-codex-dispatch`). 프로젝트 자체의
동명 `.claude/skills` / `.claude/agents` 가 플러그인 것을 **override** 하므로,
플러그인 자신의 사본을 실제로 동작시키려면 그것들이 없는 디렉터리에서
실행하세요.

### 보안 모델 읽기

*툴킷에 의존하기 전에 전체 threat model 을 보고 싶을 때만.*
[SECURITY.md](SECURITY.md) 참고 — 지속적인 control 은 model trust 가 아니라
privilege separation 입니다(아래 [보안](#보안-security) 에 요약).

### 백그라운드 자동 업데이트 rate limit

*백그라운드 자동 업데이트가 GitHub API rate limit 에 걸릴 때만.* 환경변수
`GITHUB_TOKEN` 을 설정해 한도를 올리세요; 그 외에는 공개 GitHub 로 설치/업데이트가
그대로 동작합니다.

## 문제 해결 (Troubleshooting)

| 증상 | 원인 | 해결 |
|---|---|---|
| 매 디스패치마다 권한 프롬프트가 뜨거나, headless 에서 거부됨 | wrapper `Bash(...)` 명령이 allowlist 에 없음 | [권한 설정](#권한-설정-필수)의 엔트리를 `.claude/settings.json` 에 추가한 뒤 **세션 재시작**(allowlist 는 시작 시 로드). |
| 설치 뒤 새 skill/agent 가 안 뜸 | 플러그인 skill 은 세션 시작 시 로드 | 설치 + 설정 편집 뒤 Claude Code 세션을 한 번 reload / 재시작. |
| 디스패치가 `oauth-env` 로 실패 | 워커 CLI 의 로그인이 만료됐거나 없음 | 해당 vendor 의 native login 재실행(`codex login`, 또는 `agy` OAuth 로그인). wrapper 는 대신 재인증하지 않습니다 — 신호만 surface 하니 직접 로그인하세요. |
| gemini leg 이 `IneligibleTier` 로 실패(개인 계정) | Gemini CLI *개인* tier 폐지 | `agy`(Antigravity) leg 을 대신 사용하세요 — 개인 사용자의 Google-family leg 입니다. `gemini` 는 엔터프라이즈 / 조직 계정 전용. |
| 디스패치가 non-zero 로 끝났고 원인을 알고 싶음 | 각 실패에는 분류 + exit code 가 있음 | 아래 exit-code 범례 + `[wrapper] …` stderr 줄의 분류를 보세요. |

**Exit-code 범례**(wrapper 프로세스 exit code; 같은 실패 class 가
`[wrapper] <cli> <class> …` stderr 줄의 단어로도 나타납니다):

| Exit | 의미 | 조치 |
|---|---|---|
| `0` | 성공 — 이어서 답변 | 없음. |
| `64` | 재시도 후에도 server capacity 소진 | 일시적 vendor 과부하; 기다렸다 재시도. |
| `65` | 인증 / config / quota(예: `oauth-env`, `cli-subscription-cap`) | 재로그인하거나 quota reset 대기 — 분류 단어 참고. |
| `66` | 구조화 출력(`--pydantic`) 스키마 검증 실패 | 1회 repair 재시도 후에도 모델 JSON 이 스키마 불일치. |
| `69` | code task 가 blocked / 컨텍스트 부족(codex `--task code`) | 부족한 컨텍스트를 채워 재디스패치. |

## 범위와 한계 — 이 도구가 하지 않는 것

플러그인이 어디서 멈추는지 알 수 있도록, 정직한 경계:

- **vendor 인증이나 token 을 관리하지 않습니다.** token 발급/refresh 없음, API-key
  주입 없음. 각 vendor CLI 의 native login 으로 직접 로그인하며, 인증성 에러는
  재로그인하라고 surface 됩니다. credential 을 toolkit 밖에 두는 것 자체가 의도된
  safety boundary 입니다.
- **OS 패키지를 설치하지 않습니다.** vendor CLI 와 `python3` 는 직접 설치하며,
  플러그인은 PATH 에 이미 있는 것을 오케스트레이션만 합니다.
- **자기개선 분류기는 heuristic 이지 oracle 이 아닙니다.** 진짜 실패를
  그럴듯하지만 틀린 class 로 라우팅할 수 있습니다. worst case 는 *integrity* 이슈 —
  지속적 라우팅 오분류이지 코드 실행이 **아닙니다**([보안](#보안-security) 참고) —
  이지만, `~/.config/triad-dispatch/classifier-patches.json` 에 적용된 delta 를
  주기적으로 검토하세요.
- **wrapper containment 은 프로세스/권한 수준이지 OS 수준 confinement 이 아닙니다.**
  read-only 리뷰 leg 은 *알려진* agy 도구 표면에 대한 fs-write denylist 를
  강제하지만, sandbox jail 은 아닙니다. 격리는 궁극적으로 격리된 작업
  디렉터리 + 커밋 전 사용자 검토에 의존합니다.

## 동작 원리 (How it works)

위의 가치가 이해된 뒤 살펴보는 메커니즘:

- **Leader / worker.** 내 Claude Code 세션이 *leader* 입니다. 외부 의견이 필요하면
  *worker* — `codex`, `gemini`, `agy` 로의 단발 호출 — 를 skill 을 통해
  디스패치하고, 답 하나를 받아 계속 진행합니다. worker 는 내 세션 기억이 없습니다;
  그 프롬프트 하나에만 답합니다.
- **분류 기반 라우팅.** 모든 디스패치는 raw 쉘 호출이 아니라 skill 을 거칩니다.
  wrapper 가 결과에 *분류*(`ok`, 또는 `oauth-env` / `server-capacity` 같은 명명된
  실패)를 태그하므로, leader 가 raw 출력으로 추측하지 않고 정확히 반응합니다.
- **자기개선 분류기.** 실패가 알려진 class 에 안 맞으면, read-only analyzer 가 새
  규칙 하나를 제안하고 leader 가 결정적으로 적용합니다. 다음 동일 실패는 자동
  라우팅됩니다. 이 상태는 홈 디렉터리에 저장되어 플러그인 업데이트를 가로질러
  지속됩니다.
- **크로스-패밀리 리뷰(머지 게이트).** 위험한 변경에는 leader 가 세 패밀리에 동시에
  fan-out 하고 — 각각 독립 리뷰어 — 판정을 종합합니다. *leg* 은 그 fan-out 에서 한
  패밀리의 몫을 뜻할 뿐입니다.

## 권장 사용법 (Recommended usage)

leader 와 오너가 실제로 사용하는 방식:

- Claude Code **leader** 는 자기 컨텍스트 밖의 답이 필요할 때 단발 워커를
  디스패치합니다: `triad-codex-dispatch` (codex), `triad-gemini-dispatch`
  (gemini), 또는 `triad-antigravity-dispatch` (agy). 직접 raw 로 쉘을 띄우지
  **않습니다** — SKILL 이 분류 라우팅과 자기개선 repair fallback 을 처리합니다.
- **agy = 검색 / 리서치 특화** — agy 의 웹 `read_url` / `search_web` 는 항상
  허용됩니다. 웹 기반 조회에는 반드시 agy 를 포함하세요.
- 리뷰 가치가 있거나 정확성이 중요한 작업을 머지하기 전, leader 는
  **`triad-cross-family-review`** 를 실행합니다 (the cross-family review rule): 서로 다른
  모델 패밀리의 독립 리뷰어 셋 — claude fresh-eye `Agent` 서브에이전트 + codex
  + Google-family CLI (agy 또는 gemini, 런타임 선택) — 가 각각 의심 결정을
  질문 형태로 제기하고, leader 가 판정을 종합해
  수정 → 재확인을 만장일치 SAFE 가 될 때까지 반복합니다.
- 분류기는 **자기개선**합니다: 인식되지 않은 에러는 wrapper-repair 에이전트로
  라우팅되어 영속 확장 JSON 에 패턴을 추가하고, 이후 동일한 에러는 자동으로
  라우팅됩니다.

## 사용 시나리오 (Usage scenarios)

1. **codex 단발 호출** — leader 가 개별 프롬프트에 대한 codex 의 답이 필요할 때
   → `triad-codex-dispatch`. codex 의 답(분류는 stderr)을 반환하며, `unknown`
   실패는 `codex-wrapper-repair` 에이전트로 자동 라우팅됩니다.
2. **gemini 단발 호출** — Android/XML/vision 또는 Google 생태계 프롬프트 →
   `triad-gemini-dispatch`.
3. **agy 를 통한 웹 리서치** — 웹 기반 조회 → `triad-antigravity-dispatch`
   (agy 의 `read_url` 은 항상 허용). 검색에는 항상 agy 를 포함하세요.
4. **구조화된 출력** — 검증된 JSON 이 필요할 때 → wrapper 의
   `--pydantic module:Class` (프롬프트로 JSON 지시 + 검증 + 1회 repair 재시도;
   스키마 실패 시 exit 66).
5. **머지 전 크로스-패밀리 리뷰** — 위험한 변경을 머지하기 직전 →
   `triad-cross-family-review` (claude + codex + Google-family CLI — agy 또는
   gemini, 런타임 선택; SAFE 가 될 때까지 수정 → 재확인).

## 자기개선 (영속)

분류기는 `~/.config/triad-dispatch/classifier-patches.json` 를 통해 플러그인
업데이트를 가로질러 학습합니다 — 사용자 홈 디렉터리에 있으므로 **플러그인
업데이트에도 살아남습니다** (휘발성 플러그인 디렉터리가 아님). repair
서브에이전트가 새 `error → class` 엔트리를 제안하고 leader 가
`bin/apply_patch.py` 로 적용하며, 엔진이 런타임에 병합합니다. 이식 가능 — 팀이
큐레이션하고 공유할 수 있습니다.

## 보안 (Security)

지속적인 control 은 model trust 가 아니라 **privilege separation** 입니다.
분류기는 untrusted vendor run-log 에서 학습하므로, run-log 를 읽는 컴포넌트는
write 권한이 0 입니다: 세션 내 repair 에이전트는 READ-ONLY analyzer
(harness 가 `Read, Grep, Glob` 만 허용 — Write/Edit/Bash/network 없음)로,
유일한 출력은 inline proposal 이고 leader 가 결정적 zero-LLM `bin/apply_patch.py`
로 적용합니다. "model 이 injection 에 저항한다"는 경계가 **아닙니다**. wrapper 는
인증을 관리하지 않습니다. 전체 threat model 과 per-product 집행:
[SECURITY.md](SECURITY.md).

## 런타임 산출물과 정리

Wrapper telemetry는 로컬에 남지만 크기가 제한됩니다. 파일은 wrapper family별로
`bin/_logs/<cli>/` 아래에 생깁니다(`codex`, `gemini`, `antigravity`).

- `audit.jsonl`은 active file이 10 MB를 넘으면 rotate하고, CLI당 archive는
  최대 5개 / 50 MB까지만 유지합니다.
- 실패 IPC run log는 `bin/_logs/<cli>/runs/*.json`에 생깁니다. 파일명에는 UTC
  timestamp, process id, 8자 random UUID suffix가 들어가므로 병렬 dispatch끼리
  충돌하지 않습니다.
- 정상 dispatch cleanup은 repair agent가 끝난 뒤 run log와 대응되는
  `.repair.json`을 지웁니다.
- wrapper failsafe는 run log를 CLI당 100개 / 20 MB로 제한하고, 다음 normal
  dispatch 시작 시 7200초보다 오래된 run log와 `.repair.json`을 sweep합니다.

Classifier patch는 `~/.config/triad-dispatch/classifier-patches.json`에 남습니다.
repair agent는 이 파일을 고치기 전 옆의 lock file을 사용하므로 병렬 repair 간
덮어쓰기가 일어나지 않습니다.

## 구성 (What's inside)

- **skills** (4): `triad-codex-dispatch`, `triad-gemini-dispatch`,
  `triad-antigravity-dispatch`, `triad-cross-family-review`.
- **agents** (3): `codex-wrapper-repair`, `gemini-wrapper-repair`, `agy-wrapper-repair`.
- **bin**: Python wrapper 들 (codex / gemini / agy) + `agy-daily-check.sh` +
  `gemini-daily-check.sh` + `policies/gemini-readonly.toml` (gemini `--sandbox
  read-only` 모드가 per-call 로 부착하는 read-only Policy Engine 파일).
- **tests**: stdlib-only wrapper 테스트 — 설치 검증에 그대로 사용:

  ```bash
  python3 tests/test_gemini_sandbox.py   # 6 checks — gemini sandbox argv 계약
  python3 tests/test_log_cleanup.py      # 2 checks — log prune + audit rotation
  ```

- **migration**: `CLAUDE.recommended.md` — 이 toolkit 이 전제하는 작업 관행
  (pre-execution discipline, cross-family review, artifact 이식성) 을 담은
  starter CLAUDE.md.
