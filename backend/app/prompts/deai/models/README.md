# 模型家族先验表：怎么建、怎么加

本目录每个 `<family>.prior.md` 会在写 / 改 / 审三处注入提示词（`deai_rules.model_prior`），
只要 `detect_model_family` 能识别出这个家族且文件存在。本文件不是家族名，不会被注入。

文件名必须带 `.prior` 后缀：裸的 `claude.md` 在 Windows（文件名大小写不敏感）会被 Claude Code / Devin 等 AI 编码工具
当成 `CLAUDE.md` 指令文件自动加载进会话，把小说先验当成编码规则。

## 规矩（沿用 sepia）

1. **不猜。** 每条倾向都要能指向一个来源；写不出来源的，不进表。
2. **证据分级并标注在条目上。** 优先级从高到低：
   - 实测（语料统计 / 受控盲评，最好有数字）
   - 厂商自述（模型卡、官方提示指南里关于"它默认怎么写"的句子）
   - 编辑观察（社区 / 编辑 / 我们自己读样本得出的印象，n 小，标"未量测"）
3. **只写"倾向 → 纠正"。** 表是给模型执行的，不是评测报告；数字点到为止，细节放本文件。
4. **英文测得的是形状。** 对应到中文写法是推断，条目里要写出中文形态（例如 "said, voice low" → "压低声音说"）。
5. **按版本分列。** 同一家族不同版本可以行为相反（Grok 4.5 复读、4.6 大纲体），先验会随版本过时，写明核实日期。
6. **校准优先。** 表里的纠正也受 `calibration.md` 管：每章挑 3–5 招，不要把每条都用满。

## 找证据的地方（按可靠度）

| 来源 | 能拿到什么 | 备注 |
|---|---|---|
| StoryScope（arXiv 2604.03136） | 叙事层 30 项特征的逐模型指纹 | 只测了 Claude / GPT / Gemini / DeepSeek / Kimi，sepia 原表来源 |
| EQ-Bench Creative Writing v3（eqbench.com/creative_writing.html） | 每模型 96 篇英文短篇：slop / 重复度 / 篇幅 / 词汇复杂度；评审判据相对强弱（Purple Prose、Pacing、Show-Don't-Tell…）；高频重复短语与词；风格描述词 | 数据在页面的 `creative_writing.js` / `creative_writing_chartdata*.js` 里，`backend/scripts/deai_model_evidence.py` 可一键抽取 |
| Lech Mazur 短篇成对盲评（github.com/lechmazur/writing） | `reports/pair_analysis/` 下逐模型的定性报告（叙事控制、因果、结尾、散文），带核验声明编号 | 英文；分析者是 LLM，但每条声明附原文证据 |
| Foreverse 中文续写横评（foreverse.app/zh/blog） | 两本中文书 20 轮续写、成对双盲：逐字重复率、意象复用计数、「我」密度、篇幅 | 目前唯一按文体（玄幻 / 女频）分开测中文小说的公开来源；n 小（每书一条链） |
| 厂商文档 / 模型卡 | 官方写作风格自述、采样参数限制 | xAI 没有写作风格指南，只有 RL 目标的描述 |
| 社区观察（知乎 / 龙空 / Reddit） | 口癖、拒写、复读等印象 | 标"编辑观察、未量测" |

## 步骤

1. 跑 `python backend/scripts/deai_model_evidence.py <模型名片段>`（如 `grok`、`qwen`、`glm`），得到 EQ-Bench 的数字、判据强弱、高频短语、风格词，看它相对榜单中位偏在哪。
2. 找该家族的成对定性报告 / 中文实测，把"结尾怎么收、动机怎么给、意象和口癖"这类叙事层观察摘出来。
3. 每条写成"倾向〔标签〕→ 纠正"，中文形态写明，按版本分列。
4. 文件名 = `detect_model_family` 返回的家族名 + `.prior.md`（如 `qwen.prior.md`）；家族还不能识别的，在 `deai_rules._FAMILY_PATTERNS` 加一行。
5. 在 `tests/test_deai_rules.py` 加一条"该表存在且带证据标签"的用例；重启服务生效（规则文件 lru_cache）。

## Grok 表的来源（2026-09-12 核实）

