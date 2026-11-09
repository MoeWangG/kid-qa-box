# 给孩子做的 AI 问答机 · 树莓派 3B

> 按一下按钮 → 说话 → 松手 → 它回答你。
> 一个不会打字的小学生，也能自己把「为什么」问到底。

一台放在孩子桌上的语音问答机：**树莓派 3B + USB 声卡 + 小音箱 + 一个大按钮**。
按一下说话，松手后 1.5~2.5 秒听到答案。没有屏幕，没有唤醒词。

| | |
|---|---|
| 硬件成本 | ¥100~200（不含树莓派本体） |
| 使用成本 | **约 2 分钱一次问答**，每月约 20 元 |
| 技术栈 | Python + 阿里云百炼（语音）+ DeepSeek（大模型） |
| 智能在哪 | 全在云端；3B 只负责按键、录音、放音 |
| 代码来源 | 几乎全部由 AI 辅助写成 —— 所以这份文档是写给「不一定会写代码的人」的 |

## 为什么不用现成的智能音箱

唤醒词对小学生是灾难：发音不准、天天误唤醒，而且「机器什么时候在听」这件事他说了不算。

**用一个大按钮，把「什么时候说话」的决定权交给孩子。** 这个选择决定了后面所有的设计。

## 这台机器不做什么（设计原则，比技术选型重要）

- **没有屏幕** —— 不抢他的眼睛
- **没有唤醒词** —— 不存在「一直在听、等你叫它」的状态
- **不假装是人** —— 系统提示里明确禁止它说「想你」「宝贝」这类话。它是工具，爸爸才是爸爸
- **录音不留档** —— 声音只在内存里，识别完就丢；本机长期留下的只有文字日志（`aibox.jsonl`），随时可删

> 说清楚一件事：语音识别是云端服务，**音频必然经过厂商接口**，这点无法避免。
> 「不留档」指的是不落在你自己的磁盘上、不留在你的存储里。

---

# 0. 一页看懂

## 这套东西长什么样

```
┌──────────────── 树莓派 3B ────────────────┐
│                                           │
│  按钮 ──GPIO17──┐                          │
│                 │                          │
│  USB声卡 ←── 麦克风                        │
│     │                                     │
│     └──────→ 小音箱                        │
│                                           │
│  Python: 常开录音流 + 按键循环              │
└──────────────────┬────────────────────────┘
                   │ WiFi / 网线
                   ▼
        ┌──────────────────────┐
        │  ASR → LLM → TTS     │   全在云端
        └──────────────────────┘
```

树莓派 3B 只干三件事：按键、录音、放音。**所有智能都在云上**。
3B 的 1GB 内存跑不动本地语音模型，这是硬约束，不要试。

## 两条链路，先慢后快

| | 档 A（step6） | 档 A+（step7） |
|---|---|---|
| 怎么跑 | 全部串行，等一段完再下一段 | 大模型边吐，语音边合成边播 |
| 端到端 | 3~5 秒 | 1.5~2.5 秒 |
| 代码 | `answer_oneshot` | `answer_stream` |
| 用途 | 先确认每一步都对 | 日常用这个 |

**同一个按键循环，只差一个参数。** 所以你在 step6 验证过的东西，切到 step7 不会变形。

## 目录

```
ai-qa-box/
├── README.md                  ← 项目概览（先看这个）
├── docs/guide.md              ← 你在看的：完整搭建手册
├── config.example.json        ← 配置模板（非密钥）
├── secrets.json               ← 只有 API key，自己生成，不进 git
├── requirements.txt
├── aibox/                     ← 库
│   ├── config.py              配置加载 + 模拟模式
│   ├── audio.py               常开录音流 / WAV 播放
│   ├── button.py              按键（真机 gpiozero / 模拟回车）
│   ├── providers.py           ASR / LLM / TTS 分发
│   ├── providers_ali.py       阿里云百炼语音（ASR/TTS，默认）
│   ├── providers_volc.py      火山引擎语音（备选）
│   ├── errors.py              统一异常
│   ├── splitter.py            流式切句
│   ├── cache.py               答案缓存
│   ├── pipeline.py            两条链路
│   └── device.py              主循环
├── scripts/
│   ├── setup_pi.sh            树莓派一键装依赖
│   ├── selftest.py            不用硬件不用网络，验证代码
│   ├── probe_ali.py           ★ 只测阿里云（默认走这个）
│   ├── probe_volc.py          只测火山（备选）
│   ├── log_report.py          看孩子问了什么、效果如何
│   ├── step0_api.py           ★ 只测云端
│   ├── step1_loopback.py      ★ 只测声卡
│   ├── step2_button.py        ★ 只测按键
│   ├── step3_asr.py           按键 → 打印识别文本
│   ├── step4_llm.py           打字 → 打印回答
│   ├── step5_tts.py           打字 → 出声
│   ├── step6_main.py          ★ 全链路，串行
│   └── step7_stream.py        ★ 全链路，流式（日常用这个）
└── deploy/aibox.service       开机自启
```

