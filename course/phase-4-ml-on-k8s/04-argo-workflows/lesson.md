# Phase 4 / 04 — Argo Workflows (DAG 워크플로 + RAG 인덱싱 파이프라인)

> **Phase**: 4 — ML on Kubernetes
> **소요 시간**: 3~4시간 (Argo 설치 + Hello DAG 30분, RAG 인덱싱 파이프라인 빌드·실행 2시간, CronWorkflow + 검증 30분)
> **선수 학습**: [Phase 2/02 — Volumes / PVC](../../phase-2-operations/02-volumes-pvc/lesson.md) (단계 간 데이터 공유에 PVC 사용), [Phase 2/04 — Job / CronJob](../../phase-2-operations/04-job-cronjob/lesson.md) (배치 워크로드 기본기), [Phase 4/02 — KServe Inference](../02-kserve-inference/lesson.md) (서빙 추상화 — 본 토픽은 *데이터/학습 측* 의 추상화)
>
> 이전 토픽들에서 우리는 *한 개씩의 매니페스트*를 다뤘습니다. 분류 모델 Deployment 1개, 평가 Job 1개, 데이터 다운로드 InitContainer 1개. 그런데 ML 워크플로는 본래 *여러 단계가 의존성을 가지고 흐르는 그래프*입니다 — 데이터 다운로드 → 전처리 → 학습 → 평가 → 모델 등록, 또는 본 토픽의 시나리오인 *문서 로드 → 청크 분할 → 임베딩 → Qdrant Upsert*. 본 토픽은 흩어져 있던 Job/Deployment 들을 **DAG 으로 묶어 재현 가능한 파이프라인**으로 만드는 도구를 익힙니다. 그 결과물은 캡스톤 Day 3("인덱싱 Argo Workflow 클러스터 실행") 에 *그대로 복사-붙여넣기* 됩니다.

---

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

1. **Argo Workflows 를 minikube 에 설치하고, argo CLI / UI 로 워크플로우를 제출·관찰합니다.** quick-start-minimal 매니페스트로 컨트롤러 + 서버 + RBAC 을 한 번에 띄우고, server 모드 인증 패치로 학습용 토큰 입력을 우회합니다.
2. **DAG / Steps, container / script template, parameters / artifacts / PVC 의 차이를 매니페스트 수준에서 식별합니다.** Hello DAG 매니페스트 (5개 task 의 fan-out / fan-in) 에서 이 4가지 개념이 모두 보이고, 본 코스의 자주 하는 실수 1·2번이 어디에서 터지는지 직접 시연합니다.
3. **RAG 인덱싱 4단계 파이프라인을 DAG 으로 구성하고, 단계 간 데이터를 PVC 로 공유합니다.** 단일 이미지 (`rag-pipeline:0.1.0`) 가 `pipeline.py {load-docs|chunk|embed|upsert}` 로 4 역할을 모두 처리하고, `volumeClaimTemplates` 가 워크플로우 시작 시 5GB PVC 를 자동 생성·종료 시 자동 삭제합니다. 결과는 Qdrant 의 `rag-docs` 컬렉션에 코사인 거리 384차원 벡터로 적재됩니다.
4. **CronWorkflow 로 일별 자동화하고, 캡스톤 Day 3 에 재사용할 패턴을 정리합니다.** `schedule: "0 3 * * *"` + `concurrencyPolicy: Replace` 의 의미와, 운영에서 같은 워크플로우 정의를 `WorkflowTemplate` 으로 빼낼 때의 트레이드오프를 설명합니다.

**완료 기준 (1줄)**: minikube 에서 `argo submit -n ml-pipelines manifests/20-rag-indexing-workflow.yaml --watch` 가 4개 task 모두 `Succeeded` 로 끝나고, `curl http://localhost:6333/collections/rag-docs` 가 `points_count >= 10` 를 반환하면 통과.

---

## 왜 ML 엔지니어에게 Argo Workflows 가 필요한가

Phase 2 에서 우리는 Job / CronJob 으로 *한 단계짜리 배치 워크로드*를 다뤘습니다. 단순 평가 잡, 일별 백테스트 같은 워크로드라면 Job 한 개로 충분합니다. 그런데 실제 ML 시스템은 *단계가 4~10개씩 이어지는 파이프라인* 으로 자라납니다 — 본 토픽의 RAG 인덱싱(load → chunk → embed → upsert), 학습 파이프라인(download → preprocess → train → eval → register), 평가 자동화(predict → metric → report)…

