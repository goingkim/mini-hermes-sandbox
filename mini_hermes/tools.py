from __future__ import annotations

import ast
import json
import operator
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from mini_hermes.store import MiniHermesStore
from mini_hermes.upstream_runtime import UpstreamHermesRuntime

try:
    from PIL import ImageGrab
except Exception:
    ImageGrab = None

try:
    import config
except ModuleNotFoundError:
    config = None


@dataclass(frozen=True)
class ToolContext:
    store: MiniHermesStore
    run_id: str
    workspace: Path


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool: {tool.name}")
        self._tools[tool.name] = tool

    def definitions(self) -> list[dict[str, Any]]:
        return [tool.as_openai_tool() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        return "\n".join(f"- {tool.name}: {tool.description}" for tool in self._tools.values())

    def dispatch(self, name: str, arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"unknown tool: {name}"}
        try:
            result = tool.handler(context, arguments)
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if "ok" not in result:
            result = {"ok": True, **result}
        return result


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    read_roots_hint = _read_roots_hint()
    write_roots_hint = _write_roots_hint()
    registry.register(
        Tool(
            name="calculate",
            description="Evaluate a safe arithmetic expression.",
            parameters=_object_schema(
                {
                    "expression": {
                        "type": "string",
                        "description": "Arithmetic expression using +, -, *, /, //, %, ** and parentheses.",
                    }
                },
                ["expression"],
            ),
            handler=_calculate,
        )
    )
    registry.register(
        Tool(
            name="capture_screen",
            description="Capture the current screen and save it as an observation for later learning.",
            parameters=_object_schema(
                {
                    "note": {"type": "string", "description": "What the screenshot is meant to capture."},
                    "action_label": {
                        "type": "string",
                        "description": "Short label such as open_email, write_document, inspect_error.",
                    },
                },
                [],
            ),
            handler=_capture_screen_tool,
        )
    )
    registry.register(
        Tool(
            name="remember",
            description="Store a persistent memory that should influence later runs.",
            parameters=_object_schema(
                {
                    "text": {"type": "string", "description": "Memory text to store."},
                    "kind": {"type": "string", "description": "Memory type, for example preference, fact, feedback."},
                    "tags": {"type": "string", "description": "Comma-separated tags."},
                },
                ["text"],
            ),
            handler=_remember,
        )
    )
    registry.register(
        Tool(
            name="retrieve_memory",
            description="Search persistent memory by keyword.",
            parameters=_object_schema(
                {
                    "query": {"type": "string", "description": "Search query."},
                    "limit": {"type": "integer", "description": "Maximum number of memories to return."},
                },
                ["query"],
            ),
            handler=_retrieve_memory,
        )
    )
    registry.register(
        Tool(
            name="list_files",
            description=(
                "List files under the workspace or configured local read paths such as Desktop. "
                "Use path 'desktop' for the current user's Windows Desktop, including OneDrive-redirection. "
                f"Configured read roots: {read_roots_hint}"
            ),
            parameters=_object_schema(
                {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative folder path, or an absolute path under an allowed read root.",
                    },
                    "pattern": {"type": "string", "description": "Glob pattern, such as *.py."},
                    "recursive": {"type": "boolean", "description": "Whether to recurse."},
                    "max_items": {"type": "integer", "description": "Maximum items to return."},
                },
                [],
            ),
            handler=_list_files,
        )
    )
    registry.register(
        Tool(
            name="read_text_file",
            description=(
                "Read a UTF-8 text file under the workspace or a configured local read path. "
                "Use path 'desktop' with list_files before reading Desktop files."
            ),
            parameters=_object_schema(
                {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path, or an absolute path under an allowed read root.",
                    },
                    "max_chars": {"type": "integer", "description": "Maximum characters to return."},
                },
                ["path"],
            ),
            handler=_read_text_file,
        )
    )
    registry.register(
        Tool(
            name="write_text_file",
            description=(
                "Write a UTF-8 text file under the workspace or a configured local write path. "
                "Use path 'desktop/filename.txt' to write to the current user's Windows Desktop. "
                f"Configured write roots: {write_roots_hint}"
            ),
            parameters=_object_schema(
                {
                    "path": {
                        "type": "string",
                        "description": "Workspace-relative file path, or a path under an allowed write root.",
                    },
                    "content": {"type": "string", "description": "File content."},
                    "overwrite": {"type": "boolean", "description": "Allow overwriting an existing file."},
                },
                ["path", "content"],
            ),
            handler=_write_text_file,
        )
    )
    registry.register(
        Tool(
            name="open_windows_app",
            description="Open a small allowlisted Windows app for UI-observation research.",
            parameters=_object_schema(
                {
                    "app": {
                        "type": "string",
                        "description": "One of: notepad, calculator.",
                    }
                },
                ["app"],
            ),
            handler=_open_windows_app,
        )
    )
    registry.register(
        Tool(
            name="run_original_hermes",
            description=(
                "Delegate a complex web, browser, memory, or planning task to the vendored original Hermes. "
                "Use this when Mini Hermes needs upstream Hermes capabilities, especially browser automation. "
                "Do not request passwords, payment actions, terminal, file, code_execution, delegation, all, or * toolsets."
            ),
            parameters=_object_schema(
                {
                    "prompt": {
                        "type": "string",
                        "description": "The complete instruction to send to original Hermes.",
                    },
                    "toolsets": {
                        "type": "string",
                        "description": "Comma-separated safe upstream toolsets. Suggested: browser,web,memory,todo.",
                    },
                    "timeout_seconds": {
                        "type": "integer",
                        "description": "Execution timeout in seconds, usually 120 to 300.",
                    },
                },
                ["prompt"],
            ),
            handler=_run_original_hermes,
        )
    )
    return registry


