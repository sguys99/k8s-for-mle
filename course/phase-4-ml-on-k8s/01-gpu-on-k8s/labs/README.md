# Phase 4 / 01 — 실습 가이드 (GPU on Kubernetes)

> [lesson.md](../lesson.md) 의 1–4 절 개념을 실제 클러스터에 적용해, K8s 의 GPU 자원 노출 / 요청 / 격리 메커니즘을 직접 검증합니다. 본 lab 은 학습자의 환경에 따라 *이중 트랙* 으로 분기합니다.
>
> **Track A — minikube 모의 (Step 0–5)**: GPU 가 없는 환경. 매니페스트 dry-run / Pending 시연 / Phase 1 deployment 와의 diff 학습이 핵심. 누구나 바로 시작 가능.
>
> **Track B — GKE 실전 (Step 0–9)**: GCP 크레딧이 있거나 로컬 NVIDIA GPU 가 있는 환경. 실제 nvidia-smi / 모델 GPU 추론 / Time-slicing 까지 포함. 마지막 단계 (클러스터 삭제) 가 *가장 중요* — 잔존 시 비용 청구 지속.
>
> **소요 시간**: Track A 30–40분 / Track B 70–90분 (클러스터 생성 5–8분 + 실습 + 삭제 5분 포함)

## 작업 디렉토리

본 lab 의 명령은 모두 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-4-ml-on-k8s/01-gpu-on-k8s
```

상대경로 `manifests/...` 와 `../../phase-1-k8s-basics/...` / `../../phase-2-operations/...` 가 그대로 동작합니다.

## 트랙 선택

먼저 자신이 어느 트랙으로 갈지 정합니다.

```bash
# 로컬 GPU 가 있는지 — 둘 중 하나라도 출력되면 Track B (로컬) 가능
nvidia-smi 2>/dev/null && echo "[로컬 GPU 있음 → Track B 가능]" || echo "[로컬 GPU 없음]"

# GCP 인증이 되어 있고 사용 가능한 프로젝트가 있는지 — Track B (GKE) 가능
gcloud config get-value project 2>/dev/null && echo "[GCP 인증 OK → Track B (GKE) 가능]" || echo "[GCP 미설정]"

# 둘 다 안 되면 Track A 만 가능 — 그것으로 충분히 핵심 학습 가능
```

> 💡 Track A 만 진행해도 본 토픽의 학습 목표 1–4 중 1, 2, 3 은 모두 달성합니다. 4 (MIG / Time-slicing 의 *실 적용*) 는 Track B 의 옵션 단계 (Step 7) 에서만 가능하지만, 개념 자체는 [lesson.md 1-4 절](../lesson.md#1-4-gpu-공유-전략--mig-vs-time-slicing-vs-mps) 로 충분히 다룹니다.

---

# Track A — minikube 모의 (Step 0–5)

## A-Step 0. 사전 점검

Phase 1 부터 살아있던 minikube 와, Phase 2/05 가 만든 dev / prod namespace 를 확인합니다.

```bash
# minikube 상태
minikube status

# Phase 2/05 의 dev / prod namespace + ResourceQuota 잔존 확인
kubectl get ns dev prod 2>/dev/null
kubectl get quota -n dev
```

**예상 출력**:

```
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured

NAME   STATUS   AGE
dev    Active   ...
prod   Active   ...

NAME        AGE   REQUEST                                                                                                  LIMIT
dev-quota   ...   count/configmaps: 0/10,count/cronjobs.batch: 0/5,...,requests.nvidia.com/gpu: 0/1,requests.storage: ...
```

✅ **확인 포인트**: `requests.nvidia.com/gpu: 0/1` — Phase 2/05 가 quota 에 GPU 자원을 등록해두었지만 used 가 *항상 0* 입니다 (minikube 에 GPU 가 없으므로). 본 토픽이 Track B 까지 가야 used 가 0 → 1 로 채워집니다.

> 💡 Phase 2/05 가 정리되어 namespace 가 없어도 본 lab 은 진행 가능합니다 — Step 0 의 dev quota 확인만 건너뛰면 됩니다.

---

## A-Step 1. GPU 자원이 *정의 가능한지* / *노드에 등록되어 있는지* 확인

GPU 가 없는 minikube 환경이라도, K8s 의 자원 모델 자체는 `nvidia.com/gpu` 를 limits 키로 *허용* 합니다. 이걸 직접 보입니다.

```bash
# pod.spec.containers.resources 의 schema 확인
kubectl explain pod.spec.containers.resources.limits

