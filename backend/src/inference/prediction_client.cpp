#include "inference/prediction_client.hpp"

#include "common/logger.hpp"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cmath>
#include <iomanip>
#include <sstream>
#include <string_view>
#include <vector>

#include <grpcpp/grpcpp.h>

namespace
{
double fallback_price_from_point(const marketstream::PricePoint& point)
{
	if (point.price() > 0.0)
	{
		return point.price();
	}
	if (point.bid_px() > 0.0 && point.ask_px() > 0.0 && point.ask_px() >= point.bid_px())
	{
		return 0.5 * (point.bid_px() + point.ask_px());
	}
	return 0.0;
}

double clamp_abs(double value, double bound)
{
	return std::max(-bound, std::min(bound, value));
}

void scrub_grpc_proxy_env()
{
	const char* proxy_keys[] = {
		"GRPC_PROXY",
		"grpc_proxy",
		"HTTPS_PROXY",
		"https_proxy",
		"HTTP_PROXY",
		"http_proxy",
		"ALL_PROXY",
		"all_proxy",
	};
	for (const auto* key : proxy_keys)
	{
		unsetenv(key);
	}
}

std::shared_ptr<grpc::Channel> create_internal_grpc_channel(const std::string& target)
{
	scrub_grpc_proxy_env();
	grpc::ChannelArguments args;
	args.SetInt("grpc.enable_http_proxy", 0);
	return grpc::CreateCustomChannel(target, grpc::InsecureChannelCredentials(), args);
}

std::optional<PredictionResult> build_linear_fallback(const std::deque<marketstream::PricePoint>& points,
													  int										   horizon_sec,
													  std::string_view							   reason)
{
	if (points.empty())
	{
		return std::nullopt;
	}

	std::vector<double> prices;
	prices.reserve(points.size());
	for (const auto& point : points)
	{
		const double px = fallback_price_from_point(point);
		if (px > 0.0)
		{
			prices.push_back(px);
		}
	}
	if (prices.size() < 3)
	{
		return std::nullopt;
	}

	const double last_price = prices.back();
	const auto ret_over = [&](std::size_t lookback) -> double {
		if (prices.size() <= lookback)
		{
			return 0.0;
		}
		const double prev = prices[prices.size() - 1 - lookback];
		if (prev <= 0.0)
		{
			return 0.0;
		}
		return (last_price - prev) / prev;
	};

	const double mom5 = clamp_abs(ret_over(5), 0.01);
	const double mom20 = clamp_abs(ret_over(20), 0.02);

	double vol20 = 0.0;
	if (prices.size() > 21)
	{
		const std::size_t start = prices.size() - 21;
		std::vector<double> rets;
		rets.reserve(20);
		for (std::size_t i = start + 1; i < prices.size(); ++i)
		{
			const double prev = prices[i - 1];
			const double curr = prices[i];
			if (prev > 0.0 && curr > 0.0)
			{
				rets.push_back((curr - prev) / prev);
			}
		}
		if (!rets.empty())
		{
			double mean = 0.0;
			for (const auto r : rets) mean += r;
			mean /= static_cast<double>(rets.size());
			double var = 0.0;
			for (const auto r : rets)
			{
				const double d = r - mean;
				var += d * d;
			}
			var /= static_cast<double>(rets.size());
			vol20 = std::sqrt(std::max(0.0, var));
		}
	}

	const auto& last_point = points.back();
	double		imbalance = 0.0;
	const double sz_sum = last_point.bid_sz() + last_point.ask_sz();
	if (sz_sum > 0.0)
	{
		imbalance = (last_point.bid_sz() - last_point.ask_sz()) / sz_sum;
	}

	double spread_bps = 0.0;
	if (last_point.bid_px() > 0.0 && last_point.ask_px() > 0.0 && last_point.ask_px() >= last_point.bid_px()
		&& last_price > 0.0)
	{
		spread_bps = ((last_point.ask_px() - last_point.bid_px()) / last_price) * 10000.0;
	}

	// Lightweight linear fallback calibrated for microstructure features.
	double pred_ret = 0.62 * mom5 + 0.38 * mom20 + 0.18 * imbalance - 0.25 * vol20 - 0.02 * (spread_bps / 10000.0);
	pred_ret = clamp_abs(pred_ret, 0.005);

	PredictionResult out{};
	out.model_name = "PulseLinearFallbackV1";
	out.last_price = last_price;
	out.predicted_return = pred_ret;
	out.predicted_price = last_price * (1.0 + pred_ret);
	if (pred_ret > 0.00005)
	{
		out.signal = "LONG";
	}
	else if (pred_ret < -0.00005)
	{
		out.signal = "SHORT";
	}
	else
	{
		out.signal = "HOLD";
	}

	std::ostringstream detail;
	detail << "{\"mode\":\"linear_fallback\",\"reason\":\"" << reason << "\",\"points\":" << prices.size()
		   << ",\"horizon_sec\":" << horizon_sec << ",\"mom5\":" << std::fixed << std::setprecision(6) << mom5
		   << ",\"mom20\":" << mom20 << ",\"vol20\":" << vol20 << ",\"imbalance\":" << imbalance << "}";
	out.detail = detail.str();
	return out;
}

class GrpcPredictionClient final : public PredictionClient
{
public:
	explicit GrpcPredictionClient(InferenceRuntimeConfig cfg)
		: _cfg(std::move(cfg))
		, _channel(create_internal_grpc_channel(_cfg.grpc_target))
		, _stub(marketstream::PredictionService::NewStub(_channel))
	{
	}

