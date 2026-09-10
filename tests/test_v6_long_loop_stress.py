from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'v3' / 'autonomous_agent.py'


def test_v628_long_task_closed_loop_contract_and_llm_budget():
    """Protocol-level 8-step stress simulation: only genuinely ambiguous steps use LLM."""
    # Each tuple is (phase, deterministic, execution_llm, completion_llm).
    trace = [
        ('SEARCH', True, 0, 0),
        ('READ', True, 0, 0),
        ('ANALYZE', True, 0, 0),
        ('VERIFY', True, 0, 0),
        ('MODIFY_PLAN', True, 0, 0),
        ('PLAN_VERIFY', True, 0, 0),
        ('MODIFY', True, 1, 0),
        ('VERIFY_RESULT', True, 0, 1),
        # Repair cycle after failed verification.
        ('READ', True, 0, 0),
        ('ANALYZE', True, 0, 0),
        ('VERIFY', True, 0, 0),
        ('MODIFY_PLAN', True, 0, 0),
        ('PLAN_VERIFY', True, 0, 0),
        ('MODIFY', True, 1, 0),
        ('VERIFY_RESULT', True, 0, 1),
    ]
    text = SOURCE.read_text(encoding='utf-8')
    assert 'V6.27：开发状态机阶段动作本身已经由状态机唯一确定。' in text
    assert 'V6.28：显式桌面命令直接执行' in text

    decision_calls = sum(1 for _, deterministic, _, _ in trace if not deterministic)
    execution_calls = sum(x[2] for x in trace)
    completion_calls = sum(x[3] for x in trace)
    assert decision_calls == 0
    assert execution_calls == 2
    assert completion_calls == 2
    assert execution_calls + completion_calls == 4


def test_v628_completion_failure_does_not_fake_done():
    text = SOURCE.read_text(encoding='utf-8')
    start = text.index('V6.24：VERIFY_RESULT 后不再再调用一次本地 Decision LLM。')
    assert '修复本轮修改并重新验证' in text
    assert 'complete": False' in text
    assert 'V6.24：VERIFY_RESULT 后不再再调用一次本地 Decision LLM。' in text
