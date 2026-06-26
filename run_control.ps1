param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ControlArgs
)

$env:PYTHONPATH = Join-Path (Get-Location) "python"
python -m moosebridge.control_cli @ControlArgs
