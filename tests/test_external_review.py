"""Completion must mean a full response, not just exit zero or SUCCESS."""

import importlib.util
import json
from pathlib import Path

import pytest


spec = importlib.util.spec_from_file_location(
    "external_review", Path(__file__).resolve().parents[1] / "scripts/run_external_review.py"
)
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


def agy_result(response="Done\nCOMPLETE", status="SUCCESS"):
    return json.dumps({"status": status, "response": response})


@pytest.mark.parametrize("response", ["", "partial", "COMPLETE\nStill working", "COMPLETE-ish"])
def test_empty_or_incomplete_success_is_rejected(response):
    assert review.validate_result("gemini", 0, agy_result(response), "", "COMPLETE")[2]


@pytest.mark.parametrize("stderr", ["print timeout; partial output", "request timed out"])
def test_exit_zero_timeout_with_marker_is_rejected(stderr):
    assert review.validate_result("gemini", 0, agy_result(), stderr, "COMPLETE")[2]


def test_completed_response_is_accepted():
    assert review.validate_result("gemini", 0, agy_result(), "", "COMPLETE")[2] is None


@pytest.mark.parametrize("stdout", ["", "not json", "[]"])
def test_invalid_json_is_rejected(stdout):
    assert review.validate_result("gemini", 0, stdout, "", "COMPLETE")[2]


def test_nonzero_and_failed_status_are_rejected():
    assert review.validate_result("gemini", 1, agy_result(), "", "COMPLETE")[2]
    assert review.validate_result("gemini", 0, agy_result(status="ERROR"), "", "COMPLETE")[2]


def test_opus_requires_exact_model_and_no_denied_tools():
    payload = {"subtype": "success", "is_error": False, "result": "Done\nCOMPLETE",
               "modelUsage": {"claude-opus-5-5": {}}}
    assert review.validate_result("opus", 0, json.dumps(payload), "", "COMPLETE")[2] is None
    payload["modelUsage"] = {"other-model": {}}
    assert review.validate_result("opus", 0, json.dumps(payload), "", "COMPLETE")[2]
    payload["modelUsage"] = {"claude-opus-5-5": {}}
    payload["permission_denials"] = [{"tool_name": "Read"}]
    assert review.validate_result("opus", 0, json.dumps(payload), "", "COMPLETE")[2]


def test_gemini_command_pins_agent_model_effort_and_duration():
    command = review.build_command("gemini", "agy.exe", "packet", 180)
    assert command[command.index("--agent") + 1] == "gemini-review"
    assert command[command.index("--model") + 1] == "gemini-3.8-flash-high"
    assert command[command.index("--effort") + 1] == "high"
    assert command[command.index("--print-timeout") + 1] == "180s"
    assert "--disable-slash-commands" not in command
    assert "--dangerously-skip-permissions" not in command


def test_gemini_packet_is_bounded():
    with pytest.raises(ValueError):
        review.build_command("gemini", "agy.exe", "x" * 20_001, 180)


def test_agent_fallback_is_not_accepted_as_requested_agent_success():
    error = review.validate_result(
        "gemini", 0, agy_result(), "", "COMPLETE",
        'Agent "gemini-review" not found, falling back to default',
    )[2]
    assert "fell back" in error
    error = review.validate_result(
        "gemini", 0, agy_result(), 'Agent "gemini-review" not found,\nfalling back to default',
        "COMPLETE",
    )[2]
    assert "fell back" in error


def test_agent_activation_and_exact_gemini_label_are_required_when_log_present():
    activation = "Starting new conversation (agent=true)"
    label = 'label="Gemini 3.8 Flash (High)"'
    assert review.validate_result("gemini", 0, agy_result(), "", "COMPLETE", label)[2]
    assert review.validate_result("gemini", 0, agy_result(), "", "COMPLETE", activation)[2]
    assert review.validate_result(
        "gemini", 0, agy_result(), "", "COMPLETE", activation + "\n" + label
    )[2] is None
