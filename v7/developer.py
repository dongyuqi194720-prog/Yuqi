from __future__ import annotations
import json, subprocess, sys, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from .reasoning import TextReasoningBudget, TextReasoningContext

@dataclass
class DevelopmentReport:
    iterations: int = 0
    tests_run: int = 0
    tests_passed: bool = False
    repairs: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    reasoner_calls: int = 0
    reasoner_time: float = 0.0

class SoftwareDevelopmentLoop:
    """Continuous local software-engineering loop with text-first GPT escalation.

    Local build/test/repair always runs first. Ordinary web GPT is an optional
    text-only reasoner, invoked only for a genuinely unclassified failure and
    only while its explicit budget remains. Screenshots are never sent.
    """
    def __init__(self, root: str | Path, max_iterations: int = 8,
                 reasoner: Callable[[str], str] | None = None,
                 reasoner_budget: int = 0, max_prompt_chars: int = 12000):
        self.root = Path(root)
        self.max_iterations = max(1, int(max_iterations))
        self.reasoner = reasoner
        self.reasoning = TextReasoningBudget(max_calls=max(0, int(reasoner_budget)))
        self.reasoner_calls = 0
        self.reasoner_time = 0.0
        self.max_prompt_chars = max_prompt_chars

    def run(self, builder, goal: str = "自主完成观察到的软件仿制项目") -> DevelopmentReport:
        started = time.monotonic(); report = DevelopmentReport()
        built_once = False
        last_failure = None
        repeated_failures = 0
        for iteration in range(1, self.max_iterations + 1):
            report.iterations = iteration
            # Never rebuild blindly: a reasoned/local patch must survive into the
            # next test iteration. Build only when the project is not yet present.
            if not built_once:
                builder.build()
                built_once = True
            ok, msg = builder.smoke_test(); report.tests_run += 1
            if ok:
                report.tests_passed = True
                report.decisions.append(f"iteration {iteration}: tests pass")
                break
            report.decisions.append(f"iteration {iteration}: {msg}")
            if msg == last_failure:
                repeated_failures += 1
            else:
                repeated_failures = 0
                last_failure = msg
            # Stop a non-progressing repair loop before it burns GPT budget.
            if repeated_failures >= 2:
                report.repairs.append("stopped repeated identical failure")
                break
            if self._repair(builder, msg, report):
                continue
            advice = self._reason(goal, builder, msg)
            if advice:
                report.decisions.append("web-gpt(text-only): " + advice[:1000])
                if self._apply_reasoned_patch(builder, advice, report):
                    continue
                report.repairs.append("text reasoning classified failure; no safe patch applied")
            break
        report.reasoner_calls = self.reasoner_calls
        report.reasoner_time = round(self.reasoner_time, 3)
        report.elapsed = round(time.monotonic() - started, 3)
        return report

    def _reason(self, goal: str, builder, msg: str) -> str:
        if not self.reasoner or not self.reasoning.allow():
            return ""
        files = [p.name for p in builder.output.glob("*")] if builder.output.exists() else []
        ctx = TextReasoningContext(
            goal=goal, phase="DEVELOP", current_state="generated replica",
            test_output=msg + "\n\n" + getattr(builder, "text_context", lambda: "")(), files=files,
            constraints=["text only", "no screenshots", "do not invent unobserved features", "suggest only verifiable next steps"],
            max_chars=self.max_prompt_chars,
        )
        prompt = ctx.render()
        started = time.monotonic(); self.reasoning.calls += 1; self.reasoner_calls += 1
        try:
            return str(self.reasoner(prompt))
        finally:
            self.reasoner_time += time.monotonic() - started

    def _apply_reasoned_patch(self, builder, advice: str, report: DevelopmentReport) -> bool:
        """Apply only a strict JSON text patch returned by the reasoner."""
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
        if not hasattr(builder, "apply_text_patch"):
            return False
        ok, msg = builder.apply_text_patch(path, content)
        if ok:
            report.repairs.append(msg)
        return ok

    def _repair(self, builder, msg: str, report: DevelopmentReport) -> bool:
        if "replica artifacts missing" in msg:
            builder.build(); report.repairs.append("rebuild missing replica artifacts"); return True
        if "HTTP smoke test failed" in msg:
            builder.build(); report.repairs.append("rebuild HTTP service"); return True
        return False
