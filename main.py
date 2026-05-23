import argparse
import asyncio
import ast
import copy
import operator
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    function_tool,
    set_default_openai_key,
    set_tracing_disabled,
)
from agents.extensions.handoff_prompt import prompt_with_handoff_instructions
from openai import AsyncOpenAI

from agent_tools import (
    draw_in_paint as draw_in_paint_impl,
    organize_pictures_by_year as organize_pictures_by_year_impl,
    undo_photo_organization as undo_photo_organization_impl,
)
from trace_store import TraceStore

try:
    import config
except ModuleNotFoundError:
    config = None


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DEFAULT_PROVIDERS = {
    "deepseek": {
        "backend": "openai_compatible",
        "api_key": "",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model": "deepseek-chat",
        "model_env": "AGENT_MODEL",
    },
    "openai": {
        "backend": "openai",
        "api_key": "",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-5.5",
        "model_env": "AGENT_MODEL",
    },
}


def load_settings() -> dict:
    providers = copy.deepcopy(DEFAULT_PROVIDERS)
    if config and hasattr(config, "PROVIDERS"):
        providers.update(copy.deepcopy(config.PROVIDERS))

    default_provider = getattr(config, "DEFAULT_PROVIDER", "deepseek") if config else "deepseek"
    provider_name = os.getenv("AGENT_PROVIDER", default_provider).lower()
    if provider_name not in providers:
        available = ", ".join(sorted(providers))
        raise SystemExit(f"Unknown AGENT_PROVIDER '{provider_name}'. Available providers: {available}")

    provider = providers[provider_name]
    api_key = os.getenv(provider.get("api_key_env", ""), provider.get("api_key", ""))
    model = os.getenv(provider.get("model_env", ""), provider.get("model", ""))
    base_url = os.getenv(provider.get("base_url_env", ""), provider.get("base_url", ""))

    return {
        "provider_name": provider_name,
        "backend": provider.get("backend", "openai"),
        "api_key": api_key,
        "api_key_env": provider.get("api_key_env", ""),
        "model": model,
        "base_url": base_url,
    }


SETTINGS = load_settings()
if SETTINGS["provider_name"] == "openai" and SETTINGS["api_key"]:
    set_default_openai_key(SETTINGS["api_key"])

if (
    getattr(config, "DISABLE_TRACING_WITHOUT_OPENAI_KEY", True)
    and SETTINGS["provider_name"] != "openai"
    and not os.getenv("OPENAI_API_KEY")
):
    set_tracing_disabled(True)


def build_model() -> str | OpenAIChatCompletionsModel:
    backend = SETTINGS["backend"]
    api_key = SETTINGS["api_key"]
    model = SETTINGS["model"]

    if backend == "openai":
        return model

    if backend == "openai_compatible":
        client = AsyncOpenAI(api_key=api_key, base_url=SETTINGS["base_url"])
        return OpenAIChatCompletionsModel(model=model, openai_client=client)

    if backend == "litellm":
        try:
            from agents.extensions.models.litellm_model import LitellmModel
        except ImportError as exc:
            raise SystemExit(
                "This provider uses LiteLLM. Install it with: "
                "python -m pip install 'openai-agents[litellm]'"
            ) from exc

        return LitellmModel(model=model, base_url=SETTINGS["base_url"] or None, api_key=api_key)

    raise SystemExit(f"Unsupported provider backend: {backend}")


AGENT_MODEL = build_model()
TRACE_STORE = TraceStore()


@function_tool
def get_current_time(timezone: str = "Asia/Seoul") -> str:
    """Return the current local time for an IANA timezone such as Asia/Seoul."""
    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        return f"Unknown timezone: {timezone}"

    return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


