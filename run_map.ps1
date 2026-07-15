$env:PYTHONPATH = Join-Path $PSScriptRoot "python"
python -m moosebridge.map_server @args
