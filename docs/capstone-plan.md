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
- [ ] 학습 목표 5: Prometheus/Grafana로 멀티 컴포넌트 시스템을 모니터링하고 HPA(커스텀 메트릭)로 LLM 서빙을 오토스케일링할 수 있다
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
- [ ] `20-vllm-deployment.yaml` ← Phase 4-3 (namespace 변경, served-model-name 통일)
- [ ] `21-vllm-pvc.yaml` ←
- [ ] `22-vllm-service.yaml` ←
- [ ] `23-vllm-hf-secret.yaml` ←
- [ ] `24-vllm-servicemonitor.yaml` ←
- [ ] `25-vllm-hpa.yaml` ★ (prometheus-adapter + `vllm:num_requests_running`)
- [ ] `30-rag-api-deployment.yaml` ★
- [ ] `31-rag-api-service.yaml` ★
- [ ] `32-rag-api-configmap.yaml` ★ (top_k, 프롬프트 템플릿)
- [ ] `33-rag-api-secret.yaml` ★ (HF 토큰 재사용)
- [ ] `34-rag-api-servicemonitor.yaml` ★
- [ ] `35-rag-api-hpa.yaml` ★ (RPS 기준)
- [ ] `40-ingress.yaml` ★ (`/chat` 라우팅)
- [ ] `50-indexing-workflow.yaml` ← Phase 4-4 (입력 PVC를 본 코스 자료로 교체)
- [ ] `51-indexing-cron.yaml` ←

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

- [ ] `Dockerfile`
- [ ] `requirements.txt`
- [ ] `main.py` (FastAPI 진입점, `/chat` `/healthz` `/metrics`)
- [ ] `retriever.py` (Qdrant 검색)
- [ ] `llm_client.py` (vLLM `/v1/chat/completions` 호출)
- [ ] `prompts.py` (프롬프트 템플릿: system / context / user)
- [ ] `tests/test_retriever.py` (로컬 단위 테스트)

### 4.5 `practice/llm_serving/`

- [ ] `README.md` — vLLM 운영 노트 (cold start, gpu-mem-util 튜닝) ★
- [ ] `load_test.sh` — hey 기반 부하 테스트 스크립트 ★

### 4.6 `practice/pipelines/indexing/` ← Phase 4-4 이식 + 데이터 교체

- [ ] `Dockerfile`
- [ ] `requirements.txt`
- [ ] `pipeline.py` (load_docs / chunk / embed / upsert, BAAI/bge-small-en)
- [ ] `README.md` ("본 코스 자료를 인덱싱한다" 설명)

### 4.7 `labs/` — Day별 실습 가이드

- [ ] `labs/README.md` — 인덱스 (Day별 링크, 사전 준비, 정리 절차) ★
- [x] `labs/day-01-namespace-qdrant.md` ★
- [ ] `labs/day-02-indexing-script-local.md` ★
- [ ] `labs/day-03-indexing-argo.md` ★
- [ ] `labs/day-04-vllm-deploy.md` ★
- [ ] `labs/day-05-rag-api-impl.md` ★
- [ ] `labs/day-06-rag-api-deploy.md` ★
- [ ] `labs/day-07-config-secret-monitoring.md` ★
- [ ] `labs/day-08-grafana-hpa.md` ★
- [ ] `labs/day-09-load-test-tuning.md` ★
- [ ] `labs/day-10-integration-cleanup.md` ★

---

## 5. 재사용 정책 (어디서 무엇을 가져오는가)

