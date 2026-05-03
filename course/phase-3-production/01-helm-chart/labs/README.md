# Phase 3 / 01-helm-chart — 실습 가이드

> Phase 2/05 까지 학습자는 dev / prod 두 namespace 에 거의 같은 5개 자원(ConfigMap + Secret + PVC + Deployment + Service) 을 손으로 두 벌 만들었습니다. 본 lab 에서는 그 두 묶음을 **단일 Helm 차트** 로 흡수하고, `values-dev.yaml` / `values-prod.yaml` 두 override 파일로 환경 차이만 분리합니다. install / upgrade / rollback / uninstall 4가지 라이프사이클 명령으로 release 를 관리합니다.
>
> **예상 소요 시간**: 60–80분 (helm 설치 + Phase 2/05 가드레일 살아있는 가정)
>
> **선행 조건**
> - [Phase 2 / 05-namespace-quota](../../../phase-2-operations/05-namespace-quota/lesson.md) 완료 — 본 lab 4·5 단계가 dev/prod ResourceQuota / LimitRange 의 admission 검증을 그대로 사용합니다. Phase 2/05 정리 단계에서 dev namespace 만 삭제하고 prod / staging 은 보존했다면 그대로 사용 가능합니다.
> - minikube 에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/04 lab 1단계).
> - Helm v3.x — 0단계에서 설치 확인.
>
> **작업 디렉토리**
> ```bash
> cd course/phase-3-production/01-helm-chart
> ```

---

## 0단계 — 사전 준비 점검

### 0-1. helm 설치 확인

```bash
helm version --short
```

```
# 예상 출력 (v3.x 면 OK)
v3.14.0+g3fc9f4b
```

설치되어 있지 않다면 macOS: `brew install helm`, Linux: `curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`. `helm` v2 는 EOL 이라 본 lab 은 v3 만 지원합니다.

### 0-2. minikube 와 sentiment-api:v1 이미지 확인

```bash
minikube status && minikube image ls | grep sentiment-api
```

```
# 예상 출력
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured

docker.io/library/sentiment-api:v1
```

