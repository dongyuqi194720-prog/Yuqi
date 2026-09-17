from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .reasoning import TextReasoningBudget, TextReasoningContext


SAFE_TEST_PREFIXES = (
    ("pytest",),
    ("python", "-m", "pytest"),
    ("python3", "-m", "pytest"),
    ("python", "-m", "unittest"),
    ("python3", "-m", "unittest"),
)
DEFAULT_TEST_COMMANDS = (
    ("python", "-m", "pytest", "-q"),
    ("python3", "-m", "pytest", "-q"),
)


@dataclass
class DevelopmentTask:
    goal: str
    project_root: Path
    test_command: tuple[str, ...] | None = None
    max_iterations: int = 12
    max_reasoner_calls: int = 6
    max_runtime_seconds: float = 1800.0


@dataclass
class DevelopmentResult:
    status: str = "STOP"
    goal: str = ""
    iterations: int = 0
    tests_run: int = 0
    tests_passed: bool = False
    repairs: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    reasoner_calls: int = 0
    elapsed: float = 0.0
    checkpoint: str = ""


class ProjectWorkspace:
    """Evidence-first, confined workspace for small software tasks."""

    EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def exists(self) -> bool:
        return self.root.is_dir()

    def inventory(self, limit: int = 120) -> list[str]:
        if not self.exists():
            return []
        out = []
        for p in sorted(self.root.rglob("*")):
            if any(part in self.EXCLUDED for part in p.parts):
                continue
            if p.is_file():
                try:
                    rel = p.relative_to(self.root).as_posix()
                except ValueError:
                    continue
                out.append(rel)
                if len(out) >= limit:
                    break
        return out

    def text_context(self, max_chars: int = 14000) -> str:
        chunks = []
        candidates = [
            "README.md", "pyproject.toml", "setup.py", "requirements.txt",
            "package.json", "Makefile",
        ]
        files = [self.root / x for x in candidates if (self.root / x).is_file()]
        files += [self.root / x for x in self.inventory(80) if x.endswith((".py", ".js", ".ts", ".json", ".toml"))][:20]
        seen = set()
        for path in files:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            chunks.append(f"FILE: {path.relative_to(self.root).as_posix()}\n{text[:4000]}")
        return "\n\n".join(chunks)[:max_chars]

    def safe_write(self, relative_path: str, content: str) -> tuple[bool, str]:
        rel = Path(str(relative_path))
        if rel.is_absolute() or not rel.parts or ".." in rel.parts:
            return False, "unsafe patch path"
        if len(content.encode("utf-8")) > 200_000:
            return False, "patch too large"
        target = (self.root / rel).resolve()
        if self.root not in target.parents:
            return False, "patch escapes project root"
        if target.exists() and target.is_symlink():
            return False, "refusing to overwrite symlink"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return True, f"patched {rel.as_posix()}"

    def changed_files(self) -> list[str]:
        if not (self.root / ".git").exists():
            return []
        try:
            r = subprocess.run(
                ["git", "-C", str(self.root), "status", "--short"],
                capture_output=True, text=True, timeout=10, check=False,
            )
            return [x[3:].strip() if len(x) > 3 else x.strip() for x in r.stdout.splitlines() if x.strip()]
        except (OSError, subprocess.SubprocessError):
            return []


def _safe_test_command(command: tuple[str, ...]) -> bool:
    if not command:
        return False
    c = tuple(str(x) for x in command)
    return any(c[:len(prefix)] == prefix for prefix in SAFE_TEST_PREFIXES)


def run_test(root: Path, command: tuple[str, ...], timeout: float = 300.0) -> tuple[bool, str]:
    if not _safe_test_command(command):
        return False, "unsafe test command rejected"
    try:
        p = subprocess.run(
            list(command), cwd=str(root), capture_output=True, text=True,
            timeout=max(1.0, timeout), check=False,
        )
        output = (p.stdout + "\n" + p.stderr).strip()
        output = output[-12000:]
        return p.returncode == 0, output or f"exit={p.returncode}"
    except subprocess.TimeoutExpired:
        return False, "test timeout"
    except OSError as exc:
        return False, f"test execution error: {exc}"


