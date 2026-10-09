# 3–5단계 설정·구조·문구 검수

검수일: 2026-10-08. 이전 단계 변경과 공식 배포물을 보존했습니다.

## 변경과 보존 계약

- 1단계의 사용자 SMTP 포트 25/빈 서버 우선순위, 고유 임시 파일·fsync·원자 교체, 실패 시 기존 설정 보존과 UI 안내를 유지했습니다. 이번에는 실제 SettingsService의 저장 폴더·백업 범위를 설정 화면에 표시했습니다.
- 손상 JSON·잘못된 UTF-8·객체가 아닌 기존 설정은 저장 전과 교체 직전에 검증합니다. 기본값 fallback 후 설정·geometry·최근 수신자·최근 파일 저장도 OSError로 차단하여 원본 바이트를 보존합니다. 자동 복구·스키마 변경은 하지 않습니다.
- 설정 파일은 인지되는 frozen EXE 옆 `UserSetting`, 그 외 `%LOCALAPPDATA%/Programs/EML Viewer/UserSetting/settings.json`입니다. 이전 Roaming 설정은 새 파일이 없을 때만 복사하며 원본을 보존합니다. 원본 EML/MSG·저장 첨부·PDF는 별도 사용자 선택 위치이며 파일 로그 writer는 없습니다.
- Roaming 이관은 고유 sibling staging→원본 JSON·바이트·파일 identity 검증→복사본 fsync→복사본/원본 재검증→덮어쓰기 없는 hard-link 승격으로 처리합니다. 경합 중 새 target이 생기면 그 파일을 우선하며 temp만 정리합니다. 실패를 숨기지 않고 OSError로 시작을 중단해 부분 target/기본값 자동 저장을 막고 재시도할 수 있습니다. 앱의 기존 QApplication 예외 안내 경로를 사용합니다.
- `installer/eml_viewer.spec`, `installer/setup.iss`로 정의를 모았습니다. Git의 installer 제외 규칙을 해제했으며 이전 `packaging/` 진입점은 새 정의로 위임하는 호환 wrapper입니다. 모든 실제 빌드 스크립트는 canonical을 참조합니다.
- `build_windows.ps1`도 기본 미서명으로 일치시켰습니다. 명시적인 `-Signed`·인증서 지정이 있어야 개발 번들을 서명합니다. 인증서가 없거나 `-SkipSign`과 동시 지정하면 빌드 전에 실패합니다.
- 공식 Signed 게이트는 offscreen pytest, 서명 회귀, 공통 백업 회귀를 요구하며 백업 성공 근거도 매니페스트 검증에 포함합니다. 기존 staging·실행 파일 서명 순서·동일 별칭·덮어쓰기 없는 승격·외부 변경 파일 롤백 보호를 유지합니다.
- 기존 AppId·설치 경로·UserSetting 보호·AppMutex를 유지했습니다. 실행 중 구버전은 닫도록 안내하고 안전 차단하는 정책이며 자동 종료를 검증한 것으로 표시하지 않습니다.
- [공개 코드 지도](CODE_MAP.md), README 두 언어와 packaging 안내를 실제 구조에 맞췄습니다. 로컬 개인 지도는 추적하지 않습니다. [공통 백업 도구](../scripts/Manage-UserData.ps1)·[사용자 자료 계약](USER_DATA.md)은 총괄 담당자가 제공했습니다.

## 자동 검수 근거

