"""step1 —— 只测声卡：录 3 秒，存盘，再放出来。

这一步不碰按键、不碰网络。听不到自己的声音，就先把声卡搞定，别往下走。

用法：
    python3 scripts/step1_loopback.py
    python3 scripts/step1_loopback.py --devices     # 先看设备列表和序号
    python3 scripts/step1_loopback.py --in 1 --out 2   # 指定设备序号
"""

import _bootstrap  # noqa: F401

import argparse
import pathlib
import time

from aibox.audio import Recorder, list_devices, play_wav_bytes
from aibox.config import load


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--devices", action="store_true", help="只打印设备列表")
    ap.add_argument("--in", dest="in_dev", default=None, help="输入设备序号或名字片段")
    ap.add_argument("--out", dest="out_dev", default=None, help="输出设备序号或名字片段")
    ap.add_argument("--seconds", type=float, default=3.0)
    args = ap.parse_args()

    if args.devices:
        list_devices()
        return

    def as_dev(v):
        if v is None:
            return None
        try:
            return int(v)
        except ValueError:
            return v

    # 命令行参数优先，否则用 config.json 里配的设备（否则会落到板载声卡上，听不到）
    cfg = load(require_keys=False)
    audio_cfg = cfg.get("audio", {})
    in_dev = as_dev(args.in_dev) or audio_cfg.get("input_device")
    out_dev = as_dev(args.out_dev) or audio_cfg.get("output_device")
    print(f"输入设备: {in_dev or '系统默认'}   输出设备: {out_dev or '系统默认'}")

    outdir = pathlib.Path(_bootstrap.ROOT) / "recordings"
    outdir.mkdir(exist_ok=True)

    input(f"回车开始录 {args.seconds:.0f} 秒（对着麦克风说话）...")
    rec = Recorder(16000, device=in_dev)
    try:
        rec.start()
        for i in range(int(args.seconds)):
            time.sleep(1)
            print(f"  ...{i + 1}s")
        wav = rec.stop()
    finally:
        rec.close()

    path = outdir / "loopback.wav"
    path.write_bytes(wav)
    print(f"已存：{path}  ({len(wav)} 字节)")

    if len(wav) < 1000:
        print("✗ 录到的东西太少了。检查：麦克风有没有插、输入设备序号对不对")
        return

    print("回放中...")
    play_wav_bytes(wav, device=out_dev)
    print("✓ 听到自己的声音就算过。听不到但文件有大小 = 输出设备选错了")


if __name__ == "__main__":
    main()
