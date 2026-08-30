/**
 * 数组查询参数序列化。
 *
 * FastAPI 的 `list[str] = Query()` 只认**重复参数**（`?kb_ids=a&kb_ids=b`），
 * 不认逗号分隔（`?kb_ids=a,b` 会被当成单个值 "a,b"，知识库查找随即 404）。
 * axios 默认的数组序列化是 `kb_ids[]=a`，同样对不上，故显式指定。
 */
export const repeatArrayParams = (params: Record<string, unknown>): string => {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item))
    } else {
      search.append(key, String(value))
    }
  }
  return search.toString()
}
