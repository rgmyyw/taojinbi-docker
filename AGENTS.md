# AGENTS.md - taojinbi-docker

## 快速开始

1. 安装 ADB 并添加到 PATH
2. `pip install -r requirements.txt`
3. 通过 USB 连接 Android 设备
4. 通过统一入口运行: `python main.py 任务名` (例如 `python main.py 淘金币`; 无参数或 `--list` 列出全部任务)

## 环境

- **ADB 必须已安装** 并可从 PATH 访问。脚本使用 `adb devices` 来检测设备。
- **通过 USB 连接一个 Android 设备**。脚本通过 `adb` 来检测连接的设备。
- **需要 Python 3.8+**。关键依赖: `uiautomator2`, `uiautodev`, `opencv-python`, `ddddocr`, `easyocr`。

## 目录结构

- 任务脚本按类目归档在 `tasks/` 下: `taobao/`(淘宝/天猫常驻)、`events/`(双11、618 等大促)、`alipay/`(支付宝)、`xianyu/`(闲鱼); 调试工具在 `tools/`
- `main.py` 是统一入口: 自动切换到项目根目录(保证 `./img/*.png` 模板路径可用)并注入 import 路径(解析顶层 `utils` 与跨类目引用), 任务脚本内容不感知自身位置
- `tasks/taobao/淘宝多任务执行.py` 按顺序批量执行多个任务, 自带同样的环境自举
- `dashboard/` 是 Web 仪表盘(纯标准库): 设备管理(自动重连/上下线检测/电量与系统版本)、批量任务(多任务x多设备, 每台设备顺序执行、设备间并行)、任务历史持久化(7天, 按设备统计今日执行与异常中断)、每任务日志文件与事件流; 启动 `python dashboard/app.py`, Docker 部署时是容器主进程(11000 端口)
- 新增大促任务时放入对应类目目录即可, 无需修改入口

## 运行脚本

每个脚本遵循相同的模式:

```python
import uiautomator2 as u2
from utils import <helpers>

selected_device = select_device()  # 如果有多台设备则提示选择
d = u2.connect(selected_device)
start_app(d, <package_name>, init=True)
# ... 进行自动化操作
```

- `select_device()`: 如果只有一台设备则自动选择。如果有多台，会提示让你按索引选择。
- `start_app(d, package, init=True)`: 先停止应用，然后启动它。支持多用户设备——首次运行时会询问选择用户，选择会被缓存。
- 许多脚本会使用 `task_loop(d, back_func)` 进行主要任务循环，或自行实现循环。

## `utils.py` 中的关键工具

- `get_current_app(d)` — 通过 `dumpsys window` 返回 `(package_name, activity_name)`
- `check_chars_exist(text, chars)` — 检查文本中是否包含任意字符（用于任务分类）
- `find_button(image, btn_path, region)` — OpenCV 模板匹配用于图片查找
- `find_text_by_easyocr(screenshot, target_text)` — 基于 EasyOCR 的文本查找
- `task_loop(d, back_func)` — 许多脚本使用的主要迭代循环; 处理验证弹窗、按钮点击和返回导航
- `check_verify(d)` — 处理 "验证码拦截" (captcha 拦截)
- `check_popup(d)` — 关闭淘宝上的底部弹出面板
- `start_watcher(d)` — 为已知的对话框图像设置监视上下文

## 常见模式

- **SSL 验证被禁用** — `utils.py` 重写 `ssl._create_default_https_context` 以跳过 SSL 检查（获取某些图片请求时需要）。
- **OCR 阅读器** 是模块级单例: `easyocr_reader = easyocr.Reader(['ch_sim', 'en'], gpu=True)`。调用时请勿重新初始化。
- `check_can_open(d)` — 点击出现于首次启动时的 "允许/始终允许" 系统对话框。
- 应用的包/activity 映射位于 `utils.py` 的 `APP_START_CONFIG` 字典中 (TB_APP, ALIPAY_APP, FISH_APP, TMALL_APP)。
- `utils.py` 中的 `other_app` 列表 — 应该被视为 "主应用之外" 的任务名称 (例如 "蚂蚁森林", "农场" 等)。

## 提示与坑

- 如果 Android UI 状态改变（OCR/图片匹配对敏感），脚本可能会失败。请耐心运行；异常常被捕获且循环会继续。
- 如果看到 "未检测到任何连接的安卓设备", 请确保设备上的 USB 调试已启用，且 `adb devices` 返回你的设备。
- `start_app` 的首次运行会在手机有多个用户时询问选择用户。选择会通过 `_selected_user` 全局变量被缓存。
- `start_app` 中的 `init=True` 标志会强制完全重启 (stop + use_monkey)，在运行之间清理状态很有用。
- `task scripts` 中的 `back_to_task()` 处理在完成子任务后返回主任务屏幕的操作，包括关闭支付宝迷你程序和 "限时下单任务" 弹窗。

## Docker 部署 (PVE)

