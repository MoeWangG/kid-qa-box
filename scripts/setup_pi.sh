#!/usr/bin/env bash
# 树莓派一键装依赖。
#   bash scripts/setup_pi.sh
#
# 兼容 Debian 12 (bookworm) 和 Debian 13 (trixie)：
# 有些 python3-xxx 包在新发行版里可能改名或缺失，所以这里逐个装，
# 装不上的用 pip 兜底，不会因为一个包失败就整体中断。
set -uo pipefail

cd "$(dirname "$0")/.."
echo "工作目录：$(pwd)"
if [ -f /etc/os-release ]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  echo "系统：${PRETTY_NAME:-unknown}  架构：$(uname -m)"
fi

# ---------------------------------------------------------------- 1. 系统包
echo
echo "==> 1/4 安装系统包（需要 sudo 密码）"
sudo apt update || { echo "  ✗ apt update 失败，先解决网络/换源"; exit 1; }

# 必须用 apt 的（系统库/工具，pip 装不了）
HARD_DEPS=(libportaudio2 alsa-utils python3-pip python3-venv)
# 能用 pip 兜底的 Python 包
PY_DEPS=(python3-requests python3-numpy python3-sounddevice python3-gpiozero python3-lgpio)

MISSING=()
for pkg in "${HARD_DEPS[@]}" "${PY_DEPS[@]}"; do
  if sudo apt install -y -q "$pkg" >/dev/null 2>&1; then
    echo "  ✓ $pkg"
  else
    echo "  ✗ $pkg（稍后用 pip 兜底）"
    MISSING+=("$pkg")
  fi
done

for pkg in "${HARD_DEPS[@]}"; do
  for m in "${MISSING[@]:-}"; do
    if [ "$m" = "$pkg" ]; then
      echo
      echo "  ! $pkg 装不上。这是系统库，pip 装不了。"
      echo "    检查 apt 源是否正常：sudo apt update 有没有报错"
      echo "    实在不行换源（清华）：见 README 第 4 节"
    fi
  done
done

# ---------------------------------------------------------------- 2. pip 兜底
echo
echo "==> 2/4 用 pip 补齐 apt 没装上的 Python 包"
pip_install() {
  local mod="$1"
  if python3 -c "import $mod" 2>/dev/null; then
    echo "  ✓ $mod 已可用"
    return 0
  fi
  echo "  … 装 $mod"
  if python3 -m pip install --user --quiet "$mod" 2>/dev/null; then
    echo "  ✓ $mod（--user）"
  elif python3 -m pip install --user --quiet --break-system-packages "$mod" 2>/dev/null; then
    echo "  ✓ $mod（--user --break-system-packages）"
  else
    echo "  ✗ $mod 装不上"
    return 1
  fi
}
pip_install requests || true
pip_install numpy || true
pip_install sounddevice || true
pip_install gpiozero || true
pip_install dashscope || true
# lgpio 是 gpiozero 的后端，pip 包名就叫 lgpio（需要编译，apt 优先）
python3 -c "import lgpio" 2>/dev/null || pip_install lgpio || true

# ---------------------------------------------------------------- 3. 自检
echo
echo "==> 3/4 检查依赖能否 import"
python3 - <<'PY'
import sys
mods = ["requests", "numpy", "sounddevice", "gpiozero", "dashscope"]
ok = True
for m in mods:
    try:
        __import__(m)
        print(f"  ✓ {m}")
    except Exception as e:
        ok = False
        print(f"  ✗ {m}: {e}")
try:
    import lgpio  # noqa: F401
    print("  ✓ lgpio（按键后端）")
except Exception as e:
    print(f"  ? lgpio 不可用：{e}  → 按键那一步会失败，见 README 排错")
if not ok:
    print("\n有包没装上。退路：venv 路线（见 README 5.2）")
raise SystemExit(0)
PY

# ---------------------------------------------------------------- 4. 配置
echo
echo "==> 4/4 准备 config.json"
if [ -f config.json ]; then
  echo "  config.json 已存在，跳过"
elif [ -f config.example.json ]; then
  cp config.example.json config.json
  echo "  已生成 config.json（不含任何密钥）"
fi
echo
echo "音频设备："
arecord -l 2>/dev/null || echo "  （没有可用录音设备 —— 声卡插了吗？）"
echo
aplay -l 2>/dev/null || true

cat <<'TIP'

完成。接下来：
  1. python3 scripts/set_keys.py      输 key（不回显）
  2. python3 scripts/selftest.py      确认代码没问题
  3. python3 scripts/probe_ali.py     确认语音接口通了
  4. python3 scripts/step1_loopback.py --devices   看声卡序号

全都没装上时的退路（venv）：
  sudo apt install -y python3-venv libportaudio2
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install requests sounddevice numpy dashscope
  之后所有 python3 换成 .venv/bin/python
TIP
