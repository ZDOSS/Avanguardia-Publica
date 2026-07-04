# Manual chunks for `0014_covoting_timeout_hardening.sql`

Use the full migration first when possible:

```sql
migrations/0014_covoting_timeout_hardening.sql
```

If the Supabase SQL editor or the old managed project times out, run these files in order:

1. `0014_01_covoting_indexes.sql`
2. `0014_02_covoting_rpc.sql`
3. `0014_03_permissions_reload.sql`

Afterward, validate the problematic profile:

```sql
select *
from public.get_covoting('13b55892-fedb-5a23-b3c6-d363f23e5e73'::uuid);
```

The expected result is either a bounded list of co-voting overlaps or zero rows. It should
not return `57014 canceling statement due to statement timeout`.
