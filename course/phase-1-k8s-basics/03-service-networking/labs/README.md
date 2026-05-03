# Labs — Service 3종, DNS, port-forward, Endpoints 동적 갱신

> 본 labs는 [lesson.md](../lesson.md)의 7단계 흐름을 손으로 검증하는 절차입니다.
> 각 단계의 **예상 출력**은 본인 환경 결과와 비교용입니다(Pod IP·NodeIP·시간 같은 가변 값은 다를 수 있음).

## 0단계 — 사전 준비

### 0-1. kubectl context가 minikube를 가리키는지 확인

```bash
kubectl config current-context
```

**예상 출력**

```
minikube
```

다른 컨텍스트라면 `kubectl config use-context minikube`로 전환합니다.

### 0-2. minikube가 떠 있는지 확인

```bash
minikube status
```

**예상 출력 (정상 기동)**

```
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

`Stopped`라면 02 토픽 끝에서 stop했기 때문입니다. 02와 동일한 파라미터로 다시 시작합니다.

```bash
minikube start --driver=docker --memory=4g --cpus=2
```

### 0-3. sentiment-api 이미지가 minikube에 보존되어 있는지 확인

```bash
minikube image ls | grep sentiment-api
```

**예상 출력**

```
docker.io/library/sentiment-api:v2
docker.io/library/sentiment-api:v1
```

이미지가 없다면 02 1단계로 돌아가 `minikube image load sentiment-api:v1`을 다시 실행합니다.

### 0-4. CoreDNS가 동작 중인지 확인

```bash
kubectl get pods -n kube-system -l k8s-app=kube-dns
```

**예상 출력**

```
NAME                       READY   STATUS    RESTARTS   AGE
coredns-xxxxxxxxxx-xxxxx   1/1     Running   0          5m
```

`READY 1/1`이어야 3단계의 `nslookup`이 동작합니다.

---

## 1단계 — Deployment 배포 + Pod IP 메모

### 1-1. Deployment 배포

```bash
kubectl apply -f manifests/deployment.yaml
kubectl rollout status deployment/sentiment-api
```

**예상 출력**

```
deployment.apps/sentiment-api created
Waiting for deployment "sentiment-api" rollout to finish: 0 of 2 updated replicas are available...
deployment "sentiment-api" successfully rolled out
```

모델 로드(`/ready` 200 응답)까지 약 30~60초 걸립니다.

### 1-2. Pod IP를 메모해 둡니다 (휘발성 검증용)

```bash
kubectl get pods -l app=sentiment-api -o wide
```

**예상 출력**

```
NAME                             READY   STATUS    RESTARTS   AGE   IP            NODE
sentiment-api-7c8f6d4b9c-abcde   1/1     Running   0          1m    10.244.0.10   minikube
sentiment-api-7c8f6d4b9c-fghij   1/1     Running   0          1m    10.244.0.11   minikube
```

`IP` 컬럼의 두 값을 메모합니다. 7단계에서 이 IP가 바뀌는 것을 확인하기 위함입니다.

> 💡 **포인트**: 이 IP는 어디서도 호출하지 마세요. 직접 호출하지 말아야 한다는 것이 03 토픽의 핵심 주제입니다.

---

## 2단계 — ClusterIP Service 생성 + Endpoints 확인

### 2-1. Service 적용

```bash
kubectl apply -f manifests/service-clusterip.yaml
```

**예상 출력**

```
service/sentiment-api created
```

### 2-2. Service 상태 확인

```bash
kubectl get svc sentiment-api
```

**예상 출력**

```
NAME            TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
sentiment-api   ClusterIP   10.96.123.45    <none>        80/TCP    5s
```

- `TYPE=ClusterIP`: 클러스터 내부 전용
- `EXTERNAL-IP=<none>`: 외부에서 도달 불가 (정상)
- `PORT(S)=80/TCP`: 클라이언트가 보는 Service 포트

`CLUSTER-IP` 값은 환경마다 다릅니다(`10.96.x.y` 대역).

### 2-3. Endpoints 확인 — selector 매칭이 살아 있는지

```bash
kubectl get endpoints sentiment-api
```

**예상 출력**

```
NAME            ENDPOINTS                            AGE
sentiment-api   10.244.0.10:8000,10.244.0.11:8000    10s
```

여기서 보이는 IP들은 1-2단계에서 메모한 Pod IP와 일치해야 합니다. `:8000`은 Deployment의 `containerPort`(=Service `targetPort`)입니다.

> 🚨 **`ENDPOINTS`가 `<none>`이라면**: selector ↔ Pod label 불일치 또는 readinessProbe 실패입니다. `kubectl describe svc sentiment-api`의 `Selector`와 `kubectl get pods --show-labels`를 비교해 매칭 여부를 확인합니다.

---

## 3단계 — 클러스터 내부 DNS로 Service 호출

### 3-1. 디버깅용 client-pod 띄우기

```bash
kubectl apply -f manifests/client-pod.yaml
kubectl wait --for=condition=Ready pod/client --timeout=60s
```

**예상 출력**

```
pod/client created
pod/client condition met
```

### 3-2. client-pod 안으로 들어가 DNS 확인

```bash
kubectl exec -it client -- sh
```

이제 셸 프롬프트가 `/ #` 으로 바뀌었습니다. 이 안에서 다음을 실행합니다.

