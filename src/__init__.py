"""A股模拟投资系统"""

# 必须在任何子模块（尤其 config / storage）之前完成环境适配：
# 加载 .env、对齐时区、确定可写数据目录（PocketBay 注入 POCKETBAY_DATA_DIR）。
from .runtime import apply_timezone, load_env  # noqa: E402

load_env()
apply_timezone()
