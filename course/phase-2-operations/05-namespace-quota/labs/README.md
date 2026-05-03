# Phase 2 / 05-namespace-quota — 실습 가이드

> 04 까지 모든 자산을 `default` 네임스페이스에 누적해 왔다면, 본 lab 에서는 **dev / staging / prod 3개 namespace 를 만들고**, 그 안의 자원 사용량을 **ResourceQuota** 로 총량 제한, **LimitRange** 로 Pod·Container 별 정책을 강제합니다. 마지막으로 한도를 의도적으로 초과하는 Pod 를 적용해 admission 거절 메시지를 직접 확인합니다.
>
> **예상 소요 시간**: 40–60분 (sentiment-api:v1 이미지가 적재되어 있고 minikube 가 동작 중인 가정)
>
> **선행 조건**
> - [Phase 2 / 02-volumes-pvc](../../02-volumes-pvc/lesson.md) 또는 [Phase 2 / 04-job-cronjob](../../04-job-cronjob/lesson.md) 완료 — sentiment-api Deployment 의 구조와 PVC·ConfigMap·Secret 패턴이 익숙해야 합니다.
> - minikube 에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/04 lab 1단계에서 적재됨).
> - 본 lab 은 `default` 의 04 자산을 건드리지 않습니다 — 04 자산이 그대로 떠 있어도 무방하며, 격리 검증의 비교군이 됩니다.
>
> **작업 디렉토리**
> ```bash
> cd course/phase-2-operations/05-namespace-quota
> ```

---

## 0단계 — 사전 준비 점검

### 0-1. minikube 상태 확인

```bash
minikube status
```

```
# 예상 출력
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

`Stopped` 가 보이면 `minikube start` 로 기동합니다.

### 0-2. kubectl 컨텍스트 확인

```bash
kubectl config current-context
```

```
# 예상 출력
minikube
```

### 0-3. sentiment-api:v1 이미지 확인

```bash
minikube image ls | grep sentiment-api
```

```
# 예상 출력
docker.io/library/sentiment-api:v1
```

비어 있다면 → [Phase 1/04 lab 1단계](../../../phase-1-k8s-basics/04-serve-classification-model/labs/README.md#1단계--필요-시-phase-0-이미지를-minikube에-적재) 로 가서 다시 적재한 뒤 돌아옵니다.

### 0-4. default 네임스페이스 자산 점검 (격리 비교 기준)

본 lab 은 04 까지의 default 자산을 건드리지 않으므로 미리 무엇이 있는지 기록해 둡니다. lab 종료 후에도 같은 결과가 나와야 격리가 유지된 것입니다.

```bash
kubectl get all,pvc,cm,secret -n default --selector=app=sentiment-api
```

```
# 예상 출력 (예: 04 까지 진행한 학습자)
NAME                              READY   STATUS    RESTARTS   AGE
pod/sentiment-api-xxxxxxxx-yyyyy  1/1     Running   0          1d

NAME                    TYPE        CLUSTER-IP     EXTERNAL-IP   PORT(S)   AGE
service/sentiment-api   ClusterIP   10.96.10.123   <none>        80/TCP    1d

NAME                            READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/sentiment-api   1/1     1            1           1d

NAME                                STATUS   VOLUME    CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache   Bound    pvc-...   2Gi        RWO            standard       1d

NAME                              DATA   AGE
configmap/sentiment-api-config    4      1d

