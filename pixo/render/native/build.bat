@echo off
setlocal
set "CMAKE=D:\code\cmake-3.31.6-windows-x86_64\bin\cmake.exe"
set "MINGW=D:\code\mingw64"
if exist build rd /s /q build
mkdir build
"%CMAKE%" -S . -B build -G "MinGW Makefiles" -DCMAKE_MAKE_PROGRAM="%MINGW%\bin\mingw32-make.exe" -DCMAKE_CXX_COMPILER="%MINGW%\bin\g++.exe" -DCMAKE_BUILD_TYPE=Release
if errorlevel 1 exit /b 1
"%CMAKE%" --build build --config Release
if errorlevel 1 exit /b 1
echo [OK] pixo_render_native.dll copied to ..\_native\
