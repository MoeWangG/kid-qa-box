"""AI 问答机 —— 树莓派 3B 语音问答。

分层：config(配置) / audio(音频) / button(按键) / providers(云端) / pipeline(串联)
每一步都能单独跑，见 scripts/ 下的 stepN_*.py。
"""

import os

# python.org 装的 macOS Python 不自带 CA 根证书。
# 后果很隐蔽：requests 走 certifi 所以 HTTPS 正常，但 WebSocket 用 ssl 默认上下文，
# 会报 SSLCertVerificationError，看起来像「TTS 连不上 / 网络不通」，其实是本地缺证书。
# 在包初始化时兜一次，所有入口脚本都受益。树莓派 Debian 有系统证书，设了也无害。
if not os.environ.get("SSL_CERT_FILE"):
    try:
        import certifi

        os.environ["SSL_CERT_FILE"] = certifi.where()
    except ImportError:
        pass

__version__ = "0.1.0"
