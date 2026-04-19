#include "common/logger.hpp"

#include <memory>

#include <spdlog/async.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>

void Logger::init_file(const std::string& log_file, size_t max_size, size_t max_files)
{
	auto file_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(log_file, max_size, max_files);
	spdlog::set_default_logger(std::make_shared<spdlog::logger>("file_logger", file_sink));
	spdlog::set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%l] %v");
}

void Logger::init_console()
{
	spdlog::init_thread_pool(8192, 2);

	auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
	auto logger = std::make_shared<spdlog::async_logger>(
			"async_logger",
			console_sink,
			spdlog::thread_pool(),
			spdlog::async_overflow_policy::block);

	spdlog::register_logger(logger);
	spdlog::set_default_logger(logger);
	spdlog::set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%l] %v");
}

void Logger::shutdown()
{
	spdlog::shutdown();
}
