# 작업 요약

## 현재 목표

ChatGPT 공유 대화에서 논의한 것처럼 Python으로 간단한 에이전트 CLI를 구현하고, DeepSeek API 토큰으로 실행 가능한지 확인한다.

추가로 clarified된 장기 목표는 단순한 `질문 -> 후보 생성 -> 평가 -> 최고 답변 선택` 구조가 아니다. 사용자가 원하는 방향은 Hermes류의 self-improvement에 더 가깝다. 즉, 에이전트를 계속 사용하면서 실행 기록, 실패, 성공, 사용자 피드백을 축적하고, 그 데이터를 바탕으로 에이전트의 정책, 스킬, 메모리 운용, 도구 선택, 프롬프트 전략이 점진적으로 진화하는 구조다. 이 진화를 무작정 수행하지 않고, 수학적으로 정의한 목적함수/최적점 쪽으로 신경망 기반 value/reward/policy 모델을 이용해 유도하는 것이 핵심 의도다.

2026-05-24 추가 목표는 OpenClaw/Hermes처럼 "말만 하는 에이전트"가 아니라 실제 로컬 작업을 수행하는 도구 기반 에이전트로 발전시키는 것이다. 오늘의 실행 결과물은 사진 폴더 연도별 정리와 Microsoft Paint에서 Apple-style 로고, 수박, 바나나 그림 열기다.

## 구현 상태

- `main.py`를 PyCharm 샘플 코드에서 실제 에이전트 CLI로 교체했다.
- OpenAI Agents SDK 기반으로 `General Assistant`, `Coding_Agent`, `Planning_Agent`를 구성했다.
- `calculate`, `get_current_time` 도구를 추가했다.
- `DEEPSEEK_API_KEY`가 있으면 DeepSeek OpenAI-compatible endpoint를 사용하도록 수정했다.
- 기본 DeepSeek 모델은 `deepseek-chat`으로 설정했다.
- Windows 콘솔의 cp949 출력 문제를 피하려고 stdout/stderr를 UTF-8로 재설정했다.
- DeepSeek만 사용할 때 OpenAI tracing export 경고가 나오지 않도록 tracing을 비활성화했다.
- `config.py`를 추가해 API key, provider, model, base URL을 파일에서 관리하게 했다.
- `AGENT_PROVIDER`, `AGENT_MODEL`, provider별 API key 환경변수로 `config.py` 값을 임시 override할 수 있다.
- `openai`, `openai_compatible`, `litellm` backend를 지원하도록 구조를 바꿨다.
- 추후 Gemini는 OpenAI-compatible 또는 LiteLLM 방식, Claude는 LiteLLM 방식으로 붙일 수 있다.
- `requirements.txt`를 `openai-agents[litellm]>=0.6.0`으로 바꿔 LiteLLM provider를 사용할 수 있게 했다.
- 민감정보가 담긴 `config.py`가 실수로 버전관리되지 않도록 root `.gitignore`에 추가했다.
- 장기 설계 방향은 Best-of-N 답변 선택기보다 self-improving agent다. 필요한 핵심 모듈은 trace store, feedback collector, objective/reward model, policy/value model, skill/memory optimizer, evaluation loop다.
- `agent_tools.py`를 추가했다.
  - `organize_pictures_by_year`: 이미지 파일을 EXIF 날짜 또는 파일 수정 시간 기준으로 연도별 폴더에 이동/복사한다.
  - `undo_photo_organization`: 사진 정리 manifest를 기반으로 이동 작업을 되돌린다.
  - `draw_in_paint`: 설명 기반 이미지를 생성하고 Microsoft Paint에서 연다. 현재 렌더러는 Apple-style 로고, 수박, 바나나 요청을 지원한다.
  - 그림판 기능은 요청마다 `paint_logo`, `paint_watermelon` 같은 agent tool을 늘리는 방식이 아니라, 하나의 `draw_in_paint` 도구 안에서 렌더러를 선택하는 방식으로 유지한다.
  - 미지원 그림 요청의 fallback은 한글 프롬프트 텍스트를 이미지에 직접 쓰지 않는다. Pillow 기본 폰트가 한글을 깨진 텍스트처럼 렌더링할 수 있어서, 중립 placeholder 이미지로 바꿨다.
- `trace_store.py`를 추가했다.
  - SQLite `agent_runs/agent.db`에 실행 입력, provider, model, 결과, 상태를 저장한다.
- `main.py`에 새 도구를 연결했다.
  - "사진 폴더에 있는 이미지 연도별로 정리해줘" 요청에 `organize_pictures_by_year`를 쓰도록 안내했다.
  - "그림판에서 애플로고 그려줘" 같은 요청에 범용 `draw_in_paint`를 쓰도록 안내했다.
  - 단발 실행과 대화형 실행 모두 run_id를 출력하고 trace를 저장한다.
- `requirements.txt`에 `pillow>=10.0.0`을 추가했다.
- `.gitignore`에 `agent_runs/`를 추가했다.
- `scripts/verify_local_tools.py`를 추가했다.
  - LLM 호출 없이 사진 정리/되돌리기, Apple-style 로고 렌더링, 수박 렌더링, trace 저장을 검증한다.
- `trace_store.py`에서 SQLite 연결을 명시적으로 닫도록 고쳤다. Windows에서 임시 DB 검증 시 파일 잠금이 남는 문제를 막기 위해서다.

