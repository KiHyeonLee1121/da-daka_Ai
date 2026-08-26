# Dirt v3 Repository Context Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record the verified locked Dirt v3 candidate in repository contracts and documentation without committing binaries or enabling unverified production deployment.

**Architecture:** A checked-in JSON contract is the machine-readable source for verified Dirt v3 values. Human-facing documents summarize or expand that contract, while the existing generic manifest-based runtime stays fail-closed until a matching schema-v1 model sidecar is delivered.

**Tech Stack:** JSON, Markdown, Python/pytest, existing NumPy/OpenCV laptop runtime

**Spec:** `docs/superpowers/specs/2026-08-27-dirt-v3-repository-sync-design.md`

## Global Constraints

- Preserve the fixed training workspace; work only in the separate clone and feature branch.
- Do not commit ONNX, checkpoint, ZIP, dataset, CVAT, video, mask, frame, or probability-cache artifacts.
- Keep the compatibility paths `models/dirt_v2/model.onnx` and `models/dirt_v2.onnx`; they contain Dirt v3 in the V3 handoff.
- Do not change Panel model/runtime behavior.
- Keep `PRODUCTION_APPROVED` false and require field approval.
- Never use the consumed final unseen set for tuning.
- Treat the stale V3 handoff checksum file and Dirt sidecar as packaging defects, not runtime authority.

---

### Task 1: Add the repository Dirt v3 contract

**Files:**
- Create: `models/dirt_v3_runtime_contract.json`
- Create: `tests/test_dirt_v3_repository_contract.py`

**Interfaces:**
- Consumes: verified Drive evidence and locked identifiers in the design spec
- Produces: a parseable repository contract consumed by tests and referenced by documentation

- [ ] **Step 1: Write the failing contract test**

```python
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_locked_dirt_v3_repository_contract():
    contract = json.loads(
        (ROOT / 'models/dirt_v3_runtime_contract.json').read_text(encoding='utf-8')
    )
    assert contract['model']['sha256'] == '17f20296f3ba14bf9d7e5f09126fd84c460ea6bc05b829b089ebb1c17ddaed7f'
    assert contract['input'] == {'name': 'input', 'dtype': 'float32', 'shape': [1, 3, 384, 640]}
    assert contract['output']['name'] == 'binary_logit'
    assert contract['output']['probability'] == 'sigmoid(binary_logit)'
    assert contract['postprocess'] == {'threshold': 0.99725, 'minimum_component_area': 8, 'minimum_component_area_ratio': 0.0001}
    assert contract['status']['production_approved'] is False
    assert contract['status']['final_unseen'] == 'CONSUMED_DO_NOT_TUNE'
```

- [ ] **Step 2: Run the test and verify it fails because the contract file is missing**

Run: `python -m pytest -q tests/test_dirt_v3_repository_contract.py`

Expected: failure opening `models/dirt_v3_runtime_contract.json`.

- [ ] **Step 3: Add the verified JSON contract**

Create the file with the exact input/output/postprocess/status values and hashes from the design spec, plus the two legacy delivery paths and an explicit `MODEL_SIDECAR_REGENERATION_REQUIRED` integration state.

- [ ] **Step 4: Run the focused contract and segmentation tests**

Run: `python -m pytest -q tests/test_dirt_v3_repository_contract.py laptop_ai/tests/test_segmentation_postprocess.py`

Expected: all tests pass.

### Task 2: Synchronize user and developer documentation

**Files:**
- Create: `docs/dirt_v3_candidate.md`
- Modify: `README.md`
- Modify: `docs/ai_data_pipeline.md`
- Modify: `models/README.md`
- Modify: `laptop_ai/README.md`

**Interfaces:**
- Consumes: `models/dirt_v3_runtime_contract.json`
- Produces: concise project status, detailed evidence history, model delivery rules, and runtime integration guidance

- [ ] **Step 1: Add the detailed Dirt v3 lifecycle document**

Record training membership, fresh initialization, epoch/loss/optimizer details, DEV threshold selection before final unseen, regression views, sealed final results, ONNX parity, locked hashes, deployment status, and prohibited tuning work.

- [ ] **Step 2: Update the root README**

Add the Panel → ROI → Dirt flow, active Dirt v3 runtime contract, legacy path warning, final-quality summary, approval boundary, artifact delivery rule, and a link to the detailed document. Replace the obsolete statement that validation and threshold selection are still outstanding for Dirt.

- [ ] **Step 3: Update pipeline, model, and laptop runtime documents**

Separate the active v3 contract from historical v2 records; explain that the generic runtime already uses declared logits and external sigmoid/postprocess; state that the stale handoff sidecar must not be passed to the fail-closed worker; require a matching schema-v1 manifest before runtime activation.

- [ ] **Step 4: Review documentation against the JSON contract**

Compare every status, name, shape, threshold, component filter, and hash used in the documents with `models/dirt_v3_runtime_contract.json`.

### Task 3: Verify, audit, and publish

**Files:**
- Modify only files already listed in Tasks 1 and 2 if verification exposes an error.

**Interfaces:**
- Consumes: completed repository changes
- Produces: verified commits and a pushed feature branch

- [ ] **Step 1: Install test dependencies in an isolated virtual environment**

Run the repository requirements and editable laptop/training installs inside `.venv-dirt-v3-sync`.

- [ ] **Step 2: Run repository verification**

Run Python compileall, root tests, laptop tests, training tests, and the pure ROS tests from the existing full-software-audit workflow that are supported on this host.

- [ ] **Step 3: Audit the diff**

Check `git diff --check`, JSON parsing, tracked binary extensions, large files, local absolute paths outside provenance text, credential patterns, and README/code/contract consistency.

- [ ] **Step 4: Commit and push**

Commit the verified changes with a focused docs/runtime message, push `chore/sync-dirt-v3-context-20260827`, and create a pull request if authenticated tooling is available.