| 캡스톤 산출물 | 재사용 원본 | 변경 사항 | 이식 완료 |
|---------------|-------------|-----------|:---:|
| `manifests/10-qdrant-statefulset.yaml` | `course/phase-4-ml-on-k8s/04-argo-workflows/manifests/02-qdrant.yaml` | **Deployment+emptyDir → StatefulSet+volumeClaimTemplates 변환**, namespace `ml-pipelines` → `rag-llm`, PVC 5Gi, Headless Service 분리 | [x] |
| `manifests/20-vllm-deployment.yaml` | `course/phase-4-ml-on-k8s/03-vllm-llm-serving/manifests/vllm-phi2-deployment.yaml` | namespace 변경, `--served-model-name` 통일 | [ ] |
| `manifests/21-vllm-pvc.yaml`, `23-vllm-hf-secret.yaml`, `24-vllm-servicemonitor.yaml` | Phase 4-3 동명 파일 | namespace만 변경 | [ ] |
| `manifests/50-indexing-workflow.yaml`, `51-indexing-cron.yaml` | Phase 4-4 동명 파일 | 입력 PVC 경로를 본 코스 자료로 교체, 출력 Qdrant URL 변경 | [ ] |
| `practice/pipelines/indexing/pipeline.py` | Phase 4-4 `practice/pipeline.py` | `sample_docs/` 대신 마운트된 코스 자료(`/data/course/*.md`) 인덱싱 | [ ] |
| `helm/templates/monitoring.yaml` | Phase 3 `02-prometheus-grafana` ServiceMonitor 패턴 | RAG API + vLLM + Qdrant 3종 통합 | [ ] |
| `helm/templates/_helpers.tpl`, `Chart.yaml` 골격 | Phase 3 `01-helm-chart/helm/` | 차트 이름 / appVersion 변경 | [ ] |
| `manifests/25-vllm-hpa.yaml` 커스텀 메트릭 부분 | Phase 3 `03-autoscaling-hpa` prometheus-adapter 설정 | 메트릭을 `vllm:num_requests_running`으로 변경 | [ ] |

**원칙**: 가져온 자산은 **출처 주석**(`# from course/phase-4-ml-on-k8s/04-argo-workflows/...`)을 매니페스트 상단에 답니다. lesson.md에서도 "Phase 4-X에서 익힌 ~~를 그대로 사용한다"고 명시해 학습 누적성을 강조합니다.

---

## 6. lesson.md 섹션 구성 (600~800줄 목표)

작성 진행에 따라 섹션 단위로 체크.

- [x] §0 학습 목표 6개 (위 §3에서 인용)
- [x] §0 도입 — 왜 ML 엔지니어에게 필요한가 (1문단)
- [x] §1 시스템 아키텍처 (ASCII 다이어그램 + 컴포넌트별 역할표, 80~100줄)
- [ ] §2 왜 이렇게 분리했는가 (트레이드오프, 100줄)
- [ ] §3 데이터 흐름 (`/chat` 호출 → retriever → 프롬프트 합성 → vLLM → 응답, 80줄)
- [~] §4 핵심 매니페스트 해설 (5종 핵심 라인 단위 주석, 150줄) _(Day 1: §4.1 Namespace + §4.2 Qdrant StatefulSet+Headless 완료 / §4.3 vLLM·§4.4 RAG API·§4.5 Ingress TBD)_
- [ ] §5 RAG API 구현 노트 (retriever 청크 추출, 컨텍스트 합성 규칙, 스트리밍 옵션, 80줄)
- [ ] §6 모니터링 핵심 메트릭 (RAG / vLLM / Qdrant / GPU 4축, 60줄)
- [ ] §7 HPA 커스텀 메트릭 (왜 CPU 기준이 부적절한가, prometheus-adapter 흐름, 60줄)
- [ ] §8 Helm으로 한 줄 배포 (values 분리(dev/prod), `helm install --create-namespace`, 50줄)
- [ ] §9 검증 시나리오 (6단계, §9와 동일)
- [ ] §10 🚨 자주 하는 실수 (3개, 30줄)
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
- [ ] `practice/pipelines/indexing/{Dockerfile, requirements.txt, pipeline.py, README.md}`
- [ ] 본 코스 자료(`course/phase-*/**/lesson.md`)를 청크/임베드/Qdrant upsert
- [ ] `labs/day-02-indexing-script-local.md`
- [ ] 검증: 컬렉션 count > 0, 샘플 검색 한 건 성공

### Day 3 — Argo Workflow로 인덱싱
- [ ] `manifests/50-indexing-workflow.yaml`, `51-indexing-cron.yaml` 이식
- [ ] Argo 설치 (Phase 4-4 참조) → Workflow 제출 → 완료 확인
- [ ] `labs/day-03-indexing-argo.md`
- [ ] 검증: `kubectl get wf` STATUS=Succeeded

