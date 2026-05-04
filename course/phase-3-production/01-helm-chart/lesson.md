# Helm 차트 — Phase 2 의 dev/prod 매니페스트 두 벌을 한 차트로 묶기

> **Phase**: 3 — 프로덕션 운영 도구 (첫 번째 토픽)
> **소요 시간**: 60–80분 (Phase 2/05 의 dev / prod ResourceQuota / LimitRange 가 살아 있는 가정 — 살아 있지 않으면 lab 0 단계에서 5분 안에 재적용)
> **선수 학습**:
> - [Phase 2 / 05-namespace-quota — Namespace, ResourceQuota, LimitRange](../../phase-2-operations/05-namespace-quota/lesson.md) — 본 토픽의 차트가 install 되는 namespace 와 admission 가드레일이 모두 거기서 만들어졌습니다.
> - [Phase 2 / 02-volumes-pvc — Volumes & PVC](../../phase-2-operations/02-volumes-pvc/lesson.md) — initContainer 모델 다운로드 패턴이 차트의 Deployment 에 그대로 들어갑니다.
> - [Phase 2 / 01-configmap-secret](../../phase-2-operations/01-configmap-secret/lesson.md) — `inference.yaml` ConfigMap 키가 그대로 차트 templates 의 ConfigMap 으로 매핑됩니다.

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Helm 차트의 3구성 — `Chart.yaml`(메타데이터) / `values.yaml`(기본값) / `templates/`(Go template 매니페스트) — 의 역할 분담을 [manifests/chart/sentiment-api/](manifests/chart/sentiment-api/) 의 실제 파일로 설명하고, `helm create` 가 만드는 nginx 보일러플레이트를 본 차트와 직접 비교해 "왜 보일러플레이트를 그대로 쓰면 안 되는지" 를 한 단락으로 정리할 수 있습니다.
- Helm 템플릿 5문법 (`.Values.x.y` / `.Release.Name|Namespace` / `{{- include "..." . | nindent 4 }}` / `{{- if .Values.persistence.enabled }}` / `{{ toYaml .Values.resources | nindent 12 }}`) 을 [templates/deployment.yaml](manifests/chart/sentiment-api/templates/deployment.yaml) 에서 직접 짚어 설명하고, `helm template ./chart -f values-dev.yaml` vs `... -f values-prod.yaml` 의 렌더링 차이를 라인 단위로 비교할 수 있습니다.
- values 우선순위 — `values.yaml`(기본값) < `-f values-<env>.yaml` < `--set key=value` < `--set-file key=path` — 4단계를 [values.yaml](manifests/chart/sentiment-api/values.yaml) / [values-dev.yaml](manifests/chart/sentiment-api/values-dev.yaml) / [values-prod.yaml](manifests/chart/sentiment-api/values-prod.yaml) 의 차이와 `--set replicaCount=3` 한 줄이 어떻게 두 파일을 모두 덮어쓰는지로 직접 검증할 수 있습니다.
- Helm 라이프사이클 명령 4개 (`install` / `upgrade` / `rollback` / `uninstall`) 와 `helm history` / `helm get values` / `helm get manifest` 3개 보조 명령을 [labs/README.md](labs/README.md) 의 4·5·6·7·8단계로 직접 실행해, dev 환경의 replicas 를 1 → 3 으로 올리고 다시 1 로 되돌리는 두 revision 을 history 에 남겨 두 revision 이 어떻게 다른지 `helm get manifest <release> --revision <N>` 으로 비교할 수 있습니다.
- Phase 2/05 의 `dev-quota` / `dev-limitrange` 가 admission 단계에서 차트 install 결과를 검사하고, 차트가 만든 Pod 의 비어 있는 `resources` 가 LimitRange default 로 자동으로 채워지는 흐름을 `kubectl describe quota dev-quota -n dev` 의 `used` 컬럼 변화로 직접 관찰해, "차트는 운영자가 깔아둔 가드레일 안으로 install 된다" 는 패턴을 자기 말로 설명할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

