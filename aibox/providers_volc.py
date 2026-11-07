"""火山引擎语音适配（HTTP 非流式版）。

================================ 重要 ================================
这个文件里的端点、header、字段名，是我按火山语音服务文档的**形状**写的，
没有在你的账号上实测过。火山同一个能力有好几套版本的接口，字段差一个就是
400 / 403。所以：

    先跑  python3 scripts/probe_volc.py
    它会打印每一次尝试的原始响应（含 HTTP 状态码和响应体前 500 字）

然后按返回里的 message 改下面三个地方的常量，改完再跑探针：
    1. ASR_ENDPOINTS / TTS_ENDPOINTS 的 URL
    2. _asr_headers / _tts_headers 的 header 名
    3. 请求体里的字段名

跑通探针之后，主程序不用再改 —— providers.py 会走这个文件。
=====================================================================

只实现档 A 需要的两个 HTTP 接口（整段上传、整段返回）。
WebSocket 流式（二进制帧）留给档 B，见 README 第 10 节。

你需要从火山控制台拿三样东西：
  - AppID         （数字，形如 1234567890）
  - Access Token  （长字符串）
  - 音色 ID       （TTS 用，形如 zh_female_xxx 或 BV700_streaming）
"""

from __future__ import annotations

import base64
import json
import uuid

import requests

from .errors import ProviderError

# ---------------------------------------------------------------- 端点候选
# 探针会按顺序试，第一个返回 200 且解析出结果的就记下来。
# 如果全失败，说明要换你控制台里给的地址。

ASR_ENDPOINTS = [
    "https://openspeech.bytedance.com/api/v3/auc/bigmodel/recognize/flash",
    "https://openspeech.bytedance.com/api/v1/asr/json",
]

TTS_ENDPOINTS = [
    "https://openspeech.bytedance.com/api/v1/tts",
]


# ---------------------------------------------------------------- 工具

