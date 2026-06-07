# Agent 프로젝트 구조 요약

## 한 줄 요약

이 프로젝트는 `mini_hermes`를 중심으로 한 연구용 에이전트 프로젝트다. 현재 구조는 크게 네 부분으로 나뉜다.

```text
1. Mini Hermes agent
   LLM tool-calling loop, tool 실행, 결과 저장, 점수화

2. Display video dataset recorder
   Windows 화면 캡처, 마우스/키보드 이벤트 기록, episode 저장, replay, rule-based scoring

3. 원본 Hermes wrapper
   vendor/hermes-agent를 보존하고 필요할 때 subprocess로 실행

4. Telegram bridge
   Telegram 메시지를 Mini Hermes task로 전달
```

명시적 plan 후보 생성/선택/피드백/패턴 학습 계층은 제거했다. 현재 agent는 단순한 tool-calling loop와 실행 기록 중심이다.

## 최상위 구조

```text
agent/
  main.py
  config.py
  config.example.py
  README.md
  SUMMARY.md
  requirements.txt

  agent_runs/
    mini_hermes/
      mini_hermes.db
      screenshots/
      episodes/
        episodes.db
        <episode_id>/
          episode.jsonl
          frames/

  mini_hermes/
    __main__.py
    cli.py
    agent.py
    llm.py
    tools.py
    store.py
    evaluator.py
    scheduler.py
    settings.py
    privacy.py
    telegram_bot.py
    upstream.py
    upstream_runtime.py

  dataset/
    schema.py
    storage.py
    screen.py
    win_input.py
    recorder.py
    replay.py
    scoring.py

  script/
    verify_mini_hermes.py

  vendor/
    hermes-agent/
```

## 큰 그림

```text
사용자 / PyCharm / Terminal / Telegram
        |
        v
  main.py or python -m mini_hermes
        |
        v
  mini_hermes/cli.py
        |
        +--------------------+
        |                    |
        v                    v
  MiniHermesAgent      Dataset Episode Commands
  agent.py             dataset/recorder.py
        |                    |
        v                    v
  LLM + Tool Loop       Screen/Input Recorder
  llm.py/tools.py       screen.py/win_input.py
        |                    |
        v                    v
  MiniHermesStore       EpisodeStore
  store.py              dataset/storage.py
        |                    |
        v                    v
  mini_hermes.db        episodes.db + episode.jsonl + frames/*.png
```

## 실행 진입점

### `main.py`

PyCharm에서 바로 실행하기 위한 thin entrypoint다.

```text
main.py
  -> mini_hermes.cli.main()
  -> 인자가 없으면 chat 모드
```

즉 PyCharm에서 `main.py`를 실행하면 내부적으로 다음과 같다.

```powershell
python -m mini_hermes chat
```

### `mini_hermes/__main__.py`

터미널에서 아래처럼 실행할 때 쓰인다.

```powershell
python -m mini_hermes ...
```

내부적으로는 `mini_hermes.cli.main()`을 호출한다.

### `mini_hermes/cli.py`

프로젝트의 명령어 라우터다. 사람이 입력한 명령을 해석해서 agent, recorder, scheduler, Telegram, upstream wrapper로 연결한다.

```text
cli.py
  run/chat             -> agent.py
  memories/rate/export -> store.py
  schedule-*           -> scheduler.py
  telegram-*           -> telegram_bot.py
  hermes-run           -> upstream_runtime.py
  episode-*            -> dataset/*
```

현재 주요 명령어:

```text
run
chat
rate
memories
export
schedule-add
schedule-list
schedule-run-due
doctor
telegram-bot
telegram-doctor
upstream-status
upstream-import-check
hermes-run
episode-record
episode-list
episode-score
episode-feedback
episode-replay
episode-export
```

명령어 없이 문장을 바로 입력하면 자동으로 `run`으로 처리된다.

```text
python -m mini_hermes "2+2 계산해줘"
    |
    v
python -m mini_hermes run "2+2 계산해줘"
```

## Mini Hermes Agent 흐름

Mini Hermes agent는 `mini_hermes/agent.py`의 `MiniHermesAgent`가 담당한다.

