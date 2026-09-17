from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class TextReasoningBudget:
    """Hard guard for the ordinary web-GPT decision layer.

    GUI/development execution is local by default. A caller must explicitly
    inject a text-only reasoner and a positive budget before any web-GPT call.
    Screenshots are deliberately excluded from the prompt contract.
    """
    max_calls: int = 0
    calls: int = 0
    total_seconds: float = 0.0

    def allow(self) -> bool:
        return self.calls < max(0, int(self.max_calls))

@dataclass
class TextReasoningContext:
    goal: str
    phase: str
    observations: list[str] = field(default_factory=list)
    current_state: str = ""
    action_result: str = ""
    test_output: str = ""
    files: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    max_chars: int = 12000

    def render(self) -> str:
        """Render compact text only. Never includes image bytes/paths."""
        parts = [
            f"GOAL: {self.goal}",
            f"PHASE: {self.phase}",
            "CONSTRAINTS: " + " | ".join(self.constraints),
            "CURRENT_STATE: " + self.current_state,
            "ACTION_RESULT: " + self.action_result,
            "TEST_OUTPUT: " + self.test_output,
            "OBSERVATIONS:\n" + "\n".join(self.observations[-12:]),
            "FILES:\n" + "\n".join(self.files[-40:]),
            "IMPORTANT: reason from text evidence only; do not request or expect screenshots.",
        ]
        return "\n\n".join(parts)[: self.max_chars]
