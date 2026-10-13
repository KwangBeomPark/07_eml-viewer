# EML Viewer UI/UX 개선 — 2026-10-13

사용자 요청: 첨부파일 열기·저장 버튼이 눈에 잘 띄지 않으므로, 애플리케이션
디자이너 관점으로 Claude와 검토하고 전체 UI/UX를 개선한다.
Codex가 통합·실제 source 렌더 확인을 맡고 Claude Opus 5.5가 설계/검수를 맡는다.
Python/PySide6와 기존 성능·첨부 보안·인쇄·사용자 설정 계약을 보존한다.

## 현재 화면에서 확인한 문제

| 우선순위 | 근거 | 사용자 영향 | 작은 개선 |
| --- | --- | --- | --- |
| P2 | 행이 강조되지만 선택 수 0·열기/저장 비활성. selected_attachments는 checkbox만 조회 | 파일을 클릭해도 작업하지 못하는 것처럼 보임 | 행 선택과 동작 대상 통일 |
| P2 | attachment_widgets._apply_expanded_state가 접을 때 버튼도 숨김 | 첨부 작업 위치를 다시 찾아야 함 | 작업 버튼은 고정, 목록만 접기 |
| P2 | raw MIME·resizeColumnsToContents | 긴 Excel 파일명보다 형식 문자열에 공간 사용 | 파일명 stretch/ellipsis, 형식 간결화·원문 tooltip |
| P2 | 상단 text toolbar·파일열기/브라우저 중복, 메타정보 5행 | 핵심 작업/본문의 시각 우선순위 약함 | 아이콘+짧은 작업 이름, subject/sender/date와 선택형 세부 정보 |
| P2 | 빈 메타정보와 본문 placeholder만 보임 | 처음 시작할 동작이 분명하지 않음 | 빈 화면에 열기·끌어놓기 안내 |

스크린샷은 사용자 메일 없이 합성 source/offscreen Qt 화면으로 생성했다.
Windows 글꼴을 명시 등록해 렌더 환경의 글꼴 부재를 보정했다. 설치형 실화면과
동일하다고 주장하지 않는다. 최초 7개 before 화면과 source 해시는 Git 제외
build/ui-ux-20261013-ef9a7133/before/에 있다. 변경 전 관련 검사 53 passed,
4 subtests passed. 기존 성능 수정이 있는 작업 트리를 baseline으로 보존했다.

## 구현 순서와 완료 기준

1. Claude Opus 5.5 설계 응답을 읽고 최대 5개 개선으로 범위를 고정한다.
2. 첨부파일 선택·동작·목록 폭·접힘 상태를 일관되게 구현한다.
3. 상단 작업과 메일 정보·빈 화면, light/dark/system 위계와 간격을 정리한다.
4. 한국어/영어, 작은 창/긴 파일명/여러 첨부/키보드/접힘 화면을 렌더하고 회귀한다.
5. 통합 후 Opus 검수 최소 2회와 Codex 최종 확인, 필요 지적 수정·독립 staging 빌드.

선택만으로 열거나 저장하지 않는다. 첨부 열기·저장은 기존 MainWindow/service
경로와 default-app/MOTW/위험 확장자/덮어쓰기 확인을 사용한다. 사용자 메일·
UserSetting·기존 dist/release·태그·서명 파일을 변경하지 않는다.

## 반영한 개선

