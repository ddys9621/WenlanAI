"""卷纲规划纯函数与提示词（无 DB / 无 LLM）。

规划链：总纲 → 卷纲（剧情单元 + 线索编排）→ 章纲。参考岚笺 story-planning 的做法：
- 先想清因果再写自然段，下一级补足上一级里人物的行动、回应、过程和结果，不靠字段填句子
- 按实际事件分卷 / 分单元 / 分章：模型给的章数是参考，这里只把区间校正成连续、恰好覆盖（不切等长槽）
- 主角的特殊能力只是设定的一部分，不要求每一卷 / 单元 / 章都用它
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from app.utils.json_cleaner import safe_parse_json

CHAPTERS_PER_VOLUME = 40
MAX_VOLUMES = 40
CHAPTER_BATCH = 10  # 单元超过这么多章时分段生成章纲（一段一次调用，靠上一段的退出状态衔接）

STORY_RULE = (
    "先想清楚从开始到结束发生了什么、人物为何这样选择、选择造成什么结果、结果为何引出下一件事，"
    "再写成连贯的自然段：写清谁在什么处境下做了什么、别人怎样回应、事情和关系怎样变化；不要堆砌套路词，不要写成字段式短句"
)
ABILITY_RULE = (
    "主角的特殊能力 / 金手指（如有）只是设定的一部分，只在故事需要时出现；困难主要靠人物的选择、代价和关系变化来解决，"
    "兑现方式要多样（成长、智斗、反转、揭秘、感情推进、配角高光、失去与代价……），不要每段都靠它"
)
NAME_RULE = "人名、地名、势力名只能使用【本书角色】【世界规则表】【世界地图】里已有的；确需新角色时写成「新角色：身份」"
UPSTREAM_RULE = "不擅自改变已确认的设定和已经写成的情节；上级规划有缺口时在相应字段里说明缺什么，不在下级偷偷发明重要事实"


def suggest_volume_count(total_chapters: int) -> int:
    """全书章数 → 建议卷数（约 40 章一卷，夹在 [1, 40]）。"""
    if not total_chapters or total_chapters <= 0:
        return 1
    return max(1, min(MAX_VOLUMES, round(total_chapters / CHAPTERS_PER_VOLUME)))


# ---------------- 区间校正 ----------------

def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _length(item: dict) -> int:
    start, end = _int(item.get("chapter_start")), _int(item.get("chapter_end"))
    return end - start + 1 if start is not None and end is not None and end >= start else 0


def _apportion(weights: list[float], total: int) -> list[int]:
    """按权重把 total 章分给各段（最大余数法，每段至少 1 章）；权重之和恰好等于 total 时原样保留。"""
    n = len(weights)
    s = sum(weights) or 1.0
    raw = [w * total / s for w in weights]
    sizes = [int(math.floor(r)) for r in raw]
    order = sorted(range(n), key=lambda i: (raw[i] - sizes[i], -i), reverse=True)
    for i in order[: total - sum(sizes)]:
        sizes[i] += 1
    for i in range(n):
        while sizes[i] < 1:
            j = max(range(n), key=lambda k: sizes[k])
            sizes[j] -= 1
            sizes[i] += 1
    return sizes


def normalize_ranges(items: list[Any], start: int, end: int) -> list[dict]:
    """把模型给的各段章号区间校正成从 start 到 end 连续、恰好覆盖；段长按模型给的比例，缺失的按平均。"""
    total = end - start + 1
    rows = [dict(i) for i in items if isinstance(i, dict)][: max(total, 0)]
    if total <= 0 or not rows:
        return []
    lengths = [_length(r) for r in rows]
    given = [x for x in lengths if x]
    average = sum(given) / len(given) if given else 1.0
    sizes = _apportion([float(x or average) for x in lengths], total)
    cursor = start
    for row, size in zip(rows, sizes):
        row["chapter_start"], row["chapter_end"] = cursor, cursor + size - 1
        cursor += size
    return rows


def _text(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


def normalize_units(units: list[Any], start: int, end: int) -> list[dict]:
    """剧情单元：区间连续化 + 序号重排 + 文本字段规整。"""
    out = []
    for i, unit in enumerate(normalize_ranges(units, start, end), start=1):
        out.append({
            "index": i,
            "title": _text(unit.get("title"), 60) or f"单元 {i}",
            "chapter_start": unit["chapter_start"],
            "chapter_end": unit["chapter_end"],
            "story": _text(unit.get("story"), 3000),
            "turn": _text(unit.get("turn"), 800),
        })
    return out


def loads_units(raw: Any) -> list[dict]:
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return [u for u in data if isinstance(u, dict) and _int(u.get("chapter_start")) and _int(u.get("chapter_end"))] \
        if isinstance(data, list) else []


def loads_threads(raw: Any) -> list[str]:
    try:
        data = json.loads(raw) if isinstance(raw, str) and raw else raw
    except (json.JSONDecodeError, TypeError):
        return []
    return [str(t).strip() for t in data if str(t).strip()] if isinstance(data, list) else []


def unit_at(units: list[dict], chapter_number: int) -> Optional[dict]:
    return next((u for u in units if _int(u.get("chapter_start")) <= chapter_number <= _int(u.get("chapter_end"))), None)


def unit_position(unit: dict, chapter_number: int) -> tuple[int, int]:
    start, end = int(unit["chapter_start"]), int(unit["chapter_end"])
    return chapter_number - start + 1, end - start + 1


def position_guidance(index: int, size: int, next_title: Optional[str]) -> str:
    """本章在剧情单元里的位置 → 软指导（不规定比例，只说这一章在这件事里承担什么）。"""
    parts = []
    if index == 1:
        parts.append("本章开启新的剧情单元：开头直接承接上一章的结尾（不重述前情），尽快让读者看到这件事的起因和新的目标 / 麻烦")
    if 1 < index < size:
        parts.append(f"本章推进本单元（第 {index}/{size} 章）：局面要比上一章更进一步——新的阻碍、代价、选择或发现，别重复上一章的冲突形式")
    if index == size:
        tail = f"，结尾自然引出下一件事《{next_title}》" if next_title else "，结尾留下转入下一阶段的线头"
        parts.append("本章收束本单元：把这件事的冲突落地，写出可见的变化（处境、关系、实力、信息之一）" + tail)
    return "；".join(parts)


# ---------------- 提示词 ----------------

SKELETON_TASK = """# 任务：分卷（把总纲扩写成卷纲骨架）
请为第 {start}-{end} 章规划 {count} 卷左右（全书共 {total} 章）。卷数和每卷章数是参考，按故事阶段的实际大小来分。
{fixed}
# 写法
- {story_rule}
- 每卷是一个完整的故事阶段：换一个新的局面（新的舞台、对手层级或目标之一），赌注逐卷抬高，人物关系有看得见的推进
- 卷末要有这一卷最大的高潮和一个让人想看下一卷的钩子；最后一卷收束全书主线
- {ability_rule}
- {name_rule}
- {upstream_rule}

