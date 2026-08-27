# coin11-tb

使用 uiautomator2 自动化完成淘宝双11金币任务、淘金币、芭芭农场、闲鱼任务、支付宝打卡等日常任务。

需要安装 adb 并加入 PATH。

## 目录结构

```
taojinbi-docker/
├── main.py            # 统一入口（推荐）
├── utils.py           # 公共库：设备选择 / 启动应用 / OCR / 模板匹配
├── img/               # OpenCV 模板图片
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

## Docker 部署

参见 [AGENTS.md](AGENTS.md) 的 Docker 章节。常用命令：

```bash
docker compose up -d --build                              # 构建并启动常驻容器
adb connect <设备IP>:5555                                  # 无线连接设备
docker compose exec coin11-tb python /scripts/main.py      # 列出任务
docker compose exec coin11-tb python /scripts/main.py 淘金币
```

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
