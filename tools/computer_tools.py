from langchain_core.tools import tool
import os
import subprocess
from pathlib import Path
from tools.gui_observer import observe_window, capture_window
from tools.vision_gateway import vision_observe
from tools.ocr_observer import observe_text_boxes


@tool
def run_command(cmd: str):
    """
    执行Linux终端命令
    """
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120
        )

        return (
            "stdout:\n"
            + result.stdout
            + "\n\nstderr:\n"
            + result.stderr
        )

    except Exception as e:
        return f"执行失败: {e}"


@tool
def write_file(path: str, content: str):
    """
    写入文件
    """
    try:
        path=os.path.expanduser(path)

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as f:
            f.write(content)

        return f"文件写入成功: {path}"

    except Exception as e:
        return f"写入失败: {e}"


@tool
def vscode_open(path: str):
    """
    使用VS Code打开文件
    """
    try:
        path=os.path.expanduser(path)

        subprocess.Popen(
            [
                "code",
                path
            ]
        )

        return f"已打开: {path}"

    except Exception as e:
        return f"打开失败: {e}"


@tool
def mouse_move(x: int, y: int):
    """移动系统鼠标到指定屏幕坐标。"""
    try:
        subprocess.run(
            ["xdotool", "mousemove", str(x), str(y)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return f"鼠标已移动到: ({x}, {y})"
    except Exception as e:
        return f"鼠标移动失败: {e}"


@tool
def mouse_click(button: int = 1, clicks: int = 1):
    """执行系统鼠标点击。button 1=左键，2=中键，3=右键。"""
    try:
        for _ in range(max(1, clicks)):
            subprocess.run(
                ["xdotool", "click", str(button)],
                check=True,
                capture_output=True,
                text=True,
                timeout=10
            )
        return f"鼠标点击完成: button={button}, clicks={clicks}"
    except Exception as e:
        return f"鼠标点击失败: {e}"


@tool
def keyboard_type(text: str):
    """向当前活动窗口输入文本。"""
    try:
        subprocess.run(
            ["xdotool", "type", "--clearmodifiers", "--", text],
            check=True,
            capture_output=True,
            text=True,
            timeout=30
        )
        return "键盘输入完成"
    except Exception as e:
        return f"键盘输入失败: {e}"


@tool
def keyboard_press(key: str):
    """向当前活动窗口发送一个键盘按键，例如 Return、Tab、Escape、ctrl+c。"""
    try:
        subprocess.run(
            ["xdotool", "key", "--clearmodifiers", key],
            check=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return f"按键完成: {key}"
    except Exception as e:
        return f"按键失败: {e}"


@tool
def window_list(request: str = ""):
    """列出当前桌面窗口。"""
    try:
        result = subprocess.run(
            ["wmctrl", "-l"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip() or "当前没有检测到窗口"
    except Exception as e:
        return f"窗口列表获取失败: {e}"


@tool
def window_activate(window_id: str):
    """V6.29-R3.2-R2：本地解析窗口 ID/标题后激活，不调用 LLM。"""
    try:
        target = str(window_id).strip()

        # 真实 wmctrl window_id：直接执行。
        if target.lower().startswith("0x"):
            subprocess.run(
                ["wmctrl", "-i", "-a", target],
                check=True,
                capture_output=True,
                text=True,
                timeout=10
            )
            return f"窗口已激活: {target}"

        # 非 ID：本地读取窗口列表并按标题/应用关键词匹配。
        result = subprocess.run(
            ["wmctrl", "-l"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        lines = [
            line.strip()
            for line in result.stdout.splitlines()
            if line.strip()
        ]

        target_lower = target.lower()

        # V6.29-R3.2-R3：确定性候选排序。
        # 不调用 LLM；多个浏览器窗口时优先真正的浏览器窗口。
        def window_score(line):
            low = line.lower()
            score = 0

            # 精确目标字符串最高优先级。
            if target_lower and target_lower in low:
                score += 100

            # 真正浏览器应用优先于其他带“浏览器”字样的窗口。
            browser_app_keys = (
                "chromium",
                "google chrome",
                "chrome",
                "firefox",
                "microsoft edge",
                "edge",
            )
            for key in browser_app_keys:
                if key in low:
                    score += 80
                    break

            # 中文“浏览器”作为较低优先级兜底。
            if "浏览器" in low or "browser" in low:
                score += 20

            # 桌面/面板等明显非目标窗口降权。
            non_target_keys = (
                "panel",
                "桌面",
                "desktop",
            )
            if any(key in low for key in non_target_keys):
                score -= 100

            return score

        candidates = sorted(
            lines,
            key=window_score,
            reverse=True
        )

        # 只有确实存在匹配候选时才继续。
        if not candidates or window_score(candidates[0]) <= 0:
            return f"窗口激活失败：未找到窗口 {target}"

        # wmctrl -l 格式：
        # 0x00123456 desktop host title...
        parts = candidates[0].split(None, 3)
        if not parts or not parts[0].lower().startswith("0x"):
            return f"窗口激活失败：无法解析窗口 ID {candidates[0]}"

        resolved_id = parts[0]
        title = parts[3] if len(parts) >= 4 else candidates[0]

        subprocess.run(
            ["wmctrl", "-i", "-a", resolved_id],
            check=True,
            capture_output=True,
            text=True,
            timeout=10
        )

        print(
            "V6.29-R3.2-R2 WINDOW RESOLVE:",
            target,
            "→",
            resolved_id,
            title
        )

        return f"窗口已激活: {resolved_id} ({title})"

    except Exception as e:
        return f"窗口激活失败: {e}"


@tool
def click_text_local(target: str, window_query: str = "browser"):
    """
    V6.29-R3.3-B：
    本地 OCR 文字定位 → 窗口坐标转换 → 桌面绝对坐标点击。

    不调用 GPT。
    截图只作为本地临时计算工件，完成后立即删除。
    """
    screenshot = None

    try:
        target = str(target).strip()
        window_query = str(window_query).strip()

        if not target:
            return "CLICK_TEXT_LOCAL_FAILED: empty target"

        window = observe_window(window_query)

        if not window:
            return (
                "CLICK_TEXT_LOCAL_FAILED: "
                f"window not found: {window_query}"
            )

        # V6.29-R3.3-C：
        # OCR 点击前先显式激活目标顶层窗口。
        window_id = str(window.get("window_id", "")).strip()

        if window_id:
            result = subprocess.run(
                ["wmctrl", "-i", "-a", window_id],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return (
                    "CLICK_TEXT_LOCAL_FAILED: "
                    f"window_activate: {result.stderr.strip()}"
                )

        # 激活后重新截图，确保 OCR 使用的是当前窗口状态。
        if window_id:
            screenshot_path = window.get("screenshot")
            if screenshot_path:
                try:
                    Path(screenshot_path).unlink()
                except OSError:
                    pass

            capture_window(window_id, "/tmp/v6_window_click.png")
            window["screenshot"] = "/tmp/v6_window_click.png"

        screenshot = window.get("screenshot")

        if not screenshot or not Path(screenshot).exists():
            return "CLICK_TEXT_LOCAL_FAILED: screenshot unavailable"

        boxes = observe_text_boxes(screenshot)

        target_lower = target.lower()

        # ----------------------------------------------------
        # V6.29-R3.3-D：
        # OCR 多 box 文本拼接匹配。
        #
        # 例如 OCR 可能把：
        #   添加快捷方式
        # 拆成：
        #   添加 / 快捷 / 方式
        #
        # 精确匹配和单 box 子串匹配保持优先；
        # 只有前两者都失败时，才尝试同一行的连续 OCR box。
        # ----------------------------------------------------

        # 1. 精确匹配优先
        matches = [
            box for box in boxes
            if str(box.get("text", "")).strip().lower()
            == target_lower
        ]

        # 2. 单 box 子串匹配 fallback
        if not matches:
            matches = [
                box for box in boxes
                if target_lower in str(
                    box.get("text", "")
                ).strip().lower()
            ]

        if matches:
            box = matches[0]

            local_x = int(box["center_x"])
            local_y = int(box["center_y"])

        else:
            # 3. 多 box 连续文本匹配
            #
            # 先过滤空文本，并按视觉阅读顺序排序。
            valid_boxes = [
                box for box in boxes
                if str(box.get("text", "")).strip()
            ]

            valid_boxes.sort(
                key=lambda b: (
                    int(b.get("y", b.get("center_y", 0))),
                    int(b.get("x", b.get("center_x", 0))),
                )
            )

            combined_match = None

            for start_index, start_box in enumerate(valid_boxes):
                start_text = str(
                    start_box.get("text", "")
                ).strip()

                if not start_text:
                    continue

                current_text = start_text.lower()
                group = [start_box]

                if target_lower.startswith(current_text):
                    for next_box in valid_boxes[start_index + 1:]:
                        prev = group[-1]

                        prev_x = int(prev.get(
                            "x", prev.get("center_x", 0)
                        ))
                        prev_y = int(prev.get(
                            "y", prev.get("center_y", 0)
                        ))
                        prev_w = int(prev.get(
                            "width", 0
                        ))
                        prev_h = int(prev.get(
                            "height", 0
                        ))

                        next_x = int(next_box.get(
                            "x", next_box.get("center_x", 0)
                        ))
                        next_y = int(next_box.get(
                            "y", next_box.get("center_y", 0)
                        ))

                        next_text = str(
                            next_box.get("text", "")
                        ).strip()

                        if not next_text:
                            continue

                        # 必须基本处于同一视觉行。
                        y_tolerance = max(
                            12,
                            min(prev_h, int(
                                next_box.get("height", 0)
                            )) + 4,
                        )

                        if abs(next_y - prev_y) > y_tolerance:
                            break

                        # 必须从左到右，允许 OCR box 有少量间隙。
                        gap = next_x - (prev_x + prev_w)

                        if gap > 40:
                            break

                        candidate = (
                            current_text
                            + next_text.lower()
                        )

                        # 当前拼接结果已经不可能成为目标前缀。
                        if not target_lower.startswith(candidate):
                            break

                        group.append(next_box)
                        current_text = candidate

                        if current_text == target_lower:
                            combined_match = group
                            break

                    if combined_match:
                        break

            if not combined_match:
                return (
                    "CLICK_TEXT_LOCAL_NOT_FOUND: "
                    f"target={target}"
                )

            # 使用整个 OCR 文本区域的包围盒中心点击。
            left = min(
                int(b.get("x", b.get("center_x", 0)))
                for b in combined_match
            )
            top = min(
                int(b.get("y", b.get("center_y", 0)))
                for b in combined_match
            )
            right = max(
                int(b.get("x", b.get("center_x", 0)))
                + int(b.get("width", 0))
                for b in combined_match
            )
            bottom = max(
                int(b.get("y", b.get("center_y", 0)))
                + int(b.get("height", 0))
                for b in combined_match
            )

            local_x = (left + right) // 2
            local_y = (top + bottom) // 2

            box = {
                "confidence": min(
                    float(b.get("confidence", 0.0))
                    for b in combined_match
                ),
                "text": "".join(
                    str(b.get("text", "")).strip()
                    for b in combined_match
                ),
            }

            print(
                "V6.29-R3.3-D MULTI-BOX MATCH:",
                "target=",
                target,
                "boxes=",
                len(combined_match),
                "text=",
                box["text"],
                "local=",
                f"({local_x},{local_y})",
                "confidence=",
                box["confidence"],
            )

        window_x = int(window.get("x", 0))
        window_y = int(window.get("y", 0))

        desktop_x = window_x + local_x
        desktop_y = window_y + local_y

        print(
            "V6.29-R3.3-B LOCAL TEXT CLICK:",
            "target=",
            target,
            "local=",
            f"({local_x},{local_y})",
            "window=",
            f"({window_x},{window_y})",
            "desktop=",
            f"({desktop_x},{desktop_y})",
            "confidence=",
            box.get("confidence"),
        )

        result = subprocess.run(
            [
                "xdotool",
                "mousemove",
                str(desktop_x),
                str(desktop_y),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return (
                "CLICK_TEXT_LOCAL_FAILED: "
                f"mousemove: {result.stderr.strip()}"
            )

        result = subprocess.run(
            [
                "xdotool",
                "click",
                "1",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return (
                "CLICK_TEXT_LOCAL_FAILED: "
                f"click: {result.stderr.strip()}"
            )

        return (
            "CLICK_TEXT_LOCAL_OK: "
            f"target={target}; "
            f"local=({local_x},{local_y}); "
            f"desktop=({desktop_x},{desktop_y}); "
            f"confidence={box.get('confidence')}"
        )

    except Exception as e:
        return f"CLICK_TEXT_LOCAL_FAILED: {e}"

    finally:
        if screenshot:
            try:
                Path(screenshot).unlink()
            except OSError:
                pass


@tool
def observe_window_tool(query: str):
    """V6.29-R3.1：观察桌面窗口，并通过本地 Vision Gateway 分层识别。"""
    screenshot = None

    try:
        window = observe_window(query)

        if not window:
            return f"未找到窗口: {query}"

        screenshot = window.get("screenshot")

        # ----------------------------------------------------
        # V6.29-R3.1
        #
        # 统一进入 Local Vision Gateway：
        #
        #   OCR
        #    ↓
        #   OCR 无有效结果
        #    ↓
        #   Qwen3-VL
        #
        # 原始截图只作为本地计算工件。
        # Gateway 不返回 image_path。
        # ----------------------------------------------------

        if screenshot:

            vision_result = vision_observe(
                screenshot,
                prompt=(
                    "请观察当前桌面窗口。"
                    "识别界面中的窗口标题、按钮、输入框、"
                    "菜单以及明显可操作的 GUI 元素。"
                    "重点寻找可能与用户当前操作有关的目标。"
                    "只返回文字描述，不要输出图片路径。"
                ),
            )

        else:

            vision_result = {
                "ok": False,
                "source": "none",
                "text": "",
                "confidence": "low",
            }

        source = str(
            vision_result.get(
                "source",
                "none"
            )
        )

        confidence = str(
            vision_result.get(
                "confidence",
                "low"
            )
        )

        vision_text = str(
            vision_result.get(
                "text",
                ""
            )
        ).strip()

        return (
            f"窗口: {window['title']}\n"
            f"window_id: {window['window_id']}\n"
            f"位置: ({window['x']}, {window['y']})\n"
            f"大小: {window['width']}x{window['height']}\n"
            f"视觉来源: {source}\n"
            f"视觉置信度: {confidence}\n"
            f"视觉文本:\n{vision_text}"
        )

    except Exception as e:

        return f"窗口观察失败: {e}"

    finally:

        # ----------------------------------------------------
        # V6.29-R3.1 安全兜底
        #
        # Gateway 正常情况下已经删除截图。
        # 如果 Gateway 尚未接管或异常退出，这里再次清理。
        #
        # GPT 永远不会收到截图路径或原始图像。
        # ----------------------------------------------------

        if screenshot:

            try:
                os.remove(screenshot)
            except OSError:
                pass
