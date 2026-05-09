# Day 9 — 부하 테스트(hey) + vLLM 튜닝

> **상위 lesson**: [`../lesson.md`](../lesson.md) §6 모니터링 메트릭, §7 HPA, §10 자주 하는 실수 #25~#27
> **상위 plan**: [`docs/capstone-plan.md`](../../../docs/capstone-plan.md) §7 Day 9
> **상위 architecture**: [`../docs/architecture.md`](../docs/architecture.md) §3.14 부하 테스트 + 튜닝 결정 노트
> **운영 노트**: [`../practice/llm_serving/README.md`](../practice/llm_serving/README.md)
> **이전 단계**: [`day-08-grafana-hpa.md`](day-08-grafana-hpa.md)
> **소요 시간**: 1.5 ~ 2.5 시간 (사전 점검 5 분, baseline 부하 3 단계 25 분, Prometheus 메트릭 캡처 10 분, vLLM args patch + cold start 10 분, after 부하 3 단계 25 분, before/after 비교 표 작성 15 분, 정리 5 분)

---

## 🎯 Goal

Day 9 를 마치면 다음 4 가지가 충족됩니다.

- **`load_test.sh` 가 c=8/16/32 3 단계로 동작** — `LABEL=baseline bash load_test.sh` 한 번 호출로 60s × 3 회 hey 부하가 실행되고 `results/baseline-c8.txt`, `results/baseline-c16.txt`, `results/baseline-c32.txt` 3 개 파일이 디스크에 저장됩니다.
- **baseline (`--gpu-memory-utilization=0.85`) 의 chat p95/p99 latency 측정 + Prometheus 4 메트릭 캡처** — hey 출력의 `95% in` / `99% in` 행과 PromQL 4 종(`rate(rag_chat_total{status="200"}[1m])`, `histogram_quantile(0.95, ...)`, `vllm:num_requests_running`, `vllm:gpu_cache_usage_perc`) 이 동시에 기록됩니다.
- **vLLM args 0.85 → 0.90 안전 상향 patch 적용 + cold start 통과** — `kubectl patch deployment vllm` 한 줄로 args[2] 가 교체되고, PVC 캐시 hit 으로 60~120 초 안에 새 Pod 가 Ready 가 됩니다 (모델 재다운로드 *없음*).
- **before/after 비교 표 작성 (5 지표)** — hey RPS / p95 / p99 + `vllm:num_requests_running` 평균 + `vllm:gpu_cache_usage_perc` 평균을 6 시나리오(baseline/after × c=8/16/32) 모두 기록하고 [`../practice/llm_serving/README.md`](../practice/llm_serving/README.md) §5.4 템플릿을 채웁니다.

---

## 🔧 사전 조건

- **Day 8 완료 + 1 줄 검증 회귀 없음**: HPA 가 적용된 상태에서 RAG end-to-end 가 200 OK.
  ```bash
  INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
  curl -s http://$INGRESS/chat \
    -H 'Content-Type: application/json' \
    -d '{"messages":[{"role":"user","content":"ping"}],"top_k":3}' \
    -o /dev/null -w "%{http_code}\n"
  # → 200
  kubectl get hpa -n rag-llm
  # → rag-api / vllm 두 줄, TARGETS 가 0/10, 0/8 (Day 8 잔여 부하 효과 없음)
  ```
- **`hey` CLI 설치 (Day 8 동일)**:
  - macOS: `brew install hey`
  - Linux: `go install github.com/rakyll/hey@latest`
- **`jq`, `awk`, `kubectl`** — 표준 도구. macOS 는 `brew install jq`.
- **GKE T4 노드 풀 활성**: Day 8 종료 후 size=0 으로 축소했다면 복원.
  ```bash
  gcloud container node-pools resize gpu-pool \
    --num-nodes=1 --cluster=capstone --zone=us-central1-a --quiet
  kubectl get nodes -l cloud.google.com/gke-accelerator=nvidia-tesla-t4
  # → Ready 1 노드
  ```
