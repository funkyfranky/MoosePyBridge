$env:PYTHONPATH = Join-Path (Get-Location) "python"
python -m moosebridge --host 127.0.0.1 --port 42000 --control-port 42001 --log moosebridge_raw.jsonl
