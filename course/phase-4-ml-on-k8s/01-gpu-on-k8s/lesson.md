# Phase 4 / 01 — GPU on Kubernetes (NVIDIA Device Plugin, MIG, Time-slicing)

> 직전 토픽 [Phase 3/04 rbac-serviceaccount](../../phase-3-production/04-rbac-serviceaccount/lesson.md) 가 sentiment-api Pod 의 *권한 표면적* 을 마감했다면, 본 토픽은 같은 Pod 가 *다른 가속기* — GPU — 위에서 동작할 때 무엇이 달라지는지를 다룹니다. Phase 0–3 의 sentiment-api 는 *CPU 만으로 충분한* 작은 분류 모델이었지만, Phase 4/03 의 vLLM (`microsoft/phi-2`) 부터 캡스톤의 RAG 챗봇까지는 *GPU 없이는 시작도 못 합니다*. 본 토픽은 그 GPU 가 K8s 에 어떻게 노출 / 요청 / 격리되는지의 메커니즘을 정립합니다. Phase 2/05 의 [dev-quota.yaml](../../phase-2-operations/05-namespace-quota/manifests/dev-quota.yaml) 이 미리 깔아둔 `requests.nvidia.com/gpu: "1"` 쿼터의 used 가 이 토픽에서 처음 0 → 1 로 채워지는 모습도 함께 검증합니다.

## 학습 목표

1. **NVIDIA Device Plugin** 이 K8s 클러스터에 GPU 를 *extended resource* (`nvidia.com/gpu`) 로 노출하는 메커니즘 — DaemonSet 형태, `/var/lib/kubelet/device-plugins/` socket, 노드 capacity 등록 — 을 설명하고, `kubectl describe node` 로 그 결과를 직접 확인합니다.
2. Pod / Deployment 의 `resources.requests` / `limits` 에 `nvidia.com/gpu: 1` 을 명시하는 **표준 패턴** 을 작성하고, 정수만 허용 / limits-only 자동 복사 / fractional 불가 같은 *extended resource 의 특수 규칙* 을 매니페스트로 검증합니다.
3. **GPU 노드 격리 3종 — nodeSelector + taint + toleration** 의 역할 분담을 표로 정리하고, 셋 중 하나라도 빠졌을 때 어떤 Pending 메시지가 뜨는지를 [sentiment-gpu-mistake.yaml](manifests/sentiment-gpu-mistake.yaml) 로 직접 재현합니다.
4. GPU *공유 전략* — **MIG** (A100/H100 의 하드웨어 슬라이스, 격리 강) 와 **Time-slicing** (CUDA context 시분할, 격리 약) — 의 사용 시나리오 차이를 구분하고, MPS / GPU Operator 같은 인접 개념의 위치를 인지합니다.

**완료 기준 (1줄)**: Track A 학습자는 `kubectl describe pod -l phase-4-01=mistake-must-be-deleted` 의 events 에 `Insufficient nvidia.com/gpu` 메시지가 떠야 통과. Track B 학습자는 `kubectl logs gpu-smoke` 가 `nvidia-smi` 표를 출력하고, **클러스터 삭제** (`gcloud container clusters delete`) 까지 끝나야 통과.

## 왜 ML 엔지니어에게 GPU 스케줄링이 필요한가

Phase 0–3 까지 sentiment-api 는 ~500MB 짜리 RoBERTa-base 분류 모델로, CPU 한 코어만으로 추론 latency 30~80ms 를 충분히 냈습니다. 그래서 GPU 가 *왜 필요한지* 실감이 잘 안 났을 수 있습니다. 그 분기점은 다음 둘 중 하나가 들어오는 순간입니다.

- **(a) 모델이 커진다** — Phase 4/03 의 `microsoft/phi-2` (2.7B 파라미터) 만 되어도 *CPU 추론 latency 가 수 초~수십 초* 가 됩니다. 답변이 1초 안에 나와야 하는 챗봇에는 비현실적. 캡스톤의 LLM 은 GPU 가 *전제* 입니다.
- **(b) 동시 추론이 많아진다** — sentiment-api 도 RPS 200+ 부터는 CPU 코어가 부족해집니다. GPU 1 장이 CPU 32 코어 분량의 추론 처리량을 내는 일이 흔합니다.

