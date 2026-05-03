# 분류 모델 K8s 정식 배포 — Deployment + Service + 자가 치유 검증

> **Phase**: 1 — Kubernetes 기본기 (마지막 토픽)
> **소요 시간**: 60–90분 (모델 로딩 시간 포함)
> **선수 학습**:
> - [Phase 0 / 01-docker-fastapi-model — Docker로 분류 모델 감싸기](../../phase-0-docker-review/01-docker-fastapi-model/lesson.md)
> - [Phase 1 / 02-pod-deployment — Pod / ReplicaSet / Deployment](../02-pod-deployment/lesson.md)
> - [Phase 1 / 03-service-networking — Service와 DNS](../03-service-networking/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- **Phase 0의 sentiment-api:v1 이미지**를 minikube에 적재하고 `replicas=3` Deployment + ClusterIP Service로 배포해, 클러스터 내부 DNS(`http://sentiment-api/predict`)로 분류 추론을 200 OK로 받을 수 있습니다.
- **Liveness Probe / Readiness Probe**의 역할 차이를 ML 모델 관점에서 설명하고, FastAPI 앱의 `/healthz`·`/ready` 엔드포인트 동작과 매니페스트의 `initialDelaySeconds` / `failureThreshold` 값을 모델 로딩 시간(30–90초)에 맞게 직접 조정할 수 있습니다.
- `kubectl delete pod`로 1개 Pod을 강제 종료해도 **ReplicaSet이 desired=3을 맞추기 위해 새 Pod을 자동 생성**하는 자가 치유 메커니즘을 `kubectl describe rs`의 Events로 확인하고, 같은 시간 동안 Service ClusterIP가 변하지 않으며 클라이언트 호출이 끊기지 않음을 검증할 수 있습니다.
- Probe가 **없는 경우 vs 있는 경우**의 트래픽 라우팅 차이(Endpoints 등록 시점, 모델 로딩 중 503 발생 여부)를 직접 비교 실험하고, ML 추론 서비스에 Readiness Probe가 옵션이 아니라 필수인 이유를 자신의 말로 설명할 수 있습니다.
- `resources.requests` / `limits`의 의미를 분류 모델 메모리 풋프린트(약 500MB)와 연결해 설명하고, 잘못 설정했을 때 발생하는 `OOMKilled`·스케줄링 실패를 `kubectl describe pod`로 진단할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

지금까지 02·03 토픽에서 다룬 `sentiment-api:v1`은 사실 **이미지 자체가 가짜**였습니다. nginx도 아닌, 단지 같은 이름표를 단 placeholder였죠. 02에서는 Deployment 어휘(롤링 업데이트, scale, rollout undo)에 집중했고, 03에서는 Service 어휘(ClusterIP, selector, DNS)에 집중하기 위해 일부러 가벼운 이미지를 썼습니다.

04에서 처음으로 **진짜 모델 컨테이너**를 K8s 위에 올립니다. 이 순간 그동안 추상적이었던 K8s의 약속들이 ML 운영 관점에서 구체적인 의미를 갖기 시작합니다.

- 모델은 컨테이너가 부팅되고 **30–90초 후에야 응답할 준비**가 됩니다 (HF 모델 다운로드/PyTorch 초기화). 이 갭을 무시하면 클라이언트는 503을 받습니다.
- 추론 서비스는 **GPU/CPU 메모리를 넉넉히 쓰는 무거운 워크로드**입니다. `resources.limits`를 잘못 잡으면 OOMKilled로 무한 재시작에 빠집니다.
- 모델 Pod은 노드 장애·축출(eviction)·롤링 업데이트로 **언제든 죽고 다시 뜰 수 있어야** 합니다. 죽는 동안 추론 트래픽이 끊기면 SLA가 깎입니다.

K8s는 이 세 가지를 각각 **Readiness Probe**, **resources.requests/limits**, **ReplicaSet의 자가 치유**라는 메커니즘으로 해결합니다. 04 토픽 한 챕터에서 세 가지를 한 번에 묶어 직접 검증해 봅니다. 이 검증 경험이 Phase 2(ConfigMap/Secret으로 모델 설정 분리, PVC로 모델 캐시), Phase 3(HPA 자동 스케일링, Prometheus 모니터링), Phase 4(KServe / vLLM)로 가는 든든한 토대가 됩니다.

## 1. 핵심 개념

### 1-1. minikube에 로컬 이미지 적재 — 외부 레지스트리 없이 배포하기

K8s 클러스터의 노드(여기서는 minikube VM/컨테이너)는 호스트 docker와 **별도의 컨테이너 런타임**을 갖습니다. 호스트에서 `docker build`로 만든 이미지는 minikube 노드에서는 보이지 않으며, 매니페스트가 `image: sentiment-api:v1`을 참조하면 노드는 도커 허브에 그 이름의 이미지를 풀(pull)하러 가서 실패합니다 (`ImagePullBackOff`). 해결책은 두 가지입니다.

```bash
# 방법 A — minikube image load (권장, OS·환경 가장 무관)
docker build -t sentiment-api:v1 .
minikube image load sentiment-api:v1
# minikube 노드의 컨테이너 런타임에 이미지를 직접 복사 (약 1.4GB → 30~90초)

# 방법 B — minikube docker-env (호스트 docker를 minikube 노드의 docker로 직접 가리킴)
eval $(minikube docker-env)
docker build -t sentiment-api:v1 .
# 빌드 결과가 곧바로 minikube 안에 존재. 단, eval을 풀지 않으면 호스트 docker 명령이 모두 minikube 안으로 향합니다
```

본 토픽은 **방법 A**를 권장합니다. 셸 환경 변수를 건드리지 않고 명시적이며, 02 lab에서도 동일한 패턴을 썼습니다. 그리고 매니페스트에는 반드시 `imagePullPolicy: IfNotPresent`를 두어 노드가 외부 레지스트리를 풀하려 시도하지 않도록 막습니다.

### 1-2. Liveness Probe vs Readiness Probe — ML 모델 관점에서

K8s는 컨테이너의 **건강 상태(liveness)** 와 **트래픽 받을 준비(readiness)** 를 구분합니다. ML 모델 서빙에서는 이 둘이 시간적으로 다르게 충족되기 때문에 구분이 본질적입니다.

| 종류 | 질문 | 실패 시 K8s 행동 | FastAPI 엔드포인트 |
|------|------|------------------|---------------------|
| Liveness | "프로세스가 정상 동작 중인가?" | Pod 재시작 (kill + restart) | `/healthz` (항상 200) |
| Readiness | "지금 트래픽을 보내도 되는가?" | Service Endpoints에서 잠시 제외 (재시작 안 함) | `/ready` (모델 로드 후 200) |

```
시간 →

t=0s   컨테이너 부팅 시작
t=2s   uvicorn 프로세스 떠서 healthz 200 응답 가능   ← Liveness OK 시작
t=5s   FastAPI lifespan에서 모델 로딩 시작
t=60s  모델 로딩 완료 → ready 200 응답 가능          ← Readiness OK 시작 (Service에 Endpoints 등록)
```

매니페스트의 핵심 값은 `initialDelaySeconds`와 `failureThreshold`입니다. 04의 `deployment.yaml`에서:

```yaml
readinessProbe:
  httpGet: { path: /ready, port: 8000 }
  initialDelaySeconds: 10   # 컨테이너 부팅 자체에 필요한 최소 시간
  periodSeconds: 5          # 5초마다 검사
  failureThreshold: 24      # 5초 × 24 = 모델 로딩 최대 120초 허용
livenessProbe:
  httpGet: { path: /healthz, port: 8000 }
  initialDelaySeconds: 60   # 모델 로딩이 끝날 때쯤부터 검사 시작
  periodSeconds: 15
  failureThreshold: 3
```

**Liveness `initialDelaySeconds`를 짧게 잡으면 안 되는 이유**: 모델 로딩 중에 healthz가 아직 응답할 수 없으면(우리 앱은 응답합니다만, 무거운 초기화로 응답이 늦어지는 모델도 많습니다) Liveness가 실패해 컨테이너가 kill되고, 재시작 후 또 모델 로딩 → 또 kill의 무한 루프(crashloop)에 빠집니다. 보수적으로 `60s` 정도를 두는 것이 ML 워크로드 표준입니다.

### 1-3. ReplicaSet의 자가 치유 — desired vs current 루프

Deployment는 자기 안에 `replicas: 3`을 선언하고, 실제로는 ReplicaSet이라는 하위 리소스가 "desired=3 current=N" 상태를 끊임없이 비교합니다. K8s 컨트롤 플레인의 controller-manager 안에 있는 ReplicaSet 컨트롤러가 1초 단위로 다음 루프를 돕니다.

```
loop:
    desired = rs.spec.replicas
    current = count(running pods matching rs.spec.selector)
    if current < desired:
        Pod 추가 생성 (desired - current 개)   ← Pod 강제 삭제 시 여기로
    elif current > desired:
        가장 오래된 Pod부터 삭제 (current - desired 개)
```

`kubectl delete pod sentiment-api-xxx`로 Pod 1개를 지우면 0.1초 안에 ReplicaSet이 이를 감지하고 새 Pod을 만듭니다. **사용자가 할 일은 아무것도 없습니다**. 04 lab 4단계에서 이 동작을 두 셸로 동시 관찰합니다.

자가 치유는 사용자의 의도적 삭제뿐 아니라 **노드 장애, OOMKilled, evict, crash** 모든 경우에 동작합니다. 이게 K8s가 컨테이너 오케스트레이터로서 단순 docker-compose와 결정적으로 다른 점이며, ML 추론 서비스를 24×7 굴릴 수 있는 근본 이유입니다.

> **자가 치유에는 선결 조건이 있습니다**: `replicas: 1`이면 죽는 순간부터 새 Pod이 Ready가 될 때까지(=모델 로딩 완료까지) **수십 초간 다운타임**이 발생합니다. ML 추론 서비스는 최소 2, 표준 3 이상으로 두어야 자가 치유 동안에도 트래픽을 받을 수 있습니다.

### 1-4. resources.requests / limits — OOMKilled를 막는 두 줄

매니페스트에서 가장 자주 빠뜨리지만 가장 중요한 두 줄입니다.

```yaml
resources:
  requests:
    cpu: "250m"        # K8s 스케줄러가 노드를 고를 때 사용 ("이만큼 비어 있는 노드를 찾아라")
    memory: "800Mi"
  limits:
    cpu: "1"           # 컨테이너가 쓸 수 있는 최대 CPU (초과 시 throttling)
    memory: "1500Mi"   # 컨테이너가 쓸 수 있는 최대 메모리 (초과 시 OOMKilled로 강제 종료)
```

| 필드 | 의미 | 누락 시 |
|------|------|--------|
| `requests` | 스케줄링 기준치. "최소 이만큼은 보장" | 노드 자원 압박 시 가장 먼저 evict 대상이 됨 |
| `limits.memory` | 메모리 상한 | 모델이 메모리를 점차 더 쓰면서 노드 전체를 위협 → OOM 시 다른 Pod까지 함께 죽음 |
| `limits.cpu` | CPU 상한 | 추론 트래픽 폭주 시 한 Pod이 노드 CPU를 독점 → 다른 워크로드 응답 지연 |

분류 모델은 약 500MB가 메모리에 상주하므로 `requests.memory: 800Mi`(여유 포함), `limits.memory: 1500Mi`(첫 추론 시 PyTorch 작업 메모리 포함)는 안전한 시작값입니다. Phase 4의 vLLM처럼 모델이 GB 단위면 이 값을 그에 맞게 키워야 합니다.

## 2. 실습 — 핵심 흐름 (6단계 요약)

자세한 명령과 예상 출력은 [labs/README.md](labs/README.md)를 따릅니다. 여기서는 흐름과 학습 포인트만 짚습니다.

| 단계 | 핵심 동작 | 학습 포인트 |
|------|----------|-------------|
| 0 | 사전 점검 (minikube, kubectl, 기존 리소스) | 충돌 가능성 사전 차단 |
| 1 | (필요 시) `sentiment-api:v1` 이미지 적재 | minikube image load의 실제 동작 |
| 2 | `manifests/deployment.yaml` 적용 + Pod 관찰 | READY가 `0/1` → `1/1`로 바뀌는 시점차(60–90초) |
| 3 | Service + debug-client 적용, `/predict` 호출 | 클러스터 내부 DNS(`http://sentiment-api/predict`)로 200 OK 받기 |
| 4 | `kubectl delete pod` → 자가 치유 검증 | Endpoints가 갱신되어도 ClusterIP는 그대로, 호출 200 유지 |
| 5 | `deployment-no-probe.yaml`로 교체 → 503 관찰 → 복구 | Probe가 없으면 Service가 모델 로딩 중 트래픽 보냄 → 503 |
| 6 | 정리 (delete -f, minikube stop) | 이미지(`:v1`)는 Phase 2에서 재사용하므로 보존 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get pods -l app=sentiment-api`가 3개 Pod 모두 `1/1 Running`을 보입니다 (READY=1/1).
- [ ] `kubectl exec -it debug-client -- curl -s http://sentiment-api/ready`가 `{"status":"ready",...,"version":"v1"}`을 반환합니다.
- [ ] `kubectl exec -it debug-client -- curl -s -X POST http://sentiment-api/predict -H 'Content-Type: application/json' -d '{"text":"..."}'`가 `{"label":"LABEL_X","score":0.xx}`를 반환합니다.
- [ ] `kubectl delete pod <pod-name>` 직후 `kubectl get pods -w`에서 30초 안에 새 Pod이 `1/1 Running`이 되는 모습을 관찰했습니다.
- [ ] Pod 삭제 전후로 `kubectl get svc sentiment-api -o jsonpath='{.spec.clusterIP}'`의 ClusterIP가 동일합니다.
- [ ] `kubectl describe rs -l app=sentiment-api`의 Events에 `SuccessfulCreate ... Created pod ...`가 반복 기록되어 있습니다.
- [ ] `manifests/deployment-no-probe.yaml`로 교체했을 때 모델 로딩 중에 `/predict` 호출이 일시적으로 503을 받는 모습을 관찰했고, 기본 Deployment로 복구하면 다시 200이 회복됨을 확인했습니다.

## 4. 정리

```bash
# 본 토픽에서 만든 리소스 모두 삭제
kubectl delete -f manifests/debug-client.yaml --ignore-not-found
kubectl delete -f manifests/service.yaml --ignore-not-found
kubectl delete -f manifests/deployment.yaml --ignore-not-found

# 별도 셸의 watch / loop가 떠 있다면 모두 Ctrl+C
# minikube는 다음 토픽(Phase 2/01-configmap-secret)에서 그대로 사용하므로 stop만 합니다.
minikube stop
```

이미지(`sentiment-api:v1`)는 Phase 2에서 그대로 재사용하므로 `minikube image rm`을 하지 않습니다.

## 🚨 자주 하는 실수

1. **`livenessProbe.initialDelaySeconds`를 짧게 잡아 모델 로딩 중 무한 재시작** — 가장 흔하고 가장 골치 아픈 케이스입니다. 가벼운 웹 앱 예제를 베껴 `initialDelaySeconds: 5` 같은 값을 두면, 모델 로딩이 끝나기 전에 Liveness가 실패해 컨테이너가 kill됩니다. 재시작 후 또 모델 로딩 → 또 kill로 crashloop에 빠지고, `kubectl get pods`에서 RESTARTS 컬럼이 1, 2, 3, ...으로 쌓입니다. **항상 모델 로딩 시간 + 30초 이상**을 잡아야 합니다. 진단은 `kubectl describe pod`의 Events에서 `Liveness probe failed: HTTP probe failed`가 보이면 100% 이 케이스입니다.

2. **`imagePullPolicy`를 비우거나 `Always`로 두어 minikube 로컬 이미지를 못 찾는 경우** — 매니페스트에서 `imagePullPolicy`를 명시하지 않으면 이미지 태그에 따라 기본값이 달라집니다. `:latest` 태그면 `Always`, 그 외(예: `:v1`)는 `IfNotPresent`가 기본입니다. 그런데 일부 가이드는 안전을 위해 무조건 `Always`를 권장하기도 하고, 그러면 minikube가 로컬 이미지가 있어도 외부 레지스트리에 풀하러 가서 `ImagePullBackOff`가 납니다. **minikube 환경에서는 무조건 `imagePullPolicy: IfNotPresent`로 명시**합니다. 진단은 `kubectl describe pod`의 Events에서 `Failed to pull image "sentiment-api:v1"`이 보이면 이 케이스입니다.

3. **`replicas: 1`로 자가 치유를 검증하려 시도해 다운타임 발생** — Pod 1개를 지우면 새 Pod이 Ready가 될 때까지(=모델 로딩 60–90초) 트래픽이 끊깁니다. 학습자가 "자가 치유한다더니 503이 나는데?"로 혼란스러워합니다. 자가 치유는 ReplicaSet 컨트롤러가 새 Pod을 만들어 주는 것이지 **다운타임 0을 보장하는 것은 아닙니다**. 무중단 자가 치유를 원한다면 `replicas: 2` 이상에 적절한 PodDisruptionBudget(Phase 3)이 필요합니다. ML 추론 서비스는 최소 `replicas: 2`, 표준 3을 기억합니다.

## 더 알아보기

- [Kubernetes — Configure Liveness, Readiness and Startup Probes](https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/) — 본 토픽에서 다루지 않은 `startupProbe`, `exec`/`tcpSocket` Probe도 정리되어 있습니다.
- [Kubernetes — ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/) — desired vs current 루프의 공식 설명.
- [Kubernetes — Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) — requests/limits, QoS class(Guaranteed/Burstable/BestEffort) 분류 규칙.
- [Kubernetes — Pod Lifecycle](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/) — Pending/Running/Succeeded/Failed/Unknown 상태 전이와 종료 시 SIGTERM → grace period → SIGKILL 흐름.
- **PodDisruptionBudget** — 04 범위 밖. 무중단 자가 치유 / 노드 드레인 시 최소 가용 Pod 수 보장은 Phase 3에서 다룹니다.

## 다음 챕터

➡️ [Phase 2 / 01-configmap-secret — 추론 설정과 비밀 분리](../../phase-2-k8s-operations/01-configmap-secret/lesson.md) (작성 예정)

04에서 매니페스트에 하드코딩한 `MODEL_NAME`·`APP_VERSION` 같은 설정과, 앞으로 필요할 HuggingFace 토큰·S3 키 같은 비밀 값을 ConfigMap/Secret으로 분리합니다. Pod 재배포 없이 설정을 바꾸는 운영 패턴이 시작됩니다.