# 输出（纯 JSON 数组，不要 markdown）
[
  {{
    "title": "卷名（4-12 字）",
    "chapter_start": {start},
    "chapter_end": 40,
    "summary": "本卷故事（自然段 200-500 字）",
    "goal": "本卷主角想要什么、挡在面前的是谁 / 什么（50-120 字）",
    "climax": "卷末高潮（30-80 字）",
    "ending_hook": "卷末状态与转入下一卷的钩子（30-80 字）"
  }}
]"""

DETAIL_TASK = """# 任务：细化第 {number} 卷《{title}》的卷纲（第 {start}-{end} 章）
把本卷故事拆成若干剧情单元，并编排本卷要推进的线索。

# 写法
- 剧情单元 = 一件完整的事：写清起因 → 经过（阻碍、选择、代价）→ 结果，以及结果怎样引出下一件事；{story_rule}
- 单元章数按事件大小定：大事长、小事短，不要切成等长的块；章号必须连续覆盖第 {start}-{end} 章
- 节奏要有起伏：紧张的单元之后可以安排一段缓和（日常、感情、群像、收获整理），本卷最大的高潮放在卷末
- threads 写本卷要推进的感情线、支线、伏笔，每条写清本卷推进到哪一步；不必每个单元都出现
- {ability_rule}
- {name_rule}
- {upstream_rule}

