# 不做数据库迁移，使用 create_all + seed

演示原型不引入 Alembic，建表走 SQLAlchemy `create_all`，初始数据走 `make seed`。演示库的生命周期就是「删库重建」，Alembic 的核心价值 —— 在线升级存量数据 —— 根本用不上，而每批功能都要维护一个 revision 是纯负担。

## Considered Options

- **Alembic 完整迁移，每批一个 revision**：工程规范性更强；若答辩评分表把「数据库迁移方案」列为得分点，应选它。代价是为永不发生的在线升级场景持续付出维护成本。
- **Alembic 仅建一次基线，后续仍用 create_all**：折中方案，但基线本身没有下游消费者，属于为了有而有。

## Consequences

- 数据库结构变更时，开发者须手动删除 SQLite 文件后重建。README 必须明确写出这一操作，否则会踩到「改了模型但表没变」的困惑。
- 若该项目后续需要交付给他人增量升级使用，应重新评估并引入 Alembic。
