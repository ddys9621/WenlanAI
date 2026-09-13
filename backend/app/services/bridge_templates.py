"""桥段四章方法论模板（按题材族）。

四章结构（C1→C4）对所有题材一致，但每个位置"做什么"按题材换语义：
- showoff  爽文/升级流：代入+信息差 → 拉扯+开装 → 兑现爽点 → 善后+下一目标
- mystery  悬疑/推理：  日常+异象疑点 → 追查+误导 → 反转揭示 → 余波+新疑
- romance  言情/现言：  日常+情感缺口 → 推拉+误会 → 情感兑现 → 关系新状态+新阻力
- infinite 无限流/规则： 入局+规则展示 → 试探+代价 → 破局兑现 → 结算+下一副本

C3（payoff）在所有题材里都是"兑现章"：把前两章压的期待一次放完、章末不留钩子——
这是产品层决定（2026-09 评审保持现状），不要按题材改动。

DB 字段键名不变（showoff_point / c1_intro …），模板只改 prompt 里对字段的语义描述。
写作阶段（chapter_content）的 C1-C4 硬约束在 reference_pack/bridge_position_prompts.py，
用同一个 key 查表。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeTemplate:
    key: str
    name: str
    genre_keywords: tuple[str, ...]
    payoff_label: str            # showoff_point 字段在本题材的语义标签
    payoff_hint: str             # JSON 输出里 showoff_point 的填写说明
    golden_finger_hint: str      # golden_finger_usage 的填写说明
    methodology: str             # 填充 prompt「# 桥段四章方法论」正文
    position_labels: dict[str, str]
    card_hints: dict[str, str]
    extra_constraints: tuple[str, ...]
    opening_first_chapter: str   # 黄金三章：第 1 章前 1000 字必须出现什么
    payoff_types: tuple[str, ...] = ()   # 兑现方式枚举：填充时 LLM 从中选一个落 payoff_type，账本按类型统计


DEFAULT_TEMPLATE_KEY = "showoff"

_SHOWOFF = BridgeTemplate(
    key="showoff",
    name="爽文装逼打脸流",
    genre_keywords=("玄幻", "修仙", "仙侠", "都市", "系统", "重生", "武侠", "科幻", "游戏", "历史争霸"),
    payoff_label="装逼点",
    payoff_hint="装逼/爽点设计：主角亮出什么、怎么碾压、旁观者如何震惊",
    golden_finger_hint="本桥段如何使用金手指（与相邻桥段不同款）",
    methodology=(
        "每个桥段 4 章，结构固定：\n"
        "- **C1 代入+信息差**（开篇桥段 5:5：上半日常代入；非开篇桥段 1:3：开头直接承接上桥段钩子，不回无关日常）"
        "：下半亮出对方困境，读者知道主角能解决而对方不知道\n"
        "- **C2 拉扯+开装**（9:1）：配角拉扯加强期待，**章尾让主角开始装**\n"
        "- **C3 兑现爽点**（10:0）：装到底，配角震惊、反派崩溃写足，**不留钩子**\n"
        "- **C4 善后+下一目标**：本桥段收获落地（实力/资源/人脉）+ 引下个桥段"
    ),
    position_labels={
        "intro": "C1 代入+信息差", "build": "C2 拉扯+开装",
        "payoff": "C3 兑现爽点", "aftermath": "C4 善后+下一目标",
    },
    card_hints={
        "c1_intro": "C1 开场（开篇桥段为日常代入，其余桥段承接上桥段钩子）+ 下半信息差",
        "c2_build": "C2 拉扯素材 + 章尾开装动作",
        "c3_payoff": "C3 装逼完整展开 + 配角反应",
        "c4_aftermath": "C4 本桥段收尾事件 + 下桥段引子",
    },
    extra_constraints=(
        "相邻桥段的兑现方式不得同型（打脸 / 扮猪吃虎 / 收获机缘 / 反差揭底 / 护人 交替使用）",
        "对手与危机必须递进：后一桥段的对手层级或赌注要高于前一桥段，不得回落",
        "每个桥段都要有可见收获（实力 / 资源 / 人脉 / 信息之一），写进 c4_aftermath",
    ),
    opening_first_chapter="异象、金手指或核心冲突三者至少其一",
    payoff_types=("打脸", "扮猪吃虎", "收获机缘", "反差揭底", "护人", "绝境反杀", "以弱胜强"),
)

_MYSTERY = BridgeTemplate(
    key="mystery",
    name="悬疑反转流",
    genre_keywords=("悬疑", "推理", "灵异", "惊悚", "刑侦", "探案", "犯罪", "诡秘"),
    payoff_label="反转点",
    payoff_hint="反转/揭示设计：本桥段兑现的局部真相是什么、如何颠覆前两章的判断、读者事后回看哪些线索早已给出",
    golden_finger_hint="本桥段如何使用主角的特殊能力/金手指获取或验证线索（不得直接给出答案）",
    methodology=(
        "每个桥段 4 章，结构固定：\n"
        "- **C1 日常+异象疑点**（开篇桥段 5:5：上半日常代入；非开篇桥段 1:3：开头直接承接上桥段钩子，不回无关日常）"
        "：下半抛出一个反常细节或新案情，读者先于角色察觉不对\n"
        "- **C2 追查+误导**（9:1）：收集线索、嫌疑转移、误导性解释占主体，**章尾发现一条关键线索**\n"
        "- **C3 反转揭示**（10:0）：兑现局部真相，把前两章的判断整个掀翻，线索回收写足，**不留钩子**\n"
        "- **C4 余波+新疑**：收束本桥段案情 + 揭示背后更大的疑点作为下桥段引子"
    ),
    position_labels={
        "intro": "C1 日常+异象疑点", "build": "C2 追查+误导",
        "payoff": "C3 反转揭示", "aftermath": "C4 余波+新疑",
    },
    card_hints={
        "c1_intro": "C1 开场（开篇桥段为日常代入，其余桥段承接上桥段钩子）+ 下半反常细节/新案情",
        "c2_build": "C2 线索收集与误导方向 + 章尾关键线索",
        "c3_payoff": "C3 局部真相与反转逻辑 + 被回收的线索清单",
        "c4_aftermath": "C4 案情收束事件 + 更大疑点引子",
    },
    extra_constraints=(
        "线索必须公平：C3 揭示所依赖的线索都要在 C1/C2 明写过，不得凭空冒出",
        "每个桥段至少推进一条主谜团线索，且不得重复已在账本中揭示过的信息",
        "反转类型不得连续同款（身份反转 / 时间反转 / 动机反转 / 叙述者不可靠 交替）",
    ),
    opening_first_chapter="核心谜题或第一个反常事件",
    payoff_types=("身份反转", "时间反转", "动机反转", "叙述者不可靠", "物证反转", "凶手反转"),
)

_ROMANCE = BridgeTemplate(
    key="romance",
    name="言情推拉流",
    genre_keywords=("言情", "现言", "古言", "甜宠", "虐恋", "爱情", "婚恋", "豪门", "校园恋"),
    payoff_label="情感兑现点",
    payoff_hint="情感兑现设计：本桥段集中释放的甜/虐是什么、由哪个动作或台词引爆、关系因此变到哪一步",
    golden_finger_hint="本桥段如何使用主角的特殊设定/金手指推动关系（如读心、重生记忆、身份反差）",
    methodology=(
        "每个桥段 4 章，结构固定：\n"
        "- **C1 日常+情感缺口**（开篇桥段 5:5：上半日常代入；非开篇桥段 1:3：开头直接承接上桥段钩子，不回无关日常）"
        "：下半暴露一个未被满足的情感需要或误解的种子\n"
        "- **C2 推拉+误会**（9:1）：升温与拉开交替、第三方搅动占主体，**章尾一个心动/心碎的具体动作**\n"
        "- **C3 情感兑现**（10:0）：把压了两章的情绪一次放完（甜到底或虐到底），**不留钩子**\n"
        "- **C4 关系新状态+新阻力**：关系落到新台阶 + 抛出下一个阻力作为下桥段引子"
    ),
    position_labels={
        "intro": "C1 日常+情感缺口", "build": "C2 推拉+误会",
        "payoff": "C3 情感兑现", "aftermath": "C4 新状态+新阻力",
    },
    card_hints={
        "c1_intro": "C1 开场（开篇桥段为日常代入，其余桥段承接上桥段钩子）+ 下半情感缺口/误解种子",
        "c2_build": "C2 推拉与第三方搅动 + 章尾心动/心碎动作",
        "c3_payoff": "C3 情感释放的完整场景 + 双方反应",
        "c4_aftermath": "C4 关系新状态 + 下一阻力引子",
    },
    extra_constraints=(
        "甜虐比例按大纲定位保持（默认甜 7 虐 3），相邻桥段不得连续两次同向（连甜或连虐）",
        "误会必须有信息差支撑，不得靠角色智商下线制造",
        "每个桥段关系必须有可见变化（称呼 / 距离 / 承诺 / 秘密共享之一）",
    ),
    opening_first_chapter="男女主的第一次交锋或强烈的第一印象反差",
    payoff_types=("甜·告白", "甜·守护", "甜·亲密升级", "甜·误会解开", "虐·误会", "虐·分离", "虐·牺牲"),
)

_INFINITE = BridgeTemplate(
    key="infinite",
    name="无限流规则破局",
    genre_keywords=("无限流", "规则怪谈", "副本", "诡异复苏", "求生", "轮回", "游戏副本", "克苏鲁"),
    payoff_label="破局点",
    payoff_hint="破局设计：主角看穿的关键规则是什么、如何利用规则反杀/通关、代价是什么",
    golden_finger_hint="本桥段如何使用金手指辅助读规则/抗惩罚（不得替代推理）",
    methodology=(
        "每个桥段 4 章，结构固定：\n"
        "- **C1 入局+规则展示**（开篇桥段 5:5：上半日常/结算代入；非开篇桥段 1:3：开头直接承接上桥段钩子，不回无关日常）"
        "：下半进入新局并亮出表面规则\n"
        "- **C2 试探+代价**（9:1）：试错、误读规则、队友付出代价占主体，**章尾看破一条关键规则**\n"
        "- **C3 破局兑现**（10:0）：利用规则完成反杀或通关，恐惧转为掌控写足，**不留钩子**\n"
        "- **C4 结算+下一副本**：奖励结算、幸存者清点 + 下一副本或更高层世界的引子"
    ),
    position_labels={
        "intro": "C1 入局+规则展示", "build": "C2 试探+代价",
        "payoff": "C3 破局兑现", "aftermath": "C4 结算+下一副本",
    },
    card_hints={
        "c1_intro": "C1 开场（开篇桥段为结算代入，其余桥段承接上桥段钩子）+ 下半新局与表面规则",
        "c2_build": "C2 试错与代价 + 章尾看破的关键规则",
        "c3_payoff": "C3 破局完整过程 + 众人反应",
        "c4_aftermath": "C4 结算事件 + 下一副本引子",
    },
    extra_constraints=(
        "每个副本的规则必须自洽且可被读者事后验证，破局不得违反本桥段已展示的规则",
        "危险等级递进：后一桥段的副本难度或惩罚强度高于前一桥段",
        "代价不能为零：每个桥段至少有一项可见损失（队友 / 道具 / 身体 / 信息）",
    ),
    opening_first_chapter="第一次入局与第一条致命规则",
    payoff_types=("规则反杀", "规则漏洞通关", "献祭破局", "身份伪装", "团队协作破局", "规则嫁接"),
)

TEMPLATES: dict[str, BridgeTemplate] = {
    t.key: t for t in (_SHOWOFF, _MYSTERY, _ROMANCE, _INFINITE)
}

# 关键词扫描顺序：细分题材优先，showoff 兜底
_RESOLVE_ORDER = ("mystery", "romance", "infinite", "showoff")


def resolve_template(genre: str | None, explicit_key: str | None = None) -> BridgeTemplate:
    """选模板：显式 key（桥段已记录的 generation_meta.template）优先；否则按 genre 关键词；兜底 showoff。"""
    if explicit_key and explicit_key in TEMPLATES:
        return TEMPLATES[explicit_key]
    text = (genre or "").strip()
    if text:
        for key in _RESOLVE_ORDER:
            if any(kw in text for kw in TEMPLATES[key].genre_keywords):
                return TEMPLATES[key]
    return TEMPLATES[DEFAULT_TEMPLATE_KEY]
