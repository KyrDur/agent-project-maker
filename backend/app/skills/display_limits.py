"""显示层文本文件契约上限 — 单一正本。

草稿工作区适配器（skill_draft_workspace）与 revision snapshot viewer
（skill_revision_service）共享同一 fail-closed 契约（前 N 字节空字节 sniff、
每文件显示上限）。若只改一边，draft viewer 与 revision viewer 会
对同一文件作出不同判断，因此必须只在这里调整。
"""

# 用于二进制判断的 head sniff 大小。
DISPLAY_TEXT_SNIFF_BYTES = 8192

# 显示层允许读取的单文件最大字节数（超出则 fail-closed）。
MAX_DISPLAY_TEXT_BYTES = 2 * 1024 * 1024
