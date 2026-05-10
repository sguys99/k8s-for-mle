# Day 10 — Helm 통합 + 6 단계 검증 + GKE 정리

> **상위 lesson**: [`../lesson.md`](../lesson.md) §8 Helm 으로 한 줄 배포, §9 검증 시나리오, §10 자주 하는 실수 #28~#30
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 10, §9 검증 시나리오 6 단계
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §3.15 Helm 통합 결정 노트
> **차트**: [`../helm/`](../helm/) (15 파일, 약 1818 줄)
> **이전 단계**: [`day-09-load-test-tuning.md`](day-09-load-test-tuning.md)
> **소요 시간**: 1.5 ~ 2.5 시간 (Step 1~3 ~30 분, dev/prod install ~30 분, §9 6 단계 검증 ~30 분, rollback/uninstall ~10 분, GKE 삭제 + 잔여 자원 점검 ~10 분)

---

## 🎯 Goal

Day 10 을 마치면 다음 4 가지가 충족됩니다.

- **`helm install rag-llm helm/ -f helm/values-prod.yaml ...` 한 줄로 Day 1~9 의 21 매니페스트가 동등 배포** — `helm template` 출력이 raw 매니페스트 21 종과 *기능적으로 같은* 결과를 만듭니다 (네임스페이스/라벨/이미지 모두 일치).
- **라이프사이클 4 명령 직접 실행** — `helm install` (dev → uninstall → prod) → `helm upgrade --set ragApi.config.topK=5` (checksum/config 자동 rollout 검증) → `helm rollback rag-llm 1` → `helm uninstall`.
- **lesson.md §9 의 6 단계 통합 검증 모두 통과** — Workflow Succeeded → vLLM /v1/models → /chat 200 OK + sources 3 → HPA REPLICAS 변동 → Helm 한 줄 재배포 후 §1~§4 재통과 → GKE 클러스터 삭제.
- **GKE 클러스터 삭제 + 잔여 자원 0 확인** — `gcloud container clusters delete capstone --zone us-central1-a --quiet` 후 `gcloud compute addresses list` / `gcloud compute disks list` / `gcloud compute forwarding-rules list` 모두 빈 결과.

---

## 🔧 사전 조건

- **Day 1~9 모든 검증 통과**: 매니페스트 21 종이 클러스터에 적용되어 있고 Day 9 의 1 줄 회귀 없음.
  ```bash
  kubectl get all -n rag-llm | head -30
  # → qdrant-0, vllm, rag-api×2, hpa 2, ingress 1 모두 정상
  INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
  curl -s -o /dev/null -w "%{http_code}\n" -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"ping"}],"top_k":3}' http://$INGRESS/chat
  # → 200
  ```
- **Helm 3.x 설치**:
  - macOS: `brew install helm`
  - Linux: `curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash`
  - 검증: `helm version --short` → `v3.14+`
- **`gcloud` CLI + 권한**: `gcloud auth list` 에 캡스톤 GKE 클러스터 프로젝트의 활성 계정. `roles/container.clusterAdmin` 또는 동등 권한.
- **Docker Hub 본인 계정 이미지 확인**:
  ```bash
  docker pull docker.io/<user>/rag-api:0.1.0      # Day 6 푸시 결과
  docker pull docker.io/<user>/rag-indexer:0.1.0  # Day 3 푸시 결과
  # → manifest 정상 출력
  ```
- **사전 설치된 의존**: kube-prometheus-stack(`prom` release, monitoring ns), Argo controller(argo ns), prometheus-adapter(monitoring ns) — Day 7~8 lab 산출물.
- **GKE 비용 확인**: `gcloud compute instances list` 의 T4 노드 1 노드 + e2-medium 노드 2~3 노드. 일 약 $9 누적 — 본 lab 종료 시 클러스터 삭제 필수.

---

## 🚀 Steps

### Step 1. helm 차트 lint + 렌더링 사전 검증 (~5 분)

**목적**: `helm install` 전에 차트 자체의 문법 오류와 values 누락을 잡습니다.

