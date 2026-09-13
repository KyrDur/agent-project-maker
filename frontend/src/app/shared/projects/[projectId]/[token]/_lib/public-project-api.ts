import { apiFetch } from '@/lib/api/client'

interface PublicReport {
  sections: { title: string; body: string }[]
}

export async function readPublicProject(projectId: string, token: string): Promise<PublicReport> {
  return apiFetch<PublicReport>(
    `/api/project-shares/${encodeURIComponent(projectId)}/${encodeURIComponent(token)}`,
    { cache: 'no-store', referrerPolicy: 'no-referrer' },
  )
}
