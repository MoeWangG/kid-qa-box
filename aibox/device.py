"""设备主循环 —— 按下 -> 录音 -> 松手 -> 识别 -> 回答 -> 出声。

step6（串行）和 step7（流式）跑的是同一份循环，只差 stream 这一个参数。
所以你在 step6 上验证过的东西，切到 step7 不会变形。
"""

from __future__ import annotations

import json
import pathlib
import time

from .audio import Recorder, make_test_wav, play_wav_bytes
from .button import Button
from .config import banner, load
from .pipeline import answer_oneshot, answer_stream, fmt_timings, make_cache, push_history
from .providers import ProviderError, transcribe


def beep(device=None, freq: float = 880.0, seconds: float = 0.12) -> None:
    try:
        play_wav_bytes(make_test_wav(seconds=seconds, freq=freq), device=device)
    except Exception:
        pass


def run(cfg: dict, stream: bool = False) -> None:
    audio_cfg = cfg.get("audio", {})
    btn_cfg = cfg.get("button", {})
    rt = cfg.get("runtime", {})

    in_dev = audio_cfg.get("input_device")
    out_dev = audio_cfg.get("output_device")
    samplerate = int(audio_cfg.get("samplerate", 16000))
    min_sec = float(btn_cfg.get("min_record_sec", 0.4))
    max_sec = float(btn_cfg.get("max_record_sec", 20))
    turns = int(rt.get("history_turns", 20))
    max_chars = int(rt.get("history_max_chars", 1500))

    banner(cfg)

    # 先播问候语，再开麦克风：便宜的 USB 声卡同时录放容易死锁
    play_greeting(cfg, out_dev)

    led = make_led(cfg)
    meow = load_meow(cfg)
    rec = Recorder(samplerate=samplerate, device=in_dev)
    btn = Button(int(btn_cfg.get("gpio", 17)))
    cache = make_cache(cfg)
    history: list = []

    def speak(audio: bytes) -> None:
        play_wav_bytes(audio, device=out_dev)

    print(f"链路：{'流式（档 A+）' if stream else '串行（档 A）'}")
    print(f"缓存：{cache.stats()}   Ctrl+C 退出\n")

    def show_ready() -> None:
        if led is not None:
            led.on()
        print("就绪，按住按键说话 ——")

    show_ready()

    try:
        while True:
            if not btn.wait_press():
                continue

            if led is not None:
                led.off()  # 开始录音 -> 灭，表示"正在处理，别问"
            t_press = time.perf_counter()
            rec.start()

            released = btn.wait_release(timeout=max_sec)
            t_release = time.perf_counter()
            rec_seconds = t_release - t_press

            if not released:
                print(f"  ! 超过 {max_sec}s 强制停止")

            wav = rec.stop()
            print(f"  录音 {rec_seconds:.2f}s / {len(wav)} 字节")

            if rec_seconds < min_sec:
                print("  太短，忽略")
                beep(out_dev, freq=440, seconds=0.08)
                continue

            if meow:
                # 松手立刻叫太突兀（人还停在说话状态里），缓一下再叫
                delay = float((cfg.get("runtime") or {}).get("meow_delay_sec", 1.0))
                if delay > 0:
                    time.sleep(delay)
                try:
                    play_wav_bytes(meow, device=out_dev)
                except Exception:
                    pass

            try:
                t = time.perf_counter()
                question = transcribe(cfg, wav)
                t_asr = time.perf_counter() - t
                print(f"  [ASR {t_asr:.2f}s] {question!r}")

                if not question:
                    speak(_tts_safe(cfg, "我没听清，再说一遍好吗"))
                    continue

                t = time.perf_counter()
                if stream:
                    result = answer_stream(
                        cfg,
                        question,
                        history,
                        cache,
                        speak=speak,
                        on_answer=lambda a: print(f"  [回答] {a}"),
                    )
                else:
                    result = answer_oneshot(
                        cfg, question, history, cache, speak=speak
                    )
                    print(f"  [回答] {result['answer']}")

                timings = result["timings"]
                timings["asr"] = t_asr
                timings["end_to_end"] = time.perf_counter() - t_release
                print(f"  [耗时] {fmt_timings(timings)}")
                print(f"  [端到端] {timings['end_to_end']:.2f}s（松手到播完）\n")

                push_history(history, question, result["answer"], turns, max_chars)
                log_turn(
                    cfg,
                    {
                        "q": question,
                        "a": result["answer"],
                        "rec_sec": round(rec_seconds, 2),
                        "asr_sec": round(t_asr, 2),
                        "e2e_sec": round(timings["end_to_end"], 2),
                        "cache": bool(timings.get("cache_hit")),
                    },
                )

            except ProviderError as exc:
                print(f"  ! 云端出错：{exc}")
                log_turn(cfg, {"error": f"{type(exc).__name__}: {exc}"[:300]})
                speak(_tts_safe(cfg, "我的网络好像出问题了，等一下再问我吧"))
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # 设备跑一整天，任何单次失败都不能把循环打死
                print(f"  ! 意外错误：{type(exc).__name__}: {exc}")
                log_turn(cfg, {"error": f"{type(exc).__name__}: {exc}"[:300]})
                beep(out_dev, freq=330, seconds=0.2)

            show_ready()

    except KeyboardInterrupt:
        print("\n退出。")
    finally:
        if led is not None:
            led.off()
        rec.close()
        btn.close()


