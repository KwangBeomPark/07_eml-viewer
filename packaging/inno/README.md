# Inno Setup packaging

이 폴더는 이전 호출 경로를 보존하는 호환 wrapper입니다. 실제 설치 정의는 `installer/setup.iss`입니다.

## 필요 도구

- Inno Setup 6 또는 7
- Python 개발 환경
- PyInstaller

## 빌드

```powershell
.\scripts\build_installer.ps1
```

결과 파일:

```text
build\release-staging\<id>\artifacts\App07_EmlViewer_Setup_v<version>.exe
```

설치 파일은 `.eml` 및 `.msg` 더블클릭 연결을 선택 항목으로 제공합니다.
미서명 기본 빌드는 공식 `release/`를 바꾸지 않습니다. 서명·검증과 실제 설치·게시는 별도 절차입니다.