ML 엔지니어가 K8s 위에서 GPU 를 다룰 때 마주치는 *세 가지 운영 문제* 가 있고, 본 토픽이 그 셋을 차례로 풀어줍니다.

| 운영 문제 | 본 토픽의 해결 도구 |
|----------|------------------|
| GPU 가 비싸 모든 노드에 깔지는 못함 — 어떤 Pod 가 GPU 노드로 갈지 제어 | `nvidia.com/gpu` requests + nodeSelector + tolerations |
| GPU 노드에 *아무 Pod* (예: nginx 사이드카, 모니터링 agent) 이 들어가면 GPU 가 낭비 | 노드의 taint + Pod 의 toleration 으로 *GPU 워크로드만* 들어가도록 격리 |
| GPU 1 장이 비싸므로 *여러 Pod 가 공유* 하고 싶음 | MIG (A100+) 또는 Time-slicing (T4/V100 도 OK) |

세 도구 모두 K8s 표준 자원으로 동작하기 때문에, Phase 3 까지 배운 Helm / Prometheus / HPA / RBAC 와 충돌 없이 합쳐집니다. 본 토픽에서 패턴을 정립하면 Phase 4/03 vLLM, 캡스톤의 vLLM Deployment 가 같은 5–6 줄로 그대로 굴러갑니다.

## 1. 핵심 개념

### 1-1. NVIDIA Device Plugin — GPU 가 K8s 자원이 되는 길

K8s 의 스케줄러는 *CPU* 와 *memory* 만 기본 자원으로 압니다. GPU 는 *extended resource* — 외부 컴포넌트가 노드 capacity 에 등록한 임의의 자원 — 의 한 종류이고, 그 등록을 담당하는 컴포넌트가 **NVIDIA Device Plugin** 입니다.

```
[GPU 노드 (호스트)]                                      [kube-apiserver]
  ├─ NVIDIA 드라이버 (커널 모듈)
  ├─ NVIDIA Container Toolkit (containerd / docker hook)
  └─ kubelet
       │ Unix socket (/var/lib/kubelet/device-plugins/nvidia.sock)
       ▼
  ┌────────────────────────────┐    ListAndWatch       ┌─────────────────────┐
  │ nvidia-device-plugin Pod    │ ───────────────────► │ Node.status.capacity│
  │ (DaemonSet, 모든 GPU 노드)  │                       │  nvidia.com/gpu: N  │
  └────────────────────────────┘                       └─────────────────────┘
```

핵심은 *세 컴포넌트의 분업* 입니다 — 드라이버 (커널 레벨, 호스트 OS 가 설치) + Container Toolkit (컨테이너 런타임에 GPU 디바이스 매핑) + Device Plugin (K8s 에 자원 등록). 셋 중 하나라도 빠지면 Pod 가 `nvidia.com/gpu: 1` 을 요청해도 schedule 자체가 안 되거나, 컨테이너 안에서 `nvidia-smi` 가 실패합니다 (자주 하는 실수 1번).

