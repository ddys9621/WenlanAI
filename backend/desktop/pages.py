"""桌面版本地页面：主窗口的启动画面、按需打开的运行日志窗口。

样式与前端设计系统一致（frontend/src/globals.css、tailwind.config.js、BrandLogo.tsx）：
参考岚笺「青舟」：纸色画布、墨绿主色 #285b4d、朱砂信号色、扁平线框小圆角、Inter/Segoe/苹方/雅黑字体栈、lucide 线性图标。
启动画面与登录页同为「居中白卡」，进入登录页时画面不跳。
"""

# BrandLogo 的书页 + 笔迹（viewBox 256）
_LOGO_SVG = """<svg viewBox="0 0 256 256" fill="none">
      <defs>
        <mask id="logo-not-stroke" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
          <rect width="256" height="256" fill="#fff"/>
          <path d="M74 156C100 132 118 158 136 136C154 114 176 90 212 60" stroke="#000" stroke-width="16" stroke-linecap="round"/>
        </mask>
        <mask id="logo-not-pages" maskUnits="userSpaceOnUse" x="0" y="0" width="256" height="256">
          <rect width="256" height="256" fill="#fff"/>
          <path d="M48 84C76 72 104 76 122 94V196C104 178 76 174 48 186ZM208 84C180 72 152 76 134 94V196C152 178 180 174 208 186Z" fill="#000"/>
        </mask>
      </defs>
      <path d="M48 84C76 72 104 76 122 94V196C104 178 76 174 48 186ZM208 84C180 72 152 76 134 94V196C152 178 180 174 208 186Z" fill="currentColor" mask="url(#logo-not-stroke)"/>
      <path d="M74 156C100 132 118 158 136 136C154 114 176 90 212 60" stroke="currentColor" stroke-width="16" stroke-linecap="round" mask="url(#logo-not-pages)"/>
    </svg>"""

