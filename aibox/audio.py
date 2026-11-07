"""音频采集与播放。

设计要点：
1. InputStream 常开，按下按键只是开始缓存，避免每次开设备的 100~200ms 开销。
2. 录音全程在内存里，不落盘。
3. **采样率和声道自动适配设备**：便宜的 USB 声卡通常只支持 44100/48000 和双声道，
   而 ASR 要 16k 单声道、TTS 常给 24k 单声道。这里负责两头转换，
   上层（device.py / providers）永远只看到 16k 单声道。
4. sounddevice 延迟导入，模拟模式不需要装 PortAudio。
"""

from __future__ import annotations

import io
import math
import struct
import wave
from collections import deque

from .config import SIMULATE_AUDIO

_np = None


def _numpy():
    global _np
    if _np is None:
        import numpy

        _np = numpy
    return _np


# ---------------------------------------------------------------- WAV 工具

def pcm_to_wav(pcm: bytes, samplerate: int, channels: int = 1, sampwidth: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(samplerate)
        w.writeframes(pcm)
    return buf.getvalue()


def wav_params_and_pcm(data: bytes):
    with wave.open(io.BytesIO(data), "rb") as w:
        params = {
            "channels": w.getnchannels(),
            "sampwidth": w.getsampwidth(),
            "samplerate": w.getframerate(),
            "nframes": w.getnframes(),
        }
        pcm = w.readframes(w.getnframes())
    return params, pcm


def make_test_wav(seconds: float = 1.0, samplerate: int = 16000, freq: float = 440.0) -> bytes:
    n = int(seconds * samplerate)
    frames = bytearray()
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * freq * i / samplerate))
        frames += struct.pack("<h", v)
    return pcm_to_wav(bytes(frames), samplerate)


def concat_wavs(chunks: list) -> bytes:
    """把多段 WAV 拼成一段。参数不一致时放弃合并，只返回第一段。"""
    chunks = [c for c in chunks if c]
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]

    def signature(p: dict) -> tuple:
        return (p["channels"], p["sampwidth"], p["samplerate"])

    base, _ = wav_params_and_pcm(chunks[0])
    base_sig = signature(base)
    pcm_parts = []
    for c in chunks:
        params, pcm = wav_params_and_pcm(c)
        if signature(params) != base_sig:
            return chunks[0]
        pcm_parts.append(pcm)
    return pcm_to_wav(
        b"".join(pcm_parts),
        base["samplerate"],
        base["channels"],
        base["sampwidth"],
    )


def duration_of_wav(data: bytes) -> float:
    """按实际 PCM 字节数算时长（有些服务端不回填 header 的 data 长度）。"""
    try:
        params, pcm = wav_params_and_pcm(data)
        frame_bytes = params["channels"] * params["sampwidth"]
        if not frame_bytes or not params["samplerate"]:
            return 0.0
        return len(pcm) / frame_bytes / params["samplerate"]
    except Exception:
        return 0.0


# ---------------------------------------------------------------- 重采样 / 声道

def pcm_to_mono(pcm: bytes, channels: int) -> bytes:
    if channels <= 1:
        return pcm
    np = _numpy()
    arr = np.frombuffer(pcm, dtype=np.int16).reshape(-1, channels)
    return arr.mean(axis=1).astype(np.int16).tobytes()