def play_greeting(cfg: dict, out_dev) -> None:
    """启动时打招呼一次。第一次用 TTS 生成并缓存，之后走本地文件。

    开机时网络可能还没完全就绪，失败就静默跳过，绝不影响主流程。
    """
    rt = cfg.get("runtime") or {}
    text = rt.get("greeting_text")
    if not text:
        return

    raw = rt.get("greeting_wav") or "./assets/greeting.wav"
    if not str(raw).startswith("/"):
        raw = f"{cfg['_root']}/{str(raw).lstrip('./')}"
    target = pathlib.Path(raw)

    audio = None
    if target.exists():
        try:
            data = target.read_bytes()
            # 0 字节或明显不是 WAV 的，当作没缓存，重新生成
            if len(data) > 200 and data[:4] == b"RIFF":
                audio = data
            else:
                print(f"  ! 缓存文件无效（{len(data)} 字节），重新生成：{target}")
        except OSError:
            audio = None

    if audio is None:
        try:
            from .providers import synthesize

            audio = synthesize(cfg, text)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(audio)
            print(f"  已生成问候语：{target}")
        except Exception as exc:
            print(f"  ! 问候语生成失败（不影响使用）：{exc}")
            return

    try:
        play_wav_bytes(audio, device=out_dev)
    except Exception:
        pass


def make_led(cfg: dict):
    """指示灯：就绪时亮，处理中就灭。

    返回 None 表示没配或建不起来（不影响主流程）。
    """
    from .config import SIMULATE
    from .config import SIMULATE_BUTTON

    gpio = (cfg.get("button") or {}).get("led_gpio")
    if not gpio or SIMULATE or SIMULATE_BUTTON:
        return None
    try:
        from gpiozero import LED

        return LED(int(gpio))
    except Exception as exc:
        print(f"  ! LED 初始化失败（不影响使用）：{exc}")
        return None


def load_meow(cfg: dict) -> bytes | None:
    """松手后先叫一声猫，遮盖等待。

    文件不存在时用 TTS 生成一次并缓存下来（配置里的 runtime.meow_wav）。
    之后你随时可以用真猫叫的 wav 覆盖那个文件，不用改代码。
    """
    path = (cfg.get("runtime") or {}).get("meow_wav")
    if not path:
        return None
    if not str(path).startswith("/"):
        path = f"{cfg['_root']}/{str(path).lstrip('./')}"

    target = pathlib.Path(path)
    if target.exists():
        try:
            data = target.read_bytes()
            if len(data) > 200 and data[:4] == b"RIFF":
                return data
        except OSError:
            pass

    try:
        from .providers import synthesize

        audio = synthesize(cfg, "喵～")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        print(f"  已生成猫叫：{target}（想换成真猫叫，直接覆盖这个文件）")
        return audio
    except Exception as exc:
        print(f"  ! 猫叫生成失败（不影响使用）：{exc}")
        return None


def log_turn(cfg: dict, record: dict) -> None:
    """追加一行 JSONL。只记文本和耗时，不记音频。

    关掉的办法：config.json 里 runtime.log_path 设为 null。
    看统计：python3 scripts/log_report.py
    """
    path = (cfg.get("runtime") or {}).get("log_path")
    if not path:
        return
    if not str(path).startswith("/"):
        path = f"{cfg['_root']}/{str(path).lstrip('./')}"
    record = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), **record}
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 日志失败绝不影响主流程


def _tts_safe(cfg: dict, text: str) -> bytes:
    """本地固定话术转语音，失败就返回一个短提示音，绝不抛异常。"""
    from .providers import synthesize

    try:
        return synthesize(cfg, text)
    except Exception:
        return make_test_wav(seconds=0.3, freq=660)


def main(stream: bool = False) -> None:
    cfg = load()
    run(cfg, stream=stream)


if __name__ == "__main__":  # pragma: no cover
    main()
