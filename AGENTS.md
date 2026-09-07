# AGENTS.md - taojinbi-docker (mav-engine 分支)

本分支以 taojinbi-Mav 引擎为淘金币唯一实现, 原多任务脚本(支付宝/闲鱼/大促等)已全部移除。

## 快速开始

1. 安装 ADB 并添加到 PATH
2. 安装 Python >= 3.11(完整标准库, 含 lzma)
3. `pip install -r requirements.txt`
4. 通过 USB 连接已装淘宝的 Android 设备
5. 运行: `python main.py 淘金币`(无参数或 `--list` 列出任务); 仪表盘: `python dashboard/app.py`

## 目录结构

- `main.py` 统一入口: 自动切到项目根目录并注入 import 路径; 任务目录实时扫描 `tasks/`、`tools/`
- `tasks/taobao/淘金币任务.py` 任务入口(包装): 入场导航 -> 引擎 CLI
- `tasks/taobao/_淘金币导航.py` 前置导航: 启动淘宝, 经"领淘金币"入口或搜索到达淘金币页面; `_` 前缀不会出现在任务列表
- `engines/mav/` vendored taojinbi-Mav(Apache-2.0, 出处见 VENDORED.md): 引擎源码 + CLI + 524 个离线测试; 勿改动其内部, 升级时整体替换并跑 `python -m unittest discover -s tests -t .`
- `dashboard/` Web 仪表盘(纯标准库): 设备管理(自动重连/上下线/电量)、批量任务(多设备并行, 失败自动重试)、任务历史持久化(7 天, 今日统计/异常中断)、日志; Docker 部署时是容器主进程(11000 端口)

## 淘金币执行链

```
main.py / 仪表盘
  └─ tasks/taobao/淘金币任务.py (纯标准库包装)
       ├─ 选择解释器: MAV_PYTHON > 当前解释器 > PATH 中的 python3.11+ (探测 lzma)
       ├─ 设备: TASK_DEVICE 转 --serial; 未设且唯一在线设备时自动使用
       ├─ _淘金币导航.py: 把手机带到淘金币页面 (MAV_SKIP_NAV=1 跳过)
       └─ engines/mav/scripts/run_taojinbi.py --serial <dev> --max-tasks N
            (PYTHONPATH=engines/mav/src, 免安装)
```

- 调参环境变量: `MAV_TASK`(search/hashtag/featured_goods/immersive)、`MAV_MAX_TASKS`、`MAV_GPU=1`、`MAV_EXTRA`(透传如 `--dry-run`)
- 引擎退出码: 3 = `startup_failed`(未找到任务列表锚点; 常见原因是设备未装淘宝或不在淘金币页面), 130 = 取消
- 引擎 JSONL 事件日志与任务日志都在 `logs/`; `startup_failed` 的具体原因看 JSONL 里的 `page_diagnostic` 事件

## 环境要点

- ADB 必须可用; 设备需开启 USB 调试并已装淘宝
- 引擎要求 Python >= 3.11 且 `_lzma` 可导入(自编译解释器常缺); 包装脚本会自动探测并跳过不合格解释器
- easyocr 首次运行会下载 OCR 模型(约 100MB, 缓存在 `~/.EasyOCR`)
- Docker 镜像基于 `python:3.11-slim`, 已内置依赖与引擎

## 提示与坑

- 引擎为受控设计: 不从任意页面导航、只执行白名单浏览任务(搜索/话题/商品/沉浸式), 高风险任务(视频/下单/助力等)会被 `UNSAFE_ACTION_MARKERS` 过滤
- 手机若停留在其他 App/通知栏, 入场导航可能失败重试 3 次后放弃, 由引擎继续尝试并给出诊断
- 同一台设备不要同时跑多个任务; 并行是"每台设备一个进程"(仪表盘已按设备排队保证)
- 仪表盘无鉴权, 仅限内网