```text
사용자 task
  |
  v
MiniHermesAgent.run(task)
  |
  +--> store.start_run()
  |
  +--> system/user messages 구성
  |
  +--> LLM 호출
  |      |
  |      +--> final answer면 종료
  |      |
  |      +--> tool_calls가 있으면 tools.py로 실행
  |
  +--> store.add_step()
  +--> ToolRegistry.dispatch()
  +--> store.finish_step()
  |
  +--> store.finish_run()
  +--> evaluator.score_run()
  +--> store.finish_run(score 포함)
  |
  +--> 성공하면 memory 기록
  |
  v
RunResult
```

현재 agent는 “여러 plan 후보를 만들고 선택하는 구조”가 아니다. LLM이 현재 메시지와 사용 가능한 tool 정의를 보고 tool call 여부를 결정한다.

## Agent 관련 파일

### `mini_hermes/agent.py`

Mini Hermes의 기본 실행 루프다.

역할:

- task를 받아 run 생성
- system prompt 구성
- LLM 호출
- tool call 처리
- tool 결과를 다시 LLM 메시지에 넣음
- 최종 답변 생성
- run 점수화
- 성공 run을 memory로 저장

핵심 연결:

```text
agent.py
  -> llm.py
  -> tools.py
  -> store.py
  -> evaluator.py
```

### `mini_hermes/llm.py`

LLM 호출 계층이다.

지원:

- OpenAI-compatible API
- OpenAI API
- LiteLLM
- FakeLLM 테스트 클라이언트

`agent.py`는 특정 provider에 직접 의존하지 않고 `LLMClient.complete()` 인터페이스만 사용한다.

### `mini_hermes/tools.py`

LLM이 호출할 수 있는 tool을 정의하고 실행한다.

현재 기본 tool:

```text
calculate
capture_screen
remember
retrieve_memory
list_files
read_text_file
write_text_file
open_windows_app
run_original_hermes
```

구조:

```text
Tool
  name
  description
  parameters
  handler

ToolRegistry
  register()
  definitions()  -> LLM에게 넘길 tool schema
  dispatch()     -> 실제 tool 실행
```

`run_original_hermes`는 복잡한 browser/web/memory/todo 계열 작업을 원본 Hermes에 위임하는 통로다.

### `mini_hermes/store.py`

Mini Hermes agent 실행 데이터를 SQLite에 저장한다.

저장 테이블:

```text
runs
steps
observations
memories
schedules
upstream_runs
telegram_messages
```

역할:

- run 시작/종료 기록
- tool step 기록
- screenshot observation 기록
- memory 저장/검색
- schedule 저장/조회
- 원본 Hermes 실행 결과 저장
- Telegram 수신/처리 이벤트 저장
- trajectory JSONL export

현재 제거된 것:

```text
skills
plan_candidates
plan_feedback
plan_patterns
```

### `mini_hermes/evaluator.py`

agent run을 휴리스틱으로 점수화한다.

입력:

```text
status
steps
started_at
ended_at
final_answer
```

점수 기준:

- 성공 여부
- blocked 여부
- tool 수
- tool error 수
- 소요 시간

이 점수는 학습 모델이 아니라 첫 버전용 rule-based reward다.

### `mini_hermes/privacy.py`

저장 전에 민감정보를 기본적으로 redaction한다.

현재 처리:

```text
전화번호 형태 문자열 -> [PHONE]
API key 형태 문자열 -> [SECRET]
```

`store.py`, `dataset/storage.py`에서 저장 전에 사용한다.

### `mini_hermes/settings.py`

설정 로더다.

읽는 곳:

```text
config.py
환경변수
```

환경변수가 `config.py`보다 우선한다.

담당 설정:

- LLM provider
- API key
- model
- base URL
- Telegram bot token
- Telegram allowed chat id
- Telegram polling 설정

### `mini_hermes/scheduler.py`

반복 실행 스케줄러다.

```text
schedule-add
  -> schedules table에 interval job 저장

schedule-run-due
  -> due 상태인 task를 MiniHermesAgent로 실행
```

현재는 cron daemon이 아니라 “due job을 한 번 확인하고 실행하는” 단순 구조다.

## Display Video Dataset Episode 흐름

Display video dataset recorder는 `dataset/` 아래에 모듈화되어 있다.

목표:

