import json

import pytest

from agents import review_refine


class _Prompt:
    def __init__(self):
        self.values = {}

    def compile(self, **kwargs):
        self.values = kwargs
        return "review prompt"


class _Client:
    def __init__(self):
        self.prompt = _Prompt()

    def get_prompt(self, *args, **kwargs):
        return self.prompt


def _state(**overrides):
    state = {
        "content": "Source",
        "platforms": ["x"],
        "current_plan": {
            "platform_tasks": [{"platform": "x", "task": "write"}],
            "is_refinement": False,
        },
        "latest_results": {"X": {"processed_content": "Draft", "platform": "X"}},
        "quality_threshold": 0.8,
        "max_iterations": 1,
        "iteration_count": 0,
    }
    state.update(overrides)
    return state


def _mock_review(monkeypatch, review, client=None):
    client = client or _Client()
    monkeypatch.setattr(review_refine, "get_client", lambda: client)
    monkeypatch.setattr(
        review_refine,
        "invoke_text",
        lambda prompt, llm, model, **kwargs: json.dumps({"reviews": review}),
    )
    return client


@pytest.mark.parametrize(
    ("value", "expected"),
    [(0.8, 80), (1, 100), (80, 80), (0, 0), (100, 100), (None, 80), (True, 80)],
)
def test_quality_threshold_normalization(value, expected):
    assert review_refine._threshold_as_percent(value) == expected


@pytest.mark.parametrize("value", [-1, 101])
def test_quality_threshold_rejects_out_of_range(value):
    with pytest.raises(ValueError, match="quality_threshold"):
        review_refine._threshold_as_percent(value)


def test_quality_threshold_treats_fractional_percent_values_as_percent():
    assert review_refine._threshold_as_percent(1.1) == 1.1


def test_draft_text_supports_known_fields_and_rejects_empty_values():
    assert review_refine._draft_text({"processed_content": "draft"}) == "draft"
    assert review_refine._draft_text({"content": "content"}) == "content"
    assert review_refine._draft_text({"draft": "saved"}) == "saved"
    assert review_refine._draft_text(" raw draft ") == " raw draft "
    assert review_refine._draft_text({"draft": " "}) is None
    assert review_refine._draft_text(None) is None


def test_approved_review_finishes_and_returns_normalized_draft(monkeypatch):
    client = _mock_review(
        monkeypatch,
        [{"platform": "X", "quality_score": 96, "approved": True}],
    )

    result = review_refine.review_refine_node(_state())

    assert result["task_completed"] is True
    assert result["replan_required"] is False
    assert result["platform_status"] == {"x": "approved"}
    assert result["review_feedback"]["x"] == "No changes required."
    assert result["processed_content"] == [{"platform": "X", "processed_content": "Draft"}]
    assert result["quality_score"] == 96
    assert client.prompt.values["threshold"] == 80


def test_unapproved_review_requests_refinement_with_feedback(monkeypatch):
    _mock_review(
        monkeypatch,
        [
            {
                "platform": "x",
                "quality_score": 60,
                "approved": False,
                "feedback": "Add context",
            }
        ],
    )
    result = review_refine.review_refine_node(_state())

    assert result["task_completed"] is False
    assert result["replan_required"] is True
    assert result["current_step"] == "manager_refinement"
    assert result["platform_status"]["x"] == "needs_refinement"
    assert result["review_history"][0]["review_feedback"]["x"] == "Add context"


def test_review_approval_requires_threshold_and_no_rejection_reasons(monkeypatch):
    _mock_review(
        monkeypatch,
        [
            {
                "platform": "x",
                "quality_score": 70,
                "approved": True,
                "rejection_reasons": [],
            }
        ],
    )
    result = review_refine.review_refine_node(
        _state(quality_threshold=80, max_iterations=0)
    )

    assert result["platform_status"]["x"] == "needs_refinement"
    rejection_reason = result["review_history"][0]["rejection_reasons"]["x"][0]
    assert "below the approval threshold" in rejection_reason
    assert result["task_completed"] is True
    assert result["replan_required"] is False
    assert result["processed_content"][0]["processed_content"] == "Draft"


