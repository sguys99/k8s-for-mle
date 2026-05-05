# Phase 4 / 04 — 실습 가이드 (Argo Workflows + RAG 인덱싱 파이프라인)

> [lesson.md](../lesson.md) 의 1-1~1-4 개념을 minikube 에서 실제로 적용해, *Argo Workflows 의 DAG / parameters / RBAC / volumeClaimTemplates* 가 어떻게 동작하는지 직접 확인합니다. 본 토픽은 **CPU 만으로 진행 가능** — 03-vllm 의 Track A/B 분기와 달리 단일 트랙입니다.
>
> **소요 시간**: 90~120분 (Argo 설치 5분, Hello DAG 10분, RAG 이미지 빌드 15~25분 — torch CPU 다운로드 포함, RAG 워크플로우 실행 5분 — 첫 임베딩 모델 다운로드 시 90초 추가, 검증·CronWorkflow 15분, 자주 하는 실수 재현 10분, 정리 5분)

---

## 작업 디렉토리

본 lab 의 모든 명령은 다음 디렉토리에서 실행한다고 가정합니다.

```bash
cd course/phase-4-ml-on-k8s/04-argo-workflows
ls
# 예상 출력:
# labs  lesson.md  manifests  practice
```

상대경로 `manifests/...` 와 `practice/rag_pipeline/` 가 그대로 동작합니다.

---

## 실습 단계 한눈에 보기

| Step | 목적 | 핵심 명령 | 소요 |
|-----|------|---------|------|
| 0 | 사전 점검 — minikube/kubectl/Docker 가 정상 | `minikube status` / `docker info` | 5분 |
| 1 | argo CLI 설치 | `curl -sLO ...argo-darwin-arm64.gz` | 5분 |
| 2 | minikube 기동 + ml-pipelines 네임스페이스/RBAC/Qdrant 적용 | `kubectl apply -f manifests/0*.yaml manifests/02-qdrant.yaml` | 10분 |
| 3 | Argo Workflows 설치 + 인증 모드 패치 | `kubectl apply -n argo -f .../quick-start-minimal.yaml` | 5분 |
| 4 | Hello DAG 제출 — fan-out/fan-in 시각화 | `argo submit -n ml-pipelines manifests/10-hello-dag-workflow.yaml --watch` | 5분 |
| 5 | UI 접속해 그래프로 의존성 확인 | `kubectl -n argo port-forward svc/argo-server 2746:2746` | 5분 |
| 6 | RAG 파이프라인 이미지 빌드 (minikube docker-env) | `eval $(minikube docker-env) && docker build -t rag-pipeline:0.1.0 practice/rag_pipeline/` | 15~25분 |
| 7 | RAG 인덱싱 Workflow 제출 + 로그 스트리밍 | `argo submit -n ml-pipelines manifests/20-rag-indexing-workflow.yaml --watch` | 5분 |
| 8 | Qdrant 컬렉션·벡터 카운트 검증 | `curl http://localhost:6333/collections/rag-docs` | 5분 |
| 9 | CronWorkflow 등록 + 수동 트리거 | `argo submit --from cronwf/rag-indexing-daily -n ml-pipelines` | 10분 |
| 10 | 자주 하는 실수 재현 — RBAC 미적용 시 실패 메시지 | `argo submit ... --serviceaccount default` | 10분 |
| ▣ | 정리 | `kubectl delete -f manifests/ ; kubectl delete ns ml-pipelines argo` | 5분 |

---

## Step 0 — 사전 점검

```bash
# kubectl 버전 (1.28+ 권장)
kubectl version --client

# minikube 상태 — 기동 안 되어 있으면 Step 2 에서 시작
minikube status 2>/dev/null

# Docker 데몬 동작 확인 — Step 6 의 minikube docker-env 빌드에 필요
docker info | head -5
```

**예상 출력 (예시):**

```
Client Version: v1.31.x
Kustomize Version: v5.x.x

# minikube 가 아직 안 떠 있으면:
host: Stopped
```

✅ **확인 포인트**: kubectl 과 docker 가 응답하면 다음 Step 으로 넘어갑니다. minikube 기동은 Step 2 에서 함께 합니다.

---

## Step 1 — argo CLI 설치

```bash
ARGO_VERSION=v3.5.13

# macOS arm64 (Apple Silicon)
curl -sLO https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/argo-darwin-arm64.gz
gunzip argo-darwin-arm64.gz
chmod +x argo-darwin-arm64
sudo mv argo-darwin-arm64 /usr/local/bin/argo

# (Linux/WSL2 학습자: argo-linux-amd64.gz 로 파일명만 바꿔 같은 절차)

argo version --short
```

