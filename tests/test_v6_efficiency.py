import ast
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


def test_python_syntax():
    ast.parse(SOURCE.read_text(encoding='utf-8'))


def test_completion_protocol_has_next_step():
    mod = load_agent_module()

    class FakeCodex:
        def ask(self, prompt):
            return (
                'TASK_COMPLETE: NO\n'
                'PROGRESS: 第一步已完成\n'
                'REMAINING: 第二步未完成\n'
                'NEXT_STEP_REQUIREMENT: 完成第二步并重新验证'
            )

    agent = mod.AutonomousAgent.__new__(mod.AutonomousAgent)
    agent.state = {
        'question': '测试任务',
        'target_file': 'x.py',
        'verify_result_source': 'print(1)',
        'verify_result': 'PASS',
    }
    agent.codex = FakeCodex()
    result = agent.check_task_completion()
    assert result['complete'] is False
    assert result['next_step_requirement'] == '完成第二步并重新验证'


def test_decision_budget_never_means_done():
    mod = load_agent_module()
    agent = mod.AutonomousAgent.__new__(mod.AutonomousAgent)
    agent.state = {
        'phase': 'COMPUTER',
        'llm_decision_count': 3,
        'max_llm_decisions': 3,
        'question': 'x',
        'previous_step_result': 'x',
    }
    result = agent.ask_decision('{}')
    assert '__DECISION_BUDGET_EXHAUSTED__' in result
    assert '"TASK_CONTROL":"DONE"' not in result


def test_screenshot_is_not_returned_to_gpt():
    text = (ROOT / 'tools' / 'computer_tools.py').read_text(encoding='utf-8')
    assert 'finally:' in text
    assert 'os.remove(screenshot)' in text
    assert 'f"截图:' not in text


def test_search_path_is_deterministic_before_llm():
    text = SOURCE.read_text(encoding='utf-8')
    assert 'V6.24 DETERMINISTIC SEARCH → skip LLM' in text
    assert 'V6.24 SEARCH: deterministic action, skip decision LLM' in text


if __name__ == '__main__':
    for fn in (
        test_python_syntax,
        test_completion_protocol_has_next_step,
        test_decision_budget_never_means_done,
        test_screenshot_is_not_returned_to_gpt,
        test_search_path_is_deterministic_before_llm,
    ):
        fn()
    print('V6 efficiency regression tests: PASS')