이 지점에서 *Job 매니페스트를 여러 개 만들어 KubernetesAPI 를 사람이 손으로 트리거*하는 방식은 빠르게 한계에 부딪힙니다.

| 단순 Job 매니페스트의 한계 | DAG 워크플로 도구가 해결하는 방식 |
|--------------------------|-------------------------------|
| **의존성 표현 불가** — Job A 가 끝나야 Job B 시작? 사람이 `kubectl wait` 로 폴링하거나 cron 시간 차이로 어림짐작 | DAG 의 `dependencies` 필드로 *선언적*. 컨트롤러가 자동으로 다음 task 를 트리거 |
| **재시도 단위가 부정확** — 4단계 중 3번째에서 실패해도 Job 단위로 묶이지 않으면 1단계부터 다시 돌릴 위험 | task 단위 `retryStrategy` — 실패한 단계만 자동 재시도, 앞단 결과는 PVC 에 보존 |
| **시각화 부재** — 어떤 단계가 어디에서 막혔는지 알려면 `kubectl logs` 6번 | argo-server UI 가 task 의존성 그래프를 실시간 색상(Pending/Running/Succeeded/Failed)으로 표시 |
| **재사용 / 파라미터화 부재** — 같은 파이프라인을 모델 A 와 모델 B 로 두 번 돌리려면 매니페스트 두 벌 복사 | 글로벌 `arguments.parameters` + `WorkflowTemplate` 참조. `argo submit -p model=B` 한 줄로 재실행 |

본 코스가 Argo Workflows 를 메인으로 채택한 이유는 두 가지입니다. 첫째는 **K8s 네이티브** — 모든 단계가 Pod 으로 실행되어 Phase 1~3 에서 익힌 자원 요청, RBAC, ConfigMap, Volume 의 지식이 그대로 쓰입니다. 둘째는 **범용성** — Kubeflow Pipelines 가 ML 특화 메타데이터(실험 추적, lineage)를 제공하지만 학습 곡선이 가파르고, 본 코스의 시나리오(RAG 인덱싱, 평가 잡 자동화)는 ML 메타데이터가 거의 필요 없어 Argo 가 더 가볍습니다.

> ℹ️ **언제 Kubeflow Pipelines 가 더 나은가?** 실험 100개 이상 추적, MLflow 연동, GUI 에서 SDK 로 파이프라인 정의 같은 *ML 플랫폼* 단계로 넘어갈 때입니다. 본 토픽 끝의 "더 알아보기" 박스에서 한 줄로 다시 만납니다.

---

## 1. 핵심 개념

### 1-1. Argo Workflows 아키텍처 — 두 개의 컨트롤러

Argo Workflows 는 K8s 위에 *두 개의 Deployment* 와 *5 개의 CRD* 를 추가합니다.

| 컴포넌트 | 역할 |
|--------|------|
| `workflow-controller` | Workflow CRD 를 감시하다가 task 단위로 자식 Pod 을 생성·정리. *없으면 매니페스트만 등록되고 아무것도 안 돌아감* |
| `argo-server` | 웹 UI + REST/GraphQL API. CLI(`argo submit`) 와 UI 둘 다 이쪽으로 붙음 |
| CRD: `Workflow` | 실제 실행 단위. 시작 시각/종료 시각/단계별 상태가 status 에 기록됨 |
| CRD: `WorkflowTemplate` | 재사용 가능한 정의 (네임스페이스 단위). 다른 Workflow 가 `templateRef` 로 참조 |
| CRD: `ClusterWorkflowTemplate` | 클러스터 전역 템플릿 (전 네임스페이스 공용) |
| CRD: `CronWorkflow` | schedule 필드로 주기 실행. 본 토픽 30번 매니페스트에서 사용 |
| CRD: `WorkflowEventBinding` | 외부 이벤트(웹훅 등)로 트리거. 본 토픽 범위 밖 — Argo Events 와 함께 학습 |

설치는 단 한 매니페스트면 끝납니다.

