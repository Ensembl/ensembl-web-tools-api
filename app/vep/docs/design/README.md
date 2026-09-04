# VEP design documents

These documents describe the VEP implementation in this repository and its
client integration. Keep them in step with code changes; derive implementation
details and counts from the code rather than editing them by hand.

| Document | Use it for |
| --- | --- |
| [spec-and-extension-guide.md](./spec-and-extension-guide.md) | Spec format and adding annotations, options, or display output. |
| [technical-notes.md](./technical-notes.md) | Submission, pagination, filtering, performance, and testing decisions. |
| [dataflow.md](./dataflow.md) | End-to-end request flow and external dependencies. |
| [production-readiness.md](./production-readiness.md) | Deployment prerequisites and known non-blocking work. |

## Common tasks

| Task | Start here |
| --- | --- |
| Add an annotation option | [Guide: simple plugin](./spec-and-extension-guide.md#4-recipe-a--a-simple-plugin-end-to-end) and its checklist. |
| Add an allele-frequency source | [Guide: allele frequencies](./spec-and-extension-guide.md#6-recipe-c--a-new-allele-frequency-source). |
| Add a results filter | [Guide: results filters](./spec-and-extension-guide.md#73-a-new-results-filter). |
| Change form placement | [Guide: form block](./spec-and-extension-guide.md#85-the-form-block). |
| Trace a request | [Data flow](./dataflow.md). |
| Prepare deployment | [Production readiness](./production-readiness.md). |

## Updating documentation

Update the document that owns a changed behaviour in the same PR. In particular,
check the guide after changing spec models or vocabulary, technical notes after
changing runtime behaviour, data flow after changing routes or integrations, and
production readiness after resolving or adding operational work.

Before renaming a document, find code references:

```bash
rg 'app/vep/docs/design' app
```
