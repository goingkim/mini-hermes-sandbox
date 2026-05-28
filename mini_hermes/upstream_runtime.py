from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from mini_hermes.privacy import clean_text, redact_text
from mini_hermes.settings import Settings, load_settings
from mini_hermes.upstream import HermesUpstream


DEFAULT_SAFE_TOOLSETS = ("memory", "todo", "web")
DANGEROUS_TOOLSETS = {
    "*",
    "all",
    "terminal",
    "file",
    "code_execution",
    "delegation",
    "full_stack",
}
UPSTREAM_PROVIDER_ALIASES = {
    "openai": "openai-api",
    "openai-api": "openai-api",
    "deepseek": "deepseek",
    "anthropic": "anthropic",
    "claude": "anthropic",
    "gemini": "gemini",
}


@dataclass(frozen=True)
class UpstreamHermesRun:
    prompt: str
    provider: str
    model: str
    toolsets: tuple[str, ...]
    command_display: str
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    status: str

    @property
    def ok(self) -> bool:
        return self.status == "success" and self.returncode == 0


class UpstreamHermesRuntime:
    """Subprocess wrapper around the vendored upstream Hermes CLI."""

    def __init__(
        self,
        settings: Settings | None = None,
        upstream: HermesUpstream | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.upstream = upstream or HermesUpstream()
        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]

    def run_oneshot(
        self,
        prompt: str,
        toolsets: tuple[str, ...] | list[str] | str | None = None,
        timeout_seconds: int = 300,
        ignore_rules: bool = True,
        allow_dangerous_toolsets: bool = False,
    ) -> UpstreamHermesRun:
        self.upstream._ensure_available()
        prompt = clean_text(prompt)
        normalized_toolsets = self._normalize_toolsets(toolsets)
        if not allow_dangerous_toolsets:
            dangerous = sorted(set(normalized_toolsets) & DANGEROUS_TOOLSETS)
            if dangerous:
                raise ValueError(
                    "dangerous upstream Hermes toolsets require explicit approval: "
                    + ", ".join(dangerous)
                )

        provider = self._upstream_provider()
        command = [
            sys.executable,
            str((self.upstream.root / "hermes").resolve()),
            "-z",
            prompt,
            "--provider",
            provider,
            "--model",
            self.settings.model,
        ]
        if ignore_rules:
            command.append("--ignore-rules")
        if normalized_toolsets:
            command.extend(["-t", ",".join(normalized_toolsets)])

        command_display = self._command_display(provider, self.settings.model, normalized_toolsets, ignore_rules)
        env = self._build_env(provider)
        started = time.monotonic()

        try:
            completed = subprocess.run(
                command,
                cwd=str(self.project_root),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(1, int(timeout_seconds)),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            stdout = self._redact(exc.stdout or "")
            stderr = self._redact(exc.stderr or "")
            return UpstreamHermesRun(
                prompt=self._redact(prompt),
                provider=provider,
                model=self.settings.model,
                toolsets=normalized_toolsets,
                command_display=command_display,
                returncode=124,
                stdout=stdout,
                stderr=stderr or f"timeout after {timeout_seconds} seconds",
                elapsed_seconds=elapsed,
                status="timeout",
            )

        elapsed = time.monotonic() - started
        stdout = self._redact(completed.stdout)
        stderr = self._redact(completed.stderr)
        return UpstreamHermesRun(
            prompt=self._redact(prompt),
            provider=provider,
            model=self.settings.model,
            toolsets=normalized_toolsets,
            command_display=command_display,
            returncode=int(completed.returncode),
            stdout=stdout,
            stderr=stderr,
            elapsed_seconds=elapsed,
            status="success" if completed.returncode == 0 else "error",
        )

    def _normalize_toolsets(self, toolsets: tuple[str, ...] | list[str] | str | None) -> tuple[str, ...]:
        if toolsets is None:
            return DEFAULT_SAFE_TOOLSETS
        raw_items = [toolsets] if isinstance(toolsets, str) else list(toolsets)
        normalized: list[str] = []
        for item in raw_items:
            normalized.extend(part.strip() for part in str(item).split(",") if part.strip())
        return tuple(dict.fromkeys(normalized))

    def _upstream_provider(self) -> str:
        provider = self.settings.provider_name.strip().lower()
        return UPSTREAM_PROVIDER_ALIASES.get(provider, provider)

    def _build_env(self, provider: str) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["HERMES_INFERENCE_PROVIDER"] = provider
        env["HERMES_INFERENCE_MODEL"] = self.settings.model
        env["HERMES_ACCEPT_HOOKS"] = "1"
        self._add_browser_environment(env)

        api_key = self.settings.api_key
        if api_key:
            if self.settings.api_key_env:
                env[self.settings.api_key_env] = api_key
            if provider == "deepseek":
                env["DEEPSEEK_API_KEY"] = api_key
            elif provider == "openai-api":
                env["OPENAI_API_KEY"] = api_key
            elif provider == "anthropic":
                env["ANTHROPIC_API_KEY"] = api_key
            elif provider == "gemini":
                env["GEMINI_API_KEY"] = api_key
                env["GOOGLE_API_KEY"] = api_key

        base_url = self._upstream_base_url(provider)
        if base_url:
            base_url_env = {
                "deepseek": "DEEPSEEK_BASE_URL",
                "openai-api": "OPENAI_BASE_URL",
                "anthropic": "ANTHROPIC_BASE_URL",
                "gemini": "GEMINI_BASE_URL",
            }.get(provider)
            if base_url_env:
                env[base_url_env] = base_url

        return env

    def _add_browser_environment(self, env: dict[str, str]) -> None:
        hermes_home = Path(env.get("HERMES_HOME") or Path.home() / ".hermes")
        candidate_paths = [
            hermes_home / "node",
            hermes_home / "node" / "bin",
            hermes_home / "node_modules" / ".bin",
        ]
        existing_path = env.get("PATH", "")
        existing_parts = {part for part in existing_path.split(os.pathsep) if part}
        prepend = [str(path) for path in candidate_paths if path.exists() and str(path) not in existing_parts]
        if prepend:
            env["PATH"] = os.pathsep.join([*prepend, existing_path])

        if not env.get("AGENT_BROWSER_EXECUTABLE_PATH"):
            browser = self._detect_windows_browser()
            if browser:
                env["AGENT_BROWSER_EXECUTABLE_PATH"] = str(browser)

    @staticmethod
    def _detect_windows_browser() -> Path | None:
        if sys.platform != "win32":
            return None
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _upstream_base_url(self, provider: str) -> str:
        base_url = (self.settings.base_url or "").strip().rstrip("/")
        if not base_url:
            return ""
        if provider == "deepseek" and base_url in {"https://api.deepseek.com", "https://api.deepseek.com/v1"}:
            return ""
        if provider == "deepseek" and not base_url.endswith("/v1"):
            return f"{base_url}/v1"
        return base_url

    def _redact(self, text: str) -> str:
        return redact_text(text, extra_secrets=(self.settings.api_key,))

    @staticmethod
    def _command_display(
        provider: str,
        model: str,
        toolsets: tuple[str, ...],
        ignore_rules: bool,
    ) -> str:
        parts = [
            "python",
            "vendor/hermes-agent/hermes",
            "-z",
            "[PROMPT]",
            "--provider",
            provider,
            "--model",
            model,
        ]
        if ignore_rules:
            parts.append("--ignore-rules")
        if toolsets:
            parts.extend(["-t", ",".join(toolsets)])
        return " ".join(parts)
