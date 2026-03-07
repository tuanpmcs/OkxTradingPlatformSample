cmake_minimum_required(VERSION 3.25)

project(
    hello_world
    VERSION 1.0
    DESCRIPTION "Hello World C++20 project"
    LANGUAGES C CXX
)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/lib)

set(GIT_SHA "Unknown" CACHE STRING "SHA this build was generated from")
string(SUBSTRING "${GIT_SHA}" 0 8 GIT_SHORT_SHA)

if(MSVC)
    add_compile_options(/bigobj)
endif()

add_executable(hello_world
    main.cpp
)

find_package(boost_headers CONFIG REQUIRED)
find_package(boost_system CONFIG REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(spdlog CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(yaml-cpp CONFIG REQUIRED)

target_link_libraries(hello_world PRIVATE
    Boost::headers
    Boost::system
    OpenSSL::SSL
    OpenSSL::Crypto
    spdlog::spdlog
    nlohmann_json::nlohmann_json
    yaml-cpp::yaml-cpp
)

target_compile_definitions(hello_world PRIVATE
    GIT_SHORT_SHA="${GIT_SHORT_SHA}"
)
