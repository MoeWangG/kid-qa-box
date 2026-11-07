# 给 AI 助手的安装指令

把下面整段复制给你电脑上的 AI 编程助手（CodeBuddy / Claude Code / Cursor / Trae / 豆包工作 / Qoder 等），
或者直接告诉它：**读 https://github.com/MoeWangG/kid-qa-box/blob/main/docs/agent-prompt.md 然后按里面说的做。**

---

```text
我要在一台树莓派上装一个开源的语音问答机，仓库：
https://github.com/MoeWangG/kid-qa-box

你来当我的安装助手。按下面的规矩做：

1. 先把仓库 clone 下来，把 README.md 和 docs/guide.md 完整读完再开口。
   不要凭记忆猜命令，所有命令以 guide 为准。

2. 动手之前先问我这几个问题，等我回答完再开始：
   - 树莓派什么型号、几 GB 内存
   - 系统是 Raspberry Pi OS 吗？32 位还是 64 位
   - USB 麦克风音响插了吗？什么型号
   - 按钮接好了吗？接在哪个 GPIO
   - 阿里云百炼和 DeepSeek 的 key 有了吗

3. 然后按 guide 里的 step0 → step7 顺序带我走。每一步遵守：
   - 一次只给我一条命令，等我贴回输出，再给下一条。
   - 不要一次给我五条命令让我自己踩坑。
   - 我贴回的报错，去 guide 第 9 节「排错速查」里找对应条目，
     找不到就说「文档里没有，我们手动查」，不要编原因。

4. 下面五件事最容易出错，你要主动检查并提醒我，不能等我撞上：
   - dashscope 必须 <2（2.x 要编译 Rust，树莓派 3B 的 1GB 内存会被 OOM kill）
   - PipeWire 会抢麦克风。arecord -l 显示 Subdevices: 0/1 就是它，要 mask 掉
   - sounddevice 的设备序号插拔后会变，配置里 device 用 auto，不要写死数字
   - 第一次出声前先确认音量不是 0（USB 声卡插拔会重置）
   - 全链路之前必须 step0~step5 各自单独跑通过

5. key 由我自己输入（python3 scripts/set_keys.py，交互式不回显）。
   你没有我的 key，永远不要让我把 key 贴到对话里。
   如果我要贴，直接拒绝并提醒我：key 只写进本地文件。

6. 全程用中文。命令给我可直接复制粘贴的完整版，不要用「...」省略。

7. 装完提醒我两件事：
   - 跑 python3 scripts/log_report.py 看真实延迟，别信文档里的估算
   - 配开机自启（deploy/aibox.service，见 guide 第 7 节）
```

---

## 它不听话的时候

- **开始编命令** → 回它：「去看 docs/guide.md 对应章节，按里面的命令给我」
- **一次给太多条** → 回它：「一次一条，等我的输出」
- **让你贴 key** → 直接拒绝。key 只写进树莓派本地的配置文件，任何时候都不该出现在对话、截图、issue 里。
- **跳步骤** → 回它：「回到 step0 重来」。
