# 회사 환경 셋업 — Claude Code 최적화

> 🌐 **English: [COMPANY-SETUP.md](./COMPANY-SETUP.md)**
>
> 사내(폐쇄망, 제한적 프록시) Claude Code 환경을 우리가 함께 일하던 방식대로
> 최적화하기 위한 설치/구성 가이드. 동봉된 `CLAUDE.recommended.md`(영문 — 실제
> `~/.claude/CLAUDE.md`에 넣을 instruction 본문)와 짝.

대상 환경:

- **OS**: Ubuntu 24.04 (Noble) — 사내 prod 기준.
- **사용 가능 vendor CLI**: Codex CLI, **Gemini CLI(엔터프라이즈 tier)**, Claude
  Code. (Antigravity 없음) 사내 Google-family leg 는 **엔터프라이즈 Gemini** 이며
  계속 사용 — 개인-tier Gemini 폐지(사외 사용자는 Antigravity/agy 로 이전)는
  엔터프라이즈 tier 에 영향 없음.
- **네트워크**: 폐쇄망 + **제한적 프록시** — 외부 마켓플레이스 직접 접근 불가.
  공개 `github.com` URL 대신 **사내 GHE 미러** 또는 **로컬 폴더 복사**로 설치.

---

## 0. 사전 준비 (apt)

```bash
sudo apt update
sudo apt install -y python3 python3-venv git ripgrep fd-find jq \
  shellcheck shfmt expect parallel pv
# yq: apt 의 `yq` 는 다른 도구다 — Go yq 를 GitHub release 바이너리(또는 사내
#     미러)로 설치할 것. `apt install yq` 아님.
# ruff / tokei / difft: 사내 미러 또는 cargo 로 설치.
```

- `python3 --version` 이 **3.12** 여야 함 (Ubuntu 24.04 기본).
- `bash --version` 이 **5.x** 여야 함 (stock 5.2 OK).
- Ubuntu 에서 `fd` 는 `fdfind` — 원하면 셸 rc 에 `alias fd=fdfind`.

> 이 도구 묶음을 고른 이유: 전부 macOS(개발) ∩ Ubuntu 24.04(prod) **양쪽에서
> 동일 syntax 로 호출되는 artifact-callable** 도구라, 스크립트가 양쪽에서 그대로
> 돈다. Mac 전용(`osascript`, `open`, `direnv` 훅, 스크립트 안 `httpie`) 은
> 산출물에 넣지 말 것.

---

## 1. vendor CLI + 인증

쓸 CLI 를 설치하고 **대화형으로 로그인**한다. Claude 는 토큰을 발급/관리하지
않고, 여기서 설정한 자격증명을 그대로 재사용한다.

| CLI | 설치 | 인증 (직접) |
|-----|------|-------------|
| **Codex** | 사내 패키지 미러 | `codex login` |
| **Gemini** | 사내 패키지 미러 | `gemini auth login` (또는 사내 SSO) |
| **Claude Code** | 사내 패키지 미러 | `claude` 최초 실행 로그인 |

Codex/Gemini = dispatch *워커*, Claude Code = *리더*(+ fresh-eye 리뷰 레그).

---

## 2. 플러그인 / 마켓플레이스 (제한적 프록시 설치)

외부 마켓플레이스(예: `github.com/obra/superpowers`) 직접 접근 불가. 둘 중 하나:

- **사내 GHE 미러**: 마켓플레이스 repo 를 사내 GHE 에 미러 후
  `/plugin marketplace add https://<사내-GHE-호스트>/<org>/<repo>.git`
  (GHE Personal Access Token 을 git credential helper 로 연결, 또는 SSH 키를
  `ssh-agent` 에 로드 + 호스트를 `known_hosts` 에 등록).
- **로컬 폴더** (git/토큰/네트워크 0): 빌드된 플러그인 폴더를 머신에 복사 후
  `/plugin marketplace add /절대/경로/폴더`.

> **엔터프라이즈 (권장):** 위 `https URL` 방식은 사내 프록시 / GHES 인증 뒤에서
> 자주 **실패**한다(실측). 확실히 되는 길은 소스 repo 를 **로컬 git clone** 해서
> 디렉터리 마켓플레이스로 add 하는 것 — **§ 2d** 참고(최초 설치 + 이후 업데이트
> `git pull` → refresh → update 모두 포함).

