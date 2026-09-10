import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'v3' / 'autonomous_agent.py'


def load_agent_module():
    ai = types.ModuleType('ai_agent')
    ai.__path__ = [str(ROOT / 'ai_agent')]
    sys.modules['ai_agent'] = ai
    cb = types.ModuleType('ai_agent.codex_bridge')
    cb.CodexBridge = object
    sys.modules['ai_agent.codex_bridge'] = cb
    v3 = types.ModuleType('v3')
    v3.__path__ = [str(ROOT / 'v3')]
    sys.modules['v3'] = v3
    spec = importlib.util.spec_from_file_location('v3.autonomous_agent', SOURCE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['v3.autonomous_agent'] = mod
    spec.loader.exec_module(mod)
    return mod


def test_llm_metrics_are_counted_without_affecting_completion():
    mod = load_agent_module()
    agent = mod.AutonomousAgent.__new__(mod.AutonomousAgent)
    agent.state = {'llm_stats': {}}
    agent._record_llm_call('analysis', 1.25, 100, True)
    agent._record_llm_call('decision', 0.75, 50, True)
    stats = agent.get_llm_stats()
    assert stats['total_calls'] == 2
    assert stats['analysis_calls'] == 1
    assert stats['decision_calls'] == 1
    assert stats['completion_calls'] == 0
    assert stats['total_seconds'] == 2.0
    assert stats['avg_seconds'] == 1.0


if __name__ == '__main__':
    test_llm_metrics_are_counted_without_affecting_completion()
    print('V6 LLM metrics test: PASS')
