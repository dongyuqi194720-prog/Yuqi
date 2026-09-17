from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Iterable, Sequence
import re
import difflib

@dataclass(frozen=True)
class OCRBox:
    text: str
    x: int
    y: int
    width: int
    height: int
    confidence: float = 0.0

    @property
    def right(self): return self.x + self.width
    @property
    def bottom(self): return self.y + self.height
    @property
    def center_x(self): return self.x + self.width // 2
    @property
    def center_y(self): return self.y + self.height // 2

@dataclass(frozen=True)
class TextMatch:
    target: str
    boxes: tuple[OCRBox, ...]
    start_char: int
    end_char: int
    score: float
    anchor_x: int
    anchor_y: int
    anchor_kind: str

    def to_dict(self):
        return {"target": self.target, "boxes": [asdict(b) for b in self.boxes],
                "start_char": self.start_char, "end_char": self.end_char,
                "score": self.score, "anchor_x": self.anchor_x, "anchor_y": self.anchor_y,
                "anchor_kind": self.anchor_kind}

def normalize(s: str) -> str:
    return re.sub(r"\s+", "", str(s or "")).casefold()

def _chars(s: str) -> str:
    return normalize(s)

def _row(boxes: Sequence[OCRBox], target_y: int) -> list[OCRBox]:
    return sorted((b for b in boxes if abs(b.center_y - target_y) <= max(18, b.height)), key=lambda b: b.x)

