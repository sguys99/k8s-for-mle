# Phase 1 — Kubernetes 기본기 (2주)

K8s 입문 단계. Pod, Deployment, Service, kubectl을 ML 모델 서빙 맥락에서 익힙니다.

## 권장 토픽 분할 (디렉토리 단위)

```
course/phase-1-k8s-basics/
├── README.md
├── 01-why-k8s/                 # K8s가 ML 워크로드에 왜 필요한가
├── 02-architecture/            # Control Plane / Worker Node 구조
├── 03-pod-deployment-service/  # 핵심 오브젝트 + 모델 서빙 배포
├── 04-kubectl-essentials/      # 필수 명령어 + dry-run으로 매니페스트 만들기
└── 05-local-cluster/           # kind / minikube / k3d 환경 설정
```

## 학습 목표 후보

- K8s가 모델 서빙 인스턴스 자동 복구, 트래픽 기반 스케일링, GPU 노드 풀 관리에 어떻게 쓰이는지 설명할 수 있다
- Pod, ReplicaSet, Deployment, Service의 관계를 그림으로 그릴 수 있다
- 로컬 클러스터(kind 권장)를 띄우고 매니페스트를 적용할 수 있다
- `kubectl get/describe/logs/exec/port-forward`를 자유롭게 사용할 수 있다
- FastAPI 모델 서빙 컨테이너를 Deployment로 띄우고 Service로 외부 노출할 수 있다
- Pod이 죽었을 때 자동 복구되는 것을 직접 관찰할 수 있다

## ML 관점 도입

K8s를 ML 엔지니어가 알아야 하는 핵심 이유 3가지:

1. **자동 복구**: 추론 Pod이 OOM으로 죽어도 ReplicaSet이 자동으로 새 Pod을 띄웁니다
2. **무중단 모델 업데이트**: Deployment의 롤링 업데이트로 서비스 중단 없이 새 모델 버전 배포
3. **GPU 노드 풀 관리**: GPU는 비싼 자원입니다. K8s는 GPU가 필요한 Pod만 GPU 노드로 보냅니다

## 핵심 토픽 상세

### 1-1. K8s가 왜 필요한가

- Docker만으로 운영할 때 한계: 노드 1대 죽으면 끝, 스케일링 수동, 무중단 배포 어려움
- 컴포즈 vs K8s: 단일 호스트 vs 클러스터
- ML 관점: 모델 추론 100req/s에서 1000req/s로 트래픽 증가 시 자동 대응

### 1-2. 아키텍처

- **Control Plane**
  - API Server (모든 요청의 단일 진입점)
  - etcd (상태 저장소)
  - Scheduler (Pod을 어느 Node에 배치할지)
  - Controller Manager (실제 상태 → 원하는 상태로 수렴)
- **Worker Node**
  - kubelet (Node에서 Pod 띄우는 에이전트)
  - kube-proxy (네트워크 규칙)
  - container runtime (containerd 등)
- 학습자가 외울 필요는 없지만 **장애가 났을 때 어디를 봐야 할지** 감 잡는 게 목적

### 1-3. 핵심 오브젝트

| 오브젝트 | 역할 | ML 예시 |
|---------|------|--------|
| Pod | 가장 작은 배포 단위. 1 컨테이너 = 1 Pod 권장 | sentiment 모델 서빙 컨테이너 |
| ReplicaSet | Pod 복제본 유지 | 추론 Pod 3개 항상 유지 |
| Deployment | ReplicaSet 위에서 롤링 업데이트 | v1 → v2 모델 무중단 배포 |
| Service | Pod 집합에 안정적인 네트워크 엔드포인트 | `/predict` 호출 받을 ClusterIP |

Service 타입:
- ClusterIP (클러스터 내부만)
- NodePort (외부에서 노드 IP:포트로) — 학습용
- LoadBalancer (클라우드에서 외부 LB 자동 생성)

### 1-4. kubectl 필수 명령어

