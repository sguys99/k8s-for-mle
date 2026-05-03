# Job & CronJob — 단발 배치 추론과 일별 평가 자동화

> **Phase**: 2 — 운영에 필요한 K8s 개념 (네 번째 토픽)
> **소요 시간**: 40–60분 (02 의 model-cache PVC 가 살아있으면 모델 다운로드 없음)
> **선수 학습**:
> - [Phase 2 / 02-volumes-pvc — Volumes & PVC](../02-volumes-pvc/lesson.md)
> - [Phase 2 / 03-ingress — Ingress](../03-ingress/lesson.md)

## 학습 목표

이 챕터를 마치면 다음을 할 수 있습니다.

- Job 과 Deployment 의 라이프사이클 차이 — `restartPolicy` 허용값, **terminal phase(Complete/Failed)** 의 존재, `replicas` 와 `completions/parallelism` 의 의미 차이 — 를 표로 설명하고, 동일한 `sentiment-api:v1` 이미지를 [job.yaml](manifests/job.yaml) 로 적용했을 때 Pod 가 `Running → Completed` 로 전이한 뒤 사라지는 것을 `kubectl get pods -w` 로 직접 관찰할 수 있습니다.
- `backoffLimit` / `activeDeadlineSeconds` / `ttlSecondsAfterFinished` 세 시간·재시도 필드를 [failing-job.yaml](manifests/failing-job.yaml) 로 의도적으로 실패시켜 각각이 어느 시점에 발동하는지 — Pod 단위 재시도 / 잡 단위 강제 종료 / 완료 후 자동 정리 — 를 구분하고, `kubectl describe job` 의 `Conditions` 에 `BackoffLimitExceeded` 가 적히는 시점을 직접 확인할 수 있습니다.
- CronJob 의 `schedule` (cron 5필드), `timeZone: "Asia/Seoul"` (K8s 1.27+), `concurrencyPolicy: Forbid|Allow|Replace`, `successfulJobsHistoryLimit`, `startingDeadlineSeconds`, `suspend` 의 의미와 운영 권장값을 설명하고, `kubectl create job <name> --from=cronjob/daily-eval` 로 다음 schedule 을 기다리지 않고 즉시 1번 실행하는 운영 노하우를 적용할 수 있습니다.
- 02 의 `model-cache` PVC 를 그대로 마운트해 모델 가중치 다운로드를 스킵하고, 본 토픽에서 신규로 만든 [eval-results PVC](manifests/results-pvc.yaml) 에 평가 결과를 누적해 **라이프사이클이 분리된 두 PVC 를 동시에 사용** 하는 패턴을 매니페스트로 구현할 수 있습니다.

## 왜 ML 엔지니어에게 필요한가

03 까지의 [`deployment.yaml`](../02-volumes-pvc/manifests/deployment.yaml) + [`service.yaml`](../02-volumes-pvc/manifests/service.yaml) + [`ingress.yaml`](../03-ingress/manifests/ingress.yaml) 은 모두 **"오래 떠 있는 모델 서빙(long-running)"** 을 위한 오브젝트였습니다. 그러나 ML 운영의 다른 한 축은 **"한 번 실행되고 끝나는(terminal) 워크로드"** 입니다 — 평가 데이터셋 일괄 추론, 임베딩 갱신, 데이터 전처리, fine-tuning 잡, 모델 변환(quantization) 등입니다. 이 자리에서 Deployment 를 쓰면 ① 잡이 끝나도 Pod 이 살아 자원을 낭비하고 ② 실패 시 무한 재시작되며 ③ "지난 화요일 평가 결과는 어디 있지?" 같은 이력 추적이 어렵습니다. 정확히 이 자리에 들어가는 것이 Job 과 CronJob 입니다. ML 운영에서 두 오브젝트가 특별히 중요한 이유는 셋입니다. ① **모델 드리프트 감지** — 같은 평가 데이터셋으로 매일 모델 정확도를 측정해 추이를 추적하는 것은 사람이 손으로 돌리지 않고 CronJob 으로 자동화합니다. 그 결과는 Phase 3 의 Prometheus / Grafana 메트릭과 자연스럽게 연결됩니다. ② **자원·비용 효율** — GPU 가 필요한 배치 추론은 8시간 한 번 돌고 나면 노드를 반납해야 합니다. 항상 떠 있는 GPU Deployment 는 비용 폭탄입니다. Job 은 종료가 명시적이라 cluster autoscaler 가 노드를 회수하기 좋습니다. ③ **Phase 4 분산 학습의 토대** — Kubeflow Training Operator (`PyTorchJob`, `TFJob`) 와 KubeRay (`RayJob`) 모두 본 토픽의 K8s Job 위에 얹힌 Custom Resource 입니다. 본 토픽의 `restartPolicy: OnFailure`, `backoffLimit`, `activeDeadlineSeconds` 가 그대로 동작하므로 여기서 익힌 직관이 Phase 4 에서 그대로 쓰입니다.