# 노드 capacity 에 GPU 키가 *없음* 확인 (있어야 정상이 아님 — minikube 는 GPU 없음)
kubectl get node minikube -o jsonpath='{.status.capacity}' | python3 -m json.tool
echo
echo "── 위 출력에 nvidia.com/gpu 키가 있는가? ──"
kubectl get node minikube -o jsonpath='{.status.capacity.nvidia\.com/gpu}'; echo "(빈 줄이면 없음)"
```

**예상 출력**:

```
KIND:   Pod
VERSION: v1

FIELD: limits <map[string]Quantity>

DESCRIPTION:
  Limits describes the maximum amount of compute resources allowed.
  ...

{
    "cpu": "2",
    "ephemeral-storage": "...",
    "memory": "...",
    "pods": "110"
}

── 위 출력에 nvidia.com/gpu 키가 있는가? ──
(빈 줄이면 없음)
```

✅ **설명**: `kubectl explain` 의 `limits <map[string]Quantity>` 가 핵심 — *임의의 자원 키* 가 들어갈 수 있다는 뜻이고, `nvidia.com/gpu` 도 그 중 하나일 뿐입니다. 노드 capacity 에 키가 *없는* 것이 GPU 없는 환경의 정상 상태입니다.

> 💡 (참고) Track B 의 GKE GPU 노드에서 같은 명령을 돌리면 `"nvidia.com/gpu": "1"` 이 capacity 에 추가로 보입니다. NVIDIA Device Plugin 이 등록한 결과 — [lesson.md 1-1 절](../lesson.md#1-1-nvidia-device-plugin--gpu-가-k8s-자원이-되는-길) 의 다이어그램이 이 결과를 만든 것입니다.

---

## A-Step 2. 안티패턴 시연 — sentiment-gpu-mistake.yaml apply → Pending → 회수

본 단계가 Track A 의 *가장 핵심* 입니다. [sentiment-gpu-mistake.yaml](../manifests/sentiment-gpu-mistake.yaml) 은 자주 하는 실수 3 가지 (requests 누락 + nodeSelector 누락 + tolerations 누락) 를 응축한 안티패턴이고, 적용하면 *영구 Pending* 됩니다.

```bash
# 1) 적용
kubectl apply -f manifests/sentiment-gpu-mistake.yaml

# 2) Pod 가 Pending 상태로 떴는지
kubectl get pod -l app=sentiment-api-mistake

# 3) Pending 사유 — events 의 마지막 메시지에 schedule 실패 사유가 보임
POD=$(kubectl get pod -l app=sentiment-api-mistake -o jsonpath='{.items[0].metadata.name}')
kubectl describe pod $POD | tail -20
```

**예상 출력**:

```
deployment.apps/sentiment-api-gpu-mistake created

NAME                                          READY   STATUS    RESTARTS   AGE
sentiment-api-gpu-mistake-7c8d9f-abcde        0/1     Pending   0          5s

...
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  10s   default-scheduler  0/1 nodes are available: 1 Insufficient nvidia.com/gpu. preemption: 0/1 nodes are available: 1 No preemption victims found for incoming pod.
```

✅ **설명**: minikube 노드에 `nvidia.com/gpu` capacity 가 *없으므로* `Insufficient nvidia.com/gpu` 메시지로 거절. Track B (GKE) 에서는 같은 매니페스트가 `node(s) had untolerated taint {nvidia.com/gpu: present}` 메시지로 거절됩니다 — 노드는 GPU 가 있지만 toleration 이 없어서.

이제 즉시 회수합니다.

```bash
kubectl delete -f manifests/sentiment-gpu-mistake.yaml

