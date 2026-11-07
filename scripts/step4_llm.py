"""step4 —— 只测大模型：打字提问，看回答风格对不对。

这一步不需要麦克风、不需要喇叭，不需要树莓派。在 Mac 上就能调。
重点是调 config.json 里的 system_prompt，直到回答又短又适合孩子听。

用法：
    python3 scripts/step4_llm.py                  # 进入连续对话
    python3 scripts/step4_llm.py 为什么天是蓝的     # 只问一句
"""

import _bootstrap  # noqa: F401

import sys
import time

from aibox.config import banner, load
from aibox.providers import chat


def main() -> None:
    cfg = load()
    banner(cfg)
    turns = int(cfg.get("runtime", {}).get("history_turns", 3))

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
        t = time.perf_counter()
        answer = chat(cfg, question)
        print(f"\n耗时 {time.perf_counter() - t:.2f}s / {len(answer)} 字")
        print(f"回答：{answer}\n")
        print("检查三点：① 超过 60 字了吗 ② 有 markdown/符号吗 ③ 孩子听得懂吗")
        return

    history: list = []
    print("连续对话模式。空行退出。\n")
    while True:
        try:
            q = input("问：").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not q:
            break
        t = time.perf_counter()
        a = chat(cfg, q, history)
        print(f"答（{time.perf_counter() - t:.2f}s / {len(a)} 字）：{a}\n")

        history += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
        limit = max(1, turns) * 2
        if len(history) > limit:
            del history[: len(history) - limit]

    print("退出。")


if __name__ == "__main__":
    main()