## 1. 핵심 개념

### 1-1. Job vs Deployment — terminal vs long-running

같은 K8s 의 워크로드 오브젝트지만 라이프사이클 모델이 정반대입니다. 표로 정리합니다.

| 구분 | Deployment | Job |
|------|-----------|-----|
| **수명** | 사람이 멈추기 전까지 영원히 (long-running) | 작업이 끝나면 종료 (terminal) |
| **개수 표현** | `replicas` (동시에 살아 있어야 할 Pod 수) | `completions` (총 몇 번 완료) + `parallelism` (동시에 몇 개) |
| **종료 조건** | 없음 (항상 desired state 유지) | 컨테이너가 exit 0 → Complete / `backoffLimit` 초과 → Failed |
| **terminal phase** | 없음 (Pod 만 있고 Deployment 자체는 phase 없음) | **Complete / Failed** (한 번 들어가면 status 그대로 보존) |
| **`restartPolicy`** | **Always 만 허용** | **OnFailure 또는 Never 만 허용** (Always 는 apply 거절) |
| **실패 시 동작** | Pod 가 죽으면 ReplicaSet 이 새로 띄워 desired replica 유지 | `backoffLimit` 횟수만큼 재시도 → 초과 시 Job 자체가 Failed |
| **ML 활용 예시** | 모델 서빙 API (FastAPI, KServe), 벡터 DB(StatefulSet) | 배치 추론, fine-tuning, 임베딩 갱신, 데이터 전처리 |

핵심은 **terminal phase의 존재** 입니다. Deployment 는 끝이 없으므로 history 라는 개념이 없지만, Job 은 "2026-04-15 의 평가 결과" 처럼 시점이 박힌 결과물이 자연스럽게 남습니다. CronJob 의 `successfulJobsHistoryLimit` 가 그 history 를 K8s 가 자동으로 관리해 주는 도구입니다 (1-4 절).

### 1-2. Job 의 spec — restartPolicy, completions, parallelism, backoffLimit

본 토픽 [job.yaml](manifests/job.yaml) 의 `spec` 핵심 4개 필드를 정리합니다.

| 필드 | 본 토픽 값 | 의미 / 함정 |
|------|----------|------------|
| `template.spec.restartPolicy` | **`OnFailure`** | Job 은 `Always` 자체가 거절됩니다 (`The Job "..." is invalid: ... restartPolicy: Required value: valid values: "OnFailure", "Never"` — 자주 하는 실수 1번). `OnFailure` 는 같은 Pod 안에서 컨테이너만 재시작 (모델 캐시 살아있어 빠름), `Never` 는 새 Pod 을 띄움 (격리 강해 디버깅 유리, 모델 재로딩) |
| `completions` | `1` | 총 몇 번의 성공적 완료가 필요한지. 본 토픽은 단발 1회. 평가 데이터셋을 N 분할해 병렬 처리하려면 `completions: N` + `completionMode: Indexed` (Indexed Job) — Phase 4 분산 패턴 |
| `parallelism` | `1` | 동시에 떠 있을 수 있는 Pod 수. `parallelism > completions` 는 무의미 (완료 후 더 안 띄움). 본 토픽은 1 |
| `backoffLimit` | `2` | 컨테이너 실패 시 최대 재시도 횟수. **기본 6 의 함정** — 빠르게 실패하는 컨테이너에 6번 재시도가 붙으면 Pod 6개가 `Error` 상태로 누적되며 학습자가 "잡이 멈추질 않는다" 고 오해 (자주 하는 실수 2번). 운영에서는 명시적으로 작게(2~3) |

