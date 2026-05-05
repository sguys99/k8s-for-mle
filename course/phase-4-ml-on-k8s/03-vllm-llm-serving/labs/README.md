# Phase 4 / 03 — 실습 가이드 (vLLM LLM Serving)

> [lesson.md](../lesson.md) 의 1-1~1-6 개념을 실제 클러스터에 적용해, vLLM 의 OpenAI 호환 API / PagedAttention / continuous batching / Prometheus 메트릭을 직접 검증합니다. 본 lab 은 학습자의 환경에 따라 *이중 트랙* 으로 분기합니다 — Phase 4/01 의 패턴 그대로.
>
> **Track A — minikube CPU 스모크 (Step 0–5)**: GPU 가 없는 환경. vLLM CPU 빌드 이미지로 *작은 모델* (`facebook/opt-125m`) 을 띄워 OpenAI 호환 API 의 *모양* 을 익히고, GPU 매니페스트는 dry-run 으로 admission 통과만 확인. 누구나 바로 시작 가능.
>
> **Track B — GKE T4 실전 (Step 0–8)**: GCP 크레딧이 있거나 로컬 NVIDIA GPU 가 있는 환경. `microsoft/phi-2` 실 서빙 + Prometheus 메트릭 관찰 + hey 부하 테스트 + 자주 하는 실수 재현. **마지막 Step 8 (클러스터 삭제) 가 가장 중요** — 잔존 시 비용 청구 지속.
>
> **소요 시간**: Track A 40–60분 / Track B 90–120분 (GKE 클러스터 생성 15–20분 + 모델 다운로드 5–10분 + 실습 + 삭제 5분 포함)

---

## 작업 디렉토리

본 lab 의 모든 명령은 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-4-ml-on-k8s/03-vllm-llm-serving
ls
# 예상 출력:
# labs/  lesson.md  manifests/
```

상대경로 `manifests/...` 가 그대로 동작합니다.

---

## 트랙 선택

먼저 자신이 어느 트랙으로 갈지 정합니다.

```bash
# 로컬 GPU 가 있는지 — Track B (로컬) 가능
nvidia-smi 2>/dev/null | head -1 && echo "[로컬 GPU 있음 → Track B 가능]" || echo "[로컬 GPU 없음]"

# GCP 인증이 되어 있고 사용 가능한 프로젝트가 있는지 — Track B (GKE) 가능
gcloud config get-value project 2>/dev/null && echo "[GCP 인증 OK → Track B (GKE) 가능]" || echo "[GCP 미설정]"

# 둘 다 안 되면 Track A 만 가능 — 그것으로 본 토픽의 *추상화 모델* (OpenAI API / 매니페스트 구조 / GPU 격리 패턴) 은 모두 학습 가능
```

> 💡 Track A 만 따라가도 본 토픽 학습 목표 4 가지 중 1, 3, 4 는 달성합니다. 2 (PagedAttention 효과를 *메트릭으로* 관찰) 만 Track B 의 Step 5B–6B 에서 직접 확인 가능합니다.

---

## 실습 단계 한눈에 보기

| Step | Track | 목적 | 핵심 명령 | 소요 |
|-----|------|------|----------|------|
| 0 | 공통 | 사전 점검 | `kubectl cluster-info` / `gcloud --version` | 5분 |
| 1 | 공통 | Secret + PVC 적용 | `kubectl apply -f manifests/vllm-hf-secret.yaml -f manifests/vllm-pvc.yaml` | 5분 |
| 2A | A | vLLM CPU 빌드로 opt-125m 띄우기 | `kubectl apply -f vllm-cpu-smoke.yaml` (lab 안에서 인라인 작성) | 10–15분 |
| 3A | A | OpenAI 호환 API 호출 | `curl .../v1/chat/completions` | 5분 |
| 4A | A | GPU 매니페스트 dry-run | `kubectl apply --dry-run=server -f vllm-phi2-deployment.yaml` | 5분 |
| 5A | A | Track A 정리 | `kubectl delete -f vllm-cpu-smoke.yaml` | 5분 |
| 2B | B | GKE Spot T4 클러스터 생성 | `gcloud container clusters create vllm-lab ...` | 15–20분 |
| 3B | B | vllm-phi2 Deployment 적용 | `kubectl apply -f manifests/` + `kubectl logs -f` | 10–15분 |
| 4B | B | OpenAI Python SDK 호출 | `python -c "from openai import OpenAI; ..."` | 10분 |
| 5B | B | Prometheus 메트릭 관찰 | `kubectl port-forward svc/prometheus-...` | 15분 |
| 6B | B | hey 부하 테스트 | `hey -z 60s -c 8 ... /v1/chat/completions` | 30분 |
| 7B | B | 자주 하는 실수 재현 | `kubectl apply -f manifests/vllm-mistake-cpu-only.yaml` | 10분 |
| 8B | B | **GKE 클러스터 삭제** | `gcloud container clusters delete vllm-lab` | 5분 |

---

## Step 0 — 공통 사전 점검

본 토픽은 직전 토픽 [Phase 4/01](../../01-gpu-on-k8s/) 과 [Phase 4/02](../../02-kserve-inference/) 의 자산을 *재사용하지 않습니다* — 두 토픽이 모두 정리되었어도 본 토픽은 독립적으로 진행 가능합니다.

```bash
# kubectl 버전 (1.28+ 권장)
kubectl version --client

