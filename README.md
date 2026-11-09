# labscpi

Python drivers for SCPI bench instruments: power supplies (`psu_scpi`), electronic loads
(`eload_scpi`) and oscilloscopes (`oscilloscope`). Each one asks the instrument `*IDN?` and
picks the adapter for its brand and model, with a generic SCPI fallback. What every driver
offers is written in `docs/api/`. MIT licence (`LICENSE`).

## Adding an instrument

Your instrument is missing, or one of its commands differs? Add an adapter and propose it.

- **Oscilloscope:** add a module in `src/labscpi/oscilloscope/` with a class that subclasses
  `BrandAdapter`; nothing else to register. One general class per brand, whose `brand` /
  `vendor_aliases` are the vendor name exactly as the instrument reports it in `*IDN?`. A model
  that differs subclasses it and sets `MODEL_PATTERNS` (anchored regexes on the model field).
  The rules are at the top of `src/labscpi/oscilloscope/__init__.py`.
- **Power supply or electronic load:** in `psu_scpi.py` or `eload_scpi.py`, a brand class
  subclassing `BrandAdapter`, and model classes registered with `@<Brand>.register_model` and
  their `MODEL_PATTERNS`.
- Override only what your instrument does differently; keep the methods and units of
  `docs/api/`.
- Add your instrument's `*IDN?` reply to the selection tests (`tests/`) and run
  `python -m pytest`.
- Open a pull request naming the instrument, its firmware, and what you checked on the real
  instrument.

## Dev setup, editable install, and builds

## Prereqs
- Python 3.10+
- pip and venv

## Create/activate venv
```bash
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

python -m pip install -U pip
pip install -r requirements.txt

```


## Editable install (live code, best for VS Code)
```bash
pip install -e .
```
Now `import labscpi` resolves to your source and edits are instant.



## Build distributables (wheel + sdist)
```bash
pip install build
Remove-Item -Recurse -Force .\dist
python -m build
```

## Install the built wheel (test)
```bash
pip install .\dist\labscpi-<version>-py3-none-any.whl --force-reinstall
```
`<version>` is the one in `pyproject.toml`.

## VS Code tips
- Select the `.venv` interpreter.
- Autocomplete works from the editable install.
- Ensure `labscpi/__init__.py` re-exports your public API and `py.typed` exists.

## Uninstall / clean
```bash
pip uninstall labscpi
rm -rf .venv build dist *.egg-info
```
