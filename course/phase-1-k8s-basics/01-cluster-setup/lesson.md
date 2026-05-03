# minikube 설치와 첫 Pod

> **Phase**: 1 — Kubernetes 기본기
> **소요 시간**: 2–3시간 (minikube 첫 다운로드 시간 포함)
> **선수 학습**: [Phase 0 — Docker로 분류 모델 컨테이너화](../../phase-0-docker-review/01-docker-fastapi-model/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Kubernetes(쿠버네티스, K8s)가 Docker만으로는 해결하지 못하는 운영 문제(자동 복구·스케일·자원 한도)를 ML 워크로드 관점에서 설명합니다.
- WSL2 환경에서 minikube를 docker driver로 기동·정지·삭제합니다.
- kubectl이 클러스터에 접근하는 경로(`kubeconfig` → context → namespace)를 그림으로 설명하고 context를 전환합니다.
- YAML 매니페스트로 Pod(파드)를 선언·배포·삭제하고, 매니페스트 4영역(`apiVersion`/`kind`/`metadata`/`spec`)이 무엇인지 설명합니다.
- `kubectl get` / `describe` / `logs` / `exec` 4종 셋으로 Pod 상태를 진단합니다.

## 왜 ML 엔지니어에게 필요한가

Phase 0에서 만든 `sentiment-api:multi` 이미지를 호스트에서 `docker run -p 8000:8000`으로 띄우면 추론은 됩니다. 하지만 **운영 단계에서 곧 막힙니다**. 노드 1대가 죽으면 서비스가 통째로 꺼지고, 트래픽이 갑자기 10배가 되어도 자동으로 복제본을 늘릴 수 없으며, GPU 장비와 CPU 장비를 섞어 쓸 때 어느 컨테이너가 어디로 가야 할지 결정해 줄 사람이 없습니다. K8s는 "컨테이너를 어디서·몇 개로·어떤 자원을 주고·어떻게 외부에 노출할지"를 매니페스트로 선언하면 알아서 그 상태로 수렴시켜 주는 시스템입니다. 이 토픽에서는 K8s를 처음 띄워 보고, 가장 작은 배포 단위인 Pod 하나를 선언적으로 다루는 감각부터 익힙니다.

## 1. 핵심 개념

### 1-1. 클러스터·컨트롤 플레인·워커 노드

Kubernetes 클러스터는 "두뇌(컨트롤 플레인)"와 "근육(워커 노드)"로 나뉩니다.

```
┌─────────────────────────────────────────────────────┐
│                    클러스터                          │
│                                                     │
│   ┌─── Control Plane ───┐    ┌─ Worker Node(s) ─┐   │
│   │ kube-apiserver      │    │ kubelet           │  │
│   │ etcd (상태 저장소)   │    │ kube-proxy        │  │
│   │ kube-scheduler      │    │ container runtime │  │
│   │ controller-manager  │    │  └─ Pod ─ 컨테이너 │  │
│   └─────────────────────┘    └───────────────────┘   │
│                                                     │
└─────────────────────────────────────────────────────┘
                ▲
                │ kubectl (사용자가 클러스터와 대화하는 CLI)
```

- **Control Plane**은 "원하는 상태(desired state)"를 받아 클러스터를 그 상태로 맞춥니다. 학습자가 외울 필요는 없지만, 장애가 났을 때 어디를 보면 되는지 감을 잡아 두면 좋습니다.
- **Worker Node**는 실제로 Pod(컨테이너 묶음)을 실행하는 머신입니다. 한 대일 수도, 수백 대일 수도 있습니다.
- **kubectl**은 사용자가 컨트롤 플레인의 `kube-apiserver`와 대화하는 CLI입니다. 모든 명령은 `apiserver`로 향합니다.

> 💡 **팁**: ML 운영에서 "Pod이 안 뜬다"는 보통 (1) `apiserver`가 매니페스트를 거절했거나 (2) `scheduler`가 Pod을 배치할 노드를 못 찾았거나 (3) `kubelet`이 이미지를 못 받아왔기 때문입니다. 이 3단계를 머리에 두면 디버깅이 빨라집니다.

### 1-2. minikube가 단일 머신에서 클러스터를 흉내내는 방식

진짜 클러스터는 노드가 여러 대지만, 학습 환경에서는 한 머신에 클러스터 하나가 통째로 들어갑니다. minikube는 컨트롤 플레인과 워커 노드를 **하나의 컨테이너(또는 VM)** 안에 합쳐 띄워 줍니다.

| 드라이버 | 동작 방식 | 장점 | 단점 | 권장 환경 |
|---------|----------|------|------|---------|
| **docker** ⭐ | 도커 컨테이너 안에 K8s | 빠른 기동, WSL2 친화 | privileged 컨테이너 필요 | **WSL2 + Docker Desktop** |
| kvm2 | 리눅스 KVM 가상 머신 | 노드 격리 강함 | 리눅스만 가능, 무거움 | 리눅스 베어메탈 |
| hyperkit | macOS HyperKit VM | macOS 네이티브 | 구식, 점차 사라짐 | macOS (대안: docker) |
| none | 호스트에 직접 설치 | 가장 가벼움 | 호스트 오염 위험 | CI 컨테이너 안 |

이 챕터는 **WSL2 + docker driver**를 가정합니다. Docker Desktop의 WSL Integration이 켜져 있으면 minikube 명령은 그대로 작동합니다.

> 💡 **팁**: `kind`나 `k3d` 같은 다른 로컬 클러스터도 모두 같은 학습 목표를 달성할 수 있습니다. 명령 한두 줄만 다를 뿐 매니페스트와 kubectl 사용법은 100% 동일합니다.

### 1-3. kubectl ↔ kubeconfig ↔ context ↔ namespace

kubectl은 한 번에 여러 클러스터를 다룰 수 있어야 합니다. 이를 위해 다음 3단 구조를 씁니다.

```
~/.kube/config (kubeconfig 파일)
├── clusters:    [minikube, gke-prod, eks-staging, ...]
├── users:       [minikube, prod-admin, dev-readonly, ...]
└── contexts:    [minikube=cluster:minikube + user:minikube + namespace:default]
                  ↑ kubectl이 매번 어떤 클러스터/유저/namespace로 갈지 정하는 묶음
```

- **kubeconfig**: 위 3가지(클러스터·유저·context)를 담는 YAML 파일. 기본 위치는 `~/.kube/config`.
- **context**: "어느 클러스터에, 어느 유저로, 어느 namespace를 기본으로 쓸지"를 묶은 단위.
- **namespace**: 한 클러스터 안의 가상 분리 공간. 기본값은 `default`. Phase 2에서 `dev`/`staging`/`prod`로 분리합니다.

현재 context는 `kubectl config current-context`로 확인합니다. 회사 클러스터 context가 활성화된 채로 minikube 실습을 시작하면 명령이 회사 클러스터로 날아갑니다. **자주 하는 실수 3번**으로 다시 다룹니다.

### 1-4. Pod = K8s의 최소 배포 단위

K8s는 컨테이너를 직접 다루지 않고 **Pod이라는 한 단계 위 단위**를 다룹니다. Pod은 컨테이너 1개 이상을 담는 껍데기이며, 같은 Pod 안의 컨테이너들은 **네트워크와 저장소를 공유**합니다.

- 입문 단계에서는 **1 Pod = 1 컨테이너** 권장. (사이드카·init container는 Phase 2 이후에 등장합니다.)
- Pod 단독으로는 거의 쓰지 않습니다. 보통 ReplicaSet/Deployment가 Pod을 만듭니다 (다음 토픽). 이 토픽에서는 학습 목적상 Pod을 직접 만들어 봅니다.

매니페스트 4영역:

```yaml
apiVersion: v1                # 어떤 API 버전인지 (Pod은 core/v1)
kind: Pod                     # 어떤 종류의 리소스인지
metadata:                     # 이름·label 등 식별 정보
  name: first-pod
  labels:
    app: first-pod
spec:                         # "어떤 상태였으면 좋겠다"를 선언적으로 적는 곳
  containers:
    - name: hello
      image: python:3.12-slim
      command: ["sh", "-c", "echo hello && sleep 3600"]
```

`apply`를 하면 K8s는 **현재 상태와 spec을 비교해 차이를 메우는** 방식으로 동작합니다. 이걸 **선언적(declarative)** 운영이라고 부르며, "내가 절차를 일일이 적는다"는 명령형 방식과 대비됩니다.

## 2. 실습

상세 단계는 [labs/README.md](labs/README.md)를 따라갑니다. 여기서는 핵심 흐름만 짚습니다.

### 2-1. 사전 준비

```bash
docker --version            # 24.0+
kubectl version --client    # v1.28+
minikube version            # v1.32+
```

세 도구가 모두 설치되어 있어야 합니다. 설치가 안 되어 있다면 [labs/README.md 0단계](labs/README.md)의 안내를 먼저 보고 옵니다.

### 2-2. 클러스터 기동과 첫 Pod 배포

```bash
# 1. minikube 기동 (첫 실행 시 K8s 노드 이미지 다운로드로 3–5분)
minikube start --driver=docker --memory=4g --cpus=2

# 2. 클러스터 상태 확인
kubectl get nodes -o wide

# 3. 첫 Pod 배포
kubectl apply -f manifests/first-pod.yaml

# 4. Pod이 Running이 되는 과정을 실시간 관찰
kubectl get pods -w
```

### 2-3. 매니페스트 핵심 부분

```yaml
# manifests/first-pod.yaml 발췌
spec:
  containers:
    - name: hello
      image: python:3.12-slim                  # 가벼운 이미지로 Pod 라이프사이클만 학습
      command: ["sh", "-c"]                    # K8s에서 command는 Dockerfile의 ENTRYPOINT를 덮어씁니다
      args:
        - |
          echo "[ML] hello from K8s — Phase 1 / 01-cluster-setup";
          sleep 3600                            # 컨테이너를 살려둬야 logs/exec 실습이 가능합니다
      resources:
        requests:                               # 입문이라도 requests/limits는 빼지 않습니다
          cpu: "50m"
          memory: "64Mi"
        limits:
          cpu: "200m"
          memory: "128Mi"
```

> 💡 **팁**: `python:3.12-slim`을 쓰는 이유는 Phase 0의 `sentiment-api` 이미지가 첫 기동 시 모델을 받느라 느리고 메모리도 많이 먹기 때문입니다. 04-serve-classification-model 토픽에서 이 자리를 sentiment-api로 교체합니다.

### 2-4. Pod 진단 4종 셋

```bash
kubectl get pod first-pod                                        # 한 줄 상태
kubectl describe pod first-pod                                   # 상세 + Events
kubectl logs first-pod                                           # 컨테이너 stdout
kubectl exec -it first-pod -- sh                                 # 컨테이너 진입 (exit로 빠져나오기)
```

**예상 출력 (`kubectl logs first-pod`):**

```
[ML] hello from K8s — Phase 1 / 01-cluster-setup
[ML] 이 자리는 04-serve-classification-model에서 sentiment-api 컨테이너로 교체됩니다.
```

이 4종 셋은 Phase 4까지 진단의 90% 이상을 차지합니다. 손에 익혀 두면 좋습니다.

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `minikube status`가 6개 컴포넌트 모두 `Running`을 보입니다.
- [ ] `kubectl get nodes`가 `STATUS=Ready`인 노드 1개를 보여줍니다.
- [ ] `kubectl config current-context`가 `minikube`를 가리킵니다.
- [ ] `kubectl get pod first-pod`이 `STATUS=Running`, `READY=1/1`을 보입니다.
- [ ] `kubectl logs first-pod`이 위 예상 출력의 `[ML] ...` 두 줄을 보여줍니다.
- [ ] `kubectl exec -it first-pod -- sh` 안에서 `python --version`이 `Python 3.12.x`를 보입니다.

## 4. 정리

```bash
# Pod 삭제. 매니페스트 자체를 그대로 다시 쓸 수 있도록 -f로 삭제하는 습관을 들입니다.
kubectl delete -f manifests/first-pod.yaml

# minikube는 다음 토픽에서도 그대로 쓰므로 stop만 합니다 (delete 아님).
minikube stop
```

`minikube delete`는 Phase 1을 모두 마친 뒤에 합니다. 그래야 컨텍스트와 캐시가 유지되어 다음 실습이 빨라집니다.

## 🚨 자주 하는 실수

1. **Docker Desktop의 WSL Integration이 꺼져 있어서 `Cannot connect to the Docker daemon` 발생** — Docker Desktop → Settings → Resources → WSL Integration에서 사용하는 WSL 배포판을 켭니다. 끈 채로 `minikube start --driver=docker`를 돌리면 minikube는 컨테이너를 만들 곳이 없어 시작에 실패합니다.
2. **이전에 다른 드라이버로 만든 minikube 프로파일이 남아 `--driver=docker` 시작 실패** — `Existing "minikube" cluster was created using a different driver` 경고가 보이면 `minikube delete` 후 다시 `minikube start --driver=docker`로 시작합니다. 학습용이라 안에 있는 데이터는 잃어도 안전합니다.
3. **kubectl이 회사·과거 클러스터 context를 가리켜 minikube가 안 잡힘** — 사내 클러스터를 쓰던 머신이라면 `kubectl config current-context`가 `gke-prod` 같은 다른 값을 보입니다. minikube 기동 후에도 자동으로 바뀌지 않으면 `kubectl config use-context minikube`를 실행합니다. **사내 클러스터에 실수로 학습용 Pod을 띄우는 사고를 막는 습관**을 처음부터 들이는 것이 좋습니다.

## 더 알아보기

- [Kubernetes — Concepts: Cluster Architecture](https://kubernetes.io/docs/concepts/architecture/)
- [Kubernetes — Configure Access to Multiple Clusters](https://kubernetes.io/docs/tasks/access-application-cluster/configure-access-multiple-clusters/)
- [minikube — Drivers](https://minikube.sigs.k8s.io/docs/drivers/)
- [Kubernetes — Pods](https://kubernetes.io/docs/concepts/workloads/pods/)

## 다음 챕터

➡️ [Phase 1 / 02-pod-deployment — Pod / ReplicaSet / Deployment](../02-pod-deployment/lesson.md)
