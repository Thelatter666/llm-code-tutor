"""OpenAI 兼容 /embeddings 向量化器（spec §2 三级回退的第一级）。

`embed()` 为同步方法并使用同步 httpx 客户端 —— 与端口约定一致，由调用方
经 `run_in_threadpool` 卸载（阻塞卸载，ADR-0002）。
"""

import httpx

DEFAULT_OPENAI_EMBED_MODEL = "text-embedding-3-small"
DEFAULT_OPENAI_EMBED_DIMENSION = 1536

_BATCH = 64
# 连接阶段必须快失败，读取阶段放宽：OpenAI 兼容端点首 token 前可能静默较久
_TIMEOUT = httpx.Timeout(10.0, read=120.0)


class OpenAICompatEmbedder:
    name = "openai_compat"
    is_sentinel = False

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str = DEFAULT_OPENAI_EMBED_MODEL,
        dimension: int = DEFAULT_OPENAI_EMBED_DIMENSION,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimension = dimension
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        out: list[list[float]] = []
        kwargs = {"timeout": _TIMEOUT}
        if self._transport is not None:
            kwargs["transport"] = self._transport
        with httpx.Client(**kwargs) as client:
            for start in range(0, len(texts), _BATCH):
                out.extend(self._embed_batch(client, texts[start : start + _BATCH]))
        return out

    def _embed_batch(self, client: httpx.Client, batch: list[str]) -> list[list[float]]:
        resp = client.post(
            f"{self._base_url}/embeddings",
            json={"model": self._model, "input": batch},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        if resp.status_code >= 400:
            # 抛出即触发 EmbedderRuntime 的下一级回退（spec §9）
            raise RuntimeError(f"embedding 服务返回 {resp.status_code}")

        data = resp.json().get("data") or []
        if len(data) != len(batch):
            raise RuntimeError("embedding 服务返回的向量数量与输入不一致")
        # OpenAI 兼容实现不保证按输入顺序返回，必须按 index 归位
        ordered: list[list[float]] = [[] for _ in batch]
        for item in data:
            ordered[item["index"]] = [float(x) for x in item["embedding"]]
        return ordered
