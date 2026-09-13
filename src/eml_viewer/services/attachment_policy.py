from __future__ import annotations

from pathlib import Path

# Windows 환경에서 실행 및 매크로 위협이 있는 위험 확장자 목록 (보안 가드레일)
DANGEROUS_EXTENSIONS: frozenset[str] = frozenset(
    {
        # 실행 파일 및 바이너리
        ".exe", ".bat", ".cmd", ".com", ".msi", ".msp", ".scr", ".pif",
        # 스크립트 엔진
        ".js", ".jse", ".vbs", ".vbe", ".wsf", ".wsh", ".ps1", ".ps1xml",
        ".msh", ".sct", ".scf", ".hta", ".cpl", ".msc",
        # 설치 및 단축기 패키지
        ".application", ".appref-ms", ".gadget", ".lnk", ".url", ".chm",
        # 매크로 및 오피스 확장
        ".docm", ".xlsm", ".pptm", ".dotm", ".xltm", ".xlam",
        ".xll", ".iqy", ".slk",
        # 디스크 이미지 및 레지스트리
        ".iso", ".img", ".reg", ".jar",
    }
)


def is_dangerous_extension(filename: str | Path) -> bool:
    """주어진 파일명이 보안 경고가 필요한 위험 확장자를 포함하는지 판별합니다."""
    path = Path(filename)
    suffix = path.suffix.lower()
    return suffix in DANGEROUS_EXTENSIONS