```yaml
# job.yaml 에서 발췌한 핵심 라인
spec:
  backoffLimit: 2
  completions: 1
  parallelism: 1
  template:
    spec:
      restartPolicy: OnFailure          # Always 는 사용 불가
      containers:
        - name: batch
          image: sentiment-api:v1
          command: ["python", "/scripts/batch_inference.py"]
```

> 💡 **실패 vs 강제 종료**: `backoffLimit` 초과로 Job 이 끝나면 `kubectl describe job` 의 `Conditions` 에 `Reason: BackoffLimitExceeded` 가 적히고, `activeDeadlineSeconds` 초과로 끝나면 `Reason: DeadlineExceeded` 가 적힙니다. 두 종료 사유는 모니터링 알람을 다르게 잡고 싶을 때 의미 있게 구분됩니다.

### 1-3. activeDeadlineSeconds 와 ttlSecondsAfterFinished — 두 시간 필드의 차이

이름이 비슷해서 자주 혼동되지만 작동 시점과 결과가 완전히 다릅니다.

| 필드 | 작동 시점 | 발동 결과 | 본 토픽 값 | 미설정 시 문제 |
|------|----------|----------|----------|--------------|
| `activeDeadlineSeconds` | **잡 실행 중** (시작 후 N 초가 지나면) | controller 가 Pod 들에 SIGTERM → 잡이 `Failed (DeadlineExceeded)` | **600** (10분, [job.yaml](manifests/job.yaml)) / **1800** (30분, [cronjob.yaml](manifests/cronjob.yaml) jobTemplate) | 무한 — 데이터 폭증 / 데드락으로 잡이 영원히 안 끝나도 자원 점유 계속 |
| `ttlSecondsAfterFinished` | **잡 완료 후** (Complete 또는 Failed 진입 후 N 초) | Job 오브젝트와 그 Pod 들이 자동 삭제 | **1800** (30분, [job.yaml](manifests/job.yaml)) / **86400** (1일, [cronjob.yaml](manifests/cronjob.yaml)) | `kubectl get jobs/pods` 출력에 과거 잡이 영원히 누적 → etcd 부담, 운영자 가독성 ↓ |

```yaml
# job.yaml — 두 필드 함께 적용
spec:
  activeDeadlineSeconds: 600         # 실행 중 10분 넘으면 강제 종료 (방어막)
  ttlSecondsAfterFinished: 1800      # 완료 후 30분 지나면 Pod/Job 자동 삭제 (정리)
```

> ⚠️ **함정**: `activeDeadlineSeconds` 는 잡 시작 시점부터 카운트되므로, `parallelism > 1` 인 잡에서 일부 Pod 만 늦게 시작했어도 deadline 초과 시 모든 Pod 이 동시에 종료됩니다. 그래서 deadline 은 한 분할이 아닌 **전체 잡의 최악 실행 시간** 으로 잡아야 합니다.

### 1-4. CronJob — schedule, timeZone, concurrencyPolicy

CronJob 은 **"미리 정의된 jobTemplate 으로 schedule 시각마다 Job 을 만들어 주는 controller"** 입니다. CronJob 자체는 직접 Pod 을 띄우지 않습니다 — 매번 새 Job 을 만들고, 그 Job 이 Pod 을 띄웁니다. 03 의 "Resource vs Controller" 분리 패턴이 여기서도 **"CronJob → Job → Pod"** 의 3계층으로 등장합니다.

#### cron 표현식 5필드

```
┌──────── 분 (0-59)
│ ┌────── 시 (0-23)
│ │ ┌──── 일 (1-31)
│ │ │ ┌── 월 (1-12)
│ │ │ │ ┌ 요일 (0-6, 일요일=0)
│ │ │ │ │
0 3 * * *
```

| 표현 | 의미 |
|------|------|
| `0 3 * * *` | 매일 03:00 — **본 토픽 [cronjob.yaml](manifests/cronjob.yaml)** |
| `*/15 * * * *` | 15분마다 |
| `0 */6 * * *` | 6시간마다 정각 (00:00, 06:00, 12:00, 18:00) |
| `0 9 * * 1-5` | 평일 09:00 |
| `30 1 1 * *` | 매월 1일 01:30 |

#### timeZone — K8s 1.27+ 의 안전장치

