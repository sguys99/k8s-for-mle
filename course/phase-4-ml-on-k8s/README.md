# Phase 4 — ML on Kubernetes (3–4주) ⭐

> Phase 0–3 동안 만든 sentiment-api 자산을 발판 삼아 본격적인 ML 전용 도구 (GPU 스케줄링 / KServe / vLLM / Argo / KubeRay) 위로 옮겨갑니다. CPU 추론 + Helm + Prometheus + RBAC 까지 도구가 갖춰진 상태에서, 이 Phase 가 *왜 K8s 가 ML 인프라의 표준이 되었는지* — GPU 같은 비싼 자원을 안전하게 공유하고, 모델 서빙 / LLM / 분산 학습이 모두 같은 플랫폼 위에서 통합되는지 — 를 손에 잡히게 보여줍니다.
>
> **권장 기간**: 3–4주
> **선수 학습**: [Phase 3 — 프로덕션 운영 도구](../phase-3-production/)
> **GPU 필요**: 4-1, 4-3, 캡스톤. 로컬 GPU 가 없으면 GCP GKE (Spot T4) 임시 클러스터 사용 — 실습 후 클러스터 삭제 필수

## 이 Phase 에서 배우는 것

Phase 3/04 까지 sentiment-api 는 *CPU 만 쓰는 분류 모델 한 개* 였습니다. 실제 ML 운영은 (a) 비싼 GPU 를 여러 워크로드가 공유해야 하고, (b) 모델·서빙 도구가 다양하며, (c) 학습·인덱싱 같은 비-서빙 워크로드가 정기적으로 실행됩니다. Phase 4 는 그 4축을 다음과 같이 펼칩니다.

| ML 운영 문제 | Phase 4 해결책 |
|--------------|----------------|
| GPU 가 비싸고 부족함. 어떤 Pod 가 어떤 GPU 를 쓸지 어떻게 정하지? | NVIDIA Device Plugin + `nvidia.com/gpu` + nodeSelector / taint / toleration / MIG / Time-slicing |
| 모델 서빙 매니페스트가 매번 비슷한데 표준이 없음 | KServe `InferenceService` — 모델 서빙의 K8s 표준 추상화 |
| LLM (수십억 파라미터) 을 어떻게 띄우지? OpenAI 호환 API 가 필요 | vLLM Deployment + OpenAI 호환 `/v1/chat/completions` |
| 모델 학습 / 인덱싱 / 평가를 DAG 로 자동화하려면? | Argo Workflows (DAG, retry, parallelism) |
| 멀티 GPU / 멀티 노드 학습은? | KubeRay / Kubeflow Training Operator (개념 비교) |

## 학습 목표

- NVIDIA Device Plugin 이 GPU 를 K8s 자원 (`nvidia.com/gpu`) 으로 노출하는 메커니즘을 이해하고, Pod / Deployment 가 그 자원을 안전하게 요청·격리하도록 매니페스트를 작성합니다.
- KServe `InferenceService` CRD 로 분류 모델 서빙을 표준화하고, 같은 패턴이 다양한 모델 (sklearn / pytorch / huggingface) 에 동일하게 적용됨을 확인합니다.
- vLLM 으로 SLM (`microsoft/phi-2` 또는 `Qwen/Qwen2.5-1.5B-Instruct`) 을 OpenAI 호환 API 로 서빙하고, GPU 메모리 / KV cache 동작을 관찰합니다.
- Argo Workflows 로 RAG 인덱싱 파이프라인을 DAG 로 표현하고, KubeRay / Kubeflow Training Operator 의 분산 학습 디자인 차이를 개념적으로 비교합니다.

## 챕터 구성

| 챕터 | 제목 | 핵심 내용 |
|------|------|----------|
| [01](./01-gpu-on-k8s/) | GPU on Kubernetes | NVIDIA Device Plugin, `nvidia.com/gpu` requests/limits, nodeSelector + taint + toleration 3종 격리, MIG (하드웨어 슬라이스) vs Time-slicing (시분할), Phase 2/05 GPU quota 와의 연결 검증 — 이중 트랙 (minikube 모의 + GKE 실전) |
| [02](./02-kserve-inference/) | KServe InferenceService | sentiment 분류 모델을 KServe `InferenceService` 로 마이그레이션, HF 빌트인 런타임 + 커스텀 predictor, scale-to-zero / cold start 트레이드오프, `canaryTrafficPercent` 로 v1/v2 트래픽 분할 |
| [03](./03-vllm-llm-serving/) | vLLM LLM Serving ⭐ GPU | `microsoft/phi-2` 를 OpenAI 호환 API (`/v1/chat/completions`) 로 서빙, PagedAttention + continuous batching 으로 KServe HF 런타임 대비 처리량 5–10×, vllm:gpu_cache_usage_perc · num_requests_running 메트릭으로 KV cache 동작 검증 — 이중 트랙 (minikube CPU 스모크 + GKE T4 실전), 본 코스의 *모델 전환 지점* (분류 → SLM) |
| [04](./04-argo-workflows/) | Argo Workflows | quick-start-minimal 설치, Hello DAG (fan-out / fan-in), RAG 인덱싱 4단계 DAG (load → chunk → embed → upsert) + `volumeClaimTemplates` 로 단계 간 PVC 공유, CronWorkflow — 캡스톤 Day 3 의 직접 발판 |
| [05](./05-distributed-training-intro/) | Distributed Training Intro | KubeRay (RayCluster + RayJob CRD, head/worker 분리, `ray.cluster_resources()` 검증) 와 Kubeflow Training Operator (PyTorchJob, Master/Worker, `MASTER_ADDR`/`WORLD_SIZE`/`RANK` 자동 주입, `cleanPodPolicy`) 의 디자인 비교 — KubeRay 만 minikube 실행, PyTorchJob 은 매니페스트 분석 |