NAME                            TYPE     DATA   AGE
secret/sentiment-api-secrets    Opaque   2      1d
```

`No resources found` 만 나와도 본 lab 진행에는 문제 없습니다 (격리 비교는 7-2 단계에서 다른 방식으로 검증).

### 0-5. 본 토픽 매니페스트 정합성 dry-run

```bash
kubectl apply --dry-run=client -f manifests/
```

```
# 예상 출력 (8개 매니페스트, 합 13개 자원)
configmap/sentiment-api-config created (dry run)
configmap/sentiment-api-config created (dry run)
deployment.apps/sentiment-api created (dry run)
deployment.apps/sentiment-api created (dry run)
limitrange/dev-limits created (dry run)
limitrange/prod-limits created (dry run)
namespace/dev created (dry run)
namespace/prod created (dry run)
namespace/staging created (dry run)
persistentvolumeclaim/model-cache-dev created (dry run)
persistentvolumeclaim/model-cache-prod created (dry run)
pod/oversize-pod created (dry run)
resourcequota/dev-quota created (dry run)
resourcequota/prod-quota created (dry run)
secret/sentiment-api-secrets created (dry run)
secret/sentiment-api-secrets created (dry run)
service/sentiment-api created (dry run)
service/sentiment-api created (dry run)
```

> 💡 같은 이름(`sentiment-api`, `sentiment-api-config`, `sentiment-api-secrets`) 이 두 번씩 보이지만 namespace 가 dev / prod 로 다르므로 충돌이 아닙니다 — 이것이 namespace 격리의 핵심입니다.

---

## 1단계 — Namespace 생성과 컨텍스트 전환

### 1-1. namespaces.yaml 적용

```bash
kubectl apply -f manifests/namespaces.yaml
```

```
# 예상 출력
namespace/dev created
namespace/staging created
namespace/prod created
```

### 1-2. namespace 목록 확인

```bash
kubectl get ns
```

```
# 예상 출력 (default / kube-system 등은 클러스터 기본)
NAME              STATUS   AGE
default           Active   30d
dev               Active   10s
kube-node-lease   Active   30d
kube-public       Active   30d
kube-system       Active   30d
prod              Active   10s
staging           Active   10s
```

라벨까지 함께 보려면:

```bash
kubectl get ns --show-labels | grep -E '^NAME|env='
```

```
# 예상 출력
NAME              STATUS   AGE   LABELS
dev               Active   1m    env=dev,kubernetes.io/metadata.name=dev,purpose=experimentation,team=ml-platform
prod              Active   1m    env=prod,kubernetes.io/metadata.name=prod,purpose=production-serving,team=ml-platform
staging           Active   1m    env=staging,kubernetes.io/metadata.name=staging,purpose=pre-prod-validation,team=ml-platform
```

### 1-3. kubectl 컨텍스트의 기본 namespace 전환 (선택)

매번 `-n dev` 를 붙이는 대신 컨텍스트 자체를 바꿀 수 있습니다.

```bash
kubectl config set-context --current --namespace=dev
kubectl config view --minify | grep namespace
```

```
# 예상 출력
    namespace: dev
