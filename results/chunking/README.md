# 청킹 기준선

청킹 결과의 현황(청크 수, 구별·종류별 개수, 길이 통계, 결과 지문)을 청킹 버전(`chunking_version`)마다 한 줄씩 쌓아 두는 곳이다. 청킹을 바꾸기 전과 후를 같은 기준으로 비교하려는 기록이며, 검색 품질을 말해 주는 값은 아니다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `chunk_stats.csv` | 버전·형식(HTML/JSON)마다 한 줄. 열은 `scripts/chunk_stats.py`의 `COLUMNS`다. `chunks_sha256`은 청크의 모든 필드(제목, 범위, 구 목록, 조건 포함)를 해시한 지문이다. |

## 쌓는 법

```bash
uv run --locked python -m scripts.prepare_data --bundle data/handoff/jungeun/ordinance-handoff-2026-11-24 --version v1 --output-dir results/local/<새 폴더>
uv run --locked python -m scripts.chunk_stats --chunks results/local/<새 폴더>/chunks-html.json --csv results/chunking/chunk_stats.csv
uv run --locked python -m scripts.chunk_stats --chunks results/local/<새 폴더>/chunks-json.json --csv results/chunking/chunk_stats.csv
```

버전과 형식은 청크에서 읽는다. 같은 파일 안에 여러 값이 섞여 있거나 같은 (버전, 형식) 줄이 이미 있으면 거부한다.

## 규칙

1. 청킹 결과가 달라지는 변경(코드뿐 아니라 인계 번들 변경 포함)은 `src/ingestion/preprocessed_chunking.py`의 `chunking_version`을 올린다. 이름이 같은데 결과가 다르면 예전 평가 기록과 새 기록을 구별할 수 없다.
2. 새 버전은 이 CSV에 줄을 **추가**한다. 이미 있는 줄은 지우지도 고치지도 않는다.
3. 추가한 줄을 `tests/unit/chunking/test_chunking_baseline.py`의 `RELEASED_CSV`에도 그대로 붙여 넣는다. 이 테스트가 (a) 현재 청킹 결과가 CSV의 같은 버전 줄과 같은지, (b) 기록된 줄의 행 전체가 바뀌지 않았는지, (c) 같은 (버전, 형식) 줄이 중복되지 않았는지 확인한다. 한 PR에서 CSV와 `RELEASED_CSV`를 함께 고치면 통과하므로 최종 방어는 코드 리뷰다.
4. `chunk_id`가 모두 바뀌므로 근거 매핑(`tests/fixtures/interface/screen_check_set/chunk_id_map.csv`, `eval/dev.json`의 `allowed_chunk_ids` 등)과 색인을 갱신하고 영향받는 팀원에게 알린다.

## 같은 이름이 가리킨 두 상태 (내력)

`preprocessed-v2-row-v1`은 청킹 코드가 한 번 바뀌었는데 버전 이름을 올리지 않아 서로 다른 두 청크 집합을 가리킨다. 현재 CSV의 줄은 두 번째 상태이고, 첫 번째 상태의 값은 아래에 남긴다.

| 상태 | 청크 수(HTML / JSON) | `chunks_sha256` (HTML) | `chunks_sha256` (JSON) | 기준 |
| --- | --- | --- | --- | --- |
| 첫 번째 | 557 / 557 | `fefce555bb12db63f51e02ea46ae4e24a3e22f9f86902d2c9bae059df6790864` | `5ed2e04f75c2e9b2bac6da9b7782d29ea8678ffc651f1149184eb30d6d18942c` | 별표 이어지는 행 복원(`f4fa397`, PR #29) 이전. 이 상태의 기준선 CSV는 커밋 `3ca1707`(PR #28 병합)의 `results/chunking/chunk_stats.csv`에 있다(지문 열은 없었다). |
| 두 번째(현재) | 543 / 543 | `d1e90cbce3b1c8619ca107325bb731f7ccc7cc42aaef93375e5a0f393bf1ecc8` | `93af4ecd43ea1764da2b1dd52e94dcf81c4a32d27a7f0ecd7402dc7885087789` | PR #29 병합(`096412e`) 이후, 이 CSV의 현재 줄 |

두 상태의 차이: 송파구 시행규칙 별표 5(첨부 121237861)의 `table-3` 청크 22개가 8개로 합쳐졌다. 나머지 535개의 `chunk_id`는 같다.

- **평가 기록에서 구별하는 법**: 성수님 `runs.csv`에는 `chunking_version`과 `index_id`(색인 ID)가 있다. 청킹 버전 이름은 같아도 색인 ID는 청크 집합이 다르면 달라지므로 이것으로 구별한다. PR #29 이전에 만든 색인으로 돌린 실행(예: 2026-11-25 06:48 UTC 기준 실행)은 첫 번째 상태로 보는 것이 맞다 [추정: 색인을 언제 만들었는지는 확인하지 못했다].
- **제안**: 앞으로의 평가 기록에 `chunks_sha256`을 함께 남기면 버전 이름이 같아도 어떤 청크 집합을 썼는지 알 수 있다(성수님 평가 기록 쪽 변경이라 이 문서에서는 제안만 한다).
