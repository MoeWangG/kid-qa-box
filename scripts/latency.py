"""latency —— 逐条看每次对话到底花了多久。

和 log_report.py 的分工：
  log_report.py  看「孩子问了什么、效果如何」（内容视角，聚合）
  latency.py     看「每次回答花了多久」（性能视角，逐条）

用法：
    python3 scripts/latency.py                # 最近 20 条
    python3 scripts/latency.py --last 50
    python3 scripts/latency.py --all
    python3 scripts/latency.py --path /home/jeff/ai-qa-box/aibox.jsonl

列的含义：
  耗时   松手 → 播完（e2e_sec，整段音频播完才算完）
  识别   录音上传 + 转文字（asr_sec）
  录音   这次按了多久（rec_sec）
  缓存   hit = 没走大模型和 TTS，直接播本地音频，所以特别快
"""

import _bootstrap  # noqa: F401

import argparse
import json
import pathlib
import statistics

from aibox.config import load


def _f(v, unit="s"):
    if v is None:
        return "-"
    try:
        return f"{float(v):.2f}{unit}"
    except (TypeError, ValueError):
        return "-"


def _clip(s, n=26):
    s = str(s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=20, help="只看最近 N 条，默认 20")
    ap.add_argument("--all", action="store_true", help="全部")
    ap.add_argument("--path", default=None, help="日志路径，默认读 config 里的 log_path")
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

    total = len(rows)
    shown = rows if args.all else rows[-args.last :]

    print("=" * 78)
    print(f"日志：{path}")
    print(f"共 {total} 条，显示 {len(shown)} 条"
          + ("" if args.all else f"（--all 看全部）"))
    print("=" * 78)
    print(f"{'#':>4}  {'时间':<19}  {'耗时':>7}  {'识别':>6}  {'录音':>6}  {'缓存':<4}  问题")
    print("-" * 78)
    base = total - len(shown)
    for i, r in enumerate(shown, start=base + 1):
        print(
            f"{i:>4}  {str(r.get('ts', '?')):<19}  "
            f"{_f(r.get('e2e_sec')):>7}  {_f(r.get('asr_sec')):>6}  "
            f"{_f(r.get('rec_sec')):>6}  "
            f"{'hit' if r.get('cache') else ('ERR' if r.get('error') else 'miss'):<4}  "
            f"{_clip(r.get('q'))}"
        )

    ok = [r for r in rows if r.get("e2e_sec") is not None and not r.get("error")]
    e2e = [float(r["e2e_sec"]) for r in ok]
    asr = [float(r["asr_sec"]) for r in ok if r.get("asr_sec") is not None]
    rec = [float(r["rec_sec"]) for r in ok if r.get("rec_sec") is not None]
    hits = sum(1 for r in rows if r.get("cache"))
    errs = sum(1 for r in rows if r.get("error"))

    print("-" * 78)
    if not e2e:
        print("没有一条成功的记录，先看 step6/step7 的报错。")
        return

    print(f"\n成功 {len(ok)} 条 / 失败 {errs} 条 / 缓存命中 {hits} 条 "
          f"（{hits / max(len(rows), 1) * 100:.0f}%）")
    print(f"耗时   中位 {statistics.median(e2e):.2f}s   "
          f"P90 {pct(e2e, 0.9):.2f}s   "
          f"最快 {min(e2e):.2f}s   最慢 {max(e2e):.2f}s   "
          f"平均 {statistics.mean(e2e):.2f}s")
    if asr:
        print(f"识别   中位 {statistics.median(asr):.2f}s   "
              f"P90 {pct(asr, 0.9):.2f}s")
    if rec:
        print(f"录音   中位 {statistics.median(rec):.2f}s   "
              f"平均 {statistics.mean(rec):.2f}s")

    miss = [float(r["e2e_sec"]) for r in ok if not r.get("cache")]
    if miss and hits:
        h = [float(r["e2e_sec"]) for r in ok if r.get("cache")]
        print(f"缓存   命中时中位 {statistics.median(h):.2f}s  vs  "
              f"未命中时中位 {statistics.median(miss):.2f}s")

    print("\n注：耗时是「松手 → 整段播完」。日志里没有记「第一次开口」的时间点，"
          "\n    想量 1s 那个数，得在 device.py 里把首段音频的时间也写进日志。")


if __name__ == "__main__":
    main()
