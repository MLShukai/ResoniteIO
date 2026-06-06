---
name: api-contract-test-pins-all
description: Adding a Python modality client export to resoio.__all__ will fail test_api_contract.py until spec-test-author updates the frozen expected tuple
type: feedback
---

`python/tests/resoio/test_api_contract.py::test_all_matches_expected_public_names_exactly`
pins `resoio.__all__` against a hardcoded `_EXPECTED_PUBLIC_NAMES` tuple.

**Why:** It is a public-API surface contract — it intentionally breaks when
`__all__` changes so the change is reviewed deliberately.

**How to apply:** When implementing a new Python modality client and adding its
exports to `resoio/__init__.py`'s `__all__`, this test WILL fail in the
implementer's working tree. Do NOT touch the test (it's under `python/tests/`).
This is expected: `spec-test-author` owns updating `_EXPECTED_PUBLIC_NAMES`.
Before reporting it as a real failure, verify the only diff vs the old expected
tuple is your new modality's names, inserted in the correct alphabetical
position. Report it as "expected, blocked on test author" rather than a bug.
