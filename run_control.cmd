@echo off
set PYTHONPATH=%CD%\python
python -m moosebridge.control_cli %*
