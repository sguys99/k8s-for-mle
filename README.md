# K8s for ML Engineers

> Docker는 익숙하지만 Kubernetes는 처음인 ML 엔지니어를 위한, **한국어 실습 중심 K8s 교재**입니다.

- 모든 챕터에 minikube 실습 포함 — `lesson.md`(이론) + 매니페스트·코드 + `labs/`(단계별 실습) + 클러스터 검증
- 모델 서빙 · 학습 잡 · 평가 파이프라인 등 **실전 ML 워크로드 관점**을 일관되게 유지
- 분류 모델 → SLM(vLLM) → RAG 챗봇으로 진화하는 **누적 실습 스토리라인**

---

## 누구를 위한 자료인가요

- **ML/DL 모델을 운영 환경에 올리고 싶은 엔지니어** — 학습은 해봤지만 K8s 위에서 어떻게 굴러가는지가 막연한 분
- **Docker는 다뤄봤지만 Kubernetes는 처음**인 분 (이미지 빌드·`docker run`은 익숙)
- **KServe / vLLM / Argo Workflows / GPU on K8s**를 깊게 다루고 싶은 분
- 한국어 자료로 따라가고 싶은 학습자

> 총 학습 기간은 약 **10–12주** (주 8–10시간 기준)이며, 캡스톤(RAG 챗봇)까지 마치면 K8s 위에서 LLM 서빙 시스템을 직접 운영할 수 있는 수준이 목표입니다.

---

## 이 자료가 다른 점

다른 K8s 입문 자료와 달리, 본 코스는 처음부터 끝까지 **ML 엔지니어를 위한 설계**를 유지합니다.

- **ML 엔지니어 관점으로 재구성한 K8s** — 모든 매니페스트가 ML 워크로드(모델 서빙, 학습 잡, 평가 CronJob 등)이고, 매 챕터 첫 줄에 "왜 ML 엔지니어에게 필요한가"를 명시합니다.
- **누적되는 단일 실습 시스템** — Phase별로 따로 노는 예제가 아닙니다. Phase 0의 FastAPI Docker 이미지 하나가 Phase 4의 KServe 서빙을 거쳐 캡스톤의 RAG 챗봇으로 **점점 운영 가능한 형태로 진화**합니다.
- **메인 코스 4개에 깊이 집중** — KServe, vLLM, Argo Workflows, GPU on K8s를 깊게 다룹니다. Kubeflow Pipelines / KubeRay / Triton 등은 비교 박스로만 다뤄, 도구 폭에 학습자가 익사하지 않게 합니다.
- **모든 토픽이 4종 산출물 표준** — `lesson.md`(학습 목표 3개+ / 완료 기준 1줄 / 자주 하는 실수) + `manifests/`(YAML) 또는 `practice/`(Dockerfile·FastAPI 등 실습 코드) + `labs/`(단계별 명령 + 예상 출력) + minikube 검증.

---

## 커리큘럼 한눈에 보기

| Phase | 기간 | 핵심 학습 | 산출물 |
|-------|------|----------|--------|
| **0. 사전 점검** | 3–5일 | Docker 점검(레이어·멀티스테이지) + FastAPI로 분류 모델 감싸기 | 모델 서빙 Docker 이미지 |
| **1. K8s 기본기** | 2주 | Pod / ReplicaSet / Deployment / Service, kubectl 필수 명령 | K8s에 분류 모델 배포 |
| **2. 운영 개념** | 2주 | ConfigMap · Secret · PV/PVC · Ingress · Job · CronJob · Namespace | 운영형 모델 서빙 |
| **3. 운영 도구** | 2주 | Helm · Prometheus · Grafana · HPA · RBAC | 모니터링 + 자동 스케일 |
| **4. ML on K8s** ⭐ | 3–4주 | GPU on K8s · KServe · vLLM · Argo Workflows | 분류 → SLM 서빙 전환 |
| **Capstone** ⭐ | 1–2주 | RAG 챗봇 통합 시스템 (vLLM + Qdrant + Argo + 모니터링) | 운영 가능한 RAG API |
| 5. 심화 (선택) | 6주+ | Operator/CRD · GitOps · Service Mesh | — |

상세 토픽 목록과 학습 자료 링크는 [docs/study-roadmap.md](docs/study-roadmap.md)에 있습니다.

---

## 누적 실습 스토리라인

Phase별로 분리된 예제가 아니라, **하나의 ML 서비스가 K8s 위에서 점점 운영 가능한 형태로 진화**합니다.

| Phase | 산출물 | 다음 Phase 입력 |
|-------|--------|---------------|
| 0 | `cardiffnlp/twitter-roberta-base-sentiment` 분류 모델을 감싼 FastAPI Docker 이미지 | Phase 1의 Pod에 그대로 사용 |
| 1 | Deployment + Service로 분류 모델을 K8s에 배포 | Phase 2에서 운영화 |
| 2 | ConfigMap/Secret/PVC/Ingress/CronJob으로 운영화 (모델 캐시·HF 토큰·평가) | Phase 3에서 표준화 |
| 3 | Helm 차트화 + Prometheus 메트릭 + HPA 자동 스케일 | Phase 4에서 표준 서빙으로 마이그레이션 |
| 4 | KServe `InferenceService`로 분류 모델 마이그레이션 → **vLLM으로 SLM 서빙으로 전환** | 캡스톤의 LLM 백엔드 |
| Capstone | vLLM SLM + Qdrant Vector DB + Argo 인덱싱 = RAG 챗봇 | — |

