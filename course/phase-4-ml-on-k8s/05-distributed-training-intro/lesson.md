# Phase 4 / 05 — Distributed Training Intro (KubeRay vs Kubeflow Training Operator)

> **Phase**: 4 — ML on Kubernetes
> **소요 시간**: 1.5~2시간 (개념 비교 60분, KubeRay 설치 + RayCluster + RayJob 30분, PyTorchJob 매니페스트 분석 + 비교표 작성 30분)
> **선수 학습**: [Phase 4/01 — GPU on Kubernetes](../01-gpu-on-k8s/lesson.md) (`nvidia.com/gpu` requests/limits 패턴이 두 도구의 매니페스트에 똑같이 등장), [Phase 4/04 — Argo Workflows](../04-argo-workflows/lesson.md) (CRD + controller + Pod 생성 모델)
>
> 이전 토픽 04-argo-workflows 가 *데이터 / 평가 / 인덱싱* 같은 **범용 DAG** 워크플로우를 다뤘다면, 본 토픽은 *학습 워크로드만의 특수한 요구사항* — 멀티 노드 통신 (NCCL/Gloo), 노드별 RANK 부여, 학습 종료 후 자원 정리 — 를 어떤 추상화로 풀어내는지 살펴봅니다. 본 토픽은 study-roadmap 의 명시대로 **"실습은 짧게, 본편 아님"** 입니다. 본격적인 분산 학습 (DDP, FSDP, RLHF) 은 별도 학습 과정으로 미루고, 여기서는 *어떤 도구를 어떤 시점에 손에 잡을지* 의 의사결정 능력을 키웁니다.

---

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

