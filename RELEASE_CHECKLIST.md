# EML Viewer 사용자 릴리즈 체크리스트

2026-10-09 릴리스 준비 수정·검수. 설정 이관의 Windows 오류 확인·경합 검사, CLI 안내와 문서를 최소 수정하고 격리 회귀·미서명 빌드를 실행했습니다. 실제 사용자 설정·기존 공식 파일은 유지했으며 KSP 서명·설치·게시·태그 생성·커밋은 실행하지 않았습니다.

## 현재 판정과 선행 게이트

현재 소스 버전은 **0.1.17**, 공개 최신은 0.1.16입니다. 공식 계약은 `App07_EmlViewer_Setup_v<version>.exe` 하나와 `App07_EmlViewer_v<version>-manifest.json`, `App07_EmlViewer_v<version>-SHA256SUMS.txt`의 **3개**입니다. 이전 별칭/설치 ZIP/포터블 ZIP 생성은 제거돼 있습니다. 과거 공개 자산은 유지합니다.

- [x] 설치 파일 표기를 `App07_EmlViewer_Setup_v<version>.exe`로 맞췄습니다. 현재 updater 우선 패턴과 일치합니다. AppId·설치 폴더는 유지합니다.
- [x] 현재 소스의 전체 자동 회귀 **214개+36 subtests**, mock signing/path **10**, backup **32** 검사 통과. 이전 177개 결과 대신 이번 소스 결과를 사용합니다. 버전은 pyproject·__init__·설치 기본값 모두 **0.1.17**, 로컬/원격 v0.1.17 태그 부재를 조회로 확인했습니다. 게시 직전에 다시 확인합니다.
- [ ] 트레이·시작 시 자동 실행·단일 인스턴스·윈도우 관리의 실제 동작을 확인합니다. 이번 자동 회귀는 offscreen이며 실제 시작프로그램/화면/SMTP·Windows 설치를 대신하지 않습니다.
- [ ] 구버전 updater/외부 링크가 새 자산을 받을 수 있는지 확인합니다. 설치 AppId·EmlViewer.exe·파일 연결·UserSetting은 파일명과 별개로 유지합니다.
- [x] extract는 verify-only 호환 alias임을 경고로 명시했습니다. 실제 추출 경로를 출력한다는 안내를 제거했으며 이번 검사에서 파일을 생성/변경하지 않는 것을 확인했습니다. 아래는 실제 signed staging을 검사하는 명령입니다.
- [ ] 아래 파일 시스템·경합/권한 및 Windows 설치 게이트를 완료합니다. 정책을 해제/우회하거나 실제 사용자 환경으로 설치 시험을 하지 않습니다.

## 이관과 파일 시스템

설정 이관은 hard-link 실패 시 Windows MoveFileW로 덮어쓰기 없이 승격합니다. 이번에는 Unicode 인자와 Win32 오류를 명시적으로 확인하고 hard-link 불가 시 실제 MoveFileW의 성공·대상 생성 경합 보존, 권한 오류 실패주입·원본 보존을 검사했습니다. 실제 FAT32/exFAT USB와 보안 정책/ACL의 실환경 검수는 남아 있습니다. POSIX에서 hard link를 사용할 수 없으면 부분 파일을 쓰지 않고 거부합니다.

공식 release 승격은 os.link를 사용하며 현재 작업 드라이브 C:가 NTFS인 것을 읽기 확인했습니다. hard link 불가 시 원본 release를 보존하고 실패하는 자동 검사가 통과했습니다. 임시 파일은 목적지 디렉터리에 생성되며 다른 볼륨으로 연결하지 않습니다. FAT32/exFAT는 hard link 미지원입니다([Microsoft 비교표](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison)). 해당 환경에서 공식 승격을 실행하지 않으며 fallback으로 원본을 덮어쓰지 않습니다.

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

