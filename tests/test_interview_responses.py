import io
import json

import pytest
from fastapi import HTTPException

from app.interview import request_question


@pytest.fixture
def request_with_response(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    def invoke(payload):
        monkeypatch.setattr(
            "app.interview.urllib.request.urlopen",
            lambda request, timeout, context: io.BytesIO(json.dumps(payload).encode()),
        )
        return request_question({
            "resume": "Built a payment API.",
            "role": "Backend Engineer",
            "experience": "mid-level",
            "job_description": "",
            "answer": "",
            "question": "",
            "is_follow_up": False,
        })

    return invoke


def test_reads_text_after_reasoning_item(request_with_response):
    result = request_with_response({"output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "  How did you design the payment API?  "},
        ]},
    ]})
    assert result == {"question": "How did you design the payment API?"}


def test_concatenates_all_text_blocks(request_with_response):
    result = request_with_response({"output": [
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "What trade-off "},
            {"type": "output_text", "text": "did you make"},
        ]},
        {"type": "message", "role": "assistant", "content": [
            {"type": "output_text", "text": "?"},
        ]},
    ]})
    assert result == {"question": "What trade-off did you make?"}


@pytest.mark.parametrize("payload", [
    {},
    {"output": []},
    {"output": [{"type": "message", "content": []}]},
    {"output": [{"type": "message", "content": [{"type": "output_text", "text": "  "}]}]},
    {"output": [{"type": "message", "content": [{"type": "refusal", "refusal": "Cannot answer."}]}]},
    None,
    [],
    "invalid",
    {"output": None},
    {"output": "invalid"},
    {"output": [None, "invalid", 3]},
    {"output": [{"type": "message", "content": None}]},
    {"output": [{"type": "message", "content": "invalid"}]},
    {"output": [{"type": "message", "content": [None, "invalid", 3]}]},
    {"output": [{"type": "message", "content": [{"type": "output_text", "text": 123}]}]},
])
def test_rejects_missing_or_malformed_text_cleanly(request_with_response, payload):
    with pytest.raises(HTTPException) as error:
        request_with_response(payload)
    assert error.value.status_code == 502
