# EML Viewer 사용자 릴리즈 체크리스트

2026-10-09 현재 소스 재확인. 이 문서만 갱신했으며 코드·사용자 자료·배포물을 변경하거나 삭제·서명·설치·게시를 실행하지 않았습니다.

## 현재 판정과 선행 게이트

현재 소스 버전은 **0.1.17**, 공개 최신은 0.1.16입니다. 공식 계약은 `App07_EmlViewer_Setup_v<version>.exe` 하나와 `App07_EmlViewer_v<version>-manifest.json`, `App07_EmlViewer_v<version>-SHA256SUMS.txt`의 **3개**입니다. 이전 별칭/설치 ZIP/포터블 ZIP 생성은 제거돼 있습니다. 과거 공개 자산은 유지합니다.

- [ ] 이 설치 파일 표기를 최종 확정합니다. 현재 updater의 App07_EmlViewer_Setup_ 우선 패턴과 맞습니다. 제안 이름은 현재 표기와 동일하지만 사용자 선택은 아직 대기입니다.
- [ ] 현재 단일 계약으로 실제 회귀·빌드·서명 검수를 다시 수행합니다. 이전 177개+36 subtests는 이후 소스 변경의 통과로 표시하지 않습니다. current pyproject와 __init__ 버전도 함께 확인합니다.
- [ ] 추가된 트레이·시작 시 자동 실행·단일 인스턴스·윈도우 관리의 실제 동작과 회귀를 검수합니다. 현재 git diff --check는 다른 작업의 tests/test_main_window.py:451 EOF 빈 줄을 지적하므로 작성자 변경과 함께 정리합니다.
- [ ] 구버전 updater/외부 링크가 새 자산을 받을 수 있는지 확인합니다. 설치 AppId·EmlViewer.exe·파일 연결·UserSetting은 파일명과 별개로 유지합니다.
- [ ] 이전 extract action은 현재 verify만 수행하고 추출 경로를 출력하지 않습니다. 아래는 실제 signed staging을 검사하는 현재 명령입니다. 불필요한 CLI action 제거는 별도 정리 후보로 검토합니다.
- [ ] 아래 파일 시스템·경합/권한 및 Windows 설치 게이트를 완료합니다. 정책을 해제/우회하거나 실제 사용자 환경으로 설치 시험을 하지 않습니다.

## 이관과 파일 시스템

설정 이관은 기존 hard-link 방식 실패 시 Windows MoveFileW의 덮어쓰기 없는 승격 fallback을 사용하는 코드가 추가됐습니다. 따라서 이전 'fallback 없음' 설명은 현재에 적용하지 않습니다. hard-link 불가 mock 검사는 확인됐으나 실제 FAT32/exFAT USB와 Windows 대상 생성 경합·권한 오류 성공 기록은 확인하지 못했습니다. 포터블 지원은 현재 생성 정책과 구분해 결정합니다.

공식 release 승격은 여전히 os.link를 사용하므로 서명 배포 작업 폴더도 hard link 지원을 확인합니다. FAT32/exFAT는 hard link 미지원입니다([Microsoft 비교표](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison)). 원본 Roaming과 기존 새 설정을 지우지 않으며 실패/재시도·부분 파일 보호를 검수합니다.

## 삭제 후보 — 사용자 검토 전 보존


용량은 조사 시점 파일 합계(byte), 아래 후보의 Git 추적 수는 모두 0입니다. 재빌드는 가능하더라도 동일 바이트 재현을 보장하지 않습니다.