```

이 상태에서 `kubectl get pods` 는 `kubectl get pods -n dev` 와 같은 결과를 냅니다. 단, 본 lab 은 **명시성을 위해 모든 명령에 `-n <ns>` 를 붙입니다**. 학습 후에는 `kubectl config set-context --current --namespace=default` 로 되돌리세요.

### 1-4. namespaced vs cluster-scoped 자원 차이 확인

```bash
kubectl api-resources --namespaced=true | head -10
```

```
# 예상 출력 (일부)
NAME                  SHORTNAMES   APIVERSION   NAMESPACED   KIND
bindings                           v1           true         Binding
configmaps            cm           v1           true         ConfigMap
endpoints             ep           v1           true         Endpoints
events                ev           v1           true         Event
limitranges           limits       v1           true         LimitRange
persistentvolumeclaims pvc         v1           true         PersistentVolumeClaim
pods                  po           v1           true         Pod
...
```

```bash
kubectl api-resources --namespaced=false | head -10
```

```
# 예상 출력 (일부)
NAME                  SHORTNAMES   APIVERSION   NAMESPACED   KIND
componentstatuses     cs           v1           false        ComponentStatus
namespaces            ns           v1           false        Namespace
nodes                 no           v1           false        Node
persistentvolumes     pv           v1           false        PersistentVolume
clusterroles                       rbac.authorization.k8s.io/v1  false  ClusterRole
storageclasses        sc           storage.k8s.io/v1            false  StorageClass
...
```

> 💡 PVC 는 namespaced (위 출력에 있음), PV / StorageClass 는 cluster-scoped (아래 출력에 있음). 그래서 PVC 는 namespace 마다 따로 만들지만, 그 PVC 가 묶이는 PV 는 클러스터 전체가 공유합니다.

---

## 2단계 — ResourceQuota 적용과 조회

### 2-1. dev / prod 쿼터 적용

```bash
kubectl apply -f manifests/dev-quota.yaml -f manifests/prod-quota.yaml
```

```
# 예상 출력
resourcequota/dev-quota created
resourcequota/prod-quota created
```

### 2-2. 모든 namespace 의 쿼터 한눈에 보기

```bash
kubectl get resourcequota -A
```

```
# 예상 출력
NAMESPACE   NAME         AGE   REQUEST                                                                                                                                                              LIMIT
dev         dev-quota    20s   count/configmaps: 0/10, count/cronjobs.batch: 0/5, count/deployments.apps: 0/10, count/jobs.batch: 0/10, count/secrets: 0/10, count/services: 0/10, persistentvolumeclaims: 0/5, requests.cpu: 0/2, requests.memory: 0/4Gi, requests.nvidia.com/gpu: 0/1, requests.storage: 0/50Gi   limits.cpu: 0/4, limits.memory: 0/8Gi
prod        prod-quota   20s   count/configmaps: 0/30, count/cronjobs.batch: 0/10, count/deployments.apps: 0/20, count/jobs.batch: 0/20, count/secrets: 0/30, count/services: 0/20, persistentvolumeclaims: 0/10, requests.cpu: 0/8, requests.memory: 0/16Gi, requests.nvidia.com/gpu: 0/4, requests.storage: 0/200Gi   limits.cpu: 0/16, limits.memory: 0/32Gi
```

> 모든 used 값이 `0` 입니다 — 아직 dev / prod 에 어떤 Pod 도 띄우지 않았기 때문입니다. 4단계 sentiment-api 배포 후 다시 확인합니다.

### 2-3. 한 namespace 의 쿼터 상세 보기

```bash
kubectl describe quota dev-quota -n dev
```

```
# 예상 출력
Name:                       dev-quota
Namespace:                  dev
Resource                    Used  Hard
--------                    ----  ----
count/configmaps            0     10
count/cronjobs.batch        0     5
count/deployments.apps      0     10
count/jobs.batch            0     10
count/secrets               0     10
count/services              0     10
limits.cpu                  0     4
limits.memory               0     8Gi
persistentvolumeclaims      0     5
requests.cpu                0     2
requests.memory             0     4Gi
requests.nvidia.com/gpu     0     1
requests.storage            0     50Gi
```

> 💡 `Used` 컬럼은 현재 namespace 안의 Pod 들의 합계입니다. `requests.nvidia.com/gpu: 0/1` 처럼 GPU 도 hard 에는 등록되어 있지만, minikube 에는 GPU 노드가 없으므로 used 는 영원히 0 입니다 (Phase 4 GPU 토픽에서 실제로 1까지 채워지는 것을 검증).

### 2-4. staging 은 일부러 비워둠

```bash
kubectl get resourcequota -n staging
```

```
# 예상 출력
No resources found in staging namespace.
```

> staging 의 quota / limitrange 는 학습자가 직접 작성하는 연습입니다. dev 매니페스트를 staging namespace 로 복제한 뒤 dev 의 1.5–2배 값으로 조정해 보세요 (lesson.md 1-5 절 표 참고).

---

## 3단계 — LimitRange 적용과 기본값 검증

### 3-1. dev / prod 의 LimitRange 적용

```bash
kubectl apply -f manifests/dev-limitrange.yaml -f manifests/prod-limitrange.yaml
```

```
# 예상 출력
limitrange/dev-limits created
limitrange/prod-limits created
```

### 3-2. dev 의 LimitRange 상세 보기

```bash
kubectl describe limitrange dev-limits -n dev
```

```
# 예상 출력
Name:       dev-limits
Namespace:  dev
Type        Resource  Min   Max  Default Request  Default Limit  Max Limit/Request Ratio
----        --------  ---   ---  ---------------  -------------  -----------------------
Container   cpu       50m   2    200m             500m           4
Container   memory    64Mi  4Gi  256Mi            512Mi          -
Pod         cpu       -     2    -                -              -
Pod         memory    -     4Gi  -                -              -
```

> 컬럼 의미:
> - **Default Request**: requests 가 비어 있을 때 자동으로 채워질 값
> - **Default Limit**: limits 가 비어 있을 때 자동으로 채워질 값
> - **Min / Max**: 명시한 값의 허용 범위 — 벗어나면 admission 거절
> - **Max Limit/Request Ratio**: limit ÷ request 의 상한 — 과도한 burst 방지 (cpu 4 = limit 이 request 의 4배 이내)

### 3-3. 빈 Pod 로 default 가 채워지는지 즉시 검증

resources 가 완전히 비어 있는 Pod 를 임시로 띄워 LimitRange 가 어떻게 채우는지 봅니다.

```bash
kubectl run probe-default --image=registry.k8s.io/pause:3.9 -n dev
```

```
# 예상 출력
pod/probe-default created
```

```bash
kubectl get pod probe-default -n dev -o jsonpath='{.spec.containers[0].resources}' | python3 -m json.tool
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