```bash
cd ~/project/k8s-for-mle/course/capstone-rag-llm-serving

# 1) lint — Chart.yaml + values.yaml + templates/ 문법 점검
helm lint helm/ -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git \
  --set ingress.host=placeholder.nip.io
# → ==> Linting helm/
#    [INFO] Chart.yaml: icon is recommended
#    1 chart(s) linted, 0 chart(s) failed

# 2) template 렌더링 — 실제 K8s 매니페스트로 변환 (kubectl 적용 안 함)
helm template rag-llm helm/ -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git \
  --set ingress.host=placeholder.nip.io \
  > /tmp/rendered.yaml
wc -l /tmp/rendered.yaml
# → 약 700~800 줄 (raw 매니페스트 21 종 합산과 비슷)

grep -c "^kind: " /tmp/rendered.yaml
# → 17~18 (Namespace 1 + Qdrant STS+SVC 2 + vLLM 6 + RAG API 6 + Ingress 1 + Argo RBAC 3 + CronWf 1 + Grafana CM 1 + adapter CM 1)

# 3) raw 매니페스트와 diff 비교 (선택)
helm template rag-llm helm/ -f helm/values-prod.yaml ... | kubectl diff -f - 2>&1 | head -40
# → 차이는 라벨(app.kubernetes.io/* helm 표준 추가) 정도. 본질적 변경 없음
```

> 💡 **`helm lint` 가 통과해도 `helm install` 이 실패할 수 있습니다** — CRD 부재 (CronWorkflow), namespace 충돌 등 *클러스터 상태 의존* 오류는 install 시점에만 검출.

### Step 2. 기존 raw 매니페스트 일괄 삭제 (~5 분)

**목적**: Helm 차트가 *원래 raw 매니페스트와 동등하게 배포할 수 있는가* 를 깔끔히 검증하기 위해 기존 자원을 모두 정리합니다.

```bash
# 백업 — 만약을 대비
kubectl get all,cm,secret,pvc,ing,sm,hpa -n rag-llm -o yaml > /tmp/backup-day10.yaml
wc -l /tmp/backup-day10.yaml
# → 약 1500~2000 줄 (참고용)

# raw 매니페스트 일괄 삭제 (역순)
kubectl delete -f manifests/61-grafana-rag-dashboard.yaml --ignore-not-found
kubectl delete -f manifests/60-prometheus-adapter-values.yaml --ignore-not-found 2>/dev/null || true
kubectl delete -f manifests/35-rag-api-hpa.yaml --ignore-not-found
kubectl delete -f manifests/25-vllm-hpa.yaml --ignore-not-found
kubectl delete -f manifests/34-rag-api-servicemonitor.yaml --ignore-not-found
kubectl delete -f manifests/24-vllm-servicemonitor.yaml --ignore-not-found
kubectl delete -f manifests/40-ingress.yaml --ignore-not-found
kubectl delete -f manifests/33-rag-api-secret.yaml --ignore-not-found
kubectl delete -f manifests/32-rag-api-configmap.yaml --ignore-not-found
kubectl delete -f manifests/31-rag-api-service.yaml --ignore-not-found
kubectl delete -f manifests/30-rag-api-deployment.yaml --ignore-not-found
kubectl delete -f manifests/51-indexing-cronworkflow.yaml --ignore-not-found
kubectl delete -f manifests/49-argo-rbac.yaml --ignore-not-found
kubectl delete -f manifests/23-vllm-hf-secret.yaml --ignore-not-found
kubectl delete -f manifests/22-vllm-service.yaml --ignore-not-found
kubectl delete -f manifests/21-vllm-pvc.yaml --ignore-not-found
kubectl delete -f manifests/20-vllm-deployment.yaml --ignore-not-found
kubectl delete -f manifests/11-qdrant-service.yaml --ignore-not-found
kubectl delete -f manifests/10-qdrant-statefulset.yaml --ignore-not-found
# Namespace 는 helm install 시 그대로 재사용 (PVC 보호) — 또는 명시적 삭제
# kubectl delete -f manifests/00-namespace.yaml --ignore-not-found

kubectl get all -n rag-llm
# → No resources found in rag-llm namespace. (또는 종료 중인 Pod 1~2)
```

> ⚠ **PVC 는 의도적으로 남깁니다** — `qdrant-storage-qdrant-0` (5Gi 인덱스) 와 `vllm-model-cache` (20Gi 모델 캐시) 가 살아있어야 *Helm install 시 두 번째 기동 30 초 cold start* 패턴 검증 가능. PVC 삭제는 §🧹 정리 (B) 에서.

### Step 3. dev install — Helm 흐름 자체 검증 (~5 분)

**목적**: vLLM 비활성 상태에서 Helm 차트가 *오류 없이 install / Pod Ready / 접속 검증* 까지 진행되는지 확인합니다.

