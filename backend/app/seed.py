"""`python -m app.seed` 的 CLI 薄壳（P5 Task 12：种子本体迁入 `backend/seeds/` 包）。

留在本文件的只有两件事：**入口**（建库 + 开会话 + 打印）与**兼容再导出**
（`from app.seed import seed, DEFAULT_ADMIN_USERNAME` 是既有测试与运维脚本用的
名字，不得因迁移而破坏）。种子的内容与幂等规则全在 `seeds/` 包里。
"""

import asyncio
from pathlib import Path

from app.core.config import get_settings
from app.infrastructure.persistence.db import SessionFactory, engine, init_db

# 兼容再导出：迁移后 `app.seed.seed` / 默认管理员常量仍然可导入（遗留 M2）
from seeds import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, seed

__all__ = ["DEFAULT_ADMIN_PASSWORD", "DEFAULT_ADMIN_USERNAME", "seed"]


async def _main() -> None:
    await init_db(engine)
    async with SessionFactory() as session:
        await seed(session)
        await session.commit()
    print(f"seed 完成：管理员 {DEFAULT_ADMIN_USERNAME} / {DEFAULT_ADMIN_PASSWORD}")
    print("README 须写明：首次登录后请立即修改默认密码。")


if __name__ == "__main__":
    url = get_settings().database_url
    if ":///" in url and ":memory:" not in url:
        Path(url.split(":///", 1)[1]).parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_main())
