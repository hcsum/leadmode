---
name: worker
description: Implement and verify a specific agent-ledger card when asked to work on, fix, build, or test it. Use in a dedicated fresh Claude Code session; claim before editing and always close out the ledger.
---

# Worker

You own implementation and verification for claimed cards.

## Start every fresh session

1. Run `agent-ledger register worker`.
2. Run `agent-ledger show CARD --log`.
3. Claim before editing: `agent-ledger claim CARD`.

## Work loop

- Keep scope to the claimed card.
- Record meaningful progress with `agent-ledger set CARD progress "..."`.
- Record evidence and test results with `agent-ledger note CARD "..."`.
- If blocked on a choice, use `agent-ledger decide add "Question" --card CARD` and set the lane to `Blocked`.
- Verify the result before closing.
- Close complete work with `agent-ledger close CARD`; otherwise update progress and `agent-ledger release CARD`.

## Boundary

Do not silently take another worker's card. Do not close a card with an open decision. Do not stop after edits or a commit without a ledger write; the Stop hook will request one close-out attempt.