# Track B 진행 시 gcloud
gcloud --version 2>/dev/null | head -1

# Track A 진행 시 minikube
minikube status 2>/dev/null
```

**예상 출력 (Track A 진행 환경 예시)**:

```
Client Version: v1.28.x
Kustomize Version: v5.x.x

minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
```

> 💡 Track A 의 minikube 는 vLLM CPU 빌드를 띄우기 위해 *6GB+ 메모리 + 4 CPU+* 권장. 부족하면 `minikube stop && minikube start --memory=6144 --cpus=4`.

✅ **확인 포인트**: 자신이 진행할 트랙에 필요한 도구가 모두 동작합니다. 부족하면 다음 Step 으로 넘어가지 마세요.

---

## Step 1 — Secret + PVC 적용 (공통)

Track A / B 모두에서 vLLM 컨테이너가 참조하는 두 리소스 (HF 토큰 Secret, 모델 캐시 PVC) 를 먼저 적용합니다.

```bash
# Track A 는 default namespace 그대로 사용
# Track B 는 GKE 클러스터 생성 후 (Step 2B 뒤) 다시 와서 적용 — 본 Step 은 Track A 만 지금 실행
kubectl apply -f manifests/vllm-hf-secret.yaml
kubectl apply -f manifests/vllm-pvc.yaml
```

**예상 출력**:

```
secret/hf-secret created
persistentvolumeclaim/vllm-phi2-cache created
```

```bash
kubectl get secret hf-secret pvc/vllm-phi2-cache
```

**예상 출력**:

```
NAME                          TYPE     DATA   AGE
secret/hf-secret              Opaque   1      ...

NAME                                    STATUS   VOLUME      CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/vllm-phi2-cache   Bound    pvc-xxxx    20Gi       RWO            standard       ...
```

✅ **확인 포인트**:
- Secret 의 `DATA: 1` — `HF_TOKEN` 키가 1개 들어있습니다 (placeholder 값이라도 OK — phi-2 는 public).
- PVC 의 `STATUS: Bound` — 클러스터의 default StorageClass 가 PV 를 자동 프로비저닝했습니다. `Pending` 이면 StorageClass 미설정. `kubectl get sc` 로 default 확인.

---

# Track A — minikube CPU 스모크 (Step 0–5)

vLLM 은 *CPU 빌드 이미지* (`vllm/vllm-openai:v0.6.6.post1` 의 CPU 빌드 또는 vLLM 공식 CPU 가이드의 `vllm-cpu-env`) 도 제공합니다. 처리량은 GPU 빌드의 1/100 수준이지만, *OpenAI 호환 API 의 모양* 과 *매니페스트 구조* 를 학습하기에는 충분합니다.

> ⚠️ vLLM 의 공식 CPU 이미지는 빌드 환경에 따라 태그가 다릅니다. 본 lab 에서는 [vllm-project/vllm-cpu](https://github.com/vllm-project/vllm/blob/main/Dockerfile.cpu) 빌드의 일반적인 패턴을 따라 *가장 작은 모델* (`facebook/opt-125m`, 250MB) 로 스모크 테스트만 진행합니다. phi-2 (2.7B) 는 CPU 빌드로도 호스트 RAM 8GB+ 필요해 minikube 환경에서 비현실적입니다.

## A-Step 2. vLLM CPU 빌드로 opt-125m 띄우기

먼저 본 lab 안에서만 사용할 인라인 매니페스트를 만들어 적용합니다 (manifests/ 에는 두지 않습니다 — Track A 전용 학습 도구).

```bash
cat <<'EOF' > /tmp/vllm-cpu-smoke.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-cpu-smoke
  labels: { app: vllm-cpu-smoke, phase: "4", topic: "03-vllm-llm-serving" }
spec:
  replicas: 1
  selector: { matchLabels: { app: vllm-cpu-smoke } }
  template:
    metadata:
      labels: { app: vllm-cpu-smoke }
    spec:
      containers:
        - name: vllm
          # 공식 vLLM CPU 빌드 — Docker Hub 에 별도 이미지로 제공.
          # 학습용으로 가장 작은 모델만 띄울 거라 latest 태그 사용.
          image: vllm/vllm-openai:v0.6.6.post1
          # CPU 빌드는 GPU 관련 args 를 빼고, --device cpu 를 줍니다.
          args:
            - --model=facebook/opt-125m       # 250MB OPT-125M — CPU 로도 토큰/sec 5 이상 나옴
            - --device=cpu                     # CPU 모드 강제
            - --port=8000
            - --max-model-len=512              # OPT-125M 의 학습 max context (작게)
          ports:
            - { name: http, containerPort: 8000 }
          resources:
            requests: { cpu: "1", memory: "3Gi" }
            limits:   { cpu: "2", memory: "6Gi" }
          startupProbe:
            httpGet: { path: /health, port: http }
            failureThreshold: 30          # 30 × 10s = 5분. CPU 추론 첫 기동은 의외로 빠름 (작은 모델)
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: vllm-cpu-smoke
  labels: { app: vllm-cpu-smoke, phase: "4", topic: "03-vllm-llm-serving" }
