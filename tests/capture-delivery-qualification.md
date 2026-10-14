# Independent capture and delivery qualification

`captureDelivery.enabled` is disabled by default. This is a qualification path,
not an installed Fleet upgrade contract. Published monolithic Sensor images do
not enable it. Both component images must implement local protocol version 7,
and the Console must support delivery-only heartbeats.

The capture-owner image requires an explicit SHA-256 digest. Normal image tag,
digest, pull-policy and delivery resource updates change only the worker
DaemonSet. Chart version labels are not included in the owner's configuration
or enrollment data checksums. Existing state is not deleted by the split-mode
init container.

The worker is a separate DaemonSet, scheduled on the owner's node. It has a
private PID namespace, no capabilities, no service-account token and a read-only
owner-state mount. Its readiness command checks an authenticated current lease
in its own PID namespace and recent successful delivery protocol activity. The
probe neither claims a lease nor refreshes that activity. This checks local
delivery progress, not durable Console acceptance or exactly-once ingestion.

The managed upgrade controller can observe this installation and request
component-specific worker updates. Flux and Argo CD controller modes remain
unavailable for split installations. Enabling the controller does not establish
runtime qualification or permit whole-owner replacement.

Render-only checks:

```sh
python3 tests/helm-capture-delivery.test.py -v
bash tests/helm-sensor-upgrade-compat.sh
```

These tests do not deploy workloads or prove capture continuity under an
installed rollout. Native x64 and ARM64 installed tests, resource measurements,
durable Console replay and whole-owner handoff remain separate release gates.
