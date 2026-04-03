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
Bitwarden CLI sidecar image with tag defaulting to appVersion
*/}}
{{- define "carapace.bitwardenImage" -}}
{{ .Values.bitwarden.image.registry }}/{{ .Values.bitwarden.image.repository }}:{{ .Values.bitwarden.image.tag | default .Chart.AppVersion }}
{{- end }}
