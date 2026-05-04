# AI 邮件 / 会议管家 Agent 技术架构设计文档

版本：V1  
日期：2026-05-04  
状态：架构设计草案  

## 1. 文档目标

本文档描述 AI 邮件 / 会议管家 Agent 的技术架构、模块边界、数据流、工具设计、记忆系统、上下文管理、权限控制、异步任务、数据库模型、可观测性与后续演进路线。

本项目的核心目标不是做一个简单的“邮件摘要工具”或“日历生成脚本”，而是构建一个能够持续接入多邮箱、理解邮件内容、抽取时间敏感事项、生成日程和待办、识别冲突并协助用户行动的个人事务 Agent。

系统设计应重点满足以下要求：

- 多邮箱统一接入与同步。
- 邮件内容结构化理解。
- 时间、地点、会议链接、任务、联系人等信息提取。
- 日历事件草稿生成与冲突检测。
- 高风险动作必须经过用户确认。
- 邮件原文、模型判断、事件来源可追溯。
- 后台持续同步，用户查询时快速响应。
- 支持未来扩展到多 Agent、插件、外部日历、外部任务系统和语义搜索。

## 2. 产品定位与边界

### 2.1 产品定位

推荐定位：

```text
多邮箱智能日程与任务 Agent
```

第一阶段可以聚焦求职场景：

```text
求职邮件 Agent：自动整理笔试、面试、Offer、HR 沟通和待办事项。
```

长期定位可以扩展为：

```text
Personal Workflow OS：个人邮件、日程、任务和沟通行动中枢。
```

### 2.2 MVP 范围

MVP 应完成以下闭环：

```text
接入邮箱
  -> 后台同步邮件
  -> 清洗和解析邮件
  -> 邮件分类
  -> 抽取事件和任务
  -> 检测时间冲突
  -> 生成内部日历草稿
  -> 用户确认
  -> 生成提醒
  -> 用户自然语言查询
```

MVP 必须做：

- IMAP 邮箱接入。
- 增量邮件同步。
- 邮件正文清洗。
- 邮件分类。
- 面试、笔试、会议等事件抽取。
- 任务抽取。
- 时间标准化。
- 冲突检测。
- 内部日历视图。
- 提醒列表。
- 邮件来源追溯。
- Agent 执行日志。

MVP 暂不建议做：

- 自动发送邮件。
- 自动删除邮件。
- 自动移动邮件。
- 未确认时直接写入外部日历。
- 复杂多 Agent 并行调度。
- 企业级团队权限。
- 插件市场。

### 2.3 高风险能力边界

以下动作必须默认禁止自动执行：

- 自动发送邮件。
- 删除邮件。
- 移动邮件文件夹。
- 批量标记已读。
- 未经确认写入外部日历。
- 修改或取消已有外部日历事件。
- 将邮件内容转发给第三方系统。

这些能力可以作为未来功能存在，但必须由 Permission Manager 控制，并要求用户明确确认。

## 3. 总体架构

### 3.1 架构总览

```text
Client / Web UI
      |
      v
API Server
      |
      v
Agent Orchestrator
      |
      +---------------- Permission Manager
      |
      +---------------- Context Manager
      |
      +---------------- Memory Manager
      |
      +---------------- Tool Registry
      |                       |
      |                       +-- IMAP Tools
      |                       +-- Email Parser Tools
      |                       +-- Classification Tools
      |                       +-- Extraction Tools
      |                       +-- Calendar Tools
      |                       +-- Task Tools
      |                       +-- Notification Tools
      |                       +-- Search Tools
      |                       +-- Memory Tools
      |
      v
Queue / Scheduler
      |
      v
Workers
      |
      +---------------- mysql
```

### 3.2 核心设计原则

1. 数据库是业务事实源。

   邮件、事件、任务、提醒、账号、同步状态、用户偏好必须进入数据库。不要把 JSON 文件作为业务主存储。

2. JSONL 只用于 Agent 执行日志。

   参考 Claude Code 的 transcript 思想，但本项目不应把业务数据放进 JSONL。JSONL 用于调试、审计、恢复 agent run。

3. 后台同步为主，用户请求时按需刷新为辅。

   邮件应先被后台同步、解析、分类和结构化。用户提问时主要查询数据库，而不是临时连接 IMAP 全量拉取。

4. 高风险动作必须显式确认。

   读邮件、生成摘要、生成草稿可以自动执行；发送邮件、写外部日历、删除邮件必须确认。

5. 原文保留，模型上下文使用投影视图。

   完整邮件原文保存在数据库或对象存储中，模型只看到当前任务必要的摘要、结构化字段和引用 ID。

6. Agent 负责决策编排，工具负责确定性执行。

   LLM 不直接操作数据库或外部系统，而是通过受控工具调用执行动作。

## 4. 推荐技术栈


如果从零开始，推荐：

```text
Backend: python
API Framework: fastapi
Queue: rabbitmq
Cache / Lock: Redis
Database: mysql
Vector Search: chroma、
LLM: OpenAI / Claude / 可插拔 LLM Provider
Frontend: React / Next.js
Deployment: Docker Compose MVP，后续云服务部署
```


### 4.3 中间件选择

MVP 必要：

- mysql：业务数据主存储。
- Redis：队列依赖、缓存、分布式锁、同步状态。
- rabbitmq：异步任务队列。
- 结构化日志：排查 agent 决策与工具执行问题。

后续增强：

- pgvector：邮件语义搜索。
- OpenTelemetry：跨服务链路追踪。
- MinIO / S3：附件和原始邮件持久化。
- KMS / Vault：生产级密钥管理。
- Prometheus / Grafana：指标监控。

暂不建议 MVP 引入：

- Kafka。
- Elasticsearch。
- Kubernetes。
- 独立向量数据库。
- 复杂多 Agent 平台。

## 5. 系统模块设计

### 5.1 API Server

API Server 负责处理用户请求、账号管理、邮箱配置、查询接口和用户确认动作。

主要职责：

- 用户登录与认证。
- 邮箱账号绑定。
- 邮件列表查询。
- 事件列表查询。
- 任务列表查询。
- 日历视图查询。
- Agent 问答入口。
- 用户确认或拒绝某个动作。
- 手动触发同步。
- 查看 Agent 执行日志。

