import { expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen } from '../../../../../../../tests/test-utils'
import { server } from '../../../../../../../tests/setup'
import { PublicProject } from './public-project'

it('public view has no execution controls and treats report text as inert text', async () => {
  server.use(
    http.get('http://localhost:8001/api/project-shares/p/t', () =>
      HttpResponse.json({
        sections: [{ title: 'Report', body: '<img src=x onerror=alert(1)>75% → 90%' }],
      }),
    ),
  )
  const { container } = render(<PublicProject projectId="p" token="t" />)
  expect(await screen.findByText('<img src=x onerror=alert(1)>75% → 90%')).toBeInTheDocument()
  expect(container.querySelector('img')).toBeNull()
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('public revoked link renders unavailable', async () => {
  server.use(
    http.get(
      'http://localhost:8001/api/project-shares/p/t',
      () => new HttpResponse(null, { status: 404 }),
    ),
  )
  render(<PublicProject projectId="p" token="t" />)
  expect(await screen.findByRole('alert')).toHaveTextContent(
    '该项目共享不可用或已被撤销。',
  )
})