```text
Windows 화면 캡처
마우스 이동/클릭 기록
키보드 이벤트 기록
timestamp 기반 episode 저장
JSONL/SQLite 동시 저장
replay
rule-based scoring
human feedback 기록
```

첫 버전에는 신경망이 없다.

```text
No neural network
No imitation learning
No RL
Only recorder/schema/storage/replay/rule-based scoring
```

## Episode 기록 흐름

```text
episode-record "작업 설명"
  |
  v
EpisodeRecorder.record()
  |
  +--> EpisodeStore.create_episode()
  |
  +--> ScreenCapture.capture()
  |       |
  |       +--> frames/*.png 저장
  |       +--> frames table 기록
  |       +--> episode.jsonl append
  |
  +--> WindowsInputRecorder
  |       |
  |       +--> low-level mouse hook
  |       +--> low-level keyboard hook
  |       +--> input_events table 기록
  |       +--> episode.jsonl append
  |
  +--> EpisodeStore.finish_episode()
  |
  v
episode_id 반환
```

저장 위치:

```text
agent_runs/mini_hermes/episodes/
  episodes.db
  <episode_id>/
    episode.jsonl
    frames/
      000000_*.png
      000001_*.png
```

## Episode 관련 파일

### `dataset/schema.py`

episode 데이터 구조를 정의한다.

주요 dataclass:

```text
Episode
ScreenFrame
InputEvent
AgentPlan
ToolCallRecord
ObservationRecord
ScoreRecord
HumanFeedback
```

이 파일은 “어떤 데이터를 저장할 것인가”를 정하는 중심 스키마다.

### `dataset/storage.py`

episode 저장소다.

동시에 두 곳에 저장한다.

```text
1. SQLite
   episodes.db

2. JSONL
   <episode_id>/episode.jsonl
```

SQLite 테이블:

```text
episodes
frames
input_events
agent_plans
tool_calls
observations
scores
human_feedback
```

JSONL은 나중에 학습/분석 데이터로 쓰기 쉽게 append-only trace 형태로 남긴다.

### `dataset/screen.py`

Windows 화면을 캡처한다.

내부적으로 Pillow의 `ImageGrab`을 사용한다.

```text
ScreenCapture.capture()
  -> 현재 화면 grab
  -> PNG 저장
  -> ScreenFrame 반환
```

### `dataset/win_input.py`

Windows 입력 이벤트 기록과 replay를 담당한다.

기록:

```text
WindowsInputRecorder
  -> WH_MOUSE_LL hook
  -> WH_KEYBOARD_LL hook
  -> InputEvent 생성
```

Replay:

```text
WindowsInputReplayer
  -> dry-run이면 요약만 출력
  -> --execute면 SendInput으로 실제 mouse/keyboard 이벤트 전송
```

개인정보 보호:

```text
record_key_text=False 기본값
```

즉 기본적으로 키 입력 원문은 저장하지 않는다. `key_code`, `key_name`, modifier 중심으로 저장한다.

### `dataset/recorder.py`

screen capture와 input hook을 episode 단위로 묶는 상위 recorder다.

```text
EpisodeRecorder
  -> EpisodeStore
  -> ScreenCapture
  -> WindowsInputRecorder
```

CLI의 `episode-record`가 이 파일을 사용한다.

### `dataset/replay.py`

저장된 input event를 다시 재생하거나 dry-run으로 검사한다.

```text
episode-replay <episode_id>
  -> dry-run summary 출력

episode-replay <episode_id> --execute
  -> 실제 입력 이벤트 전송
```

실제 replay는 현재 포커스된 Windows UI에 영향을 주므로 안전한 테스트 창에서만 사용해야 한다.

### `dataset/scoring.py`

episode를 rule-based로 점수화한다.

점수 기준:

- episode status
- frame 수
- input event 수
- tool call 수
- tool error 수
- recorder error 수
- duration

결과는 `scores` table과 `episode.jsonl`에 저장된다.

## Telegram 흐름

```text
Telegram user
  |
  v
Telegram Bot API polling
  |
  v
telegram_bot.py
  |
  +--> /id, /status, /rate 처리
  |
  +--> 일반 메시지 or /run
          |
          v
     MiniHermesAgent.run()
          |
          v
     결과를 Telegram으로 응답
```

### `mini_hermes/telegram_bot.py`