# 잔존 검증
kubectl get all -l phase-4-01=mistake-must-be-deleted -A
```

**예상 출력**:

```
deployment.apps "sentiment-api-gpu-mistake" deleted
No resources found
```

✅ **설명**: Pending Pod 누적은 etcd 부담을 키우므로 *반드시 회수*. 본 토픽 끝까지 mistake 매니페스트가 살아있으면 안 됩니다.

> ⚠ 만약 위 events 메시지에 `Insufficient nvidia.com/gpu` 가 *아닌* 다른 메시지가 보인다면 (예: `Insufficient cpu`, `Insufficient memory`) 이는 minikube 노드의 *다른 자원* 이 부족하다는 뜻입니다. `minikube config set memory 4096 && minikube delete && minikube start` 로 메모리를 늘려 재시도하세요.

---

## A-Step 3. 정상 매니페스트의 dry-run 검증

[sentiment-gpu-deployment.yaml](../manifests/sentiment-gpu-deployment.yaml) 이 *문법적으로* 올바른지를 apply 하지 않고 검증합니다. Track A 에서는 apply 해도 Pending 으로 끝나므로 dry-run 까지만.

```bash
# client-side dry-run (단순 yaml 문법 검사)
kubectl apply --dry-run=client -f manifests/sentiment-gpu-deployment.yaml

# server-side dry-run (admission 까지 거쳐 실제 schema 검증)
kubectl apply --dry-run=server -f manifests/sentiment-gpu-deployment.yaml
```

**예상 출력**:

```
deployment.apps/sentiment-api-gpu created (dry run)
deployment.apps/sentiment-api-gpu created (server dry run)
```

✅ **설명**: 두 dry-run 이 모두 통과 — `nvidia.com/gpu: 1` requests/limits + nodeSelector + tolerations 모두 K8s 가 *문법적으로* 받아들였다는 뜻. 실제 schedule 까지는 GPU 노드가 있어야 하지만 (Track B 에서 검증), 매니페스트 자체는 정상.

추가로 `kubectl explain` 로 nodeSelector / tolerations 의 schema 도 확인.

```bash
kubectl explain deployment.spec.template.spec.nodeSelector
kubectl explain deployment.spec.template.spec.tolerations
```

✅ **설명**: 두 명령 모두 schema 설명을 출력. nodeSelector 는 `<map[string]string>`, tolerations 는 `<[]Toleration>` 으로 정의되어 있어 본 매니페스트의 구조와 일치.

---

## A-Step 4. Phase 1/04 deployment 와의 *4-군데 diff* 학습

본 토픽의 학습 핵심은 *Phase 1 의 sentiment-api 가 GPU 버전으로 옮겨갈 때 정확히 어떤 줄이 추가되는가* 입니다. diff 로 직접 봅니다.

```bash
diff -u \
    ../../phase-1-k8s-basics/04-serve-classification-model/manifests/deployment.yaml \
    manifests/sentiment-gpu-deployment.yaml \
    | head -80
```

**예상 출력 (요약 — 4 군데 추가 부분만 발췌)**:

```
+        - name: CUDA_VISIBLE_DEVICES
+          value: "0"
...
+            nvidia.com/gpu: 1
...
+            nvidia.com/gpu: 1
...
+      nodeSelector:
+        cloud.google.com/gke-accelerator: nvidia-tesla-t4
+      tolerations:
+        - key: nvidia.com/gpu
+          operator: Exists
+          effect: NoSchedule
```

✅ **설명**: 4 군데 추가만으로 같은 이미지 (`sentiment-api:v1`) 가 GPU 위에서도 동작합니다. transformers 라이브러리가 컨테이너 안에서 `torch.cuda.is_available()` 가 True 인지 확인 후 자동으로 device 를 고릅니다. 즉 *애플리케이션 코드는 변경 없고, K8s 매니페스트만 4 군데 추가* — 이게 K8s 가 ML 인프라의 표준이 된 핵심 이유.

> 💡 운영 코드에서는 `CUDA_VISIBLE_DEVICES` 를 명시하지 않아도 K8s 가 자동으로 *Pod 가 받은 GPU 의 인덱스* 를 컨테이너에 노출합니다. 본 토픽에서 명시한 이유는 *어떤 GPU 가 보이는지를 코드에서 명시적으로 알 수 있게* 하기 위함 — 디버깅 / 멀티 GPU 환경에서 유용.

---

## A-Step 5. 정리

Track A 는 *별도 정리할 자원이 거의 없음* — Step 2 의 mistake 가 이미 회수되었고, Step 3 의 dry-run 은 실제 자원을 만들지 않았습니다.

```bash
# (1) mistake 잔존 0 건 재확인
kubectl get deployment -l phase-4-01=mistake-must-be-deleted -A

# (2) minikube 는 보존 — Phase 4/02 KServe 가 그대로 사용
minikube status

