# Phase 4 / 05 — 실습 가이드 (KubeRay + Kubeflow Training Operator 비교)

> [lesson.md](../lesson.md) 의 §1-2 (KubeRay) 와 §1-3 (Kubeflow Training Operator) 를 minikube 에서 *짧게* 검증합니다. 본 토픽의 디자인 결정 — **KubeRay 만 실행, Kubeflow PyTorchJob 은 매니페스트 분석만** — 을 그대로 따릅니다. 두 도구를 모두 띄우면 minikube 자원이 빠듯하고, 본 토픽은 *분산 학습 입문* 으로 “두 도구의 차이를 매니페스트 수준에서 인지” 하는 것이 목표이기 때문입니다.
>
> **소요 시간**: 30~40분 (KubeRay operator 설치 5분, RayCluster 기동 5분, RayJob 실행 5분, dashboard 확인 5분, PyTorchJob 매니페스트 분석 10분, 정리 5분)
>
> **CPU 만으로 진행 가능** — 본 토픽은 GPU 가 필요 없습니다. 실제 분산 학습 (DDP, RLHF) 은 별도 학습 과정으로 미루고, 여기서는 *디자인 차이의 인지* 에 집중합니다.

---

## 작업 디렉토리

본 lab 의 모든 명령은 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-4-ml-on-k8s/05-distributed-training-intro
ls
# 예상 출력:
# labs  lesson.md  manifests
```

상대경로 `manifests/...` 가 그대로 동작합니다. 본 토픽에는 `practice/` 폴더가 없습니다 (별도 FastAPI 앱이나 학습 코드가 필요 없음).

---

## 실습 단계 한눈에 보기

| Step | 목적 | 핵심 명령 | 소요 |
|-----|------|---------|------|
| 0 | 사전 점검 — minikube/helm 정상 | `minikube status` / `helm version` | 3분 |
| 1 | KubeRay operator Helm 설치 + CRD 등록 확인 | `helm install kuberay-operator ...` | 5분 |
| 2 | ray-demo 네임스페이스 + RayCluster 적용 | `kubectl apply -n ray-demo -f manifests/00-...yaml` | 5분 |
| 3 | head/worker Pod READY 대기 + 자원 확인 | `kubectl get raycluster,pods -n ray-demo` | 5분 |
| 4 | head Pod 안에서 `ray status` / `ray list nodes` | `kubectl exec -it ... -- ray status` | 3분 |
| 5 | RayJob 으로 분산 코드 실행 — `cluster_resources()` 검증 | `kubectl apply -n ray-demo -f manifests/01-...yaml` | 5분 |
| 6 | Dashboard 접속 — head/worker 그래프 확인 | `kubectl port-forward svc/raycluster-toy-head-svc 8265:8265` | 5분 |
| 7 | 정리 | `kubectl delete -f manifests/` + `helm uninstall kuberay-operator` | 5분 |
| 부록 A | PyTorchJob 매니페스트 라인별 분석 (실행 없음) | (읽기만) | 10분 |
| 부록 B | KubeRay vs Kubeflow 비교표 직접 채우기 | (작성) | 10분 |

---

## Step 0 — 사전 점검

```bash
# kubectl (1.28+ 권장)
kubectl version --client

# minikube 상태 — 안 떠 있으면 Step 2 에서 함께 시작
minikube status 2>/dev/null

# Helm (3.x)
helm version --short
```

**예상 출력 (예시):**

```
Client Version: v1.31.x
v3.14.x+gXXXXX
```

✅ **확인 포인트**: kubectl, helm 둘 다 응답하면 다음 Step. minikube 가 아직 멈춰 있어도 됩니다.

---

## Step 1 — KubeRay operator Helm 설치

KubeRay operator 는 RayCluster·RayJob·RayService 3개 CRD 를 클러스터에 등록하고, 그 CR 에 반응해 Pod 을 만들어 주는 controller 입니다. Argo 의 `workflow-controller` 와 같은 자리입니다.

```bash
# minikube 기동 — head 1 + worker 2 의 RayCluster 가 ~3 CPU / ~3Gi 를 사용
minikube start --cpus=4 --memory=8g

# Helm 저장소 추가
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update

# operator 설치 (네임스페이스 분리 — 워크로드는 ray-demo, operator 는 kuberay-operator)
helm install kuberay-operator kuberay/kuberay-operator \
  --namespace kuberay-operator --create-namespace \
  --version 1.1.0