典型接口：

```text
POST   /api/mail-accounts
GET    /api/mail-accounts
POST   /api/mail-accounts/:id/sync
GET    /api/emails
GET    /api/emails/:id
GET    /api/events
PATCH  /api/events/:id/confirm
PATCH  /api/events/:id/ignore
GET    /api/tasks
POST   /api/agent/query
GET    /api/agent-runs/:id
POST   /api/actions/:id/approve
POST   /api/actions/:id/reject
```

### 5.2 Agent Orchestrator

Agent Orchestrator 是系统的 Agent Runtime。它不直接负责 IMAP、数据库或日历写入，而是负责任务规划、工具选择、上下文组装、权限判断和状态落库。

核心职责：

- 接收用户自然语言请求或后台任务请求。
- 读取相关上下文。
- 选择和调用工具。
- 合并工具结果。
- 维护本轮 Agent 状态。
- 生成面向用户的回答或待确认动作。
- 记录 agent run 和 tool call。

Agent Orchestrator 应采用单写者原则：

```text
工具可以异步执行
工具不能直接修改主 Agent State
工具返回结构化结果
主 Agent Loop 统一合并结果并写入状态
```

这样可以避免多个工具并发更新同一个事件、任务或上下文状态时产生竞态。

### 5.3 Tool Registry

Tool Registry 负责注册系统可用工具，并描述每个工具的能力边界。

每个工具应包含：

```text
tool_name
description
input_schema
output_schema
risk_level
is_concurrency_safe
requires_confirmation
idempotency_key_rule
timeout_ms
max_output_chars
permission_check
handler
```

示例：

```yaml
name: calendar.create_event
risk_level: high
requires_confirmation: true
is_concurrency_safe: false
timeout_ms: 10000
max_output_chars: 4000
```

### 5.4 Permission Manager

Permission Manager 控制工具是否可以执行。

权限判断顺序建议：

```text
1. 工具输入 schema 校验
2. 全局 deny 规则
3. 用户级权限设置
4. 工具级 permission_check
5. 风险等级判断
6. 是否需要用户确认
7. 执行工具
8. PostTool 审计
```

风险等级：

```text
low:
  - 读取数据库中的邮件元数据
  - 读取已同步邮件正文
  - 分类
  - 摘要
  - 事件抽取
  - 冲突检测

medium:
  - 创建内部事件草稿
  - 创建内部任务
  - 生成回复草稿
  - 标记内部状态

high:
  - 写入外部日历
  - 发送邮件
  - 修改邮件状态
  - 移动邮件
  - 删除邮件
  - 同步到第三方任务系统
```

默认策略：

- low 可以自动执行。
- medium 可以自动生成草稿，但应可撤销。
- high 必须用户确认。
- delete / send / external write 永远不能静默执行。

### 5.5 Context Manager

Context Manager 负责控制 LLM 每次调用看到什么内容。

它不应把全量邮件原文、全部历史对话、完整附件直接塞进上下文，而应构造任务相关的投影视图。

上下文来源：

- 当前用户问题。
- 用户偏好 memory。
- 相关邮件摘要。
- 相关事件。
- 相关任务。
- 最近 agent run 摘要。
- 工具输出 preview。
- 必要的原文引用片段。

上下文输出：

```text
System instructions
Developer instructions
User query
Relevant memories
Relevant email snippets
Relevant events
Relevant tasks
Tool result previews
Allowed tools
Permission policy
```

### 5.6 Memory Manager

Memory Manager 负责管理长期偏好和稳定背景信息。

它与业务数据库不同：

- 数据库保存事实和业务对象。
- Memory 保存未来对 Agent 决策有帮助的用户偏好、规则和长期上下文。

不应把每封邮件摘要都写入 memory。邮件摘要属于业务数据，应存入 email_messages / email_summaries。

### 5.7 Queue Workers

Workers 负责执行后台异步任务。

主要 worker：

- Mail Sync Worker。
- Email Parse Worker。
- Classification Worker。
- Event Extraction Worker。
- Task Extraction Worker。
- Conflict Detection Worker。
- Reminder Worker。
- Embedding Worker。
- Agent Background Worker。

## 6. 关键数据流

### 6.1 后台邮件同步流程

```text
Scheduler
  -> enqueue sync_mailbox(account_id)
  -> acquire mailbox lock
  -> connect IMAP
  -> fetch new UIDs
  -> store raw metadata
  -> store raw MIME / HTML / attachments
  -> enqueue parse_email(email_id)
  -> update sync cursor
  -> release mailbox lock
```

设计要点：

- 每个 mailbox 同一时间只能有一个同步任务。
- 使用 IMAP UID 做增量同步。
- 保存 UIDVALIDITY，避免邮箱重建导致 UID 失效。
- 同步失败应记录错误并重试。
- 频控错误应指数退避。
- 邮件入库需要幂等。

### 6.2 邮件解析流程

```text
parse_email(email_id)
  -> load raw MIME / HTML
  -> parse headers
  -> extract text/plain
  -> html to text
  -> extract links
  -> extract attachments metadata
  -> normalize sender / recipients
  -> store parsed body
  -> enqueue classify_email(email_id)
```

设计要点：

- 原始邮件不覆盖。
- 清洗文本与原始 HTML 分开保存。
- 附件仅保存路径、类型、hash、大小和解析状态。
- HTML 清洗必须去掉脚本、样式和无意义导航。

### 6.3 邮件分类流程

```text
classify_email(email_id)
  -> build minimal context
  -> run rules pre-classifier
  -> run LLM classifier when needed
  -> store category, confidence, reason
  -> enqueue extraction tasks based on category
```

分类标签建议：

```text
interview
written_test
meeting_invite
offer
rejection
hr_followup
todo_request
calendar_update
deadline
notification
newsletter
spam_like
unknown
```

分类结果应保存：

```text
category
confidence
model_name
prompt_version
reason
evidence_text
classified_at
```

### 6.4 事件抽取流程

