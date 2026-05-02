---
name: k8s-ml-course-author
description: ML 엔지니어를 위한 한국어 Kubernetes 교육자료(이론 lesson.md + YAML 매니페스트 + FastAPI/Dockerfile 실습 코드)를 course/ 폴더에 토픽/Phase 단위로 생성합니다. 사용자가 "K8s 학습 자료", "쿠버네티스 챕터/레슨/강의 작성", "Phase N 자료", "ML on K8s 튜토리얼", "KServe/vLLM/Triton/Kubeflow/Ray 실습", "RAG 캡스톤 프로젝트", "교육 자료 만들어줘", "study material" 등을 요청할 때 반드시 사용하세요. 도커는 알지만 K8s 입문 단계인 ML 엔지니어 대상입니다.
---

# K8s for ML Engineers — Course Author

ML 엔지니어를 위한 한국어 쿠버네티스 강의 자료(이론 + 실습)를 일관된 구조로 생성하는 스킬입니다. 단일 진실 소스인 `docs/study-roadmap.md`를 따르며, 모든 예시는 ML 워크로드(FastAPI 서빙, KServe/vLLM/Triton, RAG, LLM)로 구성됩니다.

## When to use

다음과 같은 사용자 요청이 들어오면 이 스킬을 사용합니다.

**트리거 예시**
- "Phase 1 학습 자료 만들어줘" / "Phase 2 챕터 작성해줘"
- "쿠버네티스 강의 자료 / 레슨 / 챕터 만들어줘"
- "KServe / vLLM / Triton 실습 자료 추가"
- "Kubeflow / Ray / Argo 튜토리얼 챕터"
- "ML on K8s 자료 / 교육 자료 / study material"
- "RAG 캡스톤 / LLM 서빙 종합 프로젝트 설계"
- "GPU 스케줄링 학습 자료"

**비트리거 (사용하지 않음)**
- "Pod 안 뜨는 거 디버깅해줘" → 일반 문제 해결
- "kubectl 명령어 알려줘" → 단순 질의
- "이 매니페스트 리뷰해줘" → 코드 리뷰
- "PRD 작성해줘" → 다른 스킬

요청이 모호하면(예: "K8s 자료 만들어줘"만 던진 경우) **한 번**만 짧게 질문해 어떤 Phase / 토픽인지 확인합니다. 이미 Phase나 토픽이 명시되어 있으면 추가 질문 없이 바로 진행합니다.

## Single source of truth

작업을 시작하기 전 **반드시** `docs/study-roadmap.md`를 먼저 읽습니다. 이 파일이 커리큘럼의 단일 진실 소스이며, 스킬은 임의로 새 토픽을 만들거나 순서를 바꾸지 않습니다. 로드맵에 없는 내용을 사용자가 요청하면 로드맵 어디에 추가하면 좋을지 먼저 제안하고 사용자 확인을 받습니다.

로드맵의 Phase 구조:

| Phase | 내용 | 기간 |
|-------|------|------|
| 0 | Docker 점검 + FastAPI 모델 컨테이너화 | 3–5일 |
| 1 | K8s 기본기 (Pod/Deployment/Service, kubectl, kind/minikube) | 2주 |
| 2 | 운영 (ConfigMap/Secret/PV/PVC/Ingress/Job/CronJob/StatefulSet/RBAC) | 2주 |
| 3 | 프로덕션 도구 (Helm, Prometheus+Grafana, HPA, RBAC) | 2주 |
| 4 | ML on K8s ⭐ (GPU, KServe/Seldon/vLLM/Triton, Kubeflow/Ray/Argo) | 3–4주 |
| 5 | 심화 (Operator, Service Mesh, GitOps, 멀티 클러스터) — 선택 | 6주+ |
| Capstone | RAG 챗봇 + LLM 서빙 종합 프로젝트 | 1–2주 |

## Output contract

**저장 위치**: 항상 프로젝트 루트의 `course/` 폴더 아래에 생성합니다(주의: 기존 `coursce/`가 아닌 `course/`).

