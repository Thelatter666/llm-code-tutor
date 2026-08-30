"""文档接入环节的领域异常。

放在领域层而非基础设施层：解析适配器与上传服务都要抛它们，而领域层禁止
反向依赖基础设施。异常本身零 IO，服务层负责把它们映射成 `ApiError` 与 HTTP 状态码。
"""


class UnsupportedFileTypeError(ValueError):
    """扩展名不在白名单内 → 415。"""


class FileTooLargeError(ValueError):
    """单文件超过 10MB → 413。"""


class EmptyDocumentError(ValueError):
    """无文字层（扫描版 PDF）或文本极短 → 解析失败，不做 OCR。"""
