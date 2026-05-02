# 캡스톤 — RAG 챗봇 + LLM 서빙 종합 프로젝트

학습한 K8s + ML 도구를 모두 통합해 한 번에 돌리는 종합 프로젝트입니다. 1–2주 정도 잡고 천천히 단계별로 진행하는 것을 권장합니다.

## 프로젝트 목표

내부 문서에 기반한 RAG(Retrieval-Augmented Generation) 챗봇을 K8s 위에 구축합니다. 학습자는 다음 결과물을 가지게 됩니다.

1. 문서를 임베딩해 벡터 DB에 저장하는 인덱싱 파이프라인
2. SLM/LLM을 vLLM으로 서빙하는 추론 서비스
3. 사용자 질의를 받아 관련 문서를 검색하고 LLM에 컨텍스트와 함께 전달하는 RAG API
4. 모니터링/오토스케일링이 적용된 운영 가능한 시스템

## 출력 디렉토리 구조

```
course/capstone-rag-llm-serving/
├── README.md                       # 프로젝트 전체 개요 (이 문서 기반)
├── lesson.md                       # 시스템 설계 설명
├── manifests/                      # 통합 K8s 매니페스트
│   ├── 00-namespace.yaml
│   ├── 10-vector-db-statefulset.yaml         # Qdrant
│   ├── 11-vector-db-service.yaml
│   ├── 20-vllm-deployment.yaml               # LLM 서빙
│   ├── 21-vllm-service.yaml
│   ├── 22-vllm-hpa.yaml
│   ├── 30-rag-api-deployment.yaml
│   ├── 31-rag-api-service.yaml
│   ├── 32-rag-api-configmap.yaml
│   ├── 33-rag-api-secret.yaml
│   ├── 40-ingress.yaml
│   ├── 50-indexing-job.yaml                  # 또는 Argo Workflow
│   └── 60-servicemonitor.yaml
├── practice/
│   ├── rag_app/                              # RAG API 코드
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── main.py                           # FastAPI 진입점
│   │   ├── retriever.py                      # 벡터 검색
│   │   └── llm_client.py                     # vLLM 호출
│   ├── llm_serving/
│   │   ├── README.md                         # vLLM 운영 노트
│   │   └── load_test.sh
│   └── pipelines/
│       ├── indexing/
│       │   ├── Dockerfile
│       │   ├── requirements.txt
│       │   └── index_documents.py            # 문서 → 임베딩 → Qdrant
│       └── argo-workflow.yaml                # 선택: Argo로 파이프라인화
└── docs/
    └── architecture.md                       # 아키텍처 다이어그램 + 트레이드오프
```

## 시스템 아키텍처

```
              ┌──────────────────────────────────────┐
              │  Ingress (nginx-ingress)             │
              └──────────────┬───────────────────────┘
                             │ /chat
                  ┌──────────▼──────────┐
                  │  RAG API            │  ← FastAPI, 3 replicas, HPA
                  │  (FastAPI)          │
                  └────┬───────────┬────┘
            검색 │           │ 생성
                  ▼           ▼
       ┌──────────────┐  ┌────────────────────┐
       │ Qdrant       │  │ vLLM Deployment    │  ← GPU 1, HPA on QPS
       │ (StatefulSet)│  │ (microsoft/phi-2)  │
       └──────────────┘  └────────────────────┘
            ▲
            │ 인덱싱
       ┌────────────────┐
       │ Indexing Job   │  ← CronJob 또는 Argo Workflow
       │ (Embedding +   │
       │  Upsert)       │
       └────────────────┘

부가:
- Prometheus가 RAG API / vLLM / Qdrant 메트릭 수집
- Grafana 대시보드: latency, throughput, GPU 메모리, retrieval recall
```

## 사용 도구 (택일이 명시된 곳은 가벼운 옵션 우선)

| 영역 | 도구 | 선택 이유 |
|------|------|---------|
| 벡터 DB | **Qdrant** (StatefulSet) | 단일 컨테이너로 실습 쉬움, 한국어 문서도 무난 |
| 임베딩 모델 | `BAAI/bge-small-en` 또는 `BAAI/bge-m3` | 가벼움, 다국어 |
| LLM 서빙 | **vLLM + microsoft/phi-2** (또는 `Qwen/Qwen2.5-1.5B-Instruct`) | SLM이라 단일 GPU(또는 CPU 추론 가능) 환경 친화 |
| RAG API | FastAPI | Phase 0–3에서 익힌 패턴 그대로 |
| 파이프라인 | Job (입문) 또는 Argo Workflows (확장) | 입문용은 단순 Job |
| 모니터링 | Prometheus + Grafana (Phase 3 그대로) | 재사용 |
| 게이트웨이 | nginx-ingress | Phase 2 그대로 |

## 단계별 일정 (1–2주)

