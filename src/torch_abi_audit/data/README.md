# Vendored data

Two generated JSON files mapping stable-ABI shim functions to the torch release
that introduced them. `torch_abi_audit.torch_versions.stable_shim_versions()` merges both into one
`{symbol: (major, minor, patch)}` map. Do not edit by hand.

## `shim_function_versions.json`

Pre-parsed copy of PyTorch's shim version manifest
([upstream](https://github.com/pytorch/pytorch/blob/main/torch/csrc/stable/c/shim_function_versions.txt)),
which lists only symbols introduced in 2.10.0 and later.

```bash
python scripts/update_shim_versions.py            # rewrite from pytorch/pytorch@main
python scripts/update_shim_versions.py --ref v2.14.0
python scripts/update_shim_versions.py --check    # CI: fail if stale
```

## `baseline_shim_symbols.json`

The shim symbols already present at the 2.9.0 tag, which the manifest omits.
Without it, a symbol absent from the manifest is ambiguous: it could predate
2.10.0 or be newer than our data. This file lets an audit tell *baseline* (2.9.0)
from *unknown* rather than silently flooring both to 2.9.0. Immutable, so it stays
disjoint from the manifest.

```bash
python scripts/generate_baseline_shims.py          # rewrite from pytorch/pytorch@v2.9.0
python scripts/generate_baseline_shims.py --check  # CI: fail if stale
```
