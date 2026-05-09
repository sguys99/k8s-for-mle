# Capstone 강의 자료 작성 계획

> **기준 문서**: [study-roadmap.md](study-roadmap.md) (커리큘럼 SSOT), [course-plan.md](course-plan.md) (토픽 진행 체크리스트)
> **작성 스킬**: [`/k8s-ml-course-author`](../.claude/skills/k8s-ml-course-author/)
> **작성일**: 2026-05-05
> **사용법**: 캡스톤 작성을 진행하면서 본 문서의 체크박스를 `[x]`로 갱신해 현황을 추적합니다. 토픽 단위 체크리스트는 [course-plan.md](course-plan.md)와 함께 운용합니다.

---

## 1. Context — 왜 별도 계획이 필요한가

[course-plan.md](course-plan.md)의 캡스톤 섹션은 Day 1~10 체크박스만 있고, 다른 토픽(Phase 1~4)이 갖는 산출물 4종(`lesson.md` / 매니페스트·코드 / `labs/` / 검증) 작성 계획이 없습니다. 캡스톤은 **단일 토픽이 아닌 다중 컴포넌트 통합 프로젝트**(vLLM + Qdrant + RAG API + Argo + 모니터링 + Ingress)라 별도 작성 가이드가 필요합니다.

본 계획서는 캡스톤 강의 자료를 누가 보더라도 같은 결과물을 만들 수 있도록 **디렉토리 구조 / Day별 산출물 / 재사용 자산 매핑 / 검증 시나리오**를 명시하고, **모든 항목에 체크박스를 달아 현황을 한 화면에서 파악**할 수 있게 합니다.

---

## 2. 결정 사항 (사용자 승인 완료, 2026-05-05)

| 항목 | 결정 |
|------|------|
| labs 구성 | `labs/day-01.md` ~ `labs/day-10.md` 10개 파일로 분리 (course-plan.md Day 체크박스와 1:1 매핑) |
| 매니페스트 형태 | `manifests/`(raw YAML, 학습용) + `helm/`(차트, 한 줄 배포용) 두 트랙 모두 제공 |
| GPU 환경 | GCP GKE T4 노드 풀 전제, 매 Day 끝과 Day 10에 클러스터 삭제 명령 강조. CPU fallback은 부록 한 단락 |
| RAG 인덱싱 대상 | 본 코스 자료(`course/phase-*/**/lesson.md` + `docs/study-roadmap.md`) — 자기참조형 검증이 가능 |

---

## 3. 학습 목표 (`lesson.md` 상단에 명시)

- [ ] 학습 목표 1: 여러 K8s 워크로드(Deployment, StatefulSet, Job/Workflow)를 통합한 다중 컴포넌트 ML 시스템을 설계할 수 있다
- [ ] 학습 목표 2: vLLM으로 SLM을 K8s에 서빙하고 OpenAI 호환 API로 RAG API에서 호출할 수 있다
- [ ] 학습 목표 3: Qdrant 벡터 DB를 StatefulSet으로 운영하고 PVC로 인덱스를 영속화할 수 있다
- [ ] 학습 목표 4: retrieval → augmentation → generation으로 이어지는 RAG 파이프라인을 K8s 환경에서 구현할 수 있다
- [x] 학습 목표 5: Prometheus/Grafana로 멀티 컴포넌트 시스템을 모니터링하고 HPA(커스텀 메트릭)로 LLM 서빙을 오토스케일링할 수 있다 _(Day 7: kube-prometheus-stack + ServiceMonitor 24/34 → Prometheus Targets UP / Day 8: prometheus-adapter + HPA 25/35 + Grafana 대시보드 4 패널 + hey 60s 부하 REPLICAS 변동)_
- [ ] 학습 목표 6: 캡스톤 시스템 전체를 Helm 차트 한 줄로 배포·롤백할 수 있다

**완료 기준 (1줄)**: `curl http://<ingress-host>/chat -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'` → 200 OK + 답변 텍스트 + 인용 문서 3개

---

## 4. 디렉토리 구조 (산출물 체크리스트)

> 각 파일 작성 완료 시 체크. `★`는 캡스톤 신규 작성, `←`는 기존 Phase 토픽에서 이식.

### 4.1 루트 / 문서

- [ ] `course/capstone-rag-llm-serving/README.md` — 프로젝트 개요 + 아키텍처 다이어그램 + 일정표 ★
- [~] `course/capstone-rag-llm-serving/lesson.md` — 시스템 설계 설명 (이론, 600~800줄) ★ _(Day 1: 13섹션 골격 + §0·§1·§4.1·§4.2 채움 / 나머지 TBD)_
- [x] `course/capstone-rag-llm-serving/docs/architecture.md` — 컴포넌트 분리 이유, 트레이드오프, 메트릭 표 ★ _(Day 1 초안 7섹션)_

### 4.2 `manifests/` — Raw YAML (학습용, 번호 prefix로 적용 순서 명시)

- [x] `00-namespace.yaml` ★
- [x] `10-qdrant-statefulset.yaml` ← Phase 4-4 (Deployment+emptyDir → StatefulSet+volumeClaimTemplates 변환, namespace `ml-pipelines` → `rag-llm`)
- [x] `11-qdrant-service.yaml` ← (ClusterIP → Headless `clusterIP: None` 변환)
- [x] `49-argo-rbac.yaml` ★ Day 3 ← Phase 4-4 (namespace `ml-pipelines` → `rag-llm`, Workflow Pod ServiceAccount + Role + RoleBinding)
- [x] `20-vllm-deployment.yaml` ← Phase 4-3 (Day 4: namespace `rag-llm`, 라벨 캡스톤 컨벤션, 이름 `vllm-phi2` → `vllm`, PVC 이름 `vllm-model-cache`, args 6 종에 `--served-model-name=microsoft/phi-2` 추가, 모니터링/HPA 라벨 제거)
- [x] `21-vllm-pvc.yaml` ← (Day 4: namespace + 라벨 + 이름 `vllm-model-cache`)
- [x] `22-vllm-service.yaml` ← (Day 4: namespace + 라벨 + 이름 `vllm` + selector `app=vllm`)
- [x] `23-vllm-hf-secret.yaml` ← (Day 4: namespace + 라벨 + 주석 보강 — phi-2 public 이라 옵션 처리)
- [x] `24-vllm-servicemonitor.yaml` ← Day 7 (Phase 4-3 이식 5 변경점 — name `vllm-phi2`→`vllm`, namespace 추가, selector `app=vllm`, release 라벨 `prom`, 캡스톤 컨벤션 라벨)
- [x] `25-vllm-hpa.yaml` ★ Day 8 (prometheus-adapter + `vllm_num_requests_running` 별칭, Pods averageValue=8, minReplicas=1/maxReplicas=2, behavior 비대칭 scaleUp 0s/scaleDown 300s)
- [x] `30-rag-api-deployment.yaml` ★ Day 6 (replicas=2, env 6 종 직접 박기, /healthz/liveness + /ready/readiness/startup, hf-cache emptyDir 1Gi, RollingUpdate maxSurge=1 maxUnavailable=0) → **Day 7 envFrom 리팩토링** (env 7 줄 → configMapRef + secretRef.optional 2 줄)
- [x] `31-rag-api-service.yaml` ★ Day 6 (ClusterIP 8001, named port `http`, appProtocol http — Day 7 ServiceMonitor + Day 6 Ingress 공통 endpoint)
- [x] `32-rag-api-configmap.yaml` ★ Day 7 (data 6 키 — QDRANT_URL/COLLECTION/EMBED_MODEL/LLM_BASE_URL/LLM_MODEL/TOP_K, Day 6 env 6 종 *그대로 이전*)
- [x] `33-rag-api-secret.yaml` ★ Day 7 (Opaque, stringData HF_TOKEN placeholder, 23-vllm-hf-secret 와 *별도 Secret*, optional: true 부재 허용)
- [x] `34-rag-api-servicemonitor.yaml` ★ Day 7 (selector `app=rag-api`, endpoints `port: http` interval 30s, release 라벨 `prom` 으로 Prometheus CR 매칭)
- [x] `35-rag-api-hpa.yaml` ★ Day 8 (Pods 메트릭 `rag_chat_requests_per_second` Counter rate 변환 averageValue=10, minReplicas=2/maxReplicas=6, behavior 동일 비대칭, scaleTargetRef Deployment/rag-api)
- [x] `60-prometheus-adapter-values.yaml` ★ Day 8 (helm values, rules.custom 2 규칙 — RAG `_total`→`_requests_per_second` rate 변환 + vLLM `vllm:` 콜론 별칭, Prometheus URL `prom-kube-prometheus-stack-prometheus.monitoring.svc:9090`)
- [x] `61-grafana-rag-dashboard.yaml` ★ Day 8 (ConfigMap `monitoring` namespace + `grafana_dashboard: "1"` 라벨로 sidecar 자동 import, 4 패널 — chat req/s status별 / latency p95 chat·retrieve·llm 분해 / vLLM running·waiting / GPU KV cache gauge)
- [x] `40-ingress.yaml` ★ Day 6 (GCE Ingress, `<EXTERNAL_IP>.nip.io` host placeholder, /chat + /healthz Prefix, named port 참조, BackendConfig 미적용 — Day 8 예정)
- [x] `50-indexing-workflow.yaml` ← Phase 4-4 (Day 3: namespace 변경 + git-clone step 1개 신규 추가로 5-step DAG + 이미지 레지스트리 placeholder + env 6종 주입 + volumeClaimTemplate 통합 마운트)
- [x] `51-indexing-cronworkflow.yaml` ← Phase 4-4 (Day 3: workflowSpec 본문을 50과 동기화, embedding-model 기본값 `intfloat/multilingual-e5-small` 로 갱신)

### 4.3 `helm/` — 차트 (한 줄 배포용) ★ 신규 일체

- [ ] `Chart.yaml`
- [ ] `values.yaml` (모델, GPU 개수, replicas, ingress host)
- [ ] `values-dev.yaml` (CPU fallback / replicas 1)
- [ ] `values-prod.yaml` (GPU 1, replicas 3, HPA on)
- [ ] `templates/_helpers.tpl`
- [ ] `templates/namespace.yaml`
- [ ] `templates/qdrant.yaml`
- [ ] `templates/vllm.yaml`
- [ ] `templates/rag-api.yaml`
- [ ] `templates/ingress.yaml`
- [ ] `templates/monitoring.yaml`
- [ ] `templates/indexing.yaml`

### 4.4 `practice/rag_app/` — RAG API 코드 ★ 신규 일체

- [x] `Dockerfile` _(Day 5: 멀티스테이지 + port 8001 + main:app entrypoint)_
- [x] `requirements.txt` _(Day 5: fastapi/uvicorn/pydantic + qdrant-client/sentence-transformers/openai/prometheus-client, transformers/torch 제거)_
- [x] `main.py` (FastAPI 진입점, `/chat` `/healthz` `/ready` `/metrics`) _(Day 5: lifespan + app.state 캐싱, Pydantic ChatRequest/Response, 메트릭 4 종, 3 모듈 조립)_
- [x] `retriever.py` (Qdrant 검색) _(Day 5: QdrantRetriever 클래스 + RetrievedChunk dataclass, e5 query prefix, embed/qdrant 의존성 주입)_
- [x] `llm_client.py` (vLLM `/v1/chat/completions` 호출) _(Day 5: VLLMClient 클래스 + OpenAI SDK + timeout=120, served-model-name 매개변수)_
- [x] `prompts.py` (프롬프트 템플릿: system / context / user) _(Day 5: 한국어 SYSTEM_PROMPT + build_context + build_messages, 메타 4 종 노출, 인용 마커 [n] 강제)_
- [x] `tests/test_retriever.py` (로컬 단위 테스트) _(Day 5: 5+1 케이스, Qdrant·임베딩 모두 mock, CI 친화)_
- [x] `.env.example` _(Day 5: 6 환경변수 로컬 개발 템플릿)_