```yaml
spec:
  schedule: "0 3 * * *"
  timeZone: "Asia/Seoul"             # 미지정 시 controller-manager 의 기본 TZ (보통 UTC)
```

`timeZone` 을 안 쓰면 의도한 KST 03:00 이 UTC 03:00 = KST 12:00 (정오) 로 발동되는 함정이 있습니다. K8s 1.27 이전 클러스터에서는 cron 표현식에 직접 UTC 로 환산해 적어야 합니다 (KST 03:00 = UTC 18:00 → `0 18 * * *`).

#### concurrencyPolicy — 이전 실행이 안 끝났을 때 동작

| 정책 | 동작 | 적합한 시나리오 | 자주 하는 실수 |
|------|------|---------------|---------------|
| `Allow` (기본) | 이전 실행 무시하고 새 Job 시작 | 실행 시간이 schedule 주기보다 항상 짧고 잡끼리 독립적인 경우 | **자주 하는 실수 3번** — PVC 락 충돌, GPU 메모리 폭발, 결과 파일 동시 쓰기 |
| **`Forbid`** | 이전 실행이 끝날 때까지 새 실행 스킵 (이번 회차는 영영 안 돎) | **본 토픽 권장값.** 결과 파일이 누적되는 평가 잡, 같은 PVC 를 쓰는 잡 | 잡이 평소보다 오래 걸린 회차의 다음 schedule 이 통째로 스킵됨을 모르고 결과 누락에 당황 |
| `Replace` | 이전 실행을 죽이고 새로 시작 | 최신성이 중요한 잡 (실시간 인덱스 갱신, 캐시 워밍) | 죽은 이전 잡의 부분 결과가 남아 다음 분석을 오염 |

#### Job history limit

```yaml
successfulJobsHistoryLimit: 3        # 성공 Job 은 최근 3개만 보존
failedJobsHistoryLimit: 5            # 실패 Job 은 최근 5개 (디버깅 여유)
```

이 값을 너무 크게(예: 100) 두면 매일 도는 잡이라면 100일치가 etcd 에 쌓입니다. 너무 작게(0) 두면 디버깅용 과거 로그를 잃습니다. 본 토픽의 3 / 5 가 운영에서 무난한 기본값입니다.

### 1-5. CronJob 운영 패턴 — startingDeadlineSeconds, suspend, 수동 트리거

본 절의 세 가지가 schedule 만 알면 알 수 없는 **운영 노하우** 입니다.

#### startingDeadlineSeconds — 놓친 schedule 의 처리

controller-manager 가 정전·재기동·일시적 장애로 schedule 시각을 놓쳤을 때 **얼마나 늦게까지 만회 실행** 할지 결정합니다.

```yaml
spec:
  startingDeadlineSeconds: 600       # 10분 늦은 시작까지 허용
```

미설정 시 무한 — controller 재기동 직후 그동안 놓친 모든 회차를 한꺼번에 실행하려 시도해 부하 폭주 위험이 있습니다. 본 토픽 [cronjob.yaml](manifests/cronjob.yaml) 은 600 초로 두어 10분 늦은 한 회차까지만 만회합니다.

#### suspend — 운영 중 일시 중지

배포 윈도우, 데이터 파이프라인 점검, 알람 폭주 등으로 잠시 도는 것을 멈추고 싶을 때 매니페스트를 지우지 않고 끕니다.

```bash
# 일시 중지
kubectl patch cronjob daily-eval -p '{"spec":{"suspend":true}}'

# 재개
kubectl patch cronjob daily-eval -p '{"spec":{"suspend":false}}'
```

`suspend: true` 면 controller 가 schedule 시각이 와도 Job 을 만들지 않습니다. 매니페스트는 그대로 남아 있어 점검 후 한 줄로 복구됩니다.

#### 수동 트리거 — `kubectl create job ... --from=cronjob/...`

**다음 schedule 을 기다리지 않고 즉시 한 번 실행** 하는 운영의 단골 명령입니다. CronJob 의 jobTemplate 을 그대로 복제해 새 Job 을 만들어 줍니다.

```bash
kubectl create job batch-eval-manual --from=cronjob/daily-eval
```

