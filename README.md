# kid-qa-box · 给孩子的 AI 问答机

一个盒子，一个按钮。按住说话，松开就回答。

没有屏幕，没有唤醒词，不能装 App，不能刷视频。

<img src="docs/images/device-1.jpg" width="420" alt="成品外观：亚克力盒里的树莓派 + 顶部按钮 + USB 麦克风音响">
<img src="docs/images/device-2.jpg" width="420" alt="内部：树莓派 3B、按钮接线、供电">

## 它是什么

树莓派 3B + 一个 USB 麦克风音响 + 一个按钮，接阿里云百炼（语音识别 + 语音合成）和 DeepSeek（大模型）。
按键录音 → 云端识别 → 模型作答 → 云端合成 → 喇叭播出。整机约 350 元，端到端几秒。

代码是 Python，跑在 1GB 内存的老 3B 上，串行版和流式版都能用。

## 为什么不买现成的智能音箱

我女儿 5 岁。家里有小爱和 Siri，用过一段时间，最后放弃了：

- **答案太长。** 问"为什么天是蓝的"，换来两分钟科普。她听完第三句就跑了。
- **内容不受控。** 儿童模式能过滤脏话，但过滤不了"爸爸，什么是离婚"。
- **它在一直听。** 唤醒词意味着麦克风常开。这机器是按键才录。
- **不能接话。** 她问"那恐龙呢"，音箱不记得上一句说的是恐龙。
- **它是别人的产品。** 我不能决定它明天更新成什么样。

自己搭一遍才有的好处：prompt 可以随时改，长度能调，答案风格能调，日志在你自己硬盘上。

## 三个关键设计（比技术选型重要）

**1. 先给结论，再展开一句。**
system prompt 里写死：只说两句，不超过 35 字，先答再补一句原因。这一条决定孩子会不会听完。

**2. 必须用物理按钮，不能用唤醒词。**
对小孩来说"按键"这个动作是可学习的、有仪式感的；对家长来说它意味着麦克风默认关闭。

**3. 多轮记忆只留 20 轮、1500 字。**
孩子会反复问同一个问题（我家是恐龙，一周问了 12 次）。记忆让第 13 次能接上话；
但上限必须存在，否则 1GB 内存的板子和 token 账单都会先崩。

## 快速开始

前提：树莓派 3B/4B（Raspberry Pi OS）、一个免驱 USB 麦克风音响、一个按钮接 GPIO。
以及两个 key：阿里云百炼（语音）、DeepSeek（或任意 OpenAI 兼容接口）。

```bash
# 1. 拿代码
git clone https://github.com/MoeWangG/kid-qa-box.git ~/kid-qa-box
cd ~/kid-qa-box

# 2. 装依赖（脚本会先试 apt、再 pip 兜底）
bash scripts/setup_pi.sh

# 3. 填 key（交互式输入，key 只写进 secrets.json，权限 600）
python3 scripts/set_keys.py

# 4. 先跑自检：不联网、不用硬件
python3 scripts/selftest.py
```

然后照 `docs/guide.md` 从 step0 一个一个往下测。**不要跳过步骤**——
这条链路上 5 个环节，任何一个坏了，最后一跑全链路的报错都不会告诉你是哪一个。

完整的接线、系统裁剪、开机自启在 **[docs/guide.md](docs/guide.md)**。

## 分步自测

| 脚本 | 只测什么 | 需要 |
|---|---|---|
| `scripts/step0_api.py` | 云的三个接口通不通 | 网 |
| `scripts/step1_loopback.py` | 声卡能不能录能放 | USB 音箱 |
| `scripts/step2_button.py` | 按钮接对没 | 按钮 |
| `scripts/step3_asr.py` | 按键 → 出文字 | 麦克风 |
| `scripts/step4_llm.py` | 打字 → 出回答 | — |
| `scripts/step5_tts.py` | 打字 → 出声 | 喇叭 |
| `scripts/step6_main.py` | 全链路（串行，好排查） | 全部 |
| `scripts/step7_stream.py` | 全链路（流式，日常用这个） | 全部 |

Mac 上可以先把 step0/4/5 跑一遍，不用等硬件到货——见 guide 的「6.0 先在 Mac 上预演」。

## 实测与限制

我这台：树莓派 3B（1GB）、Raspberry Pi OS 32-bit、USB 音箱一体机。

- 串行版（step6）端到端 9~16 秒。**慢在回答长度**，不是网络。
  把答案从 80 字压到 35 字，时间掉一半。
- 流式版（step7）边生成边合成边播，体感快很多，实测数字请用
  `python3 scripts/log_report.py` 自己统计（日志默认写 `aibox.jsonl`）。
- 温度 39.7°C，没装风扇，7×24 连跑没死过。
- `assets/greeting.wav` 那句开机问候是缓存好的，不联网也能响。

明确没做 / 做不了的：唤醒词、屏幕、离线运行、本地模型（3B 跑不动）、情绪识别。

## 踩过的坑

这些坑的共同点是：**不真跑就发现不了**。文档里都写了具体位置。

1. **ASR 静默失败** —— `Recognition.call()` 出错不抛异常，把错误塞进 `result.status_code`。不检查就以为"孩子没说话"。
2. **TTS 吞真实错误** —— SDK 握手失败只抛笼统的 `within 5s timeout`，真实原因要从 logging handler 里捞服务端返回体。
3. **WAV 时长算错** —— CosyVoice 不回填 header 里的 `nframes`，按 header 读会得到 1073741773 秒。得按 PCM 长度算。
4. **切句器只认句号** —— 长句永远等不到句号，永远开不了口。加了逗号弱切（16 字）。
5. **mock 污染缓存** —— 假答案被写进缓存，接真 API 时还在返回假答案。缓存 key 里加 provider 指纹。
6. **`dashscope` 必须锁 `==1.23.0`** —— 2.0 引入 tiktoken / pydantic-core（Rust），3B 的 1GB 内存编不动。
7. **pipewire 抢麦克风** —— `arecord -l` 显示 `Subdevices: 0/1` 就是这个。要 `systemctl --user mask` 掉 pipewire-pulse。
8. **设备序号会漂** —— 插拔后 `sounddevice` 的设备索引变了，所以配置用 `auto` 按名字匹配，匹配失败直接报错，不静默回退到板载声卡。

## 安全

- 音频和识别结果**不落盘**（缓存只存 TTS 的 wav，key 里不含原始问题文本）。
- 密钥分离：`config.json` 无 key，可安全分享；key 单独在 `secrets.json`（600）。
- 孩子的对话记录在 `aibox.jsonl`，只在你自己机器上。
- `.gitignore` 已覆盖 `config.json`、`secrets.json`、`cache/`、`recordings/`、`assets/`、`*.wav`。

## 目录

```
aibox/          12 个模块：录音、按键、ASR、LLM、TTS、切句、缓存、日志
scripts/        16 个脚本：7 个 step 自测 + 密钥/自检/日志分析
deploy/         aibox.service（开机自启）
docs/guide.md   完整搭建手册（接线、装系统、逐 step 排查、延迟优化）
```

## 许可

MIT。拿去改，改完告诉我你孩子的第一个问题是什么。
