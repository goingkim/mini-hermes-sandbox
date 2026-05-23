from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parent
FONT_REGULAR = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"
PDF_PATH = ROOT / "에이전트 개발 특론_오픈클로와 헤르메스로 배우는 로컬 에이전트 입문.pdf"


PAGES = [
    {
        "title": "표지",
        "body": [
            ("title", "에이전트 개발 특론"),
            ("subtitle", "오픈클로와 헤르메스로 배우는 로컬 에이전트 입문"),
            ("space", ""),
            (
                "p",
                "이 문서는 에이전트 개발을 처음 공부하는 사람을 위한 10장짜리 입문 자료입니다. "
                "코드보다 먼저 큰 그림을 이해하는 데 초점을 둡니다.",
            ),
            (
                "p",
                "핵심 질문은 세 가지입니다. 에이전트는 챗봇과 무엇이 다른가? "
                "컴퓨터에서 실제 작업을 하려면 어떤 도구와 권한이 필요한가? "
                "OpenClaw와 Hermes는 이 문제를 어떻게 나누어 해결하는가?",
            ),
            (
                "box",
                "오늘 기억할 한 문장: 에이전트는 말을 잘하는 프로그램이 아니라, "
                "도구를 골라 쓰고 결과를 기록하며 다음 행동을 조정하는 실행 시스템이다.",
            ),
        ],
    },
    {
        "title": "1. 챗봇과 에이전트의 차이",
        "body": [
            (
                "p",
                "챗봇은 보통 질문을 읽고 답변을 씁니다. 에이전트도 답변을 쓰지만, 거기서 끝나지 않습니다. "
                "필요하면 파일을 읽고, 프로그램을 실행하고, 웹을 검색하고, 결과를 다시 판단합니다.",
            ),
            ("h", "쉬운 비유"),
            (
                "bullet",
                "챗봇: 요리법을 설명해 주는 사람.",
            ),
            (
                "bullet",
                "에이전트: 냉장고를 확인하고, 부족한 재료를 주문하고, 조리 순서를 진행하는 주방 보조.",
            ),
            ("h", "에이전트의 기본 반복"),
            ("bullet", "사용자의 목표를 이해한다."),
            ("bullet", "필요한 도구를 고른다."),
            ("bullet", "도구를 실행한다."),
            ("bullet", "실행 결과를 읽고 다음 행동을 정한다."),
            (
                "p",
                "그래서 에이전트 개발의 핵심은 모델만 고르는 것이 아닙니다. "
                "도구, 권한, 기록, 검증, 실패 복구를 함께 설계해야 합니다.",
            ),
        ],
    },
    {
        "title": "2. 도구란 무엇인가",
        "body": [
            (
                "p",
                "도구는 모델이 직접 할 수 없는 일을 대신 수행하는 함수 또는 실행 인터페이스입니다. "
                "예를 들어 사진 파일을 이동하는 일, 브라우저를 여는 일, 현재 시간을 확인하는 일은 모두 도구로 만들 수 있습니다.",
            ),
            ("h", "좋은 도구의 조건"),
            ("bullet", "입력과 출력이 명확하다."),
            ("bullet", "실패했을 때 이유를 설명한다."),
            ("bullet", "한 가지 안정적인 능력을 제공한다."),
            ("bullet", "위험한 행동은 바로 실행하지 않고 승인 또는 제한을 둔다."),
            (
                "p",
                "중요한 점은 요청마다 새 도구를 만드는 것이 아니라는 것입니다. "
                "`바나나 그리기`, `사과 그리기`, `수박 그리기`를 각각 도구로 만들면 금방 관리할 수 없게 됩니다.",
            ),
            (
                "box",
                "더 나은 방향: `그림을 생성한다`라는 범용 도구를 만들고, "
                "그 안에서 이미지 생성 모델이나 도형 계획 렌더러를 사용한다.",
            ),
        ],
    },
    {
        "title": "3. 스킬은 도구와 다르다",
        "body": [
            (
                "p",
                "도구는 실제 행동을 수행합니다. 스킬은 도구를 언제, 어떤 순서로, 어떤 주의사항과 함께 쓸지 알려주는 절차 지식입니다.",
            ),
            ("h", "예시: 사진 정리 스킬"),
            ("bullet", "먼저 대상 폴더가 맞는지 확인한다."),
            ("bullet", "이미지를 EXIF 날짜 또는 수정 시간 기준으로 분류한다."),
            ("bullet", "이동하기 전에 어떤 파일이 어디로 갈지 계획을 만든다."),
            ("bullet", "실행 후 manifest를 저장해 되돌릴 수 있게 한다."),
            (
                "p",
                "OpenClaw와 Hermes 계열 시스템은 이런 절차 지식을 `SKILL.md` 같은 파일로 저장합니다. "
                "모델은 스킬을 읽고 도구를 더 안정적으로 사용합니다.",
            ),
            (
                "box",
                "짧게 말하면: Tool은 손이고, Skill은 작업 매뉴얼이다.",
            ),
        ],
    },
    {
        "title": "4. Gateway는 권한을 얻는 장치가 아니다",
        "body": [
            (
                "p",
                "Gateway라는 단어 때문에 컴퓨터 권한을 새로 얻는 장치처럼 느껴질 수 있습니다. "
                "하지만 핵심은 권한 획득이 아니라 권한 제어입니다.",
            ),
            ("h", "Gateway가 하는 일"),
            ("bullet", "CLI, Telegram, Discord, 웹훅 같은 여러 입력 채널을 받는다."),
            ("bullet", "요청을 어떤 에이전트에게 보낼지 라우팅한다."),
            ("bullet", "어떤 도구를 허용할지 정책을 확인한다."),
            ("bullet", "위험한 실행은 승인 요청을 만들거나 차단한다."),
            ("bullet", "누가 무엇을 실행했는지 기록한다."),
            (
                "p",
                "실제 파일 이동이나 프로그램 실행 권한은 결국 그 프로세스를 실행한 OS 사용자 계정에서 나옵니다. "
                "따라서 Gateway는 더 큰 권한을 주는 문이 아니라, 이미 가진 권한을 안전하게 쓰게 하는 관제소에 가깝습니다.",
            ),
        ],
    },
    {
        "title": "5. OpenClaw를 아주 쉽게 보면",
        "body": [
            (
                "p",
                "OpenClaw는 로컬 우선 개인 AI 비서를 목표로 합니다. 사용자는 여러 채팅 채널에서 요청을 보내고, "
                "OpenClaw는 Gateway를 통해 도구 실행과 자동화를 관리합니다.",
            ),
            ("h", "OpenClaw의 세 층"),
            ("bullet", "Tools: exec, browser, web_search, read, write, edit 같은 실제 실행 능력."),
            ("bullet", "Skills: 도구를 잘 쓰는 방법을 알려주는 SKILL.md 기반 절차 지식."),
            ("bullet", "Plugins: 도구, 스킬, 채널, 모델 제공자 등을 묶어 배포하는 패키지."),
            (
                "p",
                "OpenClaw 문서에서 중요한 포인트는 도구와 스킬을 구분한다는 점입니다. "
                "모든 사용자 요청을 새 함수로 만들지 않고, 범용 도구와 재사용 가능한 스킬을 조합합니다.",
            ),
            (
                "box",
                "우리 프로젝트도 이 방향을 따라야 한다. 함수 무한 증식이 아니라, 적은 수의 강한 도구와 좋은 스킬을 만든다.",
            ),
        ],
    },
    {
        "title": "6. Hermes를 아주 쉽게 보면",
        "body": [
            (
                "p",
                "Hermes Agent는 '사용하면서 성장하는 에이전트'를 강조합니다. "
                "도구를 실행하고, 경험에서 스킬을 만들고, 메모리에 중요한 사실을 저장하며, 과거 대화를 검색합니다.",
            ),
            ("h", "Hermes의 중요한 구성"),
            ("bullet", "Tools & Toolsets: terminal, file, browser, image_generate, memory 같은 도구 묶음."),
            ("bullet", "Skills: 성공한 작업 절차를 저장하고 다음에 다시 쓰는 절차 기억."),
            ("bullet", "Memory: 사용자 선호, 프로젝트 정보, 배운 사실을 제한된 크기로 저장."),
            ("bullet", "Terminal backend: local, docker, ssh, cloud sandbox 등 실행 위치를 선택."),
            (
                "p",
                "Hermes의 Tool Gateway는 로컬 컴퓨터 권한을 얻는 장치가 아닙니다. "
                "웹 검색, 이미지 생성, TTS, 클라우드 브라우저 같은 외부 도구 API를 Nous 인프라로 중계하는 기능입니다.",
            ),
        ],
    },
    {
        "title": "7. 권한과 보안을 쉽게 이해하기",
        "body": [
            (
                "p",
                "에이전트가 실제 컴퓨터 작업을 할 수 있게 되면 편리하지만 위험도 커집니다. "
                "잘못된 프롬프트, 모델 착각, 악성 웹페이지, 잘못 만든 스킬이 파일을 망가뜨릴 수 있습니다.",
            ),
            ("h", "권한을 생각하는 세 단계"),
            ("bullet", "현재 사용자 권한: Python을 실행한 Windows 계정이 접근할 수 있는 범위."),
            ("bullet", "앱 내부 정책: 어떤 도구를 허용하고, 어떤 작업은 승인받을지 정하는 규칙."),
            ("bullet", "OS 격리: Docker, 별도 사용자 계정, VM처럼 실제로 접근 범위를 줄이는 방법."),
            (
                "p",
                "Hermes 보안 문서는 강하게 말합니다. 적대적인 LLM에 대한 진짜 경계는 OS 수준 격리입니다. "
                "앱 내부 allowlist와 승인창은 도움이 되지만 완전한 감옥은 아닙니다.",
            ),
            (
                "box",
                "처음 만들 때의 안전 원칙: 삭제보다 이동, 이동보다 복사, 실행보다 계획 표시가 안전하다.",
            ),
        ],
    },
    {
        "title": "8. 우리 프로젝트와 내일부터의 로드맵",
        "body": [
            (
                "p",
                "현재 프로젝트는 작은 로컬 에이전트입니다. `main.py`가 모델을 호출하고, 모델이 필요하면 Python 함수 도구를 호출합니다.",
            ),
            ("h", "현재 가능한 일"),
            ("bullet", "DeepSeek `deepseek-chat` 모델로 대화하고, 사진을 연도별로 정리한다."),
            ("bullet", "manifest를 저장해 되돌릴 근거를 남기고, SQLite에 실행 기록을 저장한다."),
            ("bullet", "간단한 이미지를 생성하고 Microsoft Paint로 연다."),
            ("h", "현재 부족한 점"),
            ("bullet", "Gateway-lite가 없어 도구 실행 정책이 단순하다."),
            ("bullet", "그림 도구가 아직 범용 이미지 생성 시스템이 아니다."),
            ("bullet", "메모리와 스킬이 자동으로 성장하는 구조는 아직 시작 단계다."),
            ("h", "내일 읽고 볼 순서"),
            ("bullet", "`main.py`: 모델 설정과 tool 등록 위치를 찾는다."),
            ("bullet", "`agent_tools.py`: 사진 정리와 그림판 도구가 실제로 무엇을 하는지 본다."),
            ("bullet", "`trace_store.py`: 실행 기록이 어떻게 저장되는지 본다."),
            ("bullet", "그 다음 Gateway-lite의 승인, 감사 로그, 위험도 정책을 설계한다."),
        ],
    },
    {
        "title": "9. 핵심 요약과 참고자료",
        "body": [
            ("h", "핵심 요약"),
            ("bullet", "에이전트는 대화 모델 + 도구 실행 + 기록 + 판단 루프다."),
            ("bullet", "도구는 실제 행동이고, 스킬은 도구 사용 매뉴얼이다."),
            ("bullet", "Gateway는 권한을 새로 얻는 장치가 아니라 권한을 라우팅하고 통제하는 계층이다."),
            ("bullet", "실제 OS 권한은 프로세스를 실행한 사용자 계정 또는 sandbox backend에서 결정된다."),
            ("bullet", "OpenClaw와 Hermes 모두 요청마다 함수를 무한히 늘리는 방향이 아니다."),
            ("bullet", "우리 프로젝트의 다음 목표는 Gateway-lite, 범용 그림 도구, 스킬/메모리의 최소 버전이다."),
            ("h", "참고자료"),
            ("source", "OpenClaw Tools and Plugins: https://docs.openclaw.ai/tools"),
            ("source", "OpenClaw Skills: https://docs.openclaw.ai/tools/skills"),
            ("source", "OpenClaw Gateway: https://docs.openclaw.ai/gateway"),
            ("source", "Hermes Tools & Toolsets: https://hermes-agent.nousresearch.com/docs/user-guide/features/tools/"),
            ("source", "Hermes Tool Gateway: https://hermes-agent.nousresearch.com/docs/user-guide/features/tool-gateway"),
            ("source", "Hermes Security Policy: https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md"),
        ],
    },
]


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    register_fonts()

    c = canvas.Canvas(str(PDF_PATH), pagesize=A4)
    width, height = A4
    for index, page in enumerate(PAGES, start=1):
        draw_page(c, width, height, page["title"], page["body"], index, len(PAGES))
        c.showPage()
    c.save()
    print(PDF_PATH)


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Malgun", FONT_REGULAR))
    pdfmetrics.registerFont(TTFont("MalgunBold", FONT_BOLD))