def capture_screen_observation(
    store: MiniHermesStore,
    run_id: str,
    note: str,
    action_label: str,
    step_id: int | None = None,
) -> str:
    screenshot_dir = store.root / "screenshots" / run_id
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, Any] = {}
    image_path = ""

    if ImageGrab is None:
        metadata["error"] = "PIL.ImageGrab is unavailable"
    else:
        try:
            image = ImageGrab.grab()
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            output = screenshot_dir / filename
            image.save(output)
            image_path = str(output.resolve())
            metadata["size"] = list(image.size)
        except Exception as exc:
            metadata["error"] = f"{type(exc).__name__}: {exc}"

    return store.add_observation(
        run_id=run_id,
        kind="screenshot",
        note=note,
        action_label=action_label,
        image_path=image_path,
        metadata=metadata,
        step_id=step_id,
    )


def _calculate(_: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    expression = str(arguments.get("expression", ""))
    return {"value": _safe_eval(expression)}


def _safe_eval(expression: str) -> float:
    allowed_binary_ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    allowed_unary_ops = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary_ops:
            return allowed_binary_ops[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary_ops:
            return allowed_unary_ops[type(node.op)](eval_node(node.operand))
        raise ValueError(f"unsupported syntax: {ast.dump(node, include_attributes=False)}")

    parsed = ast.parse(expression, mode="eval")
    return eval_node(parsed)


def _capture_screen_tool(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    observation_id = capture_screen_observation(
        context.store,
        context.run_id,
        note=str(arguments.get("note", "")),
        action_label=str(arguments.get("action_label", "manual_capture")),
    )
    return {"observation_id": observation_id}


def _remember(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    memory_id = context.store.add_memory(
        text=str(arguments.get("text", "")),
        kind=str(arguments.get("kind", "note")),
        tags=str(arguments.get("tags", "")),
        source_run_id=context.run_id,
    )
    return {"memory_id": memory_id}


def _retrieve_memory(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    limit = int(arguments.get("limit", 5) or 5)
    return {"items": context.store.search_memories(str(arguments.get("query", "")), limit=limit)}


def _list_files(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    root = _safe_read_path(context.workspace, str(arguments.get("path", ".")))
    if not root.exists() or not root.is_dir():
        return {"ok": False, "error": f"folder does not exist: {root}"}

    pattern = str(arguments.get("pattern", "*") or "*")
    recursive = bool(arguments.get("recursive", False))
    max_items = min(int(arguments.get("max_items", 50) or 50), 200)
    iterator = root.rglob(pattern) if recursive else root.glob(pattern)
    items = []
    for path in iterator:
        resolved = path.resolve()
        items.append(
            {
                "path": _display_path(context.workspace, resolved),
                "is_dir": resolved.is_dir(),
                "size": _file_size(resolved),
            }
        )
        if len(items) >= max_items:
            break
    return {"items": items}


def _read_text_file(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = _safe_read_path(context.workspace, str(arguments.get("path", "")))
    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"file does not exist: {path}"}
    max_chars = min(int(arguments.get("max_chars", 8000) or 8000), 50_000)
    return {"path": str(path), "content": path.read_text(encoding="utf-8", errors="replace")[:max_chars]}


def _write_text_file(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    path = _safe_write_path(context.workspace, str(arguments.get("path", "")))
    overwrite = bool(arguments.get("overwrite", False))
    if path.exists() and not overwrite:
        return {"ok": False, "error": f"file already exists: {path}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(arguments.get("content", ""))
    path.write_text(content, encoding="utf-8")
    return {"path": str(path), "chars": len(content)}


def _open_windows_app(_: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "notepad": "notepad.exe",
        "calculator": "calc.exe",
    }
    app = str(arguments.get("app", "")).lower().strip()
    executable = allowed.get(app)
    if not executable:
        return {"ok": False, "error": f"unsupported app: {app}. allowed={sorted(allowed)}"}
    subprocess.Popen([executable])
    return {"app": app, "started": True}


def _run_original_hermes(context: ToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    prompt = str(arguments.get("prompt", "")).strip()
    if not prompt:
        return {"ok": False, "error": "prompt is required"}
    toolsets = str(arguments.get("toolsets", "browser,web,memory,todo") or "browser,web,memory,todo")
    timeout_seconds = min(max(int(arguments.get("timeout_seconds", 240) or 240), 30), 600)
    runtime = UpstreamHermesRuntime()
    result = runtime.run_oneshot(
        prompt=prompt,
        toolsets=toolsets,
        timeout_seconds=timeout_seconds,
        ignore_rules=True,
        allow_dangerous_toolsets=False,
    )
    upstream_run_id = context.store.record_upstream_run(
        prompt=result.prompt,
        provider=result.provider,
        model=result.model,
        toolsets=result.toolsets,
        command_display=result.command_display,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        elapsed_seconds=result.elapsed_seconds,
        status=result.status,
    )
    return {
        "ok": result.ok,
        "upstream_run_id": upstream_run_id,
        "status": result.status,
        "returncode": result.returncode,
        "stdout": result.stdout[:8000],
        "stderr": result.stderr[:3000],
        "elapsed_seconds": round(result.elapsed_seconds, 3),
    }


def _safe_workspace_path(workspace: Path, user_path: str) -> Path:
    workspace = workspace.resolve()
    raw = _expand_path(user_path)
    path = raw if raw.is_absolute() else workspace / raw
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {user_path}") from exc
    return resolved


def _safe_read_path(workspace: Path, user_path: str) -> Path:
    try:
        return _safe_workspace_path(workspace, user_path)
    except ValueError:
        pass

    raw = _expand_path(user_path)
    if not raw.is_absolute():
        raise ValueError(f"path escapes workspace: {user_path}")
    resolved = raw.resolve()
    for root in _allowed_read_roots(workspace):
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"path escapes workspace and configured read roots: {user_path}")


def _safe_write_path(workspace: Path, user_path: str) -> Path:
    try:
        return _safe_workspace_path(workspace, user_path)
    except ValueError:
        pass

    raw = _expand_path(user_path)
    if not raw.is_absolute():
        raise ValueError(f"path escapes workspace: {user_path}")
    resolved = raw.resolve()
    for root in _allowed_write_roots(workspace):
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue
    raise ValueError(f"path escapes workspace and configured write roots: {user_path}")


def _allowed_read_roots(workspace: Path) -> tuple[Path, ...]:
    roots = [workspace.resolve()]
    for path in _configured_read_paths():
        roots.append(_expand_path(path).resolve())
    return tuple(dict.fromkeys(roots))


def _allowed_write_roots(workspace: Path) -> tuple[Path, ...]:
    roots = [workspace.resolve()]
    for path in _configured_write_paths():
        roots.append(_expand_path(path).resolve())
    return tuple(dict.fromkeys(roots))


def _configured_read_paths() -> list[str]:
    return _configured_paths("LOCAL_READ_ALLOWED_PATHS", "MINI_HERMES_READ_ALLOWED_PATHS")


def _configured_write_paths() -> list[str]:
    return _configured_paths("LOCAL_WRITE_ALLOWED_PATHS", "MINI_HERMES_WRITE_ALLOWED_PATHS")


def _configured_paths(config_name: str, env_name: str) -> list[str]:
    raw_paths: list[str] = []
    if config and hasattr(config, config_name):
        configured = getattr(config, config_name)
        if isinstance(configured, str):
            raw_paths.extend(part.strip() for part in configured.split(";") if part.strip())
        elif isinstance(configured, (list, tuple, set)):
            raw_paths.extend(str(part).strip() for part in configured if str(part).strip())

    env_value = os.getenv(env_name, "")
    if env_value:
        raw_paths.extend(part.strip() for part in env_value.split(";") if part.strip())
    return raw_paths


def _expand_path(path: str) -> Path:
    raw = str(path).strip()
    normalized = raw.replace("\\", "/").strip("/")
    parts = [part for part in normalized.split("/") if part]
    desktop_aliases = {"desktop", "user_desktop", "user desktop", "바탕화면"}
    if parts and parts[0].lower() in desktop_aliases:
        desktop = _preferred_user_desktop_path()
        if desktop:
            return desktop.joinpath(*parts[1:])

    expanded = Path(os.path.expandvars(raw)).expanduser()
    profile_desktop = Path.home() / "Desktop"
    if not profile_desktop.exists():
        try:
            desktop_rel = expanded.resolve().relative_to(profile_desktop.resolve())
        except ValueError:
            desktop_rel = None
        if desktop_rel is not None:
            desktop = _preferred_user_desktop_path()
            if desktop:
                return desktop / desktop_rel
    return expanded


def _preferred_user_desktop_path() -> Path | None:
    candidates = [
        _expand_raw_path("%USERPROFILE%\\OneDrive\\Desktop"),
        _expand_raw_path("%USERPROFILE%\\Desktop"),
        *_configured_desktop_paths(public=False),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _configured_desktop_paths(public: bool) -> list[Path]:
    paths = []
    for raw in [*_configured_read_paths(), *_configured_write_paths()]:
        candidate = _expand_raw_path(raw)
        text = str(candidate).lower()
        is_public = "\\public\\" in text or "/public/" in text
        if candidate.name.lower() == "desktop" and is_public == public:
            paths.append(candidate)
    return paths


def _expand_raw_path(path: str) -> Path:
    return Path(os.path.expandvars(str(path))).expanduser()


def _read_roots_hint() -> str:
    paths = [_expand_raw_path(path) for path in _configured_read_paths()]
    if not paths:
        return "workspace only"
    return ", ".join(str(path) for path in paths)


def _write_roots_hint() -> str:
    paths = [_expand_raw_path(path) for path in _configured_write_paths()]
    if not paths:
        return "workspace only"
    return ", ".join(str(path) for path in paths)


def _display_path(workspace: Path, path: Path) -> str:
    workspace = workspace.resolve()
    try:
        return str(path.resolve().relative_to(workspace))
    except ValueError:
        return str(path.resolve())


def _file_size(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