# operator Pod 가 Running 이 되기를 대기
kubectl -n kuberay-operator rollout status deploy/kuberay-operator --timeout=120s

# CRD 가 클러스터에 등록되었는지 확인
kubectl get crd | grep ray.io
```

**예상 출력:**

```
rayclusters.ray.io                           2026-05-05T...
rayjobs.ray.io                               2026-05-05T...
rayservices.ray.io                           2026-05-05T...
```

✅ **확인 포인트**: 3개 CRD (rayclusters / rayjobs / rayservices) 가 모두 보이고, operator Pod 이 Running.

> 💡 **CRD 3종의 의미** — RayCluster 는 *오래 살아 있는 클러스터*, RayJob 은 *클러스터 위에서 실행하는 일회성 작업*, RayService 는 *Ray Serve 추론 엔드포인트*. 본 토픽은 앞 두 개를 사용하고 RayService 는 [lesson.md §1-2](../lesson.md#1-2-kuberay--raycluster--rayjob--rayservice) 에서 비교 표로만 언급합니다.

---

## Step 2 — ray-demo 네임스페이스 + RayCluster 적용

```bash
# 워크로드 네임스페이스 분리
kubectl create namespace ray-demo

# RayCluster 매니페스트 적용 — head 1 + worker 2 (모두 CPU)
kubectl apply -n ray-demo -f manifests/00-kuberay-raycluster-toy.yaml
```

**예상 출력:**

```
raycluster.ray.io/raycluster-toy created
```

```bash
# 첫 30초 안에 KubeRay operator 가 head/worker Pod 를 생성합니다.
kubectl get raycluster,pods -n ray-demo
```

**예상 출력 (생성 직후):**

```
NAME                                  DESIRED WORKERS   AVAILABLE WORKERS   CPUS   MEMORY   GPUS   STATUS   AGE
raycluster.ray.io/raycluster-toy      2                 0                   0      0        0               10s

NAME                                            READY   STATUS              RESTARTS   AGE
pod/raycluster-toy-head-xxxxx                   0/1     ContainerCreating   0          10s
pod/raycluster-toy-worker-small-workers-aaaaa   0/1     ContainerCreating   0          10s
pod/raycluster-toy-worker-small-workers-bbbbb   0/1     ContainerCreating   0          10s
```

> 💡 **이미지 풀 시간** — `rayproject/ray:2.9.0` 은 ~600MB 라 첫 풀에 60–120초가 걸립니다. 두 번째부터는 캐시 히트라 5초 이내. minikube 의 풀 진행률은 `minikube ssh -- crictl images | grep ray` 로 확인할 수 있습니다.

✅ **확인 포인트**: RayCluster CR 1개 + Pod 3개 (head 1 + worker 2) 가 모두 보입니다.

---

## Step 3 — Pod READY 대기 + 자원 확인

```bash
# head/worker 모두 Ready 가 될 때까지 대기 (최대 3분)
kubectl wait --for=condition=Ready pod \
  -l ray.io/cluster=raycluster-toy \
  -n ray-demo --timeout=180s
```

**예상 출력:**

```
pod/raycluster-toy-head-xxxxx condition met
pod/raycluster-toy-worker-small-workers-aaaaa condition met
pod/raycluster-toy-worker-small-workers-bbbbb condition met
```

```bash
# RayCluster STATUS 가 ready 로 전환되었는지
kubectl get raycluster -n ray-demo
```

**예상 출력:**

```
NAME              DESIRED WORKERS   AVAILABLE WORKERS   CPUS   MEMORY   GPUS   STATUS   AGE
raycluster-toy    2                 2                   2      4Gi      0      ready    2m
```

✅ **확인 포인트**: STATUS=ready, AVAILABLE WORKERS=2, CPUS=2 (worker 2개의 limits 합산. head 는 num-cpus=0 으로 카운팅 제외).

---

## Step 4 — head Pod 에서 `ray status`

KubeRay 가 head/worker 사이의 GCS 핸드셰이크를 정확히 끝냈는지 확인하는 가장 빠른 방법은 head 안에서 `ray status` 를 호출하는 것입니다.

```bash
HEAD_POD=$(kubectl get pod -n ray-demo \
  -l ray.io/node-type=head \
  -o jsonpath='{.items[0].metadata.name}')
echo "HEAD_POD = $HEAD_POD"

kubectl exec -it -n ray-demo "$HEAD_POD" -- ray status
```

**예상 출력 (요약):**

```
======== Autoscaler status: 2026-05-05 14:23:45.000000 ========
Node status
---------------------------------------------------------------
Active:
 1 head_group
 2 small-workers
