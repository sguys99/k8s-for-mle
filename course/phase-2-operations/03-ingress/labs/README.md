# Phase 2 / 03-ingress — 실습 가이드

> 02 까지 클러스터 내부에서만 호출하던 `service/sentiment-api` 를 nginx-ingress-controller 를 통해 클러스터 외부에서 `curl http://localhost/v1/sentiment/predict` 로 호출 가능하게 만들고, 잘못된 path / Host 로 호출했을 때의 라우팅 동작을 직접 검증합니다.
>
> **예상 소요 시간**: 40–60분 (02 의 PVC 캐시가 살아있으면 모델 다운로드 없음)
>
> **선행 조건**
> - [Phase 2 / 02-volumes-pvc](../../02-volumes-pvc/lesson.md) 완료
> - minikube 에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/04 lab 1단계에서 적재됨)
>
> **작업 디렉토리**
> ```bash
> cd course/phase-2-operations/03-ingress
> ```

---

## 0단계 — 사전 준비 점검

### 0-1. minikube 상태 확인

```bash
minikube status
```

```
# 예상 출력
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

`Stopped` 가 보이면 `minikube start` 로 기동합니다. 02 에서 `minikube stop` 만 했다면 PVC 와 그 안의 모델 캐시가 그대로 살아있어 본 토픽에서 첫 다운로드가 발생하지 않습니다.

### 0-2. kubectl 컨텍스트 확인

```bash
kubectl config current-context
```

```
# 예상 출력
minikube
```

### 0-3. sentiment-api:v1 이미지 확인

```bash
minikube image ls | grep sentiment-api
```

```
# 예상 출력
docker.io/library/sentiment-api:v1
```

비어 있다면 → [Phase 1/04 lab 1단계](../../../phase-1-k8s-basics/04-serve-classification-model/labs/README.md#1단계--필요-시-phase-0-이미지를-minikube에-적재) 로 가서 다시 적재한 뒤 돌아옵니다.

### 0-4. 02 의 잔여 자산 점검

본 토픽은 02 와 같은 이름의 Service / Deployment / ConfigMap / Secret / PVC 를 사용합니다. 02 의 정리 단계를 잘 수행했다면 PVC 만 살아있거나 비어있습니다.

```bash
kubectl get deploy,svc,pod,cm,secret,pvc -l app=sentiment-api
```

다음 두 시나리오 중 하나입니다.

- **시나리오 A** — PVC `model-cache` 만 보임 (02 의 1차 정리만 한 경우): 이상적입니다. 본 토픽은 PVC 를 그대로 재사용해 모델 다운로드를 스킵합니다.
- **시나리오 B** — 모두 비어있거나 02 자산이 그대로 남아있음: 그래도 문제없습니다. 본 토픽의 매니페스트가 모두 같은 이름이라 `apply` 가 멱등하게 덮어쓰기 / 새로 생성합니다.

만약 02 의 Deployment 가 살아있고 본 토픽을 처음부터 다시 시작하고 싶다면 Deployment 만 정리합니다.

```bash
kubectl delete deployment sentiment-api --ignore-not-found
```

```
# 예상 출력
deployment.apps "sentiment-api" deleted
# 또는 없었다면
# (출력 없음)
```

---

## 1단계 — minikube ingress addon 활성화 + Controller Pod 확인

이번 단계가 본 토픽의 가장 중요한 첫걸음입니다. **Ingress Resource 와 Ingress Controller 의 분리** ([lesson.md 1-2 절](../lesson.md#1-2-ingress-resource-vs-ingress-controller--두-오브젝트의-분리))를 직접 봅니다.

### 1-1. ingress addon 활성화

```bash
minikube addons enable ingress
```

```
# 예상 출력 (1–3분 소요)
💡  ingress is an addon maintained by Kubernetes. ...
    ▪ Using image registry.k8s.io/ingress-nginx/controller:v1.10.x
    ▪ Using image registry.k8s.io/ingress-nginx/kube-webhook-certgen:v...
