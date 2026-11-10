/**
 * 首页的静态文案：九步创作流程（预览框随步骤切换的示例内容）、各区块的卡片、题材、常见问题。
 * 示例故事《夜航灯》是首页专用的演示内容，不对应任何真实项目。
 */
import type { LucideIcon } from 'lucide-react'
import { loginHref } from '@/utils/loginRoute'
import {
  BookMarked, Bot, BrainCircuit, Container, Feather, Flag, Laptop, Link2, ListChecks, MessagesSquare, NotebookPen,
  Route as RouteIcon, ScanSearch, ServerCog, ShieldCheck, Sparkles, Undo2, Users, WandSparkles,
} from 'lucide-react'

export const SISTER_SECTION_ID = 'stardraw'

/** 顶栏锚点：[区块 id, 文字] */
export const HOME_NAV = [
  ['features', '功能'], ['team', '创作团队'], ['control', '你来拍板'], ['planning', '规划'], ['deploy', '部署'],
  [SISTER_SECTION_ID, '星绘 Studio'], ['faq', '常见问题'],
] as const

export const REPO_URL = 'https://github.com/ddys9621/WenlanAI'
export const RELEASES_URL = `${REPO_URL}/releases/latest`
export const GUIDE_URL = `${REPO_URL}/blob/master/%E5%B0%8F%E7%99%BD%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E.md`

/** 首页入口的去处：没登录先打开登录弹窗（首页 ?login=1），登录完去要去的地方（user 为 undefined = 还在探测，按没登录算） */
export function entryHref(user: unknown, path: string): string {
  return user ? path : loginHref(path)
}

/** 「一句话开新书」：带着这句灵感去书架打开灵感模式（书架读 idea 参数预填进输入框） */
export function ideaHref(user: unknown, idea: string): string {
  const text = idea.trim().slice(0, 500)
  return entryHref(user, text ? `/projects?panel=inspiration&idea=${encodeURIComponent(text)}` : '/projects?panel=inspiration')
}

/** 首屏输入框里轮播的灵感示例（也是下面可点的灵感胶囊） */
export const HERO_IDEAS = [
  '灯塔守护者发现，每一盏灯烧的都是人的魂火',
  '被退婚的炼丹师，开了一家只收故事的当铺',
  '末日第七天，我在便利店当夜班店长',
  '女捕快查一桩旧案，查到了自己的名字',
]

export const HERO_STATS: [string, string][] = [
  ['7', '位 AI 创作成员'],
  ['9', '步从灵感到完本'],
  ['1', '键撤回一整轮'],
  ['100%', '数据在你手里'],
]

/** 创作团队一节：点一位成员，右边换成他接活时的一段对话 */
export const MEMBER_DEMOS: Record<string, { ask: string; reply: string; receipt: string }> = {
  主编: { ask: '帮我把这本书推进到能写正文', reply: '先补世界设定，再定主角和总纲；每一步出的卡你确认了，我安排下一位接着做。', receipt: '安排分工 · 3 位成员' },
  世界观设定师: { ask: '把修炼体系补完整', reply: '按「点灯折寿」的代价拆成七重灯境，每一重写清门槛、代价和社会地位。', receipt: '生成世界规则 · 7 条' },
  人物设计师: { ask: '再加一个亦正亦邪的配角', reply: '加了「顾衡」：灯会掌灯使，护着航路也护着魂火账；和主角是师兄弟。', receipt: '新建候选 · 1 个人物、2 条关系' },
  总纲策划师: { ask: '主线再狠一点', reply: '把「查灯」提前到第一卷末：主角亲手点燃了师父的魂火，才发现灯油的来路。', receipt: '修改总纲 · 全书主线' },
  章节策划师: { ask: '第一卷细化成剧情单元', reply: '拆成学徒、魂火、第七座灯塔、夜航四件事，每件写清起因、阻碍和代价。', receipt: '细化卷纲 · 4 个剧情单元' },
  正文作者: { ask: '写第 12 章', reply: '按章纲写好了 3,086 字，「灯油的来历」在这章回收；在写作卡里看正文和对比。', receipt: '写一章正文 · 待采用' },
  审校编辑: { ask: '看看前十章有没有矛盾', reply: '第 7 章沈禾说不识字，第 9 章却在记账——建议改成「只认得数字」。', receipt: '审校 · 2 处问题' },
}