```sh
nslookup sentiment-api
```

**예상 출력**

```
Server:    10.96.0.10
Address:   10.96.0.10:53

Name:      sentiment-api.default.svc.cluster.local
Address:   10.96.123.45
```

- `Server: 10.96.0.10`: CoreDNS의 ClusterIP (kube-system의 `kube-dns` Service)
- `Name: sentiment-api.default.svc.cluster.local`: 짧은 이름이 search 도메인에 의해 FQDN으로 자동 확장된 결과
- `Address: 10.96.123.45`: 2-2단계에서 본 Service ClusterIP와 일치

### 3-3. 짧은 이름과 FQDN 모두로 호출

```sh
wget -qO- sentiment-api/ready
echo
wget -qO- sentiment-api.default.svc.cluster.local/ready
```

**예상 출력 (두 줄 모두 동일)**

```
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

같은 응답이 나오면 짧은 이름과 FQDN이 같은 Service ClusterIP로 도달함이 확인된 것입니다.

### 3-4. resolv.conf로 search 도메인 들여다보기

```sh
cat /etc/resolv.conf
```

**예상 출력**

```
search default.svc.cluster.local svc.cluster.local cluster.local
nameserver 10.96.0.10
options ndots:5
```

`search` 라인 덕분에 `wget sentiment-api/...` 한 글자만 적어도 K8s가 자동으로 `sentiment-api.default.svc.cluster.local`로 확장해 조회합니다.

```sh
exit
```

호스트 셸로 돌아옵니다.

---

## 4단계 — NodePort Service 생성 + 호스트에서 호출

### 4-1. NodePort Service 적용

```bash
kubectl apply -f manifests/service-nodeport.yaml
kubectl get svc sentiment-api-np
```

**예상 출력**

```
NAME                TYPE       CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
sentiment-api-np    NodePort   10.96.234.56    <none>        80:30080/TCP   5s
```

- `TYPE=NodePort`: 노드 IP의 30080 포트로 외부 도달 가능
- `PORT(S)=80:30080/TCP`: Service 포트 80 ↔ 노드 포트 30080
- ClusterIP도 함께 받습니다(NodePort는 ClusterIP 위에 외부 노출 한 겹을 더한 것)

### 4-2. 호스트에서 직접 호출 (방법 A — `minikube ip`)

```bash
NODE_IP=$(minikube ip)
echo "Node IP: $NODE_IP"
curl http://$NODE_IP:30080/ready
echo
```

**예상 출력**

```
Node IP: 192.168.49.2
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