```bash
ARGO_VERSION=v3.5.13   # 본 토픽 작성 시점 stable
kubectl create namespace argo
kubectl apply -n argo -f \
  https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/quick-start-minimal.yaml
```

`quick-start-minimal.yaml` 은 학습용으로 다음을 한 번에 만들어 줍니다.
- `workflow-controller` Deployment
- `argo-server` Deployment (UI + API, 포트 2746)
- argo 네임스페이스의 워크로드용 SA + ClusterRole + RoleBinding
- ArtifactRepository ConfigMap *없음* (production 용 quick-start.yaml 은 MinIO 까지 끌어오는 무거운 버전)

> 💡 **인증 모드 — 학습용 토큰 우회**: 기본은 `client` 모드라 UI 접속 시마다 ServiceAccount 토큰을 입력해야 합니다. 학습 환경에서는 `--auth-mode=server` 로 패치해 토큰 입력을 생략합니다. 운영에서는 SSO 연동을 권장합니다.

```bash
# 학습용 패치 — argo-server 의 args 를 server 모드로 교체
kubectl -n argo patch deploy argo-server --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":["server","--auth-mode=server"]}]'
```

### 1-2. 템플릿 종류와 의존성 표현 — DAG vs Steps, container vs script

Argo 의 핵심 단위는 *template* 입니다. template 한 개가 *재사용 가능한 작업 정의 1개* 에 해당하고, 다음 4가지 유형이 있습니다.

| 유형 | 언제 사용 |
|------|----------|
| `container` | *이미지를 띄워 명령 실행*. 본 코스가 4단계 모두 사용하는 표준 패턴 |
| `script` | template 안에 inline 으로 Python/Bash 적기. 빠른 PoC 용. 학습 단계가 4개 이상이면 이미지로 빼는 게 깔끔 |
| `dag` | template 안에 task 들을 모아 *의존성 그래프*. 본 토픽 메인 |
| `steps` | template 안에 task 들을 *직선 단계*로 나열 (A → B → C). 단순한 파이프라인이면 더 짧게 적힘 |

**DAG vs Steps 의 작은 차이**: 다음 두 매니페스트는 같은 일을 합니다(load → chunk → embed → upsert).

```yaml
# DAG 스타일 — dependencies 필드로 그래프
- name: rag-indexing
  dag:
    tasks:
    - { name: load,   template: pipeline-step }
    - { name: chunk,  template: pipeline-step, dependencies: [load] }
    - { name: embed,  template: pipeline-step, dependencies: [chunk] }
    - { name: upsert, template: pipeline-step, dependencies: [embed] }

# Steps 스타일 — 외부 리스트는 직렬, 내부 리스트는 병렬
- name: rag-indexing
  steps:
  - - { name: load,   template: pipeline-step }
  - - { name: chunk,  template: pipeline-step }
  - - { name: embed,  template: pipeline-step }
  - - { name: upsert, template: pipeline-step }
```

본 토픽은 *DAG* 을 택합니다. 이유는 (a) 캡스톤에서 임베딩 단계를 문서 배치별로 *fan-out 병렬화* 할 가능성이 있고, (b) `dependencies: [load, fetch-metadata]` 처럼 *둘 이상의 선행 단계*를 이름으로 묶기에 DAG 문법이 직관적이기 때문입니다.

### 1-3. 단계 간 데이터 전달 — parameters / artifacts / PVC 비교

DAG 의 task 는 *서로 다른 Pod* 으로 실행됩니다. 한 task 의 컨테이너 안에서 만든 파일은 그 Pod 이 끝나면 사라지므로, 다음 task 가 그 결과를 보려면 *명시적인 전달 메커니즘*이 필요합니다. Argo 는 세 가지를 제공합니다.

| 방식 | 적합한 데이터 | 인프라 요구 | 본 토픽에서 선택? |
|------|------------|-----------|----------------|
| **parameters** | 작은 string (~수 KB). batch-id, 파일 경로, 모델 이름 | 없음 — controller 가 etcd 에 저장 | Hello DAG 시연용으로만 사용 (1-2 의 batch-id) |
| **artifacts** | 파일 (KB ~ GB). 모델 가중치, jsonl 데이터 | `artifactRepository` ConfigMap + MinIO/S3/GCS 버킷 | 사용 안 함 — MinIO 설치를 학습 부담으로 판단 |
| **volumeClaimTemplates** | 파일 (GB+). 단계 사이의 모든 중간 산출물 | 클러스터 default StorageClass (minikube 는 hostpath 자동) | **본 토픽 메인 RAG 파이프라인이 사용** |

