# Day 6 — RAG API 클러스터 배포 + Ingress

> **상위 lesson**: [`../lesson.md`](../lesson.md) §3.1 챗봇 호출 흐름(Day 6 Ingress 경로), §4.4 RAG API Deployment, §4.5 Ingress
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 6
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §3.11 Ingress 라우팅 결정 노트
> **이전 단계**: [`day-05-rag-api-impl.md`](day-05-rag-api-impl.md)
> **소요 시간**: 2 ~ 3 시간 (이미지 빌드/푸시 15 분, Deployment 적용/Ready 대기 5~10 분, Ingress 적용/IP 부여 3~5 분, 검증 30 분, 정리 5 분)

---

## 🎯 Goal

Day 6 을 마치면 다음 4 가지가 충족됩니다.

- Day 5 에서 작성한 `practice/rag_app/` 4 모듈을 **Docker Hub 본인 계정으로 빌드/푸시**해 클러스터 외부 레지스트리에 이미지를 둡니다 (Day 3 의 `rag-indexer` 이미지와 동일 패턴 — 학습 일관성).
- **Deployment 30 (replicas=2) + Service 31** 적용 후 `kubectl rollout status` 로 Pod READY=2/2 + Service ClusterIP 가 내부 호출(`/healthz`) 에 200 응답.
- **GCE Ingress 40** 적용 후 외부 IP 부여 대기(3~5 분) → `<EXTERNAL_IP>.nip.io` 호스트로 sed 치환 → `/chat` end-to-end 호출 200 OK.
- 캡스톤 §3 검증 시나리오의 **1 줄 완료 기준**(`curl http://<ingress-host>/chat ... → 200 + sources 3 개 + 인용 마커 [n]`) 이 *처음 통과* 합니다 — Day 7~10 의 모든 작업이 본 동작 상태를 전제로 합니다.

---

## 🔧 사전 조건

- **Day 5 완료**: `practice/rag_app/` 6 모듈(`Dockerfile`, `requirements.txt`, `main.py`, `retriever.py`, `llm_client.py`, `prompts.py`) + tests 통과 + `.env.example` 작성.
  ```bash
  ls course/capstone-rag-llm-serving/practice/rag_app/
  # → Dockerfile  llm_client.py  main.py  prompts.py  requirements.txt  retriever.py  tests/  .env.example
  cd course/capstone-rag-llm-serving/practice/rag_app && pytest tests/ -q && cd -
  # → 6 passed
  ```
- **Day 4 vLLM Running**: vLLM Pod 가 ready 이고 OpenAI 호환 API 가 응답.
  ```bash
  kubectl get pod -n rag-llm -l app=vllm
  # → vllm-xxx   1/1   Running   ...
  ```
- **Day 1 Qdrant Running + Day 3 인덱싱 완료**: 컬렉션 `rag-docs` 의 `points_count > 0`.
  ```bash
  kubectl get pod qdrant-0 -n rag-llm
  # → qdrant-0   1/1   Running   ...
  kubectl port-forward -n rag-llm svc/qdrant 6333:6333 &
  curl -s http://localhost:6333/collections/rag-docs | jq '.result.points_count'
  # → 500~800 정도 (Day 3 Workflow 결과)
  kill %1
  ```