- [ ] 격리된 실제 Windows에서 구버전 종료 안내/AppMutex 차단, 설치·업그레이드·실패/취소·제거·UserSetting 보존, 이메일 열람/첨부/번역/전달·구버전 업데이트를 확인합니다. 종료 안내를 자동 정상 종료 성공으로 표시하지 않습니다. 현재 설치 EXE의 컴파일 후 서명 외 SignedUninstaller 콜백은 없으므로 설치된 제거 프로그램의 서명/Windows 실행 정책을 별도로 확인합니다.
- [ ] 같은 검수 commit의 원격 v<version> 태그와 세 파일을 확인합니다. 현재 안전 게시 wrapper는 없으므로 다음은 사용자가 실제 게이트 후 실행할 draft 게시 절차입니다. 기존 동일 태그가 있으면 자동 재생성/덮어쓰기를 하지 않습니다.

```powershell
$Tag = "v$Version"
$Repo = 'KwangBeomPark/07_eml-viewer'
$ErrorActionPreference = 'Stop'
$Origin = (git remote get-url origin).Trim()
if ($LASTEXITCODE -ne 0 -or $Origin -notin @("https://github.com/$Repo.git", "git@github.com:$Repo.git")) { throw 'Unexpected origin repository.' }
$Status = @(git status --porcelain)
if ($LASTEXITCODE -ne 0 -or $Status.Count) { throw 'Use the approved clean source.' }
$Branch = (git branch --show-current).Trim()
if ($LASTEXITCODE -ne 0 -or $Branch -ne 'main') { throw 'Use the approved main branch.' }
$Commit = (git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $Commit -notmatch '^[0-9a-f]{40}$') { throw 'Cannot resolve source commit.' }
$Receipt = Get-Content -LiteralPath (Join-Path $Stage 'receipt.json') -Raw | ConvertFrom-Json
if ($Receipt.source.commit -ne $Commit -or $Receipt.source.dirty) { throw 'Signed staging differs from the approved clean source.' }
$RemoteRef = gh api "repos/$Repo/git/ref/tags/$Tag" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Prepare the reviewed remote tag first; do not move an old tag.' }
$Object = $RemoteRef.object
while ($Object.type -eq 'tag') {
  $TagObject = gh api "repos/$Repo/git/tags/$($Object.sha)" | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve annotated remote tag.' }
  $Object = $TagObject.object
}
if ($Object.type -ne 'commit' -or $Object.sha -ne $Commit) { throw 'Remote tag differs from the signed source commit.' }
$Files = @(
  "release\App07_EmlViewer_Setup_v$Version.exe",
  "release\App07_EmlViewer_v$Version-manifest.json",
  "release\App07_EmlViewer_v$Version-SHA256SUMS.txt"
)
gh release create $Tag @Files --repo $Repo --verify-tag --draft --title "EML Viewer $Tag" --generate-notes
if ($LASTEXITCODE -ne 0) { throw 'Draft creation failed; existing assets were not overwritten.' }
```

- [ ] draft의 세 파일을 새 빈 폴더에 다운로드하고 이름/개수·크기·SHA-256·서명을 로컬 검증 세트와 대조합니다. 실제 설치 합격 로그와 사용자 최종 검토가 끝난 뒤만 공개합니다.

