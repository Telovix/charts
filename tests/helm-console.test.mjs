import assert from 'node:assert/strict'
import { test } from 'node:test'
import { spawnSync } from 'node:child_process'

function render(...args) {
  return spawnSync('helm', ['template', 'test', new URL('../telovix-console', import.meta.url).pathname, ...args], { encoding: 'utf8' })
}

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