> ✅ 컨테이너에 `resources` 를 적지 않았는데도 admission 단계에서 dev-limits 의 `default` / `defaultRequest` 가 자동으로 채워졌습니다. 이것이 LimitRange 의 핵심 동작입니다.

확인 후 정리:

```bash
kubectl delete pod probe-default -n dev
```

```
# 예상 출력
pod "probe-default" deleted
```

---

## 4단계 — sentiment-api 를 dev / prod 에 배포

### 4-1. dev 에 묶음 매니페스트 적용

```bash
kubectl apply -f manifests/sentiment-api-dev.yaml
```

```
# 예상 출력
configmap/sentiment-api-config created
secret/sentiment-api-secrets created
persistentvolumeclaim/model-cache-dev created
deployment.apps/sentiment-api created
service/sentiment-api created
```

### 4-2. prod 에 묶음 매니페스트 적용

```bash
kubectl apply -f manifests/sentiment-api-prod.yaml
```

```
# 예상 출력
configmap/sentiment-api-config created
secret/sentiment-api-secrets created
persistentvolumeclaim/model-cache-prod created
deployment.apps/sentiment-api created
service/sentiment-api created
```

> 💡 같은 이름(`sentiment-api`, `sentiment-api-config`, `sentiment-api-secrets`) 이지만 dev / prod / default 에 모두 따로 존재합니다 — 충돌 없음.

### 4-3. dev / prod Pod 의 Ready 대기 (모델 다운로드 시간 포함)

```bash
kubectl get pods -n dev -w
```

`Init:0/1` (모델 다운로드) → `PodInitializing` → `Running 0/1` (모델 로딩) → `Running 1/1` 순서로 전이합니다. dev 는 1분 내, prod 는 같은 모델을 두 번 받느라 1–2분 더 걸립니다. `Ctrl+C` 로 빠져나옵니다.

```
# 예상 최종 출력
NAME                             READY   STATUS    RESTARTS   AGE
sentiment-api-xxxxxxxxx-aaaaa    1/1     Running   0          90s
```

```bash
kubectl get pods -n prod
```

```
# 예상 출력
NAME                             READY   STATUS    RESTARTS   AGE
sentiment-api-yyyyyyyyy-bbbbb    1/1     Running   0          2m
sentiment-api-yyyyyyyyy-ccccc    1/1     Running   0          2m
```

### 4-4. 모든 namespace 의 Pod 한눈에 보기

```bash
kubectl get pods -A --selector=app=sentiment-api
```

```
# 예상 출력 (default 의 04 자산이 살아있는 경우 + dev + prod 합 4개)
NAMESPACE   NAME                            READY   STATUS    RESTARTS   AGE
default     sentiment-api-zzzzzzzzz-ddddd   1/1     Running   0          1d
dev         sentiment-api-xxxxxxxxx-aaaaa   1/1     Running   0          2m
prod        sentiment-api-yyyyyyyyy-bbbbb   1/1     Running   0          2m
prod        sentiment-api-yyyyyyyyy-ccccc   1/1     Running   0          2m
```

