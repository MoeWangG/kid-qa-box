"""云端能力适配层：ASR / LLM / TTS。

只有三种 kind：
  mock    假数据，不联网。用来在没有 key 的机器上验证流程。
  openai  OpenAI 兼容格式（DeepSeek / 火山 Ark / 阿里百炼 compatible-mode / 官方
          OpenAI 都是这个形状）。这是默认，也是最少坑的一条路。

所有报错都会把 HTTP 状态码和原始响应前 800 字打出来 —— 参数不对时你看一眼就知道
该改哪个字段，不要只丢一个 requests.HTTPError。
"""

from __future__ import annotations

import json
import time

import requests

from .audio import make_test_wav
from .errors import ProviderError

MOCK_ANSWER = "因为阳光穿过空气的时候，蓝色的光最容易散开，撒得满地都是，我们抬头就看见蓝色的天啦。"
MOCK_QUESTION = "为什么天是蓝的"


# kind 分发：openai = OpenAI 兼容格式；volc = 火山引擎语音；mock = 假数据

def _kind(conf: dict) -> str:
    return conf.get("kind", "openai")


def _headers(api_key: str) -> dict:
    return {"Authorization": f"Bearer {api_key}"}


def _check(resp: requests.Response, what: str) -> requests.Response:
    if resp.status_code >= 400:
        raise ProviderError(
            f"{what} 失败：HTTP {resp.status_code}\n"
            f"URL: {resp.url}\n"
            f"响应: {resp.text[:800]}"
        )
    return resp


def _mock_sleep(seconds: float) -> None:
    time.sleep(seconds)


# ---------------------------------------------------------------- ASR

def transcribe(cfg: dict, wav_bytes: bytes) -> str:
    """整段 WAV -> 文本。档 A 用这个。"""
    p = cfg["asr"]
    kind = _kind(p)
    if kind == "mock":
        _mock_sleep(1.2)
        return MOCK_QUESTION
    if kind == "volc":
        from .providers_volc import transcribe as volc_transcribe

        return volc_transcribe(cfg, wav_bytes)
    if kind == "ali":
        from .providers_ali import transcribe as ali_transcribe

        return ali_transcribe(cfg, wav_bytes)

    files = {"file": ("speech.wav", wav_bytes, "audio/wav")}
    data = {"model": p["model"]}
    if p.get("language"):
        data["language"] = p["language"]
    data.update(p.get("form_extra") or {})

    resp = requests.post(
        p["base_url"],
        headers=_headers(p["api_key"]),
        files=files,
        data=data,
        timeout=90,
    )
    _check(resp, "ASR")
    body = resp.json()
    text = body.get("text")
    if text is None:
        raise ProviderError(f"ASR 返回里没有 text 字段，原始响应：\n{resp.text[:800]}")
    return text.strip()


# ---------------------------------------------------------------- LLM

def _build_messages(cfg: dict, user_text: str, history: list | None) -> list:
    prompt = cfg["llm"]["system_prompt"]

    # 模型默认不知道“今天几号、现在几点”，不注入的话问时间就会胡编。
    # 它仍然不知道天气/新闻（API 不联网），但至少日期是准的。
    if cfg["llm"].get("inject_time", True):
        from datetime import datetime

        now = datetime.now()
        weekday = "一二三四五六日"[now.weekday()]
        prompt += f"\n\n现在是 {now.year} 年 {now.month} 月 {now.day} 日 星期{weekday} {now:%H:%M}。"

    messages = [{"role": "system", "content": prompt}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_text})
    return messages


def _llm_payload(cfg: dict, user_text: str, history: list | None, stream: bool) -> dict:
    p = cfg["llm"]
    payload = {
        "model": p["model"],
        "messages": _build_messages(cfg, user_text, history),
        "max_tokens": p.get("max_tokens", 200),
        "temperature": p.get("temperature", 0.7),
        "stream": stream,
    }
    payload.update(p.get("payload_extra") or {})
    return payload


