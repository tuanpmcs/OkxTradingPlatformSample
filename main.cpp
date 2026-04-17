#include "market_data.grpc.pb.h"

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
#include <grpcpp/grpcpp.h>
#include <simdjson.h>
#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <deque>
#include <fstream>
#include <functional>
#include <iostream>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <sstream>
#include <stdexcept>
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

std::atomic<bool> g_should_stop{false};

extern "C" void handle_stop_signal(int)
{
	g_should_stop.store(true);
}

std::string json_escape(std::string_view input)
{
	std::string escaped;
	escaped.reserve(input.size() + 8);
	for (const char ch : input)
	{
		switch (ch)
		{
		case '\"':
			escaped += "\\\"";
			break;
		case '\\':
			escaped += "\\\\";
			break;
		case '\b':
			escaped += "\\b";
			break;
		case '\f':
			escaped += "\\f";
			break;
		case '\n':
			escaped += "\\n";
			break;
		case '\r':
			escaped += "\\r";
			break;
		case '\t':
			escaped += "\\t";
			break;
		default:
			escaped += ch;
			break;
		}
	}
	return escaped;
}

struct ParsedTickPayload
{
	double							   price{0.0};
	std::string						   raw_json;
	std::map<std::string, std::string> fields;
};

std::optional<std::string> get_string_field(const simdjson::dom::element& obj, const char* key)
{
	auto value = obj[key].get_string();
	if (value.error())
	{
		return std::nullopt;
	}
	return std::string(value.value_unsafe());
}

void put_if_present(std::map<std::string, std::string>& fields,
					const simdjson::dom::element&		obj,
					const char*							key)
{
	const auto value = get_string_field(obj, key);
	if (value.has_value() && !value->empty())
	{
		fields[key] = *value;
	}
}

std::optional<double> find_price_from_fields(const std::map<std::string, std::string>& fields)
{
	for (const char* key : {"last", "lastPr", "px", "price", "markPx", "bidPx", "askPx"})
	{
		const auto it = fields.find(key);
		if (it == fields.end())
		{
			continue;
		}

		try
		{
			const auto parsed_number = std::stod(it->second);
			if (parsed_number > 0.0)
			{
				return parsed_number;
			}
		}
		catch (const std::exception&)
		{
		}
	}

	const auto bid_it = fields.find("bidPx");
	const auto ask_it = fields.find("askPx");
	if (bid_it != fields.end() && ask_it != fields.end())
	{
		try
		{
			const auto bid = std::stod(bid_it->second);
			const auto ask = std::stod(ask_it->second);
			if (bid > 0.0 && ask > 0.0)
			{
				return 0.5 * (bid + ask);
			}
		}
		catch (const std::exception&)
		{
		}
	}
	return std::nullopt;
}

std::optional<std::int64_t> parse_int64_field(const std::map<std::string, std::string>& fields, const char* key)
{
	const auto it = fields.find(key);
	if (it == fields.end() || it->second.empty())
	{
		return std::nullopt;
	}

	try
	{
		std::size_t pos = 0;
		const auto	value = std::stoll(it->second, &pos);
		if (pos == it->second.size())
		{
			return value;
		}
	}
	catch (const std::exception&)
	{
	}
	return std::nullopt;
}

void copy_okx_book_top(std::map<std::string, std::string>& fields, const simdjson::dom::element& row)
{
	auto bids = row["bids"].get_array();
	if (!bids.error() && bids.value_unsafe().size() > 0)
	{
		auto bid0 = bids.value_unsafe().at(0).get_array();
		if (!bid0.error() && bid0.value_unsafe().size() > 1)
		{
			auto px = bid0.value_unsafe().at(0).get_string();
			auto sz = bid0.value_unsafe().at(1).get_string();
			if (!px.error())
			{
				fields["bidPx"] = std::string(px.value_unsafe());
			}
			if (!sz.error())
			{
				fields["bidSz"] = std::string(sz.value_unsafe());
			}
		}
	}

	auto asks = row["asks"].get_array();
	if (!asks.error() && asks.value_unsafe().size() > 0)
	{
		auto ask0 = asks.value_unsafe().at(0).get_array();
		if (!ask0.error() && ask0.value_unsafe().size() > 1)
		{
			auto px = ask0.value_unsafe().at(0).get_string();
			auto sz = ask0.value_unsafe().at(1).get_string();
			if (!px.error())
			{
				fields["askPx"] = std::string(px.value_unsafe());
			}
			if (!sz.error())
			{
				fields["askSz"] = std::string(sz.value_unsafe());
			}
		}
	}
}

std::vector<ParsedTickPayload> parse_okx_tick_payloads(const std::string& payload)
{
	thread_local simdjson::dom::parser parser;
	auto							   parsed = parser.parse(payload);
	if (parsed.error())
	{
		return {};
	}

	std::map<std::string, std::string> arg_fields;

	auto arg = parsed["arg"];
	if (!arg.error())
	{
		const auto arg_elem = arg.value_unsafe();
		put_if_present(arg_fields, arg_elem, "channel");
		put_if_present(arg_fields, arg_elem, "instId");
		put_if_present(arg_fields, arg_elem, "instType");
	}

	auto data = parsed["data"].get_array();
	if (data.error() || data.value_unsafe().size() == 0)
	{
		return {};
	}

	std::vector<ParsedTickPayload> ticks;
	for (simdjson::dom::element first : data.value_unsafe())
	{
		ParsedTickPayload result;
		result.raw_json = payload;
		result.fields = arg_fields;

		for (const char* key : {"instId",
								"ts",
								"tradeId",
								"side",
								"seqId",
								"px",
								"sz",
								"last",
								"lastSz",
								"lastPr",
								"bidPx",
								"bidSz",
								"askPx",
								"askSz",
								"markPx",
								"indexPx",
								"open24h",
								"high24h",
								"low24h",
								"vol24h",
								"volCcy24h"})
		{
			put_if_present(result.fields, first, key);
		}

		copy_okx_book_top(result.fields, first);

		const auto price = find_price_from_fields(result.fields);
		if (!price)
		{
			continue;
		}

		result.price = *price;
		ticks.push_back(std::move(result));
	}

	return ticks;
}