/** 预览框中栏的内容块 */
export type PreviewBlock =
  | { kind: 'fields'; rows: [string, string][] }
  | { kind: 'cards'; items: { name: string; tag: string; desc: string }[] }
  | { kind: 'outline'; items: { no: string; title: string; desc: string; done?: boolean }[] }
  | { kind: 'prose'; paragraphs: string[] }
  | { kind: 'diff'; pairs: { before: string; after: string }[] }
  | { kind: 'promises'; items: { type: string; title: string; reason: string; urgent?: boolean }[] }
  | { kind: 'export'; items: { name: string; desc: string }[] }

export interface PreviewStep {
  key: string
  label: string
  /** 左栏亮的页签与入口 */
  tab: '设定' | '大纲' | '目录' | '资料'
  nav: string
  title: string
  desc: string
  blocks: PreviewBlock[]
  /** 右栏：作者说的话、哪位成员接、他说的那句话、回执、回复 */
  ask: string
  member: string
  note: string
  receipt: string
  reply: string
}

export const SIDEBAR_ITEMS: Record<PreviewStep['tab'], string[]> = {
  设定: ['作品信息', '世界设定', '世界规则', '设定条目', '角色与组织', '关系管理'],
  大纲: ['总纲', '卷纲', '章纲'],
  目录: ['第 1 章 灯油', '第 2 章 守塔人', '第 3 章 第七座灯塔', '第 4 章 雾里的船'],
  资料: ['写作风格', '提示词', '仿写参考', '故事账本'],
}