01–04 가 캡스톤 ([RAG 챗봇 + LLM 서빙 종합 프로젝트](../capstone-rag-llm-serving/)) 의 직접 구성요소이고, 05 는 학습 워크로드 확장의 출발점입니다.

## 권장 진행 순서

1. **01 GPU 부터 시작합니다**. 03 vLLM 과 캡스톤이 GPU 위에서 동작하므로, 01 의 `nvidia.com/gpu` / toleration 패턴이 모든 후속 토픽에 그대로 재사용됩니다.
2. **02 KServe → 03 vLLM 순서**. 02 가 *모델 서빙의 K8s 표준 추상화* 를 보여주고, 03 이 그 추상화로는 다 못 담는 LLM 특화 요구사항 (paged attention, OpenAI API 호환) 을 vLLM 으로 정면 돌파합니다.
3. **04 Argo → 05 Distributed Training**. 04 의 DAG 가 캡스톤 인덱싱 파이프라인의 핵심이고, 05 는 *학습 워크로드를 K8s 위로 어떻게 옮기는가* 의 개념 발판.
4. GPU 토픽 (01, 03, 캡스톤) 은 *실습 후 즉시 클러스터 삭제* — 비용 청구 방지.

## 환경 요구사항

| 도구 | 용도 | 비고 |
|------|------|------|
| kubectl v1.28+ | 모든 토픽 공통 | Phase 1 부터 사용 |
| minikube v1.32+ | 02 KServe / 04 Argo / 05 분산학습 (CPU OK), 01 의 Track A | Phase 1 부터 사용 |
| Helm v3.x | KServe / Argo Workflows 설치 | Phase 3/01 부터 사용 |
| **NVIDIA GPU + Device Plugin** | 01 의 Track B, 03 vLLM, 캡스톤 | 로컬 GPU 또는 GKE Spot T4 (~$0.35/h) |
| **gcloud CLI** | GKE 클러스터 생성 / 삭제 | GPU 가 없을 때 |
| HuggingFace 토큰 | 모델 다운로드 (제한 모델일 때) | Phase 2/01 의 Secret 패턴 재사용 |

## 마치면 할 수 있는 것

이 Phase 를 완료하면 다음을 자력으로 구축할 수 있습니다.

> *분류 모델은 KServe `InferenceService` 로, LLM 은 vLLM Deployment + OpenAI 호환 API 로 서빙하고, 두 서빙이 같은 클러스터에서 NVIDIA Device Plugin 으로 GPU 를 안전하게 공유하며, 인덱싱·평가 같은 비-서빙 워크로드는 Argo Workflows DAG 로 정기 실행되는 통합된 ML 플랫폼.*

이 그림이 정확히 [캡스톤 — RAG 챗봇 + LLM 서빙 종합 프로젝트](../capstone-rag-llm-serving/) 의 입구입니다.

## 다음 단계

➡️ [Phase 4 / 01 — GPU on Kubernetes](./01-gpu-on-k8s/) 부터 시작하세요. Phase 2/05 가 dev / prod namespace 의 ResourceQuota 에 `requests.nvidia.com/gpu` 를 미리 깔아두었고 (used 가 항상 0), 01 의 GPU Pod 가 그 used 를 처음으로 채우는 모습을 직접 검증합니다.

➡️ Phase 4 모두 완료 후: [⭐ Capstone — RAG 챗봇 + LLM 서빙 종합 프로젝트](../capstone-rag-llm-serving/) (작성 예정). 본 토픽 05 (분산 학습 입문) 은 *캡스톤의 직접 구성요소는 아닙니다* — 캡스톤은 *학습된 모델을 들고 와서 RAG 시스템에 결합* 하는 흐름이라, 학습 자체는 다루지 않습니다. 캡스톤 이후 *RAG retrieval 정확도 개선을 위해 임베딩 모델을 fine-tuning* 하는 단계로 갈 때 본 토픽 05 의 두 도구를 직접 손에 잡게 됩니다.