```text
extract_event(email_id)
  -> load parsed email
  -> load thread context if needed
  -> extract candidate event
  -> normalize time
  -> detect timezone
  -> extract company / title / location / meeting link
  -> calculate confidence
  -> deduplicate against existing events
  -> store event as draft
  -> enqueue detect_conflict(event_id)
```

事件状态：

```text
draft: 系统抽取出来，尚未确认
confirmed: 用户确认有效
ignored: 用户忽略
conflict: 与其他事件冲突
updated: 后续邮件更新了时间或地点
cancelled: 邮件明确取消
needs_review: 信息不完整或置信度低
```

### 6.5 冲突检测流程

```text
detect_conflict(event_id)
  -> load event interval
  -> load same user confirmed / draft events
  -> compare time overlap
  -> compare external calendar events if connected
  -> write conflict records
  -> update event status if needed
  -> create notification if conflict exists
```

冲突类型：

```text
hard_overlap: 时间直接重叠
buffer_overlap: 前后间隔不足
ambiguous_time: 时间不完整
timezone_uncertain: 时区不确定
duplicate_event: 疑似重复
updated_event: 疑似同一事件更新
```

### 6.6 用户查询流程

用户问：

```text
我这周有哪些面试？
```

处理流程：

```text
API Server
  -> Agent Orchestrator
  -> check last sync time
  -> if stale, enqueue quick sync or offer refresh
  -> query structured events from DB
  -> retrieve related email snippets
  -> build compact context
  -> LLM generates answer
  -> include source references
  -> store agent run
```

注意：

- 优先查结构化事件表。
- 不应直接把所有邮件塞给模型。
- 如果最近同步时间太旧，可以先提示“最近同步于 xx，是否刷新”或后台触发快速同步。

### 6.7 用户确认写入外部日历流程

```text
User clicks confirm
  -> create pending action
  -> Permission Manager validates high-risk action
  -> Calendar Tool creates external event
  -> store external_calendar_event_id
  -> mark internal event confirmed
  -> audit log
```

必须保证：

- 同一个 event_id 重复确认不会创建多个外部日历。
- 使用 idempotency key。
- 外部写入失败时内部状态不能误标为已完成。
- 用户能看到来源邮件和将要写入的内容。

## 7. 工具系统详细设计

### 7.1 工具分类

工具分为以下几类：

```text
Mail Connector Tools
Email Parsing Tools
Classification Tools
Extraction Tools
Calendar Tools
Task Tools
Search Tools
Memory Tools
Notification Tools
Audit Tools
User Confirmation Tools
```

### 7.2 Mail Connector Tools

#### imap.sync_mailbox

用途：

同步指定邮箱的新邮件。

输入：

```json
{
  "account_id": "string",
  "mode": "delta | full | recent",
  "since": "ISO datetime optional"
}
```

输出：

```json
{
  "account_id": "string",
  "new_email_ids": ["string"],
  "updated_email_ids": ["string"],
  "sync_cursor": "string",
  "errors": []
}
```

权限：

```text
risk_level: low
requires_confirmation: false
is_concurrency_safe: false per mailbox
```

说明：

- 该工具可以自动运行。
- 对同一个 account_id 必须加锁。
- 不允许修改用户邮箱状态，除非显式工具支持。

#### imap.fetch_email_body

用途：

按 email_id 获取完整正文或指定片段。

输入：

```json
{
  "email_id": "string",
  "part": "text | html | raw | headers",
  "max_chars": 12000
}
```

输出：

```json
{
  "email_id": "string",
  "content": "string",
  "truncated": true,
  "full_content_ref": "object-storage-path"
}
```

权限：

```text
risk_level: low
requires_confirmation: false
is_concurrency_safe: true
```

#### smtp.send_email

用途：

发送邮件。

权限：

```text
risk_level: high
requires_confirmation: true
is_concurrency_safe: false
```

MVP 默认不启用自动发送，只允许创建草稿。

### 7.3 Email Parsing Tools

#### email.parse_mime

用途：

将 MIME 解析为 headers、text、html、attachments。

输出：

```json
{
  "subject": "string",
  "from": "string",
  "to": ["string"],
  "cc": ["string"],
  "sent_at": "ISO datetime",
  "text_body_ref": "string",
  "html_body_ref": "string",
  "attachments": []
}
```

#### email.extract_links

用途：

从正文中提取链接。

链接类型：

```text
meeting_link
assessment_link
calendar_invite
form_link
attachment_download
generic
```

### 7.4 Classification Tools

#### email.classify

用途：

给邮件打业务分类。

输入：

```json
{
  "email_id": "string",
  "subject": "string",
  "sender": "string",
  "snippet": "string",
  "links": []
}
```

输出：

```json
{
  "category": "interview",
  "confidence": 0.92,
  "reason": "邮件包含面试邀请、具体日期和会议链接。",
  "evidence": ["面试时间", "腾讯会议"]
}
```

实现策略：

1. 规则预分类：
   - 标题包含“面试”“笔试”“测评”“interview”“assessment”等关键词。
   - 发件人域名与公司或招聘系统相关。
2. LLM 分类：
   - 对规则不确定的邮件调用模型。
3. 结果落库：
   - 保存 prompt_version 和 model_name。

### 7.5 Extraction Tools

#### event.extract_from_email

用途：

从邮件中抽取一个或多个日程事件。

输出 schema：

```json
{
  "events": [
    {
      "title": "string",
      "event_type": "interview | written_test | meeting | deadline",
      "start_time": "ISO datetime or null",
      "end_time": "ISO datetime or null",
      "timezone": "Asia/Shanghai",
      "location": "string or null",
      "meeting_link": "string or null",
      "company": "string or null",
      "contact_name": "string or null",
      "contact_email": "string or null",
      "confidence": 0.0,
      "missing_fields": ["end_time"],
      "evidence": ["string"]
    }
  ]
}
```

设计要求：

- 必须输出 evidence。
- 时间不确定不能强行编造。
- 时区不明确要标记 timezone_uncertain。
- 多个候选时间要全部返回并标记需要用户确认。

#### task.extract_from_email

用途：

提取待办事项。

输出 schema：

