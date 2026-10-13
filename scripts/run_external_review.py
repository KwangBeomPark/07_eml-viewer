"""Dispatch a bounded external review and reject empty or partial completion.

Raw prompts and CLI logs remain in the ignored build/external-agents directory.
This is a CLI bridge; it does not change Codex's built-in subagent models.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODELS = {"gemini": "gemini-3.8-flash-high", "opus": "claude-opus-5-5"}


def build_command(provider: str, executable: str, prompt: str, timeout: int) -> list[str]:
    if provider == "gemini":
        # agy expects a duration with units; slash disabling would cancel plan mode.
        # Tool restrictions come from the selected agent, not from plan mode.
        if len(prompt) > 20_000:
            raise ValueError("Gemini packet exceeds 20,000 characters; split the task.")
        return [
            executable, "--agent", "gemini-review", "--model", MODELS[provider],
            "--effort", "high", "--output-format", "json",
            "--print-timeout", f"{timeout}s", "-p", prompt,
        ]
    return [
        executable, "--model", MODELS[provider], "--effort", "high",
        "--tools", "", "--strict-mcp-config", "--no-session-persistence",
        "--output-format", "json", "-p",
    ]


def validate_result(
    provider: str, returncode: int, stdout: str, stderr: str, marker: str,
    agent_log: str = "",
) -> tuple[dict, str, str | None]:
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        return {}, "", "CLI did not return a JSON object"
    if not isinstance(payload, dict):
        return {}, "", "CLI returned a non-object JSON value"
    response = payload.get("response" if provider == "gemini" else "result", "")
    if not isinstance(response, str):
        response = ""
    if returncode != 0:
        return payload, response, f"CLI exited with code {returncode}"
    if re.search(r"print.?timeout|timed? out|partial output|timeout exceeded", stderr, re.I):
        return payload, response, "CLI reported a timeout or partial output"
    if provider == "gemini" and re.search(
        r"Agent\s+[^\r\n]*not\s+found.{0,120}?falling\s+back",
        stderr + "\n" + agent_log, re.I | re.S,
    ):
        return payload, response, "Requested agent was not found; agy fell back to default"
    if provider == "gemini" and agent_log:
        if "Starting new conversation (agent=true)" not in agent_log:
            return payload, response, "Custom agent activation was not confirmed in the CLI log"
        if 'label="Gemini 3.8 Flash (High)"' not in agent_log:
            return payload, response, "Requested Gemini model label was not confirmed in the CLI log"
    if provider == "gemini" and payload.get("status") != "SUCCESS":
        return payload, response, "Antigravity did not report SUCCESS"
    if provider == "opus":
        if payload.get("is_error") or payload.get("subtype") != "success":
            return payload, response, "Claude did not report a successful result"
        if payload.get("permission_denials"):
            return payload, response, "Claude reported denied tool requests"
        if MODELS[provider] not in payload.get("modelUsage", {}):
            return payload, response, "Claude did not confirm the requested Opus model"
    lines = response.strip().splitlines()
    if not lines or lines[-1].strip() != marker:
        return payload, response, "Missing final completion marker (empty, partial or refused task)"
    return payload, response, None


def stop_process_tree(process: subprocess.Popen) -> None:
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
        if process.poll() is None:
            process.kill()
    else:
        process.kill()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=MODELS, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    if not 15 <= args.timeout <= 1200:
        parser.error("--timeout must be between 15 and 1200 seconds")
    command_name = "agy" if args.provider == "gemini" else "claude"
    # Never feed a prompt through a Windows .cmd/.bat shim (shell metacharacters).
    executable = shutil.which(command_name + (".exe" if sys.platform == "win32" else ""))
    if not executable:
        parser.error(f"{'agy' if args.provider == 'gemini' else 'claude'} is not on PATH")
    if args.provider == "gemini":
        try:
            roster = subprocess.run(
                [executable, "agents"], cwd=PROJECT_ROOT, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=30,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            parser.error(f"Cannot check Antigravity agent registration: {type(exc).__name__}")
        if roster.returncode or "gemini-review" not in roster.stdout.split():
            parser.error("gemini-review is not registered; run agy agents and check the agent YAML")
    prompt = args.prompt_file.resolve().read_text(encoding="utf-8-sig")
    if not prompt.strip():
        parser.error("Prompt file is empty")
    marker = f"REVIEW_COMPLETE_{uuid.uuid4().hex}"
    prompt += (
        "\n\nOnly when every requested check is complete, end the response with this exact "
        f"standalone line: {marker}\nIf blocked or incomplete, do not emit that line.\n"
    )
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = PROJECT_ROOT / "build" / "external-agents" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
    try:
        command = build_command(args.provider, executable, prompt, args.timeout)
    except ValueError as exc:
        parser.error(str(exc))
    agent_log_path = run_dir / "agent.log"
    if args.provider == "gemini":
        command[1:1] = ["--log-file", str(agent_log_path)]
    start = time.perf_counter()
    process = subprocess.Popen(
        command, cwd=PROJECT_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    hard_timeout = False
    try:
        stdout, stderr = process.communicate(
            input=prompt if args.provider == "opus" else "", timeout=args.timeout + 30
        )
    except subprocess.TimeoutExpired:
        hard_timeout = True
        stop_process_tree(process)
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired as exc:
            stdout = exc.output or ""
            stderr = exc.stderr or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            process.stdout.close()
            process.stderr.close()
    except KeyboardInterrupt:
        stop_process_tree(process)
        process.communicate(timeout=15)
        raise
    elapsed = time.perf_counter() - start
    (run_dir / "stdout.json").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.txt").write_text(stderr, encoding="utf-8")
    agent_log = agent_log_path.read_text(encoding="utf-8", errors="replace") if agent_log_path.exists() else ""
    payload, response, error = validate_result(
        args.provider, process.returncode, stdout, stderr, marker, agent_log
    )
    if hard_timeout:
        error = "Host timeout; dispatched process tree was terminated"
    if args.provider == "gemini" and not agent_log:
        error = "No Antigravity CLI log; agent/model activation cannot be verified"
    if response:
        (run_dir / "report.md").write_text(response, encoding="utf-8")
    receipt = {
        "provider": args.provider, "selected_model": MODELS[args.provider], "effort": "high",
        "agent": "gemini-review" if args.provider == "gemini" else None,
        "backend_model_label_confirmed": (
            'label="Gemini 3.8 Flash (High)"' in agent_log if args.provider == "gemini" else None
        ),
        "completed": error is None, "error": error, "returncode": process.returncode,
        "elapsed_seconds": round(elapsed, 3), "hard_timeout": hard_timeout,
        "conversation_id": payload.get("conversation_id", payload.get("session_id")),
        "usage": payload.get("usage"), "model_usage": payload.get("modelUsage"),
        "completion_marker": marker,
        "report": str(run_dir / "report.md") if response else None,
    }
    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"completed": error is None, "error": error, "receipt": str(receipt_path),
                      "report": receipt["report"]}, ensure_ascii=False))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