# (3) (선택) Phase 2/05 의 dev / prod namespace 도 보존 — Track B Step 8 에서 사용
kubectl get ns dev prod
```

**예상 출력**:

```
No resources found
minikube
type: Control Plane
host: Running
...
NAME    STATUS   AGE
dev     Active   ...
prod    Active   ...
```

✅ **Track A 완료**. Track B 도 진행한다면 다음 섹션으로 이동. Track A 만 진행한 학습자는 *학습 목표 1–3* 을 모두 달성했고, 4 (MIG / Time-slicing 실 적용) 는 [lesson.md 1-4 절](../lesson.md#1-4-gpu-공유-전략--mig-vs-time-slicing-vs-mps) 로 개념 학습이 완료된 상태로 마무리합니다.

---

# Track B — GKE 실전 (Step 0–9)

> 🚨 **비용 안내**: 본 트랙은 GKE 클러스터 + Spot T4 GPU 노드 풀을 생성합니다. 1시간당 약 $0.5 (control plane $0.10 + Spot T4 ~$0.35 + 노드 호스트 비용) 가 청구됩니다. **Step 9 의 클러스터 삭제를 반드시 수행** 해야 합니다. 잊으면 24 시간 ~$10, 1주일 ~$70 청구.

## B-Step 0. gcloud 인증 + 프로젝트 / 비용 확인

```bash
# 인증 상태
gcloud auth list

# 현재 프로젝트
gcloud config get-value project

# 현재 활성 프로젝트의 결제 계정 연결 확인 (없으면 클러스터 생성 불가)
gcloud beta billing projects describe $(gcloud config get-value project) 2>/dev/null \
    || echo "[⚠ 결제 계정 미연결 — GCP 콘솔에서 연결 후 재시도]"
```

**예상 출력**:

```
       Credentialed Accounts
ACTIVE  ACCOUNT
*       you@example.com

your-project-id

billingAccountName: billingAccounts/...
billingEnabled: true
```

✅ **확인 포인트**: ACTIVE 가 ★ 표시 + `billingEnabled: true`. 둘 중 하나라도 안 되면 다음 단계 불가.

---

## B-Step 1. GKE 클러스터 + GPU 노드 풀 생성

GKE Autopilot 도 GPU 를 지원하지만, *학습 목적* (Device Plugin DaemonSet 이 보임 / taint 가 보임) 에는 Standard 클러스터가 더 적합합니다.

```bash
# 변수 (자기 환경에 맞게 변경)
export ZONE=us-central1-c            # T4 가용성이 가장 좋은 zone 중 하나
export CLUSTER_NAME=k8s-ml-gpu-lab
export PROJECT=$(gcloud config get-value project)

# 1) 클러스터 생성 — control plane + 작은 시스템 노드 풀 (e2-small × 1)
gcloud container clusters create $CLUSTER_NAME \
    --zone=$ZONE \
    --num-nodes=1 \
    --machine-type=e2-small \
    --release-channel=regular \
    --no-enable-master-authorized-networks

# 2) GPU 노드 풀 추가 — Spot T4 1 장
gcloud container node-pools create gpu-pool \
    --cluster=$CLUSTER_NAME \
    --zone=$ZONE \
    --num-nodes=1 \
    --machine-type=n1-standard-4 \
    --accelerator=type=nvidia-tesla-t4,count=1,gpu-driver-version=DEFAULT \
    --spot \
    --node-taints=nvidia.com/gpu=present:NoSchedule

# 3) kubeconfig 갱신
gcloud container clusters get-credentials $CLUSTER_NAME --zone=$ZONE
```

**예상 출력 (요약)**:

```
Creating cluster k8s-ml-gpu-lab in us-central1-c... done.
kubeconfig entry generated for k8s-ml-gpu-lab.

Creating node pool gpu-pool... done.

Fetching cluster endpoint and auth data.
kubeconfig entry generated for k8s-ml-gpu-lab.
```

✅ **확인 포인트**: 두 명령 모두 `done` 으로 끝남. 소요 시간 5–8분.

> 💡 `--gpu-driver-version=DEFAULT` 는 GKE 가 NVIDIA 드라이버 + Container Toolkit 을 자동 설치하라는 옵션. 이 옵션이 *없으면* 노드는 만들어지지만 Device Plugin 이 정상 동작하지 않습니다 (자주 하는 실수 1번 시나리오).

---

## B-Step 2. NVIDIA Device Plugin DaemonSet 자동 설치 확인

```bash
# kube-system 의 nvidia 관련 DaemonSet
kubectl get ds -n kube-system | grep -i nvidia