```json
{
  "tasks": [
    {
      "title": "string",
      "description": "string",
      "due_at": "ISO datetime or null",
      "priority": "low | medium | high",
      "assignee": "self | other | unknown",
      "confidence": 0.0,
      "evidence": ["string"]
    }
  ]
}
```

### 7.6 Time Tools

#### time.normalize

用途：

将自然语言时间转换为标准时间。

输入：

```json
{
  "text": "下周三下午两点",
  "reference_time": "2026-05-04T10:00:00+08:00",
  "default_timezone": "Asia/Singapore",
  "email_sent_at": "2026-05-03T18:00:00+08:00"
}
```

输出：

```json
{
  "start_time": "2026-05-06T14:00:00+08:00",
  "end_time": null,
  "timezone": "Asia/Singapore",
  "confidence": 0.86,
  "ambiguous": false,
  "reason": "根据 reference_time 解析下周三。"
}
```

时间解析原则：

- 优先使用邮件中明确时区。
- 其次使用用户默认时区。
- 再其次使用邮箱或发件人地区推断，但必须降低置信度。
- 对“明天”“下周三”必须基于 email_sent_at，而不是当前系统时间。
- 对无年份日期要根据邮件发送时间推断年份。

### 7.7 Calendar Tools

#### calendar.create_internal_draft

用途：

创建内部日历草稿。

权限：

```text
risk_level: medium
requires_confirmation: false
```

#### calendar.write_external_event

用途：

写入 Google Calendar、飞书 Calendar、Outlook Calendar 等外部日历。

权限：

```text
risk_level: high
requires_confirmation: true
```

输入：

```json
{
  "event_id": "string",
  "calendar_account_id": "string",
  "title": "string",
  "start_time": "ISO datetime",
  "end_time": "ISO datetime",
  "location": "string",
  "description": "string",
  "reminders": []
}
```

幂等要求：

- idempotency key = user_id + event_id + calendar_account_id。
- 如果 external_event_id 已存在，应执行更新而不是重复创建。

### 7.8 Search Tools

#### search.email_keyword

使用 mysqlSQL Full Text Search 做关键词检索。

#### search.email_semantic

使用 chroma 做语义检索。

#### search.hybrid

融合关键词和向量结果，适合用户自然语言问题：

```text
字节那封面试邮件在哪？
HR 有没有让我准备身份证？
上周哪个邮件说要做测评？
```

### 7.9 Memory Tools

#### memory.read_relevant

读取与当前问题相关的用户记忆。

#### memory.write_preference

写入用户明确偏好。

必须限制写入范围：

- 只能写用户偏好、稳定规则、长期有用信息。
- 不能写临时邮件内容。
- 不能写敏感正文。

### 7.10 Notification Tools

#### notification.schedule

创建提醒。

提醒类型：

```text
event_before_1_day
event_before_1_hour
event_before_15_min
task_due
conflict_detected
needs_review
```

#### notification.dispatch

发送提醒，可接入：

- Web push。
- 邮件提醒。
- 飞书。
- 企业微信。
- Telegram。

MVP 可以先只做站内提醒或控制台提醒。

## 8. Agent Loop 设计

### 8.1 主循环状态

每次 Agent Run 应维护一个局部状态对象：

```ts
type AgentRunState = {
  runId: string;
  userId: string;
  messages: AgentMessage[];
  toolContext: ToolContext;
  memoryContext: MemoryContext;
  contextBudget: ContextBudget;
  pendingActions: PendingAction[];
  toolResults: ToolResult[];
  turnCount: number;
  transitionReason: string;
};
```

状态写入原则：

- 工具执行期间不直接写 AgentRunState。
- 工具返回 update。
- 主循环统一合并 update。
- 每一轮模型调用前生成新的 projected context。
- 每轮结束后持久化 agent_runs 和 tool_calls。

### 8.2 工具并发策略

工具按安全性分为：

```text
concurrency_safe:
  - 读取邮件
  - 查询数据库
  - 分类
  - 摘要
  - 搜索

not_concurrency_safe:
  - 写内部事件
  - 写外部日历
  - 发送邮件
  - 修改同步游标
  - 修改邮箱状态
```

执行规则：

- safe 工具可以并发执行。
- unsafe 工具独占执行。
- 后面的 safe 工具不能越过前面的 unsafe 工具。
- 会修改上下文的工具结果按原始 tool_use 顺序应用。

### 8.3 Agent Run 类型

```text
interactive_query:
  用户主动提问。

background_sync:
  后台同步邮件后的自动处理。

background_extraction:
  邮件入库后的分类和抽取。

scheduled_reminder:
  到点提醒。

confirmation_action:
  用户确认某个高风险动作。
```

### 8.4 Agent 输出类型

Agent 不应只输出自然语言，还应输出结构化动作：

```json
{
  "answer": "你这周有 3 场面试，其中周三和周五各一场。",
  "source_refs": ["email_123", "event_456"],
  "pending_actions": [
    {
      "type": "calendar_write",
      "event_id": "event_456",
      "requires_confirmation": true
    }
  ]
}
```

## 9. 上下文管理与压缩设计

### 9.1 为什么需要上下文压缩

邮件 Agent 的上下文膨胀主要来自：

- 邮件正文很长。
- HTML 噪声很多。
- 邮件线程重复引用历史。
- 附件解析结果很大。
- 用户可能接入多个邮箱。
- 后台任务会产生大量工具输出。
- 多轮问答会累积历史。

如果每次都把完整邮件和完整工具输出放进 LLM 上下文，会导致：

- 成本过高。
- 延迟过高。
- 超过上下文窗口。
- 模型注意力被噪声干扰。
- 敏感信息暴露面扩大。

### 9.2 三层邮件上下文

系统应将邮件数据分为三层：

```text
Raw Layer:
  原始 MIME、HTML、附件、完整正文。

Parsed Layer:
  标题、发件人、收件人、纯文本、链接、附件索引。

Structured Layer:
  分类、摘要、事件、任务、联系人、时间、地点、置信度。
```

LLM 默认只读取 Structured Layer 和少量 Parsed Layer。

### 9.3 Tool Result Budget

每个工具输出必须有大小限制。

策略：