🔎  Verifying ingress addon...
🌟  The 'ingress' addon is enabled
```

이 명령이 한 일은 `ingress-nginx` 네임스페이스에 nginx-ingress-controller Deployment 와 Service, IngressClass 등 일련의 리소스를 생성한 것입니다.

### 1-2. 새로 생긴 ingress-nginx 네임스페이스 둘러보기

```bash
kubectl get ns | grep ingress-nginx
```

```
# 예상 출력
ingress-nginx           Active   1m
```

> 💡 **이 네임스페이스가 보이지 않으면** 1-1 의 addon 활성화가 실패한 것입니다 (lesson.md 자주 하는 실수 1번). `minikube logs` 로 원인 확인 후 재시도합니다.

### 1-3. Controller Pod 가 Ready 가 될 때까지 대기

```bash
kubectl wait --for=condition=Ready pod \
  -n ingress-nginx \
  -l app.kubernetes.io/component=controller \
  --timeout=180s
```

```
# 예상 출력
pod/ingress-nginx-controller-xxxxxxxx-yyyyy condition met
```

### 1-4. Controller 자원 전체 보기

```bash
kubectl get all -n ingress-nginx
```

```
# 예상 출력 (발췌)
NAME                                            READY   STATUS      RESTARTS   AGE
pod/ingress-nginx-admission-create-xxxxx        0/1     Completed   0          2m
pod/ingress-nginx-admission-patch-yyyyy         0/1     Completed   0          2m
pod/ingress-nginx-controller-zzzzzzzzz-aaaaa    1/1     Running     0          2m

NAME                                         TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)
service/ingress-nginx-controller             NodePort    10.96.x.x       <none>        80:31xxx/TCP,443:31xxx/TCP
service/ingress-nginx-controller-admission   ClusterIP   10.96.y.y       <none>        443/TCP

NAME                                       READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/ingress-nginx-controller   1/1     1            1           2m
```

이 Pod 가 본 토픽 [`ingress.yaml`](../manifests/ingress.yaml) 을 watch 하면서 자기 nginx.conf 에 라우팅 룰을 적재하는 주체입니다 (lesson.md 1-3 동작 원리).

### 1-5. IngressClass 확인

```bash
kubectl get ingressclass
```

```
# 예상 출력
NAME    CONTROLLER             PARAMETERS   AGE
nginx   k8s.io/ingress-nginx   <none>       2m
```

`nginx` 가 보이면 본 토픽의 [`ingress.yaml`](../manifests/ingress.yaml) `spec.ingressClassName: nginx` 와 정확히 매칭됩니다.

---

## 2단계 — 02 자산 일괄 적용 + Backend Ready 대기

본 토픽의 ingress 가 트래픽을 받기 전에 백엔드 (sentiment-api Pod) 가 Ready 가 되어 있어야 합니다.

### 2-1. ConfigMap / Secret / PVC / Deployment / Service 적용

```bash
kubectl apply -f manifests/configmap.yaml \
              -f manifests/secret.yaml \
              -f manifests/pvc.yaml \
              -f manifests/deployment.yaml \
              -f manifests/service.yaml
```

```
# 예상 출력
configmap/sentiment-api-config created
secret/sentiment-api-secrets created
persistentvolumeclaim/model-cache unchanged    # 02 PVC 가 살아있으면 unchanged
deployment.apps/sentiment-api created
service/sentiment-api created
```

> 💡 **PVC 가 `unchanged` 로 보이면** 02 의 모델 캐시가 그대로 살아있어 init container 가 다운로드를 스킵합니다 (10초 안에 Ready). `created` 로 보이면 새 PVC 가 만들어진 것이라 init 에서 모델 다운로드 30–60초가 발생합니다.

### 2-2. Pod Rollout 완료까지 대기

```bash
kubectl rollout status deployment/sentiment-api --timeout=180s
```

```
# 예상 출력 (PVC 캐시 재사용 시)
Waiting for deployment "sentiment-api" rollout to finish: 0 of 2 updated replicas are available...
Waiting for deployment "sentiment-api" rollout to finish: 1 of 2 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

### 2-3. APP_VERSION 이 본 토픽 값인지 확인

```bash
kubectl get cm sentiment-api-config -o jsonpath='{.data.APP_VERSION}'
echo
```

```
# 예상 출력
v1-ingress
```

5단계의 외부 호출 응답에 이 값이 그대로 보일 것입니다.

---

## 3단계 — Baseline: ClusterIP 가 여전히 동작함을 확인