### 2a. Superpowers (Anthropic 방법론 스킬) — 강력 권장

우리 작업 방식의 backbone. `obra/superpowers` 를 사내 미러(또는 스냅샷 복사)로
add + install. 우리가 늘 쓰는 스킬:

- `brainstorming` — 아이디어 → 설계/스펙 (구현 전 게이트)
- `writing-plans` — 설계 → bite-sized TDD 태스크 플랜
- `subagent-driven-development` — 플랜을 태스크 단위로 실행 + spec/품질 리뷰
- `test-driven-development` — RED → GREEN → REFACTOR (Iron Law)
- `verification-before-completion` — 완료 선언 전 fresh evidence
- `systematic-debugging` — 재현 → 메커니즘 격리 → 수정 (추측-패치 금지)
- `writing-skills` — 새 SKILL 올바르게 저술
- `requesting-code-review` / `receiving-code-review`
- `using-git-worktrees` / `finishing-a-development-branch`

### 2b. triad-dispatch (이 플러그인)

self-improving repair loop + cross-family review 를 갖춘 단발 cross-CLI
dispatch. 사내 미러/로컬 폴더로 add + install:

```
/plugin marketplace add <사내-GHE-URL-또는-로컬-경로>
/plugin install triad-dispatch@triad-internal-tools
```

실제 호출할 스킬(Codex+Gemini+Claude 환경):

- **`triad-codex-dispatch`** — "codex 한 번 호출" + 분류 라우팅 + unknown 실패 시
  repair-agent 자동. `--task code`(codex 를 격리 worktree 의 TDD 구현자로, 리더가
  검증)도 지원.
- **`triad-gemini-dispatch`** — 동일, Gemini 측(Android/문서/Google 도메인).
- **`triad-cross-family-review`** — 머지 전 게이트: 서로 다른 모델 패밀리 3인
  (Claude fresh-eye `Agent` + Codex + Gemini)이 diff 를 심사, 의심 결정은 질문으로
  제기, fix→재확인 루프. **가장 가치 높은 습관**(CLAUDE.md 의 cross-family 규칙 참고).

> 이 플러그인은 `triad-antigravity-dispatch` + `agy` repair agent 도 포함하지만,
> 이 환경에 Antigravity 가 없으면 그냥 미사용. Google 리뷰 레그가 agy →
> **gemini** 로 자동 fallback 하므로 cross-family review 는 그대로 동작.

### 2c. 플러그인 Bash allowlist (수동 — 플러그인은 self-authorize 불가)

플러그인은 자기 권한을 grant 못 한다. Claude Code 설정 `allow` 에 추가해 매번
프롬프트 없이 wrapper 가 돌게 한다:

```
Bash(codex_wrapper.py:*)
Bash(gemini_wrapper.py:*)
```

### 2d. 로컬 GIT CLONE 으로 설치 + 업데이트 (엔터프라이즈에서 확실히 되는 길)

`/plugin marketplace add <https URL>` 은 사내 프록시 / GHES 인증 뒤에서 자주
**실패**한다(실측). 실제로 동작하는 길은 소스 repo 를 **로컬 git clone** 해서
디렉터리 마켓플레이스로 add 하는 것 — 이후 `git pull` 로 업데이트(완전
에어갭이면 clone 을 다시 전송). URL 방식 말고 이걸 쓸 것.

> **버전 함정 (먼저 읽을 것):** Claude Code 는 플러그인 `version` 문자열로
> 업데이트를 게이트한다 — **새 빌드의 버전이 기존과 같으면 `/plugin update` 와
> 자동 업데이트가 조용히 SKIP** 하고 옛 코드가 그대로 남는다. 본 빌드는 매
> 릴리스마다 `.claude-plugin/plugin.json` + `marketplace.json` 의 `version` 을
> 올린다; 바뀌었는지 확인할 것(`/plugin` 이 설치된 버전 표시).

