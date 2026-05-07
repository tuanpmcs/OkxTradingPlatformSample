#pragma once

#include "market_data.grpc.pb.h"

#include <cstddef>
#include <cstdint>
#include <deque>
#include <memory>
#include <optional>
#include <string>

enum class InferenceMode
{
	Off,
	Grpc,
	Onnx,
};

struct InferenceRuntimeConfig
{
	InferenceMode mode{InferenceMode::Grpc};
	std::string	  grpc_target{"127.0.0.1:50061"};
	std::string	  model_type{"xgboost"};
	std::string	  onnx_model_path{};
	int			  horizon_sec{1};
	int			  timeout_ms{1200};
	int			  interval_ms{200};
	std::size_t	  min_points{32};
	std::size_t	  max_points{256};
	bool		  stream_predictions_enabled{false};
};

struct PredictionResult
{
	std::string model_name;
	std::string signal;
	std::string detail;
	double		last_price{0.0};
	double		predicted_price{0.0};
	double		predicted_return{0.0};
};

class PredictionClient
{
public:
	virtual ~PredictionClient() = default;

	virtual std::optional<PredictionResult> predict(const std::string&						  symbol,
												  const std::string&						  channel,
												  const std::deque<marketstream::PricePoint>& points,
												  const std::string*						  model_type_override = nullptr) = 0;
};

std::unique_ptr<PredictionClient> CreatePredictionClient(const InferenceRuntimeConfig& cfg);
