from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mini_hermes.agent import MiniHermesAgent  # noqa: E402
from dataset.replay import EpisodeReplayer  # noqa: E402
from dataset.scoring import RuleBasedEpisodeScorer  # noqa: E402
from dataset.schema import InputEvent, ScreenFrame, new_id, now_ts  # noqa: E402
from dataset.storage import EpisodeStore  # noqa: E402
from mini_hermes.llm import FakeLLM  # noqa: E402
from mini_hermes.settings import Settings, TelegramSettings  # noqa: E402
from mini_hermes.store import MiniHermesStore  # noqa: E402
from mini_hermes.telegram_bot import TelegramHermesBridge  # noqa: E402
from mini_hermes.tools import ToolContext, build_default_registry  # noqa: E402
from mini_hermes.upstream import HermesUpstream  # noqa: E402
from mini_hermes.upstream_runtime import UpstreamHermesRuntime  # noqa: E402


def main() -> None:
    _verify_upstream_adapter()
    _verify_upstream_runtime_command()
    asyncio.run(_verify_agent_loop())
    asyncio.run(_verify_blocked_run_redaction())
    asyncio.run(_verify_telegram_bridge())
    _verify_workspace_guardrails()
    _verify_episode_storage_scoring_replay()
    print("mini hermes verification passed")


def _verify_upstream_adapter() -> None:
    upstream = HermesUpstream()
    status = upstream.status()
    _assert(status.available, "vendored Hermes source is not available")
    _assert(status.core_dirs.get("agent", 0) > 0, "upstream agent package missing")
    _assert(status.core_dirs.get("tools", 0) > 0, "upstream tools package missing")
    checks = upstream.import_checks()
    failed = [check for check in checks if not check.ok]
    _assert(not failed, f"upstream import check failed: {failed}")


def _verify_upstream_runtime_command() -> None:
    settings = Settings(
        provider_name="deepseek",
        backend="openai_compatible",
        api_key="test-secret-key",
        api_key_env="DEEPSEEK_API_KEY",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
    )
    runtime = UpstreamHermesRuntime(settings=settings)
    env = runtime._build_env("deepseek")
    _assert(env.get("DEEPSEEK_API_KEY") == "test-secret-key", "deepseek key was not mapped")
    _assert("DEEPSEEK_BASE_URL" not in env, "default deepseek base URL should not override upstream")
    if sys.platform == "win32" and Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe").exists():
        _assert(env.get("AGENT_BROWSER_EXECUTABLE_PATH"), "windows browser path was not mapped")
    toolsets = runtime._normalize_toolsets("browser,web,memory,browser")
    _assert(toolsets == ("browser", "web", "memory"), "toolsets were not normalized")


async def _verify_agent_loop() -> None:
    with tempfile.TemporaryDirectory(prefix="mini_hermes_verify_") as tmp:
        root = Path(tmp)
        store = MiniHermesStore(root / "mini_hermes.db")
        llm = FakeLLM(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "calculate",
                                "arguments": json.dumps({"expression": "2+3*4"}),
                            },
                        }
                    ],
                },
                {"content": "2+3*4=14입니다."},
            ]
        )
        settings = Settings(
            provider_name="fake",
            backend="fake",
            api_key="fake",
            api_key_env="FAKE_API_KEY",
            model="fake-model",
            base_url="",
        )
        agent = MiniHermesAgent(
            llm=llm,
            settings=settings,
            store=store,
            workspace=root,
            auto_observe=False,
            max_steps=4,
        )

        result = await agent.run("2+3*4 계산해줘", learn=True)
        _assert(result.status == "success", "agent run did not succeed")
        _assert("14" in result.final_answer, "final answer missing calculated value")
        _assert(result.score > 0.7, "heuristic score too low")

        steps = store.get_steps(result.run_id)
        _assert(len(steps) == 1, "expected one tool step")
        _assert(steps[0]["tool_name"] == "calculate", "wrong tool executed")
        _assert("14" in steps[0]["result_json"], "tool result was not persisted")

        memories = store.search_memories("계산", limit=5)
        _assert(memories, "successful run did not create a memory")

        export_path = store.export_trajectories_jsonl(root / "export.jsonl")
        exported = export_path.read_text(encoding="utf-8")
        _assert(result.run_id in exported, "trajectory export missing run id")
        exported_entry = json.loads(exported.splitlines()[0])
        _assert("observations" in exported_entry, "trajectory export missing observations")

        conn = sqlite3.connect(store.db_path)
        try:
            run_row = conn.execute(
                "select status, score from runs where run_id = ?",
                (result.run_id,),
            ).fetchone()
        finally:
            conn.close()
        _assert(run_row[0] == "success" and run_row[1] > 0.7, "run score did not persist")