### 4-5. 쿼터 사용량 변화 확인

```bash
kubectl describe quota dev-quota -n dev
```

```
# 예상 출력 (핵심 라인만)
Name:                       dev-quota
Namespace:                  dev
Resource                    Used   Hard
--------                    ----   ----
count/configmaps            1      10
count/deployments.apps      1      10
count/secrets               1      10
count/services              1      10
limits.cpu                  500m   4
limits.memory               512Mi  8Gi
persistentvolumeclaims      1      5
requests.cpu                200m   2
requests.memory             256Mi  4Gi
requests.nvidia.com/gpu     0      1
requests.storage            1Gi    50Gi
```

> ✅ `requests.cpu: 200m/2` — sentiment-api-dev 의 main 컨테이너가 LimitRange `defaultRequest` 200m 으로 채워진 결과가 누적되었습니다. 남은 여유 = 2000m − 200m = 1800m → 5단계의 oversize-pod (2000m 요청) 가 거절될 조건이 만들어졌습니다.

```bash
kubectl describe quota prod-quota -n prod
```

```
# 예상 출력 (핵심 라인만)
Resource                    Used   Hard
--------                    ----   ----
limits.cpu                  2      16
limits.memory               4Gi    32Gi
persistentvolumeclaims      1      10
requests.cpu                1      8
requests.memory             2Gi    16Gi
```

> prod 의 sentiment-api 는 명시적 resources 사용 (request cpu 500m × 2 replicas = 1000m = 1) — LimitRange default 에 의존하지 않습니다.

---

## 5단계 — 쿼터 한도 초과 거절 시연

### 5-1. oversize-pod 적용 (의도적 실패)

```bash
kubectl apply -f manifests/oversize-pod.yaml
```

```
# 예상 출력 (Forbidden 에러)
Error from server (Forbidden): error when creating "manifests/oversize-pod.yaml": pods "oversize-pod" is forbidden: exceeded quota: dev-quota, requested: requests.cpu=2, used: requests.cpu=200m, limited: requests.cpu=2
```

> ✅ 정확히 이 에러가 보이면 ResourceQuota 가 admission 단계에서 동작한 것입니다. 메시지의 의미:
> - `requested: requests.cpu=2` — 본 Pod 가 추가로 요청한 양
> - `used: requests.cpu=200m` — 현재 dev 안에서 이미 사용 중인 합 (sentiment-api 의 main 컨테이너)
> - `limited: requests.cpu=2` — dev-quota 의 hard 한도
> - 200m + 2 = 2.2 > 2 → 거절

### 5-2. used 가 변하지 않았음 재확인 (Pod 가 만들어지지 않았으므로)

```bash
kubectl describe quota dev-quota -n dev | grep requests.cpu
```

```
# 예상 출력
requests.cpu                200m  2
```

> 거절된 Pod 는 etcd 에 저장되지 않으므로 used 도 변하지 않습니다 (admission 단계 거절 = "신청 자체가 접수되지 않음").

### 5-3. dev 에 oversize-pod 가 실제로 없는지 확인

```bash
kubectl get pod oversize-pod -n dev
```

```
# 예상 출력
Error from server (NotFound): pods "oversize-pod" not found
```

---

## 6단계 — LimitRange 협력 검증 (resources 누락 Pod)

### 6-1. dev 의 sentiment-api Pod 의 main 컨테이너 resources 확인

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

> ✅ [sentiment-api-dev.yaml](../manifests/sentiment-api-dev.yaml) 의 `app` 컨테이너에는 `resources` 블록이 없는데도, admission 에서 dev-limits 의 `default` / `defaultRequest` 로 채워졌습니다. 이것이 "Quota + LimitRange 협력" 의 핵심입니다 — LimitRange 가 빈 자리를 채워주지 않으면 Quota 가 즉시 거절했을 것입니다.

### 6-2. (참고) prod 의 sentiment-api Pod 는 명시값 그대로

