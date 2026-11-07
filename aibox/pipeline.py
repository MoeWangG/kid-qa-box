"""把一问一答串起来的两条链路。

answer_oneshot  —— 档 A：ASR -> LLM 整段 -> TTS 整段 -> 播放。慢但好调试。
answer_stream   —— 档 A+：LLM 流式切句，TTS 并发，按序边播。用同一批 HTTP 接口就能快 1.5~2s。

档 B（真·全流式，ASR 和 TTS 都换成厂商 WebSocket 协议）不在这里，
因为每家的二进制协议都不一样，抄不了通用代码。见 docs/guide.md 第 10 节。
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from .audio import concat_wavs
from .cache import AnswerCache
from .providers import chat, chat_stream, synthesize
from .splitter import SentenceSplitter


def answer_oneshot(
    cfg: dict,
    question: str,
    history: list | None = None,
    cache: AnswerCache | None = None,
    speak=None,
) -> dict:
    """串行链路。返回 {"answer", "audio", "timings"}。"""
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    if cache is not None:
        hit = cache.get(question)
        if hit is not None:
            answer, audio = hit
            timings["cache_hit"] = 1.0
            timings["total"] = time.perf_counter() - t0
            if speak is not None:
                speak(audio)
            return {"answer": answer, "audio": audio, "timings": timings}

    t = time.perf_counter()
    answer = chat(cfg, question, history)
    timings["llm"] = time.perf_counter() - t

    t = time.perf_counter()
    audio = synthesize(cfg, answer)
    timings["tts"] = time.perf_counter() - t

    if cache is not None and answer:
        cache.put(question, answer, audio)

    t = time.perf_counter()
    if speak is not None:
        speak(audio)
    timings["speak"] = time.perf_counter() - t
    timings["total"] = time.perf_counter() - t0
    return {"answer": answer, "audio": audio, "timings": timings}


def answer_stream(
    cfg: dict,
    question: str,
    history: list | None = None,
    cache: AnswerCache | None = None,
    speak=None,
    on_answer=None,
) -> dict:
    """流式链路：边生成边合成边播。

    关键在于 play 指针：TTS 的请求是并发发出去的（4 个工人），
    但播放严格按句子顺序，前面那句没好就等 —— 不会串词。
    """
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    if cache is not None:
        hit = cache.get(question)
        if hit is not None:
            answer, audio = hit
            timings["cache_hit"] = 1.0
            if on_answer is not None:
                on_answer(answer)
            if speak is not None:
                speak(audio)
            timings["total"] = time.perf_counter() - t0
            return {"answer": answer, "timings": timings}

    splitter = SentenceSplitter()
    # 并发开太多 TTS 连接会被服务端拒（实测 4 路会偶发超时），默认 2
    workers = int((cfg.get("runtime") or {}).get("tts_concurrency", 2))
    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futures: dict[int, object] = {}
    pieces: list[str] = []
    audio_chunks: list[bytes] = []

    idx = 0
    play_idx = 0
    first_audio_at: float | None = None
    first_text_at: float | None = None

    def play_ready(force: bool = False) -> None:
        nonlocal play_idx, first_audio_at
        while play_idx in futures:
            fut = futures[play_idx]
            if not fut.done() and not force:
                break
            audio = fut.result()
            if first_audio_at is None:
                first_audio_at = time.perf_counter() - t0
                timings["first_audio"] = first_audio_at
            audio_chunks.append(audio)
            if speak is not None:
                speak(audio)
            del futures[play_idx]
            play_idx += 1

    try:
        for delta in chat_stream(cfg, question, history):
            if first_text_at is None:
                first_text_at = time.perf_counter() - t0
                timings["first_text"] = first_text_at
            pieces.append(delta)
            for sentence in splitter.feed(delta):
                futures[idx] = pool.submit(synthesize, cfg, sentence)
                idx += 1
            play_ready()

        for sentence in splitter.flush():
            futures[idx] = pool.submit(synthesize, cfg, sentence)
            idx += 1
        play_ready(force=True)
    finally:
        pool.shutdown(wait=True)

    answer = "".join(pieces).strip()
    if on_answer is not None:
        on_answer(answer)

    if cache is not None and answer and audio_chunks:
        cache.put(question, answer, concat_wavs(audio_chunks))

    timings["total"] = time.perf_counter() - t0
    return {"answer": answer, "timings": timings}


def make_cache(cfg: dict) -> AnswerCache:
    rt = cfg.get("runtime", {})
    root = rt.get("cache_dir", "./cache")
    if not str(root).startswith("/"):
        root = f"{cfg['_root']}/{root.lstrip('./')}"
    return AnswerCache(
        root,
        enabled=bool(rt.get("cache_enabled", True)),
        salt=cache_salt(cfg),
    )


def cache_salt(cfg: dict) -> str:
    """provider 指纹：模型名 / 音色 / system_prompt 任一变化，旧缓存就不再命中。"""
    import hashlib

    parts = []
    for section in ("asr", "llm", "tts"):
        conf = cfg.get(section, {})
        parts += [str(conf.get(k, "")) for k in ("kind", "model", "voice")]
    parts.append(str(cfg.get("llm", {}).get("system_prompt", "")))
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:10]


def push_history(
    history: list,
    question: str,
    answer: str,
    turns: int = 20,
    max_chars: int = 1500,
) -> None:
    """往 history 里追加一轮，并按两个上限裁剪。

    为什么不是一个轮数就完事：
      轮数控不了长度。一轮可能是“嗯”（1 字），也可能是 200 字的长回答。
      所以先用轮数封顶，再用字符预算兜底 —— 后者才是真正的保险。

    max_chars=1500 约等于 1000~1500 token，占 DeepSeek 64K 窗口的 2%。
    真要装能装几万 token，但语音问答里超过 20 轮的对话基本不存在，
    而且每条 ASR 错误都会留在历史里污染后续回答。
    """
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})

    # 成对删除，保证 user/assistant 不会被拆开
    limit = max(1, turns) * 2
    while len(history) > limit:
        del history[:2]
    while len(history) > 2 and sum(
        len(str(m.get("content", ""))) for m in history
    ) > max_chars:
        del history[:2]


def fmt_timings(timings: dict) -> str:
    order = ["asr", "llm", "tts", "first_text", "first_audio", "speak"]
    parts = []
    for key in order:
        if key in timings:
            parts.append(f"{key}={timings[key]:.2f}s")
    for key, value in timings.items():
        if key not in order and key not in ("cache_hit", "total", "end_to_end"):
            parts.append(f"{key}={value:.2f}s")
    # 缓存命中时 total 只是查表耗时，会让人误以为流程很快；真正的数字是 end_to_end
    if timings.get("cache_hit"):
        parts.insert(0, "缓存命中")
    elif "total" in timings:
        parts.append(f"total={timings['total']:.2f}s")
    return "  ".join(parts)