def draw_page(c: canvas.Canvas, width: float, height: float, title: str, body: list[tuple[str, str]], page_no: int, page_count: int) -> None:
    margin_x = 46
    y = height - 48

    c.setFillColor(colors.HexColor("#1f2933"))
    c.setFont("MalgunBold", 15)
    c.drawString(margin_x, y, title)
    c.setStrokeColor(colors.HexColor("#d0d7de"))
    c.line(margin_x, y - 10, width - margin_x, y - 10)
    y -= 36

    for kind, text in body:
        if kind == "space":
            y -= 18
            continue
        if kind == "title":
            y = draw_wrapped(c, text, margin_x, y, width - margin_x * 2, "MalgunBold", 26, 35, colors.HexColor("#0f172a"))
            y -= 2
            continue
        if kind == "subtitle":
            y = draw_wrapped(c, text, margin_x, y, width - margin_x * 2, "Malgun", 14, 22, colors.HexColor("#475569"))
            y -= 18
            continue
        if kind == "h":
            y -= 5
            y = draw_wrapped(c, text, margin_x, y, width - margin_x * 2, "MalgunBold", 12.2, 18, colors.HexColor("#0f172a"))
            y -= 3
            continue
        if kind == "bullet":
            y = draw_bullet(c, text, margin_x, y, width - margin_x * 2)
            y -= 2
            continue
        if kind == "box":
            y = draw_box(c, text, margin_x, y, width - margin_x * 2)
            y -= 8
            continue
        if kind == "source":
            y = draw_wrapped(c, text, margin_x + 10, y, width - margin_x * 2 - 10, "Malgun", 8.8, 13, colors.HexColor("#334155"))
            y -= 2
            continue
        y = draw_wrapped(c, text, margin_x, y, width - margin_x * 2, "Malgun", 10.7, 16, colors.HexColor("#1f2933"))
        y -= 9

    if y < 58:
        raise RuntimeError(f"Page {page_no} content overflowed. Remaining y={y}")

    c.setStrokeColor(colors.HexColor("#e5e7eb"))
    c.line(margin_x, 38, width - margin_x, 38)
    c.setFillColor(colors.HexColor("#64748b"))
    c.setFont("Malgun", 8.5)
    c.drawString(margin_x, 24, "에이전트 개발 특론")
    c.drawRightString(width - margin_x, 24, f"{page_no} / {page_count}")