---

# 1. 验收标准（先定死，否则会一直打磨）

## 「做完了」

- [ ] 孩子**自己**按 5 次，至少 4 次能听到完整答案
- [ ] 端到端（松手到出声）**≤ 3 秒**
- [ ] 连续通电 **2 小时**不崩、不需要重启
- [ ] 拔掉网线再插上，机器自己恢复（不用断电）

## 「能给孩子用」

- [ ] 放在桌上，孩子不用教就会按
- [ ] 声音够大，隔着房间能听见
- [ ] 回答不超过 60 字（超过就是 system_prompt 没调好）

## 建议的验证节奏

别一次全做完。按这个顺序，每一步都能独立判断：

| 阶段 | 判据 |
|---|---|
| 代码对不对 | `python3 scripts/selftest.py` 全绿（不用硬件、不用网） |
| 云端通不通 | `python3 scripts/probe_ali.py` 打出 `✓` |
| 全链路通不通 | `python3 scripts/step6_main.py` 能完整回答一句 |
| 能不能给孩子用 | 上面「做完了」那几条 |

---

# 2. 默认方案：为什么这么选

下面这些都是**只改 `config.json` 就能换掉的**，不是写死的。

## 2.1 云端：阿里云百炼语音 + DeepSeek

按你定的来：

| 能力 | 厂商 | 代码里的 kind | 确定性 |
|---|---|---|---|
| ASR | 阿里云百炼 | `ali` | 高（官方 SDK） |
| LLM | 阿里云百炼（通义千问） | `openai` | 高（OpenAI 兼容） |
| TTS | 阿里云百炼 | `ali` | 高（官方 SDK） |

**为什么阿里云这条路比火山稳：** 它有官方 Python SDK（`dashscope`），
WebSocket 协议、鉴权、重试、心跳全在 SDK 里。我不需要猜二进制帧和 header 名——
那些东西是火山那条路上唯一的不确定来源。

另一个实际收益：语音识别和语音合成都从同一个百炼账号出，只填一个 key，账单也只在一处。

> 但注意：**树莓派在家里走公网访问 DashScope，不会因为你云服务器在阿里云就走内网。**
> 同厂的实际好处是账号/SDK/账单统一，不是网络加速。

**火山还留着**：`providers_volc.py` 没删。哪天你觉得阿里云音色不满意，
把 `kind` 改成 `volc`、填上 appid/token、跑 `probe_volc.py` 就行。两套并存。

**想切成全阿里云（LLM 也用通义）**：`llm.kind` 保持 `openai`，
`base_url` 改 `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions`，
`api_key` 用同一个百炼 key，`model` 填 `qwen-plus` 之类。一个 key 全搞定。

## 2.2 多轮记忆：默认 20 轮 + 1500 字上限

```json
"runtime": {
  "history_turns": 20,
  "history_max_chars": 1500
}
```

**两个数是两道闸，不是重复：**

| 参数 | 作用 |
|---|---|
| `history_turns: 20` | 最多保留 20 轮（40 条消息） |
| `history_max_chars: 1500` | 总字符超 1500 就从头删，不管几轮 |

为什么需要第二个：**轮数控不了长度**。一轮可能是「嗯」（1 字），也可能是 400 字的长回答。
只有轮数上限，极端情况下会把窗口吃满；加了字符预算，最坏情况也可控。

实测：
- 30 轮短问答 → 保留 20 轮
- 10 轮各 400 字 → 自动裁到 3 轮 / 1206 字

**为什么不是 50 轮或更多**：DeepSeek 窗口 64K，技术上装得下。
但语音问答里超过 20 轮的对话基本不存在，而且每条 ASR 错误都会留在历史里污染后续回答。

**该设多少？两周后让数据说话** —— `scripts/log_report.py` 会告诉你实测最长会话几轮。

---

# 3. 买什么

> 价格是量级参考，随行就市，下单前自己核一遍。

