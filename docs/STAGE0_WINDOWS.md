# DeerFlow 1.x：Windows 本机启动与验证

本仓库基于官方 `main-1.x` 分支提交 `2ab28765803d4d9582aaa8f2f3355137d154e273`。这是 DeerFlow 1.x。本文记录最初的 Windows 本机配置和验证；当前二次开发功能及新克隆仓库的安装步骤见仓库根目录的 `README_zh.md`。

第一阶段先跑通原项目的“提出问题 → 规划 → 工具研究 → 汇总报告”流程，再学习 LangGraph 的状态、节点、路由和人工确认。暂不启用 MCP、知识库、Python 代码执行、播客和长期数据库检查点。

## 1. 先理解运行的是什么

- **前端**：浏览器中的聊天与任务执行界面，地址为 <http://127.0.0.1:3000>。
- **后端**：Python/FastAPI 服务，接收前端请求并运行 LangGraph，地址为 <http://127.0.0.1:8000>；接口文档位于 <http://127.0.0.1:8000/docs>。
- **DeepSeek**：通过互联网调用的模型 API，负责理解需求、生成计划、选择工具和生成报告。无需在电脑上下载大模型。
- **Tavily**：原项目采用的联网搜索工具。DeepSeek 本身不会因为接入了 API 就自动获得互联网搜索能力。

打开页面仅表示前端可以访问。完整研究任务还要经过后端、模型 API 和搜索工具；这几部分需要分开验证。

## 2. 环境已放在哪里

下表记录当时本机放在仓库目录内的运行时和依赖；`.tools/`、`.venv/`、`web/node_modules/` 均不会随 Git 仓库发布。新克隆仓库请按根目录 `README_zh.md` 安装所需工具和依赖。

| 路径 | 用途 |
| --- | --- |
| `.tools/python/` | Python 3.12.15 本地运行时 |
| `.venv/` | Python 虚拟环境与后端依赖 |
| `.tools/uv/uv.exe` | uv 0.13.1，用于按锁文件管理 Python 环境 |
| `.tools/node/node.exe` | Node.js 22.23.3 本地运行时 |
| `.tools/pnpm/node_modules/pnpm/bin/pnpm.cjs` | pnpm 10.6.5 |
| `web/node_modules/` | 前端依赖 |
| `.env` | 本机 API 密钥和开关，不应提交 Git |
| `conf.yaml` | 模型名称、API 地址和参数 |
| `.runtime/` | 服务日志、服务进程记录及环境验证结果 |

`.venv` 是 Python 虚拟环境；前端的对应依赖目录是 `web/node_modules`，不放进 Python 虚拟环境。这两部分都位于本项目内。

初次设置使用 Python 的 `uv.lock` 和前端的 `pnpm-lock.yaml` 固定依赖。后续学习时先保持锁文件，避免自行运行升级命令而改变版本组合。

两个上游锁文件均保持原样。针对 Windows 构建时的符号链接权限错误，仅调整了 `web/next.config.js`：Windows 使用普通构建输出，Linux 保留原有 `standalone` 输出。

## 3. 填写 API 密钥

2026-10-20 曾在本机填写两项密钥并完成真实调用验证；密钥不在本仓库中。复现时请在项目根目录的 `.env` 填写自己的密钥：

```dotenv
DEEPSEEK_API_KEY=这里填写你自己的DeepSeek密钥
TAVILY_API_KEY=这里填写你自己的Tavily密钥
```