Phase 2/05 까지 학습자는 같은 5개 자원(ConfigMap + Secret + PVC + Deployment + Service)을 **dev 와 prod 두 벌로 손으로** 만들었습니다. 두 매니페스트 [sentiment-api-dev.yaml](../../phase-2-operations/05-namespace-quota/manifests/sentiment-api-dev.yaml) / [sentiment-api-prod.yaml](../../phase-2-operations/05-namespace-quota/manifests/sentiment-api-prod.yaml) 을 비교하면 차이는 6가지뿐입니다 — `replicas`(1 vs 2), `APP_VERSION`(v1-dev vs v1-prod), `LOG_LEVEL`(DEBUG vs INFO), `batch_size`(16 vs 32), `resources` 명시 여부, PVC 이름·크기. 나머지 200줄은 두 파일이 **글자 단위로 같습니다**. 환경이 staging 까지 늘면 세 벌, 추가 모델이 들어오면 여섯 벌 — 한 줄 바꾸려면 N 곳을 손으로 동기화해야 하고, 한 곳만 빠뜨려도 운영 사고가 됩니다. Helm 은 정확히 이 자리에 들어갑니다. ML 엔지니어에게 본 토픽이 특별히 중요한 이유는 셋입니다. ① **ML 스택은 거의 다 Helm 으로 배포됩니다** — Phase 3/02 의 kube-prometheus-stack, Phase 4/01 의 NVIDIA GPU Operator, Phase 4/02 의 KServe, Phase 4/03 의 vLLM, Phase 4/04 의 Argo Workflows 모두 공식 차트를 통해 들어옵니다. 차트를 못 읽으면 ML 도구 도입 자체가 어려워집니다. ② **values.yaml 이 환경 차이의 단일 진실 소스가 됩니다** — Phase 2/05 의 `dev` namespace 와 `prod` namespace 의 차이가 매니페스트 200줄이 아니라 `values-dev.yaml` 의 6줄로 압축됩니다. 운영 변경이 6줄 PR 1개로 끝납니다. ③ **차트는 운영자가 깔아둔 가드레일과 자연스럽게 협력합니다** — Phase 2/05 의 ResourceQuota / LimitRange 는 `helm install` 의 admission 검사를 그대로 수행하므로, 차트가 가드레일을 우회하지 않습니다. 본 토픽이 완성되는 순간 Phase 2 의 손작업 6벌이 `helm install -f values-dev.yaml` 한 줄로 줄어들고, Phase 3/02 (Prometheus) / 03 (HPA) / 04 (RBAC) 가 이 차트 위에 점진적으로 얹힙니다.

## 1. 핵심 개념

### 1-1. Helm 차트 — Chart.yaml / values.yaml / templates/ 3구성

Helm 차트는 본질적으로 **"K8s 매니페스트 묶음 + 그 안의 변수를 채울 기본값 + 메타데이터"** 입니다. 본 토픽 [manifests/chart/sentiment-api/](manifests/chart/sentiment-api/) 의 실제 파일과 매핑하면:

| 파일/디렉토리 | 역할 | 본 차트의 내용 |
|--------------|------|--------------|
| [Chart.yaml](manifests/chart/sentiment-api/Chart.yaml) | 차트 자체의 메타데이터 (이름, 버전, appVersion) | `name: sentiment-api`, `version: 0.1.0`, `appVersion: "v1"` |
| [values.yaml](manifests/chart/sentiment-api/values.yaml) | **기본값**. 사용자가 override 하지 않을 때 쓰일 값 | `replicaCount: 1`, `image.tag: v1`, `model.batchSize: 32`, ... |
| [templates/](manifests/chart/sentiment-api/templates/) | Go template 으로 작성한 K8s 매니페스트들 | `configmap.yaml`, `secret.yaml`, `pvc.yaml`, `deployment.yaml`, `service.yaml`, `_helpers.tpl`, `NOTES.txt` |
| `values-<env>.yaml` (선택) | 환경별 override. 본 차트에선 [values-dev.yaml](manifests/chart/sentiment-api/values-dev.yaml) / [values-prod.yaml](manifests/chart/sentiment-api/values-prod.yaml) | 6줄 안팎으로 환경 차이만 표현 |
| `templates/_helpers.tpl` | 여러 매니페스트가 공유하는 명명 규칙·라벨 헬퍼 | `sentiment-api.fullname`, `sentiment-api.labels`, `sentiment-api.selectorLabels` |
| `templates/NOTES.txt` | install 직후 출력되는 안내 메시지 | `kubectl port-forward` 명령과 `/ready` curl 안내 |
| `charts/` (선택) | 의존 차트 — 본 토픽에서는 사용 안 함 | (없음) — Phase 3/02 의 kube-prometheus-stack 이 의존 차트의 첫 사례 |

