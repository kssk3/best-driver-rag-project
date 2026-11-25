"""행정안전부 KIKmix 파일에서 서울 행정동·법정동 매핑표(CSV)를 만든다.

담당: 이명지

입력: 행정안전부 '행정기관(행정동) 및 관할구역(법정동) 변경내역' 게시물의
      jscode<기준일>.zip 안의 KIKmix.<기준일> (CP949, 공백으로 칸을 맞춘 텍스트)
출력: 구, 행정동, 행정동코드, 법정동, 법정동코드 한 줄씩 (서울특별시만)

실행 예:
    uv run --locked python -m scripts.build_dong_map \
        data/raw/mois-codes/jscode20261111/KIKmix.20261111 \
        data/reference/seoul_dong_map.csv
"""

import argparse
import csv
from pathlib import Path

SIDO = "서울특별시"
FIELDS = ["district", "admin_dong", "admin_code", "legal_dong", "legal_code"]


def parse_kikmix(path: Path) -> list[dict[str, str]]:
    """KIKmix에서 서울의 '행정동 1개 + 법정동 1개' 줄만 뽑는다.

    한 줄의 칸: 행정동코드 시도명 시군구명 읍면동명 법정동코드 동리명 생성일자 [말소일자]
    - 시도·구 자체를 뜻하는 줄은 읍면동명이 비어 칸 수가 모자라므로 건너뛴다.
    - 말소일자가 있는 줄(폐지된 동)은 현재 유효하지 않으므로 건너뛴다.
    """
    rows: list[dict[str, str]] = []
    with path.open(encoding="cp949") as file:
        next(file)  # 첫 줄은 열 이름
        for line in file:
            parts = line.split()
            if len(parts) not in (7, 8) or parts[1] != SIDO:
                continue
            if len(parts) == 8:  # 말소일자가 있음 → 폐지된 동
                continue
            admin_code, _, district, admin_dong, legal_code, legal_dong, _ = parts
            rows.append(
                {
                    "district": district,
                    "admin_dong": admin_dong,
                    "admin_code": admin_code,
                    "legal_dong": legal_dong,
                    "legal_code": legal_code,
                }
            )
    # 실행할 때마다 같은 순서가 나오도록 코드 순으로 정렬한다.
    rows.sort(key=lambda row: (row["admin_code"], row["legal_code"]))
    return rows


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("kikmix", type=Path, help="KIKmix.<기준일> 파일 경로")
    parser.add_argument("output", type=Path, help="만들 CSV 경로")
    args = parser.parse_args()

    rows = parse_kikmix(args.kikmix)
    write_csv(rows, args.output)
    admin = {(r["district"], r["admin_dong"]) for r in rows}
    legal = {(r["district"], r["legal_dong"]) for r in rows}
    print(
        f"{len(rows)}줄, 행정동 {len(admin)}개, 법정동 {len(legal)}개 → {args.output}"
    )


if __name__ == "__main__":
    main()
