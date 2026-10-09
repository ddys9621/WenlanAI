"""桥段节奏（纯函数）：变长桥段 + 卷内节奏曲线。

固定 4 章循环写 1000 章 = 250 个一模一样的「代入→拉扯→兑现→善后」，读者很快就能摸清套路。网文实际节奏是：
开篇快进、卷中有一次较大的高潮、高潮后有低谷（受挫 / 代价）、卷末大高潮连爽几章、大高潮之后给一章缓冲。

- positions_for(n)：n 章桥段的位置序列（3-12 章）。多出来的章 = 加长拉扯 / 第二波兑现 / 缓冲章（breather）
- plan_beat_lengths(chapters)：把一个主线节点的篇幅切成长短不一的桥段，返回 [(章数, 节奏角色)]，总和严格等于篇幅
- position_note(seq, i)：同一桥段里有多个拉扯章 / 多波兑现时，给该章的补充说明（只有最后一个拉扯章章尾开装等）
"""
from __future__ import annotations

MIN_BRIDGE_CHAPTERS = 3
MAX_BRIDGE_CHAPTERS = 12
OPENING_BRIDGE = 4
FINALE_BRIDGE = 6
CLIMAX_FINALE_BRIDGE = 8
MID_CLIMAX_BRIDGE = 6
MID_CLIMAX_MIN_BODY = 14

RHYTHM_LABELS = {
    "opening": "开篇", "rise": "升温", "mid_climax": "卷中高潮", "dip": "低谷·受挫",
    "finale": "卷末收官", "climax_finale": "全书高潮收官", "standard": "",
}
RHYTHM_FILL_RULES = {
    "mid_climax": "卷中高潮：兑现规模明显大于前面的桥段，可以安排两波兑现（第一波兑现一半、第二波彻底放完）",
    "dip": "卷中低谷：紧跟在高潮之后，主角受挫 / 付出代价 / 被反制，兑现方式偏向险胜或失败中的收获，别一路碾压",
    "finale": "卷末收官：把本卷积压的期待集中放完，最后一章是缓冲章（日常 / 感情 / 群像 / 收获盘点），为下一卷开门",
    "climax_finale": "全书高潮收官：多波兑现层层加码，回收本卷乃至全书伏笔，最后一章缓冲收束",
    "opening": "开篇：黄金三章，节奏要快，第 3 章前完成第一次兑现",
}

_FIXED_POSITIONS: dict[int, tuple[str, ...]] = {
    3: ("intro", "payoff", "aftermath"),
    4: ("intro", "build", "payoff", "aftermath"),
    5: ("intro", "build", "build", "payoff", "aftermath"),
    6: ("intro", "build", "build", "payoff", "aftermath", "breather"),
    7: ("intro", "build", "build", "payoff", "payoff", "aftermath", "breather"),
    8: ("intro", "build", "payoff", "build", "build", "payoff", "aftermath", "breather"),
}


def positions_for(count: int) -> tuple[str, ...]:
    count = max(MIN_BRIDGE_CHAPTERS, min(MAX_BRIDGE_CHAPTERS, int(count)))
    if count in _FIXED_POSITIONS:
        return _FIXED_POSITIONS[count]
    waves = 2 if count <= 10 else 3
    builds = count - 3 - waves  # intro + aftermath + breather 固定，每波一个兑现章
    seq: list[str] = ["intro"]
    for w in range(waves):
        share = builds // waves + (1 if w < builds % waves else 0)
        seq += ["build"] * share + ["payoff"]
    return tuple(seq + ["aftermath", "breather"])


