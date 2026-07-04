> 🌐 **English: [README.md](./README.md)**

# triad-dispatch

Claude Code **leader** 를 위한 단발(single-shot) 크로스-CLI 디스패치 도구.
**codex**, **gemini**, **antigravity (agy)** 를 단발 워커로 디스패치하며, 분류
기반(classification-aware) 라우팅 + 자기개선 분류기 + 머지 전 크로스-패밀리
리뷰를 제공합니다.

## 요구사항 (Requirements)

- **vendor CLI 설치 + 인증** — wrapper 는 인증을 직접 관리하지 않습니다:
  - `codex` 설치 후 `codex login`.
  - **Google-family leg — 사용하는 Gemini 액세스에 맞춰 선택:**
    - **개인(individual) Gemini 액세스 → `agy` (Antigravity)** 설치 + OAuth 로그인.
      Gemini CLI *개인* tier 는 폐지(Google 이 Antigravity 스위트로 이전)되어, 개인
      사용자의 Google-family leg 는 agy 입니다.
    - **엔터프라이즈 / 조직(organization) Gemini 액세스 → `gemini` (Gemini CLI)**
      설치 + 조직 로그인. **엔터프라이즈** Gemini tier 는 계속 사용됩니다(개인-tier
      폐지의 영향 없음); 이 경우 agy 가 아니라 `gemini` 를 사용합니다.
  - 리뷰의 claude leg 는 세션 내 `Agent` 서브에이전트입니다 — 별도 설치 불필요.
- **`python3 >= 3.12`** 가 PATH 에 있어야 합니다 (`bin/` wrapper 는
  `#!/usr/bin/env python3` 로 실행).

## 설치 (Install)

```
/plugin marketplace add codefoundry-io/triad-dispatch
/plugin install triad-dispatch@triad-dispatch
```

저장소가 공개(public)이므로 설치에 별도 인증이 필요 없습니다. 백그라운드
자동 업데이트도 공개 GitHub 로 그대로 동작하며, 환경변수 `GITHUB_TOKEN` 는
API rate limit 을 올리려는 경우에만 설정하면 됩니다.

**로컬 설치 (빌드한 폴더에서 직접).** 저장소에 publish 하기 전에
로컬 빌드본을 테스트하려면 `marketplace add` 에 플러그인 디렉터리 자체를
지정하세요 — **git repo 불필요** (디렉터리의 `.claude-plugin/marketplace.json`
이 읽히고, 그 상대경로 `source` 는 로컬-디렉터리 add 시 정상 해소). 경로는
절대경로이거나 `./` 로 시작해야 합니다:

```
/plugin marketplace add /absolute/path/to/triad-dispatch
/plugin install triad-dispatch@triad-dispatch
```

**반드시 깨끗한 작업 디렉터리에서 테스트** — 자체 `.claude/skills/` 나
`agents/` 가 이미 있는 체크아웃 말고. 플러그인 skill/agent 는
네임스페이스됩니다(예: `triad-dispatch:triad-codex-dispatch`). 프로젝트
자체의 동명 `.claude/skills` / `.claude/agents` 가 플러그인 것을 **override**
하므로, 플러그인 자신의 사본을 실제로 동작시키려면 그것들이 없는
디렉터리에서 실행하세요.

## 권한 설정 (필수)

플러그인은 Bash 권한을 **부여할 수 없습니다**. 따라서 사용자가 직접
`.claude/settings.json` (또는 `.claude/settings.local.json`) 에 추가합니다:

```json
{ "permissions": { "allow": [
  "Bash(codex_wrapper.py:*)",
  "Bash(gemini_wrapper.py:*)",
  "Bash(antigravity_wrapper.py:*)",
  "Bash(agy-daily-check.sh:*)",
  "Bash(gemini-daily-check.sh:*)"
] } }
```

이 설정이 없으면 디스패치마다 승인 프롬프트가 뜨고, headless 환경에서는 호출이 거부됩니다.
이 명령들은 **네트워크 송신(egress)** 이 필요합니다 — wrapper 가 vendor CLI 를
띄우고 그 CLI 가 API 를 호출하기 때문입니다 — 그러므로 네트워크 없는 Bash
샌드박스 안에서 실행하지 마세요.

## 설치 검증 (Verify)

설치 + 권한 allowlist 후, 플러그인이 살아있는지 확인:

1. **bin PATH** — Bash tool 호출에서 `command -v codex_wrapper.py` 가 설치된
   플러그인의 `bin/` 아래로 해소됩니다(자동 PATH 추가; 사용자 조치 불필요).
2. **단발 디스패치** — leader 가 사소한 프롬프트로 `triad-codex-dispatch`
   (또는 `triad-gemini-dispatch`) 사용 → 답 + stderr 의
   `[wrapper] <cli> ok …` 요약 줄 확인.
3. **자기개선 분류기** — 인식 안 된 실패 시 해당 wrapper-repair 에이전트가
   `~/.config/triad-dispatch/classifier-patches.json` (홈 디렉터리, 플러그인
   디렉터리 아님)에 패턴을 추가 → 그 파일에 엔트리가 생기고 플러그인
   업데이트를 가로질러 보존됩니다.
4. **크로스-패밀리 리뷰** — `triad-cross-family-review` 가 Google-family leg
   를 런타임 해소(`TRIAD_GOOGLE_REVIEW_CLI`, 없으면 agy, 없으면 gemini)하고
   claude(`Agent`) + codex + 그 leg 를 실행.

## 권장 동반 도구 — Superpowers

링크: https://github.com/obra/superpowers . 마켓플레이스로 설치
(`/plugin marketplace add https://github.com/obra/superpowers` 후
`/plugin install superpowers`) 하거나, 해당 README 를 따르세요.

- **codex**: Superpowers **권장** — 설치하세요. 이 툴킷의 codex `--task code`
  는 Superpowers 의 implementer 서브에이전트를 본떴고,
  `triad-cross-family-review` 는 `superpowers:subagent-driven-development` 의
  마무리(capstone)입니다.
- **gemini**: Superpowers **지원** — gemini 는 네이티브 skills (`gemini skills`)
  를 갖추고 있으므로 Superpowers 를 동반 설치하세요. 동봉된
  `gemini-daily-check.sh` 가 설치된 skill 세트(superpowers 포함)를 추적합니다.
- **antigravity (agy)**: Superpowers 는 Antigravity CLI 를 **아직 지원하지
  않습니다** — **향후 업데이트가 예정**되어 있습니다. `agy-daily-check.sh` 가
  매일 "superpowers-for-agy" 릴리스를 탐지합니다.

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
서브에이전트가 새 `error → class` 엔트리를 추가하고, 엔진이 런타임에 병합합니다.
이식 가능 — 팀이 큐레이션하고 공유할 수 있습니다.

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
