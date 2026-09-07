# taojinbi-docker

淘金币自动化:**以 [taojinbi-Mav](https://github.com/Linshi7766/taojinbi-Mav) 引擎为准** + Web 仪表盘(设备管理 / 任务调度 / 日志)。

任务核心源自 [czl0325/coin11-tb](https://github.com/czl0325/coin11-tb)(Apache-2.0),经 taojinbi-Mav 大幅重写——修复了原版脚本搜一搜进度不结算、平台上调浏览时长后不计数、返回过冲等问题,并带 524 个离线测试。本仓库(mav-engine 分支)只保留淘金币这一个任务场景,原多任务脚本已全部移除。

## 目录结构

```
taojinbi-docker/
├── main.py                     # 统一入口
├── requirements.txt            # 依赖(uiautomator2/opencv/easyocr)
├── dashboard/                  # Web 仪表盘: 设备管理 / 任务调度 / 日志
│   ├── app.py                  #   启动: python dashboard/app.py (11000 端口)
│   └── static/index.html
├── engines/mav/                # taojinbi-Mav 引擎 (vendored, Apache-2.0)
│   ├── src/taojinbi_mav/       #   引擎源码
│   ├── scripts/run_taojinbi.py #   引擎 CLI
│   └── tests/                  #   524 个离线测试
├── tasks/taobao/
│   ├── 淘金币任务.py            # 任务入口 = 入场导航 + 引擎调用
│   └── _淘金币导航.py           # 前置导航(把手机带到淘金币页面)
└── logs/                       # 任务日志 + 引擎 JSONL 事件日志(运行时生成)
```

## 环境要求

- **adb** 已安装并在 PATH 中
- **Python >= 3.11**(需完整标准库, 含 lzma; 部分自编译解释器缺 `_lzma` 会被自动跳过)
- `pip install -r requirements.txt`(easyocr 会带入 torch, 首次下载较大)
- 安卓设备已开启 USB 调试,**已安装淘宝**

## 快速开始

```bash
pip install -r requirements.txt
python main.py                 # 列出任务
python main.py 淘金币           # 执行淘金币任务(自动导航 + 引擎)
python dashboard/app.py        # 或用仪表盘管理: http://localhost:11000
```

## 淘金币任务 (Mav 引擎)

`tasks/taobao/淘金币任务.py` 的执行流程与调参:

- **入场导航**: 引擎是受控设计, 不从任意页面导航; 包装脚本先用 `_淘金币导航.py` 把手机带到淘金币页面(启动淘宝 → 首页"领淘金币"入口/搜索兜底), 再交给引擎(`MAV_SKIP_NAV=1` 跳过)
- **解释器**: 自动选择可用的 Python >= 3.11(`MAV_PYTHON` 显式指定最优先)
- **设备**: `TASK_DEVICE=<serial>` 指定, 未设置且恰好只有一台在线设备时自动使用
- **调参**: `MAV_TASK=search|hashtag|featured_goods|immersive`(默认扫描全部)、`MAV_MAX_TASKS=1`、`MAV_GPU=1`、`MAV_EXTRA="--dry-run"`(只读检查)等
- **日志**: 任务日志与引擎结构化 JSONL 事件日志均在 `logs/`; 引擎退出码 3 = `startup_failed`(未找到任务列表锚点, 通常是设备未装淘宝或不在淘金币页面)

## 仪表盘

Web 管理界面(纯标准库, 无额外依赖), 白色系总览 + 设备管理 + 批量任务 + 日志:

```bash
python dashboard/app.py          # 默认 11000 端口, DASHBOARD_PORT 可覆盖
```

- **状态总览**: 服务运行时长、ADB 环境、设备在线数、运行/排队任务、今日执行与异常数、轮询健康度
- **设备管理**: 添加/移除 ADB 地址, 每 5 秒轮询上下线, 掉线自动重连; 显示品牌型号、系统版本、电量
- **批量执行**: 淘金币任务 x 多台设备, 每台顺序执行、设备间并行; 失败自动重试(次数可选)
- **历史与日志**: 任务历史持久化 7 天, 按设备统计今日执行与异常中断; 每任务日志实时查看

注意: 服务无鉴权, 仅限内网使用。

## Docker 部署

容器主进程即仪表盘, 浏览器打开 `http://<宿主机IP>:11000`:

```bash
docker compose up -d --build    # host 网络, 镜像内置 Python 3.11 + 全部依赖
```

仍可命令行执行:

```bash
docker compose exec coin11-tb python /scripts/main.py 淘金币
```

## 多设备

```bash
adb connect 192.168.1.100:5555   # 每台设备首次需有线 adb tcpip 5555
adb connect 192.168.1.101:5555

TASK_DEVICE=192.168.1.100:5555 python main.py 淘金币 &
TASK_DEVICE=192.168.1.101:5555 python main.py 淘金币 &

# 或在仪表盘勾选多台设备批量执行(设备间并行)
```

同一台设备不要同时跑多个任务(UI 操作会互相干扰)。
