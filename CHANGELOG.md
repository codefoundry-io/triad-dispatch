# Changelog

## 0.2.478 — 2026-07-11

**Codex reasoning tier `max`.** The codex reasoning-effort enum now
exposes `max`, the deepest pure-depth tier, above `xhigh`:

- `ultra` is deliberately NOT exposed — it adds automatic subagent
  delegation on top of max reasoning, which makes a single-shot dispatch
  run away and over-long, and not every model variant supports it; the
  wrapper rejects `--reasoning ultra` at parse time.
- The cross-family-review codex leg moves its top tier `xhigh` → `max`.
- The wrapper pins no model, so it auto-routes to the current default;
  only the reasoning enum changed.

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
