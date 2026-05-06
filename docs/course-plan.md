# K8s for ML 교육자료 작성 진행 체크리스트

> **기준 문서**: [study-roadmap.md](study-roadmap.md) — 커리큘럼의 Single Source of Truth
> **사용법**: 한 토픽을 진행한 뒤 해당 산출물 체크박스를 `[x]`로 업데이트합니다.
> **스킬 연계**: 토픽 작성 시 [`/k8s-ml-course-author`](../.claude/skills/k8s-ml-course-author/) 스킬을 호출하면 본 계획서와 study-roadmap을 함께 참조합니다.

---

## 📐 토픽별 산출물 4종 (모든 토픽 공통)

각 토픽은 `course/phase-<N>-<slug>/<NN>-<topic-slug>/` 아래에 다음 4개 산출물을 갖춥니다.

| # | 산출물 | 내용 |
|---|--------|------|
| 1 | `lesson.md` | 학습 목표 3개+, 완료 기준 1줄, 자주 하는 실수 1–3개, 다음 토픽 링크 |
| 2 | 매니페스트/코드 | `manifests/`(YAML) 또는 `app/`(Dockerfile, FastAPI). 토픽 성격에 따라 다름 |
| 3 | `labs/` | 단계별 실습 명령 + 예상 출력 |
| 4 | minikube 검증 | 실제 클러스터에서 동작 확인 (Phase 0은 `docker run`, Phase 4 GPU는 클라우드) |

---

## Phase 0. 사전 점검 (3–5일)

- [x] **01-docker-fastapi-model** — Docker 점검 + FastAPI로 `cardiffnlp/twitter-roberta-base-sentiment` 감싸기
  - [x] lesson.md
  - [x] Dockerfile + FastAPI 앱 코드
  - [x] labs/
  - [x] `docker run` 로컬 검증

---

## Phase 1. Kubernetes 기본기 (2주)

- [ ] **01-cluster-setup** — minikube 설치·기동, kubectl 컨텍스트, 첫 Pod
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–6단계 실행 후 갱신)_
- [ ] **02-pod-deployment** — Pod / ReplicaSet / Deployment, 롤링 업데이트, `kubectl scale`
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **03-service-networking** — Service 3종(ClusterIP/NodePort/LoadBalancer), DNS, port-forward
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **04-serve-classification-model** — Phase 0 이미지를 Deployment + Service로 배포, Pod 강제 종료 시 자동 복구 검증
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–6단계 실행 후 갱신)_

---

## Phase 2. 운영에 필요한 K8s 개념 (2주)

- [ ] **01-configmap-secret** — 추론 하이퍼파라미터(ConfigMap), HF 토큰·S3 키(Secret)
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **02-volumes-pvc** — PV/PVC/StorageClass, 모델 가중치 캐시, init container로 S3 다운로드
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **03-ingress** — nginx-ingress 설치, 경로 기반 라우팅
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **04-job-cronjob** — 배치 추론 Job, 일별 평가 CronJob, `backoffLimit`/`activeDeadlineSeconds`
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **05-namespace-quota** — dev/staging/prod 네임스페이스, ResourceQuota/LimitRange
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–7단계 실행 후 갱신)_

---

## Phase 3. 프로덕션 운영 도구 (2주)

- [ ] **01-helm-chart** — Phase 2 매니페스트를 Helm 차트로 패키징, install/upgrade/rollback
  - [x] lesson.md
  - [x] Helm 차트 (Chart.yaml, values.yaml, templates/)
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–8단계 실행 후 갱신)_
- [ ] **02-prometheus-grafana** — kube-prometheus-stack, FastAPI `/metrics`, ServiceMonitor, Grafana 대시보드
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–9단계 실행 후 갱신)_
- [ ] **03-autoscaling-hpa** — HPA + 부하 테스트(`hey`/`wrk`), VPA·Cluster Autoscaler 개념
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–10단계 실행 후 갱신)_
- [ ] **04-rbac-serviceaccount** — ServiceAccount/Role/RoleBinding, 최소 권한, kubeconfig 분리
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs 0–10단계 실행 후 갱신)_

---

## Phase 4. ML on Kubernetes (3–4주) ⭐

> ⚠️ **GPU 필요 토픽**: 4-1, 4-3, 캡스톤. 로컬 GPU 없으면 GCP GKE 임시 클러스터 사용. **실습 후 클러스터 삭제 필수.**

