#include "common/logger.hpp"
#include "inference/prediction_client.hpp"
#include "simulator/paper_simulator.hpp"

#include "market_data.grpc.pb.h"

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <deque>
#include <iostream>
#include <limits>
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
	int			runtime_sec{0};
	int			report_every{50};
	int			horizon_sec{30};
	int			inference_timeout_ms{25};
	std::size_t min_points{32};
	std::size_t max_points{256};

	PaperSimulatorConfig simulator{};
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

bool parse_u64(std::string_view raw, std::uint64_t& out)
{
	try
	{
		const auto v = std::stoull(std::string(raw));
		out = static_cast<std::uint64_t>(v);
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

std::uint64_t read_ts_ms(const marketstream::Tick& tick)
{
	if (tick.ts() > 0)
	{
		return static_cast<std::uint64_t>(tick.ts());
	}
	const auto it = tick.fields().find("ts");
	if (it == tick.fields().end())
	{
		return 0;
	}
	std::uint64_t out = 0;
	if (!parse_u64(it->second, out))
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
		else if (arg == "--runtime-sec" && need_value("--runtime-sec"))
		{
			if (!parse_int(argv[++i], cfg.runtime_sec))
			{
				return false;
			}
		}
		else if (arg == "--report-every" && need_value("--report-every"))
		{
			if (!parse_int(argv[++i], cfg.report_every))
			{
				return false;
			}
		}
		else if (arg == "--horizon-sec" && need_value("--horizon-sec"))
		{
			if (!parse_int(argv[++i], cfg.horizon_sec))
			{
				return false;
			}
		}
		else if (arg == "--inference-timeout-ms" && need_value("--inference-timeout-ms"))
		{
			if (!parse_int(argv[++i], cfg.inference_timeout_ms))
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
		else if (arg == "--trade-notional-usd" && need_value("--trade-notional-usd"))
		{
			if (!parse_double(argv[++i], cfg.simulator.trade_notional_usd))
			{
				return false;
			}
		}
		else if (arg == "--fee-bps" && need_value("--fee-bps"))
		{
			if (!parse_double(argv[++i], cfg.simulator.fee_bps))
			{
				return false;
			}
		}
		else if (arg == "--slippage-bps" && need_value("--slippage-bps"))
		{
			if (!parse_double(argv[++i], cfg.simulator.slippage_bps))
			{
				return false;
			}
		}
		else if (arg == "--max-hold-ms" && need_value("--max-hold-ms"))
		{
			int v = 0;
			if (!parse_int(argv[++i], v))
			{
				return false;
			}
			cfg.simulator.max_hold_ms = static_cast<std::int64_t>(std::max(0, v));
		}
		else if (arg == "--min-pred-ret" && need_value("--min-pred-ret"))
		{
			if (!parse_double(argv[++i], cfg.simulator.min_predicted_return))
			{
				return false;
			}
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
		std::cerr
				<< "Usage: paper_trader [--stream-target host:port] [--predict-target host:port]\n"
				<< "                    [--symbol BTC-USDT] [--channel books5]\n"
				<< "                    [--runtime-sec 0] [--report-every 50]\n"
				<< "                    [--min-points 32] [--max-points 256]\n";
		return 1;
	}

	InferenceRuntimeConfig inf_cfg;
	inf_cfg.mode = InferenceMode::Grpc;
	inf_cfg.grpc_target = cfg.predict_target;
	inf_cfg.model_type = "xgboost";
	inf_cfg.horizon_sec = std::max(1, cfg.horizon_sec);
	inf_cfg.timeout_ms = std::max(1, cfg.inference_timeout_ms);
	inf_cfg.min_points = cfg.min_points;
	inf_cfg.max_points = std::max(cfg.min_points, cfg.max_points);
	auto prediction_client = CreatePredictionClient(inf_cfg);
	if (!prediction_client)
	{
		LOG_STREAM_ERROR("Failed to create prediction client.");
		return 1;
	}

	PaperSimulator simulator(cfg.simulator);

	const auto stream_channel = grpc::CreateChannel(cfg.stream_target, grpc::InsecureChannelCredentials());
	auto	   stream_stub = marketstream::MarketData::NewStub(stream_channel);

	grpc::ClientContext context;
	marketstream::SubscribeRequest request;
	request.set_symbol(cfg.symbol);
	request.set_channel(cfg.channel);

	auto reader = stream_stub->Subscribe(&context, request);
	marketstream::Tick tick;
	std::deque<marketstream::PricePoint> points;
	std::uint64_t tick_count = 0;
	const auto started_at = std::chrono::steady_clock::now();

	LOG_STREAM_INFO("paper_trader started, stream_target=" << cfg.stream_target << ", predict_target=" << cfg.predict_target
														  << ", symbol=" << cfg.symbol << ", channel=" << cfg.channel);

	while (reader->Read(&tick))
	{
		++tick_count;
		const std::uint64_t ts_ms = read_ts_ms(tick);
		const double		 mid_price = tick.price();
		if (!(mid_price > 0.0))
		{
			continue;
		}

		marketstream::PricePoint point;
		point.set_ts(static_cast<std::int64_t>(ts_ms));
		point.set_price(mid_price);
		point.set_bid_px(read_double_field(tick.fields(), "bidPx").value_or(0.0));
		point.set_ask_px(read_double_field(tick.fields(), "askPx").value_or(0.0));
		point.set_bid_sz(read_double_field(tick.fields(), "bidSz").value_or(0.0));
		point.set_ask_sz(read_double_field(tick.fields(), "askSz").value_or(0.0));
		points.push_back(point);
		if (points.size() > inf_cfg.max_points)
		{
			points.pop_front();
		}

		std::string signal = "HOLD";
		double		pred_ret = 0.0;
		if (points.size() >= inf_cfg.min_points)
		{
			const auto pred = prediction_client->predict(cfg.symbol, cfg.channel, points);
			if (pred)
			{
				signal = pred->signal;
				pred_ret = pred->predicted_return;
			}
		}

		const auto event = simulator.on_signal(static_cast<std::int64_t>(ts_ms), mid_price, signal, pred_ret);
		if (event)
		{
			const auto snap = simulator.snapshot();
			LOG_STREAM_INFO("sim_event action=" << event->action << ", fill_px=" << event->fill_price
												<< ", fill_qty=" << event->fill_qty
												<< ", realized=" << event->realized_pnl_usd
												<< ", equity=" << snap.equity_usd);
		}

		if (cfg.report_every > 0 && tick_count % static_cast<std::uint64_t>(cfg.report_every) == 0)
		{
			const auto snap = simulator.snapshot();
			LOG_STREAM_INFO("paper_status ticks=" << tick_count << ", price=" << mid_price << ", signal=" << signal
												  << ", pred_ret=" << pred_ret << ", pos_qty=" << snap.position_qty
												  << ", realized=" << snap.realized_pnl_usd << ", equity=" << snap.equity_usd);
		}

		if (cfg.runtime_sec > 0)
		{
			const auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(
					std::chrono::steady_clock::now() - started_at);
			if (elapsed.count() >= cfg.runtime_sec)
			{
				break;
			}
		}
	}

	const grpc::Status status = reader->Finish();
	if (!status.ok())
	{
		LOG_STREAM_WARN("stream closed with status: " << status.error_message());
	}

	double last_price = points.empty() ? 0.0 : points.back().price();
	if (last_price > 0.0)
	{
		(void)simulator.close_all(static_cast<std::int64_t>(
										  std::chrono::duration_cast<std::chrono::milliseconds>(
												  std::chrono::system_clock::now().time_since_epoch())
												  .count()),
								  last_price,
								  "shutdown");
	}

	const auto snap = simulator.snapshot();
	LOG_STREAM_INFO("paper_trader done ticks=" << tick_count << ", trades=" << snap.trade_count
												<< ", wins=" << snap.win_count << ", losses=" << snap.loss_count
												<< ", realized_pnl=" << snap.realized_pnl_usd
												<< ", fees=" << snap.fees_paid_usd << ", equity=" << snap.equity_usd);
	return 0;
}
