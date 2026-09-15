from __future__ import annotations

import os #用来和操作系统交互
import re #Python 的正则表达式模块
import shlex #用来按照命令行语法拆分字符串
import subprocess #用来从当前 Python程序中启动其他程序或执行系统命令 例如创建一个子进程来执行hello.py
import time #用来计算命令运行了多久
from typing import Any

from Agent01.core.state import RuntimeState

DEFAULT_TIMEOUT_SECONDS = 10 #防止命令运行太久
MAX_OUTPUT_CHARS = 6000 #防止命令输出太多，占用LLM上下文

DANGEROUS_PATTERNS = [ #危险命令
    r"\brm\s+-rf\b",
    r"\bRemove-Item\b.*\b-Recurse\b.*\b-Force\b",
    r"\bdel\s+/[sq]\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r">\s*(?:[A-Za-z]:\\|/)",
]

def _coerce_timeout(timeout_seconds: int | str | float) -> int: #接收命令运行需要的时间 将整型、字符串、浮点型的数字都转换成整型
    try:
        return int(timeout_seconds)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS #转换不了就用默认的10秒

def _normalize_command(command: str) -> str:
    #做“命令兼容转换”的，为了让 LLM生成的一些 Linux/macOS 命令也能在 Windows 上运行
    if os.name == "nt":
        #判断系统是不是Windows #Windows：os.name == "nt" #Linux/macOS：os.name == "posix"
        normalized = re.sub(r"^\s*python3(\.exe)?\b", "python", command, count=1, flags=re.IGNORECASE)
        normalized = re.sub(r"\bls\s+-la\b", "dir", normalized)
        normalized = re.sub(r"\bls\b", "dir", normalized)
        normalized = re.sub(r"\bcat\s+([^\s|&<>]+)", r"type \1", normalized)
        return normalized
    return command

def _handle_tail_command(state: RuntimeState, command: str) -> dict[str, Any] | None:
    #识别 tail 命令，并且不用系统终端执行，而是直接通过 Python读取文件，返回文件最后几行
    #主要是为了兼容 Windows，因为 Windows CMD 默认没有 Linux 的 tail 命令
    #例如 Agent调用：tail -n 10 logs.txt
    #这个函数会直接读取 logs.txt，然后返回最后 10 行
    match = re.fullmatch(r"\s*tail(?:\s+-n)?\s+(\d+)\s+(.+?)\s*", command) #正则匹配tail命令 因为使用的是re.fullmatch() 所以整条命令必须跟正则格式相同
    if not match:
        match = re.fullmatch(r"\s*tail\s+-(\d+)\s+(.+?)\s*", command) #正则匹配第二种tail命令格式
    if not match:
        return None #两次都匹配失败 返回None
    
    count = int(match.group(1)) #取出需要读取的行数
    #match.group(1) 是正则表达式中第一组括号捕获到的内容
    #例如tail -n 10 test.txt 第一个括号匹配到的就是"10" 所以需要读取的行数就是10行

    raw_path = shlex.split(match.group(2), posix=False)[0] #取出文件路径
    #match.group(2) 是正则表达式中第二组括号捕获到的内容
    #例如tail -n 10 test.txt 第二个括号匹配到的内容就是"test.txt" 

    from Agent01.tools.file_tools import read_text_lossy, resolve_workspace_path #导入文件读取相关工具类

    path = resolve_workspace_path(state, raw_path)
    #补全文件路径 变成绝对路径

    if not path.exists() or not path.is_file():
        return {"ok": False, "error": f"file does not exist: {raw_path}"}
    
    lines = read_text_lossy(path).splitlines()
    #读取文件 并拆分成行

    output = "\n".join(lines[-count:])
    #读取出最后count行数返回

    return {
        "ok": True,
        "timed_out": False,
        "command": command,
        "exit_code": 0,
        "stdout": output + ("\n" if output else ""), #正常输出
        "stderr": "", #错误输出为空
        "duration_ms": 0,
    }

def _looks_dangerous(command: str) -> str | None:
    #匹配危险命令；如果匹配到，就返回对应的危险正则规则；如果没有匹配到，就返回 None
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern
    return None


def run_bash(state: RuntimeState, command: str, timeout_seconds: int | str | float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    if not command.strip():
        #检查command是否为空
        return {"ok": False, "error": "command must not be empty"}
    
    timeout = _coerce_timeout(timeout_seconds)
    #定义执行时间

    if timeout <= 0 or timeout > 60:
        #校验时间格式
        return {"ok": False, "error": "timeout_seconds must be between 1 and 60"}
    
    normalized_command = _normalize_command(command)
    #正常化Linux命令到window命令

    handled = _handle_tail_command(state, normalized_command)
    #处理tail命令
    if handled is not None:
        return handled

    blocked = _looks_dangerous(normalized_command)
    #检查是否是危险命令
    if blocked:
        return {"ok": False, "error": f"blocked potentially dangerous command pattern: {blocked}"}

    started = time.perf_counter()
    #记录命令开始执行前的时间

    env = os.environ.copy()
    #复制当前python进程的环境变量 后面要增加环境变量 但不希望直接更改当前python主程序的环境
    env.setdefault("PYTHONIOENCODING", "utf-8")
    #给子进程设置PYTHONIOENCODING=utf-8 作用是让子进程中的python尽量使用utf-8 减少中文乱码
    #setdefault() 的意思是：如果这个变量原来不存在，就设置；如果原来已经存在，则保留原值。
    env.setdefault("PYTHONUTF8", "1")
    #这是告诉子进程中的 Python启用 UTF-8 模式。
    try:
        completed = subprocess.run(  #subprocess.run() 会创建一个子进程，并执行命令 执行完成后结果保存在：completed
            normalized_command,
            cwd=state.workspace, #指定命令从当前 Agent工作区开始执行
            shell=True, #通过系统 Shell执行
            text=True, #让 stdout 和 stderr 返回字符串，而不是字节
            encoding="utf-8", #指定编码
            errors="replace", #无法解码时进行替换
            capture_output=True, # 捕获命令的正常输出和错误输出 执行结束后，可以通过：completed.stdout、completed.stderr获得内容
            timeout=timeout, #设置超时时间
            env=env, #给子进程传递环境变量
        )
    except subprocess.TimeoutExpired as exc:
        #捕获超时异常
        return {
            "ok": False,
            "timed_out": True,
            "exit_code": None,
            "stdout": (exc.stdout or "")[:MAX_OUTPUT_CHARS],
            "stderr": (exc.stderr or "")[:MAX_OUTPUT_CHARS],
            "duration_ms": round((time.perf_counter() - started) * 1000), #减去开始时间获得duration
        }

    stdout = completed.stdout[:MAX_OUTPUT_CHARS] #获取正常输出，并只保留前 6000 个字符
    stderr = completed.stderr[:MAX_OUTPUT_CHARS] #获取错误输出，同样只保留前 6000 个字符
    return {
        "ok": completed.returncode == 0, #判断退出码是否为0 如果为0为true 不为0为false
        "timed_out": False,
        "command": normalized_command,
        "exit_code": completed.returncode, #返回命令退出码
        "stdout": stdout, #正常输出
        "stderr": stderr, #错误输出
        "duration_ms": round((time.perf_counter() - started) * 1000), #执行耗时
    }