@function_tool
def calculate(expression: str) -> str:
    """Evaluate a basic arithmetic expression using +, -, *, /, //, %, **, and parentheses."""
    try:
        value = _safe_eval(expression)
    except Exception as exc:
        return f"Could not calculate expression: {exc}"

    return str(value)


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
    allowed_unary_ops = {
        ast.UAdd: operator.pos,
        ast.USub: operator.neg,
    }

    def eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed_binary_ops:
            return allowed_binary_ops[type(node.op)](eval_node(node.left), eval_node(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in allowed_unary_ops:
            return allowed_unary_ops[type(node.op)](eval_node(node.operand))
        raise ValueError(f"unsupported syntax: {ast.dump(node, include_attributes=False)}")

    parsed = ast.parse(expression, mode="eval")
    return eval_node(parsed)


organize_pictures_by_year = function_tool(organize_pictures_by_year_impl)
undo_photo_organization = function_tool(undo_photo_organization_impl)
draw_in_paint = function_tool(draw_in_paint_impl)

CORE_TOOLS = [
    calculate,
    get_current_time,
    organize_pictures_by_year,
    undo_photo_organization,
    draw_in_paint,
]


coding_agent = Agent(
    name="Coding_Agent",
    handoff_description="Handles Python implementation, debugging, refactoring, and code explanation.",
    instructions=(
        "You are a careful Python coding assistant. Give concrete implementation steps, "
        "point out assumptions, and prefer simple, maintainable code."
    ),
    model=AGENT_MODEL,
    tools=[calculate, get_current_time],
)

planning_agent = Agent(
    name="Planning_Agent",
    handoff_description="Breaks ambiguous goals into practical execution plans.",
    instructions=(
        "You turn broad requests into concise plans with clear order of operations, "
        "risks, and next actions. Keep the plan practical."
    ),
    model=AGENT_MODEL,
    tools=[get_current_time],
)

general_agent = Agent(
    name="General Assistant",
    instructions=prompt_with_handoff_instructions(
        "You are a Korean-speaking assistant. Answer in Korean unless the user asks otherwise. "
        "Use tools when they improve accuracy. Hand off coding work to Coding_Agent and "
        "planning-heavy work to Planning_Agent. If no handoff is needed, answer directly. "
        "If the user asks to organize images or photos by year, call organize_pictures_by_year. "
        "If the user asks to draw something in Microsoft Paint, call draw_in_paint with a concise description "
        "and leave open_paint true unless the user explicitly asks for file generation only. "
        "After file organization, mention the manifest path so the operation can be reviewed or undone."
    ),
    model=AGENT_MODEL,
    handoffs=[coding_agent, planning_agent],
    tools=CORE_TOOLS,
)


async def run_once(prompt: str) -> None:
    _ensure_api_key()
    run_id = TRACE_STORE.start_run(SETTINGS["provider_name"], SETTINGS["model"], prompt)
    try:
        result = await Runner.run(general_agent, prompt)
    except Exception as exc:
        TRACE_STORE.finish_run(run_id, status="error", error=str(exc))
        raise

    TRACE_STORE.finish_run(
        run_id,
        final_output=result.final_output,
        last_agent=result.last_agent.name,
    )
    print(result.final_output)
    print(f"\n[answered_by={result.last_agent.name}]")
    print(f"[run_id={run_id}]")


async def chat() -> None:
    _ensure_api_key()
    print("Python Agent CLI")
    print("Type 'exit' or 'quit' to finish.\n")

    history = []
    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if user_input.lower() in {"exit", "quit"}:
            return
        if not user_input:
            continue

        run_id = TRACE_STORE.start_run(SETTINGS["provider_name"], SETTINGS["model"], user_input)
        try:
            result = await Runner.run(general_agent, history + [{"role": "user", "content": user_input}])
        except Exception as exc:
            TRACE_STORE.finish_run(run_id, status="error", error=str(exc))
            print(f"agent(error)> {exc}\n")
            continue

        history = result.to_input_list()
        TRACE_STORE.finish_run(
            run_id,
            final_output=result.final_output,
            last_agent=result.last_agent.name,
        )
        print(f"agent({result.last_agent.name})> {result.final_output}\n[run_id={run_id}]\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Python agent built with the OpenAI Agents SDK.")
    parser.add_argument("prompt", nargs="*", help="Prompt to run once. Omit it to start interactive chat.")
    return parser.parse_args()


def _ensure_api_key() -> None:
    if not SETTINGS["api_key"]:
        raise SystemExit(
            f"API key is not set for provider '{SETTINGS['provider_name']}'. "
            f"Set it in config.py or with ${SETTINGS['api_key_env']}."
        )


async def main() -> None:
    args = parse_args()
    if args.prompt:
        await run_once(" ".join(args.prompt))
    else:
        await chat()


if __name__ == "__main__":
    asyncio.run(main())