# 输出（纯 JSON 对象，不要 markdown）
{{
  "units": [
    {{"title": "单元名（4-12 字）", "chapter_start": {start}, "chapter_end": {sample_end}, "story": "这件事的经过（自然段 150-400 字）", "turn": "单元结束时局面怎样变化（30-80 字）"}}
  ],
  "threads": ["感情线：……本卷推进到……", "伏笔：……"]
}}"""

CHAPTERS_TASK = """# 任务：把剧情单元 {index}《{title}》展开为第 {start}-{end} 章的章纲（共 {count} 章）
单元全程是第 {unit_start}-{unit_end} 章，本次只写第 {start}-{end} 章。

# 写法
- 按单元故事里实际发生的事件和场景顺序分章；每章都要让局面、关系或信息至少一项发生变化，不要原地打转，也不要为了凑章数把一句话的小事拆成一章
- plot_points 用自然段写清：谁在什么处境下做了什么、别人怎样回应、结果如何（200-400 字）
- key_events 3-6 条，按发生顺序；最后一条是章末落点，通常留下一个未闭合的问题或新的变化；单元最后一章收束这件事并引出下一件事
- {ability_rule}
- {pov_rule}
- 人名只能使用【本书角色】里的名字；characters_involved / pov 不得出现新名字；有【世界地图】时 scene 尽量用图上的地点名
- 章节契约：entry_state 承接上一章的 exit_state（本次第一章承接【上一章结尾】）；exit_state = 章末落点完成后停在哪；
  forbidden 1-3 条本章绝不能发生 / 揭晓的事（通常是后面章节才发生的关键事件）
- narrative_tasks：resolve = 本章回收的旧伏笔（promise_id 填【当前未回收的伏笔】里的编号如 P3，how 写怎么回收）；advance = 顺带推进的旧伏笔；
  plant = 新埋的伏笔（payoff_after = 计划多少章后回收）；没有合适的就留空