GKE / EKS / AKS 의 GPU 노드 풀은 위 셋을 *자동* 으로 깔아줍니다. 로컬 GPU + minikube 환경에서는 직접 깔아야 하고, 그 표준 도구가 [NVIDIA GPU Operator](https://github.com/NVIDIA/gpu-operator) — Operator 가 드라이버 / Toolkit / Device Plugin 을 *한 번에* 관리해 줍니다.

> 💡 본 토픽의 [`gpu-smoke-pod.yaml`](manifests/gpu-smoke-pod.yaml) 은 *Device Plugin 이 정상 동작하는지의 5초 검증* 입니다. `nvidia/cuda:12.2.0-base` 이미지로 `nvidia-smi` 한 번 출력하고 종료. 본격적인 sentiment-api / vLLM 을 띄우기 *전에* 이 한 줄로 환경 점검을 끝내는 습관을 권장.

### 1-2. Pod 의 GPU 자원 요청 — extended resource 의 특수 규칙

`nvidia.com/gpu` 는 K8s 의 표준 자원 (`cpu`, `memory`) 이 아닌 *extended resource* 라서 다음 4 가지 규칙이 일반 자원과 다릅니다.

```yaml
# 표준 패턴
resources:
  requests:
    cpu: "250m"
    memory: "1Gi"
    nvidia.com/gpu: 1     # ① 정수만 — 0.5, "1.5" 같은 fractional 불가
  limits:
    cpu: "1"
    memory: "2Gi"
    nvidia.com/gpu: 1     # ② requests 와 *동일 값* 이어야 함 (다르면 admission 거절)
```

| 규칙 | 의미 | 함정 / 운영 팁 |
|-----|------|--------------|
| ① **정수만** | 카드 1장 단위로만 요청. fractional 표현 (0.5) 은 admission 에서 거절 | "GPU 절반만 쓰고 싶다" 는 욕구는 Time-slicing / MIG 로 해결 — 본 1-4 절 |
| ② **requests = limits** | extended resource 는 *burst 개념이 없음* — 같은 값이어야 한다는 K8s 의 제약 | 자주 하는 실수 2번. CPU/memory 처럼 limits 만 두면 K8s 가 자동 복사 (마치 의도된 듯) — 운영 코드는 양쪽 다 명시 권장 |
| ③ **requests-only 와 limits-only 가 다르다** | 일반 자원과 달리, extended resource 는 *limits-only* 도 admission 통과 (자동 복사) | [sentiment-gpu-mistake.yaml](manifests/sentiment-gpu-mistake.yaml) 의 함정 ① — limits 에만 적은 경우. 동작은 하지만 의도 불명확 |
| ④ **자원 *발견* 은 노드별** | `nvidia.com/gpu` capacity 는 GPU 가 있는 노드에만 등록. 일반 노드에는 키 자체가 없음 | `kubectl describe node <gpu-node> \| grep -A2 Capacity` 로 직접 확인 (1-1 절 다이어그램의 결과) |

**자원 차감은 어떻게 일어나나?** Pod 가 `nvidia.com/gpu: 1` 로 schedule 되는 순간 노드의 `Allocatable.nvidia.com/gpu` 에서 1 이 차감되고, Pod 가 종료 / 삭제되면 복구됩니다. 동일 노드에 4 GPU 가 있다면 4 개 Pod 까지 동시 schedule 가능. 다섯 번째 Pod 는 *다른 GPU 노드* 로 가거나 (없으면) Pending.

> 💡 `kubectl describe node` 의 `Allocated resources` 섹션에 `nvidia.com/gpu` 사용량이 보입니다. Phase 2/05 의 dev namespace 안에서 GPU Pod 을 띄우면 *namespace 의 ResourceQuota* 까지 함께 차감되어, `kubectl describe quota dev-quota -n dev` 의 `requests.nvidia.com/gpu used: 1` 을 직접 확인할 수 있습니다 (lab Track B Step 8).

### 1-3. GPU 노드 격리 3종 — nodeSelector + taint + toleration

GPU 가 비싸기 때문에, 한 클러스터에 GPU 노드와 일반 노드를 *섞어* 두는 것이 표준입니다. 이때 두 가지 실수가 흔합니다 — (a) GPU Pod 이 일반 노드로 가서 `Insufficient nvidia.com/gpu` 로 Pending, (b) 일반 Pod 이 비싼 GPU 노드로 가서 GPU 가 *낭비*. 두 문제를 양방향으로 막는 도구 3 종이 nodeSelector / taint / toleration 입니다.

| 도구 | 어디에 설정 | 방향 | 의미 |
|-----|------------|------|------|
| **nodeSelector** (또는 nodeAffinity) | Pod | Pod → Node *양수* | "나는 라벨이 X 인 노드로 가고 싶다" — 매칭 안 되면 schedule 안 됨 |
| **taint** | Node | Node → Pod *거부* | "이 노드는 toleration 이 있는 Pod 만 받는다" — taint 가 있는데 Pod 에 toleration 이 없으면 schedule 거절 |
| **toleration** | Pod | Pod → Node *거부 무시* | "나는 X taint 가 있어도 들어갈 수 있다" — taint 와 짝. taint 가 없는 노드에는 영향 없음 |

세 도구의 *조합 효과* 가 핵심입니다. GKE GPU 노드는 *기본적으로* 다음 두 가지가 자동 설정되어 있습니다.

```yaml
# Node 의 metadata 에 자동 추가되는 라벨
labels:
  cloud.google.com/gke-accelerator: nvidia-tesla-t4

# Node 의 spec 에 자동 추가되는 taint
taints:
  - key: nvidia.com/gpu
    value: present
    effect: NoSchedule
```

이 두 가지 때문에 GKE GPU 노드는 다음 4 케이스로 동작합니다.

```
                  toleration 없음                     toleration 있음
nodeSelector 없음  ❌ taint 거절 → 다른 노드로         ❌ 다른 노드도 GPU capacity 없음 → Pending
                                                        (단, 일반 노드로는 갈 수 있음 — GPU 낭비 못함)
nodeSelector 있음  ❌ taint 거절 → Pending             ✅ GPU 노드 스케줄 → 정상 동작
```

오른쪽 위 칸이 [sentiment-gpu-mistake.yaml](manifests/sentiment-gpu-mistake.yaml) 의 시연 (양쪽 다 누락) 에 가깝고, 오른쪽 아래 칸이 [sentiment-gpu-deployment.yaml](manifests/sentiment-gpu-deployment.yaml) 의 정상 패턴입니다. 두 매니페스트의 *4-군데 diff* 가 본 토픽이 가르치는 표준 GPU Pod 의 모양입니다.

> 💡 nodeSelector 대신 *nodeAffinity* 를 쓰면 더 복잡한 매칭 (예: "T4 또는 L4, 단 V100 은 제외") 이 가능합니다. 본 토픽은 단순 nodeSelector 만 다루지만, *여러 GPU 모델이 섞인 클러스터* 운영에서는 nodeAffinity 가 표준이 됩니다.

### 1-4. GPU 공유 전략 — MIG vs Time-slicing vs MPS

GPU 1 장은 보통 16~80GB 메모리를 가지는데, sentiment-api 같은 작은 추론 모델은 그 중 0.5~2GB 만 씁니다. *나머지 메모리·연산을 다른 Pod 와 공유* 하고 싶다는 게 자연스러운 욕구이고, 그 답은 GPU 모델과 격리 요구에 따라 셋 중 하나입니다.

| 전략 | 격리 강도 | 지원 GPU | 동작 원리 | 적합한 워크로드 |
|------|---------|---------|---------|---------------|
| **MIG** (Multi-Instance GPU) | ⭐⭐⭐ 강 (하드웨어) | A100, H100, L40S 등 *최신 데이터센터 GPU* | GPU 를 *하드웨어 단위* 로 1g.5gb / 2g.10gb / 3g.20gb / 7g.40gb 등 슬라이스. 메모리·SM (Streaming Multiprocessor) 이 물리적으로 분리 | 멀티테넌시 (다른 팀 / 보안 격리), 서로 다른 추론 워크로드 |
| **Time-slicing** | ⭐ 약 (시분할) | *모든 NVIDIA GPU* (T4, V100 포함) | NVIDIA Device Plugin 이 GPU 1 장을 N 개로 *복제* 한 것처럼 노출. CUDA context 가 시분할로 swap | 작은 추론 모델 다중 실행, 개발 / 학습 환경 |
| **MPS** (Multi-Process Service) | ⭐⭐ 중 (프로세스 격리) | 동일 GPU 카드 위 여러 *CUDA 프로세스* | NVIDIA MPS daemon 이 여러 프로세스의 CUDA 호출을 단일 GPU context 로 합침 | 추론 latency 민감 워크로드 (context switch 오버헤드 회피) |

본 토픽은 [gpu-time-slicing-config.yaml](manifests/gpu-time-slicing-config.yaml) 으로 Time-slicing 의 *설정 모양* 만 보여줍니다. 실 운영에서는 NVIDIA GPU Operator 의 helm values 또는 GKE 의 `--gpu-sharing-strategy=time-sharing` 옵션이 더 간단합니다.

세 전략의 결정 트리를 한 줄로 요약하면: *서로 다른 팀이 공유하면 MIG, 같은 팀이 작은 모델 여러 개를 띄우면 Time-slicing, latency 민감 다중 프로세스면 MPS*. Phase 4/03 vLLM 은 *MIG / Time-slicing 둘 다 비추* — LLM 추론은 GPU 메모리 / 연산을 풀로 쓰는 것이 paged attention 효율이 가장 좋기 때문입니다.

> ⚠ Time-slicing 은 *격리가 약함* — 한 Pod 가 GPU 메모리를 다 쓰면 다른 Pod 도 같이 OOM. 자주 하는 실수 3번. 본 토픽 1-2 절의 ResourceQuota 와 함께 사용해 GPU 메모리 *상한* 을 admission 단계에서 강제하는 패턴이 안전합니다 (단, GPU 메모리 자체에 대한 K8s 표준 제한은 없음 — sidecar 모니터링으로 보완).

### 1-5. ML 운영 관점에서 본 GPU 의 두 패턴

K8s 위 GPU 워크로드는 거의 항상 다음 두 패턴 중 하나입니다.

**(a) 추론 서빙 — sentiment-api / KServe / vLLM**

- Pod 1 개당 GPU 0.x~1 장 (Time-slicing 또는 단독)
- GPU 메모리에 모델 가중치를 *상주* 시키고, 요청을 받을 때마다 forward pass 만 실행
- HPA 로 *Pod 개수* 를 조정 (Phase 3/03), 각 Pod 는 GPU 1 장을 점유
- 본 토픽의 [sentiment-gpu-deployment.yaml](manifests/sentiment-gpu-deployment.yaml) 이 입구. Phase 4/02 KServe / 03 vLLM 이 그 위에 추론 표준 / LLM 특화 기능을 얹음.

**(b) 학습 / 인덱싱 — Argo Job / KubeRay / Kubeflow Training**

- Pod 여러 개가 GPU 여러 장을 *동시* 에 점유 (분산 학습), 또는 단일 GPU 로 짧게 실행 후 종료
- 워크로드는 *Job / Workflow* — 끝나면 Pod 가 사라지고 GPU 자원 즉시 회수
- 본 토픽 범위 밖이지만 Phase 4/04 Argo / 05 분산학습 이 같은 `nvidia.com/gpu` 자원을 *Job 의 PodTemplate* 으로 요청

두 패턴 모두 *Pod 의 nvidia.com/gpu requests* 라는 같은 어휘로 표현됩니다. 본 토픽이 정립하는 매니페스트 5–6 줄이 Phase 4 의 모든 후속 토픽에 *그대로* 들어갑니다.

## 2. 실습 개요

전체 절차는 [labs/README.md](labs/README.md) 에 *이중 트랙* 으로 정리되어 있습니다. 학습자는 자신의 환경에 맞는 트랙을 고른 뒤 그 안의 단계를 순서대로 진행합니다.

### Track A — minikube 모의 (GPU 없이도 진행 가능, Step 0–5)

| 단계 | 내용 | 핵심 검증 |
|-----|------|---------|
| 0 | minikube 기동 + Phase 2/05 dev quota 잔존 확인 | `kubectl get quota -n dev` |
| 1 | `kubectl explain pod.spec.containers.resources` 로 nvidia.com/gpu 가 limits 키에 들어갈 수 있음을 확인 + 노드 capacity 에 GPU 키가 *없음* 확인 | `kubectl get node -o yaml \| grep -A2 capacity` |
| 2 | [sentiment-gpu-mistake.yaml](manifests/sentiment-gpu-mistake.yaml) apply → Pending → `kubectl describe pod` events 의 `Insufficient nvidia.com/gpu` 메시지 확인 → delete | apply / describe / delete |
| 3 | [sentiment-gpu-deployment.yaml](manifests/sentiment-gpu-deployment.yaml) `--dry-run=server` — 매니페스트 정합성 검증 (실제 apply 는 안 함) | `kubectl apply --dry-run=server` |
| 4 | Phase 1/04 의 [deployment.yaml](../../phase-1-k8s-basics/04-serve-classification-model/manifests/deployment.yaml) 와 *4-군데 diff* 확인 — 본 토픽의 핵심 학습 포인트 | `diff` 또는 시각적 비교 |
| 5 | 정리 — mistake 삭제 / minikube 보존 (Phase 4/02 가 사용) | `kubectl get all -l phase-4-01=mistake-must-be-deleted -A` 가 0 건 |

### Track B — GKE 실전 (GPU 노드 풀, Step 0–9)

| 단계 | 내용 | 핵심 검증 |
|-----|------|---------|
| 0 | gcloud 인증 + 프로젝트 선택 + 비용 안내 확인 | `gcloud config list` |
| 1 | GKE 클러스터 + GPU 노드 풀 (Spot T4 1 장) 생성 — *시작 시간 ~5–8분* | `gcloud container clusters create` |
| 2 | nvidia-device-plugin DaemonSet 자동 설치 확인 | `kubectl get ds -n kube-system \| grep nvidia` |
| 3 | `kubectl describe node` 로 capacity / allocatable 의 `nvidia.com/gpu` 등록 확인 | `kubectl describe node \| grep -A2 nvidia.com/gpu` |
| 4 | [gpu-smoke-pod.yaml](manifests/gpu-smoke-pod.yaml) apply → `kubectl logs gpu-smoke` 로 nvidia-smi 표 출력 확인 | `kubectl logs` |
| 5 | (선택) 자기 sentiment-api:v1 이미지를 Artifact Registry 에 push → [sentiment-gpu-deployment.yaml](manifests/sentiment-gpu-deployment.yaml) image 변경 후 apply → `kubectl exec` + `nvidia-smi` 로 GPU 메모리 사용 확인 | `kubectl exec ... -- nvidia-smi` |
| 6 | [sentiment-gpu-mistake.yaml](manifests/sentiment-gpu-mistake.yaml) apply → events 의 `node(s) had untolerated taint {nvidia.com/gpu: present}` 메시지 확인 → 즉시 delete | `kubectl describe pod` |
| 7 | (옵션) [gpu-time-slicing-config.yaml](manifests/gpu-time-slicing-config.yaml) 개념 학습 + (시간 여유 있으면) GKE node pool `--gpu-sharing-strategy=time-sharing` 으로 재생성 시도 | `kubectl describe node \| grep -A2 nvidia.com/gpu` (capacity 가 1 → N) |
| 8 | Phase 2/05 dev namespace 가 살아있다면 GPU Pod 을 dev 에 배치 → `kubectl describe quota dev-quota -n dev` 의 `requests.nvidia.com/gpu used: 1` 확인 | `kubectl describe quota` |
| 9 | **클러스터 삭제** — `gcloud container clusters delete` 로 비용 청구 정지 | `gcloud container clusters list` 가 0 건 |

## 3. 검증 체크리스트

본 토픽 완료 후 다음이 모두 ✅ 여야 합니다 (트랙별로 적용 항목이 다름).

**Track A (minikube)**
- [ ] `kubectl get node minikube -o jsonpath='{.status.capacity.nvidia\.com/gpu}'` 결과가 *비어 있음* (GPU 없는 환경 정상 상태)
- [ ] `kubectl describe pod -l app=sentiment-api-mistake` events 에 `Insufficient nvidia.com/gpu` 또는 `didn't have free ports`/유사 메시지 확인 후, mistake 매니페스트 회수 (`kubectl get deploy -l phase-4-01=mistake-must-be-deleted -A` 가 0 건)
- [ ] `kubectl apply --dry-run=server -f manifests/sentiment-gpu-deployment.yaml` 가 syntax 오류 없이 통과
- [ ] [Phase 1/04 deployment.yaml](../../phase-1-k8s-basics/04-serve-classification-model/manifests/deployment.yaml) 과 [sentiment-gpu-deployment.yaml](manifests/sentiment-gpu-deployment.yaml) 의 4-군데 diff 를 *직접 손으로 짚을 수 있음*

**Track B (GKE)**
- [ ] `kubectl describe node | grep -A2 nvidia.com/gpu` 가 `Capacity: nvidia.com/gpu: 1` (Time-slicing 이라면 N) 출력
- [ ] `kubectl logs gpu-smoke` 가 `nvidia-smi` 표 (T4 / 메모리 사용 / 드라이버 버전) 출력
- [ ] `kubectl describe pod -l app=sentiment-api-mistake` events 에 `node(s) had untolerated taint` 또는 `Insufficient nvidia.com/gpu` 메시지 확인 후 회수
- [ ] (Step 8 진행 시) `kubectl describe quota dev-quota -n dev` 의 `requests.nvidia.com/gpu` used 값이 1 이상으로 채워짐
- [ ] **`gcloud container clusters list` 결과가 비어 있음** (가장 중요 — 클러스터 삭제 안 하면 비용 청구 지속)

## 4. 정리

본 토픽이 만든 자산 중 *영구 보존 / 일시적 / 절대 잔존 X* 가 명확합니다.

```bash
# (영구 보존) 매니페스트 4종 + lesson.md + labs/README.md
#   → 학습 자료. 어떤 정리도 하지 않음. Phase 4/02 KServe / 03 vLLM 이 같은 매니페스트 패턴을 확장해 사용.

# (절대 잔존 X) Track A / B 양쪽의 mistake 매니페스트
kubectl delete -f manifests/sentiment-gpu-mistake.yaml --ignore-not-found
kubectl get all -l phase-4-01=mistake-must-be-deleted -A
# → 결과 0 건이어야 함

# (Track B 만, 그러나 가장 중요) GKE 클러스터 삭제
gcloud container clusters delete <cluster-name> --zone=<zone> --quiet
gcloud container clusters list
# → 본 토픽으로 만든 클러스터가 *목록에 없어야* 함. 잔존 시 시간당 ~$0.5+ 청구 지속.
```

> 🚨 GKE 클러스터 삭제는 *본 토픽의 가장 중요한 정리 단계* 입니다. Spot T4 1 장이라도 클러스터 (control plane + GPU 노드 풀) 가 24 시간 살아있으면 ~$10 가 청구됩니다. 다음 토픽 시작 시 새 클러스터를 다시 만드는 것이 표준 (Phase 4/03 vLLM 도 별도 클러스터를 권장 — 더 큰 GPU 가 필요).

## 🚨 자주 하는 실수

1. **NVIDIA Device Plugin / Container Toolkit / 드라이버 *셋 중 하나* 빠짐 → `nvidia.com/gpu` 자원이 노드에 등록 안 됨**
   GPU 가 *물리적으로* 꽂혀 있어도, 드라이버 (호스트 OS 의 커널 모듈) + Container Toolkit (containerd hook) + Device Plugin (DaemonSet) 셋이 모두 살아있어야 K8s 가 GPU 를 자원으로 인식합니다. 진단: `kubectl get ds -n kube-system | grep nvidia` (Device Plugin 살아있는지) + `kubectl describe node <gpu-node> | grep -A2 Capacity` (capacity 에 nvidia.com/gpu 키가 있는지). GKE / EKS / AKS 의 GPU 노드 풀은 자동 설치하지만, *minikube + 로컬 GPU* 환경에서는 셋 다 직접 설치해야 합니다. 해결 패턴: ① 클라우드면 GPU 노드 풀 옵션 (`gcloud container node-pools create --accelerator=...`) 으로 재생성, ② 온프렘이면 [NVIDIA GPU Operator](https://github.com/NVIDIA/gpu-operator) helm chart 한 줄 설치 — Operator 가 셋을 함께 관리.

2. **toleration 또는 nodeSelector 누락 → 영구 Pending**
   GKE / EKS 의 GPU 노드는 자동으로 `nvidia.com/gpu=present:NoSchedule` taint 가 걸려 있어, *toleration 없는 Pod 은 GPU 노드에 들어갈 수 없습니다*. 동시에 nodeSelector 가 없으면 GPU *노드를 양수로 매칭* 도 안 되어 일반 노드로 갈 수 있고, 일반 노드에는 `nvidia.com/gpu` capacity 가 없어 Pending. 본 토픽의 [sentiment-gpu-mistake.yaml](manifests/sentiment-gpu-mistake.yaml) 이 *양쪽 다 누락한 안티패턴* 입니다. 진단: `kubectl describe pod <pending-pod>` events 에 `node(s) had untolerated taint` 또는 `Insufficient nvidia.com/gpu` 메시지가 보입니다. 해결: ① nodeSelector 로 GPU 노드 라벨 양수 매칭 (`cloud.google.com/gke-accelerator: nvidia-tesla-t4`), ② tolerations 로 GPU 노드 taint 허용 (`key: nvidia.com/gpu, operator: Exists, effect: NoSchedule`). 둘이 *항상 함께* 다닙니다 — 본 토픽의 [sentiment-gpu-deployment.yaml](manifests/sentiment-gpu-deployment.yaml) 이 정상 패턴.

3. **GPU 메모리 100% 점유 (`--gpu-memory-utilization=1.0`, 도커 시절 `--gpus all` 습관) → 같은 GPU 다른 Pod 와 OOM 충돌**
   K8s 의 `nvidia.com/gpu: 1` 은 *카드 단위* 만 통제하고, *GPU 메모리* 자체에 대한 admission 제한은 없습니다 (Time-slicing / MIG 활성화 시에도). 한 Pod 가 vLLM 의 `--gpu-memory-utilization=1.0` (GPU 메모리 100% 예약) 으로 띄워지면 같은 GPU 의 다른 Pod 가 *메모리 할당을 시도하는 순간 OOM* 으로 죽습니다. 도커 단독 환경에서 `--gpus all` 로 무제한 사용했던 습관이 K8s 멀티테넌시로 옮겨오면 이 함정이 자주 발생. 진단: `nvidia-smi` 의 *Memory-Usage* 컬럼이 ~100% 로 고정되어 있으면 위험 신호. 해결: ① vLLM 의 `--gpu-memory-utilization=0.85` 같이 명시적 상한 설정, ② Time-slicing 은 *작은 모델* (각 < GPU 메모리 / N) 끼리만 사용, ③ 큰 모델 / LLM 은 GPU 1 장을 단독 점유 (Phase 4/03 vLLM 의 표준 패턴).

## 더 알아보기

- [Kubernetes 공식 — Schedule GPUs](https://kubernetes.io/docs/tasks/manage-gpus/scheduling-gpus/) — 본 토픽 1-1 / 1-2 절의 풀 reference. extended resource 의 모든 동작 규칙.
- [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html) — 드라이버 / Container Toolkit / Device Plugin 을 통합 관리하는 Operator. 온프렘 / 로컬 minikube 의 표준.
- [NVIDIA k8s-device-plugin — Time-slicing 가이드](https://github.com/NVIDIA/k8s-device-plugin#shared-access-to-gpus-with-cuda-time-slicing) — 본 토픽 1-4 절 / [gpu-time-slicing-config.yaml](manifests/gpu-time-slicing-config.yaml) 의 출처.
- [NVIDIA MIG User Guide](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/) — A100 / H100 의 MIG 슬라이스 (1g.5gb / 7g.40gb 등) 가 *왜 그런 이름인가* 의 원전.
- [GKE — GPU 노드 풀 만들기](https://cloud.google.com/kubernetes-engine/docs/how-to/gpus) — Track B 의 클러스터 생성 명령 (Spot T4 / `--gpu-sharing-strategy=time-sharing`) 의 풀 옵션.
- [Phase 2/05 의 dev-quota.yaml](../../phase-2-operations/05-namespace-quota/manifests/dev-quota.yaml) — `requests.nvidia.com/gpu` 가 ResourceQuota 에 어떻게 등록되는지 (used 가 0 인 상태에서 본 토픽이 처음 채움).

## 다음 챕터

➡️ [Phase 4 / 02 — KServe InferenceService](../02-kserve-inference/lesson.md) (작성 예정)

본 토픽이 마감한 자산이 다음 토픽에서 어떻게 이어지는지: ① **`nvidia.com/gpu` requests + nodeSelector + toleration 5–6 줄 패턴** 이 KServe `InferenceService` 의 `spec.predictor.containers[0].resources` 에 그대로 들어가 *모델 서빙의 K8s 표준 추상화* 가 시작됩니다. ② **Time-slicing / MIG** 는 KServe Autoscaler 가 *Pod 개수* 를 조정할 때 GPU 1 장당 몇 Pod 가 들어갈 수 있는지의 전제 조건. ③ **GKE 클러스터 삭제 습관** 은 다음 토픽 시작 시 새 클러스터를 다시 만드는 패턴으로 이어집니다 (캡스톤까지 동일 흐름).
