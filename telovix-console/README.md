# Telovix Console Helm Chart

This chart deploys the Telovix Console as a single-binary Kubernetes application. The Console
serves the operator API, embedded web UI and sensor mTLS on one HTTPS listener, mounts a persistent
`/data` volume for local state, and supports in-console binary self-updates.

## What this chart deploys

- A `Deployment` running one or more Telovix Console pods
- A `Service` exposing the combined HTTPS port 15483
- An optional `Ingress` for browser access
- A `PersistentVolumeClaim` for `/data`
- A `Secret` holding database and bootstrap values
- Optional single-node PostgreSQL and ClickHouse StatefulSets with private Services and PVCs

## Prerequisites

- Kubernetes 1.26 or newer
- Helm 3.12 or newer
- PostgreSQL and ClickHouse reachable from the cluster, or `bundledDatabases.enabled=true`
- A Console image built from `console/Dockerfile`, preferably pinned with `image.digest`
- Customer-owned DHI pull authentication plus the authorized Console pull Secret

PostgreSQL stores transactional Console state. ClickHouse stores analytics and runtime event data.
Both are required for a functional deployment.

Chart **1.1.0** adds bundled storage and self-hosted bootstrap settings; chart
1.0.0 does not support them. The chart version is separate from the Console
application version. Its default image tag is `edge`; use a qualified image
digest for deployment. Preconfigured setup requires a Console image that supports
self-hosted bootstrap, not just the new chart.

Bundled storage is opt-in; Portal-generated values enable it. Configure
`imagePullSecrets` for both registries and a default StorageClass (or set
`bundledDatabases.storageClass`). Generated database passwords and Console ID
are retained via Secret lookup on upgrades. Do not delete that Secret or use
offline `helm template | kubectl apply` for upgrades with generated secrets.
For GitOps/offline rendering, supply externally managed databases and explicit
credentials and identity instead. Back up the Secret and all three data stores.

## First-run access

Ingress defaults off. Startup, liveness and default routing readiness probes use
HTTPS `/healthz`, so the wizard is reachable before databases are configured.
`/readyz` intentionally returns 503 until setup completes; operators may change
`readinessPath` to `/readyz` after onboarding. TLS files are generated under the
persistent data directory when no TLS Secret is supplied.

For the Portal's generated `fullnameOverride: telovix-console`, access the wizard:

```bash
kubectl -n telovix-console port-forward service/telovix-console 15483:15483
```

Use PostgreSQL host `telovix-console-postgres`, port 5432, and ClickHouse URL
`http://telovix-console-clickhouse:8123`. Database/user are `telovix_console`.
Retrieve credentials locally; these commands print secrets, so do not log/share
their output:

```bash
kubectl -n telovix-console get secret telovix-console-secret -o jsonpath='{.data.DATABASE_URL}' | base64 --decode
kubectl -n telovix-console get secret telovix-console-secret -o jsonpath='{.data.CLICKHOUSE_PASSWORD}' | base64 --decode
```

Open `https://localhost:15483`, register the displayed Console ID in Portal,
import its signed license and create the administrator. Restart the Deployment
after setup to start background workers. Restrict access during onboarding.

For external databases leave `bundledDatabases.enabled=false` and configure
`database.url` and `clickhouse.*`. ClickHouse needs schema/DDL privileges.
If enabling ingress, keep HTTPS upstream and preserve sensor client certificates
with TLS passthrough. The nginx annotations require a controller with SSL
passthrough enabled; ordinary HTTPS termination alone is insufficient for
self-hosted sensor mTLS. Direct TLS exposure is another option.

## Quick start

Create a values override file with your database, analytics, hostname, and TLS settings, then install:

```bash
helm repo add telovix https://telovix.github.io/charts
helm repo update telovix
helm install telovix-console telovix/telovix-console \
  --version 1.1.0 \
  --namespace telovix \
  --create-namespace \
  -f values-override.yaml
```

Minimal override example:

```yaml
database:
  url: postgres://telovix:password@postgresql:5432/telovix_console

clickhouse:
  url: http://clickhouse:8123
  password: change-me

sensorTls:
  secretName: telovix-console-tls

ingress:
  hosts:
    - host: console.example.com
      paths:
        - path: /
          pathType: Prefix
```

## Self-update mechanism

The Console can update its own binary from the UI without pulling a new image:

1. The administrator checks for updates from the Settings UI.
2. The Console downloads the new binary and stages it at `$TELOVIX_DATA_DIR/telovix-console-update`.
3. The administrator triggers a restart.
4. On the next pod start, `entrypoint.sh` copies the staged binary into `/app/telovix-console` before launching the process.

This only works if `/data` is persistent across restarts. Do not replace the PVC with `emptyDir`
unless you intentionally want staged updates to be discarded on every restart.

## Managed vs self-hosted mode

Set `deploymentMode` to one of:

- `self_hosted`: for customer-operated deployments. Bootstrap values are optional.
- `managed`: for Portal-provisioned instances. The Portal provisioner sets bootstrap admin and license values.

Managed mode typically sets:

- `bootstrap.adminEmail`
- `bootstrap.adminName`
- `bootstrap.adminPasswordHash`
- `bootstrap.licenseBundle`