**언제 쓰나**: ① 새 잡 매니페스트 동작 검증 (1번 돌려보고 잘 되는지 확인) ② 정전·서비스 장애로 놓친 회차를 사람이 만회 ③ 평가 데이터셋이 갱신된 직후 즉시 결과 보고 싶을 때. 본 토픽 lab 5 단계가 이 명령으로 schedule 을 기다리지 않고 즉시 시연합니다.

### 1-6. 데이터 입출력 패턴 — ConfigMap 스크립트 + 두 PVC

본 토픽 매니페스트는 sentiment-api:v1 이미지를 그대로 재사용하면서, **새 Docker 이미지를 빌드하지 않기 위해** ConfigMap 에 Python 스크립트와 입력 데이터를 함께 넣었습니다. 어디에 무엇을 두는지 정리합니다.

| 데이터 종류 | 어디에 | 본 토픽 매니페스트 | 운영 변형 |
|------------|--------|------------------|----------|
| **모델 가중치** (~500MB) | PVC `model-cache` | 02 에서 만든 PVC 그대로 재사용 ([02 pvc.yaml](../02-volumes-pvc/manifests/pvc.yaml)) | S3 → init container 로 PVC 캐시 (02 패턴 동일) |
| **실행 코드** (`batch_inference.py`, `evaluate.py`) | ConfigMap `eval-scripts` | [scripts-configmap.yaml](manifests/scripts-configmap.yaml) `data:` | Docker 이미지에 포함 — CI 가 있다는 전제. 본 토픽은 학습 단순화로 ConfigMap |
| **입력 데이터** (`sample-input.jsonl`, 8건) | 같은 ConfigMap 의 다른 키 | [scripts-configmap.yaml](manifests/scripts-configmap.yaml) `sample-input.jsonl` | S3 → 별도 입력 PVC. 또는 init container 로 다운로드 |
| **추론·평가 결과** (`inference-*.jsonl`, `eval-*.json`) | PVC `eval-results` (신규) | [results-pvc.yaml](manifests/results-pvc.yaml) | S3 / 메트릭 시스템 (Prometheus pushgateway, MLflow) |

**왜 model-cache 와 eval-results 를 분리했나**: 라이프사이클이 다릅니다. 모델 캐시는 거의 변하지 않고 여러 토픽이 공유하지만, 평가 결과는 매일 누적되며 한두 달에 한 번 비울 수 있습니다. 보존 정책·백업 주기가 다른 데이터를 같은 PVC 에 두면 한쪽 정책에 다른 쪽이 끌려갑니다.

```yaml
# job.yaml — 두 PVC 를 동시에 마운트
volumes:
  - name: model-cache
    persistentVolumeClaim: { claimName: model-cache }      # 02 PVC, 읽기 위주
  - name: results
    persistentVolumeClaim: { claimName: eval-results }     # 신규 PVC, 쓰기 위주
```

> 💡 **운영에서의 진화**: 배치 잡이 늘어나면 [job.yaml](manifests/job.yaml) 의 `command/args` 를 매번 손으로 고치는 게 부담이 됩니다. 그때는 (a) 잡별 ConfigMap 분리 (b) Helm chart 로 templating (Phase 3) (c) Argo Workflows 의 DAG 로 통합 (Phase 4-4) 순으로 진화합니다.

### 1-7. ML 워크로드별 활용 시나리오

언제 Job, 언제 CronJob, 언제 둘 다 아닌지 표로 정리합니다.

