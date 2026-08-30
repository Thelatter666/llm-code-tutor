import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SENSITIVE = [
    "backend/.secret_key",
    "backend/data/app.db",
    "backend/.venv/pyvenv.cfg",
    "frontend/node_modules/x",
    "frontend/dist/x.js",
]


def test_sensitive_paths_are_git_ignored():
    """B5 守护：spec §8.8 的论证前提是「整个目录极可能被拷贝传播」。

    加密主密钥、含密码哈希的库文件、虚拟环境、依赖目录均不得入库。
    """
    for rel in SENSITIVE:
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
        assert r.returncode == 0, f"{rel} 未被 .gitignore 覆盖"
