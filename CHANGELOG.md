# Changelog

## 0.2.464 — 2026-07-06

**Repair privilege-separation redesign.** The self-improving classifier's
repair path is now split so the component that reads an untrusted vendor
run-log has zero write authority:

- The in-session repair agent is a **read-only analyzer** (`Read, Grep,
  Glob` only) that proposes one classifier delta as inline JSON — it never
  edits a file, spawns a process, or reaches the network.
- The leader applies the proposal via the **deterministic, zero-LLM**
  `bin/apply_patch.py`, which re-validates every field and is the only
  writer to the persistent classifier extension.
- Ships a **SECURITY.md** documenting the threat model, the control, and —
  explicitly — what is NOT the control ("the model resists injection" is not
  the boundary).

README polish: value-first opening, a copy-runnable first-dispatch example,
a troubleshooting + exit-code section, and an honest scope-&-limits list.

Built from the Triad source of truth. Full history: https://github.com/codefoundry-io/triad-dispatch/commits/main (each release commit summarizes its delta).

### Upgrading from 0.1.x (installed before 2026-07-05)

The marketplace was renamed `triad-internal-tools` → `triad-dispatch`,
so a bare `claude plugin update triad-dispatch` reports *not found*
(verified). Use either path once:

```bash
claude plugin update triad-dispatch@triad-internal-tools   # keeps the old key
# — or a clean re-key —
claude plugin marketplace remove triad-internal-tools
claude plugin marketplace add <repo-or-path>
claude plugin install triad-dispatch
```

Both were tested; neither leaves a ghost install or duplicate skills.
