"""
V6.29-R3.2-R3 Local Vision Gateway

设计原则：

    GUI screenshot
          |
          v
    Local Vision Gateway
          |
       +--+--+
       |     |
      OCR   Qwen3-VL
       |     |
       +--+--+
          |
          v
    structured text/result

原始截图只允许作为本地计算工件。
不得把 screenshot path 返回给 GPT。
"""

from pathlib import Path
import json
import os


def _safe_delete(path):
    """安全删除本地视觉临时文件。"""
    if not path:
        return

    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


def _load_ocr():
    """延迟加载 OCR，避免启动阶段强依赖。"""
    from tools.ocr_observer import observe_text
    return observe_text


def _load_vlm():
    """延迟加载本地 Qwen3-VL。"""
    from tools.vision_observer import observe_image
    return observe_image


def vision_observe(
    image_path,
    prompt=(
        "请观察当前桌面窗口。"
        "识别窗口标题、按钮、输入框、菜单以及明显可操作的 GUI 元素。"
        "重点寻找可能与用户当前操作有关的目标。"
        "只返回文字描述，不要输出图片路径。"
    ),
):
    """
    本地视觉观察。

    优先 OCR。
    OCR 无有效结果时才调用 Qwen3-VL。

    返回值只包含结构化文字信息。
    不返回 screenshot path。
    """

    image_path = str(image_path or "").strip()

    if not image_path:
        return {
            "ok": False,
            "source": "none",
            "text": "",
            "confidence": "none",
            "error": "未提供截图路径",
        }

    if not Path(image_path).exists():
        return {
            "ok": False,
            "source": "none",
            "text": "",
            "confidence": "none",
            "error": "截图文件不存在",
        }

    try:
        # ----------------------------------------------------
        # 第一层：OCR
        # ----------------------------------------------------
        try:
            observe_text = _load_ocr()
            ocr_text = observe_text(image_path)
            ocr_text = str(ocr_text or "").strip()

            if ocr_text:
                return {
                    "ok": True,
                    "source": "ocr",
                    "text": ocr_text,
                    "confidence": "medium",
                }

        except Exception as ocr_error:
            ocr_error_text = str(ocr_error)
        else:
            ocr_error_text = ""

        # ----------------------------------------------------
        # 第二层：本地 Qwen3-VL
        # ----------------------------------------------------
        try:
            observe_image = _load_vlm()

            vlm_text = observe_image(
                image_path,
                prompt=prompt,
            )

            vlm_text = str(vlm_text or "").strip()

            if vlm_text:
                return {
                    "ok": True,
                    "source": "qwen3-vl",
                    "text": vlm_text,
                    "confidence": "medium",
                }

            return {
                "ok": False,
                "source": "qwen3-vl",
                "text": "",
                "confidence": "low",
                "error": "OCR 和 Qwen3-VL 均未返回有效结果",
            }

        except Exception as vlm_error:
            return {
                "ok": False,
                "source": "qwen3-vl",
                "text": "",
                "confidence": "none",
                "error": (
                    "本地视觉失败: "
                    + str(vlm_error)
                    + (
                        "；OCR错误: "
                        + ocr_error_text
                        if ocr_error_text
                        else ""
                    )
                ),
            }

    finally:
        # ----------------------------------------------------
        # V6.29 privacy gate
        #
        # 无论 OCR/VLM 成功还是失败，
        # 原始截图都必须立即删除。
        # ----------------------------------------------------
        _safe_delete(image_path)


def vision_observe_json(image_path, prompt=None):
    """JSON 字符串接口，方便 ToolRouter / Agent 使用。"""
    if prompt is None:
        result = vision_observe(image_path)
    else:
        result = vision_observe(
            image_path,
            prompt=prompt,
        )

    return json.dumps(
        result,
        ensure_ascii=False,
    )
