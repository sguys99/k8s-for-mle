# Phase 4-4 — Argo Workflows 핵심 정리

## Workflow / WorkflowTemplate / CronWorkflow

- `Workflow` 는 일회성 실행입니다. `generateName` 으로 매번 새 이름이 붙습니다.
- `WorkflowTemplate` 은 재사용 가능한 정의입니다. 다른 Workflow 가 참조해 같은 단계를 반복합니다.
- `CronWorkflow` 는 schedule 필드를 추가해 주기적으로 Workflow 를 만들어줍니다.

## DAG vs Steps

DAG 는 의존성을 직접 적어 fan-out / fan-in 같은 복잡한 그래프를 만들 수 있습니다. Steps 는 직선적인 단계 나열에 가깝습니다. RAG 인덱싱처럼 단계가 직선이지만 차후 병렬화 가능성이 있는 워크로드는 DAG 가 자연스럽습니다.

## parameters / artifacts / PVC

세 가지 모두 단계 사이의 데이터 전달 수단입니다.
- parameters: 작은 string 값
- artifacts: 파일 — 단 ArtifactRepository(MinIO/S3) 가 필요
- PVC: workflow 단위로 자동 생성되는 공유 디스크. 입문자에게 가장 간단

## 자주 하는 실수

- ServiceAccount RBAC 누락 → "pods is forbidden"
- entrypoint 미지정 → "entrypoint template not specified"
- emptyDir 로 단계 간 데이터 공유 시도 → 단계마다 다른 Pod 이라 사라짐
