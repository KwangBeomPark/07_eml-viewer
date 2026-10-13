# EML Viewer 공개 코드 지도

EML Viewer는 EML·MSG 열람, 첨부파일 저장, PDF 내보내기와 SMTP 전달을 담당합니다.
FileOps Hub의 파일 일괄 변환·동기화와 별도 앱으로 유지합니다.

| 경로 | 역할·계약 |
| --- | --- |
| `src/eml_viewer/app.py`, `app_identity.py` | 앱 시작·Windows mutex·설정 위치·제품 이름·읽기 전용 중앙 기본값 |
| `src/eml_viewer/services/settings_service.py` | 사용자 저장 키가 중앙 기본값보다 우선. 사용자 지정 SMTP 25/빈 서버 보존. 손상 원본 덮어쓰기 차단, 고유 임시 파일·fsync 후 교체, 실패 시 원본 유지·오류 전달 |
| `src/eml_viewer/models/app_settings.py` | 저장 모델·값 검증 |
| `src/eml_viewer/services/` | EML/MSG 파싱·첨부 보호·파일 처리·SMTP 전달·업데이트 |
| `src/eml_viewer/gui/main_window.py`, `window_manager.py` | 열람·저장·설정 방송. 저장 성공 후 설정 적용, 실패 사용자 안내 |
| `src/eml_viewer/gui/attachment_widgets.py`, `ui_helpers.py`, `theme.py` | 행 선택과 첨부 열기·저장, 접어도 유지하는 작업 버튼, 안전한 표시·생략·팔레트 대비. 원본 데이터·추출 정책은 변경하지 않음 |
| `src/eml_viewer/gui/settings_dialog.py` | 실제 설정 서비스의 저장 폴더와 백업 범위 표시 |
| `src/eml_viewer/i18n/locales/` | 영어·한국어 사용자 문구 |
| `installer/eml_viewer.spec`, `installer/setup.iss` | PyInstaller·Inno의 유일한 정의. staging 출력·기존 AppId/경로·UserSetting 보호 |
| `packaging/pyinstaller/eml_viewer.spec`, `packaging/inno/eml_viewer.iss` | 과거 경로의 호환 wrapper. 새 정의로 위임하며 별도 제품 정의를 유지하지 않음 |
| `scripts/build_windows.ps1`, `build_installer.ps1` | 앱 번들 및 미서명 설치 검수본. 공식 release 변경 없음 |
| `scripts/ReleasePipeline.ps1`, `sign_and_release.ps1` | clean source·테스트→번들 EXE 서명→설치 EXE 한 개→검증→덮어쓰기 없는 승격 |
| `scripts/release_artifacts.py` | 설치 EXE·해시·출처·서명 근거, 배타적 신규 파일 반영, 외부 변경 파일을 보존하는 롤백. extract는 경고를 출력하는 verify-only 호환 alias |
| `scripts/Signing.ps1`, `VerifySignatures.ps1` | 지정 서명자·타임스탬프 검증. 검증 스크립트는 실제 서명을 하지 않음 |
| `tests/` | 사용자 설정·기존 Roaming 경로·cwd 격리, 저장/SMTP/배포 실패주입 |
| `scripts/run_external_review.py`, `.agents/agents/gemini-review.md` | Codex의 외부 CLI 검수 연결. 모델·agent 등록/활성화·완료 응답 검증, raw 기록은 Git 제외 build/에 보관 |
| `scripts/benchmark_email.py` | 사용자 메일 없이 합성 EML의 파싱·일괄 첨부 저장 측정. EXE 시작/UI 측정과 구분 |
| `src/eml_viewer/services/folder_navigation.py` | 한 폴더 목록 재사용, 디렉터리 identity/mtime·명시적 무효화·변경 중 재시도 |
| `scripts/profile_email.py`, `compare_parser.py`, `benchmark_folder_navigation.py` | 파싱 profiler/벽시계 분리, SHA 검증 단건 추출, 순서 교대 폴더 비교 |
| `scripts/benchmark_widget_startup.py`, `benchmark_html_ready.py`, `smoke_pdf_output.py` | 합성 source/offscreen 빈 창·실제 HTML marker·CID PDF 검증. 설치형/physical printer와 구분 |

설정은 인지되는 frozen 실행 파일 옆 `UserSetting`, 그 외 `%LOCALAPPDATA%/Programs/EML Viewer/UserSetting/settings.json`에 있습니다.
예전 Roaming 설정은 원본 보존 후 새 설정이 없을 때만 고유 staging과 원본/복사 검증·덮어쓰기 없는 승격으로 이관합니다. 이관 실패는 시작을 중단하며 기본값 저장으로 숨기지 않습니다.
원본 이메일·저장 첨부·PDF는 사용자 선택 위치에 있으며 설정 백업에 자동 포함되지 않습니다.
파일 로그를 생성하지 않으며 진단 메시지는 표준 logging의 콘솔 출력입니다.

[백업·검증 복원](USER_DATA.md), [공통 백업 도구](../scripts/Manage-UserData.ps1),
[3–5단계 검수](STANDARDIZATION_PHASE3_5_REVIEW.md), [배포 검수](STANDARDIZATION_PHASE2_REVIEW.md)를 함께 확인하세요.
로컬 `AI_CODE_MAP.md`·개인 지침은 공개 Git 추적에 추가하지 않습니다.

2026-10-12 성능 변경: EML 일괄 저장은 `EmlParser.iter_extracted_attachments`로
작업 수명 동안 1회 해석하고 선택 payload만 디코드합니다. MSG는 기존 단건 추출
경로를 유지합니다. 본문 text의 제외 규칙을 표시·추출 인덱스에 동일하게 적용합니다.
[개선계획](PERFORMANCE_IMPROVEMENT_PLAN.md), [CLI 연결 안내](ANTIGRAVITY_CLI_SETUP.md).

2026-10-13: 실제 UI 열기는 창별 1 worker/최신 대기 1개의 비동기 경로를 사용하며
동기 load_email은 호환 API입니다. folder_navigation.py는 현재 폴더만 재사용하고
변경 감시/감시 실패를 처리합니다. HTML renderer/import는 첫 HTML까지 지연됩니다.
통합·Opus 검수·측정 경계는 [통합 기록](PERFORMANCE_OVERNIGHT_20261013.md)에 있습니다.

2026-10-13 UI/UX: 첨부 선택을 Windows 행 선택 방식으로 통일하고 열기·선택 저장·
모두 저장을 상시 표시합니다. 첫 화면·아이콘 툴바·간결한 메일 요약과 펼치는 상세
정보를 제공하며 본문 renderer는 한 번만 생성합니다.
[UI/UX 개선·검수 기록](UI_UX_IMPROVEMENT_20261013.md).