```bash
kubectl apply -f deployment.yaml       # 적용
kubectl get pods                       # 목록
kubectl get pods -o wide               # 노드 정보까지
kubectl describe pod <name>            # 상태/이벤트 상세
kubectl logs <pod>                     # 로그
kubectl logs <pod> -f                  # follow
kubectl exec -it <pod> -- bash         # 컨테이너 진입
kubectl port-forward <pod> 8000:8000   # 로컬 포트로 포워딩
kubectl delete -f deployment.yaml      # 삭제
kubectl explain pod.spec.containers    # 스키마 도움말
kubectl create deployment foo --image=bar --dry-run=client -o yaml  # 매니페스트 생성
```

### 1-5. 로컬 클러스터

| 도구 | 특징 | 추천 |
|------|------|------|
| **kind** | Docker 안에 K8s. 가볍고 CI 친화적 | ⭐ 입문 권장 |
| minikube | 가장 유명. 대시보드 내장 | GUI 좋아하면 |
| k3d | k3s 기반. 멀티노드 시뮬레이션 쉬움 | 노드 토폴로지 학습 |

설치:
```bash
# kind
go install sigs.k8s.io/kind@latest
# 또는 brew install kind

kind create cluster --name ml-lab
kubectl cluster-info --context kind-ml-lab
```

## 권장 실습 (캡스톤 격)

**Phase 0에서 만든 sentiment 모델 컨테이너를 K8s에 배포하기**

1. `kind create cluster`로 로컬 클러스터 생성
2. `kind load docker-image sentiment:0.1`로 이미지 적재 (kind 특수 절차)
3. `manifests/deployment.yaml`로 replicas=3 배포
4. `manifests/service.yaml` (NodePort)로 외부 노출
5. `kubectl port-forward` 또는 NodePort로 `/predict` 호출
6. `kubectl delete pod <sentiment-pod>`로 강제 삭제 → ReplicaSet이 자동 복구하는 것 확인
7. `kubectl scale deployment sentiment --replicas=5`로 늘려보기

## 매니페스트 패턴

### Deployment (ML 서빙 표준)
- `replicas: 3` (입문은 3개로 충분)
- `selector.matchLabels`와 `template.metadata.labels` 일치 필수
- `resources.requests` / `resources.limits` 명시 (입문이라도 빼지 않기)
- `livenessProbe` / `readinessProbe`는 Phase 1에서는 간단히 `httpGet /healthz`
- 모델 다운로드가 느리면 `initialDelaySeconds`를 60 이상으로

### Service
- 입문: `type: NodePort`로 외부에서 직접 호출 가능
- `selector`가 Deployment의 Pod label과 일치해야 함

## 자주 하는 실수

- `selector`와 Pod `labels` 불일치 → Service가 트래픽을 보낼 Pod을 못 찾음
- `kind`에서 로컬 이미지를 `kind load docker-image` 없이 사용 → ImagePullBackOff
- `requests`/`limits` 빼먹어서 노드 자원 분배 깨짐
- Probe 없어서 모델 로딩 중인 Pod이 트래픽 받음 → 첫 요청 실패

## 검증 명령어

```bash
kubectl get pods -l app=sentiment           # 3개 Running 확인
kubectl describe pod <pod>                  # Events 섹션 확인
kubectl logs deploy/sentiment --tail=20     # 모델 로딩 로그
kubectl get svc sentiment                   # NodePort 확인
curl http://localhost:<NodePort>/predict -d '{"text":"good"}'
```

예상 출력:
```
NAME                          READY   STATUS    RESTARTS   AGE
sentiment-7c9d8b5f-abc12      1/1     Running   0          2m
sentiment-7c9d8b5f-def34      1/1     Running   0          2m
sentiment-7c9d8b5f-ghi56      1/1     Running   0          2m
```

## 다음 단계

Phase 2에서 ConfigMap/Secret/PV/Ingress를 추가해 실제 운영 매니페스트로 발전시킵니다.
