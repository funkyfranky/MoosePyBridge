$env:PYTHONPATH = Join-Path (Get-Location) "python"
python -m moosebridge --host 127.0.0.1 --port 51000 --log moosebridge_raw.jsonl