**최초 1회 (clone → add → install):**
```
# 소스 접근 가능한 곳에서 clone, 또는 다른 데서 clone 후 폴더를 반입:
git clone <소스-repo-url> /절대/경로/triad-dispatch
/plugin marketplace add /절대/경로/triad-dispatch         # 디렉터리 source = 로컬 경로 (URL 아님)
/plugin install triad-dispatch@triad-internal-tools
```

**새 버전 업데이트 (pull → refresh → update → reload):**
```
git -C /절대/경로/triad-dispatch pull                     # 로컬 clone 갱신
                                                          #   (에어갭: clone 을 기존 폴더 위에 다시 전송)
/plugin marketplace update triad-internal-tools           # 로컬 폴더에서 marketplace.json + version 재읽기
/plugin update triad-dispatch                             # 새 빌드 fetch (버전 그대로면 SKIP — 위 함정 참고)
/reload-plugins                                           # 재시작 없이 적용
```

**검증:** `/plugin` 이 `triad-dispatch` 를 새 버전으로 표시; 바뀐 동작 spot-check.

> **URL 마켓플레이스 (환경이 실제로 허용할 때만):** `/plugin marketplace add
> https://<ghe-호스트>/<org>/triad-dispatch.git` 후 `/plugin marketplace update`
> — git credential helper(PAT) 또는 ssh-agent 의 SSH 키 필요. 다수 엔터프라이즈가
> 이를 막는다(실측 사례도 그랬음); 위 로컬 clone 이 항상 되는 fallback.

> **관리자 seed / managed 설치:** 조직이 seed 이미지
> (`CLAUDE_CODE_PLUGIN_CACHE_DIR`) 나 `managed-settings.json`
> (`extraKnownMarketplaces` / `strictKnownMarketplaces`) 로 배포하면, `/plugin
> marketplace update` 가 일반 사용자에게 차단된다 — 관리자가 seed 이미지 /
> managed 설정을 갱신해야 한다. Claude Code 플러그인 문서의 GitHub Enterprise
> Server 섹션 참고.

---

## 3. working-practices CLAUDE.md 적용

이 파일 옆 `CLAUDE.recommended.md`(영문)를 환경의 base instruction 으로 복사:

- **전역/크로스-프로젝트**: `~/.claude/CLAUDE.md` — working-practices 코어.
- **프로젝트별**: 프로젝트 루트 `CLAUDE.md` 가 이를 *확장*(빌드/테스트 명령,
  레이아웃, 도메인 규칙).

해당 파일 헤더가 어떤 섹션이 보편이고 어떤 걸 프로젝트별로 손볼지 설명한다.

---

## 4. 셋업 검증

```bash
codex --version && gemini --version && claude --version
rg --version && jq --version && shellcheck --version && bash --version | head -1
# 플러그인 설치 후 bin/ 이 PATH 에 있음
codex_wrapper.py --prompt 'reply with OK'
gemini_wrapper.py --prompt 'reply with OK'
```

Claude Code 세션에서 `/plugin` 으로 마켓플레이스+설치 플러그인 확인, "use
triad-codex-dispatch to ask codex a quick question" 시켜 라우팅 동작 확인.

---

## 5. "우리 페어처럼 최적화"의 진짜 의미

위 도구는 필요조건이지 충분조건이 아니다. `CLAUDE.recommended.md` 의 *습관*이
협업을 작동시켰다:

1. **비-trivial 작업 전 설명-후-질문** (바이브 아님, 페어 규율).
2. **TDD-strict** — 실패 테스트 먼저, 테스트는 PASS 가 목적이 아니라 실 결함 노출.
3. **머지 전 cross-family review** — 다른 패밀리가 서로의 맹점을 잡는다(반복 입증:
   같은-패밀리 리뷰 체인이 통과시킨 걸 Codex/Gemini 가 독립적으로 적출).
4. **Tier-1 lookup, 추측 금지** — 폐쇄망에서는 승인 미러/캐시 문서, 불확실하면 STOP.
5. **산출물은 Ubuntu 24.04 에서 동작** — unversioned shebang, apt 도구만.

도구 *와* 습관을 함께 가져갈 것. 습관이 곧 최적화다.