# DaemonSet 의 Pod 가 GPU 노드에 떠있는지
kubectl get pod -n kube-system -l k8s-app=nvidia-gpu-device-plugin -o wide
```

**예상 출력**:

```
NAME                                         DESIRED   CURRENT   READY   ...   AGE
nvidia-gpu-device-plugin-large-cos           1         1         1       ...   2m
nvidia-gpu-device-plugin-medium-cos          1         1         1       ...   2m
nvidia-gpu-device-plugin-small-cos           1         1         1       ...   2m

NAME                                                READY   STATUS    NODE
nvidia-gpu-device-plugin-large-cos-xxxxx            1/1     Running   gke-...-gpu-pool-...
```

✅ **설명**: GKE 가 Device Plugin DaemonSet 을 GPU 노드에 자동 배치 (lesson 1-1 절의 다이어그램이 *지금 살아있음*). DaemonSet 이름이 `large-cos` / `medium-cos` 등으로 분리된 이유는 GKE 가 노드 머신 타입에 따라 다른 변종을 띄우기 때문 — 본 lab 에서는 *Running 인 Pod 1 개만 있으면 OK*.

---

## B-Step 3. 노드 capacity 의 nvidia.com/gpu 등록 확인

```bash
# GPU 노드 식별
GPU_NODE=$(kubectl get nodes -l cloud.google.com/gke-accelerator=nvidia-tesla-t4 -o jsonpath='{.items[0].metadata.name}')
echo "GPU node: $GPU_NODE"

# capacity / allocatable
kubectl describe node $GPU_NODE | grep -A2 -E '^Capacity:|^Allocatable:'

# taint 확인
kubectl describe node $GPU_NODE | grep -A2 Taints
```

**예상 출력**:

```
GPU node: gke-k8s-ml-gpu-lab-gpu-pool-abcd1234-xxxx

Capacity:
  cpu:                4
  ephemeral-storage:  ...
  memory:             ...
  nvidia.com/gpu:     1
Allocatable:
  cpu:                3920m
  ephemeral-storage:  ...
  memory:             ...
  nvidia.com/gpu:     1

Taints:             nvidia.com/gpu=present:NoSchedule
```

✅ **설명**: 두 가지가 핵심.
- `Capacity.nvidia.com/gpu: 1` — Device Plugin 이 GPU 1 장을 K8s 자원으로 노출 (lesson 1-1 절의 결과).
- `Taints: nvidia.com/gpu=present:NoSchedule` — 일반 워크로드가 들어오지 못하도록 자동 격리 (lesson 1-3 절).

이게 sentiment-gpu-deployment.yaml 의 nodeSelector + toleration *5–6 줄* 이 정확히 매칭되어야 하는 이유입니다.

---

## B-Step 4. gpu-smoke-pod.yaml — nvidia-smi 로 1차 검증

본격적인 모델 추론 전, GPU 가 정말로 컨테이너 안에서 보이는지 1 분 안에 확인합니다.

```bash
kubectl apply -f manifests/gpu-smoke-pod.yaml

# Pod 가 Running → Completed 로 가는 흐름 (nvidia-smi 한 번 출력 후 종료가 정상)
kubectl get pod gpu-smoke -w  &
sleep 30 && kill %1 2>/dev/null

# logs 로 nvidia-smi 출력 확인
kubectl logs gpu-smoke
```

**예상 출력 (logs 부분)**:

```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI 535.xx.xx    Driver Version: 535.xx.xx    CUDA Version: 12.2    |
|-------------------------------+----------------------+----------------------+
| GPU  Name           ...        | Bus-Id        Disp.A | Volatile Uncorr. ECC |
|     ...                         ...                    ...                   |
+===============================+======================+======================+
|   0  Tesla T4         Off      | 00000000:00:04.0 Off |                    0 |
| N/A   45C    P8     9W /  70W  |      0MiB / 15360MiB |      0%      Default |
+-------------------------------+----------------------+----------------------+
                                                                               
