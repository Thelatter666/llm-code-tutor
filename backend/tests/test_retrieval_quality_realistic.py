"""真实粒度语料的检索质量回归（H3）。

`test_retrieval_quality.py` 的语料是 193/131/37 字，比 spec §8.2 的目标切片小
6–10 倍，语义稀释被严重低估 ——「0.35 是否偏严」在那个语料上得不出可靠结论。
本文件补两种真实形态，都用真模型 + 真 Chroma + 完整七步链路：

- **A 型：小标题密布的讲义**（现实中最常见）。切分器按 Markdown 标题先切小节，
  再在节内按 1200 字打包，于是实际切片是**小节级**的（实测 105–183 字）。
- **B 型：无标题长段正文**（教科书 prose、PDF 抽取）。没有标题可切，切片直接按
  1200 字打包，实测 600–950 字 —— 这才是「一片横跨多个主题」的稀释场景。
"""

import pytest
from sqlalchemy import select

from app.domain.knowledge.retrieval import apply_score_threshold
from app.infrastructure.adapters.embedding.sentence_transformer import (
    SentenceTransformerEmbedder,
    local_embed_available,
)
from app.infrastructure.adapters.vectorstore.chroma_store import ChromaVectorStore
from app.infrastructure.embedder_runtime import EmbedderRuntime
from app.infrastructure.persistence.models import Chunk, Document, KnowledgeBase
from app.services.indexing_service import IndexingService
from app.services.retrieval_service import RetrievalService

pytestmark = pytest.mark.skipif(
    not local_embed_available(), reason="未安装 local-embed extras"
)

MINI_THRESHOLD = 0.35  # spec §3.2 权衡 8

# --- A 型：小标题密布 ----------------------------------------------------------

CORPUS_A = {
    "A1 排序与查找": """## 1.1 冒泡排序

冒泡排序重复走访数组，比较相邻元素并在顺序错误时交换。每一轮走访都会把当前未排序
部分的最大元素"浮"到末尾。时间复杂度 O(n²)，空间复杂度 O(1)，实现简单但只适合
小规模数据。可以设置一个 exchanged 标志位，在某一轮没有发生交换时提前结束，
最好情况下时间复杂度降到 O(n)。

## 1.2 快速排序

快速排序采用分治思想：选定基准元素（pivot），把数组分成小于和大于基准的两部分，
再对两部分分别递归排序。平均时间复杂度 O(n log n)，最坏情况（数组已有序且总取
第一个元素为 pivot）退化到 O(n²)。pivot 的选取策略直接影响性能，常用的有三数取中
与随机化。原地分区的版本空间复杂度为 O(log n)（递归栈）。

## 1.3 归并排序

归并排序先把数组递归拆成单个元素，再两两合并有序序列。时间复杂度稳定为
O(n log n)，与输入数据的初始顺序无关。代价是需要 O(n) 的额外空间。

## 1.4 二分查找

二分查找要求数据有序，每次取中间元素与目标比较，把搜索区间缩小一半。时间复杂度
O(log n)。实现时中位数取 left + (right - left) // 2 可避免整数溢出。""",
    "A2 函数与闭包": """## 2.1 函数是一等公民

Python 中函数是一等对象：可以赋值给变量、可以作为参数传递、也可以作为返回值。
这是装饰器与回调机制的基础。函数名只是一个绑定到函数对象的变量，重新赋值会让它
指向别的对象。

## 2.2 闭包

闭包是函数与其定义时的引用环境的组合。内层函数可以访问外层函数的局部变量，
即使外层函数已经返回，该变量依然存活 —— 因为它被内层的 __closure__ 引用着。
闭包常用于实现装饰器与工厂函数。

## 2.3 装饰器

装饰器本质是一个接收函数、返回函数的高阶函数，用 @ 语法糖应用在函数定义处。
functools.wraps 用来把被包装函数的 __name__、__doc__ 等元信息复制到包装函数上，
否则调试和文档生成都会出问题。带参数的装饰器需要再套一层。""",
    "A3 食堂通知": """今天食堂的红烧肉味道不错，土豆炖得很烂，米饭也蒸得刚好，排队的人比昨天少。
明天开始晚餐供应时间延长到七点半，二楼新增一个清真窗口。""",
}

