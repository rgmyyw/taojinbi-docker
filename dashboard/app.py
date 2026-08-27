#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设备与任务管理仪表盘 (仅标准库, 无额外依赖)。

启动:  python dashboard/app.py    (默认 0.0.0.0:11000, 环境变量 DASHBOARD_PORT 可覆盖)

功能:
  - 设备管理: 维护一组 ADB 地址, 后台线程轮询 adb devices, 自动重连掉线的无线设备,
    采集品牌/型号/系统版本/电量, 记录上线/下线事件
  - 任务执行: 单发或批量(多任务 x 多设备, 每台设备按勾选顺序执行, 设备之间并行),
    以子进程方式经 main.py 运行(TASK_DEVICE 固定设备), stdout/stderr 实时写入 logs/
  - 历史: 任务记录持久化到 dashboard/data/history.json(保留 7 天),
    支持按设备统计"今日执行情况"与异常中断检测(服务重启时未结束的任务标记为异常中断)
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
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

ADDRESS_RE = re.compile(r"^[A-Za-z0-9._:-]+$")  # ip:port 或 USB serial
SERVER_STARTED_AT = time.time()
ACTIVE_STATUSES = ("queued", "running")


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
    PROPS_REFRESH = 30  # 在线设备属性(电量等)刷新周期(秒)

    def __init__(self):
        self.lock = threading.Lock()
        self.configured = []
        self.state = {}  # address -> {status, brand, model, android, battery, charging, ...}
        self.events = collections.deque(maxlen=200)
        self.adb_ok = True
        self.adb_version = ""
        self.last_refresh = 0.0
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="adb")
        self._load()
        self._detect_adb()
        threading.Thread(target=self._poll_loop, daemon=True, name="device-poll").start()

    # ---- 持久化 / 启动检测 ----

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

    def _detect_adb(self):
        try:
            out = subprocess.run(
                ["adb", "version"], capture_output=True, text=True, timeout=6
            ).stdout
            m = re.search(r"version ([\d.]+)", out)
            self.adb_version = m.group(1) if m else out.splitlines()[0][:40]
        except Exception:
            self.adb_version = ""

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
        """采集品牌/型号/系统版本/电量(在线设备)。"""
        def shell(cmd):
            try:
                return subprocess.run(
                    ["adb", "-s", address, "shell", cmd],
                    capture_output=True, text=True, timeout=6,
                ).stdout
            except Exception:
                return ""

        lines = [l.strip() for l in
                 shell("getprop ro.product.brand; getprop ro.product.model; getprop ro.build.version.release").splitlines()
                 if l.strip()]
        brand = lines[0] if len(lines) > 0 else ""
        model = lines[1] if len(lines) > 1 else ""
        android = lines[2] if len(lines) > 2 else ""
        bat = shell("dumpsys battery")
        m = re.search(r"^\s*level:\s*(\d+)", bat, re.M)
        level = int(m.group(1)) if m else None
        charging = bool(re.search(r"^\s*(?:USB|AC) powered:\s*true", bat, re.M))
        with self.lock:
            rec = self.state.get(address)
            if rec and rec.get("status") == "online":
                rec.update(brand=brand, model=model, android=android,
                           battery=level, charging=charging, props_at=time.time())

    def refresh(self):
        current = adb_devices()
        self.adb_ok = True
        missing = [a for a in self.configured if ":" in a and a not in current]
        if missing:  # 掉线的无线设备自动重连一次后再取状态
            list(self._executor.map(self._try_connect, missing))
            current = adb_devices()
        now = time.time()
        self.last_refresh = now
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
                        if not rec.get("brand") or now - rec.get("props_at", 0) > self.PROPS_REFRESH:
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
    """任务队列与执行: 每台设备一个工作线程顺序消费队列, 设备之间天然并行。

    状态机: queued -> running -> finished/failed/stopped;
            queued -> cancelled(未开始即取消);
            running -> interrupted(服务重启导致的异常中断, 加载历史时标记)。
    """

    KEEP_DAYS = 7
    LIST_CAP = 100

    def __init__(self, devices):
        self.lock = threading.RLock()
        self.devices = devices
        self.tasks = {}   # id -> 记录
        self.order = []   # 新在前(按入队/启动时间)
        self.queues = {}  # device -> [task_id, ...] FIFO
        self._workers = {}  # device -> Thread
        self._persist_lock = threading.Lock()  # 序列化历史文件写入, 避免并发损坏
        self._load_history()

    # ---- 历史持久化 ----

    @staticmethod
    def _public(rec):
        return {k: v for k, v in rec.items() if not k.startswith("_")}

    def _persist(self):
        with self._persist_lock:
            cutoff = time.time() - self.KEEP_DAYS * 86400
            with self.lock:
                recs = [self._public(r) for r in self.tasks.values()
                        if (r.get("started_at") or r.get("queued_at") or 0) >= cutoff]
            try:
                os.makedirs(DATA_DIR, exist_ok=True)
                tmp = f"{HISTORY_FILE}.{uuid.uuid4().hex[:6]}.tmp"  # 唯一临时文件, 防并发交错
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(recs, f, ensure_ascii=False)
                os.replace(tmp, HISTORY_FILE)
            except OSError:
                pass

    def _load_history(self):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                recs = json.load(f)
        except (OSError, ValueError):
            return
        cutoff = time.time() - self.KEEP_DAYS * 86400
        interrupted = 0
        for rec in recs:
            ts = rec.get("started_at") or rec.get("queued_at") or 0
            if ts < cutoff:
                continue
            if rec.get("status") in ACTIVE_STATUSES:  # 上次服务退出时任务未正常结束
                rec["status"] = "interrupted"
                rec["returncode"] = None
                interrupted += 1
            self.tasks[rec["id"]] = rec
        self.order = sorted(self.tasks, key=lambda i: -(self.tasks[i].get("started_at") or self.tasks[i].get("queued_at") or 0))
        if interrupted:
            self.devices._event(f"检测到上次异常中断的任务 {interrupted} 个")

    # ---- 对外操作 ----

    def start(self, task_path, device=None):
        catalog = [disp for disp, _ in main.collect_scripts()]
        if task_path not in catalog:
            return None, "未知任务, 请从列表中选择"
        if device:
            ok, err = self._check_device(device)
            if not ok:
                return None, err
        rec = self._new_record(task_path, device)
        with self.lock:
            self.tasks[rec["id"]] = rec
            self.order.insert(0, rec["id"])
        self._persist()
        threading.Thread(target=self._run_record, args=(rec,), daemon=True,
                         name=f"task-{rec['id']}").start()
        return rec, None

    def start_batch(self, task_paths, devices):
        catalog = [disp for disp, _ in main.collect_scripts()]
        bad = [t for t in task_paths if t not in catalog]
        if bad:
            return 0, f"未知任务: {bad[0]}"
        if not task_paths:
            return 0, "未选择任务"
        if not devices:
            return 0, "未选择设备"
        for device in devices:
            ok, err = self._check_device(device)
            if not ok:
                return 0, err
        created = 0
        for device in devices:
            for task_path in task_paths:
                rec = self._new_record(task_path, device)
                with self.lock:
                    self.tasks[rec["id"]] = rec
                    self.order.insert(0, rec["id"])
                    self.queues.setdefault(device, []).append(rec["id"])
                created += 1
        self._persist()
        names = [os.path.basename(t) for t in task_paths]
        self.devices._event(f"批量入队 {created} 个任务 ({len(names)}项 x {len(devices)}台), 设备间并行")
        for device in devices:
            self._ensure_worker(device)
        return created, None

    def _check_device(self, device):
        devs, _ = self.devices.snapshot()
        if not any(d.get("address") == device and d.get("status") == "online" for d in devs):
            return False, f"设备 {device} 不在线"
        return True, None

    def _new_record(self, task_path, device):
        return {
            "id": time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6],
            "task": task_path,
            "device": device or "自动",
            "status": "queued",
            "queued_at": time.time(),
            "started_at": None, "ended_at": None,
            "pid": None, "returncode": None,
            "log": None, "lines": 0, "stop_requested": False,
        }

    def _ensure_worker(self, device):
        with self.lock:
            t = self._workers.get(device)
            if t and t.is_alive():
                return
            t = threading.Thread(target=self._device_worker, args=(device,),
                                 daemon=True, name=f"worker-{device}")
            self._workers[device] = t
            t.start()

    def _device_worker(self, device):
        while True:
            with self.lock:
                q = self.queues.get(device, [])
                while q and self.tasks.get(q[0], {}).get("status") == "cancelled":
                    q.pop(0)  # 跳过已取消的排队项
                if not q:
                    self.queues.pop(device, None)
                    self._workers.pop(device, None)
                    return
                rec = self.tasks[q[0]]
                q.pop(0)
            self._run_record(rec)

    def _run_record(self, rec):
        task_path, device = rec["task"], rec["device"]
        safe = re.sub(r"[^0-9A-Za-z_.\u4e00-\u9fff]+", "_",
                      f"{os.path.splitext(os.path.basename(task_path))[0]}_{device}")
        log_path = os.path.join(LOG_DIR, f"{rec['id']}_{safe}.log")
        env = os.environ.copy()
        if device != "自动":
            env["TASK_DEVICE"] = device
        env["PYTHONUNBUFFERED"] = "1"  # 日志实时可见
        try:
            proc = subprocess.Popen(
                [sys.executable, "main.py", task_path],
                cwd=BASE_DIR, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                start_new_session=True,  # 独立进程组, 便于整组停止
            )
        except OSError as e:
            with self.lock:
                rec.update(status="failed", returncode=-1, started_at=time.time(),
                           ended_at=time.time(), error=str(e))
            self._persist()
            self.devices._event(f"任务启动失败 {os.path.basename(task_path)}: {e}")
            return
        with self.lock:
            rec.update(status="running", pid=proc.pid,
                       started_at=time.time(), log=log_path, _proc=proc)
        self.devices._event(f"任务开始 {os.path.basename(task_path)} @ {device}")
        self._persist()
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as fh:
                for line in proc.stdout:
                    fh.write(line)
                    fh.flush()
                    with self.lock:
                        rec["lines"] += 1
        except Exception as e:
            try:
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(f"\n[日志写入异常] {e}\n")
            except OSError:
                pass
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
        status_text = {"finished": "完成", "failed": f"失败(rc={rc})",
                       "stopped": "已停止"}[rec["status"]]
        self.devices._event(f"任务结束 {os.path.basename(task_path)} @ {device}: {status_text}")
        self._persist()

    def stop(self, task_id):
        """运行中 -> 终止进程组; 排队中 -> 取消。"""
        with self.lock:
            rec = self.tasks.get(task_id)
            if not rec:
                return False, "任务不存在"
            if rec["status"] == "queued":
                rec["status"] = "cancelled"
                self._persist()
                self.devices._event(f"取消排队任务 {os.path.basename(rec['task'])} @ {rec['device']}")
                return True, None
            if rec["status"] != "running":
                return False, "任务已结束"
            rec["stop_requested"] = True
            proc = rec.get("_proc")
        if proc:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                else:
                    proc.terminate()
            except (ProcessLookupError, OSError):
                pass  # 恰好已退出, 由 _run_record 收尾
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
            if rec and rec["status"] in ACTIVE_STATUSES:
                self.stop(tid)

    def running_count(self, device):
        with self.lock:
            return sum(1 for r in self.tasks.values()
                       if r["device"] == device and r["status"] == "running")

    def list(self):
        with self.lock:
            out = [self._public(self.tasks[tid]) for tid in self.order[:self.LIST_CAP]]
            return out

    def get(self, task_id):
        with self.lock:
            rec = self.tasks.get(task_id)
            return self._public(rec) if rec else None

    def today_summary(self):
        """按设备统计今日执行情况: {device: {total, finished, failed, ...}}"""
        today = time.strftime("%Y-%m-%d")
        out = {}
        with self.lock:
            for r in self.tasks.values():
                ts = r.get("started_at") or r.get("queued_at")
                if not ts or time.strftime("%Y-%m-%d", time.localtime(ts)) != today:
                    continue
                dev = r["device"]
                d = out.setdefault(dev, {"total": 0, "finished": 0, "failed": 0,
                                         "interrupted": 0, "stopped": 0,
                                         "running": 0, "queued": 0, "tasks": {}})
                d["total"] += 1
                if r["status"] in d:
                    d[r["status"]] += 1
                name = os.path.splitext(os.path.basename(r["task"]))[0]
                d["tasks"].setdefault(name, []).append(r["status"])
        return out

    def read_log(self, task_id, offset):
        rec = self.get(task_id)
        if not rec:
            return None
        if not rec.get("log"):
            return {"lines": [], "next": 0, "status": rec["status"]}
        try:
            with open(rec["log"], encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        return {"lines": lines[offset:], "next": len(lines), "status": rec["status"]}


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
        if url.path in ("/", "/index.html"):
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
                "server": {
                    "started_at": SERVER_STARTED_AT,
                    "now": time.time(),
                    "port": int(os.environ.get("DASHBOARD_PORT", "11000")),
                    "python": sys.version.split()[0],
                    "adb_ok": devices_mgr.adb_ok,
                    "adb_version": devices_mgr.adb_version or None,
                    "poll_interval": DeviceManager.POLL_INTERVAL,
                    "last_refresh": devices_mgr.last_refresh,
                },
                "devices": devices,
                "events": events,
                "tasks": tasks_mgr.list(),
                "today": tasks_mgr.today_summary(),
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
            self._json(result if result is not None else {"error": "任务不存在"},
                       200 if result else 404)
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
            self._json({"ok": rec is not None, **({"error": err} if err else {})},
                       200 if rec else 400)
            return
        if url.path == "/api/tasks/batch":
            tasks = body.get("tasks") or []
            devs = body.get("devices") or []
            if not isinstance(tasks, list) or not isinstance(devs, list):
                self._json({"ok": False, "error": "tasks/devices 必须为数组"}, 400)
                return
            created, err = tasks_mgr.start_batch([str(t) for t in tasks], [str(d) for d in devs])
            self._json({"ok": not err, "created": created, **({"error": err} if err else {})},
                       200 if not err else 400)
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
    port = int(os.environ.get("DASHBOARD_PORT", "11000"))
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