> 💡 `helm create my-chart` 는 보일러플레이트로 nginx 차트를 만듭니다. 학습자가 처음 부딪히는 함정은 **그 보일러플레이트의 templates 를 그대로 두고 values 만 바꾸는 것** 입니다 — `serviceAccount`, `ingress`, `autoscaling`, `tests/` 등 학습자가 이해하지 못한 자산이 함께 따라옵니다. 본 차트는 **Phase 2 가 실제로 사용하는 5개 자원만** 포함합니다 ([labs 1단계](labs/README.md#1단계--helm-create-보일러플레이트와-비교) 에서 둘을 직접 비교).

### 1-2. 템플릿 문법 — 이 5가지면 본 차트의 모든 줄을 읽을 수 있습니다

Helm 의 templates 는 [Go text/template](https://pkg.go.dev/text/template) 위에 [Sprig 함수](http://masterminds.github.io/sprig/) 를 얹은 것입니다. 문법은 광범위하지만, 본 차트가 실제로 쓰는 것은 5가지뿐입니다.

| 문법 | 의미 | 본 차트 등장 위치 |
|------|------|----------------|
| `{{ .Values.x.y }}` | values.yaml(또는 -f / --set) 에서 채워지는 값 | [deployment.yaml](manifests/chart/sentiment-api/templates/deployment.yaml) 의 `replicas: {{ .Values.replicaCount }}` |
| `{{ .Release.Name }}` / `{{ .Release.Namespace }}` | helm 이 install 시점에 자동으로 채우는 값 — release 이름과 namespace | [pvc.yaml](manifests/chart/sentiment-api/templates/pvc.yaml) 의 `name: model-cache-{{ .Release.Namespace }}` |
| `{{- include "sentiment-api.labels" . \| nindent 4 }}` | `_helpers.tpl` 의 named template 을 include 하고 4 칸 들여쓰기 | 모든 매니페스트의 `metadata.labels` |
| `{{- if .Values.persistence.enabled }} ... {{- end }}` | 조건부 — false 면 매니페스트 자체가 생성되지 않음 | [pvc.yaml](manifests/chart/sentiment-api/templates/pvc.yaml) 전체를 감쌈 |
| `{{ toYaml .Values.resources \| nindent 12 }}` | values 의 dict 를 그대로 YAML 로 펼치고 12칸 들여쓰기 | [deployment.yaml](manifests/chart/sentiment-api/templates/deployment.yaml) 의 main 컨테이너 `resources:` 자리 |

#### `{{-`와 `-}}`의 의미

대시 한 칸 차이가 렌더링 결과를 크게 바꿉니다.

```yaml
# {{- 는 앞쪽 공백/개행을 trim
{{- if .Values.persistence.enabled }}
apiVersion: v1
kind: PersistentVolumeClaim
{{- end }}
```

- `{{- ...}}` — 표현식 **앞** 의 공백·개행을 제거 (위로 끌어올림)
- `{{- ... -}}` — 양쪽 공백·개행을 모두 제거
- `{{ ... -}}` — 표현식 **뒤** 의 공백·개행을 제거

`if/with/range` 같은 흐름 제어는 거의 항상 `{{-`로 시작합니다 — 안 그러면 빈 줄이 매니페스트에 남아 들여쓰기가 깨집니다.

#### `nindent` vs `indent`

`nindent N` = "**개행 + N칸 공백 들여쓰기**", `indent N` = "**N칸 공백 들여쓰기 (개행 없음)**". 본 차트의 `metadata.labels:` 자리에 `include` 결과를 넣을 때:

```yaml
metadata:
  name: sentiment-api
  labels:
    {{- include "sentiment-api.labels" . | nindent 4 }}
```

`nindent 4` 는 라벨 키들을 `    app.kubernetes.io/name: ...` 처럼 4칸 들여 깔끔히 정렬합니다. `indent` 를 잘못 쓰면 `metadata:` 다음 라인에 라벨이 한 줄로 붙어 들여쓰기가 깨집니다. **자주 하는 실수 2번 후보** — `helm template` 으로 렌더링한 결과가 깨져 보이면 99%가 nindent 들여쓰기 숫자 문제입니다.

> 💡 `_helpers.tpl` 의 진짜 의미는 **DRY** — 같은 라벨 묶음(`app.kubernetes.io/name`, `instance`, `version`, `managed-by`, `app`)을 매니페스트 5개에 5번 적기 싫어서 1번 정의하고 5번 include 하는 패턴입니다. 본 차트의 `_helpers.tpl` 4 헬퍼는 모두 이 목적입니다 — Phase 3/02 (Prometheus) 가 ServiceMonitor 를 추가하면 같은 헬퍼를 그대로 재사용합니다.

### 1-3. values 우선순위 — 4단계 override

같은 키가 여러 곳에 정의되면 더 늦게(우선순위가 높게) 평가되는 쪽이 이깁니다.

```
[1] 차트 자체의 values.yaml         (낮음)
       ↓ 덮어씀
[2] -f values-dev.yaml              (-f 여러 번이면 뒤가 덮어씀)
       ↓ 덮어씀
[3] --set replicaCount=3            (CLI 인자)
       ↓ 덮어씀
[4] --set-file my.cert=./cert.pem   (파일 내용을 값으로) (높음)
```

본 차트의 `replicaCount` 가 어떻게 결정되는지 단계별로:

| 단계 | 명령 | 평가 결과 |
|------|------|----------|
| (1) 기본값만 | `helm install sentiment-api ./chart -n dev` | 1 (values.yaml 의 기본값) |
| (2) -f 추가 | `helm install ... -n dev -f values-dev.yaml` | 1 (values-dev.yaml 도 1 — 덮어쓰기 효과 없음) |
| (3) -f + --set | `helm install ... -n dev -f values-dev.yaml --set replicaCount=3` | 3 (--set 이 -f 를 덮어씀) |
| prod 으로 install | `helm install ... -n prod -f values-prod.yaml` | 2 (values-prod.yaml 의 값) |

#### 조회 명령

install 후 어떤 값이 적용 중인지 확인:

```bash
helm get values sentiment-api -n dev               # 사용자가 -f / --set 으로 override 한 값만
helm get values sentiment-api -n dev --all         # 차트 기본값까지 머지된 전체
helm get manifest sentiment-api -n dev             # 최종 렌더링된 K8s 매니페스트
```

> 💡 운영 디버깅의 표준은 `--all` 입니다. 사용자 override 만 보면 "왜 이 옵션이 동작 안 하지?" 라고 한참 헤매다가 "차트 기본값에 같은 키가 다른 형태로 잡혀 있었다" 가 발견됩니다.

### 1-4. 라이프사이클 명령 — install / upgrade / rollback / uninstall

Helm 은 release(= 한 namespace 안에 install 된 차트의 인스턴스) 단위로 상태를 관리합니다.

```
                ┌──────────────────────┐
helm install    │ release v1 (Deployed) │
   ─────────►   └──────────────────────┘
                          │
                          │  helm upgrade --set replicaCount=3
                          ▼
                ┌──────────────────────┐
                │ release v2 (Deployed) │  ← v1 은 history 에 보존 (Superseded)
                └──────────────────────┘
                          │
                          │  helm rollback sentiment-api 1
                          ▼
                ┌──────────────────────┐
                │ release v3 (Deployed) │  ← v2 의 매니페스트를 v1 의 매니페스트로 다시 만듦
                └──────────────────────┘
                          │
                          │  helm uninstall sentiment-api
                          ▼
                       (없음)
```

| 명령 | 효과 | 본 토픽 lab 단계 |
|------|------|---------------|
| `helm install <name> <chart> -n <ns>` | release 생성 | [4단계 (dev)](labs/README.md#4단계--dev-에-helm-install) / [5단계 (prod)](labs/README.md#5단계--prod-에-helm-install) |
| `helm upgrade <name> <chart> --set k=v` | 새 revision 으로 변경 적용 | [6단계](labs/README.md#6단계--helm-upgrade-로-replicas-변경) |
| `helm upgrade --install <name> <chart>` | 없으면 install, 있으면 upgrade — CI 의 표준 | (자주 하는 실수 2번에서 설명) |
| `helm rollback <name> <revision>` | 지정 revision 으로 되돌림 (새 revision 생성) | [7단계](labs/README.md#7단계--helm-rollback-으로-되돌리기) |
| `helm uninstall <name> -n <ns>` | release 와 그 안의 자원 삭제 | [8단계](labs/README.md#8단계--helm-uninstall) |
| `helm list -A` | 모든 namespace 의 release | 4·5단계 |
| `helm history <name> -n <ns>` | revision 이력 (REVISION / STATUS / CHART / DESCRIPTION) | 6·7단계 |
| `helm get values <name> -n <ns>` | 현재 적용 중인 values | 5·6단계 |
| `helm get manifest <name> -n <ns> --revision <N>` | 특정 revision 의 렌더링된 매니페스트 | 7단계 |

#### `helm template` 과 `--dry-run` 의 차이

| 명령 | 클러스터에 접속? | 동작 |
|------|---------------|------|
| `helm template ./chart -f values-dev.yaml` | **아니오** | 클라이언트에서 렌더링만 하고 stdout 에 출력. CRD 검증·서버 admission 검사 없음 |
| `helm install ... --dry-run --debug` | **예** | 서버에 보내 dry-run admission 검사까지 받음. ResourceQuota 위반 같은 admission 거절을 미리 잡을 수 있음 |

본 차트 검증의 표준 흐름은 **`helm lint` → `helm template` (구조 검증) → `helm install --dry-run --debug` (admission 검증) → 실제 install** 4단계입니다 ([labs 2·3단계](labs/README.md)).

### 1-5. 환경별 분리 — values-dev.yaml / values-prod.yaml + Phase 2/05 가드레일

본 차트의 핵심 디자인 결정은 "**환경 차이를 templates 에 넣지 않고 values 에 넣는다**" 입니다. Phase 2/05 의 두 묶음 매니페스트에서 차이가 났던 6가지가 이렇게 흡수됩니다.

| Phase 2/05 의 차이 | dev 매니페스트 | prod 매니페스트 | 본 차트 흡수 방식 |
|--------------------|---------------|----------------|-----------------|
| `replicas` | 1 | 2 | `values.yaml: replicaCount: 1` 기본 + `values-prod.yaml: replicaCount: 2` 덮어씀 |
| `APP_VERSION` | v1-dev | v1-prod | `values-dev.yaml: env.APP_VERSION: v1-helm-dev` / `values-prod.yaml: env.APP_VERSION: v1-helm-prod` |
| `LOG_LEVEL` | DEBUG | INFO | `values-dev.yaml: env.LOG_LEVEL: DEBUG` / `values-prod.yaml: env.LOG_LEVEL: INFO` |
| `batch_size` | 16 | 32 | `values-dev.yaml: model.batchSize: 16` / `values-prod.yaml: model.batchSize: 32` |
| `resources` 명시 | (비어 있음 — LimitRange default 위임) | 명시됨 | `values-dev.yaml: resources: {}` / `values-prod.yaml: resources: { requests/limits 명시 }` |
| PVC 이름·크기 | `model-cache-dev` / 1Gi | `model-cache-prod` / 2Gi | `name: model-cache-{{ .Release.Namespace }}` (자동) + `values-<env>.yaml: persistence.size` |

#### "차트는 가드레일 위에 install 된다"

Phase 2/05 에서 만든 `dev-quota` / `dev-limitrange` / `prod-quota` / `prod-limitrange` 4개 자원은 **본 차트에 포함되지 않습니다**. 그 이유:

- **권한 분리**: ResourceQuota / LimitRange 는 보통 플랫폼 팀(또는 SRE) 이 namespace 생성과 함께 미리 깔아둡니다. 차트는 application 팀의 산출물이라 이 둘을 만들 권한이 보통 없습니다 (Phase 3/04 RBAC 토픽의 직접 발판).
- **lifecycle 분리**: 차트의 `helm uninstall` 은 release 자원만 지워야 합니다. 가드레일이 차트와 함께 사라지면 다음 install 까지 그 namespace 가 무방비 상태가 됩니다.
- **환경 정책의 영속성**: dev quota 는 dev namespace 의 정책이지 sentiment-api 의 정책이 아닙니다. 다른 차트(예: Phase 3/02 의 Prometheus) 도 같은 가드레일을 공유합니다.

본 토픽 lab 4단계가 이 패턴을 직접 시연합니다 — `helm install` 의 결과 Pod 의 비어 있는 `resources` 가 `dev-limitrange` 의 default 로 채워지고, dev quota 의 `requests.cpu` used 가 0 → 200m 으로 변합니다. 차트는 가드레일을 우회하지 않습니다.

#### Phase 3/02·03·04 와의 자연스러운 연결

본 토픽이 만드는 차트는 다음 토픽들이 **점진적으로 evolve** 시킵니다.

- **Phase 3/02 (Prometheus + Grafana)**: `templates/servicemonitor.yaml` 추가, `values.yaml` 의 `monitoring.serviceMonitor.enabled` placeholder 가 `true` 로 활성화. 본 토픽 values.yaml 에 placeholder 자리만 비워둡니다.
- **Phase 3/03 (HPA)**: `templates/hpa.yaml` 추가, `values.yaml` 의 `autoscaling.enabled` 가 `true` 로 활성화.
- **Phase 3/04 (RBAC)**: `templates/serviceaccount.yaml` + `role.yaml` + `rolebinding.yaml` 추가. `_helpers.tpl` 의 `sentiment-api.serviceAccountName` 헬퍼가 그때 처음 의미를 갖습니다 (본 토픽에선 정의만 두고 사용하지 않음).

> 💡 본 토픽의 [values.yaml](manifests/chart/sentiment-api/values.yaml) 에는 `monitoring`, `autoscaling`, `ingress`, `serviceAccount` 4개 섹션이 `enabled: false` placeholder 로 미리 들어가 있습니다. **templates 는 만들지 않습니다** — references/phase-3-production.md 의 "values.yaml 에 너무 많은 옵션 넣지 말기" 원칙을 지키되, 다음 토픽이 "values.yaml 에 옵션을 추가" 가 아니라 "templates 만 추가" 의 작은 PR 로 끝나도록 자리만 잡아둡니다.

## 2. 실습

본 토픽의 실습은 [labs/README.md](labs/README.md) 에 단계별 명령 + 예상 출력으로 정리되어 있습니다. 핵심 흐름만 요약합니다.

| 단계 | 무엇을 하는가 | 핵심 검증 |
|------|------------|---------|
| **0** | 사전 준비 — helm 설치 / Phase 2/05 dev·prod namespace + ResourceQuota + LimitRange 생존 점검 | `helm version` 이 v3.x, `kubectl get quota -A` 가 dev/prod 둘 다 표시 |
| **1** | `helm create` 보일러플레이트 만들어보고 본 차트와 비교 | nginx 가 들어 있는 확인 → 보일러플레이트 그대로 쓰면 안 되는 이유 체감 |
| **2** | `helm template ./chart -f values-dev.yaml` vs `... -f values-prod.yaml` 로 렌더링 비교 | 두 결과의 diff 가 `values-dev/prod.yaml` 의 6줄 차이만큼만 발생 |
| **3** | `helm lint` + `helm install --dry-run --debug` | lint PASS / dry-run 이 admission 단계까지 통과 |
| **4** | dev 에 install (`helm install -n dev -f values-dev.yaml`) | dev quota used 가 200m 으로 변함 — Phase 2/05 4-5단계와 동일 |
| **5** | prod 에 install (`helm install -n prod -f values-prod.yaml`) + `helm list -A` / `helm get values` / `helm get manifest` | dev / prod 두 release 가 같은 차트에서 다른 매니페스트로 렌더됨 |
| **6** | `helm upgrade --set replicaCount=3` 으로 dev replicas 증가 + `helm history` | history 에 revision 1, 2 두 줄 표시. dev quota used cpu 가 600m 으로 |
| **7** | `helm rollback sentiment-api 1 -n dev` 로 되돌리기 | history 에 revision 3 (= revision 1 의 매니페스트) 추가 |
| **8** | `helm uninstall sentiment-api -n dev` | release 와 자원 삭제. PVC 보존 옵션 (`helm.sh/resource-policy: keep`) 안내 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 본 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `helm version` 이 v3.x.x 이상을 출력 (`helm` v2 는 EOL)
- [ ] `helm lint manifests/chart/sentiment-api` 가 `0 chart(s) failed` 로 통과
- [ ] `helm template manifests/chart/sentiment-api -f manifests/chart/sentiment-api/values-dev.yaml` 의 출력이 `kubectl apply --dry-run=client -f -` 으로 통과
- [ ] `helm install sentiment-api manifests/chart/sentiment-api -n dev -f values-dev.yaml` 이후 `kubectl get pods -n dev -l app=sentiment-api` 가 `1/1 Running`
- [ ] `helm list -A` 가 dev / prod 두 release 를 모두 `deployed` 로 표시
- [ ] `helm get values sentiment-api -n dev` 출력이 `replicaCount: 1` 등 -f / --set 으로 override 한 값만 표시
- [ ] `helm history sentiment-api -n dev` 가 install → upgrade → rollback 후 3개 revision 표시
- [ ] `helm uninstall sentiment-api -n dev` 후 `kubectl get all -n dev -l app=sentiment-api` 가 비어 있고, prod release 는 영향 없음

## 4. 정리

```bash
# dev release 만 uninstall (prod 는 다음 Phase 3/02 가 얹힘)
helm uninstall sentiment-api -n dev

# (선택) PVC 가 남았다면 명시적으로 삭제 — helm uninstall 은 PVC 를 자동 삭제하지 않습니다
kubectl delete pvc -n dev -l app=sentiment-api 2>/dev/null || true

# Phase 2/05 의 dev / prod / staging namespace 와 가드레일은 그대로 보존 (Phase 3/02 에서 사용)
```

> ⚠️ **prod release 보존 권장** — 다음 Phase 3/02 (Prometheus) 가 prod 의 `sentiment-api` Service / ConfigMap / Pod 를 ServiceMonitor 로 스크래핑합니다. lab 8 단계도 dev 만 uninstall, prod 는 보존합니다. 자세한 정리 절차와 검증은 [labs/README.md 정리 섹션](labs/README.md#정리-cleanup) 참고.

## 🚨 자주 하는 실수

1. **`helm install` 했는데 `Error: namespaces "dev" not found` — `--create-namespace` 누락**
   `helm install -n dev` 는 dev namespace 가 **존재한다고 가정** 하고 그 안에 자원을 만듭니다. dev 가 없으면 admission 도 아닌 API 단계에서 거절됩니다. 본 토픽은 Phase 2/05 의 dev/prod namespace 가 살아 있는 가정이라 문제가 없지만, 새 클러스터에서 처음 install 할 때는 `--create-namespace` 를 함께 줘야 합니다 (`helm install ... -n dev --create-namespace`). 단, **본 토픽에서는 일부러 사용하지 않습니다** — Phase 2/05 가 만든 quota / limitrange 가 붙은 namespace 안에 install 되어야 하기 때문입니다. `--create-namespace` 가 만든 빈 namespace 에 install 하면 가드레일 검증이 빠집니다 (자주 하는 실수 1·2번이 자연스럽게 연결됨).

2. **`helm install` 만 쓰면 CI 가 두 번째 실행에서 실패 — `helm upgrade --install` 패턴**
   `helm install <name>` 은 같은 이름의 release 가 이미 있으면 `Error: cannot re-use a name that is still in use` 로 거절됩니다. CI 에서 같은 파이프라인이 첫 배포(install) 와 이후 배포(upgrade) 모두 동작해야 한다면 **`helm upgrade --install <name> <chart>`** 가 표준입니다. 이 한 줄은 release 가 없으면 install, 있으면 upgrade 로 동작합니다 (선언적 동작). 학습 단계에서는 install / upgrade 의 차이를 익히는 것이 목적이라 두 명령을 분리해서 사용하지만, 운영에서는 거의 항상 `--install` 플래그를 함께 둡니다. 함께 가는 패턴: `helm upgrade --install <name> <chart> --atomic --timeout 5m` — `--atomic` 은 upgrade 가 실패하면 자동 rollback, `--timeout` 은 probe 통과 대기 한도.

3. **`values.yaml` 에 Secret 평문 저장 → git 으로 유출**
   초보자가 가장 많이 하는 실수입니다. `values.yaml` / `values-prod.yaml` 은 git 에 커밋되는 파일이고, 안에 `secrets.hfToken: "hf_real_token_..."` 을 적어 두면 그 토큰은 git history 에 영구 기록됩니다 (force push / rewrite 로도 다른 fork / 미러에서 복원 가능). 본 차트의 [values.yaml](manifests/chart/sentiment-api/values.yaml) 은 `secrets.hfToken: ""` 으로 비워 두고, lab 4단계가 `--set secrets.hfToken=$HF_TOKEN` 으로 환경 변수에서 주입하도록 안내합니다. 운영 표준은 셋 중 하나입니다 — ① **External Secrets Operator** (AWS Secrets Manager / HashiCorp Vault 와 K8s Secret 을 자동 동기화), ② **SealedSecrets (bitnami)** (공개 키로 암호화한 SealedSecret CRD 만 git 에 커밋, 클러스터의 controller 가 복호화), ③ **`helm secrets` plugin + sops** (values 파일 자체를 sops 로 암호화). Phase 3/04 (RBAC) 가 끝나면 다음 본격 Phase 4 / 캡스톤 단계에서 ②번이 자연스럽게 들어옵니다.

## 더 알아보기

- [Helm 공식 문서](https://helm.sh/docs/) — `Chart Template Guide` 섹션이 본 토픽의 1-2 절(템플릿 문법) 의 확장판입니다.
- [Sprig 함수 레퍼런스](http://masterminds.github.io/sprig/) — `toYaml`, `nindent`, `default`, `quote`, `tpl` 등 본 차트가 쓰는 함수의 전체 목록.
- [Helm Best Practices — Chart Conventions](https://helm.sh/docs/chart_best_practices/conventions/) — 본 차트의 라벨 스킴(`app.kubernetes.io/name` 등) 이 따르는 표준.
- [ArtifactHub](https://artifacthub.io/) — Phase 3/02 (kube-prometheus-stack), Phase 4/02 (KServe), Phase 4/03 (vLLM) 등 공식 차트의 검색·문서.
- [Helm Diff Plugin](https://github.com/databus23/helm-diff) — `helm diff upgrade` 로 upgrade 전 변경점을 미리 볼 수 있는 운영 필수 플러그인.

## 다음 챕터

➡️ [Phase 3 / 02-prometheus-grafana — kube-prometheus-stack 설치와 ServiceMonitor](../02-prometheus-grafana/lesson.md)

본 토픽이 만든 `manifests/chart/sentiment-api/` 차트는 다음 토픽에서 두 가지로 evolve 됩니다. ① **`templates/servicemonitor.yaml` 추가** — 본 토픽 [values.yaml](manifests/chart/sentiment-api/values.yaml) 의 `monitoring.serviceMonitor.enabled: false` placeholder 가 활성화되어, prod release 의 Pod 메트릭을 Prometheus 가 자동 스크래핑하게 됩니다. ② **kube-prometheus-stack 차트 install** — 본 토픽의 helm 명령을 그대로 사용해 `helm install prom prometheus-community/kube-prometheus-stack -n monitoring --create-namespace` 한 줄로 Prometheus / Grafana / Alertmanager 가 들어옵니다. Phase 3 의 나머지 토픽들 (`03-autoscaling-hpa`, `04-rbac-serviceaccount`) 도 모두 본 차트에 templates 를 추가하는 형태로 진화합니다. Helm 으로 들어오면 모든 길이 열립니다.
