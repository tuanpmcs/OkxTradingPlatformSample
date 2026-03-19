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

#define LOG_STREAM_INFO(...)  LOG_STREAM(info, __VA_ARGS__)
#define LOG_STREAM_ERROR(...) LOG_STREAM(error, __VA_ARGS__)
#define LOG_STREAM_DEBUG(...) LOG_STREAM(debug, __VA_ARGS__)
#define LOG_STREAM_WARN(...)  LOG_STREAM(warn, __VA_ARGS__)

// -------- logger.cpp --------
// #include "logger.h"

#include <spdlog/sinks/rotating_file_sink.h>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>
#include <spdlog/async.h>

void Logger::init_file(const std::string& log_file, size_t max_size, size_t max_files)
{
	auto file_sink = std::make_shared<spdlog::sinks::rotating_file_sink_mt>(log_file, max_size, max_files);
	spdlog::set_default_logger(std::make_shared<spdlog::logger>("file_logger", file_sink));
	spdlog::set_pattern("[%Y-%m-%d %H:%M:%S.%e] [%l] %v");
}

void Logger::init_console()
{
	spdlog::init_thread_pool(
		8192, // queue size
		2     // number of threads
	);

	auto console_sink = std::make_shared<spdlog::sinks::stdout_color_sink_mt>();
	auto logger = std::make_shared<spdlog::async_logger>(
        "async_logger",
        console_sink,
		spdlog::thread_pool(),
		spdlog::async_overflow_policy::block
		);

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
	std::string symbol;
	std::string channel;
};

struct WebSocketEndpoint
{
	std::string ws_url;
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

	sub.symbol = get_required<std::string>(node, "symbol");
	sub.channel = get_required<std::string>(node, "channel");

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

#include <boost/url.hpp>

int main(int argc, char* argv[])
{
	bool bench_main_mode = false;
	for (int i = 1; i < argc; ++i)
	{
		if (std::string_view(argv[i]) == "--bench-main")
		{
			bench_main_mode = true;
		}
	}

	Logger::init_console();

	std::string config_content = R"(
exchange: "okx"

network:
    forced_ip: ""
    reconnect_ms: 100
    ping_interval_ms: 100
    stale_timeout_ms: 100
    pong_timeout_ms: 100

websocket_endpoint:
    public_endpoint:
        ws_url: "wss://wspap.okx.com:8443/ws/v5/public"
        subscriptions:
            - symbol: "BTC-USDT"
              channel: "tickers"

    business_endpoint:
        ws_url: "wss://wspap.okx.com:8443/ws/v5/business"
        subscriptions:
            - symbol: "BTC-USDT"
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

	json args = json::array();
	for (const auto& sub : subs)
	{
		args.push_back({
				{"channel", sub.channel},
				{"instId", sub.symbol},
		});
	}

	json subscribe_msg = {
			{"op", "subscribe"},
			{"args", args},
	};

	if (bench_main_mode)
	{
		(void)subscribe_msg;
		return 0;
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

	auto write_result = tls_client.write(subscribe_msg.dump(), okx_config.network.reconnect_ms);
	if (!write_result.ok())
	{
		LOG_STREAM_ERROR("Failed to send subscribe message: " << write_result.message);
		return 1;
	}

	LOG_STREAM_INFO("Subscribed. Streaming messages...");

	using clock = std::chrono::steady_clock;
	const auto ping_interval = std::chrono::milliseconds(okx_config.network.ping_interval_ms);
	const auto pong_timeout = std::chrono::milliseconds(okx_config.network.pong_timeout_ms);

	auto last_rx_time = clock::now();
	auto last_ping_time = clock::time_point::min();
	bool waiting_pong = false;

	while (tls_client.is_open())
	{
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
	}

	LOG_STREAM_INFO("Logger initialized successfully.");

	return 0;
}