+-----------------------------------------------------------------------------+
| Processes:                                                                  |
|  GPU   GI   CI        PID   Type   Process name                  GPU Memory |
|        ID   ID                                                   Usage      |
|=============================================================================|
|  No running processes found                                                 |
+-----------------------------------------------------------------------------+
```

✅ **설명**: T4 카드 / 15360MiB 메모리 / 0MiB 사용 중 / 드라이버 535.xx 가 정상 출력. 본 출력이 보이면 Device Plugin + Container Toolkit + 드라이버 *세 컴포넌트가 모두 정상* (lesson 자주 하는 실수 1번이 *해당 안 됨*).

검증 끝났으니 즉시 정리:

```bash
kubectl delete pod gpu-smoke
```

**예상 출력**: `pod "gpu-smoke" deleted`

---

## B-Step 5. (선택) sentiment-api 모델을 GPU 에 올려 추론

본 단계는 *sentiment-api:v1 이미지를 Artifact Registry 에 push 한 뒤* 만 가능합니다. 본 코스 흐름은 *추론 자체는 Phase 4/02 KServe / 03 vLLM 에서 다루므로* 이 단계는 옵션입니다. 빠르게 GPU 추론을 보고 싶다면 다음 흐름:

```bash
# (사전) Artifact Registry 에 push (예시 — 자기 프로젝트 / repo 에 맞게 변경)
# gcloud artifacts repositories create ml-images --repository-format=docker --location=us-central1
# docker tag sentiment-api:v1 us-central1-docker.pkg.dev/$PROJECT/ml-images/sentiment-api:v1
# docker push us-central1-docker.pkg.dev/$PROJECT/ml-images/sentiment-api:v1

# 매니페스트의 image 만 변경한 임시 사본
sed "s|image: sentiment-api:v1|image: us-central1-docker.pkg.dev/$PROJECT/ml-images/sentiment-api:v1|" \
    manifests/sentiment-gpu-deployment.yaml > /tmp/sentiment-gpu-real.yaml

kubectl apply -f /tmp/sentiment-gpu-real.yaml

# Pod 가 GPU 노드에 떴는지
kubectl get pod -l app=sentiment-api,accelerator=gpu -o wide

# 모델 로딩 대기
kubectl wait --for=condition=Ready pod -l app=sentiment-api,accelerator=gpu --timeout=180s

# Pod 안에서 nvidia-smi — 모델이 GPU 메모리에 올라간 것 확인
POD=$(kubectl get pod -l app=sentiment-api,accelerator=gpu -o jsonpath='{.items[0].metadata.name}')
kubectl exec $POD -- nvidia-smi
```

**예상 출력 (모델 로드 후 nvidia-smi)**:

```
| Processes:                                                                  |
|=============================================================================|
|  0    N/A  N/A    1234   C   /usr/local/bin/python3                ~500MiB |
+-----------------------------------------------------------------------------+
```

✅ **설명**: `Memory Usage` 가 0 → ~500MiB 로 변화 — RoBERTa-base 모델이 GPU 메모리에 로드된 결과. 이게 *Phase 1 의 CPU 추론과의 결정적 차이* 입니다 (CPU 환경에서는 호스트 RAM 만 사용).

검증 후 정리:

```bash
kubectl delete -f /tmp/sentiment-gpu-real.yaml
rm /tmp/sentiment-gpu-real.yaml
```

> 💡 이미지 push 가 부담스러우면 본 단계는 건너뛰고 Step 4 의 nvidia-smi 검증으로 충분합니다. *진짜 LLM GPU 추론* 은 Phase 4/03 vLLM 토픽이 더 명확하게 보여줍니다.

---

## B-Step 6. 안티패턴 시연 — sentiment-gpu-mistake.yaml

Track A 의 Step 2 와 같은 매니페스트를 GKE 에 적용하면 *다른 메시지* 가 보입니다 (lesson 1-3 절의 4-칸 표).

```bash
kubectl apply -f manifests/sentiment-gpu-mistake.yaml