Self-hosted mode usually leaves those empty and performs initial configuration through the Console setup flow.

## TLS certificate setup for sensor mTLS

Create a Kubernetes Secret containing these keys:

- `server.crt`
- `server.key`
- `ca.crt`
- `issuer.crt`
- `issuer.key`

Example:

```bash
kubectl create secret generic telovix-console-tls \
  --namespace telovix \
  --from-file=server.crt=server.crt \
  --from-file=server.key=server.key \
  --from-file=ca.crt=ca.crt \
  --from-file=issuer.crt=issuer.crt \
  --from-file=issuer.key=issuer.key
```

Then set:

```yaml
sensorTls:
  secretName: telovix-console-tls
```

The chart mounts that Secret at `sensorTls.mountPath` and injects the corresponding
`TELOVIX_CONSOLE_SENSOR_TLS_*` environment variables expected by the Console.

## Values reference

| Value | Type | Default | Description |
|---|---|---|---|
| `image.repository` | string | `registry.gitlab.com/telovix/console` | Console image repository |
| `image.tag` | string | `edge` | Console image tag |
| `image.digest` | string | `""` | Immutable image digest; takes precedence over tag |
| `bundledDatabases.enabled` | bool | `false` | Install private PostgreSQL and ClickHouse |
| `selfHosted.consoleId` | string | `""` | Initial Console ID; otherwise generated and preserved |
| `readinessPath` | string | `/healthz` | Wizard-friendly routing readiness |
| `image.pullPolicy` | string | `IfNotPresent` | Image pull policy |
| `deploymentMode` | string | `self_hosted` | Deployment mode: `self_hosted` or `managed` |
| `replicaCount` | int | `1` | Number of Console replicas |
| `selfHostedBootstrap.secretName` | string | `""` | Customer-owned Secret containing private `bootstrap.json`; requires self_hosted mode and persistence |
| `service.type` | string | `ClusterIP` | Kubernetes Service type |
| `service.httpPort` | int | `15483` | Combined HTTPS service port |
| `ingress.enabled` | bool | `false` | Create an Ingress resource |
| `ingress.className` | string | `nginx` | Ingress class name |
| `ingress.annotations` | object | `{nginx.* timeouts}` | Ingress annotations |
| `ingress.hosts` | list | `console.example.com` | Ingress host and path rules |
| `ingress.tls` | list | `[]` | Ingress TLS blocks |
| `persistence.enabled` | bool | `true` | Create and mount a PVC for `/data` |
| `persistence.storageClass` | string | `""` | StorageClass name |
| `persistence.accessMode` | string | `ReadWriteOnce` | PVC access mode |
| `persistence.size` | string | `5Gi` | PVC requested size |
| `persistence.mountPath` | string | `/data` | Mount path and `TELOVIX_DATA_DIR` value |
| `database.url` | string | `""` | PostgreSQL connection string |
| `clickhouse.url` | string | `""` | ClickHouse HTTP endpoint |
| `clickhouse.database` | string | `telovix_console` | ClickHouse database name |
| `clickhouse.user` | string | `telovix_console` | ClickHouse username |
| `clickhouse.password` | string | `""` | ClickHouse password stored in the chart Secret |
| `smtp.server` | string | `""` | Reserved for SMTP configuration |
| `smtp.port` | int | `587` | Reserved for SMTP configuration |
| `smtp.username` | string | `""` | Reserved for SMTP configuration |
| `smtp.password` | string | `""` | Reserved for SMTP configuration |
| `smtp.fromAddress` | string | `""` | Reserved for SMTP configuration |
| `smtp.fromName` | string | `Telovix Console` | Reserved for SMTP configuration |
| `bootstrap.adminEmail` | string | `""` | Bootstrap admin email for managed mode |
| `bootstrap.adminName` | string | `""` | Bootstrap admin display name |
| `bootstrap.adminPasswordHash` | string | `""` | Bootstrap admin Argon2id hash |
| `bootstrap.licenseBundle` | string | `""` | Inline signed license bundle |
| `update.portalBaseUrl` | string | `https://portal.telovix.com` | Documented update source base URL |
| `update.httpProxy` | string | `""` | Documented HTTP proxy override |
| `update.httpsProxy` | string | `""` | Documented HTTPS proxy override |
| `resources.requests.cpu` | string | `250m` | Requested CPU |
| `resources.requests.memory` | string | `256Mi` | Requested memory |
| `resources.limits.cpu` | string | `2000m` | CPU limit |
| `resources.limits.memory` | string | `1Gi` | Memory limit |
| `podSecurityContext.fsGroup` | int | `65532` | Filesystem group for mounted volumes |
| `podSecurityContext.runAsNonRoot` | bool | `true` | Enforce non-root execution |
| `podSecurityContext.runAsUser` | int | `65532` | Runtime UID matching the Console image |
| `sensorTls.secretName` | string | `""` | Secret containing sensor TLS materials |
| `sensorTls.mountPath` | string | `/run/secrets/telovix-tls` | Mount path for the TLS Secret |
| `nameOverride` | string | `""` | Override the chart name |
| `fullnameOverride` | string | `""` | Override the full release name |