**예상 출력:**

```
argo: v3.5.13
```

✅ **확인 포인트**: `argo: v3.5.x` 가 보입니다. 본 lab 에서는 `argo submit`, `argo list`, `argo logs`, `argo cron list` 4개 명령만 사용합니다.

---

## Step 2 — minikube 기동 + 본 토픽 매니페스트 적용

```bash
# 메모리 8G 권장 — 임베딩 모델 + Qdrant 합쳐 6G 안팎 사용
minikube start --cpus=4 --memory=8g

# ml-pipelines 네임스페이스 + workflow SA + RBAC + Qdrant
kubectl apply -f manifests/00-namespace.yaml
kubectl apply -f manifests/01-argo-rbac.yaml
kubectl apply -f manifests/02-qdrant.yaml

kubectl get pods -n ml-pipelines -w
# Qdrant 가 Running 1/1 이 되면 Ctrl+C
```

**예상 출력:**

```
NAME                      READY   STATUS              RESTARTS   AGE
qdrant-7d6b8fc9c4-x2pbz   0/1     ContainerCreating   0          5s
qdrant-7d6b8fc9c4-x2pbz   1/1     Running             0          25s
```

```bash
# Qdrant Health 확인 — port-forward 로 6333 노출
kubectl -n ml-pipelines port-forward svc/qdrant 6333:6333 >/dev/null 2>&1 &
sleep 2
curl -s http://localhost:6333/healthz
```

**예상 출력:**

```
healthz check passed
```

✅ **확인 포인트**: Qdrant Pod 이 Running, `/healthz` 가 정상 응답.

---

## Step 3 — Argo Workflows 설치 + 인증 모드 패치

```bash
ARGO_VERSION=v3.5.13
kubectl create namespace argo

# quick-start-minimal: workflow-controller + argo-server + RBAC. ArtifactRepository 없는 가벼운 버전
kubectl apply -n argo -f \
  https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/quick-start-minimal.yaml

# 학습용: 토큰 입력 우회 — argo-server 의 args 를 ["server","--auth-mode=server"] 로 교체
kubectl -n argo patch deploy argo-server --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":["server","--auth-mode=server"]}]'

kubectl -n argo rollout status deploy/argo-server --timeout=120s
kubectl -n argo rollout status deploy/workflow-controller --timeout=120s
kubectl -n argo get pods
```

**예상 출력:**

```
NAME                                   READY   STATUS    RESTARTS   AGE
argo-server-xxxxxxxxxx-yyyyy           1/1     Running   0          1m
workflow-controller-xxxxxxxxxx-zzzzz   1/1     Running   0          1m
```

```bash
# argo CLI 가 클러스터에 닿는지 확인
argo list -n ml-pipelines
```

**예상 출력 (워크플로우가 아직 없으므로):**

```
NAME   STATUS   AGE   DURATION   PRIORITY   MESSAGE
```

✅ **확인 포인트**: argo CLI 가 *No workflows found* 가 아닌 *빈 헤더만* 출력하면 정상.

---

## Step 4 — Hello DAG 제출 (fan-out / fan-in)

```bash
argo submit -n ml-pipelines manifests/10-hello-dag-workflow.yaml --watch
```

`--watch` 는 워크플로우가 끝날 때까지 단계별 상태를 갱신해 줍니다. **예상 출력 (최종):**

```
Name:                hello-dag-abc12
Namespace:           ml-pipelines
ServiceAccount:      workflow
Status:              Succeeded
Duration:            22 seconds

STEP                  TEMPLATE          PODNAME                                  DURATION
 ✔ hello-dag-abc12   dataset-eda
 ├─✔ prepare         emit-batch-id     hello-dag-abc12-emit-batch-id-1234567       5s
 ├─✔ analyze-stats   print-with-batch  hello-dag-abc12-print-with-batch-2345678    6s
 ├─✔ analyze-shape   print-with-batch  hello-dag-abc12-print-with-batch-3456789    6s
 └─✔ join            print-with-batch  hello-dag-abc12-print-with-batch-4567890    5s
```

핵심은 `analyze-stats` 와 `analyze-shape` 가 **동시에 실행** 됐다는 점 — 둘 다 `prepare` 만 의존하므로 fan-out, `join` 은 둘 다 끝나야 시작하므로 fan-in.

