{{/*
_helpers.tpl — 본 차트의 모든 매니페스트가 공유하는 명명 / 라벨 헬퍼

이 파일은 K8s 매니페스트가 아닙니다 (`_` 로 시작하는 templates 파일은 helm 이 K8s 자원으로 렌더하지 않음).
다른 templates 가 `{{ include "sentiment-api.<name>" . }}` 으로 호출해 사용합니다.

본 차트가 정의하는 4개 헬퍼:
  - sentiment-api.name              짧은 이름 (트리밍됨)
  - sentiment-api.fullname          release 이름이 prefix 된 풀 이름
  - sentiment-api.labels            모든 자원 metadata.labels 에 붙는 표준 라벨 묶음
  - sentiment-api.selectorLabels    Deployment.spec.selector / Service.spec.selector 에 들어가는 안정 라벨
  - sentiment-api.serviceAccountName Phase 3/04 (RBAC) 가 사용할 SA 이름 — 본 토픽에선 정의만, 사용 안 함
*/}}

{{/*
짧은 차트 이름. release 이름 + 이 값으로 fullname 을 만듭니다.
.Chart.Name 이 보통 "sentiment-api" 라 trunc 63 은 거의 의미 없지만, K8s DNS 라벨 한도 (RFC 1123 = 63자) 안전 장치.
*/}}
{{- define "sentiment-api.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
fullname — 자원의 metadata.name 에 들어가는 값.
규칙:
  - .Values.fullnameOverride 가 있으면 그것을 사용
  - release 이름이 차트 이름을 이미 포함하면 release 이름만 사용 (중복 방지: helm install sentiment-api → "sentiment-api" 한 번만)
  - 그 외에는 release-chart 형태 (예: helm install foo → "foo-sentiment-api")
*/}}
{{- define "sentiment-api.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
chart label — app.kubernetes.io/version 에 사용하는 "차트이름-버전" 형식.
점(.)을 underscore 로 바꾸는 이유: K8s label 값에 "+" 같은 SemVer 메타데이터 문자가 들어가면 거부됨.
*/}}
{{- define "sentiment-api.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
표준 라벨 묶음 — 모든 자원의 metadata.labels 에 들어감.
app.kubernetes.io/* 는 K8s 표준 라벨 (Helm Best Practices 준수).
"app: sentiment-api" 는 Phase 1·2 매니페스트와의 호환을 위해 유지 (Service selector 등이 이 라벨을 매칭).
*/}}
{{- define "sentiment-api.labels" -}}
helm.sh/chart: {{ include "sentiment-api.chart" . }}
{{ include "sentiment-api.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
selectorLabels — Deployment.spec.selector / Service.spec.selector 가 사용.
selector 는 immutable (Deployment 생성 후 변경 불가) 이라, 시간이 지나도 안 바뀔 안정 라벨만 포함합니다.
"app: sentiment-api" 는 Phase 1·2 와의 호환 라벨 — 본 차트가 release 이름을 다르게 줘도 Phase 2/05 의 ResourceQuota 가
selector 매칭에 의존하지 않으므로 영향 없음.
*/}}
{{- define "sentiment-api.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sentiment-api.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app: sentiment-api
{{- end -}}

{{/*
serviceAccountName — Phase 3/04 (RBAC) 가 활성화할 헬퍼.
본 토픽에서는 어떤 templates 도 호출하지 않으며, 정의만 둡니다.
*/}}
{{- define "sentiment-api.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "sentiment-api.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}
