<p align="center">
  <img src="./logo.png" alt="Agent01 Logo" width="460" />
</p>

<h1 align="center">Agent01 · From Scratch</h1>

<p align="center">以学习为目的，从读懂每一行代码开始，逐步搭建一个能调用工具完成任务的 Agent。</p>

## 关于项目

Agent01 是我的 Agent 开发学习仓库，参考 MokioClaw 项目逐文件阅读、重建，并记录自己的理解与注释。目标是理解模型、提示词、工具和运行状态如何配合，把自然语言任务变成实际的文件操作与代码执行。

本项目使用 LangChain 等现有框架；“From Scratch”指从项目结构和基础模块开始逐步学习、组装，而不是从零实现大模型或 Agent 框架。

**当前进度：第一阶段已完成——基于 `create_agent()` 的单 Agent ReAct 工具调用循环。**

下一阶段计划学习 LangGraph，将任务拆成规划、执行、验收与重试。多 Agent、上下文压缩等能力尚未在当前版本中实现。

## 第一阶段：让 Agent 使用工具完成任务

当前版本将模型、系统提示词和工具交给 LangChain 的 `create_agent()` 组装。Agent 根据任务决定是否调用工具，工具执行结果返回模型，模型再决定继续操作还是给出最终答复。

```text
用户输入任务
    ↓
CLI 接收任务与工作区参数
    ↓
创建 RuntimeState，准备模型、提示词与工具
    ↓
模型生成回复或工具调用请求
    ├─ 调用工具 → 执行 Python 函数 → 结果返回模型 → 继续循环
    └─ 最终回复 → 展示执行结果
```

当前提供的工具：

| 工具 | 功能 |
| --- | --- |
| `FileReadTool` | 读取工作区中的文本文件，支持按行截取 |
| `FileWriteTool` | 创建文件或整体覆盖已有文件 |
| `FileEditTool` | 通过匹配旧文本进行局部替换 |
| `GrepTool` | 按正则表达式搜索文件内容 |
| `BashTool` | 执行开发命令，收集退出码、标准输出和错误输出 |

`RuntimeState` 保存工作区路径与文件读取记录，文件工具据此检查路径和编辑条件。CLI 使用 Typer 接收参数，并使用 Rich 展示运行过程。

这一阶段的验证由 Agent 调用命令工具完成，还没有独立的 planner / verifier 工作流。命令工具在本机执行命令，工作目录和基础拦截不等于完整的系统沙箱。

## 如何运行

以下示例使用 Windows PowerShell，请在项目根目录执行。

### 1. 准备环境

需要 Python 3.13 或以上版本，以及 uv。uv 的安装方法见 [官方安装文档](https://docs.astral.sh/uv/getting-started/installation/)。

进入你下载或克隆的项目目录后，安装项目与依赖：

```powershell
cd Agent01-from-Scratch
uv sync
```

uv 会根据项目配置和锁文件准备 `.venv` 环境。后续使用 `uv run` 执行命令，不需要手动激活虚拟环境。

### 2. 配置模型

首次配置时，将根目录的 `.env.example` 复制为 `.env`：

```powershell
Copy-Item .env.example .env
```

如果已经有 `.env`，直接编辑已有文件。填写以下三项：

```dotenv
API_KEY=你的API密钥
MODEL=你的模型名称
BASE_URL=你的模型服务API地址
```

三项均为当前代码的必填配置。项目通过 `ChatOpenAI` 连接服务，需要使用兼容该客户端且支持工具调用的模型与接口地址。`BASE_URL` 填 API 基础地址，不是聊天网页地址。

`.env` 已列入 `.gitignore`，不要将真实密钥提交到仓库。

### 3. 查看命令帮助

```powershell
uv run Agent01 --help
```

这一步只显示帮助，不会调用模型。

### 4. 执行第一个任务

```powershell
uv run Agent01 "创建一个 hello.py，运行后输出 Hello, Agent01!，然后执行它验证结果。"
```

默认工作区为项目根目录下的：

```text
.Agent01/workspace/
```

运行时会自动创建工作区。可以在终端观察工具调用与结果，并在该目录查看生成的文件。第一阶段默认重复使用同一工作区。

也可以指定工作区：

```powershell
uv run Agent01 "编写一个只使用标准库的计算器脚本，并用非交互方式运行一个示例。" --workspace ./demo-workspace
```

以下启动方式也会进入同一个 CLI：

```powershell
uv run main.py "你的任务"
uv run python -m Agent01 "你的任务"
```

不提供任务时会显示帮助并退出。

## 代码结构

```text
Agent01-from-Scratch/
├─ src/Agent01/
│  ├─ providers/openai_provider.py  # 读取环境配置，创建模型客户端
│  ├─ core/
│  │  ├─ paths.py                   # 定位项目根目录和默认工作区
│  │  ├─ state.py                   # 运行状态与文件读取记录
│  │  └─ agent.py                   # 组装 Agent，运行并转发事件
│  ├─ tools/
│  │  ├─ file_tools.py              # 文件读取、写入和编辑
│  │  ├─ grep_tool.py               # 文本搜索
│  │  ├─ bash_tool.py               # 命令执行
│  │  └─ registry.py                # 将函数包装为模型可调用的工具
│  ├─ prompts/version1.py           # 第一阶段系统提示词
│  ├─ cli/
│  │  ├─ app.py                     # 命令行参数与启动入口
│  │  └─ formatter.py               # 执行事件的终端展示
│  └─ __main__.py                   # python -m Agent01 入口
├─ main.py                         # 脚本启动入口
├─ pyproject.toml                  # 项目信息、依赖与命令注册
├─ uv.lock                         # 依赖锁文件
├─ .env.example                    # 模型配置模板
└─ logo.png                        # Agent01 Logo
```

## 学习记录

第一阶段主要学习：

- 使用 uv 管理 Python 项目、依赖和运行环境。
- 区分模型客户端、系统提示词、工具和运行状态的职责。
- 使用 `StructuredTool.from_function()` 包装 Python 函数。
- 使用闭包将运行状态传入工具，保留需要模型填写的参数。
- 理解模型提出工具调用请求、Python 执行工具、结果返回模型的交互过程。
- 使用流式事件将 Agent 执行过程连接到命令行展示。

下一阶段将继续在此基础上学习显式的 LangGraph 工作流、Todo 状态管理、独立验证与失败重试。