def _boundary(boxes: Sequence[OCRBox], split: int, target: str) -> tuple[int, int, str]:
    """Place the cursor at a semantic character boundary inside the target.

    If OCR split the target into several boxes, map target characters to boxes and
    place the anchor between the boxes covering chars before/after the split.
    If OCR put the whole target in one box, interpolate by character width.
    """
    target_n = _chars(target)
    if not boxes:
        return 0, 0, "none"
    ordered = sorted(boxes, key=lambda b: b.x)
    text = "".join(_chars(b.text) for b in ordered)
    if text != target_n and target_n not in text:
        # OCR can include harmless punctuation; fall back to the target span.
        text = target_n
    # character intervals per OCR box
    intervals = []
    pos = 0
    for b in ordered:
        n = max(1, len(_chars(b.text)))
        intervals.append((pos, pos + n, b))
        pos += n
    if len(ordered) == 1:
        b = ordered[0]
        n = max(1, len(target_n))
        x = b.x + round(b.width * split / n)
        margin = max(2, min(8, b.width // 8))
        x = max(b.x + margin, min(b.right - margin, x))
        return x, b.center_y, "single_box_character_boundary"
    left = next((b for a, z, b in intervals if a < split <= z), None)
    right = next((b for a, z, b in intervals if a <= split < z), None)
    # Exact boundary between two boxes is preferable.
    if left and right and left is not right:
        return (left.right + right.x) // 2, (left.center_y + right.center_y) // 2, "ocr_box_boundary"
    # Split falls inside a multi-character box.
    box = left or right or ordered[-1]
    a, z, _ = next((it for it in intervals if it[2] is box), (0, max(1, len(target_n)), box))
    frac = (split - a) / max(1, z - a)
    x = box.x + round(box.width * frac)
    x = max(box.x + 2, min(box.right - 2, x))
    return x, box.center_y, "multi_char_box_boundary"

def _match_score(target_n: str, observed: str, confidence: float) -> float:
    """Score an OCR candidate without pretending OCR is exact."""
    obs = _chars(observed)
    if not obs or not target_n:
        return 0.0
    if obs == target_n:
        return max(0.0, confidence) + 100.0
    ratio = difflib.SequenceMatcher(None, target_n, obs).ratio()
    return max(0.0, confidence) + ratio * 25.0


def resolve_text(target: str, boxes: Iterable[OCRBox]) -> list[TextMatch]:
    """Resolve visible text to safe internal click anchors.

    Matching is local and evidence-based. Exact OCR is preferred, followed by
    contiguous OCR fragments and only then a high-similarity single fragment.
    The anchor is placed at the semantic middle boundary (ceil(N/2)) rather
    than blindly at the bounding-box center. This is important when a target
    sits next to another clickable card.
    """
    target_n = _chars(target)
    if not target_n:
        return []
    boxes = [b for b in boxes if _chars(b.text) and b.width > 0 and b.height > 0]
    results: list[TextMatch] = []
    seen: set[tuple[int, int, tuple[str, ...]]] = set()
    # Known UI labels where the safest semantic click boundary is not the
    # mathematical midpoint. Keep this tiny and evidence-driven rather than
    # inventing arbitrary geometry rules for unknown labels.
    semantic_splits = {"同心共育": 2, "文件": 1, "公众号": 1}
    split = semantic_splits.get(target_n, (len(target_n) + 1) // 2)

    # 1) Exact single OCR box.
    for b in boxes:
        if _chars(b.text) == target_n:
            x, y, kind = _boundary([b], split, target)
            key = (x, y, (_chars(b.text),))
            if key not in seen:
                results.append(TextMatch(target, (b,), 0, len(target_n),
                                         _match_score(target_n, b.text, b.confidence),
                                         x, y, kind))
                seen.add(key)

    # 2) Contiguous same-row OCR fragments, e.g. 同心 + 共 + 育.
    # Avoid joining across a large gap because that often crosses cards.
    rows: list[list[OCRBox]] = []
    for b in sorted(boxes, key=lambda z: (z.center_y, z.x)):
        row = next((r for r in rows if abs(r[0].center_y - b.center_y) <= max(18, b.height, r[0].height)), None)
        if row is None:
            rows.append([b])
        else:
            row.append(b)
            row.sort(key=lambda z: z.x)
    for row in rows:
        for i in range(len(row)):
            joined = ""
            run: list[OCRBox] = []
            for j in range(i, len(row)):
                b = row[j]
                if run:
                    gap = b.x - run[-1].right
                    if gap < -max(4, b.height // 2) or gap > max(60, run[-1].height * 3):
                        break
                joined += _chars(b.text)
                run.append(b)
                if len(joined) > len(target_n):
                    break
                if joined == target_n:
                    x, y, kind = _boundary(run, split, target)
                    key = (x, y, tuple(_chars(z.text) for z in run))
                    if key not in seen:
                        conf = sum(max(0.0, z.confidence) for z in run) / len(run)
                        results.append(TextMatch(target, tuple(run), 0, len(target_n),
                                                 _match_score(target_n, joined, conf),
                                                 x, y, kind))
                        seen.add(key)
                    break

    # 3) Conservative fuzzy fallback for OCR typos, only for a single box.
    # Never fuzzy-match very short targets: false positives are too dangerous.
    if not results and len(target_n) >= 3:
        for b in boxes:
            obs = _chars(b.text)
            ratio = difflib.SequenceMatcher(None, target_n, obs).ratio()
            if ratio >= 0.82 and abs(len(obs) - len(target_n)) <= 1 and b.confidence >= 60:
                x, y, kind = _boundary([b], split, target)
                results.append(TextMatch(target, (b,), 0, len(target_n),
                                         _match_score(target_n, obs, b.confidence) - 15.0,
                                         x, y, "fuzzy_" + kind))

    # High confidence first; ties prefer the candidate with the strongest OCR
    # evidence, then the upper/left occurrence for deterministic behavior.
    return sorted(results, key=lambda m: (-m.score, m.anchor_y, m.anchor_x))


def validate_match(match: TextMatch, all_boxes: Iterable[OCRBox], window_width: int | None = None, window_height: int | None = None) -> tuple[bool, str]:
    """Cross-check a proposed anchor in both axes before a real click.

    Horizontal evidence: a boundary anchor must lie in the actual gap between
    the target fragments and must not fall inside another OCR box.
    Vertical evidence: the anchor must stay within the target row/boxes rather
    than drifting toward a neighboring row/card.
    """
    boxes = list(all_boxes)
    if not match.boxes:
        return False, "no target boxes"
    x, y = match.anchor_x, match.anchor_y
    if window_width is not None and not (0 <= x < int(window_width)):
        return False, "anchor outside horizontal window bounds"
    if window_height is not None and not (0 <= y < int(window_height)):
        return False, "anchor outside vertical window bounds"

    target_ids = {id(b) for b in match.boxes}
    if match.anchor_kind in {"ocr_box_boundary", "multi_char_box_boundary"}:
        ordered = sorted(match.boxes, key=lambda b: b.x)
        # For an OCR-box boundary, prove the anchor is actually between two
        # target boxes; for a multi-char split it must be inside its box.
        if match.anchor_kind == "ocr_box_boundary":
            pairs = list(zip(ordered, ordered[1:]))
            if not any(left.right <= x <= right.x for left, right in pairs):
                return False, "horizontal anchor is not between target fragments"
        else:
            if not any(b.x + 2 <= x <= b.right - 2 for b in ordered):
                return False, "horizontal split left target box"
    else:
        if not any(b.x + 2 <= x <= b.right - 2 for b in match.boxes):
            return False, "horizontal anchor is outside target interior"

    centers = [b.center_y for b in match.boxes]
    median_y = sorted(centers)[len(centers) // 2]
    max_h = max(b.height for b in match.boxes)
    if abs(y - median_y) > max(8, max_h):
        return False, "vertical anchor drifted outside target row"

    # An unrelated OCR box must not cover the click point. This catches the
    # dangerous case where two visual controls overlap around the proposed
    # anchor even though the target text itself matched.
    for b in boxes:
        if id(b) in target_ids:
            continue
        if b.x <= x < b.right and b.y <= y < b.bottom:
            return False, "anchor overlaps unrelated OCR box"
    return True, "geometry cross-check passed"
