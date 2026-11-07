"""统一异常类型。

单独一个文件是为了避免 providers.py 和 providers_volc.py 互相 import 成环。
"""


class ProviderError(RuntimeError):
    """云端调用失败。带 HTTP 状态码和原始响应，方便直接看出改哪个字段。"""
