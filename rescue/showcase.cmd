@echo off
cd /d "%~dp0.."
if "%~1"=="" (
  py -3 -m rescue.rescue_run --store northwind --cases 8 --holdout 4 --workers 6 --open
) else if "%~2"=="" (
  py -3 -m rescue.rescue_run --policy-file "%~1" --cases 8 --holdout 4 --workers 6 --open
) else (
  py -3 -m rescue.rescue_run --policy-file "%~1" --world-file "%~2" --cases 8 --holdout 4 --workers 6 --open
)
pause
