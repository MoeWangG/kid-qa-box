"""step7 —— 档 A+：同一套接口，改成边生成边合成边播。

和 step6 的唯一区别：
  step6 等大模型把整段话写完（2~4s），再合成整段（1~2s），再播。
  step7 大模型吐第一句就送去合成，合成第一句就开始播，后面的在后台排队。

预期端到端 1.5~2.5s。想再快就得换厂商的 WebSocket 流式接口（档 B，见 README 12 节）。

注意：必须先在 step6 上验证过识别和回答都正常，再来跑这个。
      step7 出问题，先退回 step6 确认是「本来就有问题」还是「流式改坏了」。

用法：
    python3 scripts/step7_stream.py                           # 树莓派
    AIBOX_SIMULATE_BUTTON=1 python3 scripts/step7_stream.py   # Mac，回车当按键
"""

import _bootstrap  # noqa: F401

from aibox.device import main

if __name__ == "__main__":
    main(stream=True)
