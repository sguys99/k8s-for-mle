# Day 4 — vLLM Deployment + OpenAI 호환 API 호출 검증

> **상위 lesson**: [`../lesson.md`](../lesson.md) §2.1 vLLM 분리 트레이드오프, §4.3 vLLM Deployment 매니페스트 해설
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 4
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §3.8 vLLM 결정 노트 (cold start / GPU 노드 풀 / served-model-name)
> **이전 단계**: [`day-03-indexing-argo.md`](day-03-indexing-argo.md)
> **소요 시간**: 2 ~ 3 시간 (T4 노드 풀 추가 5~7 분, 모델 다운로드 5~10 분, 검증 30 분, 두 번째 기동 검증 5 분, 정리 5 분)

---

## 🎯 Goal

Day 4 를 마치면 다음 4 가지가 충족됩니다.

- 기존 캡스톤 GKE 클러스터(Day 1~3 의 `capstone`) 에 **T4 노드 풀 1 노드를 추가**해 GPU 워크로드(vLLM) 와 CPU 워크로드(Qdrant / Argo) 를 같은 클러스터에서 분리 운영
- Phase 4-3 의 vLLM 매니페스트 4 종(Deployment / PVC / Service / HF Secret) 을 캡스톤 namespace `rag-llm` 으로 이식하고 **`--served-model-name=microsoft/phi-2`** 명시 → Day 5/6 RAG API 가 호출할 안정 모델 ID 확정
- vLLM Pod 의 **첫 기동 5~10 분** 동안 startupProbe(`failureThreshold=60`) 가 livenessProbe 를 보호하고, **두 번째 기동부터는 PVC `vllm-model-cache` 가 30 초 안에 ready** 로 만드는 흐름을 직접 확인
- `kubectl port-forward` + `curl /v1/models` + Python OpenAI SDK 의 `/v1/chat/completions` 두 검증 경로로 vLLM 의 OpenAI 호환 응답을 받고, 응답 JSON 의 `model` 필드가 `microsoft/phi-2` 임을 확인 → Day 5/6 와의 호환성 보증

---

## 🔧 사전 조건

- **Day 1~3 완료**: Qdrant `qdrant-0` Pod Running. Argo controller 는 `suspend` 상태(GPU 비용 절감) 또는 정리됨이어도 무관.
  ```bash
  kubectl get pod qdrant-0 -n rag-llm
  # → qdrant-0   1/1   Running   0   ...
  ```
- **GKE 캡스톤 클러스터 존재**:
  ```bash
  gcloud container clusters describe capstone --zone us-central1-a --format='value(name,status)'
  # → capstone   RUNNING
  ```
