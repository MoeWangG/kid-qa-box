"""所有 step 脚本的公共头：把项目根目录塞进 sys.path，这样直接 python3 scripts/xx.py 就能跑。"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__all__ = ["ROOT"]