NodeIP 값(`192.168.49.x` 대역)은 minikube driver 환경에 따라 다릅니다.

### 4-3. POST로 추론 호출

```bash
curl -X POST http://$NODE_IP:30080/predict \
     -H 'Content-Type: application/json' \
     -d '{"text":"K8s networking is fun"}'
echo
```

**예상 출력 (대략)**

```
{"label":"LABEL_2","score":0.91,"version":"v1"}
```

`LABEL_2`는 positive 감정을 의미합니다(모델 정의). `version`이 `v1`인 것은 어느 Pod로 트래픽이 갔는지 식별 가능한 표식입니다.

### 4-4. (방법 B — `minikube service`) Docker driver에서 NODE_IP 직접 호출이 안 될 때

WSL2 + Docker driver 환경에서 4-2의 `curl http://$NODE_IP:30080/...`이 timeout되면, 다음 명령을 별도 셸에서 띄워 두고 출력 URL로 호출합니다.

```bash
minikube service sentiment-api-np --url
```

**예상 출력 (이 셸은 종료하지 말고 그대로 둡니다)**

```
🏃  sentiment-api-np 서비스의 터널을 시작하는 중...
http://127.0.0.1:38421
```

다른 셸에서:

```bash
curl http://127.0.0.1:38421/ready
```

호출이 끝나면 첫 셸에서 Ctrl+C로 터널을 종료합니다.

---

## 5단계 — `kubectl port-forward`로 Service / Pod 직결

### 5-1. Service에 port-forward (셸 1)

새 셸을 하나 열어 다음을 실행합니다(이 셸은 종료하지 마세요).

```bash
kubectl port-forward svc/sentiment-api 8080:80
```

**예상 출력 (셸 점유 상태)**

```
Forwarding from 127.0.0.1:8080 -> 8000
Forwarding from [::1]:8080 -> 8000
```

`8080 -> 8000`이 보이는 이유는 Service가 `port=80, targetPort=8000`으로 설정되어 있고, port-forward는 결국 컨테이너 포트로 도달하기 때문입니다.

### 5-2. 다른 셸(셸 2)에서 호출

```bash
curl localhost:8080/ready
echo
```

**예상 출력**

```
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

### 5-3. 셸 1을 Ctrl+C로 종료한 뒤 다시 호출

셸 1에서 `Ctrl+C`를 눌러 port-forward를 종료한 직후, 셸 2에서 다시 호출합니다.

```bash
curl localhost:8080/ready
```

**예상 출력**

```
curl: (7) Failed to connect to localhost port 8080 after 0 ms: Connection refused
```

→ port-forward는 kubectl 세션과 운명을 같이 합니다. **Service의 대안이 아니라 디버깅용 직결 통로**라는 의미가 이 한 번의 실험으로 확인됩니다.

### 5-4. (참고) Pod 직결 port-forward

특정 Pod만 들여다보고 싶다면 svc 대신 pod로 지정합니다.

```bash
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
kubectl port-forward pod/$POD 8081:8000
# 다른 셸:
curl localhost:8081/ready
```

이건 Service의 selector를 의심하거나, 로드 밸런싱에 묻혀 있는 단일 Pod의 응답을 격리해 보고 싶을 때 쓰는 워크플로입니다. 끝나면 Ctrl+C.

---

## 6단계 — LoadBalancer + `minikube tunnel`

### 6-1. LoadBalancer Service 적용

```bash
kubectl apply -f manifests/service-loadbalancer.yaml
kubectl get svc sentiment-api-lb
```

**예상 출력 (즉시 확인 시)**

```
NAME                TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
sentiment-api-lb    LoadBalancer   10.96.55.66     <pending>     80:31234/TCP   3s
```

`EXTERNAL-IP=<pending>`이 정상적인 시작 상태입니다. 클라우드라면 곧 자동으로 채워지지만, minikube는 별도 도움이 필요합니다.

### 6-2. 별도 셸에서 `minikube tunnel` 실행

새 셸을 열어 다음을 실행하고 **그대로 둡니다**.

```bash
minikube tunnel
```

**예상 출력 (셸 점유 상태)**

```
✅  터널이 성공적으로 시작되었습니다.