- **HuggingFace 계정 (옵션)**: phi-2 는 public 이라 토큰 없이 동작합니다. anonymous rate limit 도달 시 또는 gated 모델로 교체 시에만 [HuggingFace > Settings > Access Tokens](https://huggingface.co/settings/tokens) 에서 read 권한 토큰 발급.
- **로컬 도구**: `kubectl`, `gcloud`, `jq`, `python3` (3.10+), `pip install openai` (Step 8 검증용).
- **GPU quota 확인**: GCP 프로젝트의 `NVIDIA_T4_GPUS` 쿼터가 1 이상이어야 합니다. 신규 GCP 계정은 기본 0 일 수 있어 [GCP Quotas](https://console.cloud.google.com/iam-admin/quotas?service=compute.googleapis.com&filter=NVIDIA_T4) 에서 한도 확인 후 부족하면 증액 요청(보통 24h).
- **작업 디렉토리**: 본 lab 의 모든 명령은 **프로젝트 루트**(`k8s-for-mle/`) 에서 실행합니다.

> 💰 **GKE T4 비용 박스 (꼭 읽기)**
>
> - **T4 1 노드 시간당 ≈ \$0.35** (us-central1-a 기준, vCPU + GPU + 디스크 합산). Day 4 단독 진행 약 2~3 시간 = **\$0.7~1.0**.
> - **Day 4 만 끝내고 Day 5 로 안 갈 때**: §🧹 정리 (c) 의 `gcloud container node-pools resize gpu-pool --num-nodes=0` 를 *반드시* 실행해 시간당 0 으로 떨어뜨립니다. size=0 → 1 복원은 5 분 안에 가능.
> - **Day 5~10 까지 이어서 진행할 때**: GPU 노드 풀을 그대로 두는 것이 자연스럽지만, 진행 중간 휴식 시간에는 size=0 으로 축소.
> - **클러스터 자체 삭제는 Day 10 마지막**: capstone-plan §11 위험 관리 항목.

---

## 🚀 Steps

### Step 1. T4 노드 풀 추가

```bash
gcloud container node-pools create gpu-pool \
  --cluster=capstone --zone=us-central1-a \
  --machine-type=n1-standard-4 \
  --accelerator=type=nvidia-tesla-t4,count=1,gpu-driver-version=default \
  --num-nodes=1 \
  --node-taints=nvidia.com/gpu=present:NoSchedule \
  --enable-autoupgrade --enable-autorepair
```

**예상 출력 (5~7 분 후 마지막 줄):**

```
Created [https://container.googleapis.com/v1/projects/<your-project>/zones/us-central1-a/clusters/capstone/nodePools/gpu-pool].
NAME      MACHINE_TYPE   DISK_SIZE_GB  NODE_VERSION
gpu-pool  n1-standard-4  100           1.30.x-gke.xxxx
```

확인:

```bash
kubectl get nodes -L cloud.google.com/gke-accelerator
```

**예상 출력:**

```
NAME                                       STATUS   ROLES    AGE     VERSION         GKE-ACCELERATOR
gke-capstone-default-pool-xxxx-yyyy        Ready    <none>   3d      v1.30.x         <none>
gke-capstone-default-pool-xxxx-zzzz        Ready    <none>   3d      v1.30.x         <none>
gke-capstone-gpu-pool-xxxx-aaaa            Ready    <none>   2m      v1.30.x         nvidia-tesla-t4
```

✅ **확인 포인트**: `GKE-ACCELERATOR` 컬럼에 `nvidia-tesla-t4` 가 표시된 노드 1 개 추가. taint 도 함께 확인:

```bash
kubectl get nodes -o jsonpath='{range .items[?(@.spec.taints)]}{.metadata.name}{"\t"}{.spec.taints}{"\n"}{end}'
```

`nvidia.com/gpu=present:NoSchedule` 가 GPU 노드에만 보이면 OK.

> 💡 **autoupgrade 트레이드오프**: `--enable-autoupgrade` 가 켜지면 GKE 가 노드를 주기적으로 갱신합니다. Day 4 진행 중 노드가 갱신되면 vLLM Pod 가 재시작되며 cold start 5~10 분이 다시 발생할 수 있어 학습 흐름을 끊을 수 있습니다. *Day 5~10 동안* 안정성이 필요하면 일시적으로 `gcloud container node-pools update gpu-pool --no-enable-autoupgrade` 로 끄고, 캡스톤 종료 후 다시 켭니다.

### Step 2. NVIDIA device plugin 동작 확인

GKE 는 GPU 노드 풀 생성 시 `nvidia-gpu-device-plugin` DaemonSet 을 자동으로 배포합니다. Day 4 학습자가 `--accelerator=...gpu-driver-version=default` 옵션을 줬다면 GPU 드라이버도 함께 설치됩니다.

```bash
kubectl get ds -n kube-system nvidia-gpu-device-plugin-large-cos
```

**예상 출력:**

```
NAME                                   DESIRED   CURRENT   READY   NODE SELECTOR              AGE
nvidia-gpu-device-plugin-large-cos     1         1         1       <gke-internal-selector>    2m
```

`READY=1` 이 보이면 device plugin 이 GPU 노드 위에서 GPU 자원을 광고 중입니다. 노드 자체에서 광고를 확인:

```bash
kubectl describe node $(kubectl get nodes -l cloud.google.com/gke-accelerator=nvidia-tesla-t4 -o name) | grep -A2 "Capacity\|Allocatable" | grep -E "nvidia.com/gpu"
```

**예상 출력:**

```
  nvidia.com/gpu:     1
  nvidia.com/gpu:     1
```

✅ **확인 포인트**: Capacity 와 Allocatable 양쪽에 `nvidia.com/gpu: 1` 이 보이면 매니페스트의 `requests/limits.nvidia.com/gpu: 1` 가 매칭될 준비 완료.

### Step 3. (옵션) HF Secret 적용

phi-2 는 HuggingFace public 이라 **본 Step 은 건너뛰어도 정상 동작**합니다. 토큰을 적용하는 두 시나리오 (rate limit 도달 / gated 모델) 만 아래 절차 진행.

```bash
# 매니페스트의 placeholder 를 본인 HF 토큰으로 임시 치환 (커밋 X)
HF_TOKEN_VALUE='hf_your_real_token_here'   # ← 본인 토큰으로 교체
sed -i.bak "s|REPLACE_WITH_YOUR_HF_TOKEN_OR_LEAVE_EMPTY|${HF_TOKEN_VALUE}|" \
  course/capstone-rag-llm-serving/manifests/23-vllm-hf-secret.yaml

kubectl apply -f course/capstone-rag-llm-serving/manifests/23-vllm-hf-secret.yaml
```

**예상 출력:**

```
secret/hf-secret created
```

작업 후 매니페스트를 placeholder 상태로 즉시 복원:

```bash
git checkout course/capstone-rag-llm-serving/manifests/23-vllm-hf-secret.yaml
rm -f course/capstone-rag-llm-serving/manifests/23-vllm-hf-secret.yaml.bak
```

✅ **확인 포인트**: `kubectl get secret hf-secret -n rag-llm` 가 존재. 미적용한 학습자는 다음 Step 으로 진행.

### Step 4. 모델 캐시 PVC 적용

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/21-vllm-pvc.yaml
kubectl get pvc -n rag-llm vllm-model-cache
```

**예상 출력:**

```
persistentvolumeclaim/vllm-model-cache created

NAME               STATUS    VOLUME   CAPACITY   ACCESS MODES   STORAGECLASS   AGE
vllm-model-cache   Pending                                      standard       3s
```

✅ **확인 포인트**: GKE 의 `standard` storageClass 는 **WaitForFirstConsumer** 모드라 *Pod 가 PVC 에 마운트할 때까지* `Pending` 이 정상입니다. Step 5 후 `Bound` 로 전환됩니다.

> 💡 **Pending 이 아닌 Lost / 즉시 Bound 시도**: 다른 storageClass(예: `standard-rwo`) 가 default 인 클러스터라면 즉시 Bound 될 수 있습니다. 둘 다 정상 — Day 4 진행에 무관.

### Step 5. vLLM Deployment + Service 적용

```bash
kubectl apply \
  -f course/capstone-rag-llm-serving/manifests/20-vllm-deployment.yaml \
  -f course/capstone-rag-llm-serving/manifests/22-vllm-service.yaml
```

**예상 출력:**

```
deployment.apps/vllm created
service/vllm created
```

즉시 Pod schedule 진행 관찰:

```bash
kubectl get pods -n rag-llm -l app=vllm -w
```

**예상 출력 시퀀스 (~30 초):**

```
NAME                    READY   STATUS              RESTARTS   AGE
vllm-xxxxxxxxxx-yyyyy   0/1     Pending             0          5s
vllm-xxxxxxxxxx-yyyyy   0/1     ContainerCreating   0          15s
vllm-xxxxxxxxxx-yyyyy   0/1     Running             0          30s    ← startupProbe 시작 (10 분 한도)
```

✅ **확인 포인트**: Pod 가 GPU 노드(`gke-capstone-gpu-pool-...`) 에 schedule 되었는지 확인:

```bash
kubectl get pod -n rag-llm -l app=vllm -o wide
# → NODE 컬럼이 gke-capstone-gpu-pool-xxxx-aaaa
```

CPU 노드(`gke-capstone-default-pool-...`) 에 schedule 되었으면 자주 하는 실수 ⑩ — taint 누락. Step 1 의 `--node-taints` 옵션 확인.

### Step 6. 모델 다운로드 + GPU 로딩 대기

`Ctrl+C` 로 watch 종료 후 logs 로 startupProbe 진행 관찰:

```bash
kubectl logs -n rag-llm -l app=vllm -f
```

**예상 로그 시퀀스 (총 5~10 분):**

```
INFO 05-07 14:23:11 api_server.py:262] vLLM API server version 0.6.6.post1
INFO 05-07 14:23:12 api_server.py:539] Started engine with config: ...
... (HF Hub 다운로드 시작)
Downloading shards: 0%|          | 0/2 [00:00<?, ?it/s]
Downloading shards: 50%|█████     | 1/2 [02:14<02:14, 134.32s/it]
Downloading shards: 100%|██████████| 2/2 [04:28<00:00, 134.40s/it]
... (가중치 GPU 로딩)
INFO 05-07 14:28:01 model_runner.py:1014] Loading model weights took 5.27 GB
... (KV cache 할당)
INFO 05-07 14:28:32 worker.py:228] # GPU blocks: 1024, # CPU blocks: 512
INFO 05-07 14:28:35 api_server.py:280] Started server process [1]
INFO 05-07 14:28:35 api_server.py:281] Waiting for application startup.
INFO 05-07 14:28:36 api_server.py:285] Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