- [ ] **01-gpu-on-k8s** — NVIDIA Device Plugin, `nvidia.com/gpu`, taint+toleration, MIG/Time-slicing
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] GPU 클러스터 검증 (로컬 GPU 또는 GKE) _(학습자가 labs Track B Step 0–9 실행 후 갱신)_
- [ ] **02-kserve-inference** — Phase 0~3 분류 모델을 KServe `InferenceService`로 마이그레이션
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs Step 0–7 실행 후 갱신)_
- [ ] **03-vllm-llm-serving** — vLLM Deployment + OpenAI 호환 API, `microsoft/phi-2` 또는 `Qwen/Qwen2.5-1.5B-Instruct` (모델 전환 지점)
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] GPU 클러스터 검증 _(학습자가 labs Track B Step 0–8 실행 후 갱신)_
- [ ] **04-argo-workflows** — DAG 워크플로 기초, RAG 인덱싱 파이프라인 프로토타입
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs Step 0–10 실행 후 갱신)_
- [ ] **05-distributed-training-intro** — KubeRay·Kubeflow Training Operator 개념 비교 (실습은 짧게)
  - [x] lesson.md
  - [x] 매니페스트/코드
  - [x] labs/
  - [ ] minikube 검증 _(학습자가 labs Step 0–7 실행 후 갱신)_

---

## ⭐ Capstone — RAG 챗봇 + LLM 서빙 종합 프로젝트 (1–2주)

산출물 위치: `course/capstone-rag-llm-serving/` (단일 디렉토리, 다수 컴포넌트)

> 캡스톤은 study-roadmap의 권장 일정(10일) 흐름을 따릅니다. 일차별 작업이 곧 산출물 단위입니다.

- [x] **Day 1** — 아키텍처 문서 작성 + Namespace + Qdrant StatefulSet _(2026-05-06: lesson.md 골격 + architecture.md 초안 7섹션 + manifests 3종 + labs/day-01 작성. 클러스터 실행 검증은 학습자 단계.)_
- [x] **Day 2** — 임베딩·인덱싱 스크립트 작성, 로컬 테스트 _(2026-05-06: practice/pipelines/indexing/ 4건(Dockerfile/requirements/pipeline.py/README) + labs/day-02 + lesson.md §3.2·§4.6·§10 + architecture.md §3.5. 임베딩 모델은 한국어 자료 대응 위해 multilingual-e5-small 로 결정. 학습자 단계 검증(points_count, search 결과)은 GKE 클러스터에서.)_
- [x] **Day 3** — 인덱싱 Argo Workflow 클러스터 실행 _(2026-05-06: manifests 3건(49-argo-rbac/50-indexing-workflow/51-indexing-cronworkflow) + labs/day-03 + labs/README.md 신규 + lesson.md §1.1·§3.3·§4.7·§10 + architecture.md §3.6·§3.7. Phase 4-4 의 4-step DAG 에 git-clone step 1개를 추가해 5-step + CronWorkflow 자동화. 학습자 단계 검증(Argo controller 설치, 이미지 빌드/푸시, Workflow Succeeded, points_count 재현) 은 GKE 클러스터에서.)_
- [ ] **Day 4** — vLLM Deployment + OpenAI 호환 API 호출 검증
- [ ] **Day 5** — RAG API 구현 (retriever + LLM 결합)
- [ ] **Day 6** — RAG API Deployment + Service + Ingress
- [ ] **Day 7** — ConfigMap/Secret 분리, ServiceMonitor 추가
- [ ] **Day 8** — Grafana 대시보드 + HPA(커스텀 메트릭) 설정
- [ ] **Day 9** — 부하 테스트(`hey`) + 튜닝
- [ ] **Day 10** — 통합 검증 + 문서화 + 클러스터 삭제

**완료 기준** (study-roadmap에서 인용):
```bash
curl http://<ingress-host>/chat -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'
# → 200 OK + 답변 텍스트 + 인용 문서 3개가 반환되면 캡스톤 완료
```

---

## 📅 권장 진행 순서 (study-roadmap의 주차별 일정 기반)

| 주차 | 진행 토픽 |
|-----|----------|
| 1 | Phase 0/01, Phase 1/01, Phase 1/02 |
| 2 | Phase 1/03, Phase 1/04 |
| 3 | Phase 2/01, Phase 2/02, Phase 2/03 |
| 4 | Phase 2/04, Phase 2/05 |
| 5 | Phase 3/01, Phase 3/02 |
| 6 | Phase 3/03, Phase 3/04 |
| 7 | Phase 4/01, Phase 4/02 |
| 8 | Phase 4/03, Phase 4/04, Phase 4/05 |
| 9 | Capstone Day 1–5 |
| 10 | Capstone Day 6–10 |

---

## 📌 진행 메모

- 토픽 작성 시 [`/k8s-ml-course-author`](../.claude/skills/k8s-ml-course-author/) 스킬 호출 권장
- 작성 후 본 파일의 체크박스를 `[x]`로 업데이트 (커밋 메시지 예: `:white_check_mark: Phase 1/01-cluster-setup 완료`)
- Phase 5(선택) 토픽은 본 코스 완료 후 별도로 검토