| 영역 | 변경 후 사용 방식 |
| --- | --- |
| 첨부 작업 | 본문 아래 카드에 **선택 열기 / 선택 저장… / 모두 저장…**을 고정. 목록을 접어도 버튼 유지 |
| 선택 | 체크박스 대신 행 클릭, Ctrl/Shift 다중 선택, Ctrl+A 전체 선택, Esc 해제. 더블클릭·Enter로 열기. 한 개 첨부만 자동 선택하며 열지는 않음 |
| 파일 목록 | 파일명 공간 우선, 긴 이름 가운데 생략·전체 tooltip, Excel/PDF 등 간결한 형식. 최종 확장자로 위험 종류를 표시하고 원본 파일명/서비스 정책 보존 |
| 메일 읽기 | 제목·보낸 사람·날짜·파일명 요약, ‘메일 정보’로 복사 가능한 전체 필드 표시. 작은 창은 상세 정보 안에서 스크롤. 본문 공간 확보 |
| 첫 화면·테마 | 메일 열기·끌어놓기 안내, 아이콘/문구 툴바, 메일 원본 저장과 첨부 저장 구분. 밝은/어두운 팔레트와 키보드 포커스·선택 글자 대비 보완 |

메일을 바꾸면 이전 첨부 선택 위치·스크롤을 초기화한다. 여러 첨부는 최초 미선택,
한 개는 선택만 한다. 6개 이상 동시에 열 때 기본 ‘아니요’ 확인을 먼저 수행하고,
개별 위험 확장자 확인·기존 임시 추출·MOTW·Windows 기본 앱 경로를 유지한다.
숨은 방향 제어 문자 등은 화면에서 명시적으로 표시하고 오류창은 파일명을
HTML로 해석하지 않는다. 추출·저장·클립보드의 원본 데이터는 UI 표시와 분리한다.

## Claude 협의와 검수

| 단계 | 실제 완료 응답 | 조치 |
| --- | --- | --- |
| Opus 5.5 설계 | `build/external-agents/20261013T203033Z-00e26b99/receipt.json` | 첨부 고정 작업·행 선택·파일명 위계·간결한 헤더·테마의 5가지로 범위 고정 |
| 통합 검수 1 | `build/external-agents/20261013T205438Z-fb08cf9a/receipt.json` — CONDITIONAL PASS | 이전 current index로 새 메일 첨부가 Enter 실행되는 결함, 접힘 상태의 stale 표시, 포커스·타입 색·경고 표시·작은 화면 문제 수정 |
| 통합 검수 2 | `build/external-agents/20261013T210529Z-0bd662c2/receipt.json` — CONDITIONAL | Tab 셀 이동 함정, 저장 경고 AutoText, disabled 문구·초기 DPI 아이콘을 보완. suffix 우회 의심은 실제 sanitizer가 끝의 점/공백을 제거해 기존 경로에서는 발생하지 않음을 확인 |
| 추가 마감 검수 | `build/external-agents/20261013T211254Z-94c91cc8/receipt.json` — CONDITIONAL PASS, 소스 blocker 없음 | 조건은 전체 회귀·최종 렌더·동일 소스 재빌드. Codex가 모두 확인하고 최종 2차 점검 완료 |

두 GPT-6 Luna 구현 작업의 파일 소유권을 분리했고, 별도 Luna가 읽기 전용 QA를
수행했다. QA에서 상세 정보를 펼칠 때 820×650 창이 높이 752px로 커지는 문제를
재현해 132px 상한의 상세 스크롤 영역으로 수정했다. Codex가 반환 소스·테스트를
확인하고 렌더에서 누락된 선택 힌트 공간·접기 화살표·PDF 문구 등을 보완했다.
Claude는 소스 및 Codex의 화면 관찰 설명을 검토했다. 스크린샷을 직접 본 것으로
표현하지 않는다. exact `claude-opus-5-5`, 완료 marker·model_usage·receipt를 검증한다.

## 확인 근거와 경계

- 변경 전 관련 검사 **53 passed / 4 subtests passed**. 최종 전체 **315 passed**를
  두 번 확인(`final-verbose-tests.log`: 13.61초, **40 subtests passed**;
  `final-confirm-tests.log`: 15.16초). 직접 filename-safety·Tab·확인 취소 회귀 포함.
- 최종 한국어/영어, empty/loaded/selected/small/dark/collapsed/many/details 8개 상태를
  기본·125%·150% 배율로 총 24장 생성. 논리 820×650 창에서 상세 정보를 펼쳐도
  창 크기 유지·첨부 3행·작업 버튼 표시 확인. 각 render receipt의 전/후 소스 해시 일치.