spec:
  type: ClusterIP
  selector: { app: vllm-cpu-smoke }
  ports: [ { name: http, port: 8000, targetPort: http } ]
EOF

kubectl apply -f /tmp/vllm-cpu-smoke.yaml
```

**예상 출력**:

```
deployment.apps/vllm-cpu-smoke created
service/vllm-cpu-smoke created
```

Pod 가 모델을 다운로드/로딩하는 동안 (3~5분) 진행 상황을 봅니다.

```bash
kubectl logs -f deploy/vllm-cpu-smoke
```

**예상 출력 (시간 흐름)**:

```
INFO ... Starting vLLM API server ...
INFO ... Loaded model: facebook/opt-125m
INFO ... Model loaded successfully
INFO ... Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

`Uvicorn running on http://0.0.0.0:8000` 메시지가 보이면 ready. `Ctrl+C` 로 watch 종료.

✅ **확인 포인트**: Pod 가 `Running` 이고 `kubectl get pod -l app=vllm-cpu-smoke` 의 `READY` 컬럼이 `1/1` 입니다. CrashLoopBackOff 면 호스트 RAM 이 부족할 가능성 (특히 minikube `--memory=6144` 미만일 때).

> 💡 CPU 빌드는 GPU 빌드의 1/100 처리량이라 *처리량 측정* 은 의미가 없습니다. 본 Step 의 목적은 (a) vLLM 컨테이너가 모델을 로드한 뒤 (b) `/health` 가 200 OK 를 반환하고 (c) `/v1/...` 엔드포인트가 살아있다는 것까지만.

## A-Step 3. OpenAI 호환 API 호출

호스트에서 직접 부르려면 `kubectl port-forward` 가 필요합니다.

```bash
kubectl port-forward svc/vllm-cpu-smoke 8000:8000 &
PF_PID=$!
sleep 2
```

**예상 출력 (백그라운드)**:

```
Forwarding from 127.0.0.1:8000 -> 8000
Forwarding from [::1]:8000 -> 8000
```

`/v1/models` — 모델 목록 (헬스체크 대체용):

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

**예상 출력**:

```json
{
    "object": "list",
    "data": [
        {
            "id": "facebook/opt-125m",
            "object": "model",
            "created": 1735689600,
            "owned_by": "vllm",
            "max_model_len": 512
        }
    ]
}
```

`/v1/chat/completions` — 챗봇 호출 (작은 모델이라 응답 품질은 무의미, *응답 형식* 학습이 목적):

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "facebook/opt-125m",
    "messages": [{"role": "user", "content": "Hello, who are you?"}],
    "max_tokens": 50,
    "temperature": 0.7
  }' | python3 -m json.tool
