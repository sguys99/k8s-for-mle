# Day 8 — Grafana 대시보드 + HPA (커스텀 메트릭)

> **상위 lesson**: [`../lesson.md`](../lesson.md) §6 모니터링 메트릭, §7 HPA 커스텀 메트릭
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 8
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §3.13 HPA 결정 노트, §5 모니터링 메트릭 표
> **이전 단계**: [`day-07-config-secret-monitoring.md`](day-07-config-secret-monitoring.md)
> **소요 시간**: 1.5 ~ 2.5 시간 (Grafana 접속 점검 5 분, 대시보드 ConfigMap 적용 + import 확인 10 분, prometheus-adapter 설치 + 메트릭 노출 검증 15 분, HPA 적용 + TARGETS 안정화 10 분, hey 부하 트리거 + REPLICAS 변동 관측 15 분, Grafana 패널 동시 변동 확인 10 분, 정리 5 분)

---

## 🎯 Goal

Day 8 을 마치면 다음 4 가지가 충족됩니다.

- **Grafana 대시보드 자동 import** — `61-grafana-rag-dashboard.yaml` ConfigMap 의 `grafana_dashboard: "1"` 라벨을 Day 7 의 `prom-grafana` sidecar 가 watch 해 *Pod 재시작 없이* `RAG-LLM Capstone` 대시보드 4 패널이 등장합니다.
- **prometheus-adapter** 가 Day 7 의 ServiceMonitor 가 수집한 메트릭을 K8s `custom.metrics.k8s.io` API 로 노출 → `kubectl get --raw` 로 `pods/rag_chat_requests_per_second` 와 `pods/vllm_num_requests_running` 두 줄을 확인할 수 있습니다.
- **HPA 25 + 35 적용** 후 `kubectl get hpa -n rag-llm` 의 TARGETS 칼럼이 `<unknown>` 이 아닌 실수치(`0/8`, `0/10`) 를 보여줍니다.
- **hey 60s 부하 후 REPLICAS 변동** — RAG API 가 2→4 로 증가하고 vLLM 은 1→2 (두 번째 Pod 는 T4 노드 풀 size=1 제약으로 *Pending 상태가 정상*).

---

## 🔧 사전 조건

- **Day 7 완료**: Prometheus Targets 페이지에 vllm + rag-api 가 모두 UP 상태. ServiceMonitor 24/34 가 라벨 매칭 통과.
  ```bash
  kubectl get servicemonitor -n rag-llm
  # → vllm + rag-api 두 줄, 모두 release=prom 라벨
  kubectl get pods -n monitoring -l release=prom | head -5
  # → prom-grafana / prom-kube-prometheus-stack-prometheus / prom-kube-state-metrics 등 Running
  ```
- **`hey` CLI 설치**: 학습자 PC 에 부하 도구 — 3 옵션 중 택 1.
  - macOS: `brew install hey`
  - Linux: `go install github.com/rakyll/hey@latest`
  - 클러스터 안 실행: Phase 3-03 의 `hey-job.yaml` 패턴 (대안)
- **`helm` CLI 설치**: Day 7 와 동일 — `helm version --short` 결과가 v3.x.x.
- **Day 6 Ingress 살아 있음**: 부하 트리거를 외부 endpoint 로 발사해야 RAG API 의 `rag_chat_total` 이 증가.
  ```bash
  kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}'
  # → <외부IP>.nip.io 형태의 host (Day 6 결정)
  ```
- **Day 6 1 줄 완료 기준 회귀 없음**: Day 7 종료 시점에서 한 번 검증.
  ```bash
  INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
  curl -s http://$INGRESS/chat \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"ping"}],"top_k":3}' \
    -o /dev/null -w "%{http_code}\n"
  # → 200
  ```

> 💰 **GKE 비용 박스 (꼭 읽기)**
>
> - **prometheus-adapter 자원**: Pod 1 개 (~64MiB memory) — 학습 환경에서 무시 가능 수준.
> - **부하 트리거 시간**: hey 60s 부하 1~2 회 + REPLICAS 변동 관측 5 분 = vLLM 노드 풀 추가 부담 약 5 분 (\$0.029).
> - **Day 8 종료 시**: HPA 25/35 + adapter 는 Day 9 부하 테스트가 *그대로 사용* 하므로 정리하지 않는 것이 자연스럽습니다. 휴식 시간이 길면(반나절 이상) §🧹 정리 분기 (B) 로 정리.
> - **GPU 노드 풀**: vLLM HPA 가 maxReplicas=2 라 노드 풀 1 대 환경에서는 추가 노드 비용이 *발생하지 않습니다* (두 번째 Pod 는 Pending). 이 자체가 학습 포인트.

