# -*- coding: utf-8 -*-
"""按顺序批量执行多个任务脚本。

脚本已按类目归档到 tasks/<类目>/ 下, 因此这里以 类目/文件名 形式列出,
并在文件开头完成与 main.py 一致的环境自举, 保证直接执行也可用:
    python tasks/taobao/淘宝多任务执行.py
"""

import os
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(BASE_DIR)  # 任务脚本使用 "./img/xxx.png" 相对路径, 必须以项目根为 CWD

TASK_DIRS = [BASE_DIR]
for _top in ("tasks", "tools"):
    _top_path = os.path.join(BASE_DIR, _top)
    if os.path.isdir(_top_path):
        for _name in sorted(os.listdir(_top_path)):
            _sub = os.path.join(_top_path, _name)
            # 类目目录名不应以 . 或 _ 开头(排除 __pycache__ 等)
            if os.path.isdir(_sub) and not _name.startswith((".", "_")):
                TASK_DIRS.append(_sub)
for _p in reversed(TASK_DIRS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TASKS_TO_RUN = [
    # "events/2026淘宝618活动.py",
    "taobao/淘宝成就中心签到.py",
    "xianyu/闲鱼扔骰子.py",
    "taobao/淘宝芭芭农场.py",
    "taobao/淘金币任务.py",
    "taobao/天猫摇钱树.py",
    "alipay/支付宝农场.py",
]


def run_scripts(rel_paths):
    python_executable = sys.executable
    env = os.environ.copy()
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    missing = [d for d in TASK_DIRS if d not in parts]
    if missing:  # 子进程同样需要解析 utils 及跨类目引用
        env["PYTHONPATH"] = os.pathsep.join(missing + parts)

    for rel in rel_paths:
        script = os.path.join(BASE_DIR, "tasks", rel)
        if not os.path.exists(script):
            print(f"警告: 脚本文件 '{script}' 不存在，跳过执行")
            continue
        print(f"开始执行: {rel}")
        try:
            # 执行脚本，等待完成后再执行下一个
            subprocess.run(
                [python_executable, script],
                check=True,
                stdout=sys.stdout,  # 子进程stdout直接指向当前进程的stdout
                stderr=sys.stderr,  # 子进程stderr直接指向当前进程的stderr
                text=True,
                env=env,
            )
            print(f"执行成功: {rel}")
        except subprocess.CalledProcessError as e:
            print(f"执行失败: {rel}")
            print(f"错误信息: {e.stderr}")


if __name__ == "__main__":
    run_scripts(TASKS_TO_RUN)
