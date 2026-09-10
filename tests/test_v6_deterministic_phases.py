from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'v3' / 'autonomous_agent.py'


def test_deterministic_phase_gate_exists():
    text = SOURCE.read_text(encoding='utf-8')
    marker = 'V6.27：开发状态机阶段动作本身已经由状态机唯一确定。'
    assert marker in text
    for phase in ('READ', 'VERIFY', 'MODIFY_PLAN', 'PLAN_VERIFY', 'MODIFY', 'VERIFY_RESULT'):
        assert f'"{phase}": "{phase}"' in text


def test_deterministic_phase_cannot_fall_through_to_decision_llm():
    text = SOURCE.read_text(encoding='utf-8')
    start = text.index('deterministic_phase_action = None')
    end = text.index('print(response)', start)
    block = text[start:end]
    assert 'skip decision LLM' in block
    assert 'elif deterministic_phase_action:' in block
    decision_start = text.index('if deterministic_search:', end)
    decision_end = text.index('elif self.state.get("phase") == "ANALYZE":', decision_start)
    decision_block = text[decision_start:decision_end]
    assert 'elif deterministic_phase_action:' in decision_block


def test_modify_still_allows_one_execution_llm_when_source_is_missing():
    text = SOURCE.read_text(encoding='utf-8')
    marker = 'V6.9 MODIFY: 使用普通 ChatGPT 已生成的完整源码'
    assert marker in text
    # The actual modify prompt remains a deliberate execution-model call.
    assert 'response = self.ask_llm(\n                        modify_prompt\n                    )' in text