```

**예상 출력 (응답 텍스트는 OPT-125M 의 약한 품질로 의미 X — 형식만 확인)**:

```json
{
    "id": "chatcmpl-...",
    "object": "chat.completion",
    "created": 1735689650,
    "model": "facebook/opt-125m",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "I am a robot. I am a robot..."},
            "finish_reason": "length"
        }
    ],
    "usage": {"prompt_tokens": 8, "completion_tokens": 50, "total_tokens": 58}
}
```

✅ **확인 포인트**: 응답 JSON 의 *키 구조* (`choices[0].message.content`, `usage.completion_tokens`) 가 OpenAI spec 그대로입니다 — Track B 에서 phi-2 로 바꿔도 *클라이언트 코드를 안 바꿔도 됩니다*. 이게 vLLM 의 OpenAI 호환 API 의 운영적 가치.

```bash
# port-forward 종료
kill $PF_PID 2>/dev/null
```

## A-Step 4. GPU 매니페스트 dry-run 으로 admission 통과 확인

Track A 환경에 GPU 가 없으므로 [vllm-phi2-deployment.yaml](../manifests/vllm-phi2-deployment.yaml) 을 실제 apply 하면 *Pending 으로 영원히 멈춥니다* (GPU 자원이 클러스터 어디에도 없음). 대신 dry-run 으로 *매니페스트 자체* 가 admission 단계에서 거절되지 않는지 확인합니다.

```bash
kubectl apply --dry-run=server -f manifests/vllm-phi2-deployment.yaml
kubectl apply --dry-run=server -f manifests/vllm-service.yaml
kubectl apply --dry-run=server -f manifests/vllm-mistake-cpu-only.yaml
```

**예상 출력**:

```
deployment.apps/vllm-phi2 created (server dry run)
service/vllm-phi2 created (server dry run)
deployment.apps/vllm-phi2-mistake created (server dry run)
```

✅ **확인 포인트**: 세 매니페스트 모두 `(server dry run)` 으로 끝납니다. 에러 (예: `error validating data: ...nvidia.com/gpu...`) 가 없으면 매니페스트가 *클러스터 schema 적합* 입니다.

> 💡 `--dry-run=server` 는 *클러스터 API 서버* 가 admission webhook 까지 거쳐 검증하는 모드입니다. `--dry-run=client` 는 클라이언트 측 schema 만 검증해 GPU resource key 같은 extended resource 검증을 못 합니다 — 본 Step 처럼 GPU 매니페스트 검증에는 `--dry-run=server` 가 정답.

```bash
# (옵션) ServiceMonitor 는 kube-prometheus-stack 미설치 minikube 에선 admission 거절
kubectl apply --dry-run=server -f manifests/vllm-servicemonitor.yaml 2>&1 | head -3
```

**예상 출력 (Phase 3/02 미완료 환경)**:

```
error: resource mapping not found for name: "vllm-phi2" namespace: "" from "manifests/vllm-servicemonitor.yaml":
no matches for kind "ServiceMonitor" in version "monitoring.coreos.com/v1"
ensure CRDs are installed first
```

이 에러는 *kube-prometheus-stack 이 ServiceMonitor CRD 를 등록하지 않았기 때문* — 매니페스트 자체는 옳습니다. Phase 3/02 가 완료되었거나 Track B 의 GKE 에서는 정상 통과.

## A-Step 5. Track A 정리

```bash
kubectl delete -f /tmp/vllm-cpu-smoke.yaml
kubectl delete -f manifests/vllm-pvc.yaml
kubectl delete -f manifests/vllm-hf-secret.yaml
rm /tmp/vllm-cpu-smoke.yaml
```

**예상 출력**:

```
deployment.apps "vllm-cpu-smoke" deleted
service "vllm-cpu-smoke" deleted
persistentvolumeclaim "vllm-phi2-cache" deleted
secret "hf-secret" deleted
```

```bash
kubectl get all -l topic=03-vllm-llm-serving
```

**예상 출력**:

```
No resources found in default namespace.
```

✅ **확인 포인트**: 본 토픽 라벨 (`topic=03-vllm-llm-serving`) 의 모든 리소스가 정리되었습니다.

**Track A 완료**. lesson.md 의 검증 체크리스트로 돌아가, "Track A" 항목 2개 + "공통" 항목 3개에 체크하세요.

---

# Track B — GKE T4 실전 (Step 0–8)

GKE Spot T4 노드 1개를 임시로 띄워 `microsoft/phi-2` 를 실 서빙합니다. T4 시간당 비용 약 **$0.35** (Spot 기준), 본 lab 전체 1.5~2 시간이면 **$0.6~0.8** 정도. **마지막 Step 8 (클러스터 삭제) 를 잊으면 비용 청구가 24시간 단위로 누적**됩니다.

## B-Step 2. GKE Spot T4 클러스터 생성

```bash
# 환경 변수 — 본인의 GCP 프로젝트로 교체
export PROJECT_ID=$(gcloud config get-value project)
export CLUSTER_NAME=vllm-lab
export ZONE=us-central1-c

# T4 노드 풀이 있는 GKE 클러스터 1노드 생성 (Spot)
gcloud container clusters create $CLUSTER_NAME \
  --zone=$ZONE \
  --num-nodes=1 \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1,gpu-driver-version=default \
  --spot \
  --release-channel=regular \
  --enable-ip-alias

