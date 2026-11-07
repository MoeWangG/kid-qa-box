"""probe_tts —— 自动试多组 model/voice，找出你这账号里能出声的那一对。

音色 ID 和模型版本是绑定的（v3.1 的音色不能配 v2 模型），配错时
服务端不一定报错，而是直接返回空音频 —— 很难看出来。

用法：
    python3 scripts/probe_tts.py
"""

import _bootstrap  # noqa: F401

import copy
import json

from aibox.config import banner, load
from aibox.providers_ali import synthesize

# 候选组合：先用你配的音色去配各个模型版本，再退回常见 v2 音色
CANDIDATES = [
    ("cosyvoice-v3", None),
    ("cosyvoice-v3-flash", None),
    ("cosyvoice-v3-plus", None),
    ("cosyvoice-v2", None),
    ("cosyvoice-v1", None),
    ("cosyvoice-v2", "longxiaochun_v2"),
    ("cosyvoice-v2", "longwan_v2"),
    ("cosyvoice-v1", "longxiaochun"),
]

TEXT = "你好，我是小问号。"


def main() -> None:
    cfg = load()
    banner(cfg)
    current_model = cfg["tts"].get("model")
    current_voice = cfg["tts"].get("voice")
    print(f"当前配置：model={current_model}  voice={current_voice}\n")

    seen = set()
    winners = []
    for model, voice in CANDIDATES:
        voice = voice or current_voice
        if (model, voice) in seen:
            continue
        seen.add((model, voice))

        trial = copy.deepcopy(cfg)
        trial["tts"]["model"] = model
        trial["tts"]["voice"] = voice
        try:
            audio = synthesize(trial, TEXT)
            secs = len(audio) / 1024
            print(f"  ✓ {model:<20} / {voice:<20} → {len(audio)} 字节")
            winners.append((model, voice))
        except Exception as exc:
            msg = str(exc).splitlines()[0][:100]
            print(f"  ✗ {model:<20} / {voice:<20} → {msg}")

    print()
    if not winners:
        print("全都不行。可能原因：")
        print("  1. 音色 ID 拼错了 —— 去百炼控制台「模型广场 → 语音合成 → 音色列表」复制完整的")
        print("  2. 语音合成模型在这个账号/区域没开通")
        print("  3. 余额不足")
        return

    best_model, best_voice = winners[0]
    print("=" * 60)
    print(f"可用的第一组：model={best_model}  voice={best_voice}")
    print("=" * 60)
    print(f'\n改法：nano config.json，把 tts.model 改成 "{best_model}"')
    if best_voice != current_voice:
        print(f'             tts.voice 改成 "{best_voice}"')
    print("\n改完跑：python3 scripts/probe_ali.py")


if __name__ == "__main__":
    main()
