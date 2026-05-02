# Phase 4 — ML on Kubernetes ⭐ (3–4주)

ML 엔지니어로서 진짜 가치를 발휘하는 영역. 도구가 많으니 **전부 다 배울 필요 없고**, 본인 업무에 가까운 1–2개를 깊게 파는 것을 추천합니다.

## 권장 토픽 분할

```
course/phase-4-ml-on-k8s/
├── README.md
├── 01-gpu/                     # NVIDIA Device Plugin, requests, MIG, Time-slicing
├── 02-kserve/                  # InferenceService로 모델 표준화 서빙
├── 03-vllm/                    # vLLM으로 LLM 서빙
├── 04-triton/                  # Triton Inference Server (멀티 프레임워크)
├── 05-kubeflow-training/       # PyTorchJob/TFJob (선택)
├── 06-kuberay/                 # Ray on K8s (분산 학습/튜닝)
└── 07-argo-workflows/          # ML 파이프라인 DAG
```

서빙 도구 비교는 `references/ml-serving-patterns.md` 참고.

## 학습 목표 (토픽별로 3–5개 선택)

### 4-1. GPU
- NVIDIA Device Plugin이 어떻게 GPU를 K8s에 노출하는지 이해한다
- Pod spec에 `nvidia.com/gpu: 1`을 명시할 수 있다
- 노드 셀렉터/taint+toleration으로 GPU 노드만 사용하게 할 수 있다
- MIG(Multi-Instance GPU)와 Time-slicing의 차이를 안다

### 4-2. KServe
- InferenceService 매니페스트로 HuggingFace/sklearn/PyTorch 모델을 서빙할 수 있다
- scale-to-zero를 활성화하고 cold start 트레이드오프를 이해한다
- Canary 배포로 v1/v2 트래픽 비율을 조절할 수 있다

### 4-3. vLLM
- vLLM Deployment로 SLM(예: phi-2)을 K8s에서 서빙할 수 있다
- OpenAI 호환 API로 클라이언트 코드를 그대로 쓴다
- GPU 메모리 사용률을 모니터링한다

### 4-4. Triton
- 모델 저장소 구조와 `config.pbtxt`를 작성할 수 있다
- 동적 배칭으로 GPU 활용도를 높인다

### 4-5/6/7. 학습 / 파이프라인
- PyTorchJob 또는 KubeRay로 분산 학습을 띄울 수 있다
- Argo Workflows로 데이터 → 학습 → 평가 → 배포 DAG을 정의한다

## ML 관점 도입 (Phase 4 README에 들어갈 내용)

이 단계가 K8s 학습의 종착지에 가깝습니다. ML 엔지니어가 K8s를 배우는 진짜 이유는:

1. **GPU 자원의 효율적 공유**: 비싼 GPU를 여러 모델/팀이 안전하게 나눠 쓰기
2. **모델 서빙 표준화**: KServe로 모든 모델을 같은 인터페이스로 노출
3. **LLM 서빙 최적화**: vLLM의 PagedAttention, continuous batching을 K8s 위에서
4. **재현 가능한 학습**: 같은 매니페스트로 어디서든 같은 학습 환경

## 핵심 토픽 상세

### 4-1. GPU on Kubernetes (필수, 다른 토픽의 전제)

**설치**:
- 클라우드 (GKE/EKS/AKS)는 GPU 노드 풀 만들면 자동 설치
- 로컬은 GPU 없으면 클라우드 임시 클러스터 사용 권장

**Pod 사용**:
```yaml
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  cloud.google.com/gke-accelerator: nvidia-tesla-t4
```

**고급 주제** (시간 되면):
- **MIG**: A100/H100을 7개로 분할 (하드웨어 격리)
- **Time-slicing**: 단일 GPU를 여러 Pod이 시분할 (격리 약함, 비용 ↓)

### 4-2. KServe

**설치** (Knative + KServe):
```bash
# 공식 quick install 스크립트 사용 권장
curl -s "https://raw.githubusercontent.com/kserve/kserve/release-0.14/hack/quick_install.sh" | bash
```

