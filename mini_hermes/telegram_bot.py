from __future__ import annotations

import asyncio
import hashlib
import json
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from mini_hermes.agent import MiniHermesAgent
from mini_hermes.privacy import clean_text
from mini_hermes.settings import TelegramSettings
from mini_hermes.store import MiniHermesStore


class TelegramAPIError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramInboundMessage:
    update_id: int
    chat_id: str
    message_id: int
    username: str
    text: str


class TelegramBotAPI:
    def __init__(self, token: str, request_timeout: int = 90) -> None:
        self.token = token
        self.request_timeout = request_timeout
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.ssl_context = ssl.create_default_context()

    async def get_me(self) -> dict[str, Any]:
        return await self.request("getMe", {})

    async def delete_webhook(self, drop_pending_updates: bool = False) -> dict[str, Any]:
        return await self.request("deleteWebhook", {"drop_pending_updates": drop_pending_updates})

    async def get_updates(
        self,
        offset: int | None,
        polling_timeout: int,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": polling_timeout,
            "allowed_updates": ["message"],
        }
        if offset is not None:
            payload["offset"] = offset
        result = await self.request(
            "getUpdates",
            payload,
            timeout=max(self.request_timeout, polling_timeout + 15),
        )
        return list(result)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_to_message_id: int | None = None,
    ) -> None:
        for chunk in _message_chunks(text):
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": chunk,
                "disable_web_page_preview": True,
            }
            if reply_to_message_id is not None:
                payload["reply_to_message_id"] = reply_to_message_id
            await self.request("sendMessage", payload)

    async def request(
        self,
        method: str,
        payload: dict[str, Any],
        timeout: int | None = None,
    ) -> Any:
        return await asyncio.to_thread(self._request_sync, method, payload, timeout)

    def _request_sync(
        self,
        method: str,
        payload: dict[str, Any],
        timeout: int | None,
    ) -> Any:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout or self.request_timeout,
                context=self.ssl_context,
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise TelegramAPIError(f"{method} failed with HTTP {exc.code}: {body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise TelegramAPIError(f"{method} failed: {exc.reason}") from exc

        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise TelegramAPIError(f"{method} returned non-JSON response") from exc
        if not parsed.get("ok"):
            description = parsed.get("description") or "unknown Telegram API error"
            raise TelegramAPIError(f"{method} failed: {description}")
        return parsed.get("result")


class TelegramHermesBridge:
    def __init__(
        self,
        settings: TelegramSettings,
        agent: MiniHermesAgent,
        store: MiniHermesStore,
        client: Any | None = None,
        allow_any_chat: bool = False,
    ) -> None:
        if not settings.bot_token:
            raise SystemExit(
                f"Telegram bot token is not set. Set it in config.py or with ${settings.bot_token_env}."
            )
        self.settings = settings
        self.agent = agent
        self.store = store
        self.client = client or TelegramBotAPI(settings.bot_token, settings.request_timeout)
        self.allow_any_chat = allow_any_chat
        self._run_lock = asyncio.Lock()

    async def run_forever(self, drop_pending_updates: bool = False) -> None:
        await self.client.delete_webhook(drop_pending_updates=drop_pending_updates)
        me = await self.client.get_me()
        username = me.get("username") or me.get("first_name") or "unknown"
        print(f"Telegram Mini Hermes bot connected as @{username}")
        print("Press Ctrl+C to stop.")
        offset: int | None = None

        while True:
            try:
                updates = await self.client.get_updates(offset, self.settings.polling_timeout)
                for update in updates:
                    update_id = int(update.get("update_id", 0))
                    offset = update_id + 1
                    await self.handle_update(update)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                print(f"telegram polling error: {type(exc).__name__}: {exc}", file=sys.stderr)
                await asyncio.sleep(3)

    async def handle_update(self, update: dict[str, Any]) -> None:
        message = _extract_message(update)
        if not message:
            return

        self._record_message(message, status="received")
        command, rest = _command_and_rest(message.text)
        if command in {"/start", "/help"}:
            await self.client.send_message(message.chat_id, self._help_text(message.chat_id), message.message_id)
            return
        if command == "/id":
            await self.client.send_message(message.chat_id, f"chat_id={message.chat_id}", message.message_id)
            return

        if not self._authorized(message.chat_id):
            self._record_message(message, status="unauthorized")
            await self.client.send_message(
                message.chat_id,
                (
                    "허용되지 않은 Telegram chat입니다.\n"
                    f"이 chat_id를 TELEGRAM_ALLOWED_CHAT_IDS에 추가하세요: {message.chat_id}"
                ),
                message.message_id,
            )
            return

        if command == "/status":
            await self.client.send_message(message.chat_id, self._status_text(), message.message_id)
            return
        if command == "/rate":
            await self._handle_rate(message, rest)
            return
        if command and command != "/run":
            await self.client.send_message(message.chat_id, self._help_text(message.chat_id), message.message_id)
            return

        task = rest if command == "/run" else message.text
        task = clean_text(task).strip()
        if not task:
            await self.client.send_message(message.chat_id, "실행할 작업 내용을 같이 보내주세요.", message.message_id)
            return

        await self._run_task(message, task)

    async def _run_task(self, message: TelegramInboundMessage, task: str) -> None:
        if self._run_lock.locked():
            await self.client.send_message(
                message.chat_id,
                "이전 Telegram 작업이 아직 실행 중입니다. 이번 요청은 이어서 처리합니다.",
                message.message_id,
            )

        async with self._run_lock:
            await self.client.send_message(message.chat_id, "Mini Hermes 작업을 시작합니다.", message.message_id)
            try:
                result = await self.agent.run(task, learn=True)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self._record_message(message, status="error", error=error)
                await self.client.send_message(message.chat_id, f"실행 실패: {error}", message.message_id)
                return

            self._record_message(message, status=result.status, run_id=result.run_id)
            answer = (
                f"{result.final_answer}\n\n"
                f"[run_id={result.run_id}]\n"
                f"[status={result.status} score={result.score:.3f}]\n"
                f"[score_reason={result.score_reason}]"
            )
            await self.client.send_message(message.chat_id, answer, message.message_id)

    async def _handle_rate(self, message: TelegramInboundMessage, rest: str) -> None:
        parts = rest.split(maxsplit=2)
        if len(parts) < 2:
            await self.client.send_message(
                message.chat_id,
                "사용법: /rate <run_id> <0.0-1.0> [이유]",
                message.message_id,
            )
            return
        run_id, score_raw = parts[0], parts[1]
        reason = parts[2] if len(parts) > 2 else "telegram user feedback"
        try:
            score = float(score_raw)
        except ValueError:
            await self.client.send_message(message.chat_id, "score는 0.0부터 1.0 사이 숫자여야 합니다.", message.message_id)
            return
        self.store.rate_run(run_id, score, reason)
        await self.client.send_message(message.chat_id, f"rated {run_id} as {max(0.0, min(1.0, score)):.3f}", message.message_id)

    def _authorized(self, chat_id: str) -> bool:
        return self.allow_any_chat or chat_id in set(self.settings.allowed_chat_ids)

    def _help_text(self, chat_id: str) -> str:
        allowed_hint = "allowed" if self._authorized(chat_id) else "not allowed"
        return (
            "Mini Hermes Telegram bridge\n"
            f"chat_id={chat_id} ({allowed_hint})\n\n"
            "명령어:\n"
            "/run <작업> - Mini Hermes로 작업 실행\n"
            "<일반 메시지> - 작업으로 바로 실행\n"
            "/rate <run_id> <0.0-1.0> [이유] - 실행 결과 보상 입력\n"
            "/status - 연결 상태 확인\n"
            "/id - chat_id 확인"
        )

    def _status_text(self) -> str:
        return (
            "Mini Hermes Telegram bridge is running.\n"
            f"allowed_chats={len(self.settings.allowed_chat_ids)}\n"
            f"allow_any_chat={self.allow_any_chat}\n"
            f"workspace={self.agent.workspace}\n"
            f"auto_observe={self.agent.auto_observe}\n"
            f"max_steps={self.agent.max_steps}\n"
            f"provider={self.agent.settings.provider_name}\n"
            f"model={self.agent.settings.model}"
        )

    def _record_message(
        self,
        message: TelegramInboundMessage,
        status: str,
        run_id: str = "",
        error: str = "",
    ) -> None:
        self.store.record_telegram_message(
            update_id=message.update_id,
            chat_id_hash=_chat_id_hash(message.chat_id),
            message_id=message.message_id,
            username=message.username,
            text=message.text,
            run_id=run_id,
            status=status,
            error=error,
        )


def _extract_message(update: dict[str, Any]) -> TelegramInboundMessage | None:
    raw_message = update.get("message") or {}
    text = raw_message.get("text")
    chat = raw_message.get("chat") or {}
    if not text or not chat.get("id"):
        return None
    sender = raw_message.get("from") or {}
    username = sender.get("username") or sender.get("first_name") or ""
    return TelegramInboundMessage(
        update_id=int(update.get("update_id", 0)),
        chat_id=str(chat["id"]),
        message_id=int(raw_message.get("message_id", 0)),
        username=str(username),
        text=clean_text(str(text)),
    )


def _command_and_rest(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", stripped
    first, _, rest = stripped.partition(" ")
    command = first.split("@", 1)[0].lower()
    return command, rest.strip()


def _chat_id_hash(chat_id: str) -> str:
    digest = hashlib.sha256(str(chat_id).encode("utf-8")).hexdigest()
    return f"telegram:{digest[:16]}"


def _message_chunks(text: str, chunk_size: int = 3800) -> list[str]:
    text = clean_text(text).strip() or "(empty)"
    return [text[index : index + chunk_size] for index in range(0, len(text), chunk_size)]