PVC 패턴은 다음과 같이 짧습니다.

```yaml
spec:
  volumeClaimTemplates:           # workflow 시작 시 PVC 자동 생성
  - metadata: { name: pipeline-data }
    spec:
      accessModes: ["ReadWriteOnce"]
      resources: { requests: { storage: 2Gi } }
  volumeClaimGC:
    strategy: OnWorkflowCompletion   # workflow 종료 시 PVC 자동 삭제 (etcd 비대 방지)
  templates:
  - name: pipeline-step
    container:
      ...
      volumeMounts:
      - { name: pipeline-data, mountPath: /data }   # 4단계 모두 같은 /data 를 봅니다
```

> 💡 **MinIO artifact 가 더 어울리는 시점**: 단계가 *진짜 병렬* 로 분리된다(다른 노드에서 동시에 실행), 또는 *다른 워크플로우 사이* 에 산출물을 공유한다는 요구가 생기면 PVC 의 `ReadWriteOnce` 한계 때문에 artifact 로 넘어갑니다. 본 토픽의 4단계 직선 DAG 은 모두 같은 노드 같은 PVC 라 RWX 가 필요 없습니다.

### 1-4. ServiceAccount / RBAC — Workflow Pod 도 K8s API 를 부른다

Argo 의 `workflow-controller` 는 controller 입장에서 Pod 을 만듭니다. 그런데 *이미지 안에서 추가로 Pod 을 띄우는 단계* (parallelism, exit handler 등) 가 있으면, **워크플로우 Pod 자체가** Kubernetes API 에 `pods.create` 호출을 합니다. 이 호출은 Pod 의 `serviceAccountName` 권한으로 갑니다.

```yaml
spec:
  serviceAccountName: workflow      # 누락하면 default SA — RBAC 없어 즉시 실패
```

본 토픽 `manifests/01-argo-rbac.yaml` 이 만드는 권한 묶음:

```yaml
- apiGroups: [""]
  resources: ["pods", "pods/exec"]                    # 자식 Pod 생성/조회/감시
  verbs: ["create", "get", "list", "watch", ...]
- apiGroups: [""]
  resources: ["pods/log"]                              # argo logs 가 작동하려면 필요
  verbs: ["get", "list", "watch"]
- apiGroups: ["argoproj.io"]
  resources: ["workflowtaskresults"]                   # 단계 결과 저장 CRD
  verbs: ["create", "get", "list", "watch", ...]
```

`pods is forbidden: User "system:serviceaccount:ml-pipelines:default" cannot create resource pods` 에러가 본 토픽 자주 하는 실수 1번입니다 — 학습자가 *RBAC 매니페스트를 안 적용한 채* `argo submit` 하면 정확히 이 메시지가 뜹니다.

---

## 2. 실습

### 2-1. 사전 준비 — 도구 버전 확인

```bash
# minikube + kubectl
minikube version
# minikube version: v1.34.0+ 권장

kubectl version --client --short

# argo CLI 설치 (macOS)
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

> 💡 **Linux/WSL2 학습자**: `argo-linux-amd64.gz` 로 파일명만 바꿔 같은 절차를 따르면 됩니다.

### 2-2. minikube 기동 + 네임스페이스 / RBAC / Qdrant 적용

```bash
minikube start --cpus=4 --memory=8g
# 메모리 8G 권장 — 임베딩 모델 로딩 + Qdrant 합쳐 6G 안팎

cd course/phase-4-ml-on-k8s/04-argo-workflows
kubectl apply -f manifests/00-namespace.yaml
kubectl apply -f manifests/01-argo-rbac.yaml
kubectl apply -f manifests/02-qdrant.yaml
kubectl get pods -n ml-pipelines
```

**예상 출력:**

```
NAME                      READY   STATUS    RESTARTS   AGE
qdrant-7d6b8fc9c4-x2pbz   1/1     Running   0          30s
```

### 2-3. Argo Workflows 설치 + 인증 모드 패치

```bash
ARGO_VERSION=v3.5.13
kubectl create namespace argo
kubectl apply -n argo -f \
  https://github.com/argoproj/argo-workflows/releases/download/${ARGO_VERSION}/quick-start-minimal.yaml

