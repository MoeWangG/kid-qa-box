"""配置加载 + 模拟开关。

三个开关，互相独立。这是为了让你在 Mac 上能用真麦克风先把整条链路跑一遍：

  AIBOX_SIMULATE=1         音声和按键都假（全模拟，不需要任何硬件）
  AIBOX_SIMULATE_BUTTON=1  只把按键换成回车，音声用真的（★ Mac 上测真实链路用这个）
  AIBOX_SIMULATE_AUDIO=1   只把音声换成假的，按键用真的

provider 的 kind 是另一回事：mock 表示假数据不联网，volc/openai 表示真调接口。
"""

from __future__ import annotations

import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

SIMULATE = os.environ.get("AIBOX_SIMULATE") == "1"
SIMULATE_AUDIO = SIMULATE or os.environ.get("AIBOX_SIMULATE_AUDIO") == "1"
SIMULATE_BUTTON = SIMULATE or os.environ.get("AIBOX_SIMULATE_BUTTON") == "1"


def mode_label() -> str:
    if SIMULATE_AUDIO and SIMULATE_BUTTON:
        return "全模拟（音频+按键都是假的）"
    if SIMULATE_BUTTON:
        return "真音频 + 回车当按键"
    if SIMULATE_AUDIO:
        return "模拟音频 + 真按键"
    return "真实硬件"


def load(path: str | None = None, require_keys: bool = True) -> dict:
    p = pathlib.Path(path or os.environ.get("AIBOX_CONFIG") or ROOT / "config.json")
    if not p.exists():
        raise SystemExit(
            f"找不到配置文件：{p}\n"
            f"先复制一份再改：cp config.example.json config.json"
        )
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["_root"] = str(ROOT)
    cfg["_config_path"] = str(p)

    # 密钥单独放 secrets.json：这样 config.json 可以随时给他看/给我改，
    # 里面永远没有 key。两边都存在时 secrets.json 优先。
    secrets_path = pathlib.Path(
        os.environ.get("AIBOX_SECRETS") or (p.parent / "secrets.json")
    )
    cfg["_secrets_path"] = str(secrets_path)
    if secrets_path.exists():
        try:
            secrets = json.loads(secrets_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{secrets_path} 不是合法 JSON：{exc}")
        for section in ("asr", "llm", "tts"):
            # asr/tts 用百炼（dashscope_api_key），llm 用 DeepSeek（llm_api_key）；
            # 也兼容全套阿里云时只填一个 dashscope_api_key 的写法。
            value = secrets.get(f"{section}_api_key") or secrets.get(
                "dashscope_api_key"
            )
            if value:
                cfg.setdefault(section, {})["api_key"] = value
        if secrets.get("tts_voice"):
            cfg.setdefault("tts", {})["voice"] = secrets["tts_voice"]

    for section in ("asr", "llm", "tts"):
        if section not in cfg:
            raise SystemExit(f"config.json 缺少 {section} 段")
        _validate_section(section, cfg[section], require=require_keys)
    return cfg


def mask(secret: str) -> str:
    """把密钥变成可安全展示的形式。只露首尾 4 位，中间打码。"""
    s = str(secret or "")
    if not s:
        return "(空)"
    if "REPLACE" in s:
        return f"未填（还是占位符 {s}）"
    if len(s) <= 8:
        return "*" * len(s) + f"（{len(s)} 位，太短，可能不对）"
    return f"{s[:4]}…{s[-4:]}（{len(s)} 位）"


def _validate_section(name: str, conf: dict, require: bool = True) -> None:
    """按 kind 校验必填项。不同厂商要的东西不一样，不能一律查 api_key。

    require=False 时只检查 kind 合法性，不要求 key 已填 ——
    看日志、看设备列表这类操作不应被“key 没填”拦住。
    """
    kind = conf.get("kind", "openai")
    if kind == "mock":
        return
    if kind not in ("openai", "volc", "ali"):
        raise SystemExit(
            f"config.json 里 {name}.kind = {kind!r} 不认识（支持 openai / volc / ali / mock）"
        )
    if not require:
        return

    if kind == "openai":
        key = str(conf.get("api_key", ""))
        if not key or "REPLACE" in key:
            raise SystemExit(f"config.json 里 {name}.api_key 还没填（当前值：{key!r}）")
        if not conf.get("base_url"):
            raise SystemExit(f"config.json 里 {name}.base_url 是空的")
        if not conf.get("model"):
            raise SystemExit(f"config.json 里 {name}.model 是空的")
        return

    if kind == "volc":
        for field in ("appid", "access_token"):
            val = str(conf.get(field, ""))
            if not val or "REPLACE" in val:
                raise SystemExit(
                    f"config.json 里 {name}.{field} 还没填（当前值：{val!r}）\n"
                    "  火山控制台 → 语音技术 → 应用管理，能看到 AppID 和 Access Token"
                )
        if name == "tts" and str(conf.get("voice", "")).startswith("REPLACE"):
            raise SystemExit(
                "config.json 里 tts.voice（音色 ID）还没填\n"
                "  火山控制台 → 语音合成 → 音色列表，抄一个 voice_type"
            )
        return

    if kind == "ali":
        key = str(conf.get("api_key", ""))
        if not key or "REPLACE" in key:
            raise SystemExit(
                f"config.json 里 {name}.api_key 还没填（当前值：{key!r}）\n"
                "  百炼控制台 → API-KEY 管理（bailian.console.aliyun.com）"
            )
        if name == "tts" and str(conf.get("voice", "")).startswith("REPLACE"):
            raise SystemExit(
                "config.json 里 tts.voice（音色 ID）还没填\n"
                "  百炼 → 模型广场 → 语音合成 → 音色列表，形如 longxiaochun_v2"
            )
        return

    raise SystemExit(
        f"config.json 里 {name}.kind = {kind!r} 不认识（支持 openai / volc / mock）"
    )


def banner(cfg: dict) -> None:
    print("=" * 56)
    print(f"配置   : {cfg['_config_path']}")
    print(f"密钥   : {cfg.get('_secrets_path')} " + ("✓" if pathlib.Path(cfg.get('_secrets_path', '')).exists() else "✗ 不存在"))
    print(f"模式   : {mode_label()}")
    for section in ("asr", "llm", "tts"):
        conf = cfg.get(section, {})
        kind = conf.get("kind", "openai")
        if kind == "mock":
            desc = "mock（假数据）"
        elif kind == "volc":
            desc = f"volc  appid={conf.get('appid')}"
            if section == "tts":
                desc += f" voice={conf.get('voice')}"
        elif kind == "ali":
            desc = f"ali   {conf.get('model')}"
            if section == "tts":
                desc += f" voice={conf.get('voice')}"
        else:
            desc = f"openai {conf.get('base_url')} model={conf.get('model')}"
        print(f"{section.upper():<7}: {desc}")
    print("=" * 56)
