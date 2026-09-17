from __future__ import annotations

import argparse
import json
from pathlib import Path

from .software_agent import SoftwareDevelopmentAgent
from .chatgpt_web import ChatGPTWebReasoner


def make_web_reasoner():
    return ChatGPTWebReasoner()


def main() -> None:
    p = argparse.ArgumentParser(description="V7 small-software development agent")
    p.add_argument("goal", nargs="+", help="development goal")
    p.add_argument("--project-root", default=".", help="project root")
    p.add_argument("--max-iterations", type=int, default=12)
    p.add_argument("--reasoner-budget", type=int, default=0)
    p.add_argument("--max-runtime", type=float, default=1800.0)
    args = p.parse_args()

    reasoner = make_web_reasoner() if args.reasoner_budget > 0 else None

    agent = SoftwareDevelopmentAgent(
        Path(args.project_root),
        reasoner=reasoner,
        max_iterations=args.max_iterations,
        reasoner_budget=args.reasoner_budget,
        max_runtime_seconds=args.max_runtime,
    )

    result = agent.run(" ".join(args.goal))
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
