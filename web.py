"""AITrader Web Dashboard — 启动脚本。

托管平台（PocketBay 等）会注入 PORT 并期望进程绑定 0.0.0.0，
本地不设 PORT 时回落到 127.0.0.1:8000。
"""

import os

import uvicorn

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "src.web.main:app",
        host=host,
        port=port,
        reload=False,
    )
