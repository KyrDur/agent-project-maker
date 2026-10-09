import test from 'node:test'
import assert from 'node:assert/strict'
import { modelPresets, presetConfig, identifyPreset } from '../src/model-presets.js'

test('DeepSeek preset uses its endpoint, current model, max_tokens and explicit non-thinking mode', () => {
  assert.deepEqual(presetConfig('deepseek'), { provider: 'openai-compatible', base_url: 'https://api.deepseek.com/v1',
    model: 'deepseek-flash', completion_token_parameter: 'max_tokens', thinking_mode: 'disabled' })
})
test('Switching service resets DeepSeek-specific settings; custom and restored endpoints remain possible', () => {
  for (const id of ['qwen', 'kimi', 'openai', 'claude', 'custom']) assert.equal(presetConfig(id).thinking_mode, null)
  assert.equal(presetConfig('claude').provider, 'anthropic-compatible')
  assert.equal(identifyPreset({ provider: 'openai-compatible', base_url: 'http://localhost:8124/v1', model: 'custom-name' }), 'custom')
  assert.equal(identifyPreset({ ...presetConfig('deepseek'), model: 'private-model' }), 'deepseek')
  assert(!JSON.stringify(modelPresets).includes('api_key'))
})
