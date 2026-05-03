# Ingress — nginx-ingress 컨트롤러로 모델 엔드포인트를 외부 경로로 노출하기

> **Phase**: 2 — 운영에 필요한 K8s 개념 (세 번째 토픽)
> **소요 시간**: 40–60분 (모델은 02 의 PVC 캐시 재사용 시 첫 다운로드 없음)
> **선수 학습**:
> - [Phase 2 / 02-volumes-pvc — Volumes & PVC](../02-volumes-pvc/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- `minikube addons enable ingress` 로 활성화된 nginx-ingress-controller 가 `ingress-nginx` 네임스페이스에 별도 Pod 로 떠 있음을 `kubectl get pods -n ingress-nginx` 로 직접 확인하고, **Ingress Resource(우리가 작성한 [ingress.yaml](manifests/ingress.yaml))** 와 **Ingress Controller(실제로 트래픽을 받는 nginx Pod)** 가 분리된 두 오브젝트임을 한 문장으로 설명할 수 있습니다.
- [`ingress.yaml`](manifests/ingress.yaml) 한 개를 적용하는 것으로 02 까지 클러스터 내부에서만 호출되던 `service/sentiment-api` 를 클러스터 외부에서 `curl http://localhost/v1/sentiment/predict` 로 호출 가능하게 만들고, `minikube tunnel` 과 `kubectl port-forward` 두 가지 외부 접근 방식의 차이를 설명할 수 있습니다.
- `pathType` (Exact / Prefix / ImplementationSpecific), `ingressClassName: nginx`, `rewrite-target` 의 역할을 잘못된 path / 잘못된 Host / 누락된 ingressClassName 으로 의도적으로 호출했을 때 nginx 가 404 또는 무응답을 돌려주는 것으로 직접 확인할 수 있습니다.
- ML 모델 응답 지연을 고려한 `nginx.ingress.kubernetes.io/proxy-read-timeout`·`proxy-body-size`·`proxy-buffering` annotation 의 역할을 설명하고, 첫 추론 요청이 nginx 기본 60s timeout 에 걸려 504 가 떨어지는 운영 함정을 사전에 차단할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

02 까지의 [`service.yaml`](manifests/service.yaml) 은 `type: ClusterIP` 라서 클러스터 내부에서만 호출됩니다. 학습 단계에서는 [`debug-client`](../02-volumes-pvc/manifests/debug-client.yaml) 안에서 `curl http://sentiment-api/predict` 로 충분했지만, 실제로 사내 다른 팀이나 모바일 앱·프런트엔드가 모델을 호출하려면 **클러스터 바깥의 어딘가에서 들어오는 HTTP 요청을 받아 올바른 Service 로 보내 줄** 진입점이 필요합니다. 이 자리에 들어가는 것이 Ingress 입니다. ML 운영에서 ingress 가 특별히 중요한 이유는 셋입니다. ① 모델 추론은 응답 지연이 5–60초가 흔해 nginx 의 **기본 60s timeout 에 걸리는 운영 첫 함정** 이 ingress annotation 한 줄로 해결됩니다. ② 한 클러스터에 모델이 늘어나면 (`/v1/sentiment`, `/v1/translate`, `/v1/summarize`, …) 단일 도메인 아래 경로 분기로 묶는 게 자연스러운데, 정확히 ingress 의 일이 그것입니다. ③ Phase 4 의 KServe `InferenceService`, vLLM 서빙, 캡스톤 RAG API 모두 ingress 를 외부 진입점으로 가정하고 설계되어 있어 본 토픽이 그 위 모든 ML 서빙 토픽의 게이트웨이 역할을 합니다.

## 1. 핵심 개념

### 1-1. Service vs Ingress — L4 vs L7

K8s 가 외부/내부 트래픽을 받는 두 가지 표준 메커니즘입니다. 둘은 경쟁 관계가 아니라 **층층이 쌓이는** 관계입니다 — Ingress 는 항상 Service 를 백엔드로 가집니다.

| 구분 | Service (ClusterIP / NodePort / LoadBalancer) | Ingress |
|------|----------------------------------------------|---------|
| **계층** | L4 (TCP/UDP) | L7 (HTTP/HTTPS) |
| **라우팅 단위** | IP + Port | Host + Path + Header |
| **여러 백엔드 통합** | 불가 (Service 1개 = 백엔드 1개) | 가능 (`/v1/sentiment` → A, `/v1/translate` → B) |
| **TLS 종단** | 직접 처리 불가 (앱이 처리) | 가능 (annotation + Secret) |
| **외부 노출 비용** | LoadBalancer 1개당 클라우드 LB 1개 (= 비쌈) | LoadBalancer 1개로 ingress 수십 개 처리 |
| **본 토픽에서의 역할** | 클러스터 내부 라우팅 (변경 없음) | 외부 진입점 신규 추가 |

운영의 일반적 모양: **외부 클라이언트 → (클라우드 LB) → ingress-controller(nginx Pod) → ingress 룰 매칭 → Service → Pod**. 이 중 ingress-controller 부터 Pod 까지가 K8s 안에서 일어나는 일입니다.

### 1-2. Ingress Resource vs Ingress Controller — 두 오브젝트의 분리

K8s 의 핵심 설계 패턴이 그대로 등장합니다. **선언(Resource) 과 실행(Controller) 의 분리.**

| 오브젝트 | 우리가 작성? | 어디에 있나 | 역할 |
|---------|------------|-----------|------|
| **Ingress Resource** | ✅ 우리가 작성 ([ingress.yaml](manifests/ingress.yaml)) | 우리 namespace (default) | "/v1/sentiment 는 sentiment-api:80 으로" 같은 라우팅 규칙 선언. **그 자체로는 트래픽을 받지 않습니다.** |
| **Ingress Controller** | ❌ 우리가 설치 (`minikube addons enable ingress`) | `ingress-nginx` 네임스페이스의 Pod | 실제로 :80/:443 을 listen 하는 nginx 프로세스. Resource 들을 watch 해서 자기 nginx.conf 에 반영 |

```bash
# Resource (우리 namespace): "라우팅 규칙" 선언만
kubectl get ingress
# NAME            CLASS   HOSTS   ADDRESS        PORTS   AGE

# Controller (별도 namespace): 실제 트래픽을 받는 nginx Pod
kubectl get pods -n ingress-nginx
# NAME                                        READY   STATUS    RESTARTS   AGE
# ingress-nginx-controller-xxxxxxxx-yyyyy     1/1     Running   0          5m
```

이 분리를 모르면 "ingress 를 만들었는데 왜 트래픽이 안 들어오지?" 의 99% 가 **controller 미설치** 임을 진단하지 못합니다. 본 토픽 [labs 1단계](labs/README.md) 가 정확히 이 확인을 먼저 합니다.

> 💡 **클러스터별 controller 선택지**: minikube 는 `addons enable ingress` 로 ingress-nginx 가 자동 설치됩니다. AWS EKS 는 ALB Ingress Controller, GKE 는 GCE Ingress Controller, 사내 베어메탈은 보통 ingress-nginx 또는 traefik 을 helm 으로 직접 설치합니다. 어떤 controller 를 쓰든 Resource YAML 은 같지만 **annotation 키** 와 **TLS 설정 방식** 이 다릅니다 (lesson 1-6 표 참고).

### 1-3. nginx-ingress 동작 원리 — Resource 변경에서 트래픽 적용까지

ingress-nginx-controller Pod 안에서 일어나는 일을 한 단계씩 보면 다음과 같습니다.

1. **Resource watch**: controller 가 K8s API 서버를 `--watch` 로 구독해 모든 namespace 의 Ingress / Service / Endpoint / ConfigMap 변경을 실시간으로 받습니다.
2. **nginx.conf 재생성**: 변경 이벤트가 들어오면 controller 의 Go 코드가 모든 ingress 규칙을 수집해 nginx.conf 한 덩어리를 새로 만듭니다.
3. **nginx reload**: 같은 컨테이너 안의 nginx 프로세스에 `nginx -s reload` 신호. 기존 connection 은 유지된 채 새 워커가 새 설정으로 시작합니다.
4. **트래픽 처리**: 외부 요청이 들어오면 nginx 가 자기 conf 의 server/location 룰 (Resource 의 host/path 가 변환된 것) 에 매칭해 해당 Service 의 ClusterIP 가 아니라 **Pod IP 직접** 으로 보냅니다 (kube-proxy 우회, 성능 최적화).

이 흐름이 [labs 7단계](labs/README.md) 에서 `kubectl logs -n ingress-nginx <controller-pod>` 의 access log 와 `kubectl describe ingress sentiment-api` 의 Events 로 확인됩니다.

> ⚠️ **흔한 오해**: "ingress 는 Service 의 ClusterIP 로 보낸다." 사실 nginx-ingress 는 controller 가 Endpoint 를 직접 watch 해서 **Pod IP 들의 upstream 풀** 을 만듭니다. Service 는 selector 표현 + DNS 이름 제공 용도이고, 실제 패킷은 nginx → Pod 직통입니다. 그래서 readinessProbe 가 정확해야 ingress 가 "Ready 인 Pod 만" 골라 보냅니다.

### 1-4. pathType — Exact / Prefix / ImplementationSpecific

`spec.rules.http.paths.pathType` 가 가장 자주 헷갈리는 부분입니다. 같은 path 문자열도 pathType 에 따라 매칭 결과가 달라집니다.

| pathType | 매칭 규칙 | 예시 (path: `/api`) | 정규식 사용 | 본 토픽 사용 |
|---------|----------|---------------------|------------|-------------|
| **Exact** | 정확히 일치하는 path 만 | `/api` ✓, `/api/` ✗, `/api/v1` ✗ | ❌ | — |
| **Prefix** | path 의 prefix 가 `/` 단위로 일치 | `/api` ✓, `/api/` ✓, `/api/v1` ✓, `/apix` ✗ | ❌ | — |
| **ImplementationSpecific** | controller 가 자기 방식으로 해석 (ingress-nginx 는 정규식 허용) | controller 의존 | ✅ | ✅ ([ingress.yaml](manifests/ingress.yaml) 가 이 모드로 rewrite 사용) |

**가장 흔한 함정 — trailing slash**: `pathType: Exact` + `path: /api` 로 두면 `/api` 는 매칭되지만 `/api/` 는 404 입니다. 브라우저는 경로 끝의 `/` 를 자동으로 붙이는 일이 잦아 학습자가 "분명히 잘 떴는데 갑자기 안 된다" 를 만나는 첫 번째 원인입니다. 운영에서는 거의 항상 `Prefix` 를 쓰고, 정규식이 필요한 자리만 `ImplementationSpecific` + nginx-ingress 의 `rewrite-target` 을 사용합니다.

본 토픽 [`ingress.yaml`](manifests/ingress.yaml) 의 path 정규식 `/v1/sentiment(/|$)(.*)` 와 annotation `rewrite-target: /$2` 의 동작은 다음과 같습니다.

| 외부 요청 path | 정규식 그룹 $2 | 백엔드(FastAPI) 가 받는 path |
|---------------|---------------|---------------------------|
| `/v1/sentiment` | `""` | `/` |
| `/v1/sentiment/` | `""` | `/` |
| `/v1/sentiment/ready` | `"ready"` | `/ready` |
| `/v1/sentiment/predict` | `"predict"` | `/predict` |
| `/v1/sentimentX` | (매칭 안 됨) | 404 |

백엔드 FastAPI 는 `/predict`, `/ready`, `/healthz` 만 알고 `/v1/sentiment` 라는 prefix 는 모르므로 **rewrite 가 필수** 입니다. 02 까지의 ClusterIP 직통 호출이 `http://sentiment-api/predict` 였던 이유와 정확히 짝을 이룹니다.

### 1-5. 호스트 라우팅 — 같은 IP 의 여러 도메인을 다른 백엔드로

본 토픽의 [`ingress.yaml`](manifests/ingress.yaml) 은 학습 단순화를 위해 `rules[0]` 의 `host` 를 비웠습니다 (= 모든 호스트 매칭). 운영에서는 보통 다음처럼 호스트별로 분리합니다.

```yaml
spec:
  rules:
    - host: sentiment.models.mycompany.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: sentiment-api, port: { number: 80 } }
    - host: translate.models.mycompany.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: { name: translate-api, port: { number: 80 } }
```

minikube 에서 도메인 셋업 없이 호스트 라우팅을 시연하려면 `nip.io` 와일드카드 DNS 가 편합니다.

```bash
MINIKUBE_IP=$(minikube ip)
echo "$MINIKUBE_IP"   # 예: 192.168.49.2
# host: sentiment.${MINIKUBE_IP}.nip.io  →  자동으로 192.168.49.2 로 resolve
curl -H "Host: sentiment.${MINIKUBE_IP}.nip.io" http://localhost/v1/sentiment/ready
```

본 토픽 [labs 6단계](labs/README.md) 에서 잘못된 Host 로 호출해 404 를 받는 시연이 있습니다.

### 1-6. ML 워크로드 특화 annotation

annotation 은 controller 별로 키가 다릅니다. 아래 표는 ingress-nginx 기준이며, 본 [`ingress.yaml`](manifests/ingress.yaml) 에 그대로 들어가 있습니다.

| annotation | 기본값 | 본 토픽 권장값 | ML 워크로드에서의 의미 |
|-----------|--------|--------------|---------------------|
| `proxy-read-timeout` / `proxy-send-timeout` | 60s | **120s** | 모델 첫 추론은 메모리 로딩 + 워밍업으로 5–60s 가 흔함. 60s 에 걸리면 nginx 가 504 를 돌려주는데 백엔드 Pod 로그는 200 OK 라 원인 진단이 어려움 |
| `proxy-body-size` | 1m | **8m** | 이미지 분류 (PNG ~3–8MB), OCR, 오디오 분류 (wav ~수 MB) 모델은 1m 를 쉽게 넘김 → 413 Payload Too Large |
| `proxy-buffering` | on | (분류 모델은 on, **LLM 스트리밍은 off**) | LLM SSE / chunked 응답에서 buffering 이 켜지면 토큰이 한참 모인 후 한꺼번에 전달돼 사용자 경험이 나빠짐. Phase 4 vLLM 에서 다시 만남 |
| `proxy-next-upstream-tries` | 3 | (기본 유지) | Pod 가 OOMKilled 등으로 죽었을 때 다른 Pod 로 재시도 횟수 |
| `enable-cors` | false | (필요 시 true) | 브라우저 직접 호출 (Streamlit / Gradio / 사내 대시보드) 이 다른 origin 일 때 |

본 토픽 백엔드는 단발성 분류 응답이라 `proxy-buffering` 은 기본값(on) 으로 두지만, **proxy-read-timeout 만 늘려도 운영의 첫 함정 하나가 통째로 사라집니다**.

### 1-7. (보너스) 카나리 — Phase 3 예고

같은 path 에 대해 새 모델 v2 로 트래픽 일부를 보내고 싶다면 ingress-nginx 의 카나리 annotation 을 사용합니다.

```yaml
# v2 ingress (별도 리소스, 같은 host/path)
metadata:
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "10"   # 10% 만 v2 로
spec:
  rules:
    - http:
        paths:
          - path: /v1/sentiment(/|$)(.*)
            pathType: ImplementationSpecific
            backend:
              service: { name: sentiment-api-v2, port: { number: 80 } }
```

본 토픽은 단일 백엔드 흐름에 집중하고, 카나리는 **Phase 3 / 03-autoscaling-hpa** 에서 부하 테스트와 함께 다룹니다.

## 2. 실습 — 핵심 흐름 (8단계 요약)

자세한 명령과 예상 출력은 [labs/README.md](labs/README.md) 를 따릅니다. 여기서는 흐름과 학습 포인트만 짚습니다.

| 단계 | 핵심 동작 | 학습 포인트 |
|------|----------|-------------|
| 0 | 사전 점검 (minikube, kubectl context, sentiment-api:v1, 02 잔여 정리) | 02 의 PVC 가 살아있다면 그대로 재사용 — 첫 다운로드 30–60초 절약 |
| 1 | `minikube addons enable ingress` → `kubectl get pods -n ingress-nginx` | Ingress Controller 가 별도 namespace 의 Pod 임을 직접 확인 |
| 2 | 02 자산 일괄 apply (`kubectl apply -f manifests/configmap.yaml -f .../secret.yaml -f .../pvc.yaml -f .../deployment.yaml -f .../service.yaml`) | Ingress 적용 전 백엔드부터 Ready |
| 3 | (baseline) `kubectl run tmp --rm -it --image=curlimages/curl -- curl http://sentiment-api/ready` | ClusterIP 가 여전히 동작 — ingress 적용 전후 비교 baseline |
| 4 | `kubectl apply -f manifests/ingress.yaml` → `kubectl get ingress` 의 ADDRESS 확인 | ingressClassName 으로 controller 가 resource 를 인식 |
| 5 | 별도 터미널 `minikube tunnel` (sudo) → `curl http://localhost/v1/sentiment/predict` | 외부 → ingress → Service → Pod 의 전체 경로, `version: v1-ingress` 응답 확인 |
| 6 | 의도적 실패 케이스 — `/v2/sentiment` → 404, 잘못된 path → 404, timeout 시뮬 (선택) | pathType / rewrite / timeout 의 의미를 실패로 학습 |
| 7 | `kubectl describe ingress` 로 controller events 확인 + `kubectl logs -n ingress-nginx <controller>` access log 직접 관찰 | controller 가 어떻게 본 리소스를 받아 nginx.conf 에 반영했는지 검증 |
| 8 | 정리 — Ingress 만 delete → Service/Pod 살아있음 확인 → 02 자산 정리 → tunnel Ctrl+C → `minikube stop` | Ingress 라이프사이클이 Service / Pod 와 분리됨, tunnel 프로세스 정리 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get pods -n ingress-nginx` 가 `ingress-nginx-controller-...` Pod 를 1/1 Running 으로 표시함을 확인했습니다.
- [ ] `kubectl get ingress sentiment-api` 의 `ADDRESS` 컬럼에 IP (`192.168.49.2` 또는 `localhost` 등) 가 채워짐을 확인했습니다 (controller 가 resource 를 인식한 증거).
- [ ] `curl http://localhost/v1/sentiment/ready` 가 200 OK + `{"version":"v1-ingress"}` 를 돌려줌을 확인했습니다.
- [ ] `curl -X POST http://localhost/v1/sentiment/predict -d '{"text":"..."}'` 가 모델 분류 결과를 돌려줌을 확인했습니다.
- [ ] `curl -i http://localhost/v2/sentiment/ready` 가 `404 Not Found` 임을 확인했습니다 (등록되지 않은 path).
- [ ] `kubectl describe ingress sentiment-api` 의 Events 섹션에 `Sync` 이벤트 (ingress-nginx 가 룰을 적재했다는 표시) 가 보임을 확인했습니다.
- [ ] `kubectl logs -n ingress-nginx <controller-pod>` 의 access log 에 본인이 호출한 `GET /v1/sentiment/ready 200` 줄이 보임을 확인했습니다.
- [ ] `kubectl delete -f manifests/ingress.yaml` 후 `kubectl get svc,pod -l app=sentiment-api` 가 여전히 살아있음을 확인했습니다 (Ingress 와 백엔드의 라이프사이클 분리).

## 4. 정리

본 토픽에서 만든 리소스를 두 단계로 삭제합니다. **Ingress 의 라이프사이클이 Service / Pod / PVC 와 분리됨을 인식하기 위함입니다.**

```bash
# 1차: Ingress 만 삭제 — Service/Pod/PVC 는 그대로 살아있음
kubectl delete -f manifests/ingress.yaml --ignore-not-found
kubectl get svc,pod,pvc -l app=sentiment-api    # 여전히 살아있는 것 확인

# 2차: 02 자산 (Deployment/Service/ConfigMap/Secret) 정리
kubectl delete -f manifests/deployment.yaml \
                -f manifests/service.yaml \
                -f manifests/configmap.yaml \
                -f manifests/secret.yaml \
                --ignore-not-found

# 3차: PVC 까지 비우려면 (다음 04-job-cronjob 에서 그대로 재사용해도 됨)
# kubectl delete pvc model-cache

# tunnel 을 띄웠다면 그 터미널에서 Ctrl+C 로 종료
# minikube 와 sentiment-api:v1 이미지는 다음 토픽(04-job-cronjob)에서 그대로 재사용하므로 stop 만 합니다.
minikube stop
```

> 💡 **`minikube addons enable ingress` 로 깔린 ingress-nginx-controller 는 자동으로 정리되지 않습니다.** 다음 토픽들에서 그대로 재사용하므로 켜둔 채 두는 것이 일반적입니다. 명시적으로 비활성화하려면 `minikube addons disable ingress` 입니다.

## 🚨 자주 하는 실수

1. **`minikube addons enable ingress` 를 안 깔고 ingress.yaml 부터 적용** — `kubectl apply -f ingress.yaml` 은 성공하는데 `kubectl get ingress` 의 ADDRESS 가 영원히 비어있고, 외부 curl 은 connection refused 만 떨어집니다. 진단은 `kubectl get ns | grep ingress-nginx` 한 줄 — **`ingress-nginx` 네임스페이스 자체가 없으면 controller 가 없는 것** 입니다. 해결은 `minikube addons enable ingress` 후 `kubectl wait --for=condition=Ready pod -n ingress-nginx -l app.kubernetes.io/component=controller --timeout=120s`. 운영에서는 helm 으로 `ingress-nginx/ingress-nginx` 차트를 미리 깔아 둡니다 (Phase 3 helm 토픽 참고).

2. **`ingressClassName: nginx` 를 빼먹어서 controller 가 리소스를 무시** — `kubectl get ingress` 의 CLASS 컬럼이 `<none>` 으로 보이는 케이스입니다. controller 는 IngressClass 가 자기 것 (`nginx`) 으로 명시된 리소스만 처리합니다. 옛 K8s 에서는 `kubernetes.io/ingress.class: nginx` annotation 으로 같은 일을 했는데 K8s 1.22+ 에서 deprecated 됐습니다. 두 방식을 동시에 쓰면 controller 동작이 일관되지 않으니 **`spec.ingressClassName: nginx` 한 곳만** 사용하세요. 본 [`ingress.yaml`](manifests/ingress.yaml) 가 이 패턴입니다. 진단: `kubectl describe ingress sentiment-api` 의 Events 가 비어있다면 controller 가 한 번도 본 리소스를 보지 못한 것입니다.

3. **`proxy-read-timeout` 미설정으로 첫 추론 요청이 504 — Pod 로그는 정상** — 학습자가 `curl -X POST .../predict` 를 처음 호출했을 때 60초 대기 후 504 Gateway Time-out 이 떨어지는데, `kubectl logs <pod>` 를 보면 추론은 80초쯤 후에 정상 완료되어 200 응답을 보낸 흔적이 있습니다. nginx 는 자기 timeout (60s 기본) 을 넘긴 백엔드 응답을 버리고 504 를 돌려준 뒤 나중에 도착한 200 은 그냥 무시한 것입니다. 본 [`ingress.yaml`](manifests/ingress.yaml) 의 `proxy-read-timeout: "120"` 한 줄이 이 함정을 차단합니다. 운영에서는 모델별 p99 latency 를 측정해 timeout 을 적정 값으로 설정합니다 — 너무 늘리면 죽은 백엔드를 오래 잡고 있어 카스케이드 장애의 원인이 됩니다.

## 더 알아보기

- [Kubernetes — Ingress](https://kubernetes.io/docs/concepts/services-networking/ingress/) — Resource 스펙, pathType 의 권위 있는 정의, IngressClass 동작 상세.
- [ingress-nginx — Annotations 전체 목록](https://kubernetes.github.io/ingress-nginx/user-guide/nginx-configuration/annotations/) — proxy 타임아웃, body size, buffering, rewrite, canary, rate-limit, basic-auth 등 운영에서 자주 쓰는 모든 키.
- [minikube — Ingress addon 가이드](https://minikube.sigs.k8s.io/docs/handbook/addons/ingress-dns/) — `minikube tunnel`, ingress-dns 와 같이 쓰는 방법, 트러블슈팅.
- [ingress-nginx — Architecture](https://kubernetes.github.io/ingress-nginx/how-it-works/) — controller 의 watch → conf 재생성 → reload 흐름의 내부 구현 다이어그램.
- [KServe — Inference Service URL Routing](https://kserve.github.io/website/latest/modelserving/servingruntimes/) — Phase 4 에서 만날 KServe 가 본 토픽의 ingress 위에 어떻게 자동으로 라우팅을 얹는지 미리보기.

## 다음 챕터

➡️ [Phase 2 / 04-job-cronjob — 배치 추론과 정기 평가 잡](../04-job-cronjob/lesson.md)

다음 토픽에서는 본 토픽까지의 "오래 떠 있는 모델 서빙 (Deployment + Service + Ingress)" 와 대비되는 **단발성 / 주기적 워크로드** 를 다룹니다. 평가 데이터셋 일괄 추론 (Job), 매일 새벽 평가 메트릭 갱신 (CronJob), `backoffLimit`·`activeDeadlineSeconds`·`concurrencyPolicy` 같은 잡 전용 필드를 학습합니다. 본 토픽의 PVC 와 ConfigMap 은 그대로 재사용해 같은 모델로 배치 추론을 수행합니다.