```bash
DOCKER_USER=<your-docker-id>
GH_USER=<your-github-id>

helm install rag-llm helm/ -n rag-llm --create-namespace \
  -f helm/values-dev.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git
# → NAME: rag-llm / STATUS: deployed / REVISION: 1 / NOTES: ...

helm list -n rag-llm
# → NAME=rag-llm CHART=capstone-rag-llm-0.1.0 STATUS=deployed REVISION=1

kubectl get pods -n rag-llm -w
# → qdrant-0 Running, rag-api-* Running (replicas=1 — values-dev), vLLM 없음
#    rag-api 의 readiness 가 *vLLM 없이도* /ready 200 (lifespan 완료)

# RAG API /chat 호출 — 503 not_ready 가 *의도된 dev 결과*
kubectl port-forward -n rag-llm svc/rag-api 8001:8001 &
curl -s -X POST http://localhost:8001/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"ping"}],"top_k":3}' | jq
# → {"detail":"vLLM not ready (...)" } 또는 503 — 의도된 dev 결과
#    (Day 7 envFrom 학습 가치를 dev 에서도 살림)

kill %1 2>/dev/null  # port-forward 정리
```

### Step 4. prod install — vLLM + Ingress + HPA 활성 (~10 분)

**목적**: dev release 를 uninstall 하고 prod values 로 재배포 — 이번에는 GPU 노드에 vLLM 배포 + Ingress + HPA + 모니터링 모두 활성.

```bash
helm uninstall rag-llm -n rag-llm
# → release "rag-llm" uninstalled

# 첫 install 은 placeholder host 로 (Step 5 에서 진짜 IP 로 갱신)
helm install rag-llm helm/ -n rag-llm --create-namespace \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git \
  --set ingress.host=placeholder.nip.io
# → NAME: rag-llm / STATUS: deployed / REVISION: 1 / NOTES (Pod Ready 안내 + GKE 비용 경고)

# Pod Ready 대기 — vLLM 첫 기동은 PVC 캐시 hit 시 30~60 초 (Step 2 에서 PVC 보존했으므로)
kubectl get pods -n rag-llm -w
# → qdrant-0 Running, vllm Running (PVC 캐시 hit ~60 초), rag-api-* Running ×2

# checksum/config annotation 확인 — Day 7 #20 자동화 약속 이행
kubectl get deployment rag-api -n rag-llm -o jsonpath='{.spec.template.metadata.annotations.checksum/config}'
# → 16 자리 hex 해시 (예: a3f8b9c2d4e5f6a7)
```

### Step 5. Ingress IP 받은 후 host 갱신 (~5 분)

```bash
# LoadBalancer IP 프로비저닝 ~3~5 분 대기
kubectl get ing rag-api -n rag-llm -w
# → ADDRESS 컬럼이 빈 값 → IP 채워짐 (예: 34.123.45.67)

EXTERNAL_IP=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "External IP: $EXTERNAL_IP"

# helm upgrade 로 host 갱신 — --reuse-values 필수 (자주 하는 실수 #29)
helm upgrade rag-llm helm/ -n rag-llm \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git \
  --set ingress.host=$EXTERNAL_IP.nip.io
# → STATUS: deployed / REVISION: 2

helm history rag-llm -n rag-llm
# → 2 revisions: 1 (placeholder), 2 (real IP)
```

### Step 6. lesson.md §9 6 단계 통합 검증 (~30 분)

**목적**: capstone-plan §9 의 6 단계 검증 시나리오를 *Helm 차트 한 줄 install 결과* 위에서 모두 통과시킵니다.

