param(
    [switch]$Help,
    [switch]$Debug,
    [string]$ControlHost = "127.0.0.1",
    [int]$ControlPort = 51001,
    [float]$Timeout = 10.0
)

$env:PYTHONPATH = Join-Path (Get-Location) "python"
if ($Help) {
    python examples\control_server_client\interactive_control_client.py --help
    exit $LASTEXITCODE
}
$args = @("examples\control_server_client\interactive_control_client.py", "--control-host", $ControlHost, "--control-port", $ControlPort, "--timeout", $Timeout)
if ($Debug) {
    $args += "--debug"
}
python @args
