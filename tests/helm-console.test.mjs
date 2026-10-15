import assert from 'node:assert/strict'
import { test } from 'node:test'
import { spawnSync } from 'node:child_process'

function render(...args) {
  return spawnSync('helm', ['template', 'test', new URL('../telovix-console', import.meta.url).pathname, ...args], { encoding: 'utf8' })
}

test('release defaults use a versioned image and preserve explicit tag overrides', () => {
  const result = render()
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /image: "registry.gitlab.com\/telovix\/console:\d+\.\d+\.\d+"/)
  const override = render('--set-string', 'image.tag=9.8.7')
  assert.equal(override.status, 0, override.stderr)
  assert.match(override.stdout, /image: "registry.gitlab.com\/telovix\/console:9.8.7"/)
})

test('shared proxy settings render once with update overrides taking precedence', () => {
  for (const updates of [false, true]) {
    const args = ['--set', 'llm.provider=custom', '--set-string', 'llm.apiKey=test-key',
      '--set-string', 'llm.httpProxy=http://llm-proxy:8080',
      '--set-string', 'llm.httpsProxy=http://llm-proxy:8443']
    if (updates) args.push('--set-string', 'update.httpProxy=http://update-proxy:8080',
      '--set-string', 'update.httpsProxy=http://update-proxy:8443')
    const result = render(...args)
    assert.equal(result.status, 0, result.stderr)
    assert.equal((result.stdout.match(/name: TELOVIX_LLM_HTTP_PROXY\n/g) ?? []).length, 1)
    assert.equal((result.stdout.match(/name: TELOVIX_LLM_HTTPS_PROXY\n/g) ?? []).length, 1)
    const host = updates ? 'update-proxy' : 'llm-proxy'
    assert.ok(result.stdout.includes(`value: "http://${host}:8080"`))
    assert.ok(result.stdout.includes(`value: "http://${host}:8443"`))
  }
  const updateOnly = render('--set-string', 'update.httpProxy=http://update-proxy:8080')
  assert.equal(updateOnly.status, 0, updateOnly.stderr)
  assert.match(updateOnly.stdout, /name: TELOVIX_LLM_HTTP_PROXY\s+value: "http:\/\/update-proxy:8080"/)
})

test('single HTTPS listener, correct UID, persistent identity and wizard-friendly probes', () => {
  const result = render()
  assert.equal(result.status, 0, result.stderr)
  assert.ok(!result.stdout.includes('15484'))
  assert.match(result.stdout, /runAsUser: 65532/)
  assert.match(result.stdout, /startupProbe:[\s\S]*scheme: HTTPS/)
  assert.match(result.stdout, /readinessProbe:\s+httpGet:\s+path: \/healthz/)
  assert.match(result.stdout, /CONSOLE_ID: "tlvc_/)
  assert.ok(!result.stdout.includes('kind: StatefulSet'))
})

test('bundled storage renders private services, PVCs, Secret references and pinned Console', () => {
  const result = render('--set', 'bundledDatabases.enabled=true', '--set', `image.digest=sha256:${'a'.repeat(64)}`)
  assert.equal(result.status, 0, result.stderr)
  assert.equal((result.stdout.match(/kind: StatefulSet/g) ?? []).length, 2)
  assert.equal((result.stdout.match(/volumeClaimTemplates:/g) ?? []).length, 2)
  assert.match(result.stdout, /registry.gitlab.com\/telovix\/console@sha256:/)
  assert.match(result.stdout, /key: POSTGRES_PASSWORD/)
  assert.match(result.stdout, /key: CLICKHOUSE_PASSWORD/)
  assert.equal(render('--set', 'bundledDatabases.enabled=true', '--set', 'database.url=external').status, 1)
})

test('customer bootstrap mounts a private Secret and cannot enable managed mode or ephemeral replay state', () => {
  const result = render('--set', 'selfHostedBootstrap.secretName=customer-bootstrap')
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /TELOVIX_CONSOLE_DEPLOYMENT_MODE\s+value: "self_hosted"/)
  assert.match(result.stdout, /TELOVIX_CONSOLE_SELF_HOSTED_BOOTSTRAP_FILE/)
  assert.match(result.stdout, /secretName: "customer-bootstrap"/)
  assert.match(result.stdout, /defaultMode: 0440/)
  assert.ok(!result.stdout.includes('TELOVIX_CONSOLE_MANAGEMENT_SECRET'))
  assert.equal(render('--set', 'selfHostedBootstrap.secretName=private', '--set', 'deploymentMode=managed').status, 1)
  assert.equal(render('--set', 'selfHostedBootstrap.secretName=private', '--set', 'persistence.enabled=false').status, 1)
})
