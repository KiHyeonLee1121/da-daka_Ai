# DA-DAKA 학습: 여기부터 읽으세요

> 🟡 **현재 상태: 코드는 준비됐고, Google Drive dataset upload 완료를 기다리는 중입니다.**

이 문서는 AI/ML이나 Colab이 처음인 사용자도 현재 상태를 바로 확인할 수 있도록 만든 안내판이다.

현재 Codex가 실행되는 PC는 피시방의 임시 컴퓨터다. 이 PC의 로컬 파일은 장기
보관소가 아니다. 이어받을 때는 GitHub feature branch와 Google Drive 인수인계
폴더를 권위 있는 작업물 저장소로 사용한다.

## 한눈에 보기

| 단계 | 상태 | 설명 |
|---|---|---|
| 학습 코드 | 🟢 완료 | Panel Detector와 Dirt Segmenter trainer 준비 |
| Colab notebook | 🟢 완료 | GPU 검사부터 staging·검증·학습까지 순서화 |
| checkpoint/resume | 🟢 완료 | 중단 후 이어하기와 Drive 결과 보존 준비 |
| 데이터 version/fingerprint | 🟢 확인 | 승인된 release identity와 일치 |
| Drive media upload | 🔴 미완료 | Master/Panel 이미지 553개, Dirt train ROI 248개 누락 snapshot |
| 실제 loader smoke test | 🟡 대기 | upload 완료 후 `/content` staged copy에서 실행 |
| 실제 baseline 학습 | 🟡 대기 | dataset과 Colab CUDA가 모두 준비돼야 시작 |
| GPU 노트북 실시간 추론 | 🟡 대기 | trained model이 나온 뒤 별도로 검증 |

## 사용자가 지금 기억할 것은 두 가지입니다

1. **현재는 학습 시작 버튼을 누르면 안 됩니다.** Dataset upload가 아직 불완전합니다.
2. Upload가 끝나면 AI agent에게 다음 문장만 전달하면 됩니다.

```text
Drive upload가 끝났어. da-daka-curation-20260825-02를 completeness,
fingerprint, staging, loader smoke 순서로 검사하고 모두 통과하면 baseline 학습을 시작해.
```

나머지 경로 입력, 검증 명령, checkpoint 저장과 resume 확인은 Codex가 repository와 인수인계 문서를 따라 수행해야 한다.

## 전체 과정

```text
현재
  ↓
Drive upload 완료
  ↓
file inventory + version + fingerprint 검사
  ↓ 실패하면 학습 금지
/content local SSD로 staging
  ↓
SHA-256 + image/mask decode full verification
  ↓ 실패하면 학습 금지
Panel/Dirt 전체 split loader smoke test
  ↓
Panel baseline 학습 → checkpoint를 Drive에 저장
  ↓
Dirt baseline 학습 → checkpoint를 Drive에 저장
  ↓
validation으로 모델·threshold 결정
  ↓
locked test 평가
  ↓
ONNX export와 GPU 노트북 실시간 추론 검증
```

## 파일을 찾는 순서

1. `TRAINING_START_HERE.md` — 지금 읽고 있는 초보자용 상태 안내
2. `training/colab/da_daka_training.ipynb` — 실제 Colab 실행 notebook
3. `training/README.md` — 명령과 checkpoint 구조
4. `docs/ai_data_pipeline.md` — 데이터부터 배포까지의 기술 계약
5. Drive 인수인계 폴더의 `CODEX_HANDOFF.md` — 다음 Codex용 현재 상태
6. Drive 인수인계 폴더의 `PROJECT_CONTEXT_AND_OBJECTIVES.md` — 프로젝트 목적과 전체 맥락

## 자동 상태 보고서

데이터 없이 코드 준비만 확인:

```bash
da-daka-readiness-report \
  --code-only \
  --output-dir readiness-report
```

Colab에서 dataset과 GPU까지 최종 확인:

```bash
da-daka-readiness-report \
  --dataset-root /content/da_daka_dataset \
  --mode full \
  --fail-if-not-ready \
  --output-dir <DRIVE_RESULTS_ROOT>/readiness
```

결과로 `training_readiness.md`와 `training_readiness.json`이 생긴다. Markdown은 사람이 읽는 안내판이고 JSON은 다음 AI agent와 자동화가 읽는 상태 기록이다.

## 중요한 안전 규칙

- 과거 Windows dataset 경로를 찾지 않는다.
- Drive release를 다시 전처리하지 않는다.
- Drive media 누락이 하나라도 있으면 학습하지 않는다.
- CUDA가 없으면 CPU로 조용히 학습하지 않는다.
- test split으로 threshold나 해상도를 고르지 않는다.
- AI GPU 노트북은 perception만 담당하며 비행이나 분사를 직접 제어하지 않는다.

## 현재 성공의 의미

현재 “완료”는 학습 코드와 Colab 준비가 끝났다는 뜻이다. 실제 모델 정확도, 실시간 추론 속도, 드론 비행과 분사 안전이 검증됐다는 뜻은 아니다. 그 단계들은 dataset upload와 baseline 학습 이후 별도의 승인 절차로 진행한다.
