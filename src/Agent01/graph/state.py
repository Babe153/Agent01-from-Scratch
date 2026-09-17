from __future__ import annotations

from typing import Annotated, Any, TypedDict #typing 是 Python 自带的类型注解工具包。
# Annotated 用于在一个类型上附加额外信息
# Any 表示这里可以放任意类型的数据
# TypedDict 用于描述一个字典应该有哪些键，以及每个键的值是什么类型

from langchain_core.messages import BaseMessage #langchain_core是langchain的核心基础包 其中messages模块定义了各种聊天消息类型 例如HumanMessage AIMessage SystemMessage ToolMessage
#这些消息类有一个共同的父类 BaseMessage 

from langgraph.graph import add_messages #langgraph 是用来构建有状态 Agent 工作流的库 add_messages 是 LangGraph提供的消息合并函数
#你可以把一个 Agent 拆成多个节点，例如： 规划节点 → 执行节点 → 验证节点 → 最终回答节点 多个节点共享同一个 Graph State，也就是这里后面定义的： Agent01GraphState

from Agent01.core.state import RuntimeState #从项目里的 core/state.py 导入RuntimeState 它大概负责保存： Agent 的工作区路径 Agent 读取过哪些文件 文件读取时的修改时间


class TodoItem(TypedDict): #定义一种“固定结构的字典类型”
    #规定一个 TodoItem 字典应该包含四个键，并且这四个键对应的值都应该是字符串
    id: str
    content: str
    status: str
    note: str

class VerificationResult(TypedDict): #定义一种“固定结构的字典类型”
    #规定一个 VerificationResult 字典应该包含五个键 以及对应的值的类型
    command: str
    ok: bool
    exit_code: int | None
    stdout: str
    stderr: str

class Agent01GraphState(TypedDict, total=False): #total=False 这表示下面声明的字段不要求同时存在。
    task: str #保存用户交给 Agent 的原始任务
    runtime: RuntimeState #RuntimeState 管工作区和文件操作安全
    messages: Annotated[list[BaseMessage], add_messages] #用于保存 Agent 对话和工具调用过程中产生的消息
    plan_summary: str #保存 Agent 对任务的整体计划总结
    todos: list[TodoItem] #保存具体的任务步骤
    acceptance_criteria: list[str] #保存“满足什么条件才算完成任务
    verification_commands: list[str] #保存用于验证修改结果的命令
    verification_results: list[VerificationResult] #保存验证命令的实际执行结果
    passed: bool #表示最终验证是否通过
    attempts: int #记录当前已经尝试修改或验证了多少次
    max_attempts: int #表示最多允许尝试多少次
    final_answer: str #保存最终准备返回给用户的答案
    last_actor_summary: str #保存最近一个执行节点完成了什么
    last_error: str #保存最近一次发生的错误
    metadata: dict[str, Any] #用于保存不适合单独定义成字段的附加数据