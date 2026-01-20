# labscpi — dev setup, editable install, and builds

## Prereqs
- Python 3.9+
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



## Update CRC before build##
```bash
python .\update_checksums.py ".\src\labscpi\rules\0.2.0"
```


## Build distributables (wheel + sdist)
```bash
pip install build
Remove-Item -Recurse -Force .\dist
python -m build
```

## Install the built wheel (test)
```bash
pip install .\dist\labscpi-0.1.0-py3-none-any.whl --force-reinstall
```

## VS Code tips
- Select the `.venv` interpreter.
- Autocomplete works from the editable install.
- Ensure `labscpi/__init__.py` re-exports your public API and `py.typed` exists.

## Uninstall / clean
```bash
pip uninstall labscpi
rm -rf .venv build dist *.egg-info
```