---

## 🚀 Steps

### Step 1. Day 7 인계 + 매니페스트 4 종 사전 검토

Day 8 의 매니페스트 4 종을 한 번 미리 봅니다 — 본 lab 의 모든 변경이 어디로 가는지 한눈에 파악.

```bash
ls course/capstone-rag-llm-serving/manifests/{25,35,60,61}-*.yaml
```

**예상 출력**:

```
course/capstone-rag-llm-serving/manifests/25-vllm-hpa.yaml
course/capstone-rag-llm-serving/manifests/35-rag-api-hpa.yaml
course/capstone-rag-llm-serving/manifests/60-prometheus-adapter-values.yaml
course/capstone-rag-llm-serving/manifests/61-grafana-rag-dashboard.yaml
```

번호의 의미: 20 번대(vLLM 컴포넌트)에서 25(HPA), 30 번대(rag-api 컴포넌트)에서 35(HPA) 가 *추가* 되고, 60/61 은 *클러스터 전역 모니터링 인프라* (monitoring namespace) 입니다.

> ⚠ `60-` 은 `kubectl apply` 대상이 아닌 **Helm values** 입니다. Step 3 에서 `helm install -f` 로 사용.

### Step 2. Grafana 접속 점검 + 대시보드 ConfigMap 적용

먼저 Day 7 에서 띄운 Grafana 가 살아 있는지 확인하고 admin 비밀번호를 추출합니다.

```bash
# Grafana Pod Running 확인
kubectl get pod -n monitoring -l app.kubernetes.io/name=grafana

# admin 비밀번호 추출 (values.yaml 의 'prom-operator' 와 동일해야 함)
kubectl get secret prom-grafana -n monitoring \
  -o jsonpath='{.data.admin-password}' | base64 -d
echo
```

**예상 출력**:

```
NAME                       READY   STATUS    RESTARTS   AGE
prom-grafana-xxxxxxxx-xxx  3/3     Running   0          1d
prom-operator
```

대시보드 ConfigMap 적용:

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/61-grafana-rag-dashboard.yaml
```

**예상 출력**:

```
configmap/rag-llm-grafana-dashboard created
```

sidecar 가 ConfigMap 변화를 감지하기까지 약 30 초 대기:

```bash
sleep 30
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboard --tail=20 \
  | grep -i 'rag-llm'
```

**예상 출력 (sidecar 로그)**:

```
... level=INFO ... msg="Updating files in folder: /tmp/dashboards"
... level=INFO ... msg="Writing /tmp/dashboards/rag-llm.json"
```

Grafana UI 접속:

```bash
kubectl port-forward -n monitoring svc/prom-grafana 3000:80 &
sleep 2
echo "Open: http://localhost:3000  (admin / prom-operator)"
```

브라우저에서 `Dashboards > Browse` 메뉴 → "RAG-LLM Capstone" 대시보드 클릭 → 4 패널이 렌더링되는지 확인 (현재 부하가 없어 ① 패널은 0, ②~④ 도 baseline).

### Step 3. prometheus-adapter Helm 설치

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1
helm repo update prometheus-community

helm install prometheus-adapter prometheus-community/prometheus-adapter \
  -n monitoring \
  -f course/capstone-rag-llm-serving/manifests/60-prometheus-adapter-values.yaml \
  --version 4.10.0 \
  --wait --timeout 5m
```

**예상 출력**:

```
NAME: prometheus-adapter
LAST DEPLOYED: ...
NAMESPACE: monitoring
STATUS: deployed
REVISION: 1
NOTES:
prometheus-adapter has been deployed.
```

adapter Pod 확인:

```bash
kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus-adapter
```

**예상 출력**:

```
NAME                                  READY   STATUS    RESTARTS   AGE
prometheus-adapter-xxxxxxxx-xxxxx     1/1     Running   0          1m
```

