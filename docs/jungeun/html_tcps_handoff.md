# 공통 HTML 변환 미해결 기록

## 한국어 참고사항

PR #9 병합 `dev`(`0328e8f`)를 반영한 작업 브랜치 `ae98583`에서 XML→HTML 경로를 확인했습니다.
`3fe57ca`의 JSON에는 복원된 글자 겹침 원문이 남아 있지만,
`src/ingestion/xml_adapter.py`의 `_HwpRenderer._pieces()`는 자식이 없는
`TCPSControl`의 `textlength`를 읽지 않아 같은 문자를 생략합니다.

| 대상 첨부 | TCPS 수 | 누락 코드포인트 수 | 영향 셀 | 영향 본문 문단 |
| --- | ---: | ---: | ---: | ---: |
| `2053883_154690993` 송파구 별지 | 14 | 28 | 7 | 4 |
| `2101297_160319463` 서대문구 별지 제1호서식 | 6 | 12 | 3 | 3 |
| 합계 | 20 | 40 | 10 | 7 |

각 수치는 기존 구조 XML과 현재 JSON, `xml_to_html()` 결과를 직접 대조한
결과입니다. 두 형식이 서로 다른 원본을 가리켜 생긴 차이는 아닙니다.
이 확인에서 HWP를 다시 해석하거나 원본 XML·HWP·구조 XML을 바꾸지 않았으며,
해당 원본 파일은 `3fe57ca`와 동일합니다.

### 최소 재현 예시

README의 Python 3.13 환경을 준비하고 활성화한 뒤 저장소 루트에서 실행합니다.
아래 예시는 공개 함수 `xml_to_html()`을 사용하며 파일 저장이나 외부 호출이 없습니다.

```zsh
python - <<'PY'
from src.ingestion.xml_adapter import xml_to_html

payload = "\ua289\ua298"
xml = (
    '<HwpDoc><BodyText><Paragraph><Text>앞</Text>'
    f'<TCPSControl textlength="{payload}"/>'
    '<Text>뒤</Text></Paragraph></BodyText></HwpDoc>'
)
html = xml_to_html(xml)
print("payload_preserved:", payload in html)
print("joined_without_payload:", "<p>앞뒤</p>" in html)
PY
```

현재 출력은 `payload_preserved: False`, `joined_without_payload: True`입니다.
입력의 `앞 + U+A289 U+A298 + 뒤`가 HTML에서는 `앞뒤`로 합쳐집니다.
수정 후에는 원문 코드포인트를 같은 위치와 순서로 보존해야 합니다.

### 실제 자료 재현 예시

다음 코드는 두 첨부 JSON의 원문 문자열 보존과 현재 HTML의 누락을 확인합니다.
아래의 셀·문단 수는 JSON에서 해당 코드포인트를 포함하는 위치의 수이며,
표 셀 ID와 문단 순서의 직접 대조에서도 같은 범위를 확인했습니다.

```zsh
python - <<'PY'
import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

from src.ingestion.xml_adapter import xml_to_html


class TextReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


base = Path("data/handoff/jungeun/p04-2026-11-24/processed/annex")
for key in ("2053883_154690993", "2101297_160319463"):
    xml = (base / f"{key}.xml").read_text(encoding="utf-8")
    raw_json = (base / f"{key}.json").read_text(encoding="utf-8")
    data = json.loads(raw_json)
    controls = list(ET.fromstring(xml).iter("TCPSControl"))
    payloads = [node.get("textlength", "") for node in controls]
    codepoints = set("".join(payloads))
    reader = TextReader()
    reader.feed(xml_to_html(xml))
    html_text = "".join(reader.parts)
    cells = [cell for table in data["tables"] for cell in table["cells"]]
    paragraphs = [b["text"] for b in data["blocks"] if b["type"] == "paragraph"]
    print(key, {
        "controls": len(controls),
        "payload_codepoints": sum(map(len, payloads)),
        "affected_cells": sum(bool(set(c["text"]) & codepoints) for c in cells),
        "affected_paragraphs": sum(bool(set(p) & codepoints) for p in paragraphs),
        "json_payloads_present": all(p and p in raw_json for p in payloads),
        "html_payloads_missing": all(c not in html_text for c in codepoints),
    })
PY
```

현재 출력의 수치는 위 표와 같으며 두 첨부 모두
`json_payloads_present=True`, `html_payloads_missing=True`입니다.
수정 후에는 누락 여부뿐 아니라 원래 셀·문단 안의 위치, 순서와 중복 여부까지
대조해야 합니다.

### 남은 제약과 영향 범위

HTML 경로에는 `annexes.py`의 `_text()`와 같은 원문 보존 처리가 없다. 이번 작업에서는 공통 코드를 수정하지 않았다. 자식 본문이 있으면 우선 사용하고, 없거나 공백뿐이면
`textlength`의 원문 문자열을 보존하는 정책입니다. 속성 이름과 달리 여기의 값은
길이 숫자가 아닌 BSTR 문자열입니다. 숫자 변환, 번호·글리프 추정, 원문
코드포인트 치환은 하지 않습니다. 실제 두 첨부의 JSON/HTML을 셀 ID·문단 순서·
출처·버전까지 대조하는 동등성 검사도 미해결 항목이다.

두 첨부는 `administrative_form`, `index_eligible=false`여서 현재 준비 명령의
검색 색인 대상에서 제외됩니다. 이 관측을 현재 답변 검색 전체의 문자 손상으로
확대해서 해석하지 않습니다. 원문 보존과 두 표현의 동등성에 관한 별도 문제입니다.

