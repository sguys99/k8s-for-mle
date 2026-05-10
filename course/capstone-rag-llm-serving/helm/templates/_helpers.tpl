{{/*
_helpers.tpl — 본 차트의 모든 매니페스트가 공유하는 명명 / 라벨 헬퍼

이 파일은 K8s 매니페스트가 아닙니다 (`_` 로 시작하는 templates 파일은 helm 이 K8s 자원으로 렌더하지 않음).
다른 templates 가 `{{ include "capstone-rag-llm.<name>" . }}` 으로 호출해 사용합니다.

본 차트가 정의하는 5 개 헬퍼 (Phase 3-01 패턴 계승):
  - capstone-rag-llm.name              짧은 차트 이름 (trunc 63)
  - capstone-rag-llm.fullname          release 이름 prefix 가 붙은 풀 이름 (예: rag-llm-vllm)
  - capstone-rag-llm.chart             "capstone-rag-llm-0.1.0" 형태 (label 안전 변환)
  - capstone-rag-llm.commonLabels      모든 자원 metadata.labels 에 붙는 표준 라벨 묶음 + part-of
  - capstone-rag-llm.componentLabels   selector 안정 라벨 (component 별 호출 — 사용처가 component 명을 인자로 전달)

캡스톤 컨벤션과의 호환:
  raw 매니페스트(00~61) 가 `app: <component>` (vllm/rag-api/qdrant) + `component: <role>` 라벨을 사용하므로,
  componentLabels 는 호출자가 component 이름을 전달하면 두 라벨을 모두 채우는 형식으로 설계.
*/}}

{{/*
짧은 차트 이름. release 이름 + 이 값으로 fullname 을 만듭니다.
.Chart.Name 이 보통 "capstone-rag-llm" 이라 trunc 63 은 안전 장치.
*/}}
{{- define "capstone-rag-llm.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
fullname — 자원의 metadata.name prefix 에 사용 (본 차트는 component 이름이 raw 매니페스트와 같아야 해서
대부분의 자원은 fullname 을 쓰지 않고 component 이름을 직접 사용 — 예: Service "vllm" 그대로).
fullname 은 release 별로 충돌을 피해야 하는 자원(Argo Workflow generateName 등) 에서 선택적으로 사용.

규칙:
  - .Values.fullnameOverride 가 있으면 그것을 사용
  - release 이름이 차트 이름을 이미 포함하면 release 이름만 사용
  - 그 외에는 release-chart 형태
*/}}
{{- define "capstone-rag-llm.fullname" -}}
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
chart label — app.kubernetes.io/version 등에 사용하는 "차트이름-버전" 형식.
점(.)을 underscore 로 바꾸는 이유: K8s label 값에 "+" 같은 SemVer 메타데이터 문자가 들어가면 거부됨.
*/}}
{{- define "capstone-rag-llm.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
commonLabels — 모든 자원의 metadata.labels 에 들어가는 표준 라벨 묶음.

K8s 표준 라벨 (Helm Best Practices) + 캡스톤 식별 라벨:
  - app.kubernetes.io/name        : 차트 이름 ("capstone-rag-llm")
  - app.kubernetes.io/instance    : release 이름 (예: "rag-llm")
  - app.kubernetes.io/version     : Chart.yaml 의 appVersion
  - app.kubernetes.io/managed-by  : "Helm" (Release.Service)
  - app.kubernetes.io/part-of     : "capstone-rag-llm" (캡스톤 식별)
  - helm.sh/chart                 : "capstone-rag-llm-0.1.0"

호출 예 (다른 templates 안):
  metadata:
    labels:
      {{- include "capstone-rag-llm.commonLabels" . | nindent 4 }}
      app: vllm
      component: llm-serving
*/}}
{{- define "capstone-rag-llm.commonLabels" -}}
helm.sh/chart: {{ include "capstone-rag-llm.chart" . }}
app.kubernetes.io/name: {{ include "capstone-rag-llm.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: capstone-rag-llm
{{- end -}}

{{/*
componentLabels — 컴포넌트 선택자(Service.spec.selector / Deployment.spec.selector) 안정 라벨.

캡스톤 raw 매니페스트가 `app: <component>` (vllm/rag-api/qdrant) 패턴을 사용하므로,
호출자가 component 이름을 dict 로 전달하면 두 라벨을 채워서 반환.

호출 예:
  spec:
    selector:
      matchLabels:
        {{- include "capstone-rag-llm.componentLabels" (dict "component" "vllm" "role" "llm-serving") | nindent 8 }}

selector 는 immutable (Deployment 생성 후 변경 불가) 이라, 시간이 지나도 안 바뀔 라벨만 포함합니다.
release 이름은 selector 에 포함하지 않음 — Phase 3-01 패턴 따름 (raw 매니페스트와 selector 호환).
*/}}
{{- define "capstone-rag-llm.componentLabels" -}}
app: {{ .component }}
{{- if .role }}
component: {{ .role }}
{{- end }}
{{- end -}}
