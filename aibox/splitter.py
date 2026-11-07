"""流式切句。

LLM 吐 token 是碎的（"因为阳光穿过" / "空气的时候，"），必须攒够一句才能送 TTS，
否则 TTS 会把半句话念成奇怪的语调，而且请求次数暴涨。

规则：只认中文句号和叹问号 + 换行。不认英文句点，因为 "3.14" "1.5米" 会被它切坏。
"""

from __future__ import annotations

ENDS = "。！？!?\n；;"      # 强切点：见到就切
WEAK = "，、,:："          # 弱切点：只有攒够长度才在它这里切

# 太短的片段不单独送 TTS（"好。" 这种，合并到下一句更自然）
MIN_LEN = 4

# 弱切：这么长还没遇到句号，就在最后一个逗号处先开口，不然孩子要等一整个长句
WEAK_MIN = 16


class SentenceSplitter:
    def __init__(self, min_len: int = MIN_LEN):
        self.buf = ""
        self.min_len = min_len
        self._pending = ""  # 攒着太短的句子

    def feed(self, delta: str) -> list[str]:
        self.buf += delta
        out: list[str] = []
        while True:
            pos = -1
            for i, ch in enumerate(self.buf):
                if ch in ENDS:
                    pos = i
                    break
            if pos < 0:
                break
            piece = (self._pending + self.buf[: pos + 1]).strip()
            self.buf = self.buf[pos + 1 :]
            self._pending = ""
            if not piece:
                continue
            if len(piece) < self.min_len:
                self._pending = piece
                continue
            out.append(piece)

        # 弱切：长句里只在逗号处断一小段，让语气更自然，也更快开口
        if len(self.buf) >= WEAK_MIN:
            cut = -1
            for ch in WEAK:
                cut = max(cut, self.buf.rfind(ch))
            if cut >= MIN_LEN:
                piece = (self._pending + self.buf[: cut + 1]).strip()
                self._pending = ""
                self.buf = self.buf[cut + 1 :]
                if piece:
                    out.append(piece)

        # 边界情况：模型一直不吐标点，攒到很长也要强行切，否则永远不开口
        if len(self.buf) >= 30:
            piece = (self._pending + self.buf).strip()
            self.buf = ""
            self._pending = ""
            if piece:
                out.append(piece)
        return out

    def flush(self) -> list[str]:
        rest = (self._pending + self.buf).strip()
        self.buf = ""
        self._pending = ""
        return [rest] if rest else []
