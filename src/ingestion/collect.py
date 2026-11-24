"""설정된 자치법규를 수집한다. import만으로 네트워크를 사용하지 않는다. 실행 진입점은 scripts.collect다."""

# 1. 필요한 도구
import hashlib  # 원본 해시
import json  # JSON 읽기·저장
import logging  # 실행 로그
import time  # 요청 간격·시간 측정
import xml.etree.ElementTree as ET  # XML 읽기
from pathlib import Path  # 파일 경로
from urllib.error import URLError  # 접속 오류

# 요청 주소 구성·첨부 링크 분석
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import urlopen  # API 요청

from src.ingestion.source_review import validate_review  # 검토 기록 검사

# parse_qs: 쿼리에서 첨부번호 flSeq 추출
# urlencode: 요청 항목을 URL 쿼리 문자열로 변환
# urljoin: 기준 주소와 첨부 링크 결합
# urlparse: URL의 경로·쿼리 분리

# 공통 API 주소. 대상 문서·저장 위치는 설정 파일에서 지정
BASE_URL = "https://www.law.go.kr"
LOGGER = logging.getLogger(__name__)


# 2. 문서명 공백 정리
def normalize_title(text: str) -> str:
    return "".join(text.split())


# 3. 수집 설정 확인
def read_config(path: Path) -> dict:
    """문서명과 안전한 로컬 ID를 검증한다. 경로는 설정 파일 기준이다."""
    config = json.loads(path.read_text(encoding="utf-8"))
    targets = config.get("targets")
    if not isinstance(targets, list) or not targets:
        raise ValueError("targets에 수집할 문서를 적어주세요.")
    # 폴더명으로 사용할 ID의 중복·허용 문자 확인
    ids = set()
    for target in targets:
        document_id = target.get("document_id", "")
        if (
            not document_id
            or not isinstance(document_id, str)
            or any(
                c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in document_id
            )
            or document_id in ids
        ):
            raise ValueError(
                "document_id는 중복 없는 영어 소문자·숫자·밑줄·하이픈이어야 해요."
            )
        ids.add(document_id)
        for field in ("title", "district"):
            if not isinstance(target.get(field), str) or not target[field].strip():
                raise ValueError(f"{document_id}: {field}가 필요해요.")
    for field, default in (("timeout_seconds", 15), ("interval_seconds", 0.5)):
        value = config.get(field, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{field}는 양수여야 해요.")
        config[field] = value
    output = config.get("output_dir", "law_runs")
    if not isinstance(output, str) or not output:
        raise ValueError("output_dir가 필요해요.")
    # 설정 파일 기준 저장 경로 계산
    config["output_path"] = (path.parent / output).resolve()
    return config


# 4. 이용조건 검토 확인
def check_reviews(config: dict) -> list[tuple[dict, str]]:
    """API 전체 검토와 문서별 검토·버전 범위를 확인한다."""
    # API 미승인 시 전체 중단, 문서 미승인 시 해당 문서 보류
    validate_review(config.get("api_access", {}))
    decisions = []
    for target in config["targets"]:
        try:
            validate_review(target.get("review", {}))
            if not str(target.get("reviewed_mst", "")).isdigit():
                raise ValueError("검토한 버전 reviewed_mst가 필요해요.")
            decisions.append((target, ""))
        except (ValueError, TypeError, AttributeError):
            decisions.append((target, "문서 이용조건·검토 기한·reviewed_mst 확인 필요"))
    return decisions


# 5. API 요청과 XML 응답
class LawClient:
    def __init__(self, oc: str, timeout_seconds: float, interval_seconds: float):
        self.oc = oc
        self.timeout_seconds = timeout_seconds
        self.interval_seconds = interval_seconds
        self.last_request_at = None

    def fetch(self, endpoint: str, **params) -> tuple[bytes, ET.Element]:
        """요청 URL·인증값은 로그나 오류에 남기지 않는다."""
        if endpoint not in {"lawSearch", "lawService"}:
            raise ValueError("지원하지 않는 API 기능이에요.")
        # 요청 간격 유지
        if self.last_request_at is not None:
            remaining = self.interval_seconds - (
                time.monotonic() - self.last_request_at
            )
            if remaining > 0:
                time.sleep(remaining)
        query = urlencode({"OC": self.oc, "type": "XML", **params})
        self.last_request_at = time.monotonic()
        try:
            with urlopen(
                f"{BASE_URL}/DRF/{endpoint}.do?{query}", timeout=self.timeout_seconds
            ) as response:
                raw = response.read()
            # 원본 데이터·파싱한 XML 반환
            return raw, ET.fromstring(raw)
        except (URLError, OSError, ET.ParseError, ValueError):
            raise RuntimeError(f"{endpoint}: 요청 또는 XML 읽기 실패") from None


# 6. 문서 검색과 선별
def find_document(client: LawClient, title: str, folder: Path) -> ET.Element:
    """검색 페이지 전체에서 정확히 일치하는 일련번호 한 개만 선택한다."""
    page = 1
    matches = {}
    while True:
        raw, root = client.fetch(
            "lawSearch",
            target="ordin",
            nw=1,
            search=1,
            query=title,
            display=100,
            page=page,
        )
        count = root.findtext(".//totalCnt", "").strip()
        if not count.isdigit():
            raise ValueError("정상 검색 건수 항목이 없어요.")
        (folder / f"search_{page}.xml").write_bytes(raw)
        rows = [node for node in root.iter() if node.findtext("자치법규일련번호")]
        for row in rows:
            if normalize_title(row.findtext("자치법규명", "")) == normalize_title(
                title
            ):
                matches[row.findtext("자치법규일련번호").strip()] = row
        # 마지막 페이지 처리 후 종료
        if page * 100 >= int(count):
            break
        if not rows:
            raise ValueError("검색 결과가 남았지만 페이지가 비어 있어요.")
        page += 1
    # 일치하는 문서 한 건만 선택
    if len(matches) != 1:
        raise ValueError(f"이름이 일치하는 버전이 {len(matches)}개예요.")
    return next(iter(matches.values()))


# 7. 본문 저장과 첨부 링크 수집
def collect_document(client: LawClient, target: dict, folder: Path) -> dict:
    """본문을 저장하고 본문 XML에 포함된 첨부 목록을 기록한다. 다운로드는 하지 않는다."""
    folder.mkdir()
    row = find_document(client, target["title"], folder)
    mst = row.findtext("자치법규일련번호").strip()
    # 검토한 MST와 불일치 시 중단
    if mst != str(target["reviewed_mst"]):
        raise ValueError("검색된 MST가 검토한 버전과 달라요. 재검토가 필요해요.")
    raw, root = client.fetch("lawService", target="ordin", MST=mst)
    titles = [node.text or "" for node in root.iter("자치법규명")]
    if not any(normalize_title(t) == normalize_title(target["title"]) for t in titles):
        raise ValueError("본문 문서명이 요청한 이름과 달라요.")
    (folder / "body.xml").write_bytes(raw)
    # 첨부 링크만 기록. 다운로드 제외
    attachments = []
    for item in root.findall("./별표/별표단위"):
        link = item.findtext("별표첨부파일명", "").strip()
        attachment_title = item.findtext("별표제목", "")
        attachment_id = parse_qs(urlparse(link).query).get("flSeq", [""])[0]
        attachments.append(
            {
                "parent_mst": mst,
                "attachment_id": attachment_id,
                "annex_key": item.get("별표키", ""),
                "title": attachment_title,
                "source_url": urljoin(BASE_URL, link) if link else "",
                "content_present": bool(item.findtext("별표내용", "").strip()),
                "deleted_marker": "삭제" in attachment_title,
                "collection_status": "link_only" if link else "link_missing",
                "usage_status": "unreviewed",
            }
        )
    # 출처·해시·검토 기록 보존
    return {
        "document_id": target["document_id"],
        "title": target["title"],
        "district": target["district"],
        "mst": mst,
        "effective_date": row.findtext("시행일자", ""),
        "source_url": f"{BASE_URL}/LSW/ordinInfoP.do?ordinSeq={mst}",
        "raw_path": f"{target['document_id']}/body.xml",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "collection_status": "body_saved",
        "review": target["review"],
        "usage_status": "index_and_model_use_unreviewed",
        "attachments": attachments,
        "attachment_inventory_scope": "body_xml_only_not_full_annex_search",
    }
