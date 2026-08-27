# coin11-tb

使用 uiautomator2 自动化完成淘宝双11金币任务、淘金币、芭芭农场、闲鱼任务、支付宝打卡等日常任务。

需要安装 adb 并加入 PATH。

## 目录结构

```
taojinbi-docker/
├── main.py            # 统一入口（推荐）
├── utils.py           # 公共库：设备选择 / 启动应用 / OCR / 模板匹配
├── img/               # OpenCV 模板图片
├── dashboard/         # Web 仪表盘：设备管理 / 任务调度 / 日志
├── tasks/
│   ├── taobao/        # 淘宝 / 天猫 常驻任务（含批量执行器）
│   ├── events/        # 大促活动任务（双11 / 618）
│   ├── alipay/        # 支付宝任务
│   └── xianyu/        # 闲鱼任务
└── tools/             # 辅助调试工具
```

## 本地运行

先执行 `pip install -r requirements.txt` 安装依赖，然后通过统一入口运行：

```bash
python main.py                       # 列出全部任务
python main.py 淘金币                 # 关键字模糊匹配并执行
python main.py xianyu/闲鱼扔骰子.py   # 以 类目/文件名 精确指定
python tasks/taobao/淘宝多任务执行.py # 按顺序批量执行多个任务
```

入口会自动切换工作目录并配置 import 路径，在任意位置启动均可。

## 仪表盘

Web 管理界面(仅标准库实现, 无需额外依赖),白色系总览 + 设备管理 + 批量任务 + 日志:

```bash
python dashboard/app.py          # 默认 11000 端口, DASHBOARD_PORT 可覆盖
```

功能:

- **状态总览**: 顶部统计卡片(服务运行时长、ADB 环境、设备在线数、运行/排队任务、今日执行与异常数、轮询健康度),右侧服务详情面板
- **设备管理**: 添加/移除 ADB 地址(ip:port 或 USB serial),后台每 5 秒轮询 `adb devices`,掉线的无线设备自动重连;显示在线/离线、品牌型号、系统版本、电量(充电⚡)、当前运行任务数,USB 直连设备自动"发现"
- **批量执行**: 勾选多个任务 x 多台设备一键启动,**每台设备按勾选顺序依次执行, 设备之间并行**(内部经 `main.py` + `TASK_DEVICE` 运行);运行中可停止,排队中可取消;**失败自动重试**(次数可选,默认 1 次,失败后等 10 秒重试,多次尝试写入同一日志并标注,今日统计按最终结果只计一次,默认值可用环境变量 `DASHBOARD_TASK_RETRY` 覆盖)
- **今日执行情况**: 设备列表"今日执行"列显示该设备今天跑过哪些任务、成功/失败/进行中(悬停看明细);任务历史持久化保留 7 天,服务重启不丢,**上次异常中断的任务自动标记**
- **日志**: 每个任务一个日志文件(`logs/` 目录,页面按行实时增量显示),设备上下线与任务生命周期事件流

注意: 服务无鉴权,仅限内网使用。

## Docker 部署

参见 [AGENTS.md](AGENTS.md) 的 Docker 章节。容器启动后**直接运行仪表盘**,浏览器打开 `http://<宿主机IP>:11000` 即可管理设备与任务:

```bash
docker compose up -d --build    # 构建并启动, 仪表盘监听 11000 (host 网络)
```

仍可命令行执行任务:

```bash
docker compose exec coin11-tb python /scripts/main.py      # 列出任务
docker compose exec coin11-tb python /scripts/main.py 淘金币
```

## 多设备

连接多台设备后(无线: `adb connect <ip>:5555`,可多个),脚本会列出设备让你选择;也可用 `TASK_DEVICE` 环境变量固定设备,实现多台并行:

```bash
adb connect 192.168.1.100:5555
adb connect 192.168.1.101:5555

TASK_DEVICE=192.168.1.100:5555 python main.py 淘金币 &
TASK_DEVICE=192.168.1.101:5555 python main.py 闲鱼扔骰子 &

# Docker 容器内
docker compose exec -e TASK_DEVICE=192.168.1.100:5555 coin11-tb python /scripts/main.py 淘金币
```

同一台设备不要同时跑多个任务(UI 会互相干扰),并行规则是"每台设备一个进程"。

## 使用教程

抖音：
```
3.53 04/14 X@z.TY bnD:/ 自动化完成淘宝任务教程  https://v.douyin.com/i5xNsWVx/ 复制此链接，打开Dou音搜索，直接观看视频！
```
或者快手：
```
https://v.kuaishou.com/nGmUFX 自动化完成淘宝任务教程 该作品在快手被播放过1次，点击链接，打开【快手极速版】直接观看！
```

## tools 说明

`tools/` 内为独立调试脚本，默认部署无需安装其额外依赖：`识别图片测试.py` 依赖 requirements 中已注释的 paddleocr；`chromedriver.py` 需要额外安装 selenium。

## 点赞历史

[![Star History Chart](https://star-history.dera.page/svg?repos=czl0325/coin11-tb&type=Date)](https://star-history.dera.page/#czl0325/coin11-tbt&Date)
<br><br>
