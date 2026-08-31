BACKEND := backend
FRONTEND := frontend
PY := . .venv/bin/activate &&

.PHONY: install install-lite setup-local-embed dev serve test seed lint

# B3：默认安装含本地 embedding（torch 约 1GB），保证无 API Key 时 RAG 仍有真实语义
install:
	cd $(BACKEND) && python3 -m venv .venv && $(PY) pip install -e ".[dev,local-embed]"
	cd $(FRONTEND) && npm install

# 精简安装：跳过 torch，适合磁盘/带宽受限；之后可用 make setup-local-embed 补装
install-lite:
	cd $(BACKEND) && python3 -m venv .venv && $(PY) pip install -e ".[dev]"
	@echo "已跳过本地 embedding extras（torch 约 1GB）；需要真实语义检索时执行 make setup-local-embed"
	cd $(FRONTEND) && npm install

setup-local-embed:
	cd $(BACKEND) && $(PY) pip install -e ".[local-embed]"

dev:
	@echo "双端口开发：前端 http://localhost:5173 · 后端 http://localhost:8000"
	(cd $(BACKEND) && $(PY) uvicorn app.main:app --reload --workers 1 --port 8000) & \
	(cd $(FRONTEND) && npm run dev) & \
	wait

serve:
	@echo "单端口演示：http://localhost:8000"
	cd $(FRONTEND) && npm run build
	@test -d $(FRONTEND)/dist || (echo "错误：frontend/dist 不存在，请先构建前端" && exit 1)
	cd $(BACKEND) && $(PY) uvicorn app.main:app --workers 1 --port 8000

# 后端 pytest 与前端 vitest 都要跑 —— 前端消毒测试若只存在于独立 runner 里会静默腐烂
test:
	cd $(BACKEND) && $(PY) python -m pytest -q
	cd $(FRONTEND) && npm test

seed:
	cd $(BACKEND) && $(PY) python -m app.seed

lint:
	cd $(BACKEND) && $(PY) ruff check app seeds tests
