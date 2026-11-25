"""공통 에러 기반의 동작 규격을 확인한다."""

import pytest

from src.common.errors import (
    ApplicationError,
    ErrorCategory,
    describe_error,
)


class _DraftError(ApplicationError, RuntimeError):
    code = "generation.invalid_draft"
    category = ErrorCategory.CONTRACT_VIOLATION


def test_base_error_keeps_message_and_class_defaults():
    error = ApplicationError("상세")

    assert str(error) == "상세"
    assert error.code == "common.application_error"
    assert error.category is ErrorCategory.INTERNAL


def test_subclass_code_and_category_apply_and_instance_can_override_code():
    default = _DraftError("초안 형식 오류")
    overridden = _DraftError(
        "조건 해석 실패", code="generation.condition_decode_failed"
    )

    assert default.code == "generation.invalid_draft"
    assert default.category is ErrorCategory.CONTRACT_VIOLATION
    assert overridden.code == "generation.condition_decode_failed"
    assert _DraftError.code == "generation.invalid_draft"


def test_subclass_without_code_inherits_parent_code():
    class _ChildError(_DraftError):
        pass

    assert _ChildError("x").code == "generation.invalid_draft"


def test_multiple_inheritance_keeps_existing_builtin_except_clauses():
    class _ManifestError(ApplicationError, ValueError):
        code = "ingestion.invalid_manifest"

    with pytest.raises(ValueError):
        raise _ManifestError("목록 형식 오류")
    with pytest.raises(ApplicationError) as caught:
        raise _ManifestError("목록 형식 오류", code="ingestion.duplicate_source")
    assert str(caught.value) == "목록 형식 오류"
    assert caught.value.code == "ingestion.duplicate_source"


@pytest.mark.parametrize(
    "code", ["Generation-Failed", "generation", "generation.", "a.b\n", None]
)
def test_malformed_class_code_is_rejected_at_definition(code):
    with pytest.raises(ValueError):
        type("_BadError", (ApplicationError,), {"code": code})


def test_builtin_exception_before_base_is_rejected_at_definition():
    # 순서가 거꾸로면 ValueError.__init__이 먼저 실행돼 code= 인자를 받지 못한다.
    with pytest.raises(TypeError):
        type("_ReversedError", (ValueError, ApplicationError), {"code": "x.reversed"})


def test_builtin_exception_before_domain_error_names_the_domain_class():
    # KeyError는 _DraftError의 MRO에 없어서 파이썬 자체 MRO 오류가 아니라 공통 검사가 막는다.
    with pytest.raises(TypeError, match="_DraftError"):
        type("_ReversedDomainError", (KeyError, _DraftError), {})


def test_non_exception_mixin_before_base_is_allowed():
    class _Mixin:
        pass

    class _MixedError(_Mixin, ApplicationError):
        code = "x.mixed"

    assert _MixedError("m", code="x.other").code == "x.other"


@pytest.mark.parametrize("user_message", [None, "", "   "])
def test_blank_user_message_is_rejected_at_definition(user_message):
    with pytest.raises(TypeError):
        type(
            "_BlankMessageError",
            (ApplicationError,),
            {"code": "x.blank_message", "user_message": user_message},
        )


def test_malformed_instance_code_is_rejected_at_construction():
    with pytest.raises(ValueError):
        ApplicationError("x", code="Bad Code")


def test_non_category_value_is_rejected_at_definition():
    with pytest.raises(TypeError):
        type(
            "_BadCategoryError",
            (ApplicationError,),
            {"code": "x.bad_category", "category": "internal"},
        )


def test_describe_foreign_exception_as_internal_with_detail():
    info = describe_error(ValueError("boom"))

    assert info.code == "common.unexpected_error"
    assert info.category is ErrorCategory.INTERNAL
    # src/pipeline.py의 기존 공통 오류 안내와 같은 문구다.
    assert info.user_message == "요청을 처리하는 중 오류가 발생했습니다."
    assert info.detail == "ValueError: boom"


def test_describe_application_error_uses_its_code_and_user_message():
    class _QuotaError(ApplicationError):
        code = "generation.quota_exceeded"
        category = ErrorCategory.EXTERNAL_SERVICE
        user_message = "잠시 후 다시 시도해 주세요."

    info = describe_error(_QuotaError("429 from provider"))

    assert info.code == "generation.quota_exceeded"
    assert info.category is ErrorCategory.EXTERNAL_SERVICE
    assert info.user_message == "잠시 후 다시 시도해 주세요."
    assert info.detail == "_QuotaError: 429 from provider"


def test_detail_of_empty_message_is_bare_type_name():
    assert describe_error(ApplicationError()).detail == "ApplicationError"


@pytest.mark.parametrize(
    "error",
    [
        ValueError("/Users/secret/key.txt sk-abc"),
        _DraftError("/Users/secret/key.txt sk-abc"),
    ],
)
def test_user_message_never_contains_original_exception_text(error):
    info = describe_error(error)

    assert "/Users/secret/key.txt" not in info.user_message
    assert "sk-abc" not in info.user_message
