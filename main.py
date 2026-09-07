#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一任务入口。

用法:
    python main.py                    # 列出全部任务
    python main.py 淘金币              # 模糊匹配并执行 tasks/taobao/淘金币任务.py
    python main.py xianyu/闲鱼扔骰子.py # 以 类目/文件名 方式执行

入口会自动完成两件事, 保证脚本内容零改动即可运行:
    1. chdir 到项目根 —— 脚本内的 "./img/xxx.png" 相对路径不受启动位置影响;
    2. 将项目根与各任务类目目录加入 sys.path/PYTHONPATH ——
       使 `from utils import ...` 与跨类目引用(如 events 脚本导入 xianyu 的函数)均能解析,
       且 subprocess 子进程同样继承该规则。
仅依赖标准库, 可在没有安装第三方依赖的机器上用于 --list/--check。
"""

import os
import runpy
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCAN_TOPS = ("tasks", "tools")


def iter_task_dirs():
    """需要加入模块搜索路径的目录: 项目根 + tasks|tools 下每个类目子目录。"""
    dirs = [BASE_DIR]
    for top in SCAN_TOPS:
        top_path = os.path.join(BASE_DIR, top)
        if not os.path.isdir(top_path):
            continue
        for name in sorted(os.listdir(top_path)):
            sub = os.path.join(top_path, name)
            if os.path.isdir(sub) and not name.startswith((".", "_")):
                dirs.append(sub)
    return dirs


def bootstrap():
    """设置运行环境: 工作目录、sys.path、以及供子进程继承的 PYTHONPATH。"""
    os.chdir(BASE_DIR)
    dirs = iter_task_dirs()
    for p in dirs:
        if p not in sys.path:
            sys.path.insert(0, p)
    parts = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    missing = [d for d in dirs if d not in parts]
    if missing:
        os.environ["PYTHONPATH"] = os.pathsep.join(missing + parts)


def collect_scripts():
    """返回 [(显示路径, 绝对路径), ...]。

    兼容两种层级: tasks/<类目>/<任务>.py 与 tools/<工具>.py。
    """
    scripts = []
    for top in SCAN_TOPS:
        top_path = os.path.join(BASE_DIR, top)
        if not os.path.isdir(top_path):
            continue
        for name in sorted(os.listdir(top_path)):
            path = os.path.join(top_path, name)
            if name.endswith(".py") and not name.startswith("_"):
                scripts.append((f"{top}/{name}", path))
            elif os.path.isdir(path) and not name.startswith((".", "_")):
                for sub in sorted(os.listdir(path)):
                    if sub.endswith(".py") and not sub.startswith("_"):
                        scripts.append(
                            (f"{top}/{name}/{sub}", os.path.join(path, sub))
                        )
    return scripts


def resolve(query):
    """名称解析: 完整显示路径或文件名 -> 唯一子串。返回 (绝对路径或 None, 候选列表)。"""
    scripts = collect_scripts()
    lookup = dict(scripts)
    if query in lookup or query in {os.path.basename(p) for _, p in scripts}:
        key = query if query in lookup else next(
            d for d in lookup if os.path.basename(d) == query
        )
        return lookup[key], []
    hits = [d for d in sorted(lookup) if query in d]
    if len(hits) == 1:
        return lookup[hits[0]], hits
    return None, hits


def show_list(stream=sys.stdout):
    w = stream.write
    w("可用任务:\n")
    by_group = {}
    for disp, _ in collect_scripts():
        group, rest = disp.split("/", 1)
        by_group.setdefault(group, []).append(rest)
    for group in sorted(by_group):
        w(f"\n[{group}]\n")
        for item in sorted(by_group[group]):
            w(f"  {group}/{item}\n")
    w("\n执行示例: python main.py 淘金币\n")


def patch_task_device():
    """TASK_DEVICE 指定设备时, 让裸写的 u2.connect() 也落在指定设备上。

    不少任务脚本直接 `d = u2.connect()`, 不经 select_device()/TASK_DEVICE;
    adb 里挂着多台设备(含掉线残留)时会抛 "more than one device",
    只有一台时则可能默默控制到别的设备。这里在入口处拦截 adbutils 的
    默认设备解析: 未显式给 serial 的一律改用 TASK_DEVICE。
    """
    dev = os.environ.get("TASK_DEVICE", "").strip()
    if not dev:
        return
    try:
        import adbutils
    except ImportError:
        return
    client = adbutils.adb
    orig = client.device

    def device(serial=None):
        return orig(serial) if serial else orig(dev)

    client.device = device


def main(argv):
    if not argv or argv == ["--list"] or argv == ["-l"]:
        show_list()
        return 0
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--check":
        for q in argv[1:] or []:
            path, hits = resolve(q)
            status = path or f"(歧义/未找到: {hits})"
            print(f"{q} -> {status}")
        return 0
    if len(argv) != 1:
        print("一次只接受一个任务名, 多个任务请使用 tasks/taobao/淘宝多任务执行.py", file=sys.stderr)
        return 2

    path, hits = resolve(argv[0])
    if path is None:
        print(f"未能唯一定位 '{argv[0]}'", file=sys.stderr)
        if hits:
            print("候选:", file=sys.stderr)
            for h in hits:
                print(f"  {h}", file=sys.stderr)
        else:
            show_list(stream=sys.stderr)
        return 1

    bootstrap()
    patch_task_device()
    print(f"=== 执行: {os.path.relpath(path, BASE_DIR)} ===")
    runpy.run_path(path, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
