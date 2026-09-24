# Audit remediation

This patch starts from `23c2905` and maps each audit finding to its code and regression coverage.

| Finding | Change | Regression coverage |
|---|---|---|
| F01 | Stock purchase confirmations carry an explicit `new_purchase`, `resume_bridge`, or `check_status` action. Only a fresh, unexpired purchase preview carries spend and minimum-output approval. Status checks are read-only and watchers always run with repeat purchasing disabled. | `DashboardHTTPTests.test_completed_during_preview_is_status_check_not_repeat_purchase`, stock purchase confirmation tests, `AuditFixTests.test_f01_completion_during_status_preview_cannot_become_purchase` |
| F04 | `Stop all` invalidates a shared execution generation and includes current and legacy purchase watchers. Broadcast holds a shared barrier lock, so stop waits for an active submission and stale requests cannot submit afterward. | `AuditFixTests.test_f04_stop_barrier_waits_for_submission_and_rejects_stale_generation`, worker-control and watcher tests |
| F02 | Jupiter v6 exact-input `route` and `sharedAccountsRoute` instructions are decoded and bound to the approved quote. Lookup tables, signer count, source/destination accounts, mints, amounts, slippage, writable permissions, platform fee, compute budget, and priority fee are checked before simulation and signing. Other variants are rejected. | `AuditFixTests.test_f02_jupiter_route_is_bound_to_preview_and_fee`, `test_f02_lookup_tables_are_resolved_and_owner_checked` |
| F03 | The bridge transaction lock now uses the correct state helper instead of the undefined `TX_s` name. | `AuditFixTests.test_f03_bridge_transaction_lock_has_no_undefined_reference`, `tools/check_undefined_names.py` |
| F07 | Conversion journal reconciliation and reservation use one file lock. Reservation rereads the journal while locked and refuses a concurrent pending conversion. | `AuditFixTests.test_f07_conversion_journal_lock_preserves_concurrent_append` |
| F05 | Solana purchase and bridge simulations compare the same associated token accounts before and after. Receipt verification uses the expected account index instead of aggregating unrelated owner accounts. | `AuditFixTests.test_f05_receipt_uses_expected_account_not_secondary_balance` |
| F06 | API-key reads use `O_NOFOLLOW`, reject non-regular or foreign-owned files, and require mode `0600`. Receipt cache loading now uses the hardened state reader. | `AuditFixTests.test_f06_credential_and_cache_reads_reject_symlinks_and_modes`, state-security tests |

## Validation

```bash
python3 tools/check_undefined_names.py
python3 -m unittest discover -s tests -t . -q
```

No validation command signs or broadcasts a transaction. Jupiter instruction support is intentionally restricted to the two decoded exact-input variants; a newly introduced route variant will fail closed until its layout is reviewed and added.