# kubectl context 가 자동으로 새 클러스터로 설정됨
kubectl config current-context
```

**예상 출력 (15–20분 후)**:

```
Creating cluster vllm-lab in us-central1-c...
...done.
Created [https://container.googleapis.com/v1/projects/.../zones/us-central1-c/clusters/vllm-lab].
kubeconfig entry generated for vllm-lab.

NAME       LOCATION       MASTER_VERSION   MASTER_IP      MACHINE_TYPE    STATUS
vllm-lab   us-central1-c  1.28.x-gke.x     ...           n1-standard-4   RUNNING

gke_<project>_us-central1-c_vllm-lab
```

✅ **확인 포인트**: `kubectl config current-context` 가 `gke_..._vllm-lab` 형태입니다. 만약 이전 minikube context 그대로면 매니페스트가 *minikube 에 적용* 되어 GPU 없이 Pending — 반드시 context 전환 확인.

GKE 의 GPU 노드는 NVIDIA Device Plugin 이 *자동으로* 설치되지만, Daemon이 Ready 될 때까지 1~2 분이 걸립니다.

```bash
# Device Plugin Daemon 이 GPU 자원을 노드에 등록할 때까지 대기
kubectl wait --for=condition=Ready pod -l k8s-app=nvidia-gpu-device-plugin -n kube-system --timeout=300s 2>/dev/null \
  || kubectl get pods -n kube-system -l k8s-app=nvidia-gpu-device-plugin

# 노드 capacity 에 nvidia.com/gpu 키가 등록되었는지 확인
kubectl get nodes -o json | python3 -c "
import json, sys
nodes = json.load(sys.stdin)['items']
for n in nodes:
    cap = n['status']['capacity']
    print(n['metadata']['name'], '→', cap.get('nvidia.com/gpu', '(없음)'))
"
```

**예상 출력**:

```
gke-vllm-lab-default-pool-xxx → 1
```

✅ **확인 포인트**: `nvidia.com/gpu: 1` — 노드에 GPU 1장이 K8s 자원으로 등록되었습니다. Phase 4/01 의 1-1 다이어그램이 *실제로* 일어난 결과.

## B-Step 3. vllm-phi2 Deployment 적용

```bash
# Step 1 의 Secret + PVC 를 GKE 클러스터에 다시 적용 (context 가 다른 클러스터로 바뀌었으므로)
kubectl apply -f manifests/vllm-hf-secret.yaml
kubectl apply -f manifests/vllm-pvc.yaml

# 메인 Deployment + Service
kubectl apply -f manifests/vllm-phi2-deployment.yaml
kubectl apply -f manifests/vllm-service.yaml
```

**예상 출력**:

```
secret/hf-secret created
persistentvolumeclaim/vllm-phi2-cache created
deployment.apps/vllm-phi2 created
service/vllm-phi2 created
```

Pod 의 첫 기동은 *모델 다운로드 5~10분 + GPU 로딩 30~60초* 가 합쳐 5~10분 걸립니다. logs 로 진행 상황 모니터링.

```bash
kubectl logs -f deploy/vllm-phi2
```

**예상 출력 (시간 흐름)**:

```
INFO ... Starting vLLM API server ...
INFO ... Downloading 'microsoft/phi-2' to /root/.cache/huggingface/hub ...
... (5~10분 다운로드 진행 — Progress bar 가 1/3, 2/3 ... 으로 진행)
INFO ... Loading model 'microsoft/phi-2' to GPU ...
INFO ... Model loaded successfully (took 45.2 seconds)
INFO ... # GPU blocks: 4096, # CPU blocks: 0          ← KV cache 의 페이지 (PagedAttention 의 페이지)
INFO ... Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

`Uvicorn running on http://0.0.0.0:8000` 메시지가 보이면 ready. `Ctrl+C` 로 watch 종료.

```bash
kubectl get pod -l app=vllm-phi2
kubectl get pvc vllm-phi2-cache
```

**예상 출력**:

```
NAME                         READY   STATUS    RESTARTS   AGE
vllm-phi2-xxxxxxxxxx-xxxxx   1/1     Running   0          7m

NAME              STATUS   VOLUME      CAPACITY   ACCESS MODES   STORAGECLASS    AGE
vllm-phi2-cache   Bound    pvc-xxxx    20Gi       RWO            standard-rwo    7m
```

✅ **확인 포인트**:
- Pod `READY: 1/1` — startupProbe 통과 + readinessProbe 통과
- PVC `STATUS: Bound` — GKE 의 standard-rwo StorageClass 가 PD 를 자동 프로비저닝

```bash
# GPU 위에 모델이 *실제로* 올라갔는지 확인
kubectl exec deploy/vllm-phi2 -- nvidia-smi
```

**예상 출력 발췌**:

```
+-----------------------------------------------------------------------------+
| NVIDIA-SMI ...                       Driver Version: ...      CUDA Version: ... |
|-------------------------------+----------------------+----------------------+
| GPU  Name                     | Memory-Usage         | GPU-Util             |
| 0   NVIDIA T4                 | 13624MiB / 15109MiB  |    0%                |
+-------------------------------+----------------------+----------------------+
```

✅ **확인 포인트**: T4 16GB 중 *13.6GB* 가 사용 중 — 모델 가중치 (~5.4GB FP16) + KV cache 풀 (~7.5GB, gpu-memory-utilization=0.85 로 사전 할당) + 약간의 activation. 즉 PagedAttention 이 *시작 시 메모리 풀을 잡아 두는* 동작이 보입니다.

## B-Step 4. OpenAI Python SDK 로 호출

```bash
# port-forward 백그라운드로
kubectl port-forward svc/vllm-phi2 8000:8000 &
PF_PID=$!
sleep 2
```

먼저 curl 로 /v1/models 확인:

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
```

**예상 출력**:

```json
{
    "object": "list",
    "data": [
        {
            "id": "microsoft/phi-2",
            "object": "model",
            "created": 1735689600,
            "owned_by": "vllm",
            "max_model_len": 2048
        }
    ]
}
```

OpenAI Python SDK 로 호출 (캡스톤의 RAG API 가 vLLM 을 부르는 *진짜 코드 모양*):

```bash
pip install openai 2>&1 | tail -1

python3 <<'PY'
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-used",                  # vLLM 은 인증 미강제
)

resp = client.chat.completions.create(
    model="microsoft/phi-2",
    messages=[
        {"role": "system", "content": "You are a Kubernetes expert."},
        {"role": "user",   "content": "What is the difference between a Pod and a Deployment?"},
    ],
    max_tokens=200,
    temperature=0.3,
)

