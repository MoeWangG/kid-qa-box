"""set_prompt —— 换 system_prompt，按问题类型分档控制回答长度。

为什么不写死"不超过 35 字"：事实类问题是"1949 年"这种 6 个字的，
原因类问题需要 40 多字才讲得清。一刀切要么太啰嗦，要么讲不明白。

用法：
    python3 scripts/set_prompt.py          # 应用下面的 PROMPT
    python3 scripts/set_prompt.py --show   # 只看当前用的
"""

import _bootstrap  # noqa: F401

import json
import pathlib
import sys

from aibox.config import ROOT

PROMPT = """你是给 6-10 岁小朋友用的语音问答助手。

怎么回答：
1. 先用一句话给出答案，再补一句"为什么"。每答都要给原因，不能只说结论。
2. 用她能看见、摸得着的东西打比方。最多一个比方。
3. 一件事如果有很多层原因，只说最主要的那一层。她要是继续问，再往下讲。
4. 答完可以补一句很短的钩子，比如"你觉得呢""你想不想试试"，
   但不要每次都用，别把聊天变成提问。

关于真实世界：
- 不说假话，也不吓人。遇到穷、病、死、吵架、不公平这类事，
  用"有的人……有的人……"把原因讲清楚，不下好坏判断。
- 你也不知道的，直接说"这个我不知道"。

说话要求：
- 只输出要念出来的字：不要 markdown、不要括号、不要表情符号、不要列表。
- 不铺垫、不反问她的问题、不说"好问题"这种客套。

绝对不要猜你不知道的事：今天天气、现在几点、最近新闻、比赛比分。"""


def main() -> None:
    path = ROOT / "config.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))

    if "--show" in sys.argv:
        print(cfg["llm"]["system_prompt"])
        return

    cfg["llm"]["system_prompt"] = PROMPT
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"✓ 已更新 system_prompt（{len(PROMPT)} 字）\n")
    print(PROMPT)
    print("\n验证：用这几句各问一次，看长度对不对")
    print("  python3 scripts/step4_llm.py 新中国哪年成立的")
    print("  python3 scripts/step4_llm.py 为什么天是蓝的")
    print("  python3 scripts/step4_llm.py 我睡不着怎么办")
    print("  python3 scripts/step4_llm.py 今天天气怎么样")


if __name__ == "__main__":
    main()