`Stopped` 면 `minikube start`, 이미지가 없으면 [Phase 1/04 lab 1단계](../../../phase-1-k8s-basics/04-serve-classification-model/labs/README.md#1단계--필요-시-phase-0-이미지를-minikube에-적재) 로 가서 적재 후 돌아옵니다.

### 0-3. Phase 2/05 가드레일 (namespace + Quota + LimitRange) 생존 점검

```bash
kubectl get ns dev prod 2>/dev/null && \
  kubectl get resourcequota,limitrange -n dev && \
  kubectl get resourcequota,limitrange -n prod
```

```
# 예상 출력 (Phase 2/05 정리 후 prod 만 보존 → dev 자산은 비어 있을 수 있음)
NAME   STATUS   AGE
dev    Active   5m
prod   Active   1d

NAME                       AGE
resourcequota/dev-quota    10s
limitrange/dev-limits      10s

NAME                        AGE
resourcequota/prod-quota    1d
limitrange/prod-limits      1d
```

**dev 가 없거나 quota / limitrange 가 비어 있다면** — Phase 2/05 의 1·2·3단계를 다시 빠르게 적용합니다:

```bash
# Phase 2/05 의 가드레일 자산만 재적용 (sentiment-api 자산은 본 lab 이 helm 으로 만듦)
kubectl apply -f ../../phase-2-operations/05-namespace-quota/manifests/namespaces.yaml
kubectl apply -f ../../phase-2-operations/05-namespace-quota/manifests/dev-quota.yaml \
               -f ../../phase-2-operations/05-namespace-quota/manifests/prod-quota.yaml
kubectl apply -f ../../phase-2-operations/05-namespace-quota/manifests/dev-limitrange.yaml \
               -f ../../phase-2-operations/05-namespace-quota/manifests/prod-limitrange.yaml
```

### 0-4. Phase 2/05 의 sentiment-api 자산이 dev/prod 에 남아 있는지 확인 (충돌 방지)

```bash
kubectl get all -n dev -l app=sentiment-api
kubectl get all -n prod -l app=sentiment-api
```

`No resources found` 또는 `Phase 2/05 의 Pod 가 보임` 둘 다 가능합니다. 본 lab 은 release 이름 `sentiment-api` 로 install 하므로 Phase 2/05 의 같은 이름 자원과 **충돌** 합니다. 충돌하면 helm 이 거절합니다 (`Error: ... existing resources not managed by this release`).

Phase 2/05 의 자산이 dev/prod 에 남아 있다면 본 lab 시작 전 정리:

```bash
kubectl delete -f ../../phase-2-operations/05-namespace-quota/manifests/sentiment-api-dev.yaml --ignore-not-found
kubectl delete -f ../../phase-2-operations/05-namespace-quota/manifests/sentiment-api-prod.yaml --ignore-not-found
kubectl delete pod oversize-pod -n prod --ignore-not-found 2>/dev/null
```

```
# 예상 출력 (자산이 있었다면)
configmap "sentiment-api-config" deleted
secret "sentiment-api-secrets" deleted
persistentvolumeclaim "model-cache-dev" deleted
deployment.apps "sentiment-api" deleted
service "sentiment-api" deleted
...
```

### 0-5. 차트 디렉토리 트리 확인

```bash
ls -F manifests/chart/sentiment-api/ && echo "---" && ls -F manifests/chart/sentiment-api/templates/
```

```
# 예상 출력
Chart.yaml      templates/      values-dev.yaml   values-prod.yaml   values.yaml
---
NOTES.txt           configmap.yaml      pvc.yaml            service.yaml
_helpers.tpl        deployment.yaml     secret.yaml
```

---

## 1단계 — `helm create` 보일러플레이트와 비교

본 차트가 왜 일부러 작은지 (5개 자원만) 를 체감하는 단계입니다.

### 1-1. 임시 디렉토리에 helm create 로 보일러플레이트 차트 생성

```bash
cd /tmp
helm create demo-chart
ls -F demo-chart/templates/
```

```
# 예상 출력
NOTES.txt           hpa.yaml            servicemonitor.yaml
_helpers.tpl        ingress.yaml        tests/
deployment.yaml     service.yaml
serviceaccount.yaml
```

> ⚠️ helm create 는 nginx 를 기본 이미지로 한 만능 보일러플레이트를 만듭니다. ingress, hpa, serviceaccount, tests/ 까지 한 번에 들어옵니다 — 학습 단계에서 이 모든 것을 이해하지 못한 채 values 만 바꾸면, 본인이 만든 차트의 절반을 본인도 모르는 상태가 됩니다.

### 1-2. 본 차트와 비교

```bash
ls -F /Users/kmyu/Desktop/project/k8s-for-mle/course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api/templates/
```

```
# 예상 출력
NOTES.txt           configmap.yaml      pvc.yaml            service.yaml
_helpers.tpl        deployment.yaml     secret.yaml
```

> ✅ 본 차트는 Phase 2 가 실제로 사용하는 자원만 — ingress / hpa / serviceaccount 는 [values.yaml](../manifests/chart/sentiment-api/values.yaml) 의 placeholder 자리만 잡아두고 templates 는 만들지 않았습니다. Phase 3/02·03·04 가 templates 를 하나씩 추가합니다.

### 1-3. 정리

```bash
rm -rf /tmp/demo-chart
cd /Users/kmyu/Desktop/project/k8s-for-mle/course/phase-3-production/01-helm-chart
```

---

## 2단계 — `helm template` 으로 렌더링 비교 (디버깅 패턴)

`helm template` 은 클러스터에 접속하지 않고 **클라이언트에서 Go template 만 렌더** 합니다. install 전에 매니페스트가 어떻게 보일지 미리 확인하는 표준 패턴입니다.

### 2-1. 기본 values 만으로 렌더

```bash
helm template sentiment-api manifests/chart/sentiment-api 2>&1 | head -40
```

```
# 예상 출력 (앞부분)
---
# Source: sentiment-api/templates/configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: sentiment-api-config
  labels:
    helm.sh/chart: sentiment-api-0.1.0
    app.kubernetes.io/name: sentiment-api
    app.kubernetes.io/instance: sentiment-api
    app: sentiment-api
    app.kubernetes.io/version: "v1"
    app.kubernetes.io/managed-by: Helm
data:
  MODEL_NAME: "cardiffnlp/twitter-roberta-base-sentiment"
  APP_VERSION: "v1-helm"
  LOG_LEVEL: "INFO"
  HF_HOME: "/cache"
  inference.yaml: |-
    model:
      name: cardiffnlp/twitter-roberta-base-sentiment
      max_length: 128
      top_k: 1
    serving:
      batch_size: 32
      timeout_seconds: 30
---
# Source: sentiment-api/templates/secret.yaml
...
```

> ✅ `app.kubernetes.io/managed-by: Helm` 라벨이 붙은 것을 확인 — `_helpers.tpl` 의 `sentiment-api.labels` 가 작동했습니다.

### 2-2. dev / prod values 로 렌더해서 diff

```bash
helm template sentiment-api manifests/chart/sentiment-api \
    -n dev -f manifests/chart/sentiment-api/values-dev.yaml > /tmp/render-dev.yaml

helm template sentiment-api manifests/chart/sentiment-api \
    -n prod -f manifests/chart/sentiment-api/values-prod.yaml > /tmp/render-prod.yaml

diff /tmp/render-dev.yaml /tmp/render-prod.yaml
```

```
# 예상 출력 (핵심 차이만 — 라벨 / 이름 라인 제외)
< replicas: 1
> replicas: 2
< APP_VERSION: "v1-helm-dev"
> APP_VERSION: "v1-helm-prod"
< LOG_LEVEL: "DEBUG"
> LOG_LEVEL: "INFO"
< batch_size: 16
> batch_size: 32
< timeout_seconds: 30
> timeout_seconds: 60
> resources:
>   limits:
>     cpu: "1"
>     memory: 2Gi
>   requests:
>     cpu: 500m
>     memory: 1Gi
< name: model-cache-dev
> name: model-cache-prod
< storage: 1Gi
> storage: 2Gi
```

> ✅ Phase 2/05 의 두 매니페스트 (sentiment-api-dev.yaml / sentiment-api-prod.yaml) 비교에서 나왔던 6가지 차이가 그대로 나타납니다. **나머지 ~200줄은 모두 동일** — 이것이 Helm 의 가치입니다.

### 2-3. `--set` 으로 한 줄 override

```bash
helm template sentiment-api manifests/chart/sentiment-api \
    -n dev -f manifests/chart/sentiment-api/values-dev.yaml \
    --set replicaCount=3 | grep -A1 'kind: Deployment' | grep replicas
```

```
# 예상 출력
spec:
  replicas: 3
```

> ✅ values-dev.yaml 의 `replicaCount: 1` 을 `--set replicaCount=3` 이 덮어썼습니다 (lesson.md 1-3 절의 우선순위 [3] > [2]).

### 2-4. 렌더링 결과를 kubectl 로 dry-run 검증

```bash
helm template sentiment-api manifests/chart/sentiment-api \
    -n dev -f manifests/chart/sentiment-api/values-dev.yaml \
    | kubectl apply --dry-run=client -f -
```

```
# 예상 출력 (4개 자원이 dry run 으로 통과)
configmap/sentiment-api-config created (dry run)
secret/sentiment-api-secrets created (dry run)
service/sentiment-api created (dry run)
deployment.apps/sentiment-api created (dry run)
persistentvolumeclaim/model-cache-dev created (dry run)
```

---

## 3단계 — `helm lint` + `helm install --dry-run --debug`

`helm lint` 는 **차트 자체** 의 정합성을 검사합니다. `helm install --dry-run --debug` 은 **클러스터의 admission 까지** 통과 시뮬레이션합니다.

### 3-1. helm lint

```bash
helm lint manifests/chart/sentiment-api
```

```
# 예상 출력
==> Linting manifests/chart/sentiment-api
[INFO] Chart.yaml: icon is recommended

1 chart(s) linted, 0 chart(s) failed
```

> 💡 `[INFO] icon is recommended` 는 Chart.yaml 에 icon 필드가 없다는 정보 메시지일 뿐 — 0 chart(s) failed 면 통과입니다. 본 토픽에서는 icon 을 두지 않습니다 (Helm Hub 에 publish 할 차트가 아니므로).

### 3-2. dev values 로 dry-run install (서버 admission 까지 검사)

```bash
helm install sentiment-api manifests/chart/sentiment-api \
    -n dev \
    -f manifests/chart/sentiment-api/values-dev.yaml \
    --dry-run --debug 2>&1 | tail -30
```

```
# 예상 출력 (마지막 부분)
COMPUTED VALUES:
... (머지된 전체 values)
HOOKS:
MANIFEST:
---
# Source: sentiment-api/templates/configmap.yaml
...
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: dev
STATUS: pending-install
REVISION: 1
TEST SUITE: None
USER-SUPPLIED VALUES:
env:
  APP_VERSION: v1-helm-dev
  HF_HOME: /cache
  LOG_LEVEL: DEBUG
model:
  batchSize: 16
  timeoutSeconds: 30
persistence:
  enabled: true
  size: 1Gi
replicaCount: 1
resources: {}
```

> ✅ `STATUS: pending-install` 는 dry-run 임을 의미합니다. 실제로 install 되지는 않았고, 서버에서 admission 검사까지 통과한 것을 확인했습니다.

> ⚠️ **dev quota 가 거절하면 여기서 잡힙니다** — 만약 dry-run 에서 `Error: ... exceeded quota` 가 보이면 Phase 2/05 에서 이미 dev 에 다른 Pod 가 떠 있어 200m + (이 차트가 만들 Pod) 가 한도를 넘는 것입니다. 0-4 단계의 정리를 다시 수행하세요.

---

## 4단계 — dev 에 helm install

### 4-1. dev install

```bash
# HF_TOKEN 환경 변수가 비어 있으면 차트의 default placeholder 가 사용됩니다 (public 모델이라 동작에 문제 없음)
helm install sentiment-api manifests/chart/sentiment-api \
    -n dev \
    -f manifests/chart/sentiment-api/values-dev.yaml \
    --set secrets.hfToken="${HF_TOKEN:-hf_REPLACE_ME_WITH_REAL_TOKEN}"
```

```
# 예상 출력
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: dev
STATUS: deployed
REVISION: 1
NOTES:
sentiment-api v1 가 namespace "dev" 의 release "sentiment-api" 로 설치되었습니다.

📦 적용된 자원:
  - ConfigMap   sentiment-api-config
  - Secret      sentiment-api-secrets
  - Service     sentiment-api (ClusterIP, port 80 → targetPort 8000)
  - Deployment  sentiment-api (replicas 1)
  - PVC         model-cache-dev (1Gi)

🚀 동작 확인:
  ...
```

> ✅ NOTES.txt 가 그대로 stdout 에 나왔습니다 — install / upgrade 직후 사용자가 무엇을 해야 하는지 안내하는 표준 패턴.

### 4-2. Pod Ready 대기 (모델 로딩 1–2분)

```bash
kubectl rollout status deployment/sentiment-api -n dev --timeout=180s
```

```
# 예상 출력
Waiting for deployment "sentiment-api" rollout to finish: 0 of 1 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

### 4-3. dev quota used 변화 확인 — 가드레일이 차트를 검사함

```bash
kubectl describe quota dev-quota -n dev | grep -E 'Resource|requests\.cpu|requests\.memory|count/'
```

```
# 예상 출력 (핵심만)
Resource                    Used   Hard
--------                    ----   ----
count/configmaps            1      10
count/deployments.apps      1      10
count/secrets               1      10
count/services              1      10
persistentvolumeclaims      1      5
requests.cpu                200m   2
requests.memory             256Mi  4Gi
```

> ✅ `requests.cpu: 200m / 2` — dev-limitrange 의 defaultRequest cpu: 200m 이 admission 단계에서 main 컨테이너의 빈 resources 에 채워졌습니다. Phase 2/05 4-5단계와 같은 결과 — 차트는 가드레일을 우회하지 않습니다.

### 4-4. main 컨테이너 resources 가 LimitRange default 로 채워졌는지 직접 확인

```bash
POD=$(kubectl get pod -n dev -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl get pod -n dev "$POD" -o jsonpath='{.spec.containers[0].resources}' | python3 -m json.tool
```

```
# 예상 출력
{
    "limits": {
        "cpu": "500m",
        "memory": "512Mi"
    },
    "requests": {
        "cpu": "200m",
        "memory": "256Mi"
    }
}
```

> ✅ values-dev.yaml 에서 `resources: {}` 였던 자리에 dev-limits 의 default / defaultRequest 가 자동으로 채워졌습니다 (Phase 2/05 6-1 단계와 동일 결과).

### 4-5. /ready 엔드포인트 호출

```bash
kubectl port-forward -n dev svc/sentiment-api 18000:80 &
PF_PID=$!
sleep 3
curl -s http://localhost:18000/ready
kill $PF_PID 2>/dev/null
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-helm-dev"}
```

> ✅ `version: v1-helm-dev` — values-dev.yaml 의 `env.APP_VERSION` 이 ConfigMap 을 거쳐 컨테이너 환경 변수로 들어가 FastAPI 앱이 응답에 그대로 반환했습니다.

---

## 5단계 — prod 에 helm install + helm 조회 명령들

### 5-1. prod install

```bash
helm install sentiment-api manifests/chart/sentiment-api \
    -n prod \
    -f manifests/chart/sentiment-api/values-prod.yaml \
    --set secrets.hfToken="${HF_TOKEN:-hf_REPLACE_ME_WITH_REAL_TOKEN}"
```

```
# 예상 출력
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: prod
STATUS: deployed
REVISION: 1
NOTES:
...
  - Deployment  sentiment-api (replicas 2)
  - PVC         model-cache-prod (2Gi)
...
```

```bash
kubectl rollout status deployment/sentiment-api -n prod --timeout=240s
```

```
# 예상 출력 (replicas 2 라 좀 더 걸림)
Waiting for deployment "sentiment-api" rollout to finish: 0 of 2 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 1 of 2 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

### 5-2. helm list -A — 모든 namespace 의 release

```bash
helm list -A
```

```
# 예상 출력
NAME            NAMESPACE  REVISION  UPDATED                  STATUS    CHART                APP VERSION
sentiment-api   dev        1         2026-05-04 10:00:00 KST  deployed  sentiment-api-0.1.0  v1
sentiment-api   prod       1         2026-05-04 10:05:00 KST  deployed  sentiment-api-0.1.0  v1
```

> 💡 같은 차트(sentiment-api-0.1.0)가 dev / prod 두 namespace 에 각자의 release 로 install 되었습니다. release 이름은 같지만 namespace 가 다르므로 충돌 없음 — Phase 2/05 의 namespace 격리가 helm 에도 그대로 적용됩니다.

### 5-3. helm get values — 적용 중인 사용자 values

```bash
helm get values sentiment-api -n dev
```

```
# 예상 출력 (사용자 -f / --set 으로 override 한 값만 — 차트 기본값 제외)
USER-SUPPLIED VALUES:
env:
  APP_VERSION: v1-helm-dev
  HF_HOME: /cache
  LOG_LEVEL: DEBUG
model:
  batchSize: 16
  timeoutSeconds: 30
persistence:
  enabled: true
  size: 1Gi
replicaCount: 1
resources: {}
secrets:
  hfToken: hf_REPLACE_ME_WITH_REAL_TOKEN
```

```bash
helm get values sentiment-api -n dev --all | head -40
```

```
# 예상 출력 (--all 은 차트 기본값까지 머지된 결과)
COMPUTED VALUES:
autoscaling:
  enabled: false
  maxReplicas: 5
  minReplicas: 1
  targetCPUUtilizationPercentage: 70
env:
  APP_VERSION: v1-helm-dev
  HF_HOME: /cache
  LOG_LEVEL: DEBUG
image:
  pullPolicy: IfNotPresent
  repository: sentiment-api
  tag: v1
ingress:
  enabled: false
  ...
```

> 💡 운영 디버깅의 표준은 `--all` 입니다. lesson.md 1-3 절 참고.

### 5-4. helm get manifest — 렌더링된 K8s 매니페스트

```bash
helm get manifest sentiment-api -n prod | grep -A2 'kind: Deployment' | head -10
```

```
# 예상 출력
kind: Deployment
metadata:
  name: sentiment-api
  ...
    replicas: 2
```

> ✅ `helm template` 의 결과와 사실상 같지만, **클러스터에 실제 적용된 매니페스트** 라는 차이가 있습니다 (manifests/ 안의 templates 가 아니라 release storage Secret 에 저장된 결과).

### 5-5. prod /ready 호출

```bash
kubectl port-forward -n prod svc/sentiment-api 18001:80 &
PF_PID=$!
sleep 3
curl -s http://localhost:18001/ready
kill $PF_PID 2>/dev/null
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-helm-prod"}
```

> ✅ `v1-helm-prod` — values-prod.yaml 의 APP_VERSION 이 들어왔습니다. 같은 차트, 같은 이미지, 다른 응답.

---

## 6단계 — `helm upgrade` 로 replicas 변경

### 6-1. dev release 의 replicas 를 1 → 3 으로 upgrade

```bash
helm upgrade sentiment-api manifests/chart/sentiment-api \
    -n dev \
    -f manifests/chart/sentiment-api/values-dev.yaml \
    --set secrets.hfToken="${HF_TOKEN:-hf_REPLACE_ME_WITH_REAL_TOKEN}" \
    --set replicaCount=3
```

```
# 예상 출력
Release "sentiment-api" has been upgraded. Happy Helming!
NAME: sentiment-api
LAST DEPLOYED: ...
NAMESPACE: dev
STATUS: deployed
REVISION: 2
NOTES:
...
  - Deployment  sentiment-api (replicas 3)
...
```

> ✅ `REVISION: 2` 로 증가 — Helm 이 새 revision 으로 변경을 적용했습니다.

### 6-2. Pod 가 3개로 늘었는지 확인

```bash
kubectl get pods -n dev -l app=sentiment-api
```

```
# 예상 출력
NAME                             READY   STATUS    RESTARTS   AGE
sentiment-api-xxxxxxxxx-aaaaa    1/1     Running   0          5m
sentiment-api-xxxxxxxxx-bbbbb    0/1     Running   0          30s
sentiment-api-xxxxxxxxx-ccccc    0/1     Running   0          30s
```

새 Pod 두 개는 모델 로딩 중이므로 곧 1/1 로 전이합니다.

### 6-3. dev quota used 변화

```bash
kubectl describe quota dev-quota -n dev | grep requests
```

```
# 예상 출력 (3 replicas × 200m = 600m 으로 증가)
requests.cpu                600m   2
requests.memory             768Mi  4Gi
requests.nvidia.com/gpu     0      1
requests.storage            1Gi    50Gi
```

> ⚠️ 만약 `--set replicaCount=11` 처럼 dev quota requests.cpu 한도(2)를 초과하면 helm upgrade 가 admission 단계에서 거절됩니다 — 11 × 200m = 2200m > 2000m. helm 메시지: `Error: UPGRADE FAILED: ... exceeded quota`. Phase 2/05 5단계와 같은 가드레일이 helm 에도 동작합니다.

### 6-4. helm history — revision 이력

```bash
helm history sentiment-api -n dev
```

```
# 예상 출력
REVISION  UPDATED  STATUS      CHART                APP VERSION  DESCRIPTION
1         ...      superseded  sentiment-api-0.1.0  v1           Install complete
2         ...      deployed    sentiment-api-0.1.0  v1           Upgrade complete
```

> ✅ revision 1 은 `superseded` (대체됨), revision 2 가 현재 `deployed`.

---

## 7단계 — `helm rollback` 으로 되돌리기

### 7-1. revision 1 (replicas: 1) 로 rollback

```bash
helm rollback sentiment-api 1 -n dev
```

```
# 예상 출력
Rollback was a success! Happy Helming!
```

### 7-2. helm history — 새 revision 3 추가됨

```bash
helm history sentiment-api -n dev
```

```
# 예상 출력
REVISION  UPDATED  STATUS      CHART                APP VERSION  DESCRIPTION
1         ...      superseded  sentiment-api-0.1.0  v1           Install complete
2         ...      superseded  sentiment-api-0.1.0  v1           Upgrade complete
3         ...      deployed    sentiment-api-0.1.0  v1           Rollback to 1
```

> 💡 rollback 은 revision 1 의 매니페스트를 **revision 3 으로 새로 적용** 합니다 — history 의 revision 1 자체로 돌아가는 것이 아니라, 그 시점의 상태를 "재-적용" 하는 새 revision 을 만듭니다.

### 7-3. replicas 가 1 로 돌아왔는지 확인

```bash
kubectl get deployment sentiment-api -n dev -o jsonpath='{.spec.replicas}'; echo
```

```
# 예상 출력
1
```

### 7-4. revision 1 vs revision 3 매니페스트 동일성 확인

```bash
helm get manifest sentiment-api -n dev --revision 1 > /tmp/r1.yaml
helm get manifest sentiment-api -n dev --revision 3 > /tmp/r3.yaml
diff /tmp/r1.yaml /tmp/r3.yaml
```

```
# 예상 출력 (체크섬 annotation 정도의 미세한 차이만 — 핵심 spec 은 동일)
< checksum/config: <hash-A>
> checksum/config: <hash-A>
```

> ✅ 본 lab 에서는 ConfigMap 을 변경하지 않았으므로 두 매니페스트가 거의 동일합니다 (체크섬 annotation 도 같음).

---

## 8단계 — `helm uninstall`

### 8-1. dev release uninstall

```bash
helm uninstall sentiment-api -n dev
```

```
# 예상 출력
release "sentiment-api" uninstalled
```

### 8-2. release 와 자원이 사라졌는지 확인

```bash
helm list -n dev && kubectl get all,cm,secret,pvc -n dev -l app=sentiment-api
```

```
# 예상 출력
NAME    NAMESPACE       REVISION        UPDATED STATUS  CHART   APP VERSION
(빈 결과)

# kubectl 결과: PVC 만 남고 Deployment / Service / ConfigMap / Secret 은 모두 사라짐
NAME                                STATUS   VOLUME    CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache-dev   Bound  pvc-...  1Gi        RWO            standard       10m
```

> ⚠️ **PVC 는 helm uninstall 이 자동으로 지우지 않습니다** — minikube hostPath StorageClass 의 reclaimPolicy 가 Delete 라도, helm 은 PVC 를 release 자원으로 등록한 채 uninstall 시점에 삭제 시도를 하지 않는 경우가 많습니다 (특히 `persistentVolumeClaimRetentionPolicy` 가 명시 안 된 경우). 운영에서 PVC 를 명시적으로 보존하려면 차트 templates/pvc.yaml 에 `helm.sh/resource-policy: keep` annotation 을 답니다 (본 차트에는 일부러 안 두었음 — 학습 환경의 자원 정리를 단순하게).

### 8-3. PVC 도 명시적으로 삭제 (학습 환경 정리)

```bash
kubectl delete pvc -n dev -l app=sentiment-api
```

```
# 예상 출력
persistentvolumeclaim "model-cache-dev" deleted
```

### 8-4. dev quota used 가 0 으로 돌아왔는지 확인

```bash
kubectl describe quota dev-quota -n dev | grep -E 'Resource|requests'
```

```
# 예상 출력
Resource                    Used  Hard
--------                    ----  ----
...
requests.cpu                0     2
requests.memory             0     4Gi
requests.nvidia.com/gpu     0     1
requests.storage            0     50Gi
```

> ✅ dev 안의 모든 sentiment-api 자원이 사라져 quota used 가 0 으로 복귀.

### 8-5. prod release 가 영향 없음 확인

```bash
helm list -n prod && kubectl get pods -n prod -l app=sentiment-api
```

```
# 예상 출력
NAME            NAMESPACE  REVISION  UPDATED  STATUS    CHART                APP VERSION
sentiment-api   prod       1         ...      deployed  sentiment-api-0.1.0  v1

NAME                             READY   STATUS    RESTARTS   AGE
sentiment-api-yyyyyyyyy-bbbbb    1/1     Running   0          15m
sentiment-api-yyyyyyyyy-ccccc    1/1     Running   0          15m
```

> ✅ helm release 는 namespace 단위로 격리됩니다 — dev uninstall 이 prod 에 전혀 영향 주지 않음.

---

## 정리 (cleanup)

> ⚠️ **prod release 보존 권장** — Phase 3/02 (Prometheus + Grafana) 가 prod 의 sentiment-api 를 ServiceMonitor 로 스크래핑합니다. dev 만 정리, prod 와 staging 은 보존합니다.

### dev release 와 PVC 삭제 (8단계에서 이미 했다면 생략)

```bash
helm uninstall sentiment-api -n dev 2>/dev/null || true
kubectl delete pvc -n dev -l app=sentiment-api 2>/dev/null || true
```

### 임시 파일 정리

```bash
rm -f /tmp/render-dev.yaml /tmp/render-prod.yaml /tmp/r1.yaml /tmp/r3.yaml
```

### Phase 2/05 자산 (가드레일) 보존

```bash
# 이 명령은 실행하지 마세요 — 다음 Phase 3/02 가 사용합니다.
# kubectl delete namespace dev   # ❌
# kubectl delete namespace prod  # ❌
```

### minikube 정지 (선택)

```bash
minikube stop
```

```
# 예상 출력
✋  Stopping node "minikube"  ...
🛑  1 node stopped.
```

---

## 검증 체크리스트

다음 항목을 모두 확인했다면 본 lab 을 마쳤다고 볼 수 있습니다.

- [ ] `helm version --short` 가 v3.x 표시 (0-1)
- [ ] `helm lint manifests/chart/sentiment-api` 가 `0 chart(s) failed` 로 통과 (3-1)
- [ ] `helm template ... -f values-dev.yaml` vs `... -f values-prod.yaml` 의 diff 가 6가지 차이 (replicas / APP_VERSION / LOG_LEVEL / batch_size / resources / PVC name·size) 만 표시 (2-2)
- [ ] `helm install sentiment-api manifests/chart/sentiment-api -n dev -f values-dev.yaml` 후 `kubectl get pods -n dev -l app=sentiment-api` 가 1/1 Running (4-2)
- [ ] dev quota `requests.cpu` used 가 0 → 200m 으로 변함 (LimitRange default 가 admission 에서 채움) (4-3, 4-4)
- [ ] `curl http://localhost:18000/ready` 응답에 `"version":"v1-helm-dev"` 표시 (4-5)
- [ ] `helm list -A` 가 dev / prod 두 release 모두 deployed 상태 (5-2)
- [ ] `helm upgrade --set replicaCount=3` 후 `helm history sentiment-api -n dev` 가 revision 2 표시 (6-1, 6-4)
- [ ] `helm rollback sentiment-api 1 -n dev` 후 history 가 revision 3 추가 + Deployment.spec.replicas 가 1 로 복귀 (7-1, 7-3)
- [ ] `helm uninstall sentiment-api -n dev` 후 `kubectl get all -n dev -l app=sentiment-api` 가 비어 있고 prod release 는 영향 없음 (8-2, 8-5)

---

## 다음 단계

➡️ [Phase 3 / 02-prometheus-grafana](../../02-prometheus-grafana/lesson.md) (작성 예정) — 본 lab 에서 만든 차트가 다음 토픽에서 두 가지로 evolve 됩니다. ① `templates/servicemonitor.yaml` 추가 — 본 차트 [values.yaml](../manifests/chart/sentiment-api/values.yaml) 의 `monitoring.serviceMonitor.enabled: false` placeholder 가 활성화. ② kube-prometheus-stack 차트 install — 본 lab 의 helm 명령(`helm install ... -n monitoring --create-namespace`)을 그대로 사용. `helm` 한 단어로 들어오는 ML 운영 도구의 첫 사례가 됩니다.
