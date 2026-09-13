"""桥段形态（纯函数）：节点收官桥段 / 全书高潮节点的收官桥段与普通桥段不同。

问题：每个桥段都是 1:1:1:1 的四章循环，高潮节点被切成 N 个同构小循环，最后一个和第一个没区别，
没有网文卷末"压 10 章、连爽 3-5 章"的堆叠感。

形态由代码从槽位推出（不落库）：
- standard        普通桥段
- finale          节点收官桥段（beat_coverage_end == 1.0）：C3 把整个节点积压的期待放完，C4 节点目标落地 + 为下一节点开门
- climax_finale   全书最大高潮节点（权重最高）的收官桥段：加密兑现——C2 拉扯压到 6:4、章尾即进入兑现前半，
                  C3 密度加倍并回收全书伏笔，C4 前半仍是兑现余波
C3 章末仍不留钩子（产品决定），形态只改变兑现的规模与密度。
"""
from __future__ import annotations

from typing import Any

SHAPE_STANDARD = "standard"
SHAPE_FINALE = "finale"
SHAPE_CLIMAX_FINALE = "climax_finale"

_LABELS = {SHAPE_STANDARD: "", SHAPE_FINALE: "【节点收官】", SHAPE_CLIMAX_FINALE: "【全书高潮·加密兑现】"}


def climax_beat_index(main: Any) -> int | None:
    """全书最大高潮所在节点 = 权重最高的主线节点（与 _load_main_timeline 一致）。"""
    beats = list(getattr(main, "beats", ()) or ())
    return max(beats, key=lambda b: b.weight).index if beats else None


def bridge_shape(beat_coverage_end: float | None, beat_index: int | None, climax_index: int | None) -> str:
    if beat_coverage_end is None or beat_coverage_end < 1.0 - 1e-6:
        return SHAPE_STANDARD
    if climax_index is not None and beat_index == climax_index:
        return SHAPE_CLIMAX_FINALE
    return SHAPE_FINALE


def shape_label(shape: str) -> str:
    return _LABELS.get(shape, "")


def shape_fill_rule(shape: str, bridge_number: int, payoff_label: str) -> str:
    """填充 prompt 的约束行（普通桥段返回空串）。"""
    if shape == SHAPE_FINALE:
        return (
            f"桥段 {bridge_number} 是节点收官桥段：C3 把整个节点积压的期待一次放完（{payoff_label}规模高于本节点其他桥段），"
            f"C4 让节点目标落地并为下一节点开门"
        )
    if shape == SHAPE_CLIMAX_FINALE:
        return (
            f"桥段 {bridge_number} 是全书最大高潮节点的收官桥段（加密兑现形态）：C2 拉扯压到 6:4、章尾即进入兑现前半；"
            f"C3 兑现密度加倍，把本节点乃至全书前文埋下的伏笔一起回收；C4 前半仍是兑现余波，后半再收官"
        )
    return ""


def shape_expansion_block(shape: str) -> str:
    """章纲展开 prompt 的「# 桥段形态」段（普通桥段返回空串）。"""
    if shape == SHAPE_FINALE:
        return (
            "# 桥段形态：节点收官\n"
            "- C3 的场景卡加密到 5 张：把整个节点积压的期待一次放完，反应镜头（配角 / 对手 / 旁观者）至少 2 张\n"
            "- C4 第一部分写清节点目标落地（实力 / 地位 / 关系的可见变化），第二部分为下一节点开门"
        )
    if shape == SHAPE_CLIMAX_FINALE:
        return (
            "# 桥段形态：全书最大高潮节点的收官（加密兑现）\n"
            "- C2 拉扯压到 6:4，最后 2 张场景卡已经进入兑现前半（不是只开个头）\n"
            "- C3 场景卡加密到 6 张，兑现密度加倍：逐张回收本节点与全书前文埋下的伏笔，反应镜头 ≥ 2 张\n"
            "- C4 前半（1-2 张卡）仍是兑现余波，后半才收官并为下一节点 / 终局开门"
        )
    return ""


def shape_writing_rule(shape: str, position: str) -> str:
    """写作阶段位置约束的追加段（普通桥段 / 无关位置返回空串）。"""
    if shape == SHAPE_FINALE:
        if position == "payoff":
            return (
                "【🏁 节点收官】本章是本节点的收官兑现：把整个节点积压的期待一次放完，"
                "兑现规模要明显高于本节点前几个桥段的兑现；反应镜头写足。"
            )
        if position == "aftermath":
            return "【🏁 节点收官】第一部分写清节点目标落地（可见变化），第二部分为下一节点开门，而不只是下一桥段。"
        return ""
    if shape == SHAPE_CLIMAX_FINALE:
        if position == "build":
            return (
                "【🔥 全书最大高潮·加密兑现】本章比例改为 6:4：前 6 成拉扯压到极限，后 4 成已经进入兑现前半"
                "（主角的动作已经打出去，只是效果尚未全部揭示），章末停在兑现的最高点之前。"
            )
        if position == "payoff":
            return (
                "【🔥 全书最大高潮·加密兑现】本章兑现密度加倍：逐个回收本节点与全书前文埋下的伏笔，"
                "每回收一个都给一次反应镜头；配角 / 对手 / 旁观者的反应至少写 3 组。章末仍不留钩子。"
            )
        if position == "aftermath":
            return "【🔥 全书最大高潮·加密兑现】前半仍是兑现余波（结算 / 反应 / 余震），后半才收官并为终局或下一节点开门。"
    return ""