| 시나리오 | 오브젝트 | 핵심 필드 권장값 | 비고 |
|---------|---------|---------------|------|
| **단발 배치 추론** (1만 건 평가셋 1회) | Job | `backoffLimit: 2`, `activeDeadlineSeconds: 7200`, `parallelism: 1` | 본 토픽 [job.yaml](manifests/job.yaml) 의 시나리오. GPU 시 `nvidia.com/gpu: 1` 추가 |
| **일별 평가** (모델 드리프트 추적) | CronJob | `schedule: "0 3 * * *"`, `concurrencyPolicy: Forbid`, `successfulJobsHistoryLimit: 3` | 본 토픽 [cronjob.yaml](manifests/cronjob.yaml) 의 시나리오 |
| **데이터 전처리** (학습 직전 정제) | Job | `parallelism: 4`, `completions: 4`, `completionMode: Indexed` | Indexed Job 으로 데이터셋 4분할 병렬 처리 |
| **임베딩 갱신** (신규 문서 1시간마다) | CronJob | `schedule: "0 * * * *"`, `concurrencyPolicy: Replace` | 최신성 우선 — 이전 실행을 죽이고 새로 시작 |
| **Fine-tuning 잡** (수 시간 GPU) | Job (Phase 4 에서 PyTorchJob) | `backoffLimit: 1`, `activeDeadlineSeconds: 86400`, `nvidia.com/gpu: N` | 학습 손실 발산 시 자동 재시도 가치 낮음 → backoff 작게 |
| **모델 변환** (양자화, ONNX export) | Job | `backoffLimit: 1`, `ttlSecondsAfterFinished: 0` (즉시 정리) | 1회성 마이그레이션 작업 |
| **장기 서빙 API** | **Deployment** | (본 토픽 범위 밖) | 끝이 없는 워크로드는 Job 이 아니라 Deployment |
| **스트리밍 처리** | **Deployment + Kafka 컨슈머** | (본 토픽 범위 밖) | "끝없이 흘러오는 이벤트" 는 Job 이 아님 |

## 2. 실습 — 핵심 흐름 (8단계 요약)

자세한 명령과 예상 출력은 [labs/README.md](labs/README.md) 를 따릅니다. 여기서는 흐름과 학습 포인트만 짚습니다.

| 단계 | 핵심 동작 | 학습 포인트 |
|------|----------|-------------|
| 0 | 사전 점검 (minikube, kubectl context, sentiment-api:v1, 02 자산) | 02 의 ConfigMap/Secret/PVC 가 살아있다면 그대로 재사용 — 첫 다운로드 30–60초 절약 |
| 1 | 02 자산 보강(필요 시) + 본 토픽 신규 자산(`results-pvc.yaml`, `scripts-configmap.yaml`) 적용 | 두 PVC 가 모두 `Bound` 됨 확인 — 라이프사이클 분리의 시작점 |
| 2 | `kubectl apply -f manifests/job.yaml` → `kubectl get pods -w` 로 라이프사이클 관찰 | `ContainerCreating → Running → Completed` 전이, jobs 의 `COMPLETIONS` 0/1 → 1/1 |
| 3 | 결과 확인 — `kubectl logs job/...` + `kubectl debug` 로 PVC 안의 jsonl 직접 읽기 | ConfigMap 스크립트 + PVC 결과 패턴이 실제로 동작함을 눈으로 검증 |
| 4 | `kubectl describe job` 으로 시간 필드 확인 | `Backoff Limit`, `Active Deadline Seconds`, `Conditions` 필드가 매니페스트 값 그대로 표시됨을 확인 |
| 5 | CronJob 적용 + 수동 트리거(`kubectl create job ... --from=cronjob/daily-eval`) | 다음 schedule 을 기다리지 않고 즉시 1회 실행, eval-YYYYMMDD.json 결과 누적 확인 |
| 6 | `failing-job.yaml` 적용 → `BackoffLimitExceeded` 직접 관찰 | 3회(원래 1 + 재시도 2) 실패 후 Job 이 `Failed` 로 전이, Conditions 에 `BackoffLimitExceeded` 표시 |
| 7 | (선택) `concurrencyPolicy: Forbid` 시뮬 — schedule 을 매분으로 일시 변경 + sleep 90 | 두 번째 실행이 첫 번째가 끝날 때까지 `Active=0` 으로 스킵되는지 관찰, 원복 |
| 8 | 정리 — failing → cronjob → job → results-pvc → scripts-cm 순서, model-cache 는 보존 권장 | Job/CronJob 의 라이프사이클이 model-cache PVC 와 분리됨을 인식 |

## 3. 검증 체크리스트

다음 항목을 모두 확인했다면 이 챕터를 마쳤다고 볼 수 있습니다.

