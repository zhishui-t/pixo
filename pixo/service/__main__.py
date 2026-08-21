"""pixo.service.__main__ —— 本地启动入口。

用法:
    python -m pixo.service
"""
from __future__ import annotations

import uvicorn

from .app import create_app

app = create_app()


def main() -> None:
    """启动本地 pixo-service。"""
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
