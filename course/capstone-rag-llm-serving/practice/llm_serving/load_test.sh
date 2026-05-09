#!/usr/bin/env bash
# Capstone Day 9 — RAG end-to-end 부하 테스트 스크립트
# 베이스: .claude/skills/k8s-ml-course-author/assets/templates/practice/load_test.sh.tmpl
# 변경점: TARGET_URL → /chat, 페이로드 RAG ChatRequest, c=8/16/32 3 단계 순차 + LABEL/CONCURRENCY 환경변수
#
# 설치: hey (https://github.com/rakyll/hey)
#   - macOS: brew install hey
#   - Linux: go install github.com/rakyll/hey@latest
#
# 사용법:
#   # 1) baseline (gpu-memory-utilization=0.85)
#   LABEL=baseline bash load_test.sh
#   # 2) vLLM args patch 후
#   LABEL=after bash load_test.sh
#   # 3) 단일 동시성만 실행
#   LABEL=baseline CONCURRENCY=16 SINGLE=1 bash load_test.sh

set -euo pipefail

# ===== 설정 =====
INGRESS_HOST="${INGRESS_HOST:-}"                   # 비어 있으면 자동 추출
TARGET_PATH="${TARGET_PATH:-/chat}"                # Day 6 Ingress
DURATION="${DURATION:-60s}"                        # hey -z
CONCURRENCY="${CONCURRENCY:-}"                     # SINGLE=1 일 때만 사용
LABEL="${LABEL:-baseline}"                         # 결과 파일 prefix (baseline | after)
SINGLE="${SINGLE:-0}"                              # 1 이면 CONCURRENCY 한 단계만 실행
WARMUP_REQS="${WARMUP_REQS:-5}"                    # 워밍업 요청 수
RESULTS_DIR="${RESULTS_DIR:-results}"

# Day 5 RAG ChatRequest 페이로드 (Day 8 Step 6 와 동일)
PAYLOAD='{"messages":[{"role":"user","content":"K8s에서 GPU 어떻게 잡지?"}],"top_k":3}'
# ================

# 사전 점검
if ! command -v hey >/dev/null 2>&1; then
  echo "Error: 'hey' is not installed."
  echo "Install: brew install hey  (or)  go install github.com/rakyll/hey@latest"
  exit 1
fi

if [ -z "$INGRESS_HOST" ]; then
  if ! command -v kubectl >/dev/null 2>&1; then
    echo "Error: INGRESS_HOST 가 비어 있고 kubectl 도 없습니다."
    echo "예: INGRESS_HOST=34.120.x.x.nip.io bash load_test.sh"
    exit 1
  fi
  INGRESS_HOST=$(kubectl get ing rag-api -n rag-llm -o jsonpath='{.spec.rules[0].host}' 2>/dev/null || true)
  if [ -z "$INGRESS_HOST" ]; then
    echo "Error: Ingress host 추출 실패. Day 6 Ingress 가 ADDRESS 를 받았는지 확인하세요."
    exit 1
  fi
fi

TARGET_URL="http://${INGRESS_HOST}${TARGET_PATH}"
mkdir -p "$RESULTS_DIR"

run_one() {
  local c="$1"
  local outfile="${RESULTS_DIR}/${LABEL}-c${c}.txt"

  echo ""
  echo "=== Load Test [LABEL=${LABEL}, CONCURRENCY=${c}] ==="
  echo "Target:      $TARGET_URL"
  echo "Duration:    $DURATION"
  echo "Output:      $outfile"
  echo ""

  hey \
    -z "$DURATION" \
    -c "$c" \
    -m POST \
    -T "application/json" \
    -d "$PAYLOAD" \
    "$TARGET_URL" | tee "$outfile"

  # hey 출력에서 핵심 지표 한 줄 요약 (Slowest / Fastest / Average / 95% / 99% / 200 OK 수)
  local slowest fastest average p95 p99 ok2xx
  slowest=$(grep -E "^\s*Slowest:"  "$outfile" | awk '{print $2}')
  fastest=$(grep -E "^\s*Fastest:"  "$outfile" | awk '{print $2}')
  average=$(grep -E "^\s*Average:"  "$outfile" | awk '{print $2}')
  p95=$(awk '/Latency distribution/,/^$/' "$outfile" | grep "95% in" | awk '{print $3}')
  p99=$(awk '/Latency distribution/,/^$/' "$outfile" | grep "99% in" | awk '{print $3}')
  ok2xx=$(awk '/Status code distribution/,/^$/' "$outfile" | grep -E "\[200\]" | awk '{print $2}')

  echo ""
  echo "[summary] LABEL=${LABEL} c=${c} | slow=${slowest:-?} fast=${fastest:-?} avg=${average:-?} p95=${p95:-?} p99=${p99:-?} 200_ok=${ok2xx:-0}"
}

# 워밍업 (cold start 와 분리)
echo "Warming up ${WARMUP_REQS} 회 (c=4) — vLLM 캐시 hit 확인..."
for i in $(seq 1 "$WARMUP_REQS"); do
  curl -s -o /dev/null -w "  attempt $i: %{http_code} (%{time_total}s)\n" \
    -X POST "$TARGET_URL" \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" || true
done

# 본 테스트
if [ "$SINGLE" = "1" ]; then
  if [ -z "$CONCURRENCY" ]; then
    echo "Error: SINGLE=1 일 때 CONCURRENCY 가 필요합니다 (예: CONCURRENCY=16)."
    exit 1
  fi
  run_one "$CONCURRENCY"
else
  for c in 8 16 32; do
    run_one "$c"
    echo ""
    echo ">>> 다음 단계 시작 전 5 초 대기 (메트릭 stabilization) <<<"
    sleep 5
  done
fi

echo ""
echo "=== Done ==="
echo "결과 파일: ls -lh $RESULTS_DIR/"
echo "Tip: 다른 터미널에서 다음 명령으로 HPA / Pod 변동을 관찰하세요"
echo "  watch -n 5 kubectl get hpa,pods -n rag-llm"
echo "Tip: Prometheus 메트릭 동시 캡처는 labs/day-09-load-test-tuning.md Step 6 PromQL 4 종을 참고하세요."
