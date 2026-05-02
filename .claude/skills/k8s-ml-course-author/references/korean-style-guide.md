# 한국어 스타일 가이드

ML 엔지니어용 K8s 강의 자료 작성 시 톤과 용어를 일관되게 유지하기 위한 가이드입니다.

## 톤

- "~합니다" 정중체 사용. "~한다" 평서체와 섞지 않습니다.
- 학습자에게 직접 말 거는 톤: "이 명령을 실행하면 ~을 볼 수 있습니다."
- "여러분" 보다는 "학습자"라는 표현은 피하고, 주어를 생략하거나 "지금 ~하면 됩니다" 식으로.
- 너무 격식 차린 학술 문체("것이다", "~함") 지양. 실무 회사 문서 톤.
- 권유: "~을 추천합니다", "~하는 게 좋습니다". 강제: "반드시 ~해야 합니다"는 정말 중요할 때만.

## 용어 표기

영문 K8s 용어는 처음 등장 시 한 번만 한글 병기, 이후 영문 유지.

| 영문 | 첫 등장 표기 | 이후 |
|------|-------------|------|
| Pod | Pod(파드) | Pod |
| Deployment | Deployment(디플로이먼트) | Deployment |
| Service | Service(서비스) | Service |
| Ingress | Ingress(인그레스) | Ingress |
| ConfigMap | ConfigMap(컨피그맵) | ConfigMap |
| Secret | Secret(시크릿) | Secret |
| PersistentVolume | PersistentVolume(PV, 영구 볼륨) | PV |
| Namespace | Namespace(네임스페이스) | Namespace |
| Node | Node(노드) | Node |
| Cluster | Cluster(클러스터) | 클러스터 |
| Container | 컨테이너 | 컨테이너 |
| Manifest | 매니페스트 | 매니페스트 |
| Workload | 워크로드 | 워크로드 |
| Replica | 레플리카 | 레플리카 |
| Rolling update | 롤링 업데이트 | 롤링 업데이트 |
| Probe | Probe(프로브) | Probe |
| Selector | Selector(셀렉터) | Selector |
| Label | Label(레이블) | Label |
| Annotation | Annotation(어노테이션) | Annotation |
| Operator | Operator(오퍼레이터) | Operator |
| Helm chart | Helm 차트 | Helm 차트 |
| Service mesh | Service Mesh(서비스 메시) | Service Mesh |

## ML 용어

| 영문 | 한글 표기 |
|------|---------|
| Inference | 추론 |
| Training | 학습 |
| Fine-tuning | 파인튜닝 |
| Embedding | 임베딩 |
| Vector DB | 벡터 DB |
| Throughput | 처리량 (또는 throughput) |
| Latency | 지연 시간 (또는 latency) |
| Batch inference | 배치 추론 |
| Online inference | 온라인 추론 |
| Model serving | 모델 서빙 |
| Checkpoint | 체크포인트 |
| Hyperparameter | 하이퍼파라미터 |
| Quantization | 양자화 |

## 코드/명령어 인용

- 인라인 명령어: 백틱 사용. 예: `kubectl get pods`
- 짧은 출력: 인라인 코드.
- 여러 줄 출력: ` ```bash ` 또는 ` ``` ` 블록.
- YAML 파일 내 한국어 주석은 사용 가능하지만 짧게.

## 강조 표기

- 정말 중요한 개념: **굵게**.
- 처음 등장하는 용어: *기울임* 또는 **굵게** 1회.
- 경고/주의: 🚨 + 굵게.
- 팁: 💡.
- 별표 강조: ⭐ (Phase 4처럼 핵심 단계 표시할 때).

## 자주 틀리는 표기

- ❌ "쿠버네티스가" → ✅ "쿠버네티스는" 또는 "Kubernetes는"
- ❌ "디플로이먼트가" → ✅ "Deployment가"
- ❌ "오토스케일링" 단독 사용 시 → ✅ "오토스케일링(autoscaling)" 첫 등장에만
- ❌ "K8" → ✅ "K8s" 또는 "쿠버네티스"

## 문장 길이

- 한 문장은 최대 80자 정도. 더 길어지면 둘로 쪼갭니다.
- 코드 설명은 짧게. "이 매니페스트는 ~을 합니다." 한 문장 + 필요시 부연.
