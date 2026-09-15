'use client'

import { useQuery } from '@tanstack/react-query'
import { useLocale } from 'next-intl'
import { middlewaresApi } from '@/lib/api/middlewares'
import { middlewareQueryKeys } from '@/lib/query-keys/middlewares'

export function useMiddlewares() {
  const locale = useLocale()
  return useQuery({
    queryKey: middlewareQueryKeys.localized(locale),
    queryFn: middlewaresApi.list,
    staleTime: 60_000,
  })
}
