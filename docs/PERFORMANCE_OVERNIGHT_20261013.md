# Python 성능 개선 통합 기록 — 2026-10-13

사용자 지시: Codex 총괄, GPT-6 Luna 하위 에이전트 적극 활용, Python 유지.
Gemini 원인 점검/추가 호출 중단. 통합 후 Opus 5.5 검수를 최소 두 번 받고,
수정이 필요하면 수정·추가 검수하며 마지막 두 번째 점검은 Codex가 마무리한다.
실제 한도 소진 시 체크포인트를 보존하고 초기화 후 이어간다. reset credit나
유료 크레딧을 사용하지 않는다.

## 파일 소유를 분리한 하위 작업

| 하위 에이전트 | 모델 | 담당 | Codex 통합 |
| --- | --- | --- | --- |
| async_open | GPT-6 Luna / medium | 백그라운드 파싱, UI 경로 변경, 최신 요청/닫기 회귀 | 완료. 완료 이벤트 전 worker 교체 경합·동기 API 경합 추가 수정 |
| folder_cache | GPT-6 Luna / medium | 한 폴더 목록 서비스, 회귀, 합성 벤치마크 | 완료. QFileSystemWatcher 연결과 감시 실패 시 재조회 추가 |
| lazy_html | GPT-6 Luna / medium | WebEngine import/뷰 지연 생성, 재사용, 검색·인쇄·차단 회귀 | 완료. 실제 .venv에서 WebEngine 정책 검사 실행 |

하위 에이전트의 처음 일부 검사는 전역 Python의 의존성 부족 영향을 받았다.
Codex가 저장소 `.venv`에 oxmsg/WebEngine이 있음을 확인하고 통합 검사를 실행했다.
반환 메시지를 무조건 완료 증거로 간주하지 않는다.

## 기능과 경합 보호

- UI의 열기·드래그·최근 파일·이전/다음·새 창/IPC 파일 경로는 async 파싱을 사용한다.
  동기 `load_email`은 호환 API로 유지하며 기존 async 결과를 무효화한다.
- 창별 실행 worker 1개와 최신 대기 요청 1개로 제한한다. 완료 신호가 GUI에서
  처리되기 전에는 다음 worker를 시작하지 않는다. 오래된 결과/오류는 표시하지 않는다.
- 닫기에서 대기 요청 제거·worker 보존·GUI 결과 무시. 강제 thread 종료를 하지 않는다.
  앱 전체 종료는 남은 파싱 완료를 기다릴 수 있다. CPU 파싱 속도와 UI 반응성은 구분한다.
- 폴더 목록은 한 폴더만 재사용. 변경 신호에서 캐시를 즉시 무효화하고 200 ms
  debounce 후 추가/이름 변경/삭제를 반영한다. watcher 등록 실패 시 재조회한다.
- 빈 창/plain에서는 WebEngine DLL import와 renderer 생성을 하지 않는다. HTML 첫
  표시에서 생성하고 재사용한다. 외부 리소스/JavaScript 차단과 CID 정책을 유지한다.

## 측정과 테스트

각 수치는 합성/격리 데이터 기준이며 전체 EXE 설치·OS cold start·실제 사용자
메일 성능으로 일반화하지 않는다. 모든 원본 JSON/로그는 Git 제외 build/에 있다.

| 측정 | 변경 전 | 변경 후 | 경계 |
| --- | --- | --- | --- |
| 같은 폴더 30회 조회, 2,000 mail + 2,000 txt + 20 디렉터리, 7회 중앙값 | 1,362.420 ms, 30회 scan | 18.018 ms, 1회 scan | 순서 교대·소스 해시 확인, 목록 매 선택 일치 |
| 첨부 6개 중 마지막 단건 추출, 11회 교대 중앙값 | 59.493 ms | 48.826 ms | 약 17.9% 시간 감소, SHA-256 일치 |
| 첨부 8개×1 MiB 중 마지막 단건 추출, 11회 교대 중앙값 | 149.039 ms | 118.431 ms | 약 20.5% 시간 감소, SHA-256 일치 |
| 빈 본문 widget 생성, 새 프로세스 각 5회 중앙값 | 90.987 ms | 8.516 ms | 최종 widget 소스, OS 파일 캐시 warm |
| 본문 module import, 같은 새 프로세스 | 72.021 ms | 41.889 ms | WebEngine import 지연, EXE 시작 수치가 아님 |

parse_file 중앙값은 같은 교대 실행에서 사실상 같은 수준이었다. 단건 추출의
효과를 메일 파싱·HTML 렌더링 속도 개선이라고 주장하지 않는다.