```text
如果工具输出 <= max_output_chars:
  直接进入上下文。

如果工具输出 > max_output_chars:
  完整输出保存到 object storage 或 tool_results 表。
  上下文只放 preview + ref。
```

上下文中的表示：

```text
<persisted-tool-result>
tool_call_id: tool_abc
full_result_ref: tool-results/tool_abc.json
preview:
  前 2000 字内容...
</persisted-tool-result>
```

关键要求：

- 同一个 tool_call_id 的压缩决策必须稳定。
- 不能这轮放完整内容，下轮变 preview，导致上下文不稳定。
- 工具结果要可追溯。
- 模型确实需要完整内容时，可以通过 read_tool_result 工具读取。

### 9.4 邮件线程压缩

邮件线程常见问题：

- 回复链包含大量 quoted text。
- 多封邮件重复引用同一内容。
- 一个线程中有最新变更，比如“时间改为周五下午”。

处理策略：

```text
1. 保存完整线程。
2. 按 message_id / in_reply_to / references 建立 thread。
3. 对每封邮件提取 delta summary。
4. 对整个 thread 维护 thread_summary。
5. 用户查询时优先使用最新有效信息。
```

线程摘要结构：

```json
{
  "thread_id": "thread_123",
  "topic": "某公司一面安排",
  "latest_decision": "面试时间改为 2026-05-10 14:00",
  "open_items": ["需要确认是否参加"],
  "superseded_events": ["event_old"],
  "source_email_ids": ["email_1", "email_2"]
}
```

### 9.5 Session Summary

Agent 多轮对话应维护 session summary。

保存内容：

- 用户当前目标。
- 已经查询过的邮件。
- 已经生成的候选事件。
- 用户刚刚确认或拒绝的动作。
- 当前未解决的问题。

不保存：

- 完整邮件正文。
- 大段工具输出。
- 与当前目标无关的旧对话。

### 9.6 Projected Context

数据库和日志保留完整历史，但模型输入使用投影视图：

```text
Full State:
  所有邮件、事件、任务、历史 tool calls、agent messages。

Projected Context:
  当前问题相关的 memory、事件、邮件摘要、必要证据片段。
```

构造顺序：

```text
1. 系统指令
2. 工具权限策略
3. 用户偏好 memory
4. 当前用户问题
5. 相关事件
6. 相关邮件摘要
7. 必要原文片段
8. 最近未完成 pending actions
9. 最近一轮工具结果 preview
```

### 9.7 上下文预算

建议为每次 LLM 调用设置预算：

```text
System / policy: 10%
User query: 5%
Memory: 10%
Structured events / tasks: 25%
Email snippets: 30%
Tool result previews: 10%
Reserved output: 10%
```

当超预算时，裁剪顺序：

```text
1. 删除低相关邮件 snippet。
2. 缩短历史 agent messages。
3. 使用 thread_summary 替代单封邮件摘要。
4. 使用 event structured fields 替代原文 evidence。
5. 保留 source_ref，不保留正文。
6. 最后才生成 session compact summary。
```

### 9.8 溢出恢复

如果模型调用失败，提示上下文过长：

```text
1. 降低 email snippet 数量。
2. 只保留 confirmed / draft event structured fields。
3. 删除 tool preview，只保留 tool result refs。
4. 使用 session summary。
5. 重新调用模型。
```

## 10. 记忆系统设计

### 10.1 Memory 与业务数据的区别

业务数据：

```text
邮件、事件、任务、提醒、附件、分类结果、同步状态。
```

Memory：

```text
用户长期偏好、稳定规则、默认配置、未来会话有帮助的信息。
```

不要把业务流水写入 Memory。

### 10.2 Memory 类型

建议类型：

```text
user_preference:
  用户偏好，如默认提醒时间、默认日历、语言风格。

user_profile:
  用户稳定背景，如当前找暑期实习、目标岗位方向。

workflow_rule:
  用户工作流规则，如面试邮件默认提前一天提醒。

contact_knowledge:
  常见联系人、HR、公司别名。

system_feedback:
  用户对 Agent 行为的反馈，如不要自动把 newsletter 标成重要。
```

### 10.3 Memory 存储

推荐使用数据库表，而不是只用 Markdown 文件。

表：user_memories

```text
id
user_id
memory_type
title
content
description
source
confidence
status
created_at
updated_at
last_used_at
```

可选补充：

- 将 memory 导出为 Markdown，便于人工查看。
- 数据库作为事实源。
- Markdown 作为可读备份或开发期调试。

### 10.4 Memory 写入策略

可以写入：

- 用户明确说“记住”。
- 用户多次重复设置同一偏好。
- 用户纠正 Agent 行为。
- 用户确认某类长期规则。

不应写入：

- 单封邮件内容。
- 单次面试时间。
- 临时任务。
- 邮箱授权码。
- 敏感正文。
- 可以从数据库查询到的事实。

### 10.5 Memory 抽取流程

在完整 Agent Run 结束后触发：

```text
agent run completed
  -> memory extraction job
  -> load recent conversation summary
  -> load existing memory manifest
  -> decide no-op / create / update / archive
  -> write user_memories
```

Memory extraction 应有专用 prompt 和严格 schema。

输出：

```json
{
  "action": "create | update | archive | noop",
  "memory_type": "user_preference",
  "title": "默认面试提醒",
  "content": "用户希望面试前 1 天和 1 小时提醒。",
  "reason": "用户明确表达了长期提醒偏好。"
}
```

### 10.6 Memory 召回策略

每次用户查询时，不要把所有 memory 放进上下文。

流程：

```text
1. 根据用户问题和工具意图选择候选 memory。
2. 过滤已过期或低置信度 memory。
3. 只注入 top K 条。
4. 标记每条 memory 的来源和类型。
```

示例：

用户问：

```text
帮我看看明天面试安排。
```

可召回：

- 默认时区。
- 面试提醒偏好。
- 当前求职方向。
- 常用日历账号。

不召回：

- 邮件分类偏好中与 newsletter 相关的规则。
- 很久以前的项目任务规则。

## 11. 数据库设计

### 11.1 users

```text
id
email
display_name
timezone
locale
created_at
updated_at
```