ingress 적용 전후를 비교하려면 baseline 이 필요합니다. 02 까지의 호출 방식 (클러스터 내부에서만) 이 아직 잘 되는지 먼저 확인합니다.

```bash
kubectl run tmp-curl --rm -it --restart=Never \
  --image=curlimages/curl:8.5.0 \
  -- curl -s http://sentiment-api/ready
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-ingress"}
pod "tmp-curl" deleted
```

`version` 이 `"v1-ingress"` 면 본 토픽 ConfigMap 이 정상 주입된 것입니다. 아직 외부 클라이언트는 이 엔드포인트에 닿을 수 없습니다 — 그것이 4단계 ingress 의 일입니다.

---

## 4단계 — Ingress 적용 + ADDRESS 채워지는 것 관찰

### 4-1. Ingress 매니페스트 적용

```bash
kubectl apply -f manifests/ingress.yaml
```

```
# 예상 출력
ingress.networking.k8s.io/sentiment-api created
```

### 4-2. ADDRESS 컬럼이 채워지는 것 확인

```bash
kubectl get ingress -w
```

수 초 안에 ADDRESS 가 채워집니다 (Ctrl+C 로 중단).

```
# 예상 출력 (ADDRESS 가 비어있다가 채워짐)
NAME            CLASS   HOSTS   ADDRESS        PORTS   AGE
sentiment-api   nginx   *       <none>         80      2s
sentiment-api   nginx   *       192.168.49.2   80      8s    ← controller 가 controller Pod IP 를 ADDRESS 로 보고
```

> 💡 **ADDRESS 가 영원히 비어있다면**:
> - `minikube addons enable ingress` 가 안 깔린 상태 (자주 하는 실수 1번)
> - `spec.ingressClassName: nginx` 가 빠져 controller 가 본 리소스를 무시 (자주 하는 실수 2번)
> - controller Pod 가 CrashLoopBackOff (1-3 단계 확인)

### 4-3. Ingress 상세 확인

```bash
kubectl describe ingress sentiment-api
```

```
# 예상 출력 (발췌)
Name:             sentiment-api
Labels:           app=sentiment-api
                  phase=2
                  topic=03-ingress
Namespace:        default
Address:          192.168.49.2
Ingress Class:    nginx
Default backend:  <default>
Rules:
  Host        Path                            Backends
  ----        ----                            --------
  *
              /v1/sentiment(/|$)(.*)          sentiment-api:80 (10.244.0.x:8000,10.244.0.y:8000)
Annotations:  nginx.ingress.kubernetes.io/proxy-body-size: 8m
              nginx.ingress.kubernetes.io/proxy-read-timeout: 120
              nginx.ingress.kubernetes.io/proxy-send-timeout: 120
              nginx.ingress.kubernetes.io/rewrite-target: /$2
Events:
  Type    Reason  Age   From                      Message
  ----    ------  ----  ----                      -------
  Normal  Sync    8s    nginx-ingress-controller  Scheduled for sync
```

**Backends 컬럼에 Pod IP 두 개**가 보이면 controller 가 Service `sentiment-api` 의 endpoint 를 직접 watch 해 upstream 풀로 잡은 것입니다 (lesson.md 1-3 의 "kube-proxy 우회" 동작).

**Events 의 `Normal Sync` 이벤트** 한 줄이 controller 가 본 리소스를 인식했다는 결정적 증거입니다 — 이게 안 보이면 ingressClassName 이 잘못된 것입니다.

---

## 5단계 — 외부에서 호출 (`minikube tunnel` 메인 + `port-forward` 폴백)

### 5-A. 메인 방식 — `minikube tunnel`

`minikube tunnel` 은 클러스터의 LoadBalancer 타입 Service 와 ingress 를 호스트의 127.0.0.1 에 노출시켜 줍니다 (실제 클라우드 LB 를 모방).

#### 5-A-1. 별도 터미널에서 tunnel 실행 (이 터미널은 계속 살아있어야 함)

```bash
minikube tunnel
```

```
# 예상 출력 (sudo 비밀번호 요구)
✅  Tunnel successfully started

📌  NOTE: Please do not close this terminal as this process must stay alive for the tunnel to be accessible ...

❗  The service/ingress sentiment-api requires privileged ports to be exposed: [80 443]
🔑  sudo permission will be asked for it.
[sudo] password for sguys99:
🏃  Starting tunnel for service sentiment-api.
```