std::optional<ParsedTickPayload> parse_okx_tick_payload(const std::string& payload)
{
	auto ticks = parse_okx_tick_payloads(payload);
	if (ticks.empty())
	{
		return std::nullopt;
	}
	return std::move(ticks.front());
}

// -------- logger.h --------
#include <string>

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

#define ENABLE_STREAM_LOGS 0

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
// -------- logger.cpp --------
// #include "logger.h"

#include <spdlog/async.h>
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
	spdlog::init_thread_pool(
			8192,  // queue size
			2	   // number of threads
	);

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

// -------- config.h --------
#include <optional>
#include <string>
#include <string_view>

#include <yaml-cpp/yaml.h>

class YamlConfig
{
public:
	static YAML::Node load(const std::string& config_file);
	static YAML::Node load_from_string(const std::string_view& config_content);
};

// -------- config.cpp --------
// #include "config.h"

YAML::Node YamlConfig::load(const std::string& config_file)
{
	try
	{
		return YAML::LoadFile(config_file);
	}
	catch (const YAML::Exception& e)
	{
		LOG_STREAM_ERROR("Failed to load config file: " << e.what());
		return YAML::Node();
	}
}

YAML::Node YamlConfig::load_from_string(const std::string_view& config_content)
{
	try
	{
		return YAML::Load(std::string(config_content));
	}
	catch (const YAML::Exception& e)
	{
		LOG_STREAM_ERROR("Failed to load config from string: " << e.what());
		return YAML::Node();
	}
}

struct Subscription
{
	std::map<std::string, std::string> args;
};

std::string build_subscribe_message_json(const std::vector<Subscription>& subs)
{
	std::string message = R"({"op":"subscribe","args":[)";
	for (size_t i = 0; i < subs.size(); ++i)
	{
		if (i > 0)
		{
			message += ",";
		}
		message += "{";
		size_t field_index = 0;
		for (const auto& [key, value] : subs[i].args)
		{
			if (field_index > 0)
			{
				message += ",";
			}
			message += "\"";
			message += json_escape(key);
			message += "\":\"";
			message += json_escape(value);
			message += "\"";
			++field_index;
		}
		message += "}";
	}
	message += "]}";
	return message;
}

struct WebSocketEndpoint
{
	std::string				  ws_url;
	std::vector<Subscription> subscriptions;
};

struct NetworkConfig
{
	std::optional<std::string> forced_ip;

	int reconnect_ms;
	int ping_interval_ms;
	int stale_timeout_ms;
	int pong_timeout_ms;
};

struct WebSocketEndpointConfig
{
	std::optional<WebSocketEndpoint> public_endpoint;
	std::optional<WebSocketEndpoint> business_endpoint;
};

struct OkxConfig
{
	std::string				exchange;
	NetworkConfig			network;
	WebSocketEndpointConfig websocket_endpoint;
};

template <typename T>
std::optional<T> get_optional(const YAML::Node& node, const std::string& key)
{
	const auto child = node[key];
	if (!child)
	{
		return std::nullopt;
	}

	try
	{
		return child.as<T>();
	}
	catch (const YAML::Exception& e)
	{
		LOG_STREAM_ERROR("Failed to parse config key '" << key << "': " << e.what());
		return std::nullopt;
	}
}

template <typename T>
T get_required(const YAML::Node& node, const std::string& key)
{
	const auto child = node[key];
	if (!child)
	{
		throw std::runtime_error("Missing required config key: " + key);
	}

	try
	{
		return child.as<T>();
	}
	catch (const YAML::Exception& e)
	{
		throw std::runtime_error("Failed to parse required config key '" + key + "': " + e.what());
	}
}

Subscription parse_subscription(const YAML::Node& node)
{
	Subscription sub;
	if (!node.IsMap())
	{
		throw std::runtime_error("Subscription entry must be a map/object.");
	}

	for (const auto& item : node)
	{
		const auto key = item.first.as<std::string>();
		const auto value = item.second.as<std::string>();
		sub.args[key] = value;
	}

	if (sub.args.find("channel") == sub.args.end())
	{
		throw std::runtime_error("Subscription entry is missing required key: channel");
	}

	return sub;
}

WebSocketEndpoint parse_websocket_endpoint(const YAML::Node& node)
{
	WebSocketEndpoint ep;

	ep.ws_url = get_required<std::string>(node, "ws_url");

	if (const auto subs_node = node["subscriptions"])
	{
		for (const auto& sub_node : subs_node)
		{
			ep.subscriptions.push_back(parse_subscription(sub_node));
		}
	}

	return ep;
}

NetworkConfig parse_network_config(const YAML::Node& node)
{
	NetworkConfig cfg;

	cfg.forced_ip = get_optional<std::string>(node, "forced_ip").value_or("");
	cfg.reconnect_ms = get_optional<int>(node, "reconnect_ms").value_or(100);
	cfg.ping_interval_ms = get_optional<int>(node, "ping_interval_ms").value_or(100);
	cfg.stale_timeout_ms = get_optional<int>(node, "stale_timeout_ms").value_or(100);
	cfg.pong_timeout_ms = get_optional<int>(node, "pong_timeout_ms").value_or(100);

	return cfg;
}

