import { ref, type Ref } from 'vue'

/**
 * 管理端「列表 + 分页」通用取数（决策 ② 消重：Logs / Users / ExerciseAdmin /
 * KnowledgeAdmin 四页原各自手写 items/total/page/loading + try/finally）。
 *
 * 筛选条件留在页面内：先改筛选、再调 reset()（回到第 1 页并重取）。
 */
export function usePagedList<T>(
  fetcher: (page: number, pageSize: number) => Promise<{ items: T[]; total: number }>,
  pageSize = 20,
) {
  const items: Ref<T[]> = ref([])
  const total = ref(0)
  const page = ref(1)
  const loading = ref(false)

  async function load() {
    loading.value = true
    try {
      const out = await fetcher(page.value, pageSize)
      items.value = out.items
      total.value = out.total
    } finally {
      loading.value = false
    }
  }

  function goto(next: number) {
    page.value = next
    void load()
  }

  /** 筛选变化后用：回到第 1 页再取。 */
  function reset() {
    page.value = 1
    void load()
  }

  return { items, total, page, pageSize, loading, load, goto, reset }
}