```bash
# 한 단계의 stdout 만 보기 — prepare 단계가 실제로 batch-id 를 만들었는지 확인
argo logs @latest -n ml-pipelines --no-color | grep prepare
```

**예상 출력:**

```
hello-dag-abc12-emit-batch-id-1234567: [prepare] generated batch-id=batch-1714911234
```

✅ **확인 포인트**: 두 분석 task 의 시작 시각이 거의 같음(±1s), join 의 stdout 에 prepare 의 batch-id 가 그대로 찍힘.

---

## Step 5 — UI 그래프 확인

```bash
# 새 터미널 또는 백그라운드로
kubectl -n argo port-forward svc/argo-server 2746:2746 >/dev/null 2>&1 &
sleep 2

# macOS 기준 — Linux/WSL2 는 firefox/chromium 직접 실행
open https://localhost:2746
```

브라우저 자체 서명 인증서 경고가 뜨면 **Advanced → Proceed to localhost (unsafe)** 로 우회합니다.
- 좌측 메뉴 *Workflows* → 네임스페이스 드롭다운에서 `ml-pipelines` 선택
- `hello-dag-abc12` 클릭 → DAG 그래프가 4 노드 + 화살표 색상으로 표시
- 한 노드를 클릭 → 우측 패널에 *컨테이너 로그* 와 *상세 정보*

✅ **확인 포인트**: `prepare` 노드에서 두 갈래로 나뉘어 `analyze-stats` / `analyze-shape` 로 가고, 그 둘이 다시 `join` 에 모이는 *Y 자 모양 그래프* 가 보입니다.

---

## Step 6 — RAG 파이프라인 이미지 빌드

minikube 내부 Docker 데몬에 직접 빌드하면 push/pull 우회가 가능합니다. `imagePullPolicy: IfNotPresent` 와 결합해 매번 hub.docker.io 를 거치지 않아도 됩니다.

```bash
# 현재 셸을 minikube 의 docker-env 로 전환 (이 셸 내에서만 유효)
eval $(minikube docker-env)

# rag-pipeline:0.1.0 이미지 빌드 — torch CPU 빌드(~700MB) 다운로드 때문에 첫 빌드는 15~25분
docker build -t rag-pipeline:0.1.0 practice/rag_pipeline/

# 빌드 결과 확인
docker images | grep rag-pipeline
```

**예상 출력:**

```
rag-pipeline   0.1.0   abcdef123456   30 seconds ago   1.2GB
```

> 💡 **이 시점부터 새 터미널을 열면** `eval $(minikube docker-env)` 가 풀려 `docker images` 에서 호스트 Docker 만 보입니다. 이미지가 사라진 게 아니라 *터미널이 가리키는 Docker 데몬이 다른 것* 일 뿐입니다. 이후 Step 들은 kubectl/argo 만 쓰므로 문제 없습니다.

✅ **확인 포인트**: `rag-pipeline:0.1.0` 이 minikube 내부 docker 에 보입니다.

---

## Step 7 — RAG 인덱싱 Workflow 제출

```bash
argo submit -n ml-pipelines manifests/20-rag-indexing-workflow.yaml --watch
```

**예상 출력 (최종):**

```
Name:                rag-indexing-q9w2k
Namespace:           ml-pipelines
ServiceAccount:      workflow
Status:              Succeeded
Duration:            1 minute 32 seconds
Parameters:
  collection-name:   rag-docs
  chunk-size:        512
  chunk-overlap:     64
  embedding-model:   sentence-transformers/all-MiniLM-L6-v2

STEP                              TEMPLATE         PODNAME                                  DURATION
 ✔ rag-indexing-q9w2k             rag-indexing
 ├─✔ load-docs                    pipeline-step    rag-indexing-q9w2k-pipeline-step-...      8s
 ├─✔ chunk                        pipeline-step    rag-indexing-q9w2k-pipeline-step-...      12s
 ├─✔ embed                        pipeline-step    rag-indexing-q9w2k-pipeline-step-...      55s
 └─✔ upsert                       pipeline-step    rag-indexing-q9w2k-pipeline-step-...      7s
```

embed 가 가장 오래 걸리는 이유는 *첫 호출에 sentence-transformer 모델(~90MB) 다운로드* 때문 — `HF_HOME=/data/hf-cache` 가 PVC 위라 같은 워크플로우 안의 다음 단계나 다음 워크플로우는 캐시 히트입니다.

