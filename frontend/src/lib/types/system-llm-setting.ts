// System LLM settings domain types — mirrors backend
// `app/schemas/system_llm_setting.py` (ADR-019).
//
// Operators pick one System Credential + model per role. provider is derived
// from the credential's `definition_key` (single source of truth), base_url is
// surfaced so LiteLLM/openai_compatible endpoints are visible at a glance.

export const SYSTEM_LLM_ROLES = [
  'builder',
  'evaluation_generator',
  'judge_optimizer',
  'image',
] as const

export type SystemLlmRole = (typeof SYSTEM_LLM_ROLES)[number]

/** Credential definition_keys allowed for a System LLM slot. */
export const SYSTEM_LLM_CREDENTIAL_KEYS = [
  'deepseek',
  'moonshot',
  'openai',
  'zhipu_glm',
  'openrouter',
  'openai_compatible',
  'anthropic',
] as const

export interface SystemLlmSettingOut {
  role: SystemLlmRole
  credential_id: string | null
  credential_name: string | null
  /** = credential.definition_key. */
  provider: string | null
  base_url: string | null
  model_name: string | null
  configured: boolean
  updated_at: string
}

export interface SystemLlmSettingUpdate {
  credential_id: string | null
  model_name: string | null
}

export interface SystemLlmTestRequest {
  provider: string
  credential_id: string
  model_name: string
}