이번 읽기 검사에서는 로더 문서 46개, 색인 대상 HTML/JSON 청크 각각 557개를
확인했습니다. 표 수, 로딩 성공과 같은 청크 수만으로 본문·조건·삭제 구획의
동등성이 증명되지는 않습니다. HTML 어댑터 수정, 수정 후 재검사, 실제 Windows의
폰트 표시와 답변 검색 품질 검증은 이번 작업에 포함하지 않았습니다.

### 별도 참고: 별지 제목과 삭제 구획

현재 HTML의 `_ANNEX_TITLE`은 `별표` 제목만 인식합니다. 실제 두 첨부의 HTML에서
`data-section-title`은 빈 값이고 `data-deleted-section`은 `false`였습니다.
송파구의 `별지1 <삭제 2014.9.25.>`, `별지1의2 <삭제 2014.9.25.>`,
`[별지 2]`, `[별지 3]`, `[별지 4]`와 서대문구의 `[별지 제1호서식]` 제목이
구획 메타데이터로 구분되지 않는 것을 확인했습니다.

이 빈 제목·삭제 여부 상태는 TCPS가 있는 두 첨부 외에도
`2101297_160319465`, `2101297_160319467`, `2101385_160561047`,
`2101385_160561049`, `2101385_160561051`, `2101385_160561053`에서 관측했습니다.
총 8개 행정 서식의 별지 제목 문제이며, TCPS 문자 누락 범위는 위의 두 첨부입니다.

이번 PR에서는 JSON 별지 분류·삭제 구획만 정정했다. 공통 HTML의 제목·삭제 메타데이터 일치는 미해결 항목이다. 이 참고사항은 TCPS 문자
누락과 원인이 다르며, 두 서식의 현재 색인 제외 상태도 함께 고려해야 합니다.
이 문서는 전달 준비안이며 HTML 담당 코드 수정이나 외부 게시·연락은 하지 않았습니다.

## English notes

I checked the XML-to-HTML route on the working branch `ae98583`, which includes PR #9 dev `0328e8f`, after PR #9.
The JSON from `3fe57ca` preserves the restored character-composition payloads,
but `_HwpRenderer._pieces()` in `src/ingestion/xml_adapter.py` ignores
`textlength` on childless `TCPSControl` elements and omits those characters.

The table above lists the directly checked scope: 14 controls and 28 missing
codepoints across seven cells and four body paragraphs in `2053883_154690993`;
six controls and 12 codepoints across three cells and three body paragraphs in
`2101297_160319463`. The total is 20 controls, 40 codepoints, 10 cells and seven
body paragraphs. These differences come from comparing the existing structural
XML, current JSON and `xml_to_html()` output, rather than different source files.
This check did not reparse the HWP or alter original XML/HWP or structural XML;
those source files are unchanged from `3fe57ca`.

Run the shared reproduction blocks above from the repository root after preparing
and activating the README's Python 3.13 environment. They use the public
`xml_to_html()` function without file writes or external calls. The minimal
example currently prints `payload_preserved: False` and
`joined_without_payload: True`: `앞 + U+A289 U+A298 + 뒤` becomes `앞뒤`.
The fix should preserve the original codepoints in their original position and order.

The actual-data example reproduces the counts in the table. Both attachments
currently return `json_payloads_present=True` and `html_payloads_missing=True`.
Its cell and paragraph counts identify JSON locations containing those codepoints;
direct comparisons by cell ID and paragraph order confirmed the same scope.
Post-fix checks should also verify position, order and absence of duplication
within each original cell and paragraph.

A possible correction would apply the same policy as `annexes.py`'s `_text()` in the HTML
`_pieces()` method: prefer existing child content; if it is absent or whitespace
only, preserve the raw `textlength` string. Despite the attribute name, its value
here is a BSTR string rather than a numeric length. Do not convert it to a number,
infer numbered glyphs or substitute the original codepoints. An actual-data comparison is also outstanding
for of both representations by cell ID, paragraph order,
source and version.

Both affected attachments are `administrative_form` with `index_eligible=false`,
so the current preparation command excludes them from the search index. This
observation does not establish character loss throughout current answer retrieval;
it concerns source preservation and equivalence of the two representations.

The read-only check loaded 46 documents and produced 557 eligible chunks for each
format. Table counts, successful loading and equal chunk counts alone do not
establish equivalence of content, conditions or deleted sections. This task did
not modify the HTML adapter, verify a subsequent fix, test native Windows font
rendering or assess answer retrieval quality.

Separately, the HTML `_ANNEX_TITLE` currently recognizes only `별표` headings.
Both actual attachments produced an empty `data-section-title` and
`data-deleted-section=false`. Songpa's `별지1 <삭제 2014.9.25.>`,
`별지1의2 <삭제 2014.9.25.>`, `[별지 2]`, `[별지 3]` and `[별지 4]`,
and Seodaemun's `[별지 제1호서식]`, were not distinguished in section metadata.
The same empty-title/deletion state was also observed in `2101297_160319465`,
`2101297_160319467`, `2101385_160561047`, `2101385_160561049`,
`2101385_160561051` and `2101385_160561053`. This heading issue covers eight
administrative forms; TCPS character loss remains limited to the two attachments
listed in the table.
JSON form classification and deleted sections are corrected in this data change.
HTML section titles and deletion metadata still require a separate consistency check.
This has a different cause from TCPS character loss; the forms' current index
exclusion also limits its present retrieval impact. This document is a handoff
draft only; no HTML-owner code edits or external publication or messages were made.


담당자의 추가 작업을 전제하지 않는 미해결 현황 기록이다. 이번 PR에서 공통 코드를 수정하거나 다른 담당자에게 작업을 할당하지 않는다.

This records an unresolved limitation without assuming further work by Seokho. This PR neither changes the common code nor assigns a follow-up task to another owner.