# argo-server 를 학습용 server auth-mode 로 전환 (토큰 입력 우회)
kubectl -n argo patch deploy argo-server --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":["server","--auth-mode=server"]}]'

kubectl -n argo rollout status deploy/argo-server
kubectl -n argo rollout status deploy/workflow-controller
kubectl -n argo get pods
```

**예상 출력:**

```
NAME                                  READY   STATUS    RESTARTS   AGE
argo-server-xxxxxxxxxx-yyyyy          1/1     Running   0          1m
workflow-controller-xxxxxxxxxx-zzzzz  1/1     Running   0          1m
```

### 2-4. Hello DAG 제출 — fan-out / fan-in 시각화

```bash
argo submit -n ml-pipelines manifests/10-hello-dag-workflow.yaml --watch
```

`--watch` 플래그는 워크플로우의 단계별 상태를 실시간으로 표시합니다. **예상 출력:**

```
Name:                hello-dag-abc12
Namespace:           ml-pipelines
ServiceAccount:      workflow
Status:              Succeeded
Conditions:
 PodRunning          False
 Completed           True
Duration:            22 seconds

STEP                  TEMPLATE          PODNAME                              DURATION
 ✔ hello-dag-abc12   dataset-eda
 ├─✔ prepare         emit-batch-id     hello-dag-abc12-emit-batch-id-1...     5s
 ├─✔ analyze-stats   print-with-batch  hello-dag-abc12-print-with-batch-2...  6s
 ├─✔ analyze-shape   print-with-batch  hello-dag-abc12-print-with-batch-3...  6s
 └─✔ join            print-with-batch  hello-dag-abc12-print-with-batch-4...  5s
```

`analyze-stats` 와 `analyze-shape` 가 *동시에* 시작했다가 둘 다 끝난 뒤 `join` 이 실행되는 모양이 핵심입니다 — DAG 이 fan-out / fan-in 을 어떻게 표현하는지 직접 확인하는 단계입니다.

### 2-5. UI 그래프로 의존성 확인

```bash
kubectl -n argo port-forward svc/argo-server 2746:2746 &
# 브라우저에서 https://localhost:2746 접속 (자체 서명 인증서 경고는 "Advanced > Proceed" 로 우회)
```

UI 의 Workflows 탭에서 방금 제출한 `hello-dag-abc12` 를 클릭하면, 4 task 가 의존성 그래프로 색칠된 모습을 볼 수 있습니다. argo CLI 의 텍스트 트리와 같은 정보를 시각화한 것입니다.

### 2-6. RAG 파이프라인 이미지 빌드 — minikube docker-env

```bash
# 이미지 빌드를 minikube 내부 Docker 데몬에 직접 — push/pull 우회
eval $(minikube docker-env)
docker build -t rag-pipeline:0.1.0 practice/rag_pipeline/
docker images | grep rag-pipeline
```

**예상 출력:**

```
rag-pipeline   0.1.0   abcd1234ef56   30 seconds ago   1.2GB
```

> 💡 **이미지 크기 1.2GB 가 큰가?** torch CPU + sentence-transformers 가 포함되어 있어서 그렇습니다. KServe 의 HuggingFace 런타임도 비슷한 크기입니다. 본 코스에서는 학습 단순성을 우선해 단일 이미지로 4단계를 처리하지만, 운영에서는 단계별로 이미지를 나눠 임베딩 단계만 큰 이미지를 쓰는 패턴도 흔합니다.

### 2-7. RAG 인덱싱 Workflow 제출

```bash
argo submit -n ml-pipelines manifests/20-rag-indexing-workflow.yaml --watch
```

**예상 출력 (요약):**

```
STEP                            TEMPLATE        PODNAME                              DURATION
 ✔ rag-indexing-xxxxx           rag-indexing
 ├─✔ load-docs                  pipeline-step   rag-indexing-xxxxx-...               8s
 ├─✔ chunk                      pipeline-step   rag-indexing-xxxxx-...               12s
 ├─✔ embed                      pipeline-step   rag-indexing-xxxxx-...               45s
 └─✔ upsert                     pipeline-step   rag-indexing-xxxxx-...               6s
