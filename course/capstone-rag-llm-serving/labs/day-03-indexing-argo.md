# Day 3 — 인덱싱 Argo Workflow 클러스터 실행

> **상위 lesson**: [`../lesson.md`](../lesson.md) §3.3 인덱싱 Workflow DAG, §4.7 Argo Workflow 매니페스트 해설
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 3
> **이전 단계**: [`day-02-indexing-script-local.md`](day-02-indexing-script-local.md)
> **소요 시간**: 2 ~ 2.5 시간 (Argo 설치 10 분, 이미지 빌드·푸시 15~25 분, Workflow 실행 5~10 분, CronWorkflow 검증 10 분)

---

## 🎯 Goal

Day 3 을 마치면 다음 5 가지가 충족됩니다.

- `argo` namespace 에 Argo Workflows controller (`workflow-controller` + `argo-server`) Running
- `rag-llm` namespace 에 ServiceAccount `workflow` + Role + RoleBinding 적용
- `argo submit -n rag-llm manifests/50-indexing-workflow.yaml` 가 5 step (`git-clone → load-docs → chunk → embed → upsert`) 모두 `Succeeded`
- Qdrant 컬렉션 `rag-docs` 의 `points_count` 가 Day 2 의 결과(약 500~800)와 같은 범위로 재현됨 (자기참조형 retrieval 동등성)
- `kubectl get cronwf rag-indexing-daily -n rag-llm` 에 schedule `0 3 * * *` 표시 + 수동 트리거 1 회 성공

---

## 🔧 사전 조건

- **Day 1 + Day 2 완료**: Qdrant `qdrant-0` Pod 가 Running, 로컬에서 `python pipeline.py all` 이 한 번 이상 성공한 상태(컨테이너 실행 결과와 비교 기준).
  ```bash
  kubectl get pod qdrant-0 -n rag-llm
  # → qdrant-0   1/1   Running   0   ...
  ```
- **클러스터**: GKE (또는 minikube/kind). Day 3 도 GPU 가 필요 없어 CPU 노드만으로 충분합니다.
- **Docker Hub 계정**: 컨테이너 이미지를 public 으로 push 할 본인 계정. `docker login` 완료 상태.
- **GitHub fork**: 본 코스 레포(`k8s-for-mle`) 의 본인 fork 가 **public** 으로 공개되어 있어야 합니다 (Workflow 의 `git-clone` step 이 무인증 clone). private 사용 시 §🚨 트러블슈팅 참고.
- **kubectl + helm**: kubectl 캡스톤 컨텍스트 활성. `argo` CLI 는 Step 1 에서 설치합니다.
- **작업 디렉토리**: 본 lab 의 모든 명령은 **프로젝트 루트**(`k8s-for-mle/`) 에서 실행하는 것을 기준으로 합니다.

> 💡 **GKE 비용 관리**: Day 3 도 CPU only 노드풀로 충분합니다. T4 GPU 노드풀은 Day 4 vLLM 까지 미루세요. Argo controller 자체는 약 200MiB 메모리 + 50m CPU 만 사용합니다.

---

## 🚀 Steps

### Step 1. argo CLI + Argo Workflows 컨트롤러 설치

```bash
# (1) argo CLI 설치 (macOS Apple Silicon 기준 — Linux/WSL2 는 argo-linux-amd64.gz 로 변경)
ARGO_VERSION=v3.5.13
curl -sLO https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/argo-darwin-arm64.gz
gunzip argo-darwin-arm64.gz && chmod +x argo-darwin-arm64
sudo mv argo-darwin-arm64 /usr/local/bin/argo
argo version --short
```

**예상 출력:**

```
argo: v3.5.13
```

```bash
# (2) Argo Workflows controller 를 argo namespace 에 설치
kubectl create namespace argo
kubectl apply -n argo -f \
  https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/quick-start-minimal.yaml

# (3) UI 토큰 입력 우회 (학습용 — 운영은 SSO 권장)
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

✅ **확인 포인트**: 두 Deployment 가 모두 Running. argo CLI 가 클러스터에 닿는지는 Step 3 후에 확인합니다.

> 💡 **왜 namespace 가 분리되어 있는가**: controller 는 `argo`, Workflow 실행은 `rag-llm` 으로 분리합니다. controller 와 워크로드를 같은 namespace 에 두면 RBAC 가 단순해지지만, 분리해 두면 캡스톤(`rag-llm`) 만 통째로 삭제할 때 controller 가 영향을 받지 않습니다. lesson.md §4.7 결정 박스 ③ 참조.

### Step 2. `rag-llm` namespace 의 Argo RBAC 적용

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/49-argo-rbac.yaml
```