- **Docker Hub 계정**: [Docker Hub](https://hub.docker.com/signup) 에서 무료 계정 생성. 로그인용 Personal Access Token 발급([Account Settings > Security](https://hub.docker.com/settings/security)).
- **로컬 도구**: `docker` (또는 `podman`), `kubectl`, `gcloud`, `jq`, `nslookup` (`dig` 도 가능). 본 lab 은 **`docker buildx` 없이** 일반 `docker build` 만 사용합니다.
- **작업 디렉토리**: 본 lab 의 모든 명령은 **프로젝트 루트**(`k8s-for-mle/`) 에서 실행합니다.

> 💰 **GKE LoadBalancer 비용 박스 (꼭 읽기)**
>
> - **GCE Ingress 가 자동 생성하는 forwarding rule + 외부 IP**: 시간당 ≈ \$0.025. Day 6 단독 진행 약 2~3 시간 = **\$0.05~0.08**.
> - **Day 6 → Day 10 5 일 동안 켜두면 약 \$3** — 학습자가 Day 10 후 깜빡 잊으면 한 달 \$20+. 매 Day 끝에 §🧹 정리의 `kubectl delete ingress` 를 *체크박스로* 운영하세요 (자주 하는 실수 ⑱).
> - **Day 7~10 진행 중**: Ingress 는 그대로 두는 것이 자연스럽지만, 휴식 시간이 길면 (반나절 이상) 정리 후 다음 Day 재시작 시 다시 apply (단, 새 외부 IP 가 부여되므로 nip.io host 도 다시 sed 필요).

---

## 🚀 Steps

### Step 1. Day 5 인계 + 사전 상태 확인

Day 6 의 모든 작업은 Qdrant + vLLM + Day 3 인덱싱 결과를 *그대로 사용* 합니다. 한 화면에서 셋의 상태를 확인.

```bash
kubectl get pod,svc -n rag-llm
```

**예상 출력 (Day 1~5 누적 상태)**:

```
NAME             READY   STATUS    RESTARTS   AGE
pod/qdrant-0     1/1     Running   0          5d
pod/vllm-xxx     1/1     Running   0          2d

NAME             TYPE        CLUSTER-IP   EXTERNAL-IP   PORT(S)    AGE
service/qdrant   ClusterIP   None         <none>        6333/TCP   5d
service/vllm     ClusterIP   10.x.x.x     <none>        8000/TCP   2d
```

vLLM 또는 Qdrant 가 Running 이 아니면 Day 4 / Day 1 lab 으로 돌아가 복구 후 진행. Argo controller(Day 3) 는 본 Day 와 무관하므로 suspend 또는 삭제된 상태여도 OK.

### Step 2. RAG API 이미지 빌드 + Docker Hub 푸시

본 캡스톤은 Day 3 인덱싱 이미지(`rag-indexer`) 와 동일 패턴으로 Docker Hub 본인 계정에 이미지를 둡니다. GKE 노드는 public Docker Hub 이미지를 무인증 pull 합니다.

```bash
# 0. Docker Hub 로그인 (PAT 권장 — Step 0 의 Personal Access Token)
docker login -u <YOUR_DOCKERHUB_USER>
# Password: <PAT 붙여넣기>

# 1. 이미지 빌드 (rag-app/ 디렉토리 안에서)
cd course/capstone-rag-llm-serving/practice/rag_app
docker build -t docker.io/<YOUR_DOCKERHUB_USER>/rag-api:0.1.0 .
# 약 3~5 분. 첫 빌드는 base image + pip install 로 5 분 이상 가능.

# 2. 푸시
docker push docker.io/<YOUR_DOCKERHUB_USER>/rag-api:0.1.0

# 3. 작업 디렉토리 복귀
cd -
```

**예상 출력 (`docker push` 마지막 줄)**:

```
0.1.0: digest: sha256:xxxxxxx... size: 2837
```

### Step 3. 매니페스트의 placeholder 치환 (sed)

매니페스트 30 의 `image: docker.io/<user>/rag-api:0.1.0` 의 `<user>` 를 본인 Docker Hub 계정으로 치환합니다.

```bash
# In-place 치환 — macOS 는 sed -i '' / Linux 는 sed -i 차이 주의
DOCKERHUB_USER=<YOUR_DOCKERHUB_USER>
cd course/capstone-rag-llm-serving/manifests

# Linux:
sed -i "s|docker.io/<user>/rag-api:0.1.0|docker.io/${DOCKERHUB_USER}/rag-api:0.1.0|g" 30-rag-api-deployment.yaml

# macOS:
# sed -i '' "s|docker.io/<user>/rag-api:0.1.0|docker.io/${DOCKERHUB_USER}/rag-api:0.1.0|g" 30-rag-api-deployment.yaml

# 확인
grep -n "image:" 30-rag-api-deployment.yaml
# → image: docker.io/myname/rag-api:0.1.0
cd ../../../..
```

> ⚠️ **git diff 주의**: 본 sed 치환은 매니페스트를 *학습자 계정으로 영구 변경* 합니다. 교육용 PR 으로 push 하기 전에 placeholder 로 되돌리세요 (`git checkout 30-rag-api-deployment.yaml` 또는 placeholder 로 reverse sed).

### Step 4. Deployment + Service 적용

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/30-rag-api-deployment.yaml
kubectl apply -f course/capstone-rag-llm-serving/manifests/31-rag-api-service.yaml
```

**예상 출력**:

```
deployment.apps/rag-api created
service/rag-api created
```

### Step 5. Pod READY 대기 (5 분 안)

```bash
kubectl rollout status deploy/rag-api -n rag-llm --timeout=6m
```

**예상 출력 (성공 시)**:

```
Waiting for deployment "rag-api" rollout to finish: 0 of 2 updated replicas are available...
Waiting for deployment "rag-api" rollout to finish: 1 of 2 updated replicas are available...
deployment "rag-api" successfully rolled out
```

첫 기동 시 e5-small 임베딩 모델 130MB 다운로드 + lifespan 초기화로 약 30~120 초. startupProbe failureThreshold=30 (5 분) 안에 ready 가 되어야 정상.

```bash
kubectl get pod -n rag-llm -l app=rag-api
# → rag-api-xxx-yyy   1/1   Running   0   2m
# → rag-api-xxx-zzz   1/1   Running   0   2m  (2 Pod 모두 ready)
```

### Step 6. Service 내부 호출 검증 (Ingress 적용 전)

Ingress 를 거치기 전에 Service 만으로 내부 호출이 동작하는지 확인 — 자주 하는 실수 ⑯ (named port mismatch) 을 미리 차단.

```bash
kubectl run curl --rm -it --image=curlimages/curl --restart=Never -n rag-llm -- \
  curl -sS http://rag-api.rag-llm.svc.cluster.local:8001/healthz
```

**예상 출력**:

```
{"status":"ok"}
pod "curl" deleted
```

`/ready` 도 확인:

```bash
kubectl run curl --rm -it --image=curlimages/curl --restart=Never -n rag-llm -- \
  curl -sS http://rag-api.rag-llm.svc.cluster.local:8001/ready
# → {"status":"ready"}
```

`/ready` 가 503 이면 lifespan 초기화 미완 — Step 5 의 rollout 이 끝나도 5~10 초 추가 대기 필요할 수 있습니다.

### Step 7. Ingress 적용 + 외부 IP 대기 (3~5 분)

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/40-ingress.yaml
```

**예상 출력**:

```
ingress.networking.k8s.io/rag-api created
```

GCE controller 가 LoadBalancer + forwarding rule + health check 를 비동기로 생성합니다. 외부 IP 부여까지 약 3~5 분.

```bash
kubectl get ingress rag-api -n rag-llm -w
```

**예상 출력 (시간이 흐르며 변화)**:

```
NAME      CLASS    HOSTS                  ADDRESS         PORTS   AGE
rag-api   <none>   <EXTERNAL_IP>.nip.io                   80      30s
rag-api   <none>   <EXTERNAL_IP>.nip.io                   80      2m
rag-api   <none>   <EXTERNAL_IP>.nip.io   34.123.45.67    80      4m   ← ADDRESS 부여
```

ADDRESS 가 채워지면 Ctrl+C 로 watch 종료.

### Step 8. nip.io host 치환 + DNS 해석 확인

placeholder `<EXTERNAL_IP>.nip.io` 를 실제 IP 로 치환합니다.

```bash
INGRESS_IP=$(kubectl get ingress rag-api -n rag-llm -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
HOST="${INGRESS_IP}.nip.io"
echo "Ingress IP: ${INGRESS_IP}, Host: ${HOST}"

# 매니페스트에 sed 치환 (재배포 시 자동 매칭되도록)
sed -i "s|<EXTERNAL_IP>.nip.io|${HOST}|g" course/capstone-rag-llm-serving/manifests/40-ingress.yaml
# macOS: sed -i '' "..."

# DNS 해석 동작 확인
nslookup "${HOST}" | grep "Address:"
```

**예상 출력**:

```
Ingress IP: 34.123.45.67, Host: 34.123.45.67.nip.io
Address: 34.123.45.67           ← nip.io 가 IP 그대로 해석
```

### Step 9. `/chat` end-to-end 호출

캡스톤 §3 의 1 줄 완료 기준 호출.

```bash
curl -sS http://${HOST}/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' | jq
```

**예상 출력 (JSON 일부 발췌)**:

```json
{
  "answer": "Kubernetes 에서 GPU 자원을 잡으려면 다음 세 가지가 필요합니다 [1]. ...",
  "sources": [
    {
      "source": "course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md",
      "phase": "phase-4-ml-on-k8s",
      "topic": "03-vllm-llm-serving",
      "heading": "Phase 4 > vLLM > GPU 자원 요청",
      "score": 0.81,
      "chunk_id": "..."
    },
    { "...": "..." },
    { "...": "..." }
  ]
}
```

`answer` 에 `[1]` `[2]` `[3]` 인용 마커가 등장하고 `sources` 가 본 코스 자료(`course/phase-*` 경로) 를 가리켜야 *자기참조형 검증* 통과 — 캡스톤 plan §10 품질 체크리스트의 핵심 항목입니다.

> ⚠️ **첫 호출이 504 일 경우**: GCE Ingress 의 default timeout 30 초를 vLLM cold start 가 넘기는 경우입니다. 30~60 초 후 두 번째 호출 시도 → vLLM warm 상태에서 1~3 초 안에 응답. 본 timeout 의 본격 해결은 Day 8 의 BackendConfig CRD (lesson.md §4.5 결정 박스 ③ 참조).

---

## ✅ 검증 체크리스트

- [ ] `kubectl get deploy/rag-api -n rag-llm` READY=2/2, AVAILABLE=2
- [ ] `kubectl get svc/rag-api -n rag-llm` ClusterIP 부여 + port 8001 + named port `http`
- [ ] `kubectl get ingress rag-api -n rag-llm` ADDRESS 컬럼에 외부 IP 채워짐
- [ ] `nslookup <IP>.nip.io` 가 외부 IP 그대로 해석
- [ ] `curl http://<IP>.nip.io/healthz` → `{"status":"ok"}` 200
- [ ] `curl http://<IP>.nip.io/chat ...` → 200 + answer 텍스트 + sources 3 개
- [ ] `sources[0]` 메타 4 종(source/phase/topic/heading) + score + chunk_id 모두 채워짐
- [ ] `answer` 에 `[1]` `[2]` `[3]` 인용 마커 등장 (한국어 답변 + Context 한정)

---

## 🧹 정리

다음 중 하나를 선택합니다.

**(A) Day 7 즉시 진행** — Ingress + Pod 모두 유지. 다음 Day 의 ConfigMap/Secret 분리가 본 Deployment 30 위에서 진행됩니다. **단, 휴식 시간이 반나절 이상이면 (B) 로 전환** — LoadBalancer 비용 누수 방지.

**(B) Day 6 단독 종료 — Ingress 만 삭제 (비용 절약)**

```bash
kubectl delete ingress rag-api -n rag-llm
# → ingress.networking.k8s.io "rag-api" deleted
# → GCE forwarding rule + 외부 IP 가 5 분 안에 자동 회수
```

Deployment 30 / Service 31 / Pod 은 그대로 두면 다음 Day 시작 시 `kubectl apply -f 40-ingress.yaml` 한 줄로 재시작 (단, 새 외부 IP 가 부여되므로 nip.io host 도 다시 sed 필요).

```bash
# 다음 Day 재시작 시
kubectl apply -f course/capstone-rag-llm-serving/manifests/40-ingress.yaml
# 새 ADDRESS 대기 후 다시 host sed
```

비용 정산 확인 — GCP Console > VPC network > External IP addresses 에서 *In use* 상태 IP 가 사라졌는지 확인.

---

## 🚨 막힐 때 (트러블슈팅)

1. **`docker push` 가 401 Unauthorized** — Step 2-0 의 `docker login` 이 만료됐거나 PAT 가 잘못됐습니다. `cat ~/.docker/config.json | jq '.auths'` 출력에 `https://index.docker.io/v1/` 항목이 있는지 확인. 없으면 `docker login` 재시도.

2. **Pod CrashLoopBackOff — `getaddrinfo: Name or service not known`** — env 의 `QDRANT_URL` / `LLM_BASE_URL` Service 이름 오타. `kubectl logs deploy/rag-api -n rag-llm --tail=20` 로 첫 에러 라인 확인. 매니페스트 30 의 env 6 종을 `course/capstone-rag-llm-serving/manifests/30-rag-api-deployment.yaml` 의 원본과 글자 단위 비교. 자주 빠지는 부분: `qdrant.rag-llm.svc.cluster.local` ↔ `qdrant.rag-llm.svc` (둘 다 동작) vs `qdrant.rag-llm` (X — `.svc` 누락).

3. **Pod CrashLoopBackOff — readiness probe failed (5 분 초과)** — startupProbe failureThreshold=30 (5 분) 을 e5-small 다운로드가 넘긴 경우. 로그 확인:
   ```bash
   kubectl logs deploy/rag-api -n rag-llm --tail=50
   # → Loading embedding model intfloat/multilingual-e5-small
   # → (다운로드 진행 중...)
   ```
   네트워크가 느린 경우 매니페스트의 `failureThreshold: 30` → `60` (10 분) 으로 임시 상향 후 재apply. 자주 하는 실수 ⑰ (Docker Hub rate limit) 도 동시 의심.

4. **`ImagePullBackOff: 429 Too Many Requests`** — Docker Hub anonymous pull rate limit (자주 하는 실수 ⑰). `kubectl describe pod rag-api-xxx -n rag-llm` 의 Events 에 `429` 보이면 즉시 imagePullSecret 추가:
   ```bash
   kubectl create secret docker-registry dockerhub \
     --docker-username=<YOUR> --docker-password=<PAT> -n rag-llm
   # 매니페스트 30 의 spec.template.spec 에 추가:
   #   imagePullSecrets:
   #     - name: dockerhub
   kubectl apply -f course/capstone-rag-llm-serving/manifests/30-rag-api-deployment.yaml
   ```

5. **Ingress ADDRESS 가 5 분 후에도 비어있음** — GKE 클러스터의 외부 IP 할당 권한 또는 Project quota 문제. `kubectl describe ingress rag-api -n rag-llm` 의 Events 에 `Translation failed` / `Quota` 메시지 확인. quota 부족 시 GCP Console > IAM > Quotas 에서 `IN_USE_ADDRESSES` 한도 확인.

6. **`curl /chat` 502 Bad Gateway** — Service 의 named port `http` 미선언 또는 backend 가 unhealthy (자주 하는 실수 ⑯). 두 가지 확인:
   ```bash
   kubectl get svc rag-api -n rag-llm -o jsonpath='{.spec.ports[*].name}'
   # → http (이여야 함. 비어있으면 Service 31 매니페스트의 ports[0].name 확인)

   kubectl describe ingress rag-api -n rag-llm | grep -A 5 "Events:"
   # → "no healthy upstream" 메시지가 있으면 Pod readiness 가 false
   ```

7. **`curl /chat` 504 Gateway Timeout** — GCE Ingress default timeout 30 초를 vLLM cold start 가 초과. 두 번째 호출 시도하거나(warm 상태) Day 8 의 BackendConfig 를 미리 적용. lesson.md §4.5 결정 박스 ③ 참조.

8. **답변 텍스트는 오는데 `sources` 가 빈 배열** — Qdrant 컬렉션이 비어있거나 e5 query prefix 누락(자주 하는 실수 ⑬). 사전 조건의 `points_count > 0` 확인 + `kubectl logs deploy/rag-api -n rag-llm --tail=100 | grep retriever` 로 검색 결과 0 인지 확인. Day 3 인덱싱 결과가 휘발됐으면 Day 3 Workflow 재실행.

9. **답변에 `[1]` `[2]` `[3]` 인용 마커가 안 보임** — `prompts.py` 의 SYSTEM_PROMPT 가 컨테이너 이미지에 포함됐는지 확인. `kubectl exec deploy/rag-api -n rag-llm -- cat /app/prompts.py | head -20` 으로 한국어 SYSTEM_PROMPT 가 있는지 확인. 누락 시 Step 2 부터 이미지 재빌드.

---

## 다음 단계

- [`day-07-config-secret-monitoring.md`](day-07-config-secret-monitoring.md) — Day 7: Deployment 30 의 env 6 종을 ConfigMap 32 + Secret 33 으로 *분리 리팩토링* + ServiceMonitor 추가로 Prometheus 가 RAG API/vLLM/Qdrant 메트릭 수집
- 작성된 매니페스트: [`../manifests/30-rag-api-deployment.yaml`](../manifests/30-rag-api-deployment.yaml), [`../manifests/31-rag-api-service.yaml`](../manifests/31-rag-api-service.yaml), [`../manifests/40-ingress.yaml`](../manifests/40-ingress.yaml)
- 관련 lesson 섹션: [`../lesson.md`](../lesson.md) §3.1 (Day 6 Ingress 흐름), §4.4 (Deployment 매니페스트 해설), §4.5 (Ingress 매니페스트 해설), §10 자주 하는 실수 ⑯⑰⑱