export const PREVIEW_STEPS: PreviewStep[] = [
  {
    key: 'idea', label: '开书立项', tab: '设定', nav: '作品信息', title: '作品信息', desc: '书名、类型、简介和全书规模',
    blocks: [{
      kind: 'fields', rows: [
        ['书名候选', '《夜航灯》 ·《雾海灯匠》 ·《一灯照九州》'],
        ['类型', '玄幻 · 成长'],
        ['简介', '雾海里没有星，船只靠灯塔认路。灯匠学徒林照发现，每一座灯塔烧的都是人的魂火……'],
        ['全书规模', '300 章 · 第三人称 · 每章约 3000 字'],
      ],
    }],
    ask: '我想写一个灯塔守护者的故事', member: '主编',
    note: '先把作品信息定下来：书名、类型、简介各给几个方向',
    receipt: '生成作品信息 · 书名 6 个候选', reply: '挑一个书名和简介，或者告诉我你更想要的方向。',
  },
  {
    key: 'world', label: '世界设定', tab: '设定', nav: '世界设定', title: '世界设定', desc: '时代、地点、氛围与规则分开整理',
    blocks: [{
      kind: 'fields', rows: [
        ['时代背景', '灯火纪元第七百年，雾海吞没了旧大陆，只剩群岛'],
        ['地点设定', '雾海群岛，十二座灯塔连成唯一的航路'],
        ['氛围基调', '潮湿、压抑，底下压着一点不肯灭的希望'],
        ['世界规则', '灯以魂火为油：点灯人每点一夜，折寿一日'],
      ],
    }],
    ask: '帮我补世界设定', member: '世界观设定师',
    note: '作品信息齐了，按世界设定的四栏补，只补空着的',
    receipt: '生成世界设定 · 4 栏', reply: '四栏都放进卡片了，你确认后写进书里。',
  },
  {
    key: 'cast', label: '角色与组织', tab: '设定', nav: '角色与组织', title: '角色与组织', desc: '人物、势力与彼此的关系',
    blocks: [{
      kind: 'cards', items: [
        { name: '林照', tag: '主角', desc: '灯匠学徒，能看见魂火的颜色' },
        { name: '沈禾', tag: '女主', desc: '守塔人之女，话少，记账很快' },
        { name: '顾衡', tag: '反派', desc: '灯会最年轻的掌灯使，左手常年缠着布' },
        { name: '灯会', tag: '组织', desc: '掌管全部灯塔的行会，也掌管魂火的来路' },
      ],
    }],
    ask: '生成主角和一个反派', member: '人物设计师',
    note: '点灯要折寿，主角就从这条代价出发',
    receipt: '生成角色与组织 · 3 个人物、1 个组织', reply: '人物关系也一起提了，建档后在关系页能看到。',
  },
  {
    key: 'outline', label: '总纲', tab: '大纲', nav: '总纲', title: '总纲', desc: '全书往哪走，一次定清楚',
    blocks: [{
      kind: 'fields', rows: [
        ['故事梗概', '学徒林照追查第七座灯塔熄灭的真相，一路查到灯会的魂火账'],
        ['全书主线', '点灯 → 查灯 → 夺灯 → 换一种不烧人的灯'],
        ['金手指', '看得见魂火的颜色，分得清谁在替谁燃烧'],
        ['核心卖点', '代价明确的成长、悬疑推进、群像温情'],
      ],
    }],
    ask: '写总纲', member: '总纲策划师',
    note: '人物齐了，总纲按梗概、主线、金手指、卖点四项写',
    receipt: '生成总纲 · 4 项', reply: '先看主线这一条，方向对了我们再分卷。',
  },
  {
    key: 'plan', label: '卷纲与章纲', tab: '大纲', nav: '卷纲', title: '卷纲 · 章纲', desc: '每卷拆成几件完整的事，再落到章',
    blocks: [{
      kind: 'outline', items: [
        { no: '第一卷', title: '第七座灯塔', desc: '第 1–40 章 · 4 个剧情单元', done: true },
        { no: '单元 1', title: '学徒', desc: '第 1–6 章：林照第一次替师父点灯', done: true },
        { no: '第 1 章', title: '灯油', desc: '开头接：码头的夜；写到：林照闻出灯油的味道就停' },
        { no: '第 2 章', title: '守塔人', desc: '本章回收：「灯油的来历」；不能提前：顾衡露面' },
      ],
    }],
    ask: '分卷，再把第一卷的章纲做出来', member: '章节策划师',
    note: '全书 300 章先分 6 卷，第一卷细化成剧情单元',
    receipt: '规划分卷 · 6 卷 ｜ 生成章纲 · 6 章', reply: '草案逐层确认：先定卷，再定单元，最后定章纲。',
  },
  {
    key: 'write', label: '写正文', tab: '目录', nav: '第 1 章 灯油', title: '第 1 章 灯油', desc: '码字、候选稿与历史版本',
    blocks: [{
      kind: 'prose', paragraphs: [
        '码头的雾是从脚底下长出来的。林照提着油壶走到第三根系船柱的时候，鞋面已经湿透了。',
        '师父说过，灯油不能闻。他还是闻了——一股烧过头发的味道，底下压着一点甜，像谁哭过之后的呼吸。',
        '“照。”塔上有人喊他，“上来，今晚你点。”',
      ],
    }],
    ask: '写第一章', member: '正文作者',
    note: '第 1 章章纲确认过了，交给正文作者写',
    receipt: '写一章正文 · 3,120 字 · 待采用', reply: '写好了，在写作卡里看正文、和现在的正文对比，满意就采用。',
  },
  {
    key: 'ledger', label: '伏笔与账本', tab: '资料', nav: '故事账本', title: '故事账本', desc: '伏笔、人物状态、章节档案与时间线',
    blocks: [{
      kind: 'promises', items: [
        { type: '伏笔', title: '灯油的来历', reason: '本章章纲要回收', urgent: true },
        { type: '悬念', title: '第七座灯塔为什么熄了', reason: '已超期（计划第 10 章前回收）', urgent: true },
        { type: '承诺', title: '带沈禾去看没有雾的海', reason: '25 章没提了' },
      ],
    }],
    ask: '检查一下前面的伏笔', member: '审校编辑',
    note: '先看写第 12 章时该照应的伏笔',
    receipt: '查看伏笔提醒 · 3 条', reply: '「灯油的来历」这章要回收，另外两条我在回复里列了建议。',
  },
  {
    key: 'polish', label: '去 AI 味', tab: '目录', nav: '第 3 章 第七座灯塔', title: '第 3 章 第七座灯塔', desc: '逐段改写，先出候选稿',
    blocks: [{
      kind: 'diff', pairs: [
        { before: '他的心中涌起一股难以言喻的悲伤，仿佛整个世界都在这一刻安静了下来。', after: '他没出声，把油壶放下，壶底磕在石阶上，响了一下。' },
        { before: '她嘴角勾起一抹淡淡的微笑。', after: '她低头把账本翻过一页。' },
      ],
    }],
    ask: '第 3 章去 AI 味', member: '正文作者',
    note: '按「去 AI 味」的写法逐段改，删套话、换成动作',
    receipt: '改写 · 12 处 · 待采用', reply: '改动在候选稿里逐句对比，采用了才替换正文，旧稿进历史版本。',
  },
  {
    key: 'export', label: '导出成书', tab: '目录', nav: '第 4 章 雾里的船', title: '导出', desc: '整本书带走',
    blocks: [{
      kind: 'export', items: [
        { name: '导出 TXT', desc: '按章节顺序输出正文，直接投稿或备份' },
        { name: '导出项目', desc: '设定、大纲、正文、故事账本一起打包，可在别处导入' },
      ],
    }],
    ask: '导出全书', member: '主编',
    note: '第一卷写完了，先导出一份 TXT 备份',
    receipt: '导出 TXT · 40 章 · 12.6 万字', reply: '导出好了。下一卷的卷纲要不要现在细化？',
  },
]

