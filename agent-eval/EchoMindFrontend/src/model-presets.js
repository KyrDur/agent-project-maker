// Connection presets, not a claim that a user's account/model has passed testing.
export const modelPresets = [
  { id: 'deepseek', label: 'DeepSeek', provider: 'openai-compatible', base_url: 'https://api.deepseek.com/v1',
    models: ['deepseek-flash', 'deepseek-v4-pro'], completion_token_parameter: 'max_tokens', thinking_mode: 'disabled',
    note: '使用 DeepSeek 官方 API Key。预设采用普通对话模式，适用于当前客服工具链。第三方平台的模型名和地址可自行修改。',
    docs: 'https://api-docs.deepseek.com/' },
  { id: 'qwen', label: '通义千问 · 阿里云百炼', provider: 'openai-compatible', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: ['qwen-plus', 'qwen-turbo', 'qwen-max'], completion_token_parameter: 'max_tokens',
    note: '默认填写北京地域兼容地址。请使用同地域的百炼 Key；也可改成控制台提供的业务空间专属地址。',
    docs: 'https://help.aliyun.com/zh/model-studio/compatibility-of-openai-with-dashscope' },
  { id: 'kimi', label: 'Kimi · 月之暗面', provider: 'openai-compatible', base_url: 'https://api.moonshot.cn/v1',
    models: ['moonshot-v1-8k', 'moonshot-v1-32k', 'moonshot-v1-128k'], completion_token_parameter: 'max_tokens',
    note: '使用 Kimi 国内平台的 API Key。可直接输入控制台已开通的其他模型名称。',
    docs: 'https://platform.kimi.com/blog/posts/kimi-api-quick-start-guide' },
  { id: 'openai', label: 'OpenAI · GPT', provider: 'openai-compatible', base_url: 'https://api.openai.com/v1',
    models: ['gpt-4.1-mini', 'gpt-4.1'], completion_token_parameter: 'max_completion_tokens',
    note: '使用 OpenAI API Key，模型以账号实际开通为准。',
    docs: 'https://developers.openai.com/api/docs/models/gpt-4.1-mini' },
  { id: 'claude', label: 'Anthropic · Claude', provider: 'anthropic-compatible', base_url: 'https://api.anthropic.com',
    models: ['claude-sonnet-5-5', 'claude-haiku-4-5'], completion_token_parameter: 'max_tokens',
    note: '填写 Claude 控制台提供的模型 ID，使用 Anthropic API Key。',
    docs: 'https://platform.claude.com/docs/en/models/overview' },
  { id: 'custom', label: '自定义 / 其他兼容服务', provider: 'openai-compatible', base_url: '',
    models: [], completion_token_parameter: 'max_tokens', note: '填写服务商提供的接口地址和模型名，可接入其他 OpenAI 或 Anthropic 兼容服务。' },
]

export function presetConfig(id) {
  const preset = modelPresets.find(p => p.id === id) || modelPresets.at(-1)
  return { provider: preset.provider, base_url: preset.base_url, model: preset.models[0] || '',
    completion_token_parameter: preset.completion_token_parameter, thinking_mode: preset.thinking_mode || null }
}

export function identifyPreset(config) {
  return modelPresets.find(p => p.id !== 'custom' && p.provider === config.provider &&
    p.base_url === config.base_url?.replace(/\/$/, ''))?.id || 'custom'
}