sleep 5
POD=$(kubectl get pod -l app=sentiment-api-mistake -o jsonpath='{.items[0].metadata.name}')
kubectl describe pod $POD | tail -15
```

**예상 출력**:

```
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  3s    default-scheduler  0/2 nodes are available: 1 Insufficient nvidia.com/gpu, 1 node(s) had untolerated taint {nvidia.com/gpu: present}. preemption: ...
```

✅ **설명**: GKE 의 메시지가 더 자세합니다.
- `1 Insufficient nvidia.com/gpu` — 일반 노드 1 대는 GPU capacity 가 없어 거절
- `1 node(s) had untolerated taint {nvidia.com/gpu: present}` — GPU 노드 1 대는 taint 가 있는데 toleration 이 없어 거절

두 거절 사유가 *동시* 에 표시 — 두 노드 어디에도 갈 수 없는 상태. 이게 lesson 1-3 절의 *오른쪽 위 칸* (toleration 없음 + nodeSelector 없음).

회수:

```bash
kubectl delete -f manifests/sentiment-gpu-mistake.yaml
kubectl get all -l phase-4-01=mistake-must-be-deleted -A   # 0 건이어야 함
```

---

## B-Step 7. (옵션) Time-slicing — 한 GPU 를 N 개로 보이게

본 단계는 *시간 여유가 있을 때* 만 진행. GKE 의 가장 간단한 Time-slicing 활성화 방법은 노드 풀을 새로 만들 때 `--gpu-sharing-strategy=time-sharing` 을 주는 것입니다 (기존 노드 풀 수정은 어려움).

```bash
# Time-slicing GPU 노드 풀 추가 (replicas 4 — 1 GPU 가 4 개로 보임)
gcloud container node-pools create gpu-pool-shared \
    --cluster=$CLUSTER_NAME \
    --zone=$ZONE \
    --num-nodes=1 \
    --machine-type=n1-standard-4 \
    --accelerator=type=nvidia-tesla-t4,count=1,gpu-driver-version=DEFAULT,gpu-sharing-strategy=time-sharing,max-shared-clients-per-gpu=4 \
    --spot \
    --node-taints=nvidia.com/gpu=present:NoSchedule