SPLASH_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>文澜 AI</title>
<style>
:root {
  --brand:#285b4d; --brand-600:#204a3e; --brand-400:#4f8a76; --signal:#d15b3d; --cinnabar:#a84337; --cinnabar-wash:#faeae7;
  --surface:#f3f5f3; --border:#d4dad6; --border-light:#e4e9e5;
  --content:#1d2420; --content-2:#46534b; --content-3:#7d8780;
  --gold-50:#fdf5e8; --gold-200:#f5cf92; --gold-500:#c47a1e;
  --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --serif: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "STSong", "SimSun", serif;
}
* { margin:0; padding:0; box-sizing:border-box; }
html, body { height:100%; }
body {
  font-family: var(--sans); color: var(--content); background: var(--surface);
  display:flex; flex-direction:column; align-items:center; justify-content:center; gap:16px;
  padding:40px 16px; overflow:hidden; -webkit-font-smoothing:antialiased; user-select:none; cursor:default;
}
button { font:inherit; color:inherit; cursor:pointer; border:0; background:none; transition: color .14s ease, background-color .14s ease, border-color .14s ease; }
button:disabled { cursor:not-allowed; opacity:.6; }
.i { width:16px; height:16px; flex-shrink:0; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 白卡（对应 .hh-glass） */
.card {
  width:100%; max-width:400px; padding:40px 36px 32px; border:1px solid var(--border); border-radius:8px; background:#fff;
  box-shadow: 0 12px 32px -20px rgba(29,36,32,.28);
}
.brand { display:flex; flex-direction:column; align-items:center; text-align:center; }
.logo {
  position:relative; width:48px; height:48px; display:inline-flex; align-items:center; justify-content:center; overflow:hidden; color:#fff;
  border-radius:8px; background: linear-gradient(to bottom right, var(--brand-600), var(--brand), var(--brand-400));
  box-shadow: inset 0 0 0 1px rgba(255,255,255,.1);
}
.logo::before { content:""; position:absolute; inset:0; background: radial-gradient(circle at top left, rgba(255,255,255,.22), transparent 38%); }
.logo::after { content:""; position:absolute; right:0; bottom:0; width:33%; height:4px; background: var(--signal); }
.logo svg { position:relative; width:66%; height:66%; }
.name { margin-top:20px; font-family:var(--serif); font-size:24px; font-weight:600; line-height:1.3; }
.tag { margin-top:6px; font-size:14px; color:var(--content-2); }

.state { display:none; margin-top:32px; }
.state.on { display:block; }
.line { display:flex; align-items:center; justify-content:center; gap:8px; font-size:14px; color:var(--content-2); }
.line .i { color:var(--brand); }
.bar { position:relative; height:2px; margin-top:16px; overflow:hidden; background:var(--border-light); }
.bar i { position:absolute; top:0; bottom:0; width:32%; background:var(--brand); animation: slide 1.4s ease-in-out infinite; }
@keyframes slide { from { left:-32%; } to { left:100%; } }
.hint { margin-top:12px; min-height:18px; font-size:12px; line-height:18px; color:var(--content-3); text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

.notice { padding:12px 14px; border:1px solid var(--gold-200); border-radius:4px; background:var(--gold-50); }
.notice b { display:block; font-size:14px; font-weight:600; color:var(--gold-500); }
.notice p { margin-top:4px; font-size:12.5px; line-height:1.65; color:var(--content-2); }
.actions { display:flex; flex-direction:column; gap:8px; margin-top:16px; }
.btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; height:40px; padding:0 16px; font-size:14px; font-weight:500; border-radius:4px; }
.btn .i { width:15px; height:15px; }
.btn-primary { background:var(--brand); color:#fff; }
.btn-primary:hover { background:var(--brand-600); }
.btn-secondary { border:1px solid var(--border); background:#fff; color:var(--content); }
.btn-secondary:hover { border-color: rgba(40,91,77,.5); color:var(--brand-600); }
.btn-ghost { color:var(--content-2); }
.btn-ghost:hover { background:#e9eeea; color:var(--content); }
.center { display:flex; justify-content:center; margin-top:12px; }
.center .btn { height:32px; font-size:13px; }

.failed-title { display:flex; align-items:center; justify-content:center; gap:8px; font-size:15px; font-weight:600; color:var(--cinnabar); }
.failed-msg {
  margin-top:12px; padding:10px 12px; border-radius:4px; background:var(--cinnabar-wash); font-size:12.5px; line-height:1.7;
  color:var(--content); white-space:pre-wrap; word-break:break-all; user-select:text; cursor:text; max-height:180px; overflow:auto;
}

.foot { display:flex; align-items:center; gap:8px; font-size:12px; color:var(--content-3); }
.foot button { color:var(--content-3); text-decoration:underline; text-underline-offset:3px; }
.foot button:hover { color:var(--brand); }
</style>
</head>
<body>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg">
  <symbol id="ic-loader" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></symbol>
  <symbol id="ic-download" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" x2="12" y1="15" y2="3"/></symbol>
  <symbol id="ic-folder" viewBox="0 0 24 24"><path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/></symbol>
  <symbol id="ic-skip" viewBox="0 0 24 24"><polygon points="5 4 15 12 5 20 5 4"/><line x1="19" x2="19" y1="5" y2="19"/></symbol>
  <symbol id="ic-back" viewBox="0 0 24 24"><path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></symbol>
  <symbol id="ic-alert" viewBox="0 0 24 24"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></symbol>
  <symbol id="ic-logs" viewBox="0 0 24 24"><path d="M15 12h-5"/><path d="M15 8h-5"/><path d="M19 17V5a2 2 0 0 0-2-2H4"/><path d="M8 21h12a2 2 0 0 0 2-2v-1a1 1 0 0 0-1-1H11a1 1 0 0 0-1 1v1a2 2 0 1 1-4 0V5a2 2 0 1 0-4 0v2a1 1 0 0 0 1 1h3"/></symbol>
</svg>

<main class="card">
  <div class="brand">
    <span class="logo" aria-hidden="true">
    %LOGO%
    </span>
    <h1 class="name">文澜 AI</h1>
    <p class="tag">长篇小说创作台</p>
  </div>

  <section class="state on" id="starting">
    <div class="line"><svg class="i spin"><use href="#ic-loader"/></svg><span>正在启动…</span></div>
    <div class="bar"><i></i></div>
    <p class="hint" id="startHint"></p>
  </section>

  <section class="state" id="model">
    <div class="notice">
      <b>首次运行：需要 AI 记忆模型（约 470MB）</b>
      <p>语义检索、伏笔追踪等记忆功能依赖它。跳过也能正常写作，下次启动时还会询问。</p>
    </div>
    <div class="actions">
      <button class="btn btn-primary" onclick="call('download_model')"><svg class="i"><use href="#ic-download"/></svg>在线下载</button>
      <button class="btn btn-secondary" onclick="call('import_model_zip')"><svg class="i"><use href="#ic-folder"/></svg>导入本地模型包 (zip)</button>
      <button class="btn btn-ghost" onclick="call('skip_model')"><svg class="i"><use href="#ic-skip"/></svg>跳过，先进入应用</button>
    </div>
  </section>

  <section class="state" id="busy">
    <div class="line"><svg class="i spin"><use href="#ic-loader"/></svg><span id="busyText">处理中…</span></div>
    <div class="bar"><i></i></div>
    <p class="hint" id="busyHint"></p>
    <div class="center"><button class="btn btn-ghost" onclick="call('cancel_model_wait')"><svg class="i"><use href="#ic-back"/></svg>返回选择</button></div>
  </section>

  <section class="state" id="failed">
    <div class="failed-title"><svg class="i"><use href="#ic-alert"/></svg>启动失败</div>
    <p class="failed-msg" id="errorText"></p>
    <div class="center"><button class="btn btn-secondary" onclick="call('open_logs')"><svg class="i"><use href="#ic-logs"/></svg>查看运行日志</button></div>
  </section>
</main>

<footer class="foot"><button onclick="call('open_logs')">运行日志</button><span id="version"></span></footer>

<script>
const $ = id => document.getElementById(id);
let leaving = false;

function show(id) {
  for (const el of document.querySelectorAll('.state')) el.classList.toggle('on', el.id === id);
}

async function call(name) {
  try { await pywebview.api[name](); } catch (e) {}
  poll();
}

async function poll() {
  if (leaving) return;
  let st;
  try { st = JSON.parse(await pywebview.api.get_status()); } catch (e) { return; }
  if (st.version) $('version').textContent = '· v' + st.version;
  if (st.error) {
    $('errorText').textContent = st.error;
    show('failed');
  } else if (st.started) {
    // 后端已就绪：直接进入主界面（replace，不留启动画面的历史记录）
    leaving = true;
    location.replace(st.url);
  } else if (st.model_busy) {
    $('busyText').textContent = st.model_busy;
    $('busyHint').textContent = st.hint || '';
    show('busy');
  } else if (st.model_required) {
    show('model');
  } else {
    $('startHint').textContent = st.hint || '';
    show('starting');
  }
}

function start() {
  poll();
  setInterval(poll, 400);
}

if (window.pywebview && window.pywebview.api && window.pywebview.api.get_status) start();
else window.addEventListener('pywebviewready', start, { once: true });
</script>
</body>
</html>""".replace("%LOGO%", _LOGO_SVG)


LOGS_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>文澜 AI - 运行日志</title>
<style>
:root {
  --brand:#285b4d; --brand-600:#204a3e; --signal:#d15b3d;
  --surface:#f3f5f3; --paper:#faf9f5; --border:#d4dad6; --border-light:#e4e9e5;
  --content:#1d2420; --content-2:#46534b; --content-3:#7d8780;
  --gold-50:#fdf5e8; --gold-200:#f5cf92; --gold-400:#e99a35; --gold-500:#c47a1e;
  --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  --mono: "Cascadia Code", "JetBrains Mono", Consolas, "Microsoft YaHei", monospace;
}
* { margin:0; padding:0; box-sizing:border-box; }
html, body { height:100%; }
body {
  font-family: var(--sans); color: var(--content); background-color: var(--surface);
  display:flex; flex-direction:column; overflow:hidden; -webkit-font-smoothing:antialiased;
}
button, input, select { font:inherit; color:inherit; transition: color .14s ease, background-color .14s ease, border-color .14s ease, box-shadow .14s ease; }
button { cursor:pointer; border:0; background:none; -webkit-tap-highlight-color:transparent; }
::selection { background: rgba(40,91,77,.18); }
::-webkit-scrollbar { width:8px; height:8px; }
::-webkit-scrollbar-track { background:transparent; }
::-webkit-scrollbar-thumb { background: rgba(70,83,75,.25); border-radius:9999px; }
::-webkit-scrollbar-thumb:hover { background: rgba(70,83,75,.42); }
.i { width:16px; height:16px; flex-shrink:0; fill:none; stroke:currentColor; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }

/* 纸色顶栏 / 白底卡片（对应 .lj-topbar / .hh-panel） */
.glass {
  position:relative; border:1px solid var(--border); background: var(--paper);
}
.glass.header::after {
  content:""; position:absolute; right:0; bottom:-1px; width:min(36vw,520px); height:2px; pointer-events:none; opacity:.6;
  background: linear-gradient(90deg, transparent, var(--brand) 68%, var(--signal) 68% 74%, transparent 74%);
}
.panel {
  position:relative; border:1px solid var(--border); border-radius:4px; background:#fff;
  box-shadow: 0 1px 2px rgba(29,36,32,.05), 0 10px 24px -18px rgba(29,36,32,.22);
}

/* 顶栏 */
.header { height:64px; flex-shrink:0; display:flex; align-items:center; gap:14px; padding:0 20px; border-width:0 0 1px 0; }
.logo {
  position:relative; width:40px; height:40px; flex-shrink:0; display:inline-flex; align-items:center; justify-content:center; overflow:hidden; color:#fff;
  border-radius:4px; background: linear-gradient(to bottom right, #204a3e, #285b4d, #4f8a76);
}
.logo::before { content:""; position:absolute; inset:0; background: radial-gradient(circle at top left, rgba(255,255,255,.22), transparent 38%); }
.logo::after { content:""; position:absolute; right:0; bottom:0; width:33%; height:3px; background: var(--signal); }
.logo svg { position:relative; width:66%; height:66%; }
.brand { flex:1; min-width:0; }
.eyebrow { display:block; font-size:11px; font-weight:600; text-transform:uppercase; letter-spacing:.16em; color:var(--brand); line-height:1; }
.title { margin-top:5px; font-size:16px; font-weight:600; letter-spacing:-.01em; line-height:1.2; color:var(--content); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }

/* 按钮（对应 .hh-btn-primary / -secondary / -ghost） */
.btn { display:inline-flex; align-items:center; justify-content:center; gap:6px; height:36px; padding:0 14px; font-size:13px; font-weight:500; white-space:nowrap; border-radius:4px; }
.btn:disabled { cursor:not-allowed; opacity:.6; }
.btn .i { width:15px; height:15px; }
.btn-primary { background:var(--brand); color:#fff; }
.btn-primary:hover { background:var(--brand-600); }
.btn-primary:active { background:var(--brand-600); }
.btn-secondary { border:1px solid var(--border); background:#fff; color:var(--content); }
.btn-secondary:hover { border-color: rgba(40,91,77,.5); color:var(--brand-600); }
.btn-ghost { padding:0 10px; color:var(--content-2); }
.btn-ghost:hover { background:#e9eeea; color:var(--content); }
.header .btn { height:40px; padding:0 18px; font-size:14px; }

/* 内容区：工具栏 + 日志 合为一张卡片 */
.main { flex:1; min-height:0; display:flex; flex-direction:column; padding:12px 12px 0; }
.card { flex:1; min-height:0; display:flex; flex-direction:column; }
.toolbar { display:flex; align-items:center; gap:8px; padding:10px 12px; border-bottom:1px solid var(--border-light); flex-shrink:0; }
.field { position:relative; flex:1; min-width:140px; max-width:280px; }
.field .i, .select .i { position:absolute; top:50%; transform:translateY(-50%); color:var(--content-3); pointer-events:none; }
.field .i { left:10px; }
.select { position:relative; }
.select .i { right:9px; width:14px; height:14px; }
.field input, .select select {
  height:36px; font-size:13px; border:1px solid var(--border); border-radius:4px; background:#fff; color:var(--content);
  outline:none;
}
.field input { width:100%; padding:0 10px 0 32px; }
.field input::placeholder { color:var(--content-3); }
.select select { padding:0 30px 0 10px; appearance:none; -webkit-appearance:none; cursor:pointer; }
.field input:focus, .select select:focus { border-color:var(--brand); box-shadow: 0 0 0 3px rgba(40,91,77,.16); }
.count { margin-left:auto; font-size:12px; color:var(--content-3); white-space:nowrap; font-variant-numeric: tabular-nums; }
.count b { font-weight:500; color:var(--content-2); }

/* 日志列表 */
#logs { flex:1; min-height:0; overflow-y:auto; font-family:var(--mono); font-size:12px; line-height:1.75; }
.log-line { display:flex; align-items:baseline; gap:10px; padding:1px 12px; }
.log-line:first-child { margin-top:6px; }
.log-line:last-child { margin-bottom:6px; }
.log-line:hover { background: rgba(40,91,77,.05); }
.log-line.is-WARNING { background: rgba(217,119,6,.04); }
.log-line.is-ERROR, .log-line.is-CRITICAL { background: rgba(220,38,38,.04); }
.ts { flex-shrink:0; color:var(--content-3); user-select:none; font-variant-numeric: tabular-nums; }
.lv { flex-shrink:0; align-self:center; width:62px; text-align:center; font-family:var(--sans); font-size:10px; font-weight:600; letter-spacing:.06em; line-height:16px; user-select:none; }
.lv-DEBUG { color:var(--content-3); background: rgba(125,135,128,.12); }
.lv-INFO { color:#2a6a55; background: rgba(47,122,95,.10); }
.lv-WARNING { color:#9c6a1f; background: rgba(214,156,60,.14); }
.lv-ERROR { color:#a84337; background: rgba(168,67,55,.10); }
.lv-CRITICAL { color:#744866; background: rgba(138,88,120,.12); }
.mod { flex-shrink:0; max-width:180px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--content-2); user-select:none; }
.msg { color:var(--content); word-break:break-all; }
.is-DEBUG .msg { color:var(--content-2); }
.empty { height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:10px; font-family:var(--sans); font-size:13px; color:var(--content-3); }
.empty .i { width:22px; height:22px; color:var(--brand); }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* 底部状态栏 */
.status { height:40px; flex-shrink:0; display:flex; align-items:center; gap:10px; margin-top:12px; padding:0 16px; font-size:12px; color:var(--content-2); border-width:1px 0 0 0; }
.dot { width:8px; height:8px; flex-shrink:0; }
.dot-ok { background:#16a34a; box-shadow: 0 0 0 3px rgba(22,163,74,.15); }
.dot-err { background:#dc2626; box-shadow: 0 0 0 3px rgba(220,38,38,.15); }
.dot-loading { background:var(--gold-400); box-shadow: 0 0 0 3px rgba(221,145,55,.18); animation: blink 1.2s ease-in-out infinite; }
@keyframes blink { 50% { opacity:.35; } }
.status .url { margin-left:auto; font-family:var(--mono); font-size:11.5px; color:var(--content-3); }
</style>
</head>
<body>
<svg style="display:none" xmlns="http://www.w3.org/2000/svg">
  <symbol id="ic-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></symbol>
  <symbol id="ic-chevron" viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></symbol>
  <symbol id="ic-pause" viewBox="0 0 24 24"><rect x="14" y="4" width="4" height="16"/><rect x="6" y="4" width="4" height="16"/></symbol>
  <symbol id="ic-play" viewBox="0 0 24 24"><polygon points="6 3 20 12 6 21 6 3"/></symbol>
  <symbol id="ic-trash" viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/><line x1="10" x2="10" y1="11" y2="17"/><line x1="14" x2="14" y1="11" y2="17"/></symbol>
  <symbol id="ic-arrow" viewBox="0 0 24 24"><path d="M7 7h10v10"/><path d="M7 17 17 7"/></symbol>
  <symbol id="ic-loader" viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></symbol>
  <symbol id="ic-inbox" viewBox="0 0 24 24"><polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/></symbol>
</svg>

<header class="header glass">
  <span class="logo" aria-hidden="true">
    %LOGO%
  </span>
  <div class="brand">
    <span class="eyebrow">运行日志</span>
    <h1 class="title">文澜 AI</h1>
  </div>
  <button class="btn btn-secondary" id="openBtn" onclick="openInBrowser()" disabled title="用系统浏览器打开（需要另外登录）">在浏览器中打开<svg class="i"><use href="#ic-arrow"/></svg></button>
</header>

<main class="main">
  <section class="card panel">
    <div class="toolbar">
      <label class="field">
        <svg class="i"><use href="#ic-search"/></svg>
        <input id="search" placeholder="筛选运行日志…" oninput="render()" spellcheck="false">
      </label>
      <span class="select">
        <select id="levelFilter" onchange="render()">
          <option value="">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <svg class="i"><use href="#ic-chevron"/></svg>
      </span>
      <button class="btn btn-secondary" id="pauseBtn" onclick="togglePause()"><svg class="i"><use href="#ic-pause"/></svg><span>暂停刷新</span></button>
      <button class="btn btn-secondary" onclick="allLogs=[];render()"><svg class="i"><use href="#ic-trash"/></svg>清空列表</button>
      <span class="count" id="logCount">0 条</span>
    </div>

    <div id="logs"><div class="empty"><svg class="i spin"><use href="#ic-loader"/></svg>正在初始化，请稍候…</div></div>
  </section>
</main>

<footer class="status glass">
  <span class="dot dot-loading" id="statusDot"></span>
  <span id="statusText">正在启动服务…</span>
  <span class="url" id="statusUrl"></span>
</footer>

<script>
let allLogs = [], lastSeq = 0, paused = false, autoScroll = true;
const logsEl = document.getElementById('logs');
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
const icon = (name, cls) => '<svg class="i' + (cls ? ' ' + cls : '') + '"><use href="#' + name + '"/></svg>';

function formatTime(ts) {
  const d = new Date(ts * 1000);
  return d.toTimeString().slice(0,8) + '.' + String(d.getMilliseconds()).padStart(3,'0');
}

function render() {
  const q = $('search').value.toLowerCase();
  const lv = $('levelFilter').value;
  const filtered = allLogs.filter(e => {
    if (lv && e.level !== lv) return false;
    if (q && !e.msg.toLowerCase().includes(q) && !e.name.toLowerCase().includes(q)) return false;
    return true;
  });
  $('logCount').innerHTML = '<b>' + filtered.length + '</b> / ' + allLogs.length + ' 条';
  if (filtered.length === 0) {
    logsEl.innerHTML = allLogs.length === 0
      ? '<div class="empty">' + icon('ic-loader', 'spin') + '等待日志输出…</div>'
      : '<div class="empty">' + icon('ic-inbox') + '没有匹配的日志记录</div>';
    return;
  }
  logsEl.innerHTML = filtered.slice(-500).map(e =>
    '<div class="log-line is-' + e.level + '">' +
    '<span class="ts">' + formatTime(e.ts) + '</span>' +
    '<span class="lv lv-' + e.level + '">' + e.level + '</span>' +
    '<span class="mod" title="' + esc(e.name) + '">' + esc(e.name) + '</span>' +
    '<span class="msg">' + esc(e.msg) + '</span>' +
    '</div>'
  ).join('');
  if (autoScroll) logsEl.scrollTop = logsEl.scrollHeight;
}

logsEl.addEventListener('scroll', () => {
  autoScroll = logsEl.scrollHeight - logsEl.scrollTop - logsEl.clientHeight < 40;
});

function togglePause() {
  paused = !paused;
  $('pauseBtn').innerHTML = paused
    ? icon('ic-play') + '<span>继续刷新</span>'
    : icon('ic-pause') + '<span>暂停刷新</span>';
}

async function poll() {
  if (paused) return;
  try {
    const raw = await pywebview.api.get_logs(lastSeq);
    const entries = JSON.parse(raw);
    if (entries.length > 0) {
      lastSeq = entries[entries.length - 1].seq;
      allLogs.push(...entries);
      if (allLogs.length > 2000) allLogs = allLogs.slice(-2000);
      render();
    }
  } catch(e) {}

  try {
    const raw = await pywebview.api.get_status();
    const st = JSON.parse(raw);
    const dot = $('statusDot'), txt = $('statusText');
    if (st.error) {
      dot.className = 'dot dot-err';
      txt.textContent = '服务启动失败：' + st.error;
    } else if (st.started) {
      dot.className = 'dot dot-ok';
      txt.textContent = '服务运行中';
    } else if (st.model_required || st.model_busy) {
      dot.className = 'dot dot-loading';
      txt.textContent = st.model_busy ? st.model_busy : '等待选择 AI 记忆模型获取方式…';
    }
    $('statusUrl').textContent = st.started && st.url ? st.url : '';
    $('openBtn').disabled = !st.started;
  } catch(e) {}
}

async function openInBrowser() {
  try { await pywebview.api.open_in_browser(); } catch(e) {}
}

setInterval(poll, 1000);
setTimeout(poll, 300);
</script>
</body>
</html>""".replace("%LOGO%", _LOGO_SVG)