def chat(cfg: dict, user_text: str, history: list | None = None) -> str:
    """非流式，一次拿全文。档 A 用这个。"""
    p = cfg["llm"]
    if _kind(p) == "mock":
        _mock_sleep(2.0)
        return MOCK_ANSWER

    resp = requests.post(
        p["base_url"],
        headers=_headers(p["api_key"]),
        json=_llm_payload(cfg, user_text, history, stream=False),
        timeout=90,
    )
    _check(resp, "LLM")
    body = resp.json()
    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        raise ProviderError(f"LLM 返回结构不对：{exc}\n原始响应：\n{resp.text[:800]}")


def chat_stream(cfg: dict, user_text: str, history: list | None = None):
    """流式，逐段 yield 文本增量。档 A+ 用这个。"""
    p = cfg["llm"]
    if _kind(p) == "mock":
        for chunk in (MOCK_ANSWER[:14], MOCK_ANSWER[14:26], MOCK_ANSWER[26:]):
            _mock_sleep(0.5)
            yield chunk
        return

    resp = requests.post(
        p["base_url"],
        headers=_headers(p["api_key"]),
        json=_llm_payload(cfg, user_text, history, stream=True),
        timeout=90,
        stream=True,
    )
    _check(resp, "LLM(stream)")

    for raw in resp.iter_lines(decode_unicode=True):
        if not raw:
            continue
        line = raw.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if chunk == "[DONE]":
            break
        try:
            obj = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        choices = obj.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        piece = delta.get("content")
        if piece:
            yield piece


# ---------------------------------------------------------------- TTS

def synthesize(cfg: dict, text: str) -> bytes:
    """文本 -> WAV bytes。"""
    p = cfg["tts"]
    text = (text or "").strip()
    if not text:
        return make_test_wav(seconds=0.05)
    kind = _kind(p)
    if kind == "mock":
        _mock_sleep(max(0.4, len(text) / 60.0))
        return make_test_wav(seconds=max(0.3, len(text) / 12.0))
    if kind == "volc":
        from .providers_volc import synthesize as volc_synthesize

        return volc_synthesize(cfg, text)
    if kind == "ali":
        from .providers_ali import synthesize as ali_synthesize

        return ali_synthesize(cfg, text)

    payload = {
        "model": p["model"],
        "input": text,
        "voice": p["voice"],
        "response_format": p.get("response_format", "wav"),
        "speed": p.get("speed", 1.0),
    }
    payload.update(p.get("payload_extra") or {})

    resp = requests.post(
        p["base_url"],
        headers=_headers(p["api_key"]),
        json=payload,
        timeout=120,
    )
    _check(resp, "TTS")

    ctype = resp.headers.get("Content-Type", "")
    if "json" in ctype or "text" in ctype:
        raise ProviderError(
            "TTS 返回的是文本/JSON 而不是音频，通常是 voice 名字或 model 名不对。\n"
            f"原始响应：\n{resp.text[:800]}"
        )
    return resp.content


def check_all(cfg: dict, wav_bytes: bytes | None = None) -> None:
    """step0 用：把三段都打通一遍，打印耗时。"""
    if wav_bytes is None:
        wav_bytes = make_test_wav(seconds=1.0)

    t = time.time()
    text = transcribe(cfg, wav_bytes)
    t_asr = time.time() - t
    print(f"[ASR ] {t_asr:5.2f}s  -> {text!r}")

    t = time.time()
    answer = chat(cfg, "为什么天是蓝的")
    t_llm = time.time() - t
    print(f"[LLM ] {t_llm:5.2f}s  -> {answer!r}")

    t = time.time()
    audio = synthesize(cfg, answer)
    t_tts = time.time() - t
    from .audio import duration_of_wav

    print(f"[TTS ] {t_tts:5.2f}s  -> {len(audio)} 字节，音频长 {duration_of_wav(audio):.2f}s")