WebSocketEndpointConfig parse_websocket_endpoint_config(const YAML::Node& node)
{
	WebSocketEndpointConfig cfg;

	if (const auto public_node = node["public_endpoint"])
	{
		cfg.public_endpoint = parse_websocket_endpoint(public_node);
	}

	if (const auto business_node = node["business_endpoint"])
	{
		cfg.business_endpoint = parse_websocket_endpoint(business_node);
	}

	return cfg;
}

OkxConfig from(const YAML::Node& root)
{
	try
	{
		OkxConfig config;

		config.exchange = get_required<std::string>(root, "exchange");
		config.network = parse_network_config(root["network"]);
		config.websocket_endpoint = parse_websocket_endpoint_config(root["websocket_endpoint"]);
		return config;
	}
	catch (const YAML::Exception& e)
	{
		throw std::runtime_error(std::string("Failed to parse OkxConfig: ") + e.what());
	}
}

// -------- tls_client.h --------
#include <boost/asio.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast.hpp>
#include <boost/beast/ssl.hpp>
#include <boost/beast/websocket.hpp>

#include <memory>
#include <string>

namespace ssl = boost::asio::ssl;
namespace beast = boost::beast;
namespace websocket = boost::beast::websocket;

class TlsClient
{
public:
	enum class Status
	{
		Success,
		HandshakeFailed,
		ConnectionFailed,
		ReadFailed,
		WriteFailed,
		Timeout,
		Closed,
		UnknownError
	};

	struct [[nodiscard]] Result
	{
		Status		status{Status::UnknownError};
		std::string message;

		bool ok() const noexcept
		{
			return status == Status::Success;
		}
	};

public:
	TlsClient();
	virtual ~TlsClient();

	[[nodiscard]] Result connect(const std::string& host,
								 const std::string& port,
								 const std::string& target,
								 int				timeout_ms);

	[[nodiscard]] Result handshake(const std::string& host, int timeout_ms);

	[[nodiscard]] Result write(const std::string& data, int timeout_ms);
	[[nodiscard]] Result read(std::string& response, int timeout_ms);
	[[nodiscard]] Result close(int timeout_ms);

	[[nodiscard]] bool is_open() const noexcept;

private:
	using tcp = boost::asio::ip::tcp;

	using WebSocketStream =
			websocket::stream<beast::ssl_stream<beast::tcp_stream>>;

private:
	static std::string make_error_message(const std::string&			   prefix,
										  const boost::system::error_code& ec)
	{
		std::ostringstream oss;
		oss << prefix << ": [" << ec.value() << "] " << ec.message();
		return oss.str();
	}

	static bool is_timeout_error(const boost::system::error_code& ec) noexcept
	{
		return ec == boost::asio::error::timed_out
				|| ec == beast::error::timeout;
	}

private:
	boost::asio::io_context			 _io_context;
	ssl::context					 _ssl_context;
	tcp::resolver					 _resolver;
	std::unique_ptr<WebSocketStream> _ws_stream;

	std::string _host;
	std::string _port;
	std::string _target;
};

// ----- tls_client.cpp -----
// #include "tls_client.h"
TlsClient::TlsClient()
	  : _ssl_context(ssl::context::tls_client), _resolver(_io_context)
{
	_ssl_context.set_default_verify_paths();
	_ssl_context.set_verify_mode(ssl::verify_peer);

	_ws_stream = std::make_unique<WebSocketStream>(_io_context, _ssl_context);

	_ws_stream->set_option(
			websocket::stream_base::timeout::suggested(beast::role_type::client));

	_ws_stream->set_option(
			websocket::stream_base::decorator(
					[](websocket::request_type& req) {
						req.set(
								boost::beast::http::field::user_agent,
								std::string(BOOST_BEAST_VERSION_STRING) + " tls-client");
					}));
}

TlsClient::~TlsClient()
{
	boost::system::error_code ec;

	if (_ws_stream && _ws_stream->is_open())
	{
		_ws_stream->close(websocket::close_code::normal, ec);
	}
}

