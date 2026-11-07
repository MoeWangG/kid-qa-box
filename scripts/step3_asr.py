"""step3 —— 按键录音 + 识别，只打印文本，不出声。

这一步打通「声音 -> 文字」。识别不准就调麦克风位置，别往下走。

用法：
    python3 scripts/step3_asr.py
    python3 scripts/step3_asr.py --save      # 同时把每次录音存到 recordings/
"""

import _bootstrap  # noqa: F401

import pathlib
import sys
import time

from aibox.audio import Recorder
from aibox.button import Button
from aibox.config import banner, load
from aibox.providers import transcribe


def main() -> None:
    cfg = load()
    banner(cfg)
    save = "--save" in sys.argv
    outdir = pathlib.Path(_bootstrap.ROOT) / "recordings"
    if save:
        outdir.mkdir(exist_ok=True)

    rec = Recorder(int(cfg["audio"].get("samplerate", 16000)), device=cfg["audio"].get("input_device"))
    btn = Button(int(cfg["button"].get("gpio", 17)))
    turns = 0
    try:
        print("按住按键说一句，松手看识别结果。Ctrl+C 退出\n")
        while True:
            btn.wait_press()
            t0 = time.perf_counter()
            rec.start()
            btn.wait_release(timeout=float(cfg["button"].get("max_record_sec", 20)))
            held = time.perf_counter() - t0
            wav = rec.stop()
            turns += 1

            if save:
                p = outdir / f"asr_{turns:02d}.wav"
                p.write_bytes(wav)
                print(f"  存了 {p}")

            t = time.perf_counter()
            try:
                text = transcribe(cfg, wav)
            except Exception as exc:
                print(f"  ! {type(exc).__name__}: {exc}\n")
                continue
            cost = time.perf_counter() - t

            print(f"  录音 {held:.2f}s -> 识别 {cost:.2f}s")
            print(f"  文本：{text!r}\n")
            print("按住按键说一句 ——")
    except KeyboardInterrupt:
        print("\n退出。")
    finally:
        rec.close()
        btn.close()


if __name__ == "__main__":
    main()
