# ML 서빙 도구 비교/선택 가이드

Phase 4에서 모델 서빙 도구를 다룰 때 참고합니다. 도구별 특성과 어느 상황에 어울리는지 정리되어 있어, 강의 자료에서 "왜 이 도구를 선택했는가"를 설명할 때 활용합니다.

## 한눈에 보기

| 도구 | 강점 | 약점 | 추천 상황 |
|------|------|------|----------|
| **FastAPI + Deployment** | 단순, 자유도 ↑, 디버깅 쉬움 | scale-to-zero 없음, 기능 직접 구현 | 입문, 소규모, 커스텀 로직 |
| **KServe** | K8s 네이티브, scale-to-zero, 다양한 포맷 표준화 | Knative 의존, 학습 곡선 ↑ | 다양한 모델 포맷 운영 |
| **Seldon Core** | 그래프형 추론 파이프라인, A/B 테스트 강함 | 무거움, OSS 정책 변동 | 복잡한 추론 흐름 |
| **vLLM (직접 Deployment)** | LLM 처리량 최강 (PagedAttention) | LLM 전용, 다른 모델 비효율 | LLM/SLM 서빙 |
| **Triton Inference Server** | 멀티 프레임워크, 동적 배칭, GPU 최적화 | 설정 복잡 | 다양한 모델 동시 운영 |
| **TGI (Text Generation Inference)** | LLM 특화, HF 통합 | LLM 전용, vLLM에 처리량 밀림 | HF 생태계 위주 |
| **Ray Serve** | 분산 처리, Python 친화 | K8s 네이티브 아님 (KubeRay 필요) | Python 파이프라인과 결합 |

## 선택 가이드 (3분 결정)

```
질문 1: LLM/SLM만 서빙하나?
  └ Yes → vLLM 또는 TGI
  └ No  → 질문 2

질문 2: 다양한 모델 포맷(ONNX, TensorRT, PyTorch, TF)을 동시 운영하나?
  └ Yes → Triton 또는 KServe
  └ No  → 질문 3

질문 3: scale-to-zero / 다양한 모델 표준화가 필요한가?
  └ Yes → KServe
  └ No  → FastAPI + Deployment (입문이라면 강력 추천)

질문 4 (보너스): 추론 그래프(전처리 → 모델 A → 후처리 → 모델 B)가 복잡한가?
  └ Yes → Seldon Core 검토
```

## 강의 자료에서의 사용

Phase 4 도입부에서 위 표를 보여주고, 학습자가 본인 업무 시나리오에 맞춰 1–2개를 깊게 파도록 안내합니다. 이 강의는 **모든 도구를 다 가르치지 않습니다.** 보통 다음 조합을 권장합니다.

- **입문 트랙**: FastAPI + Deployment (Phase 1) → KServe (Phase 4-2)
- **LLM 트랙**: FastAPI + Deployment → vLLM Deployment → 캡스톤
- **다양한 모델 트랙**: FastAPI + Deployment → Triton → KServe

## 도구별 핵심 매니페스트 패턴

### FastAPI + Deployment
- 일반 Deployment + Service. probes 필수. `requests`/`limits` 명시.
- GPU 시 `nvidia.com/gpu: 1`.
- 모델 다운로드는 init container로 PVC에 저장하면 재시작 빨라집니다.

### KServe InferenceService
```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: sentiment
spec:
  predictor:
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
- HuggingFace, sklearn, pytorch, tensorflow, triton 등 빌트인 runtime.
- scale-to-zero는 `minReplicas: 0` (Knative 설치 필요).

### vLLM Deployment
- 단일 Deployment로 시작. 명령 예: `python -m vllm.entrypoints.openai.api_server --model microsoft/phi-2`.
- OpenAI 호환 API 제공해서 클라이언트 코드 거의 그대로 씁니다.
- GPU 메모리에 모델 가중치 + KV cache 들어가야 하므로 `requests.memory`보다 GPU memory 모니터링 중요.

### Triton
- 모델 저장소 구조: `/models/<model-name>/<version>/model.pt`. config.pbtxt로 입력/출력 텐서 정의.
- ConfigMap이나 PVC로 모델 저장소 마운트.
- 동적 배칭(`dynamic_batching {}`) 활성화로 GPU 활용도 ↑.

## 모니터링 메트릭

도구별로 노출하는 표준 메트릭이 다릅니다. 강의에서는 Prometheus 스크래핑까지 묶어서 보여주는 게 좋습니다.

| 도구 | 메트릭 엔드포인트 | 핵심 메트릭 |
|------|-----------------|------------|
| FastAPI + prometheus-client | `/metrics` | `request_duration_seconds`, `requests_total` |
| KServe | predictor pod의 `/metrics` | `request_count`, `request_duration` |
| vLLM | `/metrics` (기본) | `vllm:num_requests_running`, `vllm:gpu_cache_usage_perc` |
| Triton | 8002 포트 `/metrics` | `nv_inference_request_success`, `nv_inference_queue_duration` |

## 자주 하는 실수

- **모든 모델에 vLLM 쓰기**: vLLM은 LLM 전용입니다. 분류 모델에 쓰면 오버킬.
- **scale-to-zero 켜고 cold start 무시**: 첫 요청에 모델 로딩 30초+ 걸릴 수 있음. SLA 검토 필수.
- **GPU 노드 셀렉터 누락**: GPU 필요한 Pod이 CPU 노드에 떨어져 OOM 또는 무한 Pending.
- **Triton 설정에 `instance_group`/`dynamic_batching` 빠뜨림**: 성능 절반 이하로 떨어집니다.