📌  주의 사항: 모든 트래픽을 로컬 컴퓨터에서 사용 가능한 LoadBalancer 서비스로 전달하려면 이 프로세스를 계속 실행해야 합니다.
...
```

macOS나 일부 Linux에서는 sudo 비밀번호를 요구할 수 있습니다(WSL2는 보통 요구하지 않음).

### 6-3. 원래 셸에서 EXTERNAL-IP 부여 확인

```bash
kubectl get svc sentiment-api-lb
```

**예상 출력**

```
NAME                TYPE           CLUSTER-IP      EXTERNAL-IP   PORT(S)        AGE
sentiment-api-lb    LoadBalancer   10.96.55.66     127.0.0.1     80:31234/TCP   1m
```

WSL2 + Docker driver는 EXTERNAL-IP가 보통 `127.0.0.1`로 부여됩니다.

### 6-4. EXTERNAL-IP로 호출

```bash
curl http://127.0.0.1/ready    # 또는 curl http://<EXTERNAL-IP>/ready
echo
```

**예상 출력**

```
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

확인이 끝나면 `minikube tunnel`을 띄운 별도 셸에서 Ctrl+C로 종료합니다(이 단계 이후 EXTERNAL-IP는 다시 `<pending>`으로 돌아갑니다).

---

## 7단계 — Endpoints 동적 갱신 관찰 (Service의 본질)

본 단계가 03 토픽의 핵심 시연입니다. **Pod IP는 바뀌어도 Service IP/DNS는 변하지 않는다**는 것을 자기 눈으로 확인합니다.

### 7-1. 셸 A — Endpoints 실시간 관찰

```bash
kubectl get endpoints sentiment-api -w
```

**예상 출력 (이 셸은 그대로 두고 다음 단계로)**

```
NAME            ENDPOINTS                            AGE
sentiment-api   10.244.0.10:8000,10.244.0.11:8000    5m
```

### 7-2. 셸 B — Pod 1개 강제 삭제

```bash
POD=$(kubectl get pod -l app=sentiment-api -o jsonpath='{.items[0].metadata.name}')
echo "삭제 대상 Pod: $POD"
echo "삭제 대상 IP : $(kubectl get pod $POD -o jsonpath='{.status.podIP}')"
kubectl delete pod $POD
```

**예상 출력**

```
삭제 대상 Pod: sentiment-api-7c8f6d4b9c-abcde
삭제 대상 IP : 10.244.0.10
pod "sentiment-api-7c8f6d4b9c-abcde" deleted
```

### 7-3. 셸 A의 변화 관찰

셸 A의 `kubectl get endpoints -w` 출력에 다음과 같은 변화가 자동으로 추가됩니다.

```
NAME            ENDPOINTS                            AGE
sentiment-api   10.244.0.10:8000,10.244.0.11:8000    5m
sentiment-api   10.244.0.11:8000                     6m   ← 삭제 직후 한 IP만 남음
sentiment-api   10.244.0.11:8000,10.244.0.12:8000    6m   ← ReplicaSet이 새 Pod을 띄우면 IP 자동 등록
```

→ Pod IP가 `10.244.0.10` → `10.244.0.12`로 바뀐 것을 Endpoints가 즉시 반영했습니다. 셸 A를 Ctrl+C로 종료합니다.

### 7-4. Service ClusterIP는 그대로임을 확인

```bash
kubectl get svc sentiment-api
```

**예상 출력**