class SoftwareDevelopmentAgent:
    """Long-running small-software development controller.

    Flow:
      inspect -> plan -> patch -> test -> diagnose -> patch -> regression -> finish
    The reasoner is text-only and every write is confined to project_root.
    """

    def __init__(
        self,
        root: str | Path,
        reasoner: Callable[[str], str] | None = None,
        max_iterations: int = 12,
        reasoner_budget: int = 6,
        max_runtime_seconds: float = 1800.0,
        checkpoint_path: str | Path | None = None,
    ):
        self.workspace = ProjectWorkspace(root)
        self.reasoner = reasoner
        self.reasoning = TextReasoningBudget(max_calls=max(0, int(reasoner_budget)))
        self.max_iterations = max(1, int(max_iterations))
        self.max_runtime_seconds = max(1.0, float(max_runtime_seconds))
        self.checkpoint_path = Path(checkpoint_path or self.workspace.root / ".v7-development-state.json")
        self.started = 0.0

    def run(self, goal: str, test_command: tuple[str, ...] | None = None) -> DevelopmentResult:
        """ChatGPT web decides; LocalActionRouter executes deterministic actions."""
        from .action_router import LocalActionRouter
        from .developer_protocol import parse_action

        self.started = time.monotonic()
        result = DevelopmentResult(goal=goal)

        if not self.workspace.exists():
            result.status = "STOP"
            result.decisions.append("project root does not exist")
            return self._finish(result)

        router = LocalActionRouter(self.workspace.root)

        next_prompt = (
            "你是软件开发项目的 GPT 大脑。\n"
            f"用户目标：{goal}\n\n"
            "Local Agent 是执行器和传感器，不负责开发决策。\n"
            "你负责理解目标、检查项目、读取和修改文件、运行命令和测试、分析真实结果，并决定下一步。\n"
            "Local Agent 会直接执行你返回的 ACTION，并把真实文本结果返回给你。\n\n"
            "合法 ACTION：LIST_FILES, READ_FILE, WRITE_FILE, DELETE_FILE, RUN_COMMAND, "
            "OBSERVE_GUI, OBSERVE_DESKTOP, FIND_WINDOW, WAIT_FOR_WINDOW, LAUNCH_APP, "
            "ACTIVATE_WINDOW, CLICK_TEXT, TYPE_TEXT, DONE。\n"
            "每次只能返回一个 ACTION。\n"
            "需要参数时按 ACTION 协议字段提供。\n"
            "不要输出 Markdown 代码围栏。\n"
            "不要假设没有观察到的文件、程序状态或 GUI 状态。\n"
            "确定性动作直接交给 Local Agent 执行，不调用额外 LLM。\n"
            "只有你自己需要进行判断时才进行推理。\n"
            "如果目标已经真正完成，返回 ACTION: DONE。"
        )

        for iteration in range(1, self.max_iterations + 1):
            if self._deadline():
                result.status = "PARTIAL"
                result.repairs.append("resource limit: runtime deadline reached")
                break

            if not self.reasoner or not self.reasoning.allow():
                result.status = "PARTIAL"
                result.repairs.append("resource limit: reasoner budget exhausted")
                break

            result.iterations = iteration
            result.checkpoint = f"GPT_ACTION_{iteration}"
            self.reasoning.calls += 1
            result.reasoner_calls += 1

            try:
                response = str(self.reasoner(next_prompt)).strip()
            except Exception as exc:
                result.status = "PARTIAL"
                result.failures.append(
                    f"reasoner error: {type(exc).__name__}: {exc}"
                )
                break

            if not response:
                result.status = "PARTIAL"
                result.failures.append("GPT returned empty response")
                break

            try:
                action = parse_action(response)
            except Exception as exc:
                result.status = "PARTIAL"
                result.failures.append(
                    f"invalid GPT action: {type(exc).__name__}: {exc}"
                )
                break

            result.decisions.append(
                f"iteration {iteration}: GPT ACTION {action.action}"
            )

            if action.action == "DONE":
                result.status = "DONE"
                result.checkpoint = f"GPT_DONE_{iteration}"
                result.decisions.append(
                    f"iteration {iteration}: GPT declared task complete"
                )
                break

            try:
                evidence = router.execute(action)
            except Exception as exc:
                evidence = (
                    f"LOCAL_EXECUTION_ERROR: {type(exc).__name__}: {exc}"
                )

            result.checkpoint = f"LOCAL_RESULT_{iteration}"
            self._checkpoint(result)

            next_prompt = (
                "这是 Local Agent 对你上一条 ACTION 的真实执行结果。\n"
                "请仅依据这个结果以及当前 ChatGPT 对话上下文决定下一步。\n"
                "如果任务尚未完成，返回一个且仅一个合法 ACTION；"
                "如果已经完成，返回 ACTION: DONE。\n\n"
                "LOCAL_RESULT:\n"
                f"{evidence}"
            )

            if self._deadline():
                result.status = "PARTIAL"
                result.repairs.append("resource limit: runtime deadline reached")
                break

        if result.status == "STOP" and result.reasoner_calls:
            result.status = "PARTIAL"

        return self._finish(result)

    def _discover_test_command(self, goal: str = "") -> tuple[str, ...]:
        goal_text = str(goal).lower()

        # If the requested goal explicitly asks for pytest/tests,
        # prefer pytest even when the project is currently empty.
        test_intent = any(
            keyword in goal_text
            for keyword in ("pytest", "测试", "test")
        )

        if test_intent:
            return DEFAULT_TEST_COMMANDS[0]

        if (self.workspace.root / "pytest.ini").exists() or (self.workspace.root / "tests").is_dir():
            return DEFAULT_TEST_COMMANDS[0]
        if (self.workspace.root / "pyproject.toml").exists():
            return DEFAULT_TEST_COMMANDS[0]
        return ("python", "-m", "unittest")

    def _reason(self, goal: str, phase: str, test_output: str, result: DevelopmentResult) -> str:
        if not self.reasoner or not self.reasoning.allow() or self._deadline():
            return ""
        ctx = TextReasoningContext(
            goal=goal,
            phase=phase,
            current_state="small-software development workspace",
            action_result="",
            test_output=test_output,
            observations=[
                "The controller must plan and modify only the supplied project.",
                "A successful test run is required before DONE.",
                "Use the smallest verifiable change.",
                "If the goal explicitly requires tests or pytest, the test file is part of the requested deliverable.",
                "If pytest reports 'no tests ran', treat that as missing tests, not as a successful implementation.",
                "When the required business code already exists and tests are missing, create the appropriate test file instead of rewriting the already-satisfied business code.",
                "Do not repeat an identical WRITE_FILE change when the previous change did not address the reported test failure.",
            ],
            files=self.workspace.inventory(100),
            constraints=[
                "text only",
                "no screenshots",
                "do not invent files or dependencies unless required by the goal",
                "write only inside project root",
                "return exactly one JSON object: {\"action\":\"WRITE_FILE\",\"path\":\"...\",\"content\":\"...\"}",
            ],
            max_chars=16000,
        )
        prompt = ctx.render() + "\n\nPROJECT CONTEXT:\n" + self.workspace.text_context(9000)
        self.reasoning.calls += 1
        result.reasoner_calls += 1
        try:
            return str(self.reasoner(prompt))
        except Exception as exc:
            result.decisions.append(f"reasoner error: {type(exc).__name__}: {exc}")
            return ""

    def _apply_patch(self, advice: str, result: DevelopmentResult) -> bool:
        raw = advice.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        try:
            data = json.loads(raw)
        except Exception:
            return False
        if data.get("action") != "WRITE_FILE":
            return False
        path = data.get("path")
        content = data.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return False

        # Models sometimes put Markdown code fences inside the file content.
        # Remove only an outer fence and preserve the actual source code.
        stripped = content.strip()
        if stripped.startswith("```") and stripped.endswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].strip().startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines) + ("\n" if lines else "")

        ok, msg = self.workspace.safe_write(path, content)
        if ok:
            result.repairs.append(msg)
        return ok

    def _deadline(self) -> bool:
        return bool(self.started and time.monotonic() - self.started >= self.max_runtime_seconds)

    def _checkpoint(self, result: DevelopmentResult) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "goal": result.goal,
            "status": result.status,
            "checkpoint": result.checkpoint,
            "iterations": result.iterations,
            "tests_run": result.tests_run,
            "reasoner_calls": result.reasoner_calls,
            "updated_at": time.time(),
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.checkpoint_path)

    def _finish(self, result: DevelopmentResult) -> DevelopmentResult:
        result.changed_files = self.workspace.changed_files()
        result.elapsed = round(time.monotonic() - self.started, 3) if self.started else 0.0
        self._checkpoint(result)
        return result