async def _verify_blocked_run_redaction() -> None:
    with tempfile.TemporaryDirectory(prefix="mini_hermes_blocked_") as tmp:
        root = Path(tmp)
        store = MiniHermesStore(root / "mini_hermes.db")
        llm = FakeLLM([{"content": "아이폰 앱을 직접 제어할 수 없습니다."}])
        settings = Settings(
            provider_name="fake",
            backend="fake",
            api_key="fake",
            api_key_env="FAKE_API_KEY",
            model="fake-model",
            base_url="",
        )
        agent = MiniHermesAgent(
            llm=llm,
            settings=settings,
            store=store,
            workspace=root,
            auto_observe=False,
            max_steps=2,
        )

        result = await agent.run("01056086051 문자 오면 앱에 등록해줘", learn=True)
        _assert(result.status == "blocked", "blocked request was not marked blocked")
        _assert(result.score <= 0.25, "blocked request score was too high")
        memories = store.search_memories("아이폰", limit=5)
        _assert(not memories, "blocked run should not create a successful-run memory")
        run = store.get_run(result.run_id)
        _assert(run is not None and "01056086051" not in run["task"], "phone number was not redacted in run log")


async def _verify_telegram_bridge() -> None:
    with tempfile.TemporaryDirectory(prefix="mini_hermes_telegram_") as tmp:
        root = Path(tmp)
        store = MiniHermesStore(root / "mini_hermes.db")
        llm = FakeLLM([{"content": "텔레그램 브리지 응답입니다."}])
        settings = Settings(
            provider_name="fake",
            backend="fake",
            api_key="fake",
            api_key_env="FAKE_API_KEY",
            model="fake-model",
            base_url="",
        )
        agent = MiniHermesAgent(
            llm=llm,
            settings=settings,
            store=store,
            workspace=root,
            auto_observe=False,
            max_steps=2,
        )
        telegram_settings = TelegramSettings(
            bot_token="test-token",
            bot_token_env="TELEGRAM_BOT_TOKEN",
            allowed_chat_ids=("123",),
            polling_timeout=1,
            request_timeout=5,
            workspace=str(root),
            auto_observe=False,
            max_steps=2,
        )
        client = _FakeTelegramClient()
        bridge = TelegramHermesBridge(
            settings=telegram_settings,
            agent=agent,
            store=store,
            client=client,
        )
        await bridge.handle_update(
            {
                "update_id": 10,
                "message": {
                    "message_id": 20,
                    "chat": {"id": 123},
                    "from": {"username": "tester"},
                    "text": "/run 텔레그램 테스트",
                },
            }
        )
        sent_text = "\n".join(message["text"] for message in client.sent_messages)
        _assert("텔레그램 브리지 응답입니다" in sent_text, "telegram bridge did not return agent answer")
        _assert("run_id=" in sent_text, "telegram bridge response did not include run id")

        conn = sqlite3.connect(store.db_path)
        try:
            rows = conn.execute("select status, run_id from telegram_messages order by created_at").fetchall()
        finally:
            conn.close()
        _assert(any(row[0] == "received" for row in rows), "telegram received event was not persisted")
        _assert(any(row[0] == "success" and row[1] for row in rows), "telegram run event was not persisted")

        blocked_client = _FakeTelegramClient()
        blocked_bridge = TelegramHermesBridge(
            settings=telegram_settings,
            agent=agent,
            store=store,
            client=blocked_client,
        )
        await blocked_bridge.handle_update(
            {
                "update_id": 11,
                "message": {
                    "message_id": 21,
                    "chat": {"id": 999},
                    "from": {"username": "intruder"},
                    "text": "허용되지 않은 요청",
                },
            }
        )
        blocked_text = "\n".join(message["text"] for message in blocked_client.sent_messages)
        _assert("허용되지 않은 Telegram chat" in blocked_text, "unauthorized telegram chat was not rejected")


