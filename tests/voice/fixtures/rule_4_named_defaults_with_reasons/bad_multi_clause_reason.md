read: ~/data/checkout.parquet

I'll go with event_ts. The reasoning is involved and I'll explain it below in detail across several considerations including null patterns and monotonicity properties that matter for the analysis we are doing.