`Uvicorn running on http://0.0.0.0:8000` 라인이 보이면 startupProbe 가 통과됩니다. `Ctrl+C` 로 logs 종료 후 Pod 상태 확인:

```bash
kubectl get pod -n rag-llm -l app=vllm
```

**예상 출력:**

```
NAME                    READY   STATUS    RESTARTS   AGE
vllm-xxxxxxxxxx-yyyyy   1/1     Running   0          7m
```

✅ **확인 포인트**: `READY 1/1` + `RESTARTS 0`. PVC 가 Bound 상태로 전환됐는지도 확인:

```bash
kubectl get pvc -n rag-llm vllm-model-cache
# → STATUS=Bound
```

### Step 7. `curl /v1/models` 검증 — served-model-name 확인

```bash
# 백그라운드 port-forward (이후 Step 8/9 에서도 재사용)
kubectl port-forward -n rag-llm svc/vllm 8000:8000 >/dev/null 2>&1 &
sleep 2

curl -s http://localhost:8000/v1/models | jq
```

**예상 출력:**

```json
{
  "object": "list",
  "data": [
    {
      "id": "microsoft/phi-2",
      "object": "model",
      "created": 1746623215,
      "owned_by": "vllm",
      "root": "microsoft/phi-2",
      "parent": null,
      "permission": [...]
    }
  ]
}
```

