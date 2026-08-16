# DA-DAKA repository agent instructions

## Inter-device handoff

When a task depends on the Raspberry Pi or GPU laptop, and `dadaka-agent` is
available, run `dadaka-agent receive` before duplicating work on the other
device. Use `dadaka-agent send` for a bounded request and `dadaka-agent reply`
for the result.

Include the task, status, commit SHA, test result, and artifact paths needed for
handoff. Transfer source changes through Git branches or commits. Never put
passwords, API tokens, SSH private keys, personal data, or model weights in a
bridge message. A bridge outage must not bypass flight, calibration, or spray
safety gates.
