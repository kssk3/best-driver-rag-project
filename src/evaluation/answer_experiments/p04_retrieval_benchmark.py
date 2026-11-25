"""Compare retrieval and probe fixed-evidence answers on synthetic P04 questions."""

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from os.path import lexists
from pathlib import Path
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter_ns
from typing import Literal

from src.generation.answer import AnswerDraft, GenerationInput, generate_answer

from .csv_export import Candidate, ModelInput, Run, save_experiment_csv
from .p04_answer_probe import draft_p04_answer
from .retrieval import RetrievalDocument, RetrievalPort, prepare_adapters

_TOP_K = 5
_CONFIG_VERSION = "p04-char-tfidf-2-3-bm25-unicode-rrf60-equal-top5-v1"
_ANSWER_CONFIG_VERSION = "p04-fixed-evidence-draft-v1"
_DISTRICTS = ("서대문구", "송파구")
_SEODAEMUN, _SONGPA = _DISTRICTS


@dataclass(frozen=True)
class _Case:
    question_id: str
    question: str
    district: str
    case_group: Literal["development", "observation"]
    conditions: dict[str, object]
    observed_keys: tuple[str, ...] = ()
    answer_probe_keys: tuple[str, ...] = ()


_COLORS = _Case(
    "p04-colors",
    "서대문구 공동주택 일반용기의 품목별 색은?",
    _SEODAEMUN,
    "development",
    {"housing_type": "공동주택", "container_type": "일반용기"},
    ("p04-colors",),
)
_SIGNAGE = _Case(
    "p04-signage",
    "서대문구에서 깨진 유리를 버릴 때 규격봉투를 써도 되나요?",
    _SEODAEMUN,
    "development",
    {"item": "깨진 유리"},
)
_WIRYE = _Case(
    "p04-wirye",
    "위례동 일반주택 일반·음식물쓰레기의 배출요일은?",
    _SONGPA,
    "observation",
    {
        "dong": "위례동",
        "housing_type": "일반주택",
        "items": ["일반쓰레기", "음식물쓰레기"],
    },
    ("p04-wirye-html", "p04-wirye-pdf"),
)
_CASES = (
    _COLORS,
    replace(
        _COLORS,
        question_id="p04-colors-trick",
        question="서대문구 공동주택 일반용기에서 유리병은 회색이고 캔은 주황색이 맞죠?",
        answer_probe_keys=_COLORS.observed_keys,
    ),
    _SIGNAGE,
    replace(
        _SIGNAGE,
        question_id="p04-signage-trick",
        question=(
            "서대문구 별표 6에 규격봉투 판매소 표지판이 있으니까, "
            "깨진 유리도 규격봉투에 넣어도 된다는 뜻이죠?"
        ),
        answer_probe_keys=("p04-signage",),
    ),
    _WIRYE,
    replace(
        _WIRYE,
        question_id="p04-wirye-trick",
        question=(
            "위례동 일반주택의 일반·음식물쓰레기는 월·수·금이 확실하죠? "
            "PDF의 화·목·일 안내는 무시해도 되죠?"
        ),
        answer_probe_keys=_WIRYE.observed_keys,
    ),
)