```bash
INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')

# §1. 인덱싱 Workflow 성공 ───────────────────────────────────────────────
argo submit -n rag-llm --serviceaccount workflow --from cronwf/rag-indexing-daily --watch
# → 5 step DAG (git-clone → load-docs → chunk → embed → upsert) Succeeded ~3~5 분
# Qdrant 컬렉션 확인
kubectl exec -n rag-llm qdrant-0 -- curl -s http://localhost:6333/collections/rag-docs | jq '.result.points_count'
# → 200~300 (본 코스 자료 청크 수)

# §2. vLLM /v1/models ────────────────────────────────────────────────
kubectl port-forward -n rag-llm svc/vllm 8000:8000 &
sleep 3
curl -s http://localhost:8000/v1/models | jq '.data[0].id'
# → "microsoft/phi-2"
kill %1

# §3. RAG end-to-end (1 줄 완료 기준) ──────────────────────────────────
curl -s http://$INGRESS/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' | jq
# → {"answer": "...[1]...[2]...[3]...", "sources": [{...}, {...}, {...}]}
# → status 200, sources 3 개, 인용 마커 [1]/[2]/[3] 포함

# §4. HPA REPLICAS 변동 — Day 9 부하 스크립트 재사용 ─────────────────
chmod +x practice/llm_serving/load_test.sh 2>/dev/null
LABEL=helm-integration INGRESS_HOST=$INGRESS bash practice/llm_serving/load_test.sh &
LOAD_PID=$!
watch kubectl get hpa,pods -n rag-llm
# → rag-api HPA: REPLICAS 2→3→4 변동, vllm HPA: TARGETS 변동 (학습 설계상 1~2)
# Day 9 의 c=8/16/32 3 단계가 자동 진행, 약 3~5 분
wait $LOAD_PID

# §5. Helm 한 줄 재배포 — *uninstall 후 install* 동등성 검증 ─────────
helm uninstall rag-llm -n rag-llm
sleep 30  # 자원 정리 대기 (PVC 는 보존)
helm install rag-llm helm/ -n rag-llm --create-namespace \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git \
  --set ingress.host=$EXTERNAL_IP.nip.io
# → 재install. PVC 캐시 hit 으로 vLLM 30~60 초 ready

kubectl get pods -n rag-llm -w   # 모두 Ready 까지 대기
# §1~§4 재실행 — 동일 결과 통과 확인

# §6. (선택) GKE 클러스터 삭제는 Step 10 에서 일괄 진행
```

### Step 7. ConfigMap 변경 → checksum/config 자동 rollout 검증 (~5 분)

**목적**: Day 7 결정 박스 ④ 의 *Day 10 자동화 약속* 이행 확인.

```bash
# 1) 현재 checksum 기록
BEFORE=$(kubectl get deploy rag-api -n rag-llm -o jsonpath='{.spec.template.metadata.annotations.checksum/config}')
echo "Before: $BEFORE"

# 2) ConfigMap 변경 — TOP_K 3 → 5
helm upgrade rag-llm helm/ -n rag-llm \
  -f helm/values-prod.yaml \
  --set ragApi.image.repository=docker.io/$DOCKER_USER/rag-api \
  --set indexing.imageRepository=docker.io/$DOCKER_USER/rag-indexer \
  --set indexing.gitRepo=https://github.com/$GH_USER/k8s-for-mle.git \
  --set ingress.host=$EXTERNAL_IP.nip.io \
  --set ragApi.config.topK="5"
# → STATUS: deployed / REVISION: 3

# 3) checksum 변경 + rollout 자동 트리거 검증
AFTER=$(kubectl get deploy rag-api -n rag-llm -o jsonpath='{.spec.template.metadata.annotations.checksum/config}')
echo "After: $AFTER"
[ "$BEFORE" != "$AFTER" ] && echo "✅ checksum 변경 — Pod rollout 자동 트리거" || echo "❌ checksum 동일 — 차트 버그"

kubectl rollout status deployment/rag-api -n rag-llm --timeout=120s
# → deployment "rag-api" successfully rolled out

# 4) 새 env 적용 확인
kubectl exec -n rag-llm deploy/rag-api -- env | grep TOP_K
# → TOP_K=5
```

### Step 8. helm rollback 라이프사이클 (~5 분)

```bash
# revision 3 (TOP_K=5) → revision 2 (TOP_K=3 + EXTERNAL_IP) 로 복원
helm rollback rag-llm 2 -n rag-llm
# → Rollback was a success! Happy Helming!

helm history rag-llm -n rag-llm
# → 4 revisions: 1, 2, 3, 4(rollback to 2)
#   4 의 STATUS=deployed, DESCRIPTION="Rollback to 2"

# rollback 후 TOP_K 가 3 으로 복원됐는지 확인
kubectl rollout status deployment/rag-api -n rag-llm --timeout=120s
kubectl exec -n rag-llm deploy/rag-api -- env | grep TOP_K
# → TOP_K=3 (revision 2 의 값)

# /chat 정상 동작
curl -s http://$INGRESS/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"ping"}],"top_k":3}' \
  -o /dev/null -w "%{http_code}\n"
# → 200
```

### Step 9. helm uninstall + namespace 삭제 (~5 분)