- Qt source/offscreen + 합성 메일이며 Windows 글꼴을 명시 등록했다. 실제 사용자
  메일·SMTP·설정·기본 앱을 사용한 검사로 확대 해석하지 않는다.
- source 테스트에는 Ctrl/Shift/Ctrl+A/Esc, Enter·더블클릭 1회 실행, 새 메일 current
  index 초기화, 언어·테마 전환, collapsed 작업 유지, 로드 실패 시 기존 메일 보존,
  위험 파일 경고 전 취소, 문자 표시·오류창 PlainText·DPR 아이콘을 포함한다.
- 중간 closing 전체 검사 1회가 WindowManager의 업데이트/종료 thread.wait 경로에서
  Qt native abort/access violation으로 중단됐다(`closing-tests.log`). 관련 22개 분리
  검사는 통과했고, 이어진 전체 두 번도 통과했다. 원인을 확정하거나 수정했다고
  주장하지 않는다. UI와 무관하다고 단정하지 않으며 실제 Windows 종료 안정성의
  후속 확인 항목으로 남긴다.
- 독립 PyInstaller staging **exit 0**. 최종 소스·locale·icon·spec 등 **45개 입력**
  전/후·현재 해시 일치, 모듈 archive/locale/WebEngine payload 포함 확인. 기존
  dist/release **2,947개 파일** 해시 일치, 이전 성능 검수 EXE 해시도 보존.
- 서명·설치·GitHub 게시·기존 dist/release 교체는 수행하지 않았다. 설치형 실화면·
  Office 실제 열기·Windows 고대비·Narrator·모니터 간 배율 이동·physical printer는
  미실행 게이트다. Plain PDF/실제 프린터의 기존 검증 경계는 성능 기록을 따른다.

## 최종 검수 번들

현재: **Python source UI/UX 구현·Opus 설계/통합 검수 3회·Codex 최종 2차 점검·
자동 검사·source 렌더·독립 검수 빌드 완료**. 변경은 로컬 미커밋 상태다.

- 최종 EXE: `build/ui-ux-20261013-ef9a7133/bundle-6cf581606ec5485a9d5542beea523a48/dist/EmlViewer/EmlViewer.exe`.
  `_internal`을 포함한 EmlViewer 폴더 전체가 번들이다.
- **NotSigned**. 기존 설치본/기본 파일 연결을 변경하지 않았다. 실제 frozen GUI를
  실행한 검사로 보고하지 않는다. 설치·서명·게시 완료가 아니다.
- EXE SHA-256: `7046de419c5b0d1e7ad7bd918538689f4e929fba0f290c497044d847df2a399f`.
- `build/ui-ux-20261013-ef9a7133/final-verification.json`이 최종 근거이며,
  bundle의 `source-receipt.json`·각 render receipt·Opus 완료 receipt를 함께 기록한다.
  앞선 bundle-77cc565d6d1441299ff2cea960b3d714는 최종 수정 전 중간본이다.
- 마감 검수의 비차단 항목: CRLF preview의 표시상 제어문자 노출 가능성,
  저장 후 정보창 파일명의 bidi 표시, 실제 접근성/모니터/Office 동작은 후속 항목.
  bulk 저장 이름은 service의 sanitize→unique_filename 경로가 최종 확장자를 보존함을
  Codex가 확인했다. 미확인 내용을 성공으로 간주하지 않았다.

최종 source 미리보기:

![첨부파일 선택과 고정 작업 버튼](C:/Dev/GitHub/07_eml-viewer/build/ui-ux-20261013-ef9a7133/final/small.png)

![작은 창에서 메일 정보 펼치기](C:/Dev/GitHub/07_eml-viewer/build/ui-ux-20261013-ef9a7133/final/details.png)
