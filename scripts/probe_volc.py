"""probe_volc —— 只测火山，把每一次尝试的原始响应打出来。

⚠️ 只有 config.json 里 asr.kind / tts.kind 是 "volc" 时才用这个脚本。
   默认配置走的是阿里云（kind = "ali"），那个用 scripts/probe_ali.py。
   两者都是备选，你自己选一个跑通就行。

为什么单独一个脚本：火山的语音接口有好几套版本，端点/header/字段差一个就报错。
在这里试错，比在 step0 里试错快得多 —— 它会把候选端点全试一遍，哪个通了直接告诉你。

用法：
    python3 scripts/probe_volc.py

跑之前先在 config.json 填好：
    asr.appid / asr.access_token
    tts.appid / tts.access_token / tts.voice

从哪拿：
    火山控制台 → 语音技术 → 应用管理 → AppID / Access Token
    火山控制台 → 语音合成 → 音色列表 → 抄一个 voice_type（形如 zh_female_xxx）

跑通了它会在最后告诉你 config.json 该怎么填。
"""

import _bootstrap  # noqa: F401

import pathlib

from aibox.audio import make_test_wav
from aibox.config import banner, load
from aibox.providers_volc import probe


def main() -> None:
    cfg = load()
    banner(cfg)

    rec_dir = pathlib.Path(_bootstrap.ROOT) / "recordings"
    wav = None
    for name in ("asr_01.wav", "loopback.wav"):
        candidate = rec_dir / name
        if candidate.exists():
            wav = candidate.read_bytes()
            print(f"用已有录音：{candidate}（{len(wav)} 字节）")
            break

    if wav is None:
        wav = make_test_wav(seconds=1.0)
        print("没找到录音，用 1 秒合成音。")
        print("识别结果为空是正常的 —— 只看 HTTP 是否 200、有没有报业务错误。")
        print("想测准一点：先跑 step3_asr.py --save 录一句，再回来跑这个。")

    probe(cfg, wav)

    print("\n" + "=" * 60)
    print("如果 ASR 和 TTS 都打了 ✓，就可以跑 step0 / step6 了。")
    print("如果全 ✗，把 ✗ 后面那段原始响应整个贴出来 —— 里面通常直接写着")
    print("「invalid voice_type」「resource not found」「signature mismatch」这种具体原因。")
    print("=" * 60)


if __name__ == "__main__":
    main()
