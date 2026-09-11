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
    class FakeCodexBridge:
        def __init__(self, *args, **kwargs):
            pass

    cb.CodexBridge = FakeCodexBridge
    sys.modules['ai_agent.codex_bridge'] = cb
    v3 = types.ModuleType('v3')
    v3.__path__ = [str(ROOT / 'v3')]
    sys.modules['v3'] = v3
    spec = importlib.util.spec_from_file_location('v3.autonomous_agent', SOURCE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules['v3.autonomous_agent'] = mod
    spec.loader.exec_module(mod)
    return mod


def test_v628_explicit_desktop_commands_are_deterministic():
    mod = load_agent_module()
    agent = mod.AutonomousAgent.__new__(mod.AutonomousAgent)
    result = agent.deterministic_computer_action('点击坐标 (120, 240)，输入“hello”，按 Enter')
    assert result['ACTION'] == 'MOUSE_CLICK'
    assert result['ARGS'] == '120,240'
    assert [x['ACTION'] for x in result['ACTIONS']] == [
        'MOUSE_CLICK', 'KEYBOARD_TYPE', 'KEYBOARD_PRESS'
    ]
    assert result['ACTIONS'][1]['ARGS'] == 'hello'
    assert result['ACTIONS'][2]['ARGS'] == 'Enter'


def test_v628_unknown_gui_intent_still_escalates():
    mod = load_agent_module()
    agent = mod.AutonomousAgent.__new__(mod.AutonomousAgent)
    assert agent.deterministic_computer_action('把页面弄到最合适的位置') is None

def test_v630_r2_computer_failure_strings_are_propagated():
    """V6.30-R2-1: deterministic COMPUTER must recognize real tool failure strings."""
    text = SOURCE.read_text(encoding='utf-8')

    marker = 'if self.state.get("deterministic_computer_task"):'
    start = text.index(marker)
    block = text[start:start + 900]

    for failure_prefix in (
        "鼠标点击失败:",
        "键盘输入失败:",
        "按键失败:",
        "窗口激活失败:",
    ):
        assert failure_prefix in block, (
            f"COMPUTER failure prefix not propagated: {failure_prefix}"
        )

def test_v630_r2_failed_computer_action_cannot_complete_or_continue_queue():
    """V6.30-R2-1: a failed deterministic COMPUTER action must stop the queue."""
    source = SOURCE.read_text(encoding='utf-8')

    failure_start = source.index(
        'if self.state.get("deterministic_computer_task"):'
    )
    queue_start = source.index(
        'if self.state.get("computer_action_queue"):',
        failure_start,
    )
    completion_start = source.index(
        'if (',
        queue_start,
    )

    failure_block = source[failure_start:queue_start]
    completion_block = source[completion_start:completion_start + 1800]

    assert 'self.state["deterministic_computer_failed"] = True' in failure_block

    assert (
        'not self.state.get("deterministic_computer_failed")'
        in completion_block
    )

    assert (
        'if self.state.get("computer_action_queue")'
        in source[queue_start:queue_start + 500]
    )

    stop_start = source.index(
        'if (',
        failure_start,
    )
    stop_block = source[stop_start:queue_start]

    assert 'deterministic_computer_failed' in stop_block
    assert 'self.state["computer_action_queue"] = []' in stop_block
    assert 'self.state["phase"] = "SUMMARY"' in stop_block
    assert 'break' in stop_block



def test_v630_r2_runtime_failure_stops_queue_and_skips_llm():
    """V6.30-R2-1 runtime: real run() must stop deterministic COMPUTER queue on failure."""
    mod = load_agent_module()

    class FakeLLM:
        pass

    class FakeRouter:
        pass

    class FakeController:
        def __init__(self):
            self.calls = []

        def call(self, tool, args):
            self.calls.append((tool, args))

            # 第一个真实 COMPUTER 动作故意失败。
            if len(self.calls) == 1:
                return "按键失败: simulated"

            # 如果第二个动作被错误执行，这里直接暴露问题。
            return "UNEXPECTED_SECOND_ACTION_EXECUTED"

    agent = mod.AutonomousAgent(
        FakeLLM(),
        FakeRouter(),
    )

    fake_controller = FakeController()
    agent.controller = fake_controller

    llm_calls = []

    def fake_ask_llm(*args, **kwargs):
        llm_calls.append((args, kwargs))
        raise AssertionError(
            "R2-1 violation: Decision LLM was called after deterministic COMPUTER failure"
        )

    agent.ask_llm = fake_ask_llm

    question = (
        '请在当前浏览器中按 Ctrl+L，'
        '输入“https://example.com”，然后按 Enter'
    )

    agent.run(question)

    assert fake_controller.calls == [
        ("keyboard_press", "Ctrl+L"),
    ], (
        "R2-1 violation: queue continued after failed COMPUTER action: "
        f"{fake_controller.calls}"
    )

    assert llm_calls == [], (
        "R2-1 violation: ask_llm was called: "
        f"{llm_calls}"
    )

    assert agent.state["deterministic_computer_failed"] is True
    assert agent.state["computer_action_queue"] == []
    assert agent.state["phase"] == "SUMMARY"
    assert agent.state["task_complete"] is False
    assert agent.state.get("task_completed", False) is False