- [ ] `kubectl get pvc` 가 `model-cache (Bound)` 와 `eval-results (Bound)` 두 PVC 를 표시함을 확인했습니다.
- [ ] `kubectl get pods -l job-name=batch-inference-sample` 가 Pod 가 `Completed` 상태로 종료됨을 표시함을 확인했습니다.
- [ ] `kubectl get jobs batch-inference-sample` 의 `COMPLETIONS` 컬럼이 `1/1` 임을 확인했습니다.
- [ ] eval-results PVC 안에 `inference-*.jsonl` 파일이 생성되어 있고 한 줄에 `pred_label` / `pred_score` 가 추가되어 있음을 확인했습니다.
- [ ] `kubectl get cronjob daily-eval` 의 `SCHEDULE` 컬럼에 `0 3 * * *` 가 표시되고, `kubectl create job batch-eval-manual --from=cronjob/daily-eval` 로 만든 Job 이 Completed 됨을 확인했습니다.
- [ ] eval-results PVC 안에 `eval-YYYYMMDD.json` 파일이 생성되어 있고 `accuracy`, `per_label` 키가 포함되어 있음을 확인했습니다.
- [ ] `failing-job-demo` 가 3개의 `Error` Pod 을 만든 뒤 Job STATUS 가 `Failed` 로, `kubectl describe job failing-job-demo` 의 Conditions 에 `BackoffLimitExceeded` 가 표시됨을 확인했습니다.
- [ ] 정리 후 `kubectl get pvc model-cache` 와 02 의 ConfigMap/Secret 이 의도적으로 살아있음을 확인했습니다 (다음 토픽 재사용).

## 4. 정리

본 토픽에서 만든 리소스를 단계별로 삭제합니다. **Job/CronJob 의 라이프사이클이 model-cache PVC / 02 자산과 분리됨을 인식하기 위함입니다.**

```bash
# 1차 정리 — 학습용 실패 Job 과 그 누적 Pod 제거
kubectl delete -f manifests/failing-job.yaml --ignore-not-found

# 2차 정리 — 본 토픽 워크로드 (CronJob → Job 순서 권장)
kubectl delete -f manifests/cronjob.yaml --ignore-not-found
kubectl delete -f manifests/job.yaml --ignore-not-found

# 3차 정리 — 본 토픽 신규 자산 (PVC + ConfigMap)
kubectl delete -f manifests/results-pvc.yaml --ignore-not-found
kubectl delete -f manifests/scripts-configmap.yaml --ignore-not-found

# 02 의 ConfigMap/Secret/model-cache PVC 는 다음 토픽(05-namespace-quota)에서도 재사용 권장이라 그대로 둡니다.
# 명시적으로 비우려면:
# kubectl delete cm sentiment-api-config
# kubectl delete secret sentiment-api-secrets
# kubectl delete pvc model-cache

# minikube 와 sentiment-api:v1 이미지는 다음 토픽에서도 재사용하므로 stop 만 합니다.
minikube stop
```

> 💡 **수동 트리거로 만든 Job 정리**: lab 5 단계의 `kubectl create job batch-eval-manual --from=cronjob/daily-eval` 로 만든 Job 도 `kubectl delete job batch-eval-manual` 로 별도 정리합니다. CronJob 을 지워도 그로부터 만들어진 Job 들은 자동으로 따라 사라지지 않습니다 (ownerReference 가 자동으로 잡혀 있어 `kubectl delete cronjob daily-eval --cascade=foreground` 로 같이 지우는 것도 가능).

## 🚨 자주 하는 실수

1. **`restartPolicy: Always` 로 Job 매니페스트 작성** — Deployment 매니페스트를 그대로 복사해 `kind: Job` 만 바꾼 학습자가 가장 자주 만나는 함정입니다. apply 자체가 다음 메시지로 거절됩니다: `The Job "..." is invalid: spec.template.spec.restartPolicy: Required value: valid values: "OnFailure", "Never"`. 진단은 apply 에러 메시지 그대로, 해결은 `OnFailure` 로 변경. 두 옵션의 차이를 알고 선택해야 합니다 — `OnFailure` 는 같은 Pod 안에서 컨테이너만 재시작 (모델 캐시 살아있음, 빠름), `Never` 는 새 Pod 을 띄움 (격리 강함, 모델 재로딩, 디버깅 유리). 본 토픽 [job.yaml](manifests/job.yaml) 은 `OnFailure` 입니다.

