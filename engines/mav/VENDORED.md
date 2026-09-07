# taojinbi-Mav 引擎 (vendored)

淘金币任务的主引擎, 以 https://github.com/Linshi7766/taojinbi-Mav 为准,
引入版本: commit `2dfa692` (Apache-2.0, 见 LICENSE)。

- 相比上游原版脚本, 修复了搜一搜进度不结算、浏览时长不计数、弹窗遮挡、
  返回过冲等问题(详见 CHANGELOG.md), 并带 521 个离线单元测试。
- 入口: `scripts/run_taojinbi.py`, 需要 Python >= 3.11;
  依赖(uiautomator2/easyocr/opencv)与主项目一致, 无需单独安装包 ——
  运行时通过 PYTHONPATH=engines/mav/src 直接引用。
- 本项目通过 `tasks/taobao/淘金币任务.py` 包装调用, 设备由 TASK_DEVICE 传入。
