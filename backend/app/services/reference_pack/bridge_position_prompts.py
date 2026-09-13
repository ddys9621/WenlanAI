"""V4.1 K2 桥段四章位置约束 prompt 模板（详见 v4_design.md §3.4.1）。

4 个位置（C1/C2/C3/C4）的硬约束模板：
- intro    = C1 代入 + 信息差（5:5）
- build    = C2 拉扯 + 开装（9:1，章尾开装）
- payoff   = C3 兑现爽点（10:0，无钩子）
- aftermath = C4 善后 + 下一目标（承上启下）

每个模板都接收 bridge_title / bridge_goal / bridge_showoff / target_word_count 等占位符，
由 slot_builders.build_bridge_position 在运行时格式化。
"""
from __future__ import annotations


BRIDGE_POSITION_INTRO = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C1 章】

本桥段目标：{bridge_goal}
本桥段装逼点：{bridge_showoff}

**章内结构（严格 5:5）**：

▼ 上半部分（约 {upper_word_count} 字）— 目的：制造代入（N+1 原则）
   - 用主角的日常场景让读者代入：起床/吃饭/路上聊天/和熟人对话
   - 用熟悉的内容降低陌生感，可顺带交代背景
   - **禁止**：在上半引入陌生人/陌生地点/陌生剧情
   - **禁止**：直接开始本桥段主线动作

▼ 下半部分（约 {lower_word_count} 字）— 目的：拉期待（信息差）
   - 视角切换 / 场景转换 / 主角到达目的地
   - 展示"对方面临一个主角可以解决的困境"
   - 必须制造"读者知道对方有困境，但对方不知道主角能解决"的信息差
   - **禁止**：在本章解决问题（解决是 C3 的事）
   - **禁止**：让主角开始装（装是 C2 章尾的事）

**章末钩子**：以信息差为钩，让读者期待下一章看主角介入
"""


BRIDGE_POSITION_BUILD = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C2 章】

本桥段目标：{bridge_goal}
本桥段装逼点：{bridge_showoff}

**章内结构（严格 9:1）**：

▼ 主体部分（约 {main_word_count} 字）— 目的：拉扯增强期待
   - 通过配角的台词、神态、心理活动加强读者对"主角装逼"的期待
   - 可写：配角讨论困境的严重性 / 配角对主角的怀疑 / 反派的嚣张
   - 必须让读者越来越想看"主角到底怎么解决"
   - **禁止**：主角直接介入解决（要让读者憋住）
   - **禁止**：跳过拉扯直接进入装逼

▼ 章末（约 {ending_word_count} 字）— 目的：开装钩
   - **必须**：让主角在本章结尾开始具体的装逼动作
   - 可以是：开口说一句关键的话 / 拿出某个东西 / 做出一个动作
   - 这是钩子但**不要完整呈现装逼效果**（效果留给 C3）
   - **禁止**：本章把装逼写透（节奏失控）
   - **禁止**：仅在心理活动中"准备装逼"而无外显动作

**章末钩子**：以"主角开装的瞬间"为钩，让读者迫切想看 C3 的兑现
"""


BRIDGE_POSITION_PAYOFF = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C3 章】

本桥段目标：{bridge_goal}
本桥段装逼点：{bridge_showoff}

**章内结构（10:0 纯爽点）**：

▼ 整章目的：兑现读者期待，把爽感写透
   - 把 C2 章末开始的装逼动作**完整展开**
   - 配角的震惊/崇拜/恐惧反应**必须充分描写**
   - 反派的崩溃/求饶**要给到位**
   - 给读者前两章压抑的所有情绪一次性释放

**严格禁止**：
   - ❌ 章末留任何钩子（不要写"但故事远未结束"、"他知道未来..."这类）
   - ❌ 主角自谦/总结/升华（不要写"他明白了什么道理"）
   - ❌ 跳过爽点的具体描写（不要写"几句话之间解决了问题"）
   - ❌ 引入新的次级冲突（破坏爽感专注度）

**章末处理**：以一个具体的、收束性的场景结尾即可
   - 好的例子："众人还在震惊中，他已经转身离开。"
   - 好的例子："场上一片死寂，只有他平静的脚步声。"
   - **不需要**钩子，读者已被爽感俘获，会自然读下一章