2. **`backoffLimit` 미설정 (기본 6) + 빠르게 실패하는 컨테이너 → 무한처럼 보이는 재시도** — 모델 로딩 실패·imagePullError·OOM 등으로 컨테이너가 5초 안에 죽는 Job 이 있다고 칩시다. 기본 `backoffLimit=6` 이라 약 1–2분 안에 6번 재시도되고 그동안 `kubectl get pods -l job-name=...` 에는 Error 상태 Pod 이 6개 쌓입니다. 학습자가 "Job 이 멈추질 않는다" 고 오해하는 첫 번째 원인입니다. 본 토픽 [failing-job.yaml](manifests/failing-job.yaml) 의 `backoffLimit: 2` 가 의도적으로 짧게 잡혀 있어 lab 6 단계에서 직접 관찰합니다. 운영에서는 명시적으로 작게(2~3) 두고 실패 원인을 조기에 사람이 보게 합니다 — 빠르게 실패하는 잡은 거의 항상 코드 / 환경 문제이지 재시도로 해결되지 않습니다.

3. **CronJob `concurrencyPolicy` 기본값 `Allow` 로 두기 → 잡 실행 시간이 schedule 주기보다 길어지면 동시 실행으로 PVC 락 충돌·GPU 메모리 폭발** — 매일 새벽 1번 도는 평가 잡이 데이터셋이 늘어 90분 걸리는데 schedule 이 매시간으로 바뀌면 두 Job 이 같은 `eval-results` PVC 의 `eval-YYYYMMDD.json` 을 동시에 write 하다가 충돌·손상됩니다. GPU 잡이라면 두 Pod 이 같은 GPU 메모리를 동시 점유하다 OOM. 운영에서는 거의 항상 `Forbid` (이전 끝날 때까지 새 실행 스킵) 또는 `Replace` (이전 죽이고 새로 시작) 를 명시합니다. 본 토픽 [cronjob.yaml](manifests/cronjob.yaml) 은 `Forbid` 입니다. 진단은 같은 CronJob 의 Job 두 개가 동시에 활성 상태인지 `kubectl get cronjob daily-eval -o jsonpath='{.status.active}'` 로 확인 — 비어 있어야 정상 (`Forbid` 면 한 번에 최대 1개), 두 개의 `objectReference` 가 보이면 `Allow` 동작 중입니다.

## 더 알아보기

- [Kubernetes — Jobs](https://kubernetes.io/docs/concepts/workloads/controllers/job/) — `completions`, `parallelism`, `completionMode: Indexed`, suspended Job, Pod failure policy 등 본 lesson 에서 한두 줄로 다룬 모든 옵션의 권위 있는 정의.
- [Kubernetes — CronJobs](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/) — `concurrencyPolicy`, `startingDeadlineSeconds`, `timeZone` 의 정확한 동작과 controller 한계 (예: missed schedule 이 100 회 넘으면 더 이상 실행 시도 안 함).
- [Kubernetes — Job Patterns](https://kubernetes.io/docs/tasks/job/) — work queue, Indexed Job, parallel processing, Pod 간 통신 패턴 등 분산 잡으로 가는 다음 스텝.
- [Kubernetes — Pod failure policy (alpha→beta)](https://kubernetes.io/docs/tasks/job/pod-failure-policy/) — exit code 별로 재시도 여부를 다르게 하는 고급 패턴 (예: 137=OOM 은 재시도, 1=논리 오류는 즉시 Failed).
- [KubeRay — RayJob](https://docs.ray.io/en/latest/cluster/kubernetes/getting-started/rayjob-quick-start.html) — Phase 4 분산 학습에서 만날 RayJob 이 본 토픽의 K8s Job 위에 어떻게 얹혀 있는지 미리보기.

## 다음 챕터

➡️ [Phase 2 / 05-namespace-quota — Namespace, ResourceQuota, LimitRange](../05-namespace-quota/lesson.md)

다음 토픽에서는 본 토픽까지 모두 `default` 네임스페이스에 쌓아 둔 자산을 **dev / staging / prod 네임스페이스로 분리** 하고, ResourceQuota 로 네임스페이스당 GPU 개수·CPU·메모리 총량을 제한, LimitRange 로 Pod 별 default request/limit 을 강제하는 **운영 격리** 패턴을 학습합니다. Phase 2 의 마지막 토픽이며, 이후 Phase 3 의 Helm / Prometheus / HPA 가 모두 namespace 단위로 동작하므로 본 토픽이 Phase 3 의 발판이 됩니다.