- **Prometheus port-forward 가능**:
  ```bash
  kubectl port-forward -n monitoring svc/prom-kube-prometheus-stack-prometheus 9090:9090 &
  curl -s http://localhost:9090/-/ready
  # → Prometheus is Ready.
  ```

> 💰 **GKE 비용 박스 (꼭 읽기)**
>
> - **부하 시간**: 60s × 6 회 + cold start 1 회 ≈ 약 8 분의 *집중 부하* + 메트릭 관측 30 분 = T4 노드 약 40 분 사용 (\$0.23).
> - **vLLM HPA 두 번째 Pod**: Day 8 #24 와 동일하게 maxReplicas=2 + 노드 1 대 = 두 번째 Pod 가 *Pending* 으로 추가 노드 비용 없음.
> - **Day 9 종료 시 분기**: (A) Day 10 Helm 으로 이어가면 args 를 *0.85 로 롤백* + 노드 풀 그대로. (B) 단독 종료면 클러스터 삭제 (§🧹 정리 분기 (B)).

---

## 🚀 Steps

### Step 1. 사전 점검 — Day 8 인계 + HPA 안정 상태

부하를 발사하기 *전* HPA TARGETS 가 안정 상태(`0/X`)임을 확인합니다. Day 8 의 hey 60s 부하가 끝난 직후라면 HPA stabilizationWindowSeconds (300s) 동안 REPLICAS 가 줄어들지 않으므로 *5 분 이상* 대기 후 시작합니다.

```bash
kubectl get hpa,pods -n rag-llm
```

**예상 출력 (안정 상태)**:

```
NAME                          REFERENCE             TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
horizontalpodautoscaler/rag-api   Deployment/rag-api    0/10            2         6         2          1d
horizontalpodautoscaler/vllm      Deployment/vllm       0/8             1         2         1          1d

NAME                          READY   STATUS    RESTARTS   AGE
pod/rag-api-xxxxxxxx-aaaaa    1/1     Running   0          1d
pod/rag-api-xxxxxxxx-bbbbb    1/1     Running   0          1d
pod/qdrant-0                  1/1     Running   0          1d
pod/vllm-yyyyyyyy-ccccc       1/1     Running   0          1d
```

> TARGETS 가 `0/10`, `0/8` 이면 Day 8 부하 잔여 효과가 끝난 상태입니다. `<unknown>/10` 이 보이면 prometheus-adapter Pod 가 죽은 것 — Day 8 트러블슈팅 #22 회귀.

현재 vLLM args 기본값도 확인합니다.

```bash
kubectl get deployment vllm -n rag-llm -o jsonpath='{.spec.template.spec.containers[0].args}' | tr ',' '\n' | grep gpu-memory
# → "--gpu-memory-utilization=0.85"
```

### Step 2. `load_test.sh` 권한 + INGRESS 추출

```bash
cd course/capstone-rag-llm-serving
chmod +x practice/llm_serving/load_test.sh

INGRESS_HOST=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
echo "INGRESS_HOST=$INGRESS_HOST"
# → 34.120.x.x.nip.io (Day 6 결정)

# Ingress 가 살아있는지 한 번 확인
curl -s http://$INGRESS_HOST/healthz
# → ok
```

> `INGRESS_HOST` 가 비어 있으면 Day 6 트러블슈팅 #1~#3 회귀 — Ingress ADDRESS 가 부여되지 않은 상태입니다.

### Step 3. baseline 부하 c=8/16/32 — 3 단계 순차 실행

**Terminal A (관측용 — 별도 터미널)**:

```bash
watch -n 5 kubectl get hpa,pods -n rag-llm
```

**Terminal B (부하)**:

`load_test.sh` 한 번 호출로 c=8 → c=16 → c=32 가 자동 순차 실행됩니다. 단계 사이 5 초 stabilization 이 들어가 메트릭이 정리됩니다.

