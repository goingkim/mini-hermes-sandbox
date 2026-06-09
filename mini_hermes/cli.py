from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from mini_hermes.agent import MiniHermesAgent
from dataset.primitives import UIPrimitiveBuilder
from dataset.recorder import EpisodeRecorder
from dataset.replay import EpisodeReplayer
from dataset.scoring import RuleBasedEpisodeScorer
from dataset.storage import EpisodeStore
from mini_hermes.privacy import clean_text
from mini_hermes.scheduler import MiniHermesScheduler
from mini_hermes.settings import load_telegram_settings
from mini_hermes.store import MiniHermesStore
from mini_hermes.telegram_bot import TelegramHermesBridge
from mini_hermes.upstream import HermesUpstream
from mini_hermes.upstream_runtime import UpstreamHermesRuntime


KNOWN_COMMANDS = {
    "run",
    "chat",
    "rate",
    "memories",
    "export",
    "schedule-add",
    "schedule-list",
    "schedule-run-due",
    "doctor",
    "telegram-bot",
    "telegram-doctor",
    "upstream-status",
    "upstream-import-check",
    "hermes-run",
    "episode-record",
    "episode-list",
    "episode-score",
    "episode-build-primitives",
    "episode-export-primitives",
    "episode-feedback",
    "episode-replay",
    "episode-export",
}


