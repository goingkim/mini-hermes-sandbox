# Python Agent

OpenAI Agents SDK로 만든 간단한 파이썬 에이전트 예제입니다.

## 준비

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

기본 설정은 `config.py`에서 관리합니다. 처음 실행할 때는 `config.example.py`를 참고해서 `config.py`를 만들면 됩니다. 현재 기본 provider는 `deepseek`이고 기본 모델은 `deepseek-chat`입니다.

```python
DEFAULT_PROVIDER = "deepseek"
```

환경변수로 임시 변경할 수도 있습니다. 환경변수는 `config.py`보다 우선합니다.

```powershell
$env:AGENT_PROVIDER = "deepseek"
$env:DEEPSEEK_API_KEY = "sk-..."
$env:AGENT_MODEL = "deepseek-chat"
```

## Provider 설정

`config.py`의 `PROVIDERS`에 provider를 추가하거나 수정합니다.

- `backend = "openai"`: OpenAI 기본 SDK 연결
- `backend = "openai_compatible"`: DeepSeek, Gemini OpenAI-compatible endpoint 등
- `backend = "litellm"`: Claude, Gemini 등 LiteLLM이 지원하는 provider

```powershell
$env:AGENT_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "..."
```

```powershell
$env:AGENT_PROVIDER = "claude"
$env:ANTHROPIC_API_KEY = "..."
```

## 실행

대화형 실행:

```powershell
.\.venv\Scripts\python.exe main.py
```

한 번만 실행:

```powershell
.\.venv\Scripts\python.exe main.py "파이썬 리스트 컴프리헨션 예제를 설명해줘"
```

Anaconda `torch_p3.8` 환경에서 직접 실행:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "테스트입니다. 2+3만 계산해서 답하세요."
```

로컬 작업 실행 예시:

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "사진 폴더에 있는 이미지 연도별로 정리해줘"
```

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "그림판에서 애플로고 그려줘"
```

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "그림판 열어서 수박 그려줘"
```

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe main.py "그림판 열어서 바나나 그려줘"
```

사진 정리 도구는 기본적으로 `~/Pictures/ByYear/YYYY` 아래로 이미지를 이동합니다. 실행 후 `agent_runs/manifests/`에 manifest를 저장하므로, 필요하면 `undo_photo_organization` 도구로 되돌릴 수 있습니다.

로컬 도구만 빠르게 검증하려면 아래 명령을 실행합니다.

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe scripts\verify_local_tools.py
```

그림판이 실제로 열리는 것까지 확인하려면 `--open-paint`를 붙입니다.

```powershell
C:\Users\jh902\anaconda3\envs\torch_p3.8\python.exe scripts\verify_local_tools.py --open-paint
```

## 구성

- `General Assistant`: 기본 라우터 에이전트
- `Coding_Agent`: 파이썬 구현, 디버깅, 리팩터링 담당
- `Planning_Agent`: 목표를 실행 계획으로 정리
- `calculate`: 안전한 산술 계산 도구
- `get_current_time`: IANA timezone 기준 현재 시간 도구
- `organize_pictures_by_year`: 사진/이미지를 연도별 폴더로 정리
- `undo_photo_organization`: manifest 기반 사진 정리 되돌리기
- `draw_in_paint`: 설명을 바탕으로 간단한 이미지를 만들고 Microsoft Paint에서 열기. 현재 Apple-style 로고, 수박, 바나나 렌더러를 지원하고, 미지원 요청은 깨진 텍스트 대신 중립 placeholder 이미지로 fallback한다.

## 권한 모델

현재 이 프로젝트에는 OpenClaw식 Gateway 권한 계층이 없습니다. 로컬 도구는 `main.py`를 실행한 Windows 사용자 계정의 파일 권한으로 동작합니다. 따라서 사진 정리도 별도 관리자 권한을 얻은 것이 아니라, 현재 사용자가 접근 가능한 폴더에서 Python 프로세스가 `shutil.move`를 실행한 것입니다.

외부 메신저, 웹훅, 원격 실행으로 확장하기 전에는 allowlist, 승인 프롬프트, dry-run, 감사 로그, 위험 경로 차단 같은 Gateway/permission 계층을 추가해야 합니다.

## 실행 기록

모든 단발 실행과 대화형 입력은 `agent_runs/agent.db`의 `runs` 테이블에 저장됩니다. 이 기록은 나중에 self-improvement, reward 평가, 실패 분석의 기반 데이터로 사용할 예정입니다.