```bash
helm uninstall rag-llm -n rag-llm
# → release "rag-llm" uninstalled

# PVC 잔존 확인 (데이터 보호 목적으로 helm uninstall 이 자동 삭제하지 않음)
kubectl get pvc -n rag-llm
# → qdrant-storage-qdrant-0 (5Gi), vllm-model-cache (20Gi) 잔존

# 학습 단계에서는 PVC 도 삭제 (운영 환경에선 데이터 보호)
kubectl delete pvc --all -n rag-llm
kubectl delete namespace rag-llm
# → namespace "rag-llm" deleted

kubectl get all -n rag-llm 2>&1 | head -3
# → Error from server (NotFound): namespaces "rag-llm" not found
```

### Step 10. GKE 클러스터 삭제 + 잔여 자원 0 확인 (~10 분, 필수)

> 🚨 **이 Step 은 *반드시* 실행해야 합니다.** 본 캡스톤의 학습 가치는 *클러스터 통째 삭제 + 잔여 자원 점검* 패턴까지 포함입니다 (자주 하는 실수 #30).

```bash
# 1) 클러스터 삭제 — 5~10 분 소요. 모든 노드/PVC/Service/Ingress 자동 회수
gcloud container clusters delete capstone --zone us-central1-a --quiet
# → Deleting cluster capstone...done.

# 2) 잔여 자원 점검 4 종 (모두 빈 결과여야 함)
gcloud container clusters list                # 0 lines
gcloud compute addresses list                  # 0 lines (External IP)
gcloud compute disks list --filter="zone:us-central1-a"  # 0 lines (PVC 디스크)
gcloud compute forwarding-rules list           # 0 lines (LoadBalancer)
gcloud compute target-pools list               # 0 lines

# 3) GCP Console 직접 확인 (선택 — 자동화 sanity check)
#    Console → VPC network → External IP addresses → "In use" 컬럼이 모두 비었는지
#    Console → Compute Engine → Disks → 본 클러스터의 디스크 잔존 여부
#    Console → Network services → Load balancing → forwarding rules 잔존 여부

# 4) 결제 알림 확인 (캡스톤 시작 전 budget 설정했다면)
#    Console → Billing → Budgets & alerts → 캡스톤 budget 의 실제 사용액
echo "✅ GKE 클러스터 삭제 + 잔여 자원 0 확인 완료"
```

---

## ✅ 검증 체크리스트

- [ ] **Step 1 lint + template 통과**: `helm lint helm/ -f values-prod.yaml ...` 가 0 chart failed. `helm template` 출력이 17~18 kind 매니페스트 렌더.
- [ ] **Step 3 dev install**: `helm list -n rag-llm` STATUS=deployed REVISION=1. RAG API /chat 503 not_ready (의도된 dev 결과).
- [ ] **Step 4 prod install**: vllm/qdrant/rag-api×2 모두 Ready. `kubectl get deploy rag-api -o jsonpath='{...checksum/config}'` 16 자리 hex.
- [ ] **Step 5 Ingress host 갱신**: `helm history` 2 revisions. `$INGRESS` 가 진짜 IP.nip.io 로 표시.
- [ ] **Step 6 §9 6 단계**: §1 Workflow Succeeded + points_count > 0 / §2 vLLM `/v1/models` "microsoft/phi-2" / §3 /chat 200 + sources 3 + 인용 마커 [1][2][3] / §4 HPA REPLICAS 변동 / §5 helm uninstall 후 재install 같은 결과 / §6 보류 (Step 10).
- [ ] **Step 7 checksum 자동 rollout**: ConfigMap topK 변경 후 BEFORE != AFTER, Pod rollout 자동 진행, env TOP_K=5 적용.
- [ ] **Step 8 helm rollback**: `helm history` 4 revisions. rollback 후 TOP_K=3 복원, /chat 200 OK.
- [ ] **Step 9~10 GKE 정리**: namespace 삭제 + `gcloud container clusters delete` + 잔여 자원 4 종 모두 0.

---

## 🧹 정리

> Step 10 까지 완료했다면 GKE 클러스터가 이미 삭제됐습니다. 본 §🧹 는 *Step 10 을 건너뛴 학습자* 용입니다.

### (A) 다음 학습자에게 인계 — 클러스터 유지

캡스톤 자료를 동료/후속 학습자에게 인계하는 경우. 시간당 \$0.35+ 누적 비용을 알려주고:

```bash
helm uninstall rag-llm -n rag-llm
kubectl delete namespace rag-llm
# 노드 풀 size=0 으로 축소 — T4 비용 정지 (cluster management $0.10/h 만 유지)
gcloud container node-pools resize gpu-pool \
  --num-nodes=0 --cluster=capstone --zone=us-central1-a --quiet
```

> ⚠ **클러스터 management 비용은 시간당 ~\$0.10 으로 일 ~\$2.4. 한 달 ~\$72.** 후속 학습자에게 *언제까지 유지할지* 명확한 종료 시점을 합의.

### (B) 본 캡스톤 완전 종료 — Step 10 실행

위 Step 10 의 4 단계(클러스터 삭제 + 잔여 자원 4 종 점검)를 그대로 실행. **본 캡스톤의 권장 분기**입니다.

---

## 🚨 트러블슈팅

| # | 증상 | 원인 | 해결 |
|---|------|------|------|
| 1 | `helm install` 시 `Error: rendered manifests contain a resource that already exists. Unable to continue with install` | Step 2 raw 매니페스트 삭제 누락 — 같은 자원이 *Helm release 외부* 에 이미 존재 | `kubectl delete -f manifests/` 일괄 → 재install. 또는 `--take-ownership` 으로 기존 자원을 release 에 흡수 (Helm 3.14+) |
| 2 | `Error: required value: ingress.host required` | values-prod.yaml 의 `ingress.host: ""` + `--set ingress.host=` 누락 | `--set ingress.host=placeholder.nip.io` 로 첫 install 통과 → Step 5 에서 IP 갱신 (자주 하는 실수 #29) |
| 3 | vLLM Pod 가 영원히 Pending | T4 노드 풀 size=0 (Day 9 종료 시 축소 안 한 채) | `gcloud container node-pools resize gpu-pool --num-nodes=1 --cluster capstone --zone <zone>` 후 5~10 분 대기 |
| 4 | `helm upgrade --set ragApi.config.topK=5` 후에도 RAG API 가 옛 topK | `templates/rag-api.yaml` 의 `checksum/config` annotation 누락 또는 차트 버전 옛 것 | `kubectl describe deployment rag-api -n rag-llm \| grep checksum` 부재 확인 → 차트 templates 갱신 → `helm upgrade` 재실행 (자주 하는 실수 #28) |
| 5 | `helm rollback` 후 `imagePullBackOff` | 이전 revision 의 이미지 태그가 Docker Hub 에서 삭제됨 | `kubectl describe pod rag-api-* \| grep -A 3 Events` 확인 → 이미지 재푸시 또는 `helm upgrade` 로 새 태그 설정 |
| 6 | `argo submit ... --from cronwf/...` 시 `cronworkflows.argoproj.io "rag-indexing-daily" not found` | CronWorkflow CRD 가 클러스터에 등록되지 않음 (Argo controller 사전 설치 누락) | `kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v3.5.7/quick-start-minimal.yaml` 실행 후 5 분 대기 → 재시도 |
| 7 | Grafana 대시보드 미등장 | `monitoring.grafanaDashboard.namespace` 가 Grafana Pod namespace 와 다름 | `kubectl get pods -n monitoring \| grep grafana` 로 namespace 확인 → values-prod.yaml 의 `monitoring.grafanaDashboard.namespace` 동기화 → `helm upgrade` |
| 8 | Step 10 `gcloud compute addresses list` 잔존 IP 1~2 개 | GCE Ingress 가 *Reserved External IP* 를 자동 release 안 함 | `gcloud compute addresses delete <name> --region=us-central1` 명시적 삭제. 또는 GCP Console > VPC network > External IP addresses 에서 직접 release |

---

## ➡ 다음 단계

**캡스톤 완료** 🎉 — 본 lab 까지 마쳤다면 Day 1~10 모든 검증 통과 + GKE 클러스터 정리 완료입니다.

다음 학습 분기:

- **Phase 5 (선택)** — Operator, Service Mesh, GitOps, 멀티 클러스터로 심화. 본 차트가 ArgoCD 의 *Application* 으로 자동 sync 되는 흐름이 다음 학습 지점.
- **자기 업무 적용** — 회사 모델/데이터로 같은 아키텍처 재구성. 본 차트의 *2 줄 변경* (`vllm.modelName` + `ragApi.config.embedModel`) 으로 시작.

캡스톤 완료 회고 체크리스트는 [`../lesson.md`](../lesson.md) §12 에 8 항목 — 학습자 본인 메모로 보관 권장.
