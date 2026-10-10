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
   실행)와, cross-family review 의 **jsonschema** (Draft 2020-12;
   Mac `pip3 install jsonschema`, Ubuntu 24.04 `apt install python3-jsonschema`) — 없으면
   review helper 가 exit 64 와 그 설치 안내로 멈춥니다 — 그리고 플러그인 마켓플레이스 + 네임스페이스 플러그인 skill 을
   지원할 만큼 **최신 Claude Code** 가 필요합니다. claude 리뷰 leg 는 세션 내
   `Agent` 이므로 별도 로그인이 필요 없습니다. **pydantic 2.x**
   (`'pydantic>=2,<3'`, 그 `python3` 로 import 가능) 는 wrapper 에
   `--pydantic module:Class` 를 넘기는 호출자에게만 필요합니다 (스키마 검사가 v2
   전용 API 를 씁니다).

   > **Ubuntu 24.04 주의.** `apt install python3-pydantic` 은 **1.10** 이라 동작하지
   > 않고, PEP 668 로 시스템 인터프리터가 externally-managed 이므로 `pip3 install
   > --user` 도 실패합니다. apt 의 `python3-jsonschema` 가 그대로 보이는
   > venv 를 쓰세요 — `python3 -m venv --system-site-packages ~/.venvs/triad &&
   > ~/.venvs/triad/bin/pip install 'pydantic>=2,<3'` (venv 의 pydantic 2 가 `sys.path`
   > 에서 먼저 옵니다) — 그리고 Claude Code 를 띄우는
   > 셸에서 그 venv 를 activate 해야 `#!/usr/bin/env python3` 가 venv 인터프리터로
   > 해석됩니다. 인덱스 대신 로컬 wheel 세트로 설치하려면 같은 명령에
   > `--no-index --find-links <wheel-dir>` 를 붙이세요. **그 세트는 3개가 아니라 5개**
   > 입니다 — pydantic 2.x 런타임 의존 closure 전부:
   > `pydantic-2.x-py3-none-any.whl` + `pydantic_core-*-cp312-*manylinux*.whl`
   > (pydantic 릴리스마다 `==` 고정) + `typing_extensions-*.whl` +
   > `annotated_types-*.whl` (>= 0.6) + `typing_inspection-*.whl` (>= 0.4.2,
   > pydantic 2.10 부터 필수).
   > `pip download 'pydantic>=2,<3' --only-binary=:all: --platform
   > manylinux_2_17_x86_64 --python-version 312 -d <dir>` 가 정확히 그 세트를
   > 떨굽니다.

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
   엔트리를 중복 없이 병합합니다). `<plugin-dir>` 는 설치된 플러그인의 버전
   디렉터리 `~/.claude/plugins/cache/<marketplace>/triad-dispatch/<version>/`
   입니다(`<marketplace>` = `marketplace add` 때 준 이름;
   `ls -d ~/.claude/plugins/cache/*/triad-dispatch/*/` 로 확인). `--target <경로-또는-디렉터리>`
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
(항목의 `google.route` 고정, 없으면 그 항목에 하나뿐인 route 블록, 없으면 agy, 없으면 gemini)하고 claude(`Agent`) +
codex + 그 leg 를 실행합니다.

### claude 리뷰 leg 의 모델과 effort 고르기

*`triad-cross-family-review` 의 claude leg 를 기본값과 다른 effort 로 돌리고 싶을
때만.* 이 leg 는 Claude Code 의 native subagent 로 돌고, 모델과 effort 는 그 agent
파일에 고정되어 있습니다. Claude Code 에는 호출마다 effort 를 정하는 설정이 없으므로,
다른 effort 는 다른 preset 입니다. 플러그인이 제공하는 preset (각각 같은 모델·effort 의
`-web` 쌍이 있고, 웹을 쓰는 리뷰 라운드는 그 쌍을 띄웁니다):

| `claude.agent` | 모델 | effort |
|---|---|---|
| `cross-family-review-reviewer` (기본값) | `opus` | `xhigh` |
| `cross-family-review-reviewer-high` | `opus` | `high` |
| `cross-family-review-reviewer-max` | `opus` | `max` |

