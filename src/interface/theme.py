"""화면 껍데기: 색·폰트 CSS와 로고·소개 문구. 표시 규칙(chat.py, map.py)은 건드리지 않는다.

담당: 이승주
"""

import base64
from functools import cache
from pathlib import Path

import streamlit as st

HERE = Path(__file__).parent
BRAND_DIR = HERE.parent.parent / "assets" / "brand"
HERO_IMAGE = BRAND_DIR / "dang-beoni-cutout.png"
LOGO_IMAGE = BRAND_DIR / "dang-beoni-head-cutout.png"

HERO_HTML = """
<div class="hero-copy">
  <h2>헷갈리는 분리배출,<br><em>‘분리당’</em>에 물어보세요.</h2>
  <p>서울시 공식 문서 근거로, 우리 동네 기준에 맞춰 알려드립니다.</p>
</div>
"""

SECTIONS_HTML = """
<section class="info">
  <h3>이렇게 도와드려요.</h3>
  <p class="sub">답만 주지 않고, 어디서 나온 내용인지 같이 보여줘요.</p>
  <div class="cols">
    <div class="card"><div class="ico">♻️</div><h4>분리배출 방법</h4><p>품목을 말하면 어떻게 비우고, 무엇과 같이 버릴지 알려줘요.</p></div>
    <div class="card"><div class="ico">📄</div><h4>근거 출처 표시</h4><p>답변마다 문서 이름·위치·버전을 함께 보여줘요.</p></div>
    <div class="card"><div class="ico">📍</div><h4>가까운 수거 장소</h4><p>수거함·센터 주소를 지도 링크와 함께 안내해요.</p></div>
  </div>
</section>
<section class="info">
  <h3>이용 방법</h3>
  <p class="sub">로그인 없이 바로 이용하실 수 있습니다.</p>
  <div class="steps">
    <div class="step"><b>지역 고르기</b><br><span>구마다 배출 기준이 달라요.</span></div>
    <div class="step"><b>물건 물어보기</b><br><span>말하듯이 적으면 돼요.</span></div>
    <div class="step"><b>근거와 함께 확인</b><br><span>모자라면 되물어봐요.</span></div>
  </div>
</section>
"""

FOOTER_HTML = """
<div class="foot">지원 지역: 서대문구 · 송파구 / 합성 데모 데이터 기반 · 실제 배출은 해당 구청 안내를 확인하세요.<br>내부 데모 화면입니다. 오른쪽의 검증·비교 패널은 개발·검증용으로 항상 표시됩니다.</div>
"""


def inject_theme() -> None:
    css = (HERE / "theme.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")


@cache
def _logo_uri() -> str:
    data = base64.b64encode(LOGO_IMAGE.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def brand_html() -> str:
    return f'<div class="brand"><img src="{_logo_uri()}" alt=""><b>분리당</b></div>'


def avatar_html() -> str:
    return f'<img class="avatar" src="{_logo_uri()}" alt="">'
