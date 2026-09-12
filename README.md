# 🎭 文澜 AI 小说创作工具

> **AI驱动的智能小说创作平台** - 让每个人都能成为小说家

一个专为中文小说创作设计的AI工具，提供角色管理、剧情规划、章节生成等全流程创作支持。无需编程基础，**双击即可使用**！

<div align="center">

### 📣 加入官方交流群，第一时间获取更新与帮助

🐧 **QQ 交流群：`893474348`** ｜ 👤 **作者 QQ：`973606500`** ｜ 📷 [**扫码进群 ↓**](#-加入交流群)

💾 **AI 向量模型** 请进 QQ 群 `893474348` 在群文件下载，解压后放到 `backend/embedding/` 目录

</div>

---

## ✨ 核心功能

- 🤖 **AI智能创作** - 支持 OpenAI、Claude 等多种AI模型
- 👥 **角色管理** - 智能角色设定、关系图谱、性格分析
- 📖 **剧情规划** - 故事大纲、情节卡片、章节规划
- ✍️ **章节生成** - AI辅助写作、风格定制、内容优化
- 🧠 **记忆系统** - 长期记忆、角色一致性、情节连贯性
- 🔗 **MCP插件** - 扩展AI能力，连接外部工具
- 📊 **可视化** - 关系图谱、剧情时间线、章节结构

## 🚀 一键启动（推荐）

### 系统要求
- **操作系统**: Windows 10/11
- **必备软件**: 
  - Python 3.10+ ([下载地址](https://www.python.org/downloads/))
  - Node.js 18+ ([下载地址](https://nodejs.org/))

### 快速开始

1. **下载项目**
   ```
   下载并解压本项目到任意文件夹
   ```

2. **运行一键脚本**
   
   **方法一：双击批处理文件（最简单）**
   - 双击 `一键启动.bat` 文件
   - 系统会自动调用 PowerShell 脚本
   - 无需任何额外设置
   
3. **开始使用**
   - 脚本会自动构建前端并启动应用服务
   - 应用地址：http://127.0.0.1:8000
   - 后端API：http://localhost:8000
   - API文档：http://localhost:8000/docs
   - 如需配置AI功能，一键启动/打包版请编辑根目录 `config.ini`，容器部署请编辑根目录 `.env`


## 🐳 Docker 生产部署（推荐服务器）

### 1) 准备配置与密钥

```bash
cp .env.example .env
mkdir -p secrets
echo "请替换为强密码" > secrets/local_auth_password.txt
```

Windows 可直接执行：

```powershell
./deploy.ps1
```

Linux/macOS 可执行：

```bash
chmod +x deploy.sh
./deploy.sh
```

> 首次执行会自动检查 Docker / Compose、补齐缺失文件并等待健康检查通过。

### 2) 手动部署命令（等价）

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 3) 常用运维命令

```bash
# 查看服务状态
docker compose ps

# 查看实时日志
docker compose logs -f mumuainovel

# 重启服务
docker compose restart mumuainovel

# 停止服务
docker compose down
```

### 4) 升级流程

```bash
# 1. 拉取最新代码
# 2. 按需更新 .env 与 secrets
# 3. 重建并启动
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 5) 回滚流程（快速）

- 使用上一版本代码目录重新执行同样的 `compose up -d --build`。
- 若需回滚数据，请先恢复数据库备份后再启动应用。

### 6) 备份与恢复（SQLite）

备份（从容器内复制数据库文件）：

```bash
docker compose stop mumuainovel
mkdir -p backup
docker compose cp mumuainovel:/app/data/mumuai.db backup/mumuai_$(date +%Y%m%d).db
docker compose start mumuainovel
```

恢复：

```bash
docker compose stop mumuainovel
docker compose cp backup/mumuai_20250101.db mumuainovel:/app/data/mumuai.db
docker compose start mumuainovel
```

### 7) 排障清单

1. `docker compose ps` 查看是否有容器退出。
2. `docker compose logs -f` 查看报错栈。
3. 检查 `secrets/*.txt` 是否仍是 `CHANGE_ME` 占位值。
4. 检查 `.env` 中端口是否冲突（`APP_PORT`）。
5. 验证就绪检查：`http://localhost:8000/health/ready`。

## 📋 详细安装步骤

如果一键脚本遇到问题，可以按以下步骤手动安装：

### 1. 安装必备软件

#### Python 3.10+
1. 访问 https://www.python.org/downloads/
2. 下载最新版本的Python
3. 安装时勾选"Add Python to PATH"
4. 验证安装：打开命令行输入 `python --version`

#### Node.js 18+
1. 访问 https://nodejs.org/
2. 下载LTS版本
3. 默认安装即可
4. 验证安装：打开命令行输入 `node --version`

### 2. 配置环境

本项目使用 SQLite 嵌入式数据库，无需单独安装数据库服务。首次启动时会自动创建 `backend/data/mumuai.db` 数据库文件。

#### 配置文件（顶层 `config.ini`）

一键启动和打包版用户编辑 `config.ini`；Docker 部署用户编辑 `.env` 文件。直接运行后端开发服务时，可使用 `backend/.env`。


### Q: Python 或 Node.js 命令不识别
**A**: 
1. 确认软件已正确安装
2. 重启命令行窗口
3. 检查环境变量PATH设置

### Q: 前端页面无法访问
**A**: 
1. 确认后端服务正常运行
2. 一键启动或 Docker 部署访问 http://127.0.0.1:8000
3. 只有手动运行 `npm run dev` 时才访问 http://localhost:5173
4. 检查防火墙是否阻止对应端口

### Q: AI功能不可用
**A**: 
1. 检查OpenAI API Key是否正确配置
2. 确认API Key有足够余额
3. 检查网络连接是否正常

### Q: 数据库初始化失败
**A**: 
1. 确认 `backend/data/` 目录有写入权限
2. 删除 `backend/data/mumuai.db` 后重新启动应用
3. 检查 `DATABASE_URL` 配置是否正确


### API文档
启动后端服务后，访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## 🔐 安全说明

- 默认管理员账号仅用于本地开发
- 生产环境请修改默认密码
- API Key等敏感信息请妥善保管
- 建议定期备份数据库

## 📞 技术支持

如果遇到问题：

1. **查看日志**
   - 后端日志：`backend/logs/app.log`
   - 前端控制台：浏览器F12开发者工具

2. **重置环境**
   ```powershell
   Remove-Item backend\.venv -Recurse -Force
   Remove-Item frontend\node_modules -Recurse -Force
   .\一键启动.bat
   ```

3. **数据库重置**
   ```powershell
   Remove-Item backend\data\mumuai.db -Force
   Remove-Item backend\data\chroma_db -Recurse -Force
   .\一键启动.bat
   ```

## 📄 许可证

本项目采用 MIT 许可证，详见 [LICENSE](LICENSE) 文件。

## 💬 加入交流群

<div align="center">

### 🐧 QQ 交流群：**893474348**

<a href="dev-group-qr.jpg" target="_blank">
  <img src="dev-group-qr.jpg" alt="QQ 群二维码" width="260">
</a>

📷 **扫码加入群聊** · 反馈 Bug · 分享作品 · 互助答疑 · 第一时间获取更新

📥 **AI 向量模型下载**：群文件中免费提供，下载后解压到 `backend/embedding/` 目录即可使用

<br>

---

### 👤 联系作者

**作者 QQ：`973606500`**

💡 功能建议 ｜ 🐛 Bug 反馈 ｜ 🤝 商务合作 ｜ 📖 创作交流

<br>

> 🌟 如果觉得本项目对你有帮助，请点亮 **Star** 支持作者持续更新！

</div>

## 🙏 致谢
感谢 https://linux.do/社区的支持
感谢所有贡献者和开源社区的支持！

---

**🎉 开始您的AI小说创作之旅吧！**