# --- B 型：无标题长段，一片横跨多个主题 ---------------------------------------

CORPUS_B = {
    "B1 算法基础": """排序算法是数据结构课程的入门内容，也是面试中的高频考点。冒泡排序重复走访数组，
比较相邻元素并在顺序错误时交换，每一轮都会把未排序部分的最大元素浮到末尾，时间复杂度
为 O(n²)，空间复杂度为 O(1)。它实现起来最简单，适合教学演示与小规模数据，生产中几乎
不会使用。为了优化最好情况，通常会设置一个 exchanged 标志位，若某一轮没有发生任何交换
就提前结束，这样在数组已经有序时复杂度能降到 O(n)。与冒泡排序同属 O(n²) 的还有选择
排序和插入排序：选择排序每轮在未排序部分选出最小值放到前面，交换次数最少但比较次数
固定；插入排序把每个元素插入到前面已排序部分的合适位置，对小规模或基本有序的数据
表现很好，是很多标准库在递归到小规模时的兜底选择，例如 C++ 的 std::sort 在子数组
长度小于某个阈值时就切换到插入排序，以减少递归开销。

快速排序采用分治思想，选定一个基准元素（pivot）后把数组分成小于和大于基准的两部分，
再对这两部分分别递归排序。它的平均时间复杂度是 O(n log n)，但因为分区是否均衡完全
取决于 pivot 的选取，最坏情况下（数组已经有序且总是取第一个元素作为 pivot）会退化到
O(n²)。工程上常用的 pivot 策略有三数取中和随机化两种，前者取首、中、尾三个元素的
中位数，后者随机挑选，二者都能把退化概率压到极低。快排的原地分区版本空间复杂度为
O(log n)，来自递归栈。快排不是稳定排序，相等元素的相对次序在分区后可能改变。

归并排序同样使用分治，但它是先递归地把数组拆到只剩单个元素，再两两合并有序序列。
合并过程需要一块与原数组等大的临时空间，因此空间复杂度是 O(n)，这是它相比快排最大的
代价。作为交换，归并排序的时间复杂度稳定为 O(n log n)，与输入数据的初始顺序完全无关，
也不存在退化问题。归并排序是稳定排序，这让它成为需要保持相对次序时的首选，例如按
多个字段依次排序的场景。它对链表的支持尤其自然 —— 链表归并不需要额外空间，只需改变
指针指向。此外归并排序是外部排序的基础：当数据量大到无法一次性载入内存时，可以先
把它切成若干个能放进内存的小块分别排序，再做多路归并。""",
    "B2 函数式特性": """在 Python 中函数是一等对象，这意味着函数可以像整数、字符串那样被赋值给变量、
作为参数传给别的函数、作为返回值从函数中返回，也可以放进列表和字典。这个性质是
装饰器、回调函数、闭包这些机制共同的基础。需要留意的是，函数名本身只是一个绑定到
函数对象的变量，把同一个名字重新赋值为整数，原来的函数对象如果没有别的引用就会被
垃圾回收。闭包是函数与其定义时的引用环境的组合，内层函数可以访问外层函数的局部变量，
即使外层函数已经返回，那个变量依然存活，因为它被内层函数的 __closure__ 元组引用着，
不会被回收。闭包最常见的两个用途是实现装饰器和实现工厂函数，后者可以根据参数返回
行为不同但结构相同的函数，避免写一堆重复代码。

使用闭包时最容易踩的坑是延迟绑定。在循环里创建一组闭包，内层函数捕获的是变量本身
而不是循环当时的值，等到真正调用这批函数时循环早已结束，于是所有闭包看到的都是
最后一次迭代的值。典型场景是用列表推导式生成一批 lambda，结果全部输出同一个数。
解决办法是用默认参数把当时的值固化下来，写成 lambda x, n=n: x * n —— 默认参数在
函数定义时求值一次，正好把值定住。另一个办法是再套一层函数，让每次迭代都有独立的
作用域。这个坑在 JavaScript 的早期版本里同样存在，var 声明的变量没有块级作用域，
是经典的面试题。

装饰器本质是一个接收函数、返回函数的高阶函数，用 @ 语法糖写在函数定义处，等价于
func = decorator(func)。它最常见的用途是横切关注点：日志、计时、权限校验、缓存、
重试，这些逻辑与业务无关却要挂在很多函数上，用装饰器可以只写一次。实现装饰器时
务必用 functools.wraps 把被包装函数的 __name__、__doc__、__module__ 等元信息
复制到包装函数上，否则调试时看到的函数名全是 wrapper，自动生成的文档也会出错。
带参数的装饰器需要再套一层：外层接收装饰器参数、中层接收函数、内层才是真正的调用
包装，总共三层函数，这是初学者最容易写晕的地方。""",
    "B3 食堂通知": """今天食堂的红烧肉味道不错，土豆炖得很烂，米饭也蒸得刚好，排队的人比昨天少。
明天开始晚餐供应时间延长到七点半，二楼新增一个清真窗口。另外提醒各位同学，
就餐高峰集中在十二点前后，建议错峰前往，自带餐具可以减免一元。上周有同学反映
三楼的汤偏咸，食堂已经调整了配方，欢迎再提意见。天气转凉，热饮窗口从本周起
全天供应姜茶和红枣茶，价格不变。""",
}

