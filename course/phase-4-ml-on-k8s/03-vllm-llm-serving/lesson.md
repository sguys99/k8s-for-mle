# Phase 4 / 03 — vLLM LLM Serving (microsoft/phi-2, OpenAI 호환 API)

> **Phase**: 4 — ML on Kubernetes
> **소요 시간**: 3~4시간 (Track B GPU 모델 다운로드 5~10분 포함, 부하 테스트 30분)
> **선수 학습**: [Phase 4/01 — GPU on Kubernetes](../01-gpu-on-k8s/lesson.md) (GPU 자원 패턴), [Phase 4/02 — KServe InferenceService](../02-kserve-inference/lesson.md) (서빙 표준 추상화), [Phase 3/02 — Prometheus Grafana](../../phase-3-production/02-prometheus-grafana/lesson.md) (ServiceMonitor — 옵션), [Phase 3/03 — Autoscaling HPA](../../phase-3-production/03-autoscaling-hpa/lesson.md) (`hey` 부하 테스트 도구 — 옵션)
>
> 직전 토픽 [02-kserve-inference](../02-kserve-inference/lesson.md) 가 sentiment 분류 모델을 KServe 한 매니페스트로 표준화했다면, 본 토픽은 *그 표준 추상화로 다 담을 수 없는* LLM 특화 요구사항 — PagedAttention / KV cache / continuous batching / OpenAI 호환 API — 을 vLLM Deployment 로 정면 돌파합니다. **본 토픽이 코스 전체의 모델 전환 지점입니다**: Phase 0 부터 4-2 까지 누적 프로젝트의 주인공이었던 `cardiffnlp/twitter-roberta-base-sentiment` (~500MB, CPU OK) 가 본 토픽부터 캡스톤까지 `microsoft/phi-2` (2.7B, GPU 필수) 로 바뀝니다.

---

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

1. **vLLM Deployment 매니페스트로 `microsoft/phi-2` 를 K8s 위에서 OpenAI 호환 API 로 서빙합니다.** Phase 4/01 의 GPU 격리 3종(`nvidia.com/gpu` + nodeSelector + toleration) 위에 vLLM 핵심 옵션 5종(`--model`, `--gpu-memory-utilization`, `--max-model-len`, `--port`, `--dtype`) 을 얹어, `/v1/chat/completions` 호출이 자연어 응답을 반환하는 데까지 완성합니다.
2. **PagedAttention / continuous batching / KV cache 가 GPU 메모리·처리량에 미치는 효과를 메트릭으로 관찰합니다.** vLLM 이 `/metrics` 로 노출하는 `vllm:num_requests_running`, `vllm:gpu_cache_usage_perc`, `vllm:time_to_first_token_seconds` 를 Prometheus(Phase 3/02) 로 수집해, `hey` 부하 테스트 중 어떻게 변하는지 직접 확인합니다.
3. **"왜 이 LLM 은 KServe 가 아니라 vLLM 인가" 의 근거를 정리합니다.** KServe HuggingFace 런타임이 LLM 처리량/메모리 면에서 vLLM 에 밀리는 이유, OpenAI 호환 API 가 캡스톤의 RAG API 코드를 단순하게 만드는 효과, vLLM 한계와 대안(TGI / Triton+TensorRT-LLM / Ollama) 의 자리매김.
4. **vLLM 서빙에서 자주 하는 실수 3종을 시연·재현합니다.** `nvidia.com/gpu` 누락(Pending 도 정상도 아닌 까다로운 실패), `/dev/shm` 누락(CUDA IPC 공유 메모리 부족 → "Bus error"), `--gpu-memory-utilization` 0.95+ (KV cache OOM) 가 어떤 로그/이벤트를 만드는지 직접 확인.

**완료 기준 (1줄)**: Track B 학습자는 GKE T4 클러스터에서 `kubectl get pod -l app=vllm-phi2` 가 `Running`, OpenAI 호환 호출 `curl http://localhost:8000/v1/chat/completions -d '{"model":"microsoft/phi-2","messages":[{"role":"user","content":"Hello"}]}'` 가 200 OK + 자연어 응답을 반환하고 **클러스터 삭제** 까지 끝나야 통과. Track A 학습자는 minikube 에서 vLLM CPU 빌드 이미지로 `facebook/opt-125m` 스모크 테스트가 200 OK 를 반환하고 GPU 매니페스트가 `kubectl apply --dry-run=server` 를 통과해야 통과.

---

## 왜 ML 엔지니어에게 vLLM 이 필요한가

