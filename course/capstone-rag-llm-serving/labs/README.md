# 캡스톤 실습 가이드 (`labs/`)

> **상위 lesson**: [`../lesson.md`](../lesson.md)
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 별 작성 계획
> **현재 진행 상태**: Day 1~4 작성 완료. Day 5~10 후속 작성 예정.

본 디렉토리는 캡스톤(RAG 챗봇 + LLM 서빙) 의 Day 별 실습 가이드입니다. 각 lab 은 동일한 5 섹션 구조 + 트러블슈팅 표로 작성되어 있어 학습자가 일관된 흐름으로 진행할 수 있습니다.

```
Goal → 사전 조건 → Step → 검증 체크리스트 → 정리 → 🚨 트러블슈팅
```

---

## 사전 준비 (모든 Day 공통)

| 항목 | 요구사항 |
|---|---|
| 클러스터 | GKE T4 노드 풀 (Day 4 vLLM 부터). Day 1~3 은 CPU only 노드로 충분 |
| kubectl | 1.28+ — `kubectl config current-context` 가 캡스톤 클러스터 가리키는지 확인 |
| OS | macOS / Linux / WSL2 |
| 디스크 | 로컬 ~3GB (가상환경 + Docker 이미지 layer + HF 모델 캐시) |
| GitHub | 본 코스 레포(`k8s-for-mle`) 의 본인 fork (Day 3 의 git-clone step) |
| Docker Hub | 본인 계정 (Day 3 의 컨테이너 이미지 push) |

> 💡 **GKE 비용 관리**: 캡스톤 plan §11 비용 관리 원칙에 따라 Day 별 작업 끝에 노드풀을 0 으로 줄이거나 클러스터를 삭제합니다. T4 노드는 시간당 약 $0.35 — Day 1~3 은 GPU 가 필요 없으므로 T4 노드풀을 띄우지 않은 채 진행해도 됩니다.

---

## Day 별 lab 인덱스

| Day | 주제 | 산출물 | lesson 연결 |
|---|---|---|---|
| **Day 1** | Namespace + Qdrant StatefulSet + 아키텍처 초안 | manifests 3 개 (`00-namespace`, `10-qdrant-statefulset`, `11-qdrant-service`) + architecture.md 7 섹션 초안 | [`lesson.md`](../lesson.md) §1·§4.1·§4.2 |
| **Day 2** | 본 코스 자료 인덱싱 스크립트 (로컬 Python) | practice/pipelines/indexing/ 4 개 (Dockerfile, requirements.txt, pipeline.py, README.md) + Qdrant `rag-docs` 컬렉션 적재 | [`lesson.md`](../lesson.md) §3.2·§4.6 |
| **Day 3** | 동일 코드를 Argo Workflow 5-step DAG 으로 자동화 | manifests 3 개 (`49-argo-rbac`, `50-indexing-workflow`, `51-indexing-cronworkflow`) + Workflow Succeeded + CronWorkflow 일별 자동 실행 | [`lesson.md`](../lesson.md) §3.3·§4.7 |
| **Day 4** | vLLM Deployment + OpenAI 호환 API | manifests 4 개 (`20-vllm-deployment`, `21-vllm-pvc`, `22-vllm-service`, `23-vllm-hf-secret`) + GKE T4 노드 풀 추가 + `curl /v1/models` + OpenAI Python SDK `/v1/chat/completions` 호출 | [`lesson.md`](../lesson.md) §2.1·§4.3 |
| Day 5 | RAG API 구현 (로컬 개발) | (예정) | (예정) |
| Day 6 | RAG API 클러스터 배포 + Ingress | (예정) | (예정) |
| Day 7 | ConfigMap/Secret 분리 + ServiceMonitor | (예정) | (예정) |
| Day 8 | Grafana 대시보드 + HPA(커스텀 메트릭) | (예정) | (예정) |
| Day 9 | 부하 테스트 + 튜닝 | (예정) | (예정) |
| Day 10 | Helm 한 줄 배포 + 통합 검증 + 정리 | (예정) | (예정) |

---

## 작성 완료된 lab

- [`day-01-namespace-qdrant.md`](day-01-namespace-qdrant.md) — `rag-llm` Namespace + Qdrant StatefulSet 1 Pod + Headless Service + PVC 5Gi Bound + ordinal DNS 검증.
- [`day-02-indexing-script-local.md`](day-02-indexing-script-local.md) — 본 코스 자료(`course/phase-*/**/lesson.md` + `docs/study-roadmap.md`) 를 로컬 Python 으로 청크/임베딩하여 Qdrant 컬렉션 `rag-docs` 에 적재. 자기참조형 retrieval (`pipeline.py search`) 검증.
- [`day-03-indexing-argo.md`](day-03-indexing-argo.md) — Argo Workflow controller 설치 + RBAC 적용 + 컨테이너 이미지 빌드/푸시 + Workflow 5-step DAG (`git-clone → load-docs → chunk → embed → upsert`) Succeeded + CronWorkflow 매일 03:00 KST 자동화.
- [`day-04-vllm-deploy.md`](day-04-vllm-deploy.md) — GKE T4 노드 풀 추가(별도 GPU 노드 풀, taint 분리) + vLLM Deployment(microsoft/phi-2) + Service + 모델 캐시 PVC 적용 → 첫 기동 5~10 분 / 두 번째 기동 30 초 (PVC 캐시 효과) → `curl /v1/models` + OpenAI Python SDK `/v1/chat/completions` 검증.

---

## Day 간 연속성 안내

각 Day lab 의 §🧹 정리 섹션은 두 분기를 안내합니다.

- **다음 Day 로 바로 이어서 진행** — 클러스터·매니페스트·컬렉션을 그대로 유지하고 다음 lab 으로 넘어갑니다.
- **단독으로 끝낼 때 (또는 GKE 비용 절감)** — 본 Day 에서 만든 리소스를 명시적으로 삭제합니다. 이전 Day 리소스는 해당 Day lab 의 §🧹 정리를 참조합니다.

**예시**: Day 3 만 끝내고 잠시 중단할 경우 — Day 3 §🧹 정리 의 Argo controller 삭제 + Day 1 §🧹 정리 의 Qdrant + Namespace 삭제를 순서대로 실행. 또는 캡스톤 plan §11 의 GKE 클러스터 자체 종료(`gcloud container clusters delete`) 가 가장 간단합니다.

---

## 산출물 매핑 — 캡스톤 plan §8 과 동기화

각 lab 이 끝나면 [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) 의 다음 위치를 동기화합니다.

- §7 Day N 항목의 체크박스
- §8 산출물 4종 매핑 (lesson.md / 매니페스트·코드 / labs / GPU 클러스터 검증) 의 진행률
- §14 진행 메모에 결정 사항·이슈·이식 시 차이점 누적

[`docs/course-plan.md`](../../../docs/course-plan.md) 의 Capstone 섹션 Day N 체크박스도 함께 `[x]` 로 갱신합니다.