print("─── Response ───")
print(resp.choices[0].message.content)
print()
print(f"prompt tokens: {resp.usage.prompt_tokens}, completion tokens: {resp.usage.completion_tokens}")
PY
```

**예상 출력 (구체 텍스트는 phi-2 의 응답 — 매번 약간 달라짐)**:

```
─── Response ───
A Pod is the smallest deployable unit in Kubernetes — it represents one or more
containers that share storage and network. A Deployment is a higher-level abstraction
that manages a set of identical Pods (via a ReplicaSet), providing rolling updates,
rollback, and self-healing capabilities. In short: a Pod is a single instance, a
Deployment ensures N instances stay healthy.

prompt tokens: 31, completion tokens: 87
```

✅ **확인 포인트**: 자연어 응답이 200 OK 로 돌아왔습니다. `usage` 필드의 토큰 수가 `prompt_tokens + completion_tokens = total_tokens` 로 일관됩니다 — Phase 3/02 의 Prometheus 가 이 토큰 수를 메트릭으로 기록할 때의 근거.

```bash
# port-forward 유지 — 다음 Step 들에서 재사용
```

## B-Step 5. Prometheus 메트릭 관찰

본 Step 은 *Phase 3/02 의 kube-prometheus-stack 이 GKE 클러스터에 설치되어 있을 때* 만 동작합니다. GKE 의 임시 클러스터에는 대개 미설치이므로, 두 경로 중 하나로 메트릭을 봅니다.

**경로 1 — vLLM `/metrics` 직접 조회 (Prometheus 미설치 환경에서도 동작)**:

```bash
curl -s http://localhost:8000/metrics | grep -E "^(vllm:|# HELP vllm:)" | head -30
```

**예상 출력 발췌**:

```
# HELP vllm:num_requests_running Number of requests currently running on GPU.
vllm:num_requests_running{model_name="microsoft/phi-2"} 0.0
# HELP vllm:num_requests_waiting Number of requests waiting to be processed.
vllm:num_requests_waiting{model_name="microsoft/phi-2"} 0.0
# HELP vllm:gpu_cache_usage_perc GPU KV-cache usage. 1 means 100 percent usage.
vllm:gpu_cache_usage_perc{model_name="microsoft/phi-2"} 0.0
# HELP vllm:time_to_first_token_seconds Histogram of time to first token in seconds.
vllm:time_to_first_token_seconds_bucket{le="0.001",model_name="microsoft/phi-2"} 0.0
...
vllm:generation_tokens_total{model_name="microsoft/phi-2"} 87.0
```

✅ **확인 포인트**: `vllm:generation_tokens_total` 이 87 (또는 그 부근) — Step 4B 에서 호출한 한 번의 응답이 *87 completion tokens* 였던 것과 일치. 메트릭이 실제로 누적됩니다.

**경로 2 — kube-prometheus-stack 설치 후 ServiceMonitor 활용**:

```bash
# Phase 3/02 에서 다룬 helm 으로 설치 (이미 설치되어 있으면 스킵)
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --create-namespace --namespace monitoring --wait

# ServiceMonitor 적용
kubectl apply -f manifests/vllm-servicemonitor.yaml

# Prometheus UI 로 port-forward
kubectl port-forward -n monitoring svc/kube-prometheus-stack-prometheus 9090:9090 &
PROM_PID=$!
sleep 3

echo "Prometheus UI: http://localhost:9090"
echo "  Targets 탭에서 'vllm-phi2' job 이 UP 인지 확인"
echo "  Graph 탭에서 'vllm:gpu_cache_usage_perc' 쿼리"
```

✅ **확인 포인트** (경로 2):
- Prometheus UI 의 **Status > Targets** 에 `vllm-phi2` job 이 *UP* 으로 보입니다 — ServiceMonitor 가 정상 동작.
- **Graph** 탭에서 `vllm:gpu_cache_usage_perc` 쿼리 시 0 또는 0.x 값. 부하가 없으므로 KV cache 가 비어 있습니다.
- 다음 Step (부하 테스트) 에서 이 값이 *0.6+* 로 올라갈 것입니다.

```bash
# Prometheus port-forward 종료 (다음 Step 에선 vLLM port-forward 만 유지)
kill $PROM_PID 2>/dev/null
```

## B-Step 6. hey 부하 테스트 — continuous batching 의 효과 측정

`hey` (Phase 3/03 에서 사용) 로 vLLM 에 동시 요청을 넣어, *처리량 / latency / KV cache 사용률* 의 변화를 측정합니다.

```bash
# hey 설치 확인 (Phase 3/03 에서 설치한 경우 그대로)
hey -h 2>&1 | head -1 || (echo "hey 미설치 — go install github.com/rakyll/hey@latest") || \
  brew install hey 2>/dev/null || true