def resample_pcm(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """int16 PCM 重采样。

    整数倍（如 48000 -> 16000）用分组平均，等于做了个简单抗混叠低通；
    非整数倍退化成线性插值。对语音识别够用，不值得为此装 scipy。
    """
    if src_rate == dst_rate or not pcm:
        return pcm
    np = _numpy()
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if arr.size == 0:
        return pcm

    if src_rate % dst_rate == 0:
        factor = src_rate // dst_rate
        usable = arr.size // factor * factor
        if usable == 0:
            return b""
        out = arr[:usable].reshape(-1, factor).mean(axis=1)
    else:
        n_dst = max(1, int(arr.size * dst_rate / src_rate))
        idx = np.linspace(0, arr.size - 1, n_dst)
        out = np.interp(idx, np.arange(arr.size), arr)

    return out.astype(np.int16).tobytes()


def pcm_to_channels(pcm: bytes, channels: int, want: int) -> bytes:
    """单声道 <-> 双声道互转。"""
    np = _numpy()
    if channels == want:
        return pcm
    arr = np.frombuffer(pcm, dtype=np.int16)
    if channels == 1 and want == 2:
        return np.repeat(arr, 2).tobytes()
    if channels == 2 and want == 1:
        return arr.reshape(-1, 2).mean(axis=1).astype(np.int16).tobytes()
    return pcm


# ---------------------------------------------------------------- 录音

class Recorder:
    """常开录音流，对外永远给 target 采样率的单声道 WAV。"""

    def __init__(self, samplerate: int = 16000, channels: int = 1, device=None):
        self.samplerate = samplerate  # 目标采样率（给 ASR）
        self.channels = channels
        self.device = device
        self.capture_rate = samplerate
        self.capture_channels = channels
        self._buf: deque = deque()
        self._recording = False
        self._stream = None
        if not SIMULATE_AUDIO:
            self._open()

    def _open(self) -> None:
        import sounddevice as sd

        resolved = _resolve_device(self.device, "input")
        try:
            info = sd.query_devices(resolved, kind="input")
        except Exception:
            info = sd.query_devices(kind="input")

        # 用设备自己的默认采样率采集，之后再转 —— 直接要求 16k 会被拒（-9997）
        self.capture_rate = int(info.get("default_samplerate") or self.samplerate)
        max_in = int(info.get("max_input_channels") or 1)
        self.capture_channels = max(1, min(2, max_in))

        self._stream = sd.InputStream(
            samplerate=self.capture_rate,
            channels=self.capture_channels,
            dtype="int16",
            blocksize=1024,
            device=resolved,
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status) -> None:
        if self._recording:
            self._buf.append(indata.copy())

    def start(self) -> None:
        self._buf.clear()
        self._recording = True

    def stop(self) -> bytes:
        self._recording = False
        if SIMULATE_AUDIO:
            self._buf.clear()
            return make_test_wav(seconds=1.5, samplerate=self.samplerate)
        if not self._buf:
            return pcm_to_wav(b"", self.samplerate, 1)

        raw = b"".join(frame.tobytes() for frame in self._buf)
        self._buf.clear()

        mono = pcm_to_mono(raw, self.capture_channels)
        resampled = resample_pcm(mono, self.capture_rate, self.samplerate)
        return pcm_to_wav(resampled, self.samplerate, 1)

    def close(self) -> None:
        self._recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
                self._stream = None


# ---------------------------------------------------------------- 播放

_volume_checked = False


def play_wav_bytes(data: bytes, device=None, block: bool = True) -> float:
    """播放一段 WAV，自动适配设备的采样率和声道。返回时长（秒）。"""
    global _volume_checked
    if not _volume_checked:
        ensure_output_volume()
        _volume_checked = True

    if len(data) < 12 or data[:4] != b"RIFF":
        raise RuntimeError(
            "要播放的不是 WAV 文件。"
            f"前 16 字节是 {data[:16]!r}\n"
            "如果改了 tts.format，请改回 WAV_xxx。"
        )

    params, pcm = wav_params_and_pcm(data)
    frame_bytes = params["channels"] * params["sampwidth"]
    seconds = (
        len(pcm) / frame_bytes / params["samplerate"]
        if frame_bytes and params["samplerate"]
        else 0.0
    )

    if SIMULATE_AUDIO:
        print(f"  [模拟播放] {seconds:.2f}s / {params['samplerate']}Hz / {len(data)} 字节")
        return seconds

    if params["sampwidth"] != 2:
        raise RuntimeError(f"只支持 16bit WAV，拿到 {params['sampwidth'] * 8}bit")

    import sounddevice as sd

    resolved = _resolve_device(device, "output")
    try:
        info = sd.query_devices(resolved, kind="output")
    except Exception:
        info = sd.query_devices(kind="output")

    dev_rate = int(info.get("default_samplerate") or params["samplerate"])
    dev_channels = max(1, min(2, int(info.get("max_output_channels") or 1)))

    pcm2 = resample_pcm(pcm, int(params["samplerate"]), dev_rate)
    pcm2 = pcm_to_channels(pcm2, int(params["channels"]), dev_channels)

    np = _numpy()
    arr = np.frombuffer(pcm2, dtype=np.int16)
    if dev_channels > 1:
        arr = arr.reshape(-1, dev_channels)

    sd.play(arr, dev_rate, device=resolved)
    if block:
        sd.wait()
    return seconds


def _resolve_device(device, kind: str):
    """把 config 里的设备配置解析成 sounddevice 能用的索引。

    失败时**明确报错**而不是静默回退 —— 静默回退会让你以为在播，
    其实声音进了没接音箱的板载声卡，排查成本极高。
    """
    import sounddevice as sd

    if device is None:
        return None
    if isinstance(device, int):
        return device

    text = str(device).lower()

    # "auto" = 自动找一个 USB 声卡，索引变了也不用改配置
    if text == "auto":
        fallback = None
        for idx, info in enumerate(sd.query_devices()):
            channels = (
                info["max_input_channels"]
                if kind == "input"
                else info["max_output_channels"]
            )
            if channels <= 0:
                continue
            name = info["name"].lower()
            if "usb" in name:
                return idx
            if fallback is None and "hdmi" not in name and "bcm2835" not in name:
                fallback = idx
        if fallback is not None:
            return fallback
        raise RuntimeError(
            f"audio.{kind}_device = auto，但没找到 USB {kind} 设备。\n"
            "插好 USB 声卡后跑 python3 scripts/step1_loopback.py --devices 确认。"
        )

    matches = []
    for idx, info in enumerate(sd.query_devices()):
        channels = (
            info["max_input_channels"] if kind == "input" else info["max_output_channels"]
        )
        if channels > 0 and text in info["name"].lower():
            matches.append((idx, info["name"]))

    if not matches:
        raise RuntimeError(
            f"config.json 里 audio.{kind}_device = {device!r} 匹配不到任何{kind}设备。\n"
            f"跑 python3 scripts/step1_loopback.py --devices 看可用设备，"
            "或者直接填索引数字（如 1）。"
        )
    return matches[0][0]


def ensure_output_volume(level: str = "80%") -> None:
    """把各声卡的 PCM 音量拉起来。

    便宜的 USB 声卡有个恶习：插拔后 mixer 会重置成 0%，
    表现为「播放执行了但一点声音没有」，而且 alsactl store 也存不住。
    启动时兜一次，比每次手动 amixer 靠得住。

    没有 amixer 或该卡没有 PCM 控件时静默跳过。
    """
    if SIMULATE_AUDIO:
        return
    import shutil
    import subprocess

    if not shutil.which("amixer"):
        return
    for card in range(4):
        for ctl in ("PCM", "Speaker", "Headphone"):
            try:
                subprocess.run(
                    ["amixer", "-c", str(card), "sset", ctl, level, "unmute"],
                    capture_output=True,
                    timeout=5,
                    check=False,
                )
            except Exception:
                pass


def list_devices() -> None:
    """打印设备列表和各自支持的参数。默认设备不存在时也不会崩。"""
    try:
        import sounddevice as sd
    except Exception as exc:
        print(f"装不上 sounddevice：{exc}\n树莓派先执行：sudo apt install -y libportaudio2")
        return

    print(sd.query_devices())
    for kind in ("input", "output"):
        try:
            info = sd.query_devices(kind=kind)
            print(
                f"\n默认 {kind}: [{info['index']}] {info['name']}  "
                f"rate={int(info['default_samplerate'])}  "
                f"ch={info['max_input_channels'] if kind == 'input' else info['max_output_channels']}"
            )
        except Exception:
            print(f"\n默认 {kind}: 无 —— 需要在 config.json 的 audio.{kind}_device 显式指定")