- Codex 최종 전체 통합 검사: **293 passed, 40 subtests passed**, 7.69초, exit 0.
- UI heartbeat, 최신 요청만 처리, 이전 오류 무시, 처리 중 닫기, 완료 이벤트 경합,
  sync/async 경합, 폴더 감시 add/rename/delete, watcher 실패 fallback 검증.
- 기존 PDF callback 단위 검사가 실제 native QPrinter를 호출해 COM 진단을 내던
  부분은 정확한 모듈 별칭을 mock하고 callback/파일명 설정을 검증하도록 격리했다.
  이것은 실제 PDF 인쇄/저장 성공의 증거가 아니다.
- 원본: `build/performance-overnight/parser-paired.json`, `final-regression.log`.
- stamp 안전장치 이후 원본: `folder-navigation-966652eefb11491481965ccf45c92d96.json`.
- 최종 폴더 측정은 앞선 도구에 빠져 있던 소스 해시/기준 코드와 순서 교대를
  추가한 `folder-navigation-4bb59e38f511494bae2bd114f0d9a3b9.json`을 사용한다.
- 최종 빈 본문 widget 비교 원본: `widget-startup-7a6ba0e5038c408c83748aae86a0a643/results.json`.
  이전 renderer는 5/5 실제 시작됐고 이후는 5/5 import/생성을 하지 않았다.
  HTML-ready 지연은 이 측정에 포함하지 않는다.
- 최종 HTML marker 실제 표시까지: 이전 522.154 ms (503.320–536.152), 이후
  535.910 ms (497.117–572.790), 각 5회 모두 성공. 이후 중앙값은 약 2.6% 높지만
  작은 표본의 범위가 겹치므로 HTML 가속·동등성·유의한 악화는 단정하지 않는다.
  원본: `html-ready-bf06134ebdb744758cd514ad4dcfcbed/results.json`.
  widget/HTML 벤치마크는 서로 순차 실행한 최종 기록을 사용한다.
- 실제 EmlParser와 MainWindow async 통합: 합성 4,251,069-byte EML/첨부 6개에서
  호출 반환 0.112 ms, 파싱 55.929 ms, 표시 callback 58.131 ms. UI timer가 표시 전
  실행됐고 총 heartbeat 5회, 올바른 본문/첨부 6개, worker 종료/닫기 확인.
  한 번의 source/offscreen 실행이며 설치형 UI 지연 수치가 아니다. 실행 전/후 소스
  해시 일치. 원본: `build/async-load-evidence-a192c8d137594d1cbeca592eca4c0578/`.

## Opus 검수와 최종 체크포인트

1. Opus 5.5 통합 1차: 완료, 실제 Opus modelUsage 확인. 결과는
   `build/external-agents/20261012T224514Z-eaeb4e47/`, 180.227초.
2. 1차 지적 사항 반영: 완료. 인쇄 재진입/수명, lazy GPU 공유 컨텍스트 설정,
   폴더 알림 debounce/mtime 안전장치, 빠른 연속 탐색, 원래 요청 경로,
   닫기/retain 경합 및 불필요한 닫힌 창 대화상자 보완.
3. Opus 5.5 통합 2차: 완료, 조건부 PASS. 실제 응답/모델 근거:
   `build/external-agents/20261012T225458Z-5cb16efb/`, 282.030초.
   파일 경계 검사 앞의 resolve 제거, 폴더 축소 중 pending 탐색 재매핑,
   PDF 실제 생성 검증, 인쇄 중 본문 교체 지연을 반영했다.
4. 파일 경계·인쇄 수명의 Opus 추가 확인: 완료, 조건부 PASS.
   `build/external-agents/20261012T230427Z-a90a73e4/`, 205.894초, 정확한
   claude-opus-5-5 modelUsage/완료 표식/exit 0 확인. TEMP alias와 CID 경로
   일치, 인쇄 후 deferred render 실패 시 완료 callback 보장을 반영했다.
   생성한 CID 파일만 허용하고 파일명 길이/쓰기 실패, renderer 종료,
   인쇄 중 본문·브라우저·언어 변경도 보완했다.
5. 위 조건의 좁은 Opus 추가 확인: 완료, 수정 전 NOT PASS.
   `build/external-agents/20261012T231426Z-5ef9f969/`, 82.274초.
   callback·CID allowlist·renderer 실패 후 창 해제는 통과했으나 서로 다른
   드라이브의 TEMP alias가 commonpath 비교 중 전체 반복을 중단하는 문제를 지적했다.
6. Codex 마지막 2차 검수: 위 비교의 ValueError를 각 root별로 처리하도록 수정.
   Windows에서 lexical/resolved 두 경로×두 root 순서의 4개 subtest와 전체 회귀 통과.
   `_clear_inline_temp_dir`의 allowlist 초기화도 대조했다. Opus 결과를 최종 PASS로
   바꿔 쓰지 않으며 마지막 수정의 검증 주체는 Codex다. 최종 빌드 대조도 완료했다.

