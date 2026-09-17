from __future__ import annotations
from dataclasses import dataclass, asdict
import re

@dataclass(frozen=True)
class TaskSpec:
    goal: str
    app: str
    operation: str
    target: str = ""
    contact: str = ""
    message: str = ""
    confidence: float = 0.0

    def to_dict(self):
        return asdict(self)

def parse_task(goal: str) -> TaskSpec:
    text = str(goal or "").strip()
    low = text.casefold()
    app = "wechat" if any(k in low for k in ("微信", "wechat")) else ("dingtalk" if any(k in low for k in ("钉钉", "dingtalk")) else "desktop")
    contact = ""
    message = ""
    # Common explicit forms. Keep contact/message boundaries deterministic.
    patterns = [
        r'(?:发送给|发给|给)\s*[“\"]([^“”\"]+)[”\"]\s*(?:发|发送|说|消息)?\s*[“\"]([^”\"]+)[”\"]',
        r'(?:发送给|发给|给)\s*([^：:，,。；;]+?)\s*(?:发|发送|说|消息)\s*[:：]\s*(.+)$',
        r'(?:发送给|发给|给)\s*([^：:，,。；;]+?)\s*[:：]\s*(.+)$',
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            contact = m.group(1).strip()
            message = m.group(2).strip()
            break
    if not contact:
        m = re.search(r'(?:联系人|contact)\s*[=:：]\s*([^,，;；]+)', text, re.I)
        if m: contact = m.group(1).strip()
    if not message:
        m = re.search(r'(?:消息|message)\s*[=:：]\s*(.+)$', text, re.I)
        if m: message = m.group(1).strip()
    if app == "wechat" and contact:
        operation = "find_contact_and_type" if message else "find_contact"
        conf = 0.9
    elif "同心共育" in text:
        operation, conf = "find_target", 0.95
    else:
        operation, conf = "observe", 0.7
    target = "同心共育" if operation == "find_target" else contact
    return TaskSpec(text, app, operation, target, contact, message, conf)
