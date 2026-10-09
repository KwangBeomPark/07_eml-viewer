# Compatibility entry point; the canonical definition is installer/eml_viewer.spec.
from pathlib import Path

canonical_spec = Path(SPECPATH).resolve().parents[1] / "installer" / "eml_viewer.spec"
SPECPATH = str(canonical_spec.parent)
exec(compile(canonical_spec.read_text(encoding="utf-8"), str(canonical_spec), "exec"))