该项目在 Proxmox VE 中通过 Docker 运行，典型配置如下：

### 容器启动

```bash
# 示例：使用 host 网络模式以直接访问物理 ADB 设备
docker run -d \
  --name coin11-tb \
  --network host \
  -v /path/to/scripts:/scripts \
  -v /dev/bus/usb:/dev/bus/usb \
  -e DISPLAY=${DISPLAY} \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  yanghai/coin11-tb:latest
```

### 关键配置

- `--network host`: 容器共享宿主机网络，确保 `adb devices` 可以检测到物理设备
- `/dev/bus/usb` 卷挂载: 让容器内的 Python 可以访问宿主机的 USB 设备节点，uiautomator2 通过 ADB 与 Android 通信
- 脚本目录挂载: `-v /path/to/scripts:/scripts`，将本地脚本挂载进容器
- 如需 GUI 截图支持，挂载 X11 套接字

### PVE 具体步骤

1. 在 PVE 创建新容器，选择 Docker 选项
2. 启用 "USB 设备 passthrough"，将 Android 设备通过 USB 连接到 PVE 宿主机
3. 在容器配置中添加设备: `/dev/bus/usb` 及其归属组
4. 设置网络为 `host` 模式
5. 挂载脚本目录和必要的系统路径
6. 启动容器后主进程即仪表盘, 浏览器打开 `http://<宿主机IP>:11000` 管理设备与任务; 命令行仍可用 `docker compose exec coin11-tb python /scripts/main.py 淘金币`

### 普通电脑 (非 PVE) 部署

若不使用 PVE，同样可直接在 Linux/macOS 宿主机上运行 Docker，唯一区别就是无需处理 USB passthrough 复杂性，直接使用 `-v /dev/bus/usb:/dev/bus/usb` 即可访问连接的 Android 设备。

### 常见问题

- **设备未被识别**: 检查 `/dev/bus/usb` 权限，确保容器运行用户有 `usb` 组权限，或在容器内 `chmod 666 /dev/bus/usb/*`
- **adb 指令无反应**: 确保宿主机的 ADB 版本兼容，且未被其他进程占用
- **权限不足**: 将容器用户加入 `adb`/`usb` 组，或在 Docker run 中使用 `--privileged` (不推荐，仅用调试)

## 无线 ADB 连接 (Wireless ADB)

仅在以下情况下使用本节内容：希望通过网络而非 USB 连接安卓设备。

### 设置流程

1. **首次有线启用**：
   - 使用 USB 连接设备，在容器或宿主机执行：
     ```bash
     adb usb              # 确保 USB 模式
     adb tcpip 5555       # 设置 TCP 端口为 5555
     ```
   - 执行 `adb connect <设备IP>:5555` 进行无线连接

2. **docker 启动配置**：
   - 删除 `/dev/bus/usb` 卷挂载（docker-compose.yml 已更新）
   - 确保容器网络能访问设备 IP（使用 host network 或自定义网络）
   - 启动容器后，如需回 USB 模式可重新执行 `adb usb`

3. **脚本内无线连接**（如需自动连接）
   ```python
   import subprocess
   subprocess.run(["adb", "connect", "192.168.1.100:5555"], capture_output=True)
   # 随后的 u2.connect() 将检测到无线设备
   ```

### 注意事项

- 无线连接相比 USB 可能有略微延迟，OCR 识别速度可能受网络影响
- 需要安卓设备支持无线调试（大多数现代安卓版本支持）
- 首次启用必须有线连接，随后可自由拔除 USB
- 如果设备重启，可能需要重新执行 `adb tcpip 5555` 和 `adb connect`

## 多设备 (多台手机)

`adb devices` 列出的每台设备(USB serial 或无线 `ip:5555`)都可以被脚本使用, `select_device()` 的行为:

- **1 台**: 自动选择, 无交互
- **多台且未设置 TASK_DEVICE**: 列出品牌/型号/系统版本, 输入序号选择
- **设置了 TASK_DEVICE 环境变量**: 直接使用指定设备, 跳过交互(无线地址掉线时会自动 `adb connect` 重试一次)

### 连接多台无线设备

```bash
# 每台设备首次需有线执行 adb tcpip 5555, 之后:
adb connect 192.168.1.100:5555
adb connect 192.168.1.101:5555
adb devices   # 应列出全部设备
```

### 并行控制多台

```bash
# 本机: 两个进程各控一台
TASK_DEVICE=192.168.1.100:5555 python main.py 淘金币 &
TASK_DEVICE=192.168.1.101:5555 python main.py 闲鱼扔骰子 &

# Docker 容器内
docker compose exec -e TASK_DEVICE=192.168.1.100:5555 coin11-tb python /scripts/main.py 淘金币
```

`TASK_DEVICE` 会随环境传递给 `淘宝多任务执行.py` 的子进程。注意: **同一台设备不要同时跑多个任务**(UI 操作会互相干扰), 并行是"每台设备一个进程"。