```

요청 본문을 파일로 만들어둡니다.

```bash
cat > /tmp/vllm-payload.json <<'JSON'
{
  "model": "microsoft/phi-2",
  "messages": [{"role": "user", "content": "Explain Kubernetes Deployment in 3 sentences."}],
  "max_tokens": 100,
  "temperature": 0.7
}
JSON
```

부하 테스트 1 — 동시 요청 1개 (기준선):

```bash
hey -z 30s -c 1 \
  -m POST \
  -T application/json \
  -D /tmp/vllm-payload.json \
  http://localhost:8000/v1/chat/completions
```

**예상 출력 발췌**:

```
Summary:
  Total:        30.0xxx secs
  Slowest:      4.5xxx secs
  Fastest:      3.7xxx secs
  Average:      4.1xxx secs
  Requests/sec: 0.24

Status code distribution:
  [200] 7 responses
```

부하 테스트 2 — 동시 요청 8개 (continuous batching 의 효과):

```bash
hey -z 60s -c 8 \
  -m POST \
  -T application/json \
  -D /tmp/vllm-payload.json \
  http://localhost:8000/v1/chat/completions
```

**예상 출력 발췌**:

```
Summary:
  Total:        60.0xxx secs
  Slowest:      6.5xxx secs
  Fastest:      3.9xxx secs
  Average:      5.2xxx secs
  Requests/sec: 1.5

Status code distribution:
  [200] 91 responses
```

✅ **확인 포인트**:
- `c=1` 에서 RPS *0.24*, `c=8` 에서 RPS *1.5* — **약 6 배** 증가했습니다. 동시성 8배에 RPS 6배면 *continuous batching 이 GPU 활용률을 거의 그만큼 올렸다* 는 뜻 (이론상 최대 8배, 실제 5~6 배가 흔함).
- 동시 처리 중 메트릭 확인 (다른 터미널에서):

```bash
# 부하 중 (위 hey 가 도는 동안) 다른 터미널에서:
curl -s http://localhost:8000/metrics | grep -E "^vllm:(num_requests_running|num_requests_waiting|gpu_cache_usage_perc) "
```

**예상 출력**:

```
vllm:num_requests_running{model_name="microsoft/phi-2"} 6.0     ← 동시 6개 요청이 GPU 위에서 *동시에* 처리 (continuous batching)
vllm:num_requests_waiting{model_name="microsoft/phi-2"} 2.0     ← 2개는 KV cache 자리 부족으로 대기
vllm:gpu_cache_usage_perc{model_name="microsoft/phi-2"} 0.78    ← KV cache 78% 사용 중
```

✅ **확인 포인트**: `num_requests_running` 가 *1 보다 크다* 는 사실이 본 토픽의 핵심 검증입니다 — KServe HF 런타임 / 일반 PyTorch 서버는 1 (정적 배칭) 이거나 0/1 만 왔다 갔다. vLLM 이 *동시 6개* 를 GPU 위에서 처리한다는 것이 PagedAttention + continuous batching 의 *구체적 결과*.

```bash
rm /tmp/vllm-payload.json
```

## B-Step 7. 자주 하는 실수 재현

[vllm-mistake-cpu-only.yaml](../manifests/vllm-mistake-cpu-only.yaml) 을 적용해 *GPU 자원 누락 시* 어떤 양상으로 실패하는지 직접 확인합니다.

```bash
kubectl apply -f manifests/vllm-mistake-cpu-only.yaml
sleep 30
kubectl get pod -l app=vllm-phi2-mistake
```

**예상 출력 (30초~1분 후)**:

```
NAME                                READY   STATUS             RESTARTS   AGE
vllm-phi2-mistake-xxxxxxx-xxxxx     0/1     CrashLoopBackOff   2          ...
```

```bash
# 어떤 노드로 schedule 되었는지 — GKE 환경에선 GPU 노드 taint 때문에 일반 노드로 가야 정상
kubectl get pod -l app=vllm-phi2-mistake -o wide

# logs 로 vLLM 의 실패 이유 확인
kubectl logs deploy/vllm-phi2-mistake --tail=50
```

**예상 출력 (logs 발췌)**:

```
INFO ... Starting vLLM API server ...
INFO ... Initializing CUDA ...
ERROR ... RuntimeError: No CUDA GPUs are available
ERROR ... Engine process failed to start. See stack trace for the root cause.
Traceback (most recent call last):
  File "/usr/local/lib/python3.x/site-packages/vllm/...", line ..., in <module>
    ...
RuntimeError: No CUDA GPUs are available
```

✅ **확인 포인트**:
- Pod 가 *Pending 도 아니고 Running 도 아닌* CrashLoopBackOff 상태 — `nvidia.com/gpu` 누락의 까다로움이 여기서 보입니다.
- `kubectl describe pod` 의 events 를 봐도 *schedule 은 정상* 으로 표시됩니다 (taint 없는 일반 노드에 들어감) — events 만 보고는 진단이 안 되고, *logs 를 봐야* 진단 가능.
- 정상 매니페스트 (`vllm-phi2-deployment.yaml`) 와 mistake 매니페스트의 *3 군데 diff* (① `nvidia.com/gpu`, ② nodeSelector, ③ tolerations) 가 본 실수의 핵심 학습 포인트.

mistake 매니페스트 정리:

```bash
kubectl delete -f manifests/vllm-mistake-cpu-only.yaml
```

## B-Step 8. **GKE 클러스터 삭제** (가장 중요)

본 Step 을 *반드시* 실행해야 비용 청구가 멈춥니다. `gcloud container clusters delete` 명령 한 줄.

```bash
# port-forward 종료
kill $PF_PID 2>/dev/null

