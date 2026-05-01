# CLAUDE.md

ML 엔지니어를 위한 Kubernetes 교육 자료 프로젝트입니다.
모든 챕터는 **실습을 포함**하며, **ML 워크로드 관점**(모델 서빙, 학습 잡, 파이프라인 등)을 유지합니다.

> 📌 **상세 커리큘럼은 [docs/study-roadmap.md](docs/study-roadmap.md)를 Single Source of Truth로 사용합니다.**
> 챕터 작성/수정 시 항상 이 파일을 먼저 확인하세요.

---

## 디렉토리 구조

```
.
├── course/               # 교육 콘텐츠 (Phase 단위 챕터)
├── docs/
│   └── study-roadmap.md  # 학습 로드맵 (커리큘럼의 기준 문서)
├── data/                 # 실습용 샘플 데이터 (필요 시)
└── img/                  # 다이어그램, 스크린샷
```

`course/` 내부 구조는 `docs/study-roadmap.md`를 참고하여 작업할 때마다 작성/확장합니다. 미리 골격을 만들어두지 않습니다.

---

## 챕터 작성 원칙

- 각 챕터는 `README.md`(이론) + `labs/`(실습 가이드) + `manifests/`(YAML)로 분리합니다.
- `README.md` 최상단에 **학습 목표**를 명시합니다.
- 모든 챕터에 실습을 **1개 이상** 포함합니다.
- ML 엔지니어 관점("왜 ML 엔지니어에게 필요한가")을 항상 유지합니다.
- 한국어 "~합니다" 체로 작성합니다 ([docs/study-roadmap.md](docs/study-roadmap.md)와 동일 톤).
- 매니페스트는 ML 워크로드 예시(모델 서빙, 학습 잡 등)로 작성하고, 핵심 필드에 주석을 답니다.

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
2. `course/<phase>/` 아래에 표준 구조(`README.md`, `labs/`, `manifests/`)로 작성합니다.
3. minikube에서 매니페스트 동작을 검증합니다.
4. `README.md`에 실습 명령과 **예상 출력**을 함께 적습니다.

---

## 참고 자료

- **로드맵**: [docs/study-roadmap.md](docs/study-roadmap.md)
- **공식 문서**: kubernetes.io, kubeflow.org