**경로 규칙**:
- Phase 단위 인덱스: `course/phase-<N>-<slug>/README.md`
- 토픽 단위: `course/phase-<N>-<slug>/<NN>-<topic-slug>/`
- 캡스톤: `course/capstone-rag-llm-serving/`

**Phase별 슬러그(고정)**:
```
phase-0-docker-review
phase-1-k8s-basics
phase-2-operations
phase-3-production
phase-4-ml-on-k8s
phase-5-advanced
capstone-rag-llm-serving
```

**토픽 디렉토리 표준 구성**:
```
<NN>-<topic-slug>/
├── lesson.md          # 이론 본문 (학습목표 → 개념 → ML 관점 → 실습 → 검증 → 트러블슈팅)
├── manifests/         # YAML 매니페스트 (해당 시)
│   └── *.yaml
├── practice/          # Python/Dockerfile 실습 코드 (해당 시)
│   ├── Dockerfile
│   ├── fastapi_app.py
│   └── requirements.txt
└── labs/
    └── README.md      # 실행 절차 + 예상 출력 + 검증 명령어
```

토픽에 따라 `manifests/`만 있거나 `practice/`만 있을 수 있습니다. 둘 다 없는 토픽(개념 위주)은 `lesson.md`만 두되 마지막에 `kubectl explain` 등 실습 명령은 반드시 포함합니다.

## Authoring rules

