#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设备与任务管理仪表盘 (仅标准库, 无额外依赖)。

启动:  python dashboard/app.py    (默认 0.0.0.0:8080, 环境变量 DASHBOARD_PORT 可覆盖)

功能:
  - 设备管理: 维护一组 ADB 地址, 后台线程轮询 adb devices, 自动重连掉线的无线设备,
    记录上线/下线事件与品牌型号
  - 任务执行: 以子进程方式经 main.py 运行 tasks/ 下的脚本(TASK_DEVICE 固定设备),
    stdout/stderr 实时写入 logs/ 下每任务一个日志文件
  - 日志系统: API 按行增量拉取任务日志; 设备/任务事件统一留存最近 200 条

页面: dashboard/static/index.html (无构建, 浏览器轮询刷新)。
注意: 服务无鉴权, 仅适用于内网/家庭环境。
"""

import collections
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(BASE_DIR)  # 任务子进程与日志目录均以项目根为基准
sys.path.insert(0, BASE_DIR)
import main  # 复用 collect_scripts() 获取任务清单

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LOG_DIR = os.path.join(BASE_DIR, "logs")
DEVICES_FILE = os.path.join(DATA_DIR, "devices.json")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

ADDRESS_RE = re.compile(r"^[A-Za-z0-9._:-]+$")  # ip:port 或 USB serial


def adb_devices():
    """返回 {serial: state}, state 为 device/offline/unauthorized。"""
    try:
        out = subprocess.run(
            ["adb", "devices"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return {}
    result = {}
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2:
            result[parts[0]] = parts[1]
    return result


class DeviceManager:
    """设备状态与自动重连。configured 为用户添加的地址(持久化), 其余为临时发现。"""

    POLL_INTERVAL = 5
    CONNECT_TIMEOUT = 8

    def __init__(self):
        self.lock = threading.Lock()
        self.configured = []
        self.state = {}  # address -> {status, brand, model, last_seen, configured, since}
        self.events = collections.deque(maxlen=200)
        self.adb_ok = True
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="adb")
        self._load()
        threading.Thread(target=self._poll_loop, daemon=True, name="device-poll").start()

    # ---- 持久化 ----

    def _load(self):
        try:
            with open(DEVICES_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                self.configured = [a for a in data if isinstance(a, str)]
        except (OSError, ValueError):
            self.configured = []

    def _save(self):
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DEVICES_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.configured, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DEVICES_FILE)

    # ---- 对外操作 ----

    def add(self, address):
        address = address.strip()
        if not ADDRESS_RE.match(address):
            return False, "地址格式不正确, 应为 ip:port 或 USB serial"
        with self.lock:
            if address in self.configured:
                return False, "该设备已在列表中"
            self.configured.append(address)
            self._save()
        self._event(f"添加设备 {address}, 开始尝试连接")
        self._executor.submit(self.refresh)
        return True, None

    def remove(self, address):
        with self.lock:
            if address not in self.configured:
                return False, "该设备不在列表中"
            self.configured.remove(address)
            self._save()
            self.state.pop(address, None)
        self._event(f"移除设备 {address}")
        self._executor.submit(self.refresh)
        return True, None

    def snapshot(self):
        with self.lock:
            devices = sorted(
                self.state.values(),
                key=lambda v: (not v.get("configured"), v.get("address", "")),
            )
            return [dict(v) for v in devices], list(self.events)

    # ---- 内部 ----

    def _event(self, message):
        self.events.appendleft({"time": time.time(), "message": message})

    def _poll_loop(self):
        while not self._stop.wait(self.POLL_INTERVAL):
            try:
                self.refresh()
            except Exception as e:  # 轮询线程不允许退出
                self._event(f"设备轮询异常: {e}")

    def _try_connect(self, address):
        try:
            subprocess.run(
                ["adb", "connect", address],
                capture_output=True, text=True, timeout=self.CONNECT_TIMEOUT,
            )
        except Exception:
            pass

    def _fetch_props(self, address):
        def prop(name):
            try:
                return subprocess.run(
                    ["adb", "-s", address, "shell", "getprop", name],
                    capture_output=True, text=True, timeout=6,
                ).stdout.strip()
            except Exception:
                return ""
        brand, model = prop("ro.product.brand"), prop("ro.product.model")
        with self.lock:
            rec = self.state.get(address)
            if rec and rec.get("status") == "online":
                rec["brand"], rec["model"] = brand, model

    def refresh(self):
        current = adb_devices()
        self.adb_ok = True
        missing = [a for a in self.configured if ":" in a and a not in current]
        if missing:  # 掉线的无线设备自动重连一次后再取状态
            list(self._executor.map(self._try_connect, missing))
            current = adb_devices()
        now = time.time()
        need_props = []
        with self.lock:
            serials = set(current) | set(self.configured) | set(self.state)
            for s in serials:
                rec = dict(self.state.get(s, {}))
                prev_status = rec.get("status", "未知")
                if s in current:
                    state = current[s]
                    status = "online" if state == "device" else state
                    if status == "online":
                        rec["last_seen"] = now
                        if not rec.get("brand"):
                            need_props.append(s)
                else:
                    status = "offline"
                if status != prev_status:
                    text = "上线" if status == "online" else f"下线({status})" if s in current else "下线"
                    self._event(f"设备 {s} {text}")
                    rec["since"] = now
                rec.update(address=s, status=status, configured=s in self.configured)
                self.state[s] = rec
        for s in need_props:
            self._executor.submit(self._fetch_props, s)


class TaskManager:
    """以子进程方式执行任务并捕获日志。"""

    MAX_HISTORY = 50

    def __init__(self, devices):
        self.lock = threading.Lock()
        self.devices = devices
        self.tasks = {}   # id -> 记录
        self.order = []   # 按 started_at 新在前

    def start(self, task_path, device=None):
        catalog = [disp for disp, _ in main.collect_scripts()]
        if task_path not in catalog:
            return None, "未知任务, 请从列表中选择"
        if device:
            devices, _ = self.devices.snapshot()
            if not any(d.get("address") == device and d.get("status") == "online" for d in devices):
                return None, f"设备 {device} 不在线"

        task_id = time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]
        safe = re.sub(r"[^0-9A-Za-z_.\u4e00-\u9fff]+", "_",
                      f"{os.path.splitext(os.path.basename(task_path))[0]}_{device or 'auto'}")
        log_path = os.path.join(LOG_DIR, f"{task_id}_{safe}.log")
        os.makedirs(LOG_DIR, exist_ok=True)

        env = os.environ.copy()
        if device:
            env["TASK_DEVICE"] = device
        env["PYTHONUNBUFFERED"] = "1"  # 日志实时可见
        proc = subprocess.Popen(
            [sys.executable, "main.py", task_path],
            cwd=BASE_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            start_new_session=True,  # 独立进程组, 便于整组停止
        )
        rec = {
            "id": task_id, "task": task_path, "device": device or "自动",
            "status": "running", "pid": proc.pid,
            "started_at": time.time(), "ended_at": None,
            "returncode": None, "log": log_path, "lines": 0,
            "stop_requested": False, "_proc": proc,
        }
        with self.lock:
            self.tasks[task_id] = rec
            self.order.insert(0, task_id)
        self.devices._event(f"任务开始 {os.path.basename(task_path)} @ {rec['device']}")
        threading.Thread(target=self._pump, args=(rec,), daemon=True,
                         name=f"task-{task_id}").start()
        return rec, None

    def _pump(self, rec):
        proc = rec["_proc"]
        try:
            with open(rec["log"], "w", encoding="utf-8") as fh:
                for line in proc.stdout:
                    fh.write(line)
                    fh.flush()
                    with self.lock:
                        rec["lines"] += 1
        except Exception as e:
            with open(rec["log"], "a", encoding="utf-8") as fh:
                fh.write(f"\n[日志写入异常] {e}\n")
        rc = proc.wait()
        with self.lock:
            rec["returncode"] = rc
            rec["ended_at"] = time.time()
            if rec["stop_requested"]:
                rec["status"] = "stopped"
            elif rc == 0:
                rec["status"] = "finished"
            else:
                rec["status"] = "failed"
            self._trim()
        status_text = {"finished": "完成", "failed": f"失败(rc={rc})", "stopped": "已停止"}[rec["status"]]
        self.devices._event(f"任务结束 {os.path.basename(rec['task'])} @ {rec['device']}: {status_text}")

    def _trim(self):
        finished = [tid for tid in self.order
                    if self.tasks[tid]["status"] != "running"]
        for tid in finished[self.MAX_HISTORY:]:
            self.tasks.pop(tid, None)
            self.order.remove(tid)

    def stop(self, task_id):
        with self.lock:
            rec = self.tasks.get(task_id)
            if not rec:
                return False, "任务不存在"
            if rec["status"] != "running":
                return False, "任务已结束"
            rec["stop_requested"] = True
            proc = rec["_proc"]
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            else:
                proc.terminate()
        except (ProcessLookupError, OSError):
            pass  # 恰好已退出, 由 _pump 收尾
        threading.Timer(5, self._force_kill, args=(proc,)).start()
        return True, None

    @staticmethod
    def _force_kill(proc):
        if proc.poll() is None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                else:
                    proc.kill()
            except (ProcessLookupError, OSError):
                pass

    def stop_all(self):
        for tid in list(self.order):
            rec = self.tasks.get(tid)
            if rec and rec["status"] == "running":
                self.stop(tid)

    def list(self):
        with self.lock:
            out = []
            for tid in self.order:
                rec = self.tasks[tid]
                out.append({k: v for k, v in rec.items() if not k.startswith("_")})
            return out

    def get(self, task_id):
        with self.lock:
            rec = self.tasks.get(task_id)
            return dict(rec) if rec else None

    def read_log(self, task_id, offset):
        rec = self.get(task_id)
        if not rec:
            return None
        try:
            with open(rec["log"], encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        return {
            "lines": lines[offset:],
            "next": len(lines),
            "status": rec["status"],
        }


devices_mgr = DeviceManager()
tasks_mgr = TaskManager(devices_mgr)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # 轮询频繁, 关闭逐请求日志
        pass

    # ---- 响应工具 ----

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    # ---- 路由 ----

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/" or url.path == "/index.html":
            try:
                with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                    body = f.read()
            except OSError:
                self._json({"error": "index.html 缺失"}, 500)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == "/api/state":
            devices, events = devices_mgr.snapshot()
            self._json({
                "adb_ok": devices_mgr.adb_ok,
                "devices": devices,
                "events": events,
                "tasks": tasks_mgr.list(),
                "catalog": [disp for disp, _ in main.collect_scripts()],
            })
            return
        if url.path == "/api/log":
            qs = parse_qs(url.query)
            task_id = (qs.get("id") or [""])[0]
            try:
                offset = int((qs.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            result = tasks_mgr.read_log(task_id, offset)
            self._json(result if result is not None else {"error": "任务不存在"}, 200 if result else 404)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        body = self._body()
        if body is None:
            self._json({"error": "请求体不是合法 JSON"}, 400)
            return
        if url.path == "/api/devices":
            address = str(body.get("address", ""))
            ok, err = devices_mgr.add(address)
            self._json({"ok": ok, **({"error": err} if err else {})}, 200 if ok else 400)
            return
        if url.path == "/api/tasks":
            rec, err = tasks_mgr.start(str(body.get("task", "")), body.get("device") or None)
            self._json({"ok": rec is not None, **({"error": err} if err else {})}, 200 if rec else 400)
            return
        m = re.match(r"^/api/tasks/([A-Za-z0-9-]+)/stop$", url.path)
        if m:
            ok, err = tasks_mgr.stop(m.group(1))
            self._json({"ok": ok, **({"error": err} if err else {})}, 200 if ok else 400)
            return
        self._json({"error": "not found"}, 404)

    def do_DELETE(self):
        url = urlparse(self.path)
        qs = parse_qs(url.query)
        if url.path == "/api/devices":
            address = (qs.get("address") or [""])[0]
            ok, err = devices_mgr.remove(address)
            self._json({"ok": ok, **({"error": err} if err else {})}, 200 if ok else 400)
            return
        self._json({"error": "not found"}, 404)


def main_serve():
    port = int(os.environ.get("DASHBOARD_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    server.daemon_threads = True
    devices_mgr.refresh()  # 启动即取一次状态, 不等首个轮询周期

    def shutdown(signum, frame):
        tasks_mgr.stop_all()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    print(f"仪表盘已启动: http://0.0.0.0:{port} (无鉴权, 仅限内网使用)")
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main_serve()
