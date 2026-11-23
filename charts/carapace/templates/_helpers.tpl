{{- define "carapace.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 999
runAsGroup: 999
fsGroup: 999
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{- define "carapace.containerSecurityContext" -}}
readOnlyRootFilesystem: true
allowPrivilegeEscalation: false
capabilities:
  drop: [ALL]
{{- end }}

{{/*
Common labels
*/}}
{{- define "carapace.labels" -}}
app.kubernetes.io/name: carapace
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{- end }}

{{/*
Server image with tag defaulting to appVersion
*/}}
{{- define "carapace.serverImage" -}}
{{ .Values.image.registry }}/{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Frontend image with tag defaulting to appVersion
*/}}
{{- define "carapace.frontendImage" -}}
{{ .Values.frontend.image.registry }}/{{ .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Sandbox image with tag defaulting to appVersion
*/}}
{{- define "carapace.sandboxImage" -}}
{{ .Values.sandbox.image.registry }}/{{ .Values.sandbox.image.repository }}:{{ .Values.sandbox.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Sandbox owner name. Nil means use the release default, empty string means Deployment fallback.
*/}}
{{- define "carapace.sandboxesName" -}}
{{- if eq .Values.sandbox.sandboxesName nil -}}
{{ printf "%s-sandboxes" .Release.Name }}
{{- else -}}
{{ .Values.sandbox.sandboxesName }}
{{- end -}}
{{- end }}

{{/*
Postgres image with tag.
*/}}
{{- define "carapace.postgresImage" -}}
{{ .Values.postgres.image.registry }}/{{ .Values.postgres.image.repository }}:{{ required "postgres.image.tag is required: pin the Postgres major (e.g. 19-alpine), the chart cannot migrate data between majors" .Values.postgres.image.tag }}
{{- end }}

{{/*
Postgres Secret name (generated, or the user-provided existingSecret).
*/}}
{{- define "carapace.postgres.secretName" -}}
{{- .Values.postgres.auth.existingSecret | default (printf "%s-postgres" .Release.Name) -}}
{{- end }}

{{/*
CARAPACE_DATABASE_URL env entry for the server container.
- postgres.enabled: pull the assembled SQLAlchemy URL from the Postgres Secret.
- else database.url set: inline external URL.
- else: nothing (server falls back to SQLite on the data PVC).
*/}}
{{- define "carapace.databaseUrlEnv" -}}
{{- if .Values.postgres.enabled -}}
- name: CARAPACE_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ include "carapace.postgres.secretName" . }}
      key: {{ .Values.postgres.auth.urlKey }}
# Password supplied out-of-band so special characters never need URL-encoding; libpq
# (psycopg) reads PGPASSWORD when the URL omits the password.
- name: PGPASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ include "carapace.postgres.secretName" . }}
      key: {{ .Values.postgres.auth.passwordKey }}
{{- else if .Values.database.url -}}
- name: CARAPACE_DATABASE_URL
  value: {{ .Values.database.url | quote }}
{{- end -}}
{{- end }}

{{/*
Bitwarden CLI image with tag defaulting to appVersion
*/}}
{{- define "carapace.bitwardenImage" -}}
{{ .Values.bitwarden.image.registry }}/{{ .Values.bitwarden.image.repository }}:{{ .Values.bitwarden.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Bitwarden nginx proxy image
*/}}
{{- define "carapace.bitwardenNginxImage" -}}
{{ .Values.bitwarden.nginx.image.registry }}/{{ .Values.bitwarden.nginx.image.repository }}:{{ .Values.bitwarden.nginx.image.tag }}
{{- end }}

{{/*
Standalone Bitwarden resource name for one instance.
*/}}
{{- define "carapace.bitwardenStandaloneName" -}}
{{- $root := .root -}}
{{- $instance := .instance -}}
{{- if $instance.fullnameOverride -}}
{{ $instance.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else -}}
{{ printf "%s-bitwarden-%s" $root.Release.Name $instance.name | trunc 63 | trimSuffix "-" }}
{{- end -}}
{{- end }}

{{/*
Builder image with tag defaulting to appVersion
*/}}
{{- define "carapace.builderImage" -}}
{{ .Values.builder.image.registry }}/{{ .Values.builder.image.repository }}:{{ .Values.builder.image.tag | default .Chart.AppVersion }}
{{- end }}

{{/*
Builder token Secret name (generated for the in-cluster builder, or the user-provided existingSecret).
*/}}
{{- define "carapace.builder.secretName" -}}
{{- .Values.builder.auth.existingSecret | default (printf "%s-builder" .Release.Name) -}}
{{- end }}

{{/*
CARAPACE_BUILDER_URL and _TOKEN for the server: the in-cluster builder, or one on another machine.
*/}}
{{- define "carapace.builderEnv" -}}
{{- if .Values.builder.enabled -}}
- name: CARAPACE_BUILDER_URL
  value: {{ printf "http://%s-builder:8330" .Release.Name | quote }}
- name: CARAPACE_BUILDER_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ include "carapace.builder.secretName" . }}
      key: token
{{- else if .Values.builder.externalUrl -}}
- name: CARAPACE_BUILDER_URL
  value: {{ .Values.builder.externalUrl | quote }}
- name: CARAPACE_BUILDER_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ required "builder.auth.existingSecret is required with builder.externalUrl" .Values.builder.auth.existingSecret }}
      key: token
{{- end -}}
{{- end }}