"""


BRIDGE_POSITION_AFTERMATH = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C4 章】

本桥段目标：{bridge_goal}（已在 C3 兑现）
下一桥段目标：{next_bridge_goal}

**章内结构（承上启下）**：

▼ 第一部分 — 上桥段收尾（约 {first_part_word_count} 字）
   - 明确写出"故事推进了什么"：
     * 大人物答应帮主角 / 主角获得了什么 / 某个长期问题解决
   - 收尾要具体可见，让读者感觉"哦这件事真的解决了"
   - 可插入 1-2 段有趣的日常对话/插科打诨舒缓情绪（可选）

▼ 第二部分 — 下桥段引子（约 {second_part_word_count} 字）
   - 明确告诉读者"下一步去哪 / 去做什么 / 去见谁"
   - 可用配角对话点出 / 主角内心独白 / 突发事件触发
   - 引子要勾起新期待，让读者愿意继续看 C1（下桥段）

**严格禁止**：
   - ❌ 拖拉无意义的内容（任何不属于"上桥段收尾"或"下桥段开启"的内容都伤追读欲）
   - ❌ 强行总结道理/升华主题
   - ❌ 第二部分内容超过下桥段钩子需要的量

**章末钩子**：下桥段的具体目标/问题，让读者期待下一桥段
"""


# ============================================================
# 悬疑反转流（mystery）—— 占位符与 showoff 完全一致
# ============================================================

MYSTERY_INTRO = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C1 章（悬疑：日常+异象疑点）】

本桥段目标：{bridge_goal}
本桥段反转点：{bridge_showoff}

**章内结构（严格 5:5）**：

▼ 上半部分（约 {upper_word_count} 字）— 目的：代入
   - 用主角的日常场景让读者代入，顺带交代与本案相关的背景
   - **禁止**：上半直接进入案情或抛出新角色

▼ 下半部分（约 {lower_word_count} 字）— 目的：抛出反常
   - 出现一个反常细节 / 新案情 / 与已知事实矛盾的信息
   - 让读者先于角色察觉“不对”，形成信息差
   - **禁止**：在本章解释反常（解释是 C3 的事）

**章末钩子**：以反常细节为钩，让读者想看主角怎么追
"""

MYSTERY_BUILD = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C2 章（悬疑：追查+误导）】

本桥段目标：{bridge_goal}
本桥段反转点：{bridge_showoff}

**章内结构（严格 9:1）**：

▼ 主体部分（约 {main_word_count} 字）— 目的：收集线索并误导
   - 主角按“看似合理”的方向追查，配角给出误导性解释，嫌疑转移
   - 每条被 C3 用到的线索都必须在这里明写出来（对读者公平）
   - **禁止**：主角在本章看破真相

▼ 章末（约 {ending_word_count} 字）— 目的：关键线索
   - **必须**：发现一条与主流解释矛盾的关键线索（一件物证 / 一句话 / 一个时间差）
   - 只呈现线索本身，**不要**给出解读

**章末钩子**：以关键线索为钩，让读者迫切想看 C3 的揭示
"""

MYSTERY_PAYOFF = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C3 章（悬疑：反转揭示）】

本桥段目标：{bridge_goal}
本桥段反转点：{bridge_showoff}

**章内结构（10:0 纯揭示）**：

▼ 整章目的：兑现局部真相，把前两章的判断整个掀翻
   - 逐条回收 C1/C2 埋下的线索，让读者事后能验证
   - 涉案人物的反应（震惊 / 崩溃 / 沉默）**必须充分描写**
   - 给读者前两章积压的疑惑一次性释放

**严格禁止**：
   - ❌ 章末留任何钩子（不要写“但这只是开始”这类）
   - ❌ 凭空冒出未铺垫的线索或证人
   - ❌ 借主角口把真相“总结”成大道理
   - ❌ 引入新的次级案情

