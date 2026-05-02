# Lab — minikube 기동과 첫 Pod 배포

이 실습은 [lesson.md](../lesson.md)의 내용을 그대로 따라 **WSL2 + Docker Desktop** 환경에서 minikube 클러스터를 띄우고, 학습용 Pod 하나를 매니페스트로 배포합니다.

> 모든 명령은 본 디렉토리의 부모(`01-cluster-setup/`)를 기준으로 합니다. 첫 `minikube start`는 K8s 노드 이미지(약 1GB)를 받느라 3–5분 걸릴 수 있습니다.

## 0단계 — 사전 준비

세 도구가 모두 설치되어 있는지 확인합니다.

```bash
docker --version
kubectl version --client
minikube version
```

**예상 출력 (버전은 더 높아도 OK)**

```
Docker version 24.0.7, build afdd53b
Client Version: v1.29.0
Kustomize Version: v5.0.4-0.20230601165947-6ce0bf390ce3
minikube version: v1.32.0
commit: 8220a6eb95f0a4d75f7f2d7b14cef975f050512d
```

설치가 안 되어 있다면 다음 한 줄씩으로 채웁니다.

| 도구 | WSL2 / Ubuntu 설치 명령 |
|------|------------------------|
| Docker | Docker Desktop 설치 후 **Settings → Resources → WSL Integration**에서 사용 중인 배포판 토글 켜기 |
| kubectl | `curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl` |
| minikube | `curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64 && sudo install minikube-linux-amd64 /usr/local/bin/minikube` |

> 💡 **팁**: Docker Desktop의 WSL Integration이 켜져 있는지 확인하려면 WSL 안에서 `docker ps`가 권한 에러 없이 즉시 응답하는지 보면 됩니다.

## 1단계 — minikube 기동

```bash
minikube start --driver=docker --memory=4g --cpus=2
```

**예상 출력 (요약)**

```
😄  minikube v1.32.0 on Ubuntu 22.04 (amd64)
✨  Using the docker driver based on user configuration
👍  Starting control plane node minikube in cluster minikube
🚜  Pulling base image ...
🔥  Creating docker container (CPUs=2, Memory=4096MB) ...
🐳  Preparing Kubernetes v1.28.3 on Docker 24.0.7 ...
🔎  Verifying Kubernetes components...
🌟  Enabled addons: storage-provisioner, default-storageclass
🏄  Done! kubectl is now configured to use "minikube" cluster and "default" namespace by default
```

마지막 줄의 "kubectl is now configured to use **minikube** cluster" 메시지를 확인합니다. 이게 안 보이면 자주 하는 실수 1번(WSL Integration)이나 2번(이전 프로파일 잔재)을 보세요.

## 2단계 — 클러스터 상태 확인

```bash
minikube status
kubectl cluster-info
kubectl get nodes -o wide
```

**예상 출력 — `minikube status`**

```
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

**예상 출력 — `kubectl cluster-info`**

```
Kubernetes control plane is running at https://127.0.0.1:32771
CoreDNS is running at https://127.0.0.1:32771/api/v1/namespaces/kube-system/services/kube-dns:dns/proxy
```

**예상 출력 — `kubectl get nodes -o wide`**

```
NAME       STATUS   ROLES           AGE   VERSION   INTERNAL-IP   EXTERNAL-IP   OS-IMAGE             KERNEL-VERSION   CONTAINER-RUNTIME
minikube   Ready    control-plane   2m    v1.28.3   192.168.49.2  <none>        Ubuntu 22.04.3 LTS   6.6.x-microsoft  docker://24.0.7
```

`STATUS=Ready` 한 줄이 보이면 클러스터는 사용할 준비가 됐습니다. minikube는 단일 노드라 `ROLES`에 `control-plane`만 표시됩니다.

## 3단계 — kubeconfig·context 둘러보기

kubectl이 어느 클러스터를 가리키는지 확인합니다.

```bash
kubectl config current-context
kubectl config view --minify
```

**예상 출력 — `current-context`**

```
minikube
```

**예상 출력 — `view --minify` (요약)**

```yaml
apiVersion: v1
clusters:
- cluster:
    server: https://127.0.0.1:32771
  name: minikube
contexts:
- context:
    cluster: minikube
    namespace: default
    user: minikube
  name: minikube
current-context: minikube
```

namespace는 비워 두면 `default`입니다. 다음 명령으로 namespace 목록을 봅니다.

```bash
kubectl get namespaces
```

**예상 출력**

```
NAME              STATUS   AGE
default           Active   3m
kube-node-lease   Active   3m
kube-public       Active   3m
kube-system       Active   3m
```

`kube-*`로 시작하는 것은 K8s 시스템 컴포넌트가 쓰는 namespace이므로 학습 단계에서는 건드리지 않습니다. 우리 Pod은 `default`에 들어갑니다.

> 💡 **팁**: 회사 클러스터를 쓰던 머신이라면 `current-context`가 다른 값을 보일 수 있습니다. 그러면 `kubectl config use-context minikube`로 전환합니다.

## 4단계 — 첫 Pod 배포

매니페스트를 적용 전에 한 번 dry-run으로 검증합니다. 이 습관을 들이면 production에서 사고가 줄어듭니다.

```bash
kubectl apply --dry-run=client -f manifests/first-pod.yaml
```

**예상 출력**

```
pod/first-pod created (dry run)
```

이제 실제로 적용합니다.

```bash
kubectl apply -f manifests/first-pod.yaml
```

**예상 출력**

```
pod/first-pod created
```

Pod이 `Pending → ContainerCreating → Running`으로 진행되는 모습을 실시간으로 봅니다.

```bash
kubectl get pods -w
```

**예상 출력 (Ctrl+C로 종료)**

```
NAME        READY   STATUS              RESTARTS   AGE
first-pod   0/1     ContainerCreating   0          3s
first-pod   1/1     Running             0          12s
```

첫 실행에서는 `python:3.12-slim` 이미지를 받느라 10–30초가 걸릴 수 있습니다. `READY=1/1`과 `STATUS=Running`이 같이 보이면 성공입니다.

## 5단계 — Pod 진단 4종 셋

이 4개 명령은 Phase 4까지 진단의 거의 전부입니다. 손에 익혀 두면 좋습니다.

### 5-1. `kubectl get` — 한 줄 상태

```bash
kubectl get pod first-pod
kubectl get pod first-pod -o wide        # 노드·IP까지
```

**예상 출력**

```
NAME        READY   STATUS    RESTARTS   AGE
first-pod   1/1     Running   0          1m
```

### 5-2. `kubectl describe` — 상세 + Events

```bash
kubectl describe pod first-pod
```

**예상 출력 (요약)**

```
Name:         first-pod
Namespace:    default
Node:         minikube/192.168.49.2
Status:       Running
IP:           10.244.0.5
Containers:
  hello:
    Image:          python:3.12-slim
    State:          Running
    Ready:          True
    Restart Count:  0
    Limits:
      cpu:     200m
      memory:  128Mi
    Requests:
      cpu:        50m
      memory:     64Mi