```

embed 단계가 가장 오래 걸리는 이유는 *첫 실행에 sentence-transformer 모델 (~90MB) 다운로드* 때문입니다. 같은 PVC 안의 `/data/hf-cache` 에 저장되므로, 같은 워크플로우 안에서 두 번째 task 가 호출하면 캐시 히트입니다.

각 단계의 로그를 보려면:

```bash
argo logs @latest -n ml-pipelines | head -40
```

### 2-8. Qdrant 에서 인덱싱 결과 확인

```bash
kubectl -n ml-pipelines port-forward svc/qdrant 6333:6333 &
sleep 2

# 컬렉션이 만들어졌는지 + 벡터 카운트
curl -s http://localhost:6333/collections/rag-docs | jq '.result | {points_count, config: .config.params.vectors}'
```

**예상 출력:**

```json
{
  "points_count": 18,
  "config": {
    "size": 384,
    "distance": "Cosine"
  }
}
```

`points_count` 는 `sample_docs/` 4개 파일이 chunk-size=512 / overlap=64 로 잘려서 나온 청크 개수입니다 (작은 문서가 많아 12~25 사이로 변동 가능).

검색 한 번 시도:

```bash
# "GPU 자원" 에 가까운 청크 3개 검색 (사전에 같은 임베딩 모델로 query 벡터를 만들어야 정확하지만, 본 토픽은 카운트 확인까지)
curl -s http://localhost:6333/collections/rag-docs/points?limit=3 | jq '.result.points[] | {id, source: .payload.source, text: .payload.text[0:60]}'
```

**예상 출력 (한 청크 예시):**

```json
{
  "id": "f3b8...",
  "source": "01-gpu-on-k8s.md",
  "text": "쿠버네티스의 스케줄러는 기본적으로 GPU 라는 자원을 모릅니다. NVI"
}
```

### 2-9. CronWorkflow 등록 + 수동 트리거

```bash
kubectl apply -f manifests/30-rag-indexing-cron.yaml
argo cron list -n ml-pipelines
```

**예상 출력:**

```
NAMESPACE      NAME                  AGE   LAST RUN   NEXT RUN   SCHEDULE      TIMEZONE
ml-pipelines   rag-indexing-daily    10s   N/A        18h        0 3 * * *     Asia/Seoul
```

학습 중 18시간을 기다릴 수 없으므로 *수동 트리거* 로 같은 정의를 즉시 실행해 봅니다.

```bash
argo submit --from cronwf/rag-indexing-daily -n ml-pipelines --watch
```

CronWorkflow 가 Workflow 를 만드는 패턴이 학습자에게 익숙해지면, 캡스톤에서 *실 운영에서 매일 새 문서가 들어오는 워크로드* 를 그대로 모델링할 수 있습니다.

---

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `argo submit -n ml-pipelines manifests/10-hello-dag-workflow.yaml --watch` 가 4 task 모두 `Succeeded` 로 끝나고 `analyze-stats` / `analyze-shape` 가 동시에 시작한다
- [ ] `argo submit -n ml-pipelines manifests/20-rag-indexing-workflow.yaml --watch` 가 `load-docs → chunk → embed → upsert` 4 task 모두 `Succeeded` 이고 embed 의 duration 이 가장 길다
- [ ] `curl http://localhost:6333/collections/rag-docs` 의 응답 JSON 에서 `points_count >= 10`, `vectors.size == 384`, `vectors.distance == "Cosine"` 모두 만족한다
- [ ] argo-server UI(`https://localhost:2746`) 에서 워크플로우 그래프가 색칠되어 보이고, 한 task 를 클릭하면 *그 Pod 의 로그* 가 패널에 보인다
- [ ] `manifests/01-argo-rbac.yaml` 의 `serviceAccountName: workflow` 줄을 `default` 로 바꿔 다시 제출하면 `pods is forbidden: User ... cannot create resource pods` 메시지가 워크플로우 status 에 찍힌다 (자주 하는 실수 1번 재현)

---

## 4. 정리

