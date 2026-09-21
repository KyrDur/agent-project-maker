'use client'

import { useQuery } from '@tanstack/react-query'
import { useLocale } from 'next-intl'
import { templatesApi } from '@/lib/api/templates'
import { templateQueryKeys } from '@/lib/query-keys/templates'

export function useTemplates(category?: string, options?: { enabled?: boolean }) {
  const locale = useLocale()
  return useQuery({
    queryKey: templateQueryKeys.localized(category, locale),
    queryFn: () => templatesApi.list(category),
    staleTime: 300000,
    enabled: options?.enabled ?? true,
  })
}