Events:
  Type    Reason     Age   From               Message
  ----    ------     ----  ----               -------
  Normal  Scheduled  1m    default-scheduler  Successfully assigned default/first-pod to minikube
  Normal  Pulling    1m    kubelet            Pulling image "python:3.12-slim"
  Normal  Pulled     50s   kubelet            Successfully pulled image
  Normal  Created    50s   kubelet            Created container hello
  Normal  Started    50s   kubelet            Started container hello
```

`Events` 섹션이 디버깅 핵심입니다. 시간 순으로 무슨 일이 있었는지 그대로 보입니다.

### 5-3. `kubectl logs` — 컨테이너 stdout

```bash
kubectl logs first-pod
```

**예상 출력**

```
[ML] hello from K8s — Phase 1 / 01-cluster-setup
[ML] 이 자리는 04-serve-classification-model에서 sentiment-api 컨테이너로 교체됩니다.
```

매니페스트의 `args`에 적은 `echo` 두 줄이 그대로 보이면 정상입니다. `kubectl logs first-pod -f`는 follow 모드로 실시간 로그를 봅니다 (이 Pod은 sleep 중이라 더 출력은 없습니다).

### 5-4. `kubectl exec` — 컨테이너 진입

```bash
kubectl exec -it first-pod -- sh
```

진입 후 다음을 실행해 봅니다.

```sh
python --version
ls /
exit
```

**예상 출력**

```
Python 3.12.x
bin   dev  home  lib64  mnt  proc  run   srv  tmp  var
boot  etc  lib   media  opt  root  sbin  sys  usr
```

`exit`로 빠져나오면 호스트 셸로 돌아옵니다. 컨테이너 안의 파일 시스템·프로세스가 호스트와 분리되어 있다는 사실을 직접 확인할 수 있습니다.

### 5-5. (선택) Pod의 실제 상태 보기

```bash
kubectl get pod first-pod -o yaml | head -40
```

`status` 필드가 K8s가 채운 실제 상태입니다. `spec`(우리가 적은 desired state)과 비교해 보면 어떤 필드가 자동으로 채워지는지(`nodeName`, `podIP`, `containerStatuses` 등) 감이 옵니다.

## 6단계 — 정리

```bash
kubectl delete -f manifests/first-pod.yaml
```

**예상 출력**

```
pod "first-pod" deleted
```

minikube는 다음 토픽에서도 그대로 쓰므로 **삭제(delete)가 아닌 정지(stop)** 만 합니다.

```bash
minikube stop
```

다음 토픽에서 `minikube start`만 하면 같은 클러스터가 다시 살아납니다. 만약 클러스터를 완전히 지워야 한다면 `minikube delete`를 씁니다 (이후 `minikube start`가 처음부터 다시 시작됩니다).

## 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `minikube start`가 `Cannot connect to the Docker daemon`으로 실패 | Docker Desktop의 WSL Integration이 꺼져 있음 | Docker Desktop → Settings → Resources → WSL Integration에서 사용 중인 배포판 토글을 켭니다. |
| `Existing "minikube" cluster was created using a different driver` 경고 후 시작 실패 | 이전에 `kvm2`/`virtualbox` 등 다른 드라이버로 만든 프로파일이 남음 | `minikube delete` 후 `minikube start --driver=docker` 다시 실행. 학습용이라 데이터 손실 안전합니다. |
| `kubectl get nodes`가 회사 클러스터 노드를 보여줌 | `current-context`가 사내 클러스터를 가리킴 | `kubectl config use-context minikube`로 전환. minikube 시작 시 자동 전환되지 않을 때가 있습니다. |
| Pod이 `ContainerCreating`에서 1–2분 이상 멈춤 | `python:3.12-slim` 이미지 다운로드가 느림 | `kubectl describe pod first-pod`의 Events 섹션에서 `Pulling image`가 보이는지 확인합니다. 네트워크 지연이면 그대로 기다립니다. |
| Pod이 `ImagePullBackOff` | 이미지 이름 오타 또는 네트워크 차단 | `kubectl describe pod first-pod`의 Events 메시지를 정확히 읽고, 이미지 이름과 태그를 매니페스트에서 다시 확인합니다. |

## 다음 단계

이 토픽을 끝냈으면 [02-pod-deployment](../../02-pod-deployment/lesson.md)로 이동해 ReplicaSet과 Deployment가 어떻게 Pod을 자동 복구·롤링 업데이트하는지 학습합니다.
