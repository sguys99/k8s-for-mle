# Phase 5 — 심화 (선택, 6주+)

업무에서 K8s 운영을 본격적으로 맡거나 플랫폼 엔지니어 역할로 가려는 경우만 다룹니다. 일반 ML 엔지니어는 캡스톤까지 마치고 본인 업무에 적용하는 게 우선입니다.

## 권장 토픽 분할

```
course/phase-5-advanced/
├── README.md
├── 01-operator-crd/        # Operator SDK / Kubebuilder
├── 02-service-mesh/        # Istio / Linkerd
├── 03-gitops/              # Argo CD / Flux
├── 04-multi-cluster/       # Karmada / Cluster API (개요)
└── 05-certifications/      # CKAD / CKA 안내
```

## 학습 목표 후보

- 본인 도메인의 자동화를 위해 간단한 CRD + Operator를 작성할 수 있다
- Service Mesh로 모델 간 트래픽을 카나리/A-B 분할할 수 있다
- GitOps로 매니페스트를 Git에서 자동 동기화할 수 있다
- 멀티 클러스터의 필요성과 도구 옵션을 안다

## ML 관점 (Phase 5에 필요한가)

대부분의 ML 엔지니어는 Phase 5가 필요 없습니다. 다음 신호가 있으면 Phase 5로 가는 것을 검토하세요.

- 사내 ML 플랫폼을 직접 만들어야 한다 → Operator/CRD
- 모델 v1/v2 카나리 배포를 정교하게 (5%/95%) 하고 싶다 → Service Mesh
- 매니페스트가 수십 개를 넘어 Git으로 관리하고 PR 단위로 배포하고 싶다 → GitOps
- 여러 리전/클라우드에서 모델 서빙이 필요하다 → 멀티 클러스터

## 핵심 토픽 상세 (간략)

### 5-1. Operator / CRD

- **CRD** (CustomResourceDefinition): K8s에 새 오브젝트 타입 추가
- **Operator**: 그 CRD를 보고 동작하는 컨트롤러
- 도구: Operator SDK, Kubebuilder
- ML 예시: `kind: ModelServing`이라는 CRD를 만들고, 이걸 적용하면 자동으로 Deployment + Service + HPA + ServiceMonitor 생성
- 학습 곡선이 가팔라서, 처음에는 KServe/Kubeflow 같은 기존 Operator를 분석하는 것부터 권장

### 5-2. Service Mesh

- **Istio**: 가장 유명, 기능 ↑, 무거움
- **Linkerd**: 가벼움, Rust 기반, 운영 단순
- 핵심 기능: mTLS 자동, 트래픽 분할, 재시도/타임아웃, observability
- ML 활용:
  - sentiment v1 95% / v2 5% 카나리
  - 모델 간 호출(예: RAG에서 retriever → LLM)에 mTLS
  - 모델별 latency 자동 수집

### 5-3. GitOps

- **Argo CD**: GitHub repo의 매니페스트를 보고 클러스터 상태 동기화
- **Flux**: 비슷한 컨셉, CNCF graduate
- ML 활용:
  - 모델 버전 변경을 PR로 → 머지되면 자동 배포
  - 환경별 (dev/staging/prod) 분기
  - 롤백이 git revert 한 줄

### 5-4. 멀티 클러스터 (개요만)

- **Karmada**: 멀티 클러스터에 동일 워크로드 배포
- **Cluster API**: 클러스터 자체를 K8s 매니페스트로 관리
- ML 활용: 리전별 추론 클러스터, 학습/추론 클러스터 분리

### 5-5. 자격증

- **CKAD** (Certified Kubernetes Application Developer): 개발자 관점, ML 엔지니어에게 더 적절
- **CKA** (Certified Kubernetes Administrator): 운영자 관점, 깊이 있음
- 권장 순서: CKAD → 필요하면 CKA
- 준비 자료: KodeKloud, Killercoda, 공식 시험 가이드

## 강의 자료 작성 시 주의

Phase 5는 입문자를 압도할 수 있습니다. 자료에서:
- 각 토픽 도입부에 "여기는 필요한 사람만 보세요" 명시
- 실제 시나리오를 먼저 제시 ("PR 머지하면 자동 배포가 필요해진 시점")
- 과도한 매니페스트 예시보다는 개념 설명 중심
- 각 도구에 대해 "언제 도입하는지"가 가장 중요

## 자주 하는 실수

- 처음부터 Istio 도입 → 운영 복잡도 폭증. 정말 필요할 때
- Operator를 너무 일찍 만들기 → Helm + Job 조합으로 충분한 경우 많음
- GitOps 도입 후 클러스터 직접 수정 → 동기화 충돌

## 다음 단계

Phase 5 이후는 본인 업무에서 K8s를 활용하면서 학습이 이어집니다. 캡스톤 프로젝트(`references/capstone-rag-llm.md`)를 마쳤다면 충분히 실무에 투입 가능한 수준입니다.
