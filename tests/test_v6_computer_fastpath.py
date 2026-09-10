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
