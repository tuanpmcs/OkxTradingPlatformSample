#pragma once

#include <cstddef>
#include <sstream>
#include <string>

#include <spdlog/spdlog.h>

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

#define ENABLE_STREAM_LOGS 1

#ifndef ENABLE_STREAM_LOGS
#define ENABLE_STREAM_LOGS 0
#endif

#if ENABLE_STREAM_LOGS
#define LOG_STREAM_INFO(...)  LOG_STREAM(info, __VA_ARGS__)
#define LOG_STREAM_ERROR(...) LOG_STREAM(error, __VA_ARGS__)
#define LOG_STREAM_DEBUG(...) LOG_STREAM(debug, __VA_ARGS__)
#define LOG_STREAM_WARN(...)  LOG_STREAM(warn, __VA_ARGS__)
#else
#define LOG_STREAM_INFO(...)
#define LOG_STREAM_ERROR(...)
#define LOG_STREAM_DEBUG(...)
#define LOG_STREAM_WARN(...)
#endif