모델은 `opus` 별칭입니다: 구독 로그인 경로에서 Claude Code 가 최신 Opus 로 해석합니다
(`ANTHROPIC_DEFAULT_OPUS_MODEL` 설정이 있으면 그 값으로 바뀝니다). 이전 모델은 고를 수
없습니다.

프로젝트 roster `<repo>/.claude/triad-review-legs.json` 의 claude 항목에 하나를
적으세요. 예:
`{"schema": "triad-review-legs.v2", "legs": [{"name": "claude", "claude": {"agent": "cross-family-review-reviewer-high"}}]}`.
이름은 접두어 없이 적습니다: 플러그인 접두어는 helper 가 붙이고, `:` 가 든 이름이나
제공 preset 6개 (위 3개와 각각의 `-web` 쌍) 에 없는 이름은 라운드가 시작되기 전에
거부됩니다. 그 밖의 모델이나 effort 는 새 preset, 곧 새 플러그인 릴리스가 필요합니다.
사용자 자신의 Claude Code 설정 — subagent 모델을 강제하는 설정, effort 환경변수, 조직의
effort 상한 — 은 preset 의 고정값보다 우선합니다. 각 subagent 의 대화 기록은 Claude Code 가
따로 남기므로 플러그인은 그에 대한 로그를 더하지 않습니다.

### Bash 샌드박스를 켤 경우

