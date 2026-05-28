from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Iterator


SAFE_IMPORT_CHECK_MODULES = (
    "agent.trajectory",
    "tools.registry",
)


@dataclass(frozen=True)
class ImportCheck:
    module: str
    ok: bool
    path: str
    error: str = ""


@dataclass(frozen=True)
class UpstreamStatus:
    available: bool
    root: str
    commit: str
    source: str
    core_dirs: dict[str, int]


class HermesUpstream:
    """Adapter for the vendored NousResearch/hermes-agent source tree."""

    def __init__(self, root: str | Path | None = None) -> None:
        project_root = Path(__file__).resolve().parents[1]
        self.root = Path(root) if root is not None else project_root / "vendor" / "hermes-agent"

    def status(self) -> UpstreamStatus:
        available = self.is_available()
        return UpstreamStatus(
            available=available,
            root=str(self.root.resolve()) if self.root.exists() else str(self.root),
            commit=self._read_marker(".upstream_commit"),
            source=self._read_marker(".upstream_source"),
            core_dirs=self.core_inventory() if available else {},
        )

    def is_available(self) -> bool:
        return (
            self.root.exists()
            and (self.root / "README.md").exists()
            and (self.root / "pyproject.toml").exists()
            and (self.root / "agent").is_dir()
            and (self.root / "tools").is_dir()
        )

    def import_module(self, module_name: str) -> ModuleType:
        self._ensure_available()
        with self.source_path():
            return importlib.import_module(module_name)

    def import_checks(self, modules: tuple[str, ...] = SAFE_IMPORT_CHECK_MODULES) -> list[ImportCheck]:
        checks: list[ImportCheck] = []
        for module_name in modules:
            path = self.module_path(module_name)
            try:
                self.import_module(module_name)
            except Exception as exc:
                checks.append(
                    ImportCheck(
                        module=module_name,
                        ok=False,
                        path=str(path),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
            else:
                checks.append(ImportCheck(module=module_name, ok=True, path=str(path)))
        return checks

    def module_path(self, module_name: str) -> Path:
        parts = module_name.split(".")
        module_file = self.root.joinpath(*parts).with_suffix(".py")
        package_init = self.root.joinpath(*parts, "__init__.py")
        if module_file.exists():
            return module_file
        if package_init.exists():
            return package_init
        return module_file

    def core_inventory(self) -> dict[str, int]:
        names = ("agent", "tools", "cron", "gateway", "skills", "providers", "plugins")
        inventory: dict[str, int] = {}
        for name in names:
            folder = self.root / name
            if folder.exists():
                inventory[name] = sum(1 for path in folder.rglob("*.py") if path.is_file())
        return inventory

    @contextmanager
    def source_path(self) -> Iterator[None]:
        self._ensure_available()
        source = str(self.root.resolve())
        inserted = False
        if source not in sys.path:
            sys.path.insert(0, source)
            inserted = True
        try:
            yield
        finally:
            if inserted:
                try:
                    sys.path.remove(source)
                except ValueError:
                    pass

    def _ensure_available(self) -> None:
        if not self.is_available():
            raise FileNotFoundError(f"Vendored Hermes source is missing or incomplete: {self.root}")

    def _read_marker(self, name: str) -> str:
        path = self.root / name
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace").strip()