```bash
POD=$(kubectl get pod -n prod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl get pod -n prod "$POD" -o jsonpath='{.spec.containers[0].resources}' | python3 -m json.tool
```

```
# 예상 출력
{
    "limits": {
        "cpu": "1",
        "memory": "2Gi"
    },
    "requests": {
        "cpu": "500m",
        "memory": "1Gi"
    }
}
```

> prod 매니페스트에는 명시 resources 가 있어 LimitRange default 가 채울 자리가 없습니다 — 운영의 표준 패턴.

### 6-3. (선택) LimitRange 가 없을 때 어떻게 되는지 비교

```bash
# 임시 namespace 와 quota 만 (LimitRange 없음)
kubectl create namespace noquota-test
kubectl apply -n noquota-test -f - <<EOF
apiVersion: v1
kind: ResourceQuota
metadata:
  name: small-quota
spec:
  hard:
    requests.cpu: "1"
    requests.memory: "1Gi"
EOF

# resources 없는 Pod 를 띄우려고 시도 → Quota 가 거절
kubectl run no-resources --image=registry.k8s.io/pause:3.9 -n noquota-test
```

```
# 예상 출력
Error from server (Forbidden): pods "no-resources" is forbidden: failed quota: small-quota: must specify limits.cpu for: no-resources; limits.memory for: no-resources; requests.cpu for: no-resources; requests.memory for: no-resources
```

> ⚠️ Quota 가 걸려 있는 namespace 에 LimitRange 가 없으면, **resources 를 명시하지 않은 Pod 는 모두 거절**됩니다. 이것이 "자주 하는 실수 2번" 입니다 — Quota 와 LimitRange 는 항상 한 쌍으로 운영합니다.

확인 후 정리:

```bash
kubectl delete namespace noquota-test
```

```
# 예상 출력
namespace "noquota-test" deleted
```

---

## 7단계 (선택) — 환경별 차등 비교

### 7-1. 같은 oversize Pod 를 prod 에 시도

```bash
sed 's/namespace: dev/namespace: prod/' manifests/oversize-pod.yaml | kubectl apply -f -
```

```
# 예상 출력
pod/oversize-pod created
```

> ✅ prod 에서는 통과합니다. prod-quota 의 requests.cpu 는 8 이고, sentiment-api-prod 가 1 만 사용 중이므로 1 + 2 = 3 ≤ 8 → 여유. 같은 매니페스트가 환경에 따라 다르게 동작하는 것이 환경별 quota 의 가치입니다.

```bash
kubectl get pod oversize-pod -n prod
```

```
# 예상 출력
NAME           READY   STATUS    RESTARTS   AGE
oversize-pod   1/1     Running   0          10s
```

### 7-2. namespace 격리 검증 — Service 의 selector 는 같지만 라우팅 분리

```bash
kubectl get endpoints sentiment-api -n dev
kubectl get endpoints sentiment-api -n prod
kubectl get endpoints sentiment-api -n default 2>/dev/null
```

```
# 예상 출력 (각 namespace 의 Pod IP 만 매칭됨 — 다른 namespace 의 Pod 와 절대 섞이지 않음)
NAME            ENDPOINTS         AGE
sentiment-api   10.244.0.21:8000  5m

NAME            ENDPOINTS                          AGE
sentiment-api   10.244.0.22:8000,10.244.0.23:8000  5m

NAME            ENDPOINTS         AGE
sentiment-api   10.244.0.20:8000  1d
```

> ✅ `app: sentiment-api` selector 가 같아도 Service 는 자기 namespace 안의 Pod 만 선택합니다. 이것이 namespace 격리의 강력함입니다.

### 7-3. 응답 차이 검증 (APP_VERSION)

```bash
# dev 의 Service 로 직접 호출 (port-forward)
kubectl port-forward -n dev svc/sentiment-api 18000:80 &
sleep 2
curl -s http://localhost:18000/ready
kill %1 2>/dev/null
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-dev"}
```

```bash
kubectl port-forward -n prod svc/sentiment-api 18001:80 &
sleep 2
curl -s http://localhost:18001/ready
kill %1 2>/dev/null
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-prod"}
```

