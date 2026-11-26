"""합성 첨부로 검증하는 LLM 별표 검수 경로."""

import json
import sys
from hashlib import sha256
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage

from scripts.review_annex_tables import main, review_annex_tables
from src.ingestion import annex_review_model

APPROVED_HASH = "a" * 64
OTHER_HASH = "b" * 64


@pytest.fixture
def annex_manifest(tmp_path):
    entries = []
    for name, raw_hash, example in (
        ("approved", APPROVED_HASH, "합성\n검수 후보"),
        ("other", OTHER_HASH, "미선택\n원문 조각"),
    ):
        path = tmp_path / f"{name}.json"
        identity = {
            "parent_mst": "synthetic",
            "attachment_id": name,
            "raw_sha256": raw_hash,
        }
        table = {
            "table_id": "table-1",
            "rows": 2,
            "cols": 1,
            "row_cell_ids": [["header"], ["item"]],
            "cells": [
                dict(cell_id=cell_id, row=row, col=0, rowspan=1, colspan=1, text=value)
                for row, (cell_id, value) in enumerate(
                    [("header", "품목"), ("item", example)]
                )
            ],
        }
        path.write_text(
            json.dumps(
                {**identity, "tables": [table], "blocks": []}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        entries.append({**identity, "output_file": path.name})
    manifest = tmp_path / "annex_manifest.json"
    manifest.write_text(json.dumps({"records": entries}), encoding="utf-8")
    return manifest


def _approved_output_hash(manifest):
    return sha256((manifest.parent / "approved.json").read_bytes()).hexdigest()


def test_model_review_cli_sends_only_selected_candidates(
    annex_manifest, monkeypatch, capsys
):
    chat = Mock()
    chat.bind.return_value = chat
    chat.invoke.return_value = AIMessage(
        content='{"suggestions":[{"index":0,"decision":"review"}]}'
    )
    create = Mock(return_value=chat)
    monkeypatch.setattr(annex_review_model, "create_chat_model", create)
    before = {path.name: path.read_bytes() for path in annex_manifest.parent.iterdir()}
    baseline = review_annex_tables(annex_manifest)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "review_annex_tables",
            str(annex_manifest),
            "--llm-model",
            "synthetic-model",
            "--llm-approved-sha256",
            APPROVED_HASH,
            "--llm-approved-output-sha256",
            _approved_output_hash(annex_manifest),
        ],
    )

    assert main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report.pop("llm_review") == {
        "model": "synthetic-model",
        "prompt_version": "annex-review-v1",
        "selected_candidates": 1,
        "unselected_candidates": 1,
        "approval_exclusions": {"raw_sha256_unapproved": 1},
        "status": "completed",
        "suggestions": [{"index": 0, "decision": "review"}],
    }
    assert report == baseline
    assert before == {
        path.name: path.read_bytes() for path in annex_manifest.parent.iterdir()
    }
    create.assert_called_once()
    chat.bind.assert_called_once_with(response_format={"type": "json_object"})
    messages = chat.invoke.call_args.args[0]
    assert json.loads(messages[1][1]) == {
        "candidates": [
            {"index": 0, "kind": "cell_line_break", "texts": ["합성\n검수 후보"]}
        ]
    }


@pytest.mark.parametrize(
    ("raw_approvals", "output_approval", "exclusions"),
    [
        ((), "missing", {"raw_sha256_unapproved": 2}),
        (
            (APPROVED_HASH,),
            "missing",
            {"output_sha256_unapproved": 1, "raw_sha256_unapproved": 1},
        ),
        (
            (APPROVED_HASH,),
            "mismatch",
            {"output_sha256_unapproved": 1, "raw_sha256_unapproved": 1},
        ),
        (("c" * 64,), "matching", {"raw_sha256_unapproved": 2}),
    ],
)
def test_model_review_skips_without_both_approvals(
    annex_manifest, monkeypatch, raw_approvals, output_approval, exclusions
):
    create = Mock()
    monkeypatch.setattr(annex_review_model, "create_chat_model", create)
    output_approvals = {
        "missing": (),
        "mismatch": ("d" * 64,),
        "matching": (_approved_output_hash(annex_manifest),),
    }

    report = review_annex_tables(
        annex_manifest,
        llm_model="synthetic-model",
        llm_approved_hashes=raw_approvals,
        llm_approved_output_hashes=output_approvals[output_approval],
    )

    model_report = report.pop("llm_review")
    assert model_report["status"] == "skipped"
    assert model_report["selected_candidates"] == 0
    assert model_report["unselected_candidates"] == 2
    assert model_report["approval_exclusions"] == exclusions
    assert report == review_annex_tables(annex_manifest)
    create.assert_not_called()


