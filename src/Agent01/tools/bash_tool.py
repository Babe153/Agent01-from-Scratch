from __future__ import annotations

import os #用来和操作系统交互
import platform #导入 Python 自带的系统信息模块，可以获取操作系统、处理器、Python 版本等信息
import re #Python 的正则表达式模块
import shlex #用来按照命令行语法拆分字符串
import subprocess #用来从当前 Python程序中启动其他程序或执行系统命令 例如创建一个子进程来执行hello.py
import sys
from pathlib import Path
import time #用来计算命令运行了多久
from typing import Any

from Agent01.core.approval import ApprovalDecision, classify_command_risk, make_approval_request
from Agent01.core.state import RuntimeState

DEFAULT_TIMEOUT_SECONDS = 120 #防止命令运行太久
DEFAULT_MAX_TIMEOUT_SECONDS = 600 #新增：默认允许的最大超时，实际值可由运行配置覆盖
DEFAULT_MAX_OUTPUT_CHARS = 6000 #防止命令输出太多，占用LLM上下文

DANGEROUS_PATTERNS = [ #危险命令
    r"\brm\s+-rf\b",
    r"\bRemove-Item\b.*\b-Recurse\b.*\b-Force\b",
    r"\bdel\s+/[sq]\b",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"(?:^|[^0-9])>\s*(?:[A-Za-z]:\\|/(?!dev/null\b))",
]

def bash_tool_description() -> str:
    system = platform.system().lower()
    common = (
        "Run a safe development shell command inside the workspace with timeout and output capture. "
        "The command already runs with cwd set to the workspace, so use relative paths and do not run cd /workspace, "
        "cd workspace, or long-lived interactive commands. Each call starts a fresh shell; exported variables do not persist "
        "between calls, so write reusable environment values to the configured env file or pass them inline. "
        "Long-running servers should use run_in_background=true. Prefer cross-platform Python one-liners for file checks."
    )
    if system == "windows":
        return (
            common
            + " Current platform: Windows. Commands are executed by cmd.exe, not bash or PowerShell. "
            "Use Windows cmd syntax: dir for listing, type file.txt for printing a file, copy/move/del for simple file operations, "
            "&& for chaining, and set VAR=value for environment variables. Do not use POSIX-only tools like tail, grep, sed, awk, "
            "cat, ls, export, or here-documents unless you implement the behavior with python -c."
        )
    if system == "darwin":
        return (
            common
            + " Current platform: macOS. Commands are executed by a POSIX shell. "
            "Use portable sh/bash-style commands such as ls, cat, grep, tail, export, and python/python3 as available."
        )
    return (
        common
        + " Current platform: Linux/Unix. Commands are executed by a POSIX shell. "
        "Use portable sh/bash-style commands such as ls, cat, grep, tail, export, and python/python3 as available."
    )


def _coerce_timeout(timeout_seconds: int | str | float) -> int: #接收命令运行需要的时间 将整型、字符串、浮点型的数字都转换成整型
    #新增：None 表示调用方没有指定超时；run_bash 会进一步读取运行状态中的默认值。
    if timeout_seconds is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return int(timeout_seconds)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_SECONDS #转换不了就用默认的10秒

