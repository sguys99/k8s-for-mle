# Phase 4 / 05 — manifests 색인

본 토픽은 KubeRay 와 Kubeflow Training Operator 의 *디자인 차이* 를 비교하는 자리입니다. minikube CPU 환경의 부담을 줄이기 위해 **KubeRay 만 실행**, **Kubeflow PyTorchJob 은 분석 전용** 으로 분리했습니다.

## 매니페스트 목록

| 파일 | 실행 여부 | 핵심 내용 |
|------|----------|----------|
| [00-kuberay-raycluster-toy.yaml](./00-kuberay-raycluster-toy.yaml) | ✅ 실행 | RayCluster CRD, head 1 + worker 2 (모두 CPU). dashboard/GCS/client 포트 노출, autoscaling 비활성. |
| [01-kuberay-rayjob-toy.yaml](./01-kuberay-rayjob-toy.yaml) | ✅ 실행 | RayJob CRD, 위 RayCluster 를 `clusterSelector` 로 재사용. `ray.cluster_resources()` 와 `@ray.remote` 데코레이터 호출이 분산 실행되는지 확인. |
| [10-kubeflow-pytorchjob-toy.yaml](./10-kubeflow-pytorchjob-toy.yaml) | ❌ 분석 전용 | Kubeflow Training Operator 의 PyTorchJob CRD. Master 1 + Worker 2 = `WORLD_SIZE=3`, `cleanPodPolicy: All`. 본 토픽에서는 *코드만 비교*, 실행하지 않음. |

번호 규칙: **00–09 = KubeRay (실행 가능)**, **10–19 = Kubeflow Training Operator (분석 전용)**. 학습자가 한눈에 두 묶음을 구분하기 위함입니다.

## 사전 작업 — KubeRay operator 설치

00, 01 매니페스트는 KubeRay operator 가 클러스터에 등록한 RayCluster·RayJob CRD 가 있어야 동작합니다. 자세한 절차는 [labs/README.md Step 1](../labs/README.md#step-1--kuberay-operator-helm-설치) 참고.

```bash
helm repo add kuberay https://ray-project.github.io/kuberay-helm/
helm repo update
helm install kuberay-operator kuberay/kuberay-operator \
  --namespace kuberay-operator --create-namespace \
  --version 1.1.0
```

CRD 등록 확인:

```bash
kubectl get crd | grep ray.io
# 예상 출력:
# rayclusters.ray.io                           2026-05-05T...
# rayjobs.ray.io                               2026-05-05T...
# rayservices.ray.io                           2026-05-05T...
```

## 사전 작업 — namespace 생성

00, 01 매니페스트는 `ray-demo` 네임스페이스를 가정합니다. operator 자체와 분리해 두면 권한·정리 범위가 명확합니다.

```bash
kubectl create namespace ray-demo
```

## 적용 / 정리 한 줄 명령

```bash
# 적용
kubectl apply -n ray-demo -f manifests/00-kuberay-raycluster-toy.yaml
kubectl wait --for=condition=Ready pod -l ray.io/cluster=raycluster-toy -n ray-demo --timeout=180s
kubectl apply -n ray-demo -f manifests/01-kuberay-rayjob-toy.yaml

# 정리
kubectl delete -n ray-demo -f manifests/01-kuberay-rayjob-toy.yaml --ignore-not-found
kubectl delete -n ray-demo -f manifests/00-kuberay-raycluster-toy.yaml --ignore-not-found
helm uninstall kuberay-operator -n kuberay-operator
kubectl delete namespace ray-demo kuberay-operator --ignore-not-found
```

## 분석 전용 매니페스트의 사용법

`10-kubeflow-pytorchjob-toy.yaml` 은 `kubectl apply` 하지 않습니다. 대신:

1. [lesson.md §1-3 Kubeflow Training Operator](../lesson.md#1-3-kubeflow-training-operator--pytorchjobtfjobmpijob-crd) 를 읽으면서 매니페스트의 각 필드가 어떤 자동화에 대응하는지 확인합니다.
2. [labs/README.md 부록 A](../labs/README.md#부록-a--pytorchjob-매니페스트-라인별-분석) 의 표를 보며 KubeRay 매니페스트와 한 줄씩 비교합니다.

이 분석 전용 패턴은 본 코스의 다른 토픽 (예: 01-gpu-on-k8s 의 `sentiment-gpu-mistake.yaml`, 03-vllm-llm-serving 의 `vllm-mistake-cpu-only.yaml`) 과 같은 의도 — *실행하지 않고 매니페스트만 비교* — 입니다.

## 막힐 때

| 증상 | 원인 / 해결 |
|------|------------|
| `kubectl apply` 가 `no matches for kind "RayCluster" in version "ray.io/v1"` | KubeRay operator 가 아직 설치되지 않음. 위 사전 작업 (Helm 설치) 을 먼저 수행. |
| RayCluster head Pod 가 *Pending* 에서 멈춤 | 노드 자원 부족. `kubectl describe pod -n ray-demo <head-pod>` 로 `0/1 nodes are available: insufficient cpu/memory` 확인. minikube 를 `--cpus=4 --memory=8g` 로 재기동. |
| RayJob 이 즉시 *Failed* | `clusterSelector` 가 가리키는 RayCluster 가 Ready 가 아님. `kubectl get raycluster -n ray-demo` 로 STATUS=ready 확인 후 다시 적용. |
| `kubectl apply -f 10-kubeflow-pytorchjob-toy.yaml` 실수로 실행 후 `no matches for kind "PyTorchJob"` | 정상 — 본 매니페스트는 분석 전용이라 Training Operator 미설치 상태가 의도된 결과. |