### 11.2 mail_accounts

```text
id
user_id
provider
email_address
imap_host
imap_port
imap_secure
smtp_host
smtp_port
smtp_secure
auth_type
encrypted_access_token
encrypted_refresh_token
encrypted_app_password
status
last_sync_at
created_at
updated_at
```

provider:

```text
gmail
outlook
qq
netease
custom_imap
```

### 11.3 mailbox_sync_states

```text
id
mail_account_id
folder
uid_validity
last_seen_uid
last_sync_started_at
last_sync_finished_at
sync_status
error_code
error_message
created_at
updated_at
```

### 11.4 email_messages

```text
id
user_id
mail_account_id
folder
provider_message_id
message_id_header
thread_id
imap_uid
subject
from_name
from_email
to_emails
cc_emails
bcc_emails
sent_at
received_at
snippet
raw_mime_ref
html_ref
text_ref
body_hash
has_attachments
is_read
is_deleted
sync_status
created_at
updated_at
```

唯一约束建议：

```text
(mail_account_id, folder, imap_uid)
(mail_account_id, message_id_header)
```

### 11.5 email_parsed_contents

```text
id
email_id
clean_text
clean_html_ref
links_json
language
parse_status
parse_error
created_at
updated_at
```

### 11.6 email_classifications

```text
id
email_id
category
confidence
reason
evidence_json
model_name
prompt_version
created_at
updated_at
```

### 11.7 email_threads

```text
id
user_id
thread_key
subject_normalized
summary
latest_email_id
created_at
updated_at
```

### 11.8 attachments

```text
id
email_id
filename
content_type
size_bytes
storage_ref
sha256
parse_status
extracted_text_ref
created_at
updated_at
```

### 11.9 extracted_events

```text
id
user_id
source_email_id
source_thread_id
event_type
title
company
description
start_time
end_time
timezone
location
meeting_link
contact_name
contact_email
confidence
status
missing_fields_json
evidence_json
dedupe_key
supersedes_event_id
created_at
updated_at
```

索引：

```text
(user_id, start_time)
(user_id, status)
(source_email_id)
(dedupe_key)
```

### 11.10 event_conflicts

```text
id
user_id
event_id
conflicting_event_id
conflict_type
severity
description
created_at
updated_at
```

### 11.11 tasks

```text
id
user_id
source_email_id
title
description
due_at
priority
status
confidence
evidence_json
created_at
updated_at
```

### 11.12 reminders

```text
id
user_id
target_type
target_id
remind_at
channel
status
payload_json
created_at
updated_at
```

target_type:

```text
event
task
conflict
review
```

### 11.13 calendar_accounts

```text
id
user_id
provider
display_name
encrypted_access_token
encrypted_refresh_token
status
created_at
updated_at
```

### 11.14 external_calendar_events

```text
id
user_id
internal_event_id
calendar_account_id
external_event_id
provider
sync_status
last_synced_at
created_at
updated_at
```

### 11.15 user_memories

```text
id
user_id
memory_type
title
content
description
source
confidence
status
created_at
updated_at
last_used_at
```

### 11.16 agent_runs

```text
id
user_id
run_type
status
input_text
output_text
summary
model_name
prompt_version
started_at
finished_at
error_code
error_message
jsonl_ref
created_at
updated_at
```

### 11.17 tool_calls

```text
id
agent_run_id
tool_name
input_json
output_json
output_ref
risk_level
requires_confirmation
status
started_at
finished_at
error_code
error_message
created_at
updated_at
```

### 11.18 pending_actions

```text
id
user_id
agent_run_id
action_type
payload_json
risk_level
status
expires_at
approved_at
rejected_at
created_at
updated_at
```

action_type:

```text
write_calendar_event
send_email
update_external_event
delete_email
mark_email_read
```

### 11.19 embeddings

```text
id
user_id
object_type
object_id
embedding
embedding_model
content_hash
created_at
updated_at
```

object_type:

```text
email
thread
event
task
memory
```

## 12. 异步任务设计

### 12.1 队列列表

```text
mail.sync
email.parse
email.classify
event.extract
task.extract
event.conflict_detect
reminder.schedule
reminder.dispatch
embedding.generate
memory.extract
agent.background
```

### 12.2 Job 幂等性

每个 job 必须有 idempotency key。

示例：

```text
sync_mailbox: account_id + folder + sync_cursor
parse_email: email_id + body_hash
classify_email: email_id + prompt_version
extract_event: email_id + prompt_version
embedding: object_type + object_id + content_hash
```

### 12.3 重试策略

建议：

```text
IMAP connection error:
  retry 3 times with exponential backoff

rate limit:
  retry with longer backoff

LLM transient error:
  retry 2 times

schema validation error:
  no automatic retry, mark needs_review

permission denied:
  no retry
```

### 12.4 死信队列

失败超过阈值的任务进入 dead letter queue。

需要记录：

- job type。
- payload。
- error code。
- error message。
- retry count。
- last failed at。

管理员或开发者可以手动重放。

## 13. 安全与隐私设计

### 13.1 凭证加密

邮箱授权码、OAuth token、SMTP 密码必须加密存储。

MVP：

```text
应用层 AES-GCM 加密
主密钥放在环境变量
```

生产：

```text
KMS / Vault
定期轮换密钥
分环境隔离
```

### 13.2 日志脱敏

日志中禁止输出：

- 完整邮件正文。
- 邮箱授权码。
- OAuth token。
- SMTP 密码。
- 附件内容。
- 大段个人隐私信息。

允许输出：

- email_id。
- event_id。
- tool_call_id。
- 错误码。
- 摘要级原因。

### 13.3 LLM 数据最小化

发给 LLM 的内容应尽量少：

- 默认发摘要和结构化字段。
- 必要时才发原文片段。
- 附件内容必须按需提取。
- 对不相关邮件不进入上下文。

### 13.4 用户确认

高风险动作必须生成 Pending Action。

用户确认页面应展示：

- 动作类型。
- 将要写入或发送的内容。
- 来源邮件。
- 风险说明。
- 确认和拒绝按钮。

## 14. 时间与日历设计

### 14.1 时间标准化

