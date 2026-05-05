# Email Manager Agent

AI 邮件 / 会议管家 Agent 第一版。

当前实现是单用户本地 MVP：

- 前端手动点击“同步邮件”才同步网易邮箱。
- 后端通过 IMAP 只读邮件，不删除、不移动、不标记服务器邮件。
- 邮件原文、HTML、附件本地保留 14 天。
- 后台流水线会解析邮件、分类、抽取事件/任务、生成提醒和内部 ICS 日历。
- 主 Agent 查询本地数据库里的结构化结果，不在用户提问时自动同步邮箱。
- 配置 Qwen API Key 后，主 Agent 会使用工具化 loop 查询邮件、日程、待办、日历文件和长期记忆。
- 没有配置 Qwen API Key 时，系统使用规则分类、规则抽取和规则问答兜底。

## 本地快速启动

### 方式一：Python + Vite

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload
```

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

访问：

```text
前端: http://localhost:5173
后端: http://localhost:8000
```

默认 `DATABASE_URL` 使用 SQLite，便于本地试跑。

### 方式二：Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

Docker Compose 会启动 MySQL、Redis、RabbitMQ、Chroma、Backend 和 Frontend。

## 网易邮箱配置

在前端“邮箱配置”里填写：

- 网易邮箱地址。
- 网易邮箱客户端授权码，不是网页登录密码。
- IMAP Host 默认 `imap.163.com`。

保存后点击“同步邮件”。

## Qwen 配置

如果需要启用阿里百炼 Qwen，设置：

```bash
export DASHSCOPE_API_KEY=你的百炼APIKey
```

或者写入 `.env`：

```text
QWEN_ENABLED=true
DASHSCOPE_API_KEY=你的百炼APIKey
QWEN_CLASSIFIER_MODEL=qwen3.5-flash
QWEN_AGENT_MODEL=qwen3.5-plus
```

本地 `uvicorn --reload` 启动时会自动读取 `.env`。

## 主要接口

```text
POST /api/mail-accounts
GET  /api/mail-accounts
POST /api/mail-accounts/{id}/sync
GET  /api/emails
GET  /api/events
GET  /api/tasks
GET  /api/reminders
GET  /api/calendar.ics
POST /api/agent/query
```

## 当前限制

- 第一版同步是同步 HTTP 请求，邮件很多时需要等待。
- RabbitMQ、Redis、Chroma 已在部署结构中预留，当前核心流水线先在后端进程内跑通。
- 时间解析是规则 + dateparser，复杂邮件需要后续继续增强。
- 当前是本地单用户免登录，不适合直接暴露到公网。
