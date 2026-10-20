@echo off
rem SPEC Registry Windows 入口: 需要 python 3 与 pyyaml
where python >nul 2>nul && (python "%~dp0workspace.py" %*) || (py -3 "%~dp0workspace.py" %*)
