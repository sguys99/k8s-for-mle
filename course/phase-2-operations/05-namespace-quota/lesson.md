# Namespace, ResourceQuota, LimitRange — dev/staging/prod 환경 격리와 자원 보호

> **Phase**: 2 — 운영에 필요한 K8s 개념 (다섯 번째, 마지막 토픽)
> **소요 시간**: 40–60분 (sentiment-api:v1 이미지가 minikube 에 적재되어 있는 가정)
> **선수 학습**:
> - [Phase 2 / 02-volumes-pvc — Volumes & PVC](../02-volumes-pvc/lesson.md)
> - [Phase 2 / 04-job-cronjob — Job & CronJob](../04-job-cronjob/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Namespace 의 정의 — "한 클러스터 안에서 자원 이름과 정책을 분리하는 논리적 경계" — 와 **namespaced vs cluster-scoped** 자원의 구분, `kubectl config set-context --current --namespace=...` / `-n <ns>` 두 가지 컨텍스트 전환 방식의 차이를 [namespaces.yaml](manifests/namespaces.yaml) 의 dev / staging / prod 3개를 직접 만들어 설명할 수 있습니다.
- ResourceQuota 의 4 카테고리 (compute / extended-resource(GPU) / storage / object count) 와 `hard` / `used` 의미를 [dev-quota.yaml](manifests/dev-quota.yaml) (작은 쿼터) / [prod-quota.yaml](manifests/prod-quota.yaml) (큰 쿼터) 의 차등 설정으로 비교 설명하고, `kubectl describe quota -n dev` 의 used 라인이 Pod 배포에 따라 어떻게 변하는지 직접 관찰할 수 있습니다.
- LimitRange 의 5 필드 (`default` / `defaultRequest` / `max` / `min` / `maxLimitRequestRatio`) 와 Container vs Pod 타입의 적용 범위를 [dev-limitrange.yaml](manifests/dev-limitrange.yaml) 로 적용해, [sentiment-api-dev.yaml](manifests/sentiment-api-dev.yaml) 의 `resources` 가 비어 있는 main 컨테이너에 admission 단계에서 default / defaultRequest 가 자동으로 채워지는 흐름을 `kubectl get pod -o jsonpath='{.spec.containers[0].resources}'` 로 직접 검증할 수 있습니다.
- ResourceQuota + LimitRange 협력 시나리오 — LimitRange 가 없으면 Quota 가 걸린 namespace 에 resources 누락 Pod 가 모두 거절되는 함정, LimitRange 가 있으면 default 가 채워져 통과되는 흐름 — 을 [oversize-pod.yaml](manifests/oversize-pod.yaml) 의 의도된 거절(`Forbidden: exceeded quota`) 과 임시 noquota-test namespace 의 거절(`failed quota: must specify ...`) 두 메시지를 직접 재현하며 구분할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

01–04 토픽까지 모든 자산을 `default` namespace 에 누적해 왔습니다. 학습 환경에서는 충분하지만, 실제 ML 운영에서는 **하나의 클러스터 안에 실험·검증·운영 자산이 동시에 흐르며**, 각자 다른 자원 요구·SLA·정책을 갖습니다. 정확히 이 자리에 들어가는 것이 Namespace + ResourceQuota + LimitRange 입니다. ML 운영에서 본 토픽이 특별히 중요한 이유는 셋입니다. ① **환경 격리** — fine-tuning 잡 (수 GPU 시간 점유) 이 prod 추론 서빙의 자원을 잠식하면 SLA 가 깨집니다. dev / staging / prod 를 namespace 로 분리하고 각자에 다른 ResourceQuota 를 걸면, 한쪽의 폭주가 다른 쪽으로 전파되지 않습니다. ② **GPU 쿼터로 팀별 할당** — `requests.nvidia.com/gpu` 를 ResourceQuota 에 걸어 "팀 A 는 GPU 4장까지, 팀 B 는 2장까지" 처럼 사람 개입 없이 admission 단계에서 강제할 수 있습니다 (Phase 4 GPU 토픽의 직접 발판). ③ **Phase 3 운영 도구의 전제** — Helm 의 `--namespace`, Prometheus 의 per-namespace 메트릭, HPA 의 namespace 단위 스케일은 모두 본 토픽의 namespace 분리가 깔린 상태에서 의미를 가집니다. 본 토픽이 Phase 3 의 발판이 되는 이유입니다.

## 1. 핵심 개념

### 1-1. Namespace — namespaced vs cluster-scoped

Namespace 는 **"한 클러스터 안의 자원 이름과 정책을 분리하는 논리적 경계"** 입니다. 같은 이름의 ConfigMap (`sentiment-api-config`) 이 dev / staging / prod / default 4개 namespace 에 **독립적으로** 존재할 수 있습니다 — 본 토픽 [sentiment-api-dev.yaml](manifests/sentiment-api-dev.yaml) / [sentiment-api-prod.yaml](manifests/sentiment-api-prod.yaml) 의 ConfigMap 이름이 같지만 충돌하지 않는 이유입니다.

K8s 의 모든 자원은 둘 중 하나입니다.

| 구분 | 정의 | 예시 | 본 토픽에서의 의미 |
|------|------|------|------------------|
| **namespaced** | namespace 마다 따로 존재. 이름 충돌 없음 | Pod, Deployment, Service, ConfigMap, Secret, PVC, Job, CronJob, **ResourceQuota**, **LimitRange** | namespace 마다 같은 이름의 자원이 따로 살아있음 — 격리의 단위 |
| **cluster-scoped** | 클러스터 전체에 1개. 이름 유일 | Node, **PV**, StorageClass, **Namespace 자체**, ClusterRole | namespace 라는 개념 자체가 cluster-scoped 임에 주의 |

> 💡 PVC 는 namespaced 인데 PV 는 cluster-scoped 입니다. 그래서 dev 와 prod 가 각자 PVC 를 만들지만, 그 PVC 들이 묶이는 PV 는 클러스터 전체가 공유합니다 (StorageClass 가 동적으로 생성).

확인 명령:

```bash
kubectl api-resources --namespaced=true   # namespaced 자원 목록
kubectl api-resources --namespaced=false  # cluster-scoped 자원 목록
```

#### 컨텍스트 전환 — `set-context` vs `-n`

| 방법 | 적용 범위 | 영속성 | 사용 시점 |
|------|----------|--------|----------|
| `kubectl config set-context --current --namespace=dev` | 현재 kubeconfig 의 모든 후속 명령 | kubectl 재시작 후에도 유지 | 한 namespace 에서 오래 작업할 때 |
| `kubectl <명령> -n dev` | 해당 명령 1회만 | 즉시 | 짧은 검증, CI 스크립트, 매니페스트 명시성이 중요한 lab |

본 토픽 [labs/README.md](labs/README.md) 는 명시성을 위해 모든 명령에 `-n <ns>` 를 붙입니다 — 학습자가 어느 namespace 에서 동작하는지 매 줄에서 명확히 보이도록 하기 위함입니다.

### 1-2. ResourceQuota — 4 카테고리와 hard/used

ResourceQuota 는 **한 namespace 안의 자원 사용 총량 상한선** 을 admission 에서 강제합니다. 한 카테고리라도 hard 를 초과하는 새 Pod 는 admission 단계에서 거절됩니다 (`Error from server (Forbidden): ... exceeded quota`).

본 토픽 [dev-quota.yaml](manifests/dev-quota.yaml) 가 다루는 4 카테고리:

| 카테고리 | 필드 예시 | dev 값 | prod 값 | ML 운영에서의 의미 |
|---------|----------|--------|--------|------------------|
| **compute** | `requests.cpu` / `requests.memory` / `limits.cpu` / `limits.memory` | 2 / 4Gi / 4 / 8Gi | 8 / 16Gi / 16 / 32Gi | 추론 컨테이너의 동시 가동 수 제한 |
| **extended resource (GPU)** | `requests.nvidia.com/gpu` | 1 | 4 | 팀별 GPU 할당 — Phase 4 발판 |
| **storage** | `persistentvolumeclaims` / `requests.storage` | 5 / 50Gi | 10 / 200Gi | 모델 가중치 캐시 / 평가 결과 영구 저장 한도 |
| **object count** | `count/deployments.apps` / `count/services` / `count/configmaps` / `count/secrets` / `count/jobs.batch` / `count/cronjobs.batch` | 10/10/10/10/10/5 | 20/20/30/30/20/10 | etcd / API Server 부담 제어, 무한 자동 생성 방지 |

> ⚠️ **GPU 쿼터의 minikube 한계**: minikube 에는 GPU 노드가 없으므로 `requests.nvidia.com/gpu` 는 quota 객체에 등록만 되고 used 는 항상 0 입니다. quota 자체는 정상 동작하며, **Phase 4 GPU 토픽에서 실제로 used 가 1·2·3 으로 채워지는 것을 검증** 합니다. 본 토픽은 "쿼터를 어떻게 거는가" 까지 학습하고, "GPU 가 실제로 어떻게 셀리는가" 는 Phase 4 의 몫입니다.

#### hard / used 의 의미

```bash
kubectl describe quota dev-quota -n dev
```

```
Resource         Used   Hard
--------         ----   ----
requests.cpu     200m   2
limits.cpu       500m   4
...
```

- **`Hard`**: ResourceQuota 가 정한 상한선. 매니페스트의 `spec.hard.<field>` 값.
- **`Used`**: 현재 namespace 안의 모든 Pod 의 합. **새 Pod 의 request 가 추가되었을 때 hard 를 넘지 않는지** 가 admission 검사 기준.

### 1-3. LimitRange — Container/Pod 타입과 5 필드

LimitRange 는 **한 namespace 안의 개별 Pod·Container 에 대한 자원 정책** 을 강제합니다. ResourceQuota 가 "총량 천장" 이라면 LimitRange 는 **"한 그릇의 최대·최소 + 빈 그릇 기본값"** 입니다.

본 토픽 [dev-limitrange.yaml](manifests/dev-limitrange.yaml) 의 5 필드:

| 필드 | 의미 | 동작 시점 | dev 값 (Container) | 누락 시 함정 |
|------|------|----------|------------------|-----------|
| `default` | limits 가 비어 있을 때 자동으로 채워질 값 | admission 단계에서 자동 채움 | cpu 500m, memory 512Mi | limits 누락 컨테이너가 노드 자원을 무제한 burst |
| `defaultRequest` | requests 가 비어 있을 때 자동으로 채워질 값 | admission 단계에서 자동 채움 | cpu 200m, memory 256Mi | request 누락 → quota 가 걸린 namespace 에서 admission 거절 (자주 하는 실수 2번) |
| `max` | 명시한 값의 상한 — 초과 시 admission 거절 | admission 단계에서 검사 | cpu 2, memory 4Gi | 한 컨테이너가 노드 한 대를 통째로 잡아 다른 워크로드 축출 |
| `min` | 명시한 값의 하한 — 미만 시 admission 거절 | admission 단계에서 검사 | cpu 50m, memory 64Mi | 너무 작은 request 로 노드가 Pod 로 가득 차 스케줄러가 혼잡 |
| `maxLimitRequestRatio` | limit / request 비율 상한 — 초과 시 admission 거절 | admission 단계에서 검사 | cpu 4 (limit 이 request 의 4배 이내) | 과도한 burst 가 노드 안정성을 흔듦 |

#### Container 타입 vs Pod 타입

LimitRange 안에는 여러 `limits` 항목을 둘 수 있습니다.

```yaml
spec:
  limits:
    - type: Container        # Pod 안의 각 컨테이너에 적용
      default: { cpu: 500m, memory: 512Mi }
      ...
    - type: Pod              # Pod 전체 (모든 컨테이너의 합) 에 적용
      max: { cpu: "2", memory: 4Gi }
```

- **Container 타입**: Pod 안의 컨테이너 1개당 정책. main + sidecar + init 모두 각자 검사.
- **Pod 타입**: Pod 전체 합 정책. sidecar 가 5개 늘어나도 합이 max 를 넘지 않게.

> 💡 **default 와 defaultRequest 가 둘 다 필요한 이유**: default(=limits) 만 있고 defaultRequest 가 없으면, K8s 는 requests = limits 로 간주합니다. 그러면 burst 여유가 사라지고 노드 자원이 limits 기준으로 미리 잠겨 클러스터 활용도가 떨어집니다. defaultRequest 를 별도로 두면 "보장량(requests) 은 작게, 최대치(limits) 는 크게" 가 가능해집니다.

### 1-4. Quota + LimitRange 협력 — admission 흐름과 두 가지 거절 메시지

Pod 가 만들어질 때 admission controller 는 두 단계를 차례로 통과합니다.

```
[1] LimitRange admission
    ├── resources 누락? → default / defaultRequest 로 채움
    ├── max / min / maxLimitRequestRatio 검사
    └── 위반 시 거절: "Invalid value: ... cpu max limit to request ratio per Container is 4"

[2] ResourceQuota admission
    ├── 채워진 resources 의 request·limit 합산
    ├── 현재 used + 새 합 > hard 인지 검사
    └── 위반 시 거절: "Forbidden: exceeded quota: dev-quota, requested: requests.cpu=2, used: requests.cpu=200m, limited: requests.cpu=2"
```

본 토픽이 직접 재현하는 두 거절 시나리오:

| 시나리오 | 어디서 거절 | 메시지 핵심 키워드 | 본 토픽 매니페스트 |
|---------|------------|------------------|-----------------|
| **A. Quota 만 있고 LimitRange 없음** | ResourceQuota 단계 (`failed quota`) | `must specify limits.cpu for: ...` | [labs 6-3 단계](labs/README.md) 의 임시 `noquota-test` namespace |
| **B. 둘 다 있고 한도 초과** | ResourceQuota 단계 (`exceeded quota`) | `requested: requests.cpu=2, used: ..., limited: requests.cpu=2` | [oversize-pod.yaml](manifests/oversize-pod.yaml) → dev |

> ⚠️ 두 메시지는 비슷해 보이지만 원인이 다릅니다. A 는 "request 자체가 없어서 quota 가 합산을 못 함" 이고, B 는 "request 는 있는데 합이 한도를 넘음" 입니다. 운영에서 A 를 보면 매니페스트에 resources 를 넣거나 LimitRange 를 추가하면 되고, B 를 보면 quota 한도를 늘리거나 다른 자산을 줄여야 합니다.

### 1-5. dev/staging/prod 분리 운영 패턴

본 토픽 [namespaces.yaml](manifests/namespaces.yaml) 의 3개 namespace 는 단순한 "이름 분리" 가 아니라 **운영 정책의 분리** 를 표현합니다.

| 환경 | dev | staging | prod |
|------|-----|---------|------|
| **purpose 라벨** | experimentation | pre-prod-validation | production-serving |
| **권장 quota 비율** | 1 (작게) | 2 (중간) | 4 (크게) |
| **본 토픽 quota 매니페스트** | [dev-quota.yaml](manifests/dev-quota.yaml) | (학습자 연습) | [prod-quota.yaml](manifests/prod-quota.yaml) |
| **LimitRange max** | 작게 (cpu 2) — 큰 모델 차단 | dev 와 prod 사이 | 크게 (cpu 8) — 대형 모델 허용 |
| **LimitRange default** | 작게 (cpu 500m) | (학습자 연습) | 크게 (cpu 1) — 안전한 운영 기본값 |
| **resources 명시 정책** | 누락 허용 (default 로 채움) | 권장 명시 | **반드시 명시** (LimitRange default 의존 금지) |
| **운영자 접근** | 자유 — 실험·디버깅 | 제한 — pre-prod 게이트 | 최소 권한 — RBAC (Phase 3) |

> 💡 **staging 은 학습자 연습 영역** 입니다. dev / prod 매니페스트를 참고해 staging 의 quota / limitrange 를 직접 작성해 보세요. 권장 값: dev 의 1.5–2배. Phase 3 의 Helm `values-staging.yaml` 가 이 위에 자연스럽게 얹힙니다.

#### Phase 3 와의 연결

본 토픽이 만드는 "namespace 별로 분리된 자산 + 환경별 차등 quota" 는 다음 Phase 의 토대가 됩니다.

- **Helm**: `helm install sentiment-api ./chart --namespace dev --values values-dev.yaml` — 본 토픽의 sentiment-api-dev.yaml 를 차트로 패키징하면 환경별 values 만 다르게 두면 됩니다.
- **Prometheus**: ServiceMonitor 가 `kube_resourcequota` / `kube_pod_container_resource_requests` 메트릭을 namespace 라벨로 분리해 수집 → 환경별 사용량 대시보드.
- **HPA**: HorizontalPodAutoscaler 는 namespace scoped 자원이라, 같은 매니페스트가 dev / prod 에 각자 작동하며 quota 한도 안에서 스케일.

## 2. 실습

본 토픽의 실습은 [labs/README.md](labs/README.md) 에 단계별 명령 + 예상 출력으로 정리되어 있습니다. 핵심 흐름만 요약합니다.

| 단계 | 무엇을 하는가 | 핵심 검증 |
|------|------------|---------|
| **0** | 사전 준비 — minikube / kubectl / sentiment-api:v1 / default 자산 점검 | 본 lab 이 default 자산을 건드리지 않음 확인 |
| **1** | namespaces.yaml 적용 (dev/staging/prod 생성) + 컨텍스트 전환 | `kubectl get ns` 가 3개 namespace Active 표시 |
| **2** | dev-quota / prod-quota 적용 + describe 로 hard/used 조회 | used 모두 0 (아직 Pod 없음) |
| **3** | dev-limitrange / prod-limitrange 적용 + 빈 Pod 로 default 채워짐 검증 | `kubectl get pod -o jsonpath` 가 200m/256Mi 로 채워진 결과 표시 |
| **4** | sentiment-api-dev / sentiment-api-prod 묶음 매니페스트 적용 | dev / prod 에 각각 Pod Running, dev quota used 가 200m 로 변함 |
| **5** | oversize-pod.yaml 적용 → 의도적 거절 | `Forbidden: exceeded quota` 에러 메시지 확인 |
| **6** | sentiment-api-dev main 의 채워진 resources 확인 + LimitRange 없는 namespace 에서 거절 비교 | LimitRange 가 빈 자리를 채우는 효과를 두 비교군으로 직접 봄 |
| **7** (선택) | 같은 oversize 를 prod 에 시도 → 통과 확인 + namespace 간 Service endpoints 격리 검증 | "환경별 quota 차등" 의 효과를 직접 비교 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 본 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get ns dev staging prod` 가 모두 `Active` 표시
- [ ] `kubectl describe quota dev-quota -n dev` 가 hard / used 컬럼을 모두 표시하고, sentiment-api-dev 적용 후 `requests.cpu` used 가 200m 로 변함
- [ ] `kubectl describe limitrange dev-limits -n dev` 가 Default / Default Request / Min / Max / Max Limit/Request Ratio 컬럼을 표시
- [ ] sentiment-api-dev 의 main 컨테이너가 `resources` 명시 없이도 `Running` 상태이며, `kubectl get pod -o jsonpath='{.spec.containers[0].resources}'` 가 LimitRange default 값으로 채워져 있음
- [ ] `kubectl apply -f manifests/oversize-pod.yaml` 가 비-0 exit code 와 `Forbidden: exceeded quota` 메시지로 거절되며, dev quota 의 used 는 변하지 않음
- [ ] `kubectl get all -n dev` 와 `kubectl get all -n default` 가 완전히 다른 자원 집합을 표시하여 격리가 유지됨

## 4. 정리

```bash
# dev namespace 통째로 삭제 (안의 모든 자산 cascade 삭제)
kubectl delete namespace dev

# prod 의 oversize-pod 만 삭제 (7-1 단계에서 만든 경우)
kubectl delete pod oversize-pod -n prod 2>/dev/null || true

# kubectl 컨텍스트 되돌리기 (1-3 에서 변경했다면)
kubectl config set-context --current --namespace=default

# minikube 정지 (선택)
minikube stop
```

> ⚠️ **prod 와 staging 은 보존 권장** — 다음 Phase 3 (Helm/Prometheus/HPA) 가 prod namespace 위에 얹힐 수 있습니다. 자세한 정리 절차와 검증은 [labs/README.md 정리 섹션](labs/README.md#정리-cleanup) 참고.

## 🚨 자주 하는 실수

1. **ResourceQuota 적용 시점에 이미 떠 있던 Pod 는 영향 없음**
   ResourceQuota 는 **새로 admission 을 통과하는 Pod** 에만 적용됩니다. 운영자가 quota 를 적용하고 `kubectl describe quota` 의 used 를 보며 "왜 안 줄어?" 라고 오해하기 쉬운데, 이미 떠 있던 Pod 는 quota 합산에 들어가지만 quota 한도와 관계 없이 그대로 살아있습니다 (살아있는 Pod 에 대한 회고적 강제는 없음). 새 Pod 부터 강제됩니다. 운영에서 quota 적용 직후에는 `kubectl rollout restart deployment` 로 기존 Pod 도 한 번 갈아엎어 quota 검증을 거치게 하는 것이 안전합니다.

2. **Quota 만 걸고 LimitRange 안 걸면 request 누락 Pod 전부 거절**
   ResourceQuota 의 `requests.cpu` / `requests.memory` 가 hard 에 등록되어 있으면, **request 가 없는 Pod 는 quota 합산이 불가능** 하므로 admission 단계에서 모두 거절됩니다 (`failed quota: must specify requests.cpu for: ...`). 개발자는 영문도 모르고 매니페스트에 resources 를 손으로 채워야 합니다. 본 토픽 [labs 6-3 단계](labs/README.md#6-3-선택-limitrange-가-없을-때-어떻게-되는지-비교) 가 이를 직접 재현합니다. 해결: ResourceQuota 와 LimitRange 는 **항상 한 쌍** 으로 운영합니다. LimitRange 의 `default` / `defaultRequest` 가 admission 에서 빈 자리를 채워줘야 매니페스트 누락 Pod 도 통과할 수 있습니다.

3. **`kubectl delete namespace prod` 가 안의 모든 자산을 cascade 삭제**
   `kubectl delete namespace <name>` 는 그 안의 Pod / Deployment / Service / PVC / ConfigMap / Secret / Quota / LimitRange / Job / CronJob 까지 모두 cascade 삭제합니다. PVC 가 삭제되면 그 PV 도 (`reclaimPolicy` 가 Delete 면) 함께 사라져 모델 가중치 / 평가 결과까지 통째로 날아갑니다. 운영에서 prod 에는 `kubectl auth can-i delete namespace --as <user>` 같은 RBAC 점검 (Phase 3 의 04-rbac-serviceaccount) 으로 권한 자체를 막아둡니다. 학습 환경에서도 본 토픽 [정리](labs/README.md#정리-cleanup) 단계는 dev 만 삭제하고 prod / staging 은 보존하도록 안내합니다 — 다음 Phase 의 자산이 이 위에 얹힙니다.

## 더 알아보기

- [ResourceQuota — Kubernetes 공식 문서](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
- [LimitRange — Kubernetes 공식 문서](https://kubernetes.io/docs/concepts/policy/limit-range/)
- [Hierarchical Namespace Controller (HNC)](https://github.com/kubernetes-sigs/hierarchical-namespaces) — namespace 의 부모-자식 관계와 정책 상속
- [Kueue — Kubernetes-native Job Queueing](https://github.com/kubernetes-sigs/kueue) — GPU 큐잉 / 우선순위 / 선점, Phase 4 발판

## 다음 챕터

➡️ [Phase 3 / 01-helm-chart — Helm 차트로 Phase 2 자산 패키징](../../phase-3-production/01-helm-chart/lesson.md) (작성 예정)

본 토픽까지 dev / prod 두 환경에 거의 같은 매니페스트를 손으로 두 벌 만들었습니다. 다음 토픽에서는 그 둘을 **하나의 Helm 차트** 로 묶고, `values-dev.yaml` / `values-prod.yaml` 로 환경별 차이만 분리합니다. `helm install sentiment-api ./chart --namespace dev --values values-dev.yaml` 한 줄이 본 토픽의 ConfigMap + Secret + PVC + Deployment + Service 5 개를 한 번에 배포하며, 본 토픽에서 만든 ResourceQuota / LimitRange 가 그 admission 검사를 그대로 수행합니다. Phase 2 가 끝나고 본격적인 운영 도구로 진입합니다.