### Step 4. custom.metrics.k8s.io API 에 메트릭 노출 확인

adapter 가 정상 동작하면 K8s API 에 *두 메트릭이 새로* 등록됩니다:

```bash
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" \
  | jq '.resources[] | select(.name | test("rag_chat|vllm_num"))'
```

**예상 출력**:

```json
{
  "name": "pods/rag_chat_requests_per_second",
  "singularName": "",
  "namespaced": true,
  "kind": "MetricValueList",
  "verbs": ["get"]
}
{
  "name": "pods/vllm_num_requests_running",
  "singularName": "",
  "namespaced": true,
  "kind": "MetricValueList",
  "verbs": ["get"]
}
```

실제 값 직접 조회 (트러블슈팅 시 가장 유용):

```bash
# RAG API Pod 별 RPS — 부하 없으면 0 또는 <none>
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/rag-llm/pods/*/rag_chat_requests_per_second" \
  | jq '.items[] | {pod: .describedObject.name, value: .value}'

# vLLM Pod 별 동시 요청 수 — 부하 없으면 0
kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1/namespaces/rag-llm/pods/*/vllm_num_requests_running" \
  | jq '.items[] | {pod: .describedObject.name, value: .value}'
```

**예상 출력 (idle)**:

```json
{ "pod": "rag-api-xxx-1", "value": "0" }
{ "pod": "rag-api-xxx-2", "value": "0" }
{ "pod": "vllm-xxx", "value": "0" }
```

> 💡 부재 시 트러블슈팅: 위 명령이 `Error from server (NotFound): the server could not find ...` 를 반환하면 trouble #1 또는 #2 참고 — adapter rules 의 seriesQuery 가 Prometheus 의 라벨과 매칭하지 않거나, Prometheus URL 오타.

### Step 5. HPA 25 + 35 적용

```bash
kubectl apply -f course/capstone-rag-llm-serving/manifests/25-vllm-hpa.yaml
kubectl apply -f course/capstone-rag-llm-serving/manifests/35-rag-api-hpa.yaml
```

**예상 출력**:

```
horizontalpodautoscaler.autoscaling/vllm created
horizontalpodautoscaler.autoscaling/rag-api created
```

HPA 가 메트릭을 안정적으로 읽기까지 약 60 초 대기:

```bash
sleep 60
kubectl get hpa -n rag-llm
```

**예상 출력**:

```
NAME      REFERENCE             TARGETS    MINPODS   MAXPODS   REPLICAS   AGE
rag-api   Deployment/rag-api    0/10       2         6         2          1m
vllm      Deployment/vllm       0/8        1         2         1          1m
```

> ⚠ TARGETS 가 `<unknown>/8` 또는 `<unknown>/10` 으로 굳어져 있다면 trouble #3 참고. adapter rules 또는 release 라벨 매칭 실패.

상세 진단 (정상 동작 검증):

```bash
kubectl describe hpa rag-api -n rag-llm | grep -A 5 "Metrics\|Conditions"
```

**예상 출력 (관련 부분만)**:

```
Metrics:                                            ( current / target )
  "rag_chat_requests_per_second" on pods:           0 / 10
Conditions:
  Type            Status  Reason            Message
  AbleToScale     True    ReadyForNewScale  recommended size matches current size
  ScalingActive   True    ValidMetricFound  the HPA was able to successfully calculate ...
  ScalingLimited  False   DesiredWithinRange  the desired count is within the acceptable range
```

### Step 6. hey 부하 발사 — 60 초 c=8

별도 터미널을 하나 더 열어 `watch` 와 부하를 분리합니다.

**Terminal A (관측용)**:

```bash
watch -n 5 kubectl get hpa,pods -n rag-llm
```

**Terminal B (부하)**:

```bash
INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
hey -z 60s -c 8 -m POST \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' \
  http://$INGRESS/chat
```

**예상 출력 (hey 종료 시)**:

```
Summary:
  Total:        60.0123 secs
  Slowest:      8.4521 secs
  Fastest:      0.5102 secs
  Average:      2.8314 secs
  Requests/sec: 12.34
  ...
Status code distribution:
  [200] 740 responses
```

### Step 7. REPLICAS 변동 관측