| 件 | 建议 | 参考价 | 备注 |
|---|---|---|---|
| 树莓派 3B | 你已有 | — | |
| **USB 声卡** | CM108 芯片，带 3.5mm 麦口 + 耳机口 | ¥15~25 | **别用板载 3.5mm**，噪声大还爆音 |
| 麦克风 | 3.5mm 全向领夹麦 / 小振膜麦 | ¥15~40 | 灵敏度高的优先，孩子说话轻 |
| **有源小音箱** | USB 供电 + 3.5mm 输入，带音量旋钮 | ¥30~60 | 比自己接 PAM8403 功放省事，也安全 |
| 按钮 | 大颗带灯轻触/自复位按钮 | ¥5~15 | 直径 ≥ 16mm，孩子手指好按 |
| 杜邦线 | 母对母 10cm | ¥5 | |
| microSD | 16~32G，A1/A2 | ¥20~30 | 慢卡会让整机卡 |
| 电源 | **5V 2.5A 官方或同等** | ¥25~40 | 供电不足会表现为「WiFi 偶发卡顿」，最难查 |
| 外壳 | 纸盒/亚克力/3D 打印 | — | 第一版用纸盒，别做外壳 |

**总增量花费大概 ¥100~200。**

## 可选的加速件（先别买）

- USB 双频 WiFi 网卡（RTL8812AU）：3B 只有 2.4G 802.11n，抖动大。但先试网线。
- USB 免提会议麦（带回声消除）：几十到一两百，说话轻的孩子更友好。

## 接线

```
按钮一脚 ──── GPIO17（物理脚 11）
按钮另一脚 ── GND   （物理脚 9）

USB 声卡插任意 USB 口
麦克风插声卡粉色口（Mic In）
音箱插声卡绿色口（Line Out）
```

不需要外接电阻，`gpiozero` 用内部上拉。

> **接线前断电。** 3B 的 GPIO 没有保护，接错 5V 到 GPIO 会烧。

---

# 4. 装系统（约 30 分钟，大半在下载）

## 4.1 烧卡

