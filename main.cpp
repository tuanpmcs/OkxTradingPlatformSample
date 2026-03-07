#include <boost/asio.hpp>
#include <boost/asio/dispatch.hpp>
#include <boost/asio/post.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/core/flat_buffer.hpp>
#include <boost/beast/ssl/ssl_stream.hpp>
#include <boost/beast/websocket.hpp>
#include <boost/beast/websocket/ssl.hpp>
#include <boost/multiprecision/cpp_dec_float.hpp>
#include <nlohmann/json.hpp>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

#include <array>
#include <chrono>
#include <cstdint>
#include <deque>
#include <functional>
#include <iostream>
#include <memory>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <utility>
#include <variant>
#include <vector>

#include <yaml-cpp/yaml.h>

namespace net = boost::asio;
namespace ssl = net::ssl;
namespace beast = boost::beast;
namespace websocket = beast::websocket;
using tcp = net::ip::tcp;
using json = nlohmann::json;

// logger.h
class Logger
{
public:
	static void init_file(const std::string& log_file, size_t max_size, size_t max_files);
	static void init_console();
	static void shutdown();
};

#define LOG_STREAM(level, ...)   \
	do                           \
	{                            \
		std::stringstream ss;    \
		ss << __VA_ARGS__;       \
		spdlog::level(ss.str()); \
	} while (0)

#define LOG_STREAM_INFO(...)  LOG_STREAM(info, __VA_ARGS__)
#define LOG_STREAM_ERROR(...) LOG_STREAM(error, __VA_ARGS__)
#define LOG_STREAM_DEBUG(...) LOG_STREAM(debug, __VA_ARGS__)
#define LOG_STREAM_WARN(...)  LOG_STREAM(warn, __VA_ARGS__)

// logger.cpp
// #include "logger.h"

#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

void Logger::init_file(const std::string& log_file, size_t max_size, size_t max_files)
{
	auto file_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(log_file, max_size, max_files);
	spdlog::set_default_logger(std::make_shared<spdlog::logger>("file_logger", file_sink));
	spdlog::set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%l] %v");
}

void Logger::init_console()
{
	auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
	spdlog::set_default_logger(std::make_shared<spdlog::logger>("console_logger", console_sink));
	spdlog::set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%l] %v");
}

void Logger::shutdown()
{
	spdlog::shutdown();
}

int main(int argc, char* argv[])
{
	Logger::init_file("logs/app.log", 10 * 1024 * 1024, 5);	 // 10 MB max size, keep 5 files

	LOG_STREAM_INFO("Logger initialized successfully.");
	LOG_STREAM_DEBUG("This is a debug message.");
	LOG_STREAM_WARN("This is a warning message.");
	LOG_STREAM_ERROR("This is an error message.");

	Logger::shutdown();
	return 0;
}