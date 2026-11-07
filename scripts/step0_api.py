"""step0 —— 只测 API，不碰任何硬件。

这一步的目的是：在你焊线、插声卡之前，先把 key 和模型名弄对。
跑不通别往下走，后面每一步都依赖它。

用法：
    python3 scripts/step0_api.py                 # 用合成的测试音
    python3 scripts/step0_api.py 我录的.wav       # 用真实录音测识别
"""

import _bootstrap  # noqa: F401

import sys
import time

from aibox.audio import make_test_wav
from aibox.config import banner, load
from aibox.providers import check_all


def main() -> None:
    cfg = load()
    banner(cfg)

    wav = None
    if len(sys.argv) > 1:
        path = sys.argv[1]
        wav = open(path, "rb").read()
        print(f"用录音测试：{path}（{len(wav)} 字节）")
    else:
        print("没给 wav，用 1 秒合成音测连通性（识别结果会是空的，正常）")

    t0 = time.perf_counter()
    try:
        check_all(cfg, wav)
    except Exception as exc:
        print(f"\n✗ 失败：{type(exc).__name__}: {exc}")
        print(
            "\n排查顺序：\n"
            "  1. api_key 是否填对（config.json，不是 config.example.json）\n"
            "  2. base_url 是否是该厂商的地址\n"
            "  3. model / voice 名字是否存在于该厂商的控制台\n"
            "  4. 余额是否够\n"
            "  5. 能否联网：curl -I https://openspeech.bytedance.com\n"
            "把上面打印的原始响应贴出来，一看就知道是哪一项。"
        )
        sys.exit(1)

    print(f"\n✓ 三段都通了，总耗时 {time.perf_counter() - t0:.2f}s")
    print("下一步：python3 scripts/step1_loopback.py")


if __name__ == "__main__":
    main()