```bash
LABEL=baseline INGRESS_HOST=$INGRESS_HOST bash practice/llm_serving/load_test.sh
```

**예상 출력 (워밍업 + 3 단계 + 한 줄 요약)**:

```
Warming up 5 회 (c=4) — vLLM 캐시 hit 확인...
  attempt 1: 200 (1.234s)
  attempt 2: 200 (0.987s)
  ...

=== Load Test [LABEL=baseline, CONCURRENCY=8] ===
Target:      http://34.120.x.x.nip.io/chat
Duration:    60s
Output:      results/baseline-c8.txt

Summary:
  Total:        60.0142 secs
  Slowest:      8.4521 secs
  Fastest:      0.5102 secs
  Average:      2.0314 secs
  Requests/sec: 12.34
  ...
Latency distribution:
  ...
  95% in 3.2102 secs
  99% in 5.7821 secs
Status code distribution:
  [200] 740 responses

[summary] LABEL=baseline c=8 | slow=8.4521 fast=0.5102 avg=2.0314 p95=3.2102 p99=5.7821 200_ok=740

>>> 다음 단계 시작 전 5 초 대기 (메트릭 stabilization) <<<

=== Load Test [LABEL=baseline, CONCURRENCY=16] ===
...
[summary] LABEL=baseline c=16 | slow=10.2 fast=0.62 avg=2.85 p95=4.1 p99=7.3 200_ok=1080

=== Load Test [LABEL=baseline, CONCURRENCY=32] ===
...
[summary] LABEL=baseline c=32 | slow=15.8 fast=0.71 avg=4.2 p95=5.8 p99=12.1 200_ok=1320
```

**Terminal A 동시 변동 (예상)**:

```
NAME                          REFERENCE             TARGETS         MINPODS   MAXPODS   REPLICAS   AGE
horizontalpodautoscaler/rag-api   Deployment/rag-api    13/10           2         6         4          1d
horizontalpodautoscaler/vllm      Deployment/vllm       11/8            1         2         2          1d

NAME                          READY   STATUS    RESTARTS   AGE
pod/rag-api-xxxxxxxx-aaaaa    1/1     Running   0          1d
pod/rag-api-xxxxxxxx-bbbbb    1/1     Running   0          1d
pod/rag-api-xxxxxxxx-ccccc    1/1     Running   0          2m   # HPA 가 늘림
pod/rag-api-xxxxxxxx-ddddd    1/1     Running   0          2m
pod/vllm-yyyyyyyy-ccccc       1/1     Running   0          1d
pod/vllm-yyyyyyyy-ddddd       0/1     Pending   0          1m   # T4 노드 1 대라 Pending — Day 8 #24 재현
```

> c=32 단계에서 *일부 응답이 timeout* 으로 표시되거나 200 OK 가 1100 회 미만이면 *의도된 결과* 입니다 (vLLM 단일 Pod 의 KV cache 포화 + RAG API HPA max=4 도달). `vllm:num_requests_waiting > 0` 메트릭으로 재확인.

### Step 4. baseline Prometheus 메트릭 캡처

부하가 *끝나고 30 초 안에* HPA stabilizationWindow 가 시작되기 전에 Prometheus UI 에서 4 PromQL 을 캡처합니다. Step 3 의 *부하 도중* 또는 *부하 직후* 가 의미 있는 시점입니다.

브라우저에서 `http://localhost:9090/graph` 열고 다음 4 쿼리를 순차 실행:

```promql
# ① RAG end-to-end 성공 RPS
rate(rag_chat_total{status="200"}[1m])

# ② RAG end-to-end p95 latency
histogram_quantile(0.95, sum(rate(rag_chat_latency_seconds_bucket[1m])) by (le))

# ③ vLLM 동시 처리 요청 수 (continuous batching 효과)
vllm:num_requests_running

# ④ vLLM KV cache 사용률
vllm:gpu_cache_usage_perc
```