# capacity 가 1 → 4 로 변화한 것 확인
SHARED_NODE=$(kubectl get nodes -l cloud.google.com/gke-gpu-sharing-strategy=time-sharing -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
[ -n "$SHARED_NODE" ] && kubectl describe node $SHARED_NODE | grep -A2 'Capacity:' || echo "[노드가 아직 준비 안 됨 — 1–2분 후 재시도]"
```

**예상 출력**:

```
Capacity:
  ...
  nvidia.com/gpu:     4         # ← 4 로 표시됨 (실 GPU 는 1 장이지만 시분할로 4 슬롯)
```

✅ **설명**: 한 GPU 가 *논리적으로 4 장* 으로 보입니다. 작은 추론 모델 (sentiment-api 같은) 4 개 Pod 가 같은 GPU 에 동시 배치 가능. ⚠ 격리는 약 — 한 Pod 가 GPU 메모리를 다 쓰면 다른 3 개도 OOM (자주 하는 실수 3번).

[gpu-time-slicing-config.yaml](../manifests/gpu-time-slicing-config.yaml) 은 *helm chart 기반* Device Plugin 의 직접 설정 방식 (NVIDIA GPU Operator 등) 이고, 본 단계의 `gcloud --gpu-sharing-strategy` 는 GKE 가 그 설정을 *자동* 으로 적용하는 단축 명령입니다. 결과는 같습니다.

검증 끝났으면 노드 풀 삭제 (학습 목적은 끝났고, Step 9 의 클러스터 삭제 전에 정리):

```bash
gcloud container node-pools delete gpu-pool-shared --cluster=$CLUSTER_NAME --zone=$ZONE --quiet
```

---

## B-Step 8. (옵션) Phase 2/05 dev quota 의 used 채우기

Phase 2/05 의 [dev-quota.yaml](../../phase-2-operations/05-namespace-quota/manifests/dev-quota.yaml) 이 미리 깔아둔 `requests.nvidia.com/gpu: "1"` 을 GKE 클러스터에 가져와, GPU Pod 을 dev 에 띄워 *used 가 0 → 1 로 채워지는 모습* 을 확인합니다.

```bash
# 1) Phase 2/05 의 dev namespace + quota 를 GKE 에 가져옴
kubectl apply -f ../../phase-2-operations/05-namespace-quota/manifests/namespaces.yaml
kubectl apply -f ../../phase-2-operations/05-namespace-quota/manifests/dev-quota.yaml

# 2) GPU Pod 을 dev 에 배치
kubectl apply -n dev -f manifests/gpu-smoke-pod.yaml

# 3) 잠시 대기 후 quota used 확인
sleep 5
kubectl describe quota dev-quota -n dev | grep -A1 'requests.nvidia.com/gpu'
```

**예상 출력**:

```
namespace/dev created
namespace/prod created
resourcequota/dev-quota created
pod/gpu-smoke created

requests.nvidia.com/gpu  1  1
                         ↑  ↑
                       used hard
```

✅ **설명**: Phase 2/05 가 매니페스트로 *예약* 만 해두었던 GPU 슬롯이 *처음으로* 사용된 모습 (`used: 1, hard: 1`). 두 번째 GPU Pod 을 같은 dev 에 배치하면 `Forbidden: ... exceeded quota: dev-quota, requested: requests.nvidia.com/gpu=1, used: requests.nvidia.com/gpu=1, limited: requests.nvidia.com/gpu=1` 으로 거절됩니다.

```bash
# 검증 후 정리
kubectl delete pod gpu-smoke -n dev
kubectl describe quota dev-quota -n dev | grep -A1 'requests.nvidia.com/gpu'
# → used 가 0 으로 복귀
```

---

## B-Step 9. 🚨 클러스터 삭제 — 비용 청구 정지

**본 토픽의 가장 중요한 단계입니다.** 잊으면 시간당 ~$0.5+ 가 계속 청구됩니다.

```bash
# 1) 클러스터 전체 삭제 (control plane + 모든 노드 풀)
gcloud container clusters delete $CLUSTER_NAME --zone=$ZONE --quiet

# 2) 삭제 확인
gcloud container clusters list

# 3) (정말 안전한 검증) — 결제 알림이 활성화되어 있는지
gcloud beta billing accounts list
```

**예상 출력**:

```
Deleting cluster k8s-ml-gpu-lab... done.
Deleted [https://container.googleapis.com/v1/projects/...].

Listed 0 items.

ACCOUNT_ID            NAME             OPEN  MASTER_ACCOUNT_ID
...                   My Billing       True
```

✅ **확인 포인트**: `Listed 0 items` — 본 lab 이 만든 클러스터가 *목록에 없음*. 5–10 분 안에 GCP 결제 대시보드에서도 active resource 가 0 으로 표시됩니다.

> 🚨 **만약 명령이 실패한다면** (예: 권한 문제, 네트워크 문제) — *수동으로* GCP 콘솔 (https://console.cloud.google.com/kubernetes/list) 에서 클러스터를 찾아 삭제하세요. *반드시* 확인 후 본 lab 종료.

---

## Track B 완료 — 검증 체크리스트

본 lab 의 모든 단계를 마쳤다면 다음이 모두 ✅ 여야 합니다.

- [ ] (Step 3) `kubectl describe node` 출력에 `Capacity: nvidia.com/gpu: 1` (또는 Step 7 후 4) 보였음
- [ ] (Step 4) `kubectl logs gpu-smoke` 가 nvidia-smi T4 정보 출력
- [ ] (Step 6) `kubectl describe pod` events 에 `untolerated taint` 메시지 보고 나서 mistake 회수
- [ ] (Step 8 선택) Phase 2/05 dev-quota 의 used 가 0 → 1 → 0 으로 변화 관찰
- [ ] (Step 9) `gcloud container clusters list` 결과가 *비어 있음* — 가장 중요

체크리스트가 모두 ✅ 면 [`docs/course-plan.md`](../../../../docs/course-plan.md) 의 Phase 4/01 산출물 4종 중 3 개 (lesson.md / 매니페스트·코드 / labs) 를 `[x]` 로 마킹할 수 있습니다. 4 번째 (GPU 클러스터 검증) 는 본 lab 의 Track B 완료 자체가 검증입니다.

---

## 다음 챕터

➡️ [Phase 4 / 02 — KServe InferenceService](../../02-kserve-inference/lesson.md) (작성 예정)

본 토픽이 마감한 자산: ① **`nvidia.com/gpu` requests + nodeSelector + toleration 5–6 줄 패턴** 이 다음 토픽 KServe `InferenceService` 의 `spec.predictor.containers[0].resources` 에 그대로 들어갑니다. ② **GKE 클러스터 삭제 후 재생성 흐름** 은 Phase 4 의 모든 GPU 토픽에서 반복됩니다 — 다음 토픽 시작 시 새 클러스터를 다시 만드는 것이 표준.
