"""step6 —— 档 A：全链路串行。第一次能对着它说话问问题，就是这一步。

按住 -> 录音 -> 松手 -> 识别 -> 大模型 -> 语音合成 -> 播放

预期端到端 3~5 秒。慢是正常的，快的那版是 step7。

用法：
    python3 scripts/step6_main.py                             # 树莓派，真按键
    AIBOX_SIMULATE_BUTTON=1 python3 scripts/step6_main.py     # Mac，回车当按键，音频是真的
    AIBOX_SIMULATE=1 python3 scripts/step6_main.py            # 全模拟，连麦克风都不用
"""

import _bootstrap  # noqa: F401

from aibox.device import main

if __name__ == "__main__":
    main(stream=False)