@pytest.mark.parametrize("change_text", [False, True])
def test_model_review_rechecks_exact_processed_bytes(
    annex_manifest, monkeypatch, change_text
):
    create = Mock()
    monkeypatch.setattr(annex_review_model, "create_chat_model", create)
    approved_hash = _approved_output_hash(annex_manifest)
    path = annex_manifest.parent / "approved.json"
    original_bytes = path.read_bytes()
    changed_bytes = (
        original_bytes.replace("합성".encode(), "변경".encode(), 1)
        if change_text
        else original_bytes + b"\n"
    )
    assert json.loads(changed_bytes)["raw_sha256"] == APPROVED_HASH
    path.write_bytes(changed_bytes)
    manifest = json.loads(annex_manifest.read_text(encoding="utf-8"))
    manifest["records"][0]["output_sha256"] = sha256(changed_bytes).hexdigest()
    annex_manifest.write_text(json.dumps(manifest), encoding="utf-8")

    report = review_annex_tables(
        annex_manifest,
        llm_model="synthetic-model",
        llm_approved_hashes={APPROVED_HASH},
        llm_approved_output_hashes={approved_hash},
    )

    model_report = report.pop("llm_review")
    assert model_report["status"] == "skipped"
    assert model_report["approval_exclusions"]["output_sha256_unapproved"] == 1
    assert report == review_annex_tables(annex_manifest)
    if change_text:
        assert report["candidates"][0]["cells"][0]["text"] == "변경\n검수 후보"
    create.assert_not_called()


@pytest.mark.parametrize(
    "model_output",
    [
        '{"suggestions":[{"index":1,"decision":"review"}]}',
        '{"suggestions":[{"index":0,"decision":"merge"}]}',
        '{"suggestions":[{"index":0,"decision":"review","text":"changed"}]}',
    ],
)
def test_model_review_rejects_unexpected_output(
    annex_manifest, monkeypatch, model_output
):
    chat = Mock()
    chat.bind.return_value = chat
    chat.invoke.return_value = AIMessage(content=model_output)
    monkeypatch.setattr(
        annex_review_model, "create_chat_model", Mock(return_value=chat)
    )

    report = review_annex_tables(
        annex_manifest,
        llm_model="synthetic-model",
        llm_approved_hashes={APPROVED_HASH},
        llm_approved_output_hashes={_approved_output_hash(annex_manifest)},
    )

    assert report["llm_review"]["status"] == "error"
    assert report["llm_review"]["error_code"] == "infrastructure.llm_invalid_output"
    assert report["llm_review"]["suggestions"] == []
    assert all(c["status"] == "needs_source_review" for c in report["candidates"])


def test_model_call_error_keeps_rules(annex_manifest, monkeypatch):
    chat = Mock()
    chat.bind.return_value = chat
    monkeypatch.setattr(
        annex_review_model, "create_chat_model", Mock(return_value=chat)
    )
    monkeypatch.setattr(
        annex_review_model,
        "invoke_chat",
        Mock(
            side_effect=annex_review_model.ApplicationError(
                code="infrastructure.llm_timeout"
            )
        ),
    )
    baseline = review_annex_tables(annex_manifest)

    report = review_annex_tables(
        annex_manifest,
        llm_model="synthetic-model",
        llm_approved_hashes={APPROVED_HASH},
        llm_approved_output_hashes={_approved_output_hash(annex_manifest)},
    )

    model_report = report.pop("llm_review")
    assert model_report["status"] == "error"
    assert model_report["error_code"] == "infrastructure.llm_timeout"
    assert report == baseline
