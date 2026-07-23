# GraphRAG runtime artifacts

Only a release artifact that passes `ml_pipeline/validate_graph_release.py` belongs here.

Runtime accepts facts only when all of these fields are present and valid:

- `schemaVersion=supporthr-graph-fact-v1`
- `status=approved`
- `approved=true`
- `decisionImpact=none`
- reviewer and source checksum provenance

Pending graph candidates, raw CV/JD text, and Hugging Face datasets must remain under the ignored
offline `ml_pipeline/data` or `ml_pipeline/artifacts` directories.