**예상 출력:**

```
serviceaccount/workflow created
role.rbac.authorization.k8s.io/workflow created
rolebinding.rbac.authorization.k8s.io/workflow created
```

확인:

```bash
kubectl get sa,role,rolebinding -n rag-llm -l app=argo-workflow
```

**예상 출력:**

```
NAME                       SECRETS   AGE
serviceaccount/workflow    0         5s

NAME                                       CREATED AT
role.rbac.authorization.k8s.io/workflow    2026-05-06T...

NAME                                              ROLE              AGE
rolebinding.rbac.authorization.k8s.io/workflow    Role/workflow     5s
```

✅ **확인 포인트**: 3 개 리소스(ServiceAccount, Role, RoleBinding) 가 모두 `workflow` 이름으로 생성됨.

### Step 3. 컨테이너 이미지 빌드 + Docker Hub 푸시

```bash
# Docker Hub 본인 계정으로 로그인 (1 회만)
docker login

# 이미지 빌드 (Day 2 의 동일한 Dockerfile)
DOCKER_USER=<your-dockerhub-id>   # ← 본인 ID 로 교체
docker build \
  -t docker.io/${DOCKER_USER}/rag-indexer:0.1.0 \
  course/capstone-rag-llm-serving/practice/pipelines/indexing/

# 빌드 결과 확인
docker images | grep rag-indexer
```

**예상 출력 (이미지 크기 ~1.2GB — torch CPU + sentence-transformers 포함):**

```
docker.io/<your-id>/rag-indexer   0.1.0   abcdef123456   1 minute ago   1.2GB
```

```bash
# Docker Hub 에 push (public visibility)
docker push docker.io/${DOCKER_USER}/rag-indexer:0.1.0
```

**예상 출력 (마지막 줄):**

```
0.1.0: digest: sha256:abc... size: 1234
```

✅ **확인 포인트**: Docker Hub 웹에서 본인 계정의 `rag-indexer` repo 가 public 으로 노출되어 있어야 합니다 (private 이면 GKE 노드가 pull 실패).

> 💡 **첫 빌드 15~25 분**: torch CPU 휠(~700MB) + sentence-transformers + langchain 의존성 설치 시간. 두 번째 이후는 Docker layer 캐시 덕분에 1 분 이내.

### Step 4. Workflow 매니페스트의 placeholder 치환

`50-indexing-workflow.yaml` 과 `51-indexing-cronworkflow.yaml` 두 매니페스트의 `<user>` 를 본인 GitHub 계정과 Docker Hub 계정으로 한 번에 치환합니다.

```bash
GITHUB_USER=<your-github-id>     # ← 본인 GitHub fork 소유자 ID
DOCKER_USER=<your-dockerhub-id>  # ← 본인 Docker Hub 계정 ID (Step 3 와 동일)

# Workflow + CronWorkflow 두 파일을 한 번에 치환 (in-place)
sed -i.bak \
  -e "s|https://github.com/<user>/k8s-for-mle.git|https://github.com/${GITHUB_USER}/k8s-for-mle.git|" \
  -e "s|docker.io/<user>/rag-indexer:0.1.0|docker.io/${DOCKER_USER}/rag-indexer:0.1.0|g" \
  course/capstone-rag-llm-serving/manifests/50-indexing-workflow.yaml \
  course/capstone-rag-llm-serving/manifests/51-indexing-cronworkflow.yaml
```

**확인:**

```bash
grep -E "github.com|docker.io" course/capstone-rag-llm-serving/manifests/50-indexing-workflow.yaml
```

**예상 출력 (placeholder 가 모두 사라져야 함):**

```
    - { name: git-repo,        value: "https://github.com/<your-github-id>/k8s-for-mle.git" }    # TODO: ...
      image: docker.io/<your-dockerhub-id>/rag-indexer:0.1.0    # TODO: ...
```