✅ **확인 포인트**: `data[0].id` 가 정확히 `microsoft/phi-2` (Day 4 §4.3 결정 박스 ②). 다른 값이면 매니페스트의 `--served-model-name` 라인 누락.

> 💡 **이 ID 가 Day 5/6 의 `OPENAI_MODEL` env 가 됩니다** — 캡스톤 §10 자주 하는 실수 ⑪번이 강조하듯, Day 5/6 작성 시 *완전 동일 문자열* 로 복사. 한 글자라도 다르면 RAG API 의 `/chat` 호출이 404 로 떨어집니다.

### Step 8. OpenAI Python SDK 로 `/v1/chat/completions` 호출

vLLM 의 OpenAI 호환 API 를 표준 OpenAI SDK 로 호출 — Day 5/6 의 RAG API 가 같은 패턴을 그대로 사용합니다.

```bash
pip install openai

python3 - <<'PY'
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="not-used",                       # vLLM 은 인증 미강제
)

resp = client.chat.completions.create(
    model="microsoft/phi-2",                  # ← Step 7 의 served name 과 동일
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is Kubernetes in one sentence?"},
    ],
    max_tokens=80,
    temperature=0.7,
)

print("model:", resp.model)
print("answer:", resp.choices[0].message.content)
print("tokens:", resp.usage.prompt_tokens, "+", resp.usage.completion_tokens)
PY
```