- `.venv` Python + `QT_QPA_PLATFORM=offscreen`: 최종 전체 pytest **177개 + 36 subtests**, 프로세스 exit 0. 손상 원본 보호·자동 저장 경로·임시 작성 후 외부 손상 발생 13개와 이관 실패·재시도·부분 복사·fsync·원본 변경·target 경합·손상 원본 검수 9개를 포함합니다.
- canonical/호환 PyInstaller spec의 실제 분석 입력·자료·아이콘 경로 일치 및 지정 설정 폴더 화면 표시 검수 통과. 전체 배포 실패주입 검수에는 잘못된 백업 성공 근거 거부도 추가했습니다.
- Windows PowerShell 5: 모의 서명·경로·명시적 개발 build guard 10, 공통 백업 32 — **42 assertions**. 실제 인증서 서명은 수행하지 않습니다.
- 변경 Python의 Ruff E/F 검사(기존 긴 줄 제외), PowerShell 파싱, `git diff --check` 통과.
- 실제 Inno Setup 6으로 canonical과 호환 wrapper 각각 더미 EXE fixture를 소유한 `build/standardization/inno-*/output`에 컴파일했습니다. 두 컴파일 성공은 설치 실행 증거가 아닙니다. CLI fixture 버전 0.9.99를 사용했으며 제품 버전 0.1.16은 변경하지 않았습니다.
- 담당 회귀 이후 총괄은 최종 이관 보호 소스의 canonical `installer/eml_viewer.spec`로 실제 전체 PyInstaller 미서명 빌드를 확인했습니다. exitCode=0, sourceStable=true, officialPromoted=false이며 `build/standardization/canonical-package-result.json`에 기록했습니다. 결과는 소유한 `build/standardization/canonical-package-66e5aca5a91944bf9f7cfe6818e6f375`에 있고 공식 폴더에 반영하지 않았습니다.
- 공식 `release/` 파일 **6개**의 개수와 SHA-256이 2단계 이전 기준과 같습니다. 기준은 `build/phase2-review/release-baseline.json`입니다.
- installer에 있던 과거 배포 관련 파일 16개는 총괄이 이동 전후 해시를 검증해 Git 제외 `build/release-history/installer-legacy-32132f70113a45c09383faac9327362a`에 보존했습니다. `preserved-files.json`에 원래 경로·크기·해시가 있으며 공식 release/와 현재 설치는 변경하지 않았습니다.
- pytest의 LOCALAPPDATA·APPDATA·USERPROFILE·cwd를 임시 폴더에 격리했습니다. 이전 06 runner 테스트가 07 cwd에 만든 중립적인 결과 CSV 두 개는 생성 근거를 확인한 뒤 소유한 `build/standardization/test-generated-results`로 옮겼습니다. 사용자 자료 삭제는 하지 않았고 `results/`도 추적 제외했습니다.

QtWebEngine의 offscreen GPU context 진단이 출력되지만 테스트와 프로세스 종료는 성공했습니다. 자동 검수는 실제 화면 열람·SMTP 전달·설치·업그레이드 완료 증거가 아닙니다.

## Gemini 사용과 독립 검수

Antigravity CLI `gemini-3.8-flash-high`, effort `high`에 설정 저장·정확한 UI 문구를 도구 없이 검수하도록 요청했습니다. 실제 내용이 있는 SUCCESS 응답 1회, 경과 107.167초(모델 기록 101.850초), conversation `04bcf111-2b3a-40a9-b670-c500bf4f3afb`입니다. 증거는 무시되는 `build/standardization/agy-phase3-5.json`에 있습니다. 06/07 공통 요청 1회이며 두 회 실행으로 집계하지 않습니다. 입력 22,887·출력 10,098·합계 32,985 토큰으로 토큰 절약을 확인한 결과는 아닙니다.

응답의 존재하지 않는 함수·틀린 인자·구현 없는 진단 버튼·설정만 백업한다는 설명은 독립 검수에서 제외했습니다. 실제 기능과 전체 백업 범위에 맞췄으며 권한 우회·전역 설정 변경은 하지 않았습니다.

## 남은 실제 게이트

사용자 서명 세션, 새 공식 서명물 생성, GitHub 게시, 실제 설치·실행 중 구버전 교체, 실제 SMTP·번역·화면 사용은 수행하지 않았습니다. 기존 공식 파일과 외부 사용자 자료를 보존했습니다.
