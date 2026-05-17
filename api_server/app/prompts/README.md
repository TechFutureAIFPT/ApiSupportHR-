# Prompt Management

This folder centralizes every LLM prompt used by the backend.

## Structure

- One prompt family gets its own folder.
- Each prompt version is stored as `vN.md`.
- Active versions are mapped in `app/prompts/registry.py`.

## Placeholder format

Prompt variables use the form:

```text
[[variable_name]]
```

This avoids conflicts with JSON examples that use `{}` heavily.

## Current goal

The backend can now:

- keep prompt text out of service logic
- version prompts in one place
- swap prompt versions later with a small registry change

## Next possible upgrades

- log `prompt_key` and `prompt_version` into history records
- build prompt A/B testing
- add an admin UI or config-based prompt switching
