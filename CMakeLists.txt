cmake_minimum_required(VERSION 3.25)

project(
    hello_world
    VERSION 1.0
    DESCRIPTION "Hello World C++26 project"
    LANGUAGES C CXX
)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CheckCXXCompilerFlag)
check_cxx_compiler_flag("-std=c++2c" COMPILER_SUPPORTS_CXX2C)
if(COMPILER_SUPPORTS_CXX2C)
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:-std=c++2c>)
elseif(MSVC)
    add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/std:c++latest>)
else()
    message(FATAL_ERROR "C++26/C++2c mode is not supported by the current compiler.")
endif()

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
find_package(boost_url CONFIG REQUIRED)
find_package(OpenSSL REQUIRED)
find_package(spdlog CONFIG REQUIRED)
find_package(simdjson CONFIG REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC CONFIG REQUIRED)
find_package(yaml-cpp CONFIG REQUIRED)
find_package(benchmark CONFIG REQUIRED)

set(PROTO_FILE ${CMAKE_CURRENT_SOURCE_DIR}/proto/market_data.proto)
set(PROTO_GEN_DIR ${CMAKE_CURRENT_BINARY_DIR}/generated)
file(MAKE_DIRECTORY ${PROTO_GEN_DIR})

set(PROTO_SRCS
    ${PROTO_GEN_DIR}/market_data.pb.cc
    ${PROTO_GEN_DIR}/market_data.grpc.pb.cc
)
set(PROTO_HDRS
    ${PROTO_GEN_DIR}/market_data.pb.h
    ${PROTO_GEN_DIR}/market_data.grpc.pb.h
)

add_custom_command(
    OUTPUT ${PROTO_SRCS} ${PROTO_HDRS}
    COMMAND protobuf::protoc
    ARGS
        --proto_path=${CMAKE_CURRENT_SOURCE_DIR}/proto
        --cpp_out=${PROTO_GEN_DIR}
        --grpc_out=${PROTO_GEN_DIR}
        --plugin=protoc-gen-grpc=$<TARGET_FILE:gRPC::grpc_cpp_plugin>
        ${PROTO_FILE}
    DEPENDS ${PROTO_FILE}
    VERBATIM
)

add_library(market_data_proto ${PROTO_SRCS} ${PROTO_HDRS})
target_include_directories(market_data_proto PUBLIC ${PROTO_GEN_DIR})
target_link_libraries(market_data_proto PUBLIC protobuf::libprotobuf gRPC::grpc++)

target_link_libraries(hello_world PRIVATE
    Boost::headers
    Boost::system
    Boost::url
    OpenSSL::SSL
    OpenSSL::Crypto
    spdlog::spdlog
    simdjson::simdjson
    yaml-cpp::yaml-cpp
    market_data_proto
)

target_compile_definitions(hello_world PRIVATE
    GIT_SHORT_SHA="${GIT_SHORT_SHA}"
)

add_executable(main_bench
    benchmarks/main_benchmark.cpp
)

target_link_libraries(main_bench PRIVATE
    benchmark::benchmark
)

target_compile_definitions(main_bench PRIVATE
    HELLO_WORLD_BENCH_CMD="$<TARGET_FILE:hello_world> --bench-main > /dev/null 2>&1"
)

add_dependencies(main_bench hello_world)
