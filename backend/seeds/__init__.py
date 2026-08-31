"""种子包（spec §4.3：`backend/seeds/` = 习题种子数据 + 初始 admin）。

遗留项 M2 的落点。编排顺序固定：**admin → ModelConfig → exercises**，
三步全部幂等（已存在即跳过，不覆盖既有数据）—— 与 `make seed` 的既有语义一致：
连跑两次仍是 1 个用户、1 行 ModelConfig。

`app/seed.py` 是本包的 CLI 薄壳（`python -m app.seed`，Makefile `make seed` 不变）。
本包只依赖 `app.core` 与 `app.infrastructure.persistence`，不反向依赖 services：
种子是**建仓**动作，跑在业务用例之前，走 ORM 直插是刻意为之。
"""

from seeds.admin import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, seed_admin
from seeds.exercises import seed_exercises
from seeds.model_config import seed_model_config

__all__ = [
    "DEFAULT_ADMIN_PASSWORD",
    "DEFAULT_ADMIN_USERNAME",
    "seed",
    "seed_admin",
    "seed_exercises",
    "seed_model_config",
]


async def seed(session) -> None:
    """全部种子的总入口。"""
    await seed_admin(session)
    await seed_model_config(session)
    await seed_exercises(session)
    await session.flush()
