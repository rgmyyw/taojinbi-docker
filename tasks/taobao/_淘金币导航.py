#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""入场导航: 把手机带到淘宝"淘金币首页"。

Mav 引擎是受控设计, 不负责从任意页面导航, 起点需在淘金币页面附近;
本脚本复刻旧版脚本的入场路径(入口按钮优先, 搜索兜底), 在包装脚本中
先于引擎执行。到达 TMSActivity(淘金币页面) 即视为成功, 任务弹窗由引擎
自己点击"赚更多金币"打开。

用法: python _淘金币导航.py <serial>   (退出码 0=已到达, 1=导航失败)
"""

import sys
import time

import uiautomator2 as u2

TB = "com.taobao.taobao"
ATTEMPTS = 3


def on_coin_page(d):
    cur = d.app_current() or {}
    return "TMSActivity" in (cur.get("activity") or "")


def nav_once(d):
    """单轮导航尝试, 返回 True 表示本轮动作已执行(需等待后复查)。"""
    jump = d(resourceId="com.taobao.taobao:id/tv_close", text="跳过")
    if jump.exists:
        print("关闭开屏广告")
        jump.click()
        time.sleep(2)
    coin_btn = d(classNameMatches=r"android.widget.FrameLayout|android.view.View",
                 description="领淘金币")
    if coin_btn.exists:
        print("点击首页「领淘金币」入口")
        d.double_click(coin_btn[0].center()[0], coin_btn[0].center()[1])
        time.sleep(5)
        return True
    search = d(className="android.view.View", description="搜索栏")
    if search.exists:
        print("通过搜索进入淘金币")
        search.click()
        time.sleep(2)
        edit = d(resourceId="com.taobao.taobao:id/searchEdit")
        if edit.exists:
            edit.send_keys("淘金币")
            time.sleep(3)
            hit = d(className="android.view.View", descriptionContains="淘金币")
            if hit.exists:
                hit.click()
                time.sleep(5)
                return True
        print("搜索路径未走通")
        d.press("back")
        time.sleep(1)
    return False


def main(serial):
    d = u2.connect(serial)
    if on_coin_page(d):
        print("已在淘金币页面")
        return 0
    print(f"启动淘宝 (serial={serial})")
    d.app_stop(TB)
    time.sleep(1)
    d.app_start(TB)
    time.sleep(6)
    for i in range(ATTEMPTS):
        if on_coin_page(d):
            print("已到达淘金币页面")
            return 0
        print(f"导航尝试 {i + 1}/{ATTEMPTS}")
        if not nav_once(d):
            print("本轮无可用入口, 重启淘宝后重试")
            d.app_stop(TB)
            time.sleep(1)
            d.app_start(TB)
            time.sleep(6)
    return 0 if on_coin_page(d) else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("用法: python _淘金币导航.py <serial>")
    raise SystemExit(main(sys.argv[1]))