직전 토픽 02-kserve 에서 우리는 `sentiment` 분류 모델을 InferenceService 한 매니페스트로 표준화했습니다. 그 표준 추상화의 매력은 분명했습니다 — Deployment / Service / probe / Endpoints 같은 K8s 인프라 객체 6종이 한 CRD 안으로 흡수되었고, 같은 패턴이 sklearn / pytorch / huggingface 모델에 동일하게 적용됐습니다. **그런데 LLM 이 들어오면 이 표준이 갑자기 비좁아집니다.**

LLM 서빙은 *"같은 매니페스트 패턴을 모델만 바꾸면 끝"* 이 통하지 않습니다. 다음 4 가지가 LLM 서빙을 일반 모델 서빙과 다른 *문제 클래스* 로 만듭니다.

| LLM 서빙 고유 문제 | 일반 모델 서빙에 없는 이유 |
|------------------|------------------------|
| **KV cache 메모리 관리** — 시퀀스 길이에 비례해 GPU 메모리가 커짐 | 분류/회귀 모델은 출력이 고정 차원 텐서 1개 — 메모리 사용량이 입력 크기에 거의 무관 |
| **요청별 latency 격차** — 한 요청은 50 토큰 생성, 다른 요청은 500 토큰 → latency 가 10배 차이 | 일반 모델은 모든 요청이 거의 같은 시간 — 정적 배칭으로 충분 |
| **OpenAI 호환 API 표준 압력** — 클라이언트 코드가 OpenAI SDK 로 표준화되어 있음 | 일반 모델은 `/predict` 엔드포인트로 충분 — 표준 API 가 없음 |
| **GPU 메모리 공유 — 모델 가중치 + KV cache + activation** 셋이 한 GPU 안에서 다툼 | 일반 모델은 가중치만 GPU 에 — KV cache 같은 동적 영역이 없음 |

KServe 의 HuggingFace 런타임은 transformers 의 `pipeline()` 으로 추론하는 일반 목적 코드라, 위 4가지에 대해 *특별한 최적화가 없습니다*. 같은 GPU 에서 KServe HF 런타임은 RPS 5–10, vLLM 은 RPS 50–100 이 흔한 차이입니다 — *5~10배 처리량 격차* 가 실제 운영에서 GPU 비용을 같은 비율로 줄여줍니다.

vLLM 의 차별점 3가지는 다음과 같이 정리됩니다.

1. **PagedAttention** — KV cache 를 OS 가상 메모리처럼 *페이지 단위* 로 관리해 메모리 단편화를 없앱니다. 결과적으로 같은 GPU 메모리에 *2~4배 더 많은 동시 요청* 을 담습니다.
2. **Continuous batching** — 매 *토큰 생성 step* 마다 배치를 새로 구성해, 짧은 요청이 끝나면 그 자리에 새 요청을 즉시 끼워 넣습니다. 정적 배칭 (Triton 의 dynamic batching 포함) 은 *요청 단위* 로 묶기 때문에 한 요청이 길면 GPU 가 비어도 다른 요청이 못 들어갑니다.
3. **OpenAI 호환 API** — `/v1/chat/completions`, `/v1/completions`, `/v1/models` 가 OpenAI 의 spec 과 완전 호환됩니다. 캡스톤의 RAG API 가 `from openai import OpenAI; client = OpenAI(base_url=...)` 한 줄로 vLLM 을 부를 수 있게 됩니다.

본 코스는 그래서 *분류 모델은 KServe 로, LLM 은 vLLM Deployment 로* 라는 분리를 채택합니다. 본 토픽이 이 분리의 LLM 측을 마무리하고, **그 결과물이 캡스톤(RAG 챗봇) 의 LLM 백엔드 그대로** 입니다.

---

## 1. 핵심 개념

### 1-1. PagedAttention — KV cache 를 페이지로 자르는 이유

LLM 의 *autoregressive* 생성은 매 토큰마다 *과거 모든 토큰의 key/value 텐서* 를 다시 참조합니다. 이 KV (key/value) 를 매번 재계산하지 않도록 GPU 메모리에 캐시하는 것이 KV cache 입니다. 시퀀스 길이 N, 레이어 L, 헤드 H, 헤드 차원 D 일 때 KV cache 크기는 대략 `2 × N × L × H × D × 2 byte (FP16)` — phi-2 (L=32, H=32, D=80) 의 max-model-len=2048 한 시퀀스 KV cache 만 약 *400 MB* 입니다.

