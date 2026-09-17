from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import json, time, traceback

@dataclass
class RunState:
    status: str = "IDLE"
    task_id: str = ""
    step: int = 0
    started_at: float = 0.0
    updated_at: float = 0.0
    last_error: str = ""
    recoveries: int = 0
    heartbeat_at: float = 0.0

class AutonomousSupervisor:
    """Bounded, resumable supervisor for long GUI/development runs."""
    def __init__(self, state_path: str | Path, max_runtime_seconds: int = 86400, max_recoveries: int = 8):
        self.state_path = Path(state_path)
        self.max_runtime_seconds = max(0.01, float(max_runtime_seconds))
        self.max_recoveries = max(0, int(max_recoveries))
        self.state = RunState()

    def load(self):
        try:
            self.state = RunState(**json.loads(self.state_path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            pass
        return self.state

    def checkpoint(self, **updates):
        for k, v in updates.items():
            if hasattr(self.state, k): setattr(self.state, k, v)
        now = time.time()
        self.state.updated_at = now
        self.state.heartbeat_at = now
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        payload = json.dumps(asdict(self.state), ensure_ascii=False, indent=2)
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            try:
                import os
                os.fsync(fh.fileno())
            except OSError:
                pass
        tmp.replace(self.state_path)

    def run(self, worker, recover=None, task_id: str = ""):
        self.load()
        now = time.time()
        # A completed/expired state is a historical run, not a reason to make a
        # fresh invocation inherit an old deadline. Only RUNNING/RECOVERING
        # states are resumable after a crash or process restart.
        task_id = str(task_id or "")
        # A persisted RUNNING state belongs to one logical task. Never resume it
        # for a different task merely because the same state file was reused.
        task_mismatch = bool(task_id and self.state.task_id and self.state.task_id != task_id)
        if self.state.status not in {"RUNNING", "RECOVERING"} or not self.state.started_at or task_mismatch:
            self.state = RunState(status="IDLE", task_id=task_id, started_at=now, updated_at=now)
        elif now - self.state.started_at >= self.max_runtime_seconds:
            self.state = RunState(status="IDLE", task_id=task_id, started_at=now, updated_at=now)
        elif task_id and not self.state.task_id:
            self.state.task_id = task_id
        self.checkpoint(status="RUNNING")
        while time.time() - self.state.started_at < self.max_runtime_seconds:
            try:
                result = worker(self.state)
                if not isinstance(result, dict):
                    self.checkpoint(status="STOP", last_error="worker must return a status dict")
                    return {"status": "STOP", "reason": "worker must return a status dict"}
                status = str(result.get("status", "")).upper()
                if status not in {"RUNNING", "DONE", "STOP", "PARTIAL"}:
                    self.checkpoint(status="STOP", last_error=f"invalid worker status: {status or '<missing>'}")
                    return {"status": "STOP", "reason": f"invalid worker status: {status or '<missing>'}"}
                if "step" in result:
                    try:
                        self.state.step = int(result["step"])
                    except (TypeError, ValueError):
                        self.checkpoint(status="STOP", last_error="worker returned invalid step")
                        return {"status": "STOP", "reason": "worker returned invalid step"}
                # A worker is not allowed to finish successfully after the
                # supervisor deadline. Check the wall clock again after the
                # worker returns; otherwise a slow worker could report DONE
                # after the allowed runtime and bypass the deadline.
                deadline_hit = time.time() - self.state.started_at >= self.max_runtime_seconds
                if deadline_hit:
                    self.checkpoint(status="STOP", last_error="runtime deadline exceeded")
                    return {"status": "STOP", "reason": "runtime deadline exceeded"}
                # Re-check the deadline after the worker returns. A worker can
                # legitimately take longer than the budget; its late DONE must
                # never be accepted as success.
                if time.time() - self.state.started_at >= self.max_runtime_seconds:
                    self.checkpoint(status="STOP", last_error="runtime deadline exceeded")
                    return {"status": "STOP", "reason": "runtime deadline exceeded"}
                if status in {"STOP", "PARTIAL"}:
                    self.checkpoint(status=status, last_error=str(result.get("reason", "")))
                    return result
                if status == "DONE":
                    self.checkpoint(status="DONE", step=self.state.step + 1, last_error="")
                    return result
                # A verified forward step resets the consecutive recovery
                # counter; otherwise unrelated transient errors can accumulate
                # for hours and terminate an otherwise healthy long run.
                if status == "RUNNING" and "step" in result:
                    self.state.recoveries = 0
                # RUNNING means the worker made progress but the task is not
                # complete. Persist the checkpoint and require another verified
                # worker iteration instead of silently declaring success.
                self.checkpoint(status="RUNNING", step=self.state.step, last_error="")
                time.sleep(0.01)
            except Exception as exc:
                self.state.recoveries += 1
                self.checkpoint(status="RECOVERING", last_error=f"{type(exc).__name__}: {exc}")
                if self.state.recoveries > self.max_recoveries or recover is None:
                    self.checkpoint(status="STOP")
                    return {"status": "STOP", "reason": self.state.last_error, "traceback": traceback.format_exc(limit=3)}
                if not recover(self.state, exc):
                    self.checkpoint(status="STOP")
                    return {"status": "STOP", "reason": self.state.last_error}
        self.checkpoint(status="STOP", last_error="runtime deadline exceeded")
        return {"status": "STOP", "reason": "runtime deadline exceeded"}
