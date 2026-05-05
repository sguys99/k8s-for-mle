# Phase 4-1 — GPU on Kubernetes 핵심 정리

## NVIDIA Device Plugin 이 하는 일

쿠버네티스의 스케줄러는 기본적으로 GPU 라는 자원을 모릅니다. NVIDIA Device Plugin DaemonSet 이 노드마다 떠서, 노드의 GPU 개수를 `nvidia.com/gpu` 라는 확장 리소스로 kubelet 에 등록합니다. 그 결과 매니페스트의 `resources.limits.nvidia.com/gpu: 1` 필드가 의미를 가지게 되고, 스케줄러는 GPU 1장 이상을 가진 노드에만 Pod 을 배치합니다.

## taint + toleration 으로 GPU 노드 격리

GPU 노드는 비싸기 때문에 일반 워크로드가 흘러 들어오면 안 됩니다. 노드에 `nvidia.com/gpu=true:NoSchedule` taint 를 박고, GPU 가 필요한 Pod 에만 toleration 을 답니다. 이렇게 격리하면 GPU 사용률이 올라갑니다.

## MIG vs Time-slicing

A100/H100 같은 큰 GPU 1장을 여러 작업이 나눠 쓰는 두 가지 방법입니다.
- MIG: 하드웨어 단위로 7개까지 분할. 격리가 강함.
- Time-slicing: 소프트웨어 스케줄링. 격리는 약하지만 모든 GPU 에 적용 가능.

추론처럼 메모리가 작은 워크로드에서는 1장을 4~7로 쪼개 자원 효율을 크게 올릴 수 있습니다.

## 자주 하는 실수

- nvidia.com/gpu 누락 → GPU 가 없는 노드에 떨어져 CUDA 에러
- toleration 없이 taint 만 → Pod 이 영영 Pending