```powershell
$DownloadRoot = Join-Path $PWD ('build\remote-check-' + [guid]::NewGuid().ToString('N'))
$DraftIdentity = gh release view $Tag --repo $Repo --json apiUrl | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $DraftIdentity.apiUrl -notmatch ("^https://api\.github\.com/repos/" + [regex]::Escape($Repo) + "/releases/[0-9]+$")) { throw 'Cannot resolve the expected draft release.' }
$RemoteRelease = gh api $DraftIdentity.apiUrl | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $RemoteRelease.tag_name -cne $Tag -or $RemoteRelease.draft -ne $true -or $RemoteRelease.prerelease -ne $false -or @($RemoteRelease.assets).Count -ne 3 -or @($RemoteRelease.assets | Where-Object { $_.state -ne 'uploaded' }).Count) { throw 'Unexpected draft identity or upload state; publication is blocked.' }
gh release download $Tag --repo $Repo --dir $DownloadRoot
if ($LASTEXITCODE -ne 0) { throw 'Cannot download the draft.' }
$ExpectedNames = @($Files | ForEach-Object { Split-Path -Leaf $_ })
if (@(Compare-Object ($ExpectedNames | Sort-Object) (@(Get-ChildItem -LiteralPath $DownloadRoot -File).Name | Sort-Object)).Count) { throw 'Unexpected remote asset set.' }
foreach ($File in $Files) {
  if ((Get-FileHash -LiteralPath $File).Hash -ne (Get-FileHash -LiteralPath (Join-Path $DownloadRoot (Split-Path -Leaf $File))).Hash) { throw 'Remote bytes differ from the verified local set.' }
}
.\.venv\Scripts\python.exe .\scripts\release_artifacts.py verify --stage $Stage --release $DownloadRoot --version $Version
if ($LASTEXITCODE -ne 0) { throw 'Downloaded provenance verification failed.' }
.\scripts\VerifySignatures.ps1 -Directory $DownloadRoot -CertificateThumbprint $env:SIGN_CERT_THUMBPRINT
if (-not $? -or $LASTEXITCODE -ne 0) { throw 'Downloaded signature verification failed; keep the draft.' }
# 위 검증과 실제 설치 합격 후 사용자가 공개
gh release edit $Tag --repo $Repo --draft=false --verify-tag --latest
if ($LASTEXITCODE -ne 0) { throw 'Publication failed; do not report completion.' }
$PublishedRelease = gh api "repos/$Repo/releases/tags/$Tag" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $PublishedRelease.tag_name -cne $Tag -or $PublishedRelease.draft -ne $false -or $PublishedRelease.prerelease -ne $false -or @($PublishedRelease.assets).Count -ne 3) { throw 'Published release state could not be verified; preserve it for inspection.' }
foreach ($File in $Files) {
  $AssetMatches = @($PublishedRelease.assets | Where-Object { $_.name -ceq (Split-Path -Leaf $File) })
  if ($AssetMatches.Count -ne 1 -or $AssetMatches[0].state -ne 'uploaded' -or $AssetMatches[0].size -ne (Get-Item -LiteralPath $File).Length -or $AssetMatches[0].digest -cne ('sha256:' + (Get-FileHash -LiteralPath $File).Hash.ToLowerInvariant())) { throw 'Published asset differs from the approved local set; do not overwrite it.' }
}
```

- [ ] 공개 후 다시 다운로드/서명·해시를 확인합니다. 과거 태그/자산·generic 장부를 삭제하거나 --clobber로 교체하지 않습니다.

[설치 합격표](docs/INSTALL_UPGRADE_ACCEPTANCE.md) · [이번 전체 재검토](../04_DataRefinery/docs/CLEANUP_AND_RELEASE_REVIEW.md)

## Gemini/검수 경계

10월 8일 빈 response·0토큰 요청은 미완료였습니다. 이번 10월 9일 06/07 공동 Gemini 3.8 Flash High/effort high 계약 검토는 **54.54초, 내용 있는 SUCCESS**, conversation `229c6169-5f07-48fe-8bcc-251b0cebcf51`입니다. 응답 근거는 06 `build/standardization/release-ready-18726ede62c44a229e5257b67ab08b66/agy-contract-review.json`에 보존합니다. 경합·권한 검수를 반영했으며 목적지와 같은 폴더의 임시 파일에 교차 볼륨 우려를 적용하지 않았습니다. CLI 보고 28,407토큰이며 크레딧 차감은 미확인입니다.

이번 미서명 전체 PyInstaller/Inno 빌드는 `build/release-staging/5b5c6a4ad80547ada95e15457c8e0afc`입니다. 설치 기본 버전·최종 runtime 소스까지 다시 빌드했고 **exit 0, sourceStable=true, sourceDirty=true, officialPromoted=false**입니다. 최신 로그 `build/standardization/signing-preparation-final-build.log`, 요약 `build/standardization/signing-preparation-final-result.json`, 전체 pytest 로그 `build/standardization/signing-preparation-pytest.log`에 보존합니다. 현재 변경은 미커밋이므로 승인 커밋 후 새 빌드·테스트·서명을 다시 해야 합니다. 실제 서명·설치·게시 성공은 표시하지 않습니다.
