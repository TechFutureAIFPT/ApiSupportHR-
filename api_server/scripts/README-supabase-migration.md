# SupportHR legacy-source to Supabase migration

This workflow never writes to Firebase. It exports an encrypted snapshot, imports with idempotent upserts, and reconciles totals before cutover.

## Required gates

1. Create the hosted Supabase project in Singapore, enable Pro/PITR, and apply `supabase/migrations`.
2. Import Firebase Auth with the official Supabase Firebase Auth tool, including Firebase SCRYPT parameters.
3. Set `DATABASE_URL`, `MIGRATION_ARCHIVE_KEY`, and `DATA_ENCRYPTION_KEY` only in the operator environment.
4. Keep archives outside the Git workspace. Never commit the encrypted archive, its key, auth export, or database credentials.

Generate independent 32-byte keys:

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
[Convert]::ToBase64String($bytes)
```

Run the read-only source audit:

```powershell
python scripts/legacy_source_supabase_migration.py preflight
```

Create the encrypted backup:

```powershell
python scripts/legacy_source_supabase_migration.py export --output D:\SupportHR-Migration-Backups\supporthr-final.enc
```

After Auth import and SQL migration:

```powershell
python scripts/legacy_source_supabase_migration.py import --archive D:\SupportHR-Migration-Backups\supporthr-final.enc
python scripts/legacy_source_supabase_migration.py reembed
python scripts/legacy_source_supabase_migration.py reconcile --archive D:\SupportHR-Migration-Backups\supporthr-final.enc
```

`reembed` only replaces the operational vector contract. The original 3072-dimension values remain in `legacy_embedding` and `source_payload` for reconciliation.

The final maintenance-window run repeats export/import/reconcile after writes and workers are stopped. Production runtime remains disabled until reconciliation succeeds and the required Supabase secrets are present.