def _find_text(node, _depth: int = 0):
    """在任意嵌套的 JSON 里找第一个 key 为 text 的非空字符串。

    火山的返回结构改过好几次（result.text / resp.text / data.result[0].text），
    与其猜结构，不如递归找。找不到就返回 None，调用方会打印原始响应。
    """
    if _depth > 8:
        return None
    if isinstance(node, dict):
        for key in ("text", "result_text"):
            if key in node and isinstance(node[key], str):
                return node[key].strip()
        for val in node.values():
            found = _find_text(val, _depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_text(item, _depth + 1)
            if found:
                return found
    return None


def _v3_headers(conf: dict, resource_id: str) -> dict:
    """v3 系列接口的鉴权头。注意 X-Api-Connect-Id 是必须的 uuid。"""
    return {
        "X-Api-App-Key": str(conf["appid"]),
        "X-Api-Access-Key": conf["access_token"],
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": str(uuid.uuid4()),
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------- ASR

def transcribe(cfg: dict, wav_bytes: bytes) -> str:
    """整段 WAV -> 文本。"""
    p = cfg["asr"]
    endpoint = p.get("base_url") or ASR_ENDPOINTS[0]
    resource_id = p.get("resource_id", "volc.bigasr.auc")

    body = {
        "user": {"uid": p.get("uid", "aibox")},
        "audio": {
            "format": p.get("audio_format", "wav"),
            "rate": int(cfg.get("audio", {}).get("samplerate", 16000)),
            "bits": 16,
            "channel": 1,
            "data": base64.b64encode(wav_bytes).decode("ascii"),
        },
        "request": {
            "model_name": p.get("model_name", "bigmodel"),
            "enable_itn": True,
            "enable_punc": True,
        },
    }

    resp = requests.post(
        endpoint,
        headers=_v3_headers(p, resource_id),
        data=json.dumps(body),
        timeout=90,
    )
    if resp.status_code >= 400:
        raise ProviderError(
            f"火山 ASR 失败：HTTP {resp.status_code}\n"
            f"URL: {endpoint}\n"
            f"响应: {resp.text[:800]}"
        )

    try:
        payload = resp.json()
    except json.JSONDecodeError:
        raise ProviderError(f"火山 ASR 返回的不是 JSON：{resp.text[:800]}")

    code = payload.get("code")
    if code not in (None, 0, 1000, 20000000, 3000):
        raise ProviderError(
            f"火山 ASR 业务错误 code={code} message={payload.get('message')}\n"
            f"原始响应: {resp.text[:800]}"
        )

    text = _find_text(payload)
    if text is None:
        raise ProviderError(f"火山 ASR 返回里找不到 text 字段：\n{resp.text[:800]}")
    return text


# ---------------------------------------------------------------- TTS

def synthesize(cfg: dict, text: str) -> bytes:
    """文本 -> WAV bytes。"""
    p = cfg["tts"]
    text = (text or "").strip()
    if not text:
        from .audio import make_test_wav

        return make_test_wav(seconds=0.05)

    endpoint = p.get("base_url") or TTS_ENDPOINTS[0]
    enc = p.get("encoding", "wav")

    body = {
        "app": {
            "appid": str(p["appid"]),
            "token": p["access_token"],
            "cluster": p.get("cluster", "volcano_tts"),
        },
        "user": {"uid": p.get("uid", "aibox")},
        "audio": {
            "voice_type": p["voice"],
            "encoding": enc,
            "rate": int(p.get("sample_rate", 24000)),
            "speed_ratio": float(p.get("speed", 1.0)),
        },
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "operation": "query",
            "with_frontend": 1,
            "frontend_type": "unitTson",
        },
    }

    headers = {
        # 火山这套鉴权就是带分号的，不是笔误
        "Authorization": f"Bearer;{p['access_token']}",
        "Content-Type": "application/json",
    }

    resp = requests.post(endpoint, headers=headers, json=body, timeout=120)
    if resp.status_code >= 400:
        raise ProviderError(
            f"火山 TTS 失败：HTTP {resp.status_code}\n"
            f"URL: {endpoint}\n"
            f"响应: {resp.text[:800]}\n"
            "401/403 一般是 token 错或产品没开通；"
            "400 一般是 voice_type 或 cluster 不对。"
        )

    try:
        payload = resp.json()
    except json.JSONDecodeError:
        # 有的版本直接返回二进制音频
        if resp.content[:4] == b"RIFF":
            return resp.content
        raise ProviderError(f"火山 TTS 返回无法解析：{resp.text[:800]}")

    code = payload.get("code")
    if code not in (0, 3000):
        raise ProviderError(
            f"火山 TTS 业务错误 code={code} message={payload.get('message')}\n"
            f"原始响应: {resp.text[:500]}"
        )

    data = payload.get("data")
    if not isinstance(data, str) or not data:
        raise ProviderError(f"火山 TTS 返回里没有 data 字段：{resp.text[:500]}")

    audio = base64.b64decode(data)
    if enc == "wav" and audio[:4] != b"RIFF":
        raise ProviderError(
            "要求了 wav 但返回的不是 WAV 头。"
            "检查 config.json 里 tts.encoding，或把 encoding 改成 mp3 后用 ffmpeg 转。"
        )
    return audio


# ---------------------------------------------------------------- 探针

def probe(cfg: dict, wav_bytes: bytes) -> None:
    """逐个候选端点试，打印原始响应。给 scripts/probe_volc.py 用。"""
    from .audio import duration_of_wav

    print("\n" + "=" * 60)
    print("火山 ASR 探针")
    print("=" * 60)
    for url in ASR_ENDPOINTS:
        print(f"\n→ 试 {url}")
        conf = dict(cfg["asr"])
        conf["base_url"] = url
        try:
            tmp = dict(cfg, asr=conf)
            text = transcribe(tmp, wav_bytes)
            print(f"  ✓ 通了，识别结果：{text!r}")
            print(f"  → 把 config.json 的 asr.base_url 设为：{url}")
            break
        except ProviderError as exc:
            print(f"  ✗ {exc}")
        except Exception as exc:
            print(f"  ✗ {type(exc).__name__}: {exc}")

    print("\n" + "=" * 60)
    print("火山 TTS 探针")
    print("=" * 60)
    for url in TTS_ENDPOINTS:
        print(f"\n→ 试 {url}")
        conf = dict(cfg["tts"])
        conf["base_url"] = url
        try:
            tmp = dict(cfg, tts=conf)
            audio = synthesize(tmp, "你好，我是小问号。")
            print(f"  ✓ 通了，{len(audio)} 字节，音频长 {duration_of_wav(audio):.2f}s")
            print(f"  → 把 config.json 的 tts.base_url 设为：{url}")
            break
        except ProviderError as exc:
            print(f"  ✗ {exc}")
        except Exception as exc:
            print(f"  ✗ {type(exc).__name__}: {exc}")
