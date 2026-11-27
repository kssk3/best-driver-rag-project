"""화면 껍데기: 색·폰트 CSS와 로고·소개 문구. 표시 규칙(chat.py, map.py)은 건드리지 않는다.

담당: 이승주
"""

import base64
from functools import cache
from pathlib import Path

import streamlit as st

HERE = Path(__file__).parent
BRAND_DIR = HERE.parent.parent / "assets" / "brand"
HERO_IMAGE = BRAND_DIR / "dang-beoni-hero.webp"
LOGO_IMAGE = BRAND_DIR / "dang-beoni-head-cutout.png"
AVATAR_IMAGE = BRAND_DIR / "dang-beoni-chat-avatar.png"

HERO_HTML = """
<div class="hero-copy">
  <h2>헷갈리는 분리배출,<br><em>‘분리당’</em>에 물어보세요.</h2>
  <p>서울시 공식 문서 근거로, 우리 동네 기준에 맞춰 알려드립니다.</p>
</div>
"""

FOOTER_HTML = """
<div class="foot">지원 지역: 서대문구 · 송파구 / 서울시 공식 문서 기반 · 실제 배출은 해당 구청 안내를 확인하세요.<br>데모 화면입니다. 아래의 검증·비교 대시보드는 개발·검증용으로 항상 표시됩니다.</div>
"""


def inject_theme() -> None:
    css = (HERE / "theme.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


@cache
def _data_uri(path: Path) -> str:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    mime = "image/webp" if path.suffix == ".webp" else "image/png"
    return f"data:{mime};base64,{data}"


def hero_html() -> str:
    # st.image는 움직이는 WebP를 정지 PNG로 바꿔 버리므로 img 태그로 직접 넣는다.
    return f'<img class="hero-img" src="{_data_uri(HERO_IMAGE)}" alt="분리당 마스코트 당번이">'


def brand_html() -> str:
    # 누르면 주소를 다시 열어 첫 화면(랜딩)으로 돌아간다.
    return (
        f'<a class="brand" href="./" target="_self">'
        f'<img src="{_data_uri(LOGO_IMAGE)}" alt=""><b>분리당</b></a>'
    )


def avatar_html() -> str:
    # 답변 말풍선 왼쪽의 너구리 머리(좌우 반전해서 말풍선 쪽을 바라본다).
    return f'<img class="avatar" src="{_data_uri(AVATAR_IMAGE)}" alt="">'
