# Service — Pod 집합에 안정적인 네트워크 엔드포인트 부여

> **Phase**: 1 — Kubernetes 기본기
> **소요 시간**: 2–3시간
> **선수 학습**:
> - [Phase 1 / 02-pod-deployment — Pod / ReplicaSet / Deployment](../02-pod-deployment/lesson.md)
> - [Phase 1 / 01-cluster-setup — minikube와 첫 Pod](../01-cluster-setup/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- **Pod IP가 휘발적**임을 `kubectl get pod -o wide`로 직접 확인하고, Service가 안정적 가상 IP/DNS 이름을 제공해 ML 추론 클라이언트를 Pod 재시작과 분리하는 이유를 추론 SLA 관점에서 설명합니다.
- **ClusterIP / NodePort / LoadBalancer 3종**의 도달 범위·외부 노출 방식·프로덕션 적합성을 비교하고, 분류 모델 내부 호출 / 학습용 임시 노출 / 클라우드 프로덕션이라는 ML 사용처에 매핑합니다.
- Service 매니페스트의 **`selector` / `port` / `targetPort` / `nodePort`** 4필드 의미를 그림으로 설명하고 본인 매니페스트의 각 라인이 무엇을 가리키는지 구술합니다.
- **selector ↔ Pod label 불일치로 Endpoints가 비어 503**이 나는 상황을 `kubectl get endpoints`로 진단하고, 02에서 익힌 selector immutability 지식을 활용해 수정 절차를 결정합니다.
- **K8s DNS와 FQDN(`<svc>.<ns>.svc.cluster.local`)** 을 `nslookup`으로 직접 확인하고, 동일 네임스페이스에서는 짧은 이름으로도 호출되는 `/etc/resolv.conf` `search` 도메인 메커니즘을 설명합니다.
- **`kubectl port-forward`가 Service의 대안이 아니라 디버깅용 직결 통로**임을 구분하고, 프로덕션 트래픽 경로로 사용하면 안 되는 이유를 설명합니다.
- Pod 1개를 강제 삭제했을 때 **Pod IP는 바뀌지만 Service IP/DNS는 변하지 않음**을 `kubectl get endpoints -w`로 관찰하고, 클라이언트가 Pod IP가 아니라 Service 이름으로 호출해야 하는 이유를 자기 말로 정리합니다.

## 왜 ML 엔지니어에게 필요한가

이전 02 토픽에서 `kubectl delete pod` 한 줄로 Pod이 사라지면, ReplicaSet이 새 Pod을 즉시 띄워 줬습니다. 그런데 새로 뜬 Pod의 **IP는 죽은 Pod의 IP와 다릅니다**(예: `10.244.0.10` → `10.244.0.12`). 만약 분류 모델을 호출하는 클라이언트 코드가 `requests.post("http://10.244.0.10:8000/predict", ...)` 처럼 Pod IP를 직접 박아 두고 있었다면, 모델 재시작 한 번에 503이 폭주합니다. ML 추론 SLA를 깎는 가장 흔한 자기 발등 찍기입니다. 게다가 분류 모델을 `replicas=3`으로 띄웠다면 클라이언트는 **3개 Pod 중 어느 IP를 골라 호출할지조차 모호**합니다. K8s는 이 두 문제(휘발성·부하 분산)를 한꺼번에 풀기 위해 **Service**라는 추상을 도입합니다. Service는 selector로 묶인 Pod 집합 앞에 변하지 않는 ClusterIP와 DNS 이름을 부여하고, kube-proxy가 들어오는 트래픽을 살아 있는 Pod에 자동 분산합니다. 03에서 익히는 Service / DNS / port-forward 3개는 Phase 2의 Ingress, Phase 3의 Prometheus `ServiceMonitor`, Phase 4의 KServe `InferenceService`, 그리고 캡스톤의 RAG API → vLLM 호출까지 **그대로 재사용되는 가장 기본 프리미티브**입니다. 다음 04 토픽이 "Phase 0 이미지를 Deployment + Service로 정식 배포 + Pod 강제 종료 시 자동 복구 검증"인 이유는, 03에서 익힌 Service를 02 Deployment 위에 즉시 얹기 위함입니다.

## 1. 핵심 개념

### 1-1. Pod IP의 휘발성과 Service의 등장

Pod에는 부팅 시점에 클러스터 내부 IP(예: `10.244.0.10`)가 할당되지만, 이 IP는 **그 Pod에만 묶인 일회용**입니다. Pod이 노드 장애·삭제·롤링 업데이트로 사라지면 IP도 함께 사라지고, 새로 뜬 Pod은 다른 IP를 받습니다.

```
시간 →

t0   [Pod-A 10.244.0.10]   [Pod-B 10.244.0.11]
              ▲                    ▲
       클라이언트가 직접 IP 호출   ← 위험: IP가 곧 사라질 수 있음

t1   kubectl delete pod Pod-A
     [Pod-A ✗]               [Pod-B 10.244.0.11]   [Pod-C 10.244.0.12]  ← 새 Pod, 새 IP
              ▲
       클라이언트는 503         ← Pod-A 호출은 모두 실패

```

해결책은 Pod 집합 앞에 **변하지 않는 가상 IP + DNS 이름**을 두는 것입니다. 그게 Service입니다.

```
[Service sentiment-api]   ClusterIP 10.96.123.45 (영속)
        │
        │  selector: app=sentiment-api
        ▼
   ┌──────────────┬──────────────┬──────────────┐
   │ Pod-A 10.10  │ Pod-B 10.11  │ Pod-C 10.12  │  ← Pod IP는 바뀌어도
   └──────────────┴──────────────┴──────────────┘     Service IP는 그대로
```

본 토픽 실습 7단계에서 `kubectl get endpoints -w`로 이 동작을 직접 눈으로 봅니다.

### 1-2. Service의 4핵심 필드 — selector / port / targetPort / nodePort

Service 매니페스트에서 트래픽 경로를 결정하는 필드는 4개뿐입니다. 셋이 헷갈려서 생기는 사고가 03에서 가장 흔합니다.

| 필드 | 의미 | 예시 |
|------|------|------|
| `selector` | 어떤 Pod label을 잡을지 | `app: sentiment-api` |
| `port` | **클라이언트가 보는** Service 포트 | 80 |
| `targetPort` | **컨테이너가 듣는** 포트 | 8000 (FastAPI/uvicorn) |
| `nodePort` | NodePort 타입에서 **노드 IP의 외부 포트** | 30080 (30000–32767 범위) |

포트 매핑을 그림으로 보면 이렇게 됩니다.

```
                                    ┌──── Pod (sentiment-api) ──────────┐
   client                            │                                   │
     │                               │  containerPort: 8000              │
     │  curl <node-ip>:30080         │  (uvicorn이 listen하는 포트)      │
     ▼                               └────────────────┬──────────────────┘
  ┌─── Node (minikube) ───────────┐                   ▲
  │                               │                   │ targetPort: 8000
  │   nodePort: 30080             │                   │
  │       │                       │                   │
  │       ▼                       │                   │
  │   ┌── Service ──────────┐     │                   │
  │   │  port: 80           │  ─────────────── kube-proxy/iptables ──┘
  │   │  targetPort: 8000   │     │
  │   │  selector: app=...  │     │
  │   └─────────────────────┘     │
  └───────────────────────────────┘
```

기억할 한 문장: **"클라가 보는 포트(`port`) → 컨테이너 포트(`targetPort`) → (외부 도달용) 노드 포트(`nodePort`)"**. 이 줄을 거꾸로 외우면 자주 하는 실수 2번이 사라집니다.

### 1-3. Service 3종 비교 — ClusterIP / NodePort / LoadBalancer

K8s Service는 `spec.type` 한 줄로 동작이 달라집니다. 세 타입의 도달 범위와 ML 사용처를 한눈에 비교합니다.

```
                  도달 범위                            ML 사용처
─────────────────────────────────────────────────────────────────────────────
ClusterIP      [Cluster ─────────]    외부 ✗     ← 모델 ↔ 모델 내부 호출
                                                  (RAG → vLLM, 캡스톤 표준)
                                                  Phase 4 KServe도 내부 ClusterIP

NodePort       [Cluster ─────────]               ← 학습용 / 임시 디버깅
               + NodeIP:30080  외부 ✓                (포트 30000–32767)
                                                     보안 취약, 프로덕션 비추

LoadBalancer   [Cluster ─────────]               ← 클라우드 프로덕션
               + NodeIP:30080  외부 ✓                (GCP/AWS 자동 LB 프로비저닝)
               + EXTERNAL-IP   외부 ✓             ← minikube에선
                                                     `minikube tunnel` 별도 셸 필요
```

| 타입 | 매니페스트 한 줄 | 외부 도달 | 비용·복잡도 | ML 추천 사용처 |
|------|------------------|-----------|-------------|---------------|
| `ClusterIP` | `type: ClusterIP` (기본값) | ✗ | 무료 | 분류 모델 내부 호출, RAG 컴포넌트 간 통신 |
| `NodePort` | `type: NodePort` | ✓ (노드 IP) | 무료 | 학습 / 임시 데모 |
| `LoadBalancer` | `type: LoadBalancer` | ✓ (전용 공인 IP) | 클라우드 LB 비용 | 외부 노출 프로덕션 (보통 Phase 2 Ingress와 결합) |

> 📌 **실무 메모**: 본 토픽 범위 밖이지만 `clusterIP: None`을 명시하는 **headless Service**라는 변종이 있습니다. Pod 각자의 IP를 그대로 노출해 클라이언트가 부하 분산 없이 특정 Pod을 골라 호출하게 합니다. Phase 2의 StatefulSet, Phase 3의 Prometheus 서비스 디스커버리에서 다시 등장하니 이름만 기억해 둡니다.

### 1-4. Endpoints / EndpointSlice — Service의 살아 있는 selector

Service가 추상이라면 **Endpoints는 그 추상의 실제 매핑**입니다. selector에 매칭되어 **현재 Ready 상태인 Pod IP들**을 K8s가 자동으로 모아 별도 객체에 담습니다.

```
[Service sentiment-api]        [Endpoints sentiment-api]
  selector: app=sentiment-api ──→  10.244.0.10:8000
                                    10.244.0.11:8000
                                    10.244.0.12:8000   ← Ready인 Pod만
```

진단 명령은 한 줄입니다.

```bash
kubectl get endpoints sentiment-api
# NAME            ENDPOINTS                                      AGE
# sentiment-api   10.244.0.10:8000,10.244.0.11:8000              5s
```

`ENDPOINTS` 컬럼이 `<none>`이면 100% selector ↔ Pod label 불일치 또는 Pod readinessProbe 실패입니다. 자주 하는 실수 1번에서 다시 다룹니다.

> 💡 **팁**: 큰 클러스터에서는 한 Service에 수천 개 Pod이 매달릴 수 있어 단일 Endpoints 객체가 너무 커집니다. K8s 1.21+는 이를 여러 조각으로 나눠 저장하는 **EndpointSlice**로 자동 분할합니다(`kubectl get endpointslices`). 학습용으로는 `endpoints`만 봐도 충분합니다.

### 1-5. K8s DNS와 FQDN — Pod ↔ Service 호출의 표준 경로

K8s 클러스터 안에는 CoreDNS라는 DNS 서버가 `kube-system` 네임스페이스에 떠 있어, Service가 만들어질 때마다 자동으로 DNS 레코드를 등록합니다. FQDN 형식은 다음과 같습니다.

```
sentiment-api.default.svc.cluster.local
   │             │     │   └── 클러스터 도메인 (기본값)
   │             │     └────── Service 종류 표식
   │             └──────────── 네임스페이스
   └────────────────────────── Service 이름
```

Pod 안의 `/etc/resolv.conf`에는 search 도메인이 자동으로 들어 있어, **같은 네임스페이스라면 짧은 이름** 으로도 도달합니다.

```
client-pod (default ns)              kube-system / CoreDNS
─────────────────                    ─────────────────────
 wget sentiment-api/predict
        │
        │ ① /etc/resolv.conf의 search:
        │    default.svc.cluster.local
        │    svc.cluster.local
        │    cluster.local
        ▼
   sentiment-api.default.svc.cluster.local ?
        │
        │ ② CoreDNS에 질의
        ▼
   ┌──── CoreDNS ───────────┐
   │ Service 레지스트리 조회 │
   │  → ClusterIP 반환       │
   └──────────┬──────────────┘
              │ ③ 10.96.123.45
              ▼
        TCP 10.96.123.45:80
              │ kube-proxy iptables
              ▼
        Endpoints의 Pod 중 1개 (10.244.x.z:8000)
```

본 토픽 실습 3단계에서 client-pod 안에 들어가 `nslookup sentiment-api`로 이 흐름을 직접 확인합니다.

### 1-6. `kubectl port-forward` — 디버깅용 직결 통로

`kubectl port-forward svc/sentiment-api 8080:80`을 실행하면 로컬 8080 → Service 80으로 가는 임시 터널이 열립니다. 셸을 점유하며, **kubectl 세션이 살아 있는 동안만** 동작합니다.

```
[로컬 머신]                 [kubectl 프로세스]               [클러스터]
   curl localhost:8080  ──→  port-forward 8080:80   ──→   Service:80 → Pod
                              (셸 점유, Ctrl+C 시 종료)
```

오해하기 쉬운 점이 두 가지입니다.

- **port-forward는 Service의 대안이 아닙니다.** 단일 클라이언트(=`kubectl` 프로세스 1개)만 받고, kubectl이 종료되면 즉시 끊깁니다. 프로덕션 트래픽 경로로는 절대 쓰지 않습니다.
- **Service를 우회해 Pod에 직결할 수도 있습니다.** `kubectl port-forward pod/<pod-name> 8081:8000` 형식. Service의 selector를 의심하거나, 특정 Pod만 들여다보고 싶을 때 쓰는 디버깅 도구입니다.

본 토픽 실습 5단계에서 셸 1에서 port-forward를 띄우고, 셸 2에서 호출 → 셸 1을 Ctrl+C → 셸 2의 호출이 connection refused가 되는 모습을 확인해, "kubectl 세션 종속"을 손으로 익힙니다.

## 2. 실습 — 핵심 흐름 7단계

상세 단계와 예상 출력은 [labs/README.md](labs/README.md)를 따라갑니다. 여기서는 흐름만 짚습니다.

### 2-1. 사전 준비 — minikube 기동, 이미지 보존 확인

```bash
minikube start --driver=docker --memory=4g --cpus=2   # 02 끝에서 stop했다면 다시 기동
minikube image ls | grep sentiment-api                # sentiment-api:v1 보존 확인
kubectl get pods -n kube-system -l k8s-app=kube-dns   # CoreDNS Running 확인
```

### 2-2. Deployment + ClusterIP Service 배포

```bash
kubectl apply -f manifests/deployment.yaml
kubectl rollout status deployment/sentiment-api
kubectl get pods -l app=sentiment-api -o wide        # Pod IP 메모 (휘발성 검증용)

kubectl apply -f manifests/service-clusterip.yaml
kubectl get svc sentiment-api                         # ClusterIP, port 80
kubectl get endpoints sentiment-api                   # Pod IP 목록이 들어 있어야 정상
```

### 2-3. 클러스터 내부에서 DNS로 Service 호출

```bash
kubectl apply -f manifests/client-pod.yaml
kubectl wait --for=condition=Ready pod/client --timeout=60s
kubectl exec -it client -- sh
# 이 셸 안에서:
#   nslookup sentiment-api
#   wget -qO- sentiment-api/ready
#   wget -qO- sentiment-api.default.svc.cluster.local/ready
#   exit
```

### 2-4. NodePort로 호스트에서 호출

```bash
kubectl apply -f manifests/service-nodeport.yaml
kubectl get svc sentiment-api-np                      # 80:30080/TCP
curl $(minikube ip):30080/ready                       # 또는 minikube service sentiment-api-np --url
curl -X POST $(minikube ip):30080/predict \
     -H 'Content-Type: application/json' \
     -d '{"text":"K8s networking is fun"}'
```

### 2-5. `kubectl port-forward`로 Service / Pod 직결

```bash
# 셸 1 (점유):
kubectl port-forward svc/sentiment-api 8080:80
# 셸 2:
curl localhost:8080/ready
# 셸 1을 Ctrl+C → 셸 2의 다음 호출은 Connection refused
```

### 2-6. LoadBalancer + `minikube tunnel`

```bash
kubectl apply -f manifests/service-loadbalancer.yaml
kubectl get svc sentiment-api-lb                      # 처음엔 EXTERNAL-IP <pending>
# 별도 셸에서:
minikube tunnel                                       # 셸 점유, sudo 비밀번호 요구 가능
# 다시 원래 셸:
kubectl get svc sentiment-api-lb                      # EXTERNAL-IP 부여됨 (WSL2는 보통 127.0.0.1)
curl <EXTERNAL-IP>/ready
```

### 2-7. Endpoints 동적 갱신 관찰 — Service의 본질

```bash
# 셸 A:
kubectl get endpoints sentiment-api -w
# 셸 B:
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl get pod $POD -o jsonpath='{.status.podIP}'; echo
kubectl delete pod $POD
# → 셸 A의 ENDPOINTS 컬럼이 (a) 하나 줄었다가 (b) 새 IP가 등록되는 모습이 실시간으로 보입니다
kubectl get svc sentiment-api                          # ClusterIP는 그대로
```

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get svc sentiment-api`가 `TYPE=ClusterIP`, `EXTERNAL-IP=<none>`을 보입니다.
- [ ] `kubectl get endpoints sentiment-api`가 Pod 수만큼의 `IP:8000` 목록을 보여줍니다.
- [ ] client-pod에서 `wget -qO- sentiment-api/ready`가 200 응답(JSON)을 받습니다 (짧은 이름 + 동일 ns).
- [ ] client-pod에서 `nslookup sentiment-api`가 ClusterIP를 반환합니다.
- [ ] `curl $(minikube ip):30080/ready` 또는 `minikube service sentiment-api-np --url`로 호스트에서 200 응답을 받습니다.
- [ ] `kubectl port-forward`를 Ctrl+C로 종료한 직후 `curl localhost:8080/ready`가 connection refused를 보입니다.
- [ ] 별도 셸의 `minikube tunnel` 실행 후 `kubectl get svc sentiment-api-lb`의 EXTERNAL-IP가 `<pending>`이 아닙니다.
- [ ] `kubectl delete pod` 1개 실행 후 `kubectl get endpoints -w` 출력에서 IP 목록이 즉시 갱신되고, Service ClusterIP는 변하지 않습니다.

## 4. 정리

```bash
# 본 토픽에서 만든 리소스 모두 삭제
kubectl delete -f manifests/client-pod.yaml --ignore-not-found
kubectl delete -f manifests/service-loadbalancer.yaml --ignore-not-found
kubectl delete -f manifests/service-nodeport.yaml --ignore-not-found
kubectl delete -f manifests/service-clusterip.yaml --ignore-not-found
kubectl delete -f manifests/deployment.yaml --ignore-not-found

# 별도 셸의 minikube tunnel / port-forward / kubectl get -w 가 떠 있다면 모두 Ctrl+C
# minikube는 다음 토픽(04-serve-classification-model)에서 그대로 사용하므로 stop만 합니다.
minikube stop
```

이미지(`sentiment-api:v1`)는 04에서 그대로 재사용하므로 `minikube image rm`을 하지 않습니다.

## 🚨 자주 하는 실수

1. **`selector`와 Pod label 불일치로 Endpoints가 비어 503/connection refused** — Service는 떠 있는데 호출하면 응답이 안 오거나 connection refused가 납니다. `kubectl get endpoints <svc>`의 `ENDPOINTS` 컬럼이 `<none>`이면 100% 이 케이스입니다. 매니페스트에서 Service `spec.selector`와 Deployment `spec.template.metadata.labels`를 한 글자 단위로 비교해야 합니다. 02에서 본 것처럼 Deployment의 selector는 immutable이므로 잘못 만들었으면 `kubectl delete deploy ...` 후 재생성해야 합니다(Service의 selector는 수정 가능).
2. **`port` / `targetPort` / `nodePort`를 혼동해 503 또는 connection refused** — `port=8000, targetPort=80`처럼 거꾸로 적으면 Service는 만들어지지만 컨테이너 포트로 실제 트래픽이 가지 않아 503이 납니다. **클라가 보는 포트(`port`) → 컨테이너 포트(`targetPort`) → 외부 도달용 노드 포트(`nodePort`)** 한 줄로 외워 두면 거꾸로 적는 일이 사라집니다. NodePort는 30000–32767 범위에서만 가능합니다.
3. **minikube에서 LoadBalancer EXTERNAL-IP가 영영 `<pending>`** — `kubectl apply`로 LoadBalancer Service를 만들었는데 `kubectl get svc`의 EXTERNAL-IP가 5분이 지나도 `<pending>`이라면, 거의 100% 별도 셸의 `minikube tunnel`이 떠 있지 않은 경우입니다. 클라우드(GKE/EKS)에서는 클러스터가 자동으로 LB를 프로비저닝하지만, 로컬 minikube는 이를 시뮬레이션하기 위해 `minikube tunnel` 프로세스가 필요합니다. tunnel은 셸을 점유하며 sudo 비밀번호를 요구할 수 있습니다.

## 더 알아보기

- [Kubernetes — Service](https://kubernetes.io/docs/concepts/services-networking/service/) — type, sessionAffinity, externalTrafficPolicy 등 추가 옵션
- [Kubernetes — EndpointSlices](https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/) — 대규모 클러스터의 Endpoints 분할 저장
- [Kubernetes — DNS for Services and Pods](https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/) — search 도메인, FQDN 규칙
- [minikube — Accessing apps](https://minikube.sigs.k8s.io/docs/handbook/accessing/) — `minikube service`, `minikube tunnel` 동작 원리
- **headless Service (`clusterIP: None`)** — 03 범위 밖. Phase 2 StatefulSet, Phase 3 Prometheus에서 재등장합니다.

## 다음 챕터

➡️ [Phase 1 / 04-serve-classification-model — 분류 모델 K8s 정식 배포](../04-serve-classification-model/lesson.md)

03에서 익힌 ClusterIP Service를 02 Deployment에 그대로 얹어, sentiment-api를 K8s에 정식으로 올리고 Pod 강제 종료에도 자동 복구되는지 종단 검증합니다.