**예상 출력 (응답 텍스트는 모델/seed 에 따라 다름):**

```
model: microsoft/phi-2
answer: Kubernetes is an open-source container orchestration platform that automates the deployment, scaling, and management of containerized applications across clusters of hosts.
tokens: 28 + 32
```

✅ **확인 포인트**: `model` 응답값이 `microsoft/phi-2`, `answer` 가 자연어 1 문장 이상. **Day 5/6 RAG API 가 이 코드 블록을 거의 그대로 import 합니다** — `base_url` 만 클러스터 내부 DNS 로 바뀜.

`curl` 로도 같은 호출이 가능합니다 (참고용):

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "microsoft/phi-2",
    "messages": [{"role":"user","content":"Hello"}],
    "max_tokens": 50
  }' | jq '.choices[0].message.content'
```

### Step 9. 두 번째 기동 검증 — 모델 캐시 PVC 효과

Pod 재시작 시 첫 기동의 5~10 분이 30 초 안으로 줄어드는지 직접 확인 — 운영의 *rolling update 가용성* 이 PVC 캐시에 의존함을 체감하는 단계입니다.

```bash
# 백그라운드 port-forward 종료 (Pod 재시작 후 재연결 필요)
pkill -f 'kubectl.*port-forward.*svc/vllm' 2>/dev/null

# Deployment rollout restart — 새 Pod 가 기존 PVC 를 그대로 마운트
kubectl rollout restart deployment/vllm -n rag-llm

# 새 Pod 의 ready 시간 측정 (--watch 로 30 초 안에 1/1 까지 진행)
time kubectl rollout status deployment/vllm -n rag-llm --timeout=120s
```

**예상 출력:**

```
Waiting for deployment "vllm" rollout to finish: 1 old replicas are pending termination...
deployment "vllm" successfully rolled out

real    0m38.521s        ← 30 초 ~ 1 분 (첫 기동 5~10 분의 1/10)
user    0m0.123s
sys     0m0.087s
```

logs 로 확인 — *Downloading shards* 라인이 *없어야 합니다*:

```bash
kubectl logs -n rag-llm -l app=vllm --tail=50 | grep -E "Downloading|Loading model weights|Uvicorn running"
```

**예상 출력:**

```
INFO ... model_runner.py:1014] Loading model weights took 5.27 GB
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

✅ **확인 포인트**: `Downloading shards` 라인이 안 보임 (PVC 캐시 hit). `Loading model weights` 만 보이고 30~60 초 안에 `Uvicorn running` 도달.

port-forward 재기동 후 마지막 검증:

```bash
kubectl port-forward -n rag-llm svc/vllm 8000:8000 >/dev/null 2>&1 &
sleep 2
curl -s http://localhost:8000/v1/models | jq '.data[0].id'
# → "microsoft/phi-2"
```

---

## ✅ 검증 체크리스트

다음 8 항목을 모두 만족하면 Day 4 가 완료된 것입니다.

- [ ] `kubectl get nodes -L cloud.google.com/gke-accelerator` 에 `nvidia-tesla-t4` 라벨 노드 1 개
- [ ] GPU 노드의 taint 가 `nvidia.com/gpu=present:NoSchedule`
- [ ] `kubectl get pod -l app=vllm -n rag-llm` 가 `Running 1/1`, GPU 노드(`gke-capstone-gpu-pool-...`) 에 schedule
- [ ] `kubectl get pvc vllm-model-cache -n rag-llm` 가 `Bound`
- [ ] `curl http://localhost:8000/v1/models | jq '.data[0].id'` 응답이 `"microsoft/phi-2"` (served-model-name 명시 확인)
- [ ] OpenAI Python SDK (`from openai import OpenAI`) 로 `/v1/chat/completions` 호출 시 `choices[0].message.content` 가 자연어 1 문장 이상
- [ ] `kubectl rollout restart deployment/vllm` 후 ready 시간이 **60 초 이내** (PVC 캐시 효과)
- [ ] `kubectl logs -l app=vllm --tail=50` 의 두 번째 기동 로그에 `Downloading shards` 라인이 *없음*

