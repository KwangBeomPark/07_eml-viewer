# Codex → Antigravity CLI 반복 검수 구성

2026-10-12. 이 문서는 Antigravity IDE가 아니라 `agy` CLI 연결을 다룬다.
Codex의 내장 subagent 모델 설정과는 별개다. Codex가 로컬 CLI 프로세스를
실행해 작업을 전달하고 결과를 검사한다.

## 확인한 상태와 변경

- 설치된 `agy` 버전 1.3.2. 실제 CLI 모델 목록에서
  `gemini-3.8-flash-high`와 Claude Opus 5.5 계열 선택자를 확인했다.
- Opus 계획 검수는 직접 Claude CLI에서 `claude-opus-5-5`, effort `high`로
  실행하고 반환 `modelUsage`에서 정확한 모델을 확인했다.
- 초기 `agy agents`에는 등록된 사용자 에이전트가 없었다. 이번에
  `.agents/agents/gemini-review.md`를 추가하고 전역
  `~/.gemini/config/agents/gemini-review.md`에도 동일 정의를 설치했다.
  프로젝트 정의가 우선이며, 정확한 파일 내용과 `agy agents` 등록을 확인한다.
- CLI 설정의 `trustedWorkspaces`에는 오래된 다른 프로젝트 경로만 있었다.
  기존 JSON을 고유 이름으로 백업하고 07번 경로만 추가했다. 전체 프로젝트
  신뢰나 전역 자동승인 정책을 새로 켜지 않았다.
- 기존 MCP 구성의 일부 도구 이름이 64자 제약에 걸리는 로그가 있었다.
  사용자 플러그인 연결은 보존했다. 검수 에이전트는 공통 플러그인·규칙·MCP를
  상속하지 않으며 `view_file`만 제공한다.

## 재현한 호출 문제

1. **에이전트 YAML의 model은 모델 계층이다.** 이번 구성 테스트에서
   `model: gemini-3.8-flash-high`를 넣으면 `agy agents`에 등록되지 않았고
   `--agent gemini-review` 호출이 기본 에이전트로 fallback했다.
   `model: flash`로 바꾼 뒤 등록됐다. 정확한 모델 선택은 CLI에서
   `--model gemini-3.8-flash-high --effort high`로 지정한다.
   이 재현은 이번 테스트의 결과이며 과거 사용자 실패의 단일 원인을 확정하지 않는다.
2. **시간 제한에 단위가 필요하다.** `--print-timeout 180s`가 유효하다.
   숫자 `180`만 전달하면 CLI 인자 오류가 난다.
3. **모드와 slash 비활성화 조합.** `--disable-slash-commands`를 함께 주면
   `--mode plan`이 효과가 없다는 경고가 나왔다. 이 구성을 검수 보호로 믿지 않는다.
   이번 에이전트는 쓰기·터미널 도구 자체를 제공하지 않는다.
4. **SUCCESS와 완료는 다르다.** 설치된 CLI 변경 이력은 print timeout 때
   부분 결과를 반환하고 종료 0으로 끝낼 수 있다고 명시한다. 따라서 종료 코드,
   JSON 상태, stderr timeout/partial 경고, 응답 본문과 고유 완료 표식을 함께 검사한다.
5. **등록 실패도 기본 모델 실행처럼 보일 수 있다.** 실행 로그에서
   `Agent ... not found, falling back to default`를 거부하고 custom agent 활성화와
   정확한 Gemini High 선택 라벨을 검사한다.

등록된 최소 에이전트의 실제 무도구 호출은 입력 3,056 토큰이었다. 기본 에이전트
연결 확인의 약 26,074 토큰보다 컨텍스트는 작아졌지만 경과는 약 43.7초로,
CLI/서버 시작 지연은 남아 있다. 소스 검수는 파일 읽기와 사고 토큰이 추가되므로
무도구 확인 수치를 작업당 토큰 사용량으로 일반화하지 않는다.

## 반복 사용

07번 저장소 루트에서:

```powershell
agy models
agy agents
.venv\Scripts\python.exe scripts\run_external_review.py --provider gemini --prompt-file scripts\agent_prompts\performance-review.txt --timeout 180
```

`gemini-review`가 목록에 있어야 한다. 래퍼는 모델·effort·에이전트를 고정하고
새 대화로 실행한다. 한 작업의 Gemini prompt는 20,000자 이하로 제한한다.
단순 등록/인증 확인과 실제 소스 검수를 구분하고, 큰 작업은 대상 파일·질문을 줄인다.

Opus는 전달된 packet만 읽는 도구 없는 계획·변경 검수에 사용한다:

```powershell
.venv\Scripts\python.exe scripts\run_external_review.py --provider opus --prompt-file build\performance-planning\opus-plan-review.txt --timeout 240
```

이 Opus packet은 로컬 이번 실행 자료다. 새 단계에는 Codex가 해당 단계의 소스와
계획만 담은 새 packet을 만든다. `scripts/agent_prompts/performance-review.txt`처럼
경로만 나열한 prompt를 도구 없는 Opus에 주고 실제 파일을 읽었다고 간주하지 않는다.

각 실행의 고유 `build/external-agents/<run-id>/`에 prompt, stdout JSON,
stderr, 보고서, receipt를 저장한다. Gemini는 별도 실행 로그도 저장한다.
이 폴더는 Git 제외 대상이다. receipt의 `completed: true`는 응답이 완결됐음을
검사한 결과이며, 제안의 정확성·제품 테스트·계정 과금의 증거는 아니다.
Codex가 보고서를 실제 소스와 대조한 뒤 테스트한다.

호스트 시간 제한도 두며 이를 넘으면 해당 호출의 프로세스 트리만 종료한다.
시간 초과나 빈 응답을 성공으로 바꾸거나 자동으로 다른 모델로 바꾸지 않는다.
API key나 인증정보를 이 저장소에 저장하지 않는다.

## 공식 근거

- [Custom subagents](https://antigravity.google/docs/subagents/): 탐색 경로,
  YAML model 계층, 도구 목록과 잘못된 도구 이름의 알려진 문제.
- [CLI reference](https://antigravity.google/docs/cli/reference): 설정·권한·CLI 명령.
- 로컬 내장 설정 안내:
  `~/.gemini/antigravity-cli/builtin/skills/agy-customizations/SKILL.md`.
- 모델 목록·CLI 경고·등록 여부·실행 로그는 이번 로컬 호출을 실제 확인한 결과다.
