"""按键。

真机：gpiozero.Button，按钮一端接 GPIO，另一端接 GND，内部上拉。
模拟：回车 = 按下，再回车 = 松手。所以 Mac 上也能把整个流程跑完。

轮询周期 10ms，相对音频块(32ms)可以忽略。选轮询不选回调，是为了让主流程
写成最好读的顺序代码 —— 这个项目不值得为 10ms 引入事件状态机。
"""

from __future__ import annotations

import os
import threading
import time

from .config import SIMULATE_BUTTON

POLL_SEC = 0.01


class Button:
    def __init__(self, gpio: int = 17, simulate: bool | None = None):
        self.gpio = gpio
        self._pressed = False
        self._dev = None
        self.simulate = SIMULATE_BUTTON if simulate is None else simulate

        if self.simulate:
            self._start_stdin_loop()
        else:
            from gpiozero import Button as GPIOButton

            self._dev = GPIOButton(gpio, pull_up=True, bounce_time=0.05)
            self._dev.when_pressed = lambda: self._set(True)
            self._dev.when_released = lambda: self._set(False)

    # ---------------------------------------------------------------- 内部
    def _set(self, value: bool) -> None:
        self._pressed = value
        if value:
            print("  ↓ 按下")

    def _start_stdin_loop(self) -> None:
        def loop() -> None:
            print("  [模拟按键] 回车 = 按下，再回车 = 松手；输入 q 退出")
            while True:
                try:
                    line = input()
                except (EOFError, KeyboardInterrupt):
                    return
                if line.strip().lower() == "q":
                    print("  退出。")
                    os._exit(0)
                self._set(not self._pressed)
                if not self._pressed:
                    print("  ↑ 松手")

        threading.Thread(target=loop, daemon=True).start()

    # ---------------------------------------------------------------- 对外
    @property
    def is_pressed(self) -> bool:
        if self._dev is not None:
            return self._dev.is_pressed
        return self._pressed

    def wait_press(self, timeout: float | None = None) -> bool:
        t0 = time.monotonic()
        while not self.is_pressed:
            if timeout is not None and time.monotonic() - t0 > timeout:
                return False
            time.sleep(POLL_SEC)
        return True

    def wait_release(self, timeout: float | None = None) -> bool:
        """等松手。返回 True = 正常松手，False = 超时（用作最长录音保护）。"""
        t0 = time.monotonic()
        while self.is_pressed:
            if timeout is not None and time.monotonic() - t0 > timeout:
                return False
            time.sleep(POLL_SEC)
        return True

    def close(self) -> None:
        if self._dev is not None:
            try:
                self._dev.close()
            finally:
                self._dev = None
