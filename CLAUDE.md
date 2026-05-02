# CLAUDE.md

ML 엔지니어를 위한 Kubernetes 교육 자료 프로젝트입니다.
모든 챕터는 **실습을 포함**하며, **ML 워크로드 관점**(모델 서빙, 학습 잡, 파이프라인 등)을 유지합니다.

> 📌 **상세 커리큘럼은 [docs/study-roadmap.md](docs/study-roadmap.md)를 Single Source of Truth로 사용합니다.**
> 챕터 작성/수정 시 항상 이 파일을 먼저 확인하세요.
>
> ✅ **진행 상황은 [docs/course-plan.md](docs/course-plan.md)에서 토픽별 체크리스트로 관리합니다.**
> 한 토픽을 완료하면 해당 산출물(lesson.md / 매니페스트·코드 / labs / minikube 검증) 체크박스를 업데이트하세요.

---

## 디렉토리 구조

```
.
├── course/               # 교육 콘텐츠 (Phase 단위 챕터)
├── docs/
│   ├── study-roadmap.md  # 학습 로드맵 (커리큘럼의 기준 문서, SSOT)
│   └── course-plan.md    # 토픽별 진행 체크리스트 (산출물 4종 추적)
├── data/                 # 실습용 샘플 데이터 (필요 시)
└── img/                  # 다이어그램, 스크린샷
```

`course/` 내부 구조는 `docs/study-roadmap.md`를 참고하여 작업할 때마다 작성/확장합니다. 미리 골격을 만들어두지 않습니다.

각 토픽은 `course/phase-<N>-<slug>/<NN>-<topic-slug>/` 아래에 **lesson.md / 매니페스트(또는 코드) / labs/ / minikube 검증** 4종 산출물로 구성합니다. 자세한 토픽 목록과 진행 상태는 [docs/course-plan.md](docs/course-plan.md)를 참고하세요.

---

## 챕터 작성 원칙

- 각 토픽은 `lesson.md`(이론) + `labs/`(실습 가이드) + `manifests/`(YAML) 또는 `practice/`(Dockerfile·FastAPI 등 실습 코드)로 분리합니다.
- `lesson.md` 최상단에 **학습 목표 3개 이상**을 명시합니다.
- 모든 토픽에 실습을 **1개 이상** 포함합니다.
- ML 엔지니어 관점("왜 ML 엔지니어에게 필요한가")을 항상 유지합니다.
- 한국어 "~합니다" 체로 작성합니다 ([docs/study-roadmap.md](docs/study-roadmap.md)와 동일 톤).
- 매니페스트는 ML 워크로드 예시(모델 서빙, 학습 잡 등)로 작성하고, 핵심 필드에 주석을 답니다.
- `lesson.md` 끝에 **🚨 자주 하는 실수 1–3개**와 **다음 토픽 링크**를 답니다.

---

## 실습 환경

- **기본**: minikube (GUI 대시보드 내장, 입문자 친화적)
- **대안**: kind, k3d (필요 시 챕터에서 따로 안내)
- **GPU 실습**: Phase 4부터. 로컬 불가 시 GCP/AWS 임시 클러스터 사용 (실습 후 클러스터 삭제 필수)
- **OS**: WSL2 / macOS / Linux
- **kubectl**: 최신 stable 버전 권장

---

## 새 챕터 작성 워크플로우

1. [docs/study-roadmap.md](docs/study-roadmap.md)에서 해당 Phase의 학습 내용을 확인합니다.
2. [docs/course-plan.md](docs/course-plan.md)에서 작성할 토픽과 산출물 4종(lesson.md / 매니페스트·코드 / labs / minikube 검증)을 확인합니다.
3. [`/k8s-ml-course-author`](.claude/skills/k8s-ml-course-author/) 스킬을 호출하여 토픽 작성을 진행합니다.
4. `course/phase-<N>-<slug>/<NN>-<topic-slug>/` 아래에 표준 구조(`lesson.md`, `labs/`, `manifests/` 또는 `practice/`)로 작성합니다.
5. minikube에서 매니페스트 동작을 검증합니다 (Phase 0은 `docker run`, Phase 4 GPU 토픽은 클라우드 클러스터).
6. `lesson.md`와 `labs/README.md`에 실습 명령과 **예상 출력**을 함께 적습니다.
7. 작성 완료 후 [docs/course-plan.md](docs/course-plan.md)의 해당 체크박스를 `[x]`로 업데이트합니다.

---

## 참고 자료

- **로드맵 (SSOT)**: [docs/study-roadmap.md](docs/study-roadmap.md)
- **진행 체크리스트**: [docs/course-plan.md](docs/course-plan.md)
- **작성 스킬**: [`/k8s-ml-course-author`](.claude/skills/k8s-ml-course-author/)
- **공식 문서**: kubernetes.io, kubeflow.org