def _split_body(body: int) -> list[int]:
    """把非收官部分切成 3-6 章的桥段：以 4 章为主，余数用 3 / 5 吸收，再把部分 4+4 换成 3+5 制造长短变化。"""
    if body <= 0:
        return []
    if body <= 6:
        return [body]
    lengths = [4] * (body // 4)
    remainder = body % 4
    if remainder == 3:
        lengths.append(3)
    elif remainder == 1:
        lengths[-1] = 5
    elif remainder == 2:
        lengths[-1] = 3
        lengths.append(3)
    for i in range(1, len(lengths) - 1, 3):
        if lengths[i] == 4 and lengths[i + 1] == 4:
            lengths[i], lengths[i + 1] = 3, 5
    return lengths


def plan_beat_lengths(chapters: int, *, is_opening: bool = False, is_climax: bool = False) -> list[tuple[int, str]]:
    """主线节点篇幅 → [(桥段章数, 节奏角色)]，总章数 == chapters，每段 3-12 章。"""
    chapters = max(int(chapters), MIN_BRIDGE_CHAPTERS)
    finale_role = "climax_finale" if is_climax else "finale"
    if chapters <= MAX_BRIDGE_CHAPTERS and not is_opening:
        return [(chapters, finale_role)] if chapters >= FINALE_BRIDGE else _with_roles(_split_body(chapters), finale_role)
    finale = CLIMAX_FINALE_BRIDGE if is_climax else FINALE_BRIDGE
    if is_climax and chapters >= 40:
        finale = 10
    head = [OPENING_BRIDGE] if is_opening else []
    body = chapters - finale - sum(head)
    if body < 0:
        # 篇幅太短：开篇桥段之外全给收官
        return [(OPENING_BRIDGE, "opening"), (chapters - OPENING_BRIDGE, finale_role)] if chapters - OPENING_BRIDGE >= MIN_BRIDGE_CHAPTERS \
            else [(chapters, "opening")]
    if 0 < body < MIN_BRIDGE_CHAPTERS:
        finale += body  # 余下 1-2 章并进收官桥段
        body = 0
    body_lengths = _split_body(body)
    roles = ["rise"] * len(body_lengths)
    if body >= MID_CLIMAX_MIN_BODY and len(body_lengths) >= 3:
        mid = len(body_lengths) // 2
        # 卷中高潮：把中间相邻两段合并成 6 章左右的大桥段（总章数不变）
        merged = body_lengths[mid] + body_lengths[mid + 1]
        if merged <= MAX_BRIDGE_CHAPTERS:
            body_lengths[mid:mid + 2] = [merged]
            roles[mid:mid + 2] = ["mid_climax"]
            if mid + 1 < len(roles):
                roles[mid + 1] = "dip"
    plan = [(length, "opening") for length in head]
    plan += list(zip(body_lengths, roles))
    plan.append((finale, finale_role))
    return plan


def _with_roles(lengths: list[int], last_role: str) -> list[tuple[int, str]]:
    return [(length, last_role if i == len(lengths) - 1 else "rise") for i, length in enumerate(lengths)]


def position_note(seq: tuple[str, ...] | list[str], index: int) -> str:
    """同一桥段多个拉扯章 / 多波兑现时，给第 index 章（0 起）的补充说明；标准结构返回空串。"""
    if not 0 <= index < len(seq):
        return ""
    pos = seq[index]
    if pos == "build":
        run_start = index
        while run_start > 0 and seq[run_start - 1] == "build":
            run_start -= 1
        run_end = index
        while run_end + 1 < len(seq) and seq[run_end + 1] == "build":
            run_end += 1
        if run_end == run_start:
            return ""
        k, m = index - run_start + 1, run_end - run_start + 1
        if index < run_end:
            return f"本章是本轮第 {k}/{m} 个拉扯章：继续加压、布局或试探，章尾留悬念，但主角还不开装（开装放在本轮最后一个拉扯章的章尾）"
        return f"本章是本轮最后一个拉扯章（{k}/{m}）：压力推到顶，章尾让主角开装"
    if pos == "payoff":
        payoffs = [i for i, p in enumerate(seq) if p == "payoff"]
        if len(payoffs) < 2:
            return ""
        if index != payoffs[-1]:
            return "这是本桥段的第一波兑现：兑现一半，章尾抛出更大的威胁或反转，引出下一轮拉扯"
        return "这是本桥段的最终兑现：规模要大于前一波，把积压的期待彻底放完"
    return ""
