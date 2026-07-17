@echo off
set PYTHONPATH=%CD%\python
set HOST=127.0.0.1
set PORT=42000
set LOG=moosebridge_raw.jsonl
set READER_LIMIT=16777216

if not "%~1"=="" set PORT=%~1
if not "%~2"=="" set HOST=%~2

python -m moosebridge --host %HOST% --port %PORT% --log %LOG% --reader-limit %READER_LIMIT% --interactive