TlsClient::Result TlsClient::connect(const std::string& host,
									 const std::string& port,
									 const std::string& target,
									 int				timeout_ms)
{
	try
	{
		_host = host;
		_port = port;
		_target = target;

		if (!_ws_stream)
		{
			_ws_stream = std::make_unique<WebSocketStream>(_io_context, _ssl_context);
		}

		boost::system::error_code ec;

		auto results = _resolver.resolve(_host, _port, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Resolve timeout", ec)};
			}
			return {Status::ConnectionFailed, make_error_message("Resolve failed", ec)};
		}

		auto& tcp_stream = beast::get_lowest_layer(*_ws_stream);
		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		tcp_stream.connect(results, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("TCP connect timeout", ec)};
			}
			return {Status::ConnectionFailed, make_error_message("TCP connect failed", ec)};
		}

		if (!SSL_set_tlsext_host_name(
					_ws_stream->next_layer().native_handle(),
					_host.c_str()))
		{
			boost::system::error_code ssl_ec{
					static_cast<int>(::ERR_get_error()),
					boost::asio::error::get_ssl_category()};

			return {Status::HandshakeFailed, make_error_message("SNI setup failed", ssl_ec)};
		}

		_ws_stream->next_layer().handshake(ssl::stream_base::client, ec);
		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("TLS handshake timeout", ec)};
			}
			return {Status::HandshakeFailed, make_error_message("TLS handshake failed", ec)};
		}

		tcp_stream.expires_never();

		return {Status::Success, "TCP/TLS connect success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("connect exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::handshake(const std::string& host, int timeout_ms)
{
	try
	{
		if (!_ws_stream)
		{
			return {Status::HandshakeFailed, "WebSocket stream is not initialized"};
		}

		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();

		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		const std::string effective_host = host.empty() ? _host : host;
		_ws_stream->handshake(effective_host, _target, ec);

		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("WebSocket handshake timeout", ec)};
			}
			return {Status::HandshakeFailed, make_error_message("WebSocket handshake failed", ec)};
		}

		tcp_stream.expires_never();

		return {Status::Success, "WebSocket handshake success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("handshake exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::write(const std::string& data, int timeout_ms)
{
	try
	{
		if (!_ws_stream || !_ws_stream->is_open())
		{
			return {Status::WriteFailed, "WebSocket is not open"};
		}

		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();

		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		_ws_stream->text(true);
		_ws_stream->write(boost::asio::buffer(data), ec);

		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Write timeout", ec)};
			}
			return {Status::WriteFailed, make_error_message("Write failed", ec)};
		}

		tcp_stream.expires_never();

		return {Status::Success, "Write success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("write exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::read(std::string& response, int timeout_ms)
{
	try
	{
		response.clear();

		if (!_ws_stream || !_ws_stream->is_open())
		{
			return {Status::ReadFailed, "WebSocket is not open"};
		}

		beast::flat_buffer		  buffer;
		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();

		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		_ws_stream->read(buffer, ec);

		if (ec == websocket::error::closed)
		{
			return {Status::Closed, "WebSocket closed by peer"};
		}

		if (ec)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Read timeout", ec)};
			}
			return {Status::ReadFailed, make_error_message("Read failed", ec)};
		}

		tcp_stream.expires_never();

		response = beast::buffers_to_string(buffer.data());
		return {Status::Success, "Read success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("read exception: ") + e.what()};
	}
}

TlsClient::Result TlsClient::close(int timeout_ms)
{
	try
	{
		if (!_ws_stream)
		{
			return {Status::Closed, "WebSocket stream is not initialized"};
		}

		if (!_ws_stream->is_open())
		{
			return {Status::Closed, "WebSocket already closed"};
		}

		boost::system::error_code ec;
		auto&					  tcp_stream = _ws_stream->next_layer().next_layer();

		tcp_stream.expires_after(std::chrono::milliseconds(timeout_ms));

		_ws_stream->close(websocket::close_code::normal, ec);

		if (ec && ec != websocket::error::closed)
		{
			if (is_timeout_error(ec))
			{
				return {Status::Timeout, make_error_message("Close timeout", ec)};
			}
			return {Status::UnknownError, make_error_message("Close failed", ec)};
		}

		tcp_stream.expires_never();

		return {Status::Success, "Close success"};
	}
	catch (const std::exception& e)
	{
		return {Status::UnknownError, std::string("close exception: ") + e.what()};
	}
}

bool TlsClient::is_open() const noexcept
{
	return _ws_stream && _ws_stream->is_open();
}

struct TickEvent
{
	std::int64_t					   ts_ms{0};
	double							   price{0.0};
	double							   change{0.0};
	std::string						   source;
	std::string						   raw_json;
	std::map<std::string, std::string> fields;
	std::vector<std::string>		   changed_fields;
};

std::optional<double> parse_double_field(const std::map<std::string, std::string>& fields, const char* key)
{
	const auto it = fields.find(key);
	if (it == fields.end() || it->second.empty())
	{
		return std::nullopt;
	}

	try
	{
		const double v = std::stod(it->second);
		if (std::isfinite(v))
		{
			return v;
		}
	}
	catch (const std::exception&)
	{
	}
	return std::nullopt;
}

std::string to_fixed_string(double value, int precision = 10)
{
	std::ostringstream oss;
	oss.setf(std::ios::fixed);
	oss.precision(precision);
	oss << value;
	return oss.str();
}

std::string csv_escape(const std::string& input)
{
	bool needs_quotes = false;
	for (char c : input)
	{
		if (c == ',' || c == '"' || c == '\n' || c == '\r')
		{
			needs_quotes = true;
			break;
		}
	}

	if (!needs_quotes)
	{
		return input;
	}

	std::string out;
	out.reserve(input.size() + 4);
	out.push_back('"');
	for (char c : input)
	{
		if (c == '"')
		{
			out.push_back('"');
		}
		out.push_back(c);
	}
	out.push_back('"');
	return out;
}

#include <boost/multiprecision/cpp_dec_float.hpp>

using double_type = boost::multiprecision::number<
	boost::multiprecision::cpp_dec_float<8>
	, boost::multiprecision::et_off
>;
struct Book {
    double price{};
    double quantity{};
    std::uint32_t deprecated_value{}; // or remove this field entirely
    std::uint32_t order_count{};
};

struct Books {
    std::vector<Book> bids;
    std::vector<Book> asks;

    std::uint64_t exchange_ts_ms{};
    std::uint64_t recv_ts_ms{};
    std::uint64_t sequence_id{};
    std::string instrument_id;
};

struct Books5 {
    std::array<Book, 5> bids;
    std::array<Book, 5> asks;

    std::uint64_t exchange_ts_ms{};
    std::uint64_t recv_ts_ms{};
    std::uint64_t sequence_id{};
    std::string instrument_id;
};

struct Trade {
    std::string instrument_id;
    std::string exchange_trade_id;
    double_type price{};
    double_type size{};
    std::string side;
    std::uint64_t exchange_ts_ms{};
    std::uint64_t recv_ts_ms{};
    std::uint32_t trade_count{};
    std::string exchange;
    std::uint64_t sequence_id{};
};

using Trades = std::vector<Trade>;

template <typename T>
std::string to_json(const T& obj)
{
	std::string json = simdjson::to_json(obj);
	return json;
}

template <typename T>
std::optional<T> from_json(const std::string& json_str)
{	T obj;
	auto result = simdjson::from(json_str, obj);
	if (result.error())
	{		return std::nullopt;
	}
	return obj;
}

class CsvTickWriter
{
public:
	explicit CsvTickWriter(const std::string& path)
	{
		_out.open(path, std::ios::out | std::ios::trunc);
		if (!_out.is_open())
		{
			throw std::runtime_error("Failed to open csv output: " + path);
		}
		write_header();
	}

	void write(const TickEvent& tick)
	{
		const auto getv = [&](const char* key) -> std::string {
			const auto it = tick.fields.find(key);
			return (it == tick.fields.end()) ? "" : it->second;
		};

		double bid_px = 0.0;
		double ask_px = 0.0;
		if (const auto v = parse_double_field(tick.fields, "bidPx"); v.has_value())
		{
			bid_px = *v;
		}
		if (const auto v = parse_double_field(tick.fields, "askPx"); v.has_value())
		{
			ask_px = *v;
		}
		double spread = 0.0;
		double mid_price = 0.0;
		if (bid_px > 0.0 && ask_px > bid_px)
		{
			spread = ask_px - bid_px;
			mid_price = 0.5 * (bid_px + ask_px);
		}

		_out << tick.ts_ms << ','
			 << to_fixed_string(tick.price, 8) << ','
			 << csv_escape(infer_event_type(getv("channel"))) << ','
			 << csv_escape(getv("channel")) << ','
			 << csv_escape(getv("instId")) << ','
			 << csv_escape(getv("side")) << ','
			 << csv_escape(getv("sz")) << ','
			 << csv_escape(getv("bidPx")) << ','
			 << csv_escape(getv("askPx")) << ','
			 << csv_escape(getv("bidSz")) << ','
			 << csv_escape(getv("askSz")) << ','
			 << (spread > 0.0 ? to_fixed_string(spread, 8) : "") << ','
			 << (mid_price > 0.0 ? to_fixed_string(mid_price, 8) : "") << ','
			 << csv_escape(getv("mid_price")) << ','
			 << csv_escape(getv("spread")) << ','
			 << csv_escape(getv("imbalance")) << ','
			 << csv_escape(getv("trade_volume")) << ','
			 << csv_escape(getv("trade_imbalance")) << ','
			 << csv_escape(tick.source) << '\n';
		_out.flush();
	}

private:
	static std::string infer_event_type(const std::string& channel)
	{
		return channel.find("trade") != std::string::npos ? "trade" : "order_book";
	}

	void write_header()
	{
		_out << "ts,price,event_type,channel,instId,trade_side,trade_size,bidPx,askPx,bidSz,askSz,"
				"spread,mid_price,mid_price_feat,spread_feat,imbalance_feat,trade_volume_feat,"
				"trade_imbalance_feat,source\n";
		_out.flush();
	}

private:
	std::ofstream _out;
};

class MarketFeatureEngine
{
public:
	explicit MarketFeatureEngine(std::int64_t trade_window_ms = 5000)
		  : _trade_window_ms(trade_window_ms)
	{
	}

	void enrich(TickEvent& tick)
	{
		update_book_state(tick.fields);
		update_trade_buffer(tick);
		prune_old_trades(tick.ts_ms);

		auto mid = compute_mid_price();
		auto spread = compute_spread();
		auto imb = compute_imbalance();
		double trade_volume = 0.0;
		double trade_imbalance = 0.0;

		for (const auto& t : _trades)
		{
			trade_volume += t.abs_size;
			trade_imbalance += t.signed_size;
		}

		if (mid.has_value())
		{
			tick.fields["mid_price"] = to_fixed_string(*mid);
		}
		if (spread.has_value())
		{
			tick.fields["spread"] = to_fixed_string(*spread);
		}
		if (imb.has_value())
		{
			tick.fields["imbalance"] = to_fixed_string(*imb);
		}
		tick.fields["trade_volume"] = to_fixed_string(trade_volume);
		tick.fields["trade_imbalance"] = to_fixed_string(trade_imbalance);
	}

private:
	struct TradeSample
	{
		std::int64_t ts_ms{0};
		double		 abs_size{0.0};
		double		 signed_size{0.0};
	};

	void update_book_state(const std::map<std::string, std::string>& fields)
	{
		if (auto bid_px = parse_double_field(fields, "bidPx"); bid_px.has_value() && *bid_px > 0.0)
		{
			_bid_px = *bid_px;
		}
		if (auto ask_px = parse_double_field(fields, "askPx"); ask_px.has_value() && *ask_px > 0.0)
		{
			_ask_px = *ask_px;
		}
		if (auto bid_sz = parse_double_field(fields, "bidSz"); bid_sz.has_value() && *bid_sz >= 0.0)
		{
			_bid_sz = *bid_sz;
		}
		if (auto ask_sz = parse_double_field(fields, "askSz"); ask_sz.has_value() && *ask_sz >= 0.0)
		{
			_ask_sz = *ask_sz;
		}
	}

	void update_trade_buffer(const TickEvent& tick)
	{
		const auto channel_it = tick.fields.find("channel");
		if (channel_it == tick.fields.end())
		{
			return;
		}

		const std::string& channel = channel_it->second;
		if (channel.find("trade") == std::string::npos)
		{
			return;
		}

		const auto size = parse_double_field(tick.fields, "sz");
		if (!size.has_value() || *size <= 0.0)
		{
			return;
		}

		double sign = 0.0;
		const auto side_it = tick.fields.find("side");
		if (side_it != tick.fields.end())
		{
			if (side_it->second == "buy")
			{
				sign = 1.0;
			}
			else if (side_it->second == "sell")
			{
				sign = -1.0;
			}
		}

		TradeSample sample;
		sample.ts_ms = tick.ts_ms;
		sample.abs_size = *size;
		sample.signed_size = sign * (*size);
		_trades.push_back(sample);
	}

	void prune_old_trades(std::int64_t now_ms)
	{
		const std::int64_t threshold = now_ms - _trade_window_ms;
		while (!_trades.empty() && _trades.front().ts_ms < threshold)
		{
			_trades.pop_front();
		}
	}

	std::optional<double> compute_mid_price() const
	{
		if (_bid_px.has_value() && _ask_px.has_value() && *_bid_px > 0.0 && *_ask_px > *_bid_px)
		{
			return 0.5 * (*_bid_px + *_ask_px);
		}
		return std::nullopt;
	}

	std::optional<double> compute_spread() const
	{
		if (_bid_px.has_value() && _ask_px.has_value() && *_bid_px > 0.0 && *_ask_px > *_bid_px)
		{
			return *_ask_px - *_bid_px;
		}
		return std::nullopt;
	}

	std::optional<double> compute_imbalance() const
	{
		if (!_bid_sz.has_value() || !_ask_sz.has_value())
		{
			return std::nullopt;
		}
		const double denom = *_bid_sz + *_ask_sz;
		if (denom <= 0.0)
		{
			return std::nullopt;
		}
		return (*_bid_sz - *_ask_sz) / denom;
	}

private:
	std::int64_t			   _trade_window_ms{5000};
	std::optional<double>	   _bid_px;
	std::optional<double>	   _ask_px;
	std::optional<double>	   _bid_sz;
	std::optional<double>	   _ask_sz;
	std::deque<TradeSample>	   _trades;
};

class GrpcTickHub
{
public:
	struct Subscriber
	{
		std::mutex				mutex;
		std::condition_variable cv;
		std::deque<TickEvent>	queue;
		bool					closed{false};

		bool wait_pop(TickEvent& event, std::chrono::milliseconds timeout)
		{
			std::unique_lock<std::mutex> lock(mutex);
			cv.wait_for(lock, timeout, [this]() {
				return closed || !queue.empty();
			});

			if (queue.empty())
			{
				return false;
			}

			event = std::move(queue.front());
			queue.pop_front();
			return true;
		}
	};

public:
	std::shared_ptr<Subscriber> add_subscriber()
	{
		auto						subscriber = std::make_shared<Subscriber>();
		std::lock_guard<std::mutex> lock(_mutex);
		_subscribers.push_back(subscriber);
		return subscriber;
	}

	void remove_subscriber(const std::shared_ptr<Subscriber>& target)
	{
		std::lock_guard<std::mutex> lock(_mutex);
		_subscribers.erase(
				std::remove(_subscribers.begin(), _subscribers.end(), target),
				_subscribers.end());
	}

	void broadcast(const TickEvent& event)
	{
		std::vector<std::shared_ptr<Subscriber>> snapshot;
		{
			std::lock_guard<std::mutex> lock(_mutex);
			snapshot = _subscribers;
		}

		for (auto& subscriber : snapshot)
		{
			{
				std::lock_guard<std::mutex> lock(subscriber->mutex);
				subscriber->queue.push_back(event);
				if (subscriber->queue.size() > 1024)
				{
					subscriber->queue.pop_front();
				}
			}
			subscriber->cv.notify_one();
		}
	}

	void shutdown()
	{
		std::vector<std::shared_ptr<Subscriber>> snapshot;
		{
			std::lock_guard<std::mutex> lock(_mutex);
			snapshot = _subscribers;
			_subscribers.clear();
		}

		for (auto& subscriber : snapshot)
		{
			{
				std::lock_guard<std::mutex> lock(subscriber->mutex);
				subscriber->closed = true;
			}
			subscriber->cv.notify_all();
		}
	}

private:
	std::mutex								 _mutex;
	std::vector<std::shared_ptr<Subscriber>> _subscribers;
};

class MarketDataServiceImpl final : public marketstream::MarketData::Service
{
public:
	explicit MarketDataServiceImpl(GrpcTickHub& hub)
		  : _hub(hub)
	{
	}

	grpc::Status Subscribe(grpc::ServerContext*					   context,
						   const marketstream::SubscribeRequest*   request,
						   grpc::ServerWriter<marketstream::Tick>* writer) override
	{
		auto			  subscriber = _hub.add_subscriber();
		const std::string requested_channel = request ? request->channel() : "";
		const std::string requested_symbol = request ? request->symbol() : "";

		while (!context->IsCancelled())
		{
			TickEvent event;
			if (!subscriber->wait_pop(event, std::chrono::milliseconds(250)))
			{
				continue;
			}

			if (!requested_channel.empty())
			{
				const auto it = event.fields.find("channel");
				if (it == event.fields.end() || it->second != requested_channel)
				{
					continue;
				}
			}

			if (!requested_symbol.empty())
			{
				const auto it = event.fields.find("instId");
				if (it == event.fields.end() || it->second != requested_symbol)
				{
					continue;
				}
			}

			marketstream::Tick tick;
			tick.set_ts(event.ts_ms);
			tick.set_price(event.price);
			tick.set_change(event.change);
			tick.set_source(event.source);
			tick.set_raw_json(event.raw_json);
			for (const auto& [k, v] : event.fields)
			{
				(*tick.mutable_fields())[k] = v;
			}
			for (const auto& field_name : event.changed_fields)
			{
				tick.add_changed_fields(field_name);
			}

			if (!writer->Write(tick))
			{
				break;
			}
		}

		_hub.remove_subscriber(subscriber);
		return grpc::Status::OK;
	}

private:
	GrpcTickHub& _hub;
};

class GrpcServerRuntime
{
public:
	GrpcServerRuntime(MarketDataServiceImpl& service, unsigned short port)
		  : _service(service), _port(port)
	{
	}

	~GrpcServerRuntime()
	{
		stop();
	}

	void start()
	{
		grpc::ServerBuilder builder;
		const std::string	address = "0.0.0.0:" + std::to_string(_port);
		builder.AddListeningPort(address, grpc::InsecureServerCredentials());
		builder.RegisterService(&_service);
		_server = builder.BuildAndStart();
		if (!_server)
		{
			throw std::runtime_error("Failed to start gRPC server on " + address);
		}

		_thread = std::thread([this]() {
			_server->Wait();
		});
	}

	void stop()
	{
		if (_stopped)
		{
			return;
		}
		_stopped = true;

		if (_server)
		{
			_server->Shutdown();
		}

		if (_thread.joinable())
		{
			_thread.join();
		}
	}

private:
	MarketDataServiceImpl&		  _service;
	unsigned short				  _port;
	std::unique_ptr<grpc::Server> _server;
	std::thread					  _thread;
	bool						  _stopped{false};
};

#include <boost/url.hpp>



int main(int argc, char* argv[])
{
	bool		   bench_main_mode = false;
	unsigned short grpc_port = 50051;
	bool		   grpc_enabled = true;
	std::string	   override_symbol;
	std::string	   override_channel;
	std::string	   csv_out_path;
	int			   duration_sec = 0;
	for (int i = 1; i < argc; ++i)
	{
		const std::string_view arg(argv[i]);
		if (arg == "--bench-main")
		{
			bench_main_mode = true;
		}
		else if (arg == "--grpc-port" && i + 1 < argc)
		{
			try
			{
				const int parsed = std::stoi(argv[++i]);
				if (parsed < 1 || parsed > 65535)
				{
					throw std::out_of_range("grpc port out of range");
				}
				grpc_port = static_cast<unsigned short>(parsed);
			}
			catch (const std::exception&)
			{
				std::cerr << "Invalid --grpc-port value. Expected 1..65535.\n";
				return 1;
			}
		}
		else if (arg == "--disable-grpc")
		{
			grpc_enabled = false;
		}
		else if (arg == "--symbol" && i + 1 < argc)
		{
			override_symbol = argv[++i];
		}
		else if (arg == "--channel" && i + 1 < argc)
		{
			override_channel = argv[++i];
		}
		else if (arg == "--csv-out" && i + 1 < argc)
		{
			csv_out_path = argv[++i];
		}
		else if (arg == "--duration-sec" && i + 1 < argc)
		{
			try
			{
				const int parsed = std::stoi(argv[++i]);
				if (parsed < 0)
				{
					throw std::out_of_range("duration must be non-negative");
				}
				duration_sec = parsed;
			}
			catch (const std::exception&)
			{
				std::cerr << "Invalid --duration-sec value. Expected integer >= 0.\n";
				return 1;
			}
		}
	}

	Logger::init_console();
	std::signal(SIGINT, handle_stop_signal);
	std::signal(SIGTERM, handle_stop_signal);

	std::string config_content = R"(
exchange: "okx"

network:
    forced_ip: ""
    reconnect_ms: 5000
    ping_interval_ms: 15000
    stale_timeout_ms: 1000
    pong_timeout_ms: 5000

websocket_endpoint:
    public_endpoint:
        ws_url: "wss://ws.okx.com:8443/ws/v5/public"
        subscriptions:
            - instId: "BTC-USDT"
              channel: "books5"
            - instId: "BTC-USDT"
              channel: "trades"
            - instId: "BTC-USDT"
              channel: "books"

    business_endpoint:
        ws_url: "wss://ws.okx.com:8443/ws/v5/business"
        subscriptions:
            - instId: "BTC-USDT"
              channel: "trades-all"
)";

	LOG_STREAM_INFO("Loading configuration...");

	YAML::Node config = YamlConfig::load_from_string(config_content);
	if (!config)
	{
		LOG_STREAM_ERROR("Failed to load configuration.");
		return 1;
	}

	auto okx_config = from(config);
	if (!override_symbol.empty() || !override_channel.empty())
	{
		if (!okx_config.websocket_endpoint.public_endpoint)
		{
			LOG_STREAM_ERROR("Cannot apply --symbol/--channel because public endpoint is missing.");
			return 1;
		}

		Subscription sub;
		sub.args["instId"] = override_symbol.empty() ? "BTC-USDT" : override_symbol;
		sub.args["channel"] = override_channel.empty() ? "books5" : override_channel;
		okx_config.websocket_endpoint.public_endpoint->subscriptions = {sub};

		LOG_STREAM_INFO("Override subscription: channel=" << sub.args["channel"]
														  << ", instId=" << sub.args["instId"]);
	}

	if (!okx_config.websocket_endpoint.public_endpoint)
	{
		LOG_STREAM_ERROR("Missing public websocket endpoint configuration.");
		return 1;
	}

	auto result = boost::urls::parse_uri(okx_config.websocket_endpoint.public_endpoint->ws_url);
	if (!result)
	{
		LOG_STREAM_ERROR("Failed to parse WebSocket URL: " << result.error().message());
		return 1;
	}

	std::string host = result->host();
	std::string port = result->has_port() ? result->port() : (result->scheme() == "wss" ? "443" : "80");
	const auto	target_view = result->encoded_target();
	std::string target(target_view.data(), target_view.size());
	if (target.empty())
	{
		target = "/";
	}

	const auto& subs = okx_config.websocket_endpoint.public_endpoint->subscriptions;
	if (subs.empty())
	{
		LOG_STREAM_ERROR("No subscriptions configured.");
		return 1;
	}

	const std::string subscribe_msg = build_subscribe_message_json(subs);

	if (bench_main_mode)
	{
		(void)subscribe_msg;
		return 0;
	}

	GrpcTickHub						   grpc_hub;
	MarketDataServiceImpl			   grpc_service(grpc_hub);
	std::unique_ptr<GrpcServerRuntime> grpc_server;
	std::unique_ptr<CsvTickWriter>	   csv_writer;
	if (!csv_out_path.empty())
	{
		try
		{
			csv_writer = std::make_unique<CsvTickWriter>(csv_out_path);
			LOG_STREAM_INFO("CSV export enabled: " << csv_out_path);
		}
		catch (const std::exception& e)
		{
			LOG_STREAM_ERROR("Failed to initialize CSV writer: " << e.what());
			return 1;
		}
	}
	if (grpc_enabled)
	{
		try
		{
			grpc_server = std::make_unique<GrpcServerRuntime>(grpc_service, grpc_port);
			grpc_server->start();
			LOG_STREAM_INFO("gRPC stream server listening on 0.0.0.0:" << grpc_port);
		}
		catch (const std::exception& e)
		{
			LOG_STREAM_ERROR("Failed to start gRPC server: " << e.what());
			return 1;
		}
	}

	TlsClient tls_client;
	auto	  connect_result = tls_client.connect(host, port, target, okx_config.network.reconnect_ms);
	if (!connect_result.ok())
	{
		LOG_STREAM_ERROR("Connection failed: " << connect_result.message);
		return 1;
	}

	auto handshake_result = tls_client.handshake(host, 5000);
	if (!handshake_result.ok())
	{
		LOG_STREAM_ERROR("Handshake failed: " << handshake_result.message);
		return 1;
	}

	auto write_result = tls_client.write(subscribe_msg, okx_config.network.reconnect_ms);
	if (!write_result.ok())
	{
		LOG_STREAM_ERROR("Failed to send subscribe message: " << write_result.message);
		return 1;
	}

	LOG_STREAM_INFO("Subscribed. Streaming messages...");

	using clock = std::chrono::steady_clock;
	const auto ping_interval = std::chrono::milliseconds(okx_config.network.ping_interval_ms);
	const auto pong_timeout = std::chrono::milliseconds(okx_config.network.pong_timeout_ms);
	const auto run_started_at = clock::now();

	auto							   last_rx_time = clock::now();
	auto							   last_ping_time = clock::time_point::min();
	bool							   waiting_pong = false;
	std::optional<double>			   last_price;
	std::map<std::string, std::string> previous_fields;
	MarketFeatureEngine				   feature_engine(5000);

	while (tls_client.is_open() && !g_should_stop.load())
	{
		if (duration_sec > 0)
		{
			const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(clock::now() - run_started_at);
			if (elapsed.count() >= duration_sec)
			{
				LOG_STREAM_INFO("Collection duration reached (" << duration_sec << "s). Stopping.");
				break;
			}
		}

		std::string response;
		auto		read_result = tls_client.read(response, okx_config.network.stale_timeout_ms);
		if (!read_result.ok())
		{
			if (read_result.status == TlsClient::Status::Timeout)
			{
				continue;
			}
			if (read_result.status == TlsClient::Status::Closed)
			{
				LOG_STREAM_WARN("WebSocket closed by peer.");
				break;
			}

			LOG_STREAM_ERROR("Read failed: " << read_result.message);
			return 1;
		}

		LOG_STREAM_INFO("Stream: " << response);

		if (grpc_server || csv_writer)
		{
			const auto parsed_ticks = parse_okx_tick_payloads(response);
			for (const auto& parsed : parsed_ticks)
			{
				const auto now = std::chrono::time_point_cast<std::chrono::milliseconds>(
										 std::chrono::system_clock::now())
										 .time_since_epoch()
										 .count();

				TickEvent tick;
				tick.ts_ms = parse_int64_field(parsed.fields, "ts").value_or(static_cast<std::int64_t>(now));
				tick.price = parsed.price;
				tick.change = last_price.has_value() ? (parsed.price - *last_price) : 0.0;
				tick.source = "cxx-grpc";
				tick.raw_json = parsed.raw_json;
				tick.fields = parsed.fields;
				// feature_engine.enrich(tick);

				// for (const auto& [k, v] : tick.fields)
				// {
				// 	const auto it = previous_fields.find(k);
				// 	if (it == previous_fields.end() || it->second != v)
				// 	{
				// 		tick.changed_fields.push_back(k);
				// 	}
				// }
				// for (const auto& [k, _] : previous_fields)
				// {
				// 	if (tick.fields.find(k) == tick.fields.end())
				// 	{
				// 		tick.changed_fields.push_back(k);
				// 	}
				// }

				// previous_fields = tick.fields;
				// last_price = parsed.price;

				// if (csv_writer)
				// {
				// 	csv_writer->write(tick);
				// }

				if (grpc_server)
				{
					grpc_hub.broadcast(tick);
				}
			}
		}
	}

	if (g_should_stop.load())
	{
		LOG_STREAM_INFO("Stop signal received. Shutting down gracefully...");
	}

	if (tls_client.is_open())
	{
		(void)tls_client.close(2000);
	}

	grpc_hub.shutdown();
	if (grpc_server)
	{
		grpc_server->stop();
	}

	return 0;
}