전통적 KV cache 관리는 요청마다 *연속된 메모리 블록* 을 통째로 예약합니다. 문제는 (a) 요청이 max-model-len 만큼 다 채우지 않으면 *남은 자리가 낭비* (외부 단편화) 되고, (b) 요청이 끝나서 메모리를 반환해도 *다음 요청에 맞는 크기* 가 아니면 못 씁니다.

PagedAttention 은 OS 의 가상 메모리 페이징을 모방합니다.

```
[전통적 KV cache — 연속 블록]
  ┌─────────── req A (예약: 2048 tokens, 실제 사용: 50 tokens) ────────────┐
  │ 50 토큰 사용 │            1998 토큰 만큼의 메모리 낭비                  │
  └──────────────┴───────────────────────────────────────────────────────┘
  ┌─────────── req B (Pending — A 의 낭비된 자리에 못 들어감) ──────────────┐
  │            ...                                                         │
  └────────────────────────────────────────────────────────────────────────┘

[PagedAttention — 16 토큰 페이지 단위]
  page table (req A): [p0, p1, p2, p3]                ← 50 토큰 → 4 페이지 (마지막 페이지 14 토큰 남음)
  page table (req B): [p4, p5, p6, ..., p15]          ← B 요청이 즉시 같은 GPU 메모리에 자리 잡음
  page table (req C): [p16, p17, ...]
  ...
  free pages: [pN+1, pN+2, ...]                       ← 요청이 끝나면 페이지 단위로 즉시 재사용
```

페이지 크기 (vLLM 기본 16 토큰) 단위로만 *한 페이지 분량의 자투리 낭비* 가 생기므로, 같은 GPU 메모리에 들어가는 동시 요청 수가 *2~4 배* 늘어납니다. 본 토픽 메트릭으로 측정 가능한 효과:

```
부하 테스트 시 메트릭 비교 (T4 16GB, microsoft/phi-2)
                              KServe HF runtime    vLLM
  vllm:num_requests_running   1~2 (정적)          8~16 (페이지 단위 동적)
  vllm:gpu_cache_usage_perc   N/A                 0.6~0.9 (캐시가 실제로 가득 참)
  처리량 (tok/s)              150~250             1500~2500
```

> 💡 페이지 단위 KV cache 관리는 vLLM 의 *논문 한 장* 짜리 핵심 아이디어입니다. SOSP'23 의 [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) 이 원본 — 본 토픽 끝의 "더 알아보기" 박스에서 링크를 다시 만나게 됩니다.

### 1-2. Continuous batching — 정적 배칭과의 차이

LLM 추론의 *step* 은 "다음 토큰 1개 생성" 입니다. 한 요청이 100 토큰을 생성하려면 100 step 이 필요하고, 각 step 안에서는 GPU 가 활용도 90%+ 로 돌아갑니다. 문제는 *step 사이* 의 배칭 전략입니다.

| 전략 | 배치 단위 | 짧은 요청과 긴 요청이 섞일 때 |
|------|---------|-----------------------------|
| **정적 배칭** (vanilla PyTorch) | 요청을 모아 한 번에 forward | 짧은 요청이 끝나도 *긴 요청이 끝날 때까지* 새 요청 못 들어옴 — GPU 노는 시간 발생 |
| **Dynamic batching** (Triton) | timeout 기반으로 도착한 요청들을 묶음 | 정적 배칭의 변형 — 여전히 *요청 단위* 라 같은 한계 |
| **Continuous batching** (vLLM) | *매 토큰 step 마다* 배치 재구성 | 짧은 요청이 끝난 자리에 *대기 중인 요청* 이 즉시 채워짐 — GPU 가 항상 가득 |

continuous batching 의 효과는 부하의 *분산* 이 클수록 큽니다. 사용자 질문 길이가 50~500 토큰으로 10배 차이 나는 챗봇/RAG 워크로드에서 vLLM 이 Triton 의 dynamic batching 대비 *2~3 배* 처리량 우위를 보입니다.

> 💡 캡스톤의 RAG 챗봇은 *retrieval 결과 + 시스템 프롬프트 + 사용자 질문* 을 합쳐 prompt 길이가 500~1500 토큰으로 들쭉날쭉합니다. continuous batching 이 없으면 GPU 활용률이 급격히 떨어집니다 — 본 토픽이 vLLM 을 메인으로 채택한 가장 큰 운영적 이유.

### 1-3. OpenAI 호환 API 서피스

vLLM 의 OpenAI 서버 (`python -m vllm.entrypoints.openai.api_server`) 는 *3 개의 핵심 엔드포인트* 를 OpenAI spec 과 완전 호환되게 노출합니다.