**예상 그래프 패턴**:

| 메트릭 | c=8 구간 | c=16 구간 | c=32 구간 |
|---|---|---|---|
| ① rag_chat RPS | ~12 | ~18 | ~22 (포화) |
| ② chat p95 | 1.5~3.0s | 2.0~4.0s | 3.0~6.0s |
| ③ vllm running | 8~10 | 12~15 | 14~16 (상한) |
| ④ gpu_cache_usage_perc | 0.85~0.90 | 0.88~0.92 | 0.92~0.95 |

각 그래프를 *스크린샷* 으로 저장하거나 PromQL 결과 표를 텍스트로 복사해 둡니다 — Step 9 비교 표의 baseline 행을 채우는 데 사용합니다.

> Grafana UI(`http://localhost:3000`, Day 8 의 sidecar 자동 import 대시보드 `RAG-LLM Capstone`) 4 패널을 그대로 활용해도 됩니다 — Day 8 §6 의 4 패널이 위 PromQL 4 종과 1:1 대응됩니다.

### Step 5. RAG 단계별 latency 분해 (병목 분리 진단)

Day 5 가 노출한 4 RAG 메트릭을 부하 *직후 1 분* 안에 수집합니다.

```promql
# RAG retrieve (Qdrant) p95
histogram_quantile(0.95, sum(rate(rag_retrieve_latency_seconds_bucket[1m])) by (le))

# RAG llm (vLLM 호출) p95
histogram_quantile(0.95, sum(rate(rag_llm_latency_seconds_bucket[1m])) by (le))
```

