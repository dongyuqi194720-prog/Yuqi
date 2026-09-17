import subprocess
import json


def observe_text(image_path, language="chi_sim+eng"):
    """保留原有 OCR 纯文本接口。"""
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", language, "--psm", "11"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def observe_text_boxes(image_path, language="chi_sim+eng"):
    """
    V6.29-R3.3-A：OCR 文字 + bounding box。
    返回结构化列表，不返回截图。
    """
    result = subprocess.run(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "-l",
            language,
            "--psm",
            "11",
            "tsv",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    lines = result.stdout.splitlines()
    if not lines:
        return []

    boxes = []

    # TSV:
    # level page_num block_num par_num line_num word_num
    # left top width height conf text
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue

        try:
            conf = float(parts[10])
            text = parts[11].strip()
        except (ValueError, IndexError):
            continue

        if not text or conf < 0:
            continue

        try:
            left = int(parts[6])
            top = int(parts[7])
            width = int(parts[8])
            height = int(parts[9])
        except (ValueError, IndexError):
            continue

        boxes.append(
            {
                "text": text,
                "x": left,
                "y": top,
                "width": width,
                "height": height,
                "center_x": left + width // 2,
                "center_y": top + height // 2,
                "confidence": round(conf / 100.0, 3),
            }
        )

    return boxes


def find_text_box(image_path, target, language="chi_sim+eng"):
    """
    V6.29-R3.3-A：本地确定性文字定位。
    返回最匹配的文字框；找不到返回 None。
    """
    target = str(target).strip()
    if not target:
        return None

    boxes = observe_text_boxes(image_path, language)
    target_lower = target.lower()

    # 精确匹配优先。
    exact = [
        box for box in boxes
        if box["text"].strip().lower() == target_lower
    ]
    if exact:
        return exact[0]

    # 子串匹配作为 fallback。
    partial = [
        box for box in boxes
        if target_lower in box["text"].strip().lower()
    ]
    if partial:
        return partial[0]

    return None


def observe_text_boxes_json(image_path, language="chi_sim+eng"):
    """返回 JSON 字符串，方便状态机/工具层消费。"""
    return json.dumps(
        observe_text_boxes(image_path, language),
        ensure_ascii=False
    )