```
POST /v1/chat/completions    — 멀티 턴 대화 (system / user / assistant 메시지 시퀀스). RAG 의 메인 호출 경로.
POST /v1/completions         — 단순 텍스트 보완 (legacy completion API). 자동완성/요약 등.
GET  /v1/models              — 현재 로드된 모델 목록. 헬스체크 용도로도 유용.
```

호출 예시:

```bash
# /v1/chat/completions — 챗봇 표준 호출
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "microsoft/phi-2",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "What is Kubernetes?"}
    ],
    "max_tokens": 200,
    "temperature": 0.7
  }'

# /v1/models — 모델 목록 (헬스체크 대체용)
curl http://localhost:8000/v1/models
```

응답 형식도 OpenAI spec 그대로:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1735689600,
  "model": "microsoft/phi-2",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "Kubernetes is an open-source ..."},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 25, "completion_tokens": 187, "total_tokens": 212}
}
```

**Python 클라이언트가 `openai` SDK 그대로** 라는 점이 운영적으로 가장 큰 가치입니다.

```python
from openai import OpenAI

# 캡스톤의 RAG API 가 vLLM 을 부를 때
client = OpenAI(
    base_url="http://vllm-phi2:8000/v1",   # K8s Service DNS — 외부 OpenAI 와 호환
    api_key="not-used"                      # vLLM 은 인증 미강제. 운영에서는 sidecar/API gateway 로 추가
)