```bash
# 단계별 stdout 확인
argo logs @latest -n ml-pipelines --no-color | tail -30
```

**예상 출력 (꼬리부분):**

```
rag-indexing-q9w2k-pipeline-step-...: [embed] embedding dimension=384
rag-indexing-q9w2k-pipeline-step-...: [embed] wrote 18 embeddings (dim=384) -> /data/embeddings.jsonl
rag-indexing-q9w2k-pipeline-step-...: [upsert] connecting to http://qdrant.ml-pipelines.svc.cluster.local:6333, collection=rag-docs
rag-indexing-q9w2k-pipeline-step-...: [upsert] uploaded 18 points. collection vectors_count=18
```

✅ **확인 포인트**: 4 단계 모두 `Succeeded`, embed 단계의 dim 이 `384`, upsert 의 `vectors_count` 가 10 이상.

---

## Step 8 — Qdrant 컬렉션·벡터 카운트 검증

```bash
# Step 2 에서 띄운 port-forward 가 살아 있다면 그대로 사용. 끊겼으면 다시:
kubectl -n ml-pipelines port-forward svc/qdrant 6333:6333 >/dev/null 2>&1 &
sleep 2

curl -s http://localhost:6333/collections/rag-docs | jq '.result | {points_count, vectors_size: .config.params.vectors.size, distance: .config.params.vectors.distance}'
```

**예상 출력:**

```json
{
  "points_count": 18,
  "vectors_size": 384,
  "distance": "Cosine"
}
```

```bash
# 컬렉션의 첫 3개 포인트 미리보기 (벡터 본체는 생략, payload 만)
curl -s -X POST http://localhost:6333/collections/rag-docs/points/scroll \
  -H "Content-Type: application/json" \
  -d '{"limit": 3, "with_payload": true, "with_vector": false}' \
  | jq '.result.points[] | {id, source: .payload.source, chunk_index: .payload.chunk_index, snippet: .payload.text[0:60]}'
```

**예상 출력 (한 청크 예시):**

```json
{
  "id": "f3b8a012-3c4d-5e6f-7890-abcdef012345",
  "source": "01-gpu-on-k8s.md",
  "chunk_index": 0,
  "snippet": "# Phase 4-1 — GPU on Kubernetes 핵심 정리\n\n## NVIDIA Devic"
}
```

✅ **확인 포인트**: `points_count >= 10`, `vectors_size == 384`, `distance == "Cosine"`, payload 의 `source` 가 `sample_docs/` 의 .md 파일명과 일치.

---

## Step 9 — CronWorkflow 등록 + 수동 트리거

```bash
kubectl apply -f manifests/30-rag-indexing-cron.yaml
argo cron list -n ml-pipelines
```

**예상 출력:**

```
NAMESPACE      NAME                  AGE   LAST RUN   NEXT RUN   SCHEDULE      TIMEZONE
ml-pipelines   rag-indexing-daily    10s   N/A        18h        0 3 * * *     Asia/Seoul
```

학습 중 18시간 기다릴 수는 없으므로 *수동 트리거* 로 같은 정의를 즉시 실행합니다.

```bash
argo submit --from cronwf/rag-indexing-daily -n ml-pipelines --watch
```

**예상 출력 (요약):**

```
Name:                rag-indexing-daily-r0ve8
...
STEP                              TEMPLATE         DURATION
 ✔ rag-indexing-daily-r0ve8       rag-indexing
 ├─✔ load-docs                    pipeline-step    7s
 ├─✔ chunk                        pipeline-step    11s
 ├─✔ embed                        pipeline-step    8s        ← 임베딩 모델 캐시 히트로 첫 실행 대비 10배 단축
 └─✔ upsert                       pipeline-step    6s
```

> 💡 **두 번째 실행이 빠른 이유**: HF 모델 캐시가 (별도 워크플로우의) PVC 가 아닌 *minikube 노드의 docker 이미지 layer + 파이썬 패키지 cache* 덕분. 같은 워크플로우 안의 단계 간 캐시 히트는 PVC 의 `/data/hf-cache` 효과지만, 다른 워크플로우 사이에서는 *ephemeral PVC 가 매번 새로 생성* 되므로 모델은 다시 다운로드됩니다. 운영에서는 모델 캐시용 별도 *영구* PVC 또는 모델을 이미지에 미리 굽는 패턴을 씁니다.