1. **언어/톤**: 한국어, "~합니다" 정중체. 영어 기술 용어는 `Pod(파드)`, `Deployment(디플로이먼트)`처럼 첫 등장 시 한 번만 한글 병기 후 영문 유지.
2. **ML 우선**: 모든 예시는 ML 도메인. nginx / hello-world 예시는 사용하지 않습니다. 기본 모델 예시: HuggingFace `cardiffnlp/twitter-roberta-base-sentiment` 또는 사용자가 친숙할 만한 분류 모델. LLM 예시: `microsoft/phi-2`, `Qwen/Qwen2.5-1.5B-Instruct` 같은 SLM.
3. **이론과 실습 균형**: lesson.md 본문은 이론 50%, 실습/검증 50%. 이론만 길게 늘어놓지 않고, 각 개념 직후에 짧은 명령어 실습이 들어갑니다.
4. **실행 가능성**: 모든 코드/매니페스트는 사용자가 복사-붙여넣기로 그대로 실행 가능해야 합니다. placeholder가 있다면 `# TODO:`로 명시하고 그 이유를 적습니다.
5. **예상 출력 명시**: `kubectl get pods` 결과 등 예상 출력을 ` ``` ` 블록으로 보여주어 학습자가 본인 환경과 비교할 수 있게 합니다.
6. **기본 클러스터**: kind 또는 minikube. GPU가 필요한 토픽(Phase 4-1, vLLM 등)은 처음에 명시하고 클라우드 대안을 함께 제시합니다.
7. **자주 하는 실수 1–3개**: 각 lesson.md 끝에 "🚨 자주 하는 실수" 섹션을 둡니다(예: `requests` 누락으로 OOMKilled, `imagePullPolicy: Always` 빠짐 등).
8. **다음 챕터 링크**: 모든 lesson.md 끝에 다음 토픽으로 가는 상대 경로 링크를 답니다.

## Workflow

스킬이 트리거되면 다음 5단계로 진행합니다.

1. **로드맵 로드**: `docs/study-roadmap.md`를 읽어 요청된 Phase/토픽이 어디에 해당하는지 확인합니다.
2. **스코프 확정**: 사용자 요청에서 Phase 번호 + 토픽이 추론되면 그대로 진행. 추론 어려우면 한 번만 질문합니다 ("Phase 4의 어떤 서빙 도구를 다룰까요? KServe / vLLM / Triton 중 선택").
3. **참조 자료 로드**: 해당 Phase의 `references/phase-<N>-*.md`를 읽어 세부 가이드(학습 목표 후보, ML 시나리오, 매니페스트 패턴, 자주 하는 실수)를 가져옵니다. 캡스톤이면 `references/capstone-rag-llm.md`. 서빙 도구 비교가 필요하면 `references/ml-serving-patterns.md`. 한국어 톤/용어는 `references/korean-style-guide.md`.
4. **템플릿 적용해 파일 생성**:
   - `lesson.md`는 `assets/templates/lesson.md.tmpl`을 베이스로 채웁니다.
   - 매니페스트는 `assets/templates/manifests/*.yaml.tmpl`에서 가장 가까운 것 1–2개를 골라 토픽에 맞게 수정합니다.
   - 실습 코드는 `assets/templates/practice/*.tmpl`을 사용합니다.
   - 새 Phase 디렉토리를 처음 만드는 경우 `course/phase-<N>-*/README.md`(인덱스)도 함께 생성합니다.
5. **품질 체크리스트로 자체 검증** (아래 참고).

## References index

`references/` 폴더의 파일은 필요할 때만 읽습니다. SKILL.md는 진입점만 담당하고, 상세는 references에서 가져옵니다.

| 파일 | 언제 읽나 |
|------|----------|
| `references/phase-0-docker-review.md` | Phase 0 자료 작성 시 |
| `references/phase-1-k8s-basics.md` | Phase 1 (Pod/Deployment/Service) 자료 작성 시 |
| `references/phase-2-operations.md` | Phase 2 (ConfigMap/Secret/PV/Ingress/Job/CronJob) 자료 작성 시 |
| `references/phase-3-production.md` | Phase 3 (Helm/Prometheus/HPA/RBAC) 자료 작성 시 |
| `references/phase-4-ml-on-k8s.md` | Phase 4 (GPU/KServe/vLLM/Triton/Kubeflow/Ray) 자료 작성 시 |
| `references/phase-5-advanced.md` | Phase 5 (Operator/Service Mesh/GitOps) 자료 작성 시 |
| `references/capstone-rag-llm.md` | 캡스톤 프로젝트 자료 작성 시 |
| `references/ml-serving-patterns.md` | 서빙 도구 비교/선택을 다룰 때 |
| `references/korean-style-guide.md` | 톤/용어가 헷갈릴 때, 새 Phase를 처음 시작할 때 |

## Templates index

| 템플릿 | 용도 |
|--------|------|
| `assets/templates/lesson.md.tmpl` | 모든 `lesson.md`의 기본 골격 |
| `assets/templates/README.md.tmpl` | 각 Phase 디렉토리의 인덱스 |
| `assets/templates/manifests/deployment.yaml.tmpl` | ML 모델 서빙 Deployment (probes, resources, GPU 옵션 주석 포함) |
| `assets/templates/manifests/service.yaml.tmpl` | Service (ClusterIP/NodePort) |
| `assets/templates/manifests/configmap.yaml.tmpl` | 추론 하이퍼파라미터 ConfigMap |
| `assets/templates/manifests/secret.yaml.tmpl` | HF 토큰 패턴 |
| `assets/templates/manifests/pvc.yaml.tmpl` | 모델 가중치 캐시용 PVC |
| `assets/templates/manifests/ingress.yaml.tmpl` | 멀티 모델 라우팅 Ingress |
| `assets/templates/manifests/job.yaml.tmpl` | 배치 추론 Job |
| `assets/templates/manifests/cronjob.yaml.tmpl` | 일별 평가 CronJob |
| `assets/templates/manifests/hpa.yaml.tmpl` | HPA |
| `assets/templates/manifests/kserve-inferenceservice.yaml.tmpl` | KServe InferenceService |
| `assets/templates/manifests/vllm-deployment.yaml.tmpl` | vLLM 서빙 Deployment |
| `assets/templates/practice/Dockerfile.tmpl` | 멀티스테이지 PyTorch slim |
| `assets/templates/practice/requirements.txt.tmpl` | FastAPI + transformers + prometheus-client |
| `assets/templates/practice/fastapi_app.py.tmpl` | `/predict` + `/metrics` + `/healthz` |
| `assets/templates/practice/rag_app.py.tmpl` | 캡스톤용 RAG 앱 (vector DB + LLM 호출) |
| `assets/templates/practice/load_test.sh.tmpl` | hey/wrk 부하 테스트 스크립트 |
| `assets/templates/helm/Chart.yaml.tmpl` | Helm Chart 메타데이터 |
| `assets/templates/helm/values.yaml.tmpl` | Helm values (모델 이름, 레플리카, GPU 등) |

템플릿은 그대로 복사하지 말고 토픽에 맞게 수정해서 사용합니다. 변수 자리는 `{{...}}` 또는 `# TODO:` 주석으로 표시되어 있습니다.

