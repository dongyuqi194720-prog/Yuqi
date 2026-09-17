from __future__ import annotations
import json
import re
from pathlib import Path
from .explorer import V7Explorer
from .replica import ReplicaBuilder
from .developer import SoftwareDevelopmentLoop
from .preflight import run as preflight_run
from .task_model import parse_task

class V7Agent:
    """V7 sealed controller: observe -> act -> observe -> verify, with evidence-gated exploration."""
    def __init__(self, project_root=None, max_steps=40, llm_budget=0, development_reasoner=None, development_llm_budget=0):
        self.root = Path(project_root or Path.home() / "ai_agent")
        self.explorer = V7Explorer(self.root, max_steps=max_steps, llm_budget=llm_budget)
        self.development_reasoner = development_reasoner
        self.development_llm_budget = max(0, int(development_llm_budget))

    def run(self, goal: str) -> dict:
        # Fail fast with a useful diagnostic instead of producing mysterious GUI errors.
        preflight = preflight_run()
        if not preflight["ok"]:
            return self._finish("STOP", "环境自检未通过", False, None, None, preflight=preflight)
        task = parse_task(goal)
        app = task.app
        feature = task.target or ("同心共育" if "同心共育" in goal else None)
        # 复合 GUI 任务：第一动作固定观察，不调用网页版普通 GPT。
        first = self.explorer.observe("mandatory first observation", with_ocr=False, capture=False)
        self.explorer.history[-1]["goal"] = goal
        if not first.stable:
            return self._finish("STOP", "首次观察不稳定，拒绝基于混合证据继续操作", False, None, None)
        window_terms = ("微信", "wechat") if task.app == "wechat" else (("钉钉", "dingtalk") if task.app == "dingtalk" else (task.app,))
        window = self.explorer.find_window(*window_terms)
        launch_msg = ""
        if not window:
            # The target may exist only as an unopened desktop/application icon.
            # Launch only a discovered .desktop entry, then verify the real
            # application window appears. Do not infer that a launch succeeded.
            launched, launch_msg = self.explorer.launch_app(*window_terms)
            self.explorer.step += 1
            post_launch = self.explorer.observe("post application launch observation", with_ocr=True, capture=True)
            if not launched:
                return self._finish("STOP", f"未发现{task.app}窗口；{launch_msg}", target_evidence=False)
            window = self.explorer.wait_for_window(*window_terms, timeout=15.0)
            if not window:
                return self._finish("STOP", f"{task.app}启动入口已调用，但未观察到应用窗口", target_evidence=False)
        if not self.explorer.activate(window):
            return self._finish("STOP", f"{task.app}窗口激活失败", target_evidence=False)
        self.explorer.step += 1
        second = self.explorer.observe("post activation observation", with_ocr=True, capture=True)
        if not second.stable:
            return self._finish("STOP", "激活后观察不稳定，拒绝继续操作", False, None, None)
        self.explorer.history.append({"step": self.explorer.step, "kind": "DECIDE", "decision": "search target only after fresh observation", "llm_calls": self.explorer.llm_calls})
        self.explorer.transition(first, "WINDOW_ACTIVATE", second, bool(second.active_window))

        target_evidence = bool(feature and self._contains(second, feature))
        if task.app == "wechat" and task.operation in {"find_contact", "find_contact_and_type"}:
            # WeChat contact flow: never type into an unverified field. If the
            # contact is not already visible, use only an explicitly observed
            # search affordance, then re-observe before selecting the contact.
            if not target_evidence and self.explorer.step < self.explorer.max_steps:
                search_label = next((x for x in ("搜索", "Search") if self._contains(second, x)), None)
                if search_label:
                    ok_search, search_msg = self.explorer.click_text(search_label)
                    self.explorer.step += 1
                    search_after = self.explorer.observe("post WeChat search-focus observation", with_ocr=True, capture=True)
                    self.explorer.transition(second, "CLICK_SEARCH", search_after, bool(ok_search and search_after.stable))
                    anchor = self.explorer.find_input_anchor(search_after.active_window, labels=("搜索", "Search"))
                    if anchor and self.explorer.step < self.explorer.max_steps:
                        typed, type_msg = self.explorer.type_text_local(task.contact, search_after.active_window, anchor)
                        self.explorer.step += 1
                        contact_results = self.explorer.observe("post WeChat contact search observation", with_ocr=True, capture=True)
                        self.explorer.transition(search_after, "TYPE_CONTACT", contact_results, bool(typed and contact_results.stable))
                        target_evidence = bool(typed and self._contains(contact_results, task.contact))
                        second = contact_results
                        msg = type_msg if not target_evidence else "已通过搜索证据发现联系人"
                    else:
                        msg = "未观察到可验证的微信搜索输入框，拒绝盲输入"
                else:
                    msg = "联系人未显示，且未观察到微信搜索入口"
            if target_evidence and self.explorer.step < self.explorer.max_steps:
                ok, msg = self.explorer.click_text(task.contact)
                self.explorer.step += 1
                after = self.explorer.observe("post WeChat contact selection observation", with_ocr=True, capture=True)
                verified = ok and after.stable and self._contains(after, task.contact)
                self.explorer.transition(second, "CLICK_CONTACT", after, verified)
                target_evidence = target_evidence and verified
                if target_evidence and task.operation == "find_contact_and_type" and self.explorer.step < self.explorer.max_steps:
                    input_anchor = self.explorer.find_input_anchor(after.active_window, labels=("输入消息", "发消息", "输入内容"))
                    if input_anchor is None:
                        return self._finish("STOP", "联系人已确认，但未观察到可验证的消息输入框；拒绝盲输入", True, None, None)
                    typed, type_msg = self.explorer.type_text_local(task.message, after.active_window, input_anchor)
                    self.explorer.step += 1
                    typed_after = self.explorer.observe("post WeChat message typing observation", with_ocr=True, capture=True)
                    self.explorer.transition(after, "TYPE_MESSAGE", typed_after, bool(typed and typed_after.stable and self._contains(typed_after, task.message)))
                    if not typed or not self._contains(typed_after, task.message):
                        return self._finish("STOP", f"消息输入未被后验观察确认；{type_msg}", True, None, None)
                    msg = "联系人已确认，消息已输入并通过后验观察确认"
        elif feature and target_evidence and self.explorer.step < self.explorer.max_steps:
            ok, msg = self.explorer.click_text(feature)
            self.explorer.step += 1
            after = self.explorer.observe("post target click observation", with_ocr=True, capture=True)
            verified = ok and self._meaningful_transition(second, after, feature)
            self.explorer.transition(second, "CLICK_TEXT_LOCAL", after, verified)
            target_evidence = target_evidence and ok and verified
            # Do not perform unsolicited follow-up clicks after a verified target action.
        elif feature:
            msg = "目标文字未在观察证据中确认，未盲点"
        else:
            msg = "未指定业务目标"

        # Do not fabricate a replica when the real target was never confirmed.
        # Evidence first; development starts only after the target interaction is verified.
        if not target_evidence:
            return self._finish("STOP", f"{msg}; 未确认目标已打开，停止开发以避免凭空仿制", False, None, None)

        builder = ReplicaBuilder(self.explorer.model.to_dict())
        dev = SoftwareDevelopmentLoop(builder.output, max_iterations=8, reasoner=self.development_reasoner, reasoner_budget=self.development_llm_budget)
        dev_report = dev.run(builder, goal=goal)
        replica = builder.output
        test_ok = dev_report.tests_passed
        status = "DONE" if test_ok else "PARTIAL"
        result_reason = msg if test_ok else f"{msg}; development loop did not converge"
        result = self._finish(status, result_reason, target_evidence, replica, test_ok)
        result["development"] = {
            "iterations": dev_report.iterations,
            "tests_run": dev_report.tests_run,
            "tests_passed": dev_report.tests_passed,
            "repairs": dev_report.repairs,
            "decisions": dev_report.decisions,
            "elapsed": dev_report.elapsed,
            "reasoner_calls": dev.reasoner_calls,
            "reasoner_time": dev.reasoner_time,
        }
        print(json.dumps({"development": result["development"]}, ensure_ascii=False, indent=2))
        return result

    @staticmethod
    def _meaningful_transition(before, after, text, expected_markers=None):
        """Strict post-action verification. Ambiguity is a failure, not success."""
        if not after.active_window or not before.active_window:
            return False
        if not V7Explorer._same_window(after.active_window, before.active_window):
            return False
        def norm(value):
            return re.sub(r"\s+", "", str(value or "")).casefold()
        before_text = norm(f"{before.ocr_text}\n{before.browser_text}")
        after_text = norm(f"{after.ocr_text}\n{after.browser_text}")
        if not before_text or not after_text or before_text == after_text:
            return False
        before_tokens = {t for t in re.split(r"[^\w\u3400-\u9fff]+", before_text) if t}
        after_tokens = {t for t in re.split(r"[^\w\u3400-\u9fff]+", after_text) if t}
        if len(before_tokens.symmetric_difference(after_tokens)) < 2:
            return False
        markers = [norm(x) for x in (expected_markers or ()) if norm(x)]
        if not markers and text:
            markers = [norm(text)]
        # The destination must provide explicit expected evidence. A generic
        # fingerprint/text delta is never sufficient because it can be a wrong
        # neighboring page (e.g. OA approval).
        return any(m in after_text or any(m in norm(e) for e in after.browser_elements) for m in markers)

    @staticmethod
    def _target_reached(snap, text):
        if not text:
            return False
        hay = f"{snap.ocr_text}\n{snap.browser_text}".casefold()
        # A post-click observation must still provide evidence of the target;
        # a successful low-level click alone is not task completion.
        return text.casefold() in hay or any(text.casefold() in str(e).casefold() for e in snap.browser_elements)

    @staticmethod
    def _contains(snap, text):
        def norm(value):
            return re.sub(r"\s+", "", str(value or "")).casefold()
        hay = norm(f"{snap.ocr_text}\n{snap.browser_text}")
        return norm(text) in hay

    def _safe_explore(self, snap):
        # Only navigation-like labels are considered. Never click arbitrary OCR text.
        safe_labels = ("首页", "工作台", "应用", "更多", "返回", "菜单", "家校", "同心共育")
        for label in safe_labels:
            if self.explorer.step >= self.explorer.max_steps:
                break
            if label.casefold() not in snap.ocr_text.casefold():
                continue
            ok, _ = self.explorer.click_text(label)
            self.explorer.step += 1
            after = self.explorer.observe(f"safe exploration: {label}", with_ocr=True, capture=True)
            self.explorer.transition(snap, f"CLICK_TEXT_LOCAL:{label}", after, ok and self._meaningful_transition(snap, after, label))
            snap = after

    def _finish(self, status, reason, target_evidence, replica=None, replica_test=None, preflight=None):
        result = {
            "status": status,
            "reason": reason,
            "target_evidence": bool(target_evidence),
            "pages": len(self.explorer.model.pages),
            "navigation_edges": len(self.explorer.model.edges),
            "observations": len(self.explorer.snapshots),
            "replica": str(replica) if replica is not None else None,
            "replica_test": replica_test,
            "timings": self.explorer.timings,
            "llm_calls_total": self.explorer.llm_calls,
            "llm_calls_gui": self.explorer.llm_calls,
            "llm_budget": self.explorer.llm_budget,
            "llm_time_total": round(self.explorer.llm_time_total, 3),
            "history": self.explorer.history,
            "preflight": preflight,
            "safety": {"irreversible_actions_blocked": True, "screenshots_to_web_gpt": False, "typing_content_not_blocked": True},
            "vision": {"enabled": self.explorer.vision.enabled, "model": self.explorer.vision.model, "calls": self.explorer.vision.calls, "failures": self.explorer.vision.failures},
            "task": parse_task(self.explorer.history[0].get("goal", "")) .to_dict() if self.explorer.history and self.explorer.history[0].get("goal") else {},
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return result

def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="194720-v7",
        description="V7 real-GUI agent: observe, act, verify, and develop only from observed evidence.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="7.1.2-vision",
    )
    parser.add_argument(
        "goal",
        nargs="*",
        help="业务目标；未指定时使用默认安全观察目标。",
    )
    args = parser.parse_args()
    goal = " ".join(args.goal).strip() or "请自主观察当前电脑，打开钉钉，找到同心共育并观察。"
    V7Agent().run(goal)

if __name__ == "__main__":
    main()
