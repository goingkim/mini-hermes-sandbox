# Mini Hermes Research Agent

Hermes-style research agent plus display video dataset episode recorder, kept deliberately small.

## Setup

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Provider settings live in `config.py`. Use `config.example.py` as the template.
Environment variables override `config.py`.

```powershell
$env:AGENT_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "sk-..."
$env:AGENT_MODEL = "deepseek-chat"
```

## Run

PyCharm에서 root `main.py`를 실행하면 대화형 프롬프트가 바로 뜹니다.

```text
you>
```

One task:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes run "2+3*4 계산해줘" --no-observe
```

Interactive chat:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes chat --no-observe
```

## Display Video Dataset Episodes

Windows 10/11 화면 프레임과 입력 이벤트를 episode 단위로 기록합니다. 키 입력 원문 저장은 기본 비활성화되어 있고, 기본 기록은 key code/name 중심입니다.

Screen-only smoke test:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes episode-record "검증용 화면 캡처" --duration 1 --fps 1 --no-input
```

Screen + mouse/keyboard event hooks:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes episode-record "작업 설명" --duration 10 --fps 1
```

UI primitive learning episode:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes episode-record "이메일 작성 버튼을 누르고 제목을 입력한다" --duration 10 --fps 2 --skill send-email --expected-primitive click --expected-primitive type_text --expected-primitive verify_state
.\.venv\Scripts\python.exe -m mini_hermes episode-build-primitives <episode_id>
.\.venv\Scripts\python.exe -m mini_hermes episode-score <episode_id>
.\.venv\Scripts\python.exe -m mini_hermes episode-export-primitives <episode_id> --output agent_runs\primitive_samples.jsonl
```

이 흐름은 raw screen/input trace 위에 다음 학습 단위를 추가합니다.

- `move_mouse`: pointer 이동
- `click`: UI target 클릭
- `scroll`: viewport/control 스크롤
- `type_text`: focused control에 텍스트 입력, 기본값은 원문 미저장
- `press_key`: Enter, Tab, Escape, Backspace 같은 비텍스트 키
- `verify_state`: 마지막 화면 상태 확인

Inspect, score, replay dry-run, export:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes episode-list --limit 5
.\.venv\Scripts\python.exe -m mini_hermes episode-build-primitives <episode_id>
.\.venv\Scripts\python.exe -m mini_hermes episode-score <episode_id>
.\.venv\Scripts\python.exe -m mini_hermes episode-export-primitives <episode_id> --output agent_runs\primitive_samples.jsonl
.\.venv\Scripts\python.exe -m mini_hermes episode-replay <episode_id>
.\.venv\Scripts\python.exe -m mini_hermes episode-feedback <episode_id> 0.8 "작업 품질 양호"
.\.venv\Scripts\python.exe -m mini_hermes episode-export <episode_id> --output agent_runs\episode.jsonl
```

Actual replay sends mouse/keyboard events and is disabled by default. Use `--execute` only in a safe test window.

```powershell
.\.venv\Scripts\python.exe -m mini_hermes episode-replay <episode_id> --execute
```

Episode data is stored under `agent_runs/mini_hermes/episodes/`:

- `episodes.db`: SQLite metadata and event tables
- `<episode_id>/episode.jsonl`: append-only JSONL trace
- `<episode_id>/frames/*.png`: captured screen frames

`episode-export-primitives`는 primitive별 학습 JSONL을 만듭니다. 각 sample은 `task`, `primitive`, `frame_path`, `target`, `value`, `input_event_ids`, `reward`를 포함하므로 skill 문서의 절차를 실제 화면 frame/action/reward와 연결하는 데 사용할 수 있습니다.

## Telegram Bridge

Mini Hermes can run as a Telegram polling bot. The Telegram layer is only an input/output bridge; every task still goes through the same `MiniHermesAgent.run()` path used by PyCharm and the CLI.

```python
TELEGRAM_BOT_TOKEN = ""
TELEGRAM_ALLOWED_CHAT_IDS = ["123456789"]
TELEGRAM_AUTO_OBSERVE = False
TELEGRAM_MAX_STEPS = 8
```

```powershell
.\.venv\Scripts\python.exe -m mini_hermes telegram-doctor
.\.venv\Scripts\python.exe -m mini_hermes telegram-bot --allow-any-chat
```

Send `/id` to the bot, copy the returned chat_id into `TELEGRAM_ALLOWED_CHAT_IDS`, then restart normally:

```powershell
.\.venv\Scripts\python.exe -m mini_hermes telegram-bot
```

Supported Telegram commands:

- `/run <작업>` or a plain text message: run a Mini Hermes task
- `/rate <run_id> <0.0-1.0> [이유]`: attach user reward to a run
- `/status`: show bridge status
- `/id`: show the current chat id

## Vendored Hermes

The upstream NousResearch Hermes source is preserved under `vendor/hermes-agent/`.
Use `mini_hermes/upstream.py` to import explicit upstream modules for experiments.
Use `mini_hermes/upstream_runtime.py` when Mini Hermes needs to run original Hermes as a subprocess and keep the result in the Mini Hermes research DB.

```powershell
.\.venv\Scripts\python.exe -m mini_hermes upstream-status
.\.venv\Scripts\python.exe -m mini_hermes upstream-import-check
.\.venv\Scripts\python.exe -m mini_hermes hermes-run "요청 내용" --toolsets browser,web,memory,todo
```

## Current Structure

- `mini_hermes/settings.py`: provider and Telegram config loader using `config.py` and env vars
- `mini_hermes/llm.py`: OpenAI-compatible, OpenAI, LiteLLM, and FakeLLM clients
- `mini_hermes/tools.py`: tool registry and primitive tools
- `mini_hermes/store.py`: SQLite store for agent runs, steps, observations, memories, schedules, upstream runs, and Telegram messages
- `mini_hermes/agent.py`: simple tool-calling loop, scoring, and memory logging
- `mini_hermes/evaluator.py`: heuristic run scoring
- `mini_hermes/privacy.py`: basic phone/API-key redaction before persistence
- `mini_hermes/scheduler.py`: interval schedule runner
- `mini_hermes/telegram_bot.py`: Telegram Bot API polling bridge
- `dataset/`: display video dataset recorder, schema, storage, replay, and rule-based scoring
- `mini_hermes/upstream.py`: adapter for vendored upstream Hermes modules
- `mini_hermes/upstream_runtime.py`: wrapper that executes vendored original Hermes with Mini Hermes config
- `mini_hermes/cli.py`: command-line interface

## Verify

No API call:

```powershell
.\.venv\Scripts\python.exe script\verify_mini_hermes.py
```
