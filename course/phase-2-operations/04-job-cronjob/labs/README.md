# Phase 2 / 04-job-cronjob — 실습 가이드

> 03 까지 클러스터에 항상 떠 있는 모델 서빙(Deployment + Service + Ingress) 을 다뤘다면, 본 lab 에서는 **단발성 배치 추론(Job)** 과 **일별 정기 평가(CronJob)** 를 직접 적용·관찰합니다. `restartPolicy: OnFailure`, `backoffLimit`, `activeDeadlineSeconds`, `concurrencyPolicy` 가 실제로 어떻게 동작하는지 의도적 실패 잡으로 검증합니다.
>
> **예상 소요 시간**: 40–60분 (02 의 model-cache PVC 캐시가 살아있으면 모델 다운로드 없음)
>
> **선행 조건**
> - [Phase 2 / 02-volumes-pvc](../../02-volumes-pvc/lesson.md) 완료 — 본 lab 0–1 단계가 02 의 ConfigMap/Secret/PVC 자산을 그대로 재사용합니다.
> - [Phase 2 / 03-ingress](../../03-ingress/lesson.md) 권장 (Ingress 는 본 lab 에서 사용하지 않으므로 필수는 아님)
> - minikube 에 `sentiment-api:v1` 이미지가 적재되어 있어야 합니다 (Phase 1/04 lab 1단계에서 적재됨)
>
> **작업 디렉토리**
> ```bash
> cd course/phase-2-operations/04-job-cronjob
> ```

---

## 0단계 — 사전 준비 점검

### 0-1. minikube 상태 확인

```bash
minikube status
```

```
# 예상 출력
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured
```

`Stopped` 가 보이면 `minikube start` 로 기동합니다. 03 에서 `minikube stop` 만 했다면 PVC 와 그 안의 모델 캐시가 그대로 살아있어 본 토픽에서 첫 다운로드가 발생하지 않습니다.

### 0-2. kubectl 컨텍스트 확인

```bash
kubectl config current-context
```

```
# 예상 출력
minikube
```

### 0-3. sentiment-api:v1 이미지 확인

```bash
minikube image ls | grep sentiment-api
```

```
# 예상 출력
docker.io/library/sentiment-api:v1
```

