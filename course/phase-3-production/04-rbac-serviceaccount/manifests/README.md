# Phase 3 / 04 — manifests 인덱스

본 토픽은 *차트 확장* 이 주된 산출물이고, 별도 매니페스트는 두 종류만 있습니다.

| 파일 | 용도 | apply 여부 | lab 단계 |
|------|------|----------|---------|
| [cluster-admin-mistake.yaml](./cluster-admin-mistake.yaml) | default SA 에 cluster-admin 부여 — 권한 과다 부여의 위험을 직접 확인하기 위한 *학습용 위험 매니페스트* | apply 후 *즉시 삭제* | Step 2 |
| [prometheus-adapter-rbac-snapshot.yaml](./prometheus-adapter-rbac-snapshot.yaml) | Phase 3/03 의 prom-adapter helm release 가 만드는 RBAC 5종의 정적 dump — 텍스트로 읽는 학습 자료 | **apply 하지 않음** (읽기 전용) | Step 8 |

차트의 RBAC 자원은 본 토픽이 활성화하지만 매니페스트 자체는 [course/phase-3-production/01-helm-chart/manifests/chart/sentiment-api/templates/](../../01-helm-chart/manifests/chart/sentiment-api/templates/) 아래에 둡니다 (01 차트가 점진적으로 진화하는 표준 패턴).

| 차트 templates 신규 / 수정 | 위치 |
|---------------------------|------|
| `serviceaccount.yaml` (신규) | `01-helm-chart/.../templates/serviceaccount.yaml` |
| `role.yaml` (신규) | `01-helm-chart/.../templates/role.yaml` |
| `rolebinding.yaml` (신규) | `01-helm-chart/.../templates/rolebinding.yaml` |
| `deployment.yaml` (수정) | `01-helm-chart/.../templates/deployment.yaml` — `serviceAccountName` / `automountServiceAccountToken` 2줄 추가 |
| `values.yaml` (수정) | `01-helm-chart/.../values.yaml` — `serviceAccount.automountToken` / `rbac.create` / `rbac.rules` 추가 |
| `values-prod.yaml` (수정) | `01-helm-chart/.../values-prod.yaml` — `serviceAccount.create=true` + `rbac.create=true` 활성 |

본 토픽 [lesson.md](../lesson.md) 의 1–6 절과 [labs/README.md](../labs/README.md) 의 0–10 단계가 위 자원들을 순서대로 다룹니다.