def main(argv: list[str] | None = None) -> None:
    _configure_console_encoding()
    parser = build_parser()
    argv = list(argv) if argv is not None else None
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["chat"]
    if argv and argv[0] not in KNOWN_COMMANDS and not argv[0].startswith("-"):
        argv = ["run", *argv]
    args = parser.parse_args(argv)

    if args.command == "run":
        asyncio.run(_run(args))
    elif args.command == "chat":
        asyncio.run(_chat(args))
    elif args.command == "rate":
        _rate(args)
    elif args.command == "memories":
        _memories(args)
    elif args.command == "export":
        _export(args)
    elif args.command == "schedule-add":
        _schedule_add(args)
    elif args.command == "schedule-list":
        _schedule_list(args)
    elif args.command == "schedule-run-due":
        asyncio.run(_schedule_run_due(args))
    elif args.command == "doctor":
        _doctor(args)
    elif args.command == "telegram-bot":
        asyncio.run(_telegram_bot(args))
    elif args.command == "telegram-doctor":
        _telegram_doctor(args)
    elif args.command == "upstream-status":
        _upstream_status(args)
    elif args.command == "upstream-import-check":
        _upstream_import_check(args)
    elif args.command == "hermes-run":
        _hermes_run(args)
    elif args.command == "episode-record":
        _episode_record(args)
    elif args.command == "episode-list":
        _episode_list(args)
    elif args.command == "episode-score":
        _episode_score(args)
    elif args.command == "episode-build-primitives":
        _episode_build_primitives(args)
    elif args.command == "episode-export-primitives":
        _episode_export_primitives(args)
    elif args.command == "episode-feedback":
        _episode_feedback(args)
    elif args.command == "episode-replay":
        _episode_replay(args)
    elif args.command == "episode-export":
        _episode_export(args)
    else:
        parser.print_help()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mini Hermes research agent.")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run one task.")
    run.add_argument("prompt", nargs="+")
    run.add_argument("--workspace", default=".")
    run.add_argument("--no-observe", action="store_true", help="Disable automatic screenshots.")
    run.add_argument("--no-learn", action="store_true", help="Do not create memories from this run.")
    run.add_argument("--max-steps", type=int, default=8)

    chat = sub.add_parser("chat", help="Start a simple interactive loop.")
    chat.add_argument("--workspace", default=".")
    chat.add_argument("--no-observe", action="store_true")
    chat.add_argument("--max-steps", type=int, default=8)

    rate = sub.add_parser("rate", help="Attach a user reward score to a run.")
    rate.add_argument("run_id")
    rate.add_argument("score", type=float)
    rate.add_argument("reason", nargs="*", default=[])

    memories = sub.add_parser("memories", help="Search memories.")
    memories.add_argument("query", nargs="*", default=[])
    memories.add_argument("--limit", type=int, default=10)

    export = sub.add_parser("export", help="Export Mini Hermes tool trajectory JSONL.")
    export.add_argument("--output", default="agent_runs/mini_hermes/trajectory_export.jsonl")

    schedule_add = sub.add_parser("schedule-add", help="Add an interval schedule.")
    schedule_add.add_argument("name")
    schedule_add.add_argument("task", nargs="+")
    schedule_add.add_argument("--every-minutes", type=float, default=60.0)

    sub.add_parser("schedule-list", help="List schedules.")

    due = sub.add_parser("schedule-run-due", help="Run due schedules once.")
    due.add_argument("--no-observe", action="store_true")

    sub.add_parser("doctor", help="Show local Mini Hermes configuration.")

    telegram_bot = sub.add_parser("telegram-bot", help="Run Mini Hermes as a Telegram polling bot.")
    telegram_bot.add_argument("--workspace", default="", help="Workspace for Telegram-triggered tasks.")
    telegram_bot.add_argument("--no-observe", action="store_true", help="Disable automatic screenshots.")
    telegram_bot.add_argument("--max-steps", type=int, default=0)
    telegram_bot.add_argument("--poll-timeout", type=int, default=0)
    telegram_bot.add_argument("--allow-any-chat", action="store_true", help="Process messages from any chat.")
    telegram_bot.add_argument(
        "--drop-pending-updates",
        action="store_true",
        help="Discard Telegram updates queued before the bridge starts.",
    )

    sub.add_parser("telegram-doctor", help="Show Telegram bridge configuration without revealing the token.")

    sub.add_parser("upstream-status", help="Show vendored Hermes source status.")

    upstream_check = sub.add_parser("upstream-import-check", help="Import selected upstream modules.")
    upstream_check.add_argument("modules", nargs="*", help="Module names to import, e.g. agent.trajectory")

    hermes_run = sub.add_parser("hermes-run", help="Run vendored original Hermes through the Mini Hermes wrapper.")
    hermes_run.add_argument("prompt", nargs="+")
    hermes_run.add_argument("--toolsets", default="memory,todo,web")
    hermes_run.add_argument("--timeout", type=int, default=300)
    hermes_run.add_argument("--keep-rules", action="store_true", help="Allow upstream context/rules/memory injection.")
    hermes_run.add_argument(
        "--allow-dangerous-toolsets",
        action="store_true",
        help="Allow upstream toolsets such as terminal, file, code_execution, all, or *.",
    )

    record = sub.add_parser("episode-record", help="Record a Windows screen/input episode.")
    record.add_argument("task", nargs="+")
    record.add_argument("--duration", type=float, default=10.0)
    record.add_argument("--fps", type=float, default=1.0)
    record.add_argument("--no-input", action="store_true", help="Record screen frames only.")
    record.add_argument(
        "--record-key-text",
        action="store_true",
        help="Store simple printable key text. Off by default for privacy.",
    )
    record.add_argument("--plan-step", action="append", default=[], help="Optional agent plan step metadata.")
    record.add_argument("--skill", default="", help="Optional high-level skill name, e.g. send-email.")
    record.add_argument(
        "--expected-primitive",
        action="append",
        default=[],
        help="Optional expected UI primitive label. Repeat for sequences.",
    )
    record.add_argument("--root", default="agent_runs/mini_hermes/episodes")

    episode_list = sub.add_parser("episode-list", help="List recorded dataset episodes.")
    episode_list.add_argument("--limit", type=int, default=10)
    episode_list.add_argument("--root", default="agent_runs/mini_hermes/episodes")

    episode_score = sub.add_parser("episode-score", help="Score a recorded episode with rule-based heuristics.")
    episode_score.add_argument("episode_id")
    episode_score.add_argument("--root", default="agent_runs/mini_hermes/episodes")

    primitive_build = sub.add_parser(
        "episode-build-primitives",
        help="Build UI primitive labels from a recorded episode.",
    )
    primitive_build.add_argument("episode_id")
    primitive_build.add_argument("--root", default="agent_runs/mini_hermes/episodes")
    primitive_build.add_argument(
        "--no-verify-state",
        action="store_true",
        help="Do not add a final verify_state primitive linked to the last frame.",
    )

    primitive_export = sub.add_parser(
        "episode-export-primitives",
        help="Export UI primitive training samples as JSONL.",
    )
    primitive_export.add_argument("episode_id")
    primitive_export.add_argument("--output", required=True)
    primitive_export.add_argument("--root", default="agent_runs/mini_hermes/episodes")
    primitive_export.add_argument(
        "--no-build",
        action="store_true",
        help="Do not auto-build primitive labels when missing.",
    )

    feedback = sub.add_parser("episode-feedback", help="Attach human feedback to a recorded episode.")
    feedback.add_argument("episode_id")
    feedback.add_argument("score", type=float)
    feedback.add_argument("text", nargs="*", default=[])
    feedback.add_argument("--root", default="agent_runs/mini_hermes/episodes")

    replay = sub.add_parser("episode-replay", help="Replay or inspect recorded input events.")
    replay.add_argument("episode_id")
    replay.add_argument("--execute", action="store_true", help="Actually send mouse/keyboard events. Default is dry-run.")
    replay.add_argument("--speed", type=float, default=1.0)
    replay.add_argument("--start-delay", type=float, default=2.0)
    replay.add_argument("--root", default="agent_runs/mini_hermes/episodes")

    episode_export = sub.add_parser("episode-export", help="Copy one episode JSONL to a chosen path.")
    episode_export.add_argument("episode_id")
    episode_export.add_argument("--output", required=True)
    episode_export.add_argument("--root", default="agent_runs/mini_hermes/episodes")
    return parser