Codex 독립 점검에서, 삭제된 pending 탐색 대상의 active 상태가 남아 다음
탐색이 멈추는 문제를 추가 수정했다. 이후 클릭은 새 목록의 현재 위치에서
다시 시작하고, 삭제된 대상·이전 worker 결과는 표시하지 않는다. standalone
창의 worker 종료 대기도 managed WindowManager 정리와 별도로 유지했다.
인쇄 중 외부 브라우저 열기는 버튼·메뉴·직접 메서드 경로에서 막는다.

실제 source/offscreen PDF 파일 검사에서는 HTML marker가 읽히는 것을 확인했다.
최종 red CID smoke는 PDF의 붉은 이미지 306 pixels, 읽히는 marker, 실제 Qt 인쇄
callback/busy 해제, 실행 전/후 소스 일치를 확인했다. 원본:
`pdf-cid-final-2bcc15434cc0468ead99934e59c02aad/results.json`.
plain PDF는 header/비어있지 않음/callback 검사에는 통과했으나 시각적으로
검은 막대여서 읽기 성공으로 세지 않는다. HEAD·현재 소스·직접 QTextDocument
및 3개 DPI 설정에서 같은 현상이 나왔다. offscreen Qt 인쇄/글꼴 경로 문제라는
추론은 가능하지만 실제 Windows GUI 인쇄의 결함/정상 여부는 미확인이다.
초기 `pdf-smoke-e2f08aa6d0b046c39a3a94891c710c08/results.json`의 success는
구조 검사에 한정하며 readable plain 성공 근거로 사용하지 않는다.
안정된 plain 대조 원본: `pdf-print-diagnosis-f76412a0a93c49cc82810dc1e517248d/results.json`.

1차 보완 후 전체 검사 **278 passed, 36 subtests passed**, exit 0.
하위 에이전트의 bare QThread 종료 fixture는 기본 이벤트 루프가 끝나지 않아
wait 실패 뒤 native crash가 난 잘못된 테스트였다. 실제 production처럼 run이
반환하는 QThread로 교체해 완료된 worker 해제를 독립 검사했고 **1 passed**, exit 0.
원인 불명인 제품 종료 결함으로 단정하지 않았으며, 실제 실행 중 worker 및 닫힌 창
보존/해제 검사도 별도로 통과했다.

## 완료 범위와 검수 빌드

자동화 가능한 Python 구현·측정·Opus 4회 응답 검수·Codex 최종 2차 점검과 독립
staging 빌드가 완료됐다. 최종 전체 검사와 측정 JSON의 소스 해시가 번들 입력
해시와 일치하며, `git diff --check`도 통과했다. 변경은 로컬 미커밋 상태다.

- 검수 EXE: `build/performance-overnight/bundle-4a0adb21ae8445f59dd49b50bb81cf8d/dist/EmlViewer/EmlViewer.exe`.
  `_internal`을 포함한 폴더 전체가 실행 번들이다. 설치본을 갱신하지 않았다.
- PyInstaller build exit 0, **NotSigned**. EXE SHA-256:
  `5098d03c2058c46c742a89386c21cf523c034c9a6e6aac244363ed1da9f6360f`.
- 빌드 전/후 소스·locale·icon·spec 등 44개 입력 해시 일치. archive에서 새 폴더
  서비스와 기존 parser/GUI/oxmsg, 파일에서 WebEngine DLL/process/resource와
  en/ko locale 포함을 확인했다. 실제 frozen GUI 실행 증거는 아니다.
- 기존 dist/release 2,947개 파일은 전/후 해시 일치(UserSetting 제외). 사용자
  메일/설정·기존 서명 배포물·태그를 변경하는 명령은 실행하지 않았다.
- 최종 근거: `build/performance-overnight/final-verification.json` 및 검수 번들의
  `source-receipt.json`. 기존 중간 bundle 출력은 최종본으로 사용하지 않는다.
- 한도 소진 없이 완료했으며 크레딧 구매/reset credit 사용은 없었다. 이어가기
  자동화 `07-python`은 중복 작업을 막기 위해 PAUSED로 변경하고 다시 확인했다.

남은 Windows 게이트: 설치형 첫 실행/상주/다중 창/RSS·시각 반응성·파일 연결,
plain PDF 실화면 가독성, physical printer·실제 renderer 종료, 네트워크 폴더,
교차 볼륨 TEMP/CID·SMB 차단 계측, 실제 MSG 성능. 사용자 설치/업그레이드·서명·
GitHub 게시를 완료한 것으로 보고하지 않는다.