	std::optional<PredictionResult> predict(const std::string&						   symbol,
										   const std::string&						   channel,
										   const std::deque<marketstream::PricePoint>& points,
										   const std::string*						   model_type_override) override
	{
		if (points.empty())
		{
			return std::nullopt;
		}
		if (!_stub)
		{
			return build_linear_fallback(points, _cfg.horizon_sec, "grpc_stub_unavailable");
		}

		marketstream::PredictRequest request;
		request.set_symbol(symbol);
		request.set_channel(channel);
		request.set_horizon_sec(_cfg.horizon_sec);
		request.set_model_type(model_type_override && !model_type_override->empty() ? *model_type_override
																					: _cfg.model_type);
		for (const auto& point : points)
		{
			*request.add_points() = point;
		}

		grpc::ClientContext context;
		context.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(_cfg.timeout_ms));

		marketstream::PredictResponse response;
		const grpc::Status		   status = _stub->Predict(&context, request, &response);
		if (!status.ok())
		{
			const auto now = std::chrono::steady_clock::now();
			if (now - _last_error_log > std::chrono::seconds(5))
			{
				LOG_STREAM_WARN("Prediction gRPC unavailable (" << status.error_message()
																<< "), target=" << _cfg.grpc_target);
				_last_error_log = now;
			}
			return build_linear_fallback(points, _cfg.horizon_sec, "grpc_unavailable");
		}

		PredictionResult out{};
		out.model_name = response.model_name();
		out.signal = response.signal();
		out.detail = response.detail();
		out.last_price = response.last_price();
		out.predicted_price = response.predicted_price();
		out.predicted_return = response.predicted_return();
		return out;
	}

private:
	InferenceRuntimeConfig					   _cfg;
	std::shared_ptr<grpc::Channel>			   _channel;
	std::unique_ptr<marketstream::PredictionService::Stub> _stub;
	std::chrono::steady_clock::time_point _last_error_log{};
};

class OnnxPredictionClient final : public PredictionClient
{
public:
	explicit OnnxPredictionClient(InferenceRuntimeConfig cfg)
		: _cfg(std::move(cfg))
	{
		LOG_STREAM_WARN("ONNX local mode requested, but ONNX runtime integration is not enabled in this build.");
	}

	std::optional<PredictionResult> predict(const std::string&,
											const std::string&,
											const std::deque<marketstream::PricePoint>& points,
											const std::string*) override
	{
		return build_linear_fallback(points, _cfg.horizon_sec, "onnx_not_enabled");
	}

private:
	InferenceRuntimeConfig _cfg;
};
}  // namespace

std::unique_ptr<PredictionClient> CreatePredictionClient(const InferenceRuntimeConfig& cfg)
{
	switch (cfg.mode)
	{
	case InferenceMode::Off:
		return nullptr;
	case InferenceMode::Grpc:
		return std::make_unique<GrpcPredictionClient>(cfg);
	case InferenceMode::Onnx:
		return std::make_unique<OnnxPredictionClient>(cfg);
	}
	return nullptr;
}