| 절대 경로 | 파일 수 / byte | 역할·참조 | 재생성·삭제 조건 |
| --- | ---: | --- | --- |
| `C:\Dev\GitHub\07_eml-viewer\.pytest_cache` | 5 / 17,876 | pytest 캐시 | 다음 검사 때 생성. 과거 실패 목록이 불필요하고 검사 종료 시 후보 |
| `C:\Dev\GitHub\07_eml-viewer\.ruff_cache` | 8 / 1,622 | Ruff 캐시 | 다음 검사 때 생성. 검사 도구 종료 시 후보 |
| `C:\Dev\GitHub\07_eml-viewer\dist` | 2,941 / 576,546,113 | 과거 앱 번들. 새 release pipeline은 고유 staging 사용 | 설정·수동 실행본 없음 확인 후 후보. 개발 빌드로 재생성 가능 |
| `C:\Dev\GitHub\07_eml-viewer\build\eml_viewer` | 17 / 9,468,207 | 과거 PyInstaller 캐시 | 새 canonical 빌드 성공·프로세스 종료 확인 후 후보 |
| `C:\Dev\GitHub\07_eml-viewer\build\backup-test-38b968852e5a4a2cba8c917a17deb27c` | 22 / 9,790 | 공통 백업 fixture | 테스트로 재생성. 결과 요약 보존 후 후보 |
| `C:\Dev\GitHub\07_eml-viewer\build\backup-test-779dd290c7a648e2be0ce54b447f687f` | 24 / 11,680 | 동일 | 동일 |
| `C:\Dev\GitHub\07_eml-viewer\build\backup-test-97e86a978c314d52abb582638ec991d5` | 24 / 11,673 | 동일 | 동일 |
| `C:\Dev\GitHub\07_eml-viewer\build\backup-test-aa6838219bef47a9bba8dae2bc7de04f` | 22 / 9,790 | 동일 | 동일 |
| `C:\Dev\GitHub\07_eml-viewer\build\standardization\canonical-package-66e5aca5a91944bf9f7cfe6818e6f375` | 3,007 / 633,067,654 | 검수용 새 canonical 미서명 빌드 | root의 `canonical-package-result.json`·로그·출처를 별도 보존한 뒤 큰 번들/캐시만 후보 |
| `C:\Dev\GitHub\07_eml-viewer\build\standardization\inno-6757015ecf024c54ab2943650b541a10` | 3 / 2,149,901 | 더미 설치 fixture | 재컴파일 가능. 성공 기록 보존 후 후보 |
| `C:\Dev\GitHub\07_eml-viewer\build\standardization\inno-bcaf1396809b4beda1c5e9820385563d` | 3 / 2,152,287 | 호환 wrapper fixture | 동일 |
| `C:\Dev\GitHub\07_eml-viewer\build\standardization\portable-signature-0ae84291c2734a279394acd5ad9b10f6` | 1 / 2,315,656 | 기존 ZIP 내부 EXE 검수 추출본 | 원본 ZIP 보존·검수 요약 기록 후 후보 |
| `C:\Dev\GitHub\07_eml-viewer\custom_macros` | 0 / 0 | 빈 폴더. EML 기능 참조 없음 | 06 `test_m5.py`의 상대경로·생성 시각과 관련이 추정되지만 생성 주체 확정 아님. 사용자/외부 도구 참조가 없다고 확인해야 후보 |
| `C:\Dev\GitHub\07_eml-viewer\results` | 0 / 0 | 빈 폴더. 이전 06 fixture CSV 두 개의 보존 이동 근거 있음 | 새 pytest cwd 격리로 저장소 결과 생성 방지. 사용자/외부 도구 참조 없음 확인 후 빈 폴더만 후보 |

`custom_macros`/`results` 생성 시각은 각각 2026-10-07 23:49:29/30(현지)입니다. 파일 내용을 공개하거나 이름만으로 사용자 자료를 삭제 대상으로 판단하지 않았습니다. 옮겨 보존한 fixture CSV 2개/951 byte는 `build/standardization/test-generated-results`에 있습니다.

검토 후에만 추가 후보: `build/release-staging` 3,006개/790,974,913 byte의 불필요한 미서명 preview. **유효한 signed staging의 receipt·검증 입력은 보존**해야 하므로 폴더 전체를 일괄 삭제하지 않습니다. `build/phase2-review` 9개/2,764,823 byte와 `build/standardization`의 해시 기준·검수·Gemini 근거도 보존합니다.

기본 삭제 대상 제외: `C:\Dev\GitHub\07_eml-viewer\build\release-history` 17개/2,013,249,102 byte(역사 배포물 16개+경로/해시 ledger). 특히 `installer-legacy-32132f70113a45c09383faac9327362a`는 원본을 보존 이동한 자료이며 재생성 가능한 캐시가 아닙니다. 별도 백업·복원 및 원본 해시를 확인하고 사용자가 따로 결정해야 합니다. `release/`, `.venv/`, tracked `packaging/` 호환 wrapper, 실제 UserSetting·EML/MSG·첨부·PDF도 보존합니다.

## 사용자 서명·설치·게시 작업

