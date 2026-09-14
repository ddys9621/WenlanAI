"""拆书 V2: 全书实体扫描器（纯正则版）

不引入 jieba，仅用正则覆盖 ~80% 主角检出场景。

扫描信号源（设计文档 §6.2.1）：
1. 引语归属：「X道：」「X笑道」「X说道：」等
2. 命名介绍：「X叫作Y」「名叫X」「绰号X」「外号X」「人称X」等
3. n-gram 频率：滑窗 2-4 字符中文片段
4. 章节标题：从标题中提取 2-4 字的潜在专名
5. 后缀规则：「山/城/宫/派/宗」结尾标记 location/org 候选

后处理：停用词过滤 + 多源合并 + 频率排序。

输出：list[EntityCandidate]（按频率倒序），供 DictionaryClassifier 输入 LLM 分类。
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.book_dissect.v2_types import CandidateSource, EntityCandidate


# ---------------------------------------------------------------------------
# 静态正则表 / 停用词表
# ---------------------------------------------------------------------------

_CN_CHAR = r"[\u4e00-\u9fa5]"

# 1. 引语归属：X 后接 表"说话/想"动词
# 关键：动词按长度降序排列！正则 alternation 按顺序尝试，先长后短才能让
# "王五说道：" 被切成 name="王五" + verb="说道"，而非 name="王五说" + verb="道"。
_DIALOGUE_VERBS = (
    # 4 字
    "嘿嘿一笑|微微一笑|喃喃自语|"
    # 3 字
    "冷笑道|冷哼道|冷声道|低声道|沉吟道|高声道|大声道|反问道|追问道|"
    "轻声道|柔声道|淡然道|淡淡道|微笑道|苦笑道|沉声道|思忖道|喃喃道|"
    "嘟囔道|嘟哝道|叹息道|长叹道|苦叹道|解释道|介绍道|开口道|开声道|"
    "默念道|低喝道|怒吼道|大笑道|哈哈道|嘿嘿道|嘿然道|缓缓道|肃然道|"
    "严肃道|嘶吼道|惊呼道|失声道|惊声道|"
    # 2 字
    "说道|笑道|喝道|怒道|喊道|应道|答道|问道|叹道|冷笑|冷哼|沉吟|"
    "暗想|心想|忖道|惊道|开口|愣道|"
    # 1 字（最后兜底）
    "道|说"
)

# name 用非贪婪 `{2,4}?` 让 2 字优先匹配（配合 verb 降序，确保多字 verb 能整体被抓走）。
# 例：「王五说道：」非贪婪从 name=2 开始 → "王五" + verb="说道"（2字 verb 优先于 1字 verb"道"）。
_RE_DIALOGUE_PRE = re.compile(rf"({_CN_CHAR}{{2,4}}?)(?:{_DIALOGUE_VERBS})[:：]")
_RE_DIALOGUE_POST_QUOTE = re.compile(
    rf"[\"」』』]\s*({_CN_CHAR}{{2,4}}?)(?:{_DIALOGUE_VERBS})"
)

# 2. 命名介绍
_NAMING_VERBS = "叫作|叫做|名叫|名为|唤作|唤做|绰号|外号|人称|字号|号称|姓名|姓"
# name 后紧跟非中文（标点/空白/数字/英文/EOL），避免吞掉后续短语动词
_RE_NAMING = re.compile(
    rf"(?:{_NAMING_VERBS})\s*[\"「『]?({_CN_CHAR}{{2,5}})(?=[^\u4e00-\u9fa5]|$)"
)

# 3. n-gram：纯中文滑窗
_RE_PURE_CN_RUN = re.compile(rf"{_CN_CHAR}+")

# 5. 后缀规则
_LOCATION_SUFFIX = "山|峰|岭|岛|城|镇|村|州|国|界|海|湖|河|江|林|谷|渊|渡|关|"\
                   "宫|府|寺|观|庙|塔|阁|殿|楼|院|府邸|山脉"
_ORG_SUFFIX = "派|宗|盟|帮|教|门|殿|阁|府|楼|社|会|堂|司|寨"
_ITEM_SUFFIX = "剑|刀|枪|戟|弓|笔|印|鼎|镜|珠|丹|符|令|盘|塔|册|经|诀|术|功|法"

_RE_LOCATION_SUFFIX = re.compile(rf"^({_CN_CHAR}{{1,4}})(?:{_LOCATION_SUFFIX})$")
_RE_ORG_SUFFIX = re.compile(rf"^({_CN_CHAR}{{1,4}})(?:{_ORG_SUFFIX})$")
_RE_ITEM_SUFFIX = re.compile(rf"^({_CN_CHAR}{{1,4}})(?:{_ITEM_SUFFIX})$")


# 停用词：高频功能词 / 通用代称 / 单字易误判项
# 不直接当作 EntityCandidate 输出（即便 n-gram 频率高）
_STOPWORDS: frozenset[str] = frozenset(
    [
        # 时空 / 转折连词
        "然后", "只见", "这时", "那时", "当时", "其实", "其后", "而后",
        "这样", "那样", "不过", "而且", "但是", "因为", "所以", "如果",
        "虽然", "可是", "便是", "依然", "仍然", "忽然", "突然", "终于",
        "此时", "此刻", "片刻", "霎时", "顿时", "立刻", "马上",
        # 数量 / 指代 / 通用名词
        "时候", "一个", "一些", "几个", "这里", "那里", "里面", "外面",
        "上面", "下面", "前面", "后面", "中间", "什么", "怎么", "这个",
        "那个", "如此", "这般", "那般", "其中", "其余", "其他", "其它",
        "之中", "之内", "之外", "之间", "其上", "其下",
        # 人称 / 代词 / 群体
        "自己", "别人", "大家", "我们", "他们", "她们", "你们", "众人",
        "众位", "诸位", "各位", "二人", "三人", "几人",
        # 方向动词
        "起来", "出来", "进去", "进来", "上来", "上去", "下去", "下来",
        "过去", "过来", "回来", "回去",
        # 感知 / 心理动词
        "知道", "看到", "听到", "闻到", "想到", "见到", "找到", "感到",
        "觉得", "以为", "似乎", "好像", "仿佛", "明白", "确认",
        # 身体部位 / 通用场景
        "心中", "心里", "心头", "脑海", "眼前", "眼中", "眼里", "脸上",
        "嘴角", "嘴里", "手里", "手中", "身上", "身后", "身前", "身边",
        "脚下", "肩上", "怀里", "怀中",
        # 通用人物代称（应在 EntityScanner 阶段就过滤；它们不应当独立成实体）
        "老者", "少年", "老人", "中年", "青年", "妇人", "公子", "姑娘",
        "男子", "女子", "孩童", "婴孩", "稚童", "少女", "少妇",
        # 常见量词组合
        "一阵", "一片", "一团", "一缕", "一抹", "一道", "一声", "一双",
        "几声", "几道", "几片",
        # 高频副词 / 程度
        "非常", "十分", "极为", "无比", "完全", "彻底", "几乎", "差点",
        "刚刚", "刚才", "正好", "恰好", "正在", "正要", "将要",
        # 通用动作
        "进入", "走进", "走出", "走到", "来到", "回到", "退回", "返回",
        "离开", "回头", "转身", "转头",
        # 礼貌 / 称呼通用片段（保留亲属称谓如"师父"在 alias_resolver 阶段单独处理）
        "前辈", "长辈", "晚辈", "先生", "夫人", "小姐", "公子",
    ]
)


# ---------------------------------------------------------------------------
# EntityScanner
# ---------------------------------------------------------------------------


class EntityScanner:
    """全书实体扫描器（纯正则版）。

    用法：
        scanner = EntityScanner()
        candidates = scanner.scan(full_text="...", chapter_titles=[...])
        # candidates: list[EntityCandidate] sorted by frequency desc
    """

    # ----- 配置常量 -----
    MIN_NAME_LENGTH = 2
    MAX_NAME_LENGTH = 6
    MIN_FREQUENCY_NGRAM = 5               # n-gram 候选词最低频率门槛（仅 n-gram 来源）
    MIN_FREQUENCY_OVERALL = 2             # 综合最低频率（任何来源 + n-gram 之和）
    TOP_N_CANDIDATES = 200                # 输出 top N 候选
    SAMPLE_CONTEXT_RADIUS = 24            # 每个候选词记录的上下文半径

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def scan(
        self,
        full_text: str,
        chapter_titles: Optional[list[str]] = None,
    ) -> list[EntityCandidate]:
        """扫描全文得到候选实体清单。"""
        if not full_text:
            return []

        candidates: dict[str, EntityCandidate] = {}

        # 1. 引语归属
        self._merge_into(candidates, self._scan_dialogue_attributions(full_text))
        # 2. 命名介绍
        self._merge_into(candidates, self._scan_naming_introductions(full_text))
        # 3. n-gram 频率（频率门槛较高）
        self._merge_into(candidates, self._scan_ngrams(full_text))
        # 4. 章节标题
        if chapter_titles:
            self._merge_into(candidates, self._scan_chapter_titles(chapter_titles))

        # 后处理
        self._filter_stopwords(candidates)
        self._apply_suffix_rules(candidates)
        # 先裁到 top N 再找上下文样本：n-gram 会产生十几万候选，每个都 text.find 一遍全文
        # 在 300 万字的书上要 60 秒以上（且同步阻塞事件循环），而最终只留 200 个
        top = self._merge_and_sort(candidates)
        self._fill_sample_context({c.name: c for c in top}, full_text)
        return top

    # ------------------------------------------------------------------
    # 子扫描器
    # ------------------------------------------------------------------

    def _scan_dialogue_attributions(self, text: str) -> dict[str, EntityCandidate]:
        """提取「X道：」「X笑道」等模式的说话人。"""
        result: dict[str, EntityCandidate] = {}
        for match in _RE_DIALOGUE_PRE.finditer(text):
            name = match.group(1)
            if not self._is_valid_length(name):
                continue
            self._touch(result, name, CandidateSource.DIALOGUE.value)
        for match in _RE_DIALOGUE_POST_QUOTE.finditer(text):
            name = match.group(1)
            if not self._is_valid_length(name):
                continue
            self._touch(result, name, CandidateSource.DIALOGUE.value)
        return result

    def _scan_naming_introductions(self, text: str) -> dict[str, EntityCandidate]:
        """提取命名引入模式。

        粗糙的"这位X" / "那个X" 模式已移除：噪音超过收益（X 后紧接的若是
        中文动词如"凝望"，正则会贪婪吞进 name；交给 LLM 分类即可）。
        """
        result: dict[str, EntityCandidate] = {}
        for match in _RE_NAMING.finditer(text):
            name = match.group(1).strip()
            if not self._is_valid_length(name):
                continue
            self._touch(result, name, CandidateSource.NAMING.value)
        return result

    def _scan_ngrams(self, text: str) -> dict[str, EntityCandidate]:
        """n-gram 频率扫描，对 2-4 字纯中文片段计频。

        策略：先按非中文边界切成纯中文 run，再对 run 做 n-gram 滑窗。
        这样能避免把英文/标点带进 n-gram。
        """
        from collections import Counter

        counter: Counter[str] = Counter()
        for run_match in _RE_PURE_CN_RUN.finditer(text):
            run = run_match.group(0)
            n = len(run)
            for size in range(self.MIN_NAME_LENGTH, min(self.MAX_NAME_LENGTH, n) + 1):
                # 只取 2/3/4 字 n-gram（5+ 容易是常用短语，不利于人名）
                if size > 4:
                    break
                for i in range(0, n - size + 1):
                    counter[run[i:i + size]] += 1

        result: dict[str, EntityCandidate] = {}
        for name, freq in counter.items():
            if freq < self.MIN_FREQUENCY_NGRAM:
                continue
            cand = EntityCandidate(name=name, frequency=freq)
            cand.add_source(CandidateSource.NGRAM.value)
            result[name] = cand
        return result

    def _scan_chapter_titles(self, titles: list[str]) -> dict[str, EntityCandidate]:
        """从章节标题里提取可能的 2-4 字专名。

        改为 n-gram 全子串扫描：对于 "大战青云宗"，需要能同时抽到 "大战"/"青云"/
        "云宗"/"青云宗" 等所有 2-4 字片段。这会带入噪音（"大战"/"云宗"），
        但相比错过真名 ("青云宗") 噪音可控；噪音由 LLM 分类阶段拒绝。
        """
        result: dict[str, EntityCandidate] = {}
        for title in titles:
            if not title:
                continue
            for run_match in _RE_PURE_CN_RUN.finditer(title):
                run = run_match.group(0)
                n = len(run)
                for size in (2, 3, 4):
                    if size > n:
                        break
                    for i in range(0, n - size + 1):
                        fragment = run[i:i + size]
                        self._touch(result, fragment, CandidateSource.TITLE.value)
        return result

    # ------------------------------------------------------------------
    # 后处理
    # ------------------------------------------------------------------

    def _apply_suffix_rules(self, candidates: dict[str, EntityCandidate]) -> None:
        """根据后缀规则给候选词打 suggested_type 标记。"""
        for name, cand in candidates.items():
            if cand.suggested_type:
                continue
            if _RE_LOCATION_SUFFIX.match(name):
                cand.suggested_type = "location"
                cand.add_source(CandidateSource.SUFFIX.value)
            elif _RE_ORG_SUFFIX.match(name):
                cand.suggested_type = "org"
                cand.add_source(CandidateSource.SUFFIX.value)
            elif _RE_ITEM_SUFFIX.match(name):
                cand.suggested_type = "item"
                cand.add_source(CandidateSource.SUFFIX.value)

    def _filter_stopwords(self, candidates: dict[str, EntityCandidate]) -> None:
        """就地过滤停用词（不返回新 dict，避免一次性内存翻倍）。"""
        for name in list(candidates.keys()):
            if name in _STOPWORDS:
                del candidates[name]

    def _fill_sample_context(self, candidates: dict[str, EntityCandidate], text: str) -> None:
        """为每个候选词找一个上下文样本（首次出现位置 ± SAMPLE_CONTEXT_RADIUS）。"""
        for name, cand in candidates.items():
            idx = text.find(name)
            if idx < 0:
                continue
            start = max(0, idx - self.SAMPLE_CONTEXT_RADIUS)
            end = min(len(text), idx + len(name) + self.SAMPLE_CONTEXT_RADIUS)
            ctx = text[start:end]
            # 去多余换行让 prompt 更紧凑
            ctx = ctx.replace("\r", "").replace("\n", " ").strip()
            cand.sample_context = ctx

    def _merge_and_sort(self, candidates: dict[str, EntityCandidate]) -> list[EntityCandidate]:
        """频率倒序 + 应用 MIN_FREQUENCY_OVERALL + top N 限制。"""
        items = [c for c in candidates.values() if c.frequency >= self.MIN_FREQUENCY_OVERALL]
        items.sort(
            key=lambda c: (
                c.frequency,
                # 多信号源加权：来源种类越多越优先
                len(c.sources),
                # 长度更短的字符串排前（"林七" 优于 "林天才七公子"）
                -len(c.name),
            ),
            reverse=True,
        )
        return items[: self.TOP_N_CANDIDATES]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_valid_length(self, name: str) -> bool:
        return self.MIN_NAME_LENGTH <= len(name) <= self.MAX_NAME_LENGTH

    @staticmethod
    def _touch(
        store: dict[str, EntityCandidate],
        name: str,
        source: str,
        increment: int = 1,
    ) -> EntityCandidate:
        """在字典里 +1 一个候选并记录来源。"""
        cand = store.get(name)
        if cand is None:
            cand = EntityCandidate(name=name, frequency=0)
            store[name] = cand
        cand.frequency += increment
        cand.add_source(source)
        return cand

    @staticmethod
    def _merge_into(
        target: dict[str, EntityCandidate],
        partial: dict[str, EntityCandidate],
    ) -> None:
        """把 partial 的候选合并到 target（频率累加，source 取并集）。"""
        for name, cand in partial.items():
            existing = target.get(name)
            if existing is None:
                target[name] = cand
                continue
            existing.frequency += cand.frequency
            for src in cand.sources:
                existing.add_source(src)
            if cand.sample_context and not existing.sample_context:
                existing.sample_context = cand.sample_context
            if cand.suggested_type and not existing.suggested_type:
                existing.suggested_type = cand.suggested_type