def _verify_workspace_guardrails() -> None:
    with tempfile.TemporaryDirectory(prefix="mini_hermes_tools_") as tmp:
        root = Path(tmp)
        store = MiniHermesStore(root / "mini_hermes.db")
        registry = build_default_registry()
        run_id = store.start_run("tool guardrail test", "fake", "fake")
        context = ToolContext(store=store, run_id=run_id, workspace=root)

        write_result = registry.dispatch(
            "write_text_file",
            {"path": "notes/result.txt", "content": "ok", "overwrite": False},
            context,
        )
        _assert(write_result["ok"], "workspace write failed")
        _assert((root / "notes" / "result.txt").read_text(encoding="utf-8") == "ok", "file content mismatch")

        read_result = registry.dispatch(
            "read_text_file",
            {"path": "notes/result.txt", "max_chars": 10},
            context,
        )
        _assert(read_result["content"] == "ok", "workspace read failed")

        blocked = registry.dispatch(
            "write_text_file",
            {"path": str(root.parent / "escape.txt"), "content": "bad", "overwrite": True},
            context,
        )
        _assert(not blocked["ok"], "path escape was not blocked")


def _verify_episode_storage_scoring_replay() -> None:
    with tempfile.TemporaryDirectory(prefix="mini_hermes_episode_") as tmp:
        root = Path(tmp)
        store = EpisodeStore(root)
        episode = store.create_episode(
            "테스트 작업",
            metadata={"source": "verification", "record_key_text": False},
        )
        store.add_agent_plan(episode.episode_id, ["화면을 확인한다", "필요한 입력을 수행한다"])
        frame_path = root / episode.episode_id / "frames" / "000000.png"
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        frame_path.write_bytes(b"fake-png")
        store.add_frame(
            ScreenFrame(
                frame_id=new_id("frame"),
                episode_id=episode.episode_id,
                timestamp=now_ts(),
                index=0,
                image_path=str(frame_path),
                width=10,
                height=10,
            )
        )
        store.add_input_event(
            InputEvent(
                event_id=new_id("input"),
                episode_id=episode.episode_id,
                timestamp=now_ts(),
                kind="keyboard",
                action="key_down",
                key_code=65,
                key_name="A",
                key_text="",
                metadata={"raw_key_text_recorded": False},
            )
        )
        store.add_tool_call(
            episode.episode_id,
            tool_name="test_tool",
            arguments={"ok": True},
            result={"done": True},
            status="success",
        )
        store.add_observation(episode.episode_id, kind="note", text="테스트 관찰")
        store.add_human_feedback(episode.episode_id, score=0.8, text="좋음")
        store.finish_episode(episode.episode_id, status="completed")

        scorer = RuleBasedEpisodeScorer(store)
        score = scorer.score(episode.episode_id)
        _assert(score.score > 0.5, "episode score should be positive for completed episode")
        latest = store.get_latest_score(episode.episode_id)
        _assert(latest is not None, "episode score was not persisted")

        replayer = EpisodeReplayer(store)
        replay = replayer.replay(episode.episode_id, dry_run=True)
        _assert(replay.event_count == 1, "dry-run replay should see one input event")
        _assert("keyboard" in replay.summary[0], "dry-run replay summary missing keyboard event")

        export_path = store.export_episode_jsonl(episode.episode_id, root / "exported.jsonl")
        exported = export_path.read_text(encoding="utf-8")
        _assert("episode_started" in exported, "episode JSONL missing start record")
        _assert("input_event" in exported, "episode JSONL missing input event")
        _assert("human_feedback" in exported, "episode JSONL missing human feedback")
        _assert('"key_text": ""' in exported, "raw key text should be empty by default")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


class _FakeTelegramClient:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_message_id,
            }
        )


if __name__ == "__main__":
    main()
