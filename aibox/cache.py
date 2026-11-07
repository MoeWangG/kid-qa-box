"""答案缓存。

孩子的提问高度重复（"为什么天是蓝的" 一周能问八遍）。
命中缓存 = 0 秒延迟，这是整条链路上唯一能做到"秒回"的地方。

存两样东西：
  <key>.json   {"q": 原问题, "a": 答案文本, "hits": 次数}
  <key>.wav    答案音频
"""

from __future__ import annotations

import hashlib
import json
import pathlib


def _normalize(text: str) -> str:
    """归一化：去空白和标点，让"天为什么是蓝的？"和"天为什么是蓝的"算同一个问题。"""
    drop = " \t\r\n，。、？！,?!.…~～—-\"'“”‘’"
    return "".join(ch for ch in text if ch not in drop).lower()


class AnswerCache:
    def __init__(self, root: str | pathlib.Path, enabled: bool = True, salt: str = ""):
        self.root = pathlib.Path(root)
        self.enabled = enabled
        # salt = provider 指纹。换了模型或改了 system_prompt，旧缓存自动失效。
        # 否则你会遇到最诡异的那种 bug：调了 prompt，机器还在念昨天的答案。
        self.salt = salt
        if enabled:
            self.root.mkdir(parents=True, exist_ok=True)

    def _key(self, question: str) -> str:
        raw = f"{self.salt}\x00{_normalize(question)}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    def _json_path(self, question: str) -> pathlib.Path:
        return self.root / f"{self._key(question)}.json"

    def _wav_path(self, question: str) -> pathlib.Path:
        return self.root / f"{self._key(question)}.wav"

    def get(self, question: str) -> tuple[str, bytes] | None:
        """返回 (答案文本, 音频 bytes)，没命中返回 None。"""
        if not self.enabled or not question.strip():
            return None
        jp, wp = self._json_path(question), self._wav_path(question)
        if not (jp.exists() and wp.exists()):
            return None
        try:
            meta = json.loads(jp.read_text(encoding="utf-8"))
            audio = wp.read_bytes()
        except Exception:
            return None
        meta["hits"] = int(meta.get("hits", 0)) + 1
        jp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta.get("a", ""), audio

    def put(self, question: str, answer: str, audio: bytes) -> None:
        if not self.enabled or not question.strip():
            return
        self._json_path(question).write_text(
            json.dumps({"q": question, "a": answer, "hits": 0}, ensure_ascii=False),
            encoding="utf-8",
        )
        self._wav_path(question).write_bytes(audio)

    def stats(self) -> dict:
        if not self.enabled:
            return {"entries": 0}
        metas = list(self.root.glob("*.json"))
        total_hits = 0
        for m in metas:
            try:
                total_hits += int(json.loads(m.read_text(encoding="utf-8")).get("hits", 0))
            except Exception:
                pass
        return {"entries": len(metas), "hits": total_hits}