所有时间入库建议使用：

```text
timestamptz
```

同时保存原始时区：

```text
timezone
```

原因：

- 用户可能在不同时区。
- 邮件可能来自海外公司。
- 面试邮件可能写 PST、UTC、北京时间。

### 14.2 不完整时间处理

示例：

```text
周三下午
明天上午
5 月 10 日
```

处理策略：

- 不强行生成精确时间。
- 标记 missing_fields。
- status = needs_review。
- 提醒用户确认。

### 14.3 默认时长

如果邮件只给开始时间，没有结束时间：

```text
interview: 默认 60 分钟，但标记 inferred
written_test: 默认 120 分钟，但标记 inferred
meeting: 默认 60 分钟
deadline: 无 end_time
```

推断字段必须记录：

```text
inferred_fields_json
```

## 15. 去重与更新设计

### 15.1 邮件去重

依据：

- IMAP UID。
- Message-ID header。
- body_hash。
- subject + sender + sent_at。

### 15.2 事件去重

dedupe_key 建议：

```text
user_id + company + event_type + normalized_start_time + meeting_link_hash
```

如果缺少时间，可使用：

```text
user_id + source_thread_id + event_type + company
```

### 15.3 邮件更新事件

如果后续邮件包含：

```text
时间改为
reschedule
updated invitation
取消
cancelled
```

需要判断是否更新已有事件。

策略：

- 新建 event，并设置 supersedes_event_id。
- 旧 event 标记为 updated 或 cancelled。
- 用户界面显示变更来源。

## 16. 搜索与 RAG 设计

### 16.1 第一阶段：结构化查询优先

用户问日程相关问题，应优先查 extracted_events，而不是向量搜索。

示例：

```text
我明天有什么面试？
```

SQL 查询即可解决。

### 16.2 第二阶段：关键词搜索

适合：

```text
找一下腾讯会议链接
找包含身份证的邮件
HR 发过什么材料要求
```

使用 PostgreSQL Full Text Search。

### 16.3 第三阶段：语义搜索

适合：

```text
哪封邮件说我要准备系统设计？
上周有没有公司让我做在线测评？
有哪个公司提到 base 地点？
```

使用 pgvector。

### 16.4 Hybrid Search

长期建议使用：

```text
keyword search + vector search + recency boost + source type boost
```

排序因子：

- 关键词匹配。
- 向量相似度。
- 邮件时间新近程度。
- 发件人可信度。
- 分类相关性。
- 是否已有结构化事件。

## 17. Prompt 与 Schema 设计

### 17.1 结构化输出优先

分类、事件抽取、任务抽取必须使用严格 JSON schema。

模型输出后必须校验：

- JSON 是否合法。
- 必填字段是否存在。
- 时间是否可解析。
- confidence 是否在 0 到 1。
- evidence 是否非空。

校验失败：

- 尝试一次修复。
- 仍失败则标记 needs_review。

### 17.2 Prompt Version

每个 LLM 任务必须有 prompt_version。

例如：

```text
email_classify_v1
event_extract_v1
task_extract_v1
reply_draft_v1
memory_extract_v1
```

好处：

- 可以回放旧结果。
- 可以比较不同 prompt 效果。
- 可以做离线评测。

### 17.3 置信度与证据

模型输出必须包含：

```text
confidence
evidence
missing_fields
reason
```

没有 evidence 的结果不能自动进入 confirmed。

## 18. 可观测性与评测

### 18.1 结构化日志

每个关键动作记录：

```text
request_id
user_id
agent_run_id
tool_call_id
job_id
email_id
event_id
duration_ms
status
error_code
```

### 18.2 指标

核心指标：

```text
mail_sync_success_rate
mail_sync_latency
email_parse_success_rate
classification_accuracy_sampled
event_extraction_success_rate
event_needs_review_rate
conflict_detection_count
calendar_write_success_rate
llm_cost_per_user
llm_latency
queue_lag
```

### 18.3 Agent 评测集

需要建立人工标注数据：

```text
邮件正文
正确分类
正确事件
正确任务
正确时间
是否应提醒
是否冲突
```

评测指标：

- 分类准确率。
- 事件抽取 precision / recall。
- 时间解析准确率。
- 冲突检测准确率。
- 错误写入外部日历次数。
- 需要人工 review 的比例。

### 18.4 回放机制

每个 agent_run 保存 JSONL：

```text
agent_runs/{run_id}.jsonl
```

内容：

- 用户输入。
- 投影视图上下文摘要。
- 工具调用。
- 工具结果 preview。
- 模型输出。
- schema 校验结果。
- 最终动作。

用于：

- Debug。
- 离线评测。
- Prompt 迭代。
- 审计。

## 19. JSONL 日志设计

### 19.1 为什么保留 JSONL

虽然业务数据进入数据库，但 JSONL 很适合保存 Agent 执行过程。

每行是一个事件：

```json
{"type":"user_message","run_id":"run_1","content":"我明天有什么面试？"}
{"type":"context_built","run_id":"run_1","email_refs":["email_1"],"event_refs":["event_1"]}
{"type":"tool_call","tool":"search.events","input":{"date":"2026-05-05"}}
{"type":"tool_result","tool":"search.events","preview":"找到 2 个事件"}
{"type":"assistant_message","content":"你明天有 2 场面试..."}
```

### 19.2 JSONL 不保存什么

不保存：

- 完整邮件正文。
- 明文 token。
- 附件内容。
- 大段 HTML。

保存引用：

```text
email_id
event_id
tool_result_ref
object_storage_ref
```

## 20. 外部系统接入

### 20.1 邮箱

MVP：

- 网易邮箱 IMAP。
- QQ 邮箱 IMAP。
- Gmail IMAP 或 Gmail API。

长期：

- Outlook Graph API。
- 企业邮箱。
- 自定义 IMAP。

### 20.2 日历

MVP 可以先做内部日历。

后续接入：

- Google Calendar。
- 飞书 Calendar。
- Outlook Calendar。
- Apple Calendar 导出 ICS。

### 20.3 任务系统

后续可接：

- Notion。
- Todoist。
- 飞书任务。
- Linear。
- Jira。

