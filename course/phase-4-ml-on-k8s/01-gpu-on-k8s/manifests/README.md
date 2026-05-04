# Phase 4 / 01 — GPU on Kubernetes 매니페스트

본 디렉토리에는 4 개의 매니페스트가 있고, *적용 대상 트랙* 과 *의도* 가 모두 다릅니다. 본 파일은 학습자가 어느 파일을 언제 / 어디에 / 어떻게 적용할지 한눈에 알 수 있도록 정리한 인덱스입니다. 자세한 단계는 [labs/README.md](../labs/README.md) 를 따릅니다.

## 적용 대상 매트릭스

| 매니페스트 | Track A (minikube 모의) | Track B (GKE 실전) | 의도 |
|-----------|-----------------------|-------------------|------|
| [gpu-smoke-pod.yaml](./gpu-smoke-pod.yaml) | ❌ apply 금지 (영구 Pending) | ✅ Step 4 의 1차 GPU 검증 | `nvidia/cuda` 이미지로 `nvidia-smi` 한 번 출력 — Device Plugin 이 정상 동작하는지 5초 안에 확인 |
| [sentiment-gpu-deployment.yaml](./sentiment-gpu-deployment.yaml) | ⚠️ `--dry-run=server` 만 (실제 apply 시 Pending) | ✅ (이미지 push 필요) Step 5 옵션 | Phase 1/04 deployment 와의 *4-군데 diff* 로 GPU 자원 / nodeSelector / toleration / CUDA_VISIBLE_DEVICES 를 학습 |
| [sentiment-gpu-mistake.yaml](./sentiment-gpu-mistake.yaml) | ✅ Step 2 — Pending 시연 후 즉시 delete | ✅ Step 6 — taint untolerated 메시지 시연 후 즉시 delete | 의도적 안티패턴 (requests 누락 + nodeSelector 누락 + tolerations 누락) — 자주 하는 실수의 *현장 재현* |
| [gpu-time-slicing-config.yaml](./gpu-time-slicing-config.yaml) | ❌ 적용 X (Device Plugin 자체가 없음) | ⚠️ Step 7 옵션 — 개념 학습 후 적용 시도 | Time-slicing 으로 한 GPU 를 4 분할하는 *개념 시연 dump*. 단독 apply 만으로는 효과 없음 (Device Plugin 의 config 참조 필요) |

## 4 매니페스트의 역할 분담

### 1) `gpu-smoke-pod.yaml` — *최소 검증*

NVIDIA Device Plugin 이 노드 capacity 에 `nvidia.com/gpu: N` 을 정상 노출했는지를, sentiment-api 같은 *진짜 모델 추론 매니페스트를 띄우기 전* 에 한 번에 확인합니다. `nvidia/cuda:12.2.0-base-ubuntu22.04` 이미지가 ~150MB 로 작아서 pull 도 빠르고, `nvidia-smi` 한 번 실행 후 Pod 가 Completed 되어 `kubectl logs gpu-smoke` 로 출력을 다시 볼 수 있습니다.

### 2) `sentiment-gpu-deployment.yaml` — *정상 패턴 교본*

Phase 1/04 의 [deployment.yaml](../../../phase-1-k8s-basics/04-serve-classification-model/manifests/deployment.yaml) 과 정확히 4 군데만 다릅니다 (lesson 의 *diff 학습 포인트*).

```diff
+        - name: CUDA_VISIBLE_DEVICES
+          value: "0"
         resources:
           requests:
             cpu: "250m"
             memory: "1Gi"
+            nvidia.com/gpu: 1
           limits:
             cpu: "1"
             memory: "2Gi"
+            nvidia.com/gpu: 1
+      nodeSelector:
+        cloud.google.com/gke-accelerator: nvidia-tesla-t4
+      tolerations:
+        - key: nvidia.com/gpu
+          operator: Exists
+          effect: NoSchedule
```

