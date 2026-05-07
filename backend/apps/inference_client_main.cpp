#include "common/logger.hpp"
#include "inference/prediction_client.hpp"

#include "market_data.grpc.pb.h"

#include <algorithm>
#include <cstdint>
#include <deque>
#include <iostream>
#include <memory>
#include <optional>
#include <string>
#include <string_view>

#include <grpcpp/grpcpp.h>

namespace
{
struct AppConfig
{
	std::string stream_target{"127.0.0.1:50051"};
	std::string predict_target{"127.0.0.1:50061"};
	std::string symbol{"BTC-USDT"};
	std::string channel{"books5"};
	int			horizon_sec{1};
	int			timeout_ms{25};
	std::size_t min_points{32};
	std::size_t max_points{256};
};

bool parse_int(std::string_view raw, int& out)
{
	try
	{
		out = std::stoi(std::string(raw));
		return true;
	}
	catch (const std::exception&)
	{
		return false;
	}
}

bool parse_double(std::string_view raw, double& out)
{
	try
	{
		out = std::stod(std::string(raw));
		return true;
	}
	catch (const std::exception&)
	{
		return false;
	}
}

bool parse_i64(std::string_view raw, std::int64_t& out)
{
	try
	{
		out = static_cast<std::int64_t>(std::stoll(std::string(raw)));
		return true;
	}
	catch (const std::exception&)
	{
		return false;
	}
}

std::optional<double> read_double_field(const google::protobuf::Map<std::string, std::string>& fields, const char* key)
{
	const auto it = fields.find(key);
	if (it == fields.end())
	{
		return std::nullopt;
	}
	double value = 0.0;
	if (!parse_double(it->second, value))
	{
		return std::nullopt;
	}
	return value;
}

std::int64_t read_ts_ms(const marketstream::Tick& tick)
{
	if (tick.ts() > 0)
	{
		return tick.ts();
	}
	const auto it = tick.fields().find("ts");
	if (it == tick.fields().end())
	{
		return 0;
	}
	std::int64_t out = 0;
	if (!parse_i64(it->second, out))
	{
		return 0;
	}
	return out;
}

bool parse_args(int argc, char* argv[], AppConfig& cfg)
{
	for (int i = 1; i < argc; ++i)
	{
		const std::string_view arg(argv[i]);
		auto need_value = [&](const char* name) {
			if (i + 1 >= argc)
			{
				std::cerr << "Missing value for " << name << '\n';
				return false;
			}
			return true;
		};

		if (arg == "--stream-target" && need_value("--stream-target"))
		{
			cfg.stream_target = argv[++i];
		}
		else if (arg == "--predict-target" && need_value("--predict-target"))
		{
			cfg.predict_target = argv[++i];
		}
		else if (arg == "--symbol" && need_value("--symbol"))
		{
			cfg.symbol = argv[++i];
		}
		else if (arg == "--channel" && need_value("--channel"))
		{
			cfg.channel = argv[++i];
		}
		else if (arg == "--horizon-sec" && need_value("--horizon-sec"))
		{
			if (!parse_int(argv[++i], cfg.horizon_sec))
			{
				return false;
			}
		}
		else if (arg == "--timeout-ms" && need_value("--timeout-ms"))
		{
			if (!parse_int(argv[++i], cfg.timeout_ms))
			{
				return false;
			}
		}
		else if (arg == "--min-points" && need_value("--min-points"))
		{
			int v = 0;
			if (!parse_int(argv[++i], v))
			{
				return false;
			}
			cfg.min_points = static_cast<std::size_t>(std::max(8, v));
		}
		else if (arg == "--max-points" && need_value("--max-points"))
		{
			int v = 0;
			if (!parse_int(argv[++i], v))
			{
				return false;
			}
			cfg.max_points = static_cast<std::size_t>(std::max(8, v));
		}
		else
		{
			std::cerr << "Unknown argument: " << arg << '\n';
			return false;
		}
	}
	return true;
}
}  // namespace

int main(int argc, char* argv[])
{
	Logger::init_console();

	AppConfig cfg;
	if (!parse_args(argc, argv, cfg))
	{
		std::cerr << "Usage: inference_client [--stream-target host:port] [--predict-target host:port]\n";
		return 1;
	}

	InferenceRuntimeConfig inf_cfg;
	inf_cfg.mode = InferenceMode::Grpc;
	inf_cfg.grpc_target = cfg.predict_target;
	inf_cfg.model_type = "xgboost";
	inf_cfg.horizon_sec = std::max(1, cfg.horizon_sec);
	inf_cfg.timeout_ms = std::max(1, cfg.timeout_ms);
	inf_cfg.min_points = cfg.min_points;
	inf_cfg.max_points = std::max(cfg.min_points, cfg.max_points);

	auto prediction_client = CreatePredictionClient(inf_cfg);
	if (!prediction_client)
	{
		LOG_STREAM_ERROR("Could not create PredictionClient");
		return 1;
	}

	const auto stream_channel = grpc::CreateChannel(cfg.stream_target, grpc::InsecureChannelCredentials());
	auto	   stream_stub = marketstream::MarketData::NewStub(stream_channel);

	grpc::ClientContext context;
	marketstream::SubscribeRequest request;
	request.set_symbol(cfg.symbol);
	request.set_channel(cfg.channel);
	auto reader = stream_stub->Subscribe(&context, request);

	std::deque<marketstream::PricePoint> points;
	marketstream::Tick tick;
	std::uint64_t tick_count = 0;

	LOG_STREAM_INFO("inference_client started, stream_target=" << cfg.stream_target
															   << ", predict_target=" << cfg.predict_target
															   << ", symbol=" << cfg.symbol << ", channel=" << cfg.channel);

	while (reader->Read(&tick))
	{
		++tick_count;
		if (!(tick.price() > 0.0))
		{
			continue;
		}

		marketstream::PricePoint point;
		point.set_ts(read_ts_ms(tick));
		point.set_price(tick.price());
		point.set_bid_px(read_double_field(tick.fields(), "bidPx").value_or(0.0));
		point.set_ask_px(read_double_field(tick.fields(), "askPx").value_or(0.0));
		point.set_bid_sz(read_double_field(tick.fields(), "bidSz").value_or(0.0));
		point.set_ask_sz(read_double_field(tick.fields(), "askSz").value_or(0.0));
		points.push_back(point);
		if (points.size() > inf_cfg.max_points)
		{
			points.pop_front();
		}

		if (points.size() < inf_cfg.min_points)
		{
			continue;
		}

		const auto prediction = prediction_client->predict(cfg.symbol, cfg.channel, points);
		if (!prediction)
		{
			continue;
		}

		LOG_STREAM_INFO("tick=" << tick_count << ", price=" << tick.price() << ", signal=" << prediction->signal
								<< ", pred_ret=" << prediction->predicted_return
								<< ", pred_price=" << prediction->predicted_price
								<< ", model=" << prediction->model_name);
	}

	const grpc::Status status = reader->Finish();
	if (!status.ok())
	{
		LOG_STREAM_WARN("stream finished with status: " << status.error_message());
		return 1;
	}
	return 0;
}