**章末处理**：以一个具体的、收束性的场景结尾即可
"""

MYSTERY_AFTERMATH = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C4 章（悬疑：余波+新疑）】

本桥段目标：{bridge_goal}（已在 C3 揭示）
下一桥段目标：{next_bridge_goal}

**章内结构（承上启下）**：

▼ 第一部分 — 本案收束（约 {first_part_word_count} 字）
   - 明确写出局部真相带来的后果：谁被排除 / 谁暴露 / 主角得到了什么新信息
   - 可插入 1-2 段日常对话舒缓情绪（可选）

▼ 第二部分 — 更大疑点（约 {second_part_word_count} 字）
   - 揭示的真相背后露出一个更大的矛盾或未解之谜，指向下一桥段目标
   - 用一个具体的物证 / 人物 / 时间点落地，不要空泛

**严格禁止**：
   - ❌ 重复解释 C3 已揭示的内容
   - ❌ 强行总结道理
   - ❌ 第二部分内容超过下桥段钩子需要的量

**章末钩子**：下桥段要追的具体疑点
"""


# ============================================================
# 言情推拉流（romance）
# ============================================================

ROMANCE_INTRO = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C1 章（言情：日常+情感缺口）】

本桥段目标：{bridge_goal}
本桥段情感兑现点：{bridge_showoff}

**章内结构（严格 5:5）**：

▼ 上半部分（约 {upper_word_count} 字）— 目的：代入
   - 用主角的日常与二人当前的相处状态让读者代入
   - **禁止**：上半直接进入本桥段的情感事件

▼ 下半部分（约 {lower_word_count} 字）— 目的：暴露缺口
   - 暴露一个未被满足的情感需要，或埋下一个误解的种子
   - 读者看得见缺口，角色自己未必看得见
   - **禁止**：在本章解决缺口

**章末钩子**：以缺口为钩，让读者想看它怎么被触碰
"""

ROMANCE_BUILD = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C2 章（言情：推拉+误会）】

本桥段目标：{bridge_goal}
本桥段情感兑现点：{bridge_showoff}

**章内结构（严格 9:1）**：

▼ 主体部分（约 {main_word_count} 字）— 目的：推拉
   - 升温与拉开交替，第三方（情敌 / 闺蜜 / 家人）搅动
   - 误会必须有信息差支撑，不得靠角色智商下线
   - **禁止**：主角在本章把话说透

▼ 章末（约 {ending_word_count} 字）— 目的：心动/心碎动作
   - **必须**：一个具体的外显动作（递伞 / 转身 / 撕信 / 拨号又挂断）
   - 只呈现动作，**不要**写出对方反应（反应留给 C3）

**章末钩子**：以这个动作为钩
"""

ROMANCE_PAYOFF = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C3 章（言情：情感兑现）】

本桥段目标：{bridge_goal}
本桥段情感兑现点：{bridge_showoff}

**章内结构（10:0 纯兑现）**：

▼ 整章目的：把压了两章的情绪一次放完（甜到底或虐到底）
   - 双方的反应、台词、身体感受**必须充分描写**
   - 关系因此落到一个明确的新位置

**严格禁止**：
   - ❌ 章末留任何钩子
   - ❌ 兑现一半又收回（拖延感）
   - ❌ 借旁白升华爱情观
   - ❌ 引入新的第三方事件

**章末处理**：以一个具体的、收束性的场景结尾即可
"""

ROMANCE_AFTERMATH = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C4 章（言情：新状态+新阻力）】

本桥段目标：{bridge_goal}（已在 C3 兑现）
下一桥段目标：{next_bridge_goal}

**章内结构（承上启下）**：

▼ 第一部分 — 关系新状态（约 {first_part_word_count} 字）
   - 用可见变化写出关系落到了哪一步（称呼 / 距离 / 承诺 / 秘密共享）
   - 可插入 1-2 段轻松日常（可选）

▼ 第二部分 — 新阻力（约 {second_part_word_count} 字）
   - 抛出下一个阻力（外部事件 / 身份 / 第三方），指向下一桥段目标
   - 阻力要具体，落到一个人物或一件事上

**严格禁止**：
   - ❌ 重复 C3 的情绪
   - ❌ 强行总结感情道理
   - ❌ 第二部分内容超过下桥段钩子需要的量

**章末钩子**：下桥段要面对的具体阻力
"""


# ============================================================
# 无限流规则破局（infinite）
# ============================================================