---

## 🧹 정리

**(a) Day 5 로 바로 이어서 진행하는 경우** — vLLM Deployment / Service / PVC / GPU 노드 풀을 그대로 둡니다. Day 5 의 RAG API 가 `vllm.rag-llm.svc.cluster.local:8000` 을 호출합니다.

**(b) Day 4 만 단독으로 종료** (학습 결과는 보존):

```bash
# port-forward 종료
pkill -f 'kubectl.*port-forward.*svc/vllm' 2>/dev/null

# vLLM 리소스 삭제 (Deployment + Service)
kubectl delete -f course/capstone-rag-llm-serving/manifests/22-vllm-service.yaml
kubectl delete -f course/capstone-rag-llm-serving/manifests/20-vllm-deployment.yaml

# (선택) HF Secret 정리
kubectl delete -f course/capstone-rag-llm-serving/manifests/23-vllm-hf-secret.yaml --ignore-not-found

# PVC 는 데이터 보호로 자동 삭제 안 됨 — 명시적 삭제
kubectl delete pvc vllm-model-cache -n rag-llm
```

**(c) GPU 노드 풀 size=0 으로 축소** (시간당 비용 0, 5 분 안에 복원 가능):

```bash
gcloud container node-pools resize gpu-pool \
  --cluster=capstone --zone=us-central1-a \
  --num-nodes=0 --quiet
```

> 💰 **꼭 실행하세요** — Day 5 로 이어가지 않을 때 size=0 을 빠뜨리면 시간당 \$0.35 가 계속 청구됩니다.

**(d) GPU 노드 풀 영구 삭제** (다시 만들 때 5~7 분 재생성 필요):

```bash
gcloud container node-pools delete gpu-pool \
  --cluster=capstone --zone=us-central1-a --quiet
```

**(e) 캡스톤 클러스터 자체 삭제** — Day 10 마지막에 일괄 정리. capstone-plan §11 위험 관리 항목 참조.

---

## 🚨 막힐 때 (트러블슈팅)