Pending:
 (no pending nodes)
Recent failures:
 (no failures)

Resources
---------------------------------------------------------------
Usage:
 0.0/2.0 CPU
 0B/2.65GiB memory
 0B/1.32GiB object_store_memory

Demands:
 (no resource demands)
```

핵심: **Active 항목에 head_group 1개 + small-workers 2개 — 총 3 노드** 가 보이고, **Resources 의 CPU 가 2.0** 입니다 (worker 2개의 num-cpus 합산).

```bash
# 같은 정보를 한 줄씩 확인하려면
kubectl exec -it -n ray-demo "$HEAD_POD" -- ray list nodes
```

**예상 출력:**

```
======== List: 2026-05-05 14:23:50.000000 ========
Stats:
------------------------------
Total: 3

Table:
------------------------------
    NODE_ID                                                   NODE_IP        IS_HEAD_NODE   STATE   ...
 0  abcd1234...                                               10.244.0.5     True           ALIVE
 1  efgh5678...                                               10.244.0.6     False          ALIVE
 2  ijkl9012...                                               10.244.0.7     False          ALIVE
```

✅ **확인 포인트**: 3개 노드 (head 1 + worker 2) 모두 ALIVE.

---

## Step 5 — RayJob 으로 분산 코드 실행

이미 떠 있는 RayCluster 위에 5초짜리 Python 코드를 던집니다. `clusterSelector` 로 Step 2 의 RayCluster 를 재사용합니다.

```bash
kubectl apply -n ray-demo -f manifests/01-kuberay-rayjob-toy.yaml
```

**예상 출력:**

```
rayjob.ray.io/rayjob-toy created
```

```bash
# RayJob 의 라이프사이클을 watch — Initializing → Running → Complete 순으로 진행
kubectl get rayjob -n ray-demo -w
# 30~60초 후 Status 가 Complete 가 되면 Ctrl+C
```

**예상 출력 (최종):**

```
NAME           JOB STATUS   DEPLOYMENT STATUS   START TIME             END TIME               AGE
rayjob-toy     SUCCEEDED    Complete            2026-05-05T14:24:00Z   2026-05-05T14:24:25Z   30s
```

```bash
# RayJob 이 만든 Submitter Job 의 로그에서 entrypoint 출력 확인
SUBMITTER_POD=$(kubectl get pod -n ray-demo \
  -l ray.io/originated-from-cr-name=rayjob-toy \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n ray-demo "$SUBMITTER_POD" | tail -20
```

**예상 출력 (꼬리부분):**

```
=== ray.cluster_resources() ===
{'CPU': 2.0, 'memory': 2849338819.0, 'object_store_memory': 1424669409.0, 'node:10.244.0.5': 1.0, 'node:10.244.0.6': 1.0, 'node:10.244.0.7': 1.0, 'node:__internal_head__': 1.0}
=== ray.nodes() (count only) ===
node_count = 3
=== distributed map result ===
[0, 1, 4, 9, 16, 25, 36, 49]
```

핵심:

- `ray.cluster_resources()` 의 `'CPU': 2.0` — Step 4 의 `ray status` 와 일치. *코드 한 줄에서 클러스터 전체 자원을 본다* 는 Ray 의 추상화.
- `ray.nodes()` 가 **3** — head 1 + worker 2.
- `[square.remote(i) for i in range(8)]` 의 결과 `[0, 1, 4, 9, 16, 25, 36, 49]` — 8개 task 가 worker 2개에 분산 실행되어 결과를 모았습니다.

✅ **확인 포인트**: JOB STATUS=SUCCEEDED, 로그의 `node_count == 3`, `[0, 1, 4, 9, 16, 25, 36, 49]` 결과 출력.

---

## Step 6 — Dashboard 접속 — head/worker 그래프 확인

Ray 는 클러스터 상태와 task/actor 흐름을 시각화하는 자체 Dashboard 를 head Pod 안에서 8265 포트로 띄웁니다.

```bash
# 새 터미널 또는 백그라운드로
kubectl -n ray-demo port-forward svc/raycluster-toy-head-svc 8265:8265 >/dev/null 2>&1 &
sleep 2

# macOS 기준 — Linux/WSL2 는 firefox/chromium 직접 실행
open http://localhost:8265
```

브라우저에서 다음을 확인합니다.

- **Cluster** 탭: head 1 + worker 2 의 자원 사용률 표시
- **Jobs** 탭: 방금 실행한 `rayjob-toy` 가 SUCCEEDED 상태로 기록됨
- **Actors / Tasks** 탭: `square` task 가 8회 실행된 흔적

✅ **확인 포인트**: Dashboard 좌측 사이드바에 Overview / Jobs / Cluster / Actors 메뉴가 보이고, Cluster 탭에서 3개 노드의 CPU/메모리 게이지가 표시됩니다.

> 💡 **Dashboard 가 흰 화면이거나 connection refused** — head Pod 안에서 dashboard 가 8265 로 바인딩됐는지 확인 (`kubectl exec -it -n ray-demo $HEAD_POD -- netstat -tlnp | grep 8265`). 기본 매니페스트의 `dashboard-host: "0.0.0.0"` 가 빠지면 head Pod 의 localhost 에만 떠서 port-forward 가 안 됩니다.

---

## Step 7 — 정리

```bash
# port-forward 백그라운드 종료
pkill -f 'kubectl.*port-forward.*raycluster-toy' 2>/dev/null

# RayJob → RayCluster 순서로 정리 (역순)
kubectl delete -n ray-demo -f manifests/01-kuberay-rayjob-toy.yaml --ignore-not-found
kubectl delete -n ray-demo -f manifests/00-kuberay-raycluster-toy.yaml --ignore-not-found

# operator 와 워크로드 네임스페이스 정리
helm uninstall kuberay-operator -n kuberay-operator
kubectl delete namespace ray-demo kuberay-operator --ignore-not-found

# CRD 까지 완전 제거하려면 (helm uninstall 만으로는 CRD 가 남음)
kubectl delete crd rayclusters.ray.io rayjobs.ray.io rayservices.ray.io --ignore-not-found

# minikube 자체를 끌 때 (캡스톤도 진행할 거면 생략)
# minikube stop
```

✅ **확인 포인트**: `kubectl get ns` 에 ray-demo 와 kuberay-operator 가 모두 사라지고, `kubectl get crd | grep ray.io` 결과가 비어 있음.

---

## 부록 A — PyTorchJob 매니페스트 라인별 분석

`manifests/10-kubeflow-pytorchjob-toy.yaml` 을 *실행하지 않고* 코드만 읽으면서, KubeRay 매니페스트와 어떻게 다른지 짚습니다.

| 라인 | 필드 | 의미 | KubeRay 의 대응 |
|------|------|------|----------------|
| `apiVersion: kubeflow.org/v1` | API 그룹 | Kubeflow Training Operator 가 등록한 CRD | `apiVersion: ray.io/v1` (KubeRay) |
| `kind: PyTorchJob` | CRD 종류 | *PyTorch DDP 전용*. TF 는 TFJob, MPI 는 MPIJob 으로 *프레임워크별 CRD 분리* | `kind: RayCluster` 또는 `kind: RayJob` (프레임워크 무관) |
| `runPolicy.cleanPodPolicy: All` | 학습 종료 후 Pod 처리 | *없으면 default = None* → Pod 가 살아 GPU 점유 ([자주 하는 실수 1번](../lesson.md#-자주-하는-실수)) | RayJob 의 `shutdownAfterJobFinishes` 가 비슷한 역할이지만, *클러스터 단위* 정리 |
| `pytorchReplicaSpecs.Master.replicas: 1` | Master role 의 Pod 수 | DDP 통신의 *rendezvous 포인트*. 항상 1 | KubeRay 의 `headGroupSpec.replicas` 는 *고정 1*, 프레임워크와 무관 |
| `pytorchReplicaSpecs.Worker.replicas: 2` | Worker role 의 Pod 수 | `WORLD_SIZE = Master + Worker = 3` | `workerGroupSpecs.replicas`. *역할 분리 없음* — 모든 worker 가 같은 자격 |
| (없음) | 환경변수 자동 주입 | Training Operator 가 *자동으로* `MASTER_ADDR`, `MASTER_PORT`, `WORLD_SIZE`, `RANK` 를 각 Pod 에 주입 | 학습자가 `ray.init()` 한 줄로 추상화 — 환경변수 직접 다루지 않음 |
| `image: pytorch/pytorch:...` | 학습 이미지 | *학습 코드 + DDP 초기화* 를 포함한 사용자 정의 이미지 | `image: rayproject/ray:...` — Ray 라이브러리만 들어 있고, 학습 코드는 RayJob 의 `entrypoint` 로 *런타임에 전달* |
| `nvidia.com/gpu: 1` (주석 처리) | GPU 요청 | Master/Worker 각자에 명시 | Ray 도 같은 방식 — `workerGroupSpecs` 의 resources.limits 에 명시 |

**핵심 관찰 3개**:

1. **PyTorchJob 은 *프레임워크별 CRD*** — TF 모델은 TFJob, OpenMPI 기반 분산은 MPIJob. KubeRay 는 *프레임워크 무관* — Ray 가 통신을 다 추상화.
2. **`cleanPodPolicy` 는 PyTorchJob 의 *고유한 안전 장치*** — KubeRay 의 RayJob 은 `shutdownAfterJobFinishes` 가 비슷하지만 *클러스터 전체* 를 정리. 학습 중 디버깅 가치가 높을 때 PyTorchJob 의 세분화가 유리.
3. **환경변수 vs 라이브러리 추상화** — Kubeflow 는 *low-level 통신 환경* 을 만들어 주고 학습 코드는 native PyTorch 그대로. KubeRay 는 *Ray 라이브러리 위에서 코드를 작성* 해야 함. 기존 PyTorch 학습 스크립트 마이그레이션은 Kubeflow 가 더 쉬움.

이 3개 관찰은 [lesson.md §1-4 선택 가이드](../lesson.md#1-4-선택-가이드--언제-무엇을-쓰는가) 표의 행마다 직접 대응됩니다.

---

## 부록 B — KubeRay vs Kubeflow 비교표 직접 채우기

학습자가 lesson.md 와 본 lab 의 경험을 바탕으로 다음 빈 표를 직접 채워 봅니다. 답안은 [lesson.md §1-4](../lesson.md#1-4-선택-가이드--언제-무엇을-쓰는가) 의 표와 비교해 자가 채점하세요.

| 비교 축 | KubeRay | Kubeflow Training Operator |
|---------|---------|----------------------------|
| 추상화 수준 | (예: 라이브러리 + 클러스터 매니저) | (예: K8s CRD + 환경변수 주입만) |
| 지원 프레임워크 | | |
| 학습 코드 작성 방식 | | |
| Pod 역할 분리 | | |
| 자동 정리 정책 필드 | | |
| 분산 통신 초기화 | | |
| Hyperparameter Tuning 지원 | | |
| RLHF / Tune / Serve 통합 | | |
| 기존 PyTorch 코드 마이그레이션 비용 | | |
| 학습 곡선 | | |

---

## 막힐 때

| 증상 | 원인 / 해결 |
|------|------------|
| `helm install kuberay-operator` 가 *not found* | helm repo 추가/업데이트 누락. `helm repo add kuberay https://ray-project.github.io/kuberay-helm/ && helm repo update` 다시. |
| RayCluster 의 STATUS 가 *Failed* | head/worker Pod 의 `kubectl logs` 확인. `version mismatch` 메시지면 매니페스트의 `rayVersion` 과 컨테이너 이미지 태그가 다른 것. |
| head Pod 만 Ready, worker 가 *CrashLoopBackOff* | head 의 GCS 포트 (6379) 에 worker 가 못 붙은 것. `kubectl logs <worker-pod>` 에서 `Failed to register worker` 메시지 확인. minikube 재기동으로 해결되는 경우 다수. |
| RayJob 이 *Failed*, Submitter Pod logs 에 `RuntimeError: cannot connect to ray://...` | Step 5 시점에 RayCluster 가 ready 가 아직 아닌 상태. Step 3 의 `kubectl wait` 가 끝났는지 다시 확인 후 Job 재제출. |
| Dashboard 가 *connection refused* | head Pod 의 dashboard 가 0.0.0.0 에 바인딩 안 됨. 매니페스트의 `dashboard-host: "0.0.0.0"` 라인 누락 여부 확인. |
| `kubectl apply -f 10-kubeflow-pytorchjob-toy.yaml` 가 *no matches for kind "PyTorchJob"* | 정상 — 본 매니페스트는 분석 전용이라 Training Operator 미설치 상태가 의도된 결과 ([manifests/README.md](../manifests/README.md#막힐-때)). |

---

## 다음 단계

본 lab 을 마쳤다면 [docs/course-plan.md](../../../../docs/course-plan.md) 의 Phase 4 / 05-distributed-training-intro 의 *minikube 검증* 체크박스를 `[x]` 로 갱신합니다.

➡️ 다음 토픽: [⭐ Capstone — RAG 챗봇 + LLM 서빙 종합 프로젝트](../../capstone-rag-llm-serving/) (Day 1 부터 시작)