# (查询, 期望命中的文档)；只列真模型在这两种语料上稳定分得开的那些
CLEAR_QUERIES = {
    "A": [
        ("讲讲排序算法", "A1 排序与查找"),
        ("冒泡排序的时间复杂度是多少", "A1 排序与查找"),
        ("闭包是什么", "A2 函数与闭包"),
        ("今天中午食堂的饭菜怎么样？", "A3 食堂通知"),
    ],
    "B": [
        ("讲讲排序算法", "B1 算法基础"),
        ("冒泡排序的时间复杂度是多少", "B1 算法基础"),
        ("今天中午食堂的饭菜怎么样？", "B3 食堂通知"),
    ],
}


@pytest.fixture(scope="module")
def runtime():
    rt = EmbedderRuntime(
        lambda level: SentenceTransformerEmbedder() if level == 1 else None
    )
    import asyncio

    asyncio.run(rt.warmup())
    return rt


def _write_source(tmp_path, title, text):
    p = tmp_path / f"{title}.txt"
    p.write_text(text, encoding="utf-8")
    return p


async def _index(session_factory, runtime, store, corpus, kb_id, tmp_path):
    async with session_factory() as s:
        s.add(KnowledgeBase(id=kb_id, name="讲义", status="ready"))
        for title, text in corpus.items():
            s.add(
                Document(
                    id=f"doc-{title}",
                    kb_id=kb_id,
                    title=title,
                    source_type="txt",
                    status="pending",
                    source_uri=str(_write_source(tmp_path, title, text)),
                )
            )
        await s.commit()
    for title in corpus:
        await IndexingService(
            session_factory(), embedder=runtime, vector_store=store,
            session_factory=session_factory,
        ).index_document(f"doc-{title}")


@pytest.fixture(params=["A", "B"], ids=["小标题讲义", "无标题长段"])
async def corpus(request, session_factory, runtime, tmp_path):
    """把 A / B 两型语料各自索引进独立的 Chroma 目录。"""
    label = request.param
    corpus_map = CORPUS_A if label == "A" else CORPUS_B
    kb_id = f"kb-{label}"
    store = ChromaVectorStore(persist_dir=tmp_path / f"chroma-{label}")
    await _index(session_factory, runtime, store, corpus_map, kb_id, tmp_path)

    async with session_factory() as s:
        rows = (
            await s.execute(select(Chunk).where(Chunk.kb_id == kb_id))
        ).scalars().all()
        docs = {
            d.id: d.title
            for d in (
                await s.execute(select(Document).where(Document.kb_id == kb_id))
            ).scalars().all()
        }
    return {
        "label": label,
        "kb_id": kb_id,
        "store": store,
        "corpus": corpus_map,
        "sizes": [r.char_count for r in rows],
        "chunk_of": {r.vector_id: docs.get(r.document_id, "?") for r in rows},
    }


def _svc(session, runtime, corpus) -> RetrievalService:
    return RetrievalService(session, embedder=runtime, vector_store=corpus["store"])


# --- 粒度：确认测的确实是真实粒度 ----------------------------------------------