> ⚠️ **WSL2 / macOS 권한 안내**: 80 / 443 은 privileged port 라 sudo 가 필요합니다. tunnel 이 계속 살아있어야 외부 호출이 동작합니다 — 이 터미널을 닫지 마세요.

#### 5-A-2. (원래 터미널로 돌아와서) 외부 호출

```bash
curl -s http://localhost/v1/sentiment/ready
echo
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-ingress"}
```

```bash
curl -s -X POST http://localhost/v1/sentiment/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"Ingress finally exposes my model to the world"}'
echo
```

```
# 예상 출력
{"label":"LABEL_2","score":0.9...}
```

축하합니다 — 외부 클라이언트가 ingress → Service → Pod 의 전 경로를 거쳐 모델 응답을 받았습니다.

### 5-B. 폴백 방식 — `kubectl port-forward` (tunnel 이 안 되는 환경)

WSL2 의 일부 네트워크 모드에서 `minikube tunnel` 의 sudo 가 잘 안 되거나 호스트와 게스트 사이 라우팅 문제로 `localhost` 가 닿지 않을 때 사용합니다.

#### 5-B-1. ingress-nginx Service 를 호스트 8080 으로 포워딩

```bash
# 별도 터미널에서 실행 (이 터미널 계속 살아있어야 함)
kubectl port-forward -n ingress-nginx svc/ingress-nginx-controller 8080:80
```

```
# 예상 출력
Forwarding from 127.0.0.1:8080 -> 80
Forwarding from [::1]:8080 -> 80
```

#### 5-B-2. (원래 터미널로 돌아와서) 외부 호출 — 포트만 8080 으로

```bash
curl -s http://localhost:8080/v1/sentiment/ready
echo
```

```
# 예상 출력
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1-ingress"}
```

```bash
curl -s -X POST http://localhost:8080/v1/sentiment/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"Port-forward works too"}'
echo
```

```
# 예상 출력
{"label":"LABEL_2","score":0.9...}
```

> 💡 **두 방식의 차이**: tunnel 은 운영 LoadBalancer 동작에 가깝고 80 포트를 그대로 사용하므로 학습 가치가 큽니다. port-forward 는 단일 Service 를 호스트의 임의 포트에 직접 묶는 디버깅 도구로 운영에서는 사용하지 않습니다. 6–7 단계는 5-A 또는 5-B 중 어느 쪽으로든 진행하면 됩니다 (이하 명령은 5-A 의 `localhost` 기준, 5-B 라면 `localhost:8080` 으로 바꿔 읽으세요).

---

## 6단계 — 의도적 실패 케이스로 라우팅 동작 검증

ingress 는 어떤 path 에 어떤 Host 로 와야 매칭되는지 정확한 룰이 있습니다. 잘못된 호출이 어떻게 거절되는지 직접 보면 1-4 / 1-5 절의 표가 머리에 남습니다.

### 6-1. 등록되지 않은 path → 404 (ingress-nginx 가 돌려줌)

```bash
curl -i http://localhost/v2/sentiment/ready
```

```
# 예상 출력 (헤더 + 본문)
HTTP/1.1 404 Not Found
Date: ...
Content-Type: text/html
Content-Length: 146
Connection: keep-alive

<html>
<head><title>404 Not Found</title></head>
<body>
<center><h1>404 Not Found</h1></center>
<hr><center>nginx</center>
</body>
</html>
```

본문 끝의 `<center>nginx</center>` 가 결정적 증거입니다 — 이 404 는 백엔드 FastAPI 가 아니라 **ingress-nginx-controller** 가 직접 돌려준 것입니다 (등록된 어느 path 룰에도 매칭되지 않음).