async def _run(args: argparse.Namespace) -> None:
    agent = MiniHermesAgent(
        workspace=args.workspace,
        auto_observe=not args.no_observe,
        max_steps=args.max_steps,
    )
    result = await agent.run(" ".join(args.prompt), learn=not args.no_learn)
    print(result.final_answer)
    print(f"\n[run_id={result.run_id}]")
    print(f"[status={result.status} score={result.score:.3f}]")
    print(f"[score_reason={result.score_reason}]")


async def _chat(args: argparse.Namespace) -> None:
    agent = MiniHermesAgent(
        workspace=args.workspace,
        auto_observe=not args.no_observe,
        max_steps=args.max_steps,
    )
    print("Mini Hermes CLI. Type exit or quit to finish.")
    while True:
        try:
            prompt = clean_text(input("you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if prompt.lower() in {"exit", "quit"}:
            return
        if not prompt:
            continue
        result = await agent.run(prompt, learn=True)
        print(f"agent> {result.final_answer}")
        print(f"[run_id={result.run_id} score={result.score:.3f}]\n")


def _rate(args: argparse.Namespace) -> None:
    store = MiniHermesStore()
    reason = " ".join(args.reason) if args.reason else "no reason provided"
    store.rate_run(args.run_id, args.score, reason)
    print(f"rated {args.run_id} as {max(0.0, min(1.0, args.score)):.3f}")


def _memories(args: argparse.Namespace) -> None:
    store = MiniHermesStore()
    query = " ".join(args.query)
    for item in store.search_memories(query, limit=args.limit):
        print(f"- {item['kind']} score={item.get('score')}: {item['text']}")


def _export(args: argparse.Namespace) -> None:
    store = MiniHermesStore()
    path = store.export_trajectories_jsonl(args.output)
    print(f"exported {Path(path).resolve()}")


def _schedule_add(args: argparse.Namespace) -> None:
    scheduler = MiniHermesScheduler()
    schedule_id = scheduler.add_interval_job(
        name=args.name,
        task=" ".join(args.task),
        every_minutes=args.every_minutes,
    )
    print(f"schedule_id={schedule_id}")


def _schedule_list(args: argparse.Namespace) -> None:
    store = MiniHermesStore()
    for item in store.list_schedules():
        print(
            f"- {item['name']} enabled={bool(item['enabled'])} "
            f"next={item['next_run_at']} task={item['task']}"
        )


async def _schedule_run_due(args: argparse.Namespace) -> None:
    store = MiniHermesStore()
    agent = MiniHermesAgent(store=store, auto_observe=not args.no_observe)
    scheduler = MiniHermesScheduler(store=store)
    results = await scheduler.run_due(agent=agent)
    print(f"ran {len(results)} due schedule(s)")
    for item in results:
        print(f"- {item.name}: run_id={item.result.run_id} score={item.result.score:.3f}")


def _doctor(args: argparse.Namespace) -> None:
    from mini_hermes.settings import load_settings

    settings = load_settings()
    store = MiniHermesStore()
    episode_store = EpisodeStore()
    print(f"provider={settings.provider_name}")
    print(f"backend={settings.backend}")
    print(f"model={settings.model}")
    print(f"api_key_set={bool(settings.api_key)}")
    print(f"db={store.db_path.resolve()}")
    print(f"episodes_db={episode_store.db_path.resolve()}")


async def _telegram_bot(args: argparse.Namespace) -> None:
    telegram_settings = load_telegram_settings()
    if not telegram_settings.bot_token:
        raise SystemExit(
            f"Telegram bot token is not set. Set it in config.py or with ${telegram_settings.bot_token_env}."
        )
    workspace = args.workspace or telegram_settings.workspace
    max_steps = args.max_steps if args.max_steps > 0 else telegram_settings.max_steps
    if args.poll_timeout > 0:
        telegram_settings = type(telegram_settings)(
            bot_token=telegram_settings.bot_token,
            bot_token_env=telegram_settings.bot_token_env,
            allowed_chat_ids=telegram_settings.allowed_chat_ids,
            polling_timeout=args.poll_timeout,
            request_timeout=telegram_settings.request_timeout,
            workspace=telegram_settings.workspace,
            auto_observe=telegram_settings.auto_observe,
            max_steps=telegram_settings.max_steps,
        )
    store = MiniHermesStore()
    agent = MiniHermesAgent(
        store=store,
        workspace=workspace,
        auto_observe=telegram_settings.auto_observe and not args.no_observe,
        max_steps=max_steps,
    )
    bridge = TelegramHermesBridge(
        settings=telegram_settings,
        agent=agent,
        store=store,
        allow_any_chat=args.allow_any_chat,
    )
    await bridge.run_forever(drop_pending_updates=args.drop_pending_updates)


def _telegram_doctor(args: argparse.Namespace) -> None:
    settings = load_telegram_settings()
    print(f"telegram_token_set={bool(settings.bot_token)}")
    print(f"telegram_token_env={settings.bot_token_env}")
    print(f"allowed_chat_count={len(settings.allowed_chat_ids)}")
    print(f"polling_timeout={settings.polling_timeout}")
    print(f"request_timeout={settings.request_timeout}")
    print(f"workspace={settings.workspace}")
    print(f"auto_observe={settings.auto_observe}")
    print(f"max_steps={settings.max_steps}")


def _upstream_status(args: argparse.Namespace) -> None:
    upstream = HermesUpstream()
    status = upstream.status()
    print(f"available={status.available}")
    print(f"root={status.root}")
    print(f"commit={status.commit}")
    print(f"source={status.source}")
    for name, count in status.core_dirs.items():
        print(f"{name}={count} python files")


def _upstream_import_check(args: argparse.Namespace) -> None:
    upstream = HermesUpstream()
    modules = tuple(args.modules) if args.modules else None
    checks = upstream.import_checks(modules) if modules else upstream.import_checks()
    failed = False
    for check in checks:
        state = "ok" if check.ok else "error"
        print(f"{state} {check.module} {check.path}")
        if check.error:
            failed = True
            print(f"  {check.error}")
    if failed:
        raise SystemExit(1)


def _hermes_run(args: argparse.Namespace) -> None:
    runtime = UpstreamHermesRuntime()
    prompt = " ".join(args.prompt)
    result = runtime.run_oneshot(
        prompt=prompt,
        toolsets=args.toolsets,
        timeout_seconds=args.timeout,
        ignore_rules=not args.keep_rules,
        allow_dangerous_toolsets=args.allow_dangerous_toolsets,
    )
    store = MiniHermesStore()
    upstream_run_id = store.record_upstream_run(
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
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)
    print(
        f"\n[upstream_run_id={upstream_run_id}] "
        f"[status={result.status} returncode={result.returncode} elapsed={result.elapsed_seconds:.2f}s]"
    )


def _episode_record(args: argparse.Namespace) -> None:
    store = EpisodeStore(args.root)
    recorder = EpisodeRecorder(store)
    result = recorder.record(
        task=" ".join(args.task),
        duration_seconds=args.duration,
        fps=args.fps,
        capture_input=not args.no_input,
        record_key_text=args.record_key_text,
        agent_plan=args.plan_step,
        skill_name=args.skill,
        expected_ui_primitives=args.expected_primitive,
    )
    print(f"episode_id={result.episode_id}")
    print(f"status={result.status}")
    print(f"duration={result.duration_seconds:.2f}s frames={result.frame_count} inputs={result.input_event_count}")
    print(f"jsonl={result.jsonl_path}")


def _episode_list(args: argparse.Namespace) -> None:
    store = EpisodeStore(args.root)
    for episode in store.list_episodes(limit=args.limit):
        print(
            f"- {episode['episode_id']} status={episode['status']} "
            f"started={episode['started_at']} task={episode['task']}"
        )


def _episode_score(args: argparse.Namespace) -> None:
    scorer = RuleBasedEpisodeScorer(EpisodeStore(args.root))
    result = scorer.score(args.episode_id, persist=True)
    print(f"episode_id={result.episode_id}")
    print(f"score={result.score:.3f}")
    print(f"reason={result.reason}")
    print(f"metrics={result.metrics}")


def _episode_build_primitives(args: argparse.Namespace) -> None:
    builder = UIPrimitiveBuilder(EpisodeStore(args.root))
    result = builder.build(
        args.episode_id,
        persist=True,
        include_verify_state=not args.no_verify_state,
    )
    print(f"episode_id={result.episode_id}")
    print(f"primitive_count={result.primitive_count}")
    print(f"counts={result.counts}")


def _episode_export_primitives(args: argparse.Namespace) -> None:
    builder = UIPrimitiveBuilder(EpisodeStore(args.root))
    result = builder.export_training_jsonl(
        args.episode_id,
        output_path=args.output,
        build_if_missing=not args.no_build,
    )
    print(f"episode_id={result.episode_id}")
    print(f"sample_count={result.sample_count}")
    print(f"jsonl={result.output_path}")


def _episode_feedback(args: argparse.Namespace) -> None:
    store = EpisodeStore(args.root)
    text = " ".join(args.text) if args.text else "no feedback text"
    feedback = store.add_human_feedback(
        episode_id=args.episode_id,
        score=args.score,
        text=text,
        metadata={"source": "cli"},
    )
    print(f"feedback_id={feedback.feedback_id}")
    print(f"score={feedback.score}")


def _episode_replay(args: argparse.Namespace) -> None:
    replayer = EpisodeReplayer(EpisodeStore(args.root))
    result = replayer.replay(
        args.episode_id,
        dry_run=not args.execute,
        speed=args.speed,
        start_delay=args.start_delay,
    )
    print(f"episode_id={result.episode_id}")
    print(f"dry_run={result.dry_run} event_count={result.event_count}")
    for line in result.summary[:100]:
        print(f"- {line}")
    if len(result.summary) > 100:
        print(f"... {len(result.summary) - 100} more event(s)")


def _episode_export(args: argparse.Namespace) -> None:
    store = EpisodeStore(args.root)
    output = store.export_episode_jsonl(args.episode_id, args.output)
    print(f"exported {output.resolve()}")


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
