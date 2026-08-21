# pixo.render native C++ unit tests (零依赖, 不引入 gtest)。
# 仅当 PIXO_RENDER_NATIVE_BUILD_TESTS=ON 时构建。
add_executable(pixo_render_native_tests
    test_main.cpp
)

target_link_libraries(pixo_render_native_tests PRIVATE pixo_render_native)