def _normalize_command(command: str) -> str:
    #做“命令兼容转换”的，为了让 LLM生成的一些 Linux/macOS 命令也能在 Windows 上运行
    if os.name == "nt":
        #判断系统是不是Windows #Windows：os.name == "nt" #Linux/macOS：os.name == "posix"
        normalized = re.sub(r"^\s*python3(\.exe)?\b", "python", command, count=1, flags=re.IGNORECASE)
        normalized = re.sub(
            r"^\s*cd\s+(?:/workspace|workspace|\.?/workspace|\.Agent01[\\/]+workspace)\s*(?:&&|&)\s*",
            "",
            normalized,
            count=1,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(r"^\s*pwd\s*$", "cd", normalized, count=1, flags=re.IGNORECASE)
        normalized = re.sub(r"\bls\s+-la\b", "dir", normalized)
        normalized = re.sub(r"\bls\b", "dir", normalized)
        normalized = re.sub(r"\bcat\s+([^\s|&<>]+)", r"type \1", normalized)
        return normalized
    return re.sub(
        r"^\s*cd\s+(?:/workspace|workspace|\.?/workspace|\.mokioclaw[\\/]+workspace)\s*(?:&&|;)\s*pwd\s*$",
        "cd",
        command,
        count=1,
        flags=re.IGNORECASE,
    )

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

def _handle_workspace_query(state: RuntimeState, command: str) -> dict[str, Any] | None:
    #直接回答工作目录查询 如果命令只是 cd 或 pwd，就直接返回工作区路径，不启动子进程执行命令。
    #如果不是这类命令 就返回None
    if not re.fullmatch(r"\s*(?:cd|pwd)\s*", command, flags=re.IGNORECASE):
        return None
    return {
        "ok": True,
        "timed_out": False,
        "command": command.strip() or "cd",
        "exit_code": 0,
        "stdout": f"{state.workspace}\n",
        "stderr": "",
        "duration_ms": 0,
    }

def _looks_dangerous(command: str) -> str | None:
    #匹配危险命令；如果匹配到，就返回对应的危险正则规则；如果没有匹配到，就返回 None
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return pattern
    return None

def _decode_output(output: bytes | str | None) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    for encoding in ("utf-8", "gbk", "mbcs"):
        try:
            return output.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return output.decode("utf-8", errors="replace")


def run_bash(
    state: RuntimeState,
    command: str,
    timeout_seconds: int | str | float | None = None,
    run_in_background: bool | str = False,
) -> dict[str, Any]:
    #改动：未指定超时时读取配置；后台模式启动进程后立即返回，不等待最终执行结果。
    if not command.strip():
        #检查command是否为空
        return {"ok": False, "error": "command must not be empty"}
    
    max_timeout = _state_int(state, "bash_max_timeout_seconds", DEFAULT_MAX_TIMEOUT_SECONDS)
    timeout = _coerce_timeout(timeout_seconds)
    if timeout_seconds is None:
        timeout = _state_int(state, "bash_default_timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    #定义执行时间

    if timeout <= 0 or timeout > max_timeout:
        #校验时间格式
        return {"ok": False, "error": f"timeout_seconds must be between 1 and {max_timeout}"}
    
    normalized_command = _normalize_command(command)
    #正常化Linux命令到window命令
    background = _coerce_bool(run_in_background) #兼容模型传入 true、"true" 等形式

    handled = _handle_tail_command(state, normalized_command)
    #处理tail命令
    if handled is not None:
        return handled

    handled = _handle_workspace_query(state, normalized_command)
    if handled is not None:
        return handled

    blocked = _looks_dangerous(normalized_command)
    #检查是否是危险命令
    if blocked:
        return {"ok": False, "error": f"blocked potentially dangerous command pattern: {blocked}"}

    approval = _resolve_approval(state, normalized_command)
    if approval is not None and not approval.get("approved"):
        return approval

    started = time.perf_counter()
    #记录命令开始执行前的时间

    #改动：环境准备移入 _build_env，统一加载环境文件并调整工具查找路径。
    env, env_error = _build_env(state)
    if env_error is not None:
        return {"ok": False, "error": env_error}
    max_output_chars = _state_int(state, "bash_max_output_chars", DEFAULT_MAX_OUTPUT_CHARS)
    if background:
        return _run_background(state, normalized_command, env, approval)
    try:
        completed = subprocess.run(  #subprocess.run() 会创建一个子进程，并执行命令 执行完成后结果保存在：completed
            normalized_command,
            cwd=state.workspace, #指定命令从当前 Agent工作区开始执行
            shell=True, #通过系统 Shell执行
           #text=True, #让 stdout 和 stderr 返回字符串，而不是字节
           #encoding="utf-8", #指定编码
           #errors="replace", #无法解码时进行替换
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
            #超时前已产生的输出也保留；超长内容写入日志文件。
            **_format_captured_output(state, _decode_output(exc.stdout), _decode_output(exc.stderr), max_output_chars),
            "duration_ms": round((time.perf_counter() - started) * 1000), #减去开始时间获得duration
            **(approval or {}), #超时结果也带上审批信息
        }

   #stdout = completed.stdout[:MAX_OUTPUT_CHARS] #获取正常输出，并只保留前 6000 个字符
   #stderr = completed.stderr[:MAX_OUTPUT_CHARS] #获取错误输出，同样只保留前 6000 个字符
    #改动：不再直接丢弃超长输出，返回截短内容和完整日志路径。
    output = _format_captured_output(
        state, _decode_output(completed.stdout), _decode_output(completed.stderr), max_output_chars
    )
    return {
        "ok": completed.returncode == 0, #判断退出码是否为0 如果为0为true 不为0为false
        "timed_out": False,
        "command": normalized_command,
        "exit_code": completed.returncode, #返回命令退出码
        #正常输出
        #错误输出
        **output,
        "duration_ms": round((time.perf_counter() - started) * 1000), #执行耗时
        **(approval or {}),
    }


def _resolve_approval(state: RuntimeState, command: str) -> dict[str, Any] | None:
    risk_reason = classify_command_risk(command)
    if risk_reason is None:
        return None

    request = make_approval_request(command, risk_reason)
    base = {
        "requires_approval": True,
        "approval_id": request.id,
        "risk_reason": risk_reason,
        "command": command,
    }
    if state.approval_mode == "auto":
        return {**base, "approved": True}
    if state.approval_mode == "deny" or state.approval_handler is None:
        return {
            **base,
            "ok": False,
            "approved": False,
            "error": f"human approval required for high-risk command: {risk_reason}",
        }

    decision = state.approval_handler(request)
    if isinstance(decision, ApprovalDecision):
        approved = decision.approved
        decision_reason = decision.reason
    else:
        approved = bool(decision)
        decision_reason = ""
    if approved:
        return {**base, "approved": True}
    return {
        **base,
        "ok": False,
        "approved": False,
        "error": decision_reason or f"human rejected high-risk command: {risk_reason}",
    }


def _state_int(state: RuntimeState, name: str, default: int) -> int:
    #新增：从运行状态读取正整数配置；缺失、无效或非正数时返回默认值。
    try:
        value = int(getattr(state, name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _coerce_bool(value: bool | str) -> bool:
    #新增：统一布尔参数，避免 bool("false") 反而得到 True；只认可列出的真值字符串。
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _build_env(state: RuntimeState) -> tuple[dict[str, str], str | None]:
    #新增：每次命令构建独立环境，不修改主进程；再合并环境文件中的变量。
    env = os.environ.copy()
    #复制当前python进程的环境变量 后面要增加环境变量 但不希望直接更改当前python主程序的环境
    env.setdefault("PYTHONIOENCODING", "utf-8")
    #给子进程设置PYTHONIOENCODING=utf-8 作用是让子进程中的python尽量使用utf-8 减少中文乱码
    #setdefault() 的意思是：如果这个变量原来不存在，就设置；如果原来已经存在，则保留原值。
    env.setdefault("PYTHONUTF8", "1")
    #这是告诉子进程中的 Python启用 UTF-8 模式。
    _prepend_harness_paths(state, env)
    env_file = state.bash_env_file or state.workspace / ".Agent01.env"
    if env_file.exists():
        try:
            env.update(_parse_env_file(env_file, env))
        except OSError as exc:
            return env, f"failed to read bash env file {env_file}: {exc}"
    return env, None


def _prepend_harness_paths(state: RuntimeState, env: dict[str, str]) -> None:
    #新增：把工具包装脚本及项目工具目录放到 PATH 前部，减少调用到错误环境的情况。
    path_candidates = [
        _ensure_toolchain_shims(state),
        state.workspace / ".venv" / ("Scripts" if os.name == "nt" else "bin"),
        state.workspace / "venv" / ("Scripts" if os.name == "nt" else "bin"),
        state.workspace / "node_modules" / ".bin",
        Path(sys.executable).parent,
    ]
    existing = [part for part in env.get("PATH", "").split(os.pathsep) if part]
    merged: list[str] = []
    for path in [str(candidate) for candidate in path_candidates if candidate.exists()] + existing:
        if path not in merged:
            merged.append(path)
    env["PATH"] = os.pathsep.join(merged)
    if getattr(sys, "prefix", None) and sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        env.setdefault("VIRTUAL_ENV", sys.prefix)


def _ensure_toolchain_shims(state: RuntimeState) -> Path:
    #新增：生成命令转发脚本，让 python/pip 使用当前解释器；pip 缺失时尝试 ensurepip。
    shim_dir = state.workspace / ".Agent01" / "shims"
    shim_dir.mkdir(parents=True, exist_ok=True)
    python_executable = sys.executable
    if os.name == "nt":
        _write_shim(shim_dir / "python.cmd", f'@echo off\r\n"{python_executable}" %*\r\n')
        _write_shim(shim_dir / "python3.cmd", f'@echo off\r\n"{python_executable}" %*\r\n')
        pip_cmd = (
            "@echo off\r\n"
            f'"{python_executable}" -c "import pathlib,sys; import pip; '
            'p=pathlib.Path(pip.__file__).resolve(); '
            'prefix=pathlib.Path(sys.prefix).resolve(); '
            'raise SystemExit(0 if p == prefix or prefix in p.parents else 1)" >nul 2>nul\r\n'
            f'if errorlevel 1 "{python_executable}" -m ensurepip --upgrade >nul 2>nul\r\n'
            f'"{python_executable}" -m pip %*\r\n'
        )
        _write_shim(shim_dir / "pip.cmd", pip_cmd)
        _write_shim(shim_dir / "pip3.cmd", pip_cmd)
        return shim_dir
    _write_shim(shim_dir / "python", f"#!/bin/sh\nexec {shlex.quote(python_executable)} \"$@\"\n")
    _write_shim(shim_dir / "python3", f"#!/bin/sh\nexec {shlex.quote(python_executable)} \"$@\"\n")
    quoted_python = shlex.quote(python_executable)
    pip_shim = (
        "#!/bin/sh\n"
        f"{quoted_python} - <<'PY' >/dev/null 2>&1\n"
        "import pathlib\n"
        "import sys\n"
        "import pip\n"
        "pip_path = pathlib.Path(pip.__file__).resolve()\n"
        "prefix = pathlib.Path(sys.prefix).resolve()\n"
        "raise SystemExit(0 if pip_path == prefix or prefix in pip_path.parents else 1)\n"
        "PY\n"
        "if [ $? -ne 0 ]; then\n"
        f"  {quoted_python} -m ensurepip --upgrade >/dev/null 2>&1 || exit $?\n"
        "fi\n"
        f"exec {quoted_python} -m pip \"$@\"\n"
    )
    _write_shim(shim_dir / "pip", pip_shim)
    _write_shim(shim_dir / "pip3", pip_shim)
    return shim_dir


def _write_shim(path: Path, content: str) -> None:
    #新增：仅在内容变化时写入包装脚本；Unix 还需要设置可执行权限。
    if not path.exists() or path.read_text(encoding="utf-8", errors="replace") != content:
        path.write_text(content, encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o755)


def _parse_env_file(path, base_env: dict[str, str]) -> dict[str, str]:
    #新增：逐行解析 KEY=value，忽略注释和无效行；这是简单解析器，不执行 shell 代码。
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        parsed[key] = _expand_env_value(_unquote_env_value(value.strip()), {**base_env, **parsed})
    return parsed


def _unquote_env_value(value: str) -> str:
    #新增：去掉首尾配对引号，例如把 "hello" 转成 hello。
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _expand_env_value(value: str, env: dict[str, str]) -> str:
    #新增：用已有变量替换 $NAME 或 ${NAME}；找不到的变量替换为空字符串。
    def replace_var(match: re.Match[str]) -> str:
        name = match.group("braced") or match.group("plain") or ""
        return env.get(name, "")

    return re.sub(r"\$\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)\}|\$(?P<plain>[A-Za-z_][A-Za-z0-9_]*)", replace_var, value)


def _format_captured_output(state: RuntimeState, stdout: str, stderr: str, max_output_chars: int) -> dict[str, Any]:
    #新增：给模型返回有限长度文本，超出的完整输出写入工作区日志，并返回相对路径。
    output: dict[str, Any] = {}
    output_dir = state.workspace / ".Agent01" / "bash-outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    if len(stdout) > max_output_chars:
        stdout_path = output_dir / f"stdout-{time.time_ns()}.log"
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        output["stdout_path"] = str(stdout_path.relative_to(state.workspace))
        output["stdout_truncated"] = True
    if len(stderr) > max_output_chars:
        stderr_path = output_dir / f"stderr-{time.time_ns()}.log"
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
        output["stderr_path"] = str(stderr_path.relative_to(state.workspace))
        output["stderr_truncated"] = True
    output["stdout"] = stdout[:max_output_chars]
    output["stderr"] = stderr[:max_output_chars]
    return output


def _run_background(
    state: RuntimeState,
    command: str,
    env: dict[str, str],
    approval: dict[str, Any] | None,
) -> dict[str, Any]:
    #新增：用 Popen 启动后台进程并将输出写入文件；返回成功只表示启动成功，未等待结束，也不设置运行超时。
    output_dir = state.workspace / ".Agent01" / "background"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.time_ns()
    stdout_path = output_dir / f"job-{stamp}.out"
    stderr_path = output_dir / f"job-{stamp}.err"
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    try:
        process = subprocess.Popen(
            command,
            cwd=state.workspace,
            shell=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=(os.name != "nt"),
            #Windows 后台执行不弹出控制台窗口。
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    return {
        "ok": True,
        "timed_out": False,
        "command": command,
        "background": True,
        "pid": process.pid,
        "exit_code": None,
        "stdout": "",
        "stderr": "",
        "stdout_path": str(stdout_path.relative_to(state.workspace)),
        "stderr_path": str(stderr_path.relative_to(state.workspace)),
        "duration_ms": 0,
        **(approval or {}),
    }
