// Middleware catalog (read-only). Backend exposes `/api/middlewares`.

import { apiFetch } from './client'
import { getActiveClientLocale } from '@/i18n/client-locale'

export interface MiddlewareRegistryItem {
  type: string
  name: string
  display_name: string
  description: string
  category: 'context' | 'planning' | 'safety' | 'reliability' | 'provider' | string
  config_schema: Record<string, unknown>
  provider_specific: string | null
}

export const middlewaresApi = {
  list: () =>
    apiFetch<MiddlewareRegistryItem[]>(`/api/middlewares?locale=${getActiveClientLocale()}`),
}
