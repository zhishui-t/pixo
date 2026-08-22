@echo off
REM pixo.render 一键构建 + 测试（可复现性入口）
REM
REM 步骤：
REM   1) src/pixo/render/native CMake 构建并拷贝 pixo_render_native.dll 到 src/pixo/render/_native/
REM   2) src/pixo/render/native C++ 单元测试（pixo_render_native_tests.exe）
REM   3) Python 全量单元测试（src/render/tests，不含 e2e；render 为兼容 shim）
REM   4) 功能门禁 gate 测试（pytest -m gate，失败即阻塞）
REM   5) bench_preview 冷启动（warmup=0）
REM   6) bench_preview 热启动（warmup=1, runs=2）
REM
REM 用法：
REM   render\run_all_tests.bat （顶层 shim，转发到本脚本）
REM
REM 可选环境变量：
REM   RAW_PATH  指定 bench 使用的 RAW/DNG 文件；缺省用 bench_preview.py 内置默认路径。
REM
REM 说明：
REM   - 本脚本从仓库根目录运行；PYTHONPATH 自动指向仓库根。
REM   - gate 阶段是硬门禁：任一 gate 用例失败，脚本立即以非零退出码结束。
REM   - bench 阶段为性能/质量验收（bench_preview.py 在门禁未达标时返回非零），
REM     失败同样阻塞（红灯期间禁止合入，见 FUNCTION_GATE_SPEC §9）。
setlocal EnableDelayedExpansion

set "ROOT=%~dp0..\..\.."
cd /d "%ROOT%"
set "PYTHONPATH=%ROOT%\src;%ROOT%;%PYTHONPATH%"

set "RAW_OPT="
if defined RAW_PATH set "RAW_OPT=--raw "%RAW_PATH%""

set "SUMMARY="

echo === [1/6] Native CMake 构建 ===
pushd src\pixo\render\native
call build.bat
if errorlevel 1 (
    echo [FAIL] native build failed
    set "SUMMARY=!SUMMARY! [1/6 FAIL]"
    popd
    exit /b 1
) else (
    echo [OK] native build
    set "SUMMARY=!SUMMARY! [1/6 PASS]"
)
popd

echo === [2/6] C++ 单元测试 ===
pushd src\pixo\render\native
call run_tests.bat
if errorlevel 1 (
    echo [FAIL] native C++ tests failed
    set "SUMMARY=!SUMMARY! [2/6 FAIL]"
    popd
    exit /b 1
) else (
    echo [OK] native C++ tests
    set "SUMMARY=!SUMMARY! [2/6 PASS]"
)
popd

echo === [3/6] Python 全量单元测试 ===
python -m pytest src/render/tests -q -m "not e2e"
if errorlevel 1 (
    echo [FAIL] Python tests failed
    set "SUMMARY=!SUMMARY! [3/6 FAIL]"
    exit /b 1
) else (
    echo [OK] Python tests
    set "SUMMARY=!SUMMARY! [3/6 PASS]"
)

echo === [4/6] 功能门禁 gate 测试（离线 L0-L2，失败阻塞） ===
python -m pytest src/render/tests/gate -q -m "gate and not gate_e2e"
if errorlevel 1 (
    echo [FAIL] gate tests failed
    set "SUMMARY=!SUMMARY! [4/6 FAIL]"
    exit /b 1
) else (
    echo [OK] gate tests
    set "SUMMARY=!SUMMARY! [4/6 PASS]"
)

echo === [5/6] bench_preview cold (warmup=0, runs=1; 失败阻塞) ===
python src/pixo/render/tools/bench_preview.py %RAW_OPT% --mode cold --edges 1024,2048 --runs 1 --warmup 0 --ab ^
    --baseline src/pixo/render/bench/preview_cold_baseline.json
if errorlevel 1 (
    echo [FAIL] bench_preview cold 未达标（性能或 A/B 门禁）
    set "SUMMARY=!SUMMARY! [5/6 FAIL]"
    exit /b 1
) else (
    echo [OK] bench_preview cold finished
    set "SUMMARY=!SUMMARY! [5/6 PASS]"
)

echo === [6/6] bench_preview hot (warmup=1, runs=2; 失败阻塞) ===
python src/pixo/render/tools/bench_preview.py %RAW_OPT% --mode hot --edges 1024,2048 --runs 2 --warmup 1 --ab ^
    --baseline src/pixo/render/bench/preview_hot_baseline.json
if errorlevel 1 (
    echo [FAIL] bench_preview hot 未达标（性能或 A/B 门禁）
    set "SUMMARY=!SUMMARY! [6/6 FAIL]"
    exit /b 1
) else (
    echo [OK] bench_preview hot finished
    set "SUMMARY=!SUMMARY! [6/6 PASS]"
)

echo.
echo === PASS/FAIL 汇总 ===
echo %SUMMARY%
echo [OK] pixo.render run_all_tests completed
exit /b 0
