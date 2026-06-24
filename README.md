# aihydro-core

Robustness substrate for the AI-Hydro ecosystem.

Provides the single hashing and provenance vocabulary (`content_hash`, `param_hash`,
`ProvenanceRecord`) shared across all AI-Hydro packages, plus the `Store` protocol and
`AsyncJobRegistry` used by higher-level layers.

**Zero heavy dependencies** — pure Python stdlib. Designed to be the lowest layer in the
stack so it can be safely depended on by any AI-Hydro package without pulling in numpy,
pandas, or geo libraries.

## Install

```bash
pip install aihydro-core
```

## Part of the AI-Hydro ecosystem

- [aihydro-data](https://github.com/AI-Hydro/AIhydro-data) — global hydrology dataverse
- [AI-Hydro](https://github.com/AI-Hydro/AI-Hydro) — AI-native hydrologic modelling platform

## Citation

If you use `aihydro-core` in your research, please cite:

```bibtex
@software{aihydro_core_2026,
  title   = {aihydro-core: Zero-Dependency Substrate for Scientific Defensibility},
  author  = {Galib, Mohammad and Merwade, Venkatesh},
  year    = {2026},
  version = {0.2.0},
  doi     = {10.5281/zenodo.20823444},
  url     = {https://doi.org/10.5281/zenodo.20823444}
}
```
