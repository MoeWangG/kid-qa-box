"""set_keys —— 交互式写入密钥，输入不回显，文件权限 600。

两个 key：
    百炼（阿里云）  → ASR + TTS
    DeepSeek        → 大模型

两个文件，职责分开：
    config.json   非密钥配置（模型名、prompt、GPIO、设备号、音色）
    secrets.json  只有 API key

好处：config.json 可以随便给人看、给 AI 改，里面永远没有 key。

用法：
    python3 scripts/set_keys.py             # 交互式填/改
    python3 scripts/set_keys.py --status    # 只看状态（掩码，可以安全贴出来）
"""

import _bootstrap  # noqa: F401

import argparse
import getpass
import json
import os
import pathlib
import stat
import sys

from aibox.config import ROOT, mask


def load_json(path: pathlib.Path, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path} 不是合法 JSON：{exc}")


def write_hardened(path: pathlib.Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 600
    except OSError as exc:
        print(f"  ! 改权限失败：{exc}")


def migrate(config: dict, secrets: dict) -> list[str]:
    """把旧格式收拾成 asr_api_key / tts_api_key / llm_api_key。"""
    moved = []

    # config.json 里残留的明文 key
    for section in ("asr", "llm", "tts"):
        conf = config.get(section) or {}
        old = conf.pop("api_key", None)
        if old and "REPLACE" not in str(old):
            key = f"{section}_api_key"
            if not secrets.get(key):
                secrets[key] = old
                moved.append(f"config.json 的 {section}.api_key")

    # 单 key 写法 -> asr/tts
    unified = secrets.pop("dashscope_api_key", None)
    if unified:
        if not secrets.get("asr_api_key"):
            secrets["asr_api_key"] = unified
        if not secrets.get("tts_api_key"):
            secrets["tts_api_key"] = unified
        moved.append("dashscope_api_key")

    return moved


def show_status(config: dict, secrets: dict, cfg_path: pathlib.Path, sec_path: pathlib.Path) -> None:
    print(f"配置：{cfg_path}")
    print(f"密钥：{sec_path}")
    for path in (cfg_path, sec_path):
        if path.exists():
            mode = stat.S_IMODE(path.stat().st_mode)
            warn = "" if mode <= 0o600 else "  ⚠ 建议 600"
            print(f"  {path.name:<14} {oct(mode)}{warn}")
    print()

    ali = secrets.get("asr_api_key")
    ds = secrets.get("llm_api_key")
    rows = [
        ("百炼 key", ali, True),
        ("DeepSeek key", ds, True),
        ("asr.model", (config.get("asr") or {}).get("model"), False),
        ("llm.model", (config.get("llm") or {}).get("model"), False),
        ("llm.base_url", (config.get("llm") or {}).get("base_url"), False),
        ("tts.model", (config.get("tts") or {}).get("model"), False),
        ("tts.voice", (config.get("tts") or {}).get("voice"), False),
    ]
    for name, value, secret in rows:
        print(f"  {name:<14}: {mask(value) if secret else (value or '(空)')}")

    missing = [n for n, v, s2 in rows if s2 and not v]
    if missing:
        print(f"\n⚠ 还没填：{', '.join(missing)}")
    print("\n上面这个输出可以安全贴出来 —— key 只露首尾 4 位。")


def ask(prompt: str, current: str | None, secret: bool) -> str | None:
    hint = f"（当前 {mask(current)}，回车不改）" if current else "（回车跳过）"
    try:
        if secret:
            value = getpass.getpass(f"{prompt} {hint}: ")
        else:
            value = input(f"{prompt} {hint}: ")
    except (EOFError, KeyboardInterrupt):
        print("\n中断，什么都没改。")
        sys.exit(1)
    return value.strip() or None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true", help="只显示状态，不修改")
    ap.add_argument("--config", default=None, help="config.json 路径")
    ap.add_argument("--keys", default=None, help="密钥文件路径")
    args = ap.parse_args()

    cfg_path = pathlib.Path(args.config) if args.config else ROOT / "config.json"
    sec_path = pathlib.Path(args.keys) if args.keys else ROOT / "secrets.json"

    if not cfg_path.exists():
        example = ROOT / "config.example.json"
        if not example.exists():
            raise SystemExit(f"找不到 {example}")
        cfg_path.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"已从 config.example.json 生成 {cfg_path.name}")

    config = load_json(cfg_path, {})
    secrets = load_json(sec_path, {})

    if args.status:
        show_status(config, secrets, cfg_path, sec_path)
        return

    moved = migrate(config, secrets)
    if moved:
        print(f"已整理：{', '.join(moved)}")

    print("=" * 60)
    print("需要两个 key。输入时不显示是正常的。回车 = 跳过不改。")
    print("=" * 60)

    ali = ask("百炼 API-KEY（语音用）", secrets.get("asr_api_key"), True)
    if ali:
        secrets["asr_api_key"] = ali
        secrets["tts_api_key"] = ali

    voice = ask(
        "百炼音色 ID（非密钥，形如 longxiaochun_v2）",
        (config.get("tts") or {}).get("voice"),
        False,
    )
    if voice:
        config.setdefault("tts", {})["voice"] = voice

    ds = ask("DeepSeek API-KEY（大模型用）", secrets.get("llm_api_key"), True)
    if ds:
        secrets["llm_api_key"] = ds

    write_hardened(sec_path, secrets)
    cfg_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(cfg_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass

    print(f"\n已写入：{sec_path.name}（600）、{cfg_path.name}")
    print("复核（这段可以安全贴出来）：\n")
    show_status(config, secrets, cfg_path, sec_path)
    print("\n下一步：python3 scripts/probe_ali.py")


if __name__ == "__main__":
    main()