export interface FeatureCard {
  icon: LucideIcon
  title: string
  desc: string
}

export const LONGFORM_CARDS: FeatureCard[] = [
  { icon: BookMarked, title: '写到后面，前面对得上', desc: '每章写完自动分析：人物状态、物品、境界、伏笔和时间线记进故事账本；写下一章时按需带上，和设定冲突的先提醒你。' },
  { icon: Link2, title: '续写接得上前文', desc: '写正文前带上上一章结尾、本章章纲和章节契约（从哪接、写到哪停、哪些事不能提前），以及本章出场人物的当前状态。' },
  { icon: Flag, title: '伏笔不掉线', desc: '章纲写明本章要回收、推进、埋下哪条伏笔；写作时底栏提醒，全书悬念时间线一眼看全，超期、掉线都标出来。' },
  { icon: Users, title: '人物不走样', desc: '性格、说话方式、关系和组织归属一起带进生成；给人物改名，章纲和档案里记着的名字一起换。' },
  { icon: Feather, title: '写出来像你', desc: '写作风格按书设定，去 AI 味逐段改写；AI 的结果先成候选稿，你采用了才替换正文，旧稿留在历史版本。' },
  { icon: ListChecks, title: '大纲不跑偏', desc: '总纲 → 卷纲 → 章纲逐层确认才往下走；正文写完对照章纲检查有没有写偏、有没有提前写了不该写的。' },
]

export const TEAM_MEMBERS: { name: string; initials: string; tone: string; duty: string }[] = [
  { name: '主编', initials: '编', tone: 'bg-emerald-100 text-emerald-700', duty: '和你商量方向、安排分工' },
  { name: '世界观设定师', initials: '世', tone: 'bg-sky-100 text-sky-700', duty: '世界设定、规则与设定条目' },
  { name: '人物设计师', initials: '人', tone: 'bg-rose-100 text-rose-700', duty: '角色、组织与人物关系' },
  { name: '总纲策划师', initials: '纲', tone: 'bg-amber-100 text-amber-700', duty: '总纲与全书主线' },
  { name: '章节策划师', initials: '章', tone: 'bg-violet-100 text-violet-700', duty: '分卷、剧情单元与章纲' },
  { name: '正文作者', initials: '写', tone: 'bg-orange-100 text-orange-700', duty: '按章纲写正文、改写润色' },
  { name: '审校编辑', initials: '审', tone: 'bg-slate-100 text-slate-700', duty: '对照设定和前文挑问题' },
]

export const TEAM_SCENARIOS: { title: string; quote: string; desc: string }[] = [
  { title: '从一个灵感开始', quote: '我想写一个灯塔守护者的故事', desc: '先定书名、简介、类型，再补世界设定、生成主角、写总纲；每一步出的卡你确认了，团队接着往下做。' },
  { title: '接着往下写', quote: '写第 12 章', desc: '先看前情和本章章纲，缺什么先补什么；写好的章在对话里出一张写作卡，看正文、逐句对比、一键采用。' },
  { title: '检查前文问题', quote: '看看前面哪里写矛盾了', desc: '审校编辑对照设定、故事账本逐章核对，引用原文指出问题，并给出怎么改。' },
  { title: '一口气做完', quote: '打开「自动执行」', desc: '修改直接应用、草案直接确认、正文写完直接采用，一轮从上游做到你要的结果；每一步写进了什么都列在回执里。' },
]

export const CONTROL_CARDS: FeatureCard[] = [
  { icon: ShieldCheck, title: '先出卡片，你确认才写入', desc: '修改带前后对比，新建要你建档，草案要你确认，正文先成候选稿。' },
  { icon: Undo2, title: '一整轮撤回', desc: '这一轮写进书里的修改、新建、正文一次撤回；撤不了的写明原因。' },
  { icon: MessagesSquare, title: '处理中接着说', desc: '团队忙的时候照样能补充要求，下一步开始前就读到。' },
  { icon: Sparkles, title: '每一步看得见', desc: '先说一句在做什么，再给一行回执：做了什么、成没成。' },
  { icon: NotebookPen, title: '作品备忘', desc: '长期偏好和定下的约定记下来，每轮都带上，开新对话也不丢。' },
  { icon: WandSparkles, title: '写作技能', desc: '黄金三章、开篇钩子、章纲写法、去 AI 味……打「/」点名，这一轮照着做。' },
]