## 현재 권한 모델

- 이 프로젝트에는 아직 OpenClaw식 Gateway 권한 계층이 없다.
- 로컬 도구는 `main.py`를 실행한 Windows 사용자 계정의 권한으로 동작한다.
- 사진 정리는 별도 관리자 권한을 얻은 것이 아니라, Python 프로세스가 현재 사용자가 접근 가능한 폴더에서 `shutil.move`를 실행한 것이다.
- 외부 채널/웹훅/상시 실행으로 확장하기 전에는 allowlist, 승인 프롬프트, dry-run, 감사 로그, 위험 경로 차단 같은 권한 계층이 필요하다.

## OpenClaw/Hermes 방향 점검

2026-05-24에 공개 문서와 레포를 다시 확인했다.

- OpenClaw는 Tools, Skills, Plugins를 구분한다. Tool은 모델이 호출하는 typed function이고, Skill은 `SKILL.md`로 도구를 언제/어떻게 쓸지 알려주는 절차 지식이며, Plugin은 도구/스킬/채널/모델 provider 등을 패키징한다.
- OpenClaw의 Gateway는 여러 채널과 실행 도구를 하나의 로컬 제어면으로 묶고, 인증/권한/승인 경계를 둔다.
- Hermes Agent도 Tools & Toolsets, Skills, Persistent Memory를 분리한다. Hermes는 경험에서 스킬을 만들고 개선하며, bounded memory와 session search를 통해 과거 작업을 재사용하는 구조다.
- 따라서 현재 프로젝트도 요청 하나마다 새 agent tool 함수를 무한히 만드는 방향이 아니라, 소수의 안정적인 primitive tool과 재사용 가능한 skill/memory/evaluation 계층을 쌓는 방향이 맞다.

## 검증 결과

- 프로젝트 `.venv` 환경:
  - Python: `C:\Users\jh902\PycharmProjects\agent\.venv\Scripts\python.exe`
  - Version: Python 3.14.0
  - `openai-agents` 설치됨
  - `python -m py_compile main.py` 통과
  - DeepSeek API 호출 1회 성공

- Anaconda `torch_p3.8` 환경:
  - Python: `C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe`
  - Version: Python 3.10.20
  - 처음에는 `agents` 모듈이 설치되어 있지 않아 `ModuleNotFoundError: No module named 'agents'`가 발생했다.
  - `conda run -n torch_p3.8 python -m pip install -r requirements.txt`로 의존성을 설치했다.
  - 이후 `openai-agents` import 성공
  - LiteLLM 설치 및 import 성공
  - Pillow 설치 성공
  - `python -m py_compile main.py` 통과
  - `python -m py_compile main.py agent_tools.py trace_store.py config.py config.example.py scripts\verify_local_tools.py` 통과
  - `python scripts\verify_local_tools.py` 통과
  - 환경변수 없이 `config.py`의 DeepSeek 키만으로 API 호출 성공: `2 + 3 = 5입니다.`
  - 임시 사진 폴더를 자연어 프롬프트로 정리하는 테스트 성공
  - `agent_runs/paint/apple_logo.png` 생성 및 Paint 실행 성공
  - `mspaint` 프로세스 확인: `apple_logo - 그림판`
  - `main.py "그림판 열어서 수박 그려줘"` 실행 성공
  - `agent_runs/paint/drawing.png` 생성 확인
  - `mspaint` 프로세스 확인: `drawing - 그림판`
  - 생성된 수박 이미지 픽셀 검사: red_pixels=51576, green_pixels=183217
  - `main.py "그림판 열어서 바나나 그려줘"` 실행 성공
  - 생성된 바나나 이미지 픽셀 검사: yellow_pixels=61239, brown_pixels=20727
  - 테스트 사진 폴더 프롬프트 실행 성공: 2021/2025 이미지가 각각 `ByYear\2021`, `ByYear\2025`로 이동됨
  - `agent_runs/agent.db`에 실행 trace 저장 확인

## 실행 모델

- 기본 provider: `deepseek`
- DeepSeek 사용 시 기본 모델: `deepseek-chat`
- 환경변수 `AGENT_PROVIDER`, `AGENT_MODEL`로 변경 가능하다.

## 실행 예시

```powershell
$env:DEEPSEEK_API_KEY = "sk-..."
$env:AGENT_MODEL = "deepseek-chat"
.\.venv\Scripts\python.exe main.py "테스트입니다. 2+3만 계산해서 답하세요."
```

현재는 `config.py`에 DeepSeek 키가 등록되어 있으므로 PyCharm 실행 버튼처럼 환경변수를 넣지 않는 실행도 동작한다.

Anaconda `torch_p3.8`에서 실행하려면 아래처럼 실행할 수 있다.

```powershell
conda run -n torch_p3.8 python main.py "테스트입니다. 2+3만 계산해서 답하세요."
```

또는 conda 환경의 Python을 직접 호출할 수 있다.

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "테스트입니다. 2+3만 계산해서 답하세요."
```

사진 정리:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "사진 폴더에 있는 이미지 연도별로 정리해줘"
```

그림판 실행:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "그림판에서 애플로고 그려줘"
```

수박 그림판 실행:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "그림판 열어서 수박 그려줘"
```

바나나 그림판 실행:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "그림판 열어서 바나나 그려줘"
```

로컬 도구 검증:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe scripts\verify_local_tools.py
```
