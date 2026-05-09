# Day 7 — ConfigMap/Secret 분리 + ServiceMonitor

> **상위 lesson**: [`../lesson.md`](../lesson.md) §4.4 RAG API Deployment(env 분리 효과 비교 표), §4.8 ConfigMap/Secret 해설, §4.9 ServiceMonitor 해설, §6 모니터링 핵심 메트릭
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 7
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §3.12 모니터링 결정 노트, §5 모니터링 핵심 메트릭 표
> **이전 단계**: [`day-06-rag-api-deploy.md`](day-06-rag-api-deploy.md)
> **소요 시간**: 1.5 ~ 2.5 시간 (ConfigMap/Secret 적용 10 분, Deployment 리팩토링 + rollout 5~10 분, kube-prometheus-stack 설치 5~10 분, ServiceMonitor 적용 + Targets UP 검증 15 분, PromQL 쿼리 검증 15 분, 정리 5 분)

---

## 🎯 Goal

Day 7 을 마치면 다음 4 가지가 충족됩니다.

- Day 6 의 `30-rag-api-deployment.yaml` env 6 종을 **ConfigMap 32 + Secret 33 으로 분리**하고 `envFrom` 일괄 주입으로 리팩토링합니다. ConfigMap 변경 시 Pod 가 *자동 재시작되지 않는다는 사실* 을 직접 체험합니다 (자주 하는 실수 #20).
- **kube-prometheus-stack** 을 `monitoring` namespace 에 설치 (Phase 3-02 values 재사용) → Prometheus + Alertmanager + Grafana + node-exporter + kube-state-metrics 가 한 번에 배포됩니다.
- **ServiceMonitor 24 (vLLM) + 34 (RAG API)** 적용 후 Prometheus UI Targets 페이지에서 두 서비스가 모두 **UP** 상태로 표시됩니다.
- PromQL `rate(rag_chat_total[1m])` 쿼리에 Day 6 부하가 그래프로 보이고, `vllm:num_requests_running` 으로 vLLM 동시 요청 수를 직접 확인할 수 있습니다.

---

## 🔧 사전 조건

- **Day 6 완료**: Deployment 30 + Service 31 + Ingress 40 적용 후 `curl http://<IP>.nip.io/chat` 200 OK 통과.
  ```bash
  kubectl get pod,svc,ing -n rag-llm
  # → rag-api Pod 2/2 Running, Service rag-api ClusterIP, Ingress rag-api 외부 IP 부여
  ```
- **`/metrics` 엔드포인트 노출 확인** (Day 5 의 main.py 가 prometheus_client 메트릭 4 종 + `/metrics` 라우트 등록):
  ```bash
  kubectl port-forward -n rag-llm svc/rag-api 8001:8001 &
  curl -s http://localhost:8001/metrics | grep -E '^rag_(chat|retrieve|llm)_' | head -5
  # → rag_chat_total{status="ok"} 등 metric 라인 출력
  kill %1
  ```
- **helm CLI 설치**: `helm version --short` 결과가 v3.x.x. Phase 3-02 lab 을 진행했다면 이미 설치됨.
- **monitoring namespace 권한**: GKE 사용자가 `monitoring` namespace 를 생성·수정할 수 있어야 합니다 (캡스톤 클러스터 owner 권한이면 자동).
- **기존 prometheus 설치 점검** (Phase 3-02 lab 을 한 학습자에게 중요):
  ```bash
  helm list -A | grep prom || echo "no prom release"
  # → "no prom release" 이면 본 lab 의 Step 5 그대로 진행
  # → 이미 release 가 있으면 본 lab 은 reuse 또는 uninstall 후 재설치 (트러블슈팅 #6)
  ```

> 💰 **GKE 비용 박스 (꼭 읽기)**
>
> - **kube-prometheus-stack 자원**: Prometheus(2Gi mem) + Alertmanager(256Mi) + Grafana(256Mi) + node-exporter(daemonset) + kube-state-metrics(128Mi) 합계 **약 2.5~3GB 메모리**. 기존 `capstone` 클러스터의 e2-medium CPU 노드(4GB) 한 대로는 빠듯할 수 있습니다.
> - **부족 시 대응**: ① Phase 3-02 의 `values.yaml` retention 2 일 + Alertmanager 비활성 설정을 그대로 사용 (이미 본 lab 의 -f 인자에 들어 있음). ② 그래도 부족하면 노드 풀 1 노드 추가 — `gcloud container clusters resize capstone --num-nodes=2`.
> - **Ingress 비용**: Day 6 의 forwarding rule 은 그대로 유지됩니다 (시간당 \$0.025). Day 7 작업 약 2 시간 추가로 약 \$0.05.
> - **Day 7 종료 시**: 본 Day 의 Prometheus 자원은 Day 8 (Grafana 대시보드 + HPA) 에서 즉시 사용되므로 *지우지 않는 것* 이 자연스럽습니다. 휴식 시간이 길면(반나절 이상) §🧹 정리 분기 (B) 로 `helm uninstall prom` 후 다음 Day 재설치.

---

## 🚀 Steps

### Step 1. Day 6 인계 + 매니페스트 4 종 사전 검토

Day 7 의 매니페스트 4 종을 한 번 미리 봅니다 — 본 lab 의 모든 변경이 어디로 가는지 한눈에 파악.

```bash
ls course/capstone-rag-llm-serving/manifests/{32,33,24,34}-*.yaml
```

**예상 출력**:

```
course/capstone-rag-llm-serving/manifests/24-vllm-servicemonitor.yaml
course/capstone-rag-llm-serving/manifests/32-rag-api-configmap.yaml
course/capstone-rag-llm-serving/manifests/33-rag-api-secret.yaml
course/capstone-rag-llm-serving/manifests/34-rag-api-servicemonitor.yaml
```

번호의 의미: 30 번대(rag-api 컴포넌트)에서 32(ConfigMap) + 33(Secret) + 34(ServiceMonitor) 가 *추가* 되고, 20 번대(vLLM 컴포넌트)에서는 24(ServiceMonitor) 가 *추가* 됩니다. Deployment 30 은 본 Day 에 *리팩토링* 만 — 새 파일은 아닙니다.

### Step 2. ConfigMap 32 + Secret 33 적용

먼저 ConfigMap/Secret 을 적용합니다. **순서가 중요합니다** — Deployment 30 (다음 Step 3) 가 envFrom 으로 두 리소스를 참조하기 때문에, 두 리소스가 *없는 상태로* Deployment 를 재기동하면 Pod 가 `CreateContainerConfigError` 로 실패합니다.

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/32-rag-api-configmap.yaml
kubectl apply -f course/capstone-rag-llm-serving/manifests/33-rag-api-secret.yaml
```

**예상 출력**:

```
configmap/rag-api-config created
secret/rag-api-secrets created
```

ConfigMap 의 6 키와 Secret 의 1 키를 한 화면에서 확인:

```bash
kubectl get cm rag-api-config -n rag-llm -o jsonpath='{.data}' | jq
kubectl get secret rag-api-secrets -n rag-llm -o jsonpath='{.data}' | jq 'keys'
```

**예상 출력**:

```json
{
  "EMBED_MODEL": "intfloat/multilingual-e5-small",
  "LLM_BASE_URL": "http://vllm.rag-llm.svc.cluster.local:8000/v1",
  "LLM_MODEL": "microsoft/phi-2",
  "QDRANT_COLLECTION": "rag-docs",
  "QDRANT_URL": "http://qdrant.rag-llm.svc.cluster.local:6333",
  "TOP_K": "3"
}
[
  "HF_TOKEN"
]
```

Secret 의 `data` 출력은 base64 인코딩된 placeholder 입니다 — `stringData` 로 입력해도 읽을 때는 항상 `data` 형태로 base64 인코딩되어 나옵니다 (자주 하는 실수 #21).

### Step 3. Deployment 30 리팩토링 + 적용

본 캡스톤 매니페스트 30 은 *이미* envFrom 패턴으로 리팩토링되어 있습니다. 변경 사항을 git diff 로 확인 후 그대로 적용:

```bash
# 만약 Day 6 시점의 30-rag-api-deployment.yaml 이 git 에 커밋된 채 남아 있다면 diff 로 확인
git log -p course/capstone-rag-llm-serving/manifests/30-rag-api-deployment.yaml | head -60

# 본 캡스톤 자료의 현재 상태(envFrom 리팩토링 완료) 적용
kubectl apply -f course/capstone-rag-llm-serving/manifests/30-rag-api-deployment.yaml
```

**예상 출력**:

```
deployment.apps/rag-api configured
```

Day 6 → Day 7 의 핵심 차이를 매니페스트에서 직접 확인:

```bash
kubectl get deploy rag-api -n rag-llm -o yaml | grep -A 8 "envFrom\|^[[:space:]]*env:"
```

**예상 출력** (envFrom 1 블록만 — env 6 종 사라짐):

```yaml
        envFrom:
        - configMapRef:
            name: rag-api-config
        - secretRef:
            name: rag-api-secrets
            optional: true
```

### Step 4. ⚠ 수동 재시작 + 새 env 적용 검증

Deployment spec 자체가 변경됐으면 `kubectl apply` 가 자동으로 rollout 을 트리거하지만, **ConfigMap/Secret 만 수정**한 시나리오에서는 Pod 가 자동 재시작되지 않습니다 (자주 하는 실수 #20). 본 Step 은 Day 7 → Day 10 사이에 ConfigMap 만 손볼 때마다 반복할 명령입니다.

```bash
kubectl rollout restart deployment/rag-api -n rag-llm
kubectl rollout status deployment/rag-api -n rag-llm --timeout=5m
```

**예상 출력**:

```
deployment.apps/rag-api restarted
Waiting for deployment "rag-api" rollout to finish: 1 out of 2 new replicas have been updated...
...
deployment "rag-api" successfully rolled out
```

새 Pod 의 env 가 ConfigMap/Secret 에서 주입됐는지 확인:

```bash
kubectl exec -n rag-llm deploy/rag-api -- env | grep -E '^(QDRANT|EMBED|LLM|TOP_K|HF)' | sort
```

**예상 출력** (HF_TOKEN 은 placeholder 라 길이만 확인):

```
EMBED_MODEL=intfloat/multilingual-e5-small
HF_TOKEN=REPLACE_WITH_YOUR_HF_TOKEN_OR_LEAVE_EMPTY
LLM_BASE_URL=http://vllm.rag-llm.svc.cluster.local:8000/v1
LLM_MODEL=microsoft/phi-2
QDRANT_COLLECTION=rag-docs
QDRANT_URL=http://qdrant.rag-llm.svc.cluster.local:6333
TOP_K=3
```

Day 6 의 검증 1 줄 완료 기준이 *여전히 통과* 하는지 확인 (env 분리가 회귀를 일으키지 않았다는 검증):

```bash
INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
curl -s http://$INGRESS/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' \
  | jq '{answer: .answer | .[0:80], sources_n: (.sources | length)}'
```

**예상 출력**:

```json
{
  "answer": "K8s 에서 GPU 를 사용하려면 Pod spec 의 resources.limits 에 nvidia.com/gpu: 1 ...",
  "sources_n": 3
}
```

### Step 5. kube-prometheus-stack 설치

Phase 3-02 의 values.yaml 을 그대로 재사용합니다 (retention 2 일 + Alertmanager 비활성 — 학습용 경량 설정).

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install prom prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f course/phase-3-production/02-prometheus-grafana/manifests/kube-prometheus-stack/values.yaml \
  --version 60.0.0 \
  --wait --timeout 10m
```

**예상 출력 (마지막 줄)**:

```
NAME: prom
LAST DEPLOYED: ...
NAMESPACE: monitoring
STATUS: deployed
REVISION: 1
NOTES:
kube-prometheus-stack has been installed. Check its status by running:
  kubectl --namespace monitoring get pods -l "release=prom"
```

설치된 Pod 들이 모두 Running 인지 확인:

```bash
kubectl get pod -n monitoring -l release=prom
kubectl get prometheus,alertmanager -n monitoring
```

**예상 출력 (각각)**:

```
NAME                                                   READY   STATUS    RESTARTS   AGE
prom-kube-prometheus-stack-operator-xxx                1/1     Running   0          2m
prom-kube-state-metrics-xxx                            1/1     Running   0          2m
prom-prometheus-node-exporter-xxx                      1/1     Running   0          2m
prom-grafana-xxx                                       3/3     Running   0          2m

NAME                                                          VERSION   REPLICAS
prometheus.monitoring.coreos.com/prom-kube-prometheus-stack   2.55.0    1
```

> 💡 본 lab 은 Alertmanager 를 values.yaml 에서 비활성화한 설정을 사용해 자원을 절약합니다. Day 8 에서 알림 시나리오를 다룰 때 활성화합니다.

### Step 6. ServiceMonitor 24 + 34 적용

Prometheus CRD 가 등록된 *이후* 에 ServiceMonitor 매니페스트를 적용해야 합니다 (Step 5 가 선행).

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/24-vllm-servicemonitor.yaml
kubectl apply -f course/capstone-rag-llm-serving/manifests/34-rag-api-servicemonitor.yaml
```

**예상 출력**:

```
servicemonitor.monitoring.coreos.com/vllm created
servicemonitor.monitoring.coreos.com/rag-api created
```

두 ServiceMonitor 가 라벨 매칭 2 단계를 통과하는지 확인 (자주 하는 실수 #19):

```bash
# (1) Prometheus CR 의 selector 확인 — `release: prom` 이 본 ServiceMonitor 의 라벨과 매칭
kubectl get prometheus -n monitoring -o jsonpath='{.items[0].spec.serviceMonitorSelector}' | jq

# (2) ServiceMonitor 의 labels 확인 — release: prom 이 있는지
kubectl get servicemonitor -n rag-llm -o jsonpath='{.items[*].metadata.labels}' | jq
```

**예상 출력 (각각)**:

```json
{ "matchLabels": { "release": "prom" } }
```

```json
{ "app": "vllm", "component": "llm-serving", "release": "prom" }
{ "app": "rag-api", "component": "rag-api", "release": "prom" }
```

### Step 7. Prometheus UI 에서 Targets UP 검증

```bash
kubectl port-forward -n monitoring svc/prom-kube-prometheus-stack-prometheus 9090:9090 &
sleep 2
echo "Open: http://localhost:9090/targets"
```

브라우저에서 `http://localhost:9090/targets` 열고 다음 두 그룹이 **UP** 상태인지 확인:

- `serviceMonitor/rag-llm/rag-api/0` — instances 2/2 (replicas=2 라 endpoints 2 개)
- `serviceMonitor/rag-llm/vllm/0` — instances 1/1

CLI 로도 검증:

```bash
curl -s http://localhost:9090/api/v1/targets \
  | jq '.data.activeTargets[] | select(.labels.namespace=="rag-llm") | {job: .labels.job, health: .health}'
```

**예상 출력**:

```json
{ "job": "vllm", "health": "up" }
{ "job": "rag-api", "health": "up" }
{ "job": "rag-api", "health": "up" }
```

### Step 8. PromQL 쿼리로 메트릭 검증

먼저 RAG API 에 약간의 부하를 발사 (메트릭 카운터를 0 → N 으로 올리기 위함):

```bash
INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
for i in {1..5}; do
  curl -s -o /dev/null -w "[$i] %{http_code}\n" \
    http://$INGRESS/chat \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"Service 와 Ingress 의 차이"}],"top_k":3}'
  sleep 2
done
```

Prometheus UI Graph 탭에서 다음 4 가지 PromQL 을 한 번씩 실행:

```promql
# (1) RAG API 호출 수 — Counter 증가 확인
rate(rag_chat_total[1m])

# (2) RAG API end-to-end latency p95
histogram_quantile(0.95, sum(rate(rag_chat_latency_seconds_bucket[5m])) by (le))

# (3) vLLM 현재 동시 처리 중인 요청 수
vllm:num_requests_running

# (4) Day 8 HPA 가 사용할 후보 — 모든 namespace=rag-llm 의 up 상태
up{namespace="rag-llm"}
```

**예상 결과**:

- (1) Step 8 부하 발사 직후 라인이 0 → 0.0833 (5/60sec) 으로 상승
- (2) 1.0 ~ 5.0 (초) — Day 9 부하 테스트 전 baseline
- (3) 0 또는 1 (단일 요청 처리 중)
- (4) 모두 1 — `rag-api` 2 instance + `vllm` 1 instance + `qdrant` 0 instance (Qdrant ServiceMonitor 미적용 — 본 lab 부록 참고)

port-forward 종료:

```bash
kill %1 2>/dev/null
```

---

## ✅ 검증 체크리스트

다음 8 항목이 모두 통과해야 Day 7 완료입니다.

- [ ] **(1) ConfigMap + Secret 적용**: `kubectl get cm,secret -n rag-llm rag-api-config rag-api-secrets` 결과 두 줄, ConfigMap DATA=6 / Secret TYPE=Opaque
- [ ] **(2) Deployment env 새 값**: `kubectl exec deploy/rag-api -- env | grep QDRANT_URL` 결과 `qdrant.rag-llm.svc.cluster.local:6333` (ConfigMap 의 값과 동일)
- [ ] **(3) Pod rollout 성공**: `kubectl rollout status deploy/rag-api -n rag-llm` 결과 `successfully rolled out`
- [ ] **(4) end-to-end /chat 회귀 없음**: `curl http://<INGRESS>/chat ...` 200 OK + sources 3 개 (Day 6 의 1 줄 완료 기준 그대로 통과)
- [ ] **(5) kube-prometheus-stack 설치**: `kubectl get prometheus,alertmanager -n monitoring` 결과 1 건씩, replicas READY
- [ ] **(6) ServiceMonitor 2 종 등록**: `kubectl get servicemonitor -n rag-llm` 결과 2 건 (vllm, rag-api), 모두 `release=prom` 라벨
- [ ] **(7) Prometheus Targets UP**: `curl /api/v1/targets ... | jq '... | .health'` 결과 vllm/rag-api 모두 `up`
- [ ] **(8) PromQL 쿼리 결과 0 이상**: Step 8 의 (1) `rate(rag_chat_total[1m])` 가 부하 발사 후 라인 표시

---

## 🧹 정리

본 Day 종료 분기 2 개 — 자신의 일정에 맞게 선택.

### (A) Day 8 까지 그대로 유지 (권장)

**Day 8 (Grafana 대시보드 + HPA)** 가 본 Day 의 Prometheus 자원을 *그대로 사용* 하므로 정리하지 않는 것이 자연스럽습니다. 휴식 시간 1~2 시간이면 그대로 두고, 반나절 이상이면 다음 (B) 로 분기.

```bash
# 비용 모니터링 — Ingress 외부 IP 가 살아 있는지 확인 (Day 6 비용 박스)
kubectl get ing -n rag-llm
gcloud compute addresses list 2>/dev/null | grep -E '(rag|capstone)' || echo "no extra addresses"
```

### (B) Day 7 단독 종료 + 비용 절감

장기간 (반나절 이상) 멈출 때 — Prometheus 자원이 무거우니 helm uninstall 로 즉시 회수.

```bash
# (1) ServiceMonitor 2 종 삭제 (CRD 가 사라지기 *전* 에)
kubectl delete servicemonitor vllm rag-api -n rag-llm

# (2) kube-prometheus-stack uninstall (Prometheus + Alertmanager + Grafana + node-exporter + kube-state-metrics)
helm uninstall prom -n monitoring

# (3) namespace 자체도 정리 (선택)
kubectl delete namespace monitoring

# (4) ConfigMap/Secret 도 지울지는 선택 — 그대로 두면 Day 8 재시작 시 envFrom 정합 유지됨
# kubectl delete cm rag-api-config -n rag-llm
# kubectl delete secret rag-api-secrets -n rag-llm

# (5) Day 6 Ingress 도 비용 절감하려면 추가 정리 (Day 6 §🧹 정리 (B) 와 동일)
# kubectl delete ingress rag-api -n rag-llm
```

> ⚠ **(B) 분기 후 Day 8 재시작 시**: Step 5 ~ 6 을 다시 실행하고, ConfigMap/Secret 도 삭제했다면 Step 2 까지 거슬러 올라가 재적용 후 `kubectl rollout restart deploy/rag-api` 가 필요합니다.

---

## 📎 부록 — Qdrant ServiceMonitor 추가 패턴 (선택)

본 lab 에서는 vLLM + RAG API 2 종 ServiceMonitor 만 작성하고 Qdrant 는 *의도적으로 제외* 했습니다 (architecture.md §3.12.3 결정 노트 참고). 학습자가 직접 추가하고 싶다면 다음 패턴:

```yaml
# manifests/35-qdrant-servicemonitor.yaml (예시 — 본 캡스톤에는 미포함)
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: qdrant
  namespace: rag-llm
  labels: { app: qdrant, component: vector-db, release: prom }
spec:
  selector:
    matchLabels: { app: qdrant }
  endpoints:
    - port: http                    # ⚠ 11-qdrant-service.yaml 에 named port 추가 선행 필요
      path: /metrics
      interval: 30s
```

선결 조건: `manifests/11-qdrant-service.yaml` 의 ports 에 `name: http` 추가 (현재 캡스톤 매니페스트는 미선언). Day 10 Helm 차트의 `templates/monitoring.yaml` 에서 vllm + rag-api + qdrant 3 종이 통합되어 정식 도입됩니다.

---

## 🚨 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| **#1** `kubectl apply` 후 Pod 가 `CreateContainerConfigError` 로 실패 | ConfigMap 32 또는 Secret 33 이 *없는 상태* 로 envFrom 적용 | Step 2 의 ConfigMap/Secret 적용을 *먼저*, 그 후 Deployment 재기동. `kubectl describe pod` 로 `couldn't find key` 또는 `configmap "rag-api-config" not found` 메시지 확인 |
| **#2** ConfigMap 수정했는데 RAG API 가 옛값 사용 | ConfigMap/Secret 변경은 Pod 자동 재시작 안 함 (자주 하는 실수 #20) | `kubectl rollout restart deployment/rag-api -n rag-llm` 수동 실행. Day 10 Helm 의 `checksum/config` annotation 으로 자동화 예고 |
| **#3** Prometheus Targets 페이지에 RAG API 가 *안 보임* | ServiceMonitor 의 `release: prom` 라벨 누락 → Prometheus CR 의 `serviceMonitorSelector` 매칭 실패 (자주 하는 실수 #19) | `kubectl get servicemonitor rag-api -n rag-llm -o jsonpath='{.metadata.labels}'` 출력에 `release: prom` 있는지 확인. 누락 시 매니페스트 수정 후 재apply |
| **#4** Targets 페이지에 RAG API 보이지만 `DOWN` + `connection refused` | Service 31 의 named port `http` 미선언 또는 Pod `/metrics` 엔드포인트 미응답 | Step 7 의 `port-forward + curl /metrics` 로 직접 확인. 또는 `kubectl get svc rag-api -n rag-llm -o jsonpath='{.spec.ports[*].name}'` 결과가 `http` 인지 확인 (자주 하는 실수 #16) |
| **#5** `kubectl exec deploy/rag-api -- env` 에 `HF_TOKEN` 없음 | Secret 33 미적용 + `optional: true` → 정상 동작 | 의도된 결과. e5-small public 모델은 토큰 없이도 다운로드 가능 |
| **#6** `helm install prom ...` 결과 `Error: cannot re-use a name that is still in use` | Phase 3-02 에서 이미 `prom` release 가 monitoring 외 다른 namespace 에 있음 | `helm list -A | grep prom` 으로 위치 확인. 옵션 A) 기존 release 그대로 재사용 — Step 6 만 진행 (CRD 는 클러스터 전역) / 옵션 B) `helm uninstall prom -n <namespace>` 후 재설치 |
| **#7** `data` vs `stringData` 혼동으로 Pod 가 *깨진 토큰* 받음 | Secret 매니페스트에 `data: HF_TOKEN: hf_xxx` 처럼 평문 입력 | `data` 는 base64 인코딩 값, 평문은 `stringData` 사용 (자주 하는 실수 #21). 또는 `kubectl create secret generic rag-api-secrets --from-literal=HF_TOKEN=hf_xxx -n rag-llm --dry-run=client -o yaml \| kubectl apply -f -` |
| **#8** kube-prometheus-stack Pod 가 `Pending` (Insufficient memory) | e2-medium 노드 1 대로는 Prometheus 가 너무 큼 (≈ 2.5GB 추가) | `gcloud container clusters resize capstone --num-nodes=2 --zone <zone>` 으로 노드 1 추가. 또는 values.yaml 의 `prometheus.prometheusSpec.resources.requests.memory` 를 1Gi 로 축소 |

---

## ➡ 다음 Day

[`day-08-grafana-hpa.md`](day-08-grafana-hpa.md) (작성 예정) — Grafana 대시보드 작성 + prometheus-adapter 로 커스텀 메트릭 HPA 구성.

본 Day 에서 ServiceMonitor 가 *수집한 메트릭* 이 Day 8 의 모든 작업의 입력이 됩니다.