@pytest.mark.asyncio
async def test_the_two_corpora_represent_different_chunk_granularities(corpus):
    """A 型切片是小节级、B 型切片接近 spec §8.2 的 1200 字目标。

    这条不只是自证：切分器按 Markdown 标题先切小节，所以**标题密布的讲义根本切不出
    1200 字的片**。若只测 A 型，「真实粒度」这一前提就是假的，H3 的结论会跟着错。
    """
    sizes = corpus["sizes"]
    assert sizes, "语料必须产出切片"

    if corpus["label"] == "A":
        assert max(sizes) < 300, f"A 型应为小节级切片，实际最大 {max(sizes)} 字"
    else:
        assert max(sizes) >= 600, f"B 型应接近 1200 字，实际最大 {max(sizes)} 字"


# --- 质量：分得开 --------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_queries_hit_the_right_document(session, runtime, corpus):
    for query, expected in CLEAR_QUERIES[corpus["label"]]:
        result = await _svc(session, runtime, corpus).search(
            query, kb_ids=[corpus["kb_id"]], top_k=10
        )
        assert result.rag_hit is True, f"「{query}」本应命中，却降级为 {result.fallback_reason}"
        assert result.threshold == MINI_THRESHOLD
        assert result.citations[0].doc_title == expected, (
            f"「{query}」首位命中 {result.citations[0].doc_title}，期望 {expected}"
        )
        assert result.citations[0].score >= MINI_THRESHOLD


@pytest.mark.asyncio
async def test_unrelated_query_does_not_pull_in_lecture_chunks(session, runtime, corpus):
    """食堂话题只该命中食堂通知，讲义切片不得混进引用。"""
    result = await _svc(session, runtime, corpus).search(
        "今天中午食堂的饭菜怎么样？", kb_ids=[corpus["kb_id"]], top_k=10
    )
    titles = {c.doc_title for c in result.citations}
    assert titles == {f"{corpus['label']}3 食堂通知"}, titles


# --- 稀释：真实长切片下的行为 --------------------------------------------------


@pytest.mark.asyncio
async def test_diluted_query_degrades_visibly_rather_than_mis_hitting(
    session, runtime, corpus
):
    """B 型长切片上「闭包是什么」被稀释到低于阈值 —— 必须零命中降级，不能硬凑。

    实测（1200 字级切片）：正确文档 B2 只有 ~0.08，而无关的食堂通知反而 ~0.19。
    此时任何「让它命中」的做法都等于把食堂通知当成闭包的引用来源 ——
    零命中有可见降级，错命中是把无关内容当引用喂给模型，后者更糟。
    """
    if corpus["label"] != "B":
        pytest.skip("只有长切片语料才会出现这种稀释")

    result = await _svc(session, runtime, corpus).search(
        "闭包是什么", kb_ids=[corpus["kb_id"]], top_k=10
    )
    assert result.rag_hit is False
    assert result.degraded is True
    assert result.fallback_reason == "no_relevant_chunk"
    assert result.citations == []


@pytest.mark.asyncio
async def test_lowering_the_threshold_lets_in_unrelated_without_rescuing_the_right_one(
    session, runtime, corpus
):
    """回归：把阈值降到 0.15 会放进完全无关的切片，却救不回被稀释的正确项。

    这条是「默认阈值保持 0.35」（裁定 5.1(c)、否决 (a)）的依据性断言。
    它同时也说明：阈值下调的收益（救回被稀释的正确项）在这类语料上为零，
    代价（注入无关引用）却是实打实的。
    """
    if corpus["label"] != "B":
        pytest.skip("只有长切片语料才会出现这种稀释")

    query = "闭包是什么"
    query_vector = (await runtime.embed([query]))[0]
    hits = await corpus["store"].query(
        query_vector, top_k=100, kb_ids=[corpus["kb_id"]]
    )
    candidates = [
        {
            "vector_id": h.vector_id,
            "score": h.score,
            "document_id": corpus["chunk_of"].get(h.vector_id, ""),
        }
        for h in hits
    ]
    assert candidates, "向量库必须召回到候选"

    lenient = apply_score_threshold(candidates, 0.15)
    survivors = {c["document_id"] for c in lenient}

    assert "B2 函数式特性" not in survivors, "正确项本就没被稀释到阈值以下"
    assert "B3 食堂通知" in survivors, (
        "预期：降到 0.15 后进来的是完全无关的食堂通知，而正确项仍进不来"
    )
