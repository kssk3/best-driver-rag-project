"""비밀값을 포함하지 않는 공통 실행 설정."""

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.contracts import PipelineOptions


class RuntimeSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index_path: Path = Path("data/indexes/demo.json")
    runs_path: Path = Path("results/local/runs")
    max_document_characters: int = Field(default=20000, ge=1)
    demo_dimensions: int = Field(default=128, ge=8)
    pipeline: PipelineOptions = Field(default_factory=PipelineOptions)


def load_settings(
    path: str | Path | None = None, *, project_root: str | Path | None = None
) -> RuntimeSettings:
    """명시한 JSON 설정을 읽고 상대 데이터 경로를 프로젝트 기준으로 맞춘다.

    기본 기준은 현재 작업 폴더다. 설정 파일 주변이나 저장소에서 입력을 자동 탐색하지 않는다.
    API 키는 이 설정/실행 기록에 넣지 않고 해당 제공자의 환경변수로 전달한다.
    """
    payload = (
        {} if path is None else json.loads(Path(path).read_text(encoding="utf-8-sig"))
    )
    if not isinstance(payload, dict):
        raise ValueError("실행 설정은 JSON 객체여야 합니다.")
    settings = RuntimeSettings.model_validate(payload)
    root = Path.cwd() if project_root is None else Path(project_root)
    for name in ("index_path", "runs_path"):
        value = getattr(settings, name)
        setattr(
            settings,
            name,
            (root / value).resolve() if not value.is_absolute() else value.resolve(),
        )
    return settings