# 输出（纯 JSON 数组，{count} 个对象，chapter_number 从 {start} 到 {end}，不要 markdown）
[
  {{
    "chapter_number": {start},
    "title": "章节标题",
    "scene": "场景地点",
    "pov": "视角角色名",
    "plot_points": "本章经过（自然段）",
    "entry_state": "本章开头人物在哪、刚发生什么",
    "key_events": ["事件1", "事件2", "章末落点"],
    "exit_state": "章末落点完成后停在哪",
    "forbidden": ["本章不能提前发生的事"],
    "characters_involved": ["角色1", "角色2"],
    "target_word_count": {words},
    "narrative_tasks": {{"resolve": [], "advance": [], "plant": []}}
  }}
]"""


def _common() -> dict[str, str]:
    return {"story_rule": STORY_RULE, "ability_rule": ABILITY_RULE, "name_rule": NAME_RULE, "upstream_rule": UPSTREAM_RULE}


def render_skeleton_task(*, total_chapters: int, start_chapter: int, volume_count: int, fixed_text: str) -> str:
    fixed = f"\n# 已确认、不要改动的前几卷\n{fixed_text}\n" if fixed_text else ""
    return SKELETON_TASK.format(start=start_chapter, end=total_chapters, total=total_chapters, count=volume_count,
                                fixed=fixed, **_common())


def render_detail_task(volume: dict) -> str:
    start, end = int(volume["chapter_start"]), int(volume["chapter_end"])
    return DETAIL_TASK.format(number=volume.get("volume_number"), title=volume.get("title") or "", start=start, end=end,
                              sample_end=min(end, start + 7), **_common())


def render_chapters_task(unit: dict, start: int, end: int, pov_rule: str, default_words: int = 3000) -> str:
    return CHAPTERS_TASK.format(
        index=unit.get("index"), title=unit.get("title") or "", start=start, end=end, count=end - start + 1,
        unit_start=unit.get("chapter_start"), unit_end=unit.get("chapter_end"), pov_rule=pov_rule, words=default_words,
        ability_rule=ABILITY_RULE,
    )


# ---------------- 解析 ----------------

def parse_skeleton(raw: str, *, start_chapter: int, end_chapter: int, first_number: int) -> list[dict]:
    data = safe_parse_json(raw, default=[], expected_type="array", log_prefix="[分卷]")
    rows = [d for d in data if isinstance(d, dict) and _text(d.get("title"), 200) and _text(d.get("summary"), 10)] \
        if isinstance(data, list) else []
    if not rows:
        raise ValueError("分卷结果为空或缺少卷名 / 本卷故事，请重试")
    out = []
    for i, row in enumerate(normalize_ranges(rows, start_chapter, end_chapter)):
        out.append({
            "volume_number": first_number + i,
            "title": _text(row.get("title"), 200),
            "chapter_start": row["chapter_start"],
            "chapter_end": row["chapter_end"],
            "summary": _text(row.get("summary"), 5000),
            "goal": _text(row.get("goal"), 1500),
            "climax": _text(row.get("climax"), 1500),
            "ending_hook": _text(row.get("ending_hook"), 1500),
        })
    return out


def parse_detail(raw: str, volume: dict) -> dict[str, Any]:
    data = safe_parse_json(raw, default={}, expected_type="object", log_prefix="[卷纲细化]")
    if not isinstance(data, dict):
        data = {}
    units = [u for u in (data.get("units") or []) if isinstance(u, dict) and _text(u.get("title"), 60)]
    if not units:
        raise ValueError("卷纲细化结果里没有剧情单元，请重试")
    threads = [_text(t, 300) for t in (data.get("threads") or []) if _text(t, 300)][:12]
    return {
        "units": normalize_units(units, int(volume["chapter_start"]), int(volume["chapter_end"])),
        "threads": threads,
        "summary": _text(data.get("summary"), 5000),
    }


def _list(value: Any, limit: int, max_items: int) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\n；;]", value)
    if not isinstance(value, list):
        return []
    return [str(x).strip()[:limit] for x in value if str(x).strip()][:max_items]


def _words(value: Any) -> Optional[int]:
    number = _int(value)
    return number if number and 500 <= number <= 10000 else None


def parse_chapter_outlines(raw: str, start: int, end: int) -> list[dict]:
    data = safe_parse_json(raw, default=[], expected_type="array", log_prefix="[章纲]")
    rows = [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
    wanted = list(range(start, end + 1))
    by_number = {n: d for d in rows if (n := _int(d.get("chapter_number"))) in wanted}
    if len(by_number) == len(wanted):
        ordered = [by_number[n] for n in wanted]
    elif len(rows) >= len(wanted):
        ordered = rows[: len(wanted)]
    else:
        raise ValueError(f"章纲数量不足：需要第 {start}-{end} 章共 {len(wanted)} 章，模型只给了 {len(rows)} 章")
    out = []
    for number, row in zip(wanted, ordered):
        tasks = row.get("narrative_tasks")
        out.append({
            "chapter_number": number,
            "title": _text(row.get("title"), 200) or f"第{number}章",
            "scene": _text(row.get("scene"), 200) or None,
            "pov": _text(row.get("pov"), 100) or None,
            "plot_points": _text(row.get("plot_points"), 6000),
            "entry_state": _text(row.get("entry_state"), 1000) or None,
            "exit_state": _text(row.get("exit_state"), 1000) or None,
            "key_events": _list(row.get("key_events"), 300, 12),
            "forbidden": _list(row.get("forbidden"), 200, 5),
            "characters_involved": _list(row.get("characters_involved"), 60, 20),
            "target_word_count": _words(row.get("target_word_count")),
            "narrative_tasks": tasks if isinstance(tasks, dict) else None,
        })
    return out