def draw_bullet(c: canvas.Canvas, text: str, x: float, y: float, max_width: float) -> float:
    c.setFillColor(colors.HexColor("#334155"))
    c.setFont("MalgunBold", 10.5)
    c.drawString(x + 3, y, "-")
    return draw_wrapped(c, text, x + 18, y, max_width - 18, "Malgun", 10.3, 15.3, colors.HexColor("#1f2933"))


def draw_box(c: canvas.Canvas, text: str, x: float, y: float, max_width: float) -> float:
    lines = wrap_text(text, "Malgun", 10.2, max_width - 26)
    box_height = len(lines) * 15 + 20
    top = y + 8
    c.setFillColor(colors.HexColor("#f8fafc"))
    c.setStrokeColor(colors.HexColor("#cbd5e1"))
    c.roundRect(x, top - box_height, max_width, box_height, 6, fill=1, stroke=1)
    c.setFillColor(colors.HexColor("#0f172a"))
    c.setFont("Malgun", 10.2)
    line_y = top - 20
    for line in lines:
        c.drawString(x + 13, line_y, line)
        line_y -= 15
    return top - box_height - 8


def draw_wrapped(c: canvas.Canvas, text: str, x: float, y: float, max_width: float, font: str, size: float, leading: float, color: colors.Color) -> float:
    c.setFillColor(color)
    c.setFont(font, size)
    for line in wrap_text(text, font, size, max_width):
        c.drawString(x, y, line)
        y -= leading
    return y


def wrap_text(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
        if pdfmetrics.stringWidth(word, font, size) <= max_width:
            current = word
        else:
            for piece in split_long_word(word, font, size, max_width):
                if current:
                    lines.append(current)
                    current = ""
                if pdfmetrics.stringWidth(piece, font, size) <= max_width:
                    lines.append(piece)
                else:
                    current = piece
    if current:
        lines.append(current)
    return lines


def split_long_word(word: str, font: str, size: float, max_width: float) -> list[str]:
    pieces: list[str] = []
    current = ""
    for char in word:
        candidate = current + char
        if pdfmetrics.stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = char
    if current:
        pieces.append(current)
    return pieces


if __name__ == "__main__":
    main()
