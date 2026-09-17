from __future__ import annotations

# These are destructive BUSINESS ACTIONS, not words that are inherently unsafe
# to type.  A user may legitimately need to type a message containing “发送”
# or “付款”; blocking keyboard text because of the content would violate the
# requirement to enter information accurately.
BLOCKED_ACTIONS = {
    "CLICK_TEXT_LOCAL", "BROWSER_CLICK_TEXT", "MOUSE_CLICK",
}
BLOCKED_TARGETS = (
    "发送", "发布", "删除", "支付", "付款", "转账", "提现",
    "提交", "确认订单", "确定付款", "永久删除", "同意并提交",
)
OBSERVATION_ACTIONS = {"WINDOW_LIST", "WINDOW_ACTIVATE", "OBSERVE_WINDOW", "OBSERVE_DESKTOP", "BROWSER_STATE", "BROWSER_TEXT", "BROWSER_ELEMENTS"}
SAFE_INTERACTION_ACTIONS = {"CLICK_TEXT_LOCAL", "BROWSER_CLICK_TEXT", "MOUSE_CLICK", "KEYBOARD_PRESS", "KEYBOARD_TYPE", "TEXT_TYPE"}

def is_blocked(action: str, args: str = "") -> bool:
    action_u = str(action or "").upper()
    if action_u not in BLOCKED_ACTIONS:
        return False
    text = str(args or "").casefold()
    return any(word.casefold() in text for word in BLOCKED_TARGETS)

def action_allowed(action: str, args: str = "") -> bool:
    action_u = str(action or "").upper()
    return action_u in OBSERVATION_ACTIONS | SAFE_INTERACTION_ACTIONS | {"STOP", "DONE"} and not is_blocked(action_u, args)

def reversible_target(text: str) -> bool:
    return not is_blocked("CLICK_TEXT_LOCAL", text)

def typing_allowed(text: str) -> bool:
    # Content is not an action. This deliberately permits arbitrary message
    # text; sending/submitting remains a separate, policy-gated click action.
    return action_allowed("TEXT_TYPE", text)