```
NAME            TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)   AGE
sentiment-api   ClusterIP   10.96.123.45    <none>        80/TCP    10m
```

`CLUSTER-IP=10.96.123.45`는 2-2단계와 동일합니다. Pod이 죽었다 살아도 클라이언트가 보는 엔드포인트는 변하지 않습니다 — 이것이 03 토픽의 한 줄 요약입니다.

### 7-5. (선택) client-pod에서 다시 호출해 정상임을 재확인

```bash
kubectl exec client -- wget -qO- sentiment-api/ready
echo
```

**예상 출력**

```
{"status":"ready","model":"cardiffnlp/twitter-roberta-base-sentiment","version":"v1"}
```

새로 뜬 Pod의 IP를 우리는 모르지만, Service 이름으로 호출했기 때문에 정상 도달합니다.

---

## 8단계 — 정리

```bash
# 셸 A의 watch / 셸 1·6의 port-forward / minikube tunnel 등 점유 셸은 모두 Ctrl+C로 종료
kubectl delete -f manifests/client-pod.yaml --ignore-not-found
kubectl delete -f manifests/service-loadbalancer.yaml --ignore-not-found
kubectl delete -f manifests/service-nodeport.yaml --ignore-not-found
kubectl delete -f manifests/service-clusterip.yaml --ignore-not-found
kubectl delete -f manifests/deployment.yaml --ignore-not-found

# 다음 토픽(04-serve-classification-model)에서도 동일 클러스터를 사용하므로 stop만 합니다
minikube stop
```

이미지(`sentiment-api:v1`)는 04에서 그대로 재사용하므로 `minikube image rm` 하지 않습니다.

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `kubectl get endpoints <svc>`가 `<none>` | selector ↔ Pod label 불일치 또는 readinessProbe 실패로 모든 Pod이 NotReady | `kubectl describe svc <svc>`의 Selector와 `kubectl get pods --show-labels`를 비교. probe 실패라면 `kubectl describe pod <pod>` Events 확인. |
| client-pod 안 `wget: bad address 'sentiment-api'` | client-pod이 다른 ns에 있거나, Service가 아직 생성 전 | `kubectl get pod client -o jsonpath='{.metadata.namespace}'`로 ns 확인. 다른 ns면 FQDN(`sentiment-api.<ns>.svc.cluster.local`) 사용. |
| `curl $(minikube ip):30080`이 timeout (NodePort) | Docker driver / WSL2에서 minikube IP 도달 불가 | `minikube service sentiment-api-np --url`을 별도 셸에서 띄워 출력 URL로 호출 (4-4). |
| LoadBalancer EXTERNAL-IP가 5분 넘게 `<pending>` | 별도 셸의 `minikube tunnel` 미실행 | 새 셸에서 `minikube tunnel` 실행 후 셸 유지. 클라우드(GKE/EKS)에서는 자동 부여되므로 학습용 차이임을 인지. |
| `minikube tunnel` 실행 시 sudo 비밀번호 요구 후 종료 | macOS / 일부 Linux 권한 정책 (route 추가에 root 필요) | 비밀번호 입력 후 셸 유지. WSL2는 보통 비밀번호 없이 동작. |
| `kubectl port-forward`가 즉시 끊김 | 대상 Pod이 NotReady거나 컨테이너 포트가 다름 | `kubectl get pod <pod> -o jsonpath='{.status.containerStatuses[0].ready}'` 확인. Pod 직결 port-forward로 컨테이너 포트(8000) 직접 지정해 격리 시도. |

## 다음 단계

이 토픽을 끝냈으면 [04-serve-classification-model](../../04-serve-classification-model/lesson.md)으로 이동해, 03에서 익힌 ClusterIP Service를 02 Deployment에 그대로 얹어 분류 모델을 K8s에 정식으로 올리고, Pod 강제 종료 후에도 자동 복구되며 외부 호출이 끊기지 않는지를 종단 검증합니다.