### Day 4 — vLLM Deployment
- [ ] `manifests/20-vllm-deployment.yaml`, `21-vllm-pvc.yaml`, `22-vllm-service.yaml`, `23-vllm-hf-secret.yaml` 이식
- [ ] HF Secret 생성 → vLLM Deployment 적용 → `/v1/models`로 모델 인지 확인
- [ ] `labs/day-04-vllm-deploy.md`
- [ ] 검증: OpenAI 클라이언트 호출 200 OK + 응답 텍스트

### Day 5 — RAG API 구현 (로컬)
- [ ] `practice/rag_app/{Dockerfile, requirements.txt, main.py, retriever.py, llm_client.py, prompts.py}`
- [ ] `practice/rag_app/tests/test_retriever.py`
- [ ] port-forward로 vLLM·Qdrant 호출하며 로컬 개발
- [ ] `labs/day-05-rag-api-impl.md`
- [ ] 검증: `pytest tests/` 통과, 로컬 `uvicorn` `/chat` 200 OK

### Day 6 — RAG API 클러스터 배포 + Ingress
- [ ] `manifests/30-rag-api-deployment.yaml`, `31-rag-api-service.yaml`, `40-ingress.yaml`
- [ ] 이미지 빌드/푸시 → Deployment 적용 → Ingress로 `/chat` 호출
- [ ] `labs/day-06-rag-api-deploy.md`
- [ ] 검증: end-to-end `curl http://<ingress>/chat` 200 OK

### Day 7 — ConfigMap/Secret 분리 + ServiceMonitor
- [ ] `manifests/32-rag-api-configmap.yaml`, `33-rag-api-secret.yaml`
- [ ] `manifests/24-vllm-servicemonitor.yaml`(이식), `34-rag-api-servicemonitor.yaml`
- [ ] `labs/day-07-config-secret-monitoring.md`
- [ ] 검증: Prometheus UI에 vllm/rag-api/qdrant 타겟 UP

### Day 8 — Grafana 대시보드 + HPA
- [ ] `manifests/25-vllm-hpa.yaml`, `35-rag-api-hpa.yaml`
- [ ] Grafana 대시보드 JSON (RAG latency / vLLM tokens / GPU 메모리 / retriever hit-ratio)
- [ ] prometheus-adapter 설치 → HPA 적용 → 부하로 스케일 트리거
- [ ] `labs/day-08-grafana-hpa.md`
- [ ] 검증: `kubectl get hpa` REPLICAS 변동 확인

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

- [ ] Day 1 — 아키텍처 문서 작성 + Namespace + Qdrant StatefulSet
- [ ] Day 2 — 임베딩·인덱싱 스크립트 작성, 로컬 테스트
- [ ] Day 3 — 인덱싱 Argo Workflow 클러스터 실행
- [ ] Day 4 — vLLM Deployment + OpenAI 호환 API 호출 검증
- [ ] Day 5 — RAG API 구현 (retriever + LLM 결합)
- [ ] Day 6 — RAG API Deployment + Service + Ingress
- [ ] Day 7 — ConfigMap/Secret 분리, ServiceMonitor 추가
- [ ] Day 8 — Grafana 대시보드 + HPA(커스텀 메트릭) 설정
- [ ] Day 9 — 부하 테스트(hey) + 튜닝
- [ ] Day 10 — 통합 검증 + 문서화 + 클러스터 삭제

산출물 4종 관점 체크 (캡스톤은 단일 토픽이지만 4종을 만족해야 함):

- [ ] **lesson.md** — `course/capstone-rag-llm-serving/lesson.md` 13개 섹션 모두 작성
- [ ] **매니페스트/코드** — `manifests/`(18개) + `helm/`(13개) + `practice/`(rag_app·llm_serving·pipelines)
- [ ] **labs/** — `labs/README.md` + `labs/day-01.md ~ day-10.md` (총 11개)
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