Track A 학습자는 이 파일을 *교본* 으로 읽고 dry-run 만 합니다. Track B 학습자는 이미지를 GCR / Artifact Registry 에 push 한 뒤 실제 apply 가 가능하지만, 본 코스 흐름은 *추론 자체는 Phase 4/02 KServe / 03 vLLM 에서* 다루므로 Track B 도 이 파일은 dry-run 검증 + nvidia-smi 검증 (gpu-smoke-pod.yaml) 으로 대체 가능합니다.

### 3) `sentiment-gpu-mistake.yaml` — *안티패턴 시연*

자주 하는 실수 3 가지 (requests 누락, nodeSelector 누락, tolerations 누락) 를 *한 매니페스트에 응축* 했습니다. 적용하면 양 트랙에서 모두 Pending 으로 끝나며, 각 트랙별로 `kubectl describe pod` events 의 메시지가 다릅니다.

| 트랙 | 예상 events 메시지 (요약) |
|------|---------------------------|
| Track A (minikube) | `0/1 nodes are available: 1 Insufficient nvidia.com/gpu` — 노드에 GPU capacity 자체가 없음 |
| Track B (GKE) | `node(s) had untolerated taint {nvidia.com/gpu: present}` — GPU 노드에 들어갈 toleration 이 없음 |

### 4) `gpu-time-slicing-config.yaml` — *공유 전략 개념*

본 토픽은 MIG / Time-slicing 의 *개념* 만 다루고, 실 적용은 KServe / vLLM 토픽 이후로 미룹니다 (인프라 팀 작업의 영역). 본 ConfigMap 은 *Device Plugin 이 어떤 형식의 설정을 받는가* 를 보여주는 정적 dump 이고, 실제로 동작시키려면 Device Plugin DaemonSet 의 args / helm values 변경이 추가로 필요합니다 (파일 안의 주석 참고).

## 적용 / 회수 명령 모음

Track A (minikube) 흐름의 핵심 두 줄:

```bash
# Step 2: 안티패턴 적용 → Pending 관찰 → 즉시 delete
kubectl apply -f manifests/sentiment-gpu-mistake.yaml
kubectl describe deployment sentiment-api-gpu-mistake | head -40
kubectl describe pod -l app=sentiment-api-mistake | grep -A5 Events
kubectl delete -f manifests/sentiment-gpu-mistake.yaml

# Step 4: 정상 매니페스트의 dry-run 검증
kubectl apply --dry-run=server -f manifests/sentiment-gpu-deployment.yaml
```

Track B (GKE) 흐름의 핵심 명령:

```bash
# Step 4: nvidia-smi 검증
kubectl apply -f manifests/gpu-smoke-pod.yaml
kubectl wait --for=condition=Ready pod/gpu-smoke --timeout=60s || true   # Completed 도 OK
kubectl logs gpu-smoke

# Step 6: 안티패턴 — taint untolerated 메시지
kubectl apply -f manifests/sentiment-gpu-mistake.yaml
kubectl describe pod -l app=sentiment-api-mistake | grep -A5 Events
kubectl delete -f manifests/sentiment-gpu-mistake.yaml

# 모든 단계 후 정리
kubectl delete pod gpu-smoke --ignore-not-found
kubectl get all -l phase-4-01=mistake-must-be-deleted -A   # 0 건이어야 함
```

## ⚠️ 정리 체크포인트

본 토픽이 끝나면 다음 자원이 *남아 있지 않아야* 합니다 (잔존 시 GKE 비용 또는 Track A 의 Pending Pod 누적).

- `kubectl get deployment -l phase-4-01=mistake-must-be-deleted -A` → 0 건
- `kubectl get pod gpu-smoke` → NotFound (Track B 에서 띄웠다면 삭제)
- (Track B) `gcloud container clusters list` → 실습용 클러스터 0 건 (가장 중요 — 비용 청구 방지)