- 〔EQ〕EQ-Bench Creative Writing v3，https://eqbench.com/creative_writing.html （数据文件 `creative_writing.js?v=1.0.91`、`creative_writing_chartdata.js`、`creative_writing_chartdata_style.js`）。
  榜单列：model, elo, rubric, avg_length, vocab_complexity, slop, repetition。133 个模型，slop 中位 25.5、重复度中位 4.42、篇幅中位 6509 字符。
  grok-4.5：elo 1576、slop 17.73、重复 3.52、篇幅 7190、词汇 36.87；grok-4.20-beta：1570.7 / 15.85 / 4.50 / 7250；grok-4.1-fast：1324.8 / 36.48 / 4.56 / 6483；grok-3-beta：1183.5 / 33.88 / 4.26 / 7022。
  判据相对强弱（对同榜模型，对数刻度）：4.5 弱项 Pacing −1.0、Avoids Purple Prose −0.67、Show-Don't-Tell −0.27；强项 Avoids Positivity Bias +1.0、Instruction Following +0.68。4.1-fast 弱项 Avoids Purple Prose −1.0、Sentence Flow −0.55。3-beta 弱项 Avoids Purple Prose −1.0、Pacing −0.37。4.20-beta 反向：Avoids Purple Prose +0.84、Strong Dialogue +1.0，弱项 Instruction Following −1.0。
  高频重复短语（4.5 / 4.20）：said, voice low · faint metallic tang · heart hammering (against his ribs) · smiled without warmth · air hung thick · like distant thunder · smells like / tastes like / air smelled · six months ago · three nights ago · three full seconds · half second · looked at her then, really looked · opened her mouth, closed it · sounded suspiciously like · like someone trying · internal monologue · muscle memory；二元组 "word count" 27 / 62 次；4.20 "must decline this request" 13 次。高频词：memetic、amnestics、viewport、airlock、anomalous、flickered、hummed、gleamed、hissed、murmured；人名 kael、voss、lira、hana、elias、elin、rika、harlan。
  风格描述词（评审对该模型最偏爱的形容）：3-beta risky / gritty / hyperbolic / lavish / vulgar / profane / overwrought；4.1-fast gritty / vulgar / profane / cinematic / decadent / flashy / lush；4.20-beta funny / dialogue-driven / vulgar / dark humor / cliche / grandiose / sardonic；4.5 introspective / calm / engineered / visceral / matter-of-fact / sparse / dry / wry / irreverent / minimalist。
- 〔LM〕Lech Mazur, "Grok 4.6 (high) vs. grok-4.5-high: comparative writing analysis"，https://github.com/lechmazur/writing/blob/main/reports/pair_analysis/grok-4.6-high__vs__grok-4.5-high__comparator_v2_eval_v2_v3_predecessor_depth_n50__subjective_v4_extended_reader_summary.md
  50 对匹配提示，4.6 胜 42 / 平 2 / 负 6；分析者 gpt-5.6-high、kimi-k3、claude-opus-5-xhigh，87 条核验声明。两代共有：孤身专家 + 规定方法 + 规定物品 + 启示的模板；动机宣告而非发展；几乎无幽默、无持续对话、无形式实验；人名回收；真相靠静电、涟漪、信件独自发现。4.5 独有：结尾跳出故事核验合规（"all elements wove together seamlessly"）、叙述者记账（"the action unfolded"）、把提示词短语原时态化石般嵌进过去时叙述、前置交代、结局扩散到社群与制度、全员皈依。4.6：结局有界、留问题活着，但会滑成格言式简写或公式化开放结尾。
  同榜（当前成对榜）Grok 4.6 (high) 第 46、Grok 4.3 第 49、Grok 4.5 (high) 第 50（共 50 左右），https://github.com/lechmazur/writing
- 〔FV〕Foreverse《Grok 4.5 的卷宗，我们按原协议重审了一遍》（2026-08-13），https://foreverse.app/zh/blog/grok-4-6-fiction-retrial ；《Grok 能写小说吗？能，但先看这两次复读实测》，https://foreverse.app/zh/blog/grok-continue-novel-howto
  协议：890 万字传统玄幻 + 《后宫·甄嬛传》，55% 深度起笔，1.6 万 token 滚动窗口，20 轮，温度 0.7，六家评委成对双盲。4.5：玄幻第 9–11 轮同 271 字逐字循环三遍；女频「菖蒲」19 轮 21 次、「麝香混着」13 次，剧情 20 轮停在案发当日；每千字「我」9.0（原著）→ 5.2。4.6：对前代 12:0 / 12:0；12-gram 跨轮重复峰值 2.8% / 2.1%；「我」11.0；每轮约 150 字（冠军 475），女频对冠军 2:10，评语"大纲化萎缩、叙事干瘪"；意象复用「铁锈腥气」9 轮 9 次、「阴冷」12 次、「腥甜」8 轮 6 次、「井水」5 轮。推理 token 占输出 95.5%。
- 〔V〕xAI, "Grok 4.1"（x.ai/news/grok-4-1，2025-11）：用 Grok 4 的强化学习基础设施"optimize the style, personality, helpfulness, and alignment"，以前沿 agentic 推理模型作奖励模型自动评分迭代；自评 EQ-Bench3 与 Creative Writing v3。xAI 无写作风格提示指南（docs.x.ai 仅有语音实时 prompting guide）。
  采样限制（docs.x.ai reasoning 页）：推理模型不支持 `presence_penalty` / `frequency_penalty` / `stop`，带上会直接报错；`presence_penalty` 连 grok-3 也不支持。
- 未采纳：《经济学人》"How to spot AI writing"（2026-07-31）对 ChatGPT / Claude / Gemini / Grok 的标点统计——仅见 X 上转述，方法未公开，sepia 自己也判定对白名单"changes nothing"。

## 边界

- EQ / LM 是英文短篇（LM 还是 400–700 词的受限命题），到中文长篇章节是形状迁移；FV 是中文但每书只有一条链（n=1）。
- 三处评审都是 LLM 评委（EQ 用 Claude Sonnet，LM 用三家，FV 用六家），不是人类读者；数字是方向，不是阈值。
- Grok 版本更迭快（4.3 → 4.5 → 4.6 半年三版），条目按版本挂，核实日期就是保质期。
