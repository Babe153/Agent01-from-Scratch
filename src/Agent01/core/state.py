from __future__ import annotations
#导入 annotations 让类型注解延后处理

from dataclasses import dataclass, field
#从 Python 自带的 dataclasses 模块中，导入 dataclass 和 field。
#dataclass：帮你自动生成类里一些常见代码，例如创建对象时给属性赋值。
#field：用来设置某个属性的默认值等规则。

from pathlib import Path
#从 Python 自带的 pathlib 模块中，导入处理文件和文件夹路径的 Path 类

@dataclass(frozen=True) #frozen=True 表示：对象创建后，不能再给它的属性重新赋值
class FileSnapshot:
    path: Path # 文件路径
    mtime_ns: int # 文件最后修改时间，单位是纳秒
    complete: bool # 这次是否完整读取了文件

@dataclass
class RuntimeState:
    #程序运行时的一份记录
    workspace: Path
    read_files: dict[Path, FileSnapshot] = field(default_factory=dict)

    def record_read(self, path: Path, *, complete: bool) -> None:
        #单独的 * 表示：它后面的参数必须通过名字传入。
        #state.record_read(Path("a.txt"), complete=True) 正确 
        #state.record_read(Path("a.txt"), True) 错误

        stat = path.stat()
        #path.stat() 会获取文件的元信息，例如文件大小、最后修改时间等，不会读取文件内容。结果存到变量 stat 中

        resolved = path.resolve()
        self.read_files[resolved] = FileSnapshot(
            path=resolved,
            mtime_ns=stat.st_mtime_ns,
            complete=complete,
        )

    def snapshot_for(self, path: Path) -> FileSnapshot | None:
        #根据文件路径，从字典里取出对应的快照 找到返回FileSnapshot 找不到返回None
        return self.read_files.get(path.resolve())

    def assert_workspace_path(self, path: Path) -> Path:
        #防止 agent 操作工作区之外的路径
        resolved = path.resolve()
        workspace = self.workspace.resolve()
        if resolved != workspace and workspace not in resolved.parents:
            raise ValueError(f"path must stay inside workspace: {workspace}")
        return resolved