| 증상 | 원인 | 해결 |
|---|---|---|
| Step 1 노드 풀 생성 시 `quota 'NVIDIA_T4_GPUS' exceeded` | GCP 프로젝트의 T4 쿼터 0 또는 부족 | [GCP Quotas](https://console.cloud.google.com/iam-admin/quotas) 에서 `NVIDIA_T4_GPUS` 한도 1 이상으로 증액 요청. 신규 계정은 보통 24h 처리 |
| Step 5 후 Pod 가 `Pending` 으로 멈춤 (`0/3 nodes are available: ... untolerated taint {nvidia.com/gpu: present}`) | 매니페스트의 `tolerations` 키 또는 effect 가 노드 taint 와 불일치 | 노드 taint 확인: `kubectl get nodes -o jsonpath='{range .items[*]}{.spec.taints}{"\n"}{end}'`. 매니페스트의 `tolerations.key=nvidia.com/gpu, operator=Exists, effect=NoSchedule` 정확히 일치 |
| Pod 가 CPU 노드에 schedule 되어 `RuntimeError: No CUDA GPUs are available` | Step 1 의 `--node-taints` 옵션 누락으로 GPU 노드 풀에 taint 없음 (자주 하는 실수 ⑩) | `gcloud container node-pools describe gpu-pool --cluster capstone --format='value(config.taints)'` 로 taint 확인. 누락 시 `gcloud container node-pools update gpu-pool --node-taints=...` 또는 노드 풀 재생성 |
| startupProbe 60 회 실패 후 CrashLoopBackOff | 학습자 네트워크가 느려 5GB 다운로드가 10 분 초과 | 매니페스트의 `startupProbe.failureThreshold: 60` → `90` (15 분 한도) 으로 임시 상향 후 `kubectl apply`. 다운로드 완료 후 다시 60 으로 복원 가능 |
| logs 에 `torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate ...` | `--gpu-memory-utilization=0.85` 가 다른 GPU 점유 프로세스와 충돌 (Phase 4-3 자주 하는 실수 3번) | T4 16GB 에는 0.80~0.85 가 안전. `kubectl exec deploy/vllm -- nvidia-smi` 로 GPU 위 다른 프로세스 확인. 충돌 없음에도 OOM 이면 0.75 로 하향 |
| Pod 시작 후 `Bus error` 또는 worker 응답 없음 | `/dev/shm` 마운트 누락 또는 sizeLimit 부족 (Phase 4-3 자주 하는 실수 2번) | 본 매니페스트의 `volumes.shm.emptyDir.sizeLimit: 4Gi` 가 적용됐는지 `kubectl describe pod -l app=vllm \| grep -A5 shm` 로 확인. 7B+ 모델로 교체 시 8Gi+ 로 상향 |
| Step 7 `curl /v1/models` 가 응답 X 또는 timeout | port-forward 가 끊겼거나 Pod 가 ready 전 | `kubectl get pod -l app=vllm` 가 `1/1 Running` 인지, `kubectl logs --tail=20` 에 `Uvicorn running` 이 보이는지 확인. port-forward 재실행: `kubectl port-forward svc/vllm 8000:8000 -n rag-llm` |
| Step 7 응답의 `data[0].id` 가 `microsoft/phi-2` 가 아닌 다른 값 | 매니페스트의 `--served-model-name=microsoft/phi-2` 라인 누락 또는 다른 값 | `grep served-model-name course/capstone-rag-llm-serving/manifests/20-vllm-deployment.yaml` 확인. 수정 후 `kubectl apply -f ... && kubectl rollout restart deployment/vllm` |
| Step 8 OpenAI SDK 호출 시 `model 'phi-2' does not exist` (대소문자 다름) | SDK 호출의 `model=` 값이 served name 과 다름 (자주 하는 실수 ⑪ 미리 발생) | Step 7 의 `data[0].id` 응답값을 *복사하여 그대로* model 파라미터에 사용 |
| Step 9 두 번째 기동에 다시 `Downloading shards` 라인 출현 | PVC 가 Bound 가 아니거나 mountPath 불일치 | `kubectl get pvc vllm-model-cache -n rag-llm` Bound 확인. 매니페스트의 `volumeMounts.mountPath: /root/.cache/huggingface` 가 vLLM 0.6+ 의 `HF_HOME` env 와 일치하는지 확인 |
| `ImagePullBackOff` (`vllm/vllm-openai:v0.6.6.post1` 가 안 받아짐) | DockerHub rate limit 또는 일시적 GHCR 장애 | `kubectl describe pod` 의 Events 에서 정확한 에러 확인. `vllm/vllm-openai:v0.6.5` 또는 `v0.6.4.post1` 같은 인접 버전으로 임시 교체 후 다시 시도 |

---

## 다음 단계

➡️ Day 5 — RAG API 구현 (retriever + LLM 호출 결합) — 작성 예정

본 lab 에서 만든 vLLM Service DNS `vllm.rag-llm.svc.cluster.local:8000` 가 Day 5 의 RAG API 의 **`OPENAI_BASE_URL`** env 가 됩니다. Step 8 의 OpenAI SDK 코드 블록은 RAG API 의 `llm_client.py` 핵심 함수에 거의 그대로 옮겨집니다 — `base_url` 만 클러스터 내부 DNS 로 바꾸고, system prompt 에 retriever 결과를 끼워 넣는 한 줄이 추가됩니다.

> 참고: Day 5 부터는 GPU 노드 풀이 *유지된 상태* 에서 RAG API 개발(로컬 → 클러스터) 이 진행됩니다. Day 4 §🧹 정리 (c) `size=0` 은 Day 5 로 이어가지 *않을* 때만 실행합니다.