```bash
# 본 토픽 리소스
kubectl delete -f manifests/30-rag-indexing-cron.yaml --ignore-not-found
kubectl delete -f manifests/02-qdrant.yaml --ignore-not-found
kubectl delete -f manifests/01-argo-rbac.yaml --ignore-not-found
kubectl delete namespace ml-pipelines --ignore-not-found

# 모든 워크플로우 인스턴스 (이미 ml-pipelines namespace 와 함께 삭제되지만 명시적으로)
argo delete --all -n ml-pipelines 2>/dev/null || true

# argo 컨트롤러
kubectl delete namespace argo

# minikube 자체를 정리할 때
minikube delete
```

---

## 🚨 자주 하는 실수

1. **`serviceAccountName` 누락 또는 default SA 사용** — 워크플로우 status 에 `pods is forbidden: User "system:serviceaccount:ml-pipelines:default" cannot create resource pods` 메시지가 찍히고 진행이 멈춥니다. 원인은 default SA 에 RBAC 이 없기 때문 — `manifests/01-argo-rbac.yaml` 의 `workflow` SA 를 만들고 매니페스트 spec 에 `serviceAccountName: workflow` 한 줄을 반드시 답니다. 클러스터 단위 default 로 두고 싶으면 `kubectl patch sa default -n ml-pipelines ...` 로 default SA 에 권한을 줄 수 있지만, 학습 단계에서는 *전용 SA + 명시적 참조* 가 더 명확합니다.

2. **`spec.entrypoint` 누락** — `argo submit` 시점에 `entrypoint template not specified` 에러가 즉시 떨어집니다. Argo 는 *어느 template 부터 실행할지를 spec.entrypoint 로 받기 때문에*, `templates: [...]` 안에 dag/steps 가 있어도 entrypoint 가 비어 있으면 시작점을 찾지 못합니다. 매니페스트의 가장 흔한 입력 실수 — Workflow 의 가장 첫 줄 spec 바로 아래에 항상 `entrypoint: <template-name>` 을 답니다.

3. **emptyDir 또는 hostPath 로 단계 간 데이터 공유 시도** — 직관적으로는 "단계마다 같은 Pod 안에 있을 것 같으니 emptyDir 면 충분하지 않나" 라고 생각하기 쉽지만, **DAG 의 각 task 는 서로 다른 Pod** 입니다. emptyDir 는 *Pod 수명* 과 묶이므로 다음 task 가 시작될 때 비어 있습니다. 본 토픽의 PVC `volumeClaimTemplates` 패턴(워크플로우 시작 시 자동 생성, 종료 시 자동 삭제) 또는 Argo artifacts (MinIO/S3) 를 사용해야 합니다. 매니페스트 `20-rag-indexing-workflow.yaml` 의 `volumeClaimTemplates` + `volumeClaimGC.strategy: OnWorkflowCompletion` 두 줄이 이 문제를 해결하는 패턴입니다.

---

## 더 알아보기

- [Argo Workflows 공식 문서](https://argo-workflows.readthedocs.io/en/latest/) — Walk-through, CRD 레퍼런스, examples 폴더가 풍부합니다
- [Argo Events](https://argoproj.github.io/argo-events/) — 외부 이벤트(웹훅, S3 PUT, Kafka)로 Workflow 를 트리거. 본 토픽의 CronWorkflow 다음 단계
- [Kubeflow Pipelines vs Argo Workflows](https://www.kubeflow.org/docs/components/pipelines/v1/introduction/) — KFP 가 Argo 위에서 실험 추적 / lineage 를 더한 ML 특화 플랫폼이라는 관계
- [PagedAttention 논문 (vLLM)](https://arxiv.org/abs/2309.06180) — 본 토픽 `sample_docs/03-vllm-llm-serving.md` 가 인덱싱 대상으로 사용한 직전 토픽 자료의 원본

---

## 다음 챕터

➡️ [Phase 4 / 05 — Distributed Training Intro](../05-distributed-training-intro/lesson.md) — KubeRay 와 Kubeflow Training Operator 의 *개념 비교*. 본 토픽의 Argo Workflows 가 *범용 DAG* 이라면, 학습 분산은 *프레임워크 특화 (PyTorch DDP, Ray, JAX)* 로 갈라지는 이유를 정리합니다.