INFINITE_INTRO = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C1 章（无限流：入局+规则展示）】

本桥段目标：{bridge_goal}
本桥段破局点：{bridge_showoff}

**章内结构（严格 5:5）**：

▼ 上半部分（约 {upper_word_count} 字）— 目的：代入
   - 用结算 / 休整 / 队友日常让读者代入，顺带交代当前资源与状态
   - **禁止**：上半直接进入副本

▼ 下半部分（约 {lower_word_count} 字）— 目的：入局与表面规则
   - 进入新局，亮出表面规则（可见的、字面的）
   - 用一个小惩罚或旁人的死亡证明规则是真的
   - **禁止**：在本章看破规则的真实含义

**章末钩子**：以第一条致命规则为钩
"""

INFINITE_BUILD = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C2 章（无限流：试探+代价）】

本桥段目标：{bridge_goal}
本桥段破局点：{bridge_showoff}

**章内结构（严格 9:1）**：

▼ 主体部分（约 {main_word_count} 字）— 目的：试错与代价
   - 队伍按字面理解试探规则，误读带来实际损失（队友 / 道具 / 身体）
   - 每条被 C3 用到的规则细节都必须在这里展示过
   - **禁止**：主角在本章完成破局

▼ 章末（约 {ending_word_count} 字）— 目的：看破关键规则
   - **必须**：主角注意到一处规则的真实含义（措辞 / 例外 / 顺序）
   - 只呈现“注意到了”，**不要**写出利用方式

**章末钩子**：以看破的瞬间为钩
"""

INFINITE_PAYOFF = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C3 章（无限流：破局兑现）】

本桥段目标：{bridge_goal}
本桥段破局点：{bridge_showoff}

**章内结构（10:0 纯破局）**：

▼ 整章目的：利用规则完成反杀或通关，恐惧转为掌控
   - 破局过程逐步展开，每一步都对应 C1/C2 展示过的规则
   - 队友与对手的反应**必须充分描写**

**严格禁止**：
   - ❌ 章末留任何钩子
   - ❌ 破局违反本桥段已展示的规则
   - ❌ 借金手指直接给答案代替推理
   - ❌ 引入新的副本机制

**章末处理**：以一个具体的、收束性的场景结尾即可
"""

INFINITE_AFTERMATH = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C4 章（无限流：结算+下一副本）】

本桥段目标：{bridge_goal}（已在 C3 兑现）
下一桥段目标：{next_bridge_goal}

**章内结构（承上启下）**：

▼ 第一部分 — 结算（约 {first_part_word_count} 字）
   - 奖励结算、幸存者清点、代价落地（谁没回来 / 失去了什么）
   - 可插入 1-2 段队友日常舒缓情绪（可选）

▼ 第二部分 — 下一副本引子（约 {second_part_word_count} 字）
   - 露出下一副本或更高层世界的第一条信息，指向下一桥段目标
   - 用一个具体的提示 / 人物 / 异常落地

**严格禁止**：
   - ❌ 重复 C3 的破局过程
   - ❌ 强行总结生存哲理
   - ❌ 第二部分内容超过下桥段钩子需要的量

**章末钩子**：下一副本的具体威胁
"""


# ============================================================
# 非开篇桥段的 C1（承接版，1:3）—— 四个题材族各一份
# ============================================================
# N+1 日常代入是给"新读者第一次进书"用的；第 2 个桥段起读者早已代入，再来半章起床吃饭就是断节奏。
# 上桥段 C4 已经明确"下一步去哪 / 做什么"，本章开头必须直接接上，不得重述、不得回无关日常。

_CONTINUED_HEAD = """【🎯 桥段位置约束 - 本章 = 桥段「{bridge_title}」C1 章（承接上桥段）】

本桥段目标：{bridge_goal}
本桥段{payoff_label}：{bridge_showoff}
上桥段留下的钩子：{prev_bridge_hook}

**章内结构（严格 1:3，本桥段不是开篇，读者已代入，不写日常铺垫）**：

▼ 开头（约 {lead_word_count} 字）— 目的：承接
   - 从上桥段结尾的钩子 / 引子直接接上：人物已在路上 / 已到现场 / 已开口，不得重述上桥段内容
   - **禁止**：无关日常（起床、吃饭、寒暄等与本桥段无关的铺垫）；**禁止**：用回忆或旁白复述前情
   - 若需要新舞台 / 新人物，直接以事件带出，不做静态介绍
"""