샌드박스는 **기본 OFF** 이므로 대부분의 설치는 step 3 의 권한 allowlist 만으로
충분합니다. 켠다면(`/sandbox`), 설정 스크립트가 이미 wrapper 를
`sandbox.excludedCommands` 로 면제해 둡니다 — 네트워크와 vendor 인증이 필요하기
때문입니다. vendor API 를 미리 승인하고 fallback 을 두려면
`sandbox.network.allowedDomains` 와 `allowUnsandboxedCommands` 를 직접
추가하세요; [Claude Code 샌드박스 문서](https://code.claude.com/docs/en/sandboxing) 참고.

### 권장 동반 도구 — Superpowers

*implementer / TDD / 리뷰 워크플로 skill 을 원할 때만.* Superpowers 는 이 툴킷과
잘 맞는 동반 skill 세트입니다. 자체 마켓플레이스로 설치
(`/plugin marketplace add https://github.com/obra/superpowers` 후
`/plugin install superpowers`)하거나 해당 README 를 따르세요:
https://github.com/obra/superpowers .

- **codex**: 권장 — `triad-cross-family-review` 는
  `superpowers:subagent-driven-development` 의 마무리(capstone)입니다.
- **gemini**: 지원 — gemini 는 네이티브 skills (`gemini skills`)를 갖추어
  Superpowers 를 동반 설치합니다.
- **antigravity (agy)**: Superpowers 는 Antigravity CLI 를 아직 지원하지
  않습니다 — 향후 업데이트가 예정되어 있습니다.

### 추가 검증 단계

*step 4 의 스모크 테스트로 부족해 각 계층을 확인하고 싶을 때만.*

- **플러그인 경로** — 디스패치 skill 은 각 `bin/` 파일을
  `python3 ${CLAUDE_PLUGIN_ROOT}/bin/<file>` 로 실행합니다; Claude Code 가 skill 을
  로드할 때 설치된 플러그인 디렉터리를 채워 넣습니다(사용자 조치 불필요).
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
추가하세요 — 스크립트가 병합하는 `permissions.allow` 엔트리가 이것입니다. 스크립트는
이 밖에도 `sandbox.excludedCommands`, hardening `env` 블록, sidecar 파일 하나를
씁니다
([이 플러그인이 쓰는 파일](#이-플러그인이-쓰는-파일) 참고):

```json
{ "permissions": { "allow": [
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/codex_wrapper.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/gemini_wrapper.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/antigravity_wrapper.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/apply_patch.py *)",
  "Bash(env TRIAD_REVIEW_LOG_DIR=* python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/codex_wrapper.py *)",
  "Bash(env TRIAD_REVIEW_LOG_DIR=* python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/gemini_wrapper.py *)",
  "Bash(env TRIAD_READ_AUDIT_FILE=* env TRIAD_REVIEW_LOG_DIR=* python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/antigravity_wrapper.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/review_scratch.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/verdict_v2.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/agy_hook.py *)",
  "Bash(python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/roster_v2.py *)",
  "Bash(bash <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/read_audit_gate.sh *)"
] } }
```

앞의 네 개는 디스패치 skill 이 실행하는 명령, 다음 세 개는 리뷰 skill 의 leg 줄
(`env` 접두가 붙어 규칙이 따로 필요함), 마지막 다섯 개는 리뷰 skill 이 실행하라고
안내하는 리뷰 라이브러리 파일입니다(read-audit gate 스크립트는 `bash` 로 실행).
`<home>` 은 홈 디렉터리의 절대 경로로, `<marketplace>` 는 `marketplace add` 때 준
이름으로 바꿔 쓰세요; `triad-dispatch/` 뒤의 `*` 는 플러그인 버전 자리라 업데이트
뒤에도 엔트리가 유지됩니다. 와일드카드가 두 개인 규칙은 인자가 붙은 명령에만
맞습니다 — 인자 없는 `python3 …/codex_wrapper.py` 는 여전히 프롬프트가 뜨며,
skill 이 실행하는 디스패치는 모두 인자를 붙입니다.
기록된 한계: skill 은 플러그인 경로를 따옴표 없이 씁니다(따옴표로 감싼 경로는 이
규칙에 맞지 않음). 그래서 홈 디렉터리 경로에 공백이 있으면 호출이 깨지며, 이는
처리하지 않습니다. 또 `~/.claude` 나 홈 디렉터리가 심볼릭 링크이면 grant 는 해소된
실제 경로를 담으므로, 해소되지 않은 경로로 입력된 디스패치는 프롬프트가 뜹니다 —
배치를 고친 뒤 `--install` 을 다시 실행하거나 해소되지 않은 형태를 직접 추가하세요.
그리고 리뷰 leg 의 렌더링된 줄은 셸 리다이렉션(`> verdict.json 2> stderr.log`)을
noclobber 로 보호된 subshell 안에 담고 있고, claude leg 의 `guard:` 줄은 grant 가
없는 셸 내장 명령입니다. Claude Code 는 이런 부분을 모든 Bash 규칙과 별개로
승인하므로, 설치된 환경의 리뷰 라운드는 leg 마다 한 번(leg 당 Bash 호출 하나)
승인을 묻습니다(리다이렉션은 2026-10-11 측정; subshell 과 내장 명령 부분은 측정하지
않음).
leader 가 쓰는 prompt / proposal 파일은 `<project>/_runs/prompts/` 아래에 있습니다;
`_runs/` 가 아직 무시되지 않는다면 프로젝트 `.gitignore` 에 추가하세요.
allowlist 가 없으면 디스패치마다 승인 프롬프트가 뜨고 headless 환경에서는 거부
됩니다. allowlist 등록과 샌드박스는 **직교(orthogonal)** 합니다 — allowlist 에
있다고 해서 Bash 샌드박스에서 면제되지 않습니다.

Bash 샌드박스는 **기본 OFF** 입니다 (`/sandbox` 로 opt-in). 켜면 네트워크가
제한되며, wrapper 는 사용자 인증으로 API 를 호출하는 vendor CLI 를 띄우므로
샌드박스 **밖에서** 실행되어야 합니다. `scripts/setup_permissions.py` 가 이미
이 명령들을 `sandbox.excludedCommands` 에 추가합니다; 수동 형태는:

```json
{ "sandbox": { "excludedCommands": [
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/codex_wrapper.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/gemini_wrapper.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/antigravity_wrapper.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/apply_patch.py *",
  "env TRIAD_REVIEW_LOG_DIR=* python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/codex_wrapper.py *",
  "env TRIAD_REVIEW_LOG_DIR=* python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/gemini_wrapper.py *",
  "env TRIAD_READ_AUDIT_FILE=* env TRIAD_REVIEW_LOG_DIR=* python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/bin/antigravity_wrapper.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/review_scratch.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/verdict_v2.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/agy_hook.py *",
  "python3 <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/roster_v2.py *",
  "bash <home>/.claude/plugins/cache/<marketplace>/triad-dispatch/*/skills/triad-cross-family-review/lib/read_audit_gate.sh *"
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
  모델 패밀리의 독립 리뷰어 셋 — claude fresh-eye 서브에이전트 (이름으로 고르는
  제공 reviewer preset; 위 "claude 리뷰 leg 의 모델과 effort 고르기" 참고) + codex
  + Google-family CLI (agy 또는 gemini, 런타임 선택) — 가 각각 의심 결정을
  질문 형태로 제기하고, leader 가 판정을 종합해
  수정 → 재확인을 만장일치 SAFE 가 될 때까지 반복합니다.
- 분류기는 **자기개선**합니다: 인식되지 않은 에러는 읽기 전용 wrapper-repair
  분석 에이전트로 라우팅되어 run-log 의 측정된 문장으로 엔트리 하나를 제안하고,
  leader 가 `bin/apply_patch.py` 로 영속 확장 JSON 에 적용하면 이후 동일한
  에러는 자동으로 라우팅됩니다.

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
큐레이션하고 공유할 수 있습니다. 적용 단계가 출력하는 세 줄을 메인테이너에게 보내면
메인테이너가 학습된 문구를 배포 목록으로 승격합니다.

## 보안 (Security)

지속적인 control 은 model trust 가 아니라 **privilege separation** 입니다.
분류기는 untrusted vendor run-log 에서 학습하므로, run-log 를 읽는 컴포넌트는
write 권한이 0 입니다: 세션 내 repair 에이전트는 READ-ONLY analyzer
(harness 가 `Read, Grep, Glob, WebSearch, WebFetch` 만 허용 — Write/Edit/Bash 없음, web 도구는 제한된 조사 규칙에만 사용)로,
유일한 출력은 inline proposal 이고 leader 가 결정적 zero-LLM `bin/apply_patch.py`
로 적용합니다. "model 이 injection 에 저항한다"는 경계가 **아닙니다**. wrapper 는
인증을 관리하지 않습니다. 전체 threat model 과 per-product 집행:
[SECURITY.md](SECURITY.md).

## 런타임 산출물과 정리

Wrapper telemetry는 로컬에 남고, 정리 설정(`bin/cleanup-roots.default.json`, 또는 프로젝트의
`.claude/triad-cleanup.json`)이 선언한 폴더 안에서 role별 floor에 따라 wrapper 자신의 코드만
지웁니다. 파일은 wrapper family별로 `bin/_logs/<cli>/` 아래에 생깁니다(`codex`, `gemini`,
`antigravity`).

- `audit.jsonl`은 active file이 크기 상한을 넘으면 rotate하고, rotate할 때 개수 / byte
  상한을 넘는 archive를 가장 오래된 것부터 지웁니다.
- run log는 `bin/_logs/<cli>/runs/*.json`에 실패한 호출마다 하나 생깁니다(리뷰 attempt는
  모든 호출마다 자기 attempt 폴더 안에 씁니다). 파일명에는 UTC
  timestamp, process id, 8자 random UUID suffix가 들어가므로 병렬 dispatch끼리
  충돌하지 않습니다.
- repair loop 뒤에 run log를 지우는 단계는 없습니다: 다음 normal dispatch가 role의 floor를
  넘은 run log를 sweep하고, cap prune이 개수 / byte 상한을 넘는 것을 가장
  오래된 것부터 지웁니다. floor보다 새 파일은 지우지 않으므로 run log 디렉터리(그리고
  read-audit 디렉터리)는 cap을 넘은 채로 남을 수 있습니다 — cap이 디스크가 차는 것을 막지는
  않습니다.

Classifier patch는 `~/.config/triad-dispatch/classifier-patches.json`에 남습니다.
repair agent는 이 파일을 고치기 전 옆의 lock file을 사용하므로 병렬 repair 간
덮어쓰기가 일어나지 않습니다.

### 이 플러그인이 쓰는 파일

아래의 `~/.config` 는 `$XDG_CONFIG_HOME` 이 절대 경로로 설정되어 있으면 그
경로입니다 (config home). 상대 경로인 `XDG_CONFIG_HOME` 은 wrapper 가 wrapper 명령을
실행한 디렉터리를 기준으로 해석합니다. 제거 단계는 그곳에서 아무것도 지우지
않습니다: wrapper 가 그곳에 쓴 것은 남고, 사용자의 것입니다.

| 범위 | 경로 | 쓰는 시점 | 지우는 방법 |
|---|---|---|---|
| 프로젝트 | `.claude/settings.json` — `permissions.allow`, `sandbox.excludedCommands`, `env` (파일이 없었다면 파일 자체도; `--install` 과 `--remove` 는 이전 버전이 쓰고 그 기록에 담긴 `hooks.PreToolUse` 항목도 지움; `--remove` 는 기록된 항목을 지우고 파일을 다시 씀 — 파일과 비게 된 컨테이너는 남음; 직접 비운 hook 그룹은 남음) | `scripts/setup_permissions.py` | 설치 때와 같은 `--target` 으로 `setup_permissions.py --remove` |
| 프로젝트 | `.claude/.triad-dispatch-managed.json` (설정 스크립트가 쓴 내용의 기록; 설치가 쓴 설정 파일 하나의 이름을 담음; 설정 파일보다 먼저 쓰고 설정 파일을 쓴 뒤 마무리하므로, 두 쓰기 사이에서 멈춘 실행은 설정 스크립트를 다시 실행하면 복구됨; 기록만 바꾸는 실행은 기록만 씀) | `scripts/setup_permissions.py` | 설치 때와 같은 `--target` 으로 `setup_permissions.py --remove` |
| 프로젝트 | `_runs/review/<date>-<slug>/` 리뷰 packet 과 라운드별 git worktree | `triad-cross-family-review` gate 마다 | `review_scratch.py close <packet-dir>`; 오래된 packet 은 다음 `open` 이 정리; 비어 있는 `_runs/review/` 디렉터리는 남음 |
| 프로젝트 | codex write 호출용 `_runs/worktrees/<name>/` git worktree (`triad-codex-dispatch` § Write calls; `_runs/worktrees/` 를 프로젝트 `.gitignore` 에 두어 커밋이 트리를 embedded repository 로 담지 않게 함) | 그 문단대로 leader 가 만듦; 멈춘 `cleanup.py remove code-worktrees` 가 남긴 빈 폴더는 그대로 남지만 해롭지 않음 — 같은 이름으로 나중에 `git worktree add` 해도 성공함 (git 2.43.0 과 2.50.1 에서 측정 — git-worktree 매뉴얼은 이를 명시하지 않음) | 트리의 모든 작업을 그 브랜치에 커밋한 뒤 프로젝트 최상위에서 `python3 <plugin-dir>/bin/cleanup.py remove code-worktrees _runs/worktrees/<name>` (커밋되지 않았거나 추적되지 않는 변경이 있는 트리는 거부됨) |
| 프로젝트 | `_runs/prompts/<utc-timestamp>-<cli>.md` 와 `…-<cli>-proposal.json` — 디스패치와 적용하는 repair proposal 을 위해 leader 가 쓰는 prompt / proposal 파일 (`_runs/` 를 프로젝트 `.gitignore` 에 둠) | leader 가 Write tool 로 (디스패치 Step 1, Step 5c) | 파일이 `dispatch-prompts` role 의 floor 보다 오래되면 wrapper 의 다음 실행 sweep (`TRIAD_DISPATCH_PROMPTS_DIR` 가 절대 경로 폴더를 가리키면 그 폴더를 대신 sweep) |
| 머신 | `~/.config/triad-dispatch/classifier-patches.json` 과 `classifier-patches.json.lock` | repair 제안이 적용될 때 | `setup_permissions.py --uninstall-machine` |
| 머신 | `~/.gemini/config/agents/triad-readonly-review.md` 와 `triad-readonly-research.md` | `bin/antigravity_wrapper.py --setup-agents` | `setup_permissions.py --uninstall-machine` |
| 임시 | `$TMPDIR/codex_last_*.txt`, `$TMPDIR/codex_schema_*.json` | codex 디스패치마다 | 호출이 끝날 때 wrapper 가 지움; 공유 임시 디렉터리에 남은 wrapper 이름 형태의 항목은 남고, 사용자의 것임 |
| 플러그인 디렉터리 | `bin/_logs/<cli>/` (audit log, run log, read-audit digest) | 디스패치마다 | 위의 rotation, sweep, cap prune (role 의 floor 보다 새 파일은 남음); 플러그인 디렉터리 삭제 |
| 플러그인 디렉터리 | `bin/_debug/<UTC-date>/` | `--debug` 를 줄 때만 | `wrapper-debug` floor 를 지난 날짜 디렉터리는 다음 `--debug` 호출이 지움; 플러그인 디렉터리 삭제 |

- repair 제안은 classifier 파일에 **자동으로** 적용됩니다. 먼저 묻지 않습니다.
- 플러그인은 다음 디렉터리가 없으면 만들 수 있고, 지우지는 않습니다:
  `<project>/.claude/`, `<project>/_runs/`, config home, `~/.gemini/`,
  `~/.gemini/config/`, `~/.gemini/config/agents/`.
- 환경 변수로 옮긴 위치(`TRIAD_DISPATCH_LOG_DIR`, `TRIAD_DEBUG_DIR`,
  `TRIAD_CLASSIFIER_EXTENSION`, `AGY_AGENTS_DIR`,
  `TRIAD_READ_AUDIT_FILE`)는 사용자의 것이며, 어떤 단계도
  지우지 않습니다. 예외는 `TRIAD_DISPATCH_PROMPTS_DIR` 하나입니다 — prompts sweep 을
  옮기므로, 그 폴더 바로 안에 있는 `dispatch-prompts` floor 보다 오래된 파일은 지워집니다.
  `TRIAD_READ_AUDIT_FILE` 은 호출한 쪽이 정한 read-audit 파일이며,
  리뷰 도우미는 이를 리뷰 packet 안에 두므로 `close` 가 지웁니다.
- 파일을 쓰는 동안에는 비슷한 이름의 임시 파일이 잠깐 옆에 생깁니다. 정상적으로
  끝난 실행은 아무것도 남기지 않습니다.
- 머신 범위의 경로는 이 머신의 모든 triad-dispatch 빌드(두 번째 checkout, 소스
  트리)가 함께 씁니다. 한 빌드를 제거한 뒤에는 다른 빌드에서
  `bin/antigravity_wrapper.py --setup-agents` 를 실행하세요.
- 제거 단계는 심볼릭 링크인 항목과, 심볼릭 링크인 플러그인 이름의 디렉터리
  (`triad-dispatch/`)를 남깁니다. 심볼릭 링크인 상위 디렉터리
  (`~/.config`, `~/.gemini`)는 사용자의 구성입니다: wrapper 가 그 경로를 거쳐
  썼으므로 제거 단계도 그 경로를 거쳐 지웁니다. 제거 단계는 공유 임시 디렉터리에서
  아무것도 지우지 않습니다.
- vendor CLI 자체의 세션·기록 저장소는 플러그인의 것이 아니며, 제거 단계가
  건드리지 않습니다.

### 제거 (Uninstall)

아래 순서대로 실행하세요. 호스트의 플러그인 제거를 먼저 실행해서
`scripts/setup_permissions.py` 가 없어졌다면, 위 '이 플러그인이 쓰는 파일' 표의
경로를 지울 플러그인 코드가 남아 있지 않습니다: 그 경로들은 남고, 사용자의 것입니다.

1. **열린 리뷰 packet 닫기**:
   `python3 <plugin-dir>/skills/triad-cross-family-review/lib/review_scratch.py close <packet-dir>`.
2. **설정 스크립트를 실행했던 프로젝트마다**:
   `--install` 때 준 것과 **같은** `--target` 으로
   `python3 <plugin-dir>/scripts/setup_permissions.py --remove` (프로젝트 루트에서
   설정했다면 `--target` 없이). 설정 스크립트가 쓴 내용의 기록은 설치가 쓴 설정
   파일 하나의 이름을 담고 있어서, 다른 `--target` 을 주면 `--remove` 는 아무것도
   바꾸지 않고 그 파일을 알려 줍니다. 이전 버전이 쓴 기록에는 파일 이름이 없습니다:
   그 내용이 대상 파일에 하나도 없으면 `--remove` 와 `--install` 은 아무것도 바꾸지
   않고 그렇다고 알립니다 — 그 설치가 쓴 `--target` 을 주세요. 내용이 하나도
   보이지 않는 동안 두 명령 모두 그 기록을 지우지 않습니다: 손으로 지운 항목과 같은
   디렉터리의 다른 설정 파일에 있는 항목을 구별할 수 없기 때문입니다. 남은 기록은 사용자의
   것입니다. 설정 파일에 있지만 어떤 기록에도 없는 플러그인의 항목(기록이
   지워졌거나 이전 버전이 쓴 것)은 사용자의 것으로 보며, 두 명령 모두 이를 지우지
   않으니 설정 파일에서 직접 고치세요. 아무 항목도 없는 기록은 설정 파일을 읽을 수
   없을 때도 `--remove` 가 지웁니다. 이전 플러그인 버전이 설정 파일 옆에 남긴 빈
   `.claude/.triad-dispatch.lock` 은 이제 `--remove` 가 건드리지 않으며, 사용자가
   지웁니다. 호스트 제거보다 **먼저** 하세요: 호스트 제거가 이 스크립트를 지웁니다. **이전** 버전이 설정한
   프로젝트에는 그 버전의 디렉터리에 고정된 `hooks.PreToolUse` 항목이 있어서, 호스트가
   그 디렉터리를 지우면 그 프로젝트의 모든 셸 명령이 실패합니다. 플러그인을 업데이트한
   뒤에는 이전 버전이 설정한 프로젝트마다 설치 때와 같은 `--target` 으로
   `setup_permissions.py` 를 한 번 실행하세요: 그 hook 항목을 지워 줍니다.
3. **마지막 프로젝트 다음에, 머신당 한 번**:
   `python3 <plugin-dir>/scripts/setup_permissions.py --uninstall-machine`. 항목마다
   `removed <path>` 또는 `left <path>: <reason>` 을 출력하며, `--dry-run` 으로 미리
   볼 수 있습니다. 공유 임시 디렉터리에는 무엇이 플러그인의 것인지 기록이 없어서
   그곳에서는 아무것도 지우지도, 알리지도 않습니다; 그곳에 남은 wrapper 이름
   형태의 항목은 사용자의 것입니다.
4. **호스트 단계.** 셸에서:

   ```
   claude plugin uninstall triad-dispatch@triad-dispatch
   claude plugin marketplace remove triad-dispatch
   ```

   세션 안에서는 `/plugin uninstall triad-dispatch@triad-dispatch` 다음에
   `/plugin marketplace remove triad-dispatch`. uninstall 은 설정에서 플러그인
   항목과 플러그인 데이터 디렉터리를 지웁니다. `bin/_logs` 와 `bin/_debug` 가 들어
   있는 캐시된 플러그인 디렉터리는 표시만 해 두었다가 14일 뒤 백그라운드 정리가
   지우는데, 이 정리는 설치된 플러그인이 하나 이상 남아 있을 때만 돕니다. 이것이
   마지막 플러그인이었다면 `~/.claude/plugins/cache/triad-dispatch/` 는
   남습니다. marketplace 를 제거하면 거기서 설치한 플러그인도 모두 제거됩니다.
5. **남는 것 — 사용자의 것**: `.gitignore` 의 `_runs/review/` 와 `_runs/worktrees/` 줄; roster 파일 (`.claude/triad-review-legs.json`,
   `~/.config/triad/review-legs.json`); `docs/reviews/` 아래 리뷰 ledger.

## 구성 (What's inside)

- **skills** (4): `triad-codex-dispatch`, `triad-gemini-dispatch`,
  `triad-antigravity-dispatch`, `triad-cross-family-review`.
- **agents** (9): `codex-wrapper-repair`, `gemini-wrapper-repair`, `agy-wrapper-repair`,
  그리고 claude 리뷰 preset 6개 (위 "claude 리뷰 leg 의 모델과 effort 고르기" 참고).
- **bin**: Python wrapper 들 (codex / gemini / agy) + `policies/gemini-readonly.toml` (gemini `--sandbox
  read-only` 모드가 per-call 로 부착하는 read-only Policy Engine 파일).
- **tests**: stdlib-only wrapper 테스트 — 설치 검증에 그대로 사용:

  ```bash
  python3 tests/test_gemini_sandbox.py   # 6 checks — gemini sandbox argv 계약
  python3 tests/test_log_cleanup.py      # 2 checks — log prune + audit rotation
  ```

