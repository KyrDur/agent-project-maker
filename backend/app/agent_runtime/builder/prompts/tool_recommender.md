# 能力方案生成

根据用户已确认的需求，生成最小可行能力方案。输入包含需求、可用目录及用户修改意见。
只返回 JSON 数组，每项包含 tool_name、kind、description、reason。

- 简单归纳、写作、润色和对话由模型指令承担，允许返回空数组，不添加凑数工具。
- 查询数据或修改状态使用 kind="planned" 的模拟接口。名称必须为 ASCII 字母、数字、下划线或连字符，不超过 64 字符。提供 input_schema（JSON Schema object）。不得连接真实工具、MCP 或业务系统。
- 多步骤流程、领域规范需要指南时，使用 kind="generated_skill"，提供 content 字段：完整 SKILL.md 文本，带 name 和 description 的 YAML frontmatter。指南只包含文本，不包含可执行脚本。名称同样为安全 ASCII slug，正文为中文。
- 目录中已有适用文本指南可以使用 kind="skill"，tool_name 必须精确匹配目录名称。
- 未知业务规则不能伪称事实，只使用已确认的模拟假设。
- 用户要求修改时，重新生成完整方案，并严格遵守其取舍。
- 不得推荐真实 tool/mcp 连接。每项 reason 说明与确认需求的关系。
