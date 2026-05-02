# Phase 2 — 운영에 필요한 K8s 개념 (2주)

ML 모델 서빙은 환경 변수, 모델 가중치, 인증 정보, 영구 저장소가 모두 필요합니다. Phase 2는 진짜 운영에 필요한 오브젝트를 다룹니다.

## 권장 토픽 분할

```
course/phase-2-operations/
├── README.md
├── 01-configmap-secret/        # 추론 설정 / HF 토큰 주입
├── 02-volumes/                 # PV/PVC로 모델 가중치 캐싱
├── 03-ingress/                 # 멀티 모델 라우팅
├── 04-jobs-cronjobs/           # 배치 추론 / 정기 평가
├── 05-statefulset-daemonset/   # 분산 학습 워커 / GPU 모니터링
└── 06-namespace-rbac-basics/   # dev/staging/prod 분리
```

## 학습 목표 후보

- ConfigMap과 Secret을 사용해 모델 설정과 자격증명을 컨테이너에 주입할 수 있다
- PV/PVC/StorageClass의 관계를 이해하고 모델 가중치 캐시용 PVC를 만들 수 있다
- Ingress로 여러 모델 엔드포인트를 호스트/경로 기반으로 라우팅할 수 있다
- Job/CronJob으로 배치 추론과 정기 평가를 실행할 수 있다
- Namespace로 환경 분리를 할 수 있다

## ML 워크로드 매핑

| 카테고리 | 오브젝트 | ML 활용 예시 |
|---------|---------|-------------|
| 설정 | ConfigMap | 모델 하이퍼파라미터, 추론 batch_size, top_k |
| 비밀 | Secret | HuggingFace 토큰, S3 키, OpenAI API 키 |
| 저장소 | PV / PVC / StorageClass | 모델 가중치 캐시, 학습 체크포인트, 로그 |
| 네트워크 | Ingress | `/v1/sentiment`, `/v1/translate` 경로 라우팅 |
| 워크로드 | Job | 배치 추론 (한 번 돌고 끝) |
| 워크로드 | CronJob | 매일 새벽 평가 데이터셋 평가 |
| 워크로드 | StatefulSet | 분산 학습 워커, 벡터 DB(Qdrant, Milvus) |
| 워크로드 | DaemonSet | 노드별 GPU 사용률 모니터링 에이전트 |
| 격리 | Namespace, ResourceQuota | dev/staging/prod 분리, GPU 쿼터 |

## 핵심 토픽 상세

### 2-1. ConfigMap & Secret

- **ConfigMap**: 평문 설정. envFrom 또는 volumeMount로 마운트.
- **Secret**: base64 인코딩(암호화 아님). 외부 KMS와 연동하면 진짜 보안.
- ML 패턴:
  - ConfigMap에 `inference_config.yaml` 통째로 마운트 → 코드는 파일만 읽음
  - Secret으로 `HF_TOKEN` env 주입 → `transformers` 라이브러리가 자동 사용

매니페스트 예:
```yaml
envFrom:
- configMapRef:
    name: inference-config
- secretRef:
    name: model-tokens
```

### 2-2. Volumes (PV/PVC/StorageClass)

- **PV**: 클러스터 관리자가 만들거나 동적 프로비저닝
- **PVC**: 사용자가 "이 정도 필요해요" 신청
- **StorageClass**: 어떤 종류 (SSD, HDD, NFS)
- ML 패턴:
  - 모델 가중치 (수 GB)를 매번 다운로드하지 않으려면 PVC에 캐시
  - init container로 S3에서 받아 PVC에 저장 → 메인 컨테이너는 PVC만 마운트
  - `accessModes: ReadOnlyMany`로 여러 Pod이 같은 모델 공유

### 2-3. Ingress

- Service만으로는 외부 노출이 제한적 → Ingress가 L7 라우팅 담당
- Ingress Controller 필수 (nginx-ingress, traefik)
- ML 패턴:
  - `models.example.com/sentiment` → sentiment-svc
  - `models.example.com/translate` → translate-svc
  - 한 도메인에 여러 모델

### 2-4. Job & CronJob

- **Job**: 한 번 실행 후 완료
  - 배치 추론 (10000개 문장 분류 후 종료)
  - 학습 데이터 전처리
- **CronJob**: 스케줄 실행
  - 매일 새벽 3시 평가 데이터셋에 대해 모델 평가 (`schedule: "0 3 * * *"`)
  - 매시간 신규 데이터로 임베딩 갱신

### 2-5. StatefulSet & DaemonSet (간단히)

- **StatefulSet**: Pod에 안정적인 이름 + 순서 보장. 벡터 DB(Qdrant, Milvus), 분산 학습 워커
- **DaemonSet**: 모든(또는 특정 라벨) 노드에 1개씩. node-exporter, NVIDIA DCGM exporter

### 2-6. Namespace & RBAC 기초

- Namespace로 환경 분리 (dev/staging/prod)
- ResourceQuota로 namespace당 GPU 개수 제한
- RBAC 기초는 Phase 3에서 본격화. 여기서는 ServiceAccount 개념만

## 권장 실습 (캡스톤 격)

**MLOps 미니 시스템 구축**

1. PVC에 모델 가중치 다운로드 (init container로 HuggingFace에서)
2. ConfigMap으로 추론 파라미터(`max_length`, `top_k`) 관리
3. Secret으로 `HF_TOKEN` 주입
4. Ingress로 `/v1/sentiment`, `/v1/translate` 라우팅 (모델 2개)
5. CronJob으로 매일 평가 데이터셋 실행 결과 로그 수집

토픽별로 작은 실습을 두고, 마지막 06 또는 별도 capstone-mini로 통합 실습.

## 자주 하는 실수

- Secret을 git에 평문으로 커밋 → SealedSecret 또는 외부 KMS 사용 권장
- PVC `accessModes`를 `ReadWriteOnce`로 두고 여러 Pod에서 마운트 시도 → 실패
- ConfigMap 변경해도 Pod 자동 재시작 안 됨 → annotation에 hash 넣거나 Reloader 사용
- Job이 실패해도 재시도 무한 → `backoffLimit` 설정 필수
- CronJob `concurrencyPolicy: Allow` 기본값으로 두면 작업 겹침 → `Forbid`로

## 검증 명령어

```bash
kubectl get configmap inference-config -o yaml
kubectl get secret model-tokens -o yaml
kubectl get pvc model-cache
kubectl describe pvc model-cache  # 바인딩 확인
kubectl get ingress
curl -H "Host: models.example.com" http://<ingress-ip>/v1/sentiment -d '{"text":"good"}'
kubectl get jobs
kubectl get cronjobs
kubectl logs job/eval-2026-05-01
```

## 다음 단계

Phase 3에서 Helm으로 이 모든 매니페스트를 패키징하고, Prometheus/Grafana로 모니터링, HPA로 자동 스케일링을 추가합니다.
