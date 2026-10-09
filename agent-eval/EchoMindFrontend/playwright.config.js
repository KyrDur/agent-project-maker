import { defineConfig } from '@playwright/test'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const frontend = path.dirname(fileURLToPath(import.meta.url))
const python = process.env.ECHOMIND_TEST_PYTHON || path.resolve(frontend, '../EchoMind/.venv/bin/python')
const evidence = process.env.ECHOMIND_TEST_EVIDENCE_DIR || path.resolve(frontend, '../../output/e2e-captures/agent-eval')
const backendPort = process.env.ECHOMIND_TEST_BACKEND_PORT || '8014'
const providerPort = process.env.ECHOMIND_TEST_PROVIDER_PORT || '8124'
const frontendPort = process.env.ECHOMIND_TEST_FRONTEND_PORT || '5174'
export default defineConfig({
  testDir: './tests/browser',
  timeout: 90000,
  expect: { timeout: 12000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['json', { outputFile: evidence + '/browser-tests.json' }], ['junit', { outputFile: evidence + '/browser-tests.xml' }]],
  outputDir: './test-results',
  use: { baseURL: `http://127.0.0.1:${frontendPort}`, viewport: { width: 1440, height: 1000 },
    trace: 'off', video: 'off', screenshot: 'off',
    ...(process.env.ECHOMIND_TEST_CHROMIUM ? { launchOptions: { executablePath: process.env.ECHOMIND_TEST_CHROMIUM } } : {}) },
  webServer: [
    { command: `"${python}" tests/local_server.py --backend-port ${backendPort} --provider-port ${providerPort}`,
      env: { PYTHONPATH: path.resolve(frontend, '../EchoMind'), ECHOMIND_TEST_EVIDENCE_DIR: evidence },
      url: `http://127.0.0.1:${backendPort}/openapi.json`, timeout: 30000, reuseExistingServer: false },
    { command: `pnpm exec vite --port ${frontendPort}`, env: { ECHOMIND_BACKEND_URL: `http://127.0.0.1:${backendPort}` },
      url: `http://127.0.0.1:${frontendPort}`, timeout: 30000, reuseExistingServer: false },
  ],
})
