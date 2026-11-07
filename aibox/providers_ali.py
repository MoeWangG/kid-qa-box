"""阿里云百炼（DashScope）语音适配。

用官方 dashscope SDK，**不手写 WebSocket** —— 这是选阿里云最大的好处：
协议、鉴权、重试、心跳都由 SDK 处理，我不用猜二进制帧和 header 名。

需要的参数只有一样：DASHSCOPE_API_KEY（`sk-` 开头）。
从 bailian.console.aliyun.com → API-KEY 管理 拿。

跟火山的区别（供你判断）：
  火山：HTTP/WS 手写，字段要对着文档核，但延迟低、音色多
  阿里：SDK 封装，一次跑通的概率高，但 CSoyVoice 需要 WebSocket，SDK 内部管

注意：dashscope 的 api_key 是**模块级全局变量**，不是每次传参。
所以这里每次调用前都设一遍 —— 多线程并发调 TTS 时不会串到别的 key。
"""

from __future__ import annotations

import os
import tempfile

from .errors import ProviderError


def _load_sdk(section: str, cfg: dict):
    try:
        import dashscope
    except ImportError:
        raise ProviderError(
            "没装 dashscope SDK。装：\n"
            "  pip3 install --user dashscope\n"
            "树莓派上如果 pip 报错，先 sudo apt install -y python3-venv 再走 venv 路线。"
        )
    key = str(cfg[section].get("api_key", ""))
    if not key or "REPLACE" in key:
        raise ProviderError(f"config.json 里 {section}.api_key 还没填（百炼的 sk- key）")
    dashscope.api_key = key
    return dashscope


def _make_callback():
    """Recognition 必须传 callback。这里要一个不出声的空实现，只记错误。"""
    from dashscope.audio.asr import RecognitionCallback

    class _Null(RecognitionCallback):
        def __init__(self):
            super().__init__()
            self.error = None

        def on_open(self) -> None:
            pass

        def on_close(self) -> None:
            pass

        def on_event(self, result) -> None:
            pass

        def on_complete(self) -> None:
            pass

        def on_error(self, result) -> None:
            self.error = result

    return _Null()


# ---------------------------------------------------------------- ASR

