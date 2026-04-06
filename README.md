
# Telovix Sensor - Helm Chart

[![Helm](https://img.shields.io/badge/helm-3.8%2B-blue)](https://helm.sh)
[![Kubernetes](https://img.shields.io/badge/kubernetes-1.21%2B-blue)](https://kubernetes.io)
[![License](https://img.shields.io/badge/license-Commercial-lightgrey)](https://telovix.com)

Deploys the **Telovix eBPF Sensor** as a `DaemonSet` - one sensor per Linux node. The sensor uses eBPF to monitor all host processes, network connections, and file activity in real time and reports to the Telovix Console over mTLS.

Designed for **telecom and Open RAN environments**: supports O-RAN role labeling (`o_du`, `o_cu`, `o_ru`, `gnb`), runs on k3s, k8s, RKE2, EKS, GKE, AKS, and OpenShift.


## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Installation](#installation)
  - [Step 1 - Add the Helm repo](#step-1--add-the-helm-repo)
  - [Step 2 - Generate an enrollment token](#step-2--generate-an-enrollment-token)
  - [Step 3 - Install](#step-3--install)
  - [Step 4 - Verify](#step-4--verify)
- [Configuration](#configuration)
- [Node Roles](#node-roles)
- [Upgrade](#upgrade)
- [Uninstall](#uninstall)
- [Platform Notes](#platform-notes)
  - [k3s](#k3s)
  - [RKE2](#rke2)
  - [EKS / GKE / AKS](#eks--gke--aks)
  - [OpenShift](#openshift)
  - [ARM64](#arm64--graviton--ampere)
- [Security Posture](#security-posture)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

| Requirement | Minimum version / detail |
|---|---|
| Kubernetes or k3s | 1.21+ |
| Helm | 3.8+ |
| Linux kernel | 5.8+ (5.15+ recommended for full eBPF feature set) |
| Telovix Console | Running and reachable from nodes |
| Enrollment token | Generated in Console → Sensors → Deploy |
| Privileges | Namespace must allow `privileged` pods (`hostPID`, `hostNetwork`) |


## Quick Start

```bash
helm repo add telovix https://telovix.github.io/charts
helm repo update

helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE \
  --set clusterName=my-cluster
```

After ~30 seconds, sensors appear in the Telovix Console under **Sensors → Fleet**.

---

## Installation

### Step 1 - Add the Helm repo

```bash
helm repo add telovix https://telovix.github.io/charts
helm repo update
```

### Step 2 - Generate an enrollment token

In the **Telovix Console**, navigate to:

> **Sensors → Deploy → Generate Enrollment Token**

Copy the token. It is valid for one-time use - the sensor exchanges it for an mTLS certificate on first contact with the Console.

### Step 3 - Install

Choose the profile that matches your environment:

#### Development / single-node k3s

```bash
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE
```

#### Production - standard Kubernetes

```bash
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE \
  --set clusterName=prod-k8s-east \
  --set priorityClass.create=true \
  --set resources.requests.cpu=200m \
  --set resources.limits.cpu=4000m
```

#### Production - O-RAN (DU nodes)

```bash
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE \
  --set sensor.nodeRole=o_du \
  --set clusterName=oran-site-helsinki \
  --set priorityClass.create=true \
  --set resources.requests.cpu=200m \
  --set resources.limits.cpu=4000m \
  --set nodeSelector."telovix\.com/role"=o_du
```

#### Using a Kubernetes Secret for the enrollment token (GitOps / ArgoCD)

Store the token as a secret first so it never lives in Helm values or Git:

```bash
kubectl create namespace telovix

kubectl create secret generic telovix-enrollment \
  --namespace telovix \
  --from-literal=enrollmentToken=YOUR_TOKEN_HERE

helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.existingSecret=telovix-enrollment \
  --set clusterName=prod-gitops
```

#### Private registry (GitLab Container Registry)

The Telovix sensor image is hosted in a private registry.
You will receive a read-only deploy token with your Telovix license.

```bash
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_ENROLLMENT_TOKEN \
  --set imageCredentials.username=telovix-helm-pull \
  --set imageCredentials.password=YOUR_REGISTRY_TOKEN \
  --set clusterName=prod-oran-east
```

The chart automatically creates a `kubernetes.io/dockerconfigjson` Secret
in the sensor namespace and attaches it to the DaemonSet pods.

#### Using a values file

```bash
# Download the default values
helm show values telovix/telovix-sensor > my-values.yaml

# Edit my-values.yaml, then install
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  -f my-values.yaml
```

### Step 4 - Verify

```bash
# One pod should exist per node
kubectl get daemonset -n telovix

# All pods should be Running
kubectl get pods -n telovix -l app.kubernetes.io/name=telovix-sensor

# Tail logs on one node
kubectl logs -n telovix \
  -l app.kubernetes.io/name=telovix-sensor \
  --follow --tail=50

# Sensors should appear in the Console within ~30 seconds
# Console: Sensors → Fleet
```


## Configuration

### Core parameters

| Parameter | Description | Default |
|---|---|---|
| `sensor.consoleUrl` | **Required.** Telovix Console base URL | `""` |
| `sensor.enrollmentToken` | Enrollment token (ignored if `existingSecret` set) | `""` |
| `sensor.existingSecret` | Name of existing K8s Secret with key `enrollmentToken` | `""` |
| `sensor.nodeRole` | O-RAN role label for fleet segmentation | `generic_linux` |
| `sensor.nodeNameOverride` | Override the node name reported to Console | `""` (uses K8s node name) |
| `sensor.bootstrapCaCertPath` | Path to Console CA cert - self-hosted deployments only | `""` |
| `clusterName` | Cluster display name in the Console | `""` |

### Image

| Parameter | Description | Default |
|---|---|---|
| `image.registry` | Container registry | `registry.gitlab.com` |
| `image.repository` | Image repository | `telovix/sensor` |
| `image.tag` | Image tag (empty = chart `appVersion`) | `""` |
| `image.pullPolicy` | Pull policy | `IfNotPresent` |
| `image.pullSecrets` | List of image pull secret names | `[]` |
| `imageCredentials.registry` | Registry host used for auto-created pull secret | `registry.gitlab.com` |
| `imageCredentials.username` | Deploy token username for auto-created pull secret | `""` |
| `imageCredentials.password` | Deploy token password for auto-created pull secret | `""` |
| `existingPullSecret` | Existing `imagePullSecret` name to use instead of creating one | `""` |

### Resources

| Parameter | Description | Default |
|---|---|---|
| `resources.requests.cpu` | CPU request | `100m` |
| `resources.requests.memory` | Memory request | `256Mi` |
| `resources.limits.cpu` | CPU limit | `2000m` |
| `resources.limits.memory` | Memory limit | `1024Mi` |

> **Sizing guidance:** Start at 3–5% of node CPU capacity. On a 16-core DU node, `resources.limits.cpu=800m` is a reasonable production ceiling.

### Scheduling

| Parameter | Description | Default |
|---|---|---|
| `tolerations` | Pod tolerations | tolerates all taints |
| `nodeSelector` | Node label selector | `{}` |
| `affinity` | Affinity rules | `{}` |
| `priorityClass.create` | Create a `PriorityClass` | `false` |
| `priorityClass.name` | PriorityClass name | `telovix-sensor-priority` |
| `priorityClass.value` | Priority value | `1000` |

### RBAC & ServiceAccount

| Parameter | Description | Default |
|---|---|---|
| `rbac.create` | Create `ClusterRole` and `ClusterRoleBinding` | `true` |
| `rbac.clusterWide` | Include workload controllers (Deployment, DaemonSet…) | `true` |
| `serviceAccount.create` | Create `ServiceAccount` | `true` |
| `serviceAccount.name` | ServiceAccount name | `telovix-sensor` |
| `serviceAccount.annotations` | Annotations on the ServiceAccount (e.g. IRSA) | `{}` |

### Host paths

| Parameter | Description | Default |
|---|---|---|
| `statePath` | Host path for sensor state (certs, packs) | `/var/lib/telovix-sensor` |
| `bpfPath` | Host path for the BPF filesystem | `/sys/fs/bpf` |

### Advanced

| Parameter | Description | Default |
|---|---|---|
| `updateStrategy.type` | DaemonSet update strategy | `RollingUpdate` |
| `updateStrategy.rollingUpdate.maxUnavailable` | Max unavailable pods during update | `1` |
| `hostPID` | Grant access to host PID namespace | `true` |
| `hostNetwork` | Use host network namespace | `true` |
| `dnsPolicy` | Pod DNS policy | `ClusterFirstWithHostNet` |
| `terminationGracePeriodSeconds` | Graceful shutdown window | `30` |
| `podAnnotations` | Extra annotations on sensor pods | `{}` |
| `podLabels` | Extra labels on sensor pods | `{}` |
| `extraEnv` | Extra environment variables | `[]` |
| `extraVolumes` | Extra volumes | `[]` |
| `extraVolumeMounts` | Extra volume mounts | `[]` |
| `openshift.enabled` | Create OpenShift `SecurityContextConstraints` | `false` |

---

## Node Roles

Use `sensor.nodeRole` to segment your fleet by O-RAN function. This label is used for:

- Policy pack targeting ("enforce on all `o_du` nodes")
- Alert rule scoping ("alert when `o_ru` nodes degrade")
- Fleet health breakdown by role in the Console

| Value | O-RAN function |
|---|---|
| `generic_linux` | General-purpose Linux node |
| `o_du` | Distributed Unit - baseband processing |
| `o_cu` | Central Unit - RRC/PDCP |
| `o_ru` | Radio Unit - RF front-end |
| `gnb` | gNB (monolithic 5G base station) |


## Upgrade

```bash
# Pull latest chart versions
helm repo update

# Upgrade in place, keeping existing values
helm upgrade telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --reuse-values

# Upgrade and change a specific value
helm upgrade telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --reuse-values \
  --set resources.limits.cpu=4000m
```

The DaemonSet uses a `RollingUpdate` strategy with `maxUnavailable: 1` - nodes are updated one at a time. Live monitoring continues on all other nodes during the rollout.


## Uninstall

```bash
# Remove the DaemonSet and all associated resources
helm uninstall telovix-sensor --namespace telovix

# Optionally remove the namespace
kubectl delete namespace telovix
```

> **Note:** Uninstalling removes pods and Kubernetes resources but does NOT delete `/var/lib/telovix-sensor` on the host nodes. Sensor certificates and state persist on disk. If you reinstall later, re-enrollment happens automatically.
>
> To fully wipe sensor identity from a node: `rm -rf /var/lib/telovix-sensor` on that node.


## Platform Notes

### k3s

Works out of the box. No additional configuration required.

```bash
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE \
  --set clusterName=k3s-edge-site-01
```

### RKE2

RKE2 may mount the BPF filesystem at a non-standard path depending on the node configuration. If sensors fail to start with a BPF mount error:

```bash
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE \
  --set bpfPath=/host/sys/fs/bpf
```

### EKS / GKE / AKS

Managed Kubernetes services work without modifications. For token security, use IRSA (EKS), Workload Identity (GKE), or Pod Identity (AKS) to inject the enrollment token from a secrets manager rather than a Helm value:

```bash
# Example: use a secret pre-created via Secrets Manager sync
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.existingSecret=telovix-enrollment-synced \
  --set clusterName=eks-prod-us-east-1
```

### OpenShift

OpenShift's default pod security restricts privileged workloads. Grant the sensor service account access to the `privileged` SCC:

```bash
# Install the chart
helm install telovix-sensor telovix/telovix-sensor \
  --namespace telovix \
  --create-namespace \
  --set sensor.consoleUrl=https://console.your-org.com \
  --set sensor.enrollmentToken=YOUR_TOKEN_HERE \
  --set clusterName=ocp-oran-prod

# Grant privileged SCC
oc adm policy add-scc-to-serviceaccount privileged \
  -z telovix-sensor \
  -n telovix
```

### ARM64 / Graviton / Ampere

The sensor image is multi-arch (`linux/amd64`, `linux/arm64`). No additional configuration required. Automatically selected by Kubernetes based on node architecture.


## Security Posture

The sensor requires elevated privileges because eBPF monitoring operates at the kernel level:

| Privilege | Why it is required |
|---|---|
| `hostPID: true` | Monitor processes across all namespaces and containers - without this, only processes inside the sensor's own namespace are visible |
| `hostNetwork: true` | Track network connections on the host network stack - without this, inter-pod traffic is invisible |
| `privileged: true` | Load eBPF programs into the kernel, pin maps to `/sys/fs/bpf`, lock memory for BPF maps - required by the Linux BPF subsystem |

**What the sensor does NOT do:**

- Does not write to host paths outside `/var/lib/telovix-sensor`
- Does not mount `/etc` writable (read-only mount for OS fingerprinting only)
- Does not require write access to `/proc` (read-only)
- Does not shell out to system tools - the sensor binary is self-contained

These requirements are identical to CrowdStrike Falcon, Sysdig Agent, Falco, and every other kernel-level security sensor. The Linux eBPF verifier enforces all safety guarantees at the kernel level.


## Troubleshooting

### Pods are not starting

```bash
kubectl describe pod -n telovix -l app.kubernetes.io/name=telovix-sensor
kubectl logs -n telovix -l app.kubernetes.io/name=telovix-sensor --previous
```

**Common causes:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `permission denied` on BPF mount | Node BPF path is non-standard | Set `bpfPath=/host/sys/fs/bpf` |
| `failed to pull image` | Image not yet pushed to registry | Push the sensor image or use `image.tag` override |
| `ImagePullBackOff` with private registry | Missing pull secret | Set `imageCredentials.*`, `existingPullSecret`, or `image.pullSecrets` |
| OpenShift `SCC` violation | Missing `privileged` SCC grant | Run `oc adm policy add-scc-to-serviceaccount` (see above) |
| Pod stuck in `Pending` | No node tolerates the DaemonSet | Check taints: `kubectl get nodes -o json \| jq '.items[].spec.taints'` |

### Sensors not appearing in the Console

```bash
# Check if the sensor reached the Console
kubectl logs -n telovix -l app.kubernetes.io/name=telovix-sensor | grep -i enroll
```

- Verify `sensor.consoleUrl` is reachable from within the cluster
- Confirm the enrollment token has not already been used (tokens are single-use)
- For self-hosted Console with a private CA, set `sensor.bootstrapCaCertPath`

### Checking sensor version

```bash
kubectl exec -n telovix \
  -it $(kubectl get pod -n telovix -l app.kubernetes.io/name=telovix-sensor -o jsonpath='{.items[0].metadata.name}') \
  -- /usr/local/bin/telovix-sensor --version
```


## Links

- [Telovix Console](https://telovix.com)
- [Documentation](https://docs.telovix.com)
- [Helm Chart Source](https://github.com/telovix/charts)
- [Support](mailto:support@telovix.com)