Telegram Bot API를 표준 라이브러리 HTTP 호출로 사용한다.

특징:

- 별도 Telegram 패키지 의존성 없음
- polling 방식
- allowed chat id 기반 접근 제한
- Telegram 메시지 처리 결과를 `telegram_messages` table에 저장

## 원본 Hermes wrapper 흐름

```text
Mini Hermes
  |
  +--> run_original_hermes tool
          |
          v
     upstream_runtime.py
          |
          v
     vendor/hermes-agent subprocess 실행
          |
          v
     stdout/stderr/status 저장
```

### `mini_hermes/upstream.py`

`vendor/hermes-agent`가 정상 보존되어 있는지 확인하고, 주요 upstream module import 가능성을 검사한다.

CLI:

```powershell
python -m mini_hermes upstream-status
python -m mini_hermes upstream-import-check
```

### `mini_hermes/upstream_runtime.py`

원본 Hermes를 subprocess로 실행한다.

담당:

- Mini Hermes provider 설정을 원본 Hermes 환경변수로 변환
- toolset allow/deny 처리
- browser path 환경변수 주입
- 실행 결과를 `upstream_runs` table에 저장할 수 있게 반환

CLI:

```powershell
python -m mini_hermes hermes-run "요청" --toolsets browser,web,memory,todo
```

## 데이터 저장 구조

### Mini Hermes agent DB

```text
agent_runs/mini_hermes/mini_hermes.db
```

테이블:

```text
runs
steps
observations
memories
schedules
upstream_runs
telegram_messages
```

용도:

```text
agent 실행 기록
tool call 기록
screenshot observation
memory
schedule
원본 Hermes 실행 로그
Telegram bridge 로그
```

### Episode recorder DB

```text
agent_runs/mini_hermes/episodes/episodes.db
```

테이블:

```text
episodes
frames
input_events
agent_plans
tool_calls
observations
scores
human_feedback
```

용도:

```text
Windows 화면/입력 행동 데이터셋
replay 가능한 timestamp event 기록
rule-based score
human feedback
```

## 명령어별 내부 연결

```text
run
  -> cli._run()
  -> MiniHermesAgent.run()

chat
  -> cli._chat()
  -> MiniHermesAgent.run() 반복

rate
  -> MiniHermesStore.rate_run()

memories
  -> MiniHermesStore.search_memories()

export
  -> MiniHermesStore.export_trajectories_jsonl()

episode-record
  -> EpisodeRecorder.record()

episode-list
  -> EpisodeStore.list_episodes()

episode-score
  -> RuleBasedEpisodeScorer.score()

episode-feedback
  -> EpisodeStore.add_human_feedback()

episode-replay
  -> EpisodeReplayer.replay()
  -> WindowsInputReplayer

episode-export
  -> EpisodeStore.export_episode_jsonl()

telegram-bot
  -> TelegramHermesBridge.run_forever()

hermes-run
  -> UpstreamHermesRuntime.run_oneshot()
```

## 현재 연구 방향에서 중요한 포인트

현재 코드베이스는 “바로 학습하는 agent”가 아니라, 학습/최적화 연구를 위한 데이터를 쌓는 기반이다.

지금 저장되는 데이터:

```text
agent task
tool call trajectory
screen observation
Windows screen frames
mouse/keyboard events
agent plan metadata
tool call metadata
rule-based score
human feedback
```

다음 단계에서 붙일 수 있는 것:

```text
trajectory 분석
behavior cloning dataset 구성
reward model 학습
policy optimization
screen-action model
task success classifier
```

중요한 안전 기본값:

```text
키 입력 원문 저장 비활성화
Telegram allowed chat id 필요
replay는 기본 dry-run
원본 Hermes dangerous toolset 기본 차단
파일 tool은 workspace 밖 접근 차단
전화번호/API-key 형태 문자열 redaction
```

## 검증

기본 검증:

```powershell
.\.venv\Scripts\python.exe script\verify_mini_hermes.py
```

검증 스크립트가 확인하는 것:

```text
upstream Hermes adapter
upstream runtime 환경변수 매핑
Mini Hermes tool-calling loop
blocked run redaction
Telegram bridge
workspace 파일 guardrail
episode storage/scoring/replay/export
```