✅ **확인 포인트**: `argo cron list` 에 `rag-indexing-daily` 가 보이고, 수동 트리거한 워크플로우가 4단계 모두 Succeeded.

---

## Step 10 — 자주 하는 실수 1번 재현 (RBAC 미적용)

`lesson.md` 의 자주 하는 실수 1 (`pods is forbidden ... default`) 을 직접 재현해 봅니다.

```bash
# 일부러 default SA 로 같은 워크플로우 제출
argo submit -n ml-pipelines manifests/10-hello-dag-workflow.yaml \
  --serviceaccount default \
  --watch
```

**예상 출력 (실패 메시지):**

```
Name:           hello-dag-failure-fxxxx
Namespace:      ml-pipelines
ServiceAccount: default
Status:         Error
Message:        pods is forbidden: User "system:serviceaccount:ml-pipelines:default" cannot create resource "pods" in API group "" in the namespace "ml-pipelines"
```

같은 매니페스트가 `serviceAccountName: workflow` 로는 성공, `default` 로는 RBAC 없어 실패. 캡스톤에서 새 네임스페이스를 만들 때 *워크플로우 SA 와 RBAC 을 잊지 않고 함께 적용해야 한다*는 교훈이 여기서 나옵니다.

```bash
# 실패한 워크플로우 정리
argo delete -n ml-pipelines @latest
```

✅ **확인 포인트**: 에러 메시지 본문이 `pods is forbidden ... default ... cannot create resource "pods"` 형태로 정확히 출력.

---

## ▣ 정리

```bash
# port-forward 백그라운드 종료
pkill -f 'kubectl.*port-forward.*qdrant' 2>/dev/null
pkill -f 'kubectl.*port-forward.*argo-server' 2>/dev/null

# 본 토픽 워크플로우 인스턴스 삭제
argo delete --all -n ml-pipelines 2>/dev/null || true

# 본 토픽 매니페스트 정리
kubectl delete -f manifests/30-rag-indexing-cron.yaml --ignore-not-found
kubectl delete -f manifests/02-qdrant.yaml --ignore-not-found
kubectl delete -f manifests/01-argo-rbac.yaml --ignore-not-found
kubectl delete namespace ml-pipelines --ignore-not-found

# Argo 컨트롤러 정리
kubectl delete namespace argo --ignore-not-found

# minikube 자체를 끌 때 (다음 토픽도 진행할 거면 생략)
# minikube stop
```

✅ **확인 포인트**: `kubectl get ns` 에 `ml-pipelines` 와 `argo` 가 모두 사라짐.

---

## 막힐 때

| 증상 | 원인 / 해결 |
|------|------------|
| `argo submit` 가 `pods is forbidden` 으로 즉시 실패 | `manifests/01-argo-rbac.yaml` 미적용 또는 `spec.serviceAccountName: workflow` 누락. (자주 하는 실수 1번) |
| `argo submit` 가 `entrypoint template not specified` | Workflow spec 의 `entrypoint:` 한 줄 누락. (자주 하는 실수 2번) |
| RAG 워크플로우의 `chunk` 단계가 *Pending* 에서 멈춤 | 이전 단계 `load-docs` 의 결과가 PVC 로 안 넘어옴 — `volumeClaimTemplates` 미선언, 또는 volumeMounts 누락. (자주 하는 실수 3번) |
| `embed` 단계가 *ImagePullBackOff* | minikube docker-env 에 빌드 안 된 상태. Step 6 다시. `imagePullPolicy: Always` 로 바뀌어 있으면 `IfNotPresent` 로 교체 |
| Qdrant `points_count: 0` | upsert 단계 stdout 에서 `connecting to ... collection=rag-docs` 가 보였는지 확인. QDRANT_URL 환경변수가 매니페스트에서 잘못 가리킬 가능성 |
| UI 가 https 자체 서명 인증서 경고 | 학습 환경이므로 Advanced → Proceed 로 우회. 운영에서는 Ingress + TLS 또는 SSO 연동 |

---

## 다음 단계

본 lab 을 마쳤다면 [docs/course-plan.md](../../../../docs/course-plan.md) 의 Phase 4 / 04-argo-workflows 의 *minikube 검증* 체크박스를 `[x]` 로 갱신합니다 (산출물 3개 — lesson.md / 매니페스트/코드 / labs — 는 이미 작성 완료).

➡️ 다음 토픽: [Phase 4 / 05 — Distributed Training Intro](../../05-distributed-training-intro/lesson.md)