resp = client.chat.completions.create(
    model="microsoft/phi-2",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

> 💡 "OpenAI API 와 호환" 이 뜻하는 *진짜* 가치: 클라이언트 코드를 OpenAI ↔ vLLM ↔ Anthropic Claude 사이에서 *모델 ID 와 base_url 두 줄만* 바꿔 바꿀 수 있다는 것. 모델 비교/마이그레이션 비용을 거의 0 으로 만듭니다.

### 1-4. vLLM 컨테이너 spec — args 핵심 5종

본 토픽 매니페스트 [vllm-phi2-deployment.yaml](manifests/vllm-phi2-deployment.yaml) 의 `args` 5 줄이 vLLM 운영의 *모든 표면적* 입니다. 각 옵션이 *무엇을 결정* 하고 *어떤 트레이드오프* 를 가지는지 정리합니다.

| 옵션 | 본 토픽 값 | 의미 | 트레이드오프 |
|------|----------|------|-------------|
| `--model` | `microsoft/phi-2` | HF Hub 모델 ID. 첫 기동 시 자동 다운로드 | 변경 시 PVC 캐시도 함께 무효화 — 5~10 분 재다운로드 |
| `--gpu-memory-utilization` | `0.85` | GPU VRAM 의 몇 % 까지 vLLM 이 사용 (모델 + KV cache) | ↑ 면 동시 요청 ↑, but OOM 위험 — 0.95+ 는 자주 하는 실수 3번 |
| `--max-model-len` | `2048` | 한 요청이 사용 가능한 최대 토큰 수 (input + output) | ↑ 면 긴 컨텍스트 가능, but KV cache 메모리 비례 증가 — phi-2 학습 한계 2048 을 넘기면 품질 급락 |
| `--port` | `8000` | HTTP 서버 포트 | Service `targetPort` 와 일치해야 함 |
| `--dtype` | `auto` | 모델 가중치 정밀도 (FP16 / BF16 / FP32) | T4 는 BF16 미지원 — `auto` 가 자동으로 FP16 선택. A100/H100 은 BF16 권장 |

**자주 보지만 본 토픽에서 안 다루는 옵션 (lesson.md 끝의 "더 알아보기" 박스 참조)**:
- `--quantization` — AWQ/GPTQ/INT8 양자화로 VRAM 50% 절감
- `--tensor-parallel-size` — 멀티 GPU 분산 (한 Pod 안에서)
- `--enable-prefix-caching` — 같은 prefix (예: 시스템 프롬프트) 가 반복되는 RAG 에서 큰 효과
- `--swap-space` — KV cache 가 GPU 메모리 초과 시 호스트 RAM 으로 swap

### 1-5. 모델 캐시 PVC 와 /dev/shm — startupProbe failureThreshold 60 의 이유

vLLM Pod 의 *첫 기동* 은 다음 4 단계로 길게 이어집니다.

```
Pod 생성 → 컨테이너 시작 → 모델 다운로드 (5~10분) → GPU 메모리 로딩 (30~60초) → KV cache 할당 (수 초) → /health 200 OK
```

이 과정 중 어떤 단계에서도 livenessProbe 가 fail 하면 *컨테이너 재시작* 으로 진행이 무한 루프에 빠집니다. 본 토픽 매니페스트는 두 가지 안전장치를 둡니다.

**첫째 — startupProbe** 가 통과할 때까지 livenessProbe 를 *시작도 하지 않게*:

```yaml
startupProbe:
  httpGet: { path: /health, port: http }
  failureThreshold: 60         # 60 × 10s = 최대 10 분 모델 로딩 허용
  periodSeconds: 10
```

K8s 의 startupProbe 는 *통과 후 자동으로 비활성화* 되고, 그 시점부터 livenessProbe 가 동작합니다. 그래서 *느린 startup + 빠른 liveness 체크* 를 함께 둘 수 있습니다.

**둘째 — PVC** 로 모델 캐시를 영속화해, 재시작 시 5~10분 다운로드를 *건너뜀*:

```yaml
volumeMounts:
  - name: model-cache
    mountPath: /root/.cache/huggingface     # vLLM (HF transformers) 의 캐시 기본 경로
volumes:
  - name: model-cache
    persistentVolumeClaim:
      claimName: vllm-phi2-cache             # 20Gi RWO PVC
```

첫 기동에서는 HF Hub → PVC 로 5GB+ 다운로드가 일어나지만, 두 번째부터는 캐시 hit 으로 *30 초 이내* 에 GPU 로딩만 끝납니다. 운영에서 이 차이는 *Deployment 롤링 업데이트의 가용성* 에 직접 영향을 줍니다.

**셋째 — /dev/shm** 마운트:

```yaml
volumeMounts:
  - name: shm
    mountPath: /dev/shm
volumes:
  - name: shm
    emptyDir:
      medium: Memory                # tmpfs — 디스크가 아닌 RAM 에 잡힘
      sizeLimit: 4Gi
```

CUDA 의 IPC (Inter-Process Communication) 가 공유 메모리를 통해 동작하는데, 컨테이너의 `/dev/shm` 기본 크기는 *64 MB* 입니다. vLLM 의 worker 프로세스가 그 용량 안에서 통신을 시도하다 메모리 부족으로 멈춥니다 — 자주 하는 실수 2번. 4Gi 는 phi-2 단일 모델 기준 충분하고, tensor-parallel 사용 시 8Gi+ 권장.

### 1-6. vLLM Prometheus 메트릭

vLLM 은 `/metrics` 엔드포인트를 *별도 설정 없이* 켭니다. [vllm-servicemonitor.yaml](manifests/vllm-servicemonitor.yaml) 가 Phase 3/02 의 Prometheus 와 연결해, 다음 메트릭을 자동 수집합니다.

| 메트릭 | 의미 | 대시보드/알람 활용 |
|--------|------|------------------|
| `vllm:num_requests_running` | 현재 GPU 에서 동시 처리 중인 요청 수 | continuous batching 효과 측정 — 8~16 면 정상, 1~2 면 vLLM 이 비효율 사용 중 |
| `vllm:num_requests_waiting` | KV cache 부족으로 대기 중인 요청 수 | 0 이 정상. 0 이 아닌 상태가 지속되면 *더 큰 GPU* 또는 `--max-model-len` 축소 검토 |
| `vllm:gpu_cache_usage_perc` | KV cache 사용률 (0.0 ~ 1.0) | 0.9+ 가 지속되면 OOM 위험. 부하 테스트 중 0.6~0.9 이면 PagedAttention 이 잘 동작 |
| `vllm:time_to_first_token_seconds` | 첫 토큰까지 소요 시간 (히스토그램) | 사용자 체감 latency 의 핵심 지표 — p99 SLA 의 기준 |
| `vllm:e2e_request_latency_seconds` | 요청 전체 latency 분포 (히스토그램) | TTFT 와 함께 보면 *입력 처리 vs 토큰 생성* 비중 분석 가능 |
| `vllm:generation_tokens_total` | 누적 생성 토큰 수 (counter) | RPS 와 결합해 *토큰/sec* 처리량 산출 |

본 토픽 labs Step 5B 에서 `kubectl port-forward` 로 Prometheus UI 를 열어 위 메트릭을 직접 PromQL 로 쿼리합니다. Grafana 대시보드는 *캡스톤* 에서 RAG 전체 (vLLM + Qdrant + RAG API) 를 한 화면에 묶을 때 만듭니다 — 본 토픽에서는 메트릭 *원시 데이터의 모양* 을 익히는 것이 목표.

> 💡 **GPU 모델은 CPU HPA 무용** — Phase 3/03 의 HPA 는 CPU 기반이었습니다. vLLM 의 vCPU 사용률은 *낮은데도* GPU 는 가득 찰 수 있어, CPU HPA 는 vLLM 에 적합하지 않습니다. *커스텀 메트릭 HPA* (`vllm:gpu_cache_usage_perc` 또는 `vllm:num_requests_waiting` 기반) 가 정답이고, 그 구현은 캡스톤에서 다룹니다.

---

## 2. 실습 안내

본 토픽의 실습은 *분량이 많고 환경에 따라 분기* 하므로 [labs/README.md](labs/README.md) 로 위임합니다. 큰 그림만 정리하면:

| Step | 공통/Track | 무엇을 하는가 | 예상 소요 |
|------|-----------|------------|---------|
| 0 | 공통 | 사전 점검 — Track A/B 분기 결정 | 5분 |
| 1 | 공통 | Secret + PVC 적용 | 5분 |
| **Track A — minikube CPU 스모크** | | | |
| 2A | A | vLLM CPU 빌드로 facebook/opt-125m 띄우기 (스모크 검증) | 10~15분 |
| 3A | A | `/v1/chat/completions` 호출 — OpenAI 응답 형식 학습 | 5분 |
| 4A | A | GPU 매니페스트 dry-run 으로 admission 통과 확인 | 5분 |
| 5A | A | 정리 | 5분 |
| **Track B — GKE T4 실전** | | | |
| 2B | B | GKE Spot T4 클러스터 1노드 생성 | 15~20분 |
| 3B | B | vllm-phi2 Deployment 적용 + 모델 다운로드 5~10분 대기 | 10분 |
| 4B | B | OpenAI Python SDK 로 `/v1/chat/completions` 호출 | 10분 |
| 5B | B | 메트릭 관찰 — `vllm:gpu_cache_usage_perc` 등 | 15분 |
| 6B | B | hey 부하 테스트 — RPS / p99 / KV cache 사용률 변화 | 30분 |
| 7B | B | 자주 하는 실수 재현 — vllm-mistake-cpu-only.yaml | 10분 |
| 8B | B | **클러스터 삭제** (비용 청구 방지) | 5분 |

Track A 만 따라가도 본 토픽의 *추상화 모델* (vLLM 의 OpenAI API 모양, 매니페스트 구조, GPU 격리 패턴) 은 모두 손에 잡힙니다. Track B 는 *실제 GPU 위에서의 처리량/메모리 동역학* 을 직접 측정하고 싶을 때.

---

## 3. 검증 체크리스트

본 토픽을 마쳤다고 볼 기준입니다. Track A / B 별 다른 항목을 묶어 두었습니다.

**공통**
- [ ] [vllm-phi2-deployment.yaml](manifests/vllm-phi2-deployment.yaml) 의 `args` 5 종, GPU 격리 3종, startupProbe failureThreshold, /dev/shm 마운트의 *각각 이유* 를 한 문장씩 설명할 수 있다.
- [ ] OpenAI 호환 API 의 `/v1/chat/completions` 요청/응답 JSON 스키마를 예시로 적을 수 있다.
- [ ] PagedAttention / continuous batching 이 KServe HF 런타임 대비 처리량을 *왜* 끌어올리는지 한 문단으로 설명할 수 있다.

**Track A**
- [ ] minikube 에서 vLLM CPU 빌드로 작은 모델 (facebook/opt-125m) 을 띄워 `/v1/chat/completions` 200 OK 를 확인했다.
- [ ] [vllm-phi2-deployment.yaml](manifests/vllm-phi2-deployment.yaml) 가 `kubectl apply --dry-run=server` 로 admission 통과한다 (실 apply 시 GPU 자원 없어 Pending 인 것까지 확인).

**Track B**
- [ ] GKE T4 클러스터에서 `kubectl get pod -l app=vllm-phi2` 가 `Running`, `kubectl logs` 에 `Uvicorn running on http://0.0.0.0:8000` 메시지가 보인다.
- [ ] OpenAI Python SDK (`from openai import OpenAI`) 로 `/v1/chat/completions` 호출 시 자연어 응답을 받는다.
- [ ] `kubectl port-forward svc/prometheus-...` 로 Prometheus UI 에서 `vllm:gpu_cache_usage_perc` 가 *0 보다 큰* 값을 보인다 (KV cache 가 실제 동작 중).
- [ ] hey 부하 테스트 (`hey -z 60s -c 8 ...`) 중 `vllm:num_requests_running` 가 5 이상으로 올라간 것을 확인했다 (continuous batching 이 동작).
- [ ] [vllm-mistake-cpu-only.yaml](manifests/vllm-mistake-cpu-only.yaml) 적용 시 어떤 실패 양상 (CrashLoopBackOff / `RuntimeError: No CUDA GPUs are available`) 이 보이는지 직접 확인했다.
- [ ] **`gcloud container clusters delete` 로 GKE 클러스터를 삭제했다.** (Track B 의 *최종 통과 조건* — 청구서 방지)

---

## 4. 정리

```bash
# 본 토픽 리소스 일괄 삭제 (라벨 기반)
kubectl delete deploy,svc,pvc,secret,servicemonitor -l phase=4,topic=03-vllm-llm-serving

# Track B 만: GKE 클러스터 삭제
gcloud container clusters delete vllm-lab --zone=us-central1-c --quiet
```

**확인 포인트**: `kubectl get all -l topic=03-vllm-llm-serving` 의 결과가 `No resources found` 로 떠야 합니다. PVC 가 남아 있으면 `kubectl delete pvc -l topic=03-vllm-llm-serving` 로 추가 정리 — PVC 는 Deployment 와 다른 라이프사이클이라 자동 삭제되지 않습니다.

---

## 🚨 자주 하는 실수

1. **`nvidia.com/gpu: 1` 누락** — 매니페스트 작성자가 가장 많이 빠뜨리는 실수. Pod 가 *Pending 도 아니고 Running 도 아닌* 까다로운 형태로 실패합니다.
   - **Track A (GPU 노드 자체가 없음)**: schedule 자체는 됨 (CPU 노드 한 곳에) → 컨테이너 시작 후 vLLM 이 CUDA 초기화 시도 → `RuntimeError: No CUDA GPUs are available` → CrashLoopBackOff.
   - **Track B (GPU 노드 + 일반 노드 혼재)**: GKE 의 GPU 노드 taint 가 있으니 일반 노드로 schedule → 같은 CUDA 초기화 실패 → CrashLoopBackOff.
   - **재현**: [vllm-mistake-cpu-only.yaml](manifests/vllm-mistake-cpu-only.yaml) apply → `kubectl logs deploy/vllm-phi2-mistake` 로 직접 확인.
   - **해결**: `resources.requests` 와 `resources.limits` 양쪽에 `nvidia.com/gpu: 1` (정수만, requests=limits) + nodeSelector + toleration *세트로* 챙기기.

2. **`/dev/shm` 마운트 누락 (CUDA IPC 공유 메모리 부족)** — 컨테이너의 `/dev/shm` 기본 크기는 64MB 인데, vLLM 의 worker 프로세스 간 통신이 그 안에서 막힙니다.
   - **증상**: 컨테이너 시작은 되고 모델 로딩까지 진행되다가 첫 요청 처리에서 `Bus error` 또는 worker 가 응답 없음 (logs 가 멈춤).
   - **해결**: `volumes` 에 `emptyDir.medium: Memory, sizeLimit: 4Gi` 로 tmpfs 를 마운트. 본 토픽 매니페스트의 `shm` 볼륨 그대로 차용.
   - **참고**: tensor-parallel 사용 시 worker 가 더 많아 8Gi+ 권장.

3. **`--gpu-memory-utilization` 0.95+ → KV cache OOM** — vLLM 은 *시작 시* GPU 메모리의 N% 를 사전 할당해 KV cache 풀을 만듭니다. 너무 높이면 모델 가중치 + activation + 다른 프로세스 (모니터링 agent 등) 와 충돌해 *시작도 못 합니다*.
   - **증상**: vLLM logs 에 `torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate ...` → 컨테이너 종료 → CrashLoopBackOff.
   - **해결**: T4 16GB 에는 0.85, A100 40GB 에는 0.90 정도가 안전한 시작값. 부하 테스트 후 메트릭 보면서 점진적 상향.
   - **함께 확인**: `kubectl exec ... nvidia-smi` 로 GPU 위에 *다른 프로세스가 있는지* — Time-slicing 환경에서는 같은 GPU 를 다른 Pod 가 쓸 수 있습니다 (Phase 4/01 1-4 절).

---

## 다른 LLM 서빙 도구는?

본 코스가 vLLM 을 *메인 LLM 서빙 도구* 로 채택한 근거를 다른 도구와의 자리매김에서 정리합니다.

| 도구 | 강점 | 약점 | 본 코스의 자리매김 |
|------|------|------|------------------|
| **vLLM** ⭐ | PagedAttention + continuous batching, OpenAI 호환 API, OSS, 커뮤니티 활발 | LLM 전용 (분류 모델엔 오버킬), 양자화 옵션이 TGI 보다 다양은 X | **본 토픽 + 캡스톤 메인** |
| **TGI** (HuggingFace Text Generation Inference) | HF 생태계와 통합, 양자화 옵션 풍부, Rust 기반 빠른 서버 | OpenAI 호환 API 가 vLLM 만큼 완전하지 않음, 처리량은 vLLM 에 약간 밀림 | 한 줄 언급. HF 레지스트리에 깊이 결합된 워크플로면 검토 |
| **Triton Inference Server + TensorRT-LLM** | NVIDIA 공식, 멀티 모델 동시 운영, INT8/FP8 최적화 | 설정 복잡 (model repository + config.pbtxt), OSS 지만 NVIDIA 생태계 의존 | 한 줄 언급. *분류 모델과 LLM 을 같은 서버* 로 운영하면 검토 |
| **Ollama** | 로컬 노트북에서 한 줄 (`ollama run llama3`), GGUF 양자화 모델 풍부 | K8s 통합 미성숙, 단일 사용자 지향 | 본 코스 범위 밖. 개인 학습/프로토타이핑 용 |
| **llama.cpp / llama-cpp-python** | CPU 추론 가능, 작은 자원에서 큰 모델 로드 | LLM 처리량은 GPU 가속 도구에 비해 낮음 | 본 코스 범위 밖. GPU 없는 환경에서 LLM 학습용 |

> 💡 **"왜 본 코스가 vLLM 을 메인으로?"**: ① OSS 라 학습/실무 모두 자유로운 사용, ② OpenAI 호환 API 가 캡스톤의 RAG API 코드를 단순하게 만듦, ③ 처리량이 동급 도구 중 가장 안정적으로 우수, ④ K8s 상의 운영 사례/문서가 풍부. *분류 모델은 KServe 로, LLM 은 vLLM 으로* 라는 본 코스의 분리는 위 4 가지 근거에서 옵니다.

---

## 더 알아보기

- [vLLM 공식 문서](https://docs.vllm.ai/) — `vllm/vllm-openai` 이미지의 모든 args 옵션, 양자화 가이드, K8s 배포 가이드
- [PagedAttention 논문 (SOSP'23)](https://arxiv.org/abs/2309.06180) — 페이지 단위 KV cache 관리의 원본 아이디어
- [OpenAI API spec](https://platform.openai.com/docs/api-reference) — `/v1/chat/completions` / `/v1/completions` / `/v1/models` 의 표준 정의
- [vLLM Prometheus metrics 문서](https://docs.vllm.ai/en/latest/serving/metrics.html) — 본 토픽 1-6 절의 메트릭 전체 목록과 의미
- [HuggingFace `microsoft/phi-2` 모델 카드](https://huggingface.co/microsoft/phi-2) — 본 토픽의 메인 모델
- [vLLM 양자화 (AWQ/GPTQ/INT8)](https://docs.vllm.ai/en/latest/quantization/index.html) — 본 토픽이 다루지 않은 `--quantization` 옵션 (캡스톤에서 메모리 부족 시 검토)
- [vLLM tensor parallelism](https://docs.vllm.ai/en/latest/serving/distributed_serving.html) — 본 토픽이 다루지 않은 `--tensor-parallel-size` 옵션 (7B+ 모델에서 멀티 GPU 분산 시)

---

## 다음 챕터

➡️ [Phase 4 / 04 — Argo Workflows](../04-argo-workflows/lesson.md) (작성 예정)

본 토픽이 *vLLM Deployment 한 장* 으로 LLM 서빙을 마쳤다면, 다음 토픽 [Argo Workflows](../04-argo-workflows/) 는 *그 vLLM 위에서 흘러갈 RAG 인덱싱 파이프라인* (문서 → 임베딩 → Qdrant Upsert) 을 DAG 로 표현하는 법을 다룹니다. Argo Workflows 까지 끝나면 [⭐ 캡스톤 — RAG 챗봇 + LLM 서빙 종합 프로젝트](../../capstone-rag-llm-serving/) 의 모든 빌딩 블록 (vLLM + KServe + Argo + Prometheus + GPU + HPA) 이 모이게 됩니다.
