@echo off
REM pixo.render native C++ unit tests (MinGW-w64 + CMake)
REM Usage: run run_tests.bat inside native/
setlocal

set "CMAKE=D:\code\cmake-3.31.6-windows-x86_64\bin\cmake.exe"
set "MINGW=D:\code\mingw64"

if exist build_tests rd /s /q build_tests
mkdir build_tests

"%CMAKE%" -S . -B build_tests -G "MinGW Makefiles" ^
  -DCMAKE_MAKE_PROGRAM="%MINGW%\bin\mingw32-make.exe" ^
  -DCMAKE_CXX_COMPILER="%MINGW%\bin\g++.exe" ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DPIXO_RENDER_NATIVE_BUILD_TESTS=ON ^
  -DPIXO_RENDER_NATIVE_OPENMP=OFF ^
  -DPIXO_RENDER_NATIVE_COPY_TO_PY=OFF
if errorlevel 1 exit /b 1

"%CMAKE%" --build build_tests --config Release
if errorlevel 1 exit /b 1

set "PATH=%CD%\build_tests;%PATH%"
build_tests\tests\pixo_render_native_tests.exe
if errorlevel 1 exit /b 1

echo.
echo [OK] native tests passed
