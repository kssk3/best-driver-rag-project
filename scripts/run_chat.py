"""실행 모드로 Streamlit 화면을 띄운다. 팀 색인이 없으면 먼저 만든다.

사용: uv run --locked --env-file .env python -m scripts.run_chat [--settings 설정 파일]
색인을 새로 만들 때만 OpenAI 임베딩을 호출한다(약 543청크). 있으면 호출하지 않는다.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = "data/handoff/jungeun/ordinance-handoff-2026-11-24"
EMBEDDING_MODEL = "text-embedding-3-small"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default="configs/team-c-rewrite-chat.json")
    args = parser.parse_args(argv)

    index = (
        ROOT
        / json.loads((ROOT / args.settings).read_text(encoding="utf-8"))["index_path"]
    )
    if not index.exists():
        # shortcut: prepare_data의 출력 이름(index-json.json)만 자동 생성한다, 다른 색인은 직접 준비한다.
        if index.name != "index-json.json":
            sys.exit(f"색인 파일이 없습니다: {index}\n직접 준비한 뒤 다시 실행하세요.")
        if not os.environ.get("OPENAI_API_KEY"):
            sys.exit(
                f"색인 파일이 없고 OPENAI_API_KEY도 없습니다: {index}\n"
                "`uv run --locked --env-file .env python -m scripts.run_chat`로 실행하세요."
            )
        print(f"색인이 없어 새로 만듭니다(임베딩 호출 발생): {index}", flush=True)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.prepare_data",
                "--bundle",
                BUNDLE,
                "--version",
                "v1",
                "--output-dir",
                str(index.parent),
                "--openai-model",
                EMBEDDING_MODEL,
            ],
            cwd=ROOT,
            check=True,
        )
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app.py"],
        cwd=ROOT,
        env={**os.environ, "RAG_CHAT_SETTINGS": args.settings},
        check=True,
    )


if __name__ == "__main__":
    main()