## 21. 前端界面设计

### 21.1 主要页面

```text
Dashboard:
  今日事件、待确认事项、冲突提醒。

Unified Inbox:
  多邮箱统一邮件列表。

Calendar:
  内部日历视图。

Tasks:
  待办事项列表。

Event Review:
  低置信度事件人工确认。

Agent Chat:
  自然语言查询。

Settings:
  邮箱账号、日历账号、提醒偏好、权限设置。

Agent Runs:
  调试和审计日志。
```

### 21.2 待确认动作界面

必须展示：

- 来源邮件标题。
- 抽取出的事件字段。
- 证据片段。
- 置信度。
- 冲突信息。
- 将要执行的外部动作。

用户操作：

- 确认。
- 修改后确认。
- 忽略。
- 标记错误。

## 22. 部署设计

### 22.1 MVP 本地部署

```text
docker-compose
  api-server
  worker
  postgres
  redis
  minio optional
```

### 22.2 生产部署

```text
API Server: 多实例
Workers: 独立扩容
PostgreSQL: 托管数据库
Redis: 托管 Redis
Object Storage: S3 / OSS / MinIO
LLM Provider: 可配置
Secrets: KMS / Vault
Observability: OpenTelemetry + Metrics
```

### 22.3 扩容方向

优先扩容：

- email.parse workers。
- email.classify workers。
- event.extract workers。

瓶颈通常在：

- IMAP 频控。
- LLM 延迟与成本。
- 附件解析。
- 向量索引生成。

## 23. 开发阶段拆分

### 23.1 Phase 1：基础同步与存储

- 建立数据库 schema。
- 实现 mail_accounts。
- 实现 IMAP 增量同步。
- 保存邮件元数据和正文。
- 实现邮件列表页面或 API。

### 23.2 Phase 2：解析与分类

- MIME 解析。
- HTML 清洗。
- 邮件分类。
- 分类结果落库。
- Agent run 日志。

### 23.3 Phase 3：事件与任务抽取

- 事件抽取。
- 时间标准化。
- 任务抽取。
- 低置信度 review。

### 23.4 Phase 4：日历与冲突

- 内部日历。
- 冲突检测。
- 提醒生成。
- 用户确认事件。

### 23.5 Phase 5：Agent 问答

- 用户自然语言查询。
- Context Manager。
- Memory Manager。
- Source reference。

### 23.6 Phase 6：外部系统写入

- 外部日历接入。
- Pending Action。
- 权限确认。
- 幂等写入。

### 23.7 Phase 7：搜索与评测

- PostgreSQL Full Text Search。
- pgvector。
- 离线评测集。
- Prompt 版本对比。

## 24. 关键风险与应对

### 24.1 IMAP 不稳定

风险：

- 不同邮箱 IMAP 实现不同。
- 频控。
- 授权码失效。

应对：

- 增量同步。
- 重试和退避。
- 每个 provider 单独 adapter。
- 同步状态可观测。

### 24.2 时间解析错误

风险：

- 自然语言时间歧义。
- 时区不明确。
- 邮件发送时间与当前时间不同。

应对：

- 使用 email_sent_at 作为 reference_time。
- 保存 timezone_uncertain。
- 低置信度进入 needs_review。
- 保留 evidence。

### 24.3 模型幻觉

风险：

- 编造不存在的时间。
- 编造会议链接。
- 错误分类。

应对：

- 强 schema。
- evidence 必填。
- 字段必须能从邮件原文追溯。
- 低置信度不自动执行。
- 外部动作用户确认。

### 24.4 隐私泄露

风险：

- 日志泄露邮件内容。
- LLM 上下文包含过多敏感信息。
- token 明文存储。

应对：

- 凭证加密。
- 日志脱敏。
- 上下文最小化。
- 原文按需读取。

### 24.5 重复创建日历

风险：

- 同一邮件重试。
- 用户重复点击确认。
- 同一事件多封邮件。

应对：

- dedupe_key。
- idempotency key。
- external_event_id 唯一约束。
- supersedes_event_id 记录更新关系。

## 25. 与 Claude Code 架构的对应借鉴

本项目可以借鉴 Claude Code 的以下思想：

```text
主 Agent Loop:
  工具结果回到主循环，由主循环统一更新状态。

权限系统:
  工具级风险判断 + 全局 deny-first + 用户确认。

Tool Result Budget:
  大输出落盘，上下文只放 preview + ref。

Context Projection:
  完整历史保留，模型只看压缩投影视图。

JSONL Transcript:
  保存 Agent 执行过程，用于调试和审计。

Memory:
  只保存长期有用信息，不保存流水账。

子 Agent:
  后续可把分类、抽取、验证拆成独立 worker agent。
```

但不应照搬：

- 复杂五层上下文压缩。
- fork subagent。
- 插件市场。
- 完整 MCP server 生态。
- CLI 会话恢复机制。

本项目更需要的是：

```text
可靠的数据管道
明确的业务状态
严格权限控制
邮件来源可追溯
低成本异步处理
```

## 26. 推荐 MVP 最小架构

如果要尽快开始实现，建议最小架构如下：

```text
Next.js / React Frontend
        |
        v
Fastify / NestJS API
        |
        +-- PostgreSQL
        +-- Redis
        +-- BullMQ
        +-- Local File Storage
        +-- LLM Provider
        |
        v
Workers
        +-- sync_mailbox
        +-- parse_email
        +-- classify_email
        +-- extract_event
        +-- detect_conflict
```

第一版只接一个邮箱 provider，例如网易邮箱或 QQ 邮箱，把闭环跑通后再扩展 Gmail 和 Outlook。

## 27. 当前需要进一步确认的问题

后续进入详细设计前，需要确认：

- 后端使用 TypeScript 还是 Python。
- 第一版接入哪个邮箱 provider。
- 第一版是否需要前端，还是先做 API + CLI。
- 第一版日历是内部日历，还是直接接飞书 / Google Calendar。
- LLM provider 使用哪一个。
- 是否要求本地优先隐私部署。
- 邮件原文是否完整保存，保存多久。
- MVP 用户规模是个人使用、团队内部，还是外部 SaaS。

