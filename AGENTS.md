# Agent Instructions - Cubeage GitHub Infrastructure

This repository follows the central Sylphx doctrine:
<https://github.com/SylphxAI/doctrine>.

Before changing behavior, read:

- [PROJECT.md](./PROJECT.md) for this repository's goal, boundary, public
  surfaces, and delivery proof.
- [.doctrine/project.json](./.doctrine/project.json) for the machine-readable
  project manifest consumed by central audits.

Local validation ladder:

```bash
python3 -m json.tool .doctrine/project.json
git diff --check
```

Workflow changes should also be validated with an Actions workflow linter when
available and by exercising a consumer repository that calls the reusable
workflow.