부하 시작 후 약 60~120 초가 경과하면 Terminal A 의 `kubectl get hpa,pods` 출력에서 다음 변화가 보입니다.

**RAG API**: 2 → 4 (또는 6) 로 증가.
**vLLM**: 1 → 2 로 증가하지만 두 번째 Pod 는 *Pending*.

**예상 출력 (부하 도중, 약 90 초 시점)**:

```
NAME                          REFERENCE             TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
horizontalpodautoscaler/rag-api   Deployment/rag-api    13/10           2         6         4          5m
horizontalpodautoscaler/vllm      Deployment/vllm       11/8            1         2         2          5m

NAME                          READY   STATUS    RESTARTS   AGE
pod/rag-api-xxxxxxxx-aaaaa    1/1     Running   0          5m
pod/rag-api-xxxxxxxx-bbbbb    1/1     Running   0          5m
pod/rag-api-yyyyyyyy-ccccc    1/1     Running   0          30s
pod/rag-api-yyyyyyyy-ddddd    1/1     Running   0          30s
pod/vllm-xxxxxxxx-aaaaa       1/1     Running   0          1d
pod/vllm-yyyyyyyy-bbbbb       0/1     Pending   0          30s    ← 두 번째 Pod (학습 포인트)
```

두 번째 vLLM Pod 가 *왜* Pending 인지 직접 확인:

```bash
kubectl describe pod -n rag-llm -l app=vllm | grep -A 3 "Events:" | tail -5
```

