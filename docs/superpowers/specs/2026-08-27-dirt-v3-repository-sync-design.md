# Dirt v3 Repository Context Sync Design

## Goal

Synchronize the repository with the locked Dirt v3 candidate without committing model binaries or claiming field approval. Preserve the existing Panel contract and the legacy `models/dirt_v2` delivery paths.

## Evidence authority

The repository update uses the Drive `dirt_v3_evidence` files, the V3 integration manifest, and their verified SHA-256 digests as authoritative. The prompt values matched the threshold selection, regression audit, final unseen, final verdict, artifact index, runtime contract, and ONNX parity reports.

The V3 handoff also contains stale packaging metadata: `CHECKSUMS.sha256` records the old Dirt v2 ONNX digest and `models/dirt_v2/model.json` declares the old `images`/`mask_logits` v2 contract. Those two files must not be represented as valid Dirt v3 runtime metadata. The repository will document this fail-closed integration constraint instead of inventing a schema-v1 manifest.

## Active contract

- Model status: `LOCKED_DO_NOT_TUNE`
- Quality status: `QUALITY_EVALUATED`
- Deployment status: `PRODUCTION_CANDIDATE`
- Approval status: `FIELD_APPROVAL_REQUIRED`
- Production approved: `NO`
- Final unseen: `CONSUMED_DO_NOT_TUNE`
- Input: `input`, float32, `[1, 3, 384, 640]`
- Output: `binary_logit`, float32, `[1, 1, 384, 640]`
- Output semantic: `class1_logit - class0_logit`
- Probability: `sigmoid(binary_logit)` outside ONNX
- Threshold: `0.997250`
- Minimum component area: `8`
- Minimum component area ratio: `0.0001`
- Dirt ONNX SHA-256: `17f20296f3ba14bf9d7e5f09126fd84c460ea6bc05b829b089ebb1c17ddaed7f`
- Panel ONNX SHA-256: `49175ff2da601d33646e52e78f9123fd2882b213a25d6f0cb8a18e266d26a4c5`

## Repository changes

Add a small checked-in runtime-contract JSON containing only verified metadata and hashes. It is evidence/configuration, not a model bundle manifest and not a replacement for `model.json`.

Update the root README, AI pipeline documentation, model delivery documentation, and laptop runtime documentation. Keep detailed training and evaluation results in a dedicated Dirt v3 document so the root README remains operational.

Do not change the generic ONNX segmentation implementation: it already handles a single declared output, applies sigmoid for logits, thresholds externally, filters connected components, and inverse-maps letterbox coordinates. Do not point the active worker configuration at the stale handoff sidecar. A corrected schema-v1 manifest that matches the v3 ONNX is still required for fail-closed runtime startup.

## Verification

Add a repository contract test that parses the checked-in JSON and checks the consumer-visible locked values and SHA-256 identifiers. Run the focused laptop segmentation tests, root tests, laptop tests, training tests, compile checks, JSON parsing, binary-addition checks, and a secret-pattern scan. Review README/code/contract consistency before committing.