### 6-2. path 끝에 슬래시가 빠진 호출 — 본 ingress 는 동작 (정규식이 / 와 끝 모두 허용)

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/v1/sentiment
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/v1/sentiment/
curl -s -o /dev/null -w "%{http_code}\n" http://localhost/v1/sentiment/ready
```

```
# 예상 출력
200
200
200
```

본 [`ingress.yaml`](../manifests/ingress.yaml) 의 path 정규식 `/v1/sentiment(/|$)(.*)` 가 trailing slash 가 있든 없든 매칭되도록 작성됐기 때문입니다. `pathType: Exact` + 단순 `path: /v1/sentiment` 였다면 `/v1/sentiment/` 는 404 가 났을 것입니다 (lesson.md 1-4 표 함정).

### 6-3. (선택) 잘못된 Host 헤더 — 본 ingress 는 host 비웠으므로 동작

```bash
curl -s -H "Host: wrong.example.com" -o /dev/null -w "%{http_code}\n" http://localhost/v1/sentiment/ready
```

```
# 예상 출력
200
```

본 ingress 의 `rules[0].host` 를 비워뒀기 때문에 모든 호스트가 매칭됩니다. 운영에서 호스트별 라우팅을 하려면 host 를 명시해야 하며 (lesson.md 1-5), 그 경우 위 호출은 404 가 됩니다.

### 6-4. (선택) timeout 시뮬 — annotation 의 효과 체감

`proxy-read-timeout` annotation 의 효과를 실험으로 확인하려면, 아래처럼 annotation 을 일시적으로 짧게 줄여 보고 (별도 파일로 저장 권장) 첫 추론 호출이 504 로 떨어지는지 봅니다.

```bash
# 실험: timeout 을 1초로 줄임 (학습용 — 실제 사용 X)
kubectl annotate ingress sentiment-api \
  nginx.ingress.kubernetes.io/proxy-read-timeout=1 --overwrite

# 첫 추론 호출 (모델이 느리게 응답하면 504 발생)
curl -i -X POST http://localhost/v1/sentiment/predict \
  -H 'Content-Type: application/json' \
  -d '{"text":"timeout test"}'

# 예상 출력 (504 또는 정상 응답 — 환경에 따라 다름)
# HTTP/1.1 504 Gateway Time-out  ... 또는
# HTTP/1.1 200 OK ...

# 원복
kubectl annotate ingress sentiment-api \
  nginx.ingress.kubernetes.io/proxy-read-timeout=120 --overwrite