**예상 출력 (자주 하는 실수 #24 와 직접 연결)**:

```
Events:
  Type     Reason            Age   From               Message
  ----     ------            ----  ----               -------
  Warning  FailedScheduling  30s   default-scheduler  0/2 nodes are available:
                                                       1 node(s) didn't match Pod's node affinity/selector,
                                                       1 node(s) had untolerated taint {nvidia.com/gpu: present}.
```

캡스톤은 GPU 노드 풀 size=1 이라 두 번째 vLLM Pod 가 schedule 될 노드가 없습니다. 운영 환경은 노드 풀 size 를 minReplicas+1 이상으로 두거나 cluster-autoscaler 활성화 — 본 캡스톤 학습용 maxReplicas=2 의 *체험형 학습 포인트* (lesson.md §7 결정 박스 ④).

### Step 8. Grafana 패널 동시 변동 확인

부하 도중 Grafana UI 의 4 패널이 동시에 변동하는지 확인 (Step 2 의 port-forward 가 살아 있다고 가정):

```
http://localhost:3000/d/rag-llm-capstone/rag-llm-capstone
```

**예상 시각화** (부하 90 초 시점):

| 패널 | 부하 전 (idle) | 부하 도중 (90s) | 부하 종료 후 (5분) |
|---|---|---|---|
| ① /chat req/s (status별) | 0 | ok 12~14 reqps | 점진 감소 |
| ② latency p95 단계별 | 모두 NaN 또는 직선 | chat 2~5s, retrieve 0.1s, llm 1~3s | 직선 복귀 |
| ③ vLLM running vs waiting | running 0 / waiting 0 | running 8~16 / waiting 0 | running 0 |
| ④ GPU KV cache | 0.10 (모델 가중치만) | 0.85~0.95 (KV cache 채움) | 0.10 |

> ⚠ ②번 패널의 retrieve > llm 인 경우는 Day 9 튜닝 후보 — e5 모델 또는 Qdrant search 가 병목. 본 캡스톤 phi-2 + multilingual-e5-small 조합은 일반적으로 llm > retrieve.

부하 종료 후 5 분 (behavior.scaleDown.stabilizationWindowSeconds=300) 동안 REPLICAS 가 *유지* 됨을 확인 — 떨림 방지 정책 (lesson.md §7 결정 박스 ③).

```bash
# 부하 종료 후 5 분 + 1 분 = 6 분 후
sleep 360
kubectl get hpa -n rag-llm
# rag-api REPLICAS: 4 → 4 → 3 → 2 (점진 감소)
# vllm    REPLICAS: 2 → 2 → 1 (점진 감소, Pending Pod 자동 정리)
```

port-forward 종료 (작업 마무리):

```bash
kill %1 2>/dev/null  # Terminal A 의 watch 종료 후 실행
```

---

## ✅ 검증 체크리스트

다음 8 항목이 모두 통과해야 Day 8 완료입니다.

- [ ] **(1) 대시보드 ConfigMap apply**: `kubectl get cm rag-llm-grafana-dashboard -n monitoring` 결과 1 줄, DATA=1
- [ ] **(2) Grafana sidecar 자동 import**: Grafana UI > Dashboards > "RAG-LLM Capstone" 클릭 시 4 패널이 렌더링됨
- [ ] **(3) prometheus-adapter Pod Ready**: `kubectl get pod -n monitoring -l app.kubernetes.io/name=prometheus-adapter` READY=1/1
- [ ] **(4) custom.metrics.k8s.io API 노출**: `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1" | jq '.resources[].name' | grep -E '(rag_chat|vllm_num)'` 결과 2 줄
- [ ] **(5) HPA TARGETS 실수치**: `kubectl get hpa -n rag-llm` 결과 두 HPA 의 TARGETS 가 `<unknown>` 이 아닌 `0/8`, `0/10` 형태
- [ ] **(6) hey 부하 200 OK**: hey 종료 시 Status code distribution 의 `[200] N responses` 가 600 회 이상 (60s × ~12 RPS × 8 c)
- [ ] **(7) REPLICAS 변동**: 부하 도중 `kubectl get hpa` 결과 rag-api REPLICAS 2→4 이상, vllm REPLICAS 1→2 (두 번째 Pending 정상)
- [ ] **(8) Grafana 4 패널 동시 변동**: 부하 시점 ①번 ok 라인이 0→12+ 으로 상승, ③번 running 0→8+ 으로 상승

---

## 🧹 정리

본 Day 종료 분기 2 개 — 자신의 일정에 맞게 선택.

### (A) Day 9 까지 그대로 유지 (권장)

**Day 9 (부하 테스트 + 튜닝)** 이 본 Day 의 HPA + adapter + 대시보드를 *그대로 사용* 하므로 정리하지 않는 것이 자연스럽습니다.

```bash
# 비용 모니터링 — 외부 IP, 추가된 노드 풀, 비정상 잔여 자원 점검
kubectl get ing,svc -n rag-llm
kubectl get hpa -n rag-llm
gcloud compute addresses list 2>/dev/null | grep -E '(rag|capstone)' || echo "no extra addresses"
```

### (B) Day 8 단독 종료 + 비용 절감

장기간 (반나절 이상) 멈출 때.

```bash
# (1) HPA 두 개 삭제 (REPLICAS 가 minReplicas 로 고정됨)
kubectl delete hpa vllm rag-api -n rag-llm

# (2) prometheus-adapter uninstall
helm uninstall prometheus-adapter -n monitoring

# (3) 대시보드 ConfigMap 삭제 (sidecar 가 ~30 초 내에 Grafana 에서 자동 제거)
kubectl delete cm rag-llm-grafana-dashboard -n monitoring

# (4) Day 7 자원도 정리하려면 day-07 §🧹 정리 (B) 참조
# helm uninstall prom -n monitoring
# kubectl delete servicemonitor vllm rag-api -n rag-llm

# (5) Day 6 Ingress 도 정리하려면 day-06 §🧹 정리 (B) 참조
# kubectl delete ingress rag-api -n rag-llm
```

> ⚠ **(B) 분기 후 Day 9 재시작 시**: Step 2~5 를 다시 실행. 대시보드/adapter/HPA 만 재생성하면 되므로 Day 7 자원이 살아 있다면 약 5 분 안에 복원.

---

## 🚨 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| **#1** `kubectl get --raw "/apis/custom.metrics.k8s.io/v1beta1"` 결과에 `rag_chat_requests_per_second` 또는 `vllm_num_requests_running` 부재 | adapter rules.custom 의 seriesQuery 가 Prometheus 라벨과 불일치 | adapter Pod 로그 확인 — `kubectl logs deploy/prometheus-adapter -n monitoring \| tail -30`. `seriesFilter` 또는 `discovered metrics: 0` 같은 줄 확인. Prometheus UI 의 `rag_chat_total{namespace=~".+",pod=~".+"}` 쿼리 결과가 비었는지 확인 (Day 7 회귀 — ServiceMonitor 라벨 누락) |
| **#2** prometheus-adapter Pod 가 `CrashLoopBackOff` | Prometheus URL 오타 또는 monitoring namespace 의 prom-kube-prometheus-stack-prometheus Service 부재 | `kubectl logs prometheus-adapter-xxx -n monitoring --previous \| grep -i 'connect\|refused'` 로 확인. `kubectl get svc -n monitoring \| grep prometheus` 로 정확한 이름 확인 후 60-prometheus-adapter-values.yaml 의 `prometheus.url` 갱신 후 `helm upgrade prometheus-adapter ... -f 60-...` |
| **#3** HPA TARGETS 가 `<unknown>/8` 무한 지속 | adapter 메트릭은 노출되지만 K8s API 가 못 읽음 — apiservice 등록 실패 또는 selector 라벨 매칭 실패 | `kubectl get apiservice v1beta1.custom.metrics.k8s.io` Available=True 확인. `kubectl describe hpa vllm -n rag-llm` 의 `Conditions` 에 `FailedGetPodsMetric` 또는 `FailedComputeMetricsReplicas` 메시지 확인 — 표 내용에 따라 #1 또는 #2 로 분기 |
| **#4** Grafana 대시보드 ConfigMap 적용했는데 UI 에 안 등장 | sidecar 라벨 매칭 실패 또는 namespace 잘못 — sidecar 는 `grafana_dashboard: "1"` 라벨만 watch | `kubectl get cm rag-llm-grafana-dashboard -n monitoring -o jsonpath='{.metadata.labels}'` 결과에 `grafana_dashboard: 1` 있는지 확인. `kubectl logs -n monitoring deploy/prom-grafana -c grafana-sc-dashboard --tail=50 \| grep -i error` 로 sidecar 에러 확인 |
| **#5** vLLM 두 번째 Pod 가 *영원히* Pending | T4 노드 풀 size=1 제약 — 학습 포인트, 정상 동작 | 의도된 결과. `kubectl describe pod vllm-yyy -n rag-llm` 의 Events 에 `0/2 nodes are available` 메시지가 학습 포인트. 운영 시 `gcloud container node-pools resize gpu-pool --num-nodes=2 --cluster capstone --zone <zone>` 또는 maxReplicas=1 로 축소 |
| **#6** RAG API replicas 늘었는데 latency 도 함께 증가 | vLLM 이 병목 — 두 번째 vLLM Pod 가 Pending 이라 GPU 처리량 한계 | Day 9 튜닝 예고. 본 Day 검증은 *HPA 동작* 까지 — latency 개선은 노드 풀 확장 + `--gpu-memory-utilization` 튜닝(Day 9)이 필요. Grafana 패널 ②번에서 llm latency 가 chat latency 의 60% 이상이면 vLLM 병목 |
| **#7** hey 부하 중 `Get http://...: connection refused` 또는 `no such host` | Ingress 의 backend port name `http` 미선언 (Day 6 자주 하는 실수 #16 회귀) 또는 nip.io DNS 캐시 만료 | `kubectl get svc rag-api -n rag-llm -o jsonpath='{.spec.ports[*].name}'` 결과가 `http` 인지 확인. `nslookup <IP>.nip.io` 로 DNS 해석 확인 |
| **#8** Grafana 패널이 No data — 부하 발사했는데 ①번 패널 비어있음 | Prometheus scrape 지연 (15s + interval) 또는 Grafana datasource UID 매핑 실패 | Prometheus UI 직접 확인 — `http://localhost:9090/graph?g0.expr=sum(rate(rag_chat_total[1m]))` 결과가 0 이상이면 Prometheus 는 정상. Grafana 패널 우상단 `(default)` datasource 셀렉터 클릭 → "Prometheus" 명시 선택 후 패널 새로 고침 |

---

## ➡ 다음 Day

[`day-09-load-test-tuning.md`](day-09-load-test-tuning.md) (작성 예정) — hey 본격 부하 테스트(`load_test.sh`) + p95 latency 측정 + vLLM `--gpu-memory-utilization` 튜닝 1 회전.

본 Day 에서 동작 확인한 HPA + adapter + 대시보드가 Day 9 의 *측정 도구* 로 그대로 활용됩니다.
