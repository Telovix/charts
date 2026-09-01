{{/*
Expand the name of the chart.
*/}}
{{- define "telovix-sensor.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "telovix-sensor.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Chart name and version as used by the chart label.
*/}}
{{- define "telovix-sensor.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels applied to all resources.
*/}}
{{- define "telovix-sensor.labels" -}}
helm.sh/chart: {{ include "telovix-sensor.chart" . }}
{{ include "telovix-sensor.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: telovix
{{- end }}

{{/*
Selector labels used by the DaemonSet and pod template.
*/}}
{{- define "telovix-sensor.selectorLabels" -}}
app.kubernetes.io/name: {{ include "telovix-sensor.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: sensor
{{- end }}

{{/*
Full container image reference.
Appends "-telecom" to the tag when flavor is "telecom":
  standard > registry.gitlab.com/telovix/sensor:1.0.0
  telecom  > registry.gitlab.com/telovix/sensor:1.0.0-telecom
*/}}
{{- define "telovix-sensor.image" -}}
{{- $tag := .Values.image.tag | default .Chart.AppVersion }}
{{- if eq .Values.flavor "telecom" }}
{{- if .Values.image.telecomDigest }}
{{- printf "%s/%s@%s" .Values.image.registry .Values.image.repository .Values.image.telecomDigest }}
{{- else }}
{{- printf "%s/%s:%s-telecom" .Values.image.registry .Values.image.repository $tag }}
{{- end }}
{{- else }}
{{- if .Values.image.digest }}
{{- printf "%s/%s@%s" .Values.image.registry .Values.image.repository .Values.image.digest }}
{{- else }}
{{- printf "%s/%s:%s" .Values.image.registry .Values.image.repository $tag }}
{{- end }}
{{- end }}
{{- end }}

{{/* Release-controller resource names and image. */}}
{{- define "telovix-sensor.updaterName" -}}
{{- printf "%s-updater" (include "telovix-sensor.fullname" .) | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "telovix-sensor.updaterServiceAccountName" -}}
{{- if .Values.upgradeController.serviceAccount.create }}
{{- default (include "telovix-sensor.updaterName" .) .Values.upgradeController.serviceAccount.name }}
{{- else }}
{{- required "upgradeController.serviceAccount.name is required when serviceAccount.create=false" .Values.upgradeController.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "telovix-sensor.updaterIdentitySecretName" -}}
{{- default (printf "%s-identity" (include "telovix-sensor.updaterName" .)) .Values.upgradeController.identitySecret }}
{{- end }}

{{- define "telovix-sensor.updaterImage" -}}
{{- if .Values.upgradeController.image.digest }}
{{- printf "%s/%s@%s" .Values.upgradeController.image.registry .Values.upgradeController.image.repository .Values.upgradeController.image.digest }}
{{- else }}
{{- $tag := .Values.upgradeController.image.tag | default .Chart.AppVersion }}
{{- printf "%s/%s:%s" .Values.upgradeController.image.registry .Values.upgradeController.image.repository $tag }}
{{- end }}
{{- end }}

{{/*
Name of the ServiceAccount.
*/}}
{{- define "telovix-sensor.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "telovix-sensor.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Name of the enrollment token Secret.
*/}}
{{- define "telovix-sensor.secretName" -}}
{{- if .Values.sensor.existingSecret }}
{{- .Values.sensor.existingSecret }}
{{- else }}
{{- printf "%s-enrollment" (include "telovix-sensor.fullname" .) }}
{{- end }}
{{- end }}

{{/*
Name of the image pull secret to use.
*/}}
{{- define "telovix-sensor.pullSecretName" -}}
{{- if .Values.existingPullSecret }}
{{- .Values.existingPullSecret }}
{{- else if and .Values.imageCredentials.username .Values.imageCredentials.password }}
{{- printf "%s-registry" (include "telovix-sensor.fullname" .) }}
{{- end }}
{{- end }}
