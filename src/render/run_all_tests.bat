@echo off
REM render shim -> pixo 命名空间下的真实一键测试入口
REM 实际阻塞分支在 src\pixo\render\run_all_tests.bat：
REM   [4/6 FAIL] / [5/6 FAIL] / [6/6 FAIL]
call "%~dp0..\pixo\render\run_all_tests.bat"
exit /b %ERRORLEVEL%