```

---

## 7단계 — Controller Access Log 와 Sync 이벤트 직접 보기

### 7-1. Controller Pod 의 access log 확인

```bash
CTRL_POD=$(kubectl get pod -n ingress-nginx \
  -l app.kubernetes.io/component=controller \
  -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n ingress-nginx $CTRL_POD --tail=20
```

```
# 예상 출력 (5–6 단계의 호출이 한 줄씩 보임)
192.168.49.1 - - [...] "GET /v1/sentiment/ready HTTP/1.1" 200 95 "-" "curl/8.5.0" 117 0.012 [default-sentiment-api-80] [] 10.244.0.5:8000 95 0.012 200 ...
192.168.49.1 - - [...] "POST /v1/sentiment/predict HTTP/1.1" 200 56 "-" "curl/8.5.0" 215 0.234 [default-sentiment-api-80] [] 10.244.0.6:8000 56 0.234 200 ...
192.168.49.1 - - [...] "GET /v2/sentiment/ready HTTP/1.1" 404 146 "-" "curl/8.5.0" ...
```

각 줄의 `[default-sentiment-api-80]` 가 어느 Service 로 보냈는지, `10.244.0.5:8000` / `10.244.0.6:8000` 이 어느 Pod IP 로 갔는지를 보여 줍니다. **두 호출이 다른 Pod IP 로 분산되면 ingress 가 두 replica 사이에서 라운드로빈하고 있는 것** 입니다.

### 7-2. Ingress 의 Events 확인

```bash
kubectl describe ingress sentiment-api | grep -A5 Events:
```

```
# 예상 출력
Events:
  Type    Reason  Age   From                      Message
  ----    ------  ----  ----                      -------
  Normal  Sync    5m    nginx-ingress-controller  Scheduled for sync
  Normal  Sync    2m    nginx-ingress-controller  Scheduled for sync     ← annotation 변경 시 추가
```

`Normal Sync` 이벤트가 controller 가 본 리소스를 보고 nginx.conf 를 재생성·reload 한 시점입니다. annotation 을 바꿀 때마다 새 Sync 가 추가됩니다.

---

## 8단계 — 정리

본 토픽에서 만든 리소스를 단계별로 삭제합니다. **Ingress 의 라이프사이클이 Service / Pod / PVC 와 분리됨을 인식하기 위함입니다.**

### 8-1. 1차 정리 — Ingress 만 삭제

```bash
kubectl delete -f manifests/ingress.yaml --ignore-not-found
```

```
# 예상 출력
ingress.networking.k8s.io "sentiment-api" deleted
```

### 8-2. Service / Pod / PVC 가 여전히 살아있음 확인

```bash
kubectl get svc,pod,pvc -l app=sentiment-api
```

```
# 예상 출력
NAME                    TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
service/sentiment-api   ClusterIP   10.96.x.x       <none>        80/TCP    20m

NAME                                 READY   STATUS    RESTARTS   AGE
pod/sentiment-api-7c4d8f5c9b-mnop3   1/1     Running   0          20m
pod/sentiment-api-7c4d8f5c9b-qrst4   1/1     Running   0          20m

NAME                                STATUS   VOLUME ...                       CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache   Bound    pvc-...                          2Gi        RWO            standard       1h
```

**Ingress 가 사라져도 백엔드는 그대로 살아있습니다.** Ingress 는 라우팅 규칙 선언일 뿐, 실제 서비스를 죽이지 않습니다. 외부 호출은 안 되지만 클러스터 내부 호출 (3단계 baseline 방식) 은 여전히 동작합니다.

### 8-3. 2차 정리 — Deployment / Service / ConfigMap / Secret

```bash
kubectl delete -f manifests/deployment.yaml \
                -f manifests/service.yaml \
                -f manifests/configmap.yaml \
                -f manifests/secret.yaml \
                --ignore-not-found
```

```
# 예상 출력
deployment.apps "sentiment-api" deleted
service "sentiment-api" deleted
configmap "sentiment-api-config" deleted
secret "sentiment-api-secrets" deleted
```

### 8-4. PVC 처리 (다음 04-job-cronjob 에서 재사용 권장)

다음 토픽 04-job-cronjob 도 같은 모델로 배치 추론을 수행하므로 PVC 의 모델 캐시를 그대로 두는 것이 시간 절약입니다.

```bash
# PVC 그대로 두기 — 다음 토픽이 첫 다운로드를 스킵
kubectl get pvc model-cache

# 또는 명시적으로 비우려면
# kubectl delete pvc model-cache
```

### 8-5. tunnel / port-forward 종료

5단계에서 띄운 터미널에서 `Ctrl+C` 로 종료합니다.

```
# tunnel 종료 시 예상 출력
✋  Stopping tunnel for service sentiment-api.
```

### 8-6. minikube 종료

```bash
# minikube 와 sentiment-api:v1 이미지, ingress addon 은 다음 토픽에서도 그대로 재사용하므로 stop 만 합니다.
minikube stop
```

---

## 검증 체크리스트

다음 항목을 모두 확인했다면 본 lab 을 마쳤다고 볼 수 있습니다.

- [ ] **1-3 단계**: `kubectl get pods -n ingress-nginx` 가 controller Pod 를 1/1 Running 으로 표시.
- [ ] **2-2 단계**: `kubectl rollout status deployment/sentiment-api` 가 successfully rolled out 으로 종료.
- [ ] **3 단계**: ClusterIP baseline 호출이 `version: "v1-ingress"` 응답.
- [ ] **4-2 단계**: `kubectl get ingress sentiment-api` 의 ADDRESS 컬럼에 IP 가 채워짐.
- [ ] **4-3 단계**: `kubectl describe ingress` 의 Backends 에 Pod IP 두 개가 보이고 Events 에 `Normal Sync` 이벤트.
- [ ] **5-A-2 또는 5-B-2 단계**: 외부 `curl http://localhost/v1/sentiment/predict` 가 모델 분류 결과 응답.
- [ ] **6-1 단계**: 잘못된 path 호출이 `404 Not Found` + `<center>nginx</center>` 응답 (controller 가 직접 돌려줌).
- [ ] **7-1 단계**: controller Pod 의 access log 에 본인이 호출한 라인이 남아있음.
- [ ] **8-2 단계**: Ingress 삭제 후에도 Service / Pod / PVC 가 살아있음을 직접 관찰.

체크리스트가 모두 채워졌다면 [docs/course-plan.md](../../../../docs/course-plan.md) 의 Phase 2/03 항목 `minikube 검증` 박스를 `[x]` 로 업데이트합니다.