| 일차 | 작업 |
|------|------|
| 1 | 아키텍처 이해 + Namespace 생성 + Qdrant StatefulSet 배포 |
| 2 | 임베딩 + 인덱싱 스크립트 작성, 로컬에서 테스트 |
| 3 | 인덱싱 Job 매니페스트로 클러스터에서 실행 |
| 4 | vLLM Deployment 배포 + OpenAI 호환 API 호출 확인 |
| 5 | RAG API 구현 (retriever + LLM 호출 결합) |
| 6 | RAG API Deployment + Service + Ingress |
| 7 | ConfigMap/Secret 분리, ServiceMonitor 추가 |
| 8 | Grafana 대시보드 + HPA 설정 |
| 9 | 부하 테스트 + 튜닝 |
| 10 | 문서화, 정리 |

## 학습 목표 (lesson.md 상단)

- 여러 K8s 워크로드(Deployment, StatefulSet, Job)를 통합한 시스템을 설계할 수 있다
- vLLM으로 SLM을 K8s에 서빙하고 OpenAI 호환 API로 호출할 수 있다
- 벡터 DB(Qdrant)를 StatefulSet으로 운영할 수 있다
- RAG 파이프라인(retrieval → augmentation → generation)을 K8s 환경에서 구현할 수 있다
- Prometheus/Grafana로 멀티 컴포넌트 시스템을 모니터링하고 HPA로 오토스케일링할 수 있다

## ML 시스템 관점 설계 노트 (lesson.md에 포함할 만한 내용)

### 왜 이런 분리인가

- **벡터 DB와 LLM 서빙 분리**: 임베딩 인덱스는 영속성(StatefulSet, PVC), LLM은 stateless(Deployment). 스케일 단위가 다릅니다
- **RAG API를 별도 레이어로**: retriever와 LLM 호출 로직 변경이 잦아 빠른 배포 사이클 필요
- **인덱싱은 Job/CronJob**: 추론과 분리해 GPU 자원 충돌 방지

### 트레이드오프

- vLLM scale-to-zero를 켜면 비용 ↓, cold start로 첫 요청 30초+
- Qdrant 단일 노드는 운영 단순하지만 SPOF. 운영에선 클러스터 모드
- 동기 호출은 단순하지만 LLM 생성이 느려 클라이언트 타임아웃 위험. SSE 스트리밍 권장

### 모니터링 핵심 메트릭

| 컴포넌트 | 메트릭 | 의미 |
|---------|-------|------|
| RAG API | request latency p95 | 사용자 체감 |
| RAG API | retriever_top_k_hit_ratio | retrieval 품질 |
| vLLM | `vllm:num_requests_running` | 동시 처리 요청 |
| vLLM | `vllm:gpu_cache_usage_perc` | KV cache 사용률 |
| Qdrant | search_latency_seconds | 검색 속도 |
| 노드 | nvidia_smi_gpu_memory_used_bytes | GPU 메모리 |

## 권장 RAG API 인터페이스

```python
POST /chat
{
  "messages": [
    {"role": "user", "content": "K8s에서 GPU 어떻게 잡지?"}
  ],
  "top_k": 5
}

Response:
{
  "answer": "...",
  "sources": [
    {"doc_id": "phase-4-1", "score": 0.92, "snippet": "..."},
    ...
  ]
}
```

스트리밍이 필요하면 `text/event-stream`으로 토큰 단위 응답.

## 자주 하는 실수

- vLLM과 RAG API를 같은 Pod에 묶기 → 스케일 단위가 달라 비효율
- Qdrant를 Deployment로 띄우기 → Pod 재시작 시 인덱스 손실
- 임베딩 모델을 매 요청마다 로딩 → 한 번 로드해서 메모리에 유지
- Secret(OpenAI 키 등)을 컨테이너 이미지에 굽기 → K8s Secret 사용
- 인덱싱 Job 실패 시 재시도 정책 없음 → `backoffLimit` + 알림
- vLLM HPA를 CPU 기준으로 → GPU 모델은 CPU가 한가해도 GPU가 포화. 커스텀 메트릭 사용

## 검증 시나리오 (학습자가 마지막에 돌리는 것)

```bash
# 1. 모든 컴포넌트 Running
kubectl get all -n rag-llm

# 2. 인덱싱 Job 완료
kubectl get job -n rag-llm
kubectl logs job/index-documents -n rag-llm

# 3. vLLM healthy
curl http://<vllm-svc>:8000/v1/models

# 4. RAG end-to-end
curl http://<ingress-host>/chat \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"GPU 노드만 사용하려면?"}],"top_k":3}'

# 5. 부하 테스트
hey -z 60s -c 20 -m POST -T application/json \
  -d '{"messages":[...],"top_k":3}' http://<ingress>/chat

# 6. HPA 동작 확인
watch kubectl get hpa,pods -n rag-llm
```

## 확장 아이디어 (lesson.md 끝에)

- Reranker 추가 (예: bge-reranker)
- 멀티 모달 (이미지 검색)
- 사용자 별 history 관리 (Redis)
- 평가 자동화 (RAGAS)
- 카나리 배포 (Service Mesh, Phase 5)
