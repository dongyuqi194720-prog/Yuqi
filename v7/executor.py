from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


class LocalExecutor:
    """GPT 的本地手脚：执行，不做开发决策。"""

    MAX_READ_CHARS = 20000
    MAX_OUTPUT_CHARS = 12000
    MAX_WRITE_CHARS = 200000
    COMMAND_TIMEOUT = 300.0

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()

    def _path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            raise ValueError("absolute paths are not allowed")
        if ".." in path.parts:
            raise ValueError("parent traversal is not allowed")
        resolved = (self.root / path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise ValueError("path escapes project root")
        return resolved

    def _clip(self, text: str) -> str:
        if len(text) <= self.MAX_OUTPUT_CHARS:
            return text
        return text[: self.MAX_OUTPUT_CHARS] + "\n...[OUTPUT TRUNCATED]"

    def list_files(self, path: str = ".") -> str:
        target = self._path(path)
        if not target.exists():
            return f"ERROR: path does not exist: {path}"

        rows = []
        excluded = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}

        for item in sorted(target.rglob("*")):
            rel = item.relative_to(self.root)
            if any(part in excluded for part in rel.parts):
                continue
            if item.is_file():
                rows.append(str(rel))

        return "FILES:\n" + ("\n".join(rows) if rows else "(empty)")

    def read_file(self, path: str) -> str:
        target = self._path(path)
        if not target.exists():
            return f"ERROR: file does not exist: {path}"
        if not target.is_file():
            return f"ERROR: not a file: {path}"

        try:
            text = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"ERROR: file is not UTF-8 text: {path}"

        if len(text) > self.MAX_READ_CHARS:
            text = text[: self.MAX_READ_CHARS] + "\n...[FILE TRUNCATED]"

        return f"FILE: {path}\n\n{text}"

    def write_file(self, path: str, content: str) -> str:
        if len(content) > self.MAX_WRITE_CHARS:
            return "ERROR: content exceeds write limit"

        target = self._path(path)
        if target.exists() and target.is_symlink():
            return "ERROR: refusing to overwrite symlink"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"WRITE_FILE: SUCCESS\nPATH: {path}\nBYTES: {len(content.encode('utf-8'))}"

    def delete_file(self, path: str) -> str:
        target = self._path(path)
        if not target.exists():
            return f"ERROR: file does not exist: {path}"
        if not target.is_file():
            return f"ERROR: not a file: {path}"
        if target.is_symlink():
            return "ERROR: refusing to delete symlink"

        target.unlink()
        return f"DELETE_FILE: SUCCESS\nPATH: {path}"

    def run_command(self, command: str) -> str:
        try:
            argv = shlex.split(command)
        except ValueError as exc:
            return f"ERROR: invalid command syntax: {exc}"

        if not argv:
            return "ERROR: empty command"

        # Safety boundary only. The executor does not decide whether
        # the command is useful; GPT decides that.
        forbidden = {
            "mkfs",
            "fdisk",
            "parted",
            "shutdown",
            "reboot",
            "poweroff",
        }
        if argv[0] in forbidden:
            return f"ERROR: command rejected by safety policy: {argv[0]}"

        try:
            proc = subprocess.run(
                argv,
                cwd=self.root,
                text=True,
                capture_output=True,
                timeout=self.COMMAND_TIMEOUT,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return (
                "COMMAND_RESULT: TIMEOUT\n"
                f"STDOUT:\n{self._clip(str(stdout))}\n"
                f"STDERR:\n{self._clip(str(stderr))}"
            )
        except OSError as exc:
            return f"COMMAND_RESULT: EXECUTION_ERROR\nERROR: {exc}"

        return (
            f"COMMAND_RESULT: EXIT_CODE={proc.returncode}\n"
            f"STDOUT:\n{self._clip(proc.stdout)}\n"
            f"STDERR:\n{self._clip(proc.stderr)}"
        )

    def execute(self, action: str, **kwargs: str) -> str:
        action = action.strip().upper()

        try:
            if action == "LIST_FILES":
                return self.list_files(kwargs.get("path", "."))
            if action == "READ_FILE":
                return self.read_file(kwargs["path"])
            if action == "WRITE_FILE":
                return self.write_file(kwargs["path"], kwargs.get("content", ""))
            if action == "DELETE_FILE":
                return self.delete_file(kwargs["path"])
            if action == "RUN_COMMAND":
                return self.run_command(kwargs["command"])
            return f"ERROR: unknown action: {action}"
        except KeyError as exc:
            return f"ERROR: missing argument: {exc.args[0]}"
        except ValueError as exc:
            return f"ERROR: {exc}"