✅ **확인 포인트**: `<user>` 라는 문자열이 더 이상 보이지 않습니다.

> 💡 **`.bak` 파일 정리**: `sed -i.bak` 가 만든 백업은 git status 에 잡히므로 `rm course/capstone-rag-llm-serving/manifests/*.bak` 로 정리하거나, 매니페스트를 기본 상태로 돌리려면 `git checkout course/capstone-rag-llm-serving/manifests/` 로 되돌립니다.

### Step 5. Workflow 매니페스트 dry-run

```bash
kubectl apply --dry-run=client \
  -f course/capstone-rag-llm-serving/manifests/49-argo-rbac.yaml \
  -f course/capstone-rag-llm-serving/manifests/50-indexing-workflow.yaml \
  -f course/capstone-rag-llm-serving/manifests/51-indexing-cronworkflow.yaml
```

**예상 출력:**

```
serviceaccount/workflow configured (dry run)
role.rbac.authorization.k8s.io/workflow configured (dry run)
rolebinding.rbac.authorization.k8s.io/workflow configured (dry run)
workflow.argoproj.io/rag-indexing-... created (dry run)
cronworkflow.argoproj.io/rag-indexing-daily created (dry run)
```

✅ **확인 포인트**: 5 개 리소스가 모두 `(dry run)` 으로 보고되면 OK.

### Step 6. Workflow 제출 + 단계별 진행 관찰

```bash
argo submit -n rag-llm \
  course/capstone-rag-llm-serving/manifests/50-indexing-workflow.yaml \
  --watch
```

`--watch` 는 모든 step 이 끝날 때까지 단계별 상태를 갱신해 줍니다.

**예상 출력 (최종, 약 3~5 분 후):**

```
Name:                rag-indexing-q9w2k
Namespace:           rag-llm
ServiceAccount:      workflow
Status:              Succeeded
Duration:            3 minutes 45 seconds
Parameters:
  git-repo:          https://github.com/<your-id>/k8s-for-mle.git
  git-branch:        main
  collection-name:   rag-docs
  chunk-size:        512
  chunk-overlap:     64
  embedding-model:   intfloat/multilingual-e5-small

STEP                              TEMPLATE          PODNAME                                  DURATION
 ✔ rag-indexing-q9w2k             rag-indexing
 ├─✔ git-clone                    git-clone-step    rag-indexing-q9w2k-git-clone-step-...    8s
 ├─✔ load-docs                    pipeline-step     rag-indexing-q9w2k-pipeline-step-...     12s
 ├─✔ chunk                        pipeline-step     rag-indexing-q9w2k-pipeline-step-...     20s
 ├─✔ embed                        pipeline-step     rag-indexing-q9w2k-pipeline-step-...     2m 30s
 └─✔ upsert                       pipeline-step     rag-indexing-q9w2k-pipeline-step-...     10s
```

✅ **확인 포인트**: 5 step 이 모두 ✔ Succeeded. embed step 이 가장 오래 걸리며 (CPU 임베딩 + 첫 모델 다운로드 ~130MB), 두 번째 실행부터는 같은 워크플로우 내 PVC 의 `/data/hf-cache` 덕분에 빨라집니다.

### Step 7. 단계별 로그 + Argo UI 그래프 확인

```bash
# 단계별 stdout 마지막 30 줄 (특히 upsert 의 points_count 확인)
argo logs -n rag-llm @latest --no-color | tail -30
```

**예상 출력 (꼬리부분):**

```
... pipeline-step-...: [embed] embedding dimension=384
... pipeline-step-...: [embed] e5 model detected → prefixing inputs with 'passage:'
... pipeline-step-...: [embed] wrote 612 embeddings (dim=384) -> /data/embeddings.jsonl
... pipeline-step-...: [upsert] connecting to http://qdrant.rag-llm.svc.cluster.local:6333, collection=rag-docs
... pipeline-step-...: [upsert] created collection 'rag-docs' (size=384, distance=Cosine)
... pipeline-step-...: [upsert] uploaded 612 points. collection points_count=612
```