export const PLANNING_CHAIN: { name: string; desc: string }[] = [
  { name: '总纲', desc: '故事梗概、全书主线、金手指与核心卖点' },
  { name: '卷纲', desc: '每卷拆成几件完整的事，线索编排写清每条线推进到哪' },
  { name: '章纲', desc: '场景、视角、关键事件和章节契约：从哪接、写到哪停' },
  { name: '正文', desc: '按章纲写候选稿，采用才替换正文，旧稿进历史版本' },
]

export const MODEL_CARDS: FeatureCard[] = [
  { icon: Bot, title: '接你自己的模型', desc: '支持 OpenAI 兼容接口，云端模型和本地模型都能接。' },
  { icon: BrainCircuit, title: '每位成员单独选', desc: '商量剧情用一个模型，写正文换一个更会写的，审校用便宜的。' },
  { icon: ScanSearch, title: '上下文用量看得见', desc: '每次发给模型的内容占多少一目了然；聊得久了，较早的对话自动压成前情摘要。' },
]

export const DEPLOY_CARDS: FeatureCard[] = [
  { icon: Laptop, title: 'Windows 桌面版', desc: '安装即用，一个窗口写到底；数据库和设置都存在你自己的电脑上。' },
  { icon: Container, title: 'Docker 部署', desc: '部署到服务器，多人各用各的账号；管理员管用户和登录方式。' },
  { icon: ServerCog, title: '源码运行', desc: '自己改、自己跑，适合想深度定制的作者和团队。' },
]

export const KNOWLEDGE_POINTS: { icon: LucideIcon; title: string; desc: string }[] = [
  { icon: RouteIcon, title: '拆书', desc: '把一本书拆成分卷、剧情单元和写法要点：一件事写几章、紧张之后怎么缓。' },
  { icon: BookMarked, title: '知识库', desc: '拆好的书和你的资料都进知识库，写作时可以检索、引用。' },
  { icon: Sparkles, title: '仿写参考', desc: '设一本对标书，分卷、章纲和正文按它的节奏和结构参考，不照搬人物和情节。' },
]

export const GENRES = [
  '玄幻仙侠', '都市言情', '科幻末世', '悬疑推理', '历史军事', '游戏竞技', '武侠江湖',
  '系统流', '无限流', '种田经营', '宫斗宅斗', '轻小说', '克苏鲁', '严肃文学',
]

export const SISTER_PROJECT = {
  name: '星绘 Studio',
  url: 'https://xh.kr03.sixfog.com/',
  kind: '姊妹项目 · AI 视觉创作工作台',
  title: '让书里的人物，走出纸面',
  desc: '照着人物设定画出角色设定图和三视图，给书做一张封面海报，把章节改编成漫剧短片；图片、视频、音频都在一个工作台里做完。',
  tags: ['图片生成', '视频创作', '漫剧创作', '无限画布', '智能 Agent'],
}

export const FAQ: { q: string; a: string }[] = [
  {
    q: '文澜 AI 是什么？',
    a: '面向长篇小说的创作工作台。你决定故事往哪走，AI 创作团队负责把想法落成世界观、人物、大纲和正文，并按章整理伏笔、人物状态和前情。每一处改动都先给你看，你确认了才写进书里。',
  },
  {
    q: '需要自己准备模型吗？',
    a: '需要。在设置里填上你自己的模型接口（OpenAI 兼容即可），云端模型或本地模型都行；共创室里每位成员还能单独指定模型。',
  },
  {
    q: '数据存在哪里？',
    a: '存在你自己部署的地方：桌面版存在本机，服务器部署就存在你的服务器上。项目可以随时导出成 TXT 或完整备份。',
  },
  {
    q: '写到几百章，怎么避免前后矛盾？',
    a: '每章写完会自动分析，人物状态、伏笔、因果和时间线进故事账本；写新章时把相关的前情、人物当前状态和本章要照应的伏笔一起带上，写作页底部还会提醒该回收的伏笔。',
  },
  {
    q: 'AI 会直接改我的稿子吗？',
    a: '默认不会：修改、新建、草案和正文都先成卡片或候选稿，你点了才写入。打开「自动执行」才会直接写，而且一整轮可以一次撤回。',
  },
  {
    q: '能参考别的书来写吗？',
    a: '可以。拆书功能把一本书拆成分卷、剧情单元和写法要点存进知识库；设成对标书后，规划和写作会参考它的节奏和结构，但不照搬人物和情节。',
  },
  {
    q: '要花钱吗？',
    a: '文澜 AI 部署在你自己的电脑或服务器上；写作时调用的模型按你接入的服务商计费。',
  },
]