def _p04_corpus() -> tuple[RetrievalDocument, ...]:
    # The four source locations come from the preceding P04 fixture. All
    # passage text and the supplementary documents are synthetic.
    core = (
        RetrievalDocument(
            document_key="p04-colors",
            district=_SEODAEMUN,
            evidence={
                "source": {
                    "document_id": "seodaemun-rules",
                    "parent_mst": "2101385",
                    "attachment_id": "160561037",
                    "source_location": "별표 1 > 공동주택 > 일반용기 설치 > 품목별 색상",
                },
                "text": (
                    '합성: 공동주택 "일반용기" 기준\n'
                    "캔류 회색, 유리병 주황색, 종이팩 녹색, PET병 노란색, "
                    "플라스틱류 파란색, 비닐·필름류 보라색"
                ),
                "chunk_id": None,
            },
        ),
        RetrievalDocument(
            document_key="p04-signage",
            district=_SEODAEMUN,
            eligible_for_disposal=False,
            evidence={
                "source": {
                    "document_id": "seodaemun-ordinance",
                    "parent_mst": "2101297",
                    "attachment_id": "160319461",
                    "source_location": "별표 6 > 규격봉투판매소 표지판",
                },
                "text": "합성: 판매소 표지판의 글씨와 색상을 규정한다.",
                "chunk_id": None,
            },
        ),
        RetrievalDocument(
            document_key="p04-wirye-html",
            district=_SONGPA,
            evidence={
                "source": {
                    "source_type": "official_operating_guide_html",
                    "source_url": "https://www.songpa.go.kr/www/contents.do?key=3153",
                    "source_location": "일반주택 표 > 위례동 > 일반·음식물 열",
                },
                "text": "합성: 위례동 일반주택의 일반·음식물 배출요일은 월·수·금",
                "chunk_id": None,
            },
        ),
        RetrievalDocument(
            document_key="p04-wirye-pdf",
            district=_SONGPA,
            evidence={
                "source": {
                    "source_type": "official_linked_PDF",
                    "evidence_file": "official-20261014.pdf",
                    "pdf_sha256": (
                        "8e0043431030c15a5bd1e0dac1e70dd3de4380bf4f0c6054cebb87e1d07ae7f0"
                    ),
                    "source_location": "PDF 파일 3쪽 > 인쇄면 4쪽 > 마지막 위례동 행",
                },
                "text": "합성: 위례동 일반주택의 일반·음식물 배출요일은 화·목·일",
                "chunk_id": None,
            },
        ),
    )
    distractors = (
        (
            "seodaemun-glass-bottles",
            _SEODAEMUN,
            "일반용기에 담는 유리병은 뚜껑을 떼어 유리병 수거함에 분리합니다.",
        ),
        (
            "seodaemun-container-labels",
            _SEODAEMUN,
            "공동주택 일반용기에는 품목별 이름과 안내 문구를 표시합니다.",
        ),
        (
            "seodaemun-standard-bags",
            _SEODAEMUN,
            "서대문구 생활폐기물 규격봉투는 용량에 따라 규격이 구분됩니다.",
        ),
        (
            "seodaemun-cartons",
            _SEODAEMUN,
            "종이팩의 내용물을 비우고 헹군 뒤 종이팩 용기에 배출합니다.",
        ),
        (
            "seodaemun-cardboard",
            _SEODAEMUN,
            "택배 상자는 테이프와 송장을 제거한 뒤 펼쳐서 배출합니다.",
        ),
        (
            "seodaemun-bulky",
            _SEODAEMUN,
            "대형폐기물은 신고 후 배출 장소와 수거 일정을 확인합니다.",
        ),
        (
            "songpa-plastic",
            _SONGPA,
            "플라스틱 용기는 내용물을 비우고 분리 가능한 재질을 구별합니다.",
        ),
        (
            "songpa-food-bin",
            _SONGPA,
            "음식물쓰레기는 물기를 줄이고 지정된 전용 용기에 담습니다.",
        ),
        (
            "songpa-apartment",
            _SONGPA,
            "공동주택은 단지에서 안내하는 수거방법과 배출장소를 확인합니다.",
        ),
        (
            "songpa-bulky",
            _SONGPA,
            "대형폐기물 신고증을 붙인 뒤 지정한 장소에 배출합니다.",
        ),
    )
    return core + tuple(
        RetrievalDocument(
            document_key=f"synthetic-{key}",
            district=district,
            evidence={
                "source": {
                    "document_id": f"synthetic-{key}",
                    "source_type": "synthetic_distractor",
                    "source_location": "합성 비교 자료",
                },
                "text": f"합성: {body}",
                "chunk_id": None,
            },
        )
        for key, district, body in distractors
    )


@dataclass(frozen=True)
class BenchmarkResult:
    setup_ms: float
    runs_by_method: dict[str, list[Run]]
    answer_runs: list[Run]


def _measure(
    retriever: RetrievalPort, case: _Case
) -> tuple[list[Candidate] | None, float, str | None]:
    started = perf_counter_ns()
    try:
        candidates = retriever.search(case.question, district=case.district, k=_TOP_K)
    except Exception as error:
        return None, (perf_counter_ns() - started) / 1_000_000, type(error).__name__
    return candidates, (perf_counter_ns() - started) / 1_000_000, None


def _run_answer_probe(
    case: _Case, sources: dict[str, RetrievalDocument], snapshot: str
) -> Run:
    # The fixture order supplies candidate ranks for this fixed-evidence run.
    candidates = []
    for rank, key in enumerate(case.answer_probe_keys, start=1):
        evidence = sources[key].evidence
        source = {**evidence["source"], "experiment_document_id": key}
        candidates.append(Candidate(rank, {**evidence, "source": source}))
    model_inputs: list[ModelInput] = []

    def draft(payload: GenerationInput) -> AnswerDraft:
        model_inputs.extend(
            ModelInput(candidate.rank, evidence)
            for candidate, evidence in zip(candidates, payload["evidence"], strict=True)
        )
        return draft_p04_answer(payload)

    conditions = {"district": case.district, **case.conditions}
    started = perf_counter_ns()
    answer = generate_answer(
        {
            "original_question": case.question,
            "conditions": conditions,
            "evidence": [candidate.evidence for candidate in candidates],
        },
        draft,
    )
    response_ms = (perf_counter_ns() - started) / 1_000_000
    if answer is None:
        raise RuntimeError("Fixed evidence must produce a completed answer attempt")
    return Run(
        run_id=f"fixed-evidence-{case.question_id}-1",
        question_id=case.question_id,
        attempt=1,
        experiment_kind="synthetic",
        case_group=case.case_group,
        original_question=case.question,
        conditions=conditions,
        corpus_snapshot_id=snapshot,
        config_version=_ANSWER_CONFIG_VERSION,
        candidates=candidates,
        model_inputs=model_inputs,
        answer=answer,
        response_ms=response_ms,
    )