```bash
# Argo UI port-forward (새 터미널 또는 백그라운드)
kubectl -n argo port-forward svc/argo-server 2746:2746 >/dev/null 2>&1 &
sleep 2
# 브라우저에서 https://localhost:2746
# (자체 서명 인증서 경고는 Advanced → Proceed to localhost (unsafe) 로 우회)
```

UI 의 Workflows 탭에서 namespace `rag-llm` 선택 → 방금 제출한 워크플로우 클릭 → DAG 그래프에 5 노드(`git-clone`, `load-docs`, `chunk`, `embed`, `upsert`) 가 녹색으로 직선 연결된 모습을 확인합니다.

✅ **확인 포인트**: UI 에서 5 노드 모두 ✔ 녹색 + 한 노드 클릭 시 우측 패널에 그 Pod 의 stdout 이 표시됨.

### Step 8. CronWorkflow 등록 + 수동 트리거

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/51-indexing-cronworkflow.yaml
argo cron list -n rag-llm
```

**예상 출력:**

```
NAMESPACE   NAME                  AGE   LAST RUN   NEXT RUN   SCHEDULE      TIMEZONE
rag-llm     rag-indexing-daily    10s   N/A        18h        0 3 * * *     Asia/Seoul
```

학습 중 다음 03:00 까지 기다릴 수 없으므로 **수동 트리거** 로 같은 정의를 즉시 실행합니다.

```bash
argo submit --from cronwf/rag-indexing-daily -n rag-llm --watch
```

**예상 출력 (요약):**

```
Name:                rag-indexing-daily-r0ve8
...
Status:              Succeeded
Duration:            1 minute 50 seconds              ← 첫 실행보다 빠름

STEP                              TEMPLATE          DURATION
 ✔ rag-indexing-daily-r0ve8       rag-indexing
 ├─✔ git-clone                    git-clone-step    7s
 ├─✔ load-docs                    pipeline-step     11s
 ├─✔ chunk                        pipeline-step     18s
 ├─✔ embed                        pipeline-step     1m 8s   ← 모델 다운로드 캐시 히트로 절반
 └─✔ upsert                       pipeline-step     6s
```

✅ **확인 포인트**: CronWorkflow 가 schedule 표시 + 수동 트리거한 워크플로우가 5 step 모두 Succeeded. `points_count` 가 첫 Workflow 와 동일하게 유지(idempotent upsert 동작).

---

## ✅ 검증 체크리스트

다음 항목을 모두 확인했다면 Day 3 이 완료된 것입니다.

- [ ] `kubectl get deploy -n argo` 에 `argo-server`, `workflow-controller` READY `1/1`
- [ ] `kubectl get sa workflow -n rag-llm` 존재
- [ ] `kubectl get wf -n rag-llm` 의 STATUS 컬럼이 `Succeeded`
- [ ] `argo logs -n rag-llm @latest` 마지막에 `uploaded N points. collection points_count=N` (N ≈ 500~800, Day 2 와 동일 범위)
- [ ] Argo UI(`https://localhost:2746`) DAG 그래프에 5 노드(`git-clone`, `load-docs`, `chunk`, `embed`, `upsert`) 모두 녹색
- [ ] `kubectl get cronwf rag-indexing-daily -n rag-llm` 에 SCHEDULE `0 3 * * *`, TIMEZONE `Asia/Seoul`
- [ ] 수동 트리거(`argo submit --from cronwf/rag-indexing-daily -n rag-llm --watch`) 가 5 step 모두 Succeeded
- [ ] `kubectl exec -n rag-llm qdrant-0 -- curl -s localhost:6333/collections/rag-docs | grep -o 'points_count":[0-9]*'` → Day 2 결과와 동일 범위 (idempotent 재현성)

---

## 🧹 정리

**Day 4 로 바로 이어서 진행**하는 경우는 **Argo controller 와 컬렉션 데이터를 그대로 둡니다**. CronWorkflow 만 일시 중지하려면:

```bash
# CronWorkflow 일시 중지 (suspend) — Day 4~10 동안 자동 인덱싱 멈춤
kubectl patch cronwf rag-indexing-daily -n rag-llm --type=merge -p '{"spec":{"suspend": true}}'
```

**Day 3 만 단독으로 끝낼 때 (또는 GKE 비용 절감)**:

```bash
# 1. 본 토픽 워크플로우 인스턴스 삭제 (Workflow + CronWorkflow)
argo delete --all -n rag-llm 2>/dev/null || true
kubectl delete -f course/capstone-rag-llm-serving/manifests/51-indexing-cronworkflow.yaml --ignore-not-found
kubectl delete -f course/capstone-rag-llm-serving/manifests/49-argo-rbac.yaml --ignore-not-found

# 2. Argo controller namespace 삭제
kubectl delete namespace argo --ignore-not-found

# 3. (선택) 백그라운드 port-forward 종료
pkill -f 'kubectl.*port-forward.*argo-server' 2>/dev/null
```

**Day 1·2 의 Qdrant 까지 정리**하려면 [`day-01-namespace-qdrant.md`](day-01-namespace-qdrant.md) §🧹 정리 참고.

**GKE 클러스터 자체를 종료**하려면 (캡스톤 plan §11 비용 관리):

```bash
gcloud container clusters delete capstone --zone us-central1-a --quiet
```

---

## 🚨 막힐 때 (트러블슈팅)

| 증상 | 원인 | 해결 |
|---|---|---|
| Workflow 가 `Pending` 으로 멈춤 | controller 가 `argo` namespace 에 없거나 RBAC 미적용 | `kubectl get pods -n argo` 로 controller 확인. 안 보이면 Step 1 재실행. SA 누락은 Step 2 재실행 |
| `pods is forbidden: User "system:serviceaccount:rag-llm:default" cannot create resource "pods"` | Workflow 의 `serviceAccountName: workflow` 누락 또는 49-argo-rbac.yaml 미적용 | `kubectl get sa workflow -n rag-llm` 확인 → 없으면 Step 2. 매니페스트의 `serviceAccountName: workflow` 라인 확인 |
| `git-clone` step Failed — `fatal: could not read Username for 'https://github.com'` | private repo 또는 URL 오타 | 본인 fork 가 public 인지 확인. private 사용 시 Secret(GitHub Personal Access Token) 을 마운트하는 추가 설정 필요 — `manifests/50` 의 `git-clone-step` 에 `env: [{name: GIT_ASKPASS, ...}]` 추가 |
| `load-docs` 가 `0 docs found` | `DOCS_ROOT` 가 잘못된 경로(예: `/docs` 단독) | 매니페스트의 `DOCS_ROOT=/docs/k8s-for-mle/course` 인지 확인. git clone 의 결과 디렉토리 이름이 placeholder 치환 후에도 `k8s-for-mle` 인지 확인 |
| `upsert` 가 `connection refused` | `QDRANT_URL` 이 `localhost:6333` 으로 남아 있음 (Day 2 의 port-forward 패턴을 그대로 옮긴 실수) | 매니페스트의 env 가 `http://qdrant.rag-llm.svc.cluster.local:6333` 인지 확인. 클러스터 내부 DNS 사용. port-forward 는 Day 3 에서 불필요 |
| `embed` step OOMKilled | sentence-transformers 모델 + 청크 메모리가 limits 2Gi 초과 | 매니페스트의 `resources.limits.memory: 2Gi` 를 `4Gi` 로 상향, 또는 파라미터 `--chunk-size 256` 으로 청크 축소 (`argo submit -p chunk-size=256`) |
| Pod 이 `ImagePullBackOff` | Docker Hub push 누락 또는 repo 가 private | `docker push docker.io/${DOCKER_USER}/rag-indexer:0.1.0` 재실행. Docker Hub 웹에서 visibility 가 public 인지 확인. `kubectl describe pod ... -n rag-llm` 의 Events 에서 정확한 pull 에러 확인 |

---

## 다음 단계

➡️ Day 4 — vLLM Deployment + OpenAI 호환 API 호출 검증 (작성 예정)

본 lab 에서 만든 인덱싱 결과(Qdrant `rag-docs` 컬렉션)는 Day 5/6 의 RAG API 가 retrieval 단계에서 그대로 호출합니다. Day 4 에서는 vLLM 으로 SLM(`microsoft/phi-2`) 을 GPU 노드에 띄워 RAG API 의 generation 측 백엔드를 준비합니다.

> 참고: Day 4 lab 은 후속 작업입니다. 본 캡스톤 진행 순서는 [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 을 따릅니다.
