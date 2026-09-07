#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""淘金币任务入口 —— 以 engines/mav (taojinbi-Mav) 为主引擎。

上游原版脚本保留为同目录的 淘金币任务-legacy.py(部分场景已跑不动, 仅供对照)。

本包装只做三件事(纯标准库, 任意 Python >= 3.8 可运行):
  1. 找到 Python >= 3.11 的解释器运行引擎(Mav 引擎要求 3.11+):
     优先级: 当前解释器 -> MAV_PYTHON 环境变量 -> PATH 中的 python3.11/3.12/3.13
  2. 设备: 仪表盘/命令行通过 TASK_DEVICE 传入 adb serial, 转为引擎的 --serial;
     未设置时若恰好只连了一台设备则自动使用, 否则报错退出
  3. 调参(均可用环境变量覆盖):
     MAV_TASK      search|hashtag|featured_goods|immersive, 留空=扫描全部已注册任务
     MAV_MAX_TASKS 本轮最多执行几个任务(默认 1)
     MAV_GPU       =1 时传 --gpu (Mac MPS/CUDA 环境)
     MAV_EXTRA     透传给引擎的其他参数
     MAV_SKIP_NAV  =1 跳过入场导航(默认会先把手机带到淘金币页面, 引擎为受控设计)
"""

import os
import shutil
import subprocess
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE_CLI = os.path.join(BASE_DIR, "engines", "mav", "scripts", "run_taojinbi.py")
ENGINE_SRC = os.path.join(BASE_DIR, "engines", "mav", "src")


def _probe_python(path):
    """候选解释器必须 >= 3.11 且能 import lzma(部分自编译解释器缺 _lzma,
    easyocr/torchvision 导入会失败, --help 探不出来)。"""
    try:
        out = subprocess.run(
            [path, "-c", "import sys, lzma; print(sys.version_info.minor)"],
            capture_output=True, text=True, timeout=10,
        )
        return out.returncode == 0 and int(out.stdout.strip()) >= 11
    except (OSError, ValueError):
        return False


def find_python():
    """Mav 引擎要求 Python >= 3.11, 本包装自身可能在旧解释器中被启动。
    优先级: MAV_PYTHON 显式指定 -> 当前解释器 -> PATH 中的 python3.11/3.12/3.13。"""
    candidates = [os.environ.get("MAV_PYTHON")]
    if sys.version_info >= (3, 11):
        candidates.append(sys.executable)
    candidates += ["python3.13", "python3.12", "python3.11"]
    for name in candidates:
        if not name:
            continue
        path = shutil.which(name) if not os.path.isabs(name) else name
        if path and _probe_python(path):
            return path
    raise SystemExit(
        "未找到可用的 Python >= 3.11 解释器(要求完整标准库, 含 lzma)。"
        "请安装 3.11+ 或通过环境变量 MAV_PYTHON 指定解释器路径。"
    )


def resolve_serial():
    serial = os.environ.get("TASK_DEVICE", "").strip()
    if serial:
        return serial
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    found = [l.split()[0] for l in result.stdout.splitlines()[1:] if l.strip().endswith("\tdevice")]
    if len(found) == 1:
        print(f"TASK_DEVICE 未设置, 自动使用唯一在线设备: {found[0]}")
        return found[0]
    raise SystemExit(
        f"无法确定设备: TASK_DEVICE 未设置, 且当前在线设备数为 {len(found)}。"
        "请在仪表盘勾选设备, 或设置 TASK_DEVICE=<serial>。"
    )


def main():
    if not os.path.isfile(ENGINE_CLI):
        raise SystemExit(f"引擎入口缺失: {ENGINE_CLI}")
    python = find_python()
    serial = resolve_serial()

    cmd = [python, ENGINE_CLI, "--serial", serial, "--max-tasks", os.environ.get("MAV_MAX_TASKS", "1")]
    task = os.environ.get("MAV_TASK", "").strip()
    if task:
        cmd += ["--task", task]
    if os.environ.get("MAV_GPU") == "1":
        cmd += ["--gpu"]
    extra = os.environ.get("MAV_EXTRA", "").strip()
    if extra:
        cmd += extra.split()

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [ENGINE_SRC] + [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p]
    )

    # 入场导航: Mav 引擎为受控设计, 需先确保手机在淘金币页面(MAV_SKIP_NAV=1 可跳过)
    navigator = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_淘金币导航.py")
    if os.environ.get("MAV_SKIP_NAV") != "1" and os.path.isfile(navigator):
        print("=== 入场导航: 前往淘金币页面 ===")
        sys.stdout.flush()
        nav_result = subprocess.run([python, navigator, serial], cwd=BASE_DIR, env=env)
        if nav_result.returncode != 0:
            print("⚠ 导航未确认成功, 仍继续交给引擎尝试")

    print(f"=== 淘金币(Mav 引擎) === 解释器: {python}")
    print(f"执行: {' '.join(cmd[1:])}")
    sys.stdout.flush()
    result = subprocess.run(cmd, cwd=BASE_DIR, env=env)
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
