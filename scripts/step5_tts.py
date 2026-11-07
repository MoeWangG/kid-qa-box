"""step5 —— 只测语音合成：打字，出声。

跑通这一步，你已经能听到机器说话了，剩下的只是把前面接起来。

用法：
    python3 scripts/step5_tts.py
    python3 scripts/step5_tts.py 你好我是小问号      # 说一句就走
    python3 scripts/step5_tts.py --save 文本         # 顺便存成 wav；不带参数会存到 recordings/
"""

import _bootstrap  # noqa: F401

import pathlib
import sys
import time

from aibox.audio import duration_of_wav, play_wav_bytes
from aibox.config import banner, load
from aibox.providers import synthesize


def main() -> None:
    cfg = load()
    banner(cfg)
    out_dev = cfg.get("audio", {}).get("output_device")
    outdir = pathlib.Path(_bootstrap.ROOT) / "recordings"

    args = sys.argv[1:]
    save = "--save" in args
    args = [a for a in args if a != "--save"]

    def say(text: str) -> None:
        t = time.perf_counter()
        audio = synthesize(cfg, text)
        t_syn = time.perf_counter() - t
        print(f"  合成 {t_syn:.2f}s / {len(audio)} 字节 / 音频长 {duration_of_wav(audio):.2f}s")
        if save:
            outdir.mkdir(exist_ok=True)
            p = outdir / "tts.wav"
            p.write_bytes(audio)
            print(f"  存了 {p}")
        play_wav_bytes(audio, device=out_dev)

    if args:
        say(" ".join(args))
        return

    print("输入文本回车就念，空行退出。\n")
    while True:
        try:
            text = input("念：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        try:
            say(text)
        except Exception as exc:
            print(f"  ! {type(exc).__name__}: {exc}\n")
        print()
    print("退出。")


if __name__ == "__main__":
    main()
