"""selftest —— 不用硬件、不联网，验证代码本身没写错。

全部用 mock provider + 模拟硬件，所以：
  - 不需要 config.json
  - 不需要 API key
  - 不需要树莓派

它的意义：你在折腾树莓派之前，先在 Mac 上花 5 秒确认这份代码逻辑是通的。
以后你改了代码，也先跑这个。

用法：
    python3 scripts/selftest.py
"""

import os

os.environ["AIBOX_SIMULATE"] = "1"

import _bootstrap  # noqa: E402,F401

import sys  # noqa: E402
import tempfile  # noqa: E402

from aibox.audio import concat_wavs, duration_of_wav, make_test_wav  # noqa: E402
from aibox.cache import AnswerCache  # noqa: E402
from aibox.pipeline import answer_oneshot, answer_stream, fmt_timings  # noqa: E402
from aibox.splitter import SentenceSplitter  # noqa: E402

FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    mark = "✓" if cond else "✗"
    print(f"  {mark} {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILS.append(name)


def make_cfg(cache_dir: str, cache_enabled: bool = False) -> dict:
    return {
        "_root": str(_bootstrap.ROOT),
        "asr": {"kind": "mock"},
        "llm": {
            "kind": "mock",
            "model": "mock",
            "system_prompt": "mock",
            "max_tokens": 100,
            "temperature": 0.7,
        },
        "tts": {"kind": "mock", "model": "mock", "voice": "mock"},
        "audio": {"samplerate": 16000},
        "button": {"gpio": 17},
        "runtime": {
            "cache_enabled": cache_enabled,
            "cache_dir": cache_dir,
            "history_turns": 3,
        },
    }


def test_splitter() -> None:
    print("\n[1] 切句器")
    s = SentenceSplitter()
    got: list[str] = []
    for chunk in ["因为阳光", "穿过空气，", "蓝色的光最容易散开。", "所以我们", "看到蓝天！"]:
        got += s.feed(chunk)
    got += s.flush()
    check("切出 2 句", len(got) == 2, str(got))
    check("第 1 句以句号结尾", got and got[0].endswith("。"))
    check("第 2 句以叹号结尾", len(got) > 1 and got[1].endswith("！"))

    s2 = SentenceSplitter()
    check("小数不会被切坏", s2.feed("大概 3.14 米那么长，") == [])
    check("无标点超长会强切", len(s2.feed("啊" * 40)) >= 1)


def test_concat() -> None:
    print("\n[2] WAV 合并")
    a = make_test_wav(seconds=0.5, freq=440)
    b = make_test_wav(seconds=0.7, freq=660)
    merged = concat_wavs([a, b])
    d = duration_of_wav(merged)
    check("合并后时长 = 0.5 + 0.7", abs(d - 1.2) < 0.02, f"{d:.2f}s")
    check("合并结果仍是合法 WAV", merged[:4] == b"RIFF")


def test_pipelines() -> None:
    print("\n[3] 串行链路 (step6)")
    cfg = make_cfg("unused")
    r = answer_oneshot(cfg, "为什么天是蓝的", speak=lambda _a: None)
    check("有回答", bool(r["answer"]))
    check("有音频", len(r.get("audio") or b"") > 44)
    print("     ", fmt_timings(r["timings"]))

    print("\n[4] 流式链路 (step7)")
    played: list[bytes] = []
    r2 = answer_stream(
        cfg,
        "为什么天是蓝的",
        speak=lambda a: played.append(a),
        on_answer=lambda a: None,
    )
    check("有回答", bool(r2["answer"]))
    check("至少播了 2 段（证明真的分段了）", len(played) >= 2, f"{len(played)} 段")
    check("记了 first_audio 时间", "first_audio" in r2["timings"])
    check(
        "首段音频早于总耗时",
        r2["timings"]["first_audio"] <= r2["timings"]["total"] + 1e-6,
        fmt_timings(r2["timings"]),
    )


def test_cache() -> None:
    print("\n[5] 答案缓存")
    with tempfile.TemporaryDirectory() as tmp:
        cfg = make_cfg(tmp, cache_enabled=True)
        cache = AnswerCache(tmp, enabled=True)
        first = answer_oneshot(cfg, "为什么天是蓝的？", cache=cache, speak=lambda _a: None)
        check("第一次没命中", not first["timings"].get("cache_hit"))

        second = answer_oneshot(cfg, "为什么天是蓝的", cache=cache, speak=lambda _a: None)
        check("标点不同也算命中", bool(second["timings"].get("cache_hit")))
        check("命中不走大模型", "llm" not in second["timings"])
        check("命中音频可播", len(second.get("audio") or b"") > 44)

        other = AnswerCache(tmp, enabled=True, salt="another-provider")
        check("换模型/改 prompt 后旧缓存不命中", other.get("为什么天是蓝的") is None)


def main() -> None:
    print("=" * 56)
    print("自检：模拟硬件 + mock 云端，不联网")
    print("=" * 56)
    test_splitter()
    test_concat()
    test_pipelines()
    test_cache()

    print("\n" + "=" * 56)
    if FAILS:
        print(f"✗ {len(FAILS)} 项没过：{', '.join(FAILS)}")
        sys.exit(1)
    print("✓ 全部通过。代码逻辑没问题，可以去接真硬件/真 API 了。")
    print("下一步：cp config.example.json config.json")
    print("        填好百炼 api_key + tts.voice 后，跑 python3 scripts/probe_ali.py")


if __name__ == "__main__":
    main()