**HuggingFace 모델 서빙**:
```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: sentiment
spec:
  predictor:
    minReplicas: 0      # scale-to-zero
    maxReplicas: 5
    model:
      modelFormat:
        name: huggingface
      args:
      - --model_id=cardiffnlp/twitter-roberta-base-sentiment
      resources:
        limits:
          cpu: "2"
          memory: 4Gi
```

**호출**:
```bash
curl -H "Host: sentiment.default.example.com" http://<ingress>/v1/models/sentiment:predict -d '{"instances":["I love this!"]}'
```

### 4-3. vLLM

**Deployment**:
```yaml
spec:
  containers:
  - name: vllm
    image: vllm/vllm-openai:latest
    args:
    - --model=microsoft/phi-2
    - --gpu-memory-utilization=0.9
    resources:
      limits:
        nvidia.com/gpu: 1
    ports:
    - containerPort: 8000
```

**OpenAI 호환 호출**:
```python
from openai import OpenAI
client = OpenAI(base_url="http://vllm-svc:8000/v1", api_key="dummy")
client.chat.completions.create(model="microsoft/phi-2", messages=[...])
```

### 4-4. Triton

**모델 저장소** (`/models/sentiment/1/model.pt` + `config.pbtxt`):
```
name: "sentiment"
platform: "pytorch_libtorch"
max_batch_size: 32
input [{ name: "input_ids", data_type: TYPE_INT64, dims: [-1] }]
output [{ name: "logits", data_type: TYPE_FP32, dims: [3] }]
dynamic_batching {}
```

PVC로 모델 저장소 마운트 또는 init container로 다운로드.

### 4-5. Kubeflow Training Operator

```yaml
apiVersion: kubeflow.org/v1
kind: PyTorchJob
metadata:
  name: distributed-train
spec:
  pytorchReplicaSpecs:
    Master:
      replicas: 1
      template:
        spec:
          containers:
          - name: pytorch
            image: my-train:0.1
            resources: { limits: { nvidia.com/gpu: 1 } }
    Worker:
      replicas: 3
      template: ...
```

### 4-6. KubeRay

```bash
helm install kuberay-operator kuberay/kuberay-operator -n kuberay --create-namespace
```

`RayCluster` CRD로 Ray 클러스터 생성, `RayJob`으로 작업 제출. 분산 학습/하이퍼파라미터 튜닝/RLHF에 강함.

### 4-7. Argo Workflows

DAG 정의:
```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
spec:
  entrypoint: ml-pipeline
  templates:
  - name: ml-pipeline
    dag:
      tasks:
      - name: download-data
        template: download
      - name: train
        dependencies: [download-data]
        template: train
      - name: evaluate
        dependencies: [train]
        template: eval
```

## 자주 하는 실수

- GPU Pod인데 `nvidia.com/gpu: 1` 빠뜨림 → CPU 노드에 떨어져서 무한 OOM
- KServe scale-to-zero 켜고 SLA 검토 안 함 → 첫 요청 30초+
- vLLM `--gpu-memory-utilization`을 1.0에 가깝게 → 다른 프로세스 메모리와 충돌
- Triton `dynamic_batching` 누락 → 처리량 절반 이하
- Kubeflow PyTorchJob에 `cleanPodPolicy` 안 정함 → 학습 끝나도 Pod 안 사라져 GPU 점유

## 검증 명령어

```bash
# GPU 노드/리소스 확인
kubectl describe node <gpu-node> | grep -A2 nvidia.com/gpu

# KServe
kubectl get inferenceservice
kubectl describe inferenceservice sentiment

# vLLM
kubectl logs deploy/vllm-phi2
curl http://vllm:8000/v1/models

# 부하 테스트 (LLM)
hey -z 30s -c 5 -m POST -T application/json \
  -d '{"model":"microsoft/phi-2","messages":[{"role":"user","content":"hi"}]}' \
  http://vllm:8000/v1/chat/completions
```

## 다음 단계

캡스톤 프로젝트(RAG 챗봇 + LLM 서빙)에서 Phase 4의 도구들(vLLM, KServe, Argo, HPA)을 통합 활용합니다. `references/capstone-rag-llm.md` 참고.
