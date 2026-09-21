import { apiFetch } from './client'
import { getActiveClientLocale } from '@/i18n/client-locale'
import type { Template } from '@/lib/types'

export const templatesApi = {
  list: (category?: string) =>
    apiFetch<Template[]>(
      `/api/templates?locale=${getActiveClientLocale()}${category ? `&category=${encodeURIComponent(category)}` : ''}`,
    ),
  get: (id: string) => apiFetch<Template>(`/api/templates/${id}?locale=${getActiveClientLocale()}`),
}
