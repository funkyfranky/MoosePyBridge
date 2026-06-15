param(
    [string]$HostName = "127.0.0.1",
    [int]$Port = 50100,
    [string]$Log = "moosebridge_raw.jsonl",
    [int]$ReaderLimit = 16777216
)

$env:PYTHONPATH = Join-Path (Get-Location) "python"
python -m moosebridge --host $HostName --port $Port --log $Log --reader-limit $ReaderLimit --interactive
