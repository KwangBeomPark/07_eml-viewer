# Gemini 소작업 분할 실행 검증 — App07 단계 2.5

2026-10-13. Python 유지, C# 전환 없음. Codex가 Antigravity CLI를 직접 호출해
Gemini 3.8 Flash (High), effort high에 한 단계의 작은 작업을 나누어 전달했다.
Codex의 내장 subagent 모델 변경이나 Antigravity 내부 invoke_subagent 검증으로
보고하지 않는다. 실제 확인 범위는 **Codex → agy → 등록된 gemini-review → 응답**이다.

## 범위와 판정

각 작업은 코드 발췌·질문만 담은 독립 packet을 받아 새 대화로 실행했다.
기존 에이전트의 쓰기·터미널·MCP 도구 제한을 유지하고 사용자 메일·설정은
전달하지 않았다. Gemini가 코드/테스트를 초안으로 반환하고 Codex가 검증·적용한다.

G1~G3은 독립적으로 실행했고, G4는 코드 수정·회귀·측정 결과가 나온 후 실행한다.
모델 라벨, agent 활성화, 상태, timeout 경고, 본문, 고유 마지막 완료 표식을
확인한다. **통신 완료와 초안 채택은 서로 다른 판정**이다.

| 작업 | Gemini에 맡긴 범위 | 통신 결과 | Codex 검증·채택 |
| --- | --- | --- | --- |
| G1 | 벽시계와 cProfile 측정 설계, 디코드 횟수 분석 | 완료, 77.980초 | 분리 측정·exclusive/inclusive 구분 채택. Mock 스케치는 실행 코드로 부적합해 제외 |
| G2 | extract_attachment 메서드 하나의 최소 수정 코드 초안 | 완료, 80.913초 | 비대상 메타데이터 디코드를 생략하고 선택 payload를 재사용하는 초안 채택 예정 |
| G3 | 단건 추출 회귀 테스트 4개 초안 | 완료, 133.842초 | 로드·잘못된 인덱스·MSG 위임 초안 확인. 디코드 검사 테스트의 잘못된 파트 식별 발견 |
| G3R | 잘못된 디코드 검사 테스트 1개만 재작성 | 시간 초과, 184.400초 | 반환 exit 0이었으나 빈 응답/print timeout을 실패로 판정. Codex가 테스트 수정 |
| G4 | 실제 변경·테스트 결과의 최종 검수 | 완료, 61.286초 | 정적 PASS. 보고서의 잘못된 파일 링크는 채택하지 않고 실제 코드로 검증 |

G1의 클래스 단위 Mock 예시는 호출 대상·decode=True·본문/구조 호출을 분리하지
않고 실제 실행이 주석 처리되어 있어 채택하지 않았다. G3은
`_attachment_info(part, index) is not None`로 첨부를 판별했는데, 이 함수는
모든 파트의 메타데이터를 만들고 payload를 디코드한다. 따라서 시험 자체가
측정 대상을 바꾸고 인덱스도 틀어진다. 오류를 그대로 통과시키지 않고 G3R로
MIME 파트별 spy 하나만 재지시했다.

## 실제 근거

- G1: `build/external-agents/20261012T222810Z-875e5d70/`
- G2: `build/external-agents/20261012T222810Z-810cc36e/`
- G3: `build/external-agents/20261012T222846Z-39ac6fc3/`
- G3R: `build/external-agents/20261012T223138Z-dc612096/` (미완료)
- G4: `build/external-agents/20261012T223551Z-7c8458be/`
- packet·수정 전 소스·측정: `build/gemini-split-20261013/`

이 폴더는 Git 제외된 로컬 검수 자료다. 각 실행에 receipt.json, report.md,
stdout.json, stderr.txt, agent.log가 있다. UTC run-id는 사용자 날짜 10월 13일
(Europe/Warsaw)과 구분한다. 응답이 완료됐다고 코드 품질·테스트·청구를 보증하지 않는다.

## 제품 변경과 측정

Python 단건 추출 수정과 전체 246개 테스트/36 subtests 검증을 진행했다.
통신은 5호출 중 4완료/1시간 초과이며, 초안의 정확성에는 Codex 수정이 필요했다.
2026-10-13 사용자 지시로 Gemini 진단/추가 호출을 중단했다. 후속 작업은
[Codex/Luna/Opus 통합 기록](PERFORMANCE_OVERNIGHT_20261013.md)으로 이어간다.
메일 parse_file과 단건 첨부 extract_attachment를 따로 측정한다.
profiler의 inclusive 시간은 중첩되어 합산하지 않으며, 프로파일러 실행과
벽시계 반복 실행을 분리한다. 실제 GUI/설치형 EXE/MSG 속도는 이번 수치에 포함하지 않는다.
