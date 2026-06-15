@echo off
set PYTHONPATH=%CD%\python
python -m moosebridge --host 127.0.0.1 --port 50100 --log moosebridge_raw.jsonl
