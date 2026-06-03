"""Tests for Langfuse model definition upsert helpers."""

from app.admin.services.langfuse_model_upsert_helpers import (
    is_model_name_exists_error,
    parse_http_error,
)


def test_parse_http_error():
    status, body = parse_http_error(
        'HTTP 400: {"message":"Model name \'openai.gpt-5.4\' already exists in project"}'
    )
    assert status == 400
    assert "already exists" in body


def test_is_model_name_exists_error():
    detail = 'HTTP 400: {"message":"Model name \'x\' already exists in project"}'
    status, _ = parse_http_error(detail)
    assert is_model_name_exists_error(status, detail)


def test_is_model_name_exists_error_other_400():
    assert not is_model_name_exists_error(400, "invalid match pattern")
