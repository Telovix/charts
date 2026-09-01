#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
chart_dir="${repo_dir}/telovix-sensor"
legacy_values="${repo_dir}/tests/fixtures/sensor-legacy-reuse-values.yaml"

helm lint "${chart_dir}"
helm lint "${chart_dir}" --values "${legacy_values}"

helm template telovix-sensor "${chart_dir}" \
  --namespace telovix-system \
  --values "${legacy_values}" \
  --set flavor=telecom \
  --set sensor.consoleUrl=https://example.invalid \
  --set image.tag=1.0.41 >/dev/null

configured="$({
  helm template telovix-sensor "${chart_dir}" \
    --namespace telovix-system \
    --set flavor=telecom \
    --set sensor.consoleUrl=https://example.invalid \
    --set image.tag=1.0.41 \
    --set 'sensor.telecomCapture.interfaces[0]=ens5' \
    --set 'sensor.telecomCapture.networkNamespaces[0]=/proc/1/ns/net@eth0' \
    --set-string 'sensor.telecomCapture.ports=gtpu=2152;pfcp=8805'
} 2>&1)"

grep -q 'value: "ens5"' <<<"${configured}"
grep -q 'value: "/proc/1/ns/net@eth0"' <<<"${configured}"
grep -q 'value: "gtpu=2152;pfcp=8805"' <<<"${configured}"

standard="$({
  helm template telovix-sensor "${chart_dir}" \
    --namespace telovix-system \
    --set flavor=standard \
    --set sensor.consoleUrl=https://example.invalid \
    --set image.tag=1.0.41 \
    --set 'sensor.telecomCapture.interfaces[0]=ens5'
} 2>&1)"

if grep -q 'TELOVIX_MONITORING_INTERFACES' <<<"${standard}"; then
  echo "Telecom capture settings leaked into the standard sensor flavor." >&2
  exit 1
fi

if grep -q 'telovix-release-controller' <<<"${standard}"; then
  echo "Release controller must remain opt-in." >&2
  exit 1
fi

managed="$({
  helm template telovix-sensor "${chart_dir}" \
    --namespace telovix-system \
    --set flavor=standard \
    --set sensor.consoleUrl=https://console.example.invalid \
    --set sensor.enrollmentToken=test-token \
    --set clusterName=cluster-a \
    --set upgradeController.enabled=true \
    --set image.tag=1.0.47 \
    --set-string image.digest=sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
} 2>&1)"

grep -q 'kind: Deployment' <<<"${managed}"
grep -q 'app.kubernetes.io/name: telovix-release-controller' <<<"${managed}"
grep -q 'value: "managed"' <<<"${managed}"
grep -q 'registry.gitlab.com/telovix/sensor@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' <<<"${managed}"
grep -q 'resources: \["roles", "rolebindings"\]' <<<"${managed}"
grep -q 'resources: \["nodes", "pods", "namespaces", "services", "endpoints"\]' <<<"${managed}"
if grep -q 'verbs: \["escalate"\]' <<<"${managed}"; then
  echo "Managed upgrades must fail closed instead of receiving RBAC escalation rights." >&2
  exit 1
fi
if grep -A12 'name: telovix-sensor-updater' <<<"${managed}" | grep -q 'privileged: true'; then
  echo "Release controller unexpectedly rendered as privileged." >&2
  exit 1
fi

gitops="$({
  helm template telovix-sensor "${chart_dir}" \
    --namespace telovix-system \
    --set flavor=standard \
    --set sensor.consoleUrl=https://console.example.invalid \
    --set sensor.enrollmentToken=test-token \
    --set clusterName=cluster-a \
    --set upgradeController.enabled=true \
    --set upgradeController.managementMode=flux
} 2>&1)"

if grep -q 'resources: \["jobs"\]' <<<"${gitops}"; then
  echo "GitOps observation mode must not receive Job creation rights." >&2
  exit 1
fi

echo "Sensor chart upgrade compatibility checks passed."