- DeepSeek：[控制台](https://platform.deepseek.com/)。模型 API 通常按调用量计费；聊天网站账户与 API 额度并非同一概念。
- Tavily：[控制台](https://app.tavily.com/)。用于联网研究，注册后查看当前可用额度。
- 不要把真实密钥贴进聊天、截图或 Git。示例配置位于根目录 `.env.local.example`，其中没有真实密钥。

根目录 `conf.yaml` 已配置为从 `.env` 的 `DEEPSEEK_API_KEY` 读取密钥，并使用 `https://api.deepseek.com` 和 `deepseek-flash`。初始配置关闭模型思考模式，页面中的 **Deep Thinking/深度思考** 也先保持关闭；尚未单独配置 `REASONING_MODEL`。

除上述两项以外，RAG、MCP、TTS、LangSmith 等配置可以先留空。不要因为页面出现可选入口，就认为必须注册全部服务。

如果暂时没有 Tavily 密钥，可以保持空白，先做不需要搜索的模型连通验证。也可将 `.env` 中的 `SEARCH_API=tavily` 改为 `SEARCH_API=duckduckgo`；该选项不需要搜索 API 密钥，但能否访问取决于网络，不能保证研究流程稳定。

修改 `.env` 或 `conf.yaml` 后，停止并重新启动服务，使配置重新加载。

## 4. 启动与停止

在资源管理器中进入本仓库根目录。当时的 `start.cmd` 使用项目内 `.tools/` 运行时；新克隆仓库如果没有这套本机运行时，请使用根目录 `README_zh.md` 中的标准启动命令。

1. 填好 `.env`，保存文件。
2. 双击根目录 `start.cmd`，启动本项目的前后端并打开页面。
3. 首次启动前端会编译页面，浏览器暂时空白或等待时先等编译完成。
4. 在浏览器访问 <http://127.0.0.1:3000>。
5. 使用完毕后双击根目录 `stop.cmd`，停止本项目的服务。

也可以在 PowerShell 中运行，便于阅读提示：

```powershell
# 先在 PowerShell 中进入本仓库根目录
.\start.cmd
```

停止：

```powershell
.\stop.cmd
```

启动脚本使用项目内的运行时，不需要先激活 `.venv`，也不需要调整系统 Python 或 Node.js。

2026-10-20 验证结束时前后端服务保持运行，可直接打开页面。以后若服务已关闭，执行 `start.cmd` 即可。重复启动会复用本项目已有服务；停止脚本会处理本项目登记的进程树。

日志位于 `.runtime`：后端为 `backend.stdout.log`、`backend.stderr.log`，前端为 `frontend.stdout.log`、`frontend.stderr.log`。`services.json` 用来记录本项目启动的服务进程。

## 5. 怎么验证“真的跑通”

### 5.1 不调用付费 API 的检查

在项目目录的 PowerShell 中运行：

```powershell
.\verify.cmd
```

这一步检查本地依赖、原项目状态图和前后端 HTTP 服务，不调用付费模型。验证结果写入 `.runtime/verification.json`；通过本地检查不代表已经完成真实 DeepSeek 调用或联网研究。

还可以手动查看以下地址：

- <http://127.0.0.1:3000>：能看到项目页面。
- <http://127.0.0.1:8000/docs>：能看到 FastAPI 接口文档。

接口文档是给开发者调试 API 的页面。日常演示和学习使用前端聊天页面即可，无需在接口文档里手工拼 JSON。

### 5.2 模型连通检查

需要复查模型连通性时，使用真实 API 验证选项：

```powershell
.\verify.cmd --live
```

真实验证通过原项目的模型适配器执行短文本调用和一个无副作用的加法工具闭环，会产生少量 API 费用。它用于确认密钥、模型和工具调用能力，不调用 Tavily，也不生成完整研究报告。以脚本最终输出为准；模型连通与搜索连通是不同检查。

### 5.3 复现完整研究流程验证

在前后端运行时，执行：

```powershell
# 先在 PowerShell 中进入本仓库根目录，并启动前后端
.\.venv\Scripts\python.exe scripts\verify_research.py
```

这会消耗真实 DeepSeek 调用和 Tavily 额度，学习阶段运行一次即可。脚本通过原项目 `/api/chat/stream` 接口提交任务，收到计划审核中断后，再用同一 `thread_id` 发送 `accepted` 恢复执行。它自动批准本次测试计划，方便验证人工审核与恢复机制。

报告保存在 `.runtime/research-report.md`，检查汇总保存在 `.runtime/research-verification.json`。这些 API 验证生成的历史**不会自动出现在前端页面**；前端和验证脚本访问同一后端接口，但前端需要自行创建一次任务。

### 5.4 在前端观察同一个任务

打开 <http://127.0.0.1:3000/chat>，保持**深度思考关闭、联网搜索开启、自动批准计划关闭、背景调查关闭**。在设置中将计划轮数设为 1、计划步骤数设为 1、每次搜索结果数设为 2。其他可选功能先保持关闭。

输入与验证脚本相同的提示：

> 为在 Windows 上学习 Python 的学生调研项目环境管理方案：比较 Python venv + pip 与 uv 创建和管理独立项目环境的方式。必须联网查阅 docs.python.org 的 venv 官方文档和 docs.astral.sh 的 uv 官方文档，不要只凭已有知识回答。研究计划只安排 1 个 research 步骤，need_search=true。研究阶段最多搜索 2 次，只收集官方文档证据，不执行代码，不生成图片。最终用中文给出约 500 字的说明，包含选择建议、Windows PowerShell 命令和来源链接。

“最多搜索 2 次”是提示词要求，**不是代码强制的预算上限**；设置中的“搜索结果数 2”指每次搜索返回多少条结果，也不是调用次数上限。

观察以下结果：

1. **计划出现**：模型理解了需求并生成研究步骤。
2. **确认计划**：如界面要求审批，阅读后确认继续，也可先修改研究范围。
3. **工具执行**：界面显示搜索或网页读取步骤，说明任务进入工具研究阶段。
4. **报告完成**：出现最终中文报告和可打开的来源链接。

如果只出现计划而没有工具结果，不能算完整研究成功；如果只打开了页面，也不能证明 DeepSeek 密钥有效。

## 6. 本轮配置与验证记录

阶段 0 环境配置历史：

- 下载并固定官方 1.x 源码提交。
- 项目内安装 Python 3.12.15、uv 0.13.1、Node.js 22.23.3、pnpm 10.6.5。
- Python 按 `uv sync --locked --extra test` 安装完成，173 个包已解析安装。
- `uv pip check` 通过。
- 前端按冻结锁文件安装完成，1131 个包已安装。
- 40 项上游精选测试通过，覆盖主图构建、模型配置、配置加载和聊天请求模型。
- 前端 TypeScript 类型检查、Next.js 构建通过。
- 前端首页、`/chat`，后端 `/api/config`、`/api/rag/config`、`/docs` 均返回 HTTP 200。
- 后端跨域配置允许前端 `http://127.0.0.1:3000`，模型配置接口返回 `deepseek-flash`。
- 初次配置、密钥留空时，默认检查为 **10 PASS / 3 WARN / 0 FAIL**，没有发起真实模型请求。这是历史结果，不代表当前密钥状态。
- 初次验证已确认：空密钥下执行 `verify.cmd --live` 会在本地前置检查中退出，不发起 HTTP 或模型请求。
- 启动、重复启动和停止流程通过；当时停止后已确认本项目两个服务进程树退出，端口关闭。
- 创建 `.env`、`conf.yaml` 与无密钥示例配置。

2026-10-20 填入两项密钥后的真实验证：

- `verify_setup.py --live`：**13 PASS / 1 WARN / 0 FAIL**。通过原项目模型适配器完成 3 次模型请求，验证短文本回复和加法工具选择、执行、模型读取结果的闭环。剩余 WARN 表示该脚本本身不执行搜索；搜索另由下一项验证。
- `verify_research.py`：向原 `/api/chat/stream` 发起两次 HTTP 请求，均返回 200；真实观察到计划 `interrupt`、`accepted` 恢复、2 次 `web_search` 和 2 次 `crawl_tool`，最终生成带 4 个官方来源的报告。
- 完整研究耗时 **34.83 秒**，9 项流程检查全部通过。报告长度为 **3132 字符（含 Markdown）**，没有严格满足提示中的“约 500 字”。
- 报告与汇总分别位于 `.runtime/research-report.md`、`.runtime/research-verification.json`；本次验证结束后前后端服务保持运行。

这证明模型、搜索、网页读取、计划审核恢复和报告生成的主流程可以运行，**不保证每条报告结论正确，也不代表长度等任务约束均已满足**。MCP、RAG、Python 执行等未启用模块仍需后续单独验证。

## 7. 常见问题

**发送消息后出现 `removeChild` / `Runtime NotFoundError`。**

浏览器自动翻译或其他扩展可能改写 React 管理的页面节点，发送消息后的界面更新因此失败。若 Logo 从 `DeerFlow` 变成“鹿流”，说明页面经过了外部翻译。先关闭该站点的浏览器翻译，按 `Ctrl+Shift+R` 刷新，再用聊天页右上角的 `English / 中文` 按钮选择项目原生中文。

本地已在根布局加入 `translate="no"` 和翻译禁用标记，并启用原有语言切换组件。2026-10-20 已通过 TypeScript 检查，以及独立 Edge 浏览器中的语言切换、发送消息、欢迎页切换和计划展示回放检查；该检查未调用真实模型或搜索 API。这是针对翻译干扰的修复；若关闭翻译并刷新后仍出现错误，应继续检查其他扩展和组件栈。

**页面能打开，但发送消息失败。**

先检查后端的 <http://127.0.0.1:8000/docs> 能否打开，再检查 `.env` 的密钥和服务日志。错误发生在本地服务、模型还是搜索，是不同原因。

**DeepSeek 返回 401、402 或模型错误。**

401 通常需要核对密钥；402 通常需要核对 API 账户额度；模型错误需核对 `conf.yaml` 的模型名称与当前账户支持情况。不要将密钥或完整请求头公开粘贴。

**模型能回答，但研究卡在搜索。**

检查 `SEARCH_API`、Tavily 密钥、搜索额度与网络。模型 API 成功不代表搜索 API 成功。

**提示 3000 或 8000 端口被占用。**

先确认是不是本项目已在运行。可先执行 `stop.cmd` 再启动；若是其他程序占用，应识别程序后再决定处理，避免结束无关进程。

**关闭后重启，任务没有继续。**

当前没有启用数据库检查点，运行中的内存状态不在后端重启后保留。浏览器显示旧聊天记录，也不代表后端任务状态仍在。

**为什么暂时没有启用 Python 工具、MCP 和知识库？**

这些是后续学习模块。当前先验证原项目主流程，减少同时排查的变量；等理解图和工具调用后，再逐项启用并验证。

## 8. 第一轮阅读入口

先跟踪刚才的同一个任务，再阅读对应源码：

1. `src/graph/builder.py`、`types.py`：先看节点、条件路由和共享 State 中的计划、观察结果、引用、最终报告。
2. `src/graph/nodes.py`：只读 `planner_node`、`human_feedback_node`，理解计划与 `interrupt` 审核。
3. `src/agents/agents.py`、`src/tools/search.py`、`crawl.py`：理解 LangChain `create_agent` 内部的模型与工具循环。
4. 返回 `nodes.py`：跟踪研究步骤结果写回 State，以及 `reporter_node` 汇总报告。
5. `src/server/app.py`、`web/src/core/store/store.ts`：最后连接请求入口、恢复命令和 SSE 页面展示。

外层 LangGraph 管角色和步骤，内部 Agent 管工具选择。默认按第一个未完成步骤顺序调度，不能把多个角色理解成默认并行执行。当前已有 MCP/RAG 接口、上下文裁剪、引用收集和基础报告评测；检查点属于工作流状态保存，不等于长期用户偏好记忆。运行时 Skills、逐条结论证据核验、硬性调用预算等可作为后续开发方向。先理解这一条完整请求，不需要第一天看完整个仓库。