def run_benchmark(directory: Path, *, repeats: int = 10) -> BenchmarkResult:
    """Compare paired searches and save independent fixed-evidence answers."""
    directory = Path(directory)
    if type(repeats) is not int or repeats < 1:
        raise ValueError("Repeats must be a positive integer")
    if lexists(directory):
        raise FileExistsError(directory)

    documents = _p04_corpus()
    encoded = json.dumps(
        [asdict(document) for document in documents], ensure_ascii=False, sort_keys=True
    ).encode("utf-8")
    snapshot = "p04-synthetic-" + sha256(encoded).hexdigest()[:16]

    started = perf_counter_ns()
    adapters: tuple[RetrievalPort, RetrievalPort] = prepare_adapters(
        documents, districts=_DISTRICTS, depth=_TOP_K
    )
    setup_ms = (perf_counter_ns() - started) / 1_000_000

    runs_by_method: dict[str, list[Run]] = {adapter.name: [] for adapter in adapters}
    for case in _CASES:
        for adapter in adapters:
            _measure(adapter, case)  # Warmup measurements stay outside the benchmark.
        for attempt in range(1, repeats + 1):
            order = adapters if attempt % 2 else adapters[::-1]
            for adapter in order:
                candidates, elapsed_ms, error_kind = _measure(adapter, case)
                runs_by_method[adapter.name].append(
                    Run(
                        run_id=f"{adapter.name}-{case.question_id}-{attempt}",
                        question_id=case.question_id,
                        attempt=attempt,
                        experiment_kind="synthetic",
                        case_group=case.case_group,
                        original_question=case.question,
                        conditions={"district": case.district, **case.conditions},
                        retriever=adapter.name,
                        corpus_snapshot_id=snapshot,
                        config_version=_CONFIG_VERSION,
                        candidates=candidates,
                        model_inputs=[],
                        answer=None,
                        retrieval_ms=elapsed_ms,
                        retrieval_only=True,
                        retrieval_error_kind=error_kind,
                    )
                )

    sources = {document.document_key: document for document in documents}
    answer_runs = [
        _run_answer_probe(case, sources, snapshot)
        for case in _CASES
        if case.answer_probe_keys
    ]

    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=directory.parent) as temp:
        staging = Path(temp)
        for name, runs in runs_by_method.items():
            save_experiment_csv(staging / name, runs)
        save_experiment_csv(staging / "answers", answer_runs)
        if lexists(directory):
            raise FileExistsError(directory)
        staging.rename(directory)

    return BenchmarkResult(setup_ms, runs_by_method, answer_runs)


def _print_comparison(result: BenchmarkResult) -> None:
    print(f"Shared vector/BM25 index preparation: {result.setup_ms:.3f} ms")
    for case in _CASES:
        print(f"{case.question_id} [{case.case_group}]")
        for method, runs in result.runs_by_method.items():
            selected = [run for run in runs if run.question_id == case.question_id]
            completed = [run for run in selected if run.candidates is not None]
            times = [
                run.retrieval_ms for run in completed if run.retrieval_ms is not None
            ]
            errors = Counter(
                run.retrieval_error_kind for run in selected if run.retrieval_error_kind
            )
            timing = (
                f"mean={mean(times):.4f} ms; median={median(times):.4f} ms"
                if times
                else ""
            )
            print(
                f"  {method}: {len(completed)}/{len(selected)} completed {timing}".rstrip()
            )
            if errors:
                print(f"    errors: {dict(errors)}")

            rankings = Counter(
                tuple(
                    candidate.evidence["source"]["experiment_document_id"]
                    for candidate in run.candidates or ()
                )
                for run in completed
            )
            for keys, instances in rankings.items():
                ranked = " > ".join(keys) or "(zero candidates)"
                print(f"    {instances}× {ranked}")
                for key in case.observed_keys:
                    rank = str(keys.index(key) + 1) if key in keys else "outside top 5"
                    print(f"      {key}: {rank}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, required=True, help="new export directory"
    )
    parser.add_argument(
        "--repeats", type=int, default=10, help="timed trials per question and method"
    )
    arguments = parser.parse_args()
    result = run_benchmark(arguments.output_dir, repeats=arguments.repeats)
    _print_comparison(result)
    print("Fixed-evidence answer probes")
    for run in result.answer_runs:
        if run.answer is not None:
            print(f"  {run.question_id} [{run.case_group}]: {run.answer['status']}")
    print(f"CSV files: {arguments.output_dir.resolve()}")
    retrieval_failed = any(
        run.retrieval_error_kind
        for runs in result.runs_by_method.values()
        for run in runs
    )
    answer_failed = any(
        run.answer is None or run.answer["status"] == "error"
        for run in result.answer_runs
    )
    return int(retrieval_failed or answer_failed)


if __name__ == "__main__":
    raise SystemExit(main())