# 본 토픽 리소스 정리 (선택 — 클러스터 삭제 시 어차피 사라짐)
kubectl delete deploy,svc,pvc,secret -l phase=4,topic=03-vllm-llm-serving 2>/dev/null

# (위에서 ServiceMonitor 를 적용했다면) — kube-prometheus-stack 도 같이 정리되도록
helm uninstall kube-prometheus-stack -n monitoring 2>/dev/null

# ★ GKE 클러스터 자체 삭제 ★
gcloud container clusters delete $CLUSTER_NAME --zone=$ZONE --quiet
```

**예상 출력** (5분 소요):

```
Deleting cluster vllm-lab...
...done.
Deleted [https://container.googleapis.com/v1/projects/.../zones/us-central1-c/clusters/vllm-lab].
```

```bash
# 삭제 확인
gcloud container clusters list --filter="name=$CLUSTER_NAME"
```

**예상 출력**:

```
Listed 0 items.
```

✅ **확인 포인트**: `Listed 0 items.` — 클러스터가 GCP 에서 완전히 사라졌습니다. PD (PVC 가 백킹으로 사용했던 디스크) 도 클러스터 삭제 시 자동 삭제되지만, GCP Console > Compute Engine > Disks 에서 *고아 디스크* 가 남았는지 한 번 더 확인 권장.

```bash
# 고아 PD 확인 (있으면 수동 삭제 필요)
gcloud compute disks list --filter="name~vllm" 2>/dev/null
```

**Track B 완료**. lesson.md 의 검증 체크리스트로 돌아가, "Track B" 항목 5개 + "공통" 항목 3개에 체크하세요.

---

## 트러블슈팅 모음

| 증상 | 원인 | 해결 |
|------|------|------|
| `ImagePullBackOff` (vllm/vllm-openai) | Docker Hub rate limit 또는 이미지 태그 오타 | `kubectl describe pod` 의 events 확인. 5.5GB 이미지라 1차 풀에 5~10분 — 인내. rate limit 이면 Docker Hub 로그인 |
| Pod 가 `Pending` 으로 영원히 머묾 | GPU 자원 부족 (Phase 4/01 의 `Insufficient nvidia.com/gpu`) | `kubectl describe pod` events. GKE 라면 노드 자원 부족 — `gcloud container clusters resize` 또는 Spot 회수 가능성 |
| `RuntimeError: No CUDA GPUs are available` | 본 lab Step 7B 의 자주 하는 실수 1번. nodeSelector / GPU resource 누락 | 정상 매니페스트와 비교 |
| `torch.cuda.OutOfMemoryError` | `--gpu-memory-utilization` 너무 높음 (자주 하는 실수 3번), 다른 모델/프로세스가 GPU 사용 중 | utilization 0.85 → 0.80 으로 하향. `nvidia-smi` 로 다른 프로세스 점유 확인 |
| `Bus error` 또는 worker 멈춤 | `/dev/shm` 용량 부족 (자주 하는 실수 2번) | `volumes` 의 `shm` 의 `sizeLimit` 4Gi → 8Gi 로 상향 |
| 모델 다운로드 무한 재시도 | HF 토큰 만료 또는 rate limit, 네트워크 단절 | `kubectl logs` 의 error message 확인. gated 모델이면 `hf-secret` 의 `HF_TOKEN` 갱신 |
| Prometheus 의 `vllm-phi2` target 이 *DOWN* | ServiceMonitor 의 selector 와 Service 라벨 불일치 | `kubectl get svc vllm-phi2 -o yaml` 의 labels 와 ServiceMonitor 의 selector 비교. `app: vllm-phi2` 가 양쪽에 있어야 함 |
| GKE 클러스터 삭제가 *멈춤* | 디스크 또는 LoadBalancer 가 남아있음 | `gcloud compute disks list / forwarding-rules list` 로 잔존 자원 확인 후 수동 삭제 |

---

## 다음 단계

본 토픽이 *vLLM Deployment 한 장* 으로 LLM 서빙을 마쳤다면, 다음 토픽 [Phase 4 / 04 — Argo Workflows](../../04-argo-workflows/) (작성 예정) 는 *그 vLLM 위에서 흘러갈* RAG 인덱싱 파이프라인 (문서 → 임베딩 → Qdrant Upsert) 을 DAG 로 표현하는 법을 다룹니다. Argo 까지 끝나면 [⭐ 캡스톤](../../../capstone-rag-llm-serving/) 의 모든 빌딩 블록 (vLLM + KServe + Argo + Prometheus + GPU + HPA) 이 모이게 됩니다.