> ✅ 같은 image, 같은 코드인데 ConfigMap 의 `APP_VERSION` 만으로 두 환경이 구분됩니다 — namespace 별 ConfigMap 격리의 직접 효과.

---

## 정리 (cleanup)

> ⚠️ **prod 보존 권장**: 다음 Phase 3 (Helm/Prometheus/HPA) 가 prod namespace 위에 얹힐 수 있습니다. 본 lab 정리에서는 **dev / oversize 만 삭제**, prod 와 staging 은 보존합니다. default 의 04 자산도 그대로 둡니다.

### dev namespace 통째로 삭제 (안의 모든 자산 cascade 삭제)

```bash
kubectl delete namespace dev
```

```
# 예상 출력 (PVC 삭제까지 시간 걸림 — 보통 10–30초)
namespace "dev" deleted
```

> 💡 `delete namespace` 는 안의 Pod / Deployment / Service / PVC / ConfigMap / Secret / Quota / LimitRange 까지 모두 cascade 삭제합니다. 자주 하는 실수 3번 — 운영에서 prod 에 함부로 쓰지 마세요.

### prod 의 oversize-pod 만 삭제

```bash
kubectl delete pod oversize-pod -n prod 2>/dev/null || true
```

```
# 예상 출력
pod "oversize-pod" deleted
```

### 격리 검증 — default 자산은 영향 없는지

```bash
kubectl get all,pvc,cm,secret -n default --selector=app=sentiment-api
```

```
# 예상 출력 (0-4 단계와 동일해야 함)
NAME                              READY   STATUS    RESTARTS   AGE
pod/sentiment-api-xxxxxxxx-yyyyy  1/1     Running   0          1d
...
```

> ✅ default 의 04 자산이 그대로 살아있다면 namespace 격리가 끝까지 유지된 것입니다.

### kubectl 컨텍스트 되돌리기 (1-3 에서 변경했다면)

```bash
kubectl config set-context --current --namespace=default
kubectl config view --minify | grep namespace
```

```
# 예상 출력
    namespace: default
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

> minikube 를 삭제하지 않으면 prod / staging namespace 와 그 안의 자산은 다음 부팅 시 그대로 살아납니다.

---

## 검증 체크리스트

다음 항목을 모두 확인했다면 본 lab 을 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get ns` 가 dev / staging / prod 3개 모두 Active 표시 (1-2)
- [ ] `kubectl describe quota dev-quota -n dev` 가 hard / used 컬럼을 모두 표시 (2-3)
- [ ] `kubectl describe limitrange dev-limits -n dev` 가 Default Request / Default Limit 컬럼을 표시 (3-2)
- [ ] resources 가 비어 있던 임시 Pod 의 `.spec.containers[0].resources` 가 LimitRange default 로 채워진 것을 확인 (3-3)
- [ ] sentiment-api Pod 가 dev / prod 에 각각 Running 상태 (4-3, 4-4)
- [ ] dev quota 의 `requests.cpu` used 가 200m 으로 표시됨 (4-5)
- [ ] `kubectl apply -f manifests/oversize-pod.yaml` 가 `forbidden: exceeded quota` 메시지로 거절됨 (5-1)
- [ ] sentiment-api-dev 의 main 컨테이너 resources 가 LimitRange default 로 채워져 있음 (6-1)
- [ ] (선택) LimitRange 없는 noquota-test 에서 resources 누락 Pod 가 `failed quota: must specify ...` 로 거절됨 (6-3)
- [ ] (선택) 같은 oversize-pod 가 prod 에서는 통과함 (7-1)

---

## 다음 단계

➡️ [Phase 3 / 01-helm-chart](../../../phase-3-production/01-helm-chart/lesson.md) (작성 예정) — 본 lab 에서 손으로 만든 dev / prod 매니페스트를 Helm 차트 한 벌로 묶고, `values-dev.yaml` / `values-prod.yaml` 로 환경별 차이를 분리합니다. `helm install --namespace dev` / `helm install --namespace prod` 가 본 lab 의 namespace 격리 위에 얹힙니다.
