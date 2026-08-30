from app.domain.knowledge.retrieval import (
    MAX_CHUNKS_PER_DOCUMENT,
    RELATIVE_TRUNCATION_MARGIN,
    apply_diversity_truncation,
    apply_relative_truncation,
    apply_score_threshold,
    default_score_threshold,
    number_chunks,
    resolve_score_threshold,
)


def _hit(cid: str, doc: str, score: float) -> dict:
    return {"chunk_id": cid, "document_id": doc, "score": score}


def test_relative_truncation_margin_matches_spec():
    """spec §7.2 步骤 3：与最佳命中分差 > 0.15 一律丢弃。"""
    assert RELATIVE_TRUNCATION_MARGIN == 0.15


def test_diversity_cap_matches_spec():
    """spec §7.2 步骤 4：单文档最多 3 个切片。"""
    assert MAX_CHUNKS_PER_DOCUMENT == 3


def test_default_threshold_per_embedding_model():
    """M1 / spec §3.2 权衡 8：OpenAI 兼容 0.25 / MiniLM 0.35 / 其他 0.30。"""
    assert default_score_threshold("openai_compat", "text-embedding-3-small") == 0.25
    assert (
        default_score_threshold("sentence_transformers", "paraphrase-multilingual-MiniLM-L12-v2")
        == 0.35
    )
    assert default_score_threshold("hashing", "hashing-256") == 0.30
    assert default_score_threshold(None, None) == 0.30


def test_resolve_threshold_prefers_configured_value():
    """M1：ModelConfig.score_threshold 为 None 时才用按模型的默认值。"""
    assert resolve_score_threshold(0.42, "hashing", "hashing-256") == 0.42
    assert resolve_score_threshold(None, "openai_compat", "m") == 0.25
    assert resolve_score_threshold(None, "hashing", "hashing-256") == 0.30


def test_resolve_threshold_treats_zero_as_configured():
    """0 是管理员的合法选择，不能被当成「未配置」而套用默认值。"""
    assert resolve_score_threshold(0.0, "openai_compat", "m") == 0.0


def test_threshold_drops_low_scores():
    kept = apply_score_threshold([_hit("a", "d", 0.9), _hit("b", "d", 0.1)], 0.35)
    assert [h["chunk_id"] for h in kept] == ["a"]


def test_threshold_is_inclusive():
    kept = apply_score_threshold([_hit("a", "d", 0.35)], 0.35)
    assert [h["chunk_id"] for h in kept] == ["a"]


def test_relative_truncation_drops_hits_far_from_best():
    hits = [_hit("a", "d1", 0.90), _hit("b", "d2", 0.80), _hit("c", "d3", 0.70)]
    assert [h["chunk_id"] for h in apply_relative_truncation(hits)] == ["a", "b"]


def test_relative_truncation_keeps_all_when_scores_are_close():
    hits = [_hit("a", "d", 0.5), _hit("b", "d", 0.45), _hit("c", "d", 0.40)]
    assert len(apply_relative_truncation(hits)) == 3


def test_relative_truncation_boundary_is_inclusive():
    """分差恰好 0.15 保留，超过才丢弃。"""
    hits = [_hit("a", "d", 0.90), _hit("b", "d", 0.75), _hit("c", "d", 0.74)]
    assert [h["chunk_id"] for h in apply_relative_truncation(hits)] == ["a", "b"]


def test_relative_truncation_handles_empty_input():
    assert apply_relative_truncation([]) == []


def test_diversity_truncation_caps_three_chunks_per_document():
    hits = [_hit(f"c{i}", "d1", 0.9 - i * 0.01) for i in range(6)]
    assert len(apply_diversity_truncation(hits)) == 3


def test_diversity_truncation_spreads_across_documents():
    hits = [_hit("a1", "d1", 0.9), _hit("a2", "d1", 0.88), _hit("b1", "d2", 0.7)]
    kept = apply_diversity_truncation(hits)
    assert {h["document_id"] for h in kept} == {"d1", "d2"}


def test_diversity_truncation_keeps_top_scores_within_a_document():
    hits = [_hit(f"c{i}", "d1", 0.9 - i * 0.05) for i in range(5)]
    kept = apply_diversity_truncation(hits)
    assert [h["chunk_id"] for h in kept] == ["c0", "c1", "c2"]


def test_diversity_truncation_does_not_reorder():
    hits = [_hit("b", "d2", 0.8), _hit("a", "d1", 0.9)]
    assert [h["chunk_id"] for h in apply_diversity_truncation(hits)] == ["b", "a"]


def test_chunks_are_numbered_from_one():
    hits = [_hit("a", "d", 0.9), _hit("b", "d", 0.8)]
    numbered = number_chunks(hits)
    assert [n for n, _ in numbered] == [1, 2]
    assert numbered[0][1]["chunk_id"] == "a"


def test_full_pipeline_threshold_then_relative_then_diversity():
    """spec §7.2 步骤 2→3→4 的顺序：先绝对阈值，再相对截断，最后多样性截取。"""
    hits = [
        _hit("a1", "d1", 0.95),
        _hit("a2", "d1", 0.94),
        _hit("a3", "d1", 0.93),
        _hit("a4", "d1", 0.92),  # 第 4 片：被多样性截取掉
        _hit("b1", "d2", 0.60),  # 与最佳分差 0.35：被相对截断掉
        _hit("c1", "d3", 0.20),  # 低于阈值 0.35：被绝对阈值掉
    ]
    kept = apply_diversity_truncation(
        apply_relative_truncation(apply_score_threshold(hits, 0.35))
    )
    assert [h["chunk_id"] for h in kept] == ["a1", "a2", "a3"]
