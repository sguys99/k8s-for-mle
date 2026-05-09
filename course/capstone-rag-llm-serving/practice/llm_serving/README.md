# vLLM 서빙 운영 노트 (Capstone Day 9)

> Capstone Day 9 의 부하 테스트(`load_test.sh`) 와 함께 사용하는 *vLLM 운영 핸드북* 입니다. 본 노트의 vLLM 핵심 개념(args 5 종 / cold start / KV cache / Prometheus 메트릭)은 [`course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md`](../../../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md) §1-4 ~ §1-6 의 *재서술* 이며, 캡스톤 매니페스트(`manifests/20-vllm-deployment.yaml`)의 현재값 + Day 4 의 결정 6 가지 + Day 9 의 0.85 → 0.90 안전 상향 가이드가 추가됩니다.

---

## §1. vLLM args 핵심 6 종 (캡스톤 현재값)

[`manifests/20-vllm-deployment.yaml`](../../manifests/20-vllm-deployment.yaml) 의 `args:` 6 줄이 vLLM 운영의 *모든 표면적* 입니다. Phase 4-3 의 5 종에 캡스톤 Day 4 결정으로 `--served-model-name` 이 추가되어 6 종이 되었습니다.

| 옵션 | 캡스톤 값 | 의미 | 트레이드오프 / 결정 출처 |
|------|---------|------|---------------------|
| `--model` | `microsoft/phi-2` | HF Hub 모델 ID. 첫 기동 시 자동 다운로드 (5GB) | 변경 시 PVC 캐시 무효화 → 5~10 분 재다운로드. Day 9 에서 `--gpu-memory-utilization` 만 patch 하므로 영향 없음 |
| `--served-model-name` | `microsoft/phi-2` | OpenAI SDK `model` 파라미터의 매칭 키 | Day 4 결정 — HF ID 그대로 채택. RAG API 의 `OPENAI_MODEL` env 와 일치해야 함 (자주 하는 실수 #14) |
| **`--gpu-memory-utilization`** | **`0.85`** | **GPU VRAM 의 몇 % 까지 vLLM 이 사용 (모델 + KV cache)** | **↑ 면 동시 요청 ↑, but OOM 위험. Day 9 의 *유일한 튜닝 대상*. T4 권장 0.85 → 가용 상향 0.90 → 0.95+ OOM** |
| `--max-model-len` | `2048` | 한 요청이 사용 가능한 최대 토큰 수 (input + output) | phi-2 학습 한계. 늘리면 품질 급락. Day 9 에서 *변경하지 않음* (Phase 5 / capstone v2 로 미룸) |
| `--port` | `8000` | HTTP 서버 포트 | Service `targetPort` 와 일치. Day 4 의 22-vllm-service.yaml 기준 |
| `--dtype` | `auto` | 모델 가중치 정밀도 | T4 는 BF16 미지원 — `auto` 가 자동으로 FP16 선택. A100/H100 은 BF16 권장 |

**Day 9 에서 다루지 않는 옵션 (Phase 5 / 캡스톤 v2 후보)**:
- `--max-num-batched-tokens` — 동시 배치 토큰 수 상한. 모델/워크로드별 프로파일링 필요한 *2회전 튜닝* 항목. 캡스톤은 *1회전 튜닝* 학습 가치에 집중하므로 미도입
- `--enable-prefix-caching` — 시스템 프롬프트가 반복되는 RAG 에서 큰 효과. 본 캡스톤의 `prompts.py` 가 동일 SYSTEM_PROMPT 를 사용하므로 *적용 시 retrieve_latency 영향 0 + llm_latency 10~30% 감소* 기대
- `--quantization=awq` — VRAM 50% 절감. T4 16GB 에서 더 큰 모델(7B+) 서빙 가능

> 결정 노트: Day 9 가 *왜 `--gpu-memory-utilization` 한 옵션만 보는가* — Phase 4-3 의 1-4 표가 5 종을 다 보여주지만 *부하 테스트 중 1회전 튜닝으로 의미 있는 차이를 만드는 옵션* 은 이 한 가지입니다 (cold start 영향 없음, 코드 수정 0, 메트릭 즉시 반응).

---

## §2. cold start 와 PVC 캐시

vLLM Pod 의 *첫 기동* 은 다음 4 단계로 길게 이어집니다 (Phase 4-3 §1-5 인용).

```
Pod 생성 → 컨테이너 시작 → 모델 다운로드 (5~10분) → GPU 메모리 로딩 (30~60초) → KV cache 할당 (수 초) → /health 200 OK
```

캡스톤 매니페스트의 안전장치 3 종:

1. **startupProbe** `failureThreshold: 60 × periodSeconds: 10s = 최대 10 분 모델 로딩 허용`. 통과 후 livenessProbe 가 동작
2. **PVC `vllm-model-cache` 20Gi RWO** — `/root/.cache/huggingface` 에 마운트. 두 번째 부팅부터 *30~60 초* 로 단축
3. **`/dev/shm` tmpfs 4Gi** — CUDA IPC 공유 메모리 부족 (자주 하는 실수 #2 phi-2 *Bus error*) 회피

### Day 9 의 cold start 재발생 주의

`load_test.sh` 가 `LABEL=baseline` 측정 후 vLLM args 의 `--gpu-memory-utilization` 을 patch 하면 **rolling update 가 트리거** 됩니다.

| 단계 | 소요 시간 | 비고 |
|---|---|---|
| ① 기존 Pod Terminating | 5~15 초 | preStop sleep 없음 |
| ② 새 Pod 생성 + 모델 캐시 hit | 30~60 초 | PVC 가 hit → HF Hub 다운로드 안 함 |
| ③ GPU 로딩 + KV cache 재할당 (0.85 → 0.90 으로 풀 사이즈 변화) | 30~60 초 | 0.85 → 0.90 이면 KV cache 풀이 약 6% 더 큼 |
| ④ startupProbe 통과 → readinessProbe 통과 | 즉시 | endpoint 등록 |
| **합계** | **약 60~120 초** | Day 9 lab Step 7 timeout 180s 는 안전 마진 |

> 학습자가 `kubectl rollout status --timeout=180s` 가 timeout 되면 **PVC 캐시 무효화** (Day 4 자주 하는 실수 #12) 가 의심됩니다. `kubectl logs deployment/vllm -n rag-llm` 의 `Downloading shards` 메시지가 보이면 PVC hit 실패 → Day 4 lab 으로 회귀.

---

## §3. `--gpu-memory-utilization` 튜닝 가이드

### §3.1 권장값 매트릭스

| GPU | 권장 시작값 | 가용 상향 | 위험선 | 비고 |
|---|---|---|---|---|
| **T4 16GB (캡스톤)** | **0.85** | **0.90** | 0.95+ | KV cache OOM 가장 잦음. Day 9 가 본 행을 검증 |
| L4 24GB | 0.85 | 0.92 | 0.95+ | T4 와 유사 |
| A10G 24GB | 0.88 | 0.93 | 0.95+ | activation 메모리 더 큼 |
| A100 40GB | 0.90 | 0.95 | 0.97+ | 모니터링 agent 메모리 비중 작음 |
| A100 80GB | 0.92 | 0.95 | 0.97+ | 동일 |
| H100 80GB | 0.92 | 0.95 | 0.97+ | 동일, BF16 권장 |

> 표는 vLLM 0.6.x 기준. v1 엔진(`VLLM_USE_V1=1`) 으로 전환 시 메모리 회계가 약간 달라지지만 권장 시작값은 동일합니다.

### §3.2 0.85 → 0.90 안전 상향이란

vLLM 은 *시작 시* `--gpu-memory-utilization` 비율로 GPU VRAM 의 풀(pool) 을 한 번에 예약합니다.

```
T4 16GB
├── 모델 가중치 (FP16, phi-2 ≈ 5.4GB)        ─┐
├── activation buffer (~ 1GB)                 │ 가중치 + activation = 약 6.4GB (고정)
├── KV cache 풀 (남은 영역)                   ─┘ 0.85 → 13.6GB - 6.4GB = 7.2GB
│                                                0.90 → 14.4GB - 6.4GB = 8.0GB (+11% 풀)
│                                                0.95 → 15.2GB - 6.4GB = 8.8GB (모니터링 agent / driver 와 충돌 위험)
└── 시스템 / 모니터링 agent / NVIDIA driver (~0.8GB)
```

**0.85 → 0.90 의 효과 예측 (캡스톤 phi-2)**:

- **가능한 동시 요청 수**: 약 11% 증가 (KV cache 풀이 7.2 → 8.0GB)
- **`vllm:num_requests_running`**: baseline 8~12 → after 10~14 평균 상승 (continuous batching 효과 확대)
- **p95 latency**: c=16/32 부하에서 *10~20% 감소* 기대 (대기 줄어듦)
- **RPS**: c=32 부하에서 *15~25% 증가* 기대

**0.95+ 의 위험 (자주 하는 실수 #25)**:
- KV cache 풀이 OS / 모니터링 agent 와 *동시 사용 충돌* → CUDA OOM
- vLLM 컨테이너 *시작도 못 함* → CrashLoopBackOff
- `kubectl describe pod vllm` 의 *Last State: Terminated, Reason: OOMKilled*

> Day 9 가 0.90 에서 *멈추는 이유* 는 학습 안정성. 0.95+ 위험은 lesson.md §10 ㉕에 진단·해결 단계로 *이론 표면화* 했고, 학습자가 호기심으로 시도해도 자가 복구 가능합니다.

### §3.3 튜닝 체크리스트

`load_test.sh` 측정 결과로 다음 4 가지를 확인합니다.

- [ ] baseline `vllm:num_requests_running` 평균이 *6 이상* (그 이하면 부하 부족 — c=16 또는 c=32 로 확인)
- [ ] baseline `vllm:gpu_cache_usage_perc` 가 *0.90 미만* (이미 포화 상태면 0.90 상향이 의미 없음 — 더 큰 GPU 검토)
- [ ] after Pod 가 `kubectl rollout status` timeout 안에 Ready (cold start 정상)
- [ ] after `vllm:num_requests_waiting` 가 baseline 대비 *동등하거나 감소* (증가하면 0.90 풀이 부족 → 더 큰 GPU 검토)

---

## §4. 메트릭 해석 (부하 테스트 관점)

Day 7 의 `lesson.md` §6 가 메트릭 *정의* 를 다뤘다면, 여기서는 **부하 변화에 따라 이 값들이 어떻게 움직이는가** 를 봅니다.

### §4.1 vLLM 6 종 (`/metrics` 자동 노출)

| 메트릭 | 정상 범위 (캡스톤) | 부하 c=8 | 부하 c=16 | 부하 c=32 | 해석 |
|---|---|---|---|---|---|
| `vllm:num_requests_running` | 0~16 | 8~10 | 12~15 | 14~16 (상한) | continuous batching 효과. 1~2 만 보이면 *부하 부족 또는 병목 다른 곳* |
| `vllm:num_requests_waiting` | 0 정상 | 0 | 0~2 | 2~10 | 0 이 아닌 지속 = KV cache 풀 한계. 0.90 상향 후 줄면 튜닝 효과 입증 |
| `vllm:gpu_cache_usage_perc` | 0.6~0.95 | 0.85 | 0.88~0.92 | 0.92~0.95 | 0.95+ 가 지속되면 OOM 위험 (자주 하는 실수 #25) |
| `vllm:time_to_first_token_seconds` (p95) | 0.3~1.5s | 0.4s | 0.7s | 1.2s | 사용자 체감 *반응성* 의 핵심 지표 |
| `vllm:e2e_request_latency_seconds` (p95) | 0.8~3.0s | 1.0s | 1.8s | 2.7s | TTFT + 토큰 생성 합산 |
| `vllm:generation_tokens_total` (rate) | 사용자 평균 100~300 토큰 | ~1.5K tok/s | ~2.4K tok/s | ~2.8K tok/s | *토큰/sec* 처리량 |

### §4.2 RAG API 4 종 (Day 5 코드)

| 메트릭 | 정상 범위 | 부하 c=8 | 부하 c=16 | 부하 c=32 | 해석 |
|---|---|---|---|---|---|
| `rag_chat_total{status="200"}` (rate) | n/a | ~12 RPS | ~18 RPS | ~22 RPS (포화) | end-to-end 성공 RPS |
| `rag_chat_latency_seconds` (p95) | 1~3s | 2.0s | 2.8s | 4.0s | end-to-end SLO |
| `rag_retrieve_latency_seconds` (p95) | 50~200ms | 100ms | 150ms | 200ms | retriever 병목 분리 — Qdrant 가 한계인지 확인 |
| `rag_llm_latency_seconds` (p95) | 0.8~2.5s | 1.7s | 2.5s | 3.5s | vLLM 병목 분리 — `vllm:e2e_request_latency_seconds` 와 거의 동일해야 함 |

### §4.3 병목 진단 의사결정 트리

```
chat p95 가 SLO (3s) 초과
├── retrieve_latency p95 > 500ms?  ── YES → Qdrant 부하 (Day 7 §6.3 부재)
│                                        └── Day 10 후 점검 또는 더 큰 노드
├── llm_latency p95 ≈ chat_latency p95?  ── YES → vLLM 병목
│   ├── vllm:num_requests_waiting > 0 지속?  ── YES → KV cache 한계 (0.90 상향 또는 더 큰 GPU)
│   ├── vllm:gpu_cache_usage_perc > 0.95?  ── YES → 0.95+ 위험 (자주 하는 실수 #25)
│   └── vllm:num_requests_running 4 이하?  ── YES → 부하 부족 또는 RAG API HPA 한계
└── chat_latency >> retrieve + llm?  ── YES → RAG API 자체 (FastAPI 동기 호출, Day 5 §3.1)
```

> 학습 포인트: 단계별 메트릭 4 + 6 = 10 개를 *동시* 보지 않고 chat_latency 만 보면 *병목 컴포넌트* 를 오진단합니다 (자주 하는 실수 #26).

---

## §5. `load_test.sh` 사용법 + before/after 비교 표 템플릿

### §5.1 기본 사용법

```bash
# 1) baseline (gpu-memory-utilization=0.85)
LABEL=baseline bash load_test.sh
# → results/baseline-c8.txt, baseline-c16.txt, baseline-c32.txt 생성

# 2) vLLM args patch (labs/day-09 Step 7)
kubectl patch deployment vllm -n rag-llm --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/args/2","value":"--gpu-memory-utilization=0.90"}]'
kubectl rollout status deployment/vllm -n rag-llm --timeout=180s

# 3) after 측정
LABEL=after bash load_test.sh
# → results/after-c8.txt, after-c16.txt, after-c32.txt 생성
```

### §5.2 단일 동시성만 재측정

```bash
# c=16 만 다시 측정 (특정 단계 노이즈 의심 시)
LABEL=baseline CONCURRENCY=16 SINGLE=1 bash load_test.sh
```

### §5.3 환경 변수 표

| 변수 | 기본값 | 설명 |
|---|---|---|
| `INGRESS_HOST` | `kubectl` 자동 추출 | `<EXTERNAL_IP>.nip.io` 형태. 비어 있으면 `kubectl get ing rag-api ...` 으로 자동 |
| `TARGET_PATH` | `/chat` | Day 6 Ingress path |
| `DURATION` | `60s` | hey `-z` |
| `CONCURRENCY` | `8/16/32` 순차 | `SINGLE=1` 일 때만 단일 사용 |
| `LABEL` | `baseline` | 결과 파일 prefix (`baseline-c8.txt` 등) |
| `SINGLE` | `0` | `1` 이면 `CONCURRENCY` 한 단계만 |
| `WARMUP_REQS` | `5` | 워밍업 요청 수 |
| `RESULTS_DIR` | `results` | 결과 저장 디렉토리 |

### §5.4 before/after 비교 표 템플릿 (학습자 채움)

> Day 9 lab Step 9 에서 본 표를 복사해 5 지표 모두 채웁니다. 절대값보다 *변화 방향* 이 학습 포인트.

| 시나리오 | hey RPS | hey 95% | hey 99% | `vllm:num_requests_running` 평균 | `vllm:gpu_cache_usage_perc` 평균 | 200 OK 비율 |
|---|---|---|---|---|---|---|
| baseline c=8 (0.85) | _____ | _____ s | _____ s | _____ | _____ | _____ % |
| baseline c=16 (0.85) | _____ | _____ s | _____ s | _____ | _____ | _____ % |
| baseline c=32 (0.85) | _____ | _____ s | _____ s | _____ | _____ | _____ % |
| after c=8 (0.90) | _____ | _____ s | _____ s | _____ | _____ | _____ % |
| after c=16 (0.90) | _____ | _____ s | _____ s | _____ | _____ | _____ % |
| after c=32 (0.90) | _____ | _____ s | _____ s | _____ | _____ | _____ % |

**해석 한 단락 (예시)**:

> baseline c=16 의 `num_requests_running` 평균이 _____ 였고, after 에서는 _____ 로 _____ % 증가했습니다. 이는 KV cache 풀 확대로 continuous batching 의 효과가 _____ 했음을 의미합니다. p95 latency 는 _____ 변화했고, 200 OK 비율이 _____ % 였습니다. *병목* 은 `chat_latency` ≈ `llm_latency` _____ 이므로 vLLM / RAG API / Qdrant 중 _____ 입니다.

---

## §6. 다음 단계

- **Day 10 Helm 차트**: `values.yaml` 의 `gpuMemoryUtilization: 0.85` 기본값. Day 9 의 0.90 patch 는 학습 lab 한정이므로 정리 분기 A 에서 *0.85 로 롤백* 후 Day 10 진행 권장
- **Phase 5 v2 확장 후보**: `--enable-prefix-caching` 적용 후 retrieve_latency 영향 0 + llm_latency 10~30% 감소 검증, `--quantization=awq` 로 더 큰 모델(Qwen2.5-7B) 시도
- **운영 도입 시 추가 점검**:
  - GPU 노드 풀 size > 1 + vLLM HPA `maxReplicas` 노드 수 - 1 (체험형 학습 #24 해소)
  - SealedSecrets / External Secrets Operator 로 HF_TOKEN 평문 placeholder 교체
  - DCGM exporter 로 GPU utilization / memory / temperature 추가 수집

---

## §7. 참고

- 부하 명령 패턴: [`labs/day-08-grafana-hpa.md`](../../labs/day-08-grafana-hpa.md) Step 6 (`hey 60s c=8` 한 번 발사 — Day 9 의 c=8 단계와 결과 비교 가능)
- vLLM 본문 노트: [`course/phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md`](../../../phase-4-ml-on-k8s/03-vllm-llm-serving/lesson.md) §1-4 ~ §1-6
- vLLM 자주 하는 실수 3종 (Phase 4-3): GPU 격리 누락 / `/dev/shm` 4Gi 누락 / `--gpu-memory-utilization` 0.95+ — 캡스톤 §10 #25 가 마지막 항목을 직접 인용
- 캡스톤 메트릭 표: [`lesson.md`](../../lesson.md) §6 (Day 7 작성, Day 8 Grafana 4 패널과 1:1 대응)
- 캡스톤 HPA 결정: [`docs/architecture.md`](../../docs/architecture.md) §3.13 (Day 8) + §3.14 (Day 9, 부하 테스트 + 튜닝 결정)