def test_review_reason_overrides_approval_and_empty_feedback(monkeypatch):
    _mock_review(
        monkeypatch,
        [
            {
                "platform": "x",
                "quality_score": 95,
                "approved": True,
                "rejection_reasons": [" revise claims ", ""],
                "feedback": " ",
            }
        ],
    )
    result = review_refine.review_refine_node(_state(max_iterations=0))

    assert result["platform_status"]["x"] == "needs_refinement"
    assert result["review_feedback"]["x"] == "revise claims"
    assert result["review_history"][0]["rejection_reasons"]["x"] == ["revise claims"]


def test_review_falls_back_to_default_feedback_and_counts_refinement(monkeypatch):
    _mock_review(
        monkeypatch,
        [{"platform": "x", "quality_score": 40, "approved": False}],
    )
    result = review_refine.review_refine_node(
        _state(
            current_plan={
                "platform_tasks": [{"platform": "x"}],
                "is_refinement": True,
            },
            iteration_count=1,
            max_iterations=3,
        )
    )

    assert result["iteration_count"] == 2
    assert result["replan_required"] is True
    assert "did not include a specific reason" in result["review_feedback"]["x"]


@pytest.mark.parametrize(
    ("state", "message"),
    [
        ({"platforms": []}, "at least one requested platform"),
        ({"platforms": [" "]}, "non-empty platform name"),
        ({"platforms": ["x"], "current_plan": {"platform_tasks": "bad"}}, "platform_tasks"),
        ({"platforms": ["x"], "current_plan": {"platform_tasks": []}}, "platform tasks"),
        (
            {
                "platforms": ["x"],
                "current_plan": {"platform_tasks": [{"platform": "facebook"}]},
            },
            "unrequested platforms",
        ),
        (
            {
                "platforms": ["x", "linkedin"],
                "current_plan": {"platform_tasks": [{"platform": "x"}]},
            },
            "every requested platform",
        ),
        (
            {
                "platforms": ["x"],
                "current_plan": {"platform_tasks": [{"platform": "x"}]},
                "latest_results": {},
            },
            "No generated draft",
        ),
    ],
)
def test_review_validates_workflow_state(state, message):
    with pytest.raises(ValueError, match=message):
        review_refine.review_refine_node(state)


@pytest.mark.parametrize(
    ("review", "message"),
    [
        ([], "omitted the x draft"),
        ([{"platform": "x", "quality_score": True}], "invalid quality score"),
        ([{"platform": "x", "quality_score": 101}], "invalid quality score"),
        (
            [{"platform": "x", "quality_score": 80, "rejection_reasons": "bad"}],
            "invalid rejection reasons",
        ),
    ],
)
def test_review_validates_model_reviews(monkeypatch, review, message):
    _mock_review(monkeypatch, review)
    with pytest.raises(ValueError, match=message):
        review_refine.review_refine_node(_state())


def test_review_requires_final_draft_at_terminal_state(monkeypatch):
    _mock_review(
        monkeypatch,
        [{"platform": "x", "quality_score": 100, "approved": True}],
    )
    original_mapping = review_refine.platform_mapping
    mapping_calls = 0

    def remove_final_result_after_review(value):
        nonlocal mapping_calls
        mapping_calls += 1
        if mapping_calls == 4:
            return {}
        return original_mapping(value)

    monkeypatch.setattr(review_refine, "platform_mapping", remove_final_result_after_review)
    with pytest.raises(ValueError, match="No final draft"):
        review_refine.review_refine_node(_state(max_iterations=0))


def test_review_replaces_empty_result_platform_with_requested_name(monkeypatch):
    _mock_review(
        monkeypatch,
        [{"platform": "x", "quality_score": 100, "approved": True}],
    )

    result = review_refine.review_refine_node(
        _state(
            latest_results={
                "x": {"platform": " ", "processed_content": "Draft"}
            }
        )
    )

    assert result["processed_content"] == [{"platform": "x", "processed_content": "Draft"}]


def test_decode_reviews_requires_a_reviews_list():
    with pytest.raises(ValueError, match="reviews list"):
        review_refine._decode_reviews('{"reviews":"bad"}')
