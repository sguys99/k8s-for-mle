# Phase 4 / 03 — 매니페스트 목록과 적용 순서

본 디렉토리는 [Phase 4 / 03 — vLLM LLM Serving](../lesson.md) 토픽의 모든 K8s 매니페스트를 담고 있습니다. labs/README.md 의 실습은 모두 이 매니페스트를 참조합니다.

---

## 파일 목록 (적용 순서대로)

| # | 파일 | 종류 | 역할 |
|---|------|------|------|
| 1 | [vllm-hf-secret.yaml](vllm-hf-secret.yaml) | Secret | HuggingFace 토큰 (gated 모델용 — phi-2 는 옵션) |
| 2 | [vllm-pvc.yaml](vllm-pvc.yaml) | PVC | 모델 캐시 영속화 (`/root/.cache/huggingface`, 20Gi) |
| 3 | [vllm-phi2-deployment.yaml](vllm-phi2-deployment.yaml) | Deployment | **메인 매니페스트** — vLLM OpenAI 호환 서빙 + GPU 1장 |
| 4 | [vllm-service.yaml](vllm-service.yaml) | Service | ClusterIP, port 8000 — RAG API / port-forward 가 부르는 endpoint |
| 5 | [vllm-servicemonitor.yaml](vllm-servicemonitor.yaml) | ServiceMonitor | Phase 3/02 Prometheus 와 연결 — `vllm:gpu_cache_usage_perc` 등 자동 수집 |
| ※ | [vllm-mistake-cpu-only.yaml](vllm-mistake-cpu-only.yaml) | Deployment | *학습용 의도적 실패* — `nvidia.com/gpu` 누락 시 어떤 에러가 뜨는지 직접 확인 |

> 1 → 2 → 3 → 4 → 5 순서로 apply. 5번(ServiceMonitor) 은 Phase 3/02 의 kube-prometheus-stack 이 설치되어 있을 때만 의미가 있습니다.
> ※ 표시(자주 하는 실수 시연) 매니페스트는 정상 매니페스트와 *별개* 로, 학습이 끝난 뒤 즉시 삭제하세요.

---

## 한 번에 적용

```bash
# 정상 5종 일괄 적용 (mistake 매니페스트는 제외)
kubectl apply -f vllm-hf-secret.yaml \
              -f vllm-pvc.yaml \
              -f vllm-phi2-deployment.yaml \
              -f vllm-service.yaml \
              -f vllm-servicemonitor.yaml

# 또는 디렉토리 한 번에 (mistake 도 함께 적용되므로 주의 — labs Step 7B 에서 별도 진행 권장)
kubectl apply -f .
```

---

## Track 별 사용법

| Track | 환경 | 매니페스트 사용 방식 |
|------|------|--------------------|
| **A** | minikube, GPU 없음 | 1·2·3·4 를 `kubectl apply --dry-run=server` 로 admission 통과만 확인. 실제 동작 검증은 [labs Step 2A](../labs/README.md) 의 vLLM CPU 빌드 이미지로 별도 수행. ServiceMonitor(5) 는 minikube 에 kube-prometheus-stack 이 없으면 admission 거절될 수 있어 옵션. |
| **B** | GKE T4 / 로컬 GPU | 1·2·3·4·5 를 모두 `kubectl apply` 후 `kubectl logs -f deploy/vllm-phi2` 로 모델 로딩 5~10분 모니터링. mistake 매니페스트는 [labs Step 7B](../labs/README.md) 에서 짧게 시연 후 삭제. |

---

## 매니페스트 한 줄 정리

| 매니페스트 | 핵심 1줄 | 학습 포인트 |
|-----------|---------|-----------|
| `vllm-hf-secret.yaml` | Phase 2/01 Secret 패턴 | gated 모델/HF rate limit 회피 — phi-2 는 optional |
| `vllm-pvc.yaml` | 20Gi PVC, RWO | 5GB 모델을 Pod 재시작마다 재다운로드하지 않게 |
| `vllm-phi2-deployment.yaml` | `vllm/vllm-openai:v0.6.6.post1` + GPU 1 + args 5종 | GPU 격리 3종(Phase 4/01) + vLLM 핵심 옵션 + startupProbe 60×10s + /dev/shm |
| `vllm-service.yaml` | ClusterIP 8000 | 캡스톤의 RAG API 가 부를 안정 endpoint |
| `vllm-servicemonitor.yaml` | `port: http` + `path: /metrics` | Phase 3/02 Prometheus 가 vLLM 메트릭 자동 수집 |
| `vllm-mistake-cpu-only.yaml` | `nvidia.com/gpu` *없음* | "GPU 누락 시 Pending 도 아니고 정상도 아닌" 까다로운 실패 양상 시연 |

---

## 정리 명령

```bash
# 본 토픽의 모든 리소스 한 번에 삭제 (라벨 기반 — phase=4, topic=03-vllm-llm-serving 인 객체)
kubectl delete deploy,svc,pvc,secret,servicemonitor -l phase=4,topic=03-vllm-llm-serving

# (Track B 만) GKE 클러스터 자체 삭제 — 비용 청구 방지. 반드시 실행.
gcloud container clusters delete vllm-lab --zone=us-central1-c --quiet
```