- [ ] 현재 소스/문서·버전·릴리즈 노트를 검수하고 clean 검수 커밋을 확정합니다. 기존 0.1.16 태그/파일을 0.1.17 소스로 바꾸지 않습니다.
- [ ] 앱을 닫고 [USER_DATA](docs/USER_DATA.md) 범위의 전체 설정을 백업·검증합니다. 원본 EML/MSG·첨부·PDF는 별도 보관합니다.
- [ ] 의존성·Inno·Microsoft SignTool을 준비하고 SimplySign 로그인·PIN/OTP·인증서 선택은 사용자 직접 관리 서명 세션에서 처리합니다.
- [ ] 현재 단일 정책·검사·이관 게이트를 통과한 뒤 아래 공식 흐름으로 새 로컬 세트를 준비합니다. 개발 build_windows.ps1 -Signed로 공식 검수를 대체하지 않습니다.

```powershell
# 선택: 미서명 preview, 공식 release 변경 없음
.\scripts\build_installer.ps1
# 사용자 세션: 새 빌드·테스트·서명·검증·로컬 승격, 게시 없음
.\scripts\sign_and_release.ps1 -CertificateThumbprint $env:SIGN_CERT_THUMBPRINT
```

명시 -SignToolPath, -TimestampServer를 사용할 수 있습니다. -SkipBuild는 거부됩니다. 공식 작업 폴더의 hard-link 지원을 확인하고 기존 파일의 다른 바이트를 덮어쓰지 않습니다.

- [ ] 실제 사용한 버전·signed staging을 입력하고 앱 번들/공식 설치 파일의 서명·게시자·타임스탬프·해시·출처를 확인합니다. extract가 출력한 경로라는 안내를 사용하지 않습니다.

```powershell
$Version = '<실제 검수·서명한 버전>'
$Stage = 'C:\Dev\GitHub\07_eml-viewer\build\release-staging\<해당 signed staging ID>'
.\.venv\Scripts\python.exe .\scripts\release_artifacts.py verify --stage $Stage --release .\release --version $Version
.\scripts\VerifySignatures.ps1 -Directory "$Stage\dist\EmlViewer" -CertificateThumbprint $env:SIGN_CERT_THUMBPRINT
.\scripts\VerifySignatures.ps1 -Directory "$Stage\artifacts" -CertificateThumbprint $env:SIGN_CERT_THUMBPRINT
```

- [ ] 격리된 실제 Windows에서 구버전 종료 안내/AppMutex 차단, 설치·업그레이드·실패/취소·제거·UserSetting 보존, 이메일 열람/첨부/번역/전달·구버전 업데이트를 확인합니다. 종료 안내를 자동 정상 종료 성공으로 표시하지 않습니다.
- [ ] 같은 검수 commit의 원격 v<version> 태그와 세 파일을 확인합니다. 현재 안전 게시 wrapper는 없으므로 다음은 사용자가 실제 게이트 후 실행할 draft 게시 절차입니다. 기존 동일 태그가 있으면 자동 재생성/덮어쓰기를 하지 않습니다.

```powershell
$Tag = "v$Version"
$Files = @(
  "release\App07_EmlViewer_Setup_v$Version.exe",
  "release\App07_EmlViewer_v$Version-manifest.json",
  "release\App07_EmlViewer_v$Version-SHA256SUMS.txt"
)
gh release create $Tag @Files --verify-tag --draft --title "EML Viewer $Tag" --generate-notes
```

- [ ] draft의 세 파일을 새 빈 폴더에 다운로드하고 이름/개수·크기·SHA-256·서명을 로컬 검증 세트와 대조합니다. 실제 설치 합격 로그와 사용자 최종 검토가 끝난 뒤만 공개합니다.

```powershell
gh release download $Tag --dir '<새 검사 폴더>'
# 위 검증과 실제 설치 합격 후 사용자가 공개
gh release edit $Tag --draft=false --verify-tag
```

- [ ] 공개 후 다시 다운로드/서명·해시를 확인합니다. 과거 태그/자산·generic 장부를 삭제하거나 --clobber로 교체하지 않습니다.

[설치 합격표](docs/INSTALL_UPGRADE_ACCEPTANCE.md) · [이번 전체 재검토](../04_DataRefinery/docs/CLEANUP_AND_RELEASE_REVIEW.md)

## Gemini/검수 경계

10월 8일 06/07 공동 Gemini High 요청은 45초 print timeout·빈 response·0토큰으로 미완료였습니다(conversation 730c5bb8-a9e5-42c9-9012-120e6493c40a). 이번 문서는 현재 코드·CLI 도움말·파일 목록의 10월 9일 독립 읽기 검수입니다. 실제 서명·설치·게시를 실행하거나 완료로 표시하지 않았습니다.
