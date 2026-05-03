# Phase 2 — 운영에 필요한 K8s 개념 (2주)

> Phase 1의 Deployment + Service만으로는 운영이 어렵습니다. 모델 설정·자격 증명·영구 저장소·외부 라우팅·배치 작업·환경 분리를 ConfigMap / Secret / PV / Ingress / Job / Namespace로 풀어냅니다.
>
> **권장 기간**: 2주
> **선수 학습**: [Phase 1 — Kubernetes 기본기](../phase-1-k8s-basics/)

## 이 Phase에서 배우는 것

Phase 1까지의 매니페스트는 모델 이름·버전 같은 설정값이 컨테이너 이미지나 Deployment YAML에 **하드코딩**되어 있고, 모델 가중치는 매번 컨테이너가 재기동될 때마다 다시 다운로드되며, 외부에서 호출할 때는 `port-forward` 같은 임시 수단을 썼습니다. Phase 2는 이 모든 임시방편을 운영 표준으로 교체합니다.

| 운영 문제 | Phase 2 해결책 |
|----------|----------------|
| 환경마다 모델·파라미터가 바뀌는데 매번 이미지 재빌드? | ConfigMap |
| HF 토큰·S3 키를 어떻게 안전하게 주입? | Secret |
| 모델 가중치를 매번 다시 다운로드? | PV / PVC / StorageClass |
| 외부 호출은 `port-forward`로 매번? | Ingress (L7 라우팅) |
| 평가 데이터셋을 매일 새벽 한 번만 돌리고 싶다 | CronJob |
| dev/staging/prod 환경 분리는? | Namespace + ResourceQuota |

## 학습 목표

- ConfigMap·Secret으로 추론 설정과 자격 증명을 코드/이미지에서 분리할 수 있습니다.
- PV/PVC/StorageClass로 모델 가중치 캐시·학습 체크포인트용 영구 볼륨을 만들 수 있습니다.
- Ingress 컨트롤러를 설치하고 경로 기반으로 여러 모델 엔드포인트를 라우팅합니다.
- Job·CronJob으로 배치 추론과 정기 평가를 스케줄합니다.
- Namespace·ResourceQuota로 환경별 리소스 한도를 분리합니다.

## 챕터 구성

| 챕터 | 제목 | 핵심 내용 |
|------|------|----------|
| [01](./01-configmap-secret/) | ConfigMap & Secret | 04에서 하드코딩한 `MODEL_NAME`·`APP_VERSION`을 ConfigMap으로 분리, HF 토큰을 Secret으로 주입, base64 ≠ 암호화 직접 검증, 변경 후 `rollout restart` 패턴 |
| [02](./02-volumes-pvc/) | Volumes & PVC | PVC 동적 프로비저닝(`standard` StorageClass), init container로 HF 모델을 PVC에 캐시, `replicas: 2`로 RWO 공유 시연, PVC 라이프사이클·reclaimPolicy 검증 |
| 03 | Ingress | (작성 예정) nginx-ingress 설치, 경로 기반 라우팅 |
| 04 | Job & CronJob | (작성 예정) 배치 추론 Job, 일별 평가 CronJob, `backoffLimit` / `concurrencyPolicy` |
| 05 | Namespace & Quota | (작성 예정) dev/staging/prod 분리, ResourceQuota·LimitRange |

## 권장 진행 순서

1. 위 표 순서대로 진행합니다. 01의 ConfigMap·Secret 패턴은 02 이후 모든 토픽의 매니페스트에서 반복 사용됩니다.
2. Phase 1/04에서 minikube에 적재한 `sentiment-api:v1` 이미지를 그대로 재사용합니다. 재빌드는 필요 없습니다.
3. 모든 매니페스트는 `kubectl apply --dry-run=client -f manifests/` 로 적용 전 사전 검증합니다.

## 환경 요구사항

- Phase 1과 동일 (minikube v1.32+, kubectl v1.28+, 메모리 4GB+, 디스크 10GB+)
- 03 Ingress 토픽에서 `minikube addons enable ingress` 추가 활성화 안내
- GPU는 필요하지 않습니다 (Phase 4부터 GPU 사용)

## 마치면 할 수 있는 것

이 Phase를 완료하면 다음 미니 시스템을 구축할 수 있습니다.

> 분류 모델을 ConfigMap(추론 파라미터) + Secret(HF 토큰) + PVC(모델 캐시) + Ingress(`/v1/sentiment` 라우팅)로 배포하고, 매일 새벽 3시 평가 데이터셋을 돌리는 CronJob을 dev/staging Namespace에 각각 띄웁니다.

## 다음 Phase

➡️ [Phase 3 — 프로덕션 운영 도구](../phase-3-production/) (작성 예정)