비어 있다면 → [Phase 1/04 lab 1단계](../../../phase-1-k8s-basics/04-serve-classification-model/labs/README.md#1단계--필요-시-phase-0-이미지를-minikube에-적재) 로 가서 다시 적재한 뒤 돌아옵니다.

### 0-4. 02 자산 점검 — ConfigMap / Secret / model-cache PVC

본 lab 의 [job.yaml](../manifests/job.yaml) / [cronjob.yaml](../manifests/cronjob.yaml) 은 02 에서 만든 ConfigMap(`sentiment-api-config`) / Secret(`sentiment-api-secrets`) / PVC(`model-cache`) 를 **그대로 재사용** 합니다 (envFrom 과 volume 으로 참조). 02 의 정리 단계를 어디까지 했는지에 따라 두 시나리오로 분기합니다.

```bash
kubectl get cm,secret,pvc -l app=sentiment-api
```

다음 두 시나리오 중 하나입니다.

- **시나리오 A** — 02 의 ConfigMap / Secret / PVC `model-cache` 모두 보임: 이상적입니다. **1단계 0-A** 로 바로 진행 (apply 스킵).
- **시나리오 B** — 비어있거나 일부만 남음: 02 매니페스트로 한 번 더 apply 합니다. **1단계 0-B** 로 진행.

```
# 시나리오 A 예상 출력
NAME                              DATA   AGE
configmap/sentiment-api-config    4      1h

NAME                            TYPE     DATA   AGE
secret/sentiment-api-secrets    Opaque   2      1h

NAME                                STATUS   VOLUME    CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache   Bound    pvc-...   2Gi        RWO            standard       1h
```

```
# 시나리오 B 예상 출력 (예: 모두 비어있음)
No resources found in default namespace.
```

---

## 1단계 — 02 자산 보강(필요 시) + 본 토픽 신규 자산 적용

### 1-A. 시나리오 A — 02 자산 그대로 재사용 (스킵)

0-4 가 시나리오 A 였다면 02 매니페스트 apply 는 건너뛰고 1-2 로 바로 갑니다.

### 1-B. 시나리오 B — 02 매니페스트로 보강

```bash
kubectl apply -f ../02-volumes-pvc/manifests/configmap.yaml \
              -f ../02-volumes-pvc/manifests/secret.yaml \
              -f ../02-volumes-pvc/manifests/pvc.yaml
```

```
# 예상 출력
configmap/sentiment-api-config created
secret/sentiment-api-secrets created
persistentvolumeclaim/model-cache created
```

> 💡 **Deployment 는 다시 띄우지 않습니다.** 본 토픽은 항상 떠 있는 서빙이 아니라 단발 잡이라 02 의 Deployment 가 필요 없습니다. 모델 다운로드는 잡 첫 실행 시 transformers 라이브러리가 자동으로 수행해 PVC 에 캐시합니다 (시나리오 B 는 첫 실행이 30–60초 더 걸립니다).

### 1-2. 본 토픽 신규 자산 적용 — results-pvc + scripts-configmap

```bash
kubectl apply -f manifests/results-pvc.yaml \
              -f manifests/scripts-configmap.yaml
```

```
# 예상 출력
persistentvolumeclaim/eval-results created
configmap/eval-scripts created
```

### 1-3. 두 PVC 가 모두 Bound 됨 확인

라이프사이클이 분리된 두 PVC 가 동시에 동작하는 패턴이 본 토픽의 핵심입니다.

```bash
kubectl get pvc
```

```
# 예상 출력
NAME           STATUS   VOLUME    CAPACITY   ACCESS MODES   STORAGECLASS   AGE
eval-results   Bound    pvc-...   1Gi        RWO            standard       5s
model-cache    Bound    pvc-...   2Gi        RWO            standard       1h    ← 02 에서 만든 것
```

`STATUS=Bound` 두 줄이 보이면 정상. `Pending` 이 보이면 StorageClass 가 동적 프로비저닝에 실패한 것이라 `kubectl describe pvc <name>` 으로 사유 확인.

### 1-4. ConfigMap 의 키 3개 확인

```bash
kubectl get cm eval-scripts -o jsonpath='{.data}' | python -c "import sys,json; print('\n'.join(json.load(sys.stdin).keys()))"
```

```
# 예상 출력
batch_inference.py
evaluate.py
sample-input.jsonl
```

세 키 모두 보이면 본 lab 에서 사용할 스크립트와 입력 데이터가 ConfigMap 에 정상 적재된 것입니다.

---

## 2단계 — 단발 배치 추론 Job 실행 + 라이프사이클 관찰

본 단계에서 **Job 의 terminal phase** ([lesson.md 1-1](../lesson.md#1-1-job-vs-deployment--terminal-vs-long-running)) 를 직접 관찰합니다.

### 2-1. Job 적용

```bash
kubectl apply -f manifests/job.yaml
```

```
# 예상 출력
job.batch/batch-inference-sample created
```

### 2-2. Pod 의 라이프사이클 실시간 관찰

별도 터미널 또는 같은 터미널에서 (Ctrl+C 로 빠져나옴):

```bash
kubectl get pods -l job-name=batch-inference-sample -w
```

```
# 예상 출력 (시간 흐름순, 시나리오 A 기준)
NAME                                READY   STATUS              RESTARTS   AGE
batch-inference-sample-xxxxx        0/1     Pending             0          0s
batch-inference-sample-xxxxx        0/1     ContainerCreating   0          1s
batch-inference-sample-xxxxx        1/1     Running             0          15s    ← 모델 RAM 적재 중
batch-inference-sample-xxxxx        0/1     Completed           0          45s    ← 8건 추론 후 정상 종료
```

`Completed` 까지 30–60초 걸립니다 (시나리오 B 라면 모델 다운로드가 추가되어 1–2분). Pod 가 `Completed` 로 멈추는 것이 Job 의 terminal phase 입니다 — Deployment 였다면 죽으면 ReplicaSet 이 새로 띄웠을 것입니다.

### 2-3. Job status 확인 — COMPLETIONS 1/1

```bash
kubectl get jobs batch-inference-sample
```

```
# 예상 출력
NAME                     STATUS     COMPLETIONS   DURATION   AGE
batch-inference-sample   Complete   1/1           45s        1m
```

`COMPLETIONS 1/1` 가 핵심 — `completions: 1` 매니페스트 값이 채워졌다는 뜻입니다. `STATUS=Complete` 가 terminal phase 입니다.

> ⚠️ **Pod 가 즉시 사라지지 않는 이유**: [job.yaml](../manifests/job.yaml) 의 `ttlSecondsAfterFinished: 1800` 으로 30분간 보존됩니다. 그 시간 안에 `kubectl logs` 로 결과 확인 가능. 30분 뒤에는 자동으로 사라집니다.

---

## 3단계 — 결과 확인 — Job logs + PVC 안의 jsonl 직접 읽기

### 3-1. Job 의 stdout 로그 확인

```bash
kubectl logs job/batch-inference-sample
```

```
# 예상 출력
[batch] model=cardiffnlp/twitter-roberta-base-sentiment input=/inputs/sample-input.jsonl output=/results/inference-20260503T120000.jsonl
... (transformers / huggingface 라이브러리의 다운로드/적재 로그) ...
[batch] done. wrote 8 rows -> /results/inference-20260503T120000.jsonl
```

마지막 두 줄에 `wrote 8 rows` 와 결과 파일 경로가 보이면 batch_inference.py 가 정상 종료된 것입니다.

### 3-2. eval-results PVC 안의 결과 jsonl 직접 읽기 — 디버그 Pod

PVC 의 내용을 보려면 그 PVC 를 마운트한 임시 Pod 이 필요합니다. busybox 한 줄로 처리합니다.

```bash
kubectl run pvc-peek --rm -it --restart=Never \
  --image=busybox:1.36 \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "pvc-peek",
        "image": "busybox:1.36",
        "stdin": true, "tty": true,
        "command": ["sh"],
        "volumeMounts": [{"name": "results", "mountPath": "/results"}]
      }],
      "volumes": [{"name": "results", "persistentVolumeClaim": {"claimName": "eval-results"}}]
    }
  }'
```

`sh #` 프롬프트가 뜨면:

```sh
ls -la /results
cat /results/inference-*.jsonl
exit
```

```
# 예상 출력
total 8
drwxrwxrwx    2 root     root          4096 ... .
drwxr-xr-x    1 root     root          4096 ... ..
-rw-r--r--    1 root     root          1234 ... inference-20260503T120000.jsonl

{"id": 1, "text": "I love this new model, it works perfectly", "label": "LABEL_2", "pred_label": "LABEL_2", "pred_score": 0.98...}
{"id": 2, "text": "The service is acceptable, nothing special", "label": "LABEL_1", "pred_label": "LABEL_1", "pred_score": 0.7...}
... (8줄)
pod "pvc-peek" deleted
```

각 줄에 원래 입력의 `id/text/label` 외에 `pred_label`, `pred_score` 두 키가 추가되어 있다면 batch_inference.py 가 모델 예측을 정상 수행한 것입니다.

> 💡 **`kubectl debug` 로 더 짧게**: K8s 1.25+ 환경에서는 `kubectl debug -it pvc-peek --image=busybox --target=...` 으로도 디버그 컨테이너를 띄울 수 있지만, PVC 마운트는 위 `--overrides` 방식이 가장 명시적입니다.

---

## 4단계 — Job 의 시간·재시도 필드 직접 확인

[lesson.md 1-3](../lesson.md#1-3-activedeadlineseconds-와-ttlsecondsafterfinished--두-시간-필드의-차이) 에서 표로 본 세 필드가 실제로 Job 오브젝트에 어떻게 저장되어 있는지 확인합니다.

```bash
kubectl describe job batch-inference-sample
```

```
# 예상 출력 (발췌)
Name:             batch-inference-sample
Namespace:        default
Selector:         batch.kubernetes.io/controller-uid=...
Labels:           app=sentiment-eval
                  component=batch
                  phase=2
                  topic=04-job-cronjob
Parallelism:        1
Completions:        1
Backoff Limit:      2                            ← 매니페스트 값 그대로
Active Deadline:    600s                         ← activeDeadlineSeconds: 600
TTL Seconds After Finished: 1800                 ← ttlSecondsAfterFinished: 1800
Start Time:       ...
Completed At:     ...
Duration:         45s
Pods Statuses:    0 Active (0 Ready) / 1 Succeeded / 0 Failed
Pod Template:
  ...
  Restart Policy: OnFailure                      ← Always 가 아닌 OnFailure
  ...
Events:
  Type    Reason            Age   From            Message
  ----    ------            ----  ----            -------
  Normal  SuccessfulCreate  2m    job-controller  Created pod: batch-inference-sample-xxxxx
  Normal  Completed         1m    job-controller  Job completed
```

세 필드(`Backoff Limit`, `Active Deadline`, `TTL Seconds After Finished`) 가 매니페스트 값 그대로 표시되고, `Restart Policy: OnFailure` 가 보이면 정상입니다. 6단계에서 `failing-job-demo` 를 적용하면 이 자리에 `Conditions: ... BackoffLimitExceeded` 가 추가됩니다.

---

## 5단계 — CronJob 적용 + 수동 트리거로 즉시 시연

### 5-1. CronJob 적용

```bash
kubectl apply -f manifests/cronjob.yaml
```

```
# 예상 출력
cronjob.batch/daily-eval created
```

### 5-2. CronJob 상태 확인

```bash
kubectl get cronjob daily-eval
```

```
# 예상 출력
NAME         SCHEDULE      TIMEZONE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
daily-eval   0 3 * * *     Asia/Seoul    False     0        <none>          5s
```

- `SCHEDULE: 0 3 * * *` — 매일 새벽 3시 (KST)
- `TIMEZONE: Asia/Seoul` — K8s 1.27+ timeZone 필드가 적용된 결과
- `SUSPEND: False` — 정상 동작
- `ACTIVE: 0` — 현재 실행 중인 Job 없음
- `LAST SCHEDULE: <none>` — 아직 한 번도 실행 안 됨

> 💡 **TIMEZONE 컬럼이 안 보이는 클러스터**: K8s 1.26 이하라면 `timeZone` 필드가 무시됩니다. 그 경우 schedule 을 UTC 로 환산해서 적어야 합니다 (KST 03:00 = UTC 18:00 → `0 18 * * *`). minikube 1.32+ 는 K8s 1.27+ 라 본 토픽 그대로 동작합니다.

### 5-3. 수동 트리거 — 다음 schedule 을 기다리지 않고 즉시 1회 실행

운영의 단골 명령입니다 ([lesson.md 1-5](../lesson.md#1-5-cronjob-운영-패턴--startingdeadlineseconds-suspend-수동-트리거) 참고).

```bash
kubectl create job batch-eval-manual --from=cronjob/daily-eval
```

```
# 예상 출력
job.batch/batch-eval-manual created
```

### 5-4. 수동 트리거 Job 의 실행 관찰

```bash
kubectl get pods -l job-name=batch-eval-manual -w
```

```
# 예상 출력 (Ctrl+C 로 종료, 시나리오 A 기준)
NAME                          READY   STATUS              RESTARTS   AGE
batch-eval-manual-xxxxx       0/1     ContainerCreating   0          1s
batch-eval-manual-xxxxx       1/1     Running             0          10s
batch-eval-manual-xxxxx       0/1     Completed           0          40s
```

### 5-5. 평가 결과 확인 — eval-YYYYMMDD.json

```bash
kubectl logs job/batch-eval-manual
```

```
# 예상 출력 (마지막 부분)
[eval] model=cardiffnlp/twitter-roberta-base-sentiment input=/inputs/sample-input.jsonl output=/results/eval-20260503.json
{
  "model": "cardiffnlp/twitter-roberta-base-sentiment",
  "evaluated_at": "2026-05-03T12:00:00.000Z",
  "total": 8,
  "correct": 7,
  "accuracy": 0.875,
  "per_label": {
    "LABEL_0": {"precision": 1.0, "recall": 1.0},
    "LABEL_1": {"precision": 0.6667, "recall": 0.6667},
    "LABEL_2": {"precision": 1.0, "recall": 1.0}
  }
}
[eval] done -> /results/eval-20260503.json
```

`accuracy` 가 0.7~1.0 사이로 보이면 정상 (문장이 모호한 LABEL_1 사례에서 오답 1~2건은 자연스러움). 같은 PVC 안에 2단계의 inference jsonl 과 본 단계의 eval json 이 모두 누적되어 있는지 보려면 3-2 의 디버그 Pod 명령을 다시 사용:

```bash
kubectl run pvc-peek --rm -it --restart=Never \
  --image=busybox:1.36 \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "pvc-peek", "image": "busybox:1.36",
        "stdin": true, "tty": true, "command": ["sh"],
        "volumeMounts": [{"name": "results", "mountPath": "/results"}]
      }],
      "volumes": [{"name": "results", "persistentVolumeClaim": {"claimName": "eval-results"}}]
    }
  }'
```

```sh
ls -la /results
exit
```

```
# 예상 출력
-rw-r--r--    1 root     root          1234 ... inference-20260503T120000.jsonl    ← 2단계 결과
-rw-r--r--    1 root     root           512 ... eval-20260503.json                  ← 본 단계 결과
pod "pvc-peek" deleted
```

두 종류의 결과가 같은 PVC 에 라이프사이클 분리 없이 함께 쌓이고 있는 모습을 직접 확인합니다.

---

## 6단계 — `backoffLimit` 의 동작을 실패 Job 으로 직접 관찰

[lesson.md 자주 하는 실수 2번](../lesson.md#-자주-하는-실수) 의 시뮬레이션입니다. busybox 로 의도적으로 실패하는 Job 을 적용해 재시도 사이클과 `BackoffLimitExceeded` 종료를 관찰합니다.

### 6-1. failing-job-demo 적용

```bash
kubectl apply -f manifests/failing-job.yaml
```

```
# 예상 출력
job.batch/failing-job-demo created
```

### 6-2. Pod 의 재시도 사이클 관찰

```bash
kubectl get pods -l job-name=failing-job-demo -w
```

```
# 예상 출력 (Ctrl+C 로 종료, 약 1–2분간 관찰)
NAME                       READY   STATUS              RESTARTS   AGE
failing-job-demo-xxxxx     0/1     ContainerCreating   0          1s
failing-job-demo-xxxxx     1/1     Running             0          3s
failing-job-demo-xxxxx     0/1     Error               0          5s    ← 첫 실행 실패 (exit 1)
failing-job-demo-xxxxx     0/1     Error               1          15s   ← 같은 Pod 안에서 컨테이너 재시작 (OnFailure)
failing-job-demo-xxxxx     0/1     Error               2          35s   ← 두 번째 재시작 (10s, 20s 백오프 인터벌)
failing-job-demo-yyyyy     0/1     Pending             0          75s   ← backoff 한도 도달 시 새 Pod 시도 가능
... (총 3번 시도 후 종료)
```

> 💡 **Error 사이의 시간 간격**: K8s 의 backoff 는 지수증가 (10s → 20s → 40s → ...) 라 두 번째 Error 까지 약 15–20초, 세 번째까지 약 30–40초가 걸립니다. `backoffLimit: 2` 로 두었기 때문에 첫 실행 + 재시도 2회 = 총 3번 후 Job 이 종료됩니다.

### 6-3. Job status 확인 — STATUS=Failed

```bash
kubectl get job failing-job-demo
```

```
# 예상 출력
NAME               STATUS   COMPLETIONS   DURATION   AGE
failing-job-demo   Failed   0/1           90s        2m
```

`STATUS=Failed`, `COMPLETIONS=0/1` (성공이 한 번도 없었음).

### 6-4. Conditions 에 BackoffLimitExceeded 확인 — 결정적 증거

```bash
kubectl describe job failing-job-demo
```

```
# 예상 출력 (발췌, 핵심 두 섹션)
Conditions:
  Type    Status  Reason
  ----    ------  ------
  Failed  True    BackoffLimitExceeded            ← 결정적 증거
Pods Statuses:    0 Active (0 Ready) / 0 Succeeded / 3 Failed
Events:
  Type     Reason                Age    From            Message
  ----     ------                ----   ----            -------
  Normal   SuccessfulCreate      2m     job-controller  Created pod: failing-job-demo-xxxxx
  Warning  BackoffLimitExceeded  20s    job-controller  Job has reached the specified backoff limit
```

`Conditions.Reason: BackoffLimitExceeded` 와 `Pods Statuses: 3 Failed` 두 줄이 본 lab 의 핵심 관찰 결과입니다. `activeDeadlineSeconds` 초과로 끝났다면 `Reason: DeadlineExceeded` 였을 것입니다 (lesson 1-3 표).

> ⚠️ **운영 함정 — 기본 backoffLimit=6 일 때**: 매니페스트에 `backoffLimit` 을 안 적었다면 위 사이클이 6번까지 반복되어 약 4–5분간 Pod 6개가 누적됩니다. 학습자가 "잡이 멈추질 않는다" 고 오해하는 것이 그 시점입니다 (lesson.md 자주 하는 실수 2번). 본 토픽처럼 작게 두면 1–2분 안에 Failed 로 정리됩니다.

---

## 7단계 — (선택) `concurrencyPolicy: Forbid` 의 효과 시뮬

본 단계는 시간이 추가로 5–10분 걸리고 매니페스트를 일시 변경했다가 원복해야 하므로 학습 우선순위에 따라 선택합니다. 핵심은 [lesson.md 자주 하는 실수 3번](../lesson.md#-자주-하는-실수) 의 `concurrencyPolicy: Forbid` 효과를 직접 보는 것입니다.

### 7-1. CronJob 을 매분 schedule + 90초 sleep 으로 일시 패치

```bash
kubectl patch cronjob daily-eval --type='strategic' -p '{"spec":{"schedule":"* * * * *"}}'

# command 를 sleep 90 으로 잠깐 바꿔 잡이 schedule 주기(1분) 보다 길게 돌도록
kubectl patch cronjob daily-eval --type='json' -p='[
  {"op":"replace","path":"/spec/jobTemplate/spec/template/spec/containers/0/command","value":["sh","-c","echo start; sleep 90; echo end"]},
  {"op":"remove","path":"/spec/jobTemplate/spec/template/spec/containers/0/args"}
]'
```

```
# 예상 출력
cronjob.batch/daily-eval patched
cronjob.batch/daily-eval patched
```

### 7-2. CronJob 의 ACTIVE 컬럼 관찰

```bash
kubectl get cronjob daily-eval -w
```

```
# 예상 출력 (3–5분간, Ctrl+C 로 종료)
NAME         SCHEDULE      TIMEZONE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
daily-eval   * * * * *     Asia/Seoul    False     0        <none>          ...
daily-eval   * * * * *     Asia/Seoul    False     1        5s              ...    ← 1분 도달, Job 1 시작
daily-eval   * * * * *     Asia/Seoul    False     1        65s             ...    ← 2분 도달, ACTIVE 가 여전히 1 → 두 번째 schedule 스킵
daily-eval   * * * * *     Asia/Seoul    False     1        125s            ...    ← 3분 도달, 여전히 ACTIVE=1
daily-eval   * * * * *     Asia/Seoul    False     0        185s            ...    ← Job 1 끝남, ACTIVE=0
daily-eval   * * * * *     Asia/Seoul    False     1        245s            ...    ← 4분 도달, Job 2 새로 시작
```

`ACTIVE` 가 `Forbid` 정책 덕분에 항상 0 또는 1 이고 절대 2 이상으로 안 올라갑니다. 그동안 매분의 schedule 시각이 도착했지만 controller 가 "이전이 아직 살아있으니 이번 회차는 패스" 한 결과입니다.

### 7-3. 같은 시도를 `concurrencyPolicy: Allow` 로 두면 (사고 사례 — 실행 안 함, 경고만)

만약 위 패치에 `"/spec/concurrencyPolicy": "Allow"` 를 추가했다면 ACTIVE 가 1 → 2 → 3 으로 늘어나고 두 Pod 이 같은 `eval-results` PVC 의 `eval-20260503.json` 을 동시 write 하려다 충돌·손상될 수 있습니다. 운영 사고 패턴이라 직접 시연은 권장하지 않습니다.

### 7-4. 원복 — schedule 과 command 모두 되돌리기

```bash
kubectl patch cronjob daily-eval --type='strategic' -p '{"spec":{"schedule":"0 3 * * *"}}'

kubectl patch cronjob daily-eval --type='json' -p='[
  {"op":"replace","path":"/spec/jobTemplate/spec/template/spec/containers/0/command","value":["python","/scripts/evaluate.py"]},
  {"op":"add","path":"/spec/jobTemplate/spec/template/spec/containers/0/args","value":["--input=/inputs/sample-input.jsonl"]}
]'

# 원복 확인
kubectl get cronjob daily-eval
```

```
# 예상 출력
NAME         SCHEDULE      TIMEZONE      SUSPEND   ACTIVE   LAST SCHEDULE   AGE
daily-eval   0 3 * * *     Asia/Seoul    False     0|1      ...             ...
```

원복이 헷갈린다면 `kubectl delete -f manifests/cronjob.yaml && kubectl apply -f manifests/cronjob.yaml` 로 매니페스트 그대로 다시 적용해도 됩니다.

---

## 8단계 — 정리

본 토픽에서 만든 리소스를 단계별로 삭제합니다. **Job/CronJob 의 라이프사이클이 model-cache PVC / 02 자산과 분리됨을 인식하기 위함입니다.**

### 8-1. 학습용 실패 Job 정리

```bash
kubectl delete -f manifests/failing-job.yaml --ignore-not-found
```

```
# 예상 출력
job.batch "failing-job-demo" deleted
```

### 8-2. 본 토픽 워크로드 정리 (CronJob → Job 순서)

```bash
kubectl delete -f manifests/cronjob.yaml --ignore-not-found
kubectl delete -f manifests/job.yaml --ignore-not-found

# 5단계의 수동 트리거 Job 도 별도 정리
kubectl delete job batch-eval-manual --ignore-not-found
```

```
# 예상 출력
cronjob.batch "daily-eval" deleted
job.batch "batch-inference-sample" deleted
job.batch "batch-eval-manual" deleted
```

> 💡 **CronJob 을 지워도 그로부터 만들어진 Job 들은 자동으로 따라 사라지지 않습니다** (ownerReference 가 있어 `--cascade=foreground` 로 동시 삭제 가능). `kubectl delete cronjob daily-eval --cascade=foreground` 한 줄로도 처리됩니다.

### 8-3. 본 토픽 신규 자산 정리 (PVC + ConfigMap)

```bash
kubectl delete -f manifests/results-pvc.yaml --ignore-not-found
kubectl delete -f manifests/scripts-configmap.yaml --ignore-not-found
```

```
# 예상 출력
persistentvolumeclaim "eval-results" deleted
configmap "eval-scripts" deleted
```

### 8-4. 02 자산 (model-cache PVC, ConfigMap, Secret) 은 보존 권장

다음 토픽 05-namespace-quota 도 같은 sentiment-api 자산을 재사용하므로 02 자산은 그대로 두는 것이 시간 절약입니다.

```bash
kubectl get cm,secret,pvc -l app=sentiment-api
```

```
# 예상 출력 — 의도적으로 살아있어야 함
NAME                              DATA   AGE
configmap/sentiment-api-config    4      2h

NAME                            TYPE     DATA   AGE
secret/sentiment-api-secrets    Opaque   2      2h

NAME                                STATUS   VOLUME    CAPACITY   ACCESS MODES   STORAGECLASS   AGE
persistentvolumeclaim/model-cache   Bound    pvc-...   2Gi        RWO            standard       2h
```

명시적으로 비우려면:

```bash
# kubectl delete cm sentiment-api-config
# kubectl delete secret sentiment-api-secrets
# kubectl delete pvc model-cache
```

### 8-5. minikube 종료

```bash
# minikube 와 sentiment-api:v1 이미지는 다음 토픽에서도 재사용하므로 stop 만 합니다.
minikube stop
```

```
# 예상 출력
✋  Stopping node "minikube"  ...
🛑  Powering off "minikube" via SSH ...
🛑  1 node stopped.
```

---

## 검증 체크리스트

다음 항목을 모두 확인했다면 본 lab 을 마쳤다고 볼 수 있습니다.

- [ ] **1-3 단계**: `kubectl get pvc` 가 `model-cache (Bound)` 와 `eval-results (Bound)` 두 PVC 를 모두 표시.
- [ ] **2-2 단계**: batch-inference Pod 가 `Pending → Running → Completed` 로 전이하는 것을 `kubectl get pods -w` 로 직접 관찰.
- [ ] **2-3 단계**: `kubectl get jobs` 의 `STATUS=Complete`, `COMPLETIONS=1/1`.
- [ ] **3-2 단계**: 디버그 Pod 으로 PVC 안의 `inference-*.jsonl` 한 줄에 `pred_label`, `pred_score` 가 추가되어 있음.
- [ ] **4 단계**: `kubectl describe job batch-inference-sample` 출력에 `Backoff Limit: 2`, `Active Deadline: 600s`, `TTL Seconds After Finished: 1800`, `Restart Policy: OnFailure` 가 그대로 표시됨.
- [ ] **5-2 단계**: `kubectl get cronjob daily-eval` 에 `SCHEDULE=0 3 * * *`, `TIMEZONE=Asia/Seoul`, `SUSPEND=False`.
- [ ] **5-5 단계**: `kubectl logs job/batch-eval-manual` 출력에 `accuracy`, `per_label` 키가 포함된 JSON 이 보이고, eval-results PVC 에 `eval-YYYYMMDD.json` 파일이 생김.
- [ ] **6-4 단계**: failing-job-demo 의 `kubectl describe job` 출력 Conditions 에 `Failed True BackoffLimitExceeded` 가 적힘. Pods Statuses 에 `3 Failed`.
- [ ] **8-4 단계**: 정리 후에도 `model-cache` PVC 와 `sentiment-api-config` / `sentiment-api-secrets` 가 의도적으로 살아있음을 확인 (다음 토픽 재사용).

체크리스트가 모두 채워졌다면 [docs/course-plan.md](../../../../docs/course-plan.md) 의 Phase 2/04 항목 `minikube 검증` 박스를 `[x]` 로 업데이트합니다.