1. **분산 학습이 단일 GPU 학습과 *어느 지점에서* 갈라지는지 한 문단으로 설명합니다.** Data / Model / Pipeline 병렬화의 차이, GPU 메모리 한계 / 학습 시간 단축 / 모델 크기 라는 세 가지 동기, 그리고 본 토픽이 K8s 위 *분산 학습 프레임워크 추상화* 두 종류 (KubeRay, Kubeflow Training Operator) 에 집중하는 이유를 정리합니다.
2. **KubeRay 의 RayCluster · RayJob · RayService 3종 CRD 를 *언제 무엇을 쓰는지* 구분합니다.** 본 토픽 매니페스트 `00-kuberay-raycluster-toy.yaml` (장기 클러스터) + `01-kuberay-rayjob-toy.yaml` (일회성 작업) 의 라이프사이클 차이를 minikube 에서 직접 확인하고, RayService (=Ray Serve) 가 [Phase 4/02 KServe](../02-kserve-inference/lesson.md) 와 어떻게 역할이 겹치고 갈라지는지 비교합니다.
3. **Kubeflow Training Operator 의 PyTorchJob / TFJob / MPIJob 이 *무엇을 자동화* 하는지 매니페스트 수준에서 식별합니다.** Master 1 + Worker N 구조, Training Operator 가 자동 주입하는 4개 환경변수 (`MASTER_ADDR`, `MASTER_PORT`, `WORLD_SIZE`, `RANK`), 그리고 `cleanPodPolicy` 의 의미와 누락 시 발생하는 GPU 점유 문제 ([자주 하는 실수](#-자주-하는-실수) 1번) 를 매니페스트 `10-kubeflow-pytorchjob-toy.yaml` 에서 라인별로 짚습니다.
4. **두 도구의 디자인 철학 차이를 5–6개 축으로 비교한 표를 직접 채우고, *내 워크로드에 어느 쪽이 맞는지* 결정합니다.** 추상화 수준 (Ray = 라이브러리 + 클러스터 매니저, Kubeflow = 환경변수 주입만), 학습 코드 작성 방식 (Ray 코드 vs native 프레임워크 코드), HPO / RLHF / Serve 통합, 기존 PyTorch 학습 스크립트 마이그레이션 비용 — 이 네 축에서 두 도구가 어떻게 다른지 [§1-4](#1-4-선택-가이드--언제-무엇을-쓰는가) 의 표로 정리합니다.

**완료 기준 (1줄)**: minikube 에서 `kubectl exec ... -- ray status` 가 head 1 + worker 2 의 ALIVE 노드 3개를 보여주고, RayJob 의 로그에서 `ray.cluster_resources()` 가 `'CPU': 2.0` 과 `node_count == 3` 을 출력하면 통과. 더불어 [부록 B 비교표](./labs/README.md#부록-b--kuberay-vs-kubeflow-비교표-직접-채우기) 의 10개 행을 학습자 본인 언어로 채울 수 있다면 본 토픽의 *진짜* 완료입니다.

---

## 왜 ML 엔지니어에게 분산 학습 추상화가 필요한가

Phase 4-1 (GPU) 부터 Phase 4-4 (Argo) 까지 우리는 *추론* 측 워크로드를 다뤘습니다. KServe 가 분류 모델을, vLLM 이 LLM 을, Argo 가 인덱싱 파이프라인을 — 모두 학습이 *끝난 모델의 가중치* 를 들고 와 서빙하거나 활용하는 시나리오였습니다.

학습 측은 다릅니다. 학습 워크로드는 다음 셋 중 하나에서 *반드시* 분산이 필요해집니다.

| 분산 학습이 필요한 시점 | 이유 | 본 토픽이 해결하는 도구 |
|------------------------|------|----------------------|
| **모델이 한 GPU 에 안 들어감** | LLaMA-3 70B 의 가중치만 ~140GB. 단일 H100 80GB 도 부족 → 모델 자체를 여러 GPU 에 쪼갬 (Model / Tensor / Pipeline Parallel) | KubeRay (Ray Train + DeepSpeed/FSDP), Kubeflow Training Operator (PyTorchJob + FSDP) |
| **데이터셋이 너무 커서 한 GPU 의 학습이 며칠** | 같은 모델 복제본을 여러 GPU 에 띄우고, 각자 다른 데이터 배치를 본 뒤 그래디언트를 모음 (Data Parallel = DDP) | 둘 다. 본 토픽이 다루는 *가장 흔한* 케이스 |
| **하이퍼파라미터를 100개 조합 시도해야 함** | 단일 노드로는 불가. 50개 GPU 에 50개 조합을 동시 실행하고 베스트만 살림 | KubeRay (Ray Tune) — Kubeflow 는 Katib 가 별도 |

K8s 가 분산 학습의 *플랫폼* 이 되는 이유는 셋 다 같습니다 — *N개 노드의 자원 (GPU / CPU / 메모리 / 네트워크) 을 선언적으로 묶어 한 학습 작업에 할당* 하는 일이 K8s 가 본래 잘하는 일이기 때문입니다. 그런데 K8s 만으로는 부족합니다. native PyTorch 의 DDP 통신은 학습 시작 시점에 *모든 노드가 서로의 IP 와 RANK 를 알아야* 시작합니다 — 이걸 사람이 수작업으로 매 학습 Job 마다 환경변수에 넣어 주는 건 비현실적입니다.

이 지점에서 *분산 학습 워크로드 전용 추상화* 가 등장합니다. 본 토픽이 비교하는 두 진영은 다음과 같이 갈라집니다.

| 진영 | 어떻게 추상화하나 | 학습 코드 |
|------|-----------------|----------|
| **KubeRay (Ray + RayCluster CRD)** | *Ray 라이브러리* 가 내부적으로 모든 통신을 처리. K8s 위에 *오래 살아 있는 Ray 클러스터* 를 띄우고, 그 위에 학습/추론/HPO 작업을 *Python 코드 위에서* 던짐. | `ray.init()` 한 줄 + `@ray.remote` 데코레이터. Ray 패러다임으로 새로 작성 (또는 Ray Train 의 PyTorchTrainer 로 기존 코드 wrap) |
| **Kubeflow Training Operator (PyTorchJob / TFJob / MPIJob CRD)** | *환경변수 자동 주입* 만 함. `MASTER_ADDR`, `MASTER_PORT`, `WORLD_SIZE`, `RANK` 4개를 각 Pod 에 정확히 넣어주고 나머지는 *native 프레임워크* (torch.distributed, tf.distribute) 가 알아서. | Native PyTorch DDP 코드 그대로. `torch.distributed.init_process_group(backend="nccl")` 한 줄이면 작동. |

본 토픽은 *어느 쪽이 더 좋다* 가 아니라, *언제 어느 쪽을 손에 잡을지* 를 가립니다. 둘 다 K8s native 이고, 둘 다 GPU 를 다루며, 둘 다 캡스톤 / 실 운영에서 만나게 될 도구입니다.

> ℹ️ **본 토픽이 둘 *모두 실습* 하지 않는 이유** — minikube CPU 환경에서 KubeRay 의 head/worker 3 Pod + Kubeflow operator 까지 띄우면 8GB 메모리가 빠듯합니다. 본 토픽은 입문이라 KubeRay 만 *체감* 하고, Kubeflow 는 *매니페스트로 비교* 하는 데 그칩니다. 실 운영에서 둘 다 GPU 클러스터에 동시 설치해 쓰는 건 흔한 패턴입니다 (Kubeflow 가 학습 파이프라인 측에, KubeRay 가 HPO/RLHF 측에).

---

## 1. 핵심 개념

### 1-1. 분산 학습 패러다임 3종 — Data / Model / Pipeline Parallel

분산 학습 추상화 도구를 비교하기 전에 *분산 학습 자체* 의 3가지 패턴을 짚고 갑니다. 이 3가지가 KubeRay/Kubeflow 가 풀려는 *바닥의 문제* 입니다.

| 패러다임 | 무엇을 쪼개나 | 언제 쓰나 | 대표 라이브러리 |
|---------|------------|----------|--------------|
| **Data Parallel (DDP)** | *데이터 배치* 를 N개 GPU 에 나눔. 모델 가중치는 각 GPU 에 *복제본* | 모델은 한 GPU 에 들어가지만 학습이 너무 느릴 때. 가장 흔함 (~80%) | `torch.nn.parallel.DistributedDataParallel`, Horovod |
| **Model Parallel (Tensor Parallel)** | *모델 가중치 행렬* 자체를 GPU 차원으로 쪼갬. forward/backward 마다 GPU 간 all-reduce | 모델 한 개가 한 GPU 에 안 들어갈 때 (LLaMA 70B+) | DeepSpeed, Megatron-LM, FSDP |
| **Pipeline Parallel** | *모델의 layer* 를 GPU 별로 분배 (1~10층은 GPU0, 11~20층은 GPU1, ...) | Tensor Parallel 의 통신 비용이 너무 클 때, layer 가 매우 많을 때 | DeepSpeed PipelineModule, GPipe |

본 토픽은 이 3가지 *어느 것을 쓸 지* 를 직접 다루지는 않습니다. 대신, K8s 측에서 *N개 GPU/노드를 묶어 학습 작업 1개에 주는* 일을 추상화하는 두 도구를 봅니다. DDP / Tensor Parallel / Pipeline Parallel 의 선택은 *학습 코드 안의 라이브러리 호출* 이고, KubeRay/Kubeflow 는 *그 학습 코드를 N개 Pod 으로 띄워서 통신을 잡아주는* 자리입니다.

> 💡 **본 코스에서 DDP 만 손에 잡으려면**: HuggingFace `accelerate` 라이브러리 + 본 토픽 부록 A 의 PyTorchJob 매니페스트 구조면 됩니다. accelerate 가 native `torch.distributed` 의 boilerplate 를 줄여 주고, Training Operator 가 환경변수를 주입해 줍니다.

### 1-2. KubeRay — RayCluster / RayJob / RayService

KubeRay 는 K8s 위에 *Ray 클러스터* 를 운영하는 operator 입니다. Ray 자체는 *분산 Python 프레임워크* — 본래 `ray start --head` / `ray start --address=...` 로 노드를 손수 묶어야 했지만, KubeRay 가 그 일을 K8s CRD 로 추상화합니다.

KubeRay 가 등록하는 CRD 는 3종이고, 각자 *수명* 이 다릅니다.

| CRD | 수명 | 사용 시나리오 | 본 토픽에서 |
|-----|------|------------|-----------|
| `RayCluster` | *오래 살아 있음* (인터랙티브 분석, 노트북, 여러 Job 의 공유 자원) | 데이터 사이언티스트가 Jupyter 에서 ad-hoc 분석. HPO 100회 실행을 위한 안정적 클러스터 | ✅ 매니페스트 `00-kuberay-raycluster-toy.yaml` 에서 head 1 + worker 2 |
| `RayJob` | *일회성* — entrypoint 코드가 끝나면 클러스터도 정리 옵션 | 정기 학습 잡, batch HPO, CI 에서 학습 검증 | ✅ 매니페스트 `01-kuberay-rayjob-toy.yaml` 에서 위 RayCluster 재사용 |
| `RayService` | *오래 살아 있음* + 추론 엔드포인트 (Ray Serve) | LLM 추론 (FastChat, vLLM 통합), 멀티 모델 라우팅 | 본 토픽 범위 밖 — Phase 4/02 KServe 와 역할이 겹침 |

매니페스트의 핵심 모양은 다음과 같습니다 (전체는 [manifests/00-kuberay-raycluster-toy.yaml](./manifests/00-kuberay-raycluster-toy.yaml)).

```yaml
apiVersion: ray.io/v1
kind: RayCluster
metadata:
  name: raycluster-toy
spec:
  rayVersion: "2.9.0"            # head/worker 이미지 버전과 일치 필수
  headGroupSpec:                  # 1개 고정 — GCS, Dashboard, Client server
    rayStartParams:
      num-cpus: "0"               # head 자체는 task 안 받음 (학습 환경 단순화)
      dashboard-host: "0.0.0.0"   # 외부 port-forward 를 위한 바인딩
    template:
      spec:
        containers:
        - name: ray-head
          image: rayproject/ray:2.9.0
          ports:
          - { containerPort: 6379, name: gcs-server }   # head ↔ worker 통신
          - { containerPort: 8265, name: dashboard }    # 브라우저 UI
          - { containerPort: 10001, name: client }      # ray.init(address="ray://...")
  workerGroupSpecs:               # 한 그룹당 같은 spec 의 worker N개
  - groupName: small-workers
    replicas: 2
    minReplicas: 2
    maxReplicas: 2
    template: { spec: { containers: [{...}] } }
```

여기서 KubeRay 의 *디자인 철학* 이 드러납니다.

- **head/worker 는 *역할 분리만* 하고, 모두 같은 Ray 라이브러리** — head 가 GCS / dashboard / scheduler 를 담당하고 worker 는 task 를 실행하지만, 코드는 모두 동일한 `rayproject/ray:2.9.0` 이미지에서 돕니다. 학습 코드는 *런타임에 RayJob 의 entrypoint* 로 들어와서 head 의 Python interpreter 가 worker 에게 분산합니다.
- **클러스터가 *프레임워크 무관*** — PyTorch 학습은 Ray Train 으로, TensorFlow 는 Ray Train + TF, RLHF 는 RLlib, HPO 는 Ray Tune. 같은 RayCluster 위에서 *4가지 워크로드를 모두 받음*.
- **확장은 worker group 단위** — 한 RayCluster 에 `workerGroupSpecs` 를 여러 개 둬서 GPU group / CPU group / 큰 메모리 group 등 *이질적 노드* 를 한 클러스터에 섞을 수 있음.

`RayJob` 은 위 RayCluster 위에 코드 한 덩이를 던지는 자리입니다.

```yaml
apiVersion: ray.io/v1
kind: RayJob
metadata: { name: rayjob-toy }
spec:
  clusterSelector:                                # 기존 RayCluster 재사용
    ray.io/cluster: raycluster-toy
  entrypoint: |                                   # 이 Python 코드가 head 에서 실행됨
    python -c "
    import ray; ray.init()
    print(ray.cluster_resources())
    @ray.remote
    def square(x): return x * x
    print(ray.get([square.remote(i) for i in range(8)]))
    "
  shutdownAfterJobFinishes: false                 # 클러스터는 유지 (다음 job 이 재사용)
```

또는 *임시 클러스터* 패턴 — `clusterSelector` 대신 `rayClusterSpec` 을 써서 Job 시작 시점에 RayCluster 를 새로 생성, Job 종료 시 함께 삭제. 매일 학습 잡 1개씩이면 후자가 깔끔하고, 데이터 사이언티스트가 인터랙티브로 여러 잡을 던지면 전자가 효율적입니다.

> 💡 **Ray 의 *resource* 추상화** — `@ray.remote(num_gpus=1)` 한 줄이면 GPU 가 있는 worker 에 task 가 자동 라우팅됩니다. K8s 의 `nvidia.com/gpu: 1` 라인은 *worker Pod 의 K8s 자원 요청*, Ray 의 `num_gpus=1` 은 *Ray scheduler 가 보는 자원 요청* — 두 층이 따로 있다는 점이 처음에 헷갈립니다. 본 토픽 매니페스트는 CPU 만 쓰므로 둘 다 비활성이지만, GPU 학습 시 둘을 *반드시 일치* 시켜야 합니다.

### 1-3. Kubeflow Training Operator — PyTorchJob / TFJob / MPIJob CRD

Kubeflow Training Operator 는 KubeRay 와 *완전히 다른 추상화 층* 에서 동작합니다. *학습 라이브러리를 새로 도입하지 않고*, *프레임워크 native 의 분산 통신을 K8s 가 잡아 줄 수 있게 환경변수만 자동 주입* 합니다.

가장 흔한 PyTorchJob 매니페스트의 모양 (전체는 [manifests/10-kubeflow-pytorchjob-toy.yaml](./manifests/10-kubeflow-pytorchjob-toy.yaml), *분석 전용 — 실행하지 마세요*).

```yaml
apiVersion: kubeflow.org/v1
kind: PyTorchJob
metadata: { name: pytorch-ddp-toy }
spec:
  runPolicy:
    cleanPodPolicy: All                       # 학습 종료 후 Pod 자동 정리 — 자주 하는 실수 1번
    activeDeadlineSeconds: 43200              # 12시간 안전 장치
  pytorchReplicaSpecs:
    Master:                                   # Master role — DDP rendezvous 포인트
      replicas: 1                             # 항상 1
      restartPolicy: OnFailure
      template:
        spec:
          containers:
          - name: pytorch
            image: my-train:0.1               # *학습 코드 + DDP 초기화* 가 든 사용자 이미지
            command: [python, /workspace/train.py]
            resources:
              limits: { nvidia.com/gpu: 1 }
    Worker:                                   # Worker role — 동일 이미지, 다른 RANK
      replicas: 2                             # WORLD_SIZE = Master + Worker = 3
      restartPolicy: OnFailure
      template: { ... }                       # Master 와 같은 image / command / resources
```

이 매니페스트의 *핵심 메커니즘* 은 매니페스트 안에 보이지 않습니다 — Training Operator 가 *런타임에* 각 Pod 에 다음 4개 환경변수를 자동 주입합니다.

| 환경변수 | 값 | 어디에 쓰나 |
|---------|-----|----------|
| `MASTER_ADDR` | Master Pod 의 K8s Service DNS (예: `pytorch-ddp-toy-master-0.pytorch-ddp-toy.kubeflow.svc`) | `torch.distributed.init_process_group()` 가 rendezvous 시작 시 host 로 사용 |
| `MASTER_PORT` | 23456 (기본). 충돌 시 변경 가능 | rendezvous TCP 포트 |
| `WORLD_SIZE` | Master replicas + Worker replicas 합산 = 3 | DDP 가 *총 몇 개 프로세스가 참가하는지* 인지 |
| `RANK` | Master = 0, Worker = 1, 2, ... | 각 프로세스가 *자신이 몇 번째* 인지. 그래디언트 reduce 의 정렬 기준 |

학습 코드 입장에서는 다음 한 줄이면 분산 학습이 시작됩니다.

```python
import torch.distributed as dist
dist.init_process_group(backend="nccl")     # GPU. CPU 토이는 backend="gloo"
# 위 호출이 위 4개 환경변수를 *자동으로 읽음*
```

다시 말해 *학습 코드는 native PyTorch 그대로* 입니다. Training Operator 의 가치는 *오직 환경변수 주입 자동화* — 적어 보이지만 그 일이 사람 손으로 하기에는 너무 자주 틀립니다.

`cleanPodPolicy` 는 본 토픽의 첫 번째 자주 하는 실수와 직결됩니다.

| 값 | 학습 종료 후 Pod 처리 | 권장 |
|----|---------------------|------|
| `None` (default) | 모든 Pod 유지 | 디버깅 시 일시적으로만. *GPU 가 풀리지 않음* |
| `OnFailure` | 실패한 Pod 만 유지 | 디버깅 + 자원 회수 균형. 운영 권장 |
| `All` | 모든 Pod 정리 | 가장 깨끗. 본 매니페스트의 선택 |

**누락 시 무슨 일이 벌어지나** — `runPolicy.cleanPodPolicy` 자체가 없으면 default 가 `None`. 학습이 끝난 Pod 가 `Completed` 상태로 *Pod 객체와 함께 GPU limits 점유를 유지* 하고, 다음 학습 Job 이 `Pending` 으로 무한 대기. GPU 비용 시간당 청구되는 환경에서는 잠깐 자리를 비운 사이 큰 사고가 됩니다 — [§자주 하는 실수 1](#-자주-하는-실수).

PyTorchJob 외에 같은 패턴의 CRD 가 더 있습니다.

| CRD | 대상 프레임워크 | 차이점 |
|-----|---------------|------|
| `PyTorchJob` | PyTorch DDP / FSDP | Master/Worker 명명, NCCL 또는 Gloo backend |
| `TFJob` | TensorFlow `tf.distribute` | Chief/Worker/PS/Evaluator 명명, gRPC 통신 |
| `MPIJob` | OpenMPI 기반 (Horovod 포함) | Launcher/Worker 명명, MPI rendezvous |
| `XGBoostJob` | XGBoost 분산 | Master/Worker 명명, Rabit 통신 |
| `PaddleJob` | PaddlePaddle | Master/Worker 명명 |

*프레임워크가 다르면 통신 프로토콜과 환경변수가 다르므로 CRD 가 분리* 되어 있습니다. 이 분리가 KubeRay (CRD 1종 = RayCluster) 와의 가장 큰 디자인 차이입니다.

### 1-4. 선택 가이드 — 언제 무엇을 쓰는가

위 두 도구의 디자인 차이를 한 표로 모으면 다음과 같습니다. 이 표가 *본 토픽의 가장 중요한 산출물* 입니다 — 학습자는 [labs/README.md 부록 B](./labs/README.md#부록-b--kuberay-vs-kubeflow-비교표-직접-채우기) 에서 빈 표를 본인 언어로 채워봅니다.

| 비교 축 | KubeRay | Kubeflow Training Operator |
|---------|---------|----------------------------|
| **추상화 수준** | *라이브러리 + 클러스터 매니저* — Ray 라이브러리가 통신/스케줄링/메모리 모두 담당 | *환경변수 주입만* — 통신은 native 프레임워크 (torch.distributed) 가 담당 |
| **지원 프레임워크** | *프레임워크 무관* (PyTorch / TF / JAX / sklearn / pandas / Polars). 같은 RayCluster 에서 모두 | *프레임워크별 CRD 분리* (PyTorchJob / TFJob / MPIJob / ...) |
| **학습 코드 작성 방식** | Ray API (`ray.init()`, `@ray.remote`) 또는 Ray Train wrap | *Native 프레임워크 코드 그대로*. `dist.init_process_group()` 한 줄 |
| **Pod 역할 분리** | head 1 + worker N. *역할은 분리* 되지만 모두 같은 Ray 이미지 | Master 1 + Worker N. *역할별로 다른 환경변수 (RANK)* 주입 |
| **자동 정리 정책** | RayJob 의 `shutdownAfterJobFinishes` (클러스터 단위) | PyTorchJob 의 `cleanPodPolicy` (Pod 단위, 더 세분화) |
| **분산 통신 초기화** | `ray.init()` 한 줄 — Ray 가 GCS 핸드셰이크 알아서 | Training Operator 가 환경변수 주입 → 학습 코드의 `init_process_group()` 가 사용 |
| **HPO 지원** | ⭐ Ray Tune *내장* (population-based, ASHA, BOHB 등 50+ 알고리즘) | 별도 도구 — Kubeflow Katib 와 결합 |
| **RLHF / Tune / Serve 통합** | ⭐ Ray RLlib + Tune + Serve 가 *같은 RayCluster 안에서 통합* | 각자 별도 — Training Operator 는 학습만, RL 은 별도 라이브러리, 추론은 KServe |
| **기존 PyTorch 코드 마이그레이션 비용** | 중간 — Ray Train 으로 wrap 또는 `@ray.remote` 데코레이터 추가 | ⭐ *낮음* — DDP 코드 그대로 이미지에 넣고 매니페스트만 작성 |
| **학습 곡선** | Ray 패러다임 학습 필요 (액터 / 태스크 / 객체 저장소) | K8s + native 프레임워크 학습 그대로 |

**의사결정 가이드** — 다음 셋 중 본인 시나리오가 어디에 가까운지로 정합니다.

1. **단일 모델 / 정해진 프레임워크 / DDP 위주** → **Kubeflow Training Operator**. 마이그레이션 비용이 가장 낮고 native PyTorch 디버깅 도구가 그대로 쓰임.
2. **HPO 100+ 조합 / RLHF / 인터랙티브 분석** → **KubeRay**. Ray Tune + RLlib 의 통합이 결정적 가치.
3. **둘 다 필요** → 둘 다 설치. 같은 GPU 노드 풀에서 *워크로드별로 분리해 사용* 가능. 단, *같은 작업을 두 도구로 동시에 돌리지는 않음* (자원 분배 정책 충돌).

> 💡 **본 코스의 캡스톤 (RAG 챗봇 + LLM 서빙)** 은 *학습이 없으므로* 본 토픽의 도구를 직접 쓰지 않습니다. 캡스톤 이후 *RAG 의 retrieval 정확도를 높이려고 임베딩 모델을 fine-tuning* 하는 단계로 가면, 그때 위 의사결정 가이드의 1번 (Kubeflow PyTorchJob + accelerate) 이 가장 짧은 길입니다.

---

## 2. 실습 개요

본 토픽의 실습은 *짧음* — 30~40분 분량. 자세한 절차는 [labs/README.md](./labs/README.md) 를 따르고, 여기서는 핵심 흐름만 짚습니다.

### 2-1. 실습이 다루는 것 / 다루지 않는 것

| 다루는 것 | 다루지 않는 것 |
|----------|--------------|
| ✅ KubeRay operator Helm 설치 + CRD 등록 확인 | ❌ Kubeflow Training Operator 설치 (시간/자원 부담) |
| ✅ RayCluster 매니페스트 적용 + head/worker Pod 확인 | ❌ Kubeflow PyTorchJob 실행 (CPU 토이로도 무거움) |
| ✅ `ray status` / `ray list nodes` 로 GCS 핸드셰이크 검증 | ❌ 실제 DDP 학습 코드 작성 (별도 학습 과정) |
| ✅ RayJob 으로 `ray.cluster_resources()` 호출 → 분산 자원 인지 | ❌ GPU 자원 할당 (본 토픽 CPU only) |
| ✅ Ray Dashboard 접속 (8265) | ❌ Ray Tune / RLlib / Serve 연계 |
| ✅ PyTorchJob 매니페스트 라인별 분석 (실행 없이) | ❌ Training Operator 가 자동 주입한 환경변수 *직접 관찰* |

### 2-2. 실습 흐름

```bash
# 0. minikube 기동 + 사전 점검 (3분)
minikube start --cpus=4 --memory=8g

# 1. KubeRay operator Helm 설치 (5분)
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm install kuberay-operator kuberay/kuberay-operator \
  --namespace kuberay-operator --create-namespace \
  --version 1.1.0

# 2. RayCluster 적용 (5분)
kubectl create namespace ray-demo
kubectl apply -n ray-demo -f manifests/00-kuberay-raycluster-toy.yaml
kubectl wait --for=condition=Ready pod \
  -l ray.io/cluster=raycluster-toy -n ray-demo --timeout=180s

# 3. ray status 로 head/worker 검증 (3분)
HEAD_POD=$(kubectl get pod -n ray-demo -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}')
kubectl exec -it -n ray-demo "$HEAD_POD" -- ray status

# 4. RayJob 실행 + 로그 (5분)
kubectl apply -n ray-demo -f manifests/01-kuberay-rayjob-toy.yaml
# 30~60초 대기 후
kubectl logs -n ray-demo -l ray.io/originated-from-cr-name=rayjob-toy --tail=20

# 5. Dashboard 접속 (5분)
kubectl -n ray-demo port-forward svc/raycluster-toy-head-svc 8265:8265 &
open http://localhost:8265

# 6. 정리 (5분)
kubectl delete -n ray-demo -f manifests/
helm uninstall kuberay-operator -n kuberay-operator
kubectl delete namespace ray-demo kuberay-operator
```

각 단계의 예상 출력은 [labs/README.md](./labs/README.md) 를 보세요.

### 2-3. RayJob 의 핵심 출력

Step 4 의 RayJob 이 출력하는 가장 중요한 부분입니다.

```
=== ray.cluster_resources() ===
{'CPU': 2.0, 'memory': 2849338819.0, ...
 'node:__internal_head__': 1.0,
 'node:10.244.0.5': 1.0,
 'node:10.244.0.6': 1.0,
 'node:10.244.0.7': 1.0}
=== ray.nodes() (count only) ===
node_count = 3
=== distributed map result ===
[0, 1, 4, 9, 16, 25, 36, 49]
```

핵심 관찰 — 학습자가 *반드시 인지해야 하는 3가지*.

1. **`'CPU': 2.0`** — head 의 `num-cpus: "0"` (task 스케줄에서 제외) + worker 2개의 limits CPU 1 합산. 이 값이 Ray scheduler 가 보는 *실제 사용 가능한 CPU* 입니다. K8s 의 `kubectl describe pod` 가 보는 limits 와 다릅니다.
2. **`node_count = 3`** — head 1 + worker 2. 매니페스트 `headGroupSpec.replicas` (암묵적으로 1) + `workerGroupSpecs[0].replicas` (2) 의 합. *Pod 수 = Ray 노드 수* 라는 1:1 관계.
3. **`[0, 1, 4, 9, 16, 25, 36, 49]`** — 8개 task (`square.remote(i) for i in range(8)`) 가 worker 2개에 *자동 분산* 되어 결과를 모았습니다. 학습자가 *어디로 갈지 지정하지 않았는데도* Ray scheduler 가 라운드로빈으로 배치한 결과 — 이게 Ray 추상화의 가치입니다.

---

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] KubeRay operator 설치 후 `kubectl get crd | grep ray.io` 가 `rayclusters.ray.io`, `rayjobs.ray.io`, `rayservices.ray.io` 3개를 모두 보여준다
- [ ] `kubectl get raycluster -n ray-demo` 가 STATUS=ready, AVAILABLE WORKERS=2 를 보여준다
- [ ] `kubectl exec ... -- ray status` 의 Active 항목에 head_group 1개 + small-workers 2개가 모두 ALIVE
- [ ] RayJob 의 JOB STATUS=SUCCEEDED 이고, 로그의 `ray.cluster_resources()` 결과에 `'CPU': 2.0` + `node_count == 3` 출력
- [ ] Ray Dashboard (`http://localhost:8265`) 의 Cluster 탭에서 3개 노드가 보이고 Jobs 탭에 `rayjob-toy` 가 SUCCEEDED 로 기록
- [ ] [labs/README.md 부록 B](./labs/README.md#부록-b--kuberay-vs-kubeflow-비교표-직접-채우기) 의 비교표 10개 행을 본인 언어로 채울 수 있다

---

## 4. 정리

```bash
# port-forward 백그라운드 종료
pkill -f 'kubectl.*port-forward.*raycluster-toy' 2>/dev/null

# RayJob → RayCluster 순서로 정리
kubectl delete -n ray-demo -f manifests/01-kuberay-rayjob-toy.yaml --ignore-not-found
kubectl delete -n ray-demo -f manifests/00-kuberay-raycluster-toy.yaml --ignore-not-found

# operator 와 워크로드 네임스페이스 정리
helm uninstall kuberay-operator -n kuberay-operator
kubectl delete namespace ray-demo kuberay-operator --ignore-not-found

# CRD 까지 완전 제거 (helm uninstall 만으로는 CRD 가 남음)
kubectl delete crd rayclusters.ray.io rayjobs.ray.io rayservices.ray.io --ignore-not-found

# minikube 자체를 끌 때 (캡스톤도 진행할 거면 생략)
# minikube stop
```

---

## 🚨 자주 하는 실수

1. **PyTorchJob 의 `cleanPodPolicy` 누락** — `runPolicy.cleanPodPolicy` 가 없으면 default 가 `None` 이라 *학습이 끝난 Pod 가 GPU limits 를 점유한 채 Completed 상태로 남습니다*. 다음 학습 Job 은 `0/1 nodes are available: insufficient nvidia.com/gpu` 로 무한 Pending. 비싼 GPU 환경에서는 사람이 자리 비운 사이 시간당 청구가 누적됩니다. 매니페스트 작성 시 *항상* `runPolicy.cleanPodPolicy: All` (또는 `OnFailure`) 한 줄을 답니다. KubeRay 의 RayJob 에서는 같은 자리에 `shutdownAfterJobFinishes: true` — 본 토픽 매니페스트 `01-kuberay-rayjob-toy.yaml` 은 학습 시연 목적으로 일부러 false 로 두었지만, 실 운영의 일회성 학습 잡에서는 true 가 기본값입니다.

2. **RayCluster `rayVersion` 과 컨테이너 이미지 태그 불일치** — 매니페스트 `spec.rayVersion: "2.9.0"` 인데 head/worker 의 image 가 `rayproject/ray:2.8.0` 처럼 다른 버전이면 GCS 핸드셰이크 시 *`Cluster version mismatch: head 2.9.0 / worker 2.8.0`* 메시지로 worker Pod 이 CrashLoopBackOff. 본 코스 매니페스트는 둘을 `2.9.0` 으로 명시했지만, 실 운영에서 `latest` 태그를 쓰면 어느 날 silent 로 mismatch 가 발생할 위험이 있습니다. *항상 명시적 버전 태그* 를 쓰고, 두 곳을 한 변수 (Helm value 또는 Kustomize patch) 로 묶는 패턴이 안전합니다.

3. **"KubeRay 는 학습용", "Kubeflow 는 추론용" 같은 흔한 오해** — 둘 다 학습/추론을 모두 다룹니다. KubeRay 는 RayService 로 추론, Kubeflow 는 KServe 와 결합해 추론. 본 토픽 [§1-4 선택 가이드](#1-4-선택-가이드--언제-무엇을-쓰는가) 의 진짜 분기점은 *추상화 수준 (라이브러리 vs 환경변수)* 과 *통합 도구 (HPO/RL/Serve 가 함께 들어 있나)* 입니다. 또 하나의 흔한 오해는 *"Kubeflow Training Operator 는 Kubeflow 전체를 깔아야 한다"* — 사실 Training Operator 만 standalone 으로 설치 가능 (`kubectl apply -k "github.com/kubeflow/training-operator/manifests/overlays/standalone?ref=v1.8.1"`). 본 토픽은 그조차 시간 부담이라 매니페스트 분석에 그쳤습니다.

---

## 더 알아보기

- [KubeRay 공식 문서](https://docs.ray.io/en/latest/cluster/kubernetes/index.html) — RayCluster / RayJob / RayService CRD 레퍼런스, autoscaling, GPU 노드 풀 설정
- [Ray Train 가이드](https://docs.ray.io/en/latest/train/train.html) — PyTorch / TF / HuggingFace 학습 코드를 RayJob entrypoint 로 wrap 하는 패턴
- [Kubeflow Training Operator GitHub](https://github.com/kubeflow/training-operator) — PyTorchJob / TFJob / MPIJob / XGBoostJob / PaddleJob 매니페스트 예제
- [PyTorch Distributed Overview](https://pytorch.org/tutorials/beginner/dist_overview.html) — `torch.distributed`, DDP, FSDP 의 라이브러리 측 이해
- [Megatron-LM on Ray (블로그)](https://www.anyscale.com/blog/training-175b-parameter-language-models-at-1000-gpu-scale-with-alpa-and-ray) — 본 토픽 §1-1 의 Tensor Parallel 이 실제로 어떻게 KubeRay 위에서 1000-GPU 스케일로 동작하는지
- [HuggingFace accelerate](https://huggingface.co/docs/accelerate/index) — DDP boilerplate 를 줄여 PyTorchJob 매니페스트와의 결합 비용을 낮추는 라이브러리

---

## 다음 챕터

➡️ [⭐ Capstone — RAG 챗봇 + LLM 서빙 종합 프로젝트](../../capstone-rag-llm-serving/) (작성 예정) — Phase 4 의 모든 도구 (GPU / KServe / vLLM / Argo) 를 통합해 *질문 → 검색 → LLM 답변 → 인용 문서* 의 RAG 시스템을 단일 클러스터에 구축합니다. 본 토픽 (분산 학습) 은 캡스톤의 *직접 구성요소는 아니지만*, 캡스톤 이후 *RAG 의 retrieval 정확도를 높이려고 임베딩 모델을 fine-tuning* 하는 단계에서 PyTorchJob + accelerate 가 가장 짧은 길입니다.