def transcribe(cfg: dict, wav_bytes: bytes) -> str:
    """整段 WAV -> 文本。

    Recognition.call(file=...) 是同步的：SDK 内部把文件分块喂进 WebSocket，
    等最后一个句子的 sentence_end，然后返回 RecognitionResult。
    """
    p = cfg["asr"]
    _load_sdk("asr", cfg)
    from dashscope.audio.asr import Recognition

    model = p.get("model", "paraformer-realtime-v2")
    sample_rate = int(p.get("sample_rate", 16000))

    # SDK 只接受文件路径，所以这里必须落一次盘（临时文件，用完就删）
    fd, path = tempfile.mkstemp(suffix=".wav", prefix="aibox_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(wav_bytes)

        callback = _make_callback()
        try:
            recognition = Recognition(
                model=model,
                callback=callback,
                format="wav",
                sample_rate=sample_rate,
            )
            result = recognition.call(file=path)
        except Exception as exc:
            raise ProviderError(
                f"阿里云 ASR 失败：{type(exc).__name__}: {exc}\n"
                f"  模型={model} 采样率={sample_rate}\n"
                "  常见原因：模型没开通、api_key 不对、余额不足"
            ) from exc

        if callback.error is not None:
            raise ProviderError(f"阿里云 ASR 流内报错：{callback.error}")

        if result is None:
            raise ProviderError("阿里云 ASR 返回 None，通常是模型名或鉴权有问题")

        # ★ SDK 在服务端报错时不抛异常，而是把错误塞进 result.status_code。
        # 不检查这里，鉴权失败会表现为「识别结果为空」，极难排查。
        status = getattr(result, "status_code", None)
        if status is not None and int(status) != 200:
            code = getattr(result, "code", None)
            message = getattr(result, "message", None)
            raise ProviderError(
                f"阿里云 ASR 返回 HTTP {status}\n"
                f"  code={code} message={message}\n"
                f"  模型={model} 采样率={sample_rate}\n"
                "  常见原因：InvalidApiKey（key 错）/ ModelNotOpen（模型没开通）/ 余额不足"
            )

        sentences = result.get_sentence()
        if isinstance(sentences, dict):
            sentences = [sentences]
        if not sentences:
            return ""
        return "".join(
            str(s.get("text", "")) for s in sentences if isinstance(s, dict)
        ).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- TTS

def _capture_dashscope_ws_error():
    """把 dashscope 在 WebSocket 握手失败时吞掉的服务端响应体捞出来。

    SDK 的 __connect 只轮询 sock.connected，握手被拒（如 401 InvalidApiKey）时
    sock 永远不会 connected，5 秒后抛一个笼统的 TimeoutError。
    真实原因（InvalidApiKey / ModelNotOpen）只在 ERROR 日志里，用户看不到。

    返回 (logger, handler, box)，用完必须 removeHandler。
    """
    import logging
    import re

    box = {"detail": None}

    class _Handler(logging.Handler):
        def emit(self, record):
            if box["detail"]:
                return
            try:
                message = record.getMessage()
            except Exception:
                return
            match = re.search(r"b'(\{.*?\})'", message)
            if match:
                box["detail"] = match.group(1)

    handler = _Handler(level=logging.ERROR)
    logger = logging.getLogger("dashscope")
    logger.addHandler(handler)
    return logger, handler, box


def synthesize(cfg: dict, text: str, retries: int = 1) -> bytes:
    """文本 -> WAV bytes。

    流式链路会并发开多条 TTS 连接，阿里云偶尔会拒掉其中一条
    （表现为 "websocket connection could not established within 5s"）。
    这种瞬时失败重试一次基本都能过，所以外面包一层。
    """
    import time as _time

    last = None
    for attempt in range(retries + 1):
        try:
            return _synthesize_once(cfg, text)
        except Exception as exc:
            last = exc
            transient = "within 5s" in str(exc) or "Timeout" in type(exc).__name__
            if attempt < retries and transient:
                _time.sleep(0.4)
                continue
            raise
    raise last  # pragma: no cover


def _synthesize_once(cfg: dict, text: str) -> bytes:
    """真正干活的那一层。"""
    p = cfg["tts"]
    text = (text or "").strip()
    if not text:
        from .audio import make_test_wav

        return make_test_wav(seconds=0.05)

    _load_sdk("tts", cfg)
    from dashscope.audio.tts_v2 import AudioFormat, SpeechSynthesizer

    model = p.get("model", "cosyvoice-v2")
    voice = p.get("voice", "")
    if not voice or "REPLACE" in str(voice):
        raise ProviderError(
            "config.json 里 tts.voice 还没填。\n"
            "  百炼控制台 → 模型广场 → 语音合成 → 音色列表，形如 longxiaochun_v2"
        )

    fmt_name = p.get("format", "WAV_24000HZ_MONO_16BIT")
    fmt = getattr(AudioFormat, fmt_name, None)
    if fmt is None:
        raise ProviderError(
            f"tts.format = {fmt_name!r} 不是合法的 AudioFormat。\n"
            "  可用：WAV_24000HZ_MONO_16BIT / PCM_24000HZ_MONO_16BIT / MP3_24000HZ_MONO_256KBPS"
        )

    ws_box: dict = {}
    ws_logger = None
    ws_handler = None
    try:
        synthesizer = SpeechSynthesizer(model=model, voice=voice, format=fmt)
        ws_logger, ws_handler, ws_box = _capture_dashscope_ws_error()
        try:
            audio = synthesizer.call(text)
        finally:
            ws_logger.removeHandler(ws_handler)
    except Exception as exc:
        if ws_logger is not None and ws_handler is not None:
            ws_logger.removeHandler(ws_handler)
        detail = f"\n  服务端返回：{ws_box.get('detail')}" if ws_box.get("detail") else ""
        hint = ""
        if "within 5s" in str(exc):
            hint = (
                "\n  ↑ 这个「连接超时」通常是假象：SDK 握手失败后不报真实原因。"
                "\n    如果下面没有「服务端返回」，先跑 scripts/probe_ali.py 看网络自检。"
            )
        raise ProviderError(
            f"阿里云 TTS 失败：{type(exc).__name__}: {exc}\n"
            f"  模型={model} 音色={voice} 格式={fmt_name}{detail}{hint}\n"
            "  常见原因：InvalidApiKey（key 错）/ ModelNotOpen（模型没开通）/ 音色与模型不匹配"
        ) from exc

    if not audio:
        raise ProviderError(
            f"阿里云 TTS 返回空音频（模型={model} 音色={voice}）。检查音色和模型是否匹配。"
        )
    if not isinstance(audio, (bytes, bytearray)):
        raise ProviderError(f"阿里云 TTS 返回了 {type(audio).__name__}，预期 bytes")

    audio = bytes(audio)
    if audio[:4] != b"RIFF":
        raise ProviderError(
            f"TTS 返回的不是 WAV（前 4 字节 {audio[:4]!r}）。\n"
            f"  当前 format={fmt_name}。改成 WAV_24000HZ_MONO_16BIT 再试。"
        )
    return audio


# ---------------------------------------------------------------- 探针

def check_network() -> None:
    """分开测 HTTPS 和 WebSocket 可达性。

    为什么需要：DashScope 的语音合成走 WebSocket，而 HTTPS 和 WS 是两个不同的
    端点。在国外/弱网环境下常见「HTTPS 通但 WS 握不上手」，表现为 TTS 报
    「websocket connection could not established within 5s」—— 看起来像参数错，
    其实是网络。这个检查能把两种情况分开。
    """
    import requests

    print("\n[网络自检]")
    for name, url in [
        ("HTTPS 主站", "https://dashscope.aliyuncs.com"),
        ("HTTPS 国际站", "https://dashscope-intl.aliyuncs.com"),
    ]:
        try:
            resp = requests.get(url, timeout=8)
            print(f"  ✓ {name} 可达（HTTP {resp.status_code}）")
        except Exception as exc:
            print(f"  ✗ {name} 不可达：{type(exc).__name__}")

    try:
        import dashscope
        import websocket

        url = dashscope.base_websocket_api_url
        print(f"  …测 WebSocket：{url}")
        conn = websocket.create_connection(
            url,
            timeout=8,
            header={"Authorization": "bearer invalid-key-connectivity-test"},
        )
        conn.close()
        print("  ✓ WebSocket 握手成功（key 无效但能连上，说明网络没问题）")
    except ImportError:
        print("  ? 没装 websocket-client，跳过 WS 检查")
    except Exception as exc:
        text = str(exc)
        if "401" in text and "BadStatus" in type(exc).__name__:
            print("  ✓ WebSocket 可达（401 = 握手成功、只是测试用的 key 无效，正是预期）")
        elif "CERTIFICATE_VERIFY_FAILED" in text:
            print("  ✗ SSL 证书验证失败 —— 这是 Python 缺 CA 根证书，不是网络问题。")
            print("    修复：pip3 install certifi，本包已在 aibox/__init__.py 自动处理")
            print("    若仍报错：export SSL_CERT_FILE=$(python3 -c 'import certifi;print(certifi.where())')")
        else:
            print(f"  ✗ WebSocket 连不上：{type(exc).__name__}: {text[:150]}")
            print("    如果你还在国外：DashScope 的 WS 端点对海外网络不稳，回国再测。")
            print("    如果已在国内：查防火墙/公司网络是否拦了 wss。")


def probe(cfg: dict, wav_bytes: bytes) -> None:
    from .audio import duration_of_wav

    check_network()

    print("\n" + "=" * 60)
    print("阿里云 TTS 探针")
    print("=" * 60)
    p = cfg["tts"]
    print(f"模型={p.get('model')} 音色={p.get('voice')} 格式={p.get('format')}")
    try:
        audio = synthesize(cfg, "你好，我是小问号，很高兴认识你。")
        print(f"  ✓ 合成成功：{len(audio)} 字节，音频长 {duration_of_wav(audio):.2f}s")
        print("  → 下一步可以跑 step5_tts.py 听声音")
    except ProviderError as exc:
        print(f"  ✗ {exc}")

    print("\n" + "=" * 60)
    print("阿里云 ASR 探针")
    print("=" * 60)
    a = cfg["asr"]
    print(f"模型={a.get('model')} 采样率={a.get('sample_rate')}")
    try:
        text = transcribe(cfg, wav_bytes)
        if text:
            print(f"  ✓ 识别成功：{text!r}")
        else:
            print("  ✓ 接口通了，但识别结果为空。")
            print("    如果用的是合成音（正弦波），空是正常的 —— 用真实录音再测一次：")
            print("    先跑 python3 scripts/step3_asr.py --save 录一句，再回来跑这个。")
    except ProviderError as exc:
        print(f"  ✗ {exc}")
