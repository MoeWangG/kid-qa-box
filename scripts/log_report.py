"""log_report —— 读 aibox.jsonl，看孩子这两周到底问了什么、效果如何。

用法：
    python3 scripts/log_report.py
    python3 scripts/log_report.py --tail 20      # 顺便看最近 20 条原文
"""

import _bootstrap  # noqa: F401

import argparse
import collections
import json
import pathlib
import statistics
from datetime import datetime

from aibox.config import load


def pct(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(round((p / 100) * (len(values) - 1))))
    return values[idx]


def session_lengths(ok: list, gap_minutes: int = 5) -> list[int]:
    """按时间间隔切会话，返回每个会话的轮数。

    间隔 > gap_minutes 当成新话题。这个数直接告诉你 history_turns 该设多少：
    如果最长会话只有 6 轮，设 20 就是白摆。
    """
    sessions: list[list] = []
    cur: list = []
    prev = None
    for row in ok:
        try:
            ts = datetime.strptime(row["ts"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            continue
        if prev is not None and (ts - prev).total_seconds() > gap_minutes * 60:
            if cur:
                sessions.append(cur)
            cur = []
        cur.append(row)
        prev = ts
    if cur:
        sessions.append(cur)
    return [len(s) for s in sessions]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tail", type=int, default=0, help="打印最近 N 条原文")
    ap.add_argument("--path", default=None)
    args = ap.parse_args()

    cfg = load(require_keys=False)
    raw = args.path or (cfg.get("runtime") or {}).get("log_path") or "aibox.jsonl"
    path = pathlib.Path(raw)
    if not path.is_absolute():
        path = pathlib.Path(cfg["_root"]) / str(path).lstrip("./")

    if not path.exists():
        print(f"还没有日志：{path}")
        print("跑过 step6/step7 之后才会有。")
        return

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not rows:
        print("日志是空的。")
        return

    ok = [r for r in rows if r.get("q") and not r.get("error")]
    err = [r for r in rows if r.get("error")]

    print("=" * 56)
    print(f"日志：{path}")
    print(f"时间范围：{rows[0].get('ts', '?')} → {rows[-1].get('ts', '?')}")
    print("=" * 56)

    print(f"\n总交互       : {len(rows)} 次")
    print(f"成功         : {len(ok)} 次")
    print(f"失败         : {len(err)} 次" + (f"（{len(err)/len(rows)*100:.1f}%）" if rows else ""))
    if err:
        kinds = collections.Counter(r["error"].split(":")[0] for r in err)
        for k, v in kinds.most_common(5):
            print(f"    {k}: {v}")

    if ok:
        e2e = [r["e2e_sec"] for r in ok if "e2e_sec" in r]
        asr = [r["asr_sec"] for r in ok if "asr_sec" in r]
        rec = [r["rec_sec"] for r in ok if "rec_sec" in r]
        hits = sum(1 for r in ok if r.get("cache"))

        if e2e:
            print(f"\n端到端耗时   : 中位 {statistics.median(e2e):.2f}s  "
                  f"P90 {pct(e2e, 90):.2f}s  最慢 {max(e2e):.2f}s")
        if asr:
            print(f"识别耗时     : 中位 {statistics.median(asr):.2f}s")
        if rec:
            print(f"说话时长     : 中位 {statistics.median(rec):.2f}s")
        print(f"缓存命中     : {hits} 次（{hits/len(ok)*100:.0f}%）")

        # 归一化后统计重复问题（跟 cache 的规则一致）
        drop = " \t，。、？！,?!.…~～—-\"'“”‘’"
        def norm(s):
            return "".join(ch for ch in s if ch not in drop).lower()

        counter = collections.Counter(norm(r["q"]) for r in ok)
        uniq = len(counter)
        print(f"独立问题     : {uniq} 个 / 共 {len(ok)} 次")

        repeats = [(q, c) for q, c in counter.most_common(8) if c > 1]
        if repeats:
            print("\n问得最多的（重复 = 缓存的收益）：")
            raw = {norm(r["q"]): r["q"] for r in ok}
            for q, c in repeats:
                print(f"  {c:>2}×  {raw.get(q, q)[:40]}")

        if uniq:
            print(f"\n重复率       : {(len(ok) - uniq) / len(ok) * 100:.0f}% 的提问是重复的")
            if (len(ok) - uniq) / len(ok) > 0.3:
                print("  → 重复率 >30%，缓存值得保留，也可以考虑把高频答案预生成")
            else:
                print("  → 重复率低，说明孩子问得很发散，缓存收益有限")

        lens = session_lengths(ok)
        if lens:
            dist = collections.Counter(lens)
            longest = max(lens)
            print(f"\n会话数       : {len(lens)} 个（间隔 >5 分钟算新话题）")
            print(f"平均轮数     : {statistics.mean(lens):.1f} 轮")
            print(f"最长会话     : {longest} 轮")
            print("轮数分布     : " + "  ".join(f"{k}轮×{v}" for k, v in sorted(dist.items())))
            suggest = max(6, longest + 2)
            if longest <= 12:
                print(f"\n→ 实测最长 {longest} 轮，history_turns 设 {suggest} 就够。"
                      f"设 20 也行，但不产生效果，只多花钱。")
            else:
                print(f"\n→ 实测最长 {longest} 轮，20 轮合适。"
                      "长期会话多的话，值得上服务器版（可做摘要压缩）。")

    if args.tail:
        print(f"\n最近 {args.tail} 条原文：")
        for r in rows[-args.tail:]:
            if r.get("error"):
                print(f"  [{r.get('ts')}] ✗ {r['error'][:80]}")
            else:
                print(f"  [{r.get('ts')}] 问：{r.get('q', '')}")
                print(f"                 答：{str(r.get('a', ''))[:60]}")


if __name__ == "__main__":
    main()
