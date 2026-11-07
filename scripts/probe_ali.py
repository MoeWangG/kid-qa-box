"""probe_ali —— 只测阿里云百炼的语音，打印结果和报错。

跑之前先填 config.json：
    asr.api_key   （百炼的 sk- key）
    tts.api_key   （同一个 key）
    tts.voice     （音色 ID，形如 longxiaochun_v2）
    asr.model / tts.model 保持默认即可

用法：
    python3 scripts/probe_ali.py
    python3 scripts/probe_ali.py 我录的.wav     # 用真实录音测识别
"""

import _bootstrap  # noqa: F401

import pathlib
import sys

from aibox.audio import make_test_wav
from aibox.config import banner, load
from aibox.providers_ali import probe


def main() -> None:
    cfg = load()
    banner(cfg)

    wav = None
    if len(sys.argv) > 1:
        wav = pathlib.Path(sys.argv[1]).read_bytes()
        print(f"用录音：{sys.argv[1]}（{len(wav)} 字节）")
    else:
        rec_dir = pathlib.Path(_bootstrap.ROOT) / "recordings"
        for name in ("asr_01.wav", "loopback.wav"):
            candidate = rec_dir / name
            if candidate.exists():
                wav = candidate.read_bytes()
                print(f"用已有录音：{candidate}（{len(wav)} 字节）")
                break

    if wav is None:
        wav = make_test_wav(seconds=1.0)
        print("没找到录音，用 1 秒合成音（识别结果为空是正常的）")

    probe(cfg, wav)

    print("\n" + "=" * 60)
    print("两个都 ✓ → 跑 python3 scripts/step0_api.py 测完整三段")
    print("有 ✗ → 把 ✗ 那几行贴出来，我按报错改")
    print("=" * 60)


if __name__ == "__main__":
    main()
