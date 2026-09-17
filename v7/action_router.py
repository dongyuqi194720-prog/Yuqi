from __future__ import annotations

from dataclasses import asdict
from .developer_protocol import DeveloperAction
from .executor import LocalExecutor
from .explorer import V7Explorer


class LocalActionRouter:
    """Route one GPT action to local tools and return text-only evidence."""

    def __init__(self, project_root):
        self.project_root = project_root
        self.executor = LocalExecutor(project_root)
        self.explorer = V7Explorer(project_root=project_root)

    @staticmethod
    def _terms(value: str) -> tuple[str, ...]:
        return tuple(x.strip() for x in str(value).split(",") if x.strip())

    @staticmethod
    def _snapshot_text(snap) -> str:
        active = snap.active_window
        active_text = ""
        if active:
            active_text = (
                f"window_id={active.window_id}; "
                f"title={active.title}; "
                f"class={active.wm_class}; "
                f"active={active.active}; "
                f"geometry={active.x},{active.y},{active.width},{active.height}"
            )

        windows = []
        for w in snap.windows:
            windows.append(
                f"window_id={w.window_id}; title={w.title}; "
                f"class={w.wm_class}; active={w.active}; "
                f"geometry={w.x},{w.y},{w.width},{w.height}"
            )

        return (
            "GUI_RESULT:\n"
            f"STABLE: {snap.stable}\n"
            f"ACTIVE_WINDOW: {active_text or '(none)'}\n"
            "WINDOWS:\n"
            + ("\n".join(windows) if windows else "(none)")
            + "\nOCR:\n"
            + (snap.ocr_text or "(empty)")
            + "\nBROWSER_TEXT:\n"
            + (snap.browser_text or "(empty)")
        )

    def execute(self, action: DeveloperAction) -> str:
        name = action.action
        args = action.arguments

        if name == "DONE":
            return "DONE: GPT declared the task complete."

        if name in {
            "LIST_FILES",
            "READ_FILE",
            "WRITE_FILE",
            "DELETE_FILE",
            "RUN_COMMAND",
        }:
            return self.executor.execute(name, **args)

        if name == "OBSERVE_GUI":
            snap = self.explorer.observe(
                reason=args.get("reason", "GPT requested GUI observation"),
                with_ocr=True,
                capture=True,
            )
            return self._snapshot_text(snap)

        if name == "OBSERVE_DESKTOP":
            snap = self.explorer.observe_desktop(
                reason=args.get("reason", "GPT requested desktop observation"),
            )
            return self._snapshot_text(snap)

        if name == "FIND_WINDOW":
            terms = self._terms(args["terms"])
            window = self.explorer.find_window(*terms)
            if not window:
                return "FIND_WINDOW_RESULT: NOT_FOUND"
            return (
                "FIND_WINDOW_RESULT: FOUND\n"
                f"window_id={window.window_id}\n"
                f"title={window.title}\n"
                f"class={window.wm_class}\n"
                f"active={window.active}\n"
                f"geometry={window.x},{window.y},{window.width},{window.height}"
            )

        if name == "WAIT_FOR_WINDOW":
            terms = self._terms(args["terms"])
            window = self.explorer.wait_for_window(
                *terms,
                timeout=float(args.get("timeout", "15")),
            )
            if not window:
                return "WAIT_FOR_WINDOW_RESULT: NOT_FOUND"
            return (
                "WAIT_FOR_WINDOW_RESULT: FOUND\n"
                f"window_id={window.window_id}\n"
                f"title={window.title}\n"
                f"class={window.wm_class}\n"
                f"active={window.active}\n"
                f"geometry={window.x},{window.y},{window.width},{window.height}"
            )

        if name == "LAUNCH_APP":
            ok, message = self.explorer.launch_app(*self._terms(args["terms"]))
            return f"LAUNCH_APP_RESULT: {'SUCCESS' if ok else 'FAILED'}\n{message}"

        if name == "ACTIVATE_WINDOW":
            window = self.explorer._find_window_by_id(args["window_id"])
            if not window:
                return "ACTIVATE_WINDOW_RESULT: FAILED\nwindow disappeared"
            ok = self.explorer.activate(window)
            return (
                "ACTIVATE_WINDOW_RESULT: "
                + ("SUCCESS" if ok else "FAILED")
                + f"\nwindow_id={window.window_id}\n"
                f"title={window.title}"
            )

        if name == "CLICK_TEXT":
            ok, message, evidence = self.explorer.click_text_local(
                args["text"]
            )
            return (
                "CLICK_TEXT_RESULT: "
                + ("SUCCESS" if ok else "FAILED")
                + f"\n{message}\n"
                f"EVIDENCE: {evidence}"
            )

        if name == "TYPE_TEXT":
            window = None
            if args.get("window_id"):
                window = self.explorer._find_window_by_id(args["window_id"])

            anchor = None
            if args.get("input_anchor"):
                parts = args["input_anchor"].split(",")
                if len(parts) == 2:
                    anchor = (int(parts[0]), int(parts[1]))

            ok, message = self.explorer.type_text_local(
                args["text"],
                window=window,
                input_anchor=anchor,
            )
            return (
                "TYPE_TEXT_RESULT: "
                + ("SUCCESS" if ok else "FAILED")
                + f"\n{message}"
            )

        return f"ERROR: unsupported action {name}"
