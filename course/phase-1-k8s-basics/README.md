# Phase 1 — Kubernetes 기본기 (2주)

> Phase 0에서 만든 분류 모델 컨테이너 이미지를 K8s 위에 올리기 위해, K8s를 쓰는 이유부터 Pod·Deployment·Service까지 ML 모델 서빙 맥락으로 익힙니다.
>
> **권장 기간**: 2주
> **선수 학습**: [Phase 0 — Docker 점검](../phase-0-docker-review/)

## 이 Phase에서 배우는 것

K8s가 Docker만으로는 해결하지 못하는 운영 문제(자동 복구, 무중단 배포, 트래픽 기반 스케일, GPU 노드 분리)를 어떻게 다루는지 매니페스트 단위로 학습합니다. 마지막 토픽에서는 Phase 0의 `sentiment-api:multi` 이미지를 Deployment + Service로 클러스터에 띄우고, Pod를 강제로 죽여 자동 복구되는 모습을 직접 확인합니다.

## 학습 목표

- Pod, ReplicaSet, Deployment, Service의 관계를 그림으로 그리고 ML 워크로드 예시로 설명합니다.
- minikube 위에서 모델 서빙 컨테이너를 매니페스트로 선언·배포·롤아웃·삭제합니다.
- `kubectl get/describe/logs/exec/port-forward` 4–5종 셋으로 Pod 상태를 진단합니다.
- ClusterIP / NodePort / LoadBalancer Service 3종의 차이를 이해하고 상황에 맞게 선택합니다.
- Pod이 죽었을 때 ReplicaSet이 자동 복구하는 것을 직접 관찰합니다.

## 챕터 구성

| 챕터 | 제목 | 핵심 내용 |
|------|------|----------|
| [01](./01-cluster-setup/) | minikube 설치와 첫 Pod | minikube + docker driver 기동, kubectl 컨텍스트, Pod 매니페스트와 4종 진단 명령 |
| [02](./02-pod-deployment/) | Pod / ReplicaSet / Deployment | Pod 단독의 한계, ReplicaSet self-healing, Deployment 롤링 업데이트와 롤백, `kubectl scale` |
| 03 | Service 3종과 네트워킹 | (작성 예정) ClusterIP·NodePort·LoadBalancer, DNS, port-forward |
| 04 | 분류 모델 K8s 배포 | (작성 예정) Phase 0 이미지를 Deployment + Service로 배포, Pod 강제 종료 시 자동 복구 검증 |

## 권장 진행 순서

1. 위 표 순서대로 진행합니다. 각 챕터는 이전 챕터의 결과물(클러스터, 이미지, 매니페스트)을 그대로 사용합니다.
2. 막히면 `kubectl describe`와 `kubectl logs`부터 봅니다. 거의 모든 단서가 이 두 명령에 있습니다.
3. 모든 매니페스트는 `kubectl apply --dry-run=client -f` 로 적용 전 사전 검증할 수 있습니다.

## 환경 요구사항

- WSL2 또는 macOS / Linux
- Docker Engine 24.0+ (Docker Desktop의 WSL Integration 권장)
- minikube v1.32+ (`minikube version`으로 확인)
- kubectl v1.28+ (`kubectl version --client`)
- 메모리 4GB 이상 / CPU 2코어 이상 / 디스크 여유 10GB 이상

## 마치면 할 수 있는 것

이 Phase를 완료하면 다음 캡스톤 격 실습을 수행할 수 있습니다.

> Phase 0의 `sentiment-api:multi` 이미지를 minikube 클러스터에 Deployment(replicas=3) + Service(NodePort)로 배포하고, `curl /predict`로 추론 결과를 받습니다. `kubectl delete pod <name>`으로 Pod 하나를 강제로 죽여도 ReplicaSet이 즉시 새 Pod를 띄워 가용성이 유지되는 것을 직접 확인합니다.

## 다음 Phase

➡️ [Phase 2 — 운영에 필요한 K8s 개념](../phase-2-operations/) (작성 예정)
