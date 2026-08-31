"""ModelConfig 单例种子（自 `app/seed.py` 平移 —— P5 Task 12，遗留 M2）。

单例记录用固定主键（`MODEL_CONFIG_SINGLETON_ID`），存在即不重建 —— 取行与建行
的逻辑本来就收在 `registry.get_or_create_singleton()` 里，种子只负责触发一次。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.registry import get_or_create_singleton


async def seed_model_config(session: AsyncSession) -> None:
    await get_or_create_singleton(session)