CONTINUED_INTRO_TAILS: dict[str, str] = {
    "showoff": """
▼ 主体（约 {body_word_count} 字）— 目的：拉期待（信息差）
   - 展示"对方面临一个主角可以解决的困境"，制造"读者知道对方有困境，但对方不知道主角能解决"的信息差
   - **禁止**：在本章解决问题（解决是 C3 的事）；**禁止**：让主角开始装（装是 C2 章尾的事）

**章末钩子**：以信息差为钩，让读者期待下一章看主角介入
""",
    "mystery": """
▼ 主体（约 {body_word_count} 字）— 目的：抛出反常
   - 出现一个反常细节 / 新案情 / 与已知事实矛盾的信息，让读者先于角色察觉“不对”
   - **禁止**：在本章解释反常（解释是 C3 的事）

**章末钩子**：以反常细节为钩，让读者想看主角怎么追
""",
    "romance": """
▼ 主体（约 {body_word_count} 字）— 目的：暴露缺口
   - 暴露一个未被满足的情感需要，或埋下一个误解的种子；读者看得见缺口，角色自己未必看得见
   - **禁止**：在本章解决缺口

**章末钩子**：以缺口为钩，让读者想看它怎么被触碰
""",
    "infinite": """
▼ 主体（约 {body_word_count} 字）— 目的：入局与表面规则
   - 进入新局，亮出表面规则（可见的、字面的），用一个小惩罚或旁人的死亡证明规则是真的
   - **禁止**：在本章看破规则的真实含义

**章末钩子**：以第一条致命规则为钩
""",
}

_PAYOFF_LABEL_BY_FAMILY = {"showoff": "装逼点", "mystery": "反转点", "romance": "情感兑现点", "infinite": "破局点"}
CONTINUED_INTRO_LEAD_RATIO = 0.25


def format_continued_intro(
    family: str, bridge_title: str, bridge_goal: str, bridge_showoff: str,
    target_word_count: int, prev_bridge_hook: str,
) -> str:
    tail = CONTINUED_INTRO_TAILS.get(family) or CONTINUED_INTRO_TAILS["showoff"]
    lead = int(target_word_count * CONTINUED_INTRO_LEAD_RATIO)
    return (_CONTINUED_HEAD + tail).format(
        bridge_title=bridge_title, bridge_goal=bridge_goal, bridge_showoff=bridge_showoff,
        payoff_label=_PAYOFF_LABEL_BY_FAMILY.get(family, "装逼点"),
        prev_bridge_hook=prev_bridge_hook.strip() or "（上桥段未记录钩子：按上桥段 C4 的收尾与引子直接接）",
        lead_word_count=lead, body_word_count=target_word_count - lead,
    )


# 题材族 → 位置 → 模板（key 与 app/services/bridge_templates.py 一致）
BRIDGE_POSITION_TEMPLATES_BY_FAMILY: dict[str, dict[str, str]] = {
    "showoff": {
        "intro": BRIDGE_POSITION_INTRO, "build": BRIDGE_POSITION_BUILD,
        "payoff": BRIDGE_POSITION_PAYOFF, "aftermath": BRIDGE_POSITION_AFTERMATH,
    },
    "mystery": {
        "intro": MYSTERY_INTRO, "build": MYSTERY_BUILD,
        "payoff": MYSTERY_PAYOFF, "aftermath": MYSTERY_AFTERMATH,
    },
    "romance": {
        "intro": ROMANCE_INTRO, "build": ROMANCE_BUILD,
        "payoff": ROMANCE_PAYOFF, "aftermath": ROMANCE_AFTERMATH,
    },
    "infinite": {
        "intro": INFINITE_INTRO, "build": INFINITE_BUILD,
        "payoff": INFINITE_PAYOFF, "aftermath": INFINITE_AFTERMATH,
    },
}

# 位置 → 模板映射（向后兼容：默认 showoff）
BRIDGE_POSITION_TEMPLATES: dict[str, str] = BRIDGE_POSITION_TEMPLATES_BY_FAMILY["showoff"]