**해석 의사결정 (자주 하는 실수 #26 예방)**:

- `chat_p95 ≈ retrieve_p95 + llm_p95 + 약간의 overhead` 인지 합산 검산
- `llm_p95 ≈ vllm:e2e_request_latency_seconds p95` 인지 외부 메트릭과 비교
- `retrieve_p95 > 500ms` 면 Qdrant 부하 (Day 7 §6.3 부재 명시 — Day 10 도입 예정)

> **학습 포인트**: c=32 부하에서 `chat_p95 = 4.5s` 를 보고 *RAG API 가 느리다* 라고 단정하는 것이 자주 하는 실수 #26. retrieve 0.15s + llm 4.0s + overhead 0.3s 가 진짜 분해입니다 — *vLLM 이 병목*.

### Step 6. (선택) Grafana 대시보드 4 패널 동시 캡처

Day 8 의 `RAG-LLM Capstone` 대시보드 가 sidecar 로 import 된 상태입니다. 부하 도중·직후 4 패널을 한 화면에 캡처해 두면 Step 9 비교 표 해석에 큰 도움이 됩니다.

```bash
kubectl port-forward -n monitoring svc/prom-grafana 3000:80 &
# 브라우저: http://localhost:3000  (admin / prom-operator 기본 비밀번호 — Day 7 자료 참조)
# Dashboards → RAG-LLM Capstone
```

4 패널이 모두 데이터를 그리는 것을 확인하고, 시간 범위를 부하 시작 전 5 분 ~ 종료 후 5 분으로 잡습니다.

### Step 7. vLLM args patch — `--gpu-memory-utilization` 0.85 → 0.90

JSON Patch 한 줄로 args[2] 만 교체합니다 (`kubectl edit` 로 손으로 고치는 것보다 *재현 가능*). args 인덱스가 헷갈리면 [`../practice/llm_serving/README.md`](../practice/llm_serving/README.md) §1 표 참고 — args[0]=model, args[1]=served-model-name, args[2]=gpu-memory-utilization, args[3]=max-model-len.

```bash
kubectl patch deployment vllm -n rag-llm --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args/2","value":"--gpu-memory-utilization=0.90"}]'
```

**예상 출력**:

```
deployment.apps/vllm patched
```

rolling update 가 트리거됩니다. PVC `vllm-model-cache` 가 hit 되어 60~120 초 안에 새 Pod 가 Ready 됩니다.

```bash
kubectl rollout status deployment/vllm -n rag-llm --timeout=180s
# → deployment "vllm" successfully rolled out
```

patch 가 반영됐는지 한 번 더 확인:

```bash
kubectl get deployment vllm -n rag-llm -o jsonpath='{.spec.template.spec.containers[0].args}' | tr ',' '\n' | grep gpu-memory
# → "--gpu-memory-utilization=0.90"
```

> `kubectl rollout status` 가 timeout 되면 트러블슈팅 표 *0.90 patch 후 readiness 실패* 행 참조. cold start 가 길어지는 이유는 PVC hit 실패 (Day 4 자주 하는 실수 #12) 또는 KV cache 풀 0.90 재할당 시간 증가.

### Step 8. after 부하 c=8/16/32 — 동일 3 단계 반복

baseline 과 같은 명령을 `LABEL=after` 로 한 번 더 실행합니다.

```bash
LABEL=after INGRESS_HOST=$INGRESS_HOST bash practice/llm_serving/load_test.sh
```

**예상 변화 (baseline 대비)**:

| 시나리오 | hey RPS | hey p95 | vllm running 평균 | KV cache |
|---|---|---|---|---|
| after c=8 (0.90) | ~12 (변화 미미) | 1.4~2.3s (소폭 ↓) | 9~12 (↑) | 0.88~0.92 (↑) |
| after c=16 (0.90) | ~18~22 (소폭 ↑) | 1.9~3.2s (↓) | 14~18 (↑) | 0.90~0.93 (↑) |
| after c=32 (0.90) | ~22~25 (↑) | 2.8~4.5s (↓) | 16~20 (↑) | 0.92~0.95 (↑) |

> 변동 폭은 학습자 환경(GKE T4 / 네트워크 latency)에 따라 ±30%. *절대값보다 변화 방향* 이 학습 포인트입니다 ([README §3.2](../practice/llm_serving/README.md#32-085--090-안전-상향이란)).

### Step 9. before/after 비교 표 작성 + README 갱신

[`../practice/llm_serving/README.md`](../practice/llm_serving/README.md) §5.4 의 6 행 × 6 열 표 템플릿을 *복사* 해 본 lab 의 `results/` 디렉토리 옆에 `report.md` 로 저장하고 5 지표를 채웁니다.

**채우는 값**:

- hey RPS — 결과 파일의 `Requests/sec:` 행
- hey p95 — `95% in` 행
- hey p99 — `99% in` 행
- `vllm:num_requests_running` 평균 — Prometheus 그래프 또는 `avg_over_time(vllm:num_requests_running[1m])` 부하 구간 평균
- `vllm:gpu_cache_usage_perc` 평균 — 동일 방식
- 200 OK 비율 — `[200] N responses` / 전체 요청 수

**해석 한 단락 예시 (학습자 작성)**:

> baseline c=16 의 `num_requests_running` 평균이 12 였고 after 에서는 16 으로 33% 증가했습니다. KV cache 풀이 0.85→0.90 으로 +11% 확장되어 continuous batching 의 동시 처리 폭이 늘었습니다. p95 latency 는 3.5s → 2.7s 로 23% 개선됐고, 200 OK 비율이 99.7% → 99.9% 로 안정화됐습니다. *병목* 은 `chat_latency ≈ retrieve_latency + llm_latency` 검산이 일치했고 `llm_latency ≈ vllm:e2e_request_latency_seconds` 라 vLLM 이 주된 병목이었습니다 — 0.90 상향이 *맞는 튜닝* 이었음을 입증.

---

## ✅ 검증 체크리스트

다음 8 가지가 모두 충족되면 Day 9 완료입니다.

- [ ] **(1) results 디렉토리 6 파일**: `ls -lh practice/llm_serving/results/` 결과가 `baseline-c8.txt`, `baseline-c16.txt`, `baseline-c32.txt`, `after-c8.txt`, `after-c16.txt`, `after-c32.txt` 6 줄.
- [ ] **(2) baseline c=8 의 p95 측정**: `grep "95% in" results/baseline-c8.txt` 결과가 1 행 (예: `95% in 3.2102 secs`).
- [ ] **(3) Prometheus 4 메트릭 그래프 캡처**: 위 §Step 4 의 4 PromQL 모두 데이터가 그려진 시점의 스크린샷 또는 텍스트 로그 보유.
- [ ] **(4) vLLM args 0.90 반영**: `kubectl get deployment vllm -n rag-llm -o jsonpath='{.spec.template.spec.containers[0].args}' | tr ',' '\n' | grep gpu-memory` 결과가 `"--gpu-memory-utilization=0.90"`.
- [ ] **(5) cold start 통과**: `kubectl rollout status deployment/vllm --timeout=180s` 가 timeout 없이 종료. 새 Pod 의 AGE 가 5 분 이내.
- [ ] **(6) after c=8 의 running 평균 ≥ 10**: PromQL `avg_over_time(vllm:num_requests_running[1m])` 가 부하 구간에서 baseline 대비 *상승* 했음을 확인.
- [ ] **(7) before/after 비교 표 5 지표 모두 기록**: `report.md` 또는 README §5.4 템플릿이 6 행 × 6 열 모두 빈칸 없음.
- [ ] **(8) Day 8 1 줄 완료 기준 회귀 없음**: `curl http://$INGRESS_HOST/chat ...` 200 OK + `sources` 길이 3.

```bash
# 회귀 검증 한 줄
INGRESS=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}')
curl -s http://$INGRESS/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}' \
  | jq '{status: "ok", sources_count: (.sources | length), has_citation: (.answer | test("\\[[0-9]+\\]"))}'
# → {"status":"ok","sources_count":3,"has_citation":true}
```

---

## 🧹 정리

### (A) Day 10 Helm 으로 이어가기 (권장)

vLLM args 를 0.85 로 *롤백* 합니다. Day 10 의 `helm/values.yaml` 가 `gpuMemoryUtilization: 0.85` 기본값을 사용하므로 일치시켜 두면 Day 10 의 `helm install ... -f values.yaml` 한 줄 재배포 결과가 *Day 9 baseline 과 동등* 함을 검증할 수 있습니다.

```bash
kubectl patch deployment vllm -n rag-llm --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args/2","value":"--gpu-memory-utilization=0.85"}]'
kubectl rollout status deployment/vllm -n rag-llm --timeout=180s

# (선택) GPU 노드 풀 size=0 축소 — Day 10 시작 전 5 분 만에 size=1 복원 가능
gcloud container node-pools resize gpu-pool \
  --num-nodes=0 --cluster=capstone --zone=us-central1-a --quiet
```

부하 결과 파일(`results/baseline-c8.txt` 등)과 `report.md` 는 *유지* — Day 10 통합 검증 시 Helm 재배포 후 동일 부하를 다시 발사해 *값이 같은지* 비교합니다.

### (B) Day 9 단독 종료 + 비용 절감

휴식 기간이 길거나 캡스톤을 일시 중단하는 경우 클러스터 자체를 삭제합니다. PVC `qdrant-storage-qdrant-0`, `vllm-model-cache` 의 데이터도 함께 사라지므로 다시 시작하려면 Day 1 부터 회귀가 필요합니다 (인덱싱은 Day 3 의 git-clone step 으로 자동 복원, vLLM 모델은 5~10 분 다운로드).

```bash
gcloud container clusters delete capstone --zone us-central1-a --quiet
```

> 💡 **Helm 차트 작성 전이라면 (A) 권장**: Day 10 의 Helm 한 줄 재배포 검증을 위해 *현재 클러스터 상태가 그대로 보존* 되어야 하기 때문입니다.

---

## 🚨 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| **#1** `hey: command not found` | hey CLI 미설치 | macOS `brew install hey` / Linux `go install github.com/rakyll/hey@latest` |
| **#2** `INGRESS_HOST` 가 비어 있음 + load_test.sh 가 즉시 종료 | Day 6 Ingress 가 ADDRESS 를 받지 못한 상태 또는 `kubectl get ing` 권한 부재 | `kubectl get ing rag-api -n rag-llm` 으로 ADDRESS 확인. 비어 있으면 Day 6 트러블슈팅 #1~#3 회귀. 환경변수 직접 지정도 가능: `INGRESS_HOST=34.x.x.x.nip.io bash load_test.sh` |
| **#3** c=32 일 때 응답의 5~15% 가 *timeout / 5xx* | vLLM 단일 Pod 의 KV cache 포화 + RAG API HPA max=4 도달 | *의도된 결과(체험형 학습)* — `vllm:num_requests_waiting > 0` 메트릭으로 재확인. 학습 포인트는 자주 하는 실수 #27 (200 OK 만 보고 timeout 무시) 예방. 단순히 처리량을 늘리려면 maxReplicas 와 노드 풀 size 동반 확장 |
| **#4** Step 7 의 `kubectl rollout status` 가 180s timeout | (a) PVC `vllm-model-cache` 가 hit 실패 → 모델 5GB 재다운로드 (5~10 분 추가) (b) KV cache 풀 0.90 재할당 시간 증가 | `kubectl logs deployment/vllm -n rag-llm` 의 `Downloading shards` 메시지 확인. (a) 면 Day 4 자주 하는 실수 #12 회귀. 임시 회피: `kubectl rollout status --timeout=600s` 로 재대기 |
| **#5** Prometheus port-forward 즉시 끊김 — `address already in use` | 9090 포트 점유 (Day 8 잔여 또는 다른 도구) | `lsof -i :9090` 로 점유 프로세스 확인 → kill. 또는 `kubectl port-forward -n monitoring svc/prom-... 9091:9090 &` 로 9091 사용 |
| **#6** baseline 과 after 의 chat p95 가 거의 같음 | 부하가 RAG API 4 Pod 에 분산되어 단일 vLLM Pod 에 도달하는 RPS 가 *KV cache 포화 임계점에 도달 못함* | *의도된 결과* (Day 8 #24 와 같은 메커니즘) — `vllm:num_requests_running` 평균값으로 효과 확인. 더 명확한 차이를 보고 싶으면 `CONCURRENCY=64 SINGLE=1 LABEL=baseline bash load_test.sh` 로 부하 집중 |
| **#7** KV cache 0.95+ 알 수 없는 OOM (학습자가 호기심으로 0.95 시도) | gpu-memory-utilization 을 0.95 이상으로 patch → KV cache OOM | *자주 하는 실수 #25* — `kubectl patch ... 'value':"--gpu-memory-utilization=0.85"` 로 즉시 복원. `kubectl describe pod vllm` 의 `Last State: Terminated, Reason: OOMKilled` 확인 |
| **#8** RAG API 가 병목인지 vLLM 이 병목인지 분리 안 됨 | Day 5 의 단계별 latency 메트릭 (chat / retrieve / llm) 미관찰 | *자주 하는 실수 #26* — Step 5 의 PromQL 2 종을 추가 캡처. `chat_p95 ≈ retrieve_p95 + llm_p95 + overhead` 합산 검산이 일치해야 함. `llm_p95 ≈ vllm:e2e_request_latency_seconds p95` 외부 메트릭과 교차 검증 |

---

## ➡ 다음 Day

[`day-10-integration-cleanup.md`](day-10-integration-cleanup.md) (작성 예정) — Helm 차트로 캡스톤 전체(Namespace/Qdrant/vLLM/RAG API/Ingress/모니터링/HPA/인덱싱)를 한 줄 재배포 → §9 검증 시나리오 6 단계 통과 → GKE 클러스터 삭제로 마무리.
