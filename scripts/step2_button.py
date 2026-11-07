"""step2 —— 只测按键：按 5 次，看能不能识别按下/松手。

接线（务必断电接线）：
    GPIO17 (物理脚 11) --- 按钮一脚
    GND    (物理脚 9)  --- 按钮另一脚
不需要外接电阻，gpiozero 内部上拉。

没有树莓派也能跑：AIBOX_SIMULATE=1 python3 scripts/step2_button.py
"""

import _bootstrap  # noqa: F401

import time

from aibox.button import Button
from aibox.config import banner, load


def main() -> None:
    cfg = load()
    banner(cfg)
    gpio = int(cfg.get("button", {}).get("gpio", 17))
    print(f"监听 GPIO{gpio}，按 5 次\n")

    btn = Button(gpio)
    try:
        for n in range(1, 6):
            if not btn.wait_press(timeout=120):
                print("✗ 120 秒没检测到按下。检查接线是否接反、GPIO 编号对不对")
                return
            t_down = time.perf_counter()
            btn.wait_release(timeout=60)
            held = time.perf_counter() - t_down
            print(f"  #{n} 按住 {held:.2f}s")
    finally:
        btn.close()

    print("\n✓ 按键正常。下一步：python3 scripts/step3_asr.py")


if __name__ == "__main__":
    main()