1. 装 [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. 选系统：**Raspberry Pi OS Lite (32-bit)** —— 选 Lite，不要桌面；选 32-bit，3B 只有 1GB 内存，32 位更省
3. 点右下角齿轮，**先配好再烧**：
   - 主机名 `aibox`
   - 勾选「启用 SSH」，设置用户名密码（记住，下面都要用）
   - 配好 WiFi（国家 CN，2.4G 频段）
4. 烧完插卡、插网线（第一次强烈建议插网线）、上电

## 4.2 连上去

在 Mac 上：

```bash
ssh pi@aibox.local
```

`pi` 换成你设的用户名。连不上就：

```bash
# 用路由器后台找 IP，或者
ping aibox.local
ssh pi@192.168.1.xxx
```

## 4.3 先把系统弄干净

```bash
sudo apt update && sudo apt upgrade -y
sudo timedatectl set-timezone Asia/Shanghai
date                                    # 时间不对会让 API 签名/证书出问题
```

顺手关掉用不上的东西（3B 省点算力）：

```bash
sudo systemctl disable --now bluetooth avahi-daemon 2>/dev/null || true
```

> 如果 SSH 断了连不上，把 `avahi-daemon` 打开回来：`sudo systemctl enable --now avahi-daemon`

### 关掉 PipeWire（就这一条会让麦克风消失）

新版 Raspberry Pi OS 默认跑 PipeWire。它会占着 USB 声卡的录音设备，
表现是 `arecord -l` 里 `Subdevices: 0/1`（明明插着却不能用），
程序里报 "device busy" 或者干脆录到一片静音。

```bash
# 先看它是不是在跑
systemctl --user status pipewire pipewire-pulse wireplumber 2>/dev/null | grep Active

# 在跑就全关掉并永久 mask（这台机器不需要桌面音频服务）
systemctl --user mask --now pipewire pipewire-pulse wireplumber

# 拔插一次 USB 声卡，然后确认
arecord -l        # 应该看到 Subdevices: 1/1
aplay -l
```

> 如果 `systemctl --user` 报 "Failed to connect to bus"（SSH 会话里常见），
> 说明当前 shell 没有 user session。用 `sudo -u <你的用户名> XDG_RUNTIME_DIR=/run/user/$(id -u <用户名>) systemctl --user mask pipewire pipewire-pulse wireplumber`，
> 或者直接在树莓派桌面终端里跑一遍。

---

# 5. 装代码

## 5.1 传到树莓派

在 **Mac** 上，进到本项目目录的上一级：

```bash
cd <本项目所在目录>
scp -r ai-qa-box pi@aibox.local:~/
```

有 git 仓库的话更简单：

```bash
ssh pi@aibox.local
git clone <你的仓库地址> ~/ai-qa-box
```

## 5.2 装依赖

```bash
ssh pi@aibox.local
cd ~/ai-qa-box
bash scripts/setup_pi.sh
```

这个脚本会：装系统包 → 检查能否 import → 生成 `config.json` → 列出音频设备。

看到 `✓ requests / numpy / sounddevice / gpiozero` 全绿就对了。

**如果 apt 找不到某个包**（不同镜像有差异），改走 pip：

```bash
sudo apt install -y python3-venv libportaudio2
python3 -m venv --system-site-packages .venv
.venv/bin/pip install requests sounddevice numpy
# 之后所有命令用 .venv/bin/python 代替 python3
```

## 5.3 填配置（两个厂商，别搞混）

### 密钥用脚本输（重要）

```bash
python3 scripts/set_keys.py
```

它会问三样东西，**输入时不回显**（看不见是正常的），直接回车 = 跳过不改：

1. 百炼 API-KEY（asr 和 tts 自动用同一个）
2. 百炼音色 ID（这个不是密钥，会明文显示）
3. DeepSeek API-KEY

**写到哪里去：**

| 文件 | 装什么 | 权限 |
|---|---|---|
| `config.json` | 模型名、prompt、GPIO、设备号、音色 | 600 |
| `secrets.json` | **只有三个 API key** | 600 |

这个分离是有意的：**`config.json` 里永远没有密钥**。所以它可以随时给别人看、
贴到群里问问题、或者发给我改 —— 都不会泄密。

> **为什么不用 nano 改 key / 不把 key 写在命令行里：**
> - 写在命令行 → 进 `~/.bash_history`
> - 贴在聊天/截图 → 进第三方日志
> - `getpass` 输入 → key 只存在于内存和本地文件

### 看状态（这个输出可以安全贴出来）

```bash
python3 scripts/set_keys.py --status
```

```
  asr.api_key   : sk-a…9f2c（42 位）
  llm.api_key   : sk-d…77ab（35 位）
  tts.voice     : longxiaochun_v2
```

key 只露首尾 4 位。**遇到问题贴这个，别贴 config.json。**

### 非密钥字段用 nano 改

`llm.system_prompt`、`tts.model`、`asr.model`、`button.gpio`、`audio.*` 这些不是密钥，
直接用 `nano config.json` 改就行。

---

**具体填什么：**

### ① 百炼（ASR + TTS）

`asr` 和 `tts` 共用**同一个 `api_key`**（`sk-` 开头），脚本会自动填两处。

从哪拿：<https://bailian.console.aliyun.com> → 右上角 **API-KEY** → 创建。

⚠️ **两个容易搞错的点：**

1. **百炼的 key 和 DeepSeek 的 key 都是 `sk-` 开头**，贴错了一天也查不出来。
   `--status` 里看位数和首尾四位对不对。
2. **`tts.voice` 必须和 `tts.model` 匹配。** v1 的音色不能用在 v2 模型上，
   会报「voice not found」或直接返回空音频。

`tts.voice` 从哪拿：百炼 → **模型广场** → 搜「语音合成」→ 音色列表，形如 `longxiaochun_v2`。

### ② 大模型：不用单独配

全套阿里云，LLM 走 DashScope 的 OpenAI 兼容模式，**用的是同一个百炼 key**：

```
base_url: https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
model   : qwen-flash
```

如果控制台里没有 `qwen-flash`，把 `llm.model` 改成 `qwen-turbo`（更稳）或 `qwen-plus`（更强但慢）。

### ③ 设备（等 step1 拿到序号后再填）

`audio.input_device` / `audio.output_device`，先留 `null`。

## 5.4 密钥安全（别跳）

三条铁律：

| 不要 | 因为 |
|---|---|
| 把 key 贴在聊天/AI 对话里 | 会进模型请求上下文，可能被服务商日志留存 |
| 把 key 写在命令行参数里 | 会进 `~/.bash_history` |
| 截图 config.json 发人 | 等于直接给 key |

**已经泄露了怎么办：** 去控制台删除那个 key、重新生成一个，再跑一遍 `set_keys.py`。
这比事后排查省事得多。

**已做的防护：**

- ``config.json`` 里**不存在**任何 api_key，密钥全在 `secrets.json`
- 两个文件都在 `.gitignore` 里，不会被提交
- `set_keys.py` 自动 `chmod 600`
- 所有代码通过 `aibox.config.load()` 合并两个文件，key 只在内存里传给 SDK，
  不打印到日志（`banner()` 只显示模型名和音色，不显示 key）

**所以以后要改行为（prompt 太长、换个模型、改 GPIO）：**
直接用 `nano config.json` 改就行 —— 这个文件里没有任何密钥，可以放心给别人看。

## 5.5 先跑自检（不用网、不用硬件）

```bash
python3 scripts/selftest.py
```

全绿说明代码本身没问题。这一步我在 Mac 上验证过，你这边也应该全绿。

---

# 6. 一步一步测（这是主要工作）

**规矩：哪一步没过，就不要往下走。** 否则后面出问题你不知道是哪层的。

---

## 6.0 先在 Mac 上预演（不等树莓派）★

拿到百炼 key 和 DeepSeek key 之后，**不用等树莓派**——在 Mac 上就能把 90% 的东西验掉。
最大的不确定性（语音接口）在这里消掉，别留到树莓派上排查。

### ① 装依赖（Mac）

```bash
cd ~/Document/Try/try/ai-qa-box
pip3 install --user sounddevice numpy requests
```

> 如果报 `externally-managed-environment`（Homebrew 的 Python），改用：
> `python3 -m venv .venv && .venv/bin/pip install sounddevice numpy requests`，
> 之后命令里的 `python3` 换 `.venv/bin/python`。

### ② 填 config

```bash
cp config.example.json config.json
nano config.json
```

填 `asr`/`tts` 的 `api_key`（百炼 key，两处相同）+ `tts.voice`，以及 `llm.api_key`（DeepSeek）。

**`audio.input_device` / `audio.output_device` 先留 `null`** —— Mac 用系统默认设备。
等上了树莓派再改成 USB 声卡的序号。

### ③ 消掉最大的不确定性：语音接口

```bash
python3 scripts/probe_ali.py
```

- [ ] ASR 和 TTS 各打出一个 `✓`

没过就把 `✗` 那几行贴出来。**这一步过了，语音的部分就稳定了。**

### ④ 调回答风格

```bash
python3 scripts/step4_llm.py 为什么天是蓝的
```

- [ ] ≤ 60 字、无 markdown、6-10 岁能听懂

不满意改 `llm.system_prompt` 再跑。**这一步在 Mac 上调，比在树莓派上调舒服得多。**

### ⑤ 听百炼音色

```bash
python3 scripts/step5_tts.py 你好我是小问号
```

- [ ] 出声了，音色合适

不合适就换 `tts.voice`（控制台音色列表里的 voice_type）。

### ⑥ 全链路：真麦克风 + 回车当按键 ★

```bash
AIBOX_SIMULATE_BUTTON=1 python3 scripts/step6_main.py
```

回车 = 按下，再回车 = 松手，`q` = 退出。

**这条命令用的是 Mac 真实麦克风、真实百炼 ASR、真实 DeepSeek、真实百炼 TTS、真实播放。**
只有按键是回车代替的。

- [ ] 对着 Mac 说一句，听到回答

> 第一次跑会弹「想访问麦克风」，点**允许**。点了拒绝就得去
> 系统设置 → 隐私与安全性 → 麦克风 → 给你的终端打勾，然后重启终端。

### ⑦ 看流式版的延迟

```bash
AIBOX_SIMULATE_BUTTON=1 python3 scripts/step7_stream.py
```

- [ ] 端到端 ≤ 2.5 秒，句子不串词

### Mac 上测不到什么（别误以为已经稳了）

| | 为什么 |
|---|---|
| GPIO 按键 | 没有按键，用回车代替 |
| USB 声卡的音质/延迟/丢帧 | Mac 用的是内置麦和扬声器 |
| 树莓派 CPU 对录音/播放的影响 | M 系列芯片和 3B 完全不是一个量级 |
| 电源、WiFi 抖动、SD 卡 | 树莓派专有 |
| systemd 自启 | Mac 没这个 |

### Mac 预演的产出

**`config.json` 里除了 `audio` 两个设备号，其余全部填对并验证过。**
拷到树莓派后只需要改那两行 —— 这就是为什么值得先在 Mac 上做。

---

## step0 · 只测云端

**阿里云用户先跑这个**：

```bash
python3 scripts/probe_ali.py
```

**通过标准**：ASR 和 TTS 两段各打出一个 `✓`。

**没过**：阿里云的报错比火山直白，看懂字符串就能定位：
`InvalidApiKey`（key 错）/ `ModelNotOpen`（模型没开通）/ `voice not found`（音色 ID 不对）。

---

然后跑完整的三段测试：

```bash
python3 scripts/step0_api.py
```

**通过标准**：打印 `✓ 三段都通了`。

**没过**：报错里会带 HTTP 状态码和原始响应。
- `401` → key 错
- `404` → `base_url` 或模型名错
- `400` + 提到 voice → `tts.voice` 名字错，去控制台抄
- `402` / `429` → 余额不足或限流
- 一直 timeout → 树莓派连不上网，`curl -I https://openspeech.bytedance.com` 试

## step1 · 只测声卡

```bash
python3 scripts/step1_loopback.py --devices   # 先看设备
python3 scripts/step1_loopback.py
```

**通过标准**：能听到自己刚说的话。

**没过**：
- 录到的文件很小 → 麦克风没插好，或 `--in` 序号错
- 文件有大小但听不到 → `--out` 序号错，或音箱没开
- 声音是电流噪声 → 换了板载 3.5mm，换回 USB 声卡

跑通了就记下设备序号，填进 `config.json` 的 `audio.input_device` / `audio.output_device`（填序号数字，或名字片段如 `"USB"`）。

## step2 · 只测按键

```bash
python3 scripts/step2_button.py
```

**通过标准**：按 5 次，每次都打印按住时长。

**没过**：
- 完全没反应 → 按钮两条线是否一个在 GPIO17、一个在 GND；`gpiozero` 后端是否装上（`python3 -c "import gpiozero; print(gpiozero.__version__)"`）
- 按一次触发好几下 → `bounce_time` 已经设了 0.05，还抖就是按钮质量差，换一个
- 接的不是 17 脚 → 改 `config.json` 的 `button.gpio`

## step3 · 按键 → 识别

```bash
python3 scripts/step3_asr.py --save
```

**通过标准**：说「为什么天是蓝的」，打印的文本基本对得上。

**没过**：
- 识别成空 → 声音太小。看 `recordings/asr_01.wav` 用 Mac 放一下，如果声音很小就是麦克风增益问题（`alsamixer` 调 Capture）
- 识别成乱码 → 麦克风采样率不对，或离嘴太远
- 慢得离谱（>5s）→ 网络问题，看是不是在 2.4G WiFi 且信号差

## step4 · 打字 → 回答

这一步不需要硬件，在 Mac 上也能跑。重点是**调 system_prompt**。

```bash
python3 scripts/step4_llm.py 为什么天是蓝的
python3 scripts/step4_llm.py            # 连续对话模式
```

**通过标准**：回答 ≤ 60 字、没有 markdown、没有括号、没有表情、6-10 岁能听懂。

**没过**：改 `config.json` 的 `llm.system_prompt`。改完必须重跑 step4，**不要跳过直接测全链路**。

## step5 · 打字 → 出声

```bash
python3 scripts/step5_tts.py 你好我是小问号
```

**通过标准**：听到人声。

**没过**：`TTS 返回的是文本/JSON 而不是音频` → voice 名字错。`要播放的不是 WAV` → `response_format` 改回 `wav`。

## step6 · 全链路（档 A）

```bash
python3 scripts/step6_main.py
```

按住按钮说话，松手。

**通过标准**：听到回答，端到端 3~5 秒。

这一步第一次跑通，这个项目就算立住了。**先庆祝，再优化。**

**没过**：看打印的分段耗时，哪段红了就是哪层的问题，退回对应 step。

## step7 · 全链路（档 A+，日常用这个）

```bash
python3 scripts/step7_stream.py
```

**通过标准**：端到端 ≤ 2.5 秒；回答分几段播出，句子之间不能串词。

**没过**：
- 串词/漏词 → 切句器问题，把打印的句子贴出来
- 比 step6 还慢 → 网络或 TTS 限流，TTS 并发被串行化了
- 第一句迟迟不出 → 大模型不吐标点，看 `splitter.py` 的 `WEAK_MIN`

---

# 7. 开机自启

```bash
sudo cp deploy/aibox.service /etc/systemd/system/
sudo nano /etc/systemd/system/aibox.service    # 改 User= 和路径（如果不是 pi / ~/ai-qa-box）
sudo systemctl daemon-reload
sudo systemctl enable --now aibox
journalctl -u aibox -f
```

**通过标准**：断电重上电，什么都不用做，按按钮就有回答。

> 用了 venv 的话，`ExecStart` 改成 `.venv/bin/python`。

---

# 8. 延迟实测表（自己填，别信我的估算）

我给的所有延迟数字都是**量级估算，没在 3B 上实测过**。跑一遍填这张表，你才知道该优化哪。

| 环节 | 估算 | 实测 | 怎么改脚本看 |
|---|---|---|---|
| 松手 → ASR 出文本 | 0.5~1.2s | | step3 打印 |
| ASR 文本 → 首字 | 0.4~0.8s | | step7 的 `first_text` |
| 首字 → 首个音频 | 0.5~1.0s | | step7 的 `first_audio` |
| **松手 → 出声** | **1.5~2.5s** | | step7 的 `first_audio + asr` |
| 出声 → 播完 | 3~6s | | 取决于回答长度 |

## 优化优先级（按性价比排）

1. **回答更短** ← 收益最大，改 system_prompt 就行，0 成本
2. **缓存命中** ← 孩子会反复问同一句，命中就是 0 延迟
3. **WiFi 换网线** ← 3B 的 2.4G 抖动是最大变量
4. **面板里选离你近的 TTS 音色**（有些音色首包更慢）
5. **升档 B**（见第 10 节）← 收益到此为止，再往上要改协议

## 已知的、还没做的优化

- **「叮」提示音**：首段音频到达前播一声，主观延迟感砍半。没做，因为 `sd.play` 启动就有 ~150ms 延迟，要真做需要常驻 `aplay` 子进程喂 stdin。**不假装有。**
- **按下即上传**：现在是松手才开始调 ASR。改成按下就流式上传能再省 0.3~0.5s，但需要流式 ASR（档 B）。
- **本地唤醒词**：不需要，有按键。

---

## 8.5 跑两周之后怎么看效果

孩子开始用之后，每次问答会往 `aibox.jsonl` 追一行（只记文本和耗时，**不录音频**）。

```bash
python3 scripts/log_report.py --tail 20
```

输出长这样：

```
总交互       : 47 次
成功         : 44 次
失败         : 3 次（6.4%）
端到端耗时   : 中位 2.20s  P90 2.80s  最慢 4.10s
识别耗时     : 中位 1.20s
缓存命中     : 19 次（43%）
独立问题     : 31 个 / 共 44 次
重复率       : 30% 的提问是重复的
```

**盯三个数：**

| 数 | 健康值 | 不对时改什么 |
|---|---|---|
| 端到端中位 | < 2.5s | 超了先看是不是 WiFi，再看回答长度 |
| 失败率 | < 5% | 超过就是网络/鉴权问题，看错误类型 |
| 重复率 | 无所谓 | **> 30% 说明缓存很值，可以考虑把高频答案预生成** |

报告里还有一段 **会话轮数分布**，它直接告诉你 `history_turns` 该设多少：

```
会话数       : 12 个（间隔 >5 分钟算新话题）
平均轮数     : 4.0 轮
最长会话     : 6 轮
轮数分布     : 2轮×1  4轮×1  6轮×1

→ 实测最长 6 轮，history_turns 设 8 就够。设 20 也行，但不产生效果，只多花钱。
```

**关掉日志**（比如觉得写卡太频）：`config.json` 里 `runtime.log_path` 设成 `null`。

> 记录里会出现识别错的句子（比如“为什么天是**懒**的”），那不是日志的错，
> 是 ASR 真的识别错了——而这正是你需要知道的事。

---

# 9. 排错速查

| 症状 | 最可能的原因 | 怎么办 |
|---|---|---|
| `ModuleNotFoundError: sounddevice` | 没装 libportaudio2 | `sudo apt install -y libportaudio2` |
| `OSError: PortAudio library not found` | 同上 | 同上 |
| 一按按钮就报 GPIO 错 | lgpio 后端没装 | `sudo apt install -y python3-lgpio` |
| 录音全是静音 | 麦克风插在耳机口了 | 插 Mic In（粉色） |
| TTS 没声但日志正常 | 输出设备序号错 | step1 用 `--devices` 查，填 `output_device` |
| 播到一半爆音/卡顿 | SD 卡慢 或 电源不足 | 换 A1 卡、换 2.5A 电源 |
| 问什么都答同一句 | 命中了旧缓存（改过 prompt？） | 删掉 `cache/` 目录 |
| 跑几小时后变卡 | 内存泄漏或温度过高 | `free -h`、`vcgencmd measure_temp` |
| WiFi 偶发断 | 3B 电源/信号 | 插网线，或换 5V 2.5A 电源 |
| API 报 403 / `ModelNotOpen` | 模型没开通 / 没实名 / 没余额 | 百炼控制台看 |
| TTS 返回空音频 | `voice` 和 `model` 不匹配（v1 音色配 v2 模型） | 换匹配的一对 |
| LLM 报 401 | key 不对 | `set_keys.py --status` 看掩码 |
| LLM 报 model not found | 模型名不存在 | 改 `qwen-turbo` 试 |
| `ModuleNotFoundError: dashscope` | 没装 SDK | `pip3 install --user dashscope` |
| TTS 报 `CERTIFICATE_VERIFY_FAILED` | macOS 的 python.org 版本缺 CA 根证书 | 已在 `aibox/__init__.py` 自动处理；仍报就 `pip3 install certifi` |
| TTS 报 `could not established within 5s` | **先看后面那行「服务端返回」** | 写 `InvalidApiKey` 就是 key 错；`ModelNotOpen` 就是没开通；什么都没有才是真网络问题 |
| ASR 返回空字符串但没报错 | 已修：会抛 `阿里云 ASR 返回 HTTP xxx` | 如果昇级前遇到，就是旧版本 |

**清缓存**（会丢失已缓存的答案）：

```bash
python3 -c "import shutil; shutil.rmtree('cache', ignore_errors=True)"
```

> 注意：`cache/` 里现在可能有我测试时留下的 mock 数据。缓存键里带了 provider 指纹（模型名 + system_prompt），所以你换成真 key 之后**不会命中**这些脏数据，不用管。想干净就执行上面那条。

---

# 10. 想到 1 秒以内：档 B 要换什么

档 A+ 已经把「串行 HTTP」的浪费吃干了。再快只有一条路：**换掉 ASR 和 TTS 的协议**。

| 现在 | 档 B 要换成 | 收益 |
|---|---|---|
| ASR：整段 WAV POST，等全长 | WebSocket 流式 ASR，边录边传 | 省 0.3~0.5s |
| TTS：整句合成完再返回 | WebSocket 流式 TTS，PCM 块直出 | 省 0.3~0.5s |
| 播放：每段 `sd.play` 重新开设备 | 常驻 `aplay` 子进程喂 stdin PCM | 省 0.15~0.25s/段 |

**为什么我不给你写档 B 的代码**：每家的流式协议都是自定义二进制帧（火山、阿里、讯飞各不相同），我写不准，你抄过去大概率跑不通，还得逐字节调试。那不是「复制粘贴就能测」。

要上档 B 的时候告诉我用哪家，我按那家的协议文档写。

**换之前先问一句：1.5 秒对孩子真的不够用吗？** 大概率够。先把 step7 用起来，用一周再决定要不要为 0.5 秒改协议。

---

# 11. 已知情况与限制

## 已在树莓派 3B 实机上跑过

- 真 key 下的完整成功路径（ASR → LLM → TTS 全链路出声）
- 连续多日日常使用（4 天累计 184 次真实提问）
- 开机自启（`deploy/aibox.service`）
- 实时计费：约 2 分钱一次，其中约 96% 花在语音合成上

## 仍然没有验证 / 是估算的

- [ ] 第 8 节所有延迟数字（主要是估算，请以你的实测为准）
- [ ] 百炼 SDK 多线程并发调 TTS 是否串音（流式链路会并发 2~4 路）
- [ ] 便宜的 CM108 声卡在 3B 上同时录放的长期稳定性（可能丢帧，表现为录音有咔哒声）
- [ ] 3B 上 numpy + sounddevice 的实际 CPU 占用（估计 <20%）
- [ ] `cosyvoice-v2` 的音色 ID 与模型版本的对应关系（以控制台为准）

## 两个已知的坑

1. **别用 `deepseek-reasoner`**，思考链会让延迟多 3~5 秒。用 `deepseek-chat`。
2. **换 TTS 模型必须同时换音色 ID**。`longxiaochun_v2` 只属于 v2 系列，换到 `cosyvoice-v3.5-flash` 之类就要重新挑音色，否则直接报错。

遇到没覆盖的情况，开 issue 贴完整报错。

---

# 12. 可以往下做的东西

- 加一个「重听一次」按钮（不用重问，重播上一段）
- 加固定话术的本地 WAV（「我没听清」「网络出问题了」），不依赖 TTS，网络挂了也能出声
- 加一个物理旋钮调音量
- 外壳：纸盒 → 亚克力 → 3D 打印
