#include "config.h"
#include "grpc_stream.h"
#include "logger.h"
#include "market_stream.h"
#include "runtime_stream_handler.h"
#include "subscription.h"
#include "tls_client.h"

#include <boost/url.hpp>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <iostream>
#include <map>
#include <memory>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>

std::atomic<bool> g_should_stop{false};

extern "C" void handle_stop_signal(int)
{
	g_should_stop.store(true);
}

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

	const bool collector_mode = !csv_out_path.empty() && !grpc_enabled;
	const bool csv_mirror_mode = !csv_out_path.empty() && grpc_enabled;
	if (!grpc_enabled && csv_out_path.empty())
	{
		LOG_STREAM_ERROR("--disable-grpc requires --csv-out so the backend has a collector output.");
		return 1;
	}

	if (collector_mode)
	{
		LOG_STREAM_INFO("C++ backend mode: collector (OKX WS -> parse -> rolling features -> CSV export)");
	}
	else if (csv_mirror_mode)
	{
		LOG_STREAM_INFO("C++ backend mode: runtime + CSV mirror (gRPC stream and dataset export)");
	}
	else
	{
		LOG_STREAM_INFO("C++ backend mode: runtime (OKX WS -> parse -> rolling features -> gRPC stream)");
	}

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

	RuntimeSubscriptionRegistry		   runtime_subscriptions;
	runtime_subscriptions.mark_existing(subs);
	GrpcTickHub						   grpc_hub;
	MarketDataServiceImpl			   grpc_service(grpc_hub, &runtime_subscriptions);
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

	const auto flush_runtime_subscriptions = [&]() -> bool {
		auto pending = runtime_subscriptions.take_pending();
		if (pending.empty())
		{
			return true;
		}

		const auto runtime_subscribe_msg = build_subscribe_message_json(pending);
		auto	   runtime_write_result = tls_client.write(runtime_subscribe_msg, okx_config.network.reconnect_ms);
		if (!runtime_write_result.ok())
		{
			LOG_STREAM_ERROR("Failed to send runtime subscribe message: " << runtime_write_result.message);
			return false;
		}
		LOG_STREAM_INFO("Runtime subscription update: " << runtime_subscribe_msg);
		return true;
	};

	using clock = std::chrono::steady_clock;
	const auto ping_interval = std::chrono::milliseconds(okx_config.network.ping_interval_ms);
	const auto pong_timeout = std::chrono::milliseconds(okx_config.network.pong_timeout_ms);
	const auto run_started_at = clock::now();

	auto							   last_rx_time = clock::now();
	auto							   last_ping_time = clock::time_point::min();
	bool							   waiting_pong = false;
	std::optional<double>			   last_price;
	std::map<std::string, std::string> previous_fields;
	const std::string feature_csv_out_path = csv_out_path.empty() ? "" : (csv_out_path + ".features.csv");
	RuntimeStreamHandler runtime_handler(last_price, previous_fields, csv_writer, grpc_server, grpc_hub, feature_csv_out_path);
	MarketEventDispatcher			   event_dispatcher(runtime_handler);

	while (tls_client.is_open() && !g_should_stop.load())
	{
		if (!flush_runtime_subscriptions())
		{
			return 1;
		}

		if (duration_sec > 0)
		{
			const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(clock::now() - run_started_at);
			if (elapsed.count() >= duration_sec)
			{
				LOG_STREAM_INFO((collector_mode ? "Collection" : "Run")
								<< " duration reached (" << duration_sec << "s). Stopping.");
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
			(void)event_dispatcher.dispatch(response);
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