def format_position_constraint(
    position: str,
    bridge_title: str,
    bridge_goal: str,
    bridge_showoff: str,
    target_word_count: int = 3000,
    next_bridge_goal: str = "（下一桥段未设定）",
    template: str = "showoff",
    opening: bool | None = None,
    prev_bridge_hook: str = "",
    shape: str = "standard",
    c3_hook_style: str = "none",
) -> str:
    """格式化指定位置的约束模板。

    Args:
        position: 'intro' / 'build' / 'payoff' / 'aftermath'
        bridge_title: 桥段标题
        bridge_goal: 桥段目标
        bridge_showoff: 桥段装逼点（其它题材为反转点 / 情感兑现点 / 破局点）
        target_word_count: 本章目标字数（用于计算上下半篇幅）
        next_bridge_goal: 下一桥段目标（仅 aftermath 使用）
        template: 题材族 key（showoff / mystery / romance / infinite），未知回落 showoff
        opening: 是否开篇桥段（桥段 1）。False → C1 用承接版（1:3，直接接上桥段钩子）；
            True / None（未知，旧调用方）→ 5:5 日常代入版
        prev_bridge_hook: 上桥段留给本桥段的钩子（仅承接版 C1 使用）
        shape: 桥段形态（bridge_shapes：standard / finale / climax_finale），收官 / 高潮桥段在 C2-C4 追加形态段
        c3_hook_style: C3 章末风格（bridge_hook_style：none 不留钩子 / soft 半钩），仅 payoff 位置生效

    Returns:
        格式化后的 prompt 段，可直接拼入 user_prompt
    """
    text = _format_position_body(
        position, bridge_title, bridge_goal, bridge_showoff, target_word_count, next_bridge_goal, template,
        opening, prev_bridge_hook,
    )
    if not text:
        return ""
    from app.services.bridge_hook_style import apply_writing_payoff_style
    from app.services.bridge_shapes import shape_writing_rule

    if position == "payoff":
        text = apply_writing_payoff_style(text, c3_hook_style)
    extra = shape_writing_rule(shape, position)
    return f"{text}\n{extra}\n" if extra else text


def _format_position_body(
    position: str,
    bridge_title: str,
    bridge_goal: str,
    bridge_showoff: str,
    target_word_count: int,
    next_bridge_goal: str,
    template: str,
    opening: bool | None,
    prev_bridge_hook: str,
) -> str:
    family_key = template if template in BRIDGE_POSITION_TEMPLATES_BY_FAMILY else "showoff"
    family = BRIDGE_POSITION_TEMPLATES_BY_FAMILY[family_key]
    template = family.get(position)
    if not template:
        return ""

    if position == "intro" and opening is False:
        return format_continued_intro(
            family_key, bridge_title, bridge_goal, bridge_showoff, target_word_count, prev_bridge_hook,
        )

    # 按位置计算各部分字数（4:6 / 9:1 等比例已写死在模板里）
    if position == "intro":
        # 5:5
        upper = target_word_count // 2
        lower = target_word_count - upper
        return template.format(
            bridge_title=bridge_title,
            bridge_goal=bridge_goal,
            bridge_showoff=bridge_showoff,
            upper_word_count=upper,
            lower_word_count=lower,
        )
    if position == "build":
        # 9:1
        main = int(target_word_count * 0.9)
        ending = target_word_count - main
        return template.format(
            bridge_title=bridge_title,
            bridge_goal=bridge_goal,
            bridge_showoff=bridge_showoff,
            main_word_count=main,
            ending_word_count=ending,
        )
    if position == "payoff":
        return template.format(
            bridge_title=bridge_title,
            bridge_goal=bridge_goal,
            bridge_showoff=bridge_showoff,
        )
    if position == "aftermath":
        # 6:4（上桥段收尾稍多，下桥段引子精炼）
        first = int(target_word_count * 0.6)
        second = target_word_count - first
        return template.format(
            bridge_title=bridge_title,
            bridge_goal=bridge_goal,
            next_bridge_goal=next_bridge_goal,
            first_part_word_count=first,
            second_part_word_count=second,
        )
    return ""