## Capstone special case

캡스톤("RAG 챗봇 + LLM 서빙 종합 프로젝트") 요청이 들어오면:

1. `references/capstone-rag-llm.md`를 먼저 끝까지 읽습니다.
2. 다른 Phase처럼 단일 토픽 폴더가 아닌, **여러 컴포넌트가 통합된 프로젝트**임을 인식합니다.
3. 출력 위치: `course/capstone-rag-llm-serving/`
4. 구성:
   - `README.md` — 프로젝트 전체 개요(아키텍처 다이어그램, 사용 도구, 단계별 일정)
   - `lesson.md` — 시스템 설계 설명 (왜 이렇게 구성했는지, ML 시스템 관점)
   - `manifests/` — 통합 매니페스트 (vLLM Deployment, vector DB StatefulSet, RAG API Deployment, Ingress, ConfigMap, Secret, HPA)
   - `practice/rag_app/` — RAG 앱 코드 (FastAPI + 벡터 검색 + LLM 호출)
   - `practice/llm_serving/` — vLLM 서빙 설정과 부하 테스트
   - `practice/pipelines/` — 인덱싱 파이프라인 (Argo Workflows 또는 단순 Job)

캡스톤 lesson.md는 다른 lesson.md보다 길어도 괜찮습니다(800줄까지 허용).

## Quality checklist

생성을 마치기 전, 마음속으로 다음 8가지를 점검하고 부족한 부분은 채웁니다. 사용자에게 결과를 보고할 때 어느 항목을 충족했는지 간단히 언급하면 좋습니다.

- [ ] 학습 목표 3개 이상이 lesson.md 상단에 명시되어 있다
- [ ] "왜 ML 엔지니어에게 필요한가"를 도입부에서 한 문단으로 설명한다
- [ ] 매니페스트의 비자명한 라인에 한국어 주석이 달려 있다 (`# probe: 모델 로딩이 느려 initialDelaySeconds 60` 등)
- [ ] 실행 → 검증 → 정리 절차가 labs/README.md에 순서대로 있다
- [ ] `kubectl get pods` 등 주요 명령의 예상 출력이 코드 블록으로 들어가 있다
- [ ] "🚨 자주 하는 실수" 섹션이 1–3개 항목으로 끝부분에 있다
- [ ] 다음 토픽으로 가는 상대 링크가 lesson.md 마지막에 있다
- [ ] 모든 매니페스트가 `kubectl apply --dry-run=client` 통과 가능한 형식이다(눈으로 검토)

## Reporting

작업이 끝나면 사용자에게 짧게 보고합니다.

```
✅ Phase 1 / 01-pod-deployment-service 작성 완료

생성 위치: course/phase-1-k8s-basics/01-pod-deployment-service/
- lesson.md (학습목표 4개, ML 관점 도입, 실습 + 검증)
- manifests/deployment.yaml, service.yaml
- labs/README.md (kind 클러스터 기준 실습 절차 + 예상 출력)

다음 추천: "Phase 1 / 02-kubectl-essentials 작성"
```

장황한 요약 대신 위치 + 핵심 산출물 + 다음 추천 한 줄로 끝냅니다.
