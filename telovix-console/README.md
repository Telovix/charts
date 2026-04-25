# Telovix Console Helm Chart

This chart deploys the Telovix Console as a single-binary Kubernetes application. The Console
serves the operator API and embedded web UI, exposes the sensor mTLS listener, mounts a persistent
`/data` volume for local state, and supports in-console binary self-updates.

## What this chart deploys

- A `Deployment` running one or more Telovix Console pods
- A `Service` exposing the operator HTTP port and sensor mTLS port
- An optional `Ingress` for browser access
- A `PersistentVolumeClaim` for `/data`
- A `Secret` holding database and bootstrap values

## Prerequisites

- Kubernetes 1.26 or newer
- Helm 3.12 or newer
- PostgreSQL reachable from the cluster
- ClickHouse reachable from the cluster
- A container image built from `console-api/deploy/Dockerfile.production`
- A Kubernetes `Secret` containing the sensor TLS materials, or values that reference one

PostgreSQL stores transactional Console state. ClickHouse stores analytics and runtime event data.
Both are required for a functional deployment.

## Quick start

Create a values override file with your database, analytics, hostname, and TLS settings, then install:

```bash
helm install telovix-console ./charts/telovix-console \
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
| `image.tag` | string | `latest` | Console image tag |
| `image.pullPolicy` | string | `IfNotPresent` | Image pull policy |
| `deploymentMode` | string | `self_hosted` | Deployment mode: `self_hosted` or `managed` |
| `replicaCount` | int | `1` | Number of Console replicas |
| `service.type` | string | `ClusterIP` | Kubernetes Service type |
| `service.httpPort` | int | `15483` | Operator HTTP API port |
| `service.sensorPort` | int | `15484` | Sensor mTLS listener port |
| `ingress.enabled` | bool | `true` | Create an Ingress resource |
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
| `podSecurityContext.fsGroup` | int | `1001` | Filesystem group for mounted volumes |
| `podSecurityContext.runAsNonRoot` | bool | `true` | Enforce non-root execution |
| `podSecurityContext.runAsUser` | int | `1001` | Runtime UID |
| `sensorTls.secretName` | string | `""` | Secret containing sensor TLS materials |
| `sensorTls.mountPath` | string | `/run/secrets/telovix-tls` | Mount path for the TLS Secret |
| `nameOverride` | string | `""` | Override the chart name |
| `fullnameOverride` | string | `""` | Override the full release name |
