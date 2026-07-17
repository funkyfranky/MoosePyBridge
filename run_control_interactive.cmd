@echo off
set PYTHONPATH=%CD%\python
set CONTROL_HOST=127.0.0.1
set CONTROL_PORT=42001
set TIMEOUT=10.0
set DEBUG=

if "%~1"=="--help" goto help
if "%~1"=="-h" goto help
if "%~1"=="--debug" set DEBUG=--debug
if "%~2"=="--debug" set DEBUG=--debug
if "%~3"=="--debug" set DEBUG=--debug
if "%~4"=="--debug" set DEBUG=--debug

if not "%~1"=="" if not "%~1"=="--debug" set CONTROL_PORT=%~1
if not "%~2"=="" if not "%~2"=="--debug" set CONTROL_HOST=%~2
if not "%~3"=="" if not "%~3"=="--debug" set TIMEOUT=%~3

python examples\control_server_client\interactive_control_client.py --control-host %CONTROL_HOST% --control-port %CONTROL_PORT% --timeout %TIMEOUT% %DEBUG%
goto end

:help
python examples\control_server_client\interactive_control_client.py --help

:end