### 4.5 `practice/llm_serving/`

- [ ] `README.md` — vLLM 운영 노트 (cold start, gpu-mem-util 튜닝) ★
- [ ] `load_test.sh` — hey 기반 부하 테스트 스크립트 ★

### 4.6 `practice/pipelines/indexing/` ← Phase 4-4 이식 + 데이터 교체

- [x] `Dockerfile` _(Day 2: COPY sample_docs/ 제거, ENV 4종 기본값(QDRANT_URL=http://qdrant.rag-llm.svc:6333 등))_
- [x] `requirements.txt`
- [x] `pipeline.py` _(Day 2: 4 subcommand + all + search 보조. 화이트리스트 글로브, 메타데이터 4종, MD-header+Recursive 2단계, e5 prefix, idempotent upsert)_
- [x] `README.md` _(Day 2: 환경변수 표·실행 예·결정 노트 4건·트러블슈팅 표)_

> **임베딩 모델 결정 (Day 2, 사용자 승인)**: 초안 표기 `BAAI/bge-small-en` → **`intfloat/multilingual-e5-small` (384 dim, 한국어 다수 자료 대응)** 으로 교체. 차원 동일 → §4 PVC 5Gi 산정·Qdrant VectorParams 무수정. 결정 근거는 [`../course/capstone-rag-llm-serving/docs/architecture.md`](../course/capstone-rag-llm-serving/docs/architecture.md) §3.5.3.

### 4.7 `labs/` — Day별 실습 가이드

- [x] `labs/README.md` — 인덱스 (Day별 링크, 사전 준비, 정리 절차) ★ _(Day 3 작성: Day 1~3 완료 표기 + Day 4~10 예정 표기)_
- [x] `labs/day-01-namespace-qdrant.md` ★
- [x] `labs/day-02-indexing-script-local.md` ★ _(Day 2: Goal/사전조건 6/Step 10/검증 체크리스트/정리/트러블슈팅 7항목)_
- [x] `labs/day-03-indexing-argo.md` ★ _(Day 3: Goal 5/사전조건 6/Step 8/검증 체크리스트 8/정리/트러블슈팅 7항목)_
- [x] `labs/day-04-vllm-deploy.md` ★ _(Day 4: Goal 4/사전조건 6/Step 9/검증 체크리스트 8/정리 5 분기/트러블슈팅 11항목)_
- [x] `labs/day-05-rag-api-impl.md` ★ _(Day 5: Goal 4/사전조건 6/Step 9/검증 체크리스트 8/정리 2 분기/트러블슈팅 9항목)_
- [x] `labs/day-06-rag-api-deploy.md` ★ _(Day 6: Goal 4/사전조건 6/Step 9/검증 체크리스트 8/정리 2 분기/트러블슈팅 9항목 — Docker Hub 빌드/푸시 + Deployment/Service + GCE Ingress + nip.io 검증)_
- [x] `labs/day-07-config-secret-monitoring.md` ★ _(Day 7: Goal 4/사전조건 5/Step 8/검증 체크리스트 8/정리 2 분기/트러블슈팅 8항목 + Qdrant ServiceMonitor 부록 — ConfigMap/Secret 분리 + envFrom + kube-prometheus-stack + ServiceMonitor 2 종 + PromQL)_
- [x] `labs/day-08-grafana-hpa.md` ★ _(Day 8: Goal 4/사전조건 5/Step 8/검증 체크리스트 8/정리 2 분기/트러블슈팅 8항목 — Grafana sidecar 자동 import + prometheus-adapter Helm + custom.metrics.k8s.io API 노출 + HPA 2 적용 + hey 60s c=8 부하 + REPLICAS 변동(rag-api 2→4, vllm 1→2 두 번째 Pending) + Grafana 4 패널 동시 변동)_
- [ ] `labs/day-09-load-test-tuning.md` ★
- [ ] `labs/day-10-integration-cleanup.md` ★

---

## 5. 재사용 정책 (어디서 무엇을 가져오는가)

| 캡스톤 산출물 | 재사용 원본 | 변경 사항 | 이식 완료 |
|---------------|-------------|-----------|:---:|
| `manifests/10-qdrant-statefulset.yaml` | `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/02-qdrant.yaml` | **Deployment+emptyDir → StatefulSet+volumeClaimTemplates 변환**, namespace `ml-pipelines` → `rag-llm`, PVC 5Gi, Headless Service 분리 | [x] |
| `manifests/20-vllm-deployment.yaml` | `course/phase-4-ml-on-k8s/03-vllm-llm-serving/manifests/vllm-phi2-deployment.yaml` | (Day 4) 6 가지 변경: namespace `rag-llm`, 라벨 캡스톤 컨벤션(`app=vllm`/`component=llm-serving`), 이름 `vllm-phi2` → `vllm`, PVC 이름 `vllm-phi2-cache` → `vllm-model-cache`, **args 에 `--served-model-name=microsoft/phi-2` 추가**, 모니터링/HPA 라벨 제거 | [x] |
| `manifests/21-vllm-pvc.yaml`, `22-vllm-service.yaml`, `23-vllm-hf-secret.yaml` | Phase 4-3 동명 파일 | (Day 4) namespace + 라벨 + 이름(vllm-phi2 → vllm 일관) 변경 | [x] |
| `manifests/24-vllm-servicemonitor.yaml` | Phase 4-3 동명 파일 | (Day 7) 5 변경점 — name `vllm-phi2`→`vllm`, namespace 추가, selector `app=vllm` 일관, release 라벨 `kube-prometheus-stack`→`prom` (Phase 3-02 패턴), 캡스톤 컨벤션 라벨({app, component}) | [x] |
| `manifests/49-argo-rbac.yaml` | `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/01-argo-rbac.yaml` | (Day 3) namespace `ml-pipelines` → `rag-llm` 변경, ServiceAccount 이름 `workflow` 유지, Role 권한(`pods`/`pods/log`/`workflowtaskresults`) 동일 | [x] |
| `manifests/50-indexing-workflow.yaml` | `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/20-rag-indexing-workflow.yaml` | (Day 3) 5가지 변경: namespace, **git-clone step 1개 신규 추가**(5-step DAG), 이미지 `rag-pipeline:0.1.0` → `docker.io/<user>/rag-indexer:0.1.0`, env 6종 주입(DOCS_ROOT/ROADMAP_PATH/QDRANT_URL/PIPELINE_DATA_DIR/EMBED_MODEL/QDRANT_COLLECTION), volumeClaimTemplate 1개로 `/docs`+`/data` 통합 마운트 | [x] |
| `manifests/51-indexing-cronworkflow.yaml` | `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/30-rag-indexing-cron.yaml` | (Day 3) namespace 변경, workflowSpec 본문을 50과 동기화, embedding-model 기본값 `intfloat/multilingual-e5-small` (Day 2 결정 인용), schedule `0 3 * * *` Asia/Seoul + concurrencyPolicy: Replace 유지 | [x] |
| `practice/pipelines/indexing/pipeline.py` | Phase 4-4 `practice/rag_pipeline/pipeline.py` | (Day 2) 화이트리스트 재귀 글로브(`phase-*/**/lesson.md` + `capstone-*/lesson.md` + `study-roadmap.md`), 메타데이터 4종(source/phase/topic/heading) 보존, MD-header→Recursive 2단계 청킹, 모델 `intfloat/multilingual-e5-small` 로 교체 + e5 prefix, `recreate_collection` → `create_collection_if_not_exists + uuid5(point_id) + upsert` (idempotent), 보조 `all` / `search` subcommand 추가 | [x] |
| `manifests/30-rag-api-deployment.yaml` | `course/phase-4-ml-on-k8s/03-vllm-llm-serving/manifests/vllm-phi2-deployment.yaml` (구조) + `course/capstone-rag-llm-serving/manifests/20-vllm-deployment.yaml` (라벨 컨벤션) | (Day 6) GPU/PVC 제거, replicas 1→2, image `vllm/vllm-openai` → `docker.io/<user>/rag-api:0.1.0`, args 6→0(env 사용), env 6 종 신규(QDRANT_URL/COLLECTION/EMBED_MODEL/LLM_BASE_URL/LLM_MODEL/TOP_K), startupProbe 60×10s → 30×10s, resources 8Gi → 2Gi, RollingUpdate maxSurge=1 maxUnavailable=0, hf-cache emptyDir 1Gi | [x] |
| `manifests/31-rag-api-service.yaml` | `course/capstone-rag-llm-serving/manifests/22-vllm-service.yaml` | (Day 6) name `vllm` → `rag-api`, port 8000 → 8001, selector `app: vllm` → `app: rag-api`, named port `http` + appProtocol http (Day 7 ServiceMonitor 호환) | [x] |
| `manifests/40-ingress.yaml` | `.claude/skills/k8s-ml-course-author/assets/templates/manifests/ingress.yaml.tmpl` (골격) + `course/phase-2-operations/03-ingress/manifests/*` (rules 구조) | (Day 6) ingressClassName 생략 (GCE 기본), nginx annotations 제거 (`kubernetes.io/ingress.class: gce` 만), host placeholder `<EXTERNAL_IP>.nip.io`, path `/chat` + `/healthz` Prefix, backend named port `http` 참조 | [x] |
| `helm/templates/monitoring.yaml` | Phase 3 `02-prometheus-grafana` ServiceMonitor 패턴 | RAG API + vLLM + Qdrant 3종 통합 | [ ] |
| `helm/templates/_helpers.tpl`, `Chart.yaml` 골격 | Phase 3 `01-helm-chart/helm/` | 차트 이름 / appVersion 변경 | [ ] |
| `manifests/25-vllm-hpa.yaml` | Phase 3-03 `manifests/hpa-custom-metric.yaml` | (Day 8) Pods 메트릭 `predict_requests_per_second` → `vllm_num_requests_running` (adapter 별칭), scaleTargetRef Deployment/vllm, averageValue=8, minReplicas=1/maxReplicas=2 (T4 노드 풀 1 대 *체험형 학습 설계*), namespace `prod` → `rag-llm`, autoscaler 라벨 `rps` → `requests-running` | [x] |
| `manifests/35-rag-api-hpa.yaml` | Phase 3-03 `manifests/hpa-custom-metric.yaml` (형제) + `manifests/25-vllm-hpa.yaml` (캡스톤 라벨) | (Day 8) Pods 메트릭 `predict_requests_per_second` → `rag_chat_requests_per_second`, scaleTargetRef Deployment/rag-api, averageValue=10 (Day 7 측정 12 RPS 의 80% 안전선), minReplicas=2/maxReplicas=6, behavior 동일 비대칭 | [x] |
| `manifests/60-prometheus-adapter-values.yaml` | Phase 3-03 `manifests/prometheus-adapter/values.yaml` | (Day 8) rules.custom 1 → 2 규칙 — 규칙 1: RAG `_total` → `_requests_per_second` rate(2m) 변환 / 규칙 2 신규: vLLM `vllm:` 콜론을 `vllm_` 언더스코어 별칭(K8s API path 안전성) + Gauge `avg()` 쿼리, Prometheus URL 동일 | [x] |
| `manifests/61-grafana-rag-dashboard.yaml` | Phase 3-02 `manifests/grafana-dashboards/sentiment-api-dashboard.json` (JSON 골격) + `manifests/kube-prometheus-stack/values.yaml` (sidecar 라벨 매칭 메커니즘) | (Day 8) ConfigMap wrapper 신규(namespace=`monitoring`, label `grafana_dashboard: "1"`), title `Sentiment API` → `RAG-LLM Capstone`, 4 패널 PromQL 을 RAG/vLLM 메트릭으로 교체 — chat req/s status별 / latency p95 chat·retrieve·llm 단계별 분해 / vLLM running·waiting / GPU KV cache gauge(타입 stat→gauge 추가) | [x] |

**원칙**: 가져온 자산은 **출처 주석**(`# from course/phase-4-ml-on-k8s/04-argo-workflows/...`)을 매니페스트 상단에 답니다. lesson.md에서도 "Phase 4-X에서 익힌 ~~를 그대로 사용한다"고 명시해 학습 누적성을 강조합니다.

---

## 6. lesson.md 섹션 구성 (600~800줄 목표)

작성 진행에 따라 섹션 단위로 체크.

- [x] §0 학습 목표 6개 (위 §3에서 인용)
- [x] §0 도입 — 왜 ML 엔지니어에게 필요한가 (1문단)
- [x] §1 시스템 아키텍처 (ASCII 다이어그램 + 컴포넌트별 역할표, 80~100줄)
- [~] §2 왜 이렇게 분리했는가 (트레이드오프, 100줄) _(Day 4: §2 도입 + §2.1 vLLM 분리 4 축 + §2.2/§2.4 한 줄 인용 / Day 5: §2.3 RAG API 분리 4 축 신규 — 배포·상태·메트릭·의존성)_
- [x] §3 데이터 흐름 — **§3.1 챗봇 흐름(Day 5 완료, Day 6 보강) / §3.2 인덱싱 흐름(Day 2 완료) / §3.3 인덱싱 Workflow DAG(Day 3 완료)** 3 서브섹션 모두 작성됨
  - [x] §3.1 챗봇 호출 흐름 (`/chat` → 응답) — Day 5 작성 (7 단계 ASCII 시퀀스 + 단계별 책임/latency 표 + 동기 호출 채택 근거) + **Day 6 보강** (Day 5 port-forward ↔ Day 6 Ingress 호출 경로 비교 ASCII + 3 가지 운영적 차이 표)
  - [x] §3.2 인덱싱 데이터 흐름 (오프라인) — Day 2 작성 (4단계 ASCII 시퀀스 + 메타데이터 4종 보존 + 챗봇 경로와 분리 이유)
  - [x] §3.3 인덱싱 Workflow DAG (Day 3 — 클러스터 위 자동화) — 5-step DAG ASCII + Day 2↔Day 3 매핑 표 + git-clone 첫 step 결정 근거 + port-forward 차이
- [~] §4 핵심 매니페스트 해설 (라인 단위 주석) _(Day 1: §4.1·§4.2 / Day 2: §4.6 / Day 3: §4.7 / Day 4: §4.3 vLLM / Day 5: §4.4 자리표시 / Day 6: §4.4 RAG API + §4.5 Ingress 본문 작성 / **Day 7: §4.8 ConfigMap/Secret + §4.9 ServiceMonitor 신규**)_
  - [x] §4.3 vLLM Deployment (Day 4: 매니페스트 4 종 표 + args 6 종 발췌 + GPU 격리 3 종 발췌 + startupProbe 발췌 + volumes 발췌 + 결정 박스 4개(이름 통일, served-model-name, GPU 노드 풀 분리, HF Secret 옵션) + Day 4 추가 컴포넌트 표)
  - [x] §4.4 RAG API Deployment (Day 6: 매니페스트 4 종 표(30/31 + Day 7 예고 32/33) + 4 발췌(env 6 종 / 3 종 Probe / resources / RollingUpdate strategy) + 결정 박스 4개(replicas=2 비대칭, env 직접 박기, livenessProbe vs readinessProbe path 분리, emptyDir vs PVC) + Day 6 추가 컴포넌트 표)
  - [x] §4.5 Ingress (Day 6: 매니페스트 1 종 표 + 2 발췌(annotations+ingress class / rules) + 결정 박스 3개(GCE vs nginx, nip.io host, timeout 조정 Day 8 BackendConfig 로 미룸) + Day 6 추가 컴포넌트 표)
  - [x] §4.6 인덱싱 파이프라인 (Day 2: subcommand 표 + 4 코드 발췌 + idempotent 결정 박스)
  - [x] §4.7 Argo Workflow / CronWorkflow (Day 3: 매니페스트 3개 표 + 핵심 구조 발췌 + 결정 박스 4개(Workflow vs Job, volumeClaimTemplate 통합 마운트, namespace 분리+RBAC, CronWorkflow concurrencyPolicy+WorkflowTemplate 미도입) + Day 3 추가 컴포넌트 표)
  - [x] §4.8 ConfigMap / Secret 분리 (Day 7: 매니페스트 2 종 + Deployment 30 변경 표 + envFrom 일괄 발췌 + 결정 박스 4개(ConfigMap 1개 통합, Secret 별도 33 vs 23 재사용, envFrom vs env.valueFrom, ConfigMap 변경 시 재시작 4 옵션) + Day 7 추가 컴포넌트 표 (1))
  - [x] §4.9 ServiceMonitor (Day 7: 매니페스트 2 종 표 + RAG API ServiceMonitor 발췌 + 라벨 매칭 2 단계 ASCII + 결정 박스 3개(kube-prometheus-stack vs 직접 작성 vs GMP, release 라벨 `prom`, Qdrant ServiceMonitor 4 옵션) + Day 7 추가 컴포넌트 표 (2))
- [x] §5 RAG API 구현 노트 (Day 5: 6 소절 — §5.1 모듈 분리 원칙 표 + §5.2 retriever (e5 prefix + 모델 캐싱) + §5.3 llm_client (timeout/api_key/temperature) + §5.4 prompts (한국어 SYSTEM_PROMPT + 인용 마커) + §5.5 main (lifespan + 4 메트릭 + 결정 박스 임베딩 캐싱 3 옵션) + §5.6 tests/test_retriever 6 케이스 표)
- [x] §6 모니터링 핵심 메트릭 (Day 7: 4 축 소절 — §6.1 RAG API 메트릭 4 종 표 + §6.2 vLLM 메트릭 6 종 표 + §6.3 Qdrant 메트릭 부재 명시 + Day 10 도입 예고 + §6.4 GPU(DCGM) 메트릭 + 4 축 본 캡스톤 깊이 요약 / **Day 8 보강**: 4 패널 정의 갱신 — capstone-plan §7 초안의 *retriever hit-ratio* 패널을 §6.1 의 4 RAG 메트릭 단계별 분해(②번)로 교체, *GPU 메모리* 는 KV cache 사용률(④번)로 동등 시각화 명시)
- [x] §7 HPA 커스텀 메트릭 (Day 8: §7.1 왜 CPU 가 아닌 vllm:num_requests_running 인가 표 3 행 + §7.2 prometheus-adapter 4 단계 ASCII 다이어그램 + 단계별 검증 표 + §7.3 매니페스트 4 종 표 + 4 핵심 발췌 + 결정 박스 4개(num_requests_running 채택 / RAG Counter rate 변환 / behavior 비대칭 / maxReplicas=2 학습 설계) + §7.4 검증 명령 3 종 — 약 130 줄)
- [ ] §8 Helm으로 한 줄 배포 (values 분리(dev/prod), `helm install --create-namespace`, 50줄)
- [ ] §9 검증 시나리오 (6단계, §9와 동일)
- [~] §10 🚨 자주 하는 실수 _(Day 1: 3건 + Day 2: 3건 + Day 3: 3건 + Day 4: 3건 + Day 5: 3건 + Day 6: Ingress/배포 3건 + Day 7: ConfigMap/Secret/ServiceMonitor 3건 + **Day 8: HPA/Grafana/adapter 3건**(#22 prometheus-adapter `<<.LabelMatchers>>` template syntax 누락 → adapter Ready 인데 메트릭 미노출 / #23 HPA `scaleTargetRef.kind: ReplicaSet` 또는 ReplicaSet 이름 사용 → HPA 가 아무 일도 안 함 / #24 vLLM replicas 가 *왜 안 늘어나는가* 오해 → maxReplicas=2 + GPU 노드 풀 1 대 의 *체험형 학습 설계* 임을 인지) = 24건. 추후 Day 9 부하 OOM·Day 10 Helm checksum 항목 추가 예정)_
- [ ] §11 확장 아이디어 (reranker, 스트리밍, 멀티턴, RAGAS 평가, 30줄)
- [ ] §12 다음 단계 링크 (Phase 5 또는 본인 업무 적용)

---

## 7. Day별 작성 계획

각 `labs/day-NN-*.md`는 **Goal / 사전 조건 / Step / 검증 명령 / 정리** 5섹션 구조를 따릅니다. Day 단위로 매니페스트·코드·labs를 함께 추가합니다.

### Day 1 — Namespace + Qdrant + 아키텍처 초안
- [x] `manifests/00-namespace.yaml`
- [x] `manifests/10-qdrant-statefulset.yaml`, `11-qdrant-service.yaml` 이식 _(Deployment+emptyDir → StatefulSet+PVC 변환)_
- [x] `docs/architecture.md` 초안 _(7섹션)_
- [x] `labs/day-01-namespace-qdrant.md` _(Goal/사전조건/Step 8단계/검증/정리/트러블슈팅)_
- [ ] 검증: `curl qdrant:6333/healthz`, `kubectl get sts,pvc -n rag-llm` _(클러스터 실행 검증은 학습자 단계에서)_

### Day 2 — 인덱싱 스크립트 로컬
- [x] `practice/pipelines/indexing/{Dockerfile, requirements.txt, pipeline.py, README.md}` _(Phase 4-4 4-subcommand 골격 이식 + 6개 변경점 적용)_
- [x] 본 코스 자료(`course/phase-*/**/lesson.md` + `docs/study-roadmap.md`) 화이트리스트 인덱싱 — 메타데이터 4종(source/phase/topic/heading) 보존
- [x] `labs/day-02-indexing-script-local.md` _(Goal/사전조건/Step 10단계/검증/정리/트러블슈팅 7항목)_
- [x] lesson.md §3.2 + §4.6 + §10 (실수 3건) 보강, architecture.md §1+§3.5+§4+§7 갱신
- [ ] 검증: 학습자 단계 — `points_count > 0` (예상 500~800), `python pipeline.py search` 결과 top1 의 `payload.source` 가 본 코스 파일

### Day 3 — Argo Workflow로 인덱싱
- [x] `manifests/49-argo-rbac.yaml` 이식 (Phase 4-4 `01-argo-rbac.yaml` namespace 변경)
- [x] `manifests/50-indexing-workflow.yaml` 이식 + git-clone step 1개 신규 추가 → 5-step DAG (`git-clone → load-docs → chunk → embed → upsert`)
- [x] `manifests/51-indexing-cronworkflow.yaml` 이식 + workflowSpec 동기화 + 모델명 갱신
- [x] `labs/day-03-indexing-argo.md` (Goal 5/사전조건 6/Step 8/검증 8/정리/트러블슈팅 7)
- [x] lesson.md §1.1 다이어그램 보강 + §3.3 신규 + §4.7 신규 + §10 (실수 3건 추가, 총 9건), architecture.md §3.6+§3.7 신규 + §7 갱신
- [x] `labs/README.md` 신규 작성 (Day 1~3 인덱스 + Day 4~10 예정)
- [x] `practice/pipelines/indexing/README.md` Day 3 단락 갱신 (환경변수 비교 표 + step 매핑 + 이미지 빌드 명령)
- [ ] 검증: 학습자 단계 — Argo controller 설치 + RBAC 적용 + 이미지 빌드/푸시 + Workflow Succeeded + CronWorkflow `0 3 * * *` 표시 + 수동 트리거 + Day 2 와 동일 `points_count`

### Day 4 — vLLM Deployment
- [x] `manifests/20-vllm-deployment.yaml`, `21-vllm-pvc.yaml`, `22-vllm-service.yaml`, `23-vllm-hf-secret.yaml` 이식 (Phase 4-3 4 매니페스트 + 6 가지 변경)
- [x] `labs/day-04-vllm-deploy.md` (Goal 4/사전조건 6/Step 9/검증 8/정리 5 분기/트러블슈팅 11)
- [x] lesson.md §1.1 다이어그램(★ Day 4 ★ 마커) + §2.1 신규(vLLM 분리 4 축) + §4.3 신규(매니페스트 해설 + 결정 박스 4개) + §10 (실수 3건 추가, 총 12건), architecture.md §1 cold start 단락 + §3.8 신규(4 소절) + §7 갱신 + §부록 A Day 4 매니페스트 위치
- [x] `labs/README.md` Day 4 행 ✅ + 작성 완료된 lab 리스트에 day-04 추가
- [ ] 검증: 학습자 단계 — GKE T4 노드 풀 추가 → vLLM Pod Running + startupProbe 통과 → `curl /v1/models` 응답 `id="microsoft/phi-2"` → OpenAI Python SDK 호출 200 OK + 자연어 응답 → `kubectl rollout restart` 후 60 초 ready (PVC 캐시 효과) → GPU 노드 풀 size=0 축소

### Day 5 — RAG API 구현 (로컬)
- [x] `practice/rag_app/{Dockerfile, requirements.txt, main.py, retriever.py, llm_client.py, prompts.py}` _(Day 5: 6 모듈 + 모듈 분리 원칙(main 조립만, 3 모듈에 위임), e5 query prefix, 한국어 SYSTEM_PROMPT, OpenAI SDK timeout=120, lifespan + app.state 캐싱)_
- [x] `practice/rag_app/tests/test_retriever.py` _(Day 5: 5+1 mock 케이스 — search/payload/boundary/empty/e5 prefix/non-e5)_
- [x] port-forward로 vLLM·Qdrant 호출하며 로컬 개발 _(Day 5: 분리 터미널 2 개 + Terminal C 패턴, 백그라운드 변형은 트러블슈팅 #1 에 안내)_
- [x] `labs/day-05-rag-api-impl.md` _(Day 5: Goal 4/사전조건 6/Step 9/검증 8/정리 2 분기/트러블슈팅 9, .env.example 추가)_
- [x] lesson.md §1.1 다이어그램 ★ Day 5 ★ 마커 + §2.3 RAG API 분리 4 축 신규 + §3.1 챗봇 호출 흐름 신규 + §4.4 자리표시 + §5 RAG API 구현 노트 6 소절 + §10 자주 하는 실수 #13~#15, architecture.md §1 시퀀스 정밀화 + §3.9 동기 호출 + §3.10 임베딩 모델 로딩 전략 신규 + §7 Day 5 행 + 부록 A Day 5 항목
- [ ] 검증: 학습자 단계 — `pytest tests/ -v` 6 케이스 PASS + port-forward 2 개 + uvicorn `/chat` 200 OK + sources 3 개(메타 4 종 + score + chunk_id) + 답변에 `[n]` 인용 마커 등장 + `/metrics` 4 메트릭 노출

### Day 6 — RAG API 클러스터 배포 + Ingress
- [x] `manifests/30-rag-api-deployment.yaml` (replicas=2, env 6 종 직접 박기, RollingUpdate maxUnavailable=0, hf-cache emptyDir 1Gi), `31-rag-api-service.yaml` (named port `http`, appProtocol http), `40-ingress.yaml` (GCE Ingress, nip.io host placeholder, /chat + /healthz Prefix)
- [x] `labs/day-06-rag-api-deploy.md` (Goal 4/사전조건 6/Step 9/검증 8/정리 2 분기/트러블슈팅 9 — Docker Hub 빌드/푸시 sed 치환 + Deployment/Service + GCE Ingress + nip.io DNS 검증 + end-to-end /chat 200 OK + 답변에 [n] 인용 마커)
- [x] lesson.md §3.1 보강 (Day 5 port-forward ↔ Day 6 Ingress 비교 ASCII + 3 가지 운영적 차이 표) + §4.4 신규 (4 발췌 + 결정 박스 4개) + §4.5 신규 (2 발췌 + 결정 박스 3개) + §10 (3건 추가, 총 18건), architecture.md §3.11 신규 (Ingress 라우팅 결정 4 소절 — 3 옵션 비교/nip.io 채택/timeout Day 8 미룸/Phase 5 GitOps 호환) + §7 Day 6 행 + 부록 A Day 6 항목
- [x] `labs/README.md` Day 6 행 ✅ + 작성 완료된 lab 리스트에 day-06 추가
- [ ] 검증: 학습자 단계 — Docker Hub 이미지 빌드/푸시 → Deployment READY=2/2 → Service /healthz 200 → Ingress ADDRESS 부여(3~5 분) → nip.io nslookup 해석 → `curl http://<IP>.nip.io/chat` 200 OK + sources 3 개(메타 4 종 + score + chunk_id) + 답변에 `[1]` `[2]` `[3]` 인용 마커

### Day 7 — ConfigMap/Secret 분리 + ServiceMonitor
- [x] `manifests/32-rag-api-configmap.yaml` (data 6 키 — Day 6 env 6 종 그대로 이전), `33-rag-api-secret.yaml` (Opaque + stringData HF_TOKEN placeholder, 23 와 별도 Secret + optional: true)
- [x] `manifests/24-vllm-servicemonitor.yaml` (Phase 4-3 이식 5 변경점 — name `vllm-phi2`→`vllm`, namespace 추가, selector `app=vllm`, release 라벨 `prom`, 캡스톤 컨벤션 라벨), `34-rag-api-servicemonitor.yaml` (selector `app=rag-api`, endpoints `port: http` interval 30s, release 라벨 `prom`)
- [x] `manifests/30-rag-api-deployment.yaml` envFrom 리팩토링 (env 7 줄 → configMapRef + secretRef.optional 2 줄)
- [x] `labs/day-07-config-secret-monitoring.md` (Goal 4/사전조건 5/Step 8/검증 8/정리 2 분기/트러블슈팅 8 + Qdrant ServiceMonitor 부록)
- [x] lesson.md §4.8 ConfigMap/Secret 신규 + §4.9 ServiceMonitor 신규 + §6 모니터링 4 축 본문 + §10 자주 하는 실수 #19/#20/#21 추가, architecture.md §3.12 모니터링 결정 노트 신규 (4 소절 — release 라벨 매칭 / ConfigMap 재시작 4 옵션 / Qdrant 처리 4 옵션 / RBAC 분리 운영 가치) + §5 메트릭 표 실측값 갱신 + §7 Day 7 행 + 부록 A Day 7 항목
- [x] `labs/README.md` Day 7 행 ✅ + 작성 완료된 lab 리스트에 day-07 추가
- [ ] 검증: 학습자 단계 — ConfigMap/Secret apply → Deployment 30 envFrom 리팩토링 + `kubectl rollout restart` → kube-prometheus-stack `prom` release 설치(`monitoring` namespace) → ServiceMonitor 24/34 apply → Prometheus Targets 페이지 vllm + rag-api UP + PromQL `rate(rag_chat_total[1m])` / `vllm:num_requests_running` 그래프 확인 + Day 6 의 `/chat` 1 줄 완료 기준 회귀 없음

### Day 8 — Grafana 대시보드 + HPA
- [x] `manifests/25-vllm-hpa.yaml`, `35-rag-api-hpa.yaml` (Pods 메트릭 + behavior 비대칭, scaleTargetRef Deployment 명시)
- [x] `manifests/60-prometheus-adapter-values.yaml` (helm values, rules.custom 2 규칙) + `manifests/61-grafana-rag-dashboard.yaml` (ConfigMap, sidecar 자동 import 4 패널 — 초안의 retriever hit-ratio → §6.1 4 메트릭 단계별 분해 패널로 교체)
- [x] prometheus-adapter Helm 설치 → HPA 적용 → hey 60s c=8 부하로 스케일 트리거 (학습자 단계에서 검증)
- [x] `labs/day-08-grafana-hpa.md` (Goal 4/사전조건 5/Step 8/검증 8/정리 2 분기/트러블슈팅 8)
- [x] lesson.md §6 보강 + §7 신규(~130 줄, 결정 박스 4개) + §10 (3건 추가, 총 24건), architecture.md §3.13 신규 4 소절(HPA 결정 노트 — vLLM 메트릭 3 옵션·RAG API 필요성·behavior 비대칭·maxReplicas=2 학습 설계) + §5 메트릭 표 ◉/★ 마킹 + §7 Day 8 행 + 부록 A Day 8 항목 + 이식 원본 3 건 추가
- [x] `labs/README.md` Day 8 행 표 ✅ + 작성 완료된 lab 리스트에 day-08 추가
- [ ] 검증: 학습자 단계 — Grafana sidecar 자동 import 30 초 안에 "RAG-LLM Capstone" 4 패널 등장 → prometheus-adapter Pod Ready → `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1"` 결과 `pods/rag_chat_requests_per_second` + `pods/vllm_num_requests_running` 두 줄 → HPA TARGETS=`0/8`, `0/10` 안정화(60s) → hey 60s c=8 부하로 RAG API 2→4 / vLLM 1→2(두 번째 Pending) REPLICAS 변동 + Grafana 4 패널 동시 변동 + 부하 종료 후 5 분 stabilization 동안 REPLICAS 유지

### Day 9 — 부하 테스트 + 튜닝
- [ ] `practice/llm_serving/load_test.sh`
- [ ] `practice/llm_serving/README.md`
- [ ] hey로 멀티 페이로드 부하 → p95 latency 측정 → vLLM `gpu-memory-utilization` 1회전 튜닝
- [ ] `labs/day-09-load-test-tuning.md`
- [ ] 검증: p95 latency 보고 + 튜닝 전후 비교

### Day 10 — Helm + 통합 검증 + 정리
- [ ] `helm/Chart.yaml`, `values.yaml`, `values-dev.yaml`, `values-prod.yaml`
- [ ] `helm/templates/{_helpers.tpl, namespace, qdrant, vllm, rag-api, ingress, monitoring, indexing}.yaml`
- [ ] `course/capstone-rag-llm-serving/README.md` (일정표 + 통합 검증 절차)
- [ ] lesson.md 전체 검수 패스
- [ ] `labs/day-10-integration-cleanup.md`
- [ ] 검증: `helm uninstall` → `helm install` 한 줄 재배포 → §9 검증 시나리오 6단계 통과
- [ ] **GKE 클러스터 삭제 명령 실행 및 출력 캡처**

---

## 8. 산출물 4종 매핑 ↔ course-plan.md 캡스톤 체크박스

본 계획 진행과 함께 [course-plan.md](course-plan.md)의 다음 체크박스를 동기화합니다.

- [x] Day 1 — 아키텍처 문서 작성 + Namespace + Qdrant StatefulSet (2026-05-06)
- [x] Day 2 — 임베딩·인덱싱 스크립트 작성, 로컬 테스트 (2026-05-06)
- [x] Day 3 — 인덱싱 Argo Workflow 클러스터 실행 (2026-05-06)
- [x] Day 4 — vLLM Deployment + OpenAI 호환 API 호출 검증 (2026-05-07)
- [x] Day 5 — RAG API 구현 (retriever + LLM 결합) (2026-05-08)
- [x] Day 6 — RAG API Deployment + Service + Ingress (2026-05-09)
- [x] Day 7 — ConfigMap/Secret 분리, ServiceMonitor 추가 (2026-05-09)
- [x] Day 8 — Grafana 대시보드 + HPA(커스텀 메트릭) 설정 (2026-05-10)
- [ ] Day 9 — 부하 테스트(hey) + 튜닝
- [ ] Day 10 — 통합 검증 + 문서화 + 클러스터 삭제

산출물 4종 관점 체크 (캡스톤은 단일 토픽이지만 4종을 만족해야 함):

- [~] **lesson.md** — `course/capstone-rag-llm-serving/lesson.md` 13개 섹션 모두 작성 _(Day 1: §0·§1·§4.1·§4.2 / Day 2: §3.2·§4.6·§10 (3건) / Day 3: §1.1 보강·§3.3·§4.7·§10 (3건, 총 9건) / Day 4: §1.1·§2.1·§4.3·§10 (3건, 총 12건) / Day 5: §2.3·§3.1·§4.4 자리표시·§5·§10 (3건, 총 15건) / Day 6: §3.1 보강·§4.4·§4.5·§10 (3건, 총 18건) / Day 7: §4.8 ConfigMap/Secret 신규·§4.9 ServiceMonitor 신규·§6 모니터링 4 축 본문·§10 (3건 추가, 총 21건) / **Day 8: §6 보강(4 패널 정의 갱신)·§7 HPA 신규(~130 줄, 결정 박스 4개)·§10 (3건 추가, 총 24건))**)_
- [~] **매니페스트/코드** — `manifests/`(20개) + `helm/`(13개) + `practice/`(rag_app·llm_serving·pipelines) _(Day 1: manifests 3건 / Day 2: practice/pipelines/indexing/ 4건 / Day 3: manifests 3건(49·50·51) + indexing README 갱신 / Day 4: manifests 4건(20·21·22·23) / Day 5: practice/rag_app/ 9건 / Day 6: manifests 3건 추가(30·31·40) / Day 7: manifests 4건 추가(32·33·24·34) + Deployment 30 envFrom 리팩토링 / **Day 8: manifests 4건 추가(25·35·60·61))**_
- [~] **labs/** — `labs/README.md` + `labs/day-01.md ~ day-10.md` (총 11개) _(Day 1·2·3·4·5·6·7·8 작성 완료, README 갱신 완료, day-09~day-10 미작성)_
- [ ] **GPU 클러스터 검증** — Day 10 통합 검증 + GKE 클러스터 삭제 로그

---

## 9. 검증 시나리오 (캡스톤 lesson.md §9 / labs/day-10에 동일 게재)

```bash
# 0. 사전: 모든 Pod Running
kubectl get all -n rag-llm

# 1. 인덱싱 Workflow 성공
kubectl get wf -n rag-llm
# → STATUS=Succeeded, 컬렉션 docs count > 0

# 2. vLLM 서빙
kubectl port-forward -n rag-llm svc/vllm 8000:8000 &
curl http://localhost:8000/v1/models | jq
# → "id":"microsoft/phi-2"

# 3. RAG end-to-end (1줄 완료 기준)
INGRESS=$(kubectl get ing -n rag-llm rag-ingress -o jsonpath='{.spec.rules[0].host}')
curl http://$INGRESS/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' | jq
# → 200 OK, answer 텍스트, sources 3개

# 4. 부하 테스트 + HPA 스케일
bash practice/llm_serving/load_test.sh
watch kubectl get hpa,pods -n rag-llm
# → REPLICAS가 부하에 따라 증가

# 5. Helm 재배포
helm uninstall rag-llm -n rag-llm
helm install rag-llm helm/ -f helm/values-prod.yaml -n rag-llm --create-namespace
# → 한 줄 재배포 후 동일 검증 통과

# 6. 클러스터 삭제 (필수)
gcloud container clusters delete capstone --zone us-central1-a --quiet
```

검증 단계 체크:

- [ ] §1 인덱싱 Workflow Succeeded
- [ ] §2 vLLM `/v1/models` 응답 확인
- [ ] §3 RAG end-to-end 200 OK + sources 3개
- [ ] §4 HPA REPLICAS 변동 관측
- [ ] §5 Helm 한 줄 재배포 후 §1~§4 재통과
- [ ] §6 GKE 클러스터 삭제 완료

---

## 10. 작성 품질 체크리스트 (skill quality + 캡스톤 특화)

각 산출물 작성 종료 시 점검:

- [ ] 학습 목표 6개가 lesson.md 상단에 명시됨
- [ ] 도입부에 "왜 ML 엔지니어에게 필요한가" 1문단
- [ ] 매니페스트 비자명한 라인에 한국어 주석 (`gpu-memory-utilization`, `failureThreshold`, `volumeClaimTemplates` 등)
- [ ] Day별 labs에 실행 → 검증 → 정리 절차가 순서대로
- [ ] `kubectl get pods/wf/hpa` 등 주요 명령의 예상 출력이 코드 블록으로
- [ ] 🚨 자주 하는 실수 3개 lesson.md 끝부분에
- [ ] 다음 단계 링크 (Phase 5 또는 본인 업무)
- [ ] 모든 매니페스트가 `kubectl apply --dry-run=client -f manifests/` 통과
- [ ] **(캡스톤 특화)** Phase 4-3/4-4 자산 이식 시 출처 주석 명시
- [ ] **(캡스톤 특화)** Day 10 마지막에 GKE 클러스터 삭제 명령 강조 박스
- [ ] **(캡스톤 특화)** `helm install ... helm/` 한 줄 재배포가 raw 매니페스트 결과와 동등
- [ ] **(캡스톤 특화)** 자기참조형 검증 — RAG 응답에 본 코스 자료의 문장이 실제로 인용되는지 한 번 시연

---

## 11. 위험 / 주의사항

- [ ] **GKE 비용 관리**: T4 노드 시간당 약 $0.35. Day별 작업 끝에 `gcloud container clusters delete` 또는 노드풀 0으로 축소 안내를 lesson.md/labs에 명시
- [ ] **vLLM 모델 다운로드 시간**: phi-2 약 5GB. 첫 실행 시 `startupProbe.failureThreshold=60` 필수, PVC 캐시 활성화로 재시작 가속
- [ ] **Argo 컨트롤러 충돌 방지**: Phase 4-4에서 Argo namespace를 만들었다면 캡스톤은 그 위에서 동작. 새로 시작할 경우 Argo 설치 단계를 Day 3 labs에 포함
- [ ] **이식 누락 검증**: namespace 일괄 치환 시 Secret/ServiceMonitor/Service 이름 참조도 함께 수정. 매니페스트 적용 전 `grep -r argo manifests/` 점검 명령 lab에 포함

---

## 12. 핵심 참조 파일 경로

작성 시 참조할 파일들 — 모든 경로는 프로젝트 루트 기준.

- 로드맵: `docs/study-roadmap.md` §Capstone, §Phase 4
- 진행 체크리스트: `docs/course-plan.md` §Capstone
- 스킬 진입점: `.claude/skills/k8s-ml-course-author/SKILL.md`
- 스킬 캡스톤 레퍼런스: `.claude/skills/k8s-ml-course-author/references/capstone-rag-llm.md`
- 스킬 한국어 톤 가이드: `.claude/skills/k8s-ml-course-author/references/korean-style-guide.md`
- 이식 원본:
  - `course/phase-4-ml-on-k8s/03-vllm-llm-serving/manifests/`
  - `course/phase-4-ml-on-k8s/04-argo-workflows/{manifests,practice}/`
- Helm 차트 골격 참고: `course/phase-3-production/01-helm-chart/`
- 모니터링 패턴 참고: `course/phase-3-production/02-prometheus-grafana/`, `03-autoscaling-hpa/`

---

## 13. 다음 액션 (본 계획 승인 후)

- [ ] Day 1 작업 시작: `/k8s-ml-course-author` 스킬 호출 → `course/capstone-rag-llm-serving/` 디렉토리 생성 → Day 1 산출물 4건 작성
- [ ] Day 1 완료 시 `docs/course-plan.md` 캡스톤 Day 1 체크박스 + 본 문서 §7 Day 1 체크박스 동기화
- [ ] 이후 Day 2~10 동일 순서 반복
- [ ] Day 10 종료 시 §10 품질 체크리스트와 §9 검증 시나리오를 모두 만족하는지 최종 점검

---

## 14. 진행 메모 (작성 중 기록)

> 캡스톤 작성을 진행하면서 결정/이슈/이식 시 발견한 차이점을 이 섹션에 누적합니다.

- **2026-05-06 (Day 1)** — 이식 원본 차이 발견: `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/02-qdrant.yaml`은 **Deployment + emptyDir** 패턴이라 단순 namespace 치환이 아닌 **Deployment → StatefulSet, emptyDir → volumeClaimTemplates(PVC 5Gi)** 변환을 수행했습니다. 결과 매니페스트(`manifests/10-qdrant-statefulset.yaml`) 상단에 변환 사실을 출처 주석으로 명시했습니다.
- **2026-05-06 (Day 1)** — Qdrant Service 형태를 Headless 1개(`clusterIP: None`)로 결정. StatefulSet 정석 패턴이며 향후 Qdrant 클러스터링(replicas > 1) 시 무수정으로 ordinal DNS(`qdrant-0.qdrant.rag-llm.svc...`)가 동작합니다. lesson.md §4.2 와 docs/architecture.md §3 에 결정 근거를 기록했습니다.
- **2026-05-06 (Day 1)** — lesson.md 는 13섹션 헤딩 골격을 모두 배치하고 Day 1 관련 §0(학습목표 6개+도입)·§1(시스템 아키텍처 ASCII+역할표)·§4.1(Namespace)·§4.2(Qdrant StatefulSet+Headless)만 채웠습니다. 나머지 §2·§3·§4.3~§4.5·§5~§9·§11·§12 는 `<!-- TBD: Day N -->` 주석으로 자리표시 — 이후 Day 마다 누적 보강합니다.
- **2026-05-06 (Day 1)** — `docs/architecture.md` 7섹션 초안 작성: §1 시스템 개요(시퀀스 ASCII), §2 컴포넌트 분리 표, §3 왜 StatefulSet인가(Day 1 핵심), §4 PVC 5Gi 산정 근거, §5 메트릭 표(예고), §6 Qdrant 대안 비교, §7 Day별 갱신 표. Day 2(데이터 흐름)→Day 4(vLLM)→Day 8(HPA) 시점에 보강 예정.
- **2026-05-06 (Day 1)** — StatefulSet 이 캡스톤에서 **처음 본격 도입**됨을 인지하고, lesson.md §4.2 와 architecture.md §3 에 `serviceName ↔ Service.name` 매칭 규칙, `volumeClaimTemplates` 가 만드는 PVC 이름 규칙(`<vct>-<sts>-<ord>` → `qdrant-storage-qdrant-0`), Headless Service 의 `clusterIP: None` 의미를 모두 처음 설명했습니다. labs/day-01 §🚨 트러블슈팅 표에도 동일 항목 3건 반영.
- **2026-05-06 (Day 2)** — **임베딩 모델 교체 결정 (사용자 승인)**: 본 plan §4.6 초안 `BAAI/bge-small-en` → `intfloat/multilingual-e5-small` (둘 다 384 dim). 본 코스 자료가 한국어 다수라 영어 전용 모델로는 retrieval recall 부족. 차원 동일 → architecture.md §4 PVC 5Gi 산정값과 Qdrant `VectorParams.size` 무수정으로 호환. e5 계열 prefix(`passage:`/`query:`) 규약 준수를 위해 `pipeline.py` 의 `_E5_PASSAGE_PREFIX`/`_E5_QUERY_PREFIX` 상수와 `_is_e5_model()` 분기 추가. capstone-plan §4.6 + architecture.md §3.5.3·§4 동기화.
- **2026-05-06 (Day 2)** — **port-forward 패턴 채택**: 로컬 Python 스크립트 → 클러스터 Qdrant 접근에 `kubectl port-forward -n rag-llm svc/qdrant 6333:6333` 사용 (Day 1 의 Headless Service 도 port-forward 가능 — Endpoints 중 1 Pod 으로 자동 연결). Day 3 컨테이너 실행으로 전환 시 `QDRANT_URL` 환경변수만 `http://qdrant.rag-llm.svc:6333` 로 변경하면 코드 수정 불필요. labs/day-02 Step 2/Step 10 + README 환경변수 표에 명시.
- **2026-05-06 (Day 2)** — **idempotent upsert 트레이드오프**: Phase 4-4 의 `recreate_collection` (매 실행마다 비우기) → `create_collection_if_not_exists + uuid5(NAMESPACE_URL, chunk_id) + upsert` 로 전환. 운영 시 무중단 재인덱싱 + 부분 갱신 가능. 차원 불일치만 명시적 에러로 처리. lesson.md §4.6.5 결정 박스 + §10 자주 하는 실수 ⑥번. Day 3 Argo Workflow / CronWorkflow 설계 시 본 패턴이 이어집니다.
- **2026-05-06 (Day 2)** — **lesson.md §3 분할 결정**: 캡스톤 plan §6 의 단일 §3(데이터 흐름)은 챗봇 호출 흐름만 가정했으나, 캡스톤은 인덱싱(오프라인 배치) 와 챗봇(온라인 동기) 두 흐름이 분리 운영되므로 §3 을 §3.1 (챗봇 — Day 5 채움) + §3.2 (인덱싱 — Day 2 작성 완료) 로 분할. 본 plan §6 의 섹션 표도 함께 갱신.
- **2026-05-06 (Day 2)** — **청크 메타데이터 4 종(`source/phase/topic/heading`) 도입**: Day 5/6 의 RAG API 가 응답 `sources` 항목에 그대로 노출할 출처 라벨. 인덱싱 시점에 부여하지 않으면 검색 후 파일 역추적이 필요해 latency 가 늘어남. 청킹 1 차에 `MarkdownHeaderTextSplitter(strip_headers=False)` 로 h1/h2/h3 보존 후 ` > ` 로 연결한 헤딩 경로(`Phase 4 > vLLM > startupProbe`) 형식. architecture.md §3.5.1·§3.5.2 에 결정 근거.
- **2026-05-06 (Day 3)** — **입력 데이터 적재: Workflow 첫 step 에서 git-clone (사용자 승인)**: 본 plan §2 에 정리된 3 옵션(A: git-clone step / B: kubectl cp 사전 적재 / C: ConfigMap) 중 A 선택. Argo 의 step 의존성·자동화 가치를 살리고 CronWorkflow 가 매 실행마다 자동으로 main 브랜치 최신 자료 반영. DAG 가 4-step → **5-step** (`git-clone → load-docs → chunk → embed → upsert`) 으로 확장. 매니페스트 `50-indexing-workflow.yaml` 의 git-clone-step template 에 `alpine/git:2.45.2` + `git clone --depth 1` 으로 약 50MB shallow clone 으로 부담 최소화. 학습자 본인 fork 가 public 이라는 전제(plan §13 위험 항목).
- **2026-05-06 (Day 3)** — **이미지 레지스트리: Docker Hub 본인 계정 (사용자 승인)**: 매니페스트의 placeholder `docker.io/<user>/rag-indexer:0.1.0` 는 labs Step 4 의 `sed` 명령으로 본인 ID 로 일괄 치환. GKE 노드는 public Docker Hub 이미지를 무인증 pull. Phase 4-4 의 `minikube docker-env` 패턴(로컬 inner Docker daemon) 은 GKE 환경에서 동작하지 않아 캡스톤은 외부 레지스트리로 전환. GAR/Kaniko 대안은 학습 부담으로 제외. labs/day-03 §🔧 사전 조건 + Step 3 + Step 4 에 명시.
- **2026-05-06 (Day 3)** — **WorkflowTemplate 미도입 (사용자 승인)**: 50 과 51 의 workflowSpec 본문이 거의 동일해 DRY 가 깨지지만, 캡스톤의 학습 목표는 Argo 자체가 아닌 RAG 시스템 통합이므로 단순성 우선. WorkflowTemplate 의 가치(공통 4-step DAG 추출, templateRef 참조)는 lesson.md §4.7 결정 박스 ④ + Phase 4-4 lesson §1-1 링크로 한 줄 안내. 향후 Day 4~10 의 매니페스트 누적이 늘어나면 도입 재고 가능.
- **2026-05-06 (Day 3)** — **단일 PVC 통합 마운트 (mountPath 2 개로 `/docs` + `/data`)**: 5 step 이 공유할 데이터를 별도 PVC 2 개로 나누면 RWO accessMode 노드 제약이 step 마다 두 번 발생. 단일 PVC 의 mountPath 2 개로 통합하면 step 들이 같은 노드에서 순차 실행 + volumeClaimGC 가 1 개만 정리. architecture.md §3.7 에 운영 한계(진짜 병렬화 시 RWX 필요, 다른 워크플로우 간 공유 시 객체 스토리지) 까지 정리. lesson.md §4.7 결정 박스 ② + §10 자주 하는 실수 ⑨번에서도 강조.
- **2026-05-06 (Day 3)** — **namespace 분리: controller 는 `argo`, Workflow 는 `rag-llm`**: 두 namespace 를 같게 두면 RBAC 단순화되지만, 분리하면 캡스톤(`rag-llm`) 만 통째로 삭제할 때 controller 가 영향 받지 않음. 추가 비용은 RBAC 매니페스트 1 개(`49-argo-rbac.yaml`). Workflow Pod 가 자식 Pod 생성하려면 ServiceAccount `workflow` + Role(`pods`/`pods/log`/`workflowtaskresults`) + RoleBinding 필요. 누락하면 `pods is forbidden` 메시지 — Phase 4-4 자주 하는 실수 1번 + 캡스톤 lesson.md §10 자주 하는 실수 ⑦번 동일.
- **2026-05-06 (Day 3)** — **CronWorkflow `concurrencyPolicy: Replace` 채택**: 3 옵션(Allow/Forbid/Replace) 중 Replace. Day 2 의 idempotent upsert 패턴(uuid5 결정론적 point ID + create_if_not_exists) 이 동일 자료 재실행을 안전하게 만들어 주므로 Replace(이전 취소 후 새로 시작) 가 자연스러움. Allow 는 동일 PVC 경합 위험, Forbid 는 자료 갱신 지연. lesson.md §4.7 결정 박스 ④에 명시.
- **2026-05-07 (Day 4)** — **GPU 환경: 기존 `capstone` 클러스터에 T4 노드 풀 1 노드 추가 (사용자 승인)**: 본 plan §7 Day 4 의 사전 조건. 별도 GPU 클러스터 신규 생성은 RAG API → vLLM 호출이 클러스터 내부 DNS 한 줄로 끝나지 않아 단순성 저해. 단일 GPU 노드 풀(Qdrant/Argo 도 T4 노드에) 도 비용 비효율. 절충은 별도 GPU 노드 풀 + `nvidia.com/gpu=present:NoSchedule` taint 분리 — CPU 워크로드는 e2-medium, vLLM 만 T4. Day 4 종료 시 GPU 노드 풀만 size=0 으로 축소 가능 (5 분 안에 복원). architecture.md §3.8.3 표 형식으로 정리.
- **2026-05-07 (Day 4)** — **이름 통일 결정: `vllm-phi2` → `vllm`**: Phase 4-3 의 Deployment / Service / PVC 이름이 모두 `vllm-phi2` 였습니다 — *모델명 종속* 이라 Day 9 모델 교체 시 매니페스트 + RAG API 의 `OPENAI_BASE_URL` env 까지 4 곳을 함께 변경해야 합니다. 캡스톤은 이름을 `vllm` (Service/Deployment) + `vllm-model-cache` (PVC) 로 단순화 — Service DNS `vllm.rag-llm.svc.cluster.local:8000` 가 모델 교체와 무관한 안정 endpoint. 모델 종속성은 `--served-model-name` 한 곳으로만 격리 (lesson.md §4.3 결정 박스 ①).
- **2026-05-07 (Day 4)** — **`--served-model-name=microsoft/phi-2` 명시 결정 (사용자 승인 — HF ID 그대로)**: 3 옵션(HF ID 그대로 / 단축 `phi-2` / 논리명 `capstone-llm`) 중 HF ID. 학습자가 OpenAI SDK 호출(`model="microsoft/phi-2"`) 을 그대로 재현하는 것이 학습 흐름에 자연스러움. 운영적으로 가장 깔끔한 논리명(`capstone-llm`) 은 학습자가 *왜 capstone-llm 인지* 를 한 번 더 추론해야 하는 부담이 있어 캡스톤 학습 단계에서는 후순위. 향후 Phase 5 (멀티 클러스터/GitOps) 시점에 마이그레이션 — 그 때는 `--served-model-name` 한 줄 + RAG API env 한 줄 = 2 곳만 수정. architecture.md §3.8.4 표 형식으로 정리.
- **2026-05-07 (Day 4)** — **HF Secret 옵션 처리**: phi-2 는 HuggingFace public 이라 토큰 없이 다운로드. Deployment 의 `valueFrom.secretKeyRef.optional: true` 가 Secret 부재를 정상 처리. 캡스톤 디폴트는 Secret 미적용. 토큰이 필요한 두 시나리오(rate limit / gated 모델) 만 학습자에게 안내. 학습용 매니페스트라 평문 placeholder 를 그대로 두고, 운영 시 SealedSecrets / External Secrets Operator 로 전환 권장 (lesson.md §4.3 결정 박스 ④).
- **2026-05-07 (Day 4)** — **lesson.md §2 분할 결정**: 캡스톤 plan §6 의 §2(왜 이렇게 분리했는가) 를 Day 4 에서 vLLM 분리 4 축으로 본격 작성. §2.1 (vLLM 분리, Day 4 작성 완료) / §2.2 (인덱싱 분리, §3.6 한 줄 인용) / §2.3 (RAG API 분리, Day 5~6 TBD) / §2.4 (단일 Namespace, Day 1 §1.3 인용) 로 4 분할. 향후 Day 5/6 작성 시 §2.3 만 채우면 §2 완성.
- **2026-05-07 (Day 4)** — **cold start 운영적 의미를 architecture.md §3.8.2 로 분리**: vLLM cold start 5~10 분이 *Pod 라이프사이클 한 번에 한 번* 만 발생하는 latency 임을 §1 시퀀스 본문 단락에 한 문단 추가. 더 깊은 결정 노트(rolling update 가용성, Day 6 Helm 차트 values 매핑) 는 §3.8.2 로. Day 6 Helm 차트 작성 시 `values-prod.yaml.replicas: 2` + PVC 캐시 + startupProbe 길이 3 가지가 함께 있어야 사용자 체감 다운타임 0 이라는 결정.
- **2026-05-07 (Day 4)** — **자주 하는 실수 3 건 추가 (Day 4 — vLLM/GPU)**: ⑩ T4 노드 풀 taint 누락 (gcloud `--node-taints` 누락 시 vLLM Pod 가 CPU 노드에 schedule), ⑪ served-model-name 불일치 (Day 6 시점 발견되는 후속 문제 — Day 4 시점에 미리 강조), ⑫ 모델 캐시 PVC 디스크 누적 (Day 9 모델 교체 후 두 모델 캐시 누적). Phase 4-3 의 자주 하는 실수 1·2·3번(GPU 누락/`/dev/shm`/0.95+) 은 매니페스트가 *해결된 상태* 로 작성됐으므로 한 줄 링크로 처리 — 본 캡스톤에서 학습자가 처음부터 매니페스트를 작성할 때만 재현됨.
- **2026-05-08 (Day 5)** — **모듈 분리 4 개 (사용자 승인)**: 단일 `rag_app.py` 골격(skill 템플릿 163 줄) → `main.py(140) + retriever.py(120) + llm_client.py(75) + prompts.py(70)` 4 모듈로 분리. 결정 근거는 *각 외부 의존성(Qdrant + vLLM)의 단위 테스트를 분리하기 위함* — Phase 4-3 의 단일 fastapi_app.py 패턴과 의도적으로 다름. main.py 는 *조립* 만 담당하고 실 로직은 3 모듈에 위임 → 80~140 줄로 유지 가능. lesson.md §5.1 모듈 분리 원칙 표 + architecture.md §3.10 임베딩 캐싱 전략에 기록.
- **2026-05-08 (Day 5)** — **§2.3 RAG API 분리 4 축 채택 (사용자 승인)**: §2.1 vLLM 분리 4 축(스케일/라이프사이클/메트릭/모델 교체 빈도) 의 *거울 짝* 으로 RAG API 측 4 축(배포 사이클/상태성/메트릭 축/의존성 방향) 을 작성. §2.1 과 같은 4 분 구조를 두 컴포넌트 시점에서 한 번씩 본 결과로 §2 전체가 4+1+1+1 결정 노트로 완성됨. 추후 Day 5~6 에서 Day 6 RAG API 매니페스트(30~33) 작성 시 §2.3 결정을 그대로 인용.
- **2026-05-08 (Day 5)** — **한국어 SYSTEM_PROMPT 채택 (사용자 승인)**: phi-2 가 영어 강한 SLM 이지만 본 캡스톤 인덱싱 대상 자료가 한국어이므로 답변 언어 일관성 우선. prompts.py 의 SYSTEM_PROMPT 가 4 가지를 강제: (1) 역할 — Kubernetes/ML 전문가, (2) 한국어 답변, (3) Context 한정 (환각 차단), (4) [번호] 인용 마커. lesson.md §5.4 결정 근거 명시. 영어 prompt 비교는 §11 확장 아이디어로 미룸.
- **2026-05-08 (Day 5)** — **port-forward 분리 터미널 패턴 (사용자 승인)**: Day 5 lab 은 Terminal A(Qdrant 6333) + Terminal B(vLLM 8000) + Terminal C(uvicorn) 3 터미널 패턴 채택. Day 2 의 백그라운드 `&` 패턴과 다른 결정 근거: *각 endpoint 의 로그가 독립 추적 가능* + *Ctrl+C 명시적 종료* 로 디버깅 친화. 백그라운드 변형은 lab 트러블슈팅 #1 에 한 줄 변형으로만 안내.
- **2026-05-08 (Day 5)** — **테스트 전략 — Qdrant mock 위주 + 라이브는 lab 검증 (사용자 승인)**: tests/test_retriever.py 5+1 케이스가 모두 `MagicMock` 으로 Qdrant client + 임베딩 모델 주입. CI 친화적이고 port-forward 없이 통과. 라이브 검증은 lab Step 4(retriever 단독 호출) + Step 8(`/chat` curl) 두 곳으로 분리. QdrantRetriever.__init__ 가 `embed_model` / `qdrant_client` 인자를 옵셔널로 받아 의존성 주입 가능하게 한 것이 결정의 핵심. lesson.md §5.6 + architecture.md §3.10 에 근거 기록.
- **2026-05-08 (Day 5)** — **임베딩 모델 lifespan 캐싱 (사용자 승인)**: 3 옵션(module singleton / FastAPI lifespan + app.state / class instance + Depends) 중 *lifespan + app.state* 채택. 결정 근거 — pytest 단위 테스트에서 `SentenceTransformer(...)` 실 호출을 우회하기 위함 (130MB 다운로드 + 1~2 분 대기 회피). production 코드는 두 인자 생략 시 lifespan 안에서 1 회 생성, 테스트 코드는 `embed_model=MagicMock()` 주입으로 같은 코드 경로를 공유. architecture.md §3.10 에 3 옵션 비교 표.
- **2026-05-08 (Day 5)** — **자주 하는 실수 3 건 추가 (Day 5 — RAG API)**: ⑬ e5 query prefix 누락 — Day 2 인덱싱(`passage:`) 와 Day 5 검색(`query:`) 의 prefix 가 짝을 이뤄야 recall 정상. 누락 시 top_k=3 인데 0 건 또는 무관한 청크. ⑭ vLLM `model` 필드 누락 또는 served-model-name 불일치 → 422/404 — Day 4 §10 #11 의 후속 표면. ⑮ 임베딩 모델 요청별 재로딩 → p99 폭증 (Day 2 §10 #5 의 다른 표면 — 인덱싱은 batch 시간 / RAG API 는 사용자 응답 latency). 총 자주 하는 실수 12 → 15 건.
- **2026-05-09 (Day 6)** — **GKE GCE Ingress 채택 (사용자 승인)**: 3 옵션(GCE Ingress / nginx-ingress / 본문 nginx + 부록 GKE) 중 GCE 단일 트랙. 캡스톤이 GKE 전제이므로 controller 설치 단계 없이 매니페스트 한 장으로 시작 가능. Phase 2-03 의 nginx 학습 연속성 손실은 *학습자가 무의식적으로 nginx annotations 를 복사 → GCE 가 조용히 무시* 라는 *체험형 학습* 으로 lesson.md §10 자주 하는 실수 ⑯ 에 표면화. Day 8 의 BackendConfig CRD (timeout/CDN/Cloud Armor) 와 Phase 5 GitOps 시점의 IAP/Cloud Armor 통합까지 길게 봤을 때의 결정. architecture.md §3.11.1 에 3 옵션 비교 표.
- **2026-05-09 (Day 6)** — **nip.io host 처리 (사용자 승인)**: 3 옵션(nip.io / Host 헤더 / IP+path) 중 nip.io. 도메인 비용 0 + 실제 DNS A 레코드 해석 → 브라우저 검증 가능. Host 헤더 시뮬레이션은 `/etc/hosts` 수동 수정 부담, IP+path 만 사용은 Phase 2-03 의 host 라우팅 학습 포인트 무시. lab Step 6 에서 `nslookup <IP>.nip.io` 로 해석 동작 직접 검증. 외부 의존성 1 개(nip.io 서비스) 가 추가되지만 ML 엔지니어 학습 환경에서는 사실상 표준. architecture.md §3.11.2.
- **2026-05-09 (Day 6)** — **이미지 레지스트리: Day 3 와 동일 Docker Hub 본인 계정 (사용자 승인)**: 3 옵션(Docker Hub 본인 계정 / GAR / 로컬 이미지 재사용) 중 Day 3 패턴 그대로. `docker.io/<user>/rag-api:0.1.0` placeholder + lab Step 3 의 sed 일괄 치환. GKE 노드는 public Docker Hub 무인증 pull. GAR 은 IAM 자동 인증으로 운영적으로 더 깔끔하지만 lab Step 3~4 추가 부담. 로컬 이미지 재사용은 GKE 가 로컬 이미지 접근 불가라 사실상 불가능. Docker Hub rate limit (anonymous 6h/100 회) 은 자주 하는 실수 ⑰ 로 표면화 + 발생 시 imagePullSecret 안내.
- **2026-05-09 (Day 6)** — **Day 6 = 동작 / Day 7 = 분리 학습 흐름 유지**: 캡스톤 plan §7 의 Day 6/7 분리 의도 그대로 — Day 6 매니페스트 30 의 env 6 종을 *Deployment 에 직접 박기*, Day 7 에서 ConfigMap 32 + Secret 33 으로 *분리 리팩토링*. lesson.md §4.4 결정 박스 ② 에 Day 7 분리 효과 비교 표(env 변경 시 Pod 재시작 vs rollout restart, RBAC 분리 가능, Helm values 한 줄 차이) 명시. 학습자가 Day 6 lab 트러블슈팅 #2 에서 *env 한 글자 오타로 readiness 실패* 를 직접 경험하면 Day 7 ConfigMap 분리의 *체감 가치* 가 살아남.
- **2026-05-09 (Day 6)** — **§4.4 결정 박스 4 + §4.5 결정 박스 3 = Day 4 §4.3 동등 깊이 (사용자 승인)**: §4.4 ① replicas=2 비대칭(stateless) ② env Deployment 직접 박기(Day 7 분리 예고) ③ liveness `/healthz` vs readiness `/ready` path 분리(Day 5 코드 결정의 매니페스트 표면) ④ emptyDir vs PVC RWO/RWX (130MB 모델 캐시 단순화). §4.5 ① GCE vs nginx-ingress vs LoadBalancer Service 3 옵션 ② nip.io 채택 ③ timeout 조정 Day 8 BackendConfig 로 미룸. 두 절 합쳐 약 230 줄로 Day 4 §4.3 (140 줄) 보다 길지만 Ingress 의 외부 의존성(GCE / nip.io / Docker Hub) 이 많아 자연스러움.
- **2026-05-09 (Day 6)** — **livenessProbe vs readinessProbe path 분리 의의를 §4.4.5 결정 박스 ③ 에 결정 노트 표 형식으로**: Day 5 의 `main.py` 가 의도한 `/healthz` (프로세스 응답) vs `/ready` (lifespan 완료) 분리는 K8s 측 `livenessProbe` (재시작 트리거) vs `readinessProbe` (Service endpoint 제거) 의 *목적 차이* 와 정확히 매핑. 두 path 를 같게 두면 lifespan 진행 중 livenessProbe 가 503 받아 *무한 재시작 루프* — 이를 lesson.md §4.4 결정 박스 ③ 에 표 형식으로 정리. Day 5 의 분리 결정이 Day 6 매니페스트의 *기반 명세* 로 작용함을 학습자가 인지하도록 하는 의도.
- **2026-05-09 (Day 6)** — **자주 하는 실수 3 건 추가 (Day 6 — Ingress/배포)**: ⑯ Service named port `http` 미선언 → Ingress 502 Bad Gateway. 진단 명령(`kubectl get svc -o jsonpath='{.spec.ports[*].name}'`) + named port vs number 트레이드오프. ⑰ Docker Hub anonymous pull 6h/100 회 rate limit → ImagePullBackOff 429. 해결 단계(`imagePullPolicy: IfNotPresent` + tag 핀 → docker login + imagePullSecret → GAR 마이그레이션) 3 단 안내. ⑱ GKE LoadBalancer 비용 누수 — Ingress 시간당 \$0.025, 5 일 \$3, 한 달 \$20+. lab 정리 분기에 `kubectl delete ingress` 강조 + GCP Console External IP addresses 모니터링 안내. 총 자주 하는 실수 15 → 18 건.
- **2026-05-09 (Day 7)** — **Secret 별도 생성 (사용자 승인)**: 3 옵션(별도 Secret 33 / 23-vllm-hf-secret 재사용 / 통합 Secret) 중 별도 33 신규. 결정 근거 — ① 컴포넌트별 RBAC 분리 가능(vLLM/RAG API 권한 격리) ② Helm Day 10 차트 templates 분리 깔끔(`vllm.yaml` ↔ `rag-api.yaml` 가 각자 Secret 참조) ③ "vLLM 전용(`hf-secret`)" 이름을 RAG API 가 참조하면 *의미 오용*. 단점(HF_TOKEN 값 2 곳 중복) 은 학습 단계 placeholder 라 무영향. 운영 배포 시 SealedSecrets/External Secrets Operator 가 *원본은 한 곳* 에 두고 *parametrize*. lesson.md §4.8 결정 박스 ② + architecture.md §3.12.4 RBAC 분리 운영 가치.
- **2026-05-09 (Day 7)** — **Pod 재시작 트리거: Day 7 수동 + Day 10 자동 (사용자 승인)**: 4 옵션(수동 `kubectl rollout restart` / Helm `checksum/config` annotation / Reloader 컨트롤러 / volumeMount + 코드 watcher) 중 *(A) → (B) 점진적 추상화*. Day 7 = 학습자가 *왜 자동이 아닌가* 직접 체험 (자주 하는 실수 #20 명시화) → Day 10 Helm 차트가 ConfigMap sha256 을 podTemplate annotation 으로 박아 자동화. Reloader 는 외부 의존성 추가라 캡스톤 미적용 — Phase 5 *컨트롤러 패턴 학습* 에서 다시 등장. architecture.md §3.12.2 4 옵션 비교 표.
- **2026-05-09 (Day 7)** — **Qdrant ServiceMonitor: Day 7 부록 + Day 10 Helm 통합 (사용자 승인)**: 4 옵션(부록+Day 10 / 정식 포함 / Day 8 Grafana 와 함께 / 영구 미적용) 중 부록. 결정 근거 — Qdrant 가 6333 포트 `/metrics` 를 *기본 노출* 하지만 캡스톤 매니페스트 11-qdrant-service.yaml 에 named port 미선언이라 ServiceMonitor 35 작성 시 11 매니페스트 수정이 *선결*. Day 7 핵심 학습 가치(envFrom + Prometheus Operator 라벨 매칭 패턴) 흐름이 분산되어 본 Day 에서 제외. Day 10 Helm `templates/monitoring.yaml` 에서 vllm/rag-api/qdrant 3 종 통합으로 정식 도입. lab 부록 1 단락만 (35 매니페스트 5~10 줄 예시 + 11 Service 선결 안내). architecture.md §3.12.3 4 옵션 비교 표.
- **2026-05-09 (Day 7)** — **§6 모니터링 4 축 소절 + 메트릭 표 (사용자 승인)**: 3 옵션(4 축 소절 + 메트릭 표 / 목적별 3 소절 / ServiceMonitor 구조 중심) 중 4 축. 결정 근거 — architecture.md §5 메트릭 표(4 축) 와 *1:1 대응* 으로 두 문서 역할 일관성 확보. §6.1 RAG API 4 종 / §6.2 vLLM 6 종 / §6.3 Qdrant 부재 명시 + Day 10 도입 예고 / §6.4 GPU(DCGM) 캡스톤 미적용 + GKE 자동 통합 위임. 본 캡스톤 lab 검증 범위 — RAG API 4 종 + vLLM 6 종 = 10 메트릭. Day 8 Grafana 4 패널 + HPA 2 개의 입력이 본 표.
- **2026-05-09 (Day 7)** — **release 라벨 매칭 2 단계 ASCII 다이어그램 (lesson.md §4.9.2 + architecture.md §3.12.1)**: Phase 3-02 §1-2 의 자주 하는 실수 1 번이 캡스톤에서도 그대로 유효 — Prometheus CR `serviceMonitorSelector` ↔ ServiceMonitor `metadata.labels.release` ↔ ServiceMonitor `spec.selector` ↔ Service `metadata.labels` 4 단계 매칭을 ASCII 로 시각화. 학습자가 ServiceMonitor 작성 시 가장 자주 빠뜨리는 `release: prom` 한 줄을 자주 하는 실수 #19 로 표면화 + lesson.md §4.9 결정 박스 ② 에서 Helm release name 변경 시 라벨도 함께 변경해야 함을 명시.
- **2026-05-09 (Day 7)** — **자주 하는 실수 3 건 추가 (Day 7 — ConfigMap/Secret/ServiceMonitor)**: ⑲ ServiceMonitor `release` 라벨 누락 → Targets 빈 상태. 진단 단계 — Prometheus CR serviceMonitorSelector 확인 → ServiceMonitor labels 비교 → 누락 시 매니페스트 수정. ⑳ ConfigMap 변경 후 Pod 재시작 누락 → envFrom 옛값 고정. 해결 단계 — 즉시 `kubectl rollout restart` / 자동화 Day 10 Helm `checksum/config` / 외부 의존성 Reloader 컨트롤러. ㉑ Secret `data` vs `stringData` 혼동 → base64 디코딩 실패. 해결 단계 — 평문은 `stringData` / base64 는 `data` / CLI `kubectl create secret --from-literal` / 검증 `base64 -d`. 총 자주 하는 실수 18 → 21 건. Phase 2-01 §1-1 + Phase 3-02 §1-2 인용으로 학습 누적성.
- **2026-05-10 (Day 8)** — **vLLM HPA 메트릭으로 `num_requests_running` 단일 채택 (사용자 승인)**: 3 옵션(running / running+waiting / gpu_cache_usage_perc) 중 running 단일. 결정 근거 — Phase 4-3 부하 시연에서 8~16 이 정상 범위로 검증된 직관적 메트릭, 임계 averageValue=8 설정 단순, ML 학습자에게 *continuous batching 의 본질 = 동시 처리 요청 수* 라는 학습 가치. waiting 은 임계 0 이라 noise 민감, gpu_cache_usage_perc 는 정상 운영도 0.95 부근이라 임계 0.97 좁게 설정해야 함. architecture.md §3.13.1 3 옵션 비교 표 + lesson.md §7 결정 박스 ①.
- **2026-05-10 (Day 8)** — **Grafana 대시보드 import: ConfigMap + sidecar 자동 (사용자 승인)**: 3 옵션(ConfigMap + sidecar / JSON 파일 첨부 / kube-prometheus-stack values dashboards 키) 중 sidecar. 결정 근거 — Phase 3-02 패턴 계승, Day 7 의 prom-grafana 가 sidecar 활성화 상태(values.yaml grafana.sidecar.dashboards.label = grafana_dashboard 확인), Day 10 Helm `templates/monitoring.yaml` 통합 친화. ConfigMap 한 장(`61-grafana-rag-dashboard.yaml`) namespace=`monitoring` + labels.grafana_dashboard="1" 만 정확하면 ~30 초 안에 Grafana UI 자동 등장. lab Step 2 sidecar 로그 확인 명령 포함.
- **2026-05-10 (Day 8)** — **retriever hit-ratio 패널 → §6.1 4 RAG 메트릭 단계별 분해로 교체 (사용자 승인)**: capstone-plan §7 Day 8 초안의 4 패널(RAG latency / vLLM tokens / GPU 메모리 / retriever hit-ratio) 중 hit-ratio 는 main.py 에 메트릭 부재 → Day 5 코드 변경 부담. 사용자 결정으로 §6.1 의 RAG API 4 메트릭(rag_chat_total / chat_latency / retrieve_latency / llm_latency) 으로 교체. 결과 4 패널: ① chat req/s status별 / ② chat latency p95 단계별 분해(chat·retrieve·llm) / ③ vLLM running·waiting / ④ GPU KV cache gauge. 코드 변경 0, 이미 노출 중인 메트릭만 시각화. lesson.md §6 보강에 결정 명시.
- **2026-05-10 (Day 8)** — **부하 트리거 — Day 8 짧은 hey 60s c=8, 본격 Day 9 (사용자 승인)**: 3 옵션(Day 8 짧은 부하만 / Day 8 본격 hey + load_test.sh / Day 9 까지 미룸) 중 짧은 부하. 결정 근거 — capstone-plan §7 Day 9 의 부하 테스트 + 튜닝과 *역할 분담*. Day 8 lab Step 6~7 에서 hey 60s c=8 한 번 발사로 REPLICAS 변동을 *체험* 만, p95 측정·튜닝·load_test.sh 스크립트는 Day 9 로. lab 분량 적정선 유지 (~21KB Day 7 lab 와 비슷한 ~24KB).
- **2026-05-10 (Day 8)** — **maxReplicas=2 의 *체험형 학습 설계* (architecture.md §3.13.4)**: T4 노드 풀 1 대 → vLLM Pod 1 개만 schedule 가능. maxReplicas=1 두면 HPA 가 *사실상 무의미* — 학습자가 "왜 HPA 를 둬야 하는가" 체감 못함. maxReplicas=2 + 노드 1 대 = "스케일 *시도* 는 되지만 노드가 없음" 시나리오로 운영 환경의 *실제 문제* 를 학습 환경에서 안전하게 재현. lab Step 7 에서 `kubectl describe pod vllm-2` 의 `0/2 nodes are available: ... 1 node(s) had untolerated taint {nvidia.com/gpu: present}` 메시지가 학습 포인트. 자주 하는 실수 #24 와 직접 연결.
- **2026-05-10 (Day 8)** — **prometheus-adapter rules.custom 의 콜론 별칭 처리**: vLLM 메트릭 `vllm:num_requests_running` 의 콜론(`:`) 이 K8s API path (`/apis/.../pods/*/vllm:num_requests_running`) 에 안전하지 않아 일부 client 인코딩 실패. adapter 의 `name.matches: "^vllm:(.*)$"` + `name.as: "vllm_${1}"` 로 별칭 부여 → HPA 25 는 별칭 `vllm_num_requests_running` 만 참조. RAG API 의 `rag_chat_total` 은 *Counter* 라 rate(2m) PromQL 변환 + `_total` → `_requests_per_second` 별칭. 두 규칙의 차이를 자주 하는 실수 #22 (LabelMatchers 누락) + lesson.md §7.3 핵심 발췌 3 + 60-prometheus-adapter-values.yaml 주석으로 명시.
- **2026-05-10 (Day 8)** — **자주 하는 실수 3 건 추가 (Day 8 — HPA/Grafana/adapter)**: ㉒ prometheus-adapter rules.custom 의 `<<.LabelMatchers>>` template syntax 누락 → adapter Pod Ready 인데 메트릭 미노출. 진단 — adapter 로그 `discovered metrics: 0` 또는 `failed to query`. 해결 — metricsQuery 에 `<<.Series>>` + `<<.LabelMatchers>>` + `<<.GroupBy>>` 세 placeholder 모두 포함. ㉓ HPA `scaleTargetRef.kind: ReplicaSet` 또는 ReplicaSet 이름(`rag-api-7d8f9b6c5`) 사용 → HPA 가 아무 일도 안 함. 해결 — `kind: Deployment` + name 은 Deployment 이름 (해시 suffix 없는 형태). ㉔ vLLM replicas 가 *왜 안 늘어나는가* 오해 → 부하가 RAG API 4 Pod 에 분산되어 vLLM 으로 가는 RPS 가 충분히 분산됨 + maxReplicas=2 + GPU 노드 1 대 = *체험형 학습 설계* 임을 학습자가 인지 못함. 해결 — 의도된 결과로 두거나 hey -c 32 로 부하 집중 또는 노드 풀 size=2 확장. 총 자주 하는 실수 21 → 24 건.
