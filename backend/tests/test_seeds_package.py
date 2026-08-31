"""`backend/seeds/` 包迁移的回归网（P5 Task 12，遗留 M2）。

迁移的红线是**行为不变**：`make seed` 连跑两次仍是 1 用户 / 1 配置，
`from app.seed import seed, DEFAULT_ADMIN_USERNAME` 仍可用（`tests/test_seed.py`
一字未改即为证），且薄壳是**再导出**而不是第二份实现。
"""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

import seeds as seeds_package
from app.domain.auth.user import ADMIN
from app.infrastructure.persistence.models import ModelConfig, User

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_seeds_package_seed_creates_admin_and_config(session):
    await seeds_package.seed(session)
    await session.commit()

    admin = (
        await session.execute(select(User).where(User.username == seeds_package.DEFAULT_ADMIN_USERNAME))
    ).scalar_one()
    assert admin.role == ADMIN
    assert (await session.execute(select(ModelConfig))).scalars().one() is not None


@pytest.mark.asyncio
async def test_seeds_package_seed_is_idempotent(session):
    await seeds_package.seed(session)
    await session.commit()
    await seeds_package.seed(session)
    await session.commit()

    users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    configs = (await session.execute(select(func.count()).select_from(ModelConfig))).scalar_one()
    assert (users, configs) == (1, 1), "连跑两次不得翻倍"


@pytest.mark.asyncio
async def test_seed_does_not_overwrite_an_existing_admin_password(session):
    """幂等的含义是「跳过」而不是「重置」：改过的密码必须活过第二次 make seed。"""
    await seeds_package.seed_admin(session)
    await session.commit()
    admin = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    admin.hashed_password = "已经改过的哈希"
    await session.commit()

    await seeds_package.seed_admin(session)
    await seeds_package.seed_admin(session)
    await session.commit()

    again = (
        await session.execute(select(User).where(User.username == "admin"))
    ).scalar_one()
    assert again.hashed_password == "已经改过的哈希"
    assert (await session.execute(select(func.count()).select_from(User))).scalar_one() == 1


@pytest.mark.asyncio
async def test_seed_model_config_keeps_admin_edits(session):
    await seeds_package.seed_model_config(session)
    await session.commit()
    cfg = (await session.execute(select(ModelConfig))).scalars().one()
    cfg.temperature = 0.1
    cfg.revision = 7
    await session.commit()

    await seeds_package.seed_model_config(session)
    await session.commit()

    after = (await session.execute(select(ModelConfig))).scalars().one()
    assert (after.temperature, after.revision) == (0.1, 7), "已存在的配置行不得被重置"


def test_app_seed_is_a_reexport_not_a_second_implementation():
    """薄壳必须是再导出：两份实现会各自漂移，那是比不迁移更糟的结果。"""
    import app.seed as app_seed

    assert app_seed.seed is seeds_package.seed
    assert app_seed.DEFAULT_ADMIN_USERNAME == seeds_package.DEFAULT_ADMIN_USERNAME
    assert app_seed.DEFAULT_ADMIN_PASSWORD == seeds_package.DEFAULT_ADMIN_PASSWORD


def test_makefile_lint_covers_the_seeds_package():
    """工具链也得管到新包，否则 seeds 成为 lint 的死角。"""
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    lint_line = [line for line in makefile.splitlines() if "ruff check" in line]
    assert lint_line, "Makefile 里没有 lint 目标"
    assert "seeds" in lint_line[0], lint_line[0]


def test_make_seed_cli_runs_twice_and_stays_idempotent(tmp_path):
    """`python -m app.seed` 的真实 CLI 语义：跑两次仍是 1 用户 / 1 配置。

    用临时文件库，避免用例污染开发机的 `backend/data/app.db`。
    """
    db_file = tmp_path / "seed-cli.db"
    env_db = f"sqlite+aiosqlite:////{db_file}"
    out = []
    for _ in range(2):
        proc = subprocess.run(
            [sys.executable, "-m", "app.seed"],
            cwd=str(BACKEND_ROOT),
            env={**os.environ, "DATABASE_URL": env_db},
            capture_output=True,
            text=True,
            timeout=180,
            # 不用 check=True：失败时要连 stderr 一起断言，抛出就丢掉了现场
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        out.append(proc.stdout)

    assert "seed 完成" in out[0]
    assert "admin" in out[0]

    conn = sqlite3.connect(str(db_file))
    try:
        users = conn.execute("select count(*) from users").fetchone()[0]
        configs = conn.execute("select count(*) from model_configs").fetchone()[0]
    finally:
        conn.close()
    assert (users, configs) == (1, 1), f"两次 CLI 输出：{out}"