> 💡 **모델 전환 지점**: Phase 3 끝까지는 분류 모델 한 개로 K8s 운영 기본기를 익히고, Phase 4-3(vLLM)에서 SLM(`microsoft/phi-2` 또는 `Qwen/Qwen2.5-1.5B-Instruct`)으로 자연스럽게 도약합니다.

---

## 캡스톤: RAG 챗봇 미리보기 ⭐

Phase 1~4에서 익힌 모든 K8s + ML 도구를 **하나의 운영 가능한 시스템**으로 통합합니다.

```
              ┌─────────────────────────────┐
              │  Ingress (nginx-ingress)    │  ← Phase 2
              └──────────────┬──────────────┘
                             │ POST /chat
                  ┌──────────▼──────────┐
                  │  RAG API (FastAPI)  │  ← Phase 0~3 + HPA(Phase 3)
                  └────┬───────────┬────┘
              검색  │           │ 생성
                  ▼           ▼
       ┌──────────────┐  ┌─────────────────┐
       │  Qdrant      │  │ vLLM Deployment │ ← Phase 4
       │ (StatefulSet)│  │ (microsoft/phi-2)│   GPU 1, HPA(QPS)
       └──────▲───────┘  └─────────────────┘
              │ 인덱싱
       ┌──────────────────────┐
       │ Argo Workflow        │  ← Phase 4
       │ (문서→임베딩→Upsert) │
       └──────────────────────┘
```

**완료 검증**

```bash
curl http://<ingress-host>/chat \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'
# → 200 OK + 답변 텍스트 + 인용 문서 3개가 반환되면 캡스톤 완료
```

자세한 아키텍처와 일차별 진행은 [docs/study-roadmap.md](docs/study-roadmap.md#-capstone--rag-챗봇--llm-서빙-종합-프로젝트-1-2주)의 캡스톤 섹션을 참고하세요.

---

## 시작하기

### 사전 준비물

- Docker (이미지 빌드·실행 가능 환경)
- `kubectl` 최신 stable
- minikube (또는 kind, k3d)
- Python 3.10+ (Phase 0 FastAPI 실습용)

### 첫 토픽까지 3분

```bash
# 1) 저장소 클론
git clone https://github.com/<your-org>/k8s-for-mle.git
cd k8s-for-mle

# 2) minikube 시작 (Phase 1부터 사용)
minikube start --cpus 4 --memory 8192

# 3) Phase 0 첫 토픽으로 이동
cd course/phase-0-docker-review/01-docker-fastapi-model
cat lesson.md
```

OS별 minikube 설치 방법은 [공식 가이드](https://minikube.sigs.k8s.io/docs/start/)를, GPU 실습용 클라우드 환경(GKE/EKS/AKS) 선택은 [docs/study-roadmap.md](docs/study-roadmap.md#-gpu-실습-환경)의 "GPU 실습 환경" 섹션을 참고하세요.

> ⚠️ **GPU 실습 종료 후 클러스터 삭제 필수**: Phase 4-1·4-3·캡스톤은 GPU 노드를 사용하므로 실습이 끝나면 반드시 클러스터를 삭제해 비용을 차단하세요.

---

## 디렉토리 구조

```
.
├── course/                       # Phase 단위 챕터
│   └── phase-<N>-<slug>/
│       └── <NN>-<topic-slug>/
│           ├── lesson.md         # 이론 + 학습 목표 + 완료 기준
│           ├── manifests/        # K8s YAML (또는)
│           ├── practice/         # Dockerfile, FastAPI 등 실습 코드
│           └── labs/             # 단계별 실습 명령 + 예상 출력
├── docs/
│   ├── study-roadmap.md          # 커리큘럼 SSOT (Single Source of Truth)
│   └── course-plan.md            # 토픽별 진행 체크리스트
├── data/                         # 실습용 샘플 데이터
└── img/                          # 다이어그램, 스크린샷
```

각 토픽의 표준 4종 산출물(lesson.md / 매니페스트·코드 / labs / 클러스터 검증)에 대한 상세 규약은 [CLAUDE.md](CLAUDE.md)에 정리되어 있습니다.

---

## 작성 현황

- ✅ 커리큘럼 설계 완료 ([docs/study-roadmap.md](docs/study-roadmap.md))
- 🚧 토픽별 자료는 순차 작성 중입니다
- 📋 토픽별 진행 상태는 [docs/course-plan.md](docs/course-plan.md)의 체크박스에서 실시간 확인 가능합니다

---

## 관련 문서

| 문서 | 역할 |
|------|------|
| [docs/study-roadmap.md](docs/study-roadmap.md) | 커리큘럼 SSOT — Phase별 학습 내용·실습·자료 링크 |
| [docs/course-plan.md](docs/course-plan.md) | 토픽별 산출물 4종 진행 체크리스트 |
| [CLAUDE.md](CLAUDE.md) | 프로젝트 운영 원칙 (챕터 작성 표준, 디렉토리 규약) |

---

## 라이선스

본 프로젝트는 [Apache License 2.0](LICENSE)으로 배포됩니다.
