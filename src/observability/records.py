"""실행 한 건을 UTF-8 JSON으로 보존한다. 같은 run_id 파일은 덮어쓰지 않는다."""

import re
from pathlib import Path

from src.contracts import RunRecord


class RunRecorder:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    def write(self, record: RunRecord) -> Path:
        """원본 실행 기록을 독점 생성하고 저장 경로를 반환한다."""
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", record.run_id):
            raise ValueError("run_id는 경로 구분자가 없는 실행 식별자여야 합니다.")
        if (
            record.response.run_id != record.run_id
            or record.response.request_id != record.request_id
            or record.request.request_id != record.request_id
        ):
            raise ValueError("실행 기록과 요청/응답의 식별자가 일치해야 합니다.")

        # 직렬화에 실패한 빈 파일을 만들지 않도록 파일을 열기 전에 JSON을 준비한다.
        payload = record.model_dump_json(indent=2) + "\n"
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{record.run_id}.json"
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
        return path